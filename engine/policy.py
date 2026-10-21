"""Stage 3: policy engine. Pure function: (email, classification, context, config) -> decision.

Rules live in config/policy.json, not in prompts and not in code. The order of
precedence is fixed here and tested in tests/test_invariants.py:

  duplicate  ->  no reply, merge
  hard risk flag / offer stage / low confidence / watchlist startup / repeat chaser  ->  HUMAN
  otherwise  ->  the lane configured for that intent
"""
import re
from .util import parse_dt, parse_when, fmt_short, add_working_days
from .render import build_reply
from .briefs import make_brief

PRIORITY_LABEL = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}


def intent_cfg(policy, intent, sub):
    node = policy["intents"][intent]
    if "lane" in node:
        return node
    return node.get(sub) or node["_default"]


def summarise(email, c, ctx):
    e = c.entities
    s = e.get("startup") or ""
    w = f", {e['waiting_days']}d since interview" if e.get("waiting_days") and c.intent == "status_chase" else ""
    n = {
        "status_chase": f"Chasing {s}{w}",
        "application_status": "Asking about application status" + (f" ({e['waiting_days']}d waiting)" if e.get("waiting_days") else ""),
        "feedback_request": f"Asking for feedback from {s}",
        "rejection_notice": f"Reports rejection by {s}",
        "interview_prep": f"Interview prep question ({s})",
        "salary_guidance": f"Salary question ({s})",
        "reference_help": f"Reference problem ({s})",
        "faq": "General question",
        "referral": "Wants to refer a friend",
        "product_feedback": f"Product feedback: {c.sub.replace('_', ' ')}",
        "visa_sponsorship": "Visa sponsorship question",
        "negative_experience": "Unhappy with response rate",
        "placement_success": "Reports a placement",
        "thanks": "Thanks / positive feedback",
        "ooo_autoreply": "Out-of-office auto-reply",
        "video_resolved": "Says video issue is resolved",
        "vendor_inbound": "Vendor or partnership approach" if c.sub != "spam" else "Spam",
        "unsubscribe": "Unsubscribe request",
        "data_deletion": "Account and data deletion request",
        "account_admin": "Account help: " + c.sub.replace("_", " "),
        "platform_bug": "Platform problem: " + c.sub.replace("_", " "),
        "sar": "Subject access request",
        "complaint_regulatory": "Complaint with regulator threat",
        "data_incident": "Sees another person's data",
        "discrimination_report": f"Discriminatory interview questions ({s})",
        "startup_conduct": f"Unpaid trial request ({s})",
        "reputational_threat": f"Threatens public post ({s})",
        "offer_support": f"Live offer ({s})",
        "offer_withdrawn": f"Offer withdrawn ({s})",
        "reschedule_request": f"Interview reschedule ({s})",
        "startup_no_show": f"Startup no-show ({s})",
        "rtw_documents": f"Right-to-work documents request ({s})",
        "accessibility_request": "Asks for adjustment to application",
        "wellbeing_concern": "Message suggests the person may be in distress",
        "unknown": "Unclassified",
    }[c.intent]
    return n


