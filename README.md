# VendorDiscoveryShortcut

Tell it what you want to make. It works out which suppliers you need, finds them,
reads what they publish, emails them, follows up until a question is settled, and
tells you what it could and could not establish.

**Every number it reports back is stamped with where it came from** — and with
whether that source was the supplier's own marketing or somebody else.

Built for the Google × Devpost **All Things Agentic** hackathon, category
**The Taskmaster**.

---

## The two moments it turns on

Not "AI searches for suppliers." The agent builds a supplier network for a
product it has never seen, then goes out into the world to qualify it.

**Two suppliers claim the same major fragrance brand as a customer.** One is
corroborated by the brand's own site and a trade publication. The other is the
supplier's word and nothing else. The system reports them differently, and never
as the same thing.

**One supplier's website says MOQ 500; their email says 1,000.** The system
notices, and rather than asking again it puts both numbers back to them in one
targeted follow-up: *"your published minimum is 500 but we were quoted 1,000 —
is 500 possible as a pilot?"* They confirm 500 at a higher unit price, and the
resolution re-scores them.

## Why this is a job for an agent

I want to build a perfume brand. I do not have a supplier network.

That sentence hides a week of work. A 50ml EDP needs a fragrance house, a
filler, a bottle, a pump, a cap, a label, a box — and in Indonesia, BPOM
registration. For each I have to find companies, work out which of them
manufacture rather than resell, learn their minimum order quantities before I
waste their time and mine, ask the same eight questions, wait, chase, and then
compare replies that are not comparable.

Sourcing information is not published, it is *disclosed* — differently to
different people, in a negotiation. There is no dataset. The only way to know a
supplier's real minimum order is to ask them, and the only way to know whether
their claims hold is to find someone other than them saying it.

So it is a long, interruptible, multi-source investigation in which most of the
wall-clock time is spent waiting for a human being to reply. That is a bad fit
for search and a good fit for an agent.

## How it works

```
  "500 × 50ml EDP, Indonesia, premium packaging, minimize first-batch risk"
                                │
                      Mission agent reads it
                                │
                 Supply-chain agent decomposes it
                                │
        ┌──────────┬────────────┼────────────┬──────────┐
      bottle      pump         cap        filling     label      ← parallel
        │           │           │            │           │
     discovery → identity resolution → research → evidence
        │
    ┌───┴────────────────────────────┐
    │                                │
  facts known                   facts missing
    │                                │
    │                       outreach
    │                          │
    │                        email
    │                          │
    │                    supplier replies (hours later)
    │                          │
    │                   quote extraction
    │                          │
    │                   conflict detection ──→ targeted follow-up
    │                          │
    └──────────┬───────────────┘
               │
   deterministic scoring + explanation
               │
      recommended supply network
```

Nothing above is a single long LLM call. Each arrow is a persisted event.

## Taskmaster fit

| What the category asks for | Where it is |
| --- | --- |
| Receives a real objective | `POST /api/missions` → `mission.created` |
| Decomposes it | `app/agents/planning.py` |
| Decides what happens next | `handle_vendor_updated` in `app/workflow/handlers.py` |
| Uses external tools | Search, Places, YouTube, Gmail/SMTP — `app/adapters/` |
| Works asynchronously | Pub/Sub push + Cloud Tasks; the browser can be closed |
| Reacts to new events | `email.received` resumes a mission mid-flight — see Gmail integration for which half of that path has been run live |
| Maintains state | Firestore; a Cloud Run restart loses nothing |
| Produces a useful outcome | A supply network, with reasons and open risks |

The routing decision is the whole product. `handle_vendor_updated` reads a
supplier's current state and picks the next move — qualify, reject, email,
or wait — and no part of that is scripted by the user.

## Architecture

```
Next.js console ──► Cloud Run (FastAPI)
                          │
                    Orchestrator ──► Pub/Sub ──┐
                          │                     │ push
                          │◄────────────────────┘
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
   Gemini / Vertex   Google Search      Gmail API
        │            Places, YouTube
        ▼                 ▼                  ▼
              Firestore (missions, vendors, evidence,
              quotes, conflicts, approvals, event log)
                          │
                    Cloud Tasks (follow-ups, retries)
                          │
                    Cloud Logging
```

Every component in that diagram is implemented. See `docs/ARCHITECTURE.md` for
the event table and the Firestore collections.

## Agent architecture

Seven agents, each with an explicit tool allowlist (`app/domain/policy.py`).
The allowlist is the security boundary, not a comment:

| Agent | May | May not |
| --- | --- | --- |
| Mission | read the objective | anything external |
| Supply chain | decompose | any tool at all |
| Discovery | search, Maps, read pages | email |
| Research | search, read, Maps, YouTube, write evidence | **email, spend** |
| Brand evidence | search, read, YouTube, write evidence | **email, spend** |
| Communication | draft, send, read mail | alter scores |
| Recommendation | read evidence, compute | send anything |

