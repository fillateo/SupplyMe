"""Process-wide runtime, built once per Cloud Run instance."""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import Header, HTTPException, Query, status

from ..config import Settings, get_settings
from ..runtime import Runtime

log = logging.getLogger(__name__)

_runtime: Runtime | None = None


async def startup(settings: Settings | None = None, **kw: Any) -> Runtime:
    global _runtime
    settings = settings or get_settings()
    _runtime = Runtime.build(settings, **kw)
    await _runtime.start()
    log.info("runtime_started", extra={"status": "live"})
    for note in _runtime.providers.notes:
        log.warning("provider_note", extra={"status": note})
    return _runtime


async def shutdown() -> None:
    global _runtime
    if _runtime is not None:
        await _runtime.stop()
        _runtime = None


def runtime() -> Runtime:
    if _runtime is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="runtime not started"
        )
    return _runtime


def verify_push_token(
    x_vds_token: str = Header(default=""), token: str = Query(default="")
) -> None:
    """Shared secret on the Pub/Sub and Cloud Tasks endpoints.

    Cloud Run should also be configured to require an OIDC-authenticated caller
    (see terraform/pubsub.tf); this is the second lock, and the one that still
    works when the service is deliberately public for a demo.

    Cloud Tasks sets the header (see adapters/scheduler.py). A Pub/Sub push
    subscription cannot set request headers at all, so it carries the same
    secret in the push endpoint's query string instead — accepting only the
    header rejects every workflow event the cloud deployment ever publishes.
    """
    expected = get_settings().pubsub_push_token
    if not expected:
        return
    if not any(hmac.compare_digest(candidate, expected) for candidate in (x_vds_token, token)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad push token")
