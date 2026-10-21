"""Orchestrator: ingest -> classify -> cases -> policy -> actions -> outputs.

Idempotent: emails are keyed by email_id and actions by idempotency key, so running
twice never double-sends. Swap `classify_fn` for the LLM adapter to use a model
instead of rules; nothing downstream changes.
"""
import csv
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime

from .classify import classify
from .cases import build_context
from .policy import decide
from .actions import execute
from .resolve import resolve, merge_pending, FactsState
from .util import parse_dt

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails(email_id TEXT PRIMARY KEY, received_at TEXT, from_name TEXT, from_email TEXT,
  subject TEXT, body TEXT, candidate_stage TEXT, stream TEXT, startup TEXT);
CREATE TABLE IF NOT EXISTS classifications(email_id TEXT PRIMARY KEY, intent TEXT, sub TEXT, confidence REAL,
  rule TEXT, flags TEXT, entities TEXT);
CREATE TABLE IF NOT EXISTS decisions(email_id TEXT PRIMARY KEY, lane TEXT, priority INTEGER, owner TEXT,
  reasons TEXT, summary TEXT, reply TEXT);
CREATE TABLE IF NOT EXISTS actions(idem_key TEXT PRIMARY KEY, email_id TEXT, action TEXT, status TEXT,
  payload TEXT, ts TEXT);
