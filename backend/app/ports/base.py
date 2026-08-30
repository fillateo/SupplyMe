"""Port definitions.

Every external dependency is a Protocol here and an adapter in app/adapters/.
LIVE and DEMO differ only in which adapter is bound — never in the workflow, the
agents, or the events they emit. That is what lets the demo prove the same code
path that production would run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..domain.events import Event

# --------------------------------------------------------------------------
# Search / web
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    source_hint: str = ""       # "official" | "news" | "directory" | ...


@dataclass(frozen=True)
class PageContent:
    url: str
    title: str
    text: str
    fetched: bool = True
    #: Set when the site's robots.txt or terms disallow automated retrieval.
    blocked_reason: str | None = None


@runtime_checkable
class SearchProvider(Protocol):
    async def search(self, query: str, *, limit: int = 8) -> list[SearchHit]: ...
    async def fetch(self, url: str) -> PageContent: ...


# --------------------------------------------------------------------------
# Maps / Places
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Place:
    place_id: str
    name: str
    address: str = ""
    phone: str | None = None
    website: str | None = None
    lat: float | None = None
    lng: float | None = None
    rating: float | None = None
    user_ratings_total: int | None = None
    business_status: str | None = None
    types: tuple[str, ...] = ()


@runtime_checkable
class MapsProvider(Protocol):
    async def search_places(self, query: str, *, region: str = "") -> list[Place]: ...
    async def place_details(self, place_id: str) -> Place | None: ...


# --------------------------------------------------------------------------
# YouTube
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Video:
    video_id: str
    title: str
    channel: str
    description: str
    url: str
    published_at: str | None = None
    #: True when the uploading channel is the supplier's own channel.
    self_published: bool = False


@runtime_checkable
class VideoProvider(Protocol):
    async def search_videos(self, query: str, *, limit: int = 5) -> list[Video]: ...


# --------------------------------------------------------------------------
# Mail
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SentMail:
    provider_message_id: str
    provider_thread_id: str


@dataclass(frozen=True)
class InboundMail:
    provider_message_id: str
    provider_thread_id: str
    from_address: str
    subject: str
    body: str
    received_at: str


@runtime_checkable
class MailProvider(Protocol):
    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        mission_id: str = "",
    ) -> SentMail:
        """Send mail. `mission_id` is context for the demo provider, which has to
        stand in for the Gmail push webhook's thread-to-mission lookup; the live
        Gmail adapter ignores it."""
        ...
    async def fetch_thread(self, provider_thread_id: str) -> list[InboundMail]: ...
    async def history(self, since_token: str | None = None) -> tuple[list[InboundMail], str]: ...


# --------------------------------------------------------------------------
# Infrastructure
# --------------------------------------------------------------------------


@runtime_checkable
class Store(Protocol):
    """Document store. Collection names match app/domain/models.py types."""

    async def put(self, collection: str, doc_id: str, data: dict[str, Any]) -> None: ...
    async def get(self, collection: str, doc_id: str) -> dict[str, Any] | None: ...
    async def query(
        self, collection: str, *, where: dict[str, Any] | None = None, limit: int = 500
    ) -> list[dict[str, Any]]: ...
    async def append_event(self, mission_id: str, event: dict[str, Any]) -> None: ...
    async def timeline(self, mission_id: str, *, limit: int = 500) -> list[dict[str, Any]]: ...
    async def reserve(
        self, key: str, payload: dict[str, Any], *, lease_seconds: float = 300.0
    ) -> bool:
        """Atomically claim `key` for `lease_seconds`.

        False means the key is already claimed by live work, or was completed.
        An expired lease may be taken over, so a worker that died mid-action does
        not block the key forever.
        """
        ...

    async def complete(self, key: str, result: dict[str, Any] | None = None) -> None:
        """Mark a reservation done. Completed keys are never re-granted."""
        ...

    async def mutate(
        self, collection: str, doc_id: str, mutator: Any
    ) -> dict[str, Any] | None:
        """Read-modify-write `doc_id` atomically.

        `mutator` receives the current document and returns the new one. Several
        handlers touch the same vendor at once — research, brand adjudication and
        outreach all run in parallel — and a plain get/put would silently drop
        whichever write landed first.
        """
        ...


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, event: Event) -> None: ...


@runtime_checkable
class Scheduler(Protocol):
    """Delayed execution: follow-ups, non-response timeouts, retry backoff."""

    async def schedule(
        self, event: Event, *, delay_seconds: float, compressible: bool = True
    ) -> str:
        """Deliver `event` later.

        `compressible` says whether the demo clock may shorten this delay.
        Waiting two days for a supplier is business time and should compress in a
        demo. Backing off from a rate limit is not: shortening it makes the
        retries land inside the same overloaded window they were meant to avoid.
        """
        ...


@runtime_checkable
class LLM(Protocol):
    async def structured(
        self,
        *,
        agent: str,
        instruction: str,
        prompt: str,
        schema: type,
        untrusted: str | None = None,
        fast: bool = False,
        mission_id: str = "",
    ) -> Any: ...
