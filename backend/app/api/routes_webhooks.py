"""Inbound webhooks from the outside world.

This module is the whole reason the product is a Taskmaster: a supplier answers
hours later, Gmail posts here, and the mission resumes with nobody watching.

Everything arriving here is untrusted. It is turned into an event and handed to
the workflow; no content from a webhook ever becomes an instruction.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, Response, status

from ..domain.events import Event, EventType
from ..domain.models import EmailThread
from ..runtime import Runtime
from .deps import runtime, verify_push_token

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/gmail", status_code=status.HTTP_204_NO_CONTENT)
async def gmail_push(
    request: Request, rt: Runtime = Depends(runtime), _: None = Depends(verify_push_token)
) -> Response:
    """Gmail watch notification: new mail arrived somewhere in the mailbox.

    Gmail tells us only that history advanced, not what changed, so we pull the
    new messages and match each to the thread that asked for it. A message that
    matches no mission thread is somebody else's mail and is ignored.
    """
    import base64
    import json

    envelope = await request.json()
    raw = (envelope.get("message") or {}).get("data")
    if not raw:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        notification = json.loads(base64.b64decode(raw).decode())
    except ValueError:
        log.warning("gmail_push_undecodable")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    history_id = str(notification.get("historyId", ""))
    stored = await rt.providers.store.get("gmail_state", "watch")
    since = (stored or {}).get("history_id")

    try:
        messages, new_token = await rt.providers.mail.history(since)
    except Exception as exc:
        log.warning("gmail_history_failed", extra={"error": str(exc)})
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    await rt.providers.store.put(
        "gmail_state", "watch", {"history_id": new_token or history_id}
    )

    for message in messages:
        mission_id = await _mission_for_thread(rt, message.provider_thread_id, message.from_address)
        if mission_id is None:
            log.info("gmail_message_unrelated", extra={"status": "ignored"})
            continue
        await rt.orchestrator.emit(
            Event(
                type=EventType.EMAIL_RECEIVED,
                mission_id=mission_id,
                payload={
                    "provider_thread_id": message.provider_thread_id,
                    "provider_message_id": message.provider_message_id,
                    "from_address": message.from_address,
                    "subject": message.subject,
                    "body": message.body,
                },
            )
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _mission_for_thread(rt: Runtime, provider_thread_id: str, sender: str) -> str | None:
    """Find which mission owns an inbound message. Returns None for stranger mail."""
    if provider_thread_id:
        threads = await rt.repo.list(EmailThread, provider_thread_id=provider_thread_id)
        if threads:
            return threads[0].mission_id

    address = sender.split("<")[-1].strip(" >").lower() if "<" in sender else sender.lower()
    if not address:
        return None
    for thread in await rt.repo.list(EmailThread):
        if thread.to_address.lower() == address:
            return thread.mission_id
    return None
