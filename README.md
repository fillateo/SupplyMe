# VendorDiscoveryShortcut

Tell it what you want to make. It works out which suppliers you need, finds them,
reads what they publish, emails them, calls when writing will not settle a
question, and tells you what it could and could not establish.

Built for the Google × Devpost **All Things Agentic** hackathon, category
**The Taskmaster**.

---

## The friction

I want to build a perfume brand. I do not have a supplier network.

That sentence hides a week of work. Before anyone can quote me anything I have to
know that a 50ml EDP needs a fragrance house, a filler, a bottle, a pump, a cap,
a label, a box — and that in Indonesia it also needs BPOM registration. Then I
have to find companies for each, work out which of them actually manufacture
rather than resell, find out their minimum order quantities before I waste their
time and mine, ask the same eight questions by email, wait, chase, and then
compare replies that are not comparable: one vendor quotes a bundle, another
quotes three line items, a third quotes in a different currency.

And underneath all of it, one question I could not answer at all: **is any of
this true?** A supplier's site says they produce for a major fragrance house. Do
they? Their site says MOQ 500. Their sales desk emails back 1,000. Which is it?

## Why this problem exists

Sourcing information is not published, it is *disclosed* — differently to
different people, in a negotiation. There is no dataset. The only way to know a
supplier's real minimum order is to ask them, and the only way to know whether
their claims hold is to look for someone other than them saying it.

That makes it a bad fit for search and a good fit for an agent: it is a long,
interruptible, multi-source investigation where most of the wall-clock time is
spent waiting for a human being to reply.

## The twist

Not "AI searches for suppliers."

**The agent builds a supplier network for a product it has never seen, then goes
out into the world to qualify it** — and every number it reports back is
traceable to the source it came from, with a stamp saying whether that source
was the supplier's own marketing or somebody else.

The demo scenario turns on two moments:

- Two suppliers claim the same major fragrance brand as a customer. One is
  corroborated by the brand's own site and a trade publication. The other is the
  supplier's word and nothing else. The system reports them differently, and
  never as the same thing.
- One supplier's website says MOQ 500; their email says 1,000. The system
  notices, works out that another email will not settle it — they already
  answered in writing — calls them, gets *"500 for a pilot, at Rp 11,000"*, and
  re-scores them. The resolution moves that supplier from 84 to 95 out of 100.

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
    │                          contact strategy
    │                          ┌─────┴──────┐
    │                        email        call
    │                          │            │
    │                    supplier replies (hours later)
    │                          │
    │                   quote extraction
    │                          │
    │                   conflict detection ──→ follow-up or call
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
| Uses external tools | Search, Places, YouTube, Gmail, telephony — `app/adapters/` |
| Works asynchronously | Pub/Sub push + Cloud Tasks; the browser can be closed |
| Reacts to new events | `email.received` from a Gmail push resumes the mission |
| Maintains state | Firestore; a Cloud Run restart loses nothing |
| Produces a useful outcome | A supply network, with reasons and open risks |

The routing decision is the whole product. `handle_vendor_updated` reads a
supplier's current state and picks the next move — qualify, reject, email, call,
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
        │            Places, YouTube    Telephony
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
| Discovery | search, Maps, read pages | email, call |
| Research | search, read, Maps, YouTube, write evidence | **email, call, spend** |
| Brand evidence | search, read, YouTube, write evidence | **email, call, spend** |
| Communication | draft, send, read mail, place calls | alter scores |
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

Quotes are normalised before comparison, so a vendor quoting `bottle + pump +
cap = Rp 12,000` and one quoting `8,000 / 2,500 / 1,500` compare as equal. A
vendor who has not priced every requested component is reported as
not-comparable rather than as cheapest.

## Gmail integration

`users.watch` points Gmail at a Pub/Sub topic. A supplier replies at 2am, Gmail
pushes a historyId, `/webhooks/gmail` pulls the new message, matches it to the
thread that asked for it, and the mission resumes. No polling, no open browser.

Threads keep asked/answered/unanswered questions, so a follow-up asks only what
is still missing.

## Voice integration

Telephony dials and transcribes; Gemini decides everything else. The call agent
opens by identifying itself as an AI assistant, asks at most five questions
ordered so an early hangup still helps, and never negotiates or commits.

A call happens when the agent decides one is warranted — a conflict that email
already failed to settle, no email address on file, or a supplier who has gone
quiet — never as a default. Budgeted per mission and per vendor.

## Google Cloud

Cloud Run (scale to zero), Firestore, Pub/Sub with dead-lettering, Cloud Tasks,
Vertex AI, Secret Manager, Cloud Logging. All provisioned by OpenTofu in
`terraform/` — `plan` is the review surface, nothing is created by hand.

## Cost

A mission is **40–60 model calls, roughly $0.05–$0.08** (about Rp 800–1,300) on
`gemini-2.5-flash`, measured from the API's own token counts and readable per
mission at `/api/missions/{id}` → `spend`.

Every mission carries a hard stop: reaching `VDS_MAX_USD_PER_MISSION` or
`VDS_MAX_MODEL_CALLS_PER_MISSION` fails it with a reason rather than spending
more, and that failure is deliberately **not retried**. The ADK research loop is
capped at 12 calls against ADK's default of 500 — that gap was the largest
unattended-spend risk in the system.

Thinking tokens are billed as output, so the fast tier runs with a thinking
budget of zero; on a measured mission that cut cost per call by about 60%.

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

## Local development

**You do not need a Google Cloud project to run this.** With
`VDS_USE_SCRIPTED_MODEL=true` the entire system — console included — runs with
no credentials and no network. The agents, events, storage, conflict detection
and scoring are the real ones; only the text generation is deterministic.

