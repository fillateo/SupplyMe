# Architecture

Only components that exist are drawn here.

## Request and event paths

```
                 ┌──────────────────────────────────────────────┐
   browser ────► │ Next.js console — its own Cloud Run service   │
                 │  proxies /api/* server-side — no credential   │
                 │  ever reaches client JavaScript               │
                 │  holds run.invoker on the API, nothing else   │
                 └───────────────────┬──────────────────────────┘
                                     │ HTTPS, as itself
                 ┌───────────────────▼──────────────────────────┐
                 │ FastAPI — a separate Cloud Run service        │
                 │  /api/*            console reads + decisions  │
                 │  /events/pubsub    Pub/Sub push               │
                 │  /events/task      Cloud Tasks                │
                 │  /webhooks/gmail   Gmail watch notification   │
                 └───────────────────┬──────────────────────────┘
                                     │
                 ┌───────────────────▼──────────────────────────┐
                 │ Orchestrator (app/workflow/orchestrator.py)   │
                 │  claim dedup key → run handler → emit next    │
                 │  lease, bounded retry, drop unprocessable     │
                 └───┬─────────────────────────────┬────────────┘
                     │                             │
        ┌────────────▼───────────┐     ┌───────────▼─────────────┐
        │ Agents (Gemini/Vertex) │     │ Deterministic engines   │
        │ mission, supply chain, │     │ evidence, identity,     │
        │ discovery, research,   │     │ quotes, conflicts,      │
        │ brand, comms, recomm.  │     │ trust, scoring, numbers │
        └────────────┬───────────┘     └───────────┬─────────────┘
                     │                             │
        ┌────────────▼─────────────────────────────▼─────────────┐
        │ Ports (app/ports/base.py)                               │
        │  Search   Maps   Mail   Store   Bus   Scheduler          │
        └────────────────────────┬────────────────────────────────┘
                                 │
        ┌────────────────────────▼────────────────────────────────┐
        │ Adapters — every one of them the real service            │
        │  Programmable Search or Gemini grounding · Places ·      │
        │  SMTP out and IMAP in (or the Gmail API)                 │
        │                                                         │
        │  A missing credential is a startup failure, not a        │
        │  fallback. The test doubles live in tests/ and are       │
        │  reachable from nowhere in app/.                         │
        └────────────────────────┬────────────────────────────────┘
                                 ▼
                    Firestore · Pub/Sub · Cloud Tasks · Cloud Logging
```

## Why the orchestrator owns durability

Handlers are deliberately naive: read state, do work, return the events that
should happen next. Everything that makes the workflow survive production lives
one level up, so no handler can forget it:

| Concern | Mechanism |
| --- | --- |
| Redelivery | `store.reserve("evt:" + event.key)` before any work |
| Worker died mid-handler | Reservations are leases; an expired lease is taken over |
| Transient failure | Bounded retry with exponential backoff, then mission failure |
| Unprocessable event | `MissionNotFound` / `VendorNotFound` are dropped, never retried |
| Nothing found at all | Discovery coming back empty is an answer: `_maybe_finish` still emits a recommendation once every branch is in, so a mission cannot sit in `discovering` forever |
| Irreversible action | A second reservation keyed on `mission+vendor+action+version` |
| Concurrent writers | `store.mutate` — a Firestore transaction, an asyncio lock in memory |
| Clients outliving the process | `Runtime.stop` closes the search, Places and Firestore clients it opened |

## The dedup key

```python
Event.key = sha256(mission_id, type, canonical_json(payload))
```

Derived from the entire payload, not a chosen subset. An earlier version keyed
on a fixed list of id fields and silently collapsed distinct events that carried
none of them — three different supplier replies became one, and every
`vendor.updated` after the first was discarded as a duplicate. Hashing the whole
payload makes a new logical event a new key by construction; only a true
redelivery, which carries a byte-identical payload, collides.

This is why every emitter that can fire twice for the same vendor passes a
discriminator: `version=vendor.version`, `version=quote.id`,
`version=f"{thread.id}:followup:{n}"`.

## Events