The two agents that read attacker-controlled content — Research and Brand
Evidence — hold no tool that can reach the outside world. That is deliberate: if
a supplier's page convinces the model of something, the worst it can do is
record a bad claim, which the evidence engine then rates on its source.

### Where Google ADK is used, and why only there

Six of the seven agents are single structured calls, because the *workflow*
decides what happens next and the model only fills in shape. Research is the
exception: which source is worth reading depends on what the last one said, so
that stage is a **Google ADK `LlmAgent`** with real tools
(`app/agents/adk_research.py`). It searches, reads pages and queries Maps until
it can answer, and stops when it can — instead of being handed a fixed set of
pre-fetched pages, most of which it would not have needed.

A live run reading one supplier chose this sequence unprompted:

```
read_page   https://kemasan-wangi.example.com/
search_web  "PT Kemasan Wangi Nusantara Indonesia 50ml glass perfume bottle MOQ"
read_page   https://kemasan-wangi.example.com/produk/botol-parfum-50ml
```

and came back with `moq = 500`, quoted as *"Minimum order: 500 pcs per desain."*,
`unit_price` and `lead_time_days` correctly reported as missing — because that
page genuinely does not state them, which is what later causes the system to
email and ask.

ADK's `before_tool_callback` runs `app/domain/policy.py` on **every** tool
invocation, so the permission table above executes rather than describing. A
denial is returned to the model as a result, not raised, so the agent carries on
with the tools it does hold.

The tool loop gathers and writes up findings; a second call turns that write-up
into the schema. Asking one turn to both choose the next tool call and emit
strict JSON makes it do neither reliably, and everything downstream depends on
the schema.

## Evidence model

The LLM extracts claims. It does not decide what they are worth — `app/domain/evidence.py` does, from the source and nothing else:

```
Brand's own website           → verified
Two independent publications  → strong evidence
Supplier's own website        → supplier-reported, confidence capped at 0.45
A YouTube factory tour        → supplier-reported (it proves a factory exists,
                                not who its customers are)
Nothing found                 → no public evidence
```

Confidence combines sources with diminishing returns and saturates below
certainty, so twenty directory listings that copy one press release score
*lower* than the manufacturer's own spec sheet.

Every displayed fact carries a provenance state — `verified`, `direct quote`,
`published`, `supplier says`, `inferred`, `sources differ`, `unknown` — and
clicking it in the console shows the verbatim excerpt, the URL, and when it was
retrieved.

## Scoring

Deterministic and explainable. Gemini never returns a score.

```
price 20% · MOQ fit 20% · capability 20% · lead time 15% · evidence 15% · logistics 10%
```

Weights shift from what you said mattered: *"minimize risk on the first batch"*
moves weight onto MOQ fit and off price. Each component returns the sentence
that produced it — `MOQ 500 fits an order of 500`, not a bar.

**Logistics answers the question you actually asked.** You choose the scope when
you start a mission — a named city, a country, or anywhere — and the same
factory scores differently under each. At city scope a supplier in your city
scores 1.0 and one three provinces away 0.7, because being able to drive over
and look at a sample before committing is worth something real. At global scope
importing is the premise rather than a penalty, so an overseas supplier is no
longer marked down for being overseas. The choice is yours and not inferred: it
shapes the search queries, the Places region, and the ranking.

Quotes are normalised before comparison, so a vendor quoting `bottle + pump +
cap = Rp 12,000` and one quoting `8,000 / 2,500 / 1,500` compare as equal. A
vendor who has not priced every requested component is reported as
not-comparable rather than as cheapest.

## Gmail integration

`users.watch` points Gmail at a Pub/Sub topic. A supplier replies at 2am, Gmail
pushes a historyId, `/webhooks/gmail` pulls the new message, matches it to the
thread that asked for it, and the mission resumes. No polling, no open browser.

**What has and has not been run.** The workflow half is exercised on every demo
run and in the test suite: the mock provider raises real `email.received` events
through the real bus, and the mission resumes from them. The Gmail half —
OAuth, `users.watch`, and the push into `/webhooks/gmail` — is implemented and
has not been run end to end against a live mailbox, because that needs a
consent screen this project has not set up. `scripts/gmail_auth.py` is the path
if you want to. SMTP is what sends today, and it is outbound only; `/api/health`
says which of the two is bound rather than letting you assume.

Threads keep asked/answered/unanswered questions, so a follow-up asks only what
is still missing.

## Google Cloud, and what a mission costs

Cloud Run (scale to zero), Firestore, Pub/Sub with dead-lettering, Cloud Tasks,
Vertex AI, Secret Manager, Cloud Logging. All provisioned by OpenTofu in
`terraform/` — `plan` is the review surface, nothing is created by hand.

A mission is **about 60 model calls and $0.11** (roughly Rp 1,800) on
`gemini-3.5-flash` — 87,272 input and 25,840 output tokens on the run that
number comes from. Measured from the API's own token counts, not estimated, and
readable per mission at `/api/missions/{id}` → `spend`.

