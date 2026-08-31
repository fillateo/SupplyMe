"""End-to-end workflow behaviour, driven through the real event bus."""

from __future__ import annotations

import pytest

from app.config import ApprovalPolicy, Settings
from app.domain.events import Event, EventType
from app.domain.models import (
    Approval,
    ApprovalStatus,
    BrandEvidenceClass,
    BrandRelationship,
    Conflict,
    ConflictStatus,
    EmailThread,
    Evidence,
    Provenance,
    Quote,
    Recommendation,
    SupplyChainNode,
    Vendor,
    VendorStatus,
)
from app.runtime import Runtime

from .conftest import OBJECTIVE, run_to_completion
from .fixtures import build_runtime


@pytest.fixture
async def completed(runtime: Runtime):
    mission = await run_to_completion(runtime, OBJECTIVE)
    return runtime, mission


class TestMissionReachesAnOutcome:
    async def test_the_mission_completes(self, completed):
        _, mission = completed
        assert mission.status.value == "completed"

    async def test_the_objective_is_decomposed_into_several_categories(self, completed):
        runtime, mission = completed
        nodes = await runtime.repo.list(SupplyChainNode, mission_id=mission.id)
        assert len(nodes) >= 5
        assert {"bottle", "filling"} <= {n.key for n in nodes}

    async def test_consolidation_opportunities_are_identified(self, completed):
        runtime, mission = completed
        nodes = await runtime.repo.list(SupplyChainNode, mission_id=mission.id)
        assert any(n.consolidates_with for n in nodes)

    async def test_vendors_are_discovered_and_all_reach_a_terminal_state(self, completed):
        runtime, mission = completed
        vendors = await runtime.repo.list(Vendor, mission_id=mission.id)
        assert len(vendors) >= 4
        assert all(
            v.status in (VendorStatus.QUALIFIED, VendorStatus.REJECTED) for v in vendors
        )

    async def test_a_recommendation_is_produced_with_reasons(self, completed):
        runtime, mission = completed
        recommendations = await runtime.repo.list(Recommendation, mission_id=mission.id)
        assert recommendations
        recommendation = recommendations[-1]
        assert recommendation.selections
        assert all(s.get("why") for s in recommendation.selections)

    async def test_rejections_are_explained(self, completed):
        runtime, mission = completed
        rejected = [
            v for v in await runtime.repo.list(Vendor, mission_id=mission.id)
            if v.status is VendorStatus.REJECTED
        ]
        assert rejected
        assert all(v.rejection_reasons for v in rejected)


class TestEvidenceDiscipline:
    async def test_every_known_fact_carries_provenance_and_a_source(self, completed):
        runtime, mission = completed
        for vendor in await runtime.repo.list(Vendor, mission_id=mission.id):
            for field in ("moq", "unit_price", "lead_time_days"):
                fact = vendor.fact(field)
                if not fact.known:
                    continue
                assert fact.provenance is not Provenance.UNKNOWN
                assert fact.evidence_ids, f"{vendor.name}.{field} has no evidence"

    async def test_every_evidence_record_quotes_its_source(self, completed):
        runtime, mission = completed
        records = await runtime.repo.list(Evidence, mission_id=mission.id)
        assert records
        assert all(r.evidence_excerpt for r in records)

    async def test_an_unsupported_brand_claim_stays_supplier_reported(self, completed):
        """The vendor whose only source is its own website must not be upgraded."""
        runtime, mission = completed
        relationships = await runtime.repo.list(BrandRelationship, mission_id=mission.id)
        by_class = {r.classification for r in relationships}
        assert BrandEvidenceClass.SUPPLIER_REPORTED in by_class
        unsupported = [
            r for r in relationships
            if r.classification is BrandEvidenceClass.SUPPLIER_REPORTED
        ]
        assert all(r.independent_sources == 0 for r in unsupported)
        assert all(r.confidence <= 0.5 for r in unsupported)

    async def test_a_corroborated_brand_claim_is_verified(self, completed):
        runtime, mission = completed
        relationships = await runtime.repo.list(BrandRelationship, mission_id=mission.id)
        verified = [
            r for r in relationships if r.classification is BrandEvidenceClass.VERIFIED
        ]
        assert verified
        assert all(r.independent_sources >= 1 for r in verified)

    async def test_the_two_claims_about_the_same_brand_are_judged_differently(self, completed):
        """Same brand, two suppliers, different evidence — different verdicts."""
        runtime, mission = completed
        relationships = await runtime.repo.list(BrandRelationship, mission_id=mission.id)
        verel = [r for r in relationships if r.brand == "Maison Verel"]
        assert len(verel) == 2
        assert len({r.classification for r in verel}) == 2


