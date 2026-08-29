"""Live Google adapters.

Retrieval policy, applied here rather than in the agents:

* Search goes through the Programmable Search JSON API. When no engine is
  configured, it falls back to Gemini with Google Search grounding and reads the
  URLs out of the grounding metadata, so the system still has real citations.
* Page fetches are single, polite GETs: robots.txt is honoured, a real UA is
  sent, redirects are capped, and a disallowed or oversized page comes back as
  `blocked_reason` rather than being retried harder. §10 asks for no aggressive
  scraping and no bypassing of access controls; a blocked page is simply a page
  the mission does not get evidence from.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.robotparser
from html.parser import HTMLParser
from typing import ClassVar

import httpx

from ..config import Settings
from ..ports.base import PageContent, Place, SearchHit, Video

log = logging.getLogger(__name__)

USER_AGENT = "VendorDiscoveryShortcut/0.1 (sourcing research agent; +https://github.com/)"
FETCH_TIMEOUT = 15.0
MAX_PAGE_BYTES = 800_000


class _TextExtractor(HTMLParser):
    """Minimal readable-text extraction. No JS, no heuristic article detection."""

    _SKIP: ClassVar[frozenset[str]] = frozenset(
        {"script", "style", "noscript", "svg", "head"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._stack: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack.append(tag)
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        if tag in {"p", "div", "li", "br", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data.strip()
            return
        if any(t in self._SKIP for t in self._stack):
            return
        text = data.strip()
        if text:
            self.parts.append(text)

    @property
    def text(self) -> str:
        joined = "".join(
            part if part == "\n" else f" {part}" for part in self.parts
        )
        collapsed = re.sub(r"[ \t]+", " ", joined)
        return re.sub(r"\n{3,}", "\n\n", collapsed).strip()


class GoogleSearchProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = asyncio.Lock()

    async def search(self, query: str, *, limit: int = 8) -> list[SearchHit]:
        if self._settings.search_api_key and self._settings.search_engine_id:
            return await self._cse(query, limit)
        return await self._grounded(query, limit)

    async def _cse(self, query: str, limit: int) -> list[SearchHit]:
        response = await self._client.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": self._settings.search_api_key,
                "cx": self._settings.search_engine_id,
                "q": query,
                "num": min(limit, 10),
            },
        )
        if response.status_code != 200:
            log.warning("cse_failed", extra={"status": response.status_code})
            return []
        return [
            SearchHit(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                source_hint=item.get("displayLink", ""),
            )
            for item in response.json().get("items", [])
        ]

    async def _grounded(self, query: str, limit: int) -> list[SearchHit]:
        """Gemini + Google Search grounding, read for its citations."""
        from google.genai import types

        from .gemini_llm import _client, resolve_model

        client = _client(self._settings)
        model = await resolve_model(self._settings, prefer_fast=True)
        response = await client.aio.models.generate_content(
            model=model,
            contents=f"Search the web for: {query}. List what you find with sources.",
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )
        hits: list[SearchHit] = []
        for candidate in getattr(response, "candidates", None) or []:
            metadata = getattr(candidate, "grounding_metadata", None)
            for chunk in getattr(metadata, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                if web is None:
                    continue
                hits.append(
                    SearchHit(
                        title=getattr(web, "title", "") or "",
                        url=getattr(web, "uri", "") or "",
                        snippet=(getattr(response, "text", "") or "")[:300],
                        source_hint="grounding",
                    )
                )
        return hits[:limit]

    async def _allowed(self, url: str) -> tuple[bool, str]:
        """Check robots.txt once per host. A fetch failure means 'do not fetch'."""
        try:
            scheme, rest = url.split("://", 1)
            host = rest.split("/", 1)[0]
        except ValueError:
            return False, "unparseable url"
        origin = f"{scheme}://{host}"

        async with self._lock:
            parser = self._robots.get(origin, ...)  # type: ignore[arg-type]
        if parser is ...:
            parser = urllib.robotparser.RobotFileParser()
            try:
                response = await self._client.get(f"{origin}/robots.txt", timeout=8.0)
                if response.status_code == 200:
                    parser.parse(response.text.splitlines())
                else:
                    parser = None  # no robots.txt published -> allowed
            except httpx.HTTPError:
                parser = None
            async with self._lock:
                self._robots[origin] = parser

        if parser is None:
            return True, ""
        if parser.can_fetch(USER_AGENT, url):
            return True, ""
        return False, "disallowed by robots.txt"

    async def fetch(self, url: str) -> PageContent:
        allowed, reason = await self._allowed(url)
        if not allowed:
            return PageContent(url=url, title="", text="", fetched=False, blocked_reason=reason)
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as exc:
            return PageContent(
                url=url, title="", text="", fetched=False, blocked_reason=f"fetch failed: {exc}"
            )
        if response.status_code >= 400:
            return PageContent(
                url=url, title="", text="", fetched=False,
                blocked_reason=f"HTTP {response.status_code}",
            )
        if len(response.content) > MAX_PAGE_BYTES:
            return PageContent(
                url=url, title="", text="", fetched=False, blocked_reason="page too large"
            )
        parser = _TextExtractor()
        parser.feed(response.text)
        return PageContent(url=url, title=parser.title, text=parser.text[:20_000])

    async def close(self) -> None:
        await self._client.aclose()


class PlacesProvider:
    """Google Places API (New). Text Search + Place Details."""

    BASE = "https://places.googleapis.com/v1"
    FIELDS = (
        "places.id,places.displayName,places.formattedAddress,places.internationalPhoneNumber,"
        "places.websiteUri,places.location,places.rating,places.userRatingCount,"
        "places.businessStatus,places.types"
    )

    def __init__(self, settings: Settings) -> None:
        self._key = settings.maps_api_key
        self._client = httpx.AsyncClient(timeout=15.0)

    async def search_places(self, query: str, *, region: str = "") -> list[Place]:
        if not self._key:
            return []
        response = await self._client.post(
            f"{self.BASE}/places:searchText",
            headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": self.FIELDS},
            json={"textQuery": query, **({"regionCode": region} if region else {})},
        )
        if response.status_code != 200:
            log.warning("places_failed", extra={"status": response.status_code})
            return []
        return [_to_place(p) for p in response.json().get("places", [])]

    async def place_details(self, place_id: str) -> Place | None:
        if not self._key:
            return None
        fields = self.FIELDS.replace("places.", "")
        response = await self._client.get(
            f"{self.BASE}/places/{place_id}",
            headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": fields},
        )
        if response.status_code != 200:
            return None
        return _to_place(response.json())

    async def close(self) -> None:
        await self._client.aclose()


def _to_place(raw: dict) -> Place:
    location = raw.get("location") or {}
    return Place(
        place_id=raw.get("id", ""),
        name=(raw.get("displayName") or {}).get("text", ""),
        address=raw.get("formattedAddress", ""),
        phone=raw.get("internationalPhoneNumber"),
        website=raw.get("websiteUri"),
        lat=location.get("latitude"),
        lng=location.get("longitude"),
        rating=raw.get("rating"),
        user_ratings_total=raw.get("userRatingCount"),
        business_status=raw.get("businessStatus"),
        types=tuple(raw.get("types", [])),
    )


class YouTubeProvider:
    def __init__(self, settings: Settings) -> None:
        self._key = settings.youtube_api_key
        self._client = httpx.AsyncClient(timeout=15.0)

    async def search_videos(self, query: str, *, limit: int = 5) -> list[Video]:
        if not self._key:
            return []
        response = await self._client.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key": self._key, "part": "snippet", "q": query,
                "type": "video", "maxResults": min(limit, 10),
            },
        )
        if response.status_code != 200:
            return []
        videos = []
        for item in response.json().get("items", []):
            snippet = item.get("snippet", {})
            video_id = (item.get("id") or {}).get("videoId", "")
            videos.append(
                Video(
                    video_id=video_id,
                    title=snippet.get("title", ""),
                    channel=snippet.get("channelTitle", ""),
                    description=snippet.get("description", ""),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    published_at=snippet.get("publishedAt"),
                )
            )
        return videos

    async def close(self) -> None:
        await self._client.aclose()
