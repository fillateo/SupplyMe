"""Sending real mail without an OAuth dance.

The Gmail API path is the better one in production: it reads replies, and its
push notifications are what let a mission wake up when a supplier answers at 2am.
It also needs an OAuth client that can only be created in the Cloud Console, a
consent screen, and a browser sign-in — three steps, every one of which requires
the person who owns the mailbox.

For proving that outreach genuinely sends, that ceremony buys nothing, and the
message that lands in the inbox is identical either way. So this is the short
path: real delivery, one credential.

What it cannot do is read: `history` returns nothing, so a mission bound to
this provider alone sends for real and then follows up on silence exactly as it
would with a supplier who never answered. `SmtpImapMailProvider` in
imap_mail.py subclasses it to close that loop.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

from ..config import Settings
from ..ports.base import InboundMail, SentMail

log = logging.getLogger(__name__)


class SmtpMailProvider:
    """Outbound-only mail over SMTP. Enough to prove the path really sends."""

    def __init__(self, settings: Settings) -> None:
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._user = settings.smtp_user
        self._password = settings.smtp_password
        self._from = settings.smtp_from or settings.smtp_user

    @property
    def configured(self) -> bool:
        return bool(self._host and self._user and self._password)

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        mission_id: str = "",
    ) -> SentMail:
        message = EmailMessage()
        message["To"] = to
        message["From"] = self._from
        message["Subject"] = subject
        message_id = make_msgid()
        message["Message-ID"] = message_id
        if thread_id:
            # Keeps a follow-up in the same conversation in the recipient's mail
            # client, so the thread reads as a thread rather than as three
            # unrelated messages from a stranger.
            message["In-Reply-To"] = thread_id
            message["References"] = thread_id
        message.set_content(body)

        # smtplib is synchronous and this runs on the event loop, so the whole
        # exchange goes to a worker thread rather than stalling every other
        # branch of the mission for the length of a TLS handshake.
        await asyncio.to_thread(self._deliver, message)
        log.info(
            "smtp_mail_sent",
            extra={"mission_id": mission_id, "status": f"{self._from} -> {to}"},
        )
        return SentMail(
            provider_message_id=message_id, provider_thread_id=thread_id or message_id
        )

    def _deliver(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        with smtplib.SMTP(self._host, self._port, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(self._user, self._password)
            server.send_message(message)

    async def history(self, since_token: str | None = None) -> tuple[list[InboundMail], str]:
        return [], since_token or "0"
