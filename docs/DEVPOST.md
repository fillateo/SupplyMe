# SupplyMe — Devpost submission copy

> Paste-ready **About the project** write-up for the Google × Devpost
> *All Things Agentic* hackathon, category **The Taskmaster**.
> Devpost renders Markdown and LaTeX; the math below is written for that.

---

## Inspiration

A friend of ours was trying to get a product made. 500 units of a 50ml
fragrance, manufactured in Indonesia, on a first-batch budget — his first real
production run.

He started where everybody starts: the big B2B sourcing marketplaces. He had
accounts on several. They did not solve it — and the specific ways they failed
him turned out to be the specification for what we built.

* **The suppliers he most wanted were not on them.** Listing presence tracks
  marketing budget, not manufacturing quality. A factory already running OEM
  lines for established brands is booked through referral and has no reason to
  pay for a directory profile. The best candidate he eventually found had a
  local-language website, a WhatsApp number, and no marketplace listing at all.
* **The ranking answered a different question than his.** What surfaces at the
  top is a function of membership tier and ad spend. Nothing in that ordering
  knows his order is 500 units, or that a plant tooled for 50,000 is a polite
  no.
* **Many of the "manufacturers" were not manufacturers.** Trading companies and
  sourcing agents list identically to the plant itself. The difference reveals
  itself around the third email — after he had already spent the three emails.
* **The numbers on the listings were decorative.** `MOQ: 1000`.
  `$0.50 – $5.00`. Fields filled to satisfy a form, not to inform a buyer.
  Every number he could actually plan against still had to be asked for.
* **Claims were self-reported, and nothing checked them.** "We supply [major
  brand]" is a text box. Certifications are uploaded images. This is exactly
  where his two identical brand claims came from.
* **And it was still one supplier at a time.** The platform's contribution was
  a contact form. Sending the inquiry, chasing the silence, and reconciling
  eight inconsistent replies into something comparable remained his job,
  unchanged. The bulk-RFQ feature produced volume, not qualification — mostly
  an inbox of pitches from suppliers who had not read the request.

**The platform did not remove the work. It moved where the work started, then
handed it back.**

So we watched him do it by hand for three weeks.

He searched. He opened tabs — at one point 41 of them — and read supplier
websites in three languages looking for a minimum order quantity that was
usually not on the page. He curated: a spreadsheet where every promising
factory got a row, and where the MOQ column said `?` in nine of them. He
emailed, one supplier at a time, the same eight questions, and then re-asked
half of them a week later because the replies came back answering four. He
tried to rank what came back, except one quote was per-piece, one was a bundle,
and one was in a currency he had to look up. And through all of it he was
trying to match what he found against what he actually needed — *does this
factory take 500 units, or is 500 an insult to them?*

Then he showed us two suppliers who both claimed the same major fragrance brand
as a customer. One of them was telling the truth. He had no way to tell which,
and neither did we.

That was the moment the problem became legible. **Sourcing information is not
published — it is *disclosed*.** Differently, to different people, inside a
negotiation. There is no dataset of real minimum order quantities. There is no
API for "will this factory actually take a 500-unit pilot run." The only way to
learn a supplier's real MOQ is to ask them, and the only way to know whether
their answer holds is to find somebody *other than them* saying it.

Look at what he was actually doing, and it is not one job. It is two, and no
existing tool covers them together:

1. **Investigation** — read what a supplier publishes, and find out who else
   corroborates it.
2. **Waiting** — send the questions that research cannot answer, and be
   present, days later, when a reply lands at 2am.

Search engines do neither. A chatbot does the first badly and cannot do the
second at all, because the moment you close the tab it stops existing. And the
part that cost our friend three weeks was almost entirely the second one —
wall-clock time spent waiting on a human, then reconstructing where he had been
when they finally answered.

**But an agent that persists, remembers, and resumes can do both.** That is the
entire thesis of SupplyMe: give it the objective he had in his head, and get
back the spreadsheet he was building by hand — with a source behind every cell.

## What it does

SupplyMe turns *"I want to make this product"* into a **qualified supply
network** — and reports where every single number came from.

Everything our friend did by hand for three weeks, the system does as one
mission it can be left alone to run: **search, curate, email, chase, rank,
match.**

* **🧩 Decomposes the product into a supply chain.** "A 50ml EDP" becomes
  bottle, pump, cap, label, filling. "A solid oak dining table" becomes FSC oak
  lumber, hardware, protective coating, flat-pack packaging, woodworking. The
  system has no idea what a bottle is — the decomposition is derived, per
  mission, from the product itself.
* **🔍 Finds real manufacturers in parallel.** Every supply-chain node is
  searched at once against the open web and Google Places — **not a directory
  index** — so the factory with a local-language site, a WhatsApp number and no
  marketplace profile is reachable. Results are then **identity-resolved**: the
  same factory listed under three names collapses into one supplier, and a
  trading company reselling that factory is evidence about the factory rather
  than a second candidate.
* **🧠 Researches each one agentically.** A Google ADK `LlmAgent` picks which
  page to read next *based on what the last page said*, and stops when it can
  answer. In one live run it read the homepage, decided it needed the product
  page, searched for the MOQ, and returned `moq = 500` quoted verbatim — with
  `unit_price` and `lead_time_days` correctly reported as **missing**.
* **📬 Emails what it could not find out.** Those missing fields become a
  targeted message to a real business, sent over real SMTP. Replies re-enter
  the workflow days later via `In-Reply-To` and resume the same mission.
* **⚖️ Resolves contradictions instead of averaging them.** Website says MOQ
  500, email says 1,000? SupplyMe puts *both numbers back to the supplier* in
  one follow-up — *"your published minimum is 500 but we were quoted 1,000 — is
  500 possible as a pilot?"* — and re-scores on the answer.
* **🏅 Ranks with a number it can defend line by line.** Never a model score.
  Every fact carries a provenance state — `verified`, `direct quote`,
  `published`, `inferred`, `sources differ`, `unknown` — and every fact in the
  console is clickable through to the verbatim excerpt, the URL, and the
  retrieval timestamp.

Two suppliers claiming the same brand are **never reported as the same thing**
again. One is corroborated by the brand's own site and a trade publication. The
other is the supplier's word and nothing else. That distinction is the product.

## How we built it

### 🏗️ An event-sourced workflow, not one long prompt

Nothing in SupplyMe is a single sprawling LLM call. The orchestrator is a
**persisted event loop**: each stage emits an event, the event is stored, a
handler picks it up and emits the next one. `handle_vendor_updated` in
`app/workflow/handlers.py` reads a supplier's current state and picks the next
move — qualify, reject, email, or wait — and none of that is scripted by the
user.

The payoff is operational, not aesthetic: **a Cloud Run restart mid-mission
loses nothing**, and a supplier replying three days later resumes the same
mission from the same state. Every message may be delivered twice; every
external action reserves an idempotency key on
`mission + vendor + action + version` first, so **no supplier is ever emailed
twice**.

### 🤖 Seven agents with an executed security boundary

| Agent | May | May not |
| --- | --- | --- |
| **Mission** | read objective, write vendors | search, read, email, spend |
| **Supply chain** | decompose | any tool at all |
| **Discovery** | search, Maps, read pages, write vendors | email |
| **Research** | search, read, Maps, write evidence, write vendors | **email, spend** |
| **Brand evidence** | search, read, write evidence | **email, spend** |
| **Communication** | draft, send, read mail, write evidence (recording an extracted quote) | alter scores |
| **Recommendation** | write scores | send anything |

ADK's `before_tool_callback` evaluates this allowlist on every single tool
invocation **inside the Research agent's ADK loop** (`app/agents/adk_research.py`)
— the one place an agent chooses its own tool calls — and a denial is returned
to the model as a *result*, so the agent carries on with the tools it does hold
instead of derailing. The other six agents are single structured calls with no
tool loop to intercept; their allowlist in `app/domain/policy.py` is a contract
enforced by code structure — the handler is the only thing that touches a
provider — and held to the same table by `tests/test_security_policy.py`.

