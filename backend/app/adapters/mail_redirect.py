"""A safety valve for testing outreach against real suppliers.

The gap between "the mail path works" and "the mail path works, and a stranger's
inbox is the proof" is the last thing a sourcing agent should cross on a hunch.
The addresses in a live mission belong to real businesses, read off their real
websites, and the distance between a good demo and an apology is one
environment variable.

So this wraps whichever mail provider is bound and delivers every message to one
address you nominate instead. The workflow is untouched — threads still record
the supplier they were written to, follow-ups still match, idempotency keys are
unchanged — and the message says at the top who it would have reached. Delivery
is the only thing that moves.

Wrapping rather than editing `GmailProvider` is deliberate: a redirect that
lives inside one provider is bypassed by binding a different one, and a guard
you can step around by accident is not a guard.
"""

from __future__ import annotations

import logging
from typing import Any

from ..ports.base import InboundMail, SentMail

log = logging.getLogger(__name__)

BANNER = (
    "=============================================================\n"
    "REDIRECTED TEST MESSAGE - this did NOT go to the supplier.\n"
    "Intended recipient: {to}\n"
    "Unset VDS_MAIL_REDIRECT_TO to write to suppliers for real.\n"
    "=============================================================\n\n"
)


class RedirectingMailProvider:
    """Delivers everything to one address, and says so in the message."""

    def __init__(self, inner: Any, redirect_to: str) -> None:
        self._inner = inner
        self._redirect_to = redirect_to.strip()
        #: What was diverted, for tests and for reading back afterwards.
        self.redirected: list[dict[str, str]] = []

    @property
    def redirect_to(self) -> str:
        return self._redirect_to

    def __getattr__(self, name: str) -> Any:
        """Anything that is not about sending belongs to the provider underneath."""
        return getattr(self._inner, name)

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        mission_id: str = "",
    ) -> SentMail:
        intended = to
        self.redirected.append({"intended": intended, "subject": subject})
        log.warning(
            "mail_redirected",
            extra={"mission_id": mission_id, "status": f"{intended} -> {self._redirect_to}"},
        )
        return await self._inner.send(
            to=self._redirect_to,
            # Marked in the subject as well as the body: the subject line is what
            # you actually see in an inbox holding forty test messages.
            subject=f"[TEST -> {intended}] {subject}",
            body=BANNER.format(to=intended) + body,
            thread_id=thread_id,
            mission_id=mission_id,
        )

    async def fetch_thread(self, provider_thread_id: str) -> list[InboundMail]:
        return await self._inner.fetch_thread(provider_thread_id)

    async def history(self, since_token: str | None = None) -> tuple[list[InboundMail], str]:
        return await self._inner.history(since_token)
