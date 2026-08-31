"""Install a Firestore snapshot as the local database.

The snapshot format and the local store format are the same thing, so this is
mostly a copy — what it adds is a check that the file is a snapshot before it
overwrites a database, and a summary of what was installed, because a restore
that silently produced an empty console would be worse than one that failed.

    python scripts/restore_local_db.py                          # newest snapshot
    python scripts/restore_local_db.py --from path/to/snap.json
    python scripts/restore_local_db.py --merge                  # keep what is there

Without `--merge` the destination is replaced, and the file it replaced is kept
alongside it with a `.replaced-<timestamp>` suffix rather than removed.
"""

from __future__ import annotations

import argparse
import collections
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_BACKUPS = Path.home() / "supplyme-firestore-backups"
DEFAULT_TARGET = Path(__file__).resolve().parents[1] / "local-db.json"


def newest_snapshot(directory: Path) -> Path | None:
    candidates = sorted(directory.glob("firestore-snapshot-*.json"))
    return candidates[-1] if candidates else None


def summarize(documents: dict[str, object]) -> str:
    counts: collections.Counter[str] = collections.Counter()
    for path in documents:
        parts = path.split("/")
        counts["/".join(parts[::2]) if len(parts) > 2 else parts[0]] += 1
    widest = max((len(k) for k in counts), default=0)
    return "\n".join(f"  {name:<{widest}}  {n}" for name, n in sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", default="", help="snapshot to restore")
    parser.add_argument("--to", dest="target", default=str(DEFAULT_TARGET))
    parser.add_argument("--merge", action="store_true", help="add to the existing database")
    args = parser.parse_args()

    source = Path(args.source) if args.source else newest_snapshot(DEFAULT_BACKUPS)
    if source is None:
        print(f"no snapshot found in {DEFAULT_BACKUPS}", file=sys.stderr)
        print("run: python scripts/export_firestore.py", file=sys.stderr)
        return 1
    if not source.exists():
        print(f"{source} does not exist", file=sys.stderr)
        return 1

    payload = json.loads(source.read_text())
    documents = payload.get("documents")
    if not isinstance(documents, dict):
        print(f"{source} is not a snapshot: no `documents` map", file=sys.stderr)
        return 1

    target = Path(args.target)
    if args.merge and target.exists():
        existing = json.loads(target.read_text()).get("documents") or {}
        documents = {**existing, **documents}
        payload["documents"] = documents
    elif target.exists():
        kept = target.with_suffix(f".replaced-{datetime.now():%Y%m%d-%H%M%S}.json")
        shutil.copy2(target, kept)
        print(f"previous database kept at {kept.name}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))

    print(f"restored {source.name} -> {target}")
    print(summarize(documents))
    print(f"\nSet SUPPLYME_LOCAL_STORE_PATH={target} in backend/.env, then ./run.sh dev")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
