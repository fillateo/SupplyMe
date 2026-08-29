"""Event ingress from Google Cloud.

In the cloud there is no in-process bus: Pub/Sub push and Cloud Tasks both POST
here, and the orchestrator handles the event exactly as it would locally. Both
endpoints return 204 for anything they cannot use, because a 4xx or 5xx makes
Pub/Sub redeliver a message that will never succeed.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging

from fastapi import APIRouter, Depends, Request, Response, status

from ..domain.events import Event
from ..runtime import Runtime
from .deps import runtime, verify_push_token

log = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/pubsub", status_code=status.HTTP_204_NO_CONTENT)
async def pubsub_push(
    request: Request, rt: Runtime = Depends(runtime), _: None = Depends(verify_push_token)
) -> Response:
    """Pub/Sub push subscription endpoint."""
    envelope = await _json(request)
    message = (envelope or {}).get("message") or {}
    raw = message.get("data")
    if not raw:
        log.warning("pubsub_push_without_data")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        payload = json.loads(base64.b64decode(raw).decode())
        event = Event.model_validate(payload)
    except (ValueError, binascii.Error) as exc:
        # Unparseable: acknowledge it. Redelivering it will not make it parse.
        log.warning("pubsub_push_undecodable", extra={"error": str(exc)})
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    log.info(
        "pubsub_push_received",
        extra={"event_id": event.id, "event_type": event.type.value,
               "mission_id": event.mission_id, "dedup_key": event.key},
    )
    await rt.handle(event)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/task", status_code=status.HTTP_204_NO_CONTENT)
async def cloud_task(
    request: Request, rt: Runtime = Depends(runtime), _: None = Depends(verify_push_token)
) -> Response:
    """Cloud Tasks target: a delayed event whose time has come."""
    payload = await _json(request)
    try:
        event = Event.model_validate(payload)
    except ValueError as exc:
        log.warning("cloud_task_undecodable", extra={"error": str(exc)})
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    log.info(
        "cloud_task_fired",
        extra={"event_id": event.id, "event_type": event.type.value,
               "mission_id": event.mission_id},
    )
    await rt.handle(event)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _json(request: Request) -> dict | None:
    try:
        return await request.json()
    except ValueError:
        return None
