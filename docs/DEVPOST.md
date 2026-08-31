# 🧭 SupplyMe Hackathon Journey

> Paste-ready **About the project** copy for the Google × Devpost
> *All Things Agentic* hackathon, category **The Taskmaster**. Devpost renders
> block LaTeX but not inline, so the formulas below are display blocks.

**Tagline**: A multi-agent sourcing system that turns three weeks of manual
supplier hunting into one autonomous mission, from planning the supply chain to
emailing factories, chasing replies for days, and ranking what comes back with
a source behind every number.

## Inspiration

I was trying to get 500 units of a 50ml fragrance made in Indonesia, on a
first-batch budget. The B2B marketplaces failed me. The best factories were not
listed, the ranking sorted by ad spend rather than by who accepts a 500-unit
order, and every number on every profile was a form field somebody filled in
once.

So I did it by hand for **three weeks**. I opened 41 tabs and read supplier
sites in three languages, hunting for a minimum order quantity most of them
never published. I built a spreadsheet where the MOQ column said `?` in nine
rows. I emailed the same eight questions one supplier at a time, and got back
answers to four.

Then I found two suppliers who both claimed the same major fragrance brand as a
customer. **One of them was lying, and I had no way to tell which.**

No scraper fixes that, because **sourcing information is *disclosed*, never
published**. Differently to different people, inside a negotiation. No dataset
holds real minimum order quantities. You learn a supplier's by asking them, and
you learn whether the answer holds by finding somebody other than them saying
it.

That is **two jobs**: investigate what a factory publishes, then wait days for
the reply to what it does not. Search does neither. A chatbot stops existing
when you close the tab. **An agent that persists, remembers and resumes does
both.**

**So I decided to automate the whole job.**

## What it does

SupplyMe turns *"I want to make this product"* into a **qualified supply
network**. What took me three weeks by hand runs as **one autonomous mission**
you start and walk away from, and every number it returns carries the source it
came from.

- 🧩 **Plans the Supply Chain**: Decomposes a product into the components and processes it needs, derived per mission rather than from a fixed list
- 🔍 **Finds Real Manufacturers**: Searches the open web and Google Maps in parallel, reaching factories no directory lists
- 🧠 **Researches Each Supplier**: An agent chooses which page to read next based on what the last one said, and quotes what it finds
- 📬 **Asks What It Cannot Find**: Emails suppliers the open questions, then resumes the mission days later when a reply lands
- ⚖️ **Resolves Contradictions**: When a website and an email disagree, it puts both numbers back to the supplier and re-scores on the answer
- 🏅 **Ranks With Evidence**: Every fact carries its source, and every score is arithmetic a buyer can read

| By hand | One mission |
| --- | --- |
| 41 tabs open across three languages | Every component searched in parallel |
| Nine minimum-order cells left as `?` | The open questions emailed to the factory |
| Eight questions asked, four answered | Contradictions put back to the supplier and re-scored |
| Three weeks | Start it and close the tab |

## How we built it

**🏗️ Architecture & Scale**
- 7 specialized agents on Google ADK and Gemini 3.5 Flash
- 1 persisted event loop, so a restart mid-mission loses nothing and a reply three days later resumes the same work
- 4 deterministic engines for evidence, quotes, conflicts and scoring, holding every number the model may not produce
- 6 ports and adapters, each bound to a live service, with no demo mode anywhere in the system
- 484 tests covering duplicate delivery, provider outages, restarts and prompt injection

**🛡️ Security Boundary**
- Every agent carries a tool allowlist, enforced on each call rather than described in a prompt
- The two agents that read attacker-controlled web pages hold no tool that reaches the outside world
- The console proxies every request server-side, so no credential reaches the browser

**📐 The Model Extracts, Engines Decide**

Gemini supplies structured facts and never supplies a confidence, a ranking or
a score. Evidence confidence is a noisy-OR with geometric decay, so each
corroborating source counts for less than the one before it:

$$
C \;=\; \min\Bigl(1 - \prod_{i=0}^{n-1}\bigl(1 - w_i\,\delta^{\,i}\bigr),\; C_{\max}\Bigr)
\qquad \delta = 0.55,\quad C_{\max} = 0.97
$$

| Source | Weight |
| --- | --- |
| The supplier's own email | `0.90` |
| The brand's own website | `0.85` |
| The supplier's website | `0.75` |
| **A directory listing** | **`0.45`** |
| A bare search result | `0.30` |

Twenty directory listings copying one press release therefore score lower than
the manufacturer's own spec sheet. **That directory weight is the marketplace
problem written as a constant.**

Ranking is a weighted sum over price, minimum order fit, capability, lead time,
evidence strength and logistics:

$$
S \;=\; 100 \sum_{j} w_j\, r_j,
\qquad \sum_j w_j = 1,\qquad r_j \in [0,1]
$$

Ask for less risk on a first batch and weight moves onto order-size fit. The
explanation moves with it, because the explanation **is** the calculation:
`MOQ 500 fits an order of 500`, never a progress bar.

**🛠️ Technology Stack**
- Google Agent Development Kit (ADK)
- Gemini 3.5 Flash on Vertex AI
- Cloud Run, Firestore, Pub/Sub, Cloud Tasks, Cloud Scheduler
- Secret Manager and Cloud Logging
- Google Maps Places, Gmail, SMTP and IMAP
- FastAPI, Python 3.12 and Pydantic
- Next.js, React, TypeScript and Tailwind
- OpenTofu and Docker

## Challenges we ran into

Building a system this complex presented significant challenges:

**⏳ Orchestrating a Workflow That Runs for Days**
Most of a sourcing mission is spent waiting on a human in another timezone.
Keeping full context alive across restarts, retries and replies that land three
days later required an event-sourced orchestrator where every stage persists
before the next one begins, plus an idempotency key on every outbound action so
duplicate delivery can never email a supplier twice.

**🌍 Building a Domain-Agnostic Planner**
Our first version carried one industry's vocabulary inside it, which worked for
fragrance and collapsed on furniture. Teaching the planner to derive its own
component vocabulary per mission, in whatever language the suppliers use, meant
stripping out every fixed term and letting the model generate the taxonomy that
discovery then searches on.

**🔒 Enforcing a Security Boundary Inside an Agent Loop**
Our research agents read supplier webpages, which are attacker-controlled by
definition. We evaluate a per-agent tool allowlist on every call inside the ADK
loop, return each denial to the model as a result so it keeps working instead
of derailing, and sanitize hostile content before the model ever sees it.

**💸 Governing Autonomous Spend**
An agent reading whole webpages under a 500-call default ceiling can run a
serious bill unattended. Real cost governance meant metering every call from
the API's own token counts, enforcing ceilings on both the research loop and
the mission, and pricing an unrecognised model at the most expensive rate so
the budget can never under-report.

**⚖️ Reconciling Contradictory Evidence**
A supplier's website and their email often disagree, and averaging them would
produce a number nobody said. We built deterministic engines that weight
evidence by where it came from, decay repeated corroboration so twenty copies
of one press release cannot outvote a spec sheet, and put both numbers back to
the supplier in a single follow-up.

## Accomplishments that we're proud of

**🏆 Technical Achievements**
- Orchestrated 7 specialized agents through a persisted event loop that survives restarts and resumes days later
- Implemented a per-call tool allowlist that holds every agent inside its permissions, even under prompt injection
- Built deterministic evidence and scoring engines that keep every number out of the model's hands
- Provisioned the entire cloud footprint as reviewed infrastructure code, rebuilding from zero without a console click

**💼 Business Impact**
- Created a system that replaces three weeks of manual sourcing with one mission you can walk away from
- Demonstrated real generality by planning a fragrance line, an oak dining table and a USB-C power bank with the same code
- Answered the question buyers actually ask, where every number came from, down to the sentence that said it
- Measured true cost from the API's own token counts rather than estimating it: eight suppliers for $0.29

**🎨 User Experience**
- Developed a console where every fact clicks through to its excerpt, its source and the time it was read
- Created rankings that explain themselves in the arithmetic that produced them
- Built a live mission timeline that shows each agent's decision as it happens

## What we learned

**🤖 Agentic Architecture**
The instinct to reach for a bigger prompt is almost always wrong. Six of our
seven agents are single structured calls, because the workflow decides what
happens next and the model only fills in shape. One stage, choosing which
source to read next, genuinely needs a tool loop, and that is where ADK earns
its keep. Knowing where not to put the agent was our highest-leverage decision.

**⚖️ Keep Judgment Out of the Model**
Ask a model to rate its own confidence and you get a number that responds to
phrasing. Compute it from source identity and you get one that responds to
evidence. Once we drew that line, explainability stopped being a feature we had
to build and became a property we got for free.

