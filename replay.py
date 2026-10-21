#!/usr/bin/env python3
"""Replay the 510 sample emails into the live system, as if they had just landed in the inbox.

    python3 replay.py              through n8n (the full live path: engine, Slack, dashboard)
    python3 replay.py --direct     straight to the engine, if n8n isn't running
    python3 replay.py --rate 8     emails per second (default 4, so the run takes about 2 minutes)
    python3 replay.py --limit 50   only the first N

Each email goes through exactly the same path as a real one. The sample addresses are fictional
(@example.com), so their replies are logged, not emailed; your own test emails get real replies.
At the end n8n posts a summary to Slack. Open http://localhost:8080/console to watch it fill.
"""
import argparse
import csv
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--direct", action="store_true")
ap.add_argument("--rate", type=float, default=4)
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--n8n", default="http://localhost:5678/webhook")
ap.add_argument("--engine", default="http://localhost:8080")
a = ap.parse_args()


def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"content-type": "application/json"})
    return urllib.request.urlopen(req, timeout=30).read()


rows = list(csv.DictReader(open(os.path.join(ROOT, "data", "inbox.csv"), newline="", encoding="utf-8")))
rows.sort(key=lambda r: (r["received_at"], r["email_id"]))
if a.limit:
    rows = rows[:a.limit]
urllib.request.urlopen(f"{a.engine}/reset").read()
target = f"{a.engine}/triage" if a.direct else f"{a.n8n}/inbound-email"
print(f"Replaying {len(rows)} emails into {target} at {a.rate}/s. Watch {a.engine}/console")
start = time.time()
for i, r in enumerate(rows, 1):
    post(target, r)
    if i % 25 == 0 or i == len(rows):
        print(f"  {i}/{len(rows)}")
    time.sleep(1 / a.rate)
if not a.direct:
    time.sleep(3)
    post(f"{a.n8n}/replay-done", {"emails": len(rows)})
print(f"Done in {time.time() - start:.0f}s.")
print(json.loads(urllib.request.urlopen(f"{a.engine}/summary").read())["slack_text"])
