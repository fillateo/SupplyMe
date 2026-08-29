"""Deterministic identifiers.

Workflow ids are content-derived wherever a retry must produce the same id, so
a redelivered Pub/Sub message writes the same Firestore document instead of a
duplicate.
"""

from __future__ import annotations

import hashlib
import re
import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def stable_id(prefix: str, *parts: str) -> str:
    """Same inputs -> same id. Used for evidence, quotes and outreach actions."""
    digest = hashlib.sha256("\x1f".join(p.strip().lower() for p in parts).encode()).hexdigest()
    return f"{prefix}_{digest[:20]}"


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.strip().lower()).strip("-")