**💰 Cost Is an Architectural Decision**
We learned to treat spend as a design constraint rather than a bill you read
later. Reasoning tokens bill as output and extraction does not need them, so
turning the thinking budget off on our fast tier cut per-call cost by around
60% with no loss of quality. Metering every call from the API's own token
counts made cost something we could cap, test and publish rather than something
we discovered at the end of the month.

**☁️ Google Cloud as an Agent Runtime**
We learned what a serverless stack gives an agent that a plain server cannot.
Cloud Run scales to zero, so an agent waiting three days on a factory costs
nothing while it waits. Push subscriptions keep the mission moving with every
browser closed. Scheduled tasks turn a follow-up four days out into a fact the
platform holds rather than a process somebody has to keep alive. One mission
can span a week without a machine staying up for it.

**⚠️ What We Would Tell a Reviewer to Distrust**
- Replies arrive on a poll rather than a push, because we never finished the mail consent screen
- Search runs through Gemini grounding, since we never configured a custom search engine
- Quotes in different currencies sit side by side and stay out of the comparison rather than being guessed at
- The spend cap is a stop, not a to-the-cent limit; one mission whose ceiling fired finished slightly above it

## What's next for SupplyMe

**🔮 Immediate Enhancements**
- **Sample Tracking**: Close the loop from recommendation to physical outcome, because a quotation is not a supplier until a sample arrives
- **Currency Handling**: Add a dated exchange-rate source stamped into the provenance record, replacing today's refusal to compare across currencies
- **Streaming Console**: Replace the two-second poll with push, so a mission updates the moment an event lands
- **Gmail Push Delivery**: Finish the inbound consent screen so supplier replies arrive by push rather than on a fifteen-minute poll

**🚀 Long-term Vision**
- **Negotiation Memory**: Let a second product benefit from the first product's relationships, from who answered in six hours to who flexed on minimums once trust was established
- **Supplier-Side Portal**: Let a factory answer a structured form once instead of the same eight questions from every buyer, turning a scraping problem into a network
- **Multi-Tier Discovery**: Ask the bottle supplier who supplies their glass, because depth is where real supply-chain risk hides
- **Sourcing Dataset**: Turn every mission into verified minimums, prices and lead times that no public dataset holds, compounding into a benchmark buyers can price against

**🌟 Platform Evolution**
- **Local-Market Support**: Read contact details, phone formats and currencies the way each market publishes them, rather than defaulting to American conventions
- **Messaging Channels**: Reach factories on WhatsApp, where much of this industry publishes a link instead of an address
- **Adjacent Domains**: Point the same decompose, investigate, ask and rank loop at vendor selection, partner due diligence and grant sourcing

SupplyMe is only the first problem we have pointed this at. Google's AI and
cloud stack is what made an autonomous version of it possible, and we're
excited to keep pushing how much real work an agent can take off a person's
hands, in sourcing and well beyond it!

## Bonuses

- **📝 Published Build Content (+0.2)**: a public post, podcast or video about building SupplyMe `[link]`
- **📣 Social Post (+0.2)**: a public post carrying **#AllThingsAgenticHackathon** `[link]`
- **🧠 Additional Google AI Models (+0.2 each, max +0.6)**: SupplyMe runs on Gemini 3.5 Flash alone today; Gemma, Veo or Lyria would each add a point

## Built With

Python, FastAPI, Google ADK, Google Gemini, Vertex AI, Pydantic, Firestore, Google Cloud Pub/Sub, Google Cloud Tasks, Cloud Run, Cloud Scheduler, Secret Manager, Google Places API, SMTP, IMAP, Next.js, React, TypeScript, Tailwind CSS, OpenTofu, Docker, Pytest

**✅ Required technology**: Gemini 3.5 Flash on Vertex AI, Google ADK as the
agent framework, and Cloud Run, Firestore and Pub/Sub as the infrastructure.

## Try it out

- 🖥️ **Live console**: https://supply-me-console-6eilzjvuba-uc.a.run.app
- 🩺 **Live health check**: https://supply-me-6eilzjvuba-uc.a.run.app/api/health
- 💻 **Source**: https://github.com/fillateo/SupplyMe
- 🎬 **Demo video**: `[YouTube link]`

---

## Updates

> Posted from the **Updates** tab, separate from *About the project*.

**Update 1**
Started SupplyMe for the All Things Agentic hackathon, in the Taskmaster
category. Tell it what you want made and it comes back with a qualified supply
network, with a source behind every number. Leave feedback in the comments.