Reaching `VDS_MAX_USD_PER_MISSION` or `VDS_MAX_MODEL_CALLS_PER_MISSION` fails
the mission with a reason rather than spending more, and that failure is
deliberately **not retried** — retrying is the thing the cap exists to prevent.
The ADK research loop is capped at 12 calls against ADK's default of 500, which
was the largest unattended-spend risk in the system. Thinking tokens are billed
as output, so the fast tier runs with a budget of zero; that alone cut cost per
call by about 60%.

`VDS_USE_SCRIPTED_MODEL=true` runs everything with zero spend.
**[docs/COST.md](docs/COST.md)** has the measurements and every guard.

## Security

- Untrusted content is delimited, labelled as data, and injection phrasings are
  defanged before the model sees it (`app/security/sanitize.py`).
- Structured output only. There is no free-form channel from a supplier's text
  to an action.
- Least privilege, enforced by the agent tool allowlist above.
- Secrets in Secret Manager; nothing reaches the browser; the console proxies
  server-side so no API credential is ever in client JavaScript.
- Every external action requires an idempotency reservation before it runs.

## Run it

**You do not need a Google Cloud project.** With `VDS_USE_SCRIPTED_MODEL=true`
the entire system — console included — runs with no credentials and no network.
The agents, events, storage, conflict detection and scoring are the real ones;
only the text generation is deterministic.

```bash
./run.sh            # installs what is missing, then starts the API and console
./run.sh demo       # one whole mission in the terminal, ~30s
./run.sh test       # 317 tests, ~55s
./run.sh status     # what is running, and what it has spent
./run.sh stop
```

It needs Python 3.12 or 3.13 and Node 20+, and nothing else.

For real Gemini: set `VDS_PROJECT_ID` in `backend/.env`, run `gcloud auth
application-default login`, then `./run.sh live`. It refuses to start if either
is missing rather than failing halfway through a mission. Run
`backend/scripts/check_models.py` first to see which models your project can
actually reach, and from where.

**[docs/LOCAL.md](docs/LOCAL.md)** has the walkthrough, the full environment
variable reference, and what to do when something breaks.
**[docs/DEMO.md](docs/DEMO.md)** is the four-minute path through the console.

## Deploy it

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # set project_id and image
cp backend.hcl.example backend.hcl             # set your state bucket
tofu init -backend-config=backend.hcl
tofu fmt && tofu validate && tofu plan         # review before applying
tofu apply
```

`scripts/deploy.sh PROJECT_ID` does the same thing and stops at the plan, after
building the image and running the tests. Then `tofu output next_steps`.

## Testing

```bash
.venv/bin/python -m pytest -q     # 317 tests, ~55 seconds, no network
```

- **Unit** — evidence classification, identity resolution, quote normalisation,
  conflict detection, scoring, number parsing, policy, injection defence, and
  the ADK tool guard.
- **Integration** — the whole workflow over the real event bus, plus the HTTP
  surface with a `TestClient`.
- **Failure** — every message delivered twice, search outage, Maps timeout,
  blocked pages, model timeout, rate limiting, Cloud Run restart mid-mission,
  events for records that no longer exist, and a supplier reply containing a
  prompt-injection payload.

The redelivery test runs an entire mission at a 100% duplicate rate and asserts
no supplier is emailed twice.

Demo data is synthetic and marked as such: every company, brand and quote is
invented, and every domain is under the reserved `example.com`. A missing API
key never fails a mission — the provider degrades to its mock and the
substitution is reported at `/api/health`, so a demo cannot quietly claim to
have called a Google API it did not call.

## Limitations

- **Model reachability is per project and per location.** This runs on
  `gemini-3.5-flash`, which on Vertex answers from the `global` endpoint and
  404s from `us-central1` — with nothing in the error to suggest it exists
  elsewhere. `scripts/check_models.py --project X --location Y` reports what a
  given project resolves to, and the ladder in `app/config.py` picks the newest
  that answers. Which is why the model id is configuration, not a constant.
  There are two location settings for the same reason: Cloud Tasks rejects
  `global`, so `VDS_VERTEX_LOCATION` and `VDS_LOCATION` cannot be one value.
- **The Gmail inbound path has not been run against a live mailbox.** It is
  implemented and the workflow half is exercised on every run; the OAuth half
  needs a consent screen this project has not set up. See Gmail integration.
- Live web research is only as good as what suppliers publish, which in this
  industry is often a phone number and a WhatsApp link.
- Currencies are never converted. Quotes in different currencies are reported
  side by side and excluded from the price comparison rather than guessed at.
- The console polls every two seconds rather than streaming.
- One vertical's vocabulary (perfume) is encoded in the quote normaliser's
  component aliases. Another vertical needs its own alias table.

## Future work

- Sample tracking: a quotation is not a supplier until a sample arrives.
- Negotiation memory across missions, so a second product benefits from the
  first product's relationships.
- A supplier-side portal, so a supplier answers a structured form once instead
  of the same eight questions from every buyer.
