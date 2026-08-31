"""Reading replies back out of the mailbox.

`SmtpMailProvider` sends and cannot read, so a mission bound to it wrote to
suppliers and then waited on a silence it had no way to break. The Gmail API
closes that loop with push notifications, and needs an OAuth client, a consent
screen and a browser sign-in from whoever owns the mailbox.

IMAP needs none of that: the same app password that already sends can read, so
the loop closes with one credential and no console work. What it gives up is
push. Nothing tells us mail arrived, so something has to ask — see
`/webhooks/mail/poll` and the Cloud Scheduler job in terraform/scheduler.tf.
That is a real trade and worth naming: a supplier answering at 2am is picked up
on the next poll rather than the same second.

**Matching a reply to the mission that caused it** is the part that is not
obvious. When outreach is redirected for testing, replies arrive from the test
mailbox rather than from the supplier, so the sender address matches no thread.
What does survive is the mail thread itself: every message we send carries a
`Message-ID`, and any reply carries it back in `In-Reply-To` and `References`.
Those headers are what a mail client uses to draw a conversation, and they are
what we use here.
"""

from __future__ import annotations

import asyncio
import contextlib
import email
import imaplib
import logging
from email.header import decode_header, make_header
from email.message import Message
from typing import Any

from ..config import Settings
from ..ports.base import InboundMail
from .smtp_mail import SmtpMailProvider

log = logging.getLogger(__name__)

#: Never read more than this in one poll. A mailbox that has been sitting for a
#: week should not turn the first poll after a deploy into a thousand events.
MAX_PER_POLL = 25


class SmtpImapMailProvider(SmtpMailProvider):
    """Sends over SMTP, reads over IMAP. One app password does both."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._imap_host = settings.imap_host
        self._imap_port = settings.imap_port

    # -- reading ------------------------------------------------------------

    async def history(self, since_token: str | None = None) -> tuple[list[InboundMail], str]:
        """New mail since `since_token`, and the cursor to pass next time.

        The cursor is an IMAP UID, which is monotonic within a mailbox, so this
        never re-reads a message it has already turned into an event. The
        orchestrator would deduplicate a repeat anyway — the event key is a hash
        of the payload — but re-fetching a hundred messages every minute to have
        them all discarded is a poor use of a mailbox.
        """
        return await asyncio.to_thread(self._read_since, since_token)

    # -- IMAP, which is synchronous and therefore off the event loop --------

    def _connect(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL(self._imap_host, self._imap_port, timeout=30)
        client.login(self._user, self._password)
        client.select("INBOX")
        return client

    def _read_since(self, since_token: str | None) -> tuple[list[InboundMail], str]:
        client = self._connect()
        try:
            if since_token is None:
                # Never polled. Start at the newest message rather than at zero:
                # the replies this exists to catch are answers to mail we have
                # not sent yet, so everything already in the mailbox is somebody
                # else's. Walking a year of newsletters to discard all of it is
                # a slow and noisy way to begin.
                return [], str(self._newest_uid(client))

            try:
                last_uid = int(since_token)
            except ValueError:
                last_uid = 0

            # `UID <n>:*` is Gmail's own idiom for "everything newer". It returns
            # at least one message even when none are newer, so the result is
            # filtered rather than trusted.
            typ, data = client.uid("SEARCH", None, f"UID {last_uid + 1}:*")
            if typ != "OK" or not data or not data[0]:
                return [], str(last_uid)

            uids = [int(raw) for raw in data[0].split() if int(raw) > last_uid]
            if not uids:
                return [], str(last_uid)

            messages: list[InboundMail] = []
            highest = last_uid
            for uid in sorted(uids)[:MAX_PER_POLL]:
                parsed = self._fetch_one(client, uid)
                highest = max(highest, uid)
                if parsed is not None:
                    messages.append(parsed)
            return messages, str(highest)
        finally:
            _close(client)

    @staticmethod
    def _newest_uid(client: imaplib.IMAP4_SSL) -> int:
        typ, data = client.uid("SEARCH", None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return 0
        return max(int(raw) for raw in data[0].split())

    def _fetch_one(self, client: imaplib.IMAP4_SSL, uid: int) -> InboundMail | None:
        typ, data = client.uid("FETCH", str(uid), "(RFC822)")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return None
        message = email.message_from_bytes(data[0][1])

        sender = _header(message, "From")
        if self._is_our_own(sender):
            # Gmail files sent mail into the conversation. Reading our own
            # outreach back as a supplier reply would have the mission answering
            # itself, and quoting itself as evidence.
            return None

        return InboundMail(
            provider_message_id=_header(message, "Message-ID") or f"uid-{uid}",
            provider_thread_id=_thread_of(message) or _header(message, "Message-ID"),
            from_address=sender,
            subject=_header(message, "Subject"),
            body=_body_of(message),
            received_at=_header(message, "Date"),
        )

    def _is_our_own(self, sender: str) -> bool:
        address = sender.split("<")[-1].strip(" >").lower()
        return bool(self._from) and address == self._from.strip().lower()


def _close(client: imaplib.IMAP4_SSL) -> None:
    # Either may already have happened, or the mailbox may never have been
    # selected. Neither is worth failing a poll over.
    with contextlib.suppress(Exception):
        client.close()
    with contextlib.suppress(Exception):
        client.logout()


def _header(message: Message, name: str) -> str:
    raw = message.get(name)
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:
        # A malformed header is not worth losing the message over.
        return str(raw).strip()


def _thread_of(message: Message) -> str:
    """The Message-ID of ours that this reply is answering.

    `In-Reply-To` is the direct answer and is preferred. `References` carries
    the whole chain, oldest first, so its first entry is the message that opened
    the conversation — which is the id a thread was recorded under.
    """
    in_reply_to = _header(message, "In-Reply-To")
    if in_reply_to:
        return in_reply_to.split()[0]
    references = _header(message, "References").split()
    return references[0] if references else ""


def _body_of(message: Message) -> str:
    """Plain text, preferred over HTML, decoded as forgivingly as possible."""
    if not message.is_multipart():
        return _decode(message)

    html: str = ""
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_filename():
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain":
            text = _decode(part)
            if text.strip():
                return text
        elif content_type == "text/html" and not html:
            html = _decode(part)
    return html


def _decode(part: Any) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")
