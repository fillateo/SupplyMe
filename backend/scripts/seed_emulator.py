"""Load a Firestore snapshot into a running Firestore emulator.

The emulator starts empty and has no import flag, so seeding it is a write
through the ordinary client — which is the point: the documents land through
the same library the deployment uses, at the same paths, subcollections
included, so what the console then reads is not a reconstruction of the live
database but a copy of it.

**This refuses to run unless `FIRESTORE_EMULATOR_HOST` is set.** Without that
variable the Firestore client talks to Google, and a seeding script that could
be pointed at the production database by forgetting one export is not a tool,
it is an accident waiting for a bad evening.

    python scripts/seed_emulator.py                     # newest snapshot
    python scripts/seed_emulator.py --from path/to.json
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.cloud import firestore

from app.adapters.snapshot_store import decode
from app.config import get_settings

DEFAULT_BACKUPS = Path.home() / "supplyme-firestore-backups"
_BATCH_LIMIT = 500


def newest_snapshot(directory: Path) -> Path | None:
    candidates = sorted(directory.glob("firestore-snapshot-*.json"))
    return candidates[-1] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from", dest="source", default="", help="snapshot file, or a directory of them"
    )
    args = parser.parse_args()

    settings = get_settings()
    host = settings.firestore_emulator_host or os.environ.get("FIRESTORE_EMULATOR_HOST", "")
    if not host:
        print(
            "FIRESTORE_EMULATOR_HOST is not set, so this would write to the real "
            "Firestore. Start the emulator first:\n\n"
            "    ./run.sh emulator\n\n"
            "or set SUPPLYME_FIRESTORE_EMULATOR_HOST in backend/.env.",
            file=sys.stderr,
        )
        return 2
    # Belt and braces: the client reads the unprefixed name, and `settings` may
    # have come from the prefixed one.
    os.environ["FIRESTORE_EMULATOR_HOST"] = host

    explicit = bool(args.source)
    source = Path(args.source) if explicit else DEFAULT_BACKUPS
    if source.is_dir():
        # A directory is how the container gets one: the backups directory is
        # mounted in, and which file is newest is decided here rather than in
        # a compose file that cannot look.
        directory, source = source, newest_snapshot(source)
        if source is None:
            # Not an error. `docker compose up` runs this before the API, and a
            # clone with no backups yet should still come up — with an empty
            # database and a sentence saying so, rather than a failed start.
            print(f"no snapshot in {directory}: leaving the emulator empty")
            print("to fill it: python scripts/export_firestore.py, then run this again")
            return 0
    if not source.is_file():
        print(f"{source} does not exist", file=sys.stderr)
        return 1

    documents = json.loads(source.read_text()).get("documents")
    if not isinstance(documents, dict):
        print(f"{source} is not a snapshot: no `documents` map", file=sys.stderr)
        return 1

    project = settings.project_id or "supplyme-local"
    client = firestore.Client(project=project, database=settings.firestore_database)

    written = 0
    batch = client.batch()
    pending = 0
    for path, raw in documents.items():
        batch.set(client.document(path), decode(raw))
        pending += 1
        written += 1
        if pending == _BATCH_LIMIT:
            batch.commit()
            batch, pending = client.batch(), 0
    if pending:
        batch.commit()

    counts: collections.Counter[str] = collections.Counter()
    for collection in client.collections():
        counts[collection.id] = sum(1 for _ in collection.stream())

    print(f"seeded {written} documents from {source.name} into the emulator at {host}")
    print(f"project {project}, database {settings.firestore_database}")
    for name, n in sorted(counts.items()):
        print(f"  {name:<20} {n}")
    print("\nroot collections read back above; subcollections went in with their parents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
