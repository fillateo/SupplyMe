# 🧭 SupplyMe - AI-Powered Supplier Sourcing Agent System

A multi-agent sourcing system that turns *"I want to make this product"* into a
qualified supply network, discovering suppliers, reading what they publish,
emailing them, chasing replies for days, and reporting **where every single
number came from**.

## 🎯 Project Overview

SupplyMe is a sourcing and supplier-qualification platform that **finds,
interrogates, and ranks manufacturers** through a network of specialized AI
agents. The system decomposes a product into the supply chain it needs, finds
candidate factories, researches each one against the live web, emails what it
cannot find out, resolves the contradictions in what comes back, and ranks the
survivors with a deterministic score it can explain line by line.

Sourcing information is not published, it is *disclosed*, differently to
different people, in a negotiation. There is no dataset. The only way to learn a
supplier's real minimum order is to ask them, and the only way to know whether
their claims hold is to find somebody other than them saying it.

Two moments show what that buys you:

- **Two suppliers claim the same major fragrance brand as a customer.** One is
  corroborated by the brand's own site and a trade publication; the other is the
  supplier's word and nothing else. They are reported differently, and never as
  the same thing.
- **A supplier's website says MOQ 500; their email says 1,000.** Rather than
  asking again, the system puts both numbers back to them in one targeted
  follow-up, *"your published minimum is 500 but we were quoted 1,000 - is 500
  possible as a pilot?"*, and re-scores them on the answer.

Most of the wall-clock time in that job is spent waiting for a human to reply.
That is a bad fit for search, and a good fit for an agent.

## 🏗️ Architecture

![SupplyMe architecture — browser to console to API, the event plane over Pub/Sub, Cloud Tasks and Cloud Scheduler, seven Gemini agents beside the deterministic engines, and every managed service reached through a Port](./docs/architecture.png)

```mermaid
flowchart TD
    B[Browser] --> C["Next.js console<br/>Cloud Run · proxies /api/* server-side"]
    C -->|HTTPS| A["FastAPI<br/>Cloud Run"]
    A --> O["Orchestrator<br/>claim dedup key → handler → emit next"]
    O --> AG["7 agents<br/>Gemini / Vertex AI"]
    O --> DE["Deterministic engines<br/>evidence · quotes · conflicts · scoring"]
    AG --> P["Ports<br/>Search · Maps · Mail · Store · Bus · Scheduler"]
    DE --> P
    P --> X["Adapters — every one the real service<br/>Programmable Search · Places · SMTP + IMAP · Gmail API"]
    X --> S[("Firestore · Pub/Sub · Cloud Tasks · Cloud Logging")]
    S -->|push| A
```

SupplyMe consists of 4 components working together:

### Core Components

- **🧠 [Backend API](./backend/README.md)** - FastAPI, the orchestrator, the seven agents, and the deterministic engines
- **🖥️ Console** (`frontend/`) - Next.js 15 dashboard; every fact clickable back to its source excerpt
- **📬 Mail loop** (`backend/app/adapters/`) - SMTP out, IMAP in, or Gmail API push; replies re-enter the workflow by `In-Reply-To`
- **☁️ Infrastructure** (`terraform/`) - OpenTofu; Cloud Run, Firestore, Pub/Sub, Cloud Tasks, Secret Manager, budgets

Every component drawn above is implemented. Nothing in the pipeline is a single
long LLM call: **each arrow is a persisted event**, so a Cloud Run restart mid
mission loses nothing and a supplier replying three days later resumes the same
mission.

### Agent Workflow

```mermaid
graph TD
    A[Mission agent<br/>reads the objective] --> B[Supply chain agent<br/>decomposes the product]
    B --> C1[bottle]
    B --> C2[pump]
    B --> C3[cap]
    B --> C4[filling]
    B --> C5[label]
    C1 --> D[Discovery agent<br/>search + Places]
    C2 --> D
    C3 --> D
    C4 --> D
    C5 --> D
    D --> E[Identity resolution<br/>dedupe the same factory]
    E --> F[Research agent<br/>ADK tool loop]
    F --> G[Brand evidence agent<br/>corroborate the claims]
    G --> H{Facts still missing?}
    H -->|no| K[Deterministic scoring]
    H -->|yes| I[Communication agent<br/>drafts + sends email]
    I --> J[Supplier replies, hours later]
    J --> L[Quote extraction]
    L --> M{Conflict?}
    M -->|yes| I
    M -->|no| K
    K --> N[Recommended supply network<br/>with reasons and open risks]
```

