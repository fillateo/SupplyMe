"""Run a complete mission end to end and print what actually happened.

This is the proof-of-action script: every line it prints comes from a stored
workflow event or a stored document, not from a narration of what the code
intends to do.

    python scripts/run_demo.py               # scripted model, no API cost
    python scripts/run_demo.py --live-model  # same workflow, real Gemini calls
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ApprovalPolicy, Mode, Settings
from app.domain.models import (
    BrandRelationship,
    Conflict,
    EmailThread,
    Evidence,
    Recommendation,
    SupplyChainNode,
    Vendor,
)
from app.runtime import Runtime

OBJECTIVE = (
    "I want to launch a 50ml EDP perfume in Indonesia. Initial production: 500 units. "
    "I want premium packaging, but I want to minimize risk on the first batch. "
    "Find the suppliers I need, research them, and contact the best candidates."
)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-model", action="store_true", help="use real Gemini calls")
    parser.add_argument("--project", default="", help="Google Cloud project for Vertex AI")
    parser.add_argument("--duplicate-rate", type=float, default=0.3,
                        help="fraction of events redelivered, to prove idempotency")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )

    settings = Settings(
        mode=Mode.DEMO,
        # Autonomous so a single run reaches the end; the approval path has its
        # own test in tests/test_workflow.py.
        approval_policy=ApprovalPolicy.AUTONOMOUS,
        project_id=args.project,
    )

    if args.live_model:
        runtime = Runtime.build(
            settings, demo_speedup=100_000.0, duplicate_rate=args.duplicate_rate
        )
    else:
        from tests.fixtures import build_scripted_llm

        runtime = Runtime.build(
            settings, llm=build_scripted_llm(), demo_speedup=100_000.0,
            duplicate_rate=args.duplicate_rate,
        )

    print("=" * 78)
    print("VendorDiscoveryShortcut — demo run")
    for note in runtime.providers.notes:
        print(f"  note: {note}")
    print("=" * 78)

    await runtime.start(concurrency=8)
    mission = await runtime.create_mission(OBJECTIVE)
    print(f"\nmission {mission.id}\n{OBJECTIVE}\n")

    # Supplier replies arrive on a compressed clock. Wait for the mission itself
    # to reach a terminal state — the scheduler is never empty, because the
    # 48-hour follow-up timers are supposed to still be pending.
    for _ in range(400):
        await runtime.drain(timeout=180)
        current = await runtime.repo.mission(mission.id)
        if current.status.value in ("completed", "failed"):
            break
        await asyncio.sleep(0.1)
    await runtime.drain(timeout=180)

    await report(runtime, mission.id)
    await runtime.stop()
    return 0


async def report(runtime: Runtime, mission_id: str) -> None:
    repo = runtime.repo
    mission = await repo.mission(mission_id)
    timeline = await runtime.providers.store.timeline(mission_id)

    print("-" * 78)
    print("ACTIVITY TIMELINE (from stored workflow events)")
    print("-" * 78)
    for entry in timeline:
        if entry["status"] not in ("ok", "dropped", "exhausted", "failed"):
            continue
        emitted = f" -> {', '.join(entry['emitted'])}" if entry["emitted"] else ""
        subject = entry["payload"].get("vendor_id") or entry["payload"].get("node_key") or ""
        print(f"  {entry['type']:<28} {subject[:20]:<20}{emitted}")

    nodes = await repo.list(SupplyChainNode, mission_id=mission_id)
    vendors = await repo.list(Vendor, mission_id=mission_id)
    evidence = await repo.list(Evidence, mission_id=mission_id)
    relationships = await repo.list(BrandRelationship, mission_id=mission_id)
    conflicts = await repo.list(Conflict, mission_id=mission_id)
    threads = await repo.list(EmailThread, mission_id=mission_id)

    print("\n" + "-" * 78)
    print(f"SUPPLY CHAIN ({len(nodes)} categories)")
    print("-" * 78)
    for node in nodes:
        consolidation = (
            f"  [may consolidate with: {', '.join(node.consolidates_with)}]"
            if node.consolidates_with else ""
        )
        print(f"  {node.key:<12} {node.name}{consolidation}")

    print("\n" + "-" * 78)
    print(f"VENDORS ({len(vendors)})")
    print("-" * 78)
    for vendor in sorted(vendors, key=lambda v: v.name):
        print(f"  {vendor.name} — {vendor.city or '?'} [{vendor.status.value}]")
        for field in ("moq", "unit_price", "lead_time_days"):
            fact = vendor.fact(field)
            value = f"{fact.value}" if fact.known else "unknown"
            print(f"      {field:<16} {value:<12} {fact.provenance.value}")
        if vendor.rejection_reasons:
            print(f"      rejected: {'; '.join(vendor.rejection_reasons)}")

    print("\n" + "-" * 78)
    print(f"BRAND CLAIMS ({len(relationships)})")
    print("-" * 78)
    by_id = {v.id: v.name for v in vendors}
    for relationship in relationships:
        print(
            f"  {by_id.get(relationship.vendor_id, '?')} -> {relationship.brand}: "
            f"{relationship.classification.value} "
            f"({relationship.independent_sources} independent source(s), "
            f"confidence {relationship.confidence:.0%})"
        )

    print("\n" + "-" * 78)
    print(f"CONFLICTS ({len(conflicts)})")
    print("-" * 78)
    for conflict in conflicts:
        values = " vs ".join(
            f"{v['value']} ({v['source_type']})" for v in conflict.values
        )
        print(f"  {by_id.get(conflict.vendor_id, '?')} — {conflict.field}: {values}")
        print(f"      status: {conflict.status.value}; action: {conflict.resolution_action}")
        if conflict.resolved_value is not None:
            print(f"      resolved to {conflict.resolved_value} — {conflict.preferred_reason}")

    print("\n" + "-" * 78)
    print(f"COMMUNICATIONS — {len(threads)} email thread(s)")
    print("-" * 78)
    for thread in threads:
        print(
            f"  {by_id.get(thread.vendor_id, '?')} <{thread.to_address}> "
            f"[{thread.status.value}] {len(thread.messages)} message(s), "
            f"{len(thread.answered)}/{len(thread.asked)} questions answered"
        )

    recommendations = await repo.list(Recommendation, mission_id=mission_id)
    if recommendations:
        rec = recommendations[-1]
        print("\n" + "=" * 78)
        print("RECOMMENDED SUPPLY NETWORK")
        print("=" * 78)
        for selection in rec.selections:
            print(f"\n  {selection['node_name']}: {selection['vendor']['name']}")
            print(f"    score {selection['score']['total']:.1f}/100")
            for reason in selection.get("why", []):
                print(f"    - {reason}")
        if rec.estimated_unit_cost:
            print(f"\n  Estimated unit cost: {rec.currency} {rec.estimated_unit_cost:,.0f}")
        if rec.rejected:
            print("\n  NOT VIABLE:")
            for row in rec.rejected[:6]:
                reasons = row["score"]["rejection_reasons"] or row["vendor"]["rejection_reasons"]
                print(f"    {row['vendor']['name']} ({row['node_name']}): {'; '.join(reasons)}")
        for label, items in (("RISKS", rec.risks), ("UNKNOWNS", rec.unknowns),
                             ("NEXT ACTIONS", rec.next_actions)):
            if items:
                print(f"\n  {label}:")
                for item in items:
                    print(f"    - {item}")

    print("\n" + "=" * 78)
    print(f"mission status: {mission.status.value}")
    print(f"evidence records: {len(evidence)}   emails sent: {mission.emails_sent}")
    print("orchestrator counters:", runtime.orchestrator.stats)
    print("=" * 78)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
