"""The file-backed store, which is what makes a local run reproducible.

The property that matters is that the file and Firestore are the same database
in two places: a snapshot exported from one opens in the other with the mission
timeline in order, the idempotency reservations intact, and nothing dropped on
the way through — including documents at paths this adapter has no special
handling for, because a store that silently loses part of a backup is worse
than one that refuses to open it.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.adapters.snapshot_store import SnapshotStore


def _snapshot(path: Path, documents: dict) -> Path:
    path.write_text(json.dumps({"meta": {"project": "test"}, "documents": documents}))
    return path


async def test_it_opens_an_exported_snapshot_as_a_database(tmp_path: Path) -> None:
    store = SnapshotStore(
        _snapshot(
            tmp_path / "db.json",
            {
                "missions/msn_1": {"id": "msn_1", "status": "completed"},
                "vendors/ven_1": {"id": "ven_1", "mission_id": "msn_1"},
                "missions/msn_1/workflow_events/evt_b": {
                    "id": "evt_b", "created_at": "2026-01-01T00:00:02Z"
                },
                "missions/msn_1/workflow_events/evt_a": {
                    "id": "evt_a", "created_at": "2026-01-01T00:00:01Z"
                },
            },
        )
    )

    assert await store.get("missions", "msn_1") == {"id": "msn_1", "status": "completed"}
    assert await store.query("vendors", where={"mission_id": "msn_1"}) == [
        {"id": "ven_1", "mission_id": "msn_1"}
    ]
    # Firestore serves the timeline ordered by created_at, so the file has to
    # too — a JSON object does not preserve the order events were written in.
    assert [e["id"] for e in await store.timeline("msn_1")] == ["evt_a", "evt_b"]


async def test_a_timestamp_written_as_a_firestore_value_arrives_as_a_string(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(
        _snapshot(
            tmp_path / "db.json",
            {
                "missions/msn_1": {
                    "id": "msn_1",
                    "created_at": {"__type__": "datetime", "value": "2026-01-01T00:00:00+00:00"},
                }
            },
        )
    )

    mission = await store.get("missions", "msn_1")
    assert mission is not None
    assert mission["created_at"] == "2026-01-01T00:00:00+00:00"


async def test_what_it_writes_is_there_after_a_restart(tmp_path: Path) -> None:
    path = _snapshot(tmp_path / "db.json", {"missions/msn_1": {"id": "msn_1"}})
    store = SnapshotStore(path)

    await store.put("missions", "msn_2", {"id": "msn_2", "status": "running"})
    await store.append_event("msn_2", {"id": "evt_1", "created_at": "2026-01-01T00:00:00Z"})
    assert await store.reserve("outreach:ven_9", {"kind": "email"}) is True
    await store.complete("outreach:ven_9", {"message_id": "m1"})

    reopened = SnapshotStore(path)
    assert await reopened.get("missions", "msn_2") == {"id": "msn_2", "status": "running"}
    assert [e["id"] for e in await reopened.timeline("msn_2")] == ["evt_1"]
    # The claim survives too, which is the point: restarting the process must
    # not let the same supplier be emailed a second time.
    assert await reopened.reserve("outreach:ven_9", {"kind": "email"}) is False


async def test_it_keeps_documents_it_has_no_special_handling_for(tmp_path: Path) -> None:
    path = _snapshot(
        tmp_path / "db.json",
        {"missions/msn_1": {"id": "msn_1"}, "missions/msn_1/notes/deep/extra/doc": {"kept": True}},
    )
    store = SnapshotStore(path)
    await store.put("missions", "msn_1", {"id": "msn_1", "status": "completed"})

    saved = json.loads(path.read_text())["documents"]
    assert saved["missions/msn_1/notes/deep/extra/doc"] == {"kept": True}


async def test_an_absent_file_is_an_empty_database_rather_than_a_crash(tmp_path: Path) -> None:
    path = tmp_path / "not-created-yet.json"
    store = SnapshotStore(path)

    assert await store.query("missions") == []
    await store.put("missions", "msn_1", {"id": "msn_1"})
    assert path.exists()
    assert await SnapshotStore(path).get("missions", "msn_1") == {"id": "msn_1"}