The routing decision is the whole product. `handle_vendor_updated` in
`app/workflow/handlers.py` reads a supplier's current state and picks the next
move, qualify, reject, email, or wait, and no part of that is scripted by the
user.

### One system, any product

Nothing in `app/` knows what a bottle is. The supply-chain agent decomposes the
product into nodes, and each node carries the words a supplier in *that*
industry writes on a quotation: `botol`, `flacon`; `PCBA`, `board`; `papan
kayu`. That list is the mission's **component vocabulary**
(`domain/quotes.ComponentVocabulary`), and it is what lets a reply be matched to
the question that asked it.

It replaced a hardcoded alias table. The table only ever held one industry's
words, so a furniture supplier pricing `papan kayu jati` looked like a supplier
who had not answered, and a fixed three-component bundle rule meant any supplier
in any other industry who quoted one bundled price was silently uncomparable.
What a bundle contains is now the supplier's statement, recorded from their
reply; a bundle they did not explain is reported as uncomparable rather than
assumed.

One plan, from a live run against *"a 1.5m solid oak dining table for export
from Vietnam"*, a product this code has never been told anything about:

```
fsc-oak-lumber              FSC oak · gỗ sồi FSC · oak lumber · solid oak board
woodworking-and-finishing   wood machining · gia công gỗ · PU finishing · sơn PU
kd-hardware                 KD fittings · phụ kiện ngành gỗ · connecting bolts
flatpack-packaging          carton box · thùng carton · flatpack box
```

None of those words appears anywhere in `app/`, in any language. The plan is
regenerated per mission, so a second run words it differently. What is fixed is
that the vocabulary comes from the plan and not from a table. The only component
vocabulary the code ships with is that `set`, `paket` and `kit` all mean
`package`, because bundling is a property of quotations rather than of an
industry.

## ✨ Key Features

### Autonomous Investigation
- **Any physical product** - a 50ml EDP, an oak dining table, a run of hoodies, a power bank. The supply chain is derived from the product, and so is the vocabulary used to read the quotes that come back; no industry is built in
- **Parallel discovery** - every supply-chain node is searched at once, bounded so a mission cannot rate-limit itself
- **Agentic research** - a Google ADK `LlmAgent` chooses which page to read next based on what the last one said, and stops when it can answer
- **Identity resolution** - the same factory listed under three names becomes one supplier

### Evidence With Provenance
- **The model extracts claims; it never rates them** - `app/domain/evidence.py` scores a claim from its source and nothing else
- **Provenance on every displayed fact** - `verified`, `direct quote`, `published`, `inferred`, `sources differ`, `unknown`. Six states, because six is what the evidence engine can actually compute; a badge for a seventh would be a claim about the system rather than about the fact
- **Diminishing returns** - twenty directory listings copying one press release score *lower* than the manufacturer's own spec sheet
- **Click through to the excerpt** - verbatim text, URL, and retrieval time, in the console

### Outreach That Closes The Loop
- **Asks only what is missing** - threads track asked / answered / unanswered questions
- **Conflict-driven follow-ups** - contradictions become one targeted question, not a repeat of all eight
- **Reply matching by mail headers** - `Message-ID` / `In-Reply-To`, so a redirected test mailbox still resolves to the right mission
- **No polling of a browser** - Cloud Scheduler pings the mailbox, or Gmail pushes to Pub/Sub; the tab can be closed

