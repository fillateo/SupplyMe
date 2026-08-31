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
        # Decoded to reject a malformed notification here rather than inside the
        # read. Google redelivers a 5xx indefinitely, and a push that will never
        # parse will never parse on the tenth attempt either.
        json.loads(base64.b64decode(raw).decode())
    except ValueError:
        log.warning("gmail_push_undecodable")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    await drain_mailbox(rt)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/mail/poll")
async def mail_poll(
    rt: Runtime = Depends(runtime), _: None = Depends(verify_push_token)
) -> dict[str, int]:
    """Ask the mailbox whether anything arrived.

    IMAP has no push, so something has to ask; Cloud Scheduler does, every
    fifteen minutes — see terraform/scheduler.tf, which explains why that
    number and not a shorter one. Cloud Run scales to zero between missions, so
    this is also what wakes the service up to notice a reply at all.

    Returns counts rather than 204 because this endpoint is the one a human
    curls when a reply seems to have gone missing, and "read 3, resumed 1" is
    the answer to that question.
    """
    return await drain_mailbox(rt)


async def drain_mailbox(rt: Runtime) -> dict[str, int]:
    """Turn whatever is new in the mailbox into events, once.

    Shared by the Gmail push notification and the IMAP poll because the only
    thing that differs between them is what prompted the read: Gmail tells us
    history moved and IMAP has to be asked, and in both cases the work is to
    fetch what is new, match each message to the conversation that asked for it,
    and leave the rest alone.
    """
    stored = await rt.providers.store.get("mail_state", "cursor")
    since = (stored or {}).get("cursor")

    try:
        messages, new_cursor = await rt.providers.mail.history(since)
    except Exception as exc:
        # A mailbox that cannot be reached is a transient problem, and raising
        # would make Cloud Scheduler retry a poll that is about to happen again
        # anyway. The cursor is not advanced, so nothing is skipped.
        log.warning("mail_history_failed", extra={"error": str(exc)[:200]})
        return {"read": 0, "resumed": 0, "failed": 1}

    # Written before the messages are dispatched, so a crash mid-dispatch cannot
    # replay the whole batch. Anything genuinely lost that way arrives again as
    # a follow-up on silence, which is the behaviour for an unanswered email.
    if new_cursor and new_cursor != since:
        await rt.providers.store.put("mail_state", "cursor", {"cursor": new_cursor})

    resumed = 0
    for message in messages:
        mission_id = await _mission_for_thread(rt, message.provider_thread_id, message.from_address)
        if mission_id is None:
            # A mailbox receives more than supplier replies. Anything matching
            # no thread is somebody else's mail and must not enter a mission.
            log.info("mail_message_unrelated", extra={"status": "ignored"})
            continue
        resumed += 1
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
    log.info("mail_drained", extra={"status": f"read {len(messages)}, resumed {resumed}"})
    return {"read": len(messages), "resumed": resumed, "failed": 0}


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
