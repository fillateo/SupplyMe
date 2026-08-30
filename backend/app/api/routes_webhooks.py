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
from ..domain.models import EmailThread, ThreadStatus
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


#: Threads that are still waiting to hear back. A reply belongs to one of these,
#: not to a conversation that already finished.
_OPEN_THREAD_STATUSES = frozenset({ThreadStatus.SENT, ThreadStatus.RESPONDED})


async def _mission_for_thread(rt: Runtime, provider_thread_id: str, sender: str) -> str | None:
    """Find which mission owns an inbound message. Returns None for stranger mail.

    The provider's own thread id is the reliable answer and is tried first. The
    address fallback exists because a supplier who replies from a different
    mailbox, or whose client starts a new thread, still deserves to be heard —
    but it has to choose between candidates, because the same supplier can be
    contacted by more than one mission. Two rules make that choice defensible
    rather than arbitrary: only threads still awaiting a reply are eligible, and
    among those the most recently written-to wins. Returning whichever record
    the store happened to list first could attribute a reply to a mission that
    stopped asking weeks ago.
    """
    if provider_thread_id:
        threads = await rt.repo.list(EmailThread, provider_thread_id=provider_thread_id)
        if threads:
            return threads[0].mission_id

    address = sender.split("<")[-1].strip(" >").lower() if "<" in sender else sender.lower()
    if not address:
        return None

    candidates = [
        thread
        for thread in await rt.repo.list(EmailThread)
        if thread.to_address.lower() == address and thread.status in _OPEN_THREAD_STATUSES
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda thread: thread.updated_at).mission_id