### Explainable Ranking
- **Deterministic scoring, never a model score** - price 20% · MOQ fit 20% · capability 20% · lead time 15% · evidence 15% · logistics 10%
- **Weights follow your objective** - *"minimize risk on the first batch"* moves weight onto MOQ fit and off price
- **A sentence per component** - `MOQ 500 fits an order of 500`, not a bar
- **Logistics scoped to your question** - city, country or global; the same factory scores differently under each, and the choice shapes the search queries too
- **Comparable quotes only** - `bottle + pump + cap = Rp 12,000` normalises against `8,000 / 2,500 / 1,500`, and `kit = $41` against `cell / PCBA / shell`; a partial quote, or a bundle whose contents the supplier never stated, is reported as not-comparable rather than as cheapest
- **A price you cannot reach is not a price** - suppliers quote a ladder, and every reply leaves its own quote behind. A rung quoted at 1,000 units is excluded when the order is 500, so settling a MOQ down to a pilot cannot then rank the supplier on the volume price it just said no to
- **A partial total says it is partial** - the report's per-unit figure names how many of the selected components it actually covers, because a sum over two priced lines out of seven is not the unit cost of the product

### Production Behaviour
- **Event-sourced and idempotent** - every message may be delivered twice; no supplier is ever emailed twice
- **Hard spend caps** - a mission that hits its ceiling fails with a reason and is deliberately *not* retried
- **Per-mission cost accounting** - read from the API's own token counts at `/api/missions/{id}` → `spend`
- **Fail-fast configuration** - a missing credential stops the process and names itself; there is nothing to fall back to
- **Autonomous by default** - no approval step stands between the agent and the supplier. The mail redirect is the safety boundary, and `/api/health` says plainly where mail is going

## 🤖 Agent Architecture

Seven agents, each with an explicit tool allowlist in `app/domain/policy.py`.
**It is enforced at runtime in the one place an agent chooses its own tool
calls**: ADK's `before_tool_callback` runs `policy.check()` on every tool
invocation inside the Research agent's ADK loop, and a denial is returned to
the model as a result so the agent carries on with the tools it does hold
(`app/agents/adk_research.py`). The other six agents never call a tool
directly. Each is one structured call, and the handler that reads its output
is the only code that touches a provider, so their allowlist is a contract
enforced by code structure and held to the same table by
`tests/test_security_policy.py`, not by a runtime gate on every call.

| Agent | May | May not |
| --- | --- | --- |
| **Mission** | read the objective, write vendors | search, read, email, spend |
| **Supply chain** | decompose | any tool at all |
| **Discovery** | search, Maps, read pages, write vendors | email |
| **Research** | search, read, Maps, write evidence, write vendors | **email, spend** |
| **Brand evidence** | search, read, write evidence | **email, spend** |
| **Communication** | draft, send, read mail, write evidence (recording an extracted quote) | alter scores |
| **Recommendation** | write scores | send anything |

The two agents that read attacker-controlled content, Research and Brand
Evidence, hold no tool that can reach the outside world. If a supplier's page
convinces the model of something, the worst it can do is record a bad claim or
a vendor record, which the evidence engine then rates on its source.

### Where Google ADK is used, and why only there

Six of the seven agents are single structured calls, because the *workflow*
decides what happens next and the model only fills in shape. Research is the
exception: which source is worth reading depends on what the last one said, so
that stage is a Google ADK `LlmAgent` with real tools
(`app/agents/adk_research.py`). A live run reading one supplier chose this
sequence unprompted:

```
read_page   https://kemasan-wangi.example.com/
search_web  "PT Kemasan Wangi Nusantara Indonesia 50ml glass perfume bottle MOQ"
read_page   https://kemasan-wangi.example.com/produk/botol-parfum-50ml
```

and returned `moq = 500`, quoted as *"Minimum order: 500 pcs per desain."*, with
`unit_price` and `lead_time_days` correctly reported as missing, which is what
later causes the system to email and ask.

## 🛠️ Technology Stack

