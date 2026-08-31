#!/usr/bin/env python3
"""Regenerate docs/architecture.svg — the deployed architecture, drawn from
terraform/ and backend/app/ as they actually are.

Run from the repository root:

    python3 scripts/architecture_diagram.py

Then render the PNG at 2x, with any headless Chromium:

    chrome --headless=new --disable-gpu --hide-scrollbars \
      --force-device-scale-factor=2 --window-size=1680,1000 \
      --screenshot=docs/architecture.png docs/architecture.svg

Edit this file rather than the SVG: the coordinates here are the layout, and
the SVG is only its output.
"""
from __future__ import annotations

W, H = 1680, 1000
SHIFT = 44  # everything below the title block

FONT = "'Noto Sans','Liberation Sans',Arial,Helvetica,sans-serif"
INK, MUTE, LINE = "#202124", "#5F6368", "#3C4043"
EVENT, PROV = "#1A73E8", "#80868B"

out: list[str] = []
def add(s: str) -> None: out.append(s)

def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def text(x, y, t, size=9.5, fill=MUTE, weight="400", anchor="start", rotate=None):
    tr = f' transform="rotate({rotate} {x} {y})"' if rotate else ""
    add(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{tr}>{esc(t)}</text>')

def box(x, y, w, h, fill, stroke, rx=6, dash=None, sw=1):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="{sw}"{d}/>')

# ---------------------------------------------------------------- icons
def icon(kind, x, y):
    """A 20x20 glyph at (x, y). Abstract marks, not Google's own artwork."""
    g = [f'<g transform="translate({x},{y})">']
    def tile(c):  g.append(f'<rect width="20" height="20" rx="4" fill="{c}"/>')
    if kind == "run":
        tile("#4285F4"); g.append('<path d="M6 5.5 L15 10 L6 14.5 Z" fill="#fff"/>')
    elif kind == "cloud":
        tile("#1A73E8")
        g.append('<path d="M6.6 14.5 a3.2 3.2 0 0 1 -0.2 -6.4 a4.3 4.3 0 0 1 8.2 -0.6 '
                 'a3.5 3.5 0 0 1 -0.3 7 z" fill="#fff"/>')
    elif kind == "console":
        tile("#4285F4")
        g.append('<rect x="4" y="5" width="12" height="8" rx="1" fill="#fff"/>'
                 '<rect x="7.5" y="14" width="5" height="1.6" fill="#fff"/>')
    elif kind == "db":
        c = "#F9AB00"
        g.append(f'<ellipse cx="10" cy="5.5" rx="6.5" ry="2.6" fill="{c}"/>'
                 f'<path d="M3.5 5.5 v9 a6.5 2.6 0 0 0 13 0 v-9 a6.5 2.6 0 0 1 -13 0 z" fill="{c}"/>'
                 '<ellipse cx="10" cy="10" rx="6.5" ry="2.6" fill="none" stroke="#fff" stroke-width="1"/>')
    elif kind == "pubsub":
        tile("#4285F4")
        g.append('<path d="M4 7 h8 M4 7 l2.5 -2.5 M4 7 l2.5 2.5" stroke="#fff" stroke-width="1.4" fill="none" stroke-linecap="round"/>'
                 '<path d="M16 13 h-8 M16 13 l-2.5 -2.5 M16 13 l-2.5 2.5" stroke="#fff" stroke-width="1.4" fill="none" stroke-linecap="round"/>')
    elif kind == "deadletter":
        tile("#9AA0A6")
        g.append('<rect x="3.5" y="5.5" width="13" height="9" rx="1.2" fill="#fff"/>'
                 '<path d="M3.5 6.5 L10 11 L16.5 6.5" stroke="#9AA0A6" stroke-width="1.2" fill="none"/>')
    elif kind == "tasks":
        tile("#4285F4")
        g.append('<path d="M5 6.5 h10 M5 10 h10 M5 13.5 h6" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>')
    elif kind == "clock":
        tile("#4285F4")
        g.append('<circle cx="10" cy="10" r="6" fill="none" stroke="#fff" stroke-width="1.5"/>'
                 '<path d="M10 6.5 V10 l3 1.8" stroke="#fff" stroke-width="1.5" fill="none" stroke-linecap="round"/>')
    elif kind == "key":
        tile("#34A853")
        g.append('<circle cx="7.5" cy="10" r="3" fill="none" stroke="#fff" stroke-width="1.5"/>'
                 '<path d="M10.5 10 H16 M14 10 v3 M16 10 v2.5" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>')
    elif kind == "registry":
        tile("#4285F4")
        g.append('<path d="M10 4 L16 7.2 v5.6 L10 16 L4 12.8 V7.2 Z" fill="none" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/>'
                 '<path d="M4 7.2 L10 10.4 L16 7.2 M10 10.4 V16" stroke="#fff" stroke-width="1.1"/>')
    elif kind == "chart":
        tile("#4285F4")
        g.append('<path d="M5 15 V10 M9 15 V6 M13 15 V12 M17 15 V8" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>')
    elif kind == "spark":
        tile("#9334E6")
        g.append('<path d="M10 3.5 C10.7 7.6 12.4 9.3 16.5 10 C12.4 10.7 10.7 12.4 10 16.5 '
                 'C9.3 12.4 7.6 10.7 3.5 10 C7.6 9.3 9.3 7.6 10 3.5 Z" fill="#fff"/>')
    elif kind == "search":
        tile("#4285F4")
        g.append('<circle cx="9" cy="9" r="4" fill="none" stroke="#fff" stroke-width="1.6"/>'
                 '<path d="M12.2 12.2 L16 16" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>')
    elif kind == "pin":
        tile("#EA4335")
        g.append('<path d="M10 4 a4 4 0 0 1 4 4 c0 3-4 8-4 8 s-4-5-4-8 a4 4 0 0 1 4-4 z" fill="#fff"/>'
                 '<circle cx="10" cy="8" r="1.5" fill="#EA4335"/>')
    elif kind == "globe":
        tile("#34A853")
        g.append('<circle cx="10" cy="10" r="6" fill="none" stroke="#fff" stroke-width="1.3"/>'
                 '<path d="M4 10 h12 M10 4 c3 3 3 9 0 12 M10 4 c-3 3 -3 9 0 12" stroke="#fff" stroke-width="1.1" fill="none"/>')
    elif kind == "mail":
        tile("#EA4335")
        g.append('<rect x="3.5" y="5.5" width="13" height="9" rx="1.2" fill="#fff"/>'
                 '<path d="M3.5 6.5 L10 11 L16.5 6.5" stroke="#EA4335" stroke-width="1.3" fill="none"/>')
    elif kind == "person":
        g.append('<circle cx="10" cy="6.5" r="3.4" fill="#5F6368"/>'
                 '<path d="M3 17.5 a7 6.2 0 0 1 14 0 z" fill="#5F6368"/>')
    elif kind == "people":
        g.append('<circle cx="6.5" cy="7" r="3" fill="#5F6368"/><path d="M1 17 a5.5 5 0 0 1 11 0 z" fill="#5F6368"/>'
                 '<circle cx="14.5" cy="7.5" r="2.6" fill="#9AA0A6"/><path d="M9.6 17 a5 4.6 0 0 1 9.8 0 z" fill="#9AA0A6"/>')
    elif kind == "orchestrator":
        tile("#5F6368")
        g.append('<circle cx="10" cy="10" r="2.4" fill="#fff"/>'
                 '<path d="M10 10 L10 4.2 M10 10 L15 13 M10 10 L5 13" stroke="#fff" stroke-width="1.4"/>'
                 '<circle cx="10" cy="4.2" r="1.7" fill="#fff"/><circle cx="15" cy="13" r="1.7" fill="#fff"/>'
                 '<circle cx="5" cy="13" r="1.7" fill="#fff"/>')
    elif kind == "agents":
        tile("#9334E6")
        g.append('<circle cx="6" cy="6.5" r="2.2" fill="#fff"/><circle cx="14" cy="6.5" r="2.2" fill="#fff"/>'
                 '<circle cx="10" cy="14" r="2.2" fill="#fff"/>'
                 '<path d="M6 6.5 H14 M6 6.5 L10 14 M14 6.5 L10 14" stroke="#fff" stroke-width="1"/>')
    elif kind == "engines":
        tile("#34A853")
        g.append('<rect x="4.5" y="4.5" width="4.5" height="4.5" rx="0.8" fill="#fff"/>'
                 '<rect x="11" y="4.5" width="4.5" height="4.5" rx="0.8" fill="#fff"/>'
                 '<rect x="4.5" y="11" width="4.5" height="4.5" rx="0.8" fill="#fff"/>'
                 '<rect x="11" y="11" width="4.5" height="4.5" rx="0.8" fill="#fff"/>')
    elif kind == "ports":
        tile("#5F6368")
        g.append('<rect x="3.5" y="6.5" width="9" height="7" rx="1.2" fill="#fff"/>'
                 '<path d="M12.5 8.6 h4 M12.5 11.4 h4" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>')
    elif kind == "tofu":
        tile("#FFC107")
        g.append('<path d="M7.5 6 L4 10 L7.5 14 M12.5 6 L16 10 L12.5 14" stroke="#202124" stroke-width="1.6" '
                 'fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
    elif kind == "deploy":
        tile("#188038")
        g.append('<path d="M10 15 V6 M10 5 l-3.5 3.5 M10 5 l3.5 3.5" stroke="#fff" stroke-width="1.7" '
                 'fill="none" stroke-linecap="round"/>')
    g.append("</g>")
    add("".join(g))

# ---------------------------------------------------------------- cards
def card(x, y, w, h, ico, title, lines, first=48, lead=13.5, tsize=11.5):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="#FFFFFF" '
        f'stroke="#DADCE0" stroke-width="1" filter="url(#sh)"/>')
    if ico:
        icon(ico, x + 13, y + 13)
        text(x + 41, y + 27.5, title, tsize, INK, "600")
    else:
        text(x + 14, y + 26, title, tsize, INK, "600")
    for i, ln in enumerate(lines):
        text(x + 14, y + first + i * lead, ln, 9.3, MUTE)

# ---------------------------------------------------------------- arrows
def path(d, color=LINE, dash=None, head="end", width=1.4):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    mk = {LINE: "aInk", EVENT: "aEvt", PROV: "aPrv"}[color]
    m = ""
    if head in ("end", "both"): m += f' marker-end="url(#{mk})"'
    if head in ("start", "both"): m += f' marker-start="url(#{mk}s)"'
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{da}{m} '
        f'stroke-linejoin="round" stroke-linecap="butt"/>')

def poly(pts, **kw):
    path("M " + " L ".join(f"{a} {b}" for a, b in pts), **kw)

# ================================================================= document
add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
    f'viewBox="0 0 {W} {H}" font-family="{FONT}">')
add("<defs>")
add('<filter id="sh" x="-20%" y="-20%" width="140%" height="150%">'
    '<feDropShadow dx="0" dy="1" stdDeviation="1.1" flood-color="#3C4043" flood-opacity="0.18"/></filter>')
for name, col in (("aInk", LINE), ("aEvt", EVENT), ("aPrv", PROV)):
    add(f'<marker id="{name}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6.5" '
        f'markerHeight="6.5" orient="auto-start-reverse">'
        f'<path d="M 0 0.6 L 9 5 L 0 9.4 z" fill="{col}"/></marker>')
    add(f'<marker id="{name}s" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6.5" '
        f'markerHeight="6.5" orient="auto-start-reverse">'
        f'<path d="M 0 0.6 L 9 5 L 0 9.4 z" fill="{col}"/></marker>')
add("</defs>")
add(f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>')

# title block
text(24, 30, "SupplyMe — supplier sourcing as a long-running agent", 17, INK, "700")
text(24, 50, "Every box is deployed by terraform/ and reachable in the running system. "
             "No provider is simulated: a missing credential is a startup failure.", 10.5, MUTE)

add(f'<g transform="translate(0,{SHIFT})">')

# ---------------------------------------------------------------- project box
box(264, 56, 960, 860, "#DCE9FD", "#A8C7FA", 8)
icon("cloud", 284, 68)
text(312, 83, "Google Cloud project  ·  us-central1", 13, "#174EA6", "700")

# ---- Cloud Run row
box(344, 104, 860, 196, "#F1F3F4", "#DADCE0", 6)
text(360, 126, "Cloud Run  —  two services, scale to zero, one service account each; images from Artifact Registry, the API's secrets from Secret Manager", 10.5, "#3C4043", "600")

card(364, 140, 380, 140, "run", "API  ·  supply-me", [
    "FastAPI + the whole workflow in one container",
    "540s request timeout  <  600s ack deadline  <  600s lease",
    "/api/*  ·  console reads and approval decisions",
    "/events/pubsub  ·  /events/task  ·  push ingress",
    "/webhooks/gmail  ·  /webhooks/mail/poll",
], first=50, lead=13.6)

card(824, 140, 360, 140, "console", "Console  ·  supply-me-console", [
    "Next.js 15; the only thing the browser talks to",
    "app/api/[...path] proxies /api/* server-side, so",
    "no API origin, token or credential is ever in",
    "client JavaScript and there is no CORS preflight",
    "Holds run.invoker on the API. Nothing else.",
], first=50, lead=13.6)

# ---- event plane
box(344, 322, 268, 360, "#F1F3F4", "#DADCE0", 6)
text(358, 344, "Event plane  —  at-least-once", 10.5, "#3C4043", "600")

card(364, 358, 228, 68, "pubsub", "Pub/Sub", ["supply-me-workflow  + push sub",
                                              "ack 600s · OIDC + shared token"], first=46, lead=12.5)
card(364, 440, 228, 68, "deadletter", "Dead letter", ["topic + pull subscription",
                                                      "7 days to look at it, no TTL"], first=46, lead=12.5)
card(364, 522, 228, 68, "tasks", "Cloud Tasks", ["supply-me-followups",
                                                 "delayed follow-ups, backoff"], first=46, lead=12.5)
card(364, 604, 228, 68, "clock", "Cloud Scheduler", ["*/15 — IMAP has no push",
                                                     "wakes a service at zero"], first=46, lead=12.5)

# ---- runtime
box(652, 322, 552, 360, "#FEF7E0", "#FDE293", 6)
text(742, 344, "Inside the API container  —  one process; every dependency is a Port", 10.5, "#7B5800", "600")

card(672, 358, 512, 64, "orchestrator", "Orchestrator  ·  app/workflow/", [
    "claim dedup key → run handler → emit the next events",
    "lease · bounded retry · drop the unprocessable · never the same work twice",
], first=44, lead=13)

card(672, 448, 248, 96, "agents", "7 agents  ·  Gemini", [
    "mission · supply chain · discovery",
    "research (Google ADK tool loop)",
    "brand evidence · communication",
    "recommendation",
], first=46, lead=13)

card(936, 448, 248, 96, "engines", "Deterministic engines", [
    "evidence · identity · quotes",
    "conflicts · trust · scoring",
    "contacts · numbers · cost meter",
    "no model decides a rank",
], first=46, lead=13)

card(672, 570, 512, 102, "ports", "Ports and adapters  ·  app/ports, app/adapters", [
    "Search · Maps · Mail · Store · Bus · Scheduler · LLM",
    "Every adapter is the real service; the test doubles live in tests/ and are",
    "reachable from nowhere in app/. Research tool calls pass policy.check() first,",
    "so the agent that reads attacker-controlled pages cannot email or spend.",
], first=48, lead=13.4)

# ---- managed services
box(344, 720, 860, 168, "#F1F3F4", "#DADCE0", 6)
text(360, 742, "Managed services", 10.5, "#3C4043", "600")

card(364, 756, 152, 116, "db", "Firestore", ["missions · vendors", "evidence · quotes",
                                             "conflicts · approvals", "workflow_events —",
                                             "the timeline the", "console renders"], first=46, lead=12.4, tsize=11)
card(531, 756, 152, 116, "spark", "Vertex AI", ["Gemini 3.5 Flash", "global endpoint",
                                                "reasoning + fast tier", "resolved once per",
                                                "process; reported by", "/api/health"], first=46, lead=12.4, tsize=11)
card(698, 756, 152, 116, "key", "Secret Manager", ["Gemini key · Places key",
                                                   "SMTP password", "push token",
                                                   "mounted into the", "revision, never a",
                                                   "plain env value"], first=46, lead=12.4, tsize=11)
card(865, 756, 152, 116, "registry", "Artifact Registry", ["the two images",
                                                           "built by",
                                                           "scripts/deploy.sh"], first=46, lead=12.4, tsize=11)
card(1032, 756, 152, 116, "chart", "Observability", ["Cloud Logging · Monitoring",
                                                            "budget at 25/50/90/100%",
                                                            "an alert the moment",
                                                            "anything is dead-lettered",
                                                            "a log metric counting",
                                                            "injection attempts"], first=46, lead=12.4, tsize=11)

# ---------------------------------------------------------------- left column
card(24, 140, 190, 88, "person", "Buyer", ['"I want to make a 50ml',
                                           'perfume, 500 units."'], first=46, lead=13)
card(24, 322, 190, 132, "tofu", "terraform/", ["OpenTofu. Cloud Run, Firestore,",
                                               "Pub/Sub, Tasks, Scheduler, IAM,",
                                               "keys, budgets — nothing here is",
                                               "created by hand, so tofu plan is",
                                               "the review surface for a deploy."], first=48, lead=13)
card(24, 500, 190, 124, "deploy", "scripts/deploy.sh", ["Runs the tests, builds both",
                                                        "images with Cloud Build, and",
                                                        "stops at tofu plan. A human",
                                                        "reads the diff and applies it.",
                                                        "Nothing here deploys itself."], first=48, lead=13)

# legend
box(24, 760, 190, 122, "#F8F9FA", "#DADCE0", 6)
text(38, 782, "Legend", 10.5, "#3C4043", "600")
poly([(38, 800), (78, 800)])
text(86, 803.5, "synchronous call", 9.3)
poly([(38, 824), (78, 824)], color=EVENT, dash="5 4")
text(86, 827.5, "event delivery —", 9.3)
text(86, 840, "OIDC + shared token", 9.3)
poly([(38, 858), (78, 858)], color=PROV, dash="2 3")
text(86, 861.5, "provisioning / deploy", 9.3)

# ---------------------------------------------------------------- right column
box(1290, 104, 366, 204, "#F8F9FA", "#BDC1C6", 6, dash="5 4")
text(1304, 126, "Google product APIs  —  one key each, API-restricted", 10.5, "#3C4043", "600")
card(1306, 140, 334, 72, "search", "Programmable Search", [
    "or Gemini search grounding when no engine id is",
    "set. Both read the live web; neither is optional."], first=46, lead=12.5)
card(1306, 224, 334, 72, "pin", "Places API", [
    "does this factory exist where it says it does —",
    "queried by discovery and by the research loop"], first=46, lead=12.5)

box(1290, 332, 366, 430, "#F8F9FA", "#BDC1C6", 6, dash="5 4")
text(1304, 354, "The open web, and the people in it", 10.5, "#3C4043", "600")
card(1306, 372, 334, 88, "globe", "Supplier and trade sites", [
    "read_page — the agent opens the pages it found,",
    "including the /contact page nothing links to,",
    "and every fact keeps the excerpt it came from"], first=46, lead=12.5)
card(1306, 480, 334, 100, "mail", "Mailbox  ·  Gmail", [
    "SMTP out, IMAP in — one app password does both.",
    "Replies re-enter the workflow by In-Reply-To.",
    "Gmail push is wired (/webhooks/gmail) but off.",
    "SUPPLYME_MAIL_REDIRECT_TO is the demo valve."], first=46, lead=12.5)
card(1306, 630, 334, 88, "people", "Suppliers", [
    "Answer in hours or days, in their own words,",
    "in their own language, with a price ladder and",
    "a minimum that contradicts their own website."], first=46, lead=12.5)

# ---------------------------------------------------------------- arrows
# buyer -> console (over the top)
poly([(119, 140), (119, 36), (1004, 36), (1004, 140)])
text(536, 30, "HTTPS  —  the browser reaches the console and nothing else", 9.3)

# console -> api
poly([(824, 210), (744, 210)])
text(784, 203, "run.invoker", 8.6, MUTE, anchor="middle")

# api -> orchestrator
poly([(710, 280), (710, 358)])

# orchestrator <-> agents / engines
poly([(796, 422), (796, 448)], head="both")
poly([(1060, 422), (1060, 448)], head="both")
# agents -> ports
poly([(796, 544), (796, 570)])

# adapters -> pub/sub, cloud tasks
poly([(672, 596), (640, 596), (640, 392), (592, 392)])
text(631, 500, "publish the next event", 9, MUTE, anchor="middle", rotate=-90)
poly([(672, 640), (622, 640), (622, 556), (592, 556)])

# pub/sub -> dead letter
poly([(478, 426), (478, 440)], color=EVENT, dash="4 3")
text(492, 437, "after 5 attempts", 8.6, MUTE)

# returns into the API
poly([(364, 392), (332, 392), (332, 235), (364, 235)], color=EVENT, dash="5 4")
text(326, 330, "/events/pubsub", 8.8, EVENT, anchor="middle", rotate=-90)
poly([(364, 556), (316, 556), (316, 205), (364, 205)], color=EVENT, dash="5 4")
text(310, 490, "/events/task", 8.8, EVENT, anchor="middle", rotate=-90)
poly([(364, 638), (300, 638), (300, 175), (364, 175)], color=EVENT, dash="5 4")
text(294, 600, "/webhooks/mail/poll", 8.8, EVENT, anchor="middle", rotate=-90)

# adapters -> firestore, vertex
poly([(740, 672), (740, 700), (470, 700), (470, 756)])
text(494, 690, "every mission fact, and the timeline", 8.8)
poly([(900, 672), (900, 712), (607, 712), (607, 756)])
text(762, 702, "model calls, metered", 8.8)

# adapters -> the outside world
poly([(1184, 620), (1254, 620), (1254, 176), (1306, 176)])
poly([(1254, 260), (1306, 260)])
poly([(1254, 416), (1306, 416)])
poly([(1254, 530), (1306, 530)], head="both")
for jy in (260, 416, 530):
    add(f'<circle cx="1254" cy="{jy}" r="2.6" fill="{LINE}"/>')
text(1258, 171, "search", 8.6)
text(1258, 255, "maps", 8.6)
text(1258, 411, "pages", 8.6)
text(1258, 525, "mail", 8.6)

# mailbox <-> suppliers
poly([(1400, 580), (1400, 630)])
text(1408, 604, "the ask", 8.8)
poly([(1560, 630), (1560, 580)])
text(1490, 604, "the reply", 8.8, anchor="end")

# provisioning
poly([(214, 388), (264, 388)], color=PROV, dash="2 3")
text(240, 377, "plan → apply", 8.6, PROV, anchor="middle")
poly([(214, 562), (264, 562)], color=PROV, dash="2 3")
text(240, 551, "builds", 8.6, PROV, anchor="middle")

add("</g>")
add("</svg>")

import pathlib
p = pathlib.Path("docs/architecture.svg")
p.write_text("\n".join(out), encoding="utf-8")
print("wrote", p, p.stat().st_size, "bytes")
