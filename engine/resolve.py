"""Stage 4: resolve. Turns the policy decision into one of three outcomes and finds the answer.

  AUTO_REPLY   answered automatically (after the reviewer agrees), sent after a 5 to 30 minute delay
  AUTO_ACTION  silent: auto-responders, spam, duplicates, superseded reports. Every human gets a reply.
  HUMAN        a person, for one of five reasons: critical, gap (fact missing), reviewer (disagreed),
               unknown (could not classify), partner (live offer, goes to the talent partner)

Answers come from approved templates plus the facts database (config/facts.json). A missing fact sends
the email to a person; their answer is saved, so later emails needing it are answered automatically.
"""
import hashlib
import re
from datetime import timedelta

from .util import first_name, add_working_days, fmt_day, parse_dt, add_month, opener
from .render import build_reply
from .briefs import make_brief
from .reviewer import review
from .act import status_reply, labels, STARTUP_BLOCKED

CRIT_INTENTS = {"data_incident", "discrimination_report", "complaint_regulatory", "reputational_threat",
                "offer_withdrawn", "wellbeing_concern", "startup_conduct"}
CRIT_FLAGS = {"wellbeing", "injection", "privacy_legal", "data_exposure", "discrimination", "unpaid_work",
              "public_threat", "offer_withdrawn"}
CHASE = {"status_chase", "feedback_request", "rejection_notice", "application_status"}
# Assumed minutes of person time. Sign-offs are one batch click per day per action type.
MINUTES = {"critical": 5, "critical_repeat": 2, "gap": 2, "reviewer": 2, "unknown": 3, "signoff": 1, "alert": 5}


class FactsState:
    """Mutable view of the facts database for one run. Gaps are recorded with when they were first hit."""

    def __init__(self, facts, simulate_fill=True):
        self.platform = dict(facts["platform"])
        self.startups = {k: dict(v) for k, v in facts["startups"].items()}
        self.sim = facts.get("_simulated_answers", {})
        self.fill_after = timedelta(hours=facts.get("params", {}).get("gap_answer_hours", 4))
        self.simulate = simulate_fill
        self.pending = {}   # key -> time a person will have answered it
        self.log = []       # gap events

    def get(self, key, at):
        scope, field = key.split(".", 1)
        store = self.platform if scope == "platform" else self.startups.setdefault(scope, {})
        val = store.get(field)
        if val is not None:
            return val
        if key in self.pending and at >= self.pending[key]:
            store[field] = self.sim.get(key, self.sim.get("*"))
            self.log.append({"key": key, "event": "filled", "at": self.pending[key].isoformat(sep=" ")})
            return store[field]
        if key not in self.pending:
            self.log.append({"key": key, "event": "gap", "at": at.isoformat(sep=" ")})
            if self.simulate:
                self.pending[key] = at + self.fill_after
        return None

    def sponsors(self):
        return ", ".join(sorted(s for s, f in self.startups.items() if f.get("visa_sponsorship") == "yes"))


def _render(tid, email, cls, ctx, tpl, params, now, extra=None):
    first = first_name(email["from_name"])
    received = parse_dt(email["received_at"])
    late = opener(now, received, params["late_after_hours"])
    v = {"first": first, "late": late, "sorry": "Sorry ",
         "startup": cls.entities.get("startup") or "the startup",
         "followup": fmt_day(add_working_days(now, params["chase_followup_working_days"]))}
    v.update(extra or {})
    body = tpl["templates"][tid].format(**v)
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n\n" + tpl["signature"]
    subj = email["subject"] if email["subject"].lower().startswith("re:") else "Re: " + email["subject"]
    return {"subject": subj, "body": body}


def _delay(eid, received, now):
    """5 to 30 minutes, deterministic per email, only sent 08:00 to 19:00."""
    mins = 5 + int(hashlib.md5(eid.encode()).hexdigest(), 16) % 26
    t = max(now, received) + timedelta(minutes=mins)
    if t.hour >= 19:
        t = (t + timedelta(days=1)).replace(hour=8, minute=mins)
    elif t.hour < 8:
        t = t.replace(hour=8, minute=mins)
    return t


def _to_person(d, why, reason_text, email, c, ctx, now, cfg, suggested=None, brief_over=None):
    d["lane"], d["person_reason"] = "HUMAN", why
    d["reasons"] = [reason_text] + [r for r in d["reasons"] if r != reason_text]
    b = make_brief(email, c, ctx, now, cfg["emails_by_id"], cfg["cls_by_id"], d["reasons"])
    if suggested:
        b["reply"] = suggested["body"]
    if brief_over:
        b.update(brief_over)
    d["brief"] = b
    d["reply"] = None
    return d


