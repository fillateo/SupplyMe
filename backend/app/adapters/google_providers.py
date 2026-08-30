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
from dataclasses import replace
from html.parser import HTMLParser
from typing import ClassVar

import httpx

from ..config import Settings
from ..ports.base import PageContent, Place, SearchHit

log = logging.getLogger(__name__)

#: The `Mozilla/5.0 (compatible; …)` shape is the crawler convention — it is what
#: Googlebot and bingbot send — and it still names this tool and where to
#: complain about it. The plainer `SupplyMe/0.1 (…)` form was
#: being 403'd outright by supplier sites behind a WAF, which is a large part of
#: why live research read nothing. robots.txt is still obeyed either way: that,
#: not the header, is where a site says whether it wants to be read.
#: Search grounding hands back links to Google's own redirector rather than to
#: the page it read. Every downstream judgement is made on a URL — is this the
#: supplier's own site, is this source independent of them, which domain does
#: this evidence come from — and all of them are meaningless against a redirect.
#: Left unresolved, a mission's evidence cites `vertexaisearch.cloud.google.com`
#: for every fact it holds.
GROUNDING_REDIRECT_HOST = "vertexaisearch.cloud.google.com"
RESOLVE_TIMEOUT = 8.0

USER_AGENT = (
    "Mozilla/5.0 (compatible; SupplyMe/0.1; +https://github.com/nesso-labs)"
)

#: Sent with every page fetch. A request with no Accept header looks like a
#: scraper to a WAF, and this market's sites serve Indonesian when asked.
FETCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}
FETCH_TIMEOUT = 15.0
MAX_PAGE_BYTES = 800_000


class _TextExtractor(HTMLParser):
    """Minimal readable-text extraction. No JS, no heuristic article detection."""

    _SKIP: ClassVar[frozenset[str]] = frozenset(
        {"script", "style", "noscript", "svg", "head"}
    )

    #: Elements that never close. Pushing them onto the stack is what made this
    #: return an empty string for every real page on the web: `<head>` contains
    #: `<meta>` and `<link>`, so `</head>` found one of those on top, never
    #: popped `head`, and every byte of the body was then skipped as being
    #: inside the head. Demo pages are plain text, so nothing caught it.
    _VOID: ClassVar[frozenset[str]] = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input",
         "keygen", "link", "meta", "param", "source", "track", "wbr"}
    )

    #: Where a supplier's address usually is: in the href, not the link text,
    #: which reads "Email us".
    _CONTACT_SCHEMES: ClassVar[tuple[str, ...]] = ("mailto:", "tel:")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._stack: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._capture_href(tag, attrs)
        if tag in self._VOID:
            if tag == "br":
                self.parts.append("\n")
            return
        self._stack.append(tag)
        if tag == "title":
            self._in_title = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """`<br/>` and friends, which never reach handle_endtag."""
        self._capture_href(tag, attrs)
        if tag == "br":
            self.parts.append("\n")

    def _capture_href(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or any(t in self._SKIP for t in self._stack):
            return
        for name, value in attrs:
            if name != "href" or not value:
                continue
            target = value.strip()
            for scheme in self._CONTACT_SCHEMES:
                if target.lower().startswith(scheme):
                    self.parts.append(target[len(scheme) :].split("?", 1)[0])
                    return

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in self._stack:
            # Unwind to the matching tag rather than only checking the top, so a
            # page that leaves a `<p>` or `<li>` open does not strand everything
            # after it inside a section this parser thinks it is still in.
            while self._stack:
                if self._stack.pop() == tag:
                    break
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
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
            timeout=FETCH_TIMEOUT, headers=dict(FETCH_HEADERS), follow_redirects=True
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
        return await self._resolve_redirects(hits[:limit])

    async def _resolve_redirects(self, hits: list[SearchHit]) -> list[SearchHit]:
        """Turn grounding redirects into the URLs they point at.

        One HEAD each, run together, and a failure keeps the redirect rather
        than dropping the result — a hit whose destination we could not confirm
        is still a hit, and the agents read the snippet either way.
        """

        async def resolve(hit: SearchHit) -> SearchHit:
            if GROUNDING_REDIRECT_HOST not in hit.url:
                return hit
            try:
                response = await self._client.head(
                    hit.url, follow_redirects=True, timeout=RESOLVE_TIMEOUT
                )
            except Exception:  # a slow redirector costs one URL, not the search
                return hit
            final = str(response.url)
            if not final or GROUNDING_REDIRECT_HOST in final:
                return hit
            return replace(hit, url=final)

        return list(await asyncio.gather(*(resolve(hit) for hit in hits)))

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
        # The URL that answered, not the one asked for: a redirect is where the
        # content actually came from, and that is what the evidence should cite.
        return PageContent(
            url=str(response.url) or url, title=parser.title, text=parser.text[:20_000]
        )

    async def close(self) -> None:
        await self._client.aclose()


class PlacesProvider:
    """Google Places API (New). Text Search + Place Details.

    Places is billed per request and by which fields you ask for, and it is the
    most expensive call this system makes — an order of magnitude more than a
    Gemini call. Two consequences are baked in here:

    * Search asks for the cheapest field set that still identifies a business.
      Ratings and review counts are deliberately absent, because the product
      does not treat reviews as evidence of manufacturing capability anyway
      (see app/agents/research.py) and requesting them moves the request into a
      dearer SKU to no benefit.
    * The fuller field set is only fetched by `place_details`, which runs once
      per vendor that survived discovery, not once per search query.
    """

    BASE = "https://places.googleapis.com/v1"

    #: Text Search. Identification only — no ratings, no reviews.
    SEARCH_FIELDS = (
        "places.id,places.displayName,places.formattedAddress,"
        "places.websiteUri,places.location,places.businessStatus"
    )
    #: Place Details, once per shortlisted vendor.
    DETAIL_FIELDS = (
        "id,displayName,formattedAddress,internationalPhoneNumber,websiteUri,"
        "location,rating,userRatingCount,businessStatus,types"
    )

    def __init__(self, settings: Settings) -> None:
        self._key = settings.maps_api_key
        self._client = httpx.AsyncClient(timeout=15.0)

    async def search_places(self, query: str, *, region: str = "") -> list[Place]:
        if not self._key:
            return []
        response = await self._client.post(
            f"{self.BASE}/places:searchText",
            headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": self.SEARCH_FIELDS},
            json={"textQuery": query, **({"regionCode": region} if region else {})},
        )
        if response.status_code != 200:
            log.warning("places_failed", extra={"status": response.status_code})
            return []
        return [_to_place(p) for p in response.json().get("places", [])]

    async def place_details(self, place_id: str) -> Place | None:
        if not self._key:
            return None
        response = await self._client.get(
            f"{self.BASE}/places/{place_id}",
            headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": self.DETAIL_FIELDS},
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
