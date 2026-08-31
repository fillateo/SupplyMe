# Recording the demo

There are two ways to show this, and they prove different things.

**The replay** (`MOCK=true`) plays back a mission that really ran, on a
90-second clock. No credentials, no model bill, nothing to wait for. Every
supplier, price, excerpt and source URL on screen came out of a real run against
the live web — but no mission is running while you present, and you have to say
so.

**The live run** starts a real mission: real search, real Google Places, real
Gemini, real email to a real address. It takes about an hour and costs about a
dollar, and it is the only version where a supplier's answer changes the
outcome in front of the audience — because *you* answer as the supplier.

| | Replay | Live run |
| --- | --- | --- |
| Needs credentials | no — but it does need a recording, which is not in the repo | all of them |
| Costs | nothing | ~$1.00 and ~1h45m |
| Runs to a fixed script | yes — one recorded mission | no — the web decides |
| Can answer a new brief | **no** | yes |
| Reply-as-the-supplier beat | already in the recording | you perform it |
| Best for | a live room, a re-take, a laptop with no keys | the submission video |

Record the live run if you have the time and the mailbox. Keep the replay
loaded in a second window as the re-take you can do on demand.

---

# Path A — the replay

```bash
MOCK=true ./run.sh                      # or: MOCK=true docker compose up --build
```

It needs no `.env`, no Google Cloud project and no mailbox, because in mock mode
nothing is bound: the model, search, Places and mail adapters are the ones in
`app/adapters/inert.py`, which raise if anything reaches them. `/api/health` says
as much before you press anything:

```bash
curl -s localhost:8080/api/health | jq '.providers, .notes'
# llm/search/maps/mail  -> InertProvider
# notes -> "SUPPLYME_MOCK is on: missions are replayed from a recording..."
```

Press **Start sourcing** and the console fills in over about 25 seconds.

Two knobs, and the second matters more than it sounds. `MOCK_DURATION` (90) is
the budget the recorded run is scaled into. `MOCK_MAX_GAP` (3 seconds) is the
longest the screen may sit still: most of a real mission is waiting for a
supplier to answer, and played back proportionally that wait is most of the
demo, so gaps longer than the cap are shortened to it. The order and the pacing
of everything that actually happened are untouched — only the silence goes,
which is why a 90-second budget finishes in 25. Raise the cap to play the
waiting out. Natively the names are `SUPPLYME_MOCK_DURATION_SECONDS` and
`SUPPLYME_MOCK_MAX_GAP_SECONDS`.

**It does need a recording, and the recording is not in the repository.** A
snapshot holds real supplier names, addresses, email addresses and
correspondence, so `backend/local-db.json` and `~/supplyme-firestore-backups`
are both gitignored — a fresh clone has nothing to replay, and `MOCK=true`
refuses to start rather than inventing one, naming the file it looked for. On
this machine the recording is already there. Anywhere else, export one from a
Firestore that has a finished mission in it:

```bash
cd backend
.venv/bin/python scripts/export_firestore.py      # -> ~/supplyme-firestore-backups/
.venv/bin/python scripts/restore_local_db.py      # -> backend/local-db.json
```

`SUPPLYME_MOCK_RECORDING` overrides the search, which is how the Docker path
gets one: the backups directory is mounted at `/snapshots` and the newest
snapshot in it wins.

Type the brief in anyway — the console will not start on an empty objective —
but know that it is ignored. A replay answers with the mission it has, and the
objective that appears on the mission page is the recorded one.

## What is in the recording

The snapshot at `backend/local-db.json` on this machine is the Los Angeles
fragrance mission, run on 31 August 2026. It took **1h43m**, made **216 model calls** and
cost **$1.03** — which is over the $1.00 cap, and the console says so on four
suppliers. Knowing what is coming is the difference between narrating it and
reading it:

- **6 components** derived from the brief: custom glass flacon, pump and collar,
  cap, fragrance bulk (juice), folding carton, contract filling and assembly.