- **Framework**: Python 3.12+ · FastAPI · Google ADK Agents · Pydantic v2
- **AI Models**: Gemini 3.5 Flash on Vertex AI, resolved from a reachability ladder in `app/config.py`
- **Database**: Firestore (missions, vendors, evidence, quotes, conflicts, approvals, event log)
- **Messaging**: Pub/Sub push with dead-lettering · Cloud Tasks for follow-ups and retries
- **APIs**: Google Places · SMTP + IMAP on one Gmail app password · Gemini search grounding · Gmail API push
- **Frontend**: Next.js 15 · React 19 · TypeScript · Tailwind
- **Deployment**: Cloud Run (scale to zero) · Secret Manager · Cloud Logging · OpenTofu

## 📋 Prerequisites

- **Docker** with Compose v2 — the shortest path, and the only one that needs
  nothing else installed
- Or, to run it natively: **Python 3.12 or 3.13** and **Node 20+**
- **Google Cloud project** with Vertex AI enabled, plus `gcloud auth application-default login`
- **API Keys**:
  - Google Cloud project ID for Vertex AI (or a Gemini Developer API key)
  - Google Maps / Places API key. **Required**, the process will not start without it
  - Gmail app password for SMTP + IMAP, which sends and reads on one credential
  - Optional: Programmable Search key + engine ID; without one, search falls back to Gemini grounding

> `MOCK=true` is the one way to see it without credentials, and it runs no
> mission at all — it replays a recording of one that did, with no provider bound
> and nothing generated. It cannot be turned on in the deployment.

## 🚀 Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/fillateo/SupplyMe.git
cd SupplyMe
cp backend/.env.example backend/.env
# Edit backend/.env with your project and credentials
```

### 2. Environment Configuration

The minimum that starts a real mission:

```env
SUPPLYME_PROJECT_ID=your-gcp-project
SUPPLYME_VERTEX_LOCATION=global
SUPPLYME_MAPS_API_KEY=your_places_key

# The mailbox, in both directions - one Gmail app password
SUPPLYME_SMTP_USER=sourcing@example.com
SUPPLYME_SMTP_PASSWORD=your_app_password

# The one safety valve. Set it, to a DIFFERENT mailbox from the one above.
SUPPLYME_MAIL_REDIRECT_TO=you@example.com
```

> Those two must not be the same address. Outreach is sent from `SMTP_USER` and
> read back from it, and mail arriving from that address is discarded as our own
> copy, so if they match, you answer as the supplier and the mission never hears
> you.

> ⚠️ **The addresses in a mission belong to real businesses**, read off their
> real websites, and the distance between a good demonstration and an apology is
> one environment variable. Set `SUPPLYME_MAIL_REDIRECT_TO` to a mailbox you own:
> every message really sends, and says at the top who it would have reached.

### 3. Install Dependencies

`./run.sh` installs what is missing on its own. To do it explicitly:

```bash
./run.sh setup

# Or install the backend by hand
cd backend
uv venv --python 3.12 .venv && VIRTUAL_ENV=.venv uv pip install -e ".[dev]"

# And the console
cd ../frontend && npm install
```

Then confirm which models your project can actually reach. Reachability is a
property of the project *and* the location, not of the model name:

```bash
cd backend && .venv/bin/python scripts/check_models.py --project YOUR_PROJECT --location global
```

### 4. Run the System

**With Docker — the whole system, including its database:**

```bash
docker compose up --build      # console on :3000, API on :8080, Firestore on :8085
docker compose down
```

If a VPN has taken over the Docker bridge — containers healthy, nothing
answering on :3000 — add the host-network overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.host.yml up --build
```

Three services in the images the deployment runs: Google's **Firestore
emulator**, the API, and the console. The API reaches the emulator through the
same `FirestoreStore`, the same client library and the same transactions it
uses on Cloud Run, so the local data path is the deployed one rather than a
stand-in — and no Java, Python or Node is needed on the host.

The emulator starts empty and forgets everything when it stops, so `up` seeds it
first from the newest file in `~/supplyme-firestore-backups`. With no backups
there yet it comes up empty and says so; `backend/scripts/export_firestore.py`
writes one from a real Firestore. What Docker does **not** change: the model, search, Places and the
mailbox are still the live services. Browsing seeded missions is free; starting
a new one spends money.

