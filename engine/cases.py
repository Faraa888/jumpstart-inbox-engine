"""Stage 2: cross-email intelligence. One email never stands alone.

Builds, from all emails seen so far:
- identity resolution (same sender, or same name + same startup)
- exact-duplicate collapse
- thread position (is this the 2nd or 3rd time they have asked?)
- incident clusters (many people reporting the same bug become ONE case)
- startup rollups and the watchlist (derived from evidence, never hard-coded)

In production this runs incrementally per email against the database; here it
runs over the full batch because we have the full batch.
"""
import re
from collections import defaultdict, Counter

STRONG_FRUSTRATION = re.compile(
    r"ghosted|gone silent|or from you|third time|fourth time|no feedback at all|pretty poor|is anyone reading", re.I)

CHASE_FAMILY = {"status_chase": "chase", "application_status": "app", "feedback_request": "feedback",
                "platform_bug": "bug", "reschedule_request": "reschedule", "offer_support": "offer"}


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", str(s).lower()).strip()


def build_context(emails, cls, params):
    """emails: list of dicts sorted by time. cls: {email_id: Result}. Returns ctx dict."""
    # identity resolution: from_email, then merge same name + same startup
    ident = {}
    by_email = {}
    for e in emails:
        ident[e["email_id"]] = e["from_email"]
    name_startup = {}
    for e in emails:
        st = cls[e["email_id"]].entities.get("startup", "")
        key = (e["from_name"].lower(), st)
        if st and key in name_startup and name_startup[key] != e["from_email"]:
            ident[e["email_id"]] = name_startup[key]  # same person, second address
        else:
            name_startup.setdefault(key, e["from_email"])

    # duplicate collapse + thread position
    seen_body = {}
    dup_of, thread_n, thread_total = {}, {}, {}
    fam_count = defaultdict(int)
    thread_ids = defaultdict(list)
    for e in emails:
        eid = e["email_id"]
        c = cls[eid]
        person = ident[eid]
        thread_ids[person].append(eid)
        k = (person, norm(e["body"]))
        if k in seen_body:
            dup_of[eid] = seen_body[k]
        else:
            seen_body[k] = eid
        fam = CHASE_FAMILY.get(c.intent, c.intent)
        if eid not in dup_of:
            fam_count[(person, fam)] += 1
        thread_n[eid] = fam_count[(person, fam)]
    for e in emails:
        eid = e["email_id"]
        thread_total[eid] = len([x for x in thread_ids[ident[eid]] if x not in dup_of])

    # incident clusters
    clusters = defaultdict(list)
    for e in emails:
        c = cls[e["email_id"]]
        if c.intent == "platform_bug":
            if c.sub in ("video_upload", "video_check"):
                clusters["INC-VIDEO"].append(e["email_id"])
            elif c.sub == "apply_button":
                clusters["BUG-APPLY-MOBILE"].append(e["email_id"])
            elif c.sub in ("listing_missing", "resolved"):
                clusters["INC-LISTING-" + (c.entities.get("startup") or "UNKNOWN").upper().replace(" ", "-")].append(
                    e["email_id"])
    by_id = {e["email_id"]: e for e in emails}
    resolved_by_person = {}
    for e in emails:
        c = cls[e["email_id"]]
        if c.intent == "video_resolved":
            resolved_by_person[ident[e["email_id"]]] = e["email_id"]
    # thread-aware closure: an earlier bug report is moot once the same person says it's fixed
    superseded = {}
    for e in emails:
        c = cls[e["email_id"]]
        if c.intent == "video_resolved" or (c.intent == "platform_bug" and c.sub == "resolved"):
            for e2 in emails:
                if e2["email_id"] == e["email_id"] or ident[e2["email_id"]] != ident[e["email_id"]]:
                    continue
                c2 = cls[e2["email_id"]]
                if c2.intent == "platform_bug" and c2.sub != "resolved" and e2["received_at"] < e["received_at"]:
                    superseded[e2["email_id"]] = e["email_id"]
    incidents = {}
    for cid, ids in clusters.items():
        threshold = params["incident_threshold"]
        real = [i for i in ids if cls[i].sub != "resolved"]
        times = sorted(by_id[i]["received_at"] for i in real)
        detected = None
        thr = params["incident_threshold"]
        from datetime import datetime, timedelta
        for k in range(thr - 1, len(times)):
            if datetime.fromisoformat(times[k].replace(" ", "T")) - datetime.fromisoformat(
                    times[k - thr + 1].replace(" ", "T")) <= timedelta(hours=24):
                detected = times[k]
                break
        incidents[cid] = {
            "case_id": cid,
            "detected_at": detected,
            "reports_after_detection": (len([t for t in times if t > detected]) if detected else None),
            "is_incident": len(real) >= threshold,
            "email_ids": ids,
            "reports": len(real),
            "people": len({ident[i] for i in real}),
            "first_report": by_id[ids[0]]["received_at"],
            "last_report": by_id[ids[-1]]["received_at"],
            "per_day": dict(Counter(by_id[i]["received_at"][:10] for i in real)),
            "resolved_signals": [i for i in ids if cls[i].sub == "resolved"]
            + [v for p, v in resolved_by_person.items() if cid == "INC-VIDEO"],
        }

    # startup rollups + watchlist
    st = defaultdict(lambda: Counter())
    st_emails = defaultdict(lambda: defaultdict(list))
    for e in emails:
        eid = e["email_id"]
        if eid in dup_of:
            continue
        c = cls[eid]
        for s in c.entities.get("startups", []):
            st[s]["emails"] += 1
            st[s][c.intent] += 1
            st_emails[s][c.intent].append(eid)
            if STRONG_FRUSTRATION.search(e["body"]):
                st[s]["strong_frustration"] += 1
                st_emails[s]["strong_frustration"].append(eid)
            for f in c.flags:
                if f in ("unpaid_work", "discrimination", "public_threat", "offer_withdrawn"):
                    st[s][f] += 1
                    st_emails[s][f].append(eid)
    watch = {}
    for s, cnt in st.items():
        reasons = []
        if cnt["discrimination"]:
            reasons.append(f"{cnt['discrimination']} report(s) of discriminatory interview questions")
        if cnt["unpaid_work"]:
            reasons.append(f"{cnt['unpaid_work']} report(s) of unpaid trial work")
        if cnt["offer_withdrawn"]:
            reasons.append("offer withdrawn after candidate resigned")
        if cnt["strong_frustration"] >= params["watchlist_frustration_reports"]:
            reasons.append(f"{cnt['strong_frustration']} candidates reporting ghosting or no response")
        if reasons:
            if cnt["discrimination"]:
                kind = "safeguarding_hold"
            elif cnt["unpaid_work"] or cnt["strong_frustration"] >= params["watchlist_frustration_reports"]:
                kind = "conduct_watch"
            else:
                kind = "review"  # informational: does not hold replies to other candidates
            watch[s] = {"startup": s, "kind": kind, "reasons": reasons,
                        "emails": sorted({i for k in ("discrimination", "unpaid_work", "offer_withdrawn",
                                                      "strong_frustration", "public_threat")
                                          for i in st_emails[s][k]})}
    return {
        "ident": ident, "dup_of": dup_of, "superseded": superseded, "thread_n": thread_n, "thread_total": thread_total,
        "incidents": incidents, "startup_stats": {k: dict(v) for k, v in st.items()},
        "startup_emails": {k: {a: b for a, b in v.items()} for k, v in st_emails.items()},
        "watchlist": watch,
    }