- **12 suppliers** discovered, **4 qualified** — Advance Paper Box, American Oil
  Products, Superior Lithographics, Pacific Forest Products.
- **61 evidence records**, each with the excerpt and the URL it was read from.
- **8 emails sent** across 7 threads, and **4 quotes** extracted from replies:
  $0.48/unit at MOQ 1,000, $0.62 at 2,500, $0.94 at 5,000, $3.85 on the juice.
- **4 disagreements.** The one to open is **Superior Lithographics**: their site
  says a lead time of *"two or three days"*, their sales desk replied *"20
  business days from approved artwork"* — and added that the two-day figure on
  the site refers to proofs. The card carries a rose **⚡ 1 disagreement** badge;
  inside, the amber **Asking the supplier** panel shows both values with the
  reason the email won: *direct supplier response outranks published sources*.
  The other three are all on *customization*, on American Oil Products, Imperial
  Paper and Advance Paper Box, and render grey as **Left unresolved** — so expect
  a badge on the Advance Paper Box card too, and open Superior Lithographics for
  the one that actually got asked.
- **The recommendation names its own gaps.** Three components filled, two of them
  priced, and under *Operational Risks*: no viable supplier found for the glass
  flacon or the pump and collar. It does not pretend to have finished.
- **209 timeline events**, replayed in their original order — including the parts
  that overlapped, because each one is placed by its own recorded timestamp.

One thing is **not** in this recording: no supplier in it claimed a brand
relationship, so the *Brands they claim to work with* section does not render on
any card. Do not promise that beat on this path — the disagreement above is the
trust story here, and it is the stronger one anyway.

## The script — 90 seconds, word for word

> **[0:00, on the composer]**
> I want to make a perfume. Fifty millilitres, a thousand units, made in Los
> Angeles. I know what I want; I have no idea who can make it.
>
> This is one input — a product, not a parts list. Watch what it does with it.
>
> **[press Start sourcing]**
>
> **[0:15, Supply chain tab]**
> First it works out what the product is made of: a glass flacon, a pump and
> collar, a cap, the fragrance itself, a folding carton, and somebody to fill
> and assemble it. Six components. Nothing in the codebase knows what a perfume
> is; that came out of the brief.
>
> Now every one of those is being searched at the same time.
>
> **[0:35, Suppliers tab — expand Advance Paper Box]**
> Real companies. Real addresses in Los Angeles. And every number here is
> clickable — this MOQ, this price — because behind each one is the page it was
> read from, the sentence it was read out of, and the time it was retrieved. If
> it cannot show you a source, it does not print a number.
>
> **[0:55, open Superior Lithographics]**
> This is the one I would show a buyer. Their website says a lead time of two or
> three days. When it emailed them, their sales desk said twenty business days
> from approved artwork.
>
> It noticed. It did not average them and it did not pick the nicer number — it
> kept both, said which source it trusts and why, and put the question back to
> the supplier. That is the difference between a scraper and something you can
> hand a purchase order.
>
> **[1:15, Recommendation tab]**
> And here is what I find honest. Three components have a supplier and two have
> a price — and it says out loud that it could not find anyone for the flacon or
> the pump. It reports what it could not establish instead of filling the gap.
>
> One product idea in. A costed, sourced shortlist out, with a citation under
> every figure.

Say the honesty line once, early, in your own words: **this is a playback of a
mission that really ran, not a live one.** The console does not draw a badge for
it — a replay looks like a real run by eye — so the record is where it is
recorded: the mission document carries `replay_of`, pointing at the recording,
and `/api/health` names the mode. Mock mode is refused outright when
`SUPPLYME_USE_CLOUD_INFRA` is on, so a replay can never end up in the real
Firestore looking like a real mission.

---

# Path B — the live run

Nothing here is simulated. The agent reads the live web, queries Google Places,
calls Gemini, and sends real email. The one thing that is not what it appears is
the recipient: `SUPPLYME_MAIL_REDIRECT_TO` sends every message to a mailbox you
own instead of to the supplier it was addressed to, and the message says so in
the subject line and again at the top of the body.