"""


def load_cfg(root):
    with open(os.path.join(root, "config", "policy.json")) as f:
        policy = json.load(f)
    with open(os.path.join(root, "config", "templates.json")) as f:
        templates = json.load(f)
    with open(os.path.join(root, "config", "facts.json")) as f:
        facts = json.load(f)
    from .act import load_candidates
    return {"policy": policy, "templates": templates, "facts": facts, "candidates": load_candidates(root)}


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["startup"] = (r.get("startup") or "").strip()
    rows.sort(key=lambda r: (r["received_at"], r["email_id"]))
    return rows


def run(root, csv_path=None, db_path=None, out_dir=None, classify_fn=None, quiet=False, now=None, simulate_fill=True, facts=None):
    cfg = load_cfg(root)
    if facts is not None:
        cfg["facts"] = facts
    now = now or datetime.fromisoformat(cfg["policy"]["now"])
    csv_path = csv_path or os.path.join(root, "data", "inbox.csv")
    out_dir = out_dir or os.path.join(root, "out")
    db_path = db_path or os.path.join(out_dir, "inbox.db")
    os.makedirs(out_dir, exist_ok=True)
    classify_fn = classify_fn or classify
    rows = read_csv(csv_path)
    startups = sorted({s.strip() for r in rows for s in r["startup"].split(";") if s.strip()})

    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)
    new_emails = 0
    for r in rows:
        cur = db.execute("INSERT OR IGNORE INTO emails VALUES(?,?,?,?,?,?,?,?,?)",
                         (r["email_id"], r["received_at"], r["from_name"], r["from_email"], r["subject"], r["body"],
                          r["candidate_stage"], r["stream"], r["startup"]))
        new_emails += cur.rowcount

    cls = {}
    for r in rows:
        c = classify_fn(r["subject"], r["body"], r["candidate_stage"], r["startup"], startups)
        cls[r["email_id"]] = c
        db.execute("INSERT OR REPLACE INTO classifications VALUES(?,?,?,?,?,?,?)",
                   (r["email_id"], c.intent, c.sub, c.confidence, c.rule, ",".join(c.flags),
                    json.dumps(c.entities)))
    ctx = build_context(rows, cls, cfg["policy"]["params"])
    cfg["emails_by_id"] = {r["email_id"]: r for r in rows}
    cfg["cls_by_id"] = cls

    results, new_actions = [], 0
    facts = FactsState(cfg["facts"], simulate_fill=simulate_fill)
    state = {"thanked": set(), "alerted": set(), "crit_cases": {}, "signoff_days": set(), "asked": set(), "log": []}
    for r in rows:
        c = cls[r["email_id"]]
        d = decide(r, c, ctx, cfg, now)
        d = resolve(r, c, ctx, d, cfg, now, facts, state)
        results.append({"email": r, "cls": c, "dec": d, "thread_n": ctx["thread_n"][r["email_id"]],
                        "case_id": case_id_for(r["email_id"], ctx, c.entities.get("startup", ""), d)})
    merge_pending(results, ctx)
    for x in results:
        r, c, d = x["email"], x["cls"], x["dec"]
        written = execute(r, c, ctx, d, now, db)
        new_actions += len(written)
        db.execute("INSERT OR REPLACE INTO decisions VALUES(?,?,?,?,?,?,?)",
                   (r["email_id"], d["lane"], d["priority"], d["owner"], json.dumps(d["reasons"]), d["summary"],
                    json.dumps(d["reply"])))
    db.commit()
    cfg["facts_state"] = facts
    merged = {x["email"]["email_id"] for x in results if x["dec"].get("merged_into")}
    cfg["action_log"] = [a for a in state["log"] if a.get("email_id") not in merged or a["type"] == "ask_startup"]

    out = build_outputs(results, ctx, cfg, now)
    out["run"] = {"emails": len(rows), "new_emails": new_emails, "new_actions": new_actions}
    write_outputs(out, results, out_dir)
    if not quiet:
        m = out["metrics"]
        print(f"{m['emails']} emails -> {m['lanes']}  | person: {m['person']} | person time {m['person_hours']}h/week")
    db.close()
    return out


def case_id_for(eid, ctx, startup="", dec=None):
    for cid, inc in ctx["incidents"].items():
        if eid in inc["email_ids"]:
            return cid
    for s, w in ctx["watchlist"].items():
        if eid in w["emails"] and w["kind"] != "review":
            return "WATCH-" + s.upper().replace(" ", "-")
    w = ctx["watchlist"].get(startup)
    if dec and w and w["kind"] != "review" and any("list:" in r for r in dec["reasons"]):
        return "WATCH-" + startup.upper().replace(" ", "-")
    return ""


def build_outputs(results, ctx, cfg, now):
    pol = cfg["policy"]
    lanes = Counter(x["dec"]["lane"] for x in results)
    intents = Counter(x["cls"].intent for x in results)
    prio = Counter(f"P{x['dec']['priority']}" for x in results if x["dec"]["lane"] in ("HUMAN", "DRAFT"))
    human = [x for x in results if x["dec"]["lane"] == "HUMAN"]
    drafts = [x for x in results if x["dec"]["lane"] == "DRAFT"]
    # human cases: collapse people with several human emails, and startup watch groups
    case_keys = set()
    for x in human:
        e = x["email"]
        w = x.get("case_id", "")
        case_keys.add(w if w.startswith("WATCH-") else ctx["ident"][e["email_id"]])
    # startup digests
    digests = defaultdict(list)
    seen = set()
    for x in results:
        if "add_to_startup_digest" in x["dec"]["actions"]:
            s = x["cls"].entities.get("startup")
            key = (s, ctx["ident"][x["email"]["email_id"]])
            if key in seen:
                continue
            seen.add(key)
            digests[s].append({"candidate": x["email"]["from_name"], "waiting_days": x["cls"].entities.get("waiting_days"),
                               "round": x["cls"].entities.get("round", ""),
                               "chased": ctx["thread_n"][x["email"]["email_id"]], "email_id": x["email"]["email_id"]})
    # product feedback
    pf = Counter(x["cls"].sub for x in results if x["cls"].intent == "product_feedback")
    pf.update({"visa_sponsorship_filter": intents.get("visa_sponsorship", 0)})
    aged = [{"email_id": x["email"]["email_id"], "candidate": x["email"]["from_name"],
             "waiting_days": x["cls"].entities.get("waiting_days")}
            for x in results if "escalate_aged_application" in x["dec"]["actions"]]
    compliance = {
        "unsubscribes": sum(1 for x in results if x["cls"].intent == "unsubscribe"),
        "deletions": sum(1 for x in results if x["cls"].intent == "data_deletion"),
        "sars": [x["email"]["email_id"] for x in results if x["cls"].intent == "sar"],
    }
    # repeat chasers collapsed
    dups = [x["email"]["email_id"] for x in results if x["email"]["email_id"] in ctx["dup_of"]]
    auto = lanes.get("AUTO_REPLY", 0) + lanes.get("AUTO_ACTION", 0)
    metrics = {
        "emails": len(results), "unique_people": len({ctx["ident"][x["email"]["email_id"]] for x in results}),
        "lanes": dict(lanes), "intents": dict(intents), "priorities": dict(prio),
        "human_emails": len(human), "human_cases": len(case_keys), "drafts": len(drafts),
        "auto_share": round(auto / len(results), 3), "duplicates": len(dups),
        "replies_sent_dry_run": lanes.get("AUTO_REPLY", 0),
        "sla_overdue_now": sum(1 for x in results if x["dec"]["overdue_h"] > 0),
        "kb_assumed_replies": sum(1 for x in results if x["dec"].get("kb_assumed")),
    }
    pr = Counter(x["dec"]["person_reason"] for x in human)
    metrics["person"] = {"critical": pr.get("critical", 0), "gap": pr.get("gap", 0), "reviewer": pr.get("reviewer", 0),
                         "unknown": pr.get("unknown", 0),
                         "signoff": sum(1 for x in results if x["dec"].get("signoff")),
                         "alert": sum(1 for x in results if x["dec"].get("alert"))}
    metrics["partner"] = pr.get("partner", 0)
    metrics["person_minutes"] = sum(x["dec"].get("person_minutes", 0) for x in results)
    metrics["person_hours"] = round(metrics["person_minutes"] / 60, 1)
    metrics["ops_person_emails"] = len(human) - metrics["partner"]
    metrics["silent"] = lanes.get("AUTO_ACTION", 0)
    metrics["auto_replies"] = lanes.get("AUTO_REPLY", 0)
    metrics["acks_now"] = sum(1 for x in results if x["dec"].get("ack"))
    metrics["merged"] = sum(1 for x in results if x["dec"].get("merged_into"))
    metrics["reviewed"] = sum(1 for x in results if x["dec"].get("review"))
    fs = cfg.get("facts_state")
    gaps = [g for g in (fs.log if fs else []) if g["event"] == "gap"]
    metrics["facts_gaps_hit"] = len(gaps)
    metrics["facts_filled"] = sum(1 for g in (fs.log if fs else []) if g["event"] == "filled")
    return {"metrics": metrics, "incidents": ctx["incidents"], "watchlist": ctx["watchlist"],
            "digests": digests, "product_feedback": dict(pf), "aged_applications": aged,
            "compliance": compliance, "startup_stats": ctx["startup_stats"], "dup_of": ctx["dup_of"],
            "now": now.isoformat(), "params": pol["params"],
            "facts_log": cfg["facts_state"].log if cfg.get("facts_state") else [],
            "facts_seed": cfg["facts"], "action_log": cfg.get("action_log", []),
            "startup_emails": startup_emails(cfg.get("action_log", []), now)}


def startup_emails(log, now):
    """One email per startup per day: who's waiting on them, and any questions for the startup bank.
    A person approves each one before it's sent."""
    by = defaultdict(lambda: {"waiting": [], "questions": []})
    for a in log:
        if a["type"] == "chase_startup" and a.get("startup"):
            by[a["startup"]]["waiting"].append(a)
        elif a["type"] == "ask_startup":
            by[a["startup"]]["questions"].append(a["question"])
    out = {}
    for s, v in sorted(by.items()):
        seen, wl = set(), []
        for a in v["waiting"]:
            if a["candidate_email"] in seen:
                continue
            seen.add(a["candidate_email"])
            rnd = f", {a['round']} interview" if a.get("round") else ""
            wait = f", waiting {a['waiting_days']} days" if a.get("waiting_days") else ""
            wl.append(f"- {a['candidate']}{rnd}{wait}: could you share {a['ask']}?")
        lines = [f"Hi {s} team,", "", f"{len(wl)} candidate{'s are' if len(wl) != 1 else ' is'} waiting to hear from you. "
                 "A one-line reply for each is perfect, and we'll pass it on.", ""] + wl
        if v["questions"]:
            lines += ["", "One question so we can answer candidates ourselves next time:"] + \
                     [f"- {q}" for q in dict.fromkeys(v["questions"])]
        lines += ["", "Thanks,", "The Jumpstart team"]
        out[s] = {"startup": s, "waiting": len(wl), "questions": len(set(v["questions"])),
                  "subject": f"Candidates waiting on {s}: {len(wl)} update{'s' if len(wl) != 1 else ''} needed",
                  "body": "\n".join(lines), "status": "awaiting_approval"}
    return out