```bash
./run.sh            # installs what is missing, then starts the API and console
./run.sh demo       # one whole mission in the terminal, ~30s
./run.sh test       # 208 tests, ~10s
./run.sh status     # what is running, and what it has spent
./run.sh stop
```

`./run.sh` needs Python 3.12 or 3.13 and Node 20+, and nothing else — no Google
Cloud project, no API key, no network.

To use real Gemini: set `VDS_PROJECT_ID` in `backend/.env`, run
`gcloud auth application-default login`, then `./run.sh live`. It refuses to
start if either is missing rather than failing halfway through a mission.

**[docs/LOCAL.md](docs/LOCAL.md)** has the full walkthrough — what to click,
what to look for, and what to do when something breaks.

## Deployment

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # set project_id and image
cp backend.hcl.example backend.hcl             # set your state bucket
tofu init -backend-config=backend.hcl
tofu fmt && tofu validate && tofu plan         # review before applying
tofu apply
```

Then set the service's own URL so it can build webhook callbacks — `tofu output
next_steps` prints the exact command.

## Environment variables

Everything is `VDS_`-prefixed and read only in `app/config.py`.

| Variable | Default | What it does |
| --- | --- | --- |
| `VDS_MODE` | `demo` | which product integrations: `demo` binds mocks, `live` binds Google APIs |
| `VDS_USE_CLOUD_INFRA` | `false` | Firestore/Pub/Sub/Cloud Tasks vs in-process. Independent of `VDS_MODE` |
| `VDS_APPROVAL_POLICY` | `external` | `autonomous` \| `external` \| `strict` |
| `VDS_PROJECT_ID` | — | Google Cloud project for Vertex AI and Firestore |
| `VDS_REASONING_MODEL` | resolved | empty = newest reachable model on the ladder |
| `VDS_FAST_MODEL` | resolved | cheap model for extraction and classification |
| `VDS_MAPS_API_KEY` | — | Places. Unset degrades to demo data, and says so |
| `VDS_SEARCH_API_KEY` / `VDS_SEARCH_ENGINE_ID` | — | Programmable Search; unset falls back to Gemini grounding |
| `VDS_YOUTUBE_API_KEY` | — | YouTube Data API |
| `VDS_TWILIO_*` | — | telephony; unset means calls run against the mock |
| `VDS_MAX_CALLS_PER_MISSION` | `3` | cost guard |
| `VDS_MAX_CONCURRENT_RESEARCH` | `3` | caps the widest fan-out so a mission cannot rate-limit itself |
| `VDS_MAX_USD_PER_MISSION` | `0.50` | hard stop — the mission fails with a reason rather than spending more |
| `VDS_MAX_MODEL_CALLS_PER_MISSION` | `120` | hard stop |
| `VDS_MAX_RESEARCH_LLM_CALLS` | `12` | ceiling on one ADK tool loop (ADK's own default is 500) |
| `VDS_FAST_THINKING_BUDGET` | `0` | thinking is billed as output and buys nothing on extraction |
| `VDS_MAX_OUTREACH_PER_MISSION` | `12` | cost guard |
| `VDS_DEMO_SPEEDUP` | `1.0` | compresses scheduled delays in demo mode only |
| `VDS_USE_ADK_RESEARCH` | `true` | research as an ADK tool loop; off falls back to pre-fetching |

A missing key never fails the mission — the provider degrades to its mock and
the substitution is reported at `/api/health`, so a demo can never quietly claim
to have called a Google API it did not call.

## Testing

```bash
.venv/bin/python -m pytest -q     # 190 tests, ~8 seconds, no network
```

- **Unit** — evidence classification, identity resolution, quote normalisation,
  conflict detection, scoring, number parsing, policy, injection defence, and
  the ADK tool guard.
- **Integration** — the whole workflow over the real event bus, plus the HTTP
  surface with a `TestClient`.
- **Failure** — every message delivered twice, search outage, Maps timeout,
  blocked pages, call failure, model timeout, rate limiting, Cloud Run restart
  mid-mission, events for records that no longer exist, and a supplier reply
  containing a prompt-injection payload.

The redelivery test runs the entire mission with a 100% duplicate rate and
asserts no supplier is emailed twice.

## Demo

```bash
.venv/bin/python scripts/run_demo.py
```

Two modes, one workflow. `demo` binds mock providers that raise **real**
`email.received` and `call.completed` events through the real bus on a
compressed clock; `live` binds Gmail and telephony. The agents, the events, the
storage and the scoring are identical — only the adapter differs. There are no
UI-only results anywhere in this repo.

Demo data is synthetic and marked as such. Every company, brand and quote is
invented, and every domain is under the reserved `example.com`.

## Limitations

- **Model generation.** The hackathon asks for Gemini 3.5 or newer. The project
  this was built against can only reach Gemini 2.5 on Vertex AI — run
  `scripts/check_models.py` to see what any given project resolves to. The model
  id is configuration, not code: a project with 3.5 access picks it up
  automatically from the ladder in `app/config.py`, with no changes.
- Live web research is only as good as what suppliers publish, which in this
  industry is often a phone number and a WhatsApp link.
- The voice agent handles a scripted question list, not an open negotiation.
- Currencies are never converted. Quotes in different currencies are reported
  side by side and excluded from the price comparison rather than guessed at.
- The console polls every two seconds rather than streaming; server-sent events
  would be better and were not necessary to prove the workflow.
- One vertical's vocabulary (perfume) is encoded in the quote normaliser's
  component aliases. Another vertical needs its own alias table.

## Future work

- Sample tracking: a quotation is not a supplier until a sample arrives.
- Negotiation memory across missions, so a second product benefits from the
  first product's relationships.
- Supplier-side portal, so a supplier answers a structured form once instead of
  the same eight questions from every buyer.