**That mailbox must not be the one that sends.** Mail arriving from
`SUPPLYME_SMTP_USER` is discarded as our own copy — Gmail files sent mail into
the conversation, and a mission reading its own outreach back would answer
itself — so if the two match you will reply as the supplier on camera and
nothing will happen.

That redirect is also what makes the demo possible. **You reply as the
supplier.** The agent writes to a real address, a human answers, and the mission
resumes from that answer — which is the whole premise of the category, performed
rather than described.

## Before you record

```bash
cd backend && cp .env.example .env      # then fill it in
```

Everything `.env.example` marks required has to be set. There is no offline mode
on this path: a missing credential stops the process and names itself. Then:

```bash
./run.sh                # API on :8080, console on :3000
./run.sh status         # model, policy, spend, and every provider actually bound
```

Three things to check before you press record, all of them on `/api/health`:

- **`.providers`** reads `GoogleSearchProvider`, `PlacesProvider` and
  `RedirectingMailProvider`. `InertProvider` anywhere means mock mode is still
  on from a previous run. Anything else means the environment is wrong.
- **`.model`** names the model each tier resolved to, and the backend it
  answered from. This is the line worth reading out loud, because the adapter is
  called `GeminiLLM` whichever generation is behind it.
- **`.notes`** contains the `SUPPLYME_MAIL_REDIRECT_TO` line, saying mail is
  going to **your** address. If that line is missing, outreach goes to real
  businesses.

Have the receiving mailbox open in a second window. You will be answering from
it on camera.

## The brief to paste

**What are you producing?**

```
Launch a 50ml eau de parfum in Los Angeles. 1,000 units to start. Custom glass
flacon, pump and collar, folding carton, and contract filling with low minimums
on the first run.
```

**Where should we look?** → **City**, `Los Angeles`.

Four things in that brief are load-bearing, and it is worth knowing which before
you shorten it on camera:

- **It names a product, not a supply chain.** "Eau de parfum" is the whole input
  — the flacon, the pump, the carton and the filler are derived from it, and
  nothing in `app/` knows what a perfume is made of. That derivation is the claim
  the **Supply chain** tab exists to substantiate, so listing the parts yourself
  gives the tab nothing to show.
- **The unit count is what turns a minimum order into a verdict.** The planning
  agent reads only what is stated and leaves the quantity unset otherwise, so
  "1,000 units to start" is what lets a supplier quoting an MOQ of 5,000 be
  scored against a first batch of 1,000 — and it is the figure every email it
  writes asks against. Drop the number and both go quiet.
- **"Low minimums on the first run" is what the recommendation answers to.** It
  gives the closing panel a constraint to report against rather than a summary.
- **Los Angeles is the right size.** Dense enough in contract fillers and glass
  suppliers that City scope returns real companies, narrow enough that discovery
  does not spend minutes you would have to edit out.

The console ships with no prefilled examples at all, which is the point. The
brief you paste is one the tool was never tuned for.

## Getting the reply back into the mission

Nothing polls the mailbox locally. IMAP has no push, so something has to ask,
and locally that something is you:

```bash
./run.sh mail           # POST /webhooks/mail/poll -> {"read":2,"resumed":1}
```

In the deployment a Cloud Scheduler job does it every fifteen minutes
(`terraform/scheduler.tf`), so if you are demoing the deployed console you can
wait instead. On a laptop, waiting achieves nothing: run `./run.sh mail` the
moment you have sent your reply as the supplier.

A reply is matched by its `In-Reply-To` header, so **reply inside the thread**.
A fresh message to the same address matches nothing and is ignored as somebody
else's mail.

## The four-minute path

| Time | What to show | Where it comes from |
| --- | --- | --- |
| 0:00–0:25 | The friction, in one sentence: *"I want to start a perfume brand and I don't know who can actually make it."* | — |
| 0:25–0:45 | Paste the brief, set scope to **City** → `Los Angeles`, press **Start sourcing**, close the tab | `POST /api/missions` |
| 0:45–1:25 | Reopen. Components identified, discovery running in parallel across them | **Supply chain** tab |
| 1:25–2:00 | Open a supplier. Real company, real address, real website — and the evidence drawer shows the page it was read from, with the retrieval time | **Suppliers** tab → expand → click any figure |
| 2:00–2:25 | *If the run found one:* a brand claim judged on its sources — **Unverified Claim** against **Independently Reported**. Otherwise spend the time on the trust breakdown, *How confident, and in what* | **Suppliers** tab → *Brands they claim to work with* |
| 2:25–2:50 | The email it already sent, and what it personalised from — no approval step waited on you | **Communications** tab, sent thread |
| 2:50–3:20 | **Switch to the mailbox.** The email is there. Reply in the thread as the supplier — quote a price and a minimum order that contradicts their website | your inbox, then `./run.sh mail` |
| 3:20–3:45 | Back in the console: the reply is in, the quote extracted, the disagreement flagged | Activity feed, then the **⚡ disagreement** card |
| 3:45–4:00 | It puts both numbers back to them in one targeted follow-up, and the recommendation names what it could not establish | **Communications**, then **Recommendation** |

Start the mission before you start recording. A real mission is bounded by the
slowest supplier site the research agent decides to open, and it can be several
minutes before the first email is drafted. The activity feed is a stored event
log, not a progress animation — it reads exactly the same whether or not you
were watching when it was written.

## The script — four minutes, word for word

> **[0:00, composer, nothing typed yet]**
> Last year I tried to get five hundred bottles of perfume made. The
> marketplaces were useless: the good factories were not listed, the ranking
> sorted by ad spend, and not one of them published a minimum order. So I did it
> by hand for three weeks — forty-one tabs, three languages, and a spreadsheet
> where the MOQ column said question mark nine times.
>
> The part that broke me: two suppliers claimed the same fragrance house as a
> customer. One of them was lying and I had no way to tell which.
>
> **[0:25, paste the brief, set City → Los Angeles]**
> So here is the whole input. A product, a quantity, a city. Not a parts list,
> not a search query.
>
> **[press Start sourcing, then close the browser tab]**
> And I am going to close the tab, because this is not a chatbot. It runs whether
> I am watching or not.
>
> **[0:45, reopen the mission]**
> It has already decided what the product is made of — flacon, pump and collar,
> carton, the juice, and a contract filler — and it is searching for all of them
> at the same time. Nothing in the code knows what a perfume is. That came out of
> the brief.
>
> **[1:25, Suppliers tab, expand one, click a figure]**
> Real companies in Los Angeles, with real addresses and real websites. Now watch
> this — I click the minimum order, and it opens the page it was read from, the
> exact sentence, and the time it was retrieved. Every number in this console
> does that. If it cannot show you a source, it does not show you a number.
>
> **[2:00, Brands they claim to work with — only if the run produced one]**
> And here is my two-suppliers problem, handled. This claim is labelled
> *Unverified Claim* — the supplier says it and nobody else does. This one is
> *Independently Reported*: two sources that are not the supplier say it too.
> Same claim, different standing, because who is making a claim is part of the
> claim.
>
> *(No brand claim on screen? Open* How confident, and in what *instead: identity,
> capability, MOQ, pricing, lead time, contact — each scored separately, with the
> sentence behind the score. A supplier can be certainly real and still have an
> unknown price, and this says which.)*
>
> **[2:25, Communications tab]**
> It has already emailed them. Nobody approved this — that is the default, and
> what bounds it is that outreach is redirected to a mailbox I own, not a human
> clicking send. And the email is specific: it asks the questions this supplier's
> website did not answer.
>
> **[2:50, switch to the mailbox]**
> Which means it is in my inbox right now, addressed to me, saying at the top who
> it would have gone to. So I am going to be the supplier.
>
> **[type the reply, in the thread]**
> I will quote a price, I will quote a minimum order of five thousand against
> their first batch of a thousand — and I will contradict their own website on
> lead time. Send.
>
> **[run ./run.sh mail]**
> Nothing polls a mailbox locally, so I ask it to read one now. In the deployment
> Cloud Scheduler does this every fifteen minutes.
>
> **[3:20, back in the console]**
> The reply is in the timeline. The price and the minimum order have been pulled
> out of prose into fields. And there — a disagreement, flagged, because what I
> just said does not match what their site says.
>
> It kept both values. It says which source it trusts and why. And it is asking
> them about it, in one targeted follow-up, rather than guessing.
>
> **[3:45, Recommendation tab]**
> A ranked shortlist, every score a weight times a fit with the sentence that
> produced it — and a panel for what it could not establish. It reports the gaps
> instead of filling them.
>
> **[4:00]**
> I gave it one product idea. It worked out what the product is made of, found
> real manufacturers for every part, checked their claims against sources that
> were not them, wrote to them, and when a supplier's website and their sales
> desk disagreed — it noticed, and it asked.