def write_outputs(out, results, out_dir):
    cols = ["email_id", "received_at", "from_name", "from_email", "subject", "body", "candidate_stage", "stream",
            "startup", "dup_of", "thread_n", "intent", "sub", "confidence", "rule", "flags", "lane", "priority",
            "owner", "overdue_h", "summary", "why_escalated", "reply_subject", "reply_body", "actions_executed",
            "actions_proposed", "case_id"]
    ctx_dup = out["dup_of"]
    with open(os.path.join(out_dir, "inbox_triaged.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for x in results:
            e, c, d = x["email"], x["cls"], x["dec"]
            w.writerow([e["email_id"], e["received_at"], e["from_name"], e["from_email"], e["subject"], e["body"],
                        e["candidate_stage"], e["stream"], e["startup"], ctx_dup.get(e["email_id"], ""),
                        x.get("thread_n", ""), c.intent, c.sub, c.confidence, c.rule, ",".join(c.flags),
                        d["lane"], f"P{d['priority']}", d["owner"], d["overdue_h"], d["summary"],
                        "; ".join(d["reasons"]), (d["reply"] or {}).get("subject", ""),
                        (d["reply"] or {}).get("body", ""), ",".join(d["actions"]), ",".join(d["proposed"]),
                        x.get("case_id", "")])
    data = []
    for x in results:
        e, c, d = x["email"], x["cls"], x["dec"]
        data.append({"id": e["email_id"], "at": e["received_at"], "name": e["from_name"], "email": e["from_email"],
                     "subject": e["subject"], "body": e["body"], "stage": e["candidate_stage"], "stream": e["stream"],
                     "startup": e["startup"], "intent": c.intent, "sub": c.sub, "conf": c.confidence,
                     "rule": c.rule, "flags": c.flags, "lane": d["lane"], "p": d["priority"], "owner": d["owner"],
                     "reasons": d["reasons"], "summary": d["summary"], "actions": d["actions"],
                     "proposed": d["proposed"], "reply": d["reply"], "brief": d["brief"],
                     "overdue_h": d["overdue_h"], "deadline": d["deadline"], "dup_of": ctx_dup.get(e["email_id"], ""),
                     "kb_assumed": d.get("kb_assumed", False), "case": x.get("case_id", ""),
                     "why": d.get("person_reason", ""), "send_at": d.get("send_at"), "ack": d.get("ack"),
                     "review": d.get("review"), "alert": d.get("alert", ""), "signoff": d.get("signoff", False),
                     "gap_key": d.get("gap_key", ""), "merged_into": d.get("merged_into", ""),
                     "template": d.get("template"), "blocker": d.get("blocker"), "severity": d.get("severity"),
                     "move": d.get("move"), "who": d.get("who"), "known_update": d.get("known_update", False)})
    with open(os.path.join(out_dir, "console_data.json"), "w") as f:
        json.dump({"emails": data, **{k: v for k, v in out.items()}}, f, default=str)
    with open(os.path.join(out_dir, "metrics.json"), "w") as f:
        json.dump(out["metrics"], f, indent=2)