| Event | Emitted by | Does |
| --- | --- | --- |
| `mission.created` | API | Reads the objective, sets scoring weights |
| `requirements.created` | mission | Decomposes into supply-chain nodes |
| `supply_chain.planned` | supply chain | Fans out one discovery branch per node |
| `supplier.discovery.started` | fan-out | Search + Places, identity resolution |
| `vendor.discovered` | discovery | Starts research on a new vendor |
| `vendor.research.started` | discovery | Reads sources, finds a contact route, records evidence, applies facts |
| `evidence.found` | research | Timeline marker |
| `brand.claim.found` | research | Investigates a claimed customer |
| `brand.claim.adjudicated` | brand evidence | Classification recorded |
| `vendor.updated` | many | **The routing decision** |
| `vendor.qualified` / `vendor.rejected` | routing | Terminal for that vendor |
| `vendor.contact.required` | routing | Drafts an email |
| `email.draft.created` | comms | Timeline marker |
| `approval.requested` | comms | Pauses; stores the event to replay |
| `approval.granted` / `approval.denied` | API | Replays or cancels the paused event |
| `email.sent` | routing | **External action** — reserved before sending |
| `email.received` | IMAP poll or Gmail push | Extracts the quote, re-derives facts |
| `quote.extracted` | comms | Timeline marker |
| `conflict.detected` | evidence engine | Routes to a targeted follow-up |
| `followup.required` | conflict / timer | Asks only what is still missing |
| `recommendation.ready` | completion check | Scores everything, writes the report |
| `mission.completed` / `mission.failed` | terminal | Sets the status; `mission.failed` carries the reason |

## Firestore collections

`missions` · `supply_chain_nodes` · `vendors` · `evidence` ·
`brand_relationships` · `email_threads` · `quotes` · `conflicts` ·
`approvals` · `recommendations` · `agent_runs` · `idempotency` ·
`mail_state` (one document: the IMAP/Gmail cursor)

There are no migrations. A document written by an older build is read back by
whatever schema is current, so `Repo.load`/`Repo.list` skip a record they cannot
parse and log it rather than raising — one unparseable document used to 500
every read of its collection.

Plus `missions/{id}/workflow_events` — the activity timeline, written on every
handler start, success, retry, drop and exhaustion. This subcollection is the
proof of action: the console renders it directly and nothing else.

## Where the LLM is and is not

**Is:** reading the objective, decomposing the product, writing search queries,
deciding which results are real suppliers, extracting claims from pages,
judging whether a source supports a brand relationship, drafting emails,
extracting quotes from messy replies, deciding what a follow-up still needs to
ask, writing the final narrative.

**Which model:** resolved once per process from the ladder in `app/config.py`,
or pinned by `SUPPLYME_REASONING_MODEL` / `SUPPLYME_FAST_MODEL` — the live
deployment pins both. `GET /api/health` reports what each tier resolved to,
which backend served it, and the ladder that produced it, because the adapter
class is `GeminiLLM` whichever generation answered.

**Chooses its own path in exactly one place:** vendor research, which runs as a
Google ADK `LlmAgent` with `search_web`, `read_page` and `query_maps`.
Every tool call passes through `before_tool_callback`, which
calls `policy.check("research", ...)` — so the allowlist is enforced at runtime,
and the agent that reads attacker-controlled pages provably holds nothing that
can email or spend.

**Also not:** deciding which price rung applies. A supplier quotes a ladder and
each reply becomes its own `Quote`, so a vendor accumulates rungs;
`quotes.comparable_set` excludes any whose stated quantity exceeds what is being
bought. Without that, the mission settles a minimum down to a 500-unit pilot and
then scores the supplier on the 1,000-unit price — doing the whole job of finding
out what the buyer can have, and ranking the answer it was refused.

**Is not:** deciding what a claim is worth, deciding whether sources conflict,
deciding what to do about a conflict, computing confidence, computing scores,
ranking vendors, deciding whether to write to a supplier, deciding when a
mission is done — or finding a supplier's email address. All of that is deterministic and
unit-tested; see `app/domain/`.

That last one earns its place there by experience. A supplier the system cannot
write to drops out of the mission whatever else is known about it, and a live
run rejected every manufacturer it found for "no email or phone found" —
contact details are rarely in a search snippet and usually on a page called
`/contact` that nothing links to. `app/domain/contacts.py` opens the supplier's
own pages and reads the address off them. Pattern matching is cheaper and more
reliable here than a model call, and it cannot invent an address that almost
looks right.

The recommendation agent receives a ranking that is already computed and is told
it may not reorder it. If it could, the scores would be decoration.
