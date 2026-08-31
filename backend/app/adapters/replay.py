"""Replaying a mission that really ran.

What `SUPPLYME_MOCK=true` does instead of running the workflow. A demo needs to
show a mission filling in — suppliers appearing, evidence landing, emails going
out, a recommendation at the end — and doing that live costs a model bill, a
mailbox and an hour of wall clock, none of which a room full of people will
wait for.

The alternative usually taken is a fixture world: invented suppliers, invented
quotes. This codebase deleted that once already, for a good reason ("There is no
simulated mode"), and it is not coming back. **This plays back a recording.**
Every supplier, price, excerpt and source URL on screen is one that a real
mission produced against the live web; the only thing this adds is the clock.

How it works: a snapshot — the same file `scripts/export_firestore.py` writes —
holds a mission, its documents, and its `workflow_events` timeline, each stamped
with when it was written. The whole run is replayed onto a compressed clock, in
the original order, under a fresh mission id. Nothing is generated, and no
provider is called; in mock mode there is none bound to call.

What it cannot do is answer a new question. A replay of a fragrance mission is a
fragrance mission whatever objective was typed, and the mission says so.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.ids import new_id
from .snapshot_store import decode

log = logging.getLogger(__name__)

_TIMELINE = "workflow_events"
#: Not mission data: a reservation ledger and the mailbox cursor. Replaying
#: either would claim actions this process never took.
_SKIP_COLLECTIONS = frozenset({"idempotency", "mail_state"})
_ID_RE = re.compile(r"^[a-z]{3,4}_[0-9a-f]{16,20}$")


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class Recording:
    """One mission's documents and timeline, lifted out of a snapshot."""

    def __init__(self, mission_id: str, documents: dict[str, Any], events: list[Any]) -> None:
        self.mission_id = mission_id
        self.documents = documents
        self.events = events

    @property
    def objective(self) -> str:
        return str(self.documents.get(f"missions/{self.mission_id}", {}).get("objective", ""))

    @classmethod
    def load(cls, path: str | Path) -> Recording | None:
        """Read the richest mission in a snapshot, or None if there is not one.

        Richest by timeline length: a snapshot may hold several missions, and
        the one worth showing is the one that got furthest.
        """
        import json

        source = Path(path)
        if not source.is_file():
            log.warning("no recording at %s", source)
            return None
        try:
            payload = json.loads(source.read_text())
        except (OSError, ValueError):
            log.exception("could not read the recording at %s", source)
            return None

        raw = payload.get("documents")
        if not isinstance(raw, dict):
            log.warning("%s is not a snapshot: no documents map", source)
            return None

        timelines: dict[str, list[Any]] = {}
        for doc_path, document in raw.items():
            parts = doc_path.split("/")
            if len(parts) == 4 and parts[0] == "missions" and parts[2] == _TIMELINE:
                timelines.setdefault(parts[1], []).append(decode(document))
        if not timelines:
            log.warning("%s holds no mission timeline to replay", source)
            return None

        mission_id = max(timelines, key=lambda m: len(timelines[m]))
        events = sorted(timelines[mission_id], key=lambda e: str(e.get("created_at") or ""))

        documents: dict[str, Any] = {}
        for doc_path, document in raw.items():
            parts = doc_path.split("/")
            if len(parts) != 2 or parts[0] in _SKIP_COLLECTIONS:
                continue
            data = decode(document)
            belongs = (
                doc_path == f"missions/{mission_id}"
                or data.get("mission_id") == mission_id
            )
            if belongs:
                documents[doc_path] = data

        log.info(
            "recording %s: %d documents, %d timeline events",
            mission_id, len(documents), len(events),
        )
        return cls(mission_id, documents, events)