class TestConflictResolution:
    async def test_the_moq_disagreement_is_found_and_settled_in_writing(self, completed):
        runtime, mission = completed
        conflicts = await runtime.repo.list(Conflict, mission_id=mission.id)
        moq_conflicts = [c for c in conflicts if c.field == "moq"]
        assert moq_conflicts, "the website/email MOQ disagreement was not detected"

        conflict = moq_conflicts[0]
        assert {v["value"] for v in conflict.values} == {500.0, 1000}
        assert conflict.status is ConflictStatus.RESOLVED
        assert conflict.resolution_action == "email"
        assert conflict.resolved_value == 500


class TestCommunication:
    async def test_outreach_happens_and_replies_are_parsed(self, completed):
        runtime, mission = completed
        threads = await runtime.repo.list(EmailThread, mission_id=mission.id)
        assert len(threads) >= 3
        responded = [t for t in threads if len(t.messages) > 1]
        assert responded
        assert all(t.answered for t in responded)

    async def test_quotes_keep_the_original_message_as_evidence(self, completed):
        runtime, mission = completed
        quotes = await runtime.repo.list(Quote, mission_id=mission.id)
        assert quotes
        assert all(q.raw_text for q in quotes if q.source == "email")

    async def test_unanswered_questions_are_tracked(self, completed):
        runtime, mission = completed
        threads = await runtime.repo.list(EmailThread, mission_id=mission.id)
        tracked = [t for t in threads if t.asked]
        assert tracked
        assert all(set(t.answered) <= set(t.asked) for t in tracked)

    async def test_budgets_are_respected(self, completed):
        runtime, mission = completed
        assert mission.emails_sent <= runtime.settings.max_outreach_per_mission


class TestActivityTimeline:
    async def test_the_timeline_records_real_events(self, completed):
        runtime, mission = completed
        timeline = await runtime.providers.store.timeline(mission.id)
        types = {e["type"] for e in timeline if e["status"] == "ok"}
        for expected in (
            EventType.MISSION_CREATED, EventType.SUPPLY_CHAIN_PLANNED,
            EventType.VENDOR_DISCOVERED, EventType.EMAIL_SENT,
            EventType.EMAIL_RECEIVED, EventType.QUOTE_EXTRACTED,
            EventType.CONFLICT_DETECTED, EventType.FOLLOW_UP_REQUIRED,
            EventType.RECOMMENDATION_READY, EventType.MISSION_COMPLETED,
        ):
            assert expected.value in types, f"{expected.value} never happened"

    async def test_events_record_what_they_caused(self, completed):
        runtime, mission = completed
        timeline = await runtime.providers.store.timeline(mission.id)
        assert any(e["emitted"] for e in timeline)
        assert any(e["caused_by"] for e in timeline)


class TestApprovalGate:
    async def test_outreach_waits_for_approval_and_resumes_on_grant(self):
        """Under the default policy the first email to a vendor is held."""
        settings = Settings(approval_policy=ApprovalPolicy.EXTERNAL_ACTIONS)
        runtime = build_runtime(settings)
        await runtime.start(concurrency=8)
        try:
            mission = await runtime.create_mission(OBJECTIVE)
            await runtime.drain(timeout=120)

            approvals = await runtime.repo.list(Approval, mission_id=mission.id)
            pending = [a for a in approvals if a.status is ApprovalStatus.PENDING]
            assert pending, "no approval was requested for first contact"
            assert {a.action_type for a in pending} >= {"send_email"}

            threads = await runtime.repo.list(EmailThread, mission_id=mission.id)
            assert all(len(t.messages) == 1 for t in threads)
            assert not runtime.providers.mail.sent, "an email was sent without approval"

            approval = next(a for a in pending if a.action_type == "send_email")
            approval.status = ApprovalStatus.GRANTED
            await runtime.repo.save(approval)
            await runtime.orchestrator.emit(
                Event(
                    type=EventType.APPROVAL_GRANTED, mission_id=mission.id,
                    payload={"approval_id": approval.id},
                )
            )
            await runtime.drain(timeout=120)

            assert runtime.providers.mail.sent, "granting approval did not send the email"
            assert runtime.providers.mail.sent[0]["to"] == approval.preview["to"]
        finally:
            await runtime.stop()

    async def test_denial_rejects_the_vendor_rather_than_stalling(self):
        settings = Settings(approval_policy=ApprovalPolicy.EXTERNAL_ACTIONS)
        runtime = build_runtime(settings)
        await runtime.start(concurrency=8)
        try:
            mission = await runtime.create_mission(OBJECTIVE)
            await runtime.drain(timeout=120)
            approvals = await runtime.repo.list(Approval, mission_id=mission.id)
            approval = next(
                a for a in approvals
                if a.status is ApprovalStatus.PENDING and a.action_type == "send_email"
            )
            approval.status = ApprovalStatus.DENIED
            await runtime.repo.save(approval)
            await runtime.orchestrator.emit(
                Event(
                    type=EventType.APPROVAL_DENIED, mission_id=mission.id,
                    payload={"approval_id": approval.id},
                )
            )
            await runtime.drain(timeout=120)

            vendor = await runtime.repo.vendor(approval.vendor_id)
            assert vendor.status is VendorStatus.REJECTED
            assert "declined" in " ".join(vendor.rejection_reasons)
        finally:
            await runtime.stop()


