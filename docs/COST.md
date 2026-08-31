# What this costs, and what stops it

Written against a fixed prepaid balance. The numbers below are measured from the
API's own `usage_metadata`, not estimated.

## Measured

Two missions against the live web, on `gemini-3.5-flash`:

| Suppliers admitted | Model calls | Input tokens | Cost | Outcome |
| --- | --- | --- | --- | --- |
| 8 | 98 | 562,287 | **$0.29** | reached a recommendation |
| 12 | 296 | — | **$0.78** | stopped at `awaiting_response`, no recommendation |

**The second row is the one to plan against.** Cost tracks how many suppliers get
researched, not how ambitious the objective is, and the default
`SUPPLYME_MAX_VENDORS_PER_MISSION=12` will spend most of a $1.00 cap before the
first reply arrives. Lower it to 5 on a fixed balance.

**Input tokens are almost the whole bill**, and reading real pages is why: a
supplier's website runs to tens of thousands of tokens, and the research agent
reads several per supplier. Output is a twentieth of it, because what the model
returns is a filled-in schema.

The same mission measured against fixtures came to 87,000 input tokens and
$0.09. That threefold gap is not drift — it is the difference between reading a
paragraph and reading a website, and it is the reason the ceilings below are
where they are.

The effect of capping thinking, measured earlier on `gemini-2.5-flash`:

| | output tokens per call | USD per call |
| --- | --- | --- |
| thinking left on (Gemini's default) | 1,222 | $0.0033 |
| thinking capped (what ships) | 405 | $0.0013 |

Thinking tokens are billed as output. For extraction and classification — reading
a price out of an email, deciding whether a search result is a manufacturer —
they buy nothing, so the fast tier gets a budget of zero and the reasoning tier
gets a bounded allowance. That change alone cut cost per call by about 60%.

At a shortlist of eight a mission lands around **100 model calls**, so
**$0.25–$0.35**, or **Rp 4,000–5,700** at 16,400 IDR/USD. At twelve it is closer
to **$0.80 / Rp 13,000**.

Check any mission's actual spend:

```bash
curl -s localhost:8080/api/missions/$MID | jq .spend
curl -s localhost:8080/api/health | jq .spend        # process total, and the caps
```

## What actually stops spending

A budget alert emails you; it does not stop anything. These do:

| Guard | Default | Stops |
| --- | --- | --- |
| `SUPPLYME_MAX_USD_PER_MISSION` | `1.00` | the mission, with a reason on the record |
| `SUPPLYME_MAX_MODEL_CALLS_PER_MISSION` | `300` | the mission |
| `SUPPLYME_MAX_RESEARCH_LLM_CALLS` | `12` | one research agent's tool loop |
| `SUPPLYME_MAX_CONCURRENT_RESEARCH` | `3` | how many run at once |
| `SUPPLYME_MAX_CONCURRENT_MODEL_CALLS` | `4` | Gemini requests in flight, process-wide |
| `SUPPLYME_MIN_MODEL_CALL_INTERVAL_SECONDS` | `0` | how fast the queue drains |
| `SUPPLYME_MAX_OUTREACH_PER_MISSION` | `12` | emails |
| `SUPPLYME_MAX_VENDORS_PER_CATEGORY` | `8` | how many suppliers get researched |
| `SUPPLYME_MAX_EVENT_RETRIES` | `5` | retrying a failing handler forever |

Reaching a spend cap raises `BudgetExceeded`, which the orchestrator treats as
**terminal, not retryable** — retrying is precisely what the cap exists to
prevent. The mission's `failure_reason` says which cap and what it had spent.

### The one that mattered most

Google ADK defaults `max_llm_calls` to **500 per agent run**. A research agent
needs about five. Five vendors researching at 500 calls each is 2,500 model
calls for one mission — on the order of $8 with thinking on, and it would happen
silently. `SUPPLYME_MAX_RESEARCH_LLM_CALLS=12` is the ceiling that prevents it, and
`tests/test_cost.py` asserts the shipped default stays an order of magnitude
below ADK's.

Hitting that ceiling is **not a failure**. The loop stops, whatever it already
read becomes the record, and the supplier is scored on a thinner set of sources.
An earlier version raised instead, which meant the orchestrator retried the
event — spending another twelve calls to reach the same wall, five times over,
before failing the whole mission over one chatty agent.

### Counting what the tool loop spends

ADK's research loop builds its own client, so for a while its calls were
invisible to the meter: a mission would report fifteen model calls having made a
hundred and fifty. Both halves of that are now closed —
`app/agents/adk_research.py` routes ADK through the same throttle **and** the
same `CostMeter`, attributing each turn to the mission that caused it. If your
`estimated_cost_usd` looks implausibly low, that is the first thing to check.

### Search is a model call too

With no Programmable Search engine configured — the default, and what the
deployment runs — every web search is a Gemini call with search grounding. For a
while those sat outside both the gate and the meter, so a mission's reported
spend excluded most of the calls it made. Both are closed now:
`GoogleSearchProvider._grounded` takes a slot on the same throttle and records
against the same `CostMeter`, attributed through `gemini_llm.current_mission`.

### Rate limits are a queueing problem

A project with no provisioned Vertex throughput answers 429 to most of a burst,
and retrying the burst reproduces it. `SUPPLYME_MAX_CONCURRENT_MODEL_CALLS` bounds
how many requests exist at once across every agent, and
`SUPPLYME_MIN_MODEL_CALL_INTERVAL_SECONDS` spreads what is left. On a small quota,
`2` and `1.0` turn a storm into a queue. If a mission still cannot finish, set
`SUPPLYME_USE_ADK_RESEARCH=false`: the pre-fetching research agent makes **one**
metered call per supplier instead of up to twelve, at the cost of the agent
choosing its own sources.

## Costs that are not the model

| Service | On this workload |
| --- | --- |
| Cloud Run | Scale-to-zero, `cpu_idle = true`. A mission waiting two days for a supplier holds no instance. The one-minute mailbox poll wakes it briefly and does no work when nothing is new. |
| Firestore | Thousands of small documents. Well inside the free tier. |
| Pub/Sub | Tens of messages per mission. Free tier. |
| Cloud Tasks | One task per follow-up. Free tier. |
| Cloud Build | A few minutes per deploy. Free tier covers roughly 100 builds/month. |

The realistic risk on a small balance is Vertex AI. Everything else stays in the
free tier at this volume.

## There is no zero-spend mode

Every mission reads the live web and calls Gemini, so what bounds the cost is
the caps rather than a switch. That is deliberate: a system whose cheapest mode
was also its most convincing demonstration was demonstrating the wrong thing.

## Before you deploy

```bash
cd terraform
# budget_amount_usd defaults to 20 and alerts at 25/50/90/100%.
# On a fixed balance the 25% alert is the useful one.
tofu plan
```

Set `alert_email` and `billing_account` or no alert is created at all.

Cloud Run is deliberately public so a judge can open the link
(`publicly_readable` in Terraform). What bounds the damage is not the door: the
per-mission caps stop a mission rather than warning about it, outreach is
capped, and while `mail_redirect_to` is set every message goes to that address
rather than to a supplier. Turn it off before pointing this at real suppliers
with the redirect unset.

## If you are close to the limit

1. `SUPPLYME_FAST_MODEL=gemini-2.5-flash-lite` — roughly a third of flash.
2. Lower `SUPPLYME_MAX_VENDORS_PER_CATEGORY` to 3 and
   `SUPPLYME_MAX_MODEL_CALLS_PER_MISSION` to 40.
3. Check `curl -s localhost:8080/api/health | jq .spend.since_startup` after any
   live run.

The authoritative number is always Cloud Billing. The meter here is a guard
rail, and it is deliberately pessimistic — a model it has no price for is
charged at the most expensive rate on the list, so an unknown model
over-reports rather than slipping past a cap.