def resolve(email, c, ctx, d, cfg, now, facts, state):
    """Mutates and returns d. `state` carries per-run memory (thanked people, alerted startups)."""
    tpl, params = cfg["templates"], cfg["policy"]["params"]
    eid = email["email_id"]
    rec = parse_dt(email["received_at"])
    startup = c.entities.get("startup", "")
    who = ctx["ident"][eid]
    d.setdefault("person_reason", "")
    d["signoff"] = bool(d.get("proposed"))
    d["alert"] = ""
    d["ack"] = None
    d["review"] = None
    lane0 = d["lane"]
    R = lambda tid, extra=None: _render(tid, email, c, ctx, tpl, params, now, extra)  # noqa: E731

    def auto(tid, extra=None, template=None, reply=None):
        d["lane"] = "AUTO_REPLY"
        d["reply"] = reply or R(tid, extra)
        d["template"] = template or tid
        d["brief"] = None

    def gap(key, label):
        _to_person(d, "gap", f"Missing fact: {label}", email, c, ctx, now, cfg,
                   brief_over={"headline": f"Missing fact: {label}",
                               "steps": [f"Answer once: fill '{key}' in the facts database",
                                         "Your answer is saved and every later email that needs it is answered automatically",
                                         "Then send the reply below with the fact added"]})
        d["gap_key"] = key

    # ---------- silent lane: reply to every human, never to machines ----------
    if lane0 == "AUTO_ACTION":
        superseded = any("Superseded" in r for r in d["reasons"])
        if eid in ctx["dup_of"] or superseded or c.intent == "ooo_autoreply" or \
                (c.intent == "vendor_inbound" and c.sub == "spam"):
            d["person_reason"] = ""
        elif c.intent == "thanks":
            if who in state["thanked"]:
                d["reasons"] = ["Already thanked once: no reply, so it doesn't turn into ping-pong"]
            else:
                state["thanked"].add(who)
                auto("thanks_close")
        elif c.intent == "video_resolved" or (c.intent == "platform_bug" and c.sub == "resolved"):
            auto("resolved_close")
        elif c.intent == "vendor_inbound":
            auto("vendor_close")
            d["actions"].append("forward_to_partnerships")

    # ---------- escalations: keep only what is genuinely a person's job ----------
    elif lane0 == "HUMAN":
        is_offer = email["candidate_stage"] == "Offer" or c.intent == "offer_support"
        if c.intent == "sar":
            due = fmt_day(add_month(rec))
            auto("sar_ack", {"sar_due": due})
            d["proposed"] = list(dict.fromkeys(d.get("proposed", []) + ["release_data_export"]))
            d["actions"].append("compile_data_export")
            d["signoff"] = True
        elif c.intent in CRIT_INTENTS or set(c.flags) & CRIT_FLAGS:
            d["person_reason"] = "critical"
            ack = "wellbeing_ack" if (c.intent == "wellbeing_concern" or "wellbeing" in c.flags) else "critical_ack"
            if "injection" not in c.flags:
                d["ack"] = R(ack)
                d["actions"].append("send_acknowledgement_now")
        elif is_offer:
            d["person_reason"] = "partner"
            d["owner"] = "talent-partner"
            d["reasons"] = ["Live offer: goes to the candidate's talent partner"] + d["reasons"]
        elif c.intent == "unknown" or any(r.startswith("Low confidence") for r in d["reasons"]):
            d["person_reason"] = "unknown"
        elif c.intent in CHASE and any("list:" in r for r in d["reasons"]):
            tid = "rejection_ack" if c.intent == "rejection_notice" else "watch_hold"
            reply = build_reply(tid, "AUTO_REPLY", email, c, ctx, None, tpl, params, now,
                                cfg["policy"]["product_feature_labels"]) if tid == "rejection_ack" else None
            auto(tid, reply={"subject": reply[0], "body": reply[1]} if reply else None)
            if startup and startup not in state["alerted"]:
                state["alerted"].add(startup)
                d["alert"] = startup
                d["actions"].append("alert_account_owner")
        elif c.intent in CHASE and any(r.startswith("Chased") for r in d["reasons"]):
            out = build_reply("chase_first", "AUTO_REPLY", email, c, ctx, None, tpl, params, now,
                              cfg["policy"]["product_feature_labels"])
            auto("chase_repeat", reply={"subject": out[0], "body": out[1]})
            d["actions"].append("priority_flag_in_startup_digest")
        elif c.intent in ("reschedule_request", "startup_no_show"):
            auto("rebook", {"rebooking_link": facts.get("platform.rebooking_link", rec)})
            d["actions"].append("record_startup_no_show" if c.intent == "startup_no_show" else "notify_startup_reschedule")
        elif c.intent == "rtw_documents":
            auto("rtw_ack", {"secure_upload_link": facts.get("platform.secure_upload_link", rec)})
            d["actions"].append("delete_received_documents")
        elif c.intent == "accessibility_request":
            auto("adjustment", {"application_alternative": facts.get("platform.application_alternative", rec)})
        else:
            d["person_reason"] = d["person_reason"] or "critical"
        if d["lane"] == "HUMAN":
            d["reasons"] = d["reasons"] or ["Needs a person"]

    # ---------- drafts: find the answer in the facts database ----------
    elif lane0 == "DRAFT":
        b = email["body"].lower()
        if c.intent == "account_admin" and c.sub == "stream_change":
            v = facts.get("platform.stream_policy", rec)
            auto("stream_answer", {"stream_policy": v}) if v else gap("platform.stream_policy", "stream rules")
        elif c.intent == "visa_sponsorship":
            v = facts.get("platform.visa_filter", rec)
            if v is None:
                gap("platform.visa_filter", "whether candidates can filter roles by visa sponsorship")
            else:
                auto("visa_answer", {"visa_filter": v, "sponsors": facts.sponsors()})
        elif c.intent == "salary_guidance":
            if startup and re.search(r"expectation|what should i say|range", b):
                v = facts.get(f"{startup}.salary_range", rec)
                auto("salary_answer", {"salary_range": v}) if v else gap(f"{startup}.salary_range", f"{startup} salary range")
            else:
                auto("salary_general")
        elif c.intent == "reference_help":
            auto("reference_answer")
        elif c.intent == "negative_experience":
            auto("responses_answer")
            d["actions"].append("check_profile_visibility")
        elif c.intent == "platform_bug" and c.sub == "listing_missing":
            auto("listing_answer")
        elif c.intent == "platform_bug" and c.sub == "video_check":
            auto("video_check_answer")
            d["actions"].append("check_video_saved")
        else:
            d["lane"] = "AUTO_REPLY"  # existing approved reply; the reviewer decides

    # ---------- upset senders get a reply written for upset senders ----------
    if d["lane"] == "AUTO_REPLY" and "frustration_strong" in c.flags:
        var = {"watch_hold": "watch_hold_frustrated", "rejection_ack": "watch_hold_frustrated",
               "chase_repeat": "chase_frustrated", "chase_first": "chase_frustrated",
               "video_incident": "video_frustrated"}.get(d.get("template"))
        if var:
            auto(var)

    # ---------- startup-blocked: personal status update (where you are, usual timeline, what we've done) ----------
    if d["lane"] == "AUTO_REPLY" and c.intent == "status_chase" and startup and d.get("template") in (
            "chase_first", "chase_repeat", "watch_hold", "watch_hold_frustrated", "chase_frustrated"):
        t0 = d["template"]
        kind = ("watch_frustrated" if "frustrated" in t0 else "watch") if t0.startswith("watch") else \
            "frustrated" if "frustrated" in t0 else \
            "repeat" if (t0 == "chase_repeat" or ctx["thread_n"][eid] >= 2) else "first"
        rec_c = dict(cfg.get("candidates", {}).get(email["from_email"].lower()) or {})
        # the stage line describes THIS email: its stage and round, not the candidate's latest record
        rec_c["stage"] = email["candidate_stage"]
        rec_c["round"] = c.entities.get("round") or (rec_c.get("round") if rec_c.get("startup") == startup else "")
        if rec_c.get("startup") != startup:
            rec_c["startup_update"] = ""
        late = opener(now, rec, params["late_after_hours"])
        body, known, has_days = status_reply(email, c, startup, rec_c, facts, now, kind, params,
                                             first_name(email["from_name"]), late, tpl["signature"])
        d["reply"] = {"subject": d["reply"]["subject"], "body": body}
        d["template"] = "status_update_known" if known else \
            ("status_update" if kind == "first" else f"status_update_{kind}")
        d["known_update"] = known
        if kind in ("repeat", "frustrated", "watch_frustrated"):
            d["priority"] = min(d.get("priority", 2), 1)
            if "priority_flag_in_startup_digest" not in d["actions"]:
                d["actions"].append("priority_flag_in_startup_digest")
        if not has_days and not kind.startswith("watch") and (startup, "typical_feedback_days") not in state["asked"]:
            state["asked"].add((startup, "typical_feedback_days"))
            state["log"].append({"type": "ask_startup", "startup": startup, "email_id": eid,
                                 "question": "How long do you usually take to get back to candidates after each interview round?",
                                 "fact": "typical_feedback_days", "status": "open"})

    # ---------- reviewer: a second, independent check on every automatic reply ----------
    if d["lane"] == "AUTO_REPLY" and d.get("reply"):
        ok, why, mode = review(email, c, d["reply"], d.get("template"))
        d["review"] = {"ok": ok, "reason": why, "mode": mode}
        if not ok:
            _to_person(d, "reviewer", f"Reviewer disagreed: {why}", email, c, ctx, now, cfg, suggested=d["reply"])
    if d["lane"] == "AUTO_REPLY" and not d.get("reply"):
        d["lane"] = "AUTO_ACTION"

    d["send_at"] = _delay(eid, rec, now).isoformat(sep=" ", timespec="minutes") if d["lane"] == "AUTO_REPLY" else None
    if d["ack"]:
        d["ack_at"] = max(now, rec).isoformat(sep=" ", timespec="minutes")
    d.update(labels(email, c, d))
    follow = fmt_day(add_working_days(now, params["chase_followup_working_days"]))
    if d["move"] == "reply_chase":
        cand = cfg.get("candidates", {}).get(email["from_email"].lower(), {})
        state["log"].append({"type": "chase_startup", "startup": startup, "email_id": eid, "candidate": email["from_name"],
                             "candidate_email": email["from_email"], "stage": cand.get("stage", email["candidate_stage"]),
                             "round": cand.get("round", ""), "waiting_days": c.entities.get("waiting_days"),
                             "ask": "feedback for the candidate" if c.intent == "feedback_request" else
                             "a rebooked interview time" if c.intent in ("reschedule_request", "startup_no_show") else
                             "an update and expected decision date",
                             "promised_by": follow, "status": "open"})
    if d["lane"] == "AUTO_REPLY" and d.get("reply"):
        m = re.search(r"we'll (email you|let you know|keep you updated|be in touch|update you|confirm)[^.]*\.",
                      d["reply"]["body"], re.I)
        if m:
            state["log"].append({"type": "promise", "email_id": eid, "candidate": email["from_name"],
                                 "candidate_email": email["from_email"], "promise": m.group(0),
                                 "due": follow if re.search(r"by \w+day", m.group(0)) else "when it happens",
                                 "status": "open"})
    irreversible = {"execute_erasure", "release_data_export"}
    if d["lane"] != "HUMAN":
        d["actions"] += [a for a in d.get("proposed", []) if a not in irreversible]
        d["proposed"] = [a for a in d.get("proposed", []) if a in irreversible]
    d["signoff"] = d["lane"] != "HUMAN" and bool(d["proposed"])
    mins = MINUTES.get(d["person_reason"], 0) if d["lane"] == "HUMAN" else 0
    if d["lane"] == "HUMAN" and d["person_reason"] == "critical" and startup:
        key = (c.intent, startup)
        if key in state["crit_cases"]:
            first = state["crit_cases"][key]
            d["same_case_as"] = first
            mins = MINUTES["critical_repeat"]
            if d.get("brief"):
                d["brief"]["steps"] = [f"Same issue as {first}: the decision is already made, apply it here"] + \
                    d["brief"].get("steps", [])
        else:
            state["crit_cases"][key] = eid
    if d["signoff"]:
        day = (d.get("send_at") or str(now))[:10]
        for a in d["proposed"]:
            if (day, a) not in state["signoff_days"]:
                state["signoff_days"].add((day, a))
                mins += MINUTES["signoff"]
    d["person_minutes"] = mins + (MINUTES["alert"] if d["alert"] else 0)
    return d


def merge_pending(results, ctx):
    """If the same person writes again about the same thing before our reply goes out, send one reply."""
    last = {}
    for x in sorted(results, key=lambda x: x["email"]["received_at"]):
        d = x["dec"]
        if d["lane"] != "AUTO_REPLY":
            continue
        k = (ctx["ident"][x["email"]["email_id"]], x["cls"].intent)
        prev = last.get(k)
        if prev and x["email"]["received_at"] <= prev["dec"]["send_at"]:
            pd = prev["dec"]
            pd["lane"], pd["reply"], pd["send_at"] = "AUTO_ACTION", None, None
            pd["reasons"] = [f"Merged: they wrote again before our reply went out, answered once in {x['email']['email_id']}"]
            pd["merged_into"] = x["email"]["email_id"]
            pd["move"] = "no_reply"
        last[k] = x