class TestTheNarrativeAgentIsActuallyConsulted:
    """Its output was being thrown away, and nothing noticed.

    The ranking shown to the narrative agent named each node by its display name,
    while the handler looked the returned annotation up by node key. Every lookup
    missed and fell through to the score explanations — which read plausibly, so
    the substitution was invisible in the console and in this suite.
    """

    async def test_the_selection_reasons_come_from_the_agent_not_the_fallback(
        self, completed
    ):
        runtime, mission = completed
        recommendation = (await runtime.repo.list(Recommendation, mission_id=mission.id))[-1]
        assert recommendation.selections
        narrated = [
            s for s in recommendation.selections
            if any(reason.startswith("narrated:") for reason in s.get("why", []))
        ]
        assert narrated, (
            "every selection fell back to its score explanation, so the "
            "recommendation agent's output never reached the report"
        )


class TestLooseningThePolicyUnblocksWhatItAlreadyHeld:
    """An approval outlives the policy that asked for it.

    A deployment switched from `external` to `autonomous` kept six approvals
    pending on its best mission, because nothing revisits a decision already
    recorded as needed. The mission sat blocked, and the console announced that a
    human was required by a service whose entire claim is that none is.
    """

    async def test_pending_approvals_are_granted_when_the_policy_no_longer_needs_them(self):
        settings = Settings(approval_policy=ApprovalPolicy.EXTERNAL_ACTIONS)
        runtime = build_runtime(settings)
        await runtime.start(concurrency=8)
        try:
            mission = await runtime.create_mission(OBJECTIVE)
            await runtime.drain(timeout=120)
            pending = [
                a for a in await runtime.repo.list(Approval, mission_id=mission.id)
                if a.status is ApprovalStatus.PENDING
            ]
            assert pending, "nothing was held back to release"
            assert not runtime.providers.mail.sent
        finally:
            await runtime.stop()

        # The same store, restarted under a policy that asks for nothing.
        relaxed = build_runtime(Settings(approval_policy=ApprovalPolicy.AUTONOMOUS))
        relaxed.providers.store = runtime.providers.store
        relaxed.orchestrator.store = runtime.providers.store
        relaxed.repo._store = runtime.providers.store
        relaxed.orchestrator.repo._store = runtime.providers.store
        await relaxed.start(concurrency=8)
        try:
            await relaxed.drain(timeout=120)
            still_pending = [
                a for a in await relaxed.repo.list(Approval, mission_id=mission.id)
                if a.status is ApprovalStatus.PENDING
            ]
            assert not still_pending, (
                "an approval the current policy would never have asked for is "
                "still blocking the mission"
            )
            assert relaxed.providers.mail.sent, "the released events never actually sent"
        finally:
            await relaxed.stop()

    async def test_an_order_is_still_held_under_every_policy(self):
        """Loosening the policy must not release what no policy may auto-approve."""
        from app.domain.policy import ActionType

        runtime = build_runtime(Settings(approval_policy=ApprovalPolicy.AUTONOMOUS))
        binding = Approval(
            mission_id="msn_x", vendor_id="ven_x",
            action_type=ActionType.PLACE_ORDER.value,
            resume_event={"type": "email.sent", "mission_id": "msn_x", "payload": {}},
        )
        await runtime.repo.save(binding)
        assert await runtime.release_stale_approvals() == 0
        held = await runtime.repo.load(Approval, binding.id)
        assert held is not None and held.status is ApprovalStatus.PENDING


class TestResolvedConflictsAffectTheOutcome:
    """Resolving a disagreement has to change the answer, or it was theatre."""

    async def test_the_confirmed_pilot_moq_replaces_the_emailed_one(self, completed):
        runtime, mission = completed
        conflict = next(
            c for c in await runtime.repo.list(Conflict, mission_id=mission.id)
            if c.field == "moq" and c.status is ConflictStatus.RESOLVED
        )
        vendor = await runtime.repo.vendor(conflict.vendor_id)
        assert vendor.moq.value == conflict.resolved_value == 500
        assert vendor.moq.provenance is Provenance.DIRECT_QUOTE

    async def test_the_score_reflects_the_resolved_value(self, completed):
        runtime, mission = completed
        conflict = next(
            c for c in await runtime.repo.list(Conflict, mission_id=mission.id)
            if c.field == "moq" and c.status is ConflictStatus.RESOLVED
        )
        recommendation = (await runtime.repo.list(Recommendation, mission_id=mission.id))[-1]
        rows = [
            row for row in recommendation.selections + recommendation.alternatives
            if row["vendor"]["id"] == conflict.vendor_id
        ]
        assert rows, "the vendor whose conflict was resolved is absent from the ranking"
        moq_component = next(
            c for c in rows[0]["score"]["components"] if c["name"] == "moq_fit"
        )
        assert "fits" in moq_component["explanation"]
        assert moq_component["raw"] == 1.0
