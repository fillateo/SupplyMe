"""Stand-ins for search, Places and mail, for the test suite only.

The product has no simulated providers — a missing key is a startup failure, not
a fallback to invented suppliers. These exist so a whole mission can be driven
offline and deterministically, including the parts that are hard to provoke
against the real web: a supplier who never answers, one whose site contradicts
their quote, and every message being delivered twice.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.domain.events import Event, EventType
from app.domain.ids import new_id
from app.ports.base import (
    InboundMail,
    PageContent,
    Place,
    SearchHit,
    SentMail,
)

from . import doubles_world as world

log = logging.getLogger(__name__)


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2}


def _relevance(query: str, vendor: world.DemoVendor) -> int:
    q = _tokens(query)
    haystack = _tokens(
        " ".join([vendor.name, vendor.city, *vendor.keywords, *vendor.node_keys])
    )
    return len(q & haystack)


class MockSearchProvider:
    """Matches queries against the demo vendors' keywords and the independent pages."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, *, limit: int = 8) -> list[SearchHit]:
        self.queries.append(query)
        hits: list[SearchHit] = []

        scored = sorted(
            ((_relevance(query, v), v) for v in world.VENDORS),
            key=lambda pair: pair[0],
            reverse=True,
        )
        for score, vendor in scored:
            if score == 0:
                continue
            page = vendor.pages[0] if vendor.pages else None
            hits.append(
                SearchHit(
                    title=page.title if page else vendor.name,
                    url=page.url if page else f"https://{vendor.domain}/",
                    snippet=(page.text[:220] if page else vendor.name),
                    source_hint="official",
                )
            )

        q = _tokens(query)
        for page in world.INDEPENDENT_PAGES:
            if q & _tokens(page.title + " " + page.text[:400]):
                hint = (
                    "brand" if "maisonverel" in page.url
                    else "news" if "review" in page.url
                    else "directory"
                )
                hits.append(
                    SearchHit(title=page.title, url=page.url, snippet=page.text[:220],
                              source_hint=hint)
                )
        return hits[:limit]

    async def fetch(self, url: str) -> PageContent:
        for vendor in world.VENDORS:
            for page in vendor.pages:
                if page.url == url:
                    return PageContent(url=url, title=page.title, text=page.text)
        for page in world.INDEPENDENT_PAGES:
            if page.url == url:
                return PageContent(url=url, title=page.title, text=page.text)
        return PageContent(
            url=url, title="", text="", fetched=False, blocked_reason="not in the demo dataset"
        )


class MockMapsProvider:
    async def search_places(self, query: str, *, region: str = "") -> list[Place]:
        scored = sorted(
            ((_relevance(query, v), v) for v in world.VENDORS),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return [self._place(v) for score, v in scored if score > 0 and v.place_id]

    async def place_details(self, place_id: str) -> Place | None:
        vendor = next((v for v in world.VENDORS if v.place_id == place_id), None)
        return self._place(vendor) if vendor else None

    @staticmethod
    def _place(vendor: world.DemoVendor) -> Place:
        return Place(
            place_id=vendor.place_id or "",
            name=vendor.name,
            address=vendor.address,
            phone=vendor.phone,
            website=f"https://{vendor.domain}/",
            lat=vendor.lat,
            lng=vendor.lng,
            rating=vendor.rating,
            user_ratings_total=vendor.reviews,
            business_status="OPERATIONAL",
            types=("point_of_interest", "establishment"),
        )


class MockMailProvider:
    """Sends into the void, then schedules a real inbound event.

    The reply is delivered by publishing `email.received` through the scheduler,
    exactly as the Gmail push subscription would. Nothing in the workflow can
    tell the difference, which is the point.
    """

    def __init__(self, bus: Any = None, scheduler: Any = None) -> None:
        self._bus = bus
        self._scheduler = scheduler
        self.sent: list[dict[str, str]] = []
        self._threads: dict[str, list[InboundMail]] = {}
        # Keyed by (mission_id, vendor) — a vendor's scripted replies restart for
        # every mission. Keying by vendor alone leaks one mission's progress into
        # the next, and since each fixture scripts a single reply that left every
        # mission after the first waiting for a reply that would never arrive.
        self._round: dict[tuple[str, str], int] = {}

    def bind(self, bus: Any, scheduler: Any) -> None:
        self._bus, self._scheduler = bus, scheduler

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        mission_id: str = "",
    ) -> SentMail:
        provider_thread = thread_id or new_id("gthr")
        message_id = new_id("gmsg")
        self.sent.append({"to": to, "subject": subject, "body": body, "thread": provider_thread})
        log.info("mock_mail_sent", extra={"to": to, "subject": subject})

        vendor = world.vendor_by_email(to)
        if vendor is None:
            return SentMail(provider_message_id=message_id, provider_thread_id=provider_thread)

        round_key = (mission_id, vendor.key)
        round_index = self._round.get(round_key, 0)
        self._round[round_key] = round_index + 1
        reply_body = vendor.replies.get(round_index)
        if reply_body is None or self._scheduler is None:
            return SentMail(provider_message_id=message_id, provider_thread_id=provider_thread)

        inbound = InboundMail(
            provider_message_id=new_id("gmsg"),
            provider_thread_id=provider_thread,
            from_address=vendor.email or "",
            subject=f"Re: {subject}",
            body=reply_body,
            received_at="",
        )
        self._threads.setdefault(provider_thread, []).append(inbound)

        await self._scheduler.schedule(
            Event(
                type=EventType.EMAIL_RECEIVED,
                mission_id=mission_id,
                payload={
                    "provider_thread_id": provider_thread,
                    "provider_message_id": inbound.provider_message_id,
                    "from_address": inbound.from_address,
                    "subject": inbound.subject,
                    "body": reply_body,
                },
            ),
            delay_seconds=vendor.reply_delay_seconds,
        )
        return SentMail(provider_message_id=message_id, provider_thread_id=provider_thread)

    async def fetch_thread(self, provider_thread_id: str) -> list[InboundMail]:
        return list(self._threads.get(provider_thread_id, []))

    async def history(self, since_token: str | None = None) -> tuple[list[InboundMail], str]:
        return [], since_token or "0"
