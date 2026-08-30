# What this costs, and what stops it

Written against a fixed prepaid balance. The numbers below are measured from the
API's own `usage_metadata`, not estimated.

## Measured

One mission over the demo dataset — 5 suppliers, 7 supply-chain categories,
research, brand adjudication, outreach drafting, quote extraction, follow-up
planning — on `gemini-3.5-flash`, across several runs: **55–65 calls,
roughly 87,000 input and 19,000–26,000 output tokens, $0.09–$0.13.**

The spread is not measurement noise. How many suppliers reply, and how many
follow-ups a disagreement takes to settle, differ from run to run — which is
the point of the thing.

The effect of capping thinking, measured earlier on `gemini-2.5-flash`:

| | output tokens per call | USD per call |
| --- | --- | --- |
| thinking left on (Gemini's default) | 1,222 | $0.0033 |
| thinking capped (what ships) | 405 | $0.0013 |

Thinking tokens are billed as output. For extraction and classification — reading
a price out of an email, deciding whether a search result is a manufacturer —
they buy nothing, so the fast tier gets a budget of zero and the reasoning tier
gets a bounded allowance. That change alone cut cost per call by about 60%.

A full mission lands at **55–65 model calls**, so **$0.09–$0.13**, or
**Rp 1,500–2,100** at 16,400 IDR/USD. The scripted model costs nothing at all.

Check any mission's actual spend:

```bash
curl -s localhost:8080/api/missions/$MID | jq .spend
curl -s localhost:8080/api/health | jq .spend        # process total, and the caps
```

## What actually stops spending

A budget alert emails you; it does not stop anything. These do:

| Guard | Default | Stops |
| --- | --- | --- |
| `VDS_MAX_USD_PER_MISSION` | `0.50` | the mission, with a reason on the record |
| `VDS_MAX_MODEL_CALLS_PER_MISSION` | `120` | the mission |
| `VDS_MAX_RESEARCH_LLM_CALLS` | `12` | one research agent's tool loop |
| `VDS_MAX_CONCURRENT_RESEARCH` | `3` | how many run at once |
| `VDS_MAX_CONCURRENT_MODEL_CALLS` | `4` | Gemini requests in flight, process-wide |
| `VDS_MIN_MODEL_CALL_INTERVAL_SECONDS` | `0` | how fast the queue drains |
| `VDS_MAX_OUTREACH_PER_MISSION` | `12` | emails |
| `VDS_MAX_VENDORS_PER_CATEGORY` | `8` | how many suppliers get researched |
| `VDS_MAX_EVENT_RETRIES` | `5` | retrying a failing handler forever |

Reaching a spend cap raises `BudgetExceeded`, which the orchestrator treats as
**terminal, not retryable** — retrying is precisely what the cap exists to
prevent. The mission's `failure_reason` says which cap and what it had spent.

### The one that mattered most

Google ADK defaults `max_llm_calls` to **500 per agent run**. A research agent
needs about five. Five vendors researching at 500 calls each is 2,500 model
calls for one mission — on the order of $8 with thinking on, and it would happen
silently. `VDS_MAX_RESEARCH_LLM_CALLS=12` is the ceiling that prevents it, and
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

### Rate limits are a queueing problem

A project with no provisioned Vertex throughput answers 429 to most of a burst,
and retrying the burst reproduces it. `VDS_MAX_CONCURRENT_MODEL_CALLS` bounds
how many requests exist at once across every agent, and
`VDS_MIN_MODEL_CALL_INTERVAL_SECONDS` spreads what is left. On a small quota,
`2` and `1.0` turn a storm into a queue. If a mission still cannot finish, set
`VDS_USE_ADK_RESEARCH=false`: the pre-fetching research agent makes **one**
metered call per supplier instead of up to twelve, at the cost of the agent
choosing its own sources.

## Costs that are not the model

| Service | On this workload |
| --- | --- |
| Cloud Run | Scale-to-zero, `cpu_idle = true`. A mission waiting two days for a supplier holds no instance. Effectively free at demo volume. |
| Firestore | Thousands of small documents. Well inside the free tier. |
| Pub/Sub | Tens of messages per mission. Free tier. |
| Cloud Tasks | One task per follow-up. Free tier. |
| Cloud Build | A few minutes per deploy. Free tier covers roughly 100 builds/month. |

The realistic risk on a small balance is Vertex AI. Everything else stays in the
free tier at anything resembling demo volume.

## Running with no spend at all

```bash
VDS_USE_SCRIPTED_MODEL=true
```

The whole system — console included — runs deterministically with no Google
Cloud project, no API key and no network. Same agents, events, storage,
conflict detection and scoring. Use this for development, for the test suite,
and for any demo where the model output does not need to be live. It is the
default in `.env.example` for exactly this reason.

## Before you deploy

```bash
cd terraform
# budget_amount_usd defaults to 20 and alerts at 25/50/90/100%.
# On a fixed balance the 25% alert is the useful one.
tofu plan
```

Set `alert_email` and `billing_account` or no alert is created at all.

Cloud Run in `demo` mode is deliberately public so a judge can open the link.
That is safe for spend because demo mode binds mock providers — it cannot send
mail — but the model still runs, so keep the per-mission caps on.

## If you are close to the limit

1. `VDS_USE_SCRIPTED_MODEL=true` — zero spend, full workflow.
2. `VDS_FAST_MODEL=gemini-2.5-flash-lite` — roughly a third of flash.
3. Lower `VDS_MAX_VENDORS_PER_CATEGORY` to 3 and
   `VDS_MAX_MODEL_CALLS_PER_MISSION` to 40.
4. Check `curl -s localhost:8080/api/health | jq .spend.since_startup` after any
   live run.

The authoritative number is always Cloud Billing. The meter here is a guard
rail, and it is deliberately pessimistic — a model it has no price for is
charged at the most expensive rate on the list, so an unknown model
over-reports rather than slipping past a cap.
