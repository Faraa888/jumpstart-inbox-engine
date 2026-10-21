#!/usr/bin/env python3
"""Blind relabel: writes eval/my_labels.csv with 50 random emails and NO engine output visible.
Fill gold_lane (AUTO, REVIEW, HUMAN, NOREPLY) and gold_family, then:  python3 eval/score.py --gold eval/my_labels.csv
Lane meaning: AUTO = a template reply is safe. REVIEW = reply needed but a person should approve.
HUMAN = needs a person's judgement. NOREPLY = log or act, send nothing.
Families: see FAMILY values in eval/score.py (chase, application, feedback, prep, advice, faq, referral, product, visa,
other, success, thanks, ooo, bug_resolved, vendor, optout, account, bug, privacy, safeguarding, conduct, offer,
interview_urgent, accessibility, wellbeing, unknown).
"""
import csv, os, random
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = list(csv.DictReader(open(os.path.join(ROOT, "data", "inbox.csv"), newline="", encoding="utf-8")))
random.Random(2026).shuffle(rows)
with open(os.path.join(ROOT, "eval", "my_labels.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["email_id", "gold_family", "gold_lane", "subject", "body", "candidate_stage"])
    for r in rows[:50]:
        w.writerow([r["email_id"], "", "", r["subject"], r["body"], r["candidate_stage"]])
print("wrote eval/my_labels.csv")
