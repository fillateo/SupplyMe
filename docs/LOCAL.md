# Running it locally

Four ways in, cheapest first. Everything below has been run on a clean machine.

## 0. What you need

- Python 3.12 (3.13 works; 3.14 does not — `google-adk` has not caught up)
- Node 20+
- A Google Cloud project **only for options 3 and 4**

```bash
git clone <repo> && cd vendor-discovery

cd backend
uv venv --python 3.12 .venv                        # or: python3.12 -m venv .venv
VIRTUAL_ENV=.venv uv pip install -e ".[dev]"       # or: .venv/bin/pip install -e ".[dev]"
```

## 1. Run the tests — 10 seconds, no credentials, no network

```bash
cd backend
.venv/bin/python -m pytest -q
```

191 tests. They cover the whole workflow end to end, including every message
being delivered twice, a search outage, a failed call, a model timeout, a
mid-mission restart, and a supplier reply containing a prompt-injection payload.

## 2. Watch a whole mission in the terminal — 30 seconds, still no credentials

```bash
cd backend
.venv/bin/python scripts/run_demo.py
```

This runs a complete mission and prints what happened, all of it read back out
of storage: the activity timeline, the supply chain it derived, every supplier
with the provenance of each fact, the brand claims and how each was judged, the
conflict it found and how it settled it, the emails and the call transcript, and
the final ranked network.

Things worth looking for in the output:

- `PT Botol Prima Sejahtera -> Maison Verel: supplier_reported (0 independent source(s))`
  next to `PT Aroma Nusantara -> Maison Verel: verified (2 independent source(s))`.
  Same brand, two suppliers, different verdicts.
- `moq: 500.0 (official_website) vs 1000 (supplier_email) -> resolved via call`.
  The agent decided email would not settle it, because they had already answered
  in writing.
- `deduplicated: 21` in the counters, with exactly three emails sent. 30% of
  events are redelivered on purpose.

Useful flags:

```bash
--duplicate-rate 1.0    # deliver every event twice; still one email per supplier
--verbose               # every workflow event and agent run as it happens
--live-model            # use real Gemini instead (see option 4)
```

## 3. Run the console — no credentials either

Two terminals.

```bash
# terminal 1
cd backend
cp .env.example .env          # VDS_USE_SCRIPTED_MODEL=true is already set
.venv/bin/uvicorn app.api.main:app --port 8080

# terminal 2
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>, press **Start sourcing**, and watch the activity
column on the right fill in. Under the default `external` approval policy it
will stop and ask you before the first email to each supplier and before every
call — that pause is the point, and you can read the drafted email before
approving it.

Then:

- Click any number on a supplier card. Every figure on screen opens the sources
  behind it: the verbatim excerpt, the URL, and when it was retrieved.
- Open the supplier with the red **disagreement** badge to see both values side
  by side and what the system did about it.
- **Recommendation** tab → *How the score was reached* — every point is a
  weight times a fit, with the sentence that produced it.

Close the browser tab mid-mission and reopen it. The mission does not care.

Other things to poke at:

```
http://localhost:8080/docs                       interactive API
curl -s localhost:8080/api/health | jq           which providers are actually bound
```

## 4. Use real Gemini

```bash
gcloud auth application-default login

cd backend
# check what your project can actually reach first
.venv/bin/python scripts/check_models.py --project YOUR_PROJECT
```

Then in `.env`:

```
VDS_USE_SCRIPTED_MODEL=false
VDS_PROJECT_ID=your-project
```

and restart the API. `/api/health` will show `GeminiLLM`.

Everything else is identical — same agents, same events, same storage, same
scoring. What changes is that Gemini now writes the search queries, decides
which results are real suppliers, reads the pages, drafts the emails and reads
the replies, and the research stage becomes a Google ADK tool loop that chooses
what to read next.

Or, without touching `.env`:

```bash
.venv/bin/python scripts/run_demo.py --live-model --project YOUR_PROJECT
```

**Expect it to be slower**, and on a project with default quota, expect
rate limiting. A mission fans out over every supply-chain node at once and each
research branch makes several model calls. `VDS_MAX_CONCURRENT_RESEARCH=3`
bounds that; lower it to `1` if you see 429s in the log.

## Connecting the real integrations

Each one is independent, and any you skip degrades to its mock and says so at
`/api/health` — nothing silently pretends to have called an API it did not.

| Integration | To turn on |
| --- | --- |
| Google Places | `VDS_MAPS_API_KEY` |
| Programmable Search | `VDS_SEARCH_API_KEY` + `VDS_SEARCH_ENGINE_ID` (without it, Gemini search grounding is used) |
| YouTube | `VDS_YOUTUBE_API_KEY` |
| Gmail | `python scripts/gmail_auth.py --client-secret client_secret.json` |
| Telephony | `VDS_TWILIO_ACCOUNT_SID`, `VDS_TWILIO_AUTH_TOKEN`, `VDS_TWILIO_FROM_NUMBER` |

Gmail and telephony also need `VDS_MODE=live` and a publicly reachable
`VDS_PUBLIC_BASE_URL` for their webhooks — a tunnel is fine for local work.

**Sending real email and placing real calls reaches real businesses.** Keep
`VDS_APPROVAL_POLICY=external` (the default) or `strict` so nothing leaves
without you reading it first.

## If something goes wrong

**Console returns 500, log says `__webpack_modules__[moduleId] is not a function`.**
`npm run build` and `npm run dev` share `.next` and a production build run while
the dev server is up corrupts it. Stop the dev server, move `.next` aside, start
it again.

**`No model configured`.** Either set `VDS_USE_SCRIPTED_MODEL=true`, or set
`VDS_PROJECT_ID` and run `gcloud auth application-default login`.

**429 `RESOURCE_EXHAUSTED` in the API log.** Vertex quota. Lower
`VDS_MAX_CONCURRENT_RESEARCH`, or use `gemini-2.5-flash` for both tiers, or run
with the scripted model. Retries back off automatically and are deliberately
*not* compressed by `VDS_DEMO_SPEEDUP`.

**A mission sits in `awaiting_response` and does not finish.** It is waiting for
a supplier, which is correct. `VDS_DEMO_SPEEDUP=2000` turns the 48-hour
follow-up timer into about 86 seconds; without it you would wait 48 real hours.

**`pytest` fails on import with a `google-adk` error.** Check your Python is
3.12 or 3.13: `.venv/bin/python --version`.
