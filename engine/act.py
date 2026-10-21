"""Stage 5: act. Who holds the blocker, how serious it is, which of four moves, and what everyone needs to do.

  Triage   blocker:  jumpstart | startup | candidate | none
           severity: routine | sensitive | critical
  Act      move:     reply | reply_chase (reply and chase the startup) | reply_inhouse (reply and act in-house)
                     | escalate (a person) | no_reply

Startup-blocked emails get a status block: where the candidate is, how long the startup usually takes (from
the startup bank), and what we've done. If we already hold an update from the startup, the candidate gets it
and nobody is chased. Otherwise the chase goes into that startup's daily email, which a person approves,
and the follow-up agent checks back on the date we promised.
"""
import csv
import os
import re

from .util import add_working_days, fmt_day, parse_dt

STARTUP_BLOCKED = {"status_chase", "feedback_request", "reschedule_request", "startup_no_show", "offer_withdrawn",
                   "startup_conduct", "discrimination_report"}
CANDIDATE_BLOCKED = {"offer_support"}
NO_ONE = {"ooo_autoreply", "thanks", "vendor_inbound", "placement_success", "video_resolved", "rejection_notice"}
SENSITIVE = {"offer_support", "offer_withdrawn", "data_deletion", "sar", "accessibility_request", "rtw_documents",
             "visa_sponsorship", "salary_guidance", "reference_help", "negative_experience", "feedback_request"}
IN_HOUSE = {"suppress_marketing", "link_to_incident", "open_erasure_ticket", "compile_data_export", "open_sar_ticket",
            "check_profile_visibility", "check_video_saved", "delete_received_documents", "set_profile_paused",
            "send_fresh_magic_link", "send_verification_link", "forward_to_partnerships", "tag_product_feedback",
            "escalate_aged_application", "update_stage_hired"}
MOVE_LABEL = {"reply": "Reply", "reply_chase": "Reply and chase the startup", "reply_inhouse": "Reply and act in-house",
              "escalate": "Escalate to a person", "no_reply": "No reply needed"}
BLOCKER_LABEL = {"jumpstart": "Jumpstart", "startup": "Startup", "candidate": "Candidate", "none": "No one"}


def load_candidates(root):
    p = os.path.join(root, "data", "candidates_mock.csv")
    if not os.path.exists(p):
        return {}
    return {r["email"].lower(): r for r in csv.DictReader(open(p, newline="", encoding="utf-8"))}


def stages_for(startup_facts):
    m = re.search(r"(\d)\s*rounds?", str(startup_facts.get("interview_process") or ""))
    n = int(m.group(1)) if m else 3
    mids = {2: ["First interview", "Final interview"], 3: ["First interview", "Second interview", "Final interview"],
            4: ["First interview", "Second interview", "Third interview", "Final interview"]}.get(n, ["First interview",
                                                                                                    "Second interview",
                                                                                                    "Final interview"])
    return ["Applied"] + mids + ["Offer"]


def stage_line(rec, startup_facts):
    stages = stages_for(startup_facts)
    stage = rec.get("stage", "")
    rnd = rec.get("round", "")
    if stage == "Applied":
        i = 0
    elif stage == "Offer":
        i = len(stages) - 1
    elif stage in ("Interviewing", "Rejected"):
        i = {"first": 1, "second": 2, "third": 3, "final": len(stages) - 2}.get(rnd, 1)
        i = min(i, len(stages) - 2)
    else:
        return ""
    parts = [f"{s} ✓" if j < i else (f"{s} (you're here)" if j == i else s) for j, s in enumerate(stages)]
    return "   >   ".join(parts)


