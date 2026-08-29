# Running the demo

## The four-minute path

| Time | What to show | Where it comes from |
| --- | --- | --- |
| 0:00–0:20 | The friction, in one sentence: *"I want to start a perfume brand and I don't know who can actually make it."* | — |
| 0:20–0:40 | Paste the objective, press **Start sourcing**, close the tab | `POST /api/missions` |
| 0:40–1:10 | Reopen. Categories identified, discovery already running in parallel | Supply chain tab |
| 1:10–1:40 | A supplier claims a major brand. Open it: **supplier's word only, no independent source**. Open the other: **verified, brand's own site** | Suppliers tab → expand |
| 1:40–2:10 | The email it wrote, and what it personalised from | Approvals bar, "Read it first" |
| 2:10–2:45 | Reply arrives on its own. Quote extracted. **Sources differ on MOQ: 500 vs 1,000** | Activity feed, then the vendor's conflict panel |
| 2:45–3:15 | It decides email won't settle it — they already answered in writing — and calls. Transcript: *"500 for a pilot, at Rp 11,000."* | Communications tab |
| 3:15–3:40 | The supplier is re-scored. 84 → 95, because MOQ now fits | Recommendation tab → "How the score was reached" |
| 3:40–4:00 | Click any number on screen: excerpt, URL, retrieval time | Evidence drawer |

Closing line: *"I gave it one product idea. It built the sourcing workflow, checked the suppliers' claims against independent sources, contacted them, resolved a disagreement by phone, and produced the network."*

## Setup

```bash
cd backend
cp .env.example .env          # set VDS_PROJECT_ID
.venv/bin/uvicorn app.api.main:app --port 8080

cd ../frontend && npm run dev
```

Recommended `.env` for a recorded demo:

```
VDS_MODE=demo
VDS_APPROVAL_POLICY=external      # so the approval gate is visible
VDS_PROJECT_ID=your-project
VDS_DEMO_SPEEDUP=2000             # a 48h follow-up becomes ~86 seconds
VDS_DEMO_DUPLICATE_RATE=0.25      # a quarter of events delivered twice
```

`VDS_DEMO_DUPLICATE_RATE` is worth leaving on. It redelivers a quarter of all
events, and the mission still sends exactly one email per supplier — which is
the point of the idempotency work and is visible in the counters.

## Proof of action

Nothing in the console is animated. If a judge asks whether it is real:

```bash
# The stored event log the timeline renders from
curl -s localhost:8080/api/missions/$MID/activity | jq '.[-12:] | .[] | {type, status, emitted}'

# The structured logs, filtered to one mission
gcloud logging read 'jsonPayload.mission_id="'$MID'"' --limit 40

# Every claim with the source it came from
curl -s localhost:8080/api/missions/$MID/evidence | jq '.[] | {claim, source_type, source_url}'
```

And the whole thing without a browser, printing only stored state:

```bash
.venv/bin/python scripts/run_demo.py
```

## If a live model is unavailable

`scripts/run_demo.py` with no flags uses a scripted model and needs no
credentials or network. The workflow, the events, the storage and the scoring
are identical; only the text generation is deterministic. Say so if you use it.

## Demo data honesty

Demo mode uses synthetic suppliers under the reserved `example.com`, and
`/api/health` reports the substitution. No real business is described, quoted or
contacted, and no real brand is claimed as anyone's customer.