def decide(email, c, ctx, cfg, now):
    """Returns a decision dict. No side effects."""
    pol, params, tpl = cfg["policy"], cfg["policy"]["params"], cfg["templates"]
    ov = pol["overrides"]
    eid = email["email_id"]
    rec = parse_dt(email["received_at"])
    base = intent_cfg(pol, c.intent, c.sub)
    lane, reasons = base["lane"], []
    priority = base["priority"]
    actions = list(base.get("actions", []))
    proposed = list(base.get("proposed", []))
    template = base.get("template")
    thread_n = ctx["thread_n"][eid]
    startup = c.entities.get("startup", "")

    if eid in ctx["dup_of"]:
        return {"email_id": eid, "lane": "AUTO_ACTION", "priority": 3, "owner": "talent-ops",
                "reasons": [f"Exact duplicate of {ctx['dup_of'][eid]}: merged, no second reply"],
                "actions": ["merge_duplicate"], "proposed": [], "template": None, "reply": None,
                "brief": None, "summary": "Duplicate of " + ctx["dup_of"][eid], "sla_due": None, "overdue_h": 0,
                "deadline": None}

    if eid in ctx["superseded"]:
        return {"email_id": eid, "lane": "AUTO_ACTION", "priority": 3, "owner": base["owner"],
                "reasons": [f"Superseded: the same person confirmed it is resolved in {ctx['superseded'][eid]}"],
                "actions": ["mark_incident_link_resolved"], "proposed": [], "template": None, "reply": None,
                "brief": None, "kb_assumed": False, "summary": summarise(email, c, ctx) + " (resolved later)",
                "sla_due": None, "overdue_h": 0, "deadline": None}

    hard = [f for f in c.flags if f in ov["hard_flags_force_human"]]
    if hard and lane != "HUMAN":
        lane = "HUMAN"
        reasons.append("Risk flag: " + ", ".join(hard))
    if c.intent in ("ooo_autoreply",):
        lane = "AUTO_ACTION"
        reasons = []
    if ov["stage_offer_forces_human"] and email["candidate_stage"] == "Offer" and c.intent != "placement_success" \
            and lane != "HUMAN":
        lane = "HUMAN"
        reasons.append("Live offer: person-to-person")
    if ov["low_confidence_forces_human"] and c.confidence < params["min_confidence"] and lane != "HUMAN":
        lane = "HUMAN"
        reasons.append(f"Low confidence ({c.confidence:.2f})")
    wl = ctx["watchlist"].get(startup)
    if wl and wl["kind"] != "review" and c.intent in ov["watchlist_startup_forces_human_for"] and lane != "HUMAN":
        lane = "HUMAN"
        reasons.append(f"{startup} is on the {wl['kind'].replace('_', ' ')} list: " + "; ".join(wl["reasons"]))
    if ov["repeat_chaser_forces_human"] and c.intent in ("status_chase", "application_status") \
            and thread_n >= params["repeat_escalate_at"] and lane != "HUMAN":
        lane = "HUMAN"
        reasons.append(f"Chased {thread_n} times: our process has failed this person")
    if lane == "HUMAN" and not reasons:
        reasons.append({"sar": "Statutory deadline", "complaint_regulatory": "Regulator threat",
                        "data_incident": "Possible personal data breach",
                        "discrimination_report": "Equality and safeguarding",
                        "startup_conduct": "Possible unlawful or unfair practice",
                        "reputational_threat": "Reputational risk", "offer_support": "Live offer: person-to-person",
                        "offer_withdrawn": "Candidate harm and legal exposure",
                        "reschedule_request": "Time-critical", "startup_no_show": "Startup failure",
                        "rtw_documents": "Sensitive documents", "accessibility_request": "Equality duty",
                        "wellbeing_concern": "Possible risk to the person: human only",
                        "unknown": "Unclassified: fail-safe to human"}.get(c.intent, "Policy: human lane"))

    if ov.get("multi_part_downgrades_auto_to_draft") and "multi_part" in c.flags and len(email["body"]) > 90 \
            and lane == "AUTO_REPLY":
        lane = "DRAFT"
        reasons.append("Multi-part email: a template would answer only part of it")
    if ov.get("frustration_strong_downgrades_auto_to_draft") and "frustration_strong" in c.flags \
            and lane == "AUTO_REPLY":
        lane = "DRAFT"
        reasons.append("Frustrated sender: a template alone would land badly, so a person reviews the draft")

    # chasers in a human lane still get the startup digest entry as an automatic action
    if lane == "HUMAN" and c.intent == "status_chase" and "add_to_startup_digest" not in actions:
        actions.append("add_to_startup_digest")

    # conditional extras
    if c.intent == "application_status" and c.entities.get("waiting_days", 0) >= params["aged_application_days"]:
        actions.append("escalate_aged_application")
    if c.intent == "platform_bug" and c.sub in ("video_upload", "apply_button", "listing_missing"):
        pass
    if c.intent == "product_feedback" and c.sub == "zero_matches":
        actions.append("check_profile_visibility")
    if c.intent == "referral" and email["candidate_stage"] != "Hired":
        actions = [a for a in actions if a != "tag_referrer"]

    # priority: deadlines and time-critical items move up; frustration moves up
    dl_text, dl_dt, dl_hours = None, None, None
    if c.entities.get("deadline_text"):
        dl_dt = parse_when(c.entities["deadline_text"], rec)
        if dl_dt:
            dl_hours = (dl_dt - now).total_seconds() / 3600
            dl_text = fmt_short(dl_dt)
            if dl_hours <= 36:
                priority = 0
            elif dl_hours <= 96:
                priority = min(priority, 1)
    if "time_critical" in c.flags and c.intent in ("startup_conduct", "reschedule_request", "offer_support",
                                                    "discrimination_report", "startup_no_show"):
        priority = 0
    if c.intent == "reschedule_request" and "never heard back" in email["body"].lower():
        priority = 0
    if "frustration" in c.flags or thread_n >= 2:
        priority = max(0, priority - 1) if lane in ("HUMAN", "DRAFT") else priority

    sla_due = rec + __import__("datetime").timedelta(hours=base["sla_hours"])
    overdue_h = max(0, int((now - sla_due).total_seconds() // 3600))

    reply, brief = None, None
    kb_assumed = False
    if lane in ("AUTO_REPLY", "DRAFT") and template:
        out = build_reply(template, lane, email, c, ctx, None, tpl, params, now, pol["product_feature_labels"])
        if out:
            reply = {"subject": out[0], "body": out[1]}
            kb_assumed = out[2]
    elif lane == "AUTO_REPLY" and not template:
        lane = "AUTO_ACTION"
    if lane == "HUMAN":
        brief = make_brief(email, c, ctx, now, cfg["emails_by_id"], cfg["cls_by_id"], reasons)
        proposed = proposed or []
        brief["proposed"] = list(dict.fromkeys(brief.get("proposed", []) + [p.replace("_", " ") for p in proposed]))
    return {"email_id": eid, "lane": lane, "priority": priority, "owner": base["owner"], "reasons": reasons,
            "actions": actions, "proposed": proposed, "template": template, "reply": reply, "brief": brief,
            "kb_assumed": kb_assumed, "summary": summarise(email, c, ctx),
            "sla_due": sla_due.isoformat(), "overdue_h": overdue_h,
            "deadline": {"text": dl_text, "hours_from_now": round(dl_hours, 1) if dl_hours is not None else None}}
