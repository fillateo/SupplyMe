# Running it locally

## The short version

```bash
./run.sh
```

That installs anything missing, checks your credentials, starts the API and the
console, and prints the URLs.

```
./run.sh            start the API and the console
./run.sh mission    one whole mission in the terminal, no servers
./run.sh test       the test suite
./run.sh mail       read the mailbox now instead of waiting for the poll
./run.sh status     what is running, and what it has spent
./run.sh stop
./run.sh clean      remove build caches; never touches source or .env
```

**There is no offline mode.** Every provider is the real service or the process
refuses to start and names the variable that is missing, so a mission either
read the live web and wrote to a real mailbox or it never began. Filling in
`backend/.env` is the first step, not an optional one.

The one safety valve is `SUPPLYME_MAIL_REDIRECT_TO`: set it to a mailbox you own and
every outbound message goes there instead of to the supplier, with a banner
saying who it would have reached. Leave it set unless you have decided, on
purpose, to write to real businesses.

The rest of this page is what those commands do, and what to look at.

---

## 0. What you need

- Python 3.12 (3.13 works; 3.14 does not — `google-adk` has not caught up)
- Node 20+
- A Google Cloud project, for everything except option 1

```bash
git clone https://github.com/fillateo/SupplyMe.git && cd SupplyMe

cd backend
uv venv --python 3.12 .venv                        # or: python3.12 -m venv .venv
VIRTUAL_ENV=.venv uv pip install -e ".[dev]"       # or: .venv/bin/pip install -e ".[dev]"
```

## 1. Run the tests — under a minute, no credentials, no network

```bash
cd backend
.venv/bin/python -m pytest -q
```

383 tests, about 58 seconds. They cover the whole workflow end to end,
including every message being delivered twice, a search outage, a model
timeout, a mid-mission restart, and a supplier reply containing a
prompt-injection payload.

## 2. Watch a whole mission in the terminal

```bash
cd backend
.venv/bin/python scripts/run_mission.py --project YOUR_PROJECT
```

This reads the live web, so it takes minutes rather than seconds — it is bounded
by the slowest supplier site the research agent decides to open. It prints a
progress line as it goes.

This runs a complete mission and prints what happened, all of it read back out
of storage: the activity timeline, the supply chain it derived, every supplier
with the provenance of each fact, the brand claims and how each was judged, the
conflict it found and how it settled it, the emails and supplier replies, and
the final ranked network.

Things worth looking for in the output:

- Two suppliers claiming the same brand, reported differently — one
  `verified (2 independent source(s))`, the other `supplier_reported
  (0 independent source(s))`.
- A `moq` line showing what the website said against what the email said, and
  which one the follow-up settled it on.
- The `orchestrator counters` line at the end, which is the real event tally.

Its only flags are `--project`, `--objective` and `--verbose`. Redelivery is not
one of them: this runs against a bus with duplication off, because it is a real
mission and duplicating real emails is not a demonstration. The redelivery
behaviour is asserted in the suite instead, at a 100% duplicate rate —
`tests/test_resilience.py::TestIdempotency`.

## 3. Run the console

Needs the same credentials as everything else — there is no offline mode. Two
terminals.

```bash
# terminal 1
cd backend
cp .env.example .env          # then fill in the required credentials
.venv/bin/uvicorn app.api.main:app --port 8080

# terminal 2
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>, press **Start sourcing**, and watch the activity
column on the right fill in. Under the default `autonomous` policy the agent
emails suppliers itself, with no pause for approval — `SUPPLYME_MAIL_REDIRECT_TO`
is what bounds that, not a human. Set `SUPPLYME_APPROVAL_POLICY=external` if you
would rather the first email to each supplier wait for you to read and approve it.

Then:

- Click any number on a supplier card. Every figure on screen opens the sources
  behind it: the verbatim excerpt, the URL, and when it was retrieved.
- Open the supplier with the red **disagreement** badge to see both values side
  by side and what the system did about it.
- **Recommendation** tab → *How the score was reached* — every point is a
  weight times a fit, with the sentence that produced it.
- **Supply chain** tab — what the planner decided the product is made of, and how
  far each component's candidates have got.

Close the browser tab mid-mission and reopen it. The mission does not care.

Other things to poke at:

```
http://localhost:8080/docs                       interactive API
curl -s localhost:8080/api/health | jq           which providers are actually bound
```

## 3b. The one switch left

| Switch | Chooses |
| --- | --- |
| `SUPPLYME_USE_CLOUD_INFRA` | in-process store, bus and scheduler vs Firestore, Pub/Sub, Cloud Tasks |

Locally you usually want it off: real Gemini and the real Google APIs against
in-process state, because provisioning Firestore just to try the thing out is a
tax on curiosity. Missions then do not survive a restart, and `/api/health` says
so. Terraform sets it on Cloud Run.

There used to be two more switches here — one for a scripted model and one for
mock integrations. Both are gone. What they bought was a demonstration that
looked exactly like the real thing while proving nothing about it.

## 4. Use real Gemini

```bash
gcloud auth application-default login