Read that table again with an attacker in mind. The two agents that ingest
attacker-controlled content — Research and Brand Evidence — hold **no tool that
can reach the outside world**. If a supplier's webpage convinces the model of
something, the worst possible outcome is a bad claim recorded in the database,
which the evidence engine then rates on its source and discounts.

### 📐 The model extracts; deterministic engines decide

This was our hardest architectural line, and we held it: **Gemini supplies
structured facts and never supplies a confidence, a ranking, or a score.**

Evidence confidence is a noisy-OR over per-source weights with geometric decay,
so the $n$-th corroborating source counts for less than the one before it:

$$
C \;=\; \min\!\Bigl(1 - \prod_{i=0}^{n-1}\bigl(1 - w_i\,\delta^{\,i}\bigr),\; C_{\max}\Bigr)
\qquad \delta = 0.55,\quad C_{\max} = 0.97
$$

where $w_i$ is the source weight of the $i$-th strongest piece of evidence —
$0.90$ for a supplier email, $0.85$ for the brand's own website, $0.75$ for the
supplier's site, $0.45$ for a directory listing, down to $0.30$ for a bare
search result. **That directory number is the marketplace problem written as a
constant**: a paid profile is admissible evidence and it is not strong
evidence, and the system is not permitted to forget the difference.

That decay term is doing real work. **Twenty directory listings all copying one
press release score lower than the manufacturer's own spec sheet**, which is
exactly backwards from what a naive count would produce. And $C_{\max} = 0.97$
encodes an honest position: nothing read off the public web is ever certain.

Ranking is the same discipline — a weighted sum where each component carries the
sentence that produced it:

$$
S \;=\; 100 \sum_{j} w_j\, r_j,
\qquad \sum_j w_j = 1,\qquad r_j \in [0,1]
$$

with defaults $w_{\text{price}} = w_{\text{MOQ}} = w_{\text{capability}} = 0.20$,
$w_{\text{lead time}} = w_{\text{evidence}} = 0.15$, $w_{\text{logistics}} = 0.10$.
State *"minimize risk on the first batch"* and weight moves onto MOQ fit and off
price. The explanation moves with it, because the explanation **is** the
computation: `MOQ 500 fits an order of 500`, not a progress bar.

### ☁️ The stack

* **Agents & models** — Google ADK, Gemini 3.5 Flash on Vertex AI, Pydantic v2
  structured output
* **Backend** — Python 3.12, FastAPI, a ports-and-adapters core where `app/`
  depends on no vendor SDK
* **State & messaging** — Firestore, Pub/Sub push with dead-lettering, Cloud
  Tasks for follow-ups and retries
* **The outside world** — Google Programmable Search, Google Places, and the
  mailbox: SMTP out and IMAP in on a single app password, which is what runs.
  The Gmail API push path is implemented behind the same port and its workflow
  half is exercised on every run, but the OAuth half has never been pointed at a
  live mailbox — so replies arrive on a one-minute Cloud Scheduler poll rather
  than being pushed
* **Console** — Next.js 15, React 19, TypeScript, Tailwind; proxies every API
  call server-side so no credential ever reaches client JavaScript
* **Infrastructure** — Cloud Run (scale to zero), Secret Manager, Cloud
  Logging, all provisioned by **OpenTofu** — `plan` is the review surface and
  nothing was created by hand

## Challenges we ran into

**🌍 We had accidentally built a perfume tool.** This one stung. Late in the
build we pointed SupplyMe at a Vietnamese furniture supplier and watched it
report a supplier who *had* answered as one who had not. The cause was a
hardcoded alias table — one industry's vocabulary, baked into `app/`. A
supplier pricing `papan kayu jati` matched nothing. Worse, a fixed
three-component bundle rule meant any supplier in any other industry who quoted
a single bundled price was **silently uncomparable** rather than loudly
uncomparable. We tore both out. The supply-chain agent now emits a per-mission
**component vocabulary**: point it at a Vietnamese oak table and it comes back
with `gỗ sồi FSC`, `sơn PU`, `phụ kiện ngành gỗ`, `thùng carton`, none of which
appears anywhere in `app/` in any language. It is regenerated per mission, so a
second run words it differently — what is fixed is that the words come from the
plan and not from a table. `app/` ships exactly one piece of vocabulary of its
own: that `set`, `paket` and `kit` all mean `package`, because bundling is a
property of quotations rather than of an industry.

**🔌 A model that exists in one place and 404s in another.** `gemini-3.5-flash`
answers from Vertex AI's `global` endpoint and returns a flat 404 from
`us-central1` — with nothing in the error hinting that the model exists
elsewhere. We lost hours to what looked like a permissions problem. The fix is
three things: a reachability ladder in `app/config.py`, a
`scripts/check_models.py` that tells you the truth for *your* project, and two
separate location settings — because Cloud Tasks, in the opposite direction,
rejects `global` outright.

**💸 An unattended tool loop is a budget incident.** ADK's default cap on an
agent's tool loop is **500 calls**. Ours reads live webpages, which are tens of
thousands of tokens each. At 3am, unwatched, that is not a bug — it is a bill.
We capped the research loop at 12, capped missions at 300 model calls and
$1.00, and made the spend ceiling a **hard failure with a reason that is
deliberately not retried**. Cost is computed from the API's own
`usage_metadata`:

$$
\text{cost} \;=\; \frac{T_{\text{in}}}{10^{6}}\,p_{\text{in}} \;+\; \frac{T_{\text{out}}}{10^{6}}\,p_{\text{out}}
$$

and an unrecognised model prices at the *most expensive* rate in the table —
an unknown model must over-report, never under-report, or the budget stops
protecting anything.

**✉️ The addresses in a mission belong to real businesses.** Read off their
real websites. The distance between a good demo and a written apology is one
environment variable, so we built `SUPPLYME_MAIL_REDIRECT_TO`: every message
genuinely sends, over real SMTP, and states at the top who it *would* have
reached. Real infrastructure, real send path, zero strangers contacted.

**🧪 Testing a system whose main activity is waiting.** Most of a mission's
wall-clock time is a human not replying yet. Our suite drives whole missions
against test doubles that live in `tests/` and are **reachable from nowhere in
`app/`** — so we can provoke a supplier who never answers, or one whose site
contradicts their quote, while the product itself has nothing to fall back to.
386 tests, ~59 seconds, no network.

## Accomplishments that we're proud of

**🔬 Technical.** Every arrow in our architecture diagram is implemented — no
mocked stage, no "coming soon" box. A redelivery test runs an **entire mission
at a 100% duplicate delivery rate** and asserts no supplier is emailed twice.
The failure suite covers search outage, Maps timeout, blocked pages, model
timeout, rate limiting, a Cloud Run restart mid-mission, events for records
that no longer exist, and a supplier reply carrying a prompt-injection payload.

**🎯 Product.** SupplyMe answers the question buyers actually ask — *where did
this number come from?* — with a click-through to verbatim text, a URL, and a
retrieval time. Not a citation-shaped footnote. The excerpt.

**🌐 Generality, proven.** The same unchanged code plans a fragrance line, an
oak dining table, and a USB-C power bank. We didn't claim that; we ran it.

**💰 Honesty about money.** Measured from the API's own token counts, including
the number that is inconvenient. A mission over eight suppliers cost **$0.29
across 98 model calls**. A mission over twelve reached **296 calls and $0.78 and
still had not finished**, because every admitted supplier is a tool loop reading
whole websites — so the shortlist size, not the objective, is the cost knob. We
would rather publish both rows than only the flattering one. Setting the fast
tier's thinking budget to zero cut per-call cost roughly 60%, because thinking is
billed as output and buys nothing on extraction.

**🛡️ Security we can point at.** The tool allowlist runs; the injection defence
sanitizes before the model sees anything; the console proxies server-side. Each
one is a line of code, not a paragraph in a README.

## What we learned

**🤖 Agentic architecture.** The instinct to reach for a bigger prompt is
almost always wrong. Six of our seven agents are single structured calls,
because the *workflow* decides what happens next and the model only fills in
shape. Exactly one stage — deciding which source is worth reading next —
genuinely needs a tool loop, and that is the one place ADK earns its keep.
**Knowing where *not* to put the agent was the highest-leverage design decision
we made.**

**⚖️ Keep judgment out of the model.** Ask a model to rate its own confidence
and you get a number that responds to phrasing. Compute confidence from source
identity and you get a number that responds to *evidence*. Same for scores.
Once we drew that line, "explainability" stopped being a feature we had to
build and became a property we got for free — the explanation is the
calculation.

**⏳ Durability is the actual moat.** The hard part of this problem was never
reasoning quality. It was being alive, with full context, when a factory in a
different timezone finally hits reply. That is an event-sourcing problem, an
idempotency problem, and a Cloud Tasks problem — and it is why this is an agent
and not a very good search.

**☁️ Google Cloud, specifically.** Vertex AI model reachability is a property
of the project *and* the location. Pub/Sub push means the browser can be
closed. Cloud Run scaling to zero means an agent that waits three days costs
nothing while it waits. Cloud Tasks will not accept `global`. These are not
things we read — they are things that broke.

**🚫 One mode, and it is the real one.** We shipped no demo mode. Every
provider is the live service or the process refuses to start and *names the
variable that is missing*. It made the build harder and every result
trustworthy.

## What we would tell a reviewer to distrust

Four things, because a submission that lists only its strengths is asking to be
checked on them:

* **The Gmail push path has never run against a live mailbox.** It is
  implemented, and the workflow half of it is exercised on every test run, but
  the OAuth consent screen was never set up. IMAP polling is what actually runs.
* **Currencies are never converted.** Quotes in different currencies are shown
  side by side and excluded from the price comparison rather than guessed at.
* **Cost scales with the shortlist, not the ambition.** Eight suppliers is $0.29;
  twelve is $0.78 and, in the run we measured, did not reach a recommendation.
  The lever is `SUPPLYME_MAX_VENDORS_PER_MISSION`, and we would rather say so than
  publish only the cheaper number.
* **The API has no authentication.** Cloud Run is deliberately public so a judge
  can open the link. What bounds it is the per-mission spend caps, the outreach
  cap, and the mail redirect — not the door.

## What's next for SupplyMe

**🎯 Immediate**

* **Sample tracking.** A quotation is not a supplier until a sample arrives and
  someone touches it. Close the loop from recommendation to physical outcome.
* **Currency handling.** Today, quotes in different currencies are shown side
  by side and excluded from price comparison rather than guessed at. A dated FX
  source with the rate stamped into the provenance record fixes that honestly.
* **Streaming console.** It polls every two seconds. It should push.

**🚀 Longer term**

* **Negotiation memory across missions.** A second product should benefit from
  the first product's relationships — this factory answered in 6 hours, that
  one needed two follow-ups, this one flexed on MOQ once trust was established.
* **A supplier-side portal.** So a supplier answers a structured form *once*
  instead of the same eight questions from every buyer who finds them. That
  turns a scraping problem into a network.
* **Multi-tier discovery.** Ask the bottle supplier who supplies *their* glass.
  Depth is where real supply-chain risk hides.

**🌍 Platform**

The pattern generalizes past sourcing: **decompose a goal, investigate against
the live web, ask humans only what research cannot answer, resolve
contradictions, and rank with math you can read.** Procurement was our proof.
Vendor selection, partner due diligence, and grant sourcing are the same shape
of problem — and all of them are currently done by someone with 41 tabs open.

---

## Built With

Python, FastAPI, Google ADK, Google Gemini, Vertex AI, Pydantic, Firestore, Google Cloud Pub/Sub, Google Cloud Tasks, Cloud Run, Secret Manager, Google Places API, Google Programmable Search, Gmail API, SMTP, IMAP, Next.js, React, TypeScript, Tailwind CSS, OpenTofu, Terraform, Docker, Pytest, HTTPX

<details>
<summary>Plain list for the Devpost tag field (25 tags)</summary>

```
python
fastapi
google-adk
google-gemini
vertex-ai
pydantic
firestore
google-cloud-pubsub
google-cloud-tasks
cloud-run
secret-manager
google-places-api
google-programmable-search
gmail-api
smtp
imap
next.js
react
typescript
tailwindcss
opentofu
terraform
docker
pytest
httpx
```

</details>
