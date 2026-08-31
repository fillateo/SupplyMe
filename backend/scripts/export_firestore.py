"""Take a complete, restorable snapshot of the Firestore database.

Walks every collection and every subcollection rather than a hard-coded list,
because the collection set has changed twice already and a backup that only
holds what someone remembered to name is not a backup. Documents are keyed by
their full path (`missions/msn_x/workflow_events/evt_y`), which is what lets
`import_snapshot.py` put a mission's activity timeline back where it belongs.

Reads only. Nothing here writes to or deletes from the live database.

    python scripts/export_firestore.py [--out DIR]
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.cloud import firestore

from app.config import get_settings


def encode(value: Any) -> Any:
    """Make a Firestore value JSON-safe without losing what it was.

    The app writes documents with `model_dump(mode="json")`, so in practice
    everything here is already a primitive. The tagged forms exist for the
    values Firestore can hold that JSON cannot — a timestamp written by an
    older build, a byte string, a reference — so that a restore is a faithful
    copy rather than a copy of the parts that happened to be simple.
    """
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if isinstance(value, (datetime, date)):
        return {"__type__": "datetime", "value": value.isoformat()}
    if isinstance(value, bytes):
        return {"__type__": "bytes", "value": base64.b64encode(value).decode()}
    if isinstance(value, firestore.DocumentReference):
        return {"__type__": "reference", "value": value.path}
    if isinstance(value, firestore.GeoPoint):
        return {"__type__": "geopoint", "lat": value.latitude, "lng": value.longitude}
    return value


def walk(collection: Any, documents: dict[str, Any]) -> None:
    for snapshot in collection.stream():
        reference = snapshot.reference
        documents[reference.path] = encode(snapshot.to_dict() or {})
        for child in reference.collections():
            walk(child, documents)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(Path.home() / "supplyme-firestore-backups"),
        help="directory to write the snapshot into",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.project_id:
        print("SUPPLYME_PROJECT_ID is not set; nothing to export from", file=sys.stderr)
        return 1

    client = firestore.Client(project=settings.project_id, database=settings.firestore_database)
    documents: dict[str, Any] = {}
    for collection in client.collections():
        print(f"  reading {collection.id} ...", end="", flush=True)
        before = len(documents)
        walk(collection, documents)
        print(f" {len(documents) - before} documents")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = out_dir / f"firestore-snapshot-{stamp}.json"
    snapshot = {
        "meta": {
            "exported_at": datetime.now().astimezone().isoformat(),
            "project": settings.project_id,
            "database": settings.firestore_database,
            "document_count": len(documents),
        },
        "documents": documents,
    }
    snapshot_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True))

    top_level = sorted({p.split("/")[0] for p in documents})
    print(f"\n{len(documents)} documents across {len(top_level)} root collections")
    print(f"snapshot: {snapshot_path}  ({snapshot_path.stat().st_size / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