**Demonstrating it without spending anything:**

```bash
MOCK=true docker compose up --build      # or: MOCK=true ./run.sh
```

Missions are then **replayed from a recording** rather than run. Press *Start
sourcing* and the console fills in — suppliers, evidence, emails, contradictions,
a ranked recommendation — in the original order, in well under a minute. No
model call, no search, no mailbox, and no credentials needed at all.
`MOCK_DURATION` sets the budget; the long waits for supplier replies are
shortened rather than played out, so a run finishes inside it.

It is a playback, not a fixture world. Every supplier, price, excerpt and source
URL came out of a mission that really ran against the live web; the only thing
mock mode adds is a shorter clock. **No provider is bound** — the ones in
`app/adapters/inert.py` raise if anything reaches for them, so nothing can
quietly invent a supplier when the recording runs out. The replayed mission
records which recording it came from in `replay_of`, and `/api/health` says the
mode is on.

**The objective you type picks the brief.** Three of them sit over the one
recorded supply chain — the recorded 50ml eau de parfum, a 30ml vitamin C serum,
an 8oz soy candle, all Los Angeles and all 1,000 units — and the closest one to
what you typed is the one that plays; type the fragrance brief and you get the
fragrance mission. An objective matching none of them rotates through the other
two, so the console still fills with distinguishable missions rather than one
mission five times. **All of them are the same real suppliers** — a carton
printer, a glass distributor and a contract filler in LA serve skincare and
candles as readily as fragrance — and each brief brings real LA specialists of
its own (O.Berk West, APackaging Group, Lumient LA, INTI Candles, Velocity Pro
Pack, Olivia Care) carrying sentences quoted from their own websites.

What a brief changes is the question and the component vocabulary. What it never
touches is primary source material: an evidence excerpt, a source URL, an email
body and a quoted price stay exactly as recorded, because those are real
companies' actual words. So what it cannot do is answer a *new* brief — it
replays the supply chain it has under the nearest question it holds. And it is
**refused outright** when `SUPPLYME_USE_CLOUD_INFRA` is on, so it cannot run in
the deployment.

**Natively, with `run.sh`:**

```bash
./run.sh            # API on :8080, console on :3000
./run.sh emulator   # start the Firestore emulator and seed it from a backup
./run.sh mission    # one whole mission in the terminal, start to finish
./run.sh mail       # read the mailbox now instead of waiting for the poll
./run.sh test       # 492 tests, ~60s, no network
./run.sh status     # what is running, and what it has spent
./run.sh stop
./run.sh clean      # build caches only, never source or .env
```

Without `SUPPLYME_FIRESTORE_EMULATOR_HOST` or `SUPPLYME_LOCAL_STORE_PATH` set,
`./run.sh` keeps state in process and missions do not survive a restart —
`/api/health` says which of the three it got.

### 5. Access the Dashboard

Open **http://localhost:3000**, describe a product, *"500 × 50ml EDP,
Indonesia, premium packaging, minimize first-batch risk"*, and watch the supply
chain, suppliers, evidence and emails fill in live.

`GET /api/health` names every adapter actually bound and the model each tier
resolved to, which is how you check the Gemini generation from outside the code:

```bash
curl -s localhost:8080/api/health | jq '.model, .providers'
```

## 🔧 Environment Variables

All `SUPPLYME_`-prefixed, read in exactly one place, `app/config.py`. A missing
required one is a startup failure, not a fallback.

