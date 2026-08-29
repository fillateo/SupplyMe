"""Gmail send + read, with push notifications.

The push path is what makes the product a Taskmaster rather than a batch job:
`users.watch` points Gmail at a Pub/Sub topic, Gmail posts a historyId when
anything changes, and app/api/routes_webhooks.py turns that into an
`email.received` event. The browser does not need to be open, and nothing in the
workflow polls.

OAuth scopes are the minimum that supports that flow: send, read, and modify for
labelling handled threads.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from email.message import EmailMessage

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..config import Settings
from ..ports.base import InboundMail, SentMail

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailProvider:
    def __init__(self, settings: Settings, credentials: Credentials) -> None:
        self._settings = settings
        self._credentials = credentials
        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        self._sender = settings.gmail_sender

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        mission_id: str = "",   # unused: Gmail push resolves the mission on receipt
    ) -> SentMail:
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        if self._sender:
            message["From"] = self._sender
        message.set_content(body)

        payload = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
        if thread_id:
            payload["threadId"] = thread_id

        sent = await asyncio.to_thread(
            lambda: self._service.users().messages().send(userId="me", body=payload).execute()
        )
        return SentMail(
            provider_message_id=sent["id"], provider_thread_id=sent.get("threadId", "")
        )

    async def fetch_thread(self, provider_thread_id: str) -> list[InboundMail]:
        thread = await asyncio.to_thread(
            lambda: self._service.users()
            .threads()
            .get(userId="me", id=provider_thread_id, format="full")
            .execute()
        )
        return [_to_inbound(m) for m in thread.get("messages", [])]

    async def history(self, since_token: str | None = None) -> tuple[list[InboundMail], str]:
        """Messages added since `since_token`, plus the new token to store."""
        if not since_token:
            profile = await asyncio.to_thread(
                lambda: self._service.users().getProfile(userId="me").execute()
            )
            return [], str(profile["historyId"])

        response = await asyncio.to_thread(
            lambda: self._service.users()
            .history()
            .list(userId="me", startHistoryId=since_token, historyTypes=["messageAdded"])
            .execute()
        )
        messages: list[InboundMail] = []
        for record in response.get("history", []):
            for added in record.get("messagesAdded", []):
                message_id = added["message"]["id"]
                full = await asyncio.to_thread(
                    lambda mid=message_id: self._service.users()
                    .messages()
                    .get(userId="me", id=mid, format="full")
                    .execute()
                )
                if "SENT" in (full.get("labelIds") or []):
                    continue  # our own outbound copy
                messages.append(_to_inbound(full))
        return messages, str(response.get("historyId", since_token))

    async def watch(self, topic: str) -> str:
        """Ask Gmail to push change notifications to `topic`. Returns the historyId."""
        response = await asyncio.to_thread(
            lambda: self._service.users()
            .watch(userId="me", body={"topicName": topic, "labelIds": ["INBOX"]})
            .execute()
        )
        log.info("gmail_watch_started", extra={"expiration": response.get("expiration")})
        return str(response["historyId"])


def _to_inbound(message: dict) -> InboundMail:
    headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
    return InboundMail(
        provider_message_id=message["id"],
        provider_thread_id=message.get("threadId", ""),
        from_address=headers.get("from", ""),
        subject=headers.get("subject", ""),
        body=_extract_body(message.get("payload", {})),
        received_at=headers.get("date", ""),
    )


def _extract_body(payload: dict) -> str:
    """Prefer text/plain; fall back to the first text part. HTML is not rendered."""
    mime = payload.get("mimeType", "")
    data = (payload.get("body") or {}).get("data")
    if mime == "text/plain" and data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        found = _extract_body(part)
        if found:
            return found
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return ""


def credentials_from_dict(raw: dict) -> Credentials:
    creds = Credentials.from_authorized_user_info(raw, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds
