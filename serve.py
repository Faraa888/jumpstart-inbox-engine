#!/usr/bin/env python3
"""The engine as a small web service, so n8n can call it, plus the pages a person uses from Slack.
Standard library only.

    python3 serve.py            listens on http://localhost:8080

For n8n
  POST /triage        one email in, one decision out: outcome, reply, delay_seconds, ack, slack_text
  GET  /digest        "N emails need you": Slack text for the morning and afternoon nudge

For the person (links in each Slack message)
  GET  /review?id=    the email, the agents' exchange and an editable reply. "Send reply" hands it to n8n,
                      which sends it through Resend, so the person never opens the inbox.
  GET  /fill?key=     "answer once" for a missing fact; saved to config/facts.json, so the next email that
                      needs it is answered automatically.
  GET  /queue         everything waiting for a person (JSON)
  GET  /console       the inbox console, live: new emails appear by themselves, Send really sends
  GET  /summary       end-of-run Slack summary;  GET /reset clears the live inbox before a fresh run

Candidate details (stage, stream, startup) are looked up from past emails by sender address. In
production they come from Jumpstart's candidate database.

Environment (.env is read if present):
  DEMO_DELAY=1             send automatic replies after 1 minute instead of 5 to 30 (for filming)
  REVIEWER=claude          use Claude as the reviewer agent (needs ANTHROPIC_API_KEY)
  N8N_SEND_WEBHOOK=...     where approved replies go (default http://localhost:5678/webhook/send-reply)
"""
import csv
import html
import json
import os
import socket
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
if os.path.exists(os.path.join(ROOT, ".env")):
    for line in open(os.path.join(ROOT, ".env")):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v.strip().strip('"'))

from engine import reviewer  # noqa: E402
from engine.pipeline import run  # noqa: E402
from build_console import build_html, console_data  # noqa: E402

COLS = ["email_id", "received_at", "from_name", "from_email", "subject", "body", "candidate_stage", "stream", "startup"]
# The CSV stands in for Jumpstart's candidate database (stage, stream, startup by email address).
CANDIDATES = list(csv.DictReader(open(os.path.join(ROOT, "data", "inbox.csv"), newline="", encoding="utf-8")))
HISTORY = []  # emails actually received through n8n, oldest first
FACTS = os.path.join(ROOT, "config", "facts.json")
QUEUE_FILE = os.path.join(ROOT, "out", "live_queue.json")
PORT = int(os.environ.get("PORT", 8080))
BASE = f"http://localhost:{PORT}"
SEND_HOOK = os.environ.get("N8N_SEND_WEBHOOK", "http://localhost:5678/webhook/send-reply")
LABEL = {"critical": "Critical", "gap": "Missing fact", "reviewer": "Reviewer held it back",
         "unknown": "Could not classify", "partner": "Live offer, for the talent partner"}
QUEUE = json.load(open(QUEUE_FILE)) if os.path.exists(QUEUE_FILE) else {}
LIVE_FILE = os.path.join(ROOT, "out", "live_emails.json")
LIVE = json.load(open(LIVE_FILE)) if os.path.exists(LIVE_FILE) else []
try:
    BATCH = console_data()
except FileNotFoundError:
    BATCH = None  # run run.py, eval/score.py and eval/scale_test.py once to enable /console


def save_queue():
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    json.dump(QUEUE, open(QUEUE_FILE, "w"), indent=1)
    for e in LIVE:
        if e["id"] in QUEUE:
            e["status"] = QUEUE[e["id"]]["status"]
    json.dump(LIVE, open(LIVE_FILE, "w"))


def deliverable(addr):
    """Sample-data addresses are fictional: their replies are logged, never emailed."""
    return bool(addr) and not addr.lower().endswith(("@example.com", ".example.com"))


reviewer.claude_for = deliverable  # Claude reviews only replies that will really be sent


def summary():
    from collections import Counter
    c = Counter({"AUTO_REPLY": "answered automatically", "AUTO_ACTION": "no reply needed",
                 "HUMAN": "need a person"}[e["lane"]] for e in LIVE)
    why = Counter(e["why"] for e in LIVE if e["lane"] == "HUMAN")
    text = (f"*Inbox run complete: {len(LIVE)} emails processed*\n"
            f"- {c['answered automatically']} answered automatically\n- {c['no reply needed']} need no reply "
            f"(auto-responders, spam, duplicates, repeat chasers merged)\n- {c['need a person']} need a person: "
            + ", ".join(f"{n} {LABEL.get(k, k).lower()}" for k, n in why.most_common()) +
            f"\nEverything waiting for you: {BASE}/console")
    return {"count": len(LIVE), "slack_text": text}


def send_reply(qid, subject, body):
    q = QUEUE.get(qid)
    if not q or q["status"] == "sent":
        return False, "Not found or already sent"
    q["reply"] = {"subject": subject, "body": body}
    if not deliverable(q["to"]):
        q["status"], q["sent_at"] = "sent", datetime.now().isoformat(timespec="minutes")
        save_queue()
        return True, "Sample address: logged, not emailed."
    try:
        req = urllib.request.Request(SEND_HOOK, data=json.dumps({"to": q["to"], **q["reply"]}).encode(),
                                     headers={"content-type": "application/json"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as ex:
        return False, f"Not sent: n8n didn't answer at {SEND_HOOK} ({type(ex).__name__}). Is the workflow active?"
    q["status"], q["sent_at"] = "sent", datetime.now().isoformat(timespec="minutes")
    save_queue()
    return True, "Sent through Resend via n8n."


def candidate(addr):
    for r in reversed(HISTORY + CANDIDATES):
        if r["from_email"].lower() == addr.lower():
            return r["candidate_stage"], r["stream"], r["startup"]
    return os.environ.get("DEMO_STAGE", "Interviewing"), "Generalist", ""


def norm_time(s):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f%z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            pass
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def agents(e):
    """The agents' exchange, in plain words, for Slack and the review page (the audit trail)."""
    lines = [f"Triage agent: reads this as {e['intent'].replace('_', ' ')}"
             + (f" ({e['sub'].replace('_', ' ')})" if e.get("sub") else "") + f", confidence {e['conf']:.2f}."
             + (f" Risk flags: {', '.join(e['flags'])}." if e.get("flags") else " No risk flags.")]
    r = e.get("review")
    if r:
        lines.append(f"Reviewer agent ({r['mode']}): {'agrees, send it' if r['ok'] else 'objects'}. {r['reason']}.")
    elif e["lane"] == "HUMAN":
        lines.append("Reviewer agent: not asked. Critical emails and live offers never get an automatic reply.")
    if e["lane"] == "HUMAN":
        lines.append(f"Decision: a person, because {e['reasons'][0][0].lower() + e['reasons'][0][1:]}.")
    return lines


def slack_text(e):
    b = e.get("brief") or {}
    lines = [f"*{LABEL.get(e['why'], 'Needs a person')}* | P{e['p']} | {e['name']} <{e['email']}>",
             f"*{b.get('headline', e['summary'])}*", f"> {e['body'][:400]}"]
    if e.get("move"):
        lines.insert(1, f"_{ {'jumpstart': 'Jumpstart', 'startup': 'The startup', 'candidate': 'The candidate', 'none': 'No one'}.get(e['blocker'])} has to act. "
                        f"{e['severity'].capitalize()}. {'Escalated to a person' if e['move'] == 'escalate' else e['move']}._")
    if e.get("ack"):
        lines.append("Acknowledgement sent to the candidate immediately.")
    lines.append("*How the agents got here*\n" + "\n".join(f"- {x}" for x in agents(e)))
    if b.get("steps"):
        lines.append("*Next steps*\n" + "\n".join(f"- {s}" for s in b["steps"][:4]))
    if e["why"] == "gap" and e.get("gap_key"):
        lines.append(f"*Answer once:* {BASE}/fill?key={urllib.parse.quote(e['gap_key'])}")
    lines.append(f"*Review and send the reply:* {BASE}/review?id={e['id']}")
    return "\n".join(lines)


def triage(msg):
    now = datetime.now().replace(second=0, microsecond=0)
    stage, stream, startup = candidate(msg.get("from_email", ""))
    row = {"email_id": msg.get("email_id") or f"L{now:%m%d%H%M%S}{len(HISTORY)}",
           "received_at": norm_time(msg.get("received_at")), "from_name": msg.get("from_name") or msg.get("from_email", ""),
           "from_email": msg.get("from_email", ""), "subject": msg.get("subject") or "(no subject)",
           "body": (msg.get("body") or "").strip()[:4000], "candidate_stage": msg.get("candidate_stage") or stage,
           "stream": msg.get("stream") or stream, "startup": msg.get("startup") or startup}
    with tempfile.TemporaryDirectory() as t:
        p = os.path.join(t, "in.csv")
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(HISTORY + [row])
        run(ROOT, csv_path=p, out_dir=t, db_path=os.path.join(t, "x.db"), quiet=True, now=now, simulate_fill=False)
        data = json.load(open(os.path.join(t, "console_data.json")))
    HISTORY.append(row)
    e = next(x for x in data["emails"] if x["id"] == row["email_id"])
    delay = 0
    if e["lane"] == "AUTO_REPLY":
        delay = int(os.environ["DEMO_DELAY"]) * 60 if os.environ.get("DEMO_DELAY") else \
            max(60, int((datetime.fromisoformat(e["send_at"]) - now).total_seconds()))
    out = {k: e.get(k) for k in ("id", "lane", "why", "p", "owner", "intent", "sub", "flags", "reasons", "summary",
                                 "reply", "ack", "review", "gap_key", "actions", "proposed", "send_at")}
    out["outcome"] = {"AUTO_REPLY": "auto", "AUTO_ACTION": "silent", "HUMAN": "person"}[e["lane"]]
    out["delay_seconds"] = delay
    out["to"] = row["from_email"]
    out["deliver"] = deliverable(row["from_email"])
    out["agents"] = agents(e)
    out["slack_text"] = slack_text(e) if e["lane"] == "HUMAN" else ""
    if e["lane"] == "HUMAN":
        b = e.get("brief") or {}
        subj = row["subject"] if row["subject"].lower().startswith("re:") else "Re: " + row["subject"]
        QUEUE[e["id"]] = {"id": e["id"], "at": row["received_at"], "name": row["from_name"], "to": row["from_email"],
                          "subject": row["subject"], "body": row["body"], "why": e["why"], "p": e["p"],
                          "headline": b.get("headline", e["summary"]), "steps": b.get("steps", []),
                          "agents": out["agents"], "gap_key": e.get("gap_key", ""),
                          "reply": {"subject": subj, "body": b.get("reply", "")}, "status": "open"}
    live = dict(e, live=True, status="open" if e["lane"] == "HUMAN" else "")
    LIVE.append(live)
    save_queue()
    return out


def digest():
    open_items = sorted((q for q in QUEUE.values() if q["status"] == "open"), key=lambda q: (q["p"], q["at"]))
    if not open_items:
        return {"count": 0, "slack_text": ""}
    lines = [f"*{len(open_items)} email{'s need' if len(open_items) > 1 else ' needs'} you today*"]
    for q in open_items:
        lines.append(f"- P{q['p']} {LABEL.get(q['why'], 'Person')}: {q['headline']} ({q['name']}, received {q['at']}) "
                     f"{BASE}/review?id={q['id']}")
    lines.append("Everything else has been answered automatically.")
    return {"count": len(open_items), "slack_text": "\n".join(lines)}


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{title}</title><body style="font:16px/1.5 system-ui;max-width:720px;margin:32px auto;padding:0 16px;color:#15233d">
{content}</body>"""


def review_page(q, note=""):
    sent = q["status"] == "sent"
    return PAGE.format(title="Review and send", content=f"""
<h1 style="font-family:Georgia,serif;margin:0 0 4px">{html.escape(q['headline'])}</h1>
<p style="color:#5b6a7d;margin:0 0 16px">{html.escape(LABEL.get(q['why'], 'Person'))}, P{q['p']}. {html.escape(q['name'])} &lt;{html.escape(q['to'])}&gt;, {html.escape(q['at'])}</p>
<p style="background:#eef1f5;border-radius:6px;padding:10px 12px;font-style:italic">{html.escape(q['subject'])}: {html.escape(q['body'])}</p>
<h3 style="margin:18px 0 4px;font-size:15px">How the agents got here</h3><ul style="margin:0">{''.join(f'<li>{html.escape(a)}</li>' for a in q['agents'])}</ul>
{'<h3 style="margin:18px 0 4px;font-size:15px">Next steps</h3><ul style="margin:0">' + ''.join(f'<li>{html.escape(s)}</li>' for s in q['steps']) + '</ul>' if q['steps'] else ''}
{f'<p><a href="/fill?key={urllib.parse.quote(q["gap_key"])}">Answer the missing fact once</a></p>' if q['gap_key'] else ''}
<form method=post action=/review><input type=hidden name=id value="{html.escape(q['id'])}">
<h3 style="margin:18px 0 4px;font-size:15px">Reply</h3>
<input name=subject value="{html.escape(q['reply']['subject'])}" style="width:100%;font:inherit;padding:6px 8px;margin-bottom:8px" {'disabled' if sent else ''}>
<textarea name=body rows=12 style="width:100%;font:inherit;padding:8px" {'disabled' if sent else ''}>{html.escape(q['reply']['body'])}</textarea>
<p><button style="font:inherit;padding:8px 18px;background:#15233d;color:#fff;border:0;border-radius:6px" {'disabled' if sent else ''}>{'Sent' if sent else 'Send reply'}</button>
<span style="color:#0f7c7b;font-weight:600;margin-left:10px">{html.escape(note)}</span></p></form>""")


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == "/fill":
            key = qs.get("key", [""])[0]
            return self._send(200, PAGE.format(title="Answer once", content=f"""
<h1 style="font-family:Georgia,serif">Answer once</h1><p>Missing fact: <b>{html.escape(key)}</b></p>
<p style="color:#5b6a7d">Your answer is saved to the facts database. Every later email that needs it is answered automatically.</p>
<form method=post action=/fill><input type=hidden name=key value="{html.escape(key)}">
<textarea name=value rows=4 style="width:100%;font:inherit" required></textarea>
<p><button style="font:inherit;padding:8px 16px">Save answer</button></p></form>"""), "text/html; charset=utf-8")
        if u.path == "/review":
            q = QUEUE.get(qs.get("id", [""])[0])
            if not q:
                return self._send(404, PAGE.format(title="Not found", content="<p>That email isn't in the queue.</p>"),
                                  "text/html; charset=utf-8")
            return self._send(200, review_page(q), "text/html; charset=utf-8")
        if u.path == "/console":
            if not BATCH:
                return self._send(500, PAGE.format(title="Run the batch first", content="<p>Run python3 run.py, "
                                  "eval/score.py and eval/scale_test.py once, then restart serve.py.</p>"), "text/html; charset=utf-8")
            return self._send(200, build_html(True, LIVE, BATCH), "text/html; charset=utf-8")
        if u.path == "/summary":
            return self._send(200, summary())
        if u.path == "/reset":
            HISTORY.clear(); LIVE.clear(); QUEUE.clear(); save_queue()
            return self._send(200, {"ok": True, "note": "live inbox cleared"})
        if u.path == "/console/live":
            return self._send(200, LIVE)
        if u.path == "/digest":
            return self._send(200, digest())
        if u.path == "/queue":
            return self._send(200, list(QUEUE.values()))
        self._send(200, {"ok": True, "history": len(HISTORY), "waiting_for_a_person": digest()["count"]})

    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(n).decode("utf-8")
        if self.path == "/fill":
            q = urllib.parse.parse_qs(raw)
            key, value = q.get("key", [""])[0], q.get("value", [""])[0].strip()
            facts = json.load(open(FACTS))
            scope, field = key.split(".", 1)
            store = facts["platform"] if scope == "platform" else facts["startups"].setdefault(scope, {})
            store[field] = value
            json.dump(facts, open(FACTS, "w"), indent=2, ensure_ascii=False)
            return self._send(200, PAGE.format(title="Saved", content=f"<p>Saved <b>{html.escape(key)}</b>. The next email "
                                               "that needs it will be answered automatically.</p>"), "text/html; charset=utf-8")
        if self.path == "/review":
            f = urllib.parse.parse_qs(raw)
            qid = f.get("id", [""])[0]
            if qid not in QUEUE:
                return self._send(400, PAGE.format(title="Error", content="<p>Not found.</p>"), "text/html; charset=utf-8")
            ok, note = send_reply(qid, f.get("subject", [QUEUE[qid]["reply"]["subject"]])[0], f.get("body", [""])[0])
            return self._send(200, review_page(QUEUE[qid], note), "text/html; charset=utf-8")
        if self.path == "/send":
            j = json.loads(raw)
            ok, note = send_reply(j.get("id", ""), j.get("subject", ""), j.get("body", ""))
            return self._send(200, {"ok": ok, "error": "" if ok else note})
        if self.path != "/triage":
            return self._send(404, {"error": "use POST /triage"})
        try:
            self._send(200, triage(json.loads(raw)))
        except Exception as ex:  # fail safe: if the engine breaks, a person looks at the email
            self._send(200, {"lane": "HUMAN", "outcome": "person", "why": "unknown", "delay_seconds": 0, "ack": None,
                             "reply": None, "slack_text": f"*Engine error, please handle by hand*: {ex}"})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s\n" % (fmt % args))


class DualStackServer(HTTPServer):
    """Listens on IPv6 and IPv4: n8n resolves localhost to ::1, other clients to 127.0.0.1."""
    address_family = socket.AF_INET6
    request_queue_size = 64  # a replay arrives faster than one request at a time

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


if __name__ == "__main__":
    print(f"engine listening on {BASE}")
    DualStackServer(("::", PORT), H).serve_forever()