| Variable | Default | Description | Required |
| --- | --- | --- | --- |
| `SUPPLYME_PROJECT_ID` | — | Google Cloud project for Vertex AI and Firestore | Yes (or `SUPPLYME_GEMINI_API_KEY`) |
| `SUPPLYME_MAPS_API_KEY` | — | Google Places | Yes |
| `SUPPLYME_SMTP_USER` / `SUPPLYME_SMTP_PASSWORD` | — | Real mail in both directions, no OAuth client needed | Yes |
| `SUPPLYME_MAIL_REDIRECT_TO` | — | Send every message here instead of to the supplier. **Use it** | Optional |
| `SUPPLYME_VERTEX_LOCATION` | `global` | Where Vertex serves the model. Gemini 3.x answers from `global`; a named region 404s | Optional |
| `SUPPLYME_LOCATION` | `us-central1` | Region for Cloud Tasks and friends. Must be a real region, Cloud Tasks rejects `global` | Optional |
| `SUPPLYME_USE_CLOUD_INFRA` | `false` | Firestore / Pub/Sub / Cloud Tasks vs the in-process store, bus and scheduler | Optional |
| `SUPPLYME_APPROVAL_POLICY` | `autonomous` | `autonomous` \| `external` \| `strict`. Autonomous is safe because `SUPPLYME_MAIL_REDIRECT_TO` bounds the blast radius, not a human | Optional |
| `SUPPLYME_SEARCH_API_KEY` / `SUPPLYME_SEARCH_ENGINE_ID` | — | Programmable Search; unset falls back to Gemini grounding | Optional |
| `SUPPLYME_REASONING_MODEL` / `SUPPLYME_FAST_MODEL` | resolved | Empty = newest reachable model on the ladder | Optional |
| `SUPPLYME_MAX_USD_PER_MISSION` | `1.00` | Hard stop, the mission fails with a reason rather than spending more | Optional |
| `SUPPLYME_MAX_MODEL_CALLS_PER_MISSION` | `300` | Hard stop. 8 suppliers costs about 100 calls; 12 costs about 300 | Optional |
| `SUPPLYME_MAX_VENDORS_PER_MISSION` | `12` | The single biggest lever on cost. Lower it first | Optional |
| `SUPPLYME_MAX_RESEARCH_LLM_CALLS` | `12` | Ceiling on one ADK tool loop; ADK's own default is 500 | Optional |
| `SUPPLYME_MAX_CONCURRENT_RESEARCH` | `3` | Caps the widest fan-out so a mission cannot rate-limit itself | Optional |
| `SUPPLYME_FAST_THINKING_BUDGET` | `0` | Thinking is billed as output and buys nothing on extraction | Optional |

## ☁️ Deployment

