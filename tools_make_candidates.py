#!/usr/bin/env python3
"""Generate data/candidates_mock.csv: a mock candidate record per person, standing in for an applicant
tracking system. The sample CSV has no stage history or startup feedback, so this invents a plausible,
deterministic record from what the emails say (stage, startup, interview round, days waiting).
About one in five candidates waiting on a startup has an update already on file, so the demo shows both
"we already know" and "we need to chase".
"""
import csv, hashlib, json, os, re, sys
from datetime import datetime, timedelta
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from engine.classify import classify  # noqa: E402

rows = list(csv.DictReader(open(os.path.join(ROOT, "data", "inbox.csv"), newline="", encoding="utf-8")))
startups = sorted({s.strip() for r in rows for s in r["startup"].split(";") if s.strip()})
h = lambda s: int(hashlib.md5(s.encode()).hexdigest(), 16)  # noqa: E731
recs = {}
for r in sorted(rows, key=lambda r: r["received_at"]):
    c = classify(r["subject"], r["body"], r["candidate_stage"], r["startup"], startups)
    key = r["from_email"].lower()
    rec = recs.setdefault(key, {"email": r["from_email"], "name": r["from_name"], "stage": r["candidate_stage"],
                                "startup": "", "round": "", "last_contact_days": "", "startup_update": "",
                                "startup_update_on": ""})
    rec["stage"] = r["candidate_stage"]
    st = c.entities.get("startup") or ""
    if st:
        rec["startup"] = st
    if c.entities.get("round"):
        rec["round"] = c.entities["round"]
    if c.entities.get("waiting_days"):
        rec["last_contact_days"] = c.entities["waiting_days"]
for key, rec in recs.items():
    if rec["stage"] == "Interviewing" and rec["startup"] and not rec["round"]:
        rec["round"] = ["first", "second", "first"][h(key) % 3]
    if rec["stage"] == "Interviewing" and rec["startup"] and rec["startup"] not in ("Driftwell", "Saltmarsh") \
            and h(key + "u") % 5 == 0:
        on = datetime(2026, 10, 14) + timedelta(days=h(key) % 4)
        by = on + timedelta(days=5 + h(key) % 3)
        while by.weekday() >= 5:
            by += timedelta(days=1)
        rec["startup_update_on"] = on.strftime("%Y-%m-%d")
        rec["startup_update"] = f"they expect to make a decision on this round by {by.strftime('%A %d %B').replace(' 0', ' ')}"
cols = ["email", "name", "stage", "startup", "round", "last_contact_days", "startup_update", "startup_update_on"]
with open(os.path.join(ROOT, "data", "candidates_mock.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(recs.values())
print(len(recs), "candidates;", sum(1 for r in recs.values() if r["startup_update"]), "with a startup update on file")