def status_reply(email, cls, startup, rec, facts, now, kind, params, first, late, tpl_sig):
    """Personal status reply for a startup-blocked email. Returns (body, known_update, timeline_known)."""
    sf = facts.startups.get(startup, {})
    line = stage_line(rec, sf) if rec else ""
    days = sf.get("typical_feedback_days")
    follow = fmt_day(add_working_days(now, params["chase_followup_working_days"]))
    round_word = {"first": "first interview", "second": "second interview", "final": "final interview"}.get(
        (rec or {}).get("round", ""), "interview")
    first_line = {"repeat": f"Sorry you've had to keep asking on this. We've been pushing {startup} for an answer.",
                  "frustrated": f"I'm really sorry you've had to keep asking. That shouldn't happen, and we've been pushing {startup} for an answer.",
                  "watch": "Thanks for checking in, and sorry you're still waiting.",
                  "watch_frustrated": f"I'm really sorry you've had to keep asking. That shouldn't happen, and we've been pushing {startup} for an answer."
                  }.get(kind, "Thanks for checking in.")
    if kind not in ("first", "watch"):
        late = ""  # an upset or repeat chaser gets straight to the apology, no pleasantries
    body = [f"Hi {first},", "", late + first_line]
    if line and kind == "first":
        body += ["", f"Just as a reminder, here's where you are with {startup}:", line]
    known = rec.get("startup_update") if rec and not kind.startswith("watch") else ""
    if known:
        on = parse_dt(rec["startup_update_on"] + " 09:00")
        body += ["", f"Good news: {startup} told us on {on.strftime('%A %d %B').replace(' 0', ' ')} that {known}. "
                     f"We'll keep an eye on it and let you know as soon as we hear more."]
    else:
        if days and kind in ("first", "repeat"):
            body += ["", f"{startup} usually gets back to candidates within about {days} working days of an interview."]
        if kind == "first" or kind == "watch":
            body += ["", f"We've asked {startup} for an update on your {round_word} and we'll be in touch by {follow}."]
        else:
            body += ["", f"We've flagged it to them as a priority today, and we'll get back to you by {follow}, whatever the answer."]
    body += ["", tpl_sig]
    return "\n".join(body), bool(known), bool(days)


def labels(email, c, d):
    # Every email has an owner. Auto-replies, spam, duplicates and thank-yous are Jumpstart's to close.
    if d["lane"] == "AUTO_ACTION" and not d.get("reply"):
        blocker = "jumpstart"
    elif c.intent in STARTUP_BLOCKED:
        blocker = "startup"
    elif c.intent in CANDIDATE_BLOCKED:
        blocker = "candidate"
    else:
        blocker = "jumpstart"
    if d["lane"] == "HUMAN" and d.get("person_reason") == "critical":
        severity = "critical"
    elif c.intent in SENSITIVE or "frustration" in c.flags or "frustration_strong" in c.flags or \
            any("list:" in r for r in d.get("reasons", [])):
        severity = "sensitive"
    else:
        severity = "routine"
    if d["lane"] == "HUMAN":
        move = "escalate"
    elif d["lane"] == "AUTO_ACTION":
        move = "no_reply"
    elif blocker == "startup" and not d.get("known_update"):
        move = "reply_chase"
    elif set(d.get("actions", [])) & IN_HOUSE or d.get("proposed"):
        move = "reply_inhouse"
    else:
        move = "reply"
    who = {"candidate": "", "jumpstart": "", "startup": ""}
    st = c.entities.get("startup") or "the startup"
    if move == "reply_chase":
        who["startup"] = f"Give {st} an update on this candidate (asked in today's daily email)"
        who["jumpstart"] = f"Chase {st}; follow up with the candidate by the date promised"
    elif move == "reply_inhouse":
        who["jumpstart"] = ", ".join(a.replace("_", " ") for a in d["actions"] if a in IN_HOUSE) or "act in-house"
    elif move == "escalate":
        who["jumpstart"] = "A person decides: " + (d.get("reasons") or ["review"])[0]
    if c.intent in ("offer_support",):
        who["candidate"] = "Decide on the offer before the deadline"
    elif c.intent in ("reschedule_request", "startup_no_show"):
        who["candidate"] = "Pick a new interview time with the rebooking link"
    elif c.intent == "platform_bug" and c.sub == "video_upload":
        who["candidate"] = "Try the workaround, or wait for the fix email"
    elif c.intent == "account_admin" and c.sub == "change_email":
        who["candidate"] = "Click the verification link"
    return {"blocker": blocker, "severity": severity, "move": move, "who": who}
