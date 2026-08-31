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

What it cannot do is answer a new question. The supply chain on screen is the
recorded one whatever gets typed; all the objective decides is which of the
briefs in `scenarios.py` that supply chain is shown under — and one of them is
the recording's own, so asking for the fragrance mission gets the fragrance
mission, under the objective it really ran on. The mission says which recording
it came from either way.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.ids import new_id
from .scenarios import Scenario, as_dict
from .snapshot_store import decode

log = logging.getLogger(__name__)

_TIMELINE = "workflow_events"
#: Not mission data: a reservation ledger and the mailbox cursor. Replaying
#: either would claim actions this process never took.
_SKIP_COLLECTIONS = frozenset({"idempotency", "mail_state"})
_PREFIX_RE = re.compile(r"^([a-z]{2,6})_")
#: Vendor fields that are a `Fact` — a value plus where it came from. A scenario
#: supplier is built off a recorded one, so each of these has to be emptied or
#: the new supplier quietly inherits somebody else's minimum and lead time.
_FACT_FIELDS = (
    "moq",
    "unit_price",
    "lead_time_days",
    "sample_lead_time_days",
    "customization",
    "payment_terms",
)


def _unknown(fact: Any) -> dict[str, Any]:
    """The same fact, emptied — or a fresh empty one if the template had none.

    Always a dict, because the alternative is a supplier whose single sourced
    fact is dropped silently because the document it was built from happened not
    to carry that field.
    """
    base = fact if isinstance(fact, dict) else {}
    return {**base, "value": None, "provenance": "unknown", "evidence_ids": [], "confidence": 0.0}


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
        scenario: Scenario | None = None,
    ) -> None:
        self._recording = recording
        self._store = store
        self._duration = max(0.0, duration_seconds)
        self._max_gap = max(0.0, max_gap_seconds)
        self._scenario = scenario
        self._kept = self._vendors_kept()

    def for_scenario(self, scenario: Scenario | None) -> Replay:
        """A copy of this player bound to one brief.

        A new object rather than a mutated one, because replays overlap: two
        missions started ten seconds apart are two `play` coroutines running
        against the same recording, and a scenario set on a shared player would
        follow whichever was started last into both of them.
        """
        return Replay(
            self._recording,
            self._store,
            duration_seconds=self._duration,
            max_gap_seconds=self._max_gap,
            scenario=scenario,
        )

    # --- scenario -------------------------------------------------------------
    def _vendors_kept(self) -> set[str] | None:
        """Which recorded suppliers this brief carries, or None for all of them.

        A shorter roster is what makes two replays look like two missions rather
        than one mission twice: a different supplier count, a different number of
        emails sent, a different shortlist to rank.
        """
        limit = self._scenario.vendor_limit if self._scenario else None
        if limit is None:
            return None

        # Ranked by how much was found out about them, not by when they were
        # discovered. Taking the first N by timestamp dropped the suppliers the
        # recording actually investigated, and left a mission whose evidence tab
        # had six rows in it — a shorter shortlist should look researched, not
        # abandoned.
        weight: dict[str, int] = {}
        for path, document in self._recording.documents.items():
            if not path.startswith("vendors/"):
                continue
            weight[str(document.get("id"))] = 0
        for path, document in self._recording.documents.items():
            vendor_id = document.get("vendor_id")
            if isinstance(vendor_id, str) and vendor_id in weight:
                weight[vendor_id] += 3 if path.startswith("evidence/") else 5
        ranked = sorted(weight, key=lambda v: (-weight[v], v))

        # The shortlist the recommendation names comes first, whatever its
        # evidence weight. Dropping one of those leaves a closing panel that
        # recommends a supplier the Suppliers tab does not have — which reads as
        # a broken console, not as a shorter mission.
        named = self._recommended_vendors()

        # Geocoded suppliers are reserved next, for the same reason: weighting
        # them was not enough, because a supplier with ten pieces of evidence
        # outscores one with a map pin, and the candle brief came out with a
        # single marker on the map.
        located = {
            str(d.get("id"))
            for path, d in self._recording.documents.items()
            if path.startswith("vendors/")
            and d.get("lat") is not None
            and d.get("lng") is not None
        }
        kept = [v for v in ranked if v in named]
        kept += [v for v in ranked if v in located and v not in named]
        kept += [v for v in ranked if v not in named and v not in located]
        return set(kept[: max(limit, len(named))])

    def _recommended_vendors(self) -> set[str]:
        """Every supplier the recorded recommendation picked for a component."""
        named: set[str] = set()
        for path, document in self._recording.documents.items():
            if not path.startswith("recommendations/"):
                continue
            for entry in document.get("selections") or ():
                vendor = entry.get("vendor") if isinstance(entry, dict) else None
                if isinstance(vendor, dict) and isinstance(vendor.get("id"), str):
                    named.add(vendor["id"])
        return named

    def _dropped(self, document: dict[str, Any]) -> bool:
        """True for anything hanging off a supplier this brief does not carry."""
        if self._kept is None:
            return False
        vendor_id = document.get("vendor_id")
        if isinstance(vendor_id, str) and vendor_id not in self._kept:
            return True
        if document.get("id") in (self._kept or ()) or "vendor_id" in document:
            return False
        # Timeline events name the supplier in their payload.
        payload = document.get("payload")
        if isinstance(payload, dict):
            target = payload.get("vendor_id")
            if isinstance(target, str) and target.startswith("ven_") and target not in self._kept:
                return True
        return False

    def _node_keys(self) -> dict[str, str]:
        if not self._scenario:
            return {}
        return {old: skin.key for old, skin in self._scenario.nodes.items() if skin.key != old}

    def _skin_node(self, document: dict[str, Any]) -> dict[str, Any]:
        """Rename a supply-chain node into this scenario's vocabulary."""
        if not self._scenario:
            return document
        skin = self._scenario.nodes.get(str(document.get("key")))
        if skin is None:
            return document
        document = dict(document)
        document.update(
            {
                "key": skin.key,
                "name": skin.name,
                "description": skin.description,
                "aliases": list(skin.aliases),
                "search_terms": list(skin.search_terms),
            }
        )
        # The rationale explains a component that no longer exists under that
        # name. Dropping it beats leaving a paragraph about a perfume pump on a
        # candle wick.
        document["rationale"] = skin.description
        return document

    def _skin_terms(self, document: dict[str, Any]) -> dict[str, Any]:
        """Apply the scenario vocabulary to model-written product descriptions.

        Deliberately narrow. `customization.value` is a sentence a model wrote
        about what this supplier would make; an evidence excerpt, a source URL,
        an email body and a quoted price are somebody's actual words, and those
        are left exactly as recorded even when they give the recording away.
        """
        if not self._scenario or not self._scenario.terms:
            return document
        customization = document.get("customization")
        if not isinstance(customization, dict) or not isinstance(customization.get("value"), str):
            return document
        document = dict(document)
        document["customization"] = {
            **customization,
            "value": self._skin_prose(customization["value"]),
        }
        return document

    def _skin_prose(self, text: str) -> str:
        """Rewrite a model-written sentence into this scenario's vocabulary.

        The same category as a supply-chain node name: prose the model wrote
        *about the product*, not somebody's words about their own business. An
        evidence excerpt, a source URL, an email body and a quoted price never
        reach this method.

        Longest phrase first, because the maps overlap on purpose — "fragrance
        juice" has to be spent before "fragrance" gets to it, or the closing
        panel offers to source some skincare juice.
        """
        if not self._scenario or not self._scenario.terms:
            return text
        for before in sorted(self._scenario.terms, key=len, reverse=True):
            after = self._scenario.terms[before]
            text = text.replace(before, after)
            text = text.replace(before[:1].upper() + before[1:], after[:1].upper() + after[1:])
        return text

    def _kept_conflicts(self) -> set[str]:
        """Conflict ids that survive this brief's shorter supplier roster."""
        return {
            str(document.get("id"))
            for path, document in self._recording.documents.items()
            if path.startswith("conflicts/") and not self._dropped(document)
        }

    def _skin_recommendation(self, document: dict[str, Any]) -> dict[str, Any]:
        """Bring the closing panel into this scenario's brief.

        This is the beat the whole replay ends on — "three components filled,
        and here is what I could not establish" — and it was the one part still
        answering the question that was recorded rather than the one on screen:
        a shortlist of serum suppliers under a heading about a glass flacon.

        What changes is the vocabulary and the roster. What does not change is
        any number: a supplier's MOQ, a quoted price and the arithmetic that
        scored them are recorded facts, and the scenario quantity is set to the
        recorded one precisely so that none of them has to be touched here.
        """
        if not self._scenario:
            return document
        document = dict(document)

        for group in ("selections", "alternatives", "rejected"):
            entries = document.get(group)
            if not isinstance(entries, list):
                continue
            skinned: list[Any] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    skinned.append(entry)
                    continue
                vendor = entry.get("vendor")
                if (
                    self._kept is not None
                    and isinstance(vendor, dict)
                    and str(vendor.get("id")) not in self._kept
                ):
                    continue
                entry = dict(entry)
                skin = self._scenario.nodes.get(str(entry.get("node_key")))
                if skin is not None:
                    entry["node_name"] = skin.name
                if isinstance(entry.get("why"), list):
                    entry["why"] = [
                        self._skin_prose(w) if isinstance(w, str) else w for w in entry["why"]
                    ]
                skinned.append(entry)
            document[group] = skinned

        if isinstance(document.get("narrative"), str):
            document["narrative"] = self._skin_prose(document["narrative"])
        for field_name in ("risks", "next_actions", "unknowns"):
            values = document.get(field_name)
            if isinstance(values, list):
                document[field_name] = [
                    self._skin_prose(v) if isinstance(v, str) else v for v in values
                ]

        if isinstance(document.get("open_conflicts"), list):
            surviving = self._kept_conflicts()
            document["open_conflicts"] = [
                c for c in document["open_conflicts"] if str(c) in surviving
            ]

        selections = document.get("selections")
        if isinstance(selections, list):
            document["priced_selections"] = sum(
                1 for s in selections if isinstance(s, dict) and s.get("quote")
            )
        return document

    def _extra_vendors(self, mission_id: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """This scenario's own Los Angeles suppliers, with what their site says.

        Built by overwriting the identity fields of a recorded document rather
        than written out by hand, so these always carry whatever fields the
        current schema has.
        """
        if not self._scenario or not self._scenario.extra_vendors:
            return []
        vendor_template = next(
            (d for p, d in sorted(self._recording.documents.items()) if p.startswith("vendors/")),
            None,
        )
        evidence_template = next(
            (d for p, d in sorted(self._recording.documents.items()) if p.startswith("evidence/")),
            None,
        )
        if vendor_template is None or evidence_template is None:
            return []

        built: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for extra in self._scenario.extra_vendors:
            vendor_id = new_id("ven")
            evidence_id = new_id("ev")
            vendor = dict(vendor_template)
            vendor.update(
                {
                    "id": vendor_id,
                    "mission_id": mission_id,
                    "name": extra.name,
                    "legal_name": None,
                    "domain": extra.domain,
                    "website": f"https://{extra.domain}",
                    "email": extra.email,
                    "phone": None,
                    "city": extra.city,
                    "country": "USA",
                    "address": None,
                    "place_id": None,
                    "lat": None,
                    "lng": None,
                    "aliases": [],
                    "node_keys": list(extra.node_keys),
                    "capabilities": list(extra.capabilities),
                    # Found on their own website and left there: nobody wrote to
                    # them, so anything past "discovered" would be a stage this
                    # supplier never reached.
                    "status": "discovered",
                    "currency": None,
                    "evidence_ids": [evidence_id],
                    "brand_relationship_ids": [],
                    "open_conflicts": [],
                    "thread_ids": [],
                    "rejection_reasons": [],
                    "version": 0,
                }
            )
            for name in _FACT_FIELDS:
                vendor[name] = _unknown(vendor.get(name))
            # The one fact their page actually supports. `capabilities` and the
            # like are not facts, so they fall through to the list set above.
            if isinstance(vendor.get(extra.field_name), dict):
                vendor[extra.field_name] = {
                    **vendor[extra.field_name],
                    "value": extra.value or extra.claim,
                    "provenance": "publicly_listed",
                    "evidence_ids": [evidence_id],
                    "confidence": 0.7,
                }
            vendor["missing_fields"] = [
                name
                for name in ("unit_price", "moq", "lead_time_days")
                if not isinstance(vendor.get(name), dict)
                or vendor[name].get("value") is None
            ]

            evidence = dict(evidence_template)
            evidence.update(
                {
                    "id": evidence_id,
                    "mission_id": mission_id,
                    "vendor_id": vendor_id,
                    "field": extra.field_name,
                    "claim": extra.claim,
                    "value": extra.value or extra.claim,
                    "evidence_excerpt": extra.excerpt,
                    "source_url": extra.source_url,
                    "source_type": "official_website",
                    "source_title": extra.name,
                }
            )
            built.append((vendor, evidence))
        return built

    # --- id remapping -----------------------------------------------------
    def _mapping(self, mission_id: str) -> dict[str, str]:
        """Every recorded id to a fresh one, so a replay can be run twice.

        Ids are rewritten wherever they appear, not only in the fields known to
        hold them: a recommendation names vendors, a conflict names evidence,
        and an event's payload names whatever it was about. Missing one leaves a
        dangling reference the console renders as a blank.
        """
        mapping: dict[str, str] = {self._recording.mission_id: mission_id}
        mapping.update(self._node_keys())

        # Every recorded id gets a fresh one — no pattern is consulted to decide
        # which ids "look like" ids. An id that fails to be remapped is not a
        # cosmetic problem: the replay then writes that document back at its
        # recorded path, overwriting the recording with a copy that belongs to
        # another mission. That happened, silently, to `ev_...` and the longer
        # `evt_...` ids, because the pattern in use required a three-letter
        # prefix and a suffix of at most twenty characters.
        recorded_ids = [
            str(document.get("id") or path.split("/")[-1])
            for path, document in self._recording.documents.items()
        ] + [str(event.get("id")) for event in self._recording.events if event.get("id")]

        for old in recorded_ids:
            if not old or old in mapping:
                continue
            prefix = _PREFIX_RE.match(old)
            mapping[old] = new_id(prefix.group(1) if prefix else "doc")
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
            if collection == "vendors" and self._kept is not None:
                if str(document.get("id")) not in self._kept:
                    continue
            elif self._dropped(document):
                continue
            skinned = document
            if collection == "supply_chain_nodes":
                skinned = self._skin_node(skinned)
            elif collection == "vendors":
                skinned = self._skin_terms(skinned)
            elif collection == "recommendations":
                skinned = self._skin_recommendation(skinned)
            entries.append((when, collection, self._rewrite(skinned, pattern, mapping)))

        for event in self._recording.events:
            when = _parse(event.get("created_at"))
            if when is None or self._dropped(event):
                continue
            entries.append((when, _TIMELINE, self._rewrite(event, pattern, mapping)))

        for vendor, evidence in self._extra_vendors(mapping[self._recording.mission_id]):
            when = _parse(vendor.get("created_at"))
            if when is None:
                continue
            entries.append((when, "vendors", vendor))
            entries.append((when, "evidence", evidence))

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
        if self._scenario:
            recorded.update(as_dict(self._scenario))
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
                    doc_id = str(payload.get("id"))
                    if f"{kind}/{doc_id}" in self._recording.documents:
                        # Refuse rather than overwrite. Against the file store the
                        # recording *is* the local database, so a collision here
                        # would eat the very mission being replayed.
                        log.error(
                            "replay would have overwritten the recording at %s/%s; skipping",
                            kind, doc_id,
                        )
                        continue
                    await self._store.put(kind, doc_id, payload)
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
        if self._scenario:
            final.update(as_dict(self._scenario))
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
