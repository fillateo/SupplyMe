"""Idempotency for actions that cannot be taken back.

Pub/Sub is at-least-once. Without a reservation, a redelivered `EmailApproved`
sends the supplier a second copy of the same request. The key is
`mission + vendor + action + version`, so a genuinely *new* action (the vendor
record changed, hence a new version) is allowed through while a replay is not.
"""

from __future__ import annotations

from .ids import stable_id


def action_key(mission_id: str, vendor_id: str, action_type: str, version: int | str = 0) -> str:
    return stable_id("act", mission_id, vendor_id, action_type, str(version))