class Replay:
    """Writes a recording back out under a new mission id, on a shorter clock."""

    def __init__(
        self,
        recording: Recording,
        store: Any,
        *,
        duration_seconds: float = 90.0,
        max_gap_seconds: float = 3.0,
    ) -> None:
        self._recording = recording
        self._store = store
        self._duration = max(0.0, duration_seconds)
        self._max_gap = max(0.0, max_gap_seconds)

    # --- id remapping -----------------------------------------------------
    def _mapping(self, mission_id: str) -> dict[str, str]:
        """Every recorded id to a fresh one, so a replay can be run twice.

        Ids are rewritten wherever they appear, not only in the fields known to
        hold them: a recommendation names vendors, a conflict names evidence,
        and an event's payload names whatever it was about. Missing one leaves a
        dangling reference the console renders as a blank.
        """
        mapping = {self._recording.mission_id: mission_id}
        for path, document in self._recording.documents.items():
            old = document.get("id") or path.split("/")[-1]
            if old and old != self._recording.mission_id and _ID_RE.match(str(old)):
                mapping[str(old)] = new_id(str(old).split("_")[0])
        for event in self._recording.events:
            old = event.get("id")
            if old and _ID_RE.match(str(old)):
                mapping[str(old)] = new_id(str(old).split("_")[0])
        return mapping

    @staticmethod
    def _rewrite(value: Any, pattern: re.Pattern[str], mapping: dict[str, str]) -> Any:
        if isinstance(value, dict):
            return {k: Replay._rewrite(v, pattern, mapping) for k, v in value.items()}
        if isinstance(value, list):
            return [Replay._rewrite(v, pattern, mapping) for v in value]
        if isinstance(value, str):
            return pattern.sub(lambda m: mapping[m.group(0)], value)
        return value

    # --- the schedule -----------------------------------------------------
    def _schedule(self, mapping: dict[str, str]) -> list[tuple[float, str, Any]]:
        """(offset, kind, payload), ordered as the original run produced them.

        Offsets come from the recording's own timestamps, scaled so the whole
        run lands inside `duration_seconds`. Order is therefore the real order,
        including the parts that overlapped.
        """
        pattern = re.compile("|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))
        entries: list[tuple[datetime, str, Any]] = []

        for path, document in self._recording.documents.items():
            collection = path.split("/")[0]
            if collection == "missions":
                continue  # written first and last, not on the clock
            when = _parse(document.get("created_at"))
            if when is None:
                continue
            entries.append((when, collection, self._rewrite(document, pattern, mapping)))

        for event in self._recording.events:
            when = _parse(event.get("created_at"))
            if when is None:
                continue
            entries.append((when, _TIMELINE, self._rewrite(event, pattern, mapping)))

        if not entries:
            return []
        entries.sort(key=lambda e: e[0])
        first, last = entries[0][0], entries[-1][0]
        span = (last - first).total_seconds() or 1.0
        scaled = [
            ((when - first).total_seconds() / span * self._duration, kind, payload)
            for when, kind, payload in entries
        ]

        # Close the silences. Most of a real mission is waiting for a human in
        # another timezone, and played back proportionally that is a minute of a
        # still screen in the middle of the demo. Only the gaps shrink: the
        # order is untouched and so is the pacing of everything that happened.
        if not self._max_gap:
            return scaled
        played: list[tuple[float, str, Any]] = []
        shift = 0.0
        previous = 0.0
        for offset, kind, payload in scaled:
            gap = offset - previous
            if gap > self._max_gap:
                shift += gap - self._max_gap
            previous = offset
            played.append((offset - shift, kind, payload))
        return played

    # --- playing ----------------------------------------------------------
    def opening_mission(self, mission_id: str, *, user_id: str) -> dict[str, Any]:
        """The mission document as it stood when the recorded run began.

        The counters are reset rather than carried over, because they were zero
        at this point in the run that is being replayed. Everything else is the
        recorded mission: this is a playback, so the objective on screen is the
        one that was actually worked on.
        """
        recorded = dict(self._recording.documents.get(f"missions/{self._recording.mission_id}", {}))
        recorded.update(
            {
                "id": mission_id,
                "user_id": user_id,
                # `planning` rather than `created`: the recording holds one
                # version of the mission document — its last — so a replay has
                # no status history to play back, and the console would sit on
                # "created" for the whole run before jumping to "completed".
                # Planning is the state a real mission is in at this point.
                "status": "planning",
                "emails_sent": 0,
                "vendors_admitted": 0,
                "model_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_usd": 0.0,
                "failure_reason": None,
                "replay_of": self._recording.mission_id,
            }
        )
        return recorded

    async def play(self, mission_id: str, *, user_id: str = "demo-user") -> None:
        mapping = self._mapping(mission_id)
        pattern = re.compile("|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))
        schedule = self._schedule(mapping)

        started = asyncio.get_running_loop().time()
        for offset, kind, payload in schedule:
            delay = offset - (asyncio.get_running_loop().time() - started)
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                if kind == _TIMELINE:
                    await self._store.append_event(mission_id, payload)
                else:
                    await self._store.put(kind, str(payload.get("id")), payload)
            except Exception:
                # One document failing is not a reason to abandon the demo.
                log.exception("replay could not write a %s document", kind)

        final = self._rewrite(
            dict(self._recording.documents.get(f"missions/{self._recording.mission_id}", {})),
            pattern,
            mapping,
        )
        final.update(
            {"id": mission_id, "user_id": user_id, "replay_of": self._recording.mission_id}
        )
        await self._store.put("missions", mission_id, final)
        log.info("replay of %s finished as %s", self._recording.mission_id, mission_id)


def find_recording(settings: Any) -> Path | None:
    """Where to read a recording from, most specific first."""
    candidates: list[Path] = []
    if settings.mock_recording:
        candidates.append(Path(settings.mock_recording))
    if settings.local_store_path:
        candidates.append(Path(settings.local_store_path))
    candidates.append(Path("local-db.json"))
    candidates.append(Path.home() / "supplyme-firestore-backups")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
        if candidate.is_dir():
            # A directory is how a container is given one: the backups are
            # mounted in, and which file is newest is decided here.
            newest = sorted(candidate.glob("firestore-snapshot-*.json"), reverse=True)
            if newest:
                return newest[0]
    return None
