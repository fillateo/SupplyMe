"""Demo-mode adapters.

Each one implements the same port as its Google counterpart and returns data
from app/adapters/demo_world.py. The mail and voice providers are the important
ones: they do not return a reply inline. They schedule a real
`email.received` / `call.completed` event on the bus, minutes or seconds later,
so a demo run exercises the same asynchronous resumption path that a supplier
answering at 2am would — §44's requirement that mock providers produce events
through the real workflow rather than fake results in the UI.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..domain.events import Event, EventType
from ..domain.ids import new_id
from ..ports.base import (
    CallResult,
    InboundMail,
    PageContent,
    Place,
    SearchHit,
    SentMail,
    Video,
)
from . import demo_world as world

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


class MockVideoProvider:
    async def search_videos(self, query: str, *, limit: int = 5) -> list[Video]:
        out: list[Video] = []
        q = _tokens(query)
        for vendor in world.VENDORS:
            for video in vendor.videos:
                if q & _tokens(video.title + " " + video.channel + " " + vendor.name):
                    out.append(
                        Video(
                            video_id=video.video_id,
                            title=video.title,
                            channel=video.channel,
                            description=video.description,
                            url=f"https://www.youtube.com/watch?v={video.video_id}",
                            self_published=video.self_published,
                        )
                    )
        return out[:limit]


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
        self._round: dict[str, int] = {}

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

        round_index = self._round.get(vendor.key, 0)
        self._round[vendor.key] = round_index + 1
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


class MockVoiceProvider:
    """Builds a transcript by matching the planned questions against the vendor's answers."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def place_call(
        self, *, to: str, opening: str, questions: list[str], call_id: str
    ) -> CallResult:
        vendor = next(
            (
                v
                for v in world.VENDORS
                if v.phone and _digits(v.phone) == _digits(to)
            ),
            None,
        )
        self.calls.append({"to": to, "opening": opening, "questions": questions})

        if vendor is None:
            return CallResult(
                provider_call_id=new_id("call"), status="failed",
                error="number not reachable in the demo dataset",
            )
        if vendor.call_outcome != "completed":
            return CallResult(provider_call_id=new_id("call"), status=vendor.call_outcome)

        transcript = [{"speaker": "agent", "text": opening}]
        transcript.append({"speaker": "supplier", "text": "Ya, silakan."})
        for question in questions:
            transcript.append({"speaker": "agent", "text": question})
            answer = _match_answer(question, vendor.call_answers)
            transcript.append(
                {
                    "speaker": "supplier",
                    "text": answer or "Untuk itu saya harus cek dulu ke bagian produksi.",
                }
            )
        transcript.append({"speaker": "agent", "text": "Terima kasih banyak atas waktunya."})
        return CallResult(
            provider_call_id=new_id("tcall"),
            status="completed",
            transcript=transcript,
            duration_seconds=45 + 20 * len(questions),
        )


def _digits(value: str) -> str:
    digits = re.sub(r"[^0-9]", "", value or "")
    return digits[-9:] if len(digits) >= 9 else digits


def _match_answer(question: str, answers: dict[str, str]) -> str | None:
    q = question.lower()
    for needle, answer in answers.items():
        if needle.lower() in q:
            return answer
    # Fall back to token overlap so paraphrased questions still land.
    best, best_score = None, 0
    for needle, answer in answers.items():
        score = len(_tokens(needle) & _tokens(q))
        if score > best_score:
            best, best_score = answer, score
    return best if best_score > 0 else None