Everything is provisioned by OpenTofu. `plan` is the review surface, nothing is
created by hand.

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # set project_id and both images
cp backend.hcl.example backend.hcl             # set your state bucket
tofu init -backend-config=backend.hcl
tofu fmt && tofu validate && tofu plan         # review before applying
tofu apply
```

`scripts/deploy.sh PROJECT_ID` does the same thing and stops at the plan, after
building both images and running the tests.

Two Cloud Run services come out of it, the API and the console that proxies to
it. `tofu output console_url` is the link to open; `tofu output next_steps` is
what to do after that.

### 📬 Gmail integration

Two paths satisfy the same port, and `/api/health` says which is bound:

| Path | How it works | Trade |
| --- | --- | --- |
| **IMAP poll** *(what runs today)* | Cloud Scheduler posts to `/webhooks/mail/poll` every 15 minutes; the same app password that sends also reads | A supplier answering at 2am is picked up within fifteen minutes, not the same second. `POST /webhooks/mail/poll` reads it immediately |
| **Gmail push** | `users.watch` points Gmail at a Pub/Sub topic; `/webhooks/gmail` pulls the new message and the mission resumes | Needs an OAuth client, a consent screen, and a browser sign-in from the mailbox owner |

Set `gmail_push = true` in Terraform and run `backend/scripts/gmail_auth.py` to
use the push path instead.

## 📊 Data Storage

Firestore holds every mission and everything derived from one. The same
documents are what the console reads, so nothing on screen exists only in
memory.

| Collection | What it holds |
| --- | --- |
| `missions` | The brief, the supply-chain plan, status, and the running spend |
| `vendors` | One document per resolved supplier, with scores and contact detail |
| `evidence` | Every claim, its source, its verbatim excerpt, and when it was retrieved |
| `quotes` | Normalised prices, MOQs and lead times, per component and per reply |
| `conflicts` | Contradictions between sources, and how each was resolved |
| `threads` | Email conversations, with asked / answered / unanswered questions |
| `approvals` | Outbound actions held for review under `external` or `strict` |
| `events` | The workflow event log; a mission replays from it after a restart |
| `missions/{id}/workflow_events` | Per-mission timeline the console renders live |
| `idempotency` | Action reservations keyed on `mission + vendor + action + version` |

Set `SUPPLYME_USE_CLOUD_INFRA=false` and the same shapes are held in an
in-process store instead, which is what the test suite and a laptop run use.
Missions then do not survive a restart, and `/api/health` says so.

Locally there are two ways to keep them. `SUPPLYME_FIRESTORE_EMULATOR_HOST`
binds the real `FirestoreStore` to Google's emulator, which is what
`docker compose up` runs and what makes the local data path identical to the
deployed one. `SUPPLYME_LOCAL_STORE_PATH` instead points the in-process store at
a JSON file it loads at startup and writes every change back to, for when
running a container is more than the job needs.

Both read the same file: a straight export of Firestore, keyed by document path.
`backend/scripts/export_firestore.py` writes one, `restore_local_db.py` installs
it as the file store and `seed_emulator.py` loads it into the emulator — which is
how the console can be shown on the missions that really ran, offline and
without a Google Cloud project.

## 💰 Cost

Measured from the API's own token counts, on `gemini-3.5-flash`:

| Mission | Model calls | Cost | Outcome |
| --- | --- | --- | --- |
| 8 suppliers, shortlist capped low | 98 | $0.29 | completed |
| 12 suppliers, default caps | 296 | $0.78 | stopped at `awaiting_response`, still short of a recommendation |

**Cost scales with how many suppliers get researched, not with the mission**, and
the second row is the one to plan against: every admitted supplier is a tool loop
reading whole websites, and input tokens are almost the entire bill. On a fixed
balance, lower `SUPPLYME_MAX_VENDORS_PER_MISSION` before anything else. A
shortlist of five researched properly costs a third of twelve researched badly.

| Guard | Value | Effect |
| --- | --- | --- |
| Spend ceiling | `$1.00` / mission | Fails the mission with a reason, and is deliberately **not retried**. Checked before every request on every path that spends; a few concurrent calls can still land after it fires, so treat it as a stop rather than a to-the-cent limit. |
| Model calls | `300` / mission | Same |
| ADK research loop | `12` calls | Against ADK's default of 500, the largest unattended-spend risk in the system |
| Fast-tier thinking | `0` tokens | Thinking is billed as output; this alone cut cost per call ~60% |
| Places queries | `1` / supply-chain node | The priciest single call the system makes |

There is no zero-spend mode. Every mission reads the live web and calls Gemini,
so the caps are what bounds it rather than a switch.

## 🔐 Security & Privacy

- **Prompt-injection defence** - untrusted content is delimited, labelled as data, and injection phrasings defanged before the model sees it (`app/security/sanitize.py`)
- **Structured output only** - there is no free-form channel from a supplier's text to an action
- **Least privilege, executed where it matters most** - ADK's `before_tool_callback` checks the allowlist on every tool call inside the Research agent's loop, the one place an agent chooses its own tool calls; the other six agents have no tool loop to gate, so their allowlist is a contract enforced by code structure and held to the same table by `tests/test_security_policy.py`, not a runtime check on every call
- **Secrets in Secret Manager** - nothing reaches the browser; the console proxies server-side, so no API credential is ever in client JavaScript
- **Idempotency reservations** - every external action reserves before it runs, keyed on `mission + vendor + action + version`

## 📖 Usage Guide

### Running a mission

1. **State the objective** - quantity, product, market, priorities. *"500 × 50ml EDP, Indonesia, premium packaging, minimize first-batch risk"*
2. **Choose the logistics scope** - a named city, a country, or anywhere. This shapes the search queries, the Places region, and the ranking
3. **Watch the supply chain appear** - the product is decomposed into the components it needs, and each is searched in parallel
4. **Review the evidence** - click any fact to see the verbatim excerpt, the URL, and when it was retrieved
5. **Let it write** - the agent emails suppliers itself, without stopping to be authorised. `SUPPLYME_MAIL_REDIRECT_TO` is what bounds that, not a human: every message really sends, to the address you nominated. Set `SUPPLYME_APPROVAL_POLICY=external` if you would rather hold the first email to each supplier
6. **Close the tab** - replies arrive hours or days later and resume the mission on their own
7. **Read the recommendation** - a supply network with a sentence behind every score, and the open risks named

### Console features

- **Live mission timeline** - every event as it is persisted
- **Supplier cards** - provenance state on each fact, evidence drawer behind each one
- **Conflict view** - what the website said, what the email said, and how it was resolved
- **Communications** - every thread, with asked / answered / unanswered questions

Four API capabilities have no console control behind them, and are reachable
only with `curl`: `PUT /api/missions/{id}/weights` re-ranks a mission against new
priorities without re-researching, and `GET .../vendors/{vendor_id}`,
`GET .../ranking` and `GET .../map` return a single vendor's full dossier, the
live recomputed ranking, and vendor coordinates. All four are covered by
`tests/test_api.py`. The console's proxy forwards only GET and POST, so a
control for the `PUT` means adding that method to
`frontend/app/api/[...path]/route.ts` as well.

### Key API endpoints

| Endpoint | Purpose |
| --- | --- |
| `POST /api/missions` | Start a mission |
| `GET /api/missions/{id}` | Status, spend, and the mission brief |
| `GET /api/missions/{id}/vendors` | Suppliers with scores and provenance |
| `GET /api/missions/{id}/evidence` | Every claim, source and excerpt |
| `GET /api/missions/{id}/recommendation` | The final supply network |
| `POST /api/approvals/{id}` | Approve or deny an outbound action, under `external` or `strict` |
| `GET /api/health` | Which adapters and model are actually bound |
| `POST /events/pubsub` · `/events/task` · `/webhooks/gmail` · `/webhooks/mail/poll` | Machine entry points |

## 🔧 Configuration

### Model settings

Models are not pinned to a constant. `app/config.py` holds a preference ladder
and the first model that answers for your project and location wins:

```python
MODEL_LADDER = (
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-3.5-pro",
    "gemini-3-pro-preview",
    "gemini-2.5-pro",
)
```

Flash comes first deliberately. Pro costs roughly an order of magnitude more per
token, and this workload is extraction and adjudication over short excerpts
rather than long-horizon reasoning. Pin `SUPPLYME_REASONING_MODEL` and
`SUPPLYME_FAST_MODEL` where the generation matters, and read `/api/health` →
`.model` to see which one answered.

### Service ports

| Service | Port | Notes |
| --- | --- | --- |
| Console (Next.js) | `3000` | Proxies `/api/*` server-side, so no credential reaches the browser |
| API (FastAPI) | `8080` | `API_BASE_URL` points the console at it, read per-request so one image works in every environment |

## 🧪 Testing

```bash
./run.sh test
# or
cd backend && .venv/bin/python -m pytest -q     # 492 tests, ~60 seconds, no network
```

- **Unit** - evidence classification, identity resolution, quote normalisation, conflict detection, scoring, number parsing, policy, injection defence, and the ADK tool guard
- **Integration** - the whole workflow over the real event bus, plus the HTTP surface with a `TestClient`
- **Failure** - every message delivered twice, search outage, Maps timeout, blocked pages, model timeout, rate limiting, Cloud Run restart mid-mission, events for records that no longer exist, and a supplier reply carrying a prompt-injection payload

The redelivery test runs an entire mission at a 100% duplicate rate and asserts
no supplier is emailed twice.

The suite drives whole missions against test doubles, which live in `tests/` and
are reachable from nowhere in `app/`. That distinction is the point: a double
lets failures be provoked on demand, a supplier who never answers, one whose
site contradicts their quote, while the product itself has nothing to fall back
to.
