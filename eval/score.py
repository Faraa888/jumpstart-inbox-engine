#!/usr/bin/env python3
"""Score the engine against labelled data.

    python3 eval/score.py                 # gold set (eval/gold_claude.csv) + adversarial set
    python3 eval/score.py --gold my.csv   # your own labels: email_id,gold_family,gold_lane

Lane vocabulary:  AUTO (safe to auto-reply)  REVIEW (reply needed, a person approves)
                  HUMAN (needs a person's judgement)  NOREPLY (act or log, send nothing)

Headline safety metric: of emails that truly need a HUMAN, how many were routed to a human?
Anything below 100% means a risky email would have been answered by a template.
"""
import argparse
import csv
import json
import os
import shutil
import sys
import tempfile
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine.pipeline import run  # noqa: E402

LANE_MAP = {"AUTO_REPLY": "AUTO", "AUTO_ACTION": "NOREPLY", "DRAFT": "REVIEW", "HUMAN": "HUMAN"}
FAMILY = {
    "status_chase": "chase", "application_status": "application", "feedback_request": "feedback",
    "rejection_notice": "feedback", "interview_prep": "prep", "salary_guidance": "advice", "reference_help": "advice",
    "faq": "faq", "referral": "referral", "product_feedback": "product", "visa_sponsorship": "visa",
    "negative_experience": "other", "placement_success": "success", "thanks": "thanks", "ooo_autoreply": "ooo",
    "video_resolved": "bug_resolved", "vendor_inbound": "vendor", "unsubscribe": "optout", "data_deletion": "optout",
    "account_admin": "account", "platform_bug": "bug", "sar": "privacy", "data_incident": "privacy",
    "complaint_regulatory": "privacy", "rtw_documents": "privacy", "discrimination_report": "safeguarding",
    "startup_conduct": "conduct", "reputational_threat": "conduct", "offer_support": "offer",
    "offer_withdrawn": "offer", "reschedule_request": "interview_urgent", "startup_no_show": "interview_urgent",
    "accessibility_request": "accessibility", "wellbeing_concern": "wellbeing", "unknown": "unknown",
}
RANK = {"NOREPLY": 0, "AUTO": 1, "REVIEW": 2, "HUMAN": 3}


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def results_by_id(out_dir):
    rows = {r["email_id"]: r for r in load(os.path.join(out_dir, "inbox_triaged.csv"))}
    return rows


def report_gold(gold, res, label):
    n = len(gold)
    exact = fam = 0
    unsafe, missed_reply, over, under_review = [], [], [], []
    conf = Counter()
    miss_rows = []
    for g in gold:
        r = res[g["email_id"]]
        lane = LANE_MAP[r["lane"]]
        fam_e = "bug_resolved" if (r["intent"] == "platform_bug" and r["sub"] == "resolved") else FAMILY[r["intent"]]
        if r["intent"] == "chase" or r["lane"] == "AUTO_ACTION" and r["summary"].startswith("Duplicate"):
            pass
        conf[(g["gold_lane"], lane)] += 1
        if lane == g["gold_lane"]:
            exact += 1
        else:
            miss_rows.append((g["email_id"], g["gold_lane"], lane, r["intent"], r["summary"]))
        if fam_e == g["gold_family"] or (r["dup_of"] and g["gold_family"] == "chase"):
            fam += 1
        if g["gold_lane"] == "HUMAN" and lane != "HUMAN":
            unsafe.append(g["email_id"])
        if g["gold_lane"] == "AUTO" and lane == "HUMAN" and r["why_escalated"].startswith("Reviewer disagreed"):
            pass  # reviewer held it back: safe, costs a person 2 minutes
        if g["gold_lane"] == "REVIEW" and lane in ("AUTO", "NOREPLY"):
            under_review.append(g["email_id"])
        if g["gold_lane"] in ("AUTO", "REVIEW") and lane == "NOREPLY":
            missed_reply.append(g["email_id"])
        if RANK[lane] > RANK[g["gold_lane"]] and g["gold_lane"] != "NOREPLY":
            over.append(g["email_id"])
    gh = [g for g in gold if g["gold_lane"] == "HUMAN"]
    out = {
        "set": label, "n": n, "lane_exact": round(exact / n, 3), "family_accuracy": round(fam / n, 3),
        "human_recall": round((len(gh) - len(unsafe)) / len(gh), 3) if gh else None,
        "gold_human": len(gh), "human_missed": unsafe, "review_sent_auto": under_review,
        "missed_reply": missed_reply, "over_escalated": over,
        "confusion": {f"{a}->{b}": v for (a, b), v in sorted(conf.items())}, "disagreements": miss_rows,
    }
    return out


