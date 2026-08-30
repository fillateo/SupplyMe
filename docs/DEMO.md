# Running the demo

Nothing here is simulated. The agent reads the live web, queries Google Places,
calls Gemini, and sends real email. The one thing that is not what it appears is
the recipient: `VDS_MAIL_REDIRECT_TO` sends every message to a mailbox you own
instead of to the supplier it was addressed to, and the message says so at the
top.

That is also what makes the demo possible. **You reply as the supplier.** The
agent writes to a real address, a human answers, and the mission resumes from
that answer — which is the whole premise of the category, performed rather than
described.

## Before you record

```bash
cd backend && cp .env.example .env      # then fill it in
```

Everything in `.env.example` marked required has to be set; there is no offline
mode and the process will refuse to start and name what is missing. Then:

```bash
./run.sh                # API on :8080, console on :3000
./run.sh status         # confirms which providers are actually bound
```

Check two things before you press record:

- `/api/health` shows `GoogleSearchProvider`, `PlacesProvider`, `YouTubeProvider`
  and `RedirectingMailProvider`. If any of them says something else, the
  environment is wrong.
- The health notes say mail is going to **your** address. If that line is
  missing, outreach will go to real businesses.

Have the receiving mailbox open in a second window. You will be answering from
it on camera.

## The four-minute path

| Time | What to show | Where it comes from |
| --- | --- | --- |
| 0:00–0:25 | The friction, in one sentence: *"I want to start a perfume brand and I don't know who can actually make it."* | — |
| 0:25–0:45 | Paste the objective, press **Start sourcing**, close the tab | `POST /api/missions` |
| 0:45–1:25 | Reopen. Categories identified, discovery running in parallel across them | Supply chain tab |
| 1:25–2:00 | Open a supplier. Real company, real address, real website — and the evidence drawer shows the page it was read from, with the retrieval time | Suppliers tab → expand → any figure |
| 2:00–2:25 | A brand claim judged on its sources: the supplier's own word, versus something written by anyone else | Suppliers tab → brand panel |
| 2:25–2:50 | The email it wrote, and what it personalised from. Approve it | Approvals bar, "Read it first" |
| 2:50–3:20 | **Switch to the mailbox.** The email is there. Reply as the supplier — quote a price and a minimum order that contradicts their website | your inbox |
| 3:20–3:45 | Back in the console: the reply is in, the quote extracted, and the disagreement is flagged | Activity feed, then the conflict panel |
| 3:45–4:00 | It puts both numbers back to them in one targeted follow-up, and the recommendation names what it could not establish | Communications, Recommendation |

The reply takes up to a minute to appear — Cloud Scheduler polls the mailbox
once a minute. `./run.sh mail` reads it immediately if you would rather not wait
on camera.

Closing line: *"I gave it one product idea. It worked out what the product is
made of, found real manufacturers for every part, checked their claims against
sources that were not them, wrote to them, and when a supplier's website and
their sales desk disagreed — it noticed, and asked."*

## What to say about the mailbox

Say it plainly, once: every message really sends, and it is redirected to an
address the operator owns so that a demonstration does not cost a stranger their
afternoon. Judges reward that more than they reward pretending the recipient was
a factory in Tangerang.

## Proof of action

Nothing in the console is animated. If a judge asks whether it is real:

```bash
# The stored event log the timeline renders from
curl -s localhost:8080/api/missions/$MID/activity | jq '.[-12:] | .[] | {type, status, emitted}'

# Every claim with the source it came from
curl -s localhost:8080/api/missions/$MID/evidence | jq '.[] | {claim, source_type, source_url}'

# What the mission spent, from the API's own token counts
curl -s localhost:8080/api/missions/$MID | jq .spend

# The structured logs, filtered to one mission
gcloud logging read 'jsonPayload.mission_id="'$MID'"' --limit 40
```

And the whole thing without a browser, printing only stored state:

```bash
.venv/bin/python scripts/run_mission.py --project YOUR_PROJECT
```

## If a supplier's site is slow

A real mission takes longer than a recorded one wants to. Reading the live web
is bounded by the slowest site the research agent decides to open, and a mission
across a dozen suppliers can run for several minutes before the first email is
drafted.

Two things help, and neither of them fakes anything: lower
`VDS_MAX_VENDORS_PER_MISSION` so fewer branches run, and start the mission
before you start recording, so the video opens on a mission already underway.
The activity feed is a stored log — it reads the same whether you were watching
when it was written or not.