## What to say about the mailbox

Say it plainly, once: every message really sends, and it is redirected to an
address the operator owns so that a demonstration does not cost a stranger their
afternoon. Judges reward that more than they reward pretending the recipient was
a factory in Tangerang.

---

# Proof of action

Nothing in the console is animated. If a judge asks whether it is real:

```bash
# Which model, through which backend, and which adapters are bound
curl -s localhost:8080/api/health | jq '.model, .providers, .notes'

# The stored event log the timeline renders from
curl -s localhost:8080/api/missions/$MID/activity | jq '.[-12:] | .[] | {type, status, emitted}'

# Every claim with the source it came from
curl -s localhost:8080/api/missions/$MID/evidence | jq '.[] | {claim, source_type, source_url}'

# What the mission spent, from the API's own token counts
curl -s localhost:8080/api/missions/$MID | jq .spend

# The structured logs, filtered to one mission
gcloud logging read 'jsonPayload.mission_id="'$MID'"' --limit 40
```

In a replay, `.providers` reads `InertProvider` on all four and the mission
carries `replay_of` — which is how you demonstrate that the honesty is enforced
rather than promised:

```bash
curl -s localhost:8080/api/missions/$MID | jq '.mission.replay_of'
```

And the whole thing without a browser, printing only stored state:

```bash
cd backend
.venv/bin/python scripts/run_mission.py --project YOUR_PROJECT
```

That runs a real mission — it has no mock mode — and its own default brief is
the 500-unit Indonesian one. Pass `--objective` to give it the Los Angeles
brief instead. Its only other flags are `--project` and `--verbose`.

For a rehearsal against the deployed data path rather than an in-process store,
`./run.sh emulator` starts Google's Firestore emulator and seeds it from your
newest snapshot, or `docker compose up --build` brings up the emulator, the API
and the console together. Both are covered in
[LOCAL.md](./LOCAL.md#3d-a-real-firestore-locally).

# When it is slow, or stops

**A supplier's site is slow.** A real mission is bounded by the slowest page the
research agent opens. Lower `SUPPLYME_MAX_VENDORS_PER_MISSION` so fewer branches
run, and start the mission before you start recording.

**It stops at the spend cap.** `SUPPLYME_MAX_USD_PER_MISSION` defaults to $1.00,
and a twelve-supplier mission spends most of that — the recorded run finished at
$1.03 with four suppliers marked *research stopped when the mission reached its
$1.00 spend cap*. That is the guard working, and it is honest on camera. Raise
the cap, or lower the shortlist, if you would rather it did not fire.

**It sits in `awaiting_response`.** It is waiting for a supplier, which is what
the product is. Reply from the redirect mailbox, then `./run.sh mail`. Left
alone, the follow-up timer is a real 48 hours.

**429s in the API log.** Vertex quota. Lower `SUPPLYME_MAX_CONCURRENT_RESEARCH`
to 1, or set `SUPPLYME_MIN_MODEL_CALL_INTERVAL_SECONDS=0.5`.