def report_adv(adv, res):
    rows, bad_unsafe, bad_forbidden = [], [], []
    ok = 0
    for a in adv:
        r = res[a["email_id"]]
        lane = LANE_MAP[r["lane"]]
        exp = a["expected_lane"]
        good = lane == exp or (exp in ("AUTO", "REVIEW") and RANK[lane] > RANK[exp] and lane != "NOREPLY")
        # safety: anything expected HUMAN must be HUMAN; never silently auto
        if exp == "HUMAN" and lane != "HUMAN":
            bad_unsafe.append(a["email_id"])
            good = False
        if exp == "REVIEW" and lane in ("AUTO", "NOREPLY"):
            bad_unsafe.append(a["email_id"])
            good = False
        if a["forbidden_intent"] and r["intent"] == a["forbidden_intent"]:
            bad_forbidden.append(a["email_id"])
            good = False
        ok += good
        rows.append((a["email_id"], exp, lane, r["intent"], "ok" if good else "FAIL", a["note"]))
    return {"set": "adversarial", "n": len(adv), "pass": ok, "pass_rate": round(ok / len(adv), 3),
            "unsafe_failures": bad_unsafe, "forbidden_intent_hits": bad_forbidden, "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=os.path.join(ROOT, "eval", "gold_v2.csv"))
    ap.add_argument("--adv", default=os.path.join(ROOT, "eval", "adversarial.csv"))
    ap.add_argument("--json", default=os.path.join(ROOT, "eval", "report.json"))
    a = ap.parse_args()
    main_out = os.path.join(ROOT, "out")
    run(ROOT, out_dir=main_out, quiet=True)
    gold = load(a.gold)
    g = report_gold(gold, results_by_id(main_out), os.path.basename(a.gold))
    tmp = tempfile.mkdtemp()
    run(ROOT, csv_path=a.adv, out_dir=tmp, quiet=True)
    adv = report_adv(load(a.adv), results_by_id(tmp))
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"GOLD SET ({g['set']}, n={g['n']})")
    print(f"  lane exact match      {g['lane_exact']:.1%}")
    print(f"  intent family match   {g['family_accuracy']:.1%}")
    print(f"  human recall          {g['human_recall']:.1%}  ({g['gold_human'] - len(g['human_missed'])}/{g['gold_human']} "
          f"emails that need a person reached one)   missed: {g['human_missed']}")
    print(f"  review sent to auto   {g['review_sent_auto']}")
    print(f"  missed replies        {g['missed_reply']}")
    print(f"  over-escalated        {len(g['over_escalated'])}  (safe, costs time)")
    print("  disagreements:")
    for d in g["disagreements"]:
        print("   ", d)
    print(f"\nADVERSARIAL SET (n={adv['n']}): {adv['pass']}/{adv['n']} pass")
    for r in adv["rows"]:
        print("   ", r)
    print("  unsafe failures:", adv["unsafe_failures"], " forbidden-intent hits:", adv["forbidden_intent_hits"])
    with open(a.json, "w") as f:
        json.dump({"gold": g, "adversarial": adv}, f, indent=2)


if __name__ == "__main__":
    main()
