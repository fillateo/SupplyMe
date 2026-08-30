"""The workflow's event vocabulary and envelope.

Every state transition in the system is one of these events. Handlers consume an
envelope and return zero or more new envelopes; nothing else moves the workflow
forward. That constraint is what makes the workflow resumable: rebuilding state
means replaying the event log.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .ids import new_id, stable_id


class EventType(StrEnum):
    MISSION_CREATED = "mission.created"
    REQUIREMENTS_CREATED = "requirements.created"
    SUPPLY_CHAIN_PLANNED = "supply_chain.planned"
    SUPPLIER_DISCOVERY_STARTED = "supplier.discovery.started"
    VENDOR_DISCOVERED = "vendor.discovered"
    VENDOR_RESEARCH_STARTED = "vendor.research.started"
    EVIDENCE_FOUND = "evidence.found"
    BRAND_CLAIM_FOUND = "brand.claim.found"
    BRAND_CLAIM_ADJUDICATED = "brand.claim.adjudicated"
    VENDOR_QUALIFIED = "vendor.qualified"
    VENDOR_REJECTED = "vendor.rejected"
    VENDOR_CONTACT_REQUIRED = "vendor.contact.required"
    EMAIL_DRAFT_CREATED = "email.draft.created"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"
    EMAIL_SENT = "email.sent"
    EMAIL_RECEIVED = "email.received"
    QUOTE_EXTRACTED = "quote.extracted"
    CONFLICT_DETECTED = "conflict.detected"
    FOLLOW_UP_REQUIRED = "followup.required"
    VENDOR_UPDATED = "vendor.updated"
    RECOMMENDATION_READY = "recommendation.ready"
    MISSION_COMPLETED = "mission.completed"
    MISSION_FAILED = "mission.failed"


#: Events that represent an irreversible outward-facing action. The orchestrator
#: refuses to execute these without an idempotency reservation.
EXTERNAL_ACTION_EVENTS = frozenset({EventType.EMAIL_SENT})


class Event(BaseModel):
    """A workflow event. `key` is what makes redelivery safe."""

    id: str = Field(default_factory=lambda: new_id("evt"))
    type: EventType
    mission_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    #: Causal parent; lets the activity timeline render a real tree.
    caused_by: str | None = None
    attempt: int = 0

    @property
    def key(self) -> str:
        """Deduplication key: same logical event -> same key across redeliveries.

        Derived from the entire payload rather than a chosen subset. An earlier
        version keyed on a fixed list of id fields, which silently collapsed
        distinct events that happened not to carry any of them — three different
        supplier replies became one, and every `vendor.updated` after the first
        was discarded as a duplicate. Hashing the whole payload makes a new
        logical event a new key by construction; only a true redelivery, which
        carries a byte-identical payload, collides.
        """
        canonical = json.dumps(self.payload, sort_keys=True, default=str)
        return stable_id("k", self.mission_id, self.type.value, canonical)

    def child(self, type_: EventType, **payload: Any) -> Event:
        return Event(
            type=type_, mission_id=self.mission_id, payload=payload, caused_by=self.id
        )
