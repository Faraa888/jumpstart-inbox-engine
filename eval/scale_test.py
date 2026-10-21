#!/usr/bin/env python3
"""10x test: turns the 510 emails into 5,100 from distinct people, spread across the same week, and runs
the full pipeline twice: week 1 with the facts database as seeded (with gaps), and week 2 after the
answers people gave in week 1 were saved.

    python3 eval/scale_test.py [multiple]          writes eval/scale_report.json

Caveat: clones keep today's mix of topics. Real 10x volume brings new phrasings, so more emails would be
'unknown' and go to a person. That is the safe direction to be wrong in.
"""
import copy, csv, hashlib, json, os, sys, tempfile, time
from datetime import datetime, timedelta
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine.pipeline import run  # noqa: E402

k = int(sys.argv[1]) if len(sys.argv) > 1 else 10
rows = list(csv.DictReader(open(os.path.join(ROOT, "data", "inbox.csv"), newline="", encoding="utf-8")))
lo, hi = datetime(2026, 10, 12, 0, 0), datetime(2026, 10, 18, 23, 59)
out = []
for i in range(k):
    for r in rows:
        x = dict(r, email_id=f"{r['email_id']}-{i}")
        if i:
            u, d = r["from_email"].split("@")
            x["from_email"], x["from_name"] = f"{u}+{i}@{d}", f"{r['from_name']} {i}"
            shift = int(hashlib.md5(x["email_id"].encode()).hexdigest(), 16) % 4320 - 2160  # +/- 36h
            t = datetime.fromisoformat(r["received_at"]) + timedelta(minutes=shift)
            x["received_at"] = min(max(t, lo), hi).isoformat(sep=" ", timespec="minutes")
        out.append(x)


def go(facts=None):
    t = tempfile.mkdtemp()
    p = os.path.join(t, "in.csv")
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(out)
    s = time.time()
    res = run(ROOT, csv_path=p, out_dir=t, db_path=os.path.join(t, "x.db"), quiet=True, facts=facts)
    return res, time.time() - s


facts = json.load(open(os.path.join(ROOT, "config", "facts.json")))
w1, el = go()
# week 2: everything a person answered in week 1 is now in the database
f2 = copy.deepcopy(facts)
for g in w1["facts_log"]:
    if g["event"] == "gap":
        scope, field = g["key"].split(".", 1)
        store = f2["platform"] if scope == "platform" else f2["startups"].setdefault(scope, {})
        store[field] = f2["_simulated_answers"].get(g["key"], f2["_simulated_answers"]["*"])
w2, _ = go(f2)
m1, m2 = w1["metrics"], w2["metrics"]
rep = {"emails": len(out), "seconds": round(el, 1), "week1": m1, "week2": m2,
       "distinct_gaps_week1": sorted({g["key"] for g in w1["facts_log"] if g["event"] == "gap"})}
json.dump(rep, open(os.path.join(ROOT, "eval", "scale_report.json"), "w"), indent=1, default=str)
for name, m in (("week 1", m1), ("week 2", m2)):
    print(f"{name}: {len(out)} emails | sent automatically {m['auto_replies']} | silent {m['silent']} | "
          f"person {m['ops_person_emails']} {m['person']} | talent partner {m['partner']} | "
          f"person time {m['person_hours']}h")
print(f"processing time {el:.1f}s; facts asked once in week 1: {rep['distinct_gaps_week1']}")