cd backend
# check what your project can actually reach, and from where
.venv/bin/python scripts/check_models.py --project YOUR_PROJECT --location global
```

Do run that first. Reachability is a property of the project *and* the
location, not of the model name: on the project this was built against,
`gemini-3.5-flash` answers from `global` and returns 404 from `us-central1`,
while `gemini-2.5-pro` does the opposite. The 404 does not mention that the
model exists at another endpoint, so this is an easy hour to lose.

Then in `.env`:

```
SUPPLYME_PROJECT_ID=your-project
SUPPLYME_VERTEX_LOCATION=global
```

Two location settings, because no single value works for both.
`SUPPLYME_VERTEX_LOCATION` is where the model is served from. `SUPPLYME_LOCATION` is
where the service's own Google Cloud dependencies live, and Cloud Tasks rejects
`global` as an invalid location — which is how a deployment that resolved
Gemini perfectly still failed its startup probe.

and restart the API. `/api/health` will show `GeminiLLM`.

Gemini writes the search queries, decides which results are real suppliers,
reads the pages, drafts the emails and reads the replies, and the research stage
is a Google ADK tool loop that chooses what to read next.

**Expect it to be slow**, and on a project with default quota, expect
rate limiting. A mission fans out over every supply-chain node at once and each
research branch makes several model calls. `SUPPLYME_MAX_CONCURRENT_RESEARCH=3`
bounds that; lower it to `1` if you see 429s in the log.

## Connecting the real integrations

| Integration | To turn on | Skippable |
| --- | --- | --- |
| Google Places | `SUPPLYME_MAPS_API_KEY` | no — the process will not start |
| Mailbox | `SUPPLYME_SMTP_USER` + `SUPPLYME_SMTP_PASSWORD` (a Gmail app password) | no — sends and reads |
| Programmable Search | `SUPPLYME_SEARCH_API_KEY` + `SUPPLYME_SEARCH_ENGINE_ID` | yes — falls back to Gemini search grounding, which also reads the live web |
| Gmail API instead of IMAP | `python scripts/gmail_auth.py --client-secret client_secret.json` | yes — replies are polled rather than pushed |

The Gmail API path also needs a publicly reachable `SUPPLYME_PUBLIC_BASE_URL` for its
webhook; a tunnel is fine for local work. IMAP needs nothing but the app
password, and replies arrive on the next poll — `./run.sh mail` reads the
mailbox immediately rather than waiting.

**Sending real email reaches real businesses.** Keep `SUPPLYME_MAIL_REDIRECT_TO` set
to a mailbox you own — and a different one from `SUPPLYME_SMTP_USER`, or your
reply arrives from the sending address and is discarded as our own copy. The default `autonomous` policy sends without asking — set
`SUPPLYME_APPROVAL_POLICY=external` or `strict` if you want nothing to leave without
you reading it first.

## If something goes wrong

**Console returns 500, log says `__webpack_modules__[moduleId] is not a function`.**
`npm run build` and `npm run dev` share `.next`, and a production build run while
the dev server is up corrupts it. `./run.sh` detects this and clears it on
start; by hand, stop the dev server, move `.next` aside, start it again.

**`No model configured`, or `SUPPLYME_MAPS_API_KEY is not set`.** There is nothing to
fall back to. Set what the message names; for the model that is `SUPPLYME_PROJECT_ID`
plus `gcloud auth application-default login`, or `SUPPLYME_GEMINI_API_KEY`.

**429 `RESOURCE_EXHAUSTED` in the API log.** Vertex quota. Lower
`SUPPLYME_MAX_CONCURRENT_RESEARCH`, or use `gemini-2.5-flash` for both tiers.
Retries back off automatically.

**A mission sits in `awaiting_response` and does not finish.** It is waiting for
a supplier, which is correct — that is what the product is. Reply to the message
yourself from the redirect mailbox and it will resume; `./run.sh mail` reads the
reply immediately instead of waiting for the poll. Left alone, the follow-up
timer is a real 48 hours.

**A reply was sent but the mission did not notice.** Check `./run.sh mail` —
it reports how many messages were read and how many resumed a mission. A reply
is matched by its `In-Reply-To` header, so replying in the thread works and
composing a fresh message to the same address does not.

**`pytest` fails on import with a `google-adk` error.** Check your Python is
3.12 or 3.13: `.venv/bin/python --version`.

## The environment variables worth setting

All `SUPPLYME_`-prefixed, and read in exactly one place: `app/config.py` — which
is also the complete list, including the infrastructure and mail-transport
settings omitted here because their defaults are almost always right. A missing
credential stops the process and names itself rather than being substituted for,
and `/api/health` lists every adapter actually bound.

| Variable | Default | What it does |
| --- | --- | --- |
| `SUPPLYME_USE_CLOUD_INFRA` | `false` | Firestore/Pub/Sub/Cloud Tasks vs in-process |
| `SUPPLYME_APPROVAL_POLICY` | `autonomous` | `autonomous` \| `external` \| `strict` |
| `SUPPLYME_PROJECT_ID` | — | Google Cloud project for Vertex AI and Firestore |
| `SUPPLYME_LOCATION` | `us-central1` | Region for Cloud Tasks and friends. Must be a real region — Cloud Tasks rejects `global` |
| `SUPPLYME_VERTEX_LOCATION` | `global` | Where Vertex serves the model. Gemini 3.x answers from `global`; a named region 404s |
| `SUPPLYME_USE_VERTEX` | `true` | false uses the Gemini Developer API and `SUPPLYME_GEMINI_API_KEY` instead |
| `SUPPLYME_REASONING_MODEL` | resolved | empty = newest reachable model on the ladder |
| `SUPPLYME_FAST_MODEL` | resolved | cheap model for extraction and classification |
| `SUPPLYME_MAPS_API_KEY` | — | Google Places. Required; unset is a startup failure |
| `SUPPLYME_SEARCH_API_KEY` / `SUPPLYME_SEARCH_ENGINE_ID` | — | Programmable Search; unset falls back to Gemini grounding |
| `SUPPLYME_SMTP_USER` / `SUPPLYME_SMTP_PASSWORD` | — | real outbound mail without OAuth. Outbound only |
| `SUPPLYME_MAIL_REDIRECT_TO` | — | send every message here instead of to the supplier. Use it |
| `SUPPLYME_MAX_CONCURRENT_RESEARCH` | `3` | caps the widest fan-out so a mission cannot rate-limit itself |
| `SUPPLYME_MAX_CONCURRENT_MODEL_CALLS` | `4` | Gemini requests in flight, process-wide, ADK's included |
| `SUPPLYME_MIN_MODEL_CALL_INTERVAL_SECONDS` | `0` | paces the queue on a small quota |
| `SUPPLYME_MAX_USD_PER_MISSION` | `1.00` | hard stop — the mission fails with a reason rather than spending more |
| `SUPPLYME_MAX_MODEL_CALLS_PER_MISSION` | `300` | hard stop. A real mission over 8 suppliers uses about 100 |
| `SUPPLYME_MAX_RESEARCH_LLM_CALLS` | `12` | ceiling on one ADK tool loop (ADK's own default is 500) |
| `SUPPLYME_FAST_THINKING_BUDGET` | `0` | thinking is billed as output and buys nothing on extraction |
| `SUPPLYME_MAX_OUTREACH_PER_MISSION` | `12` | cost guard |
| `SUPPLYME_MAX_VENDORS_PER_MISSION` | `12` | across the whole mission, not per category |
| `SUPPLYME_USE_ADK_RESEARCH` | `true` | research as an ADK tool loop; off falls back to pre-fetching |
