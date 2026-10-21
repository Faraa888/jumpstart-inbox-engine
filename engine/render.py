"""Reply rendering. Auto-sent replies are built only from approved templates + the KB."""
import re
from .util import first_name, add_working_days, fmt_day, parse_dt, opener


def faq_key(sub, body):
    b = body.lower()
    if sub == "video":
        for pat, key in [(r"compulsory|camera shy", "video_compulsory"), (r"how long", "video_length"),
                         (r"professional", "video_professional"), (r"phone", "video_phone"),
                         (r"re-?record", "video_rerecord"), (r"talk about", "video_topics"),
                         (r"before my cv", "video_order")]:
            if re.search(pat, b):
                return key
    if re.search(r"free|pay anything", b):
        return "pricing"
    if re.search(r"how does the matching", b):
        return "matching"
    if re.search(r"what time do you send", b):
        return "email_timing"
    if re.search(r"\bevents?\b", b):
        return "events"
    if re.search(r"age limit", b):
        return "age"
    if re.search(r"right to work", b):
        return "right_to_work"
    if re.search(r"relocat|moving to london|join now|start interviewing", b):
        return "relocation"
    if re.search(r"more than one role|same startup", b):
        return "multiple_roles"
    return "general"


def howto_key(body):
    b = body.lower()
    for pat, key in [(r"headline", "headline"), (r"photo", "photo"), (r"font", "font"), (r"\bcv\b", "cv"),
                     (r"linkedin", "linkedin"), (r"phone number", "phone"), (r"language", "language"),
                     (r"my name|shows my name", "name")]:
        if re.search(pat, b):
            return key
    return "general"


def prep_key(body):
    b = body.lower()
    for pat, key in [(r"thank-you note", "thank_you"), (r"wear", "what_to_wear"), (r"how many interviews", "how_many"),
                     (r"case study", "case_study"), (r"reference", "references"), (r"final interview", "final_interview"),
                     (r"first interview|tips", "first_interview")]:
        if re.search(pat, b):
            return key
    return "general"


def build_reply(template_id, lane, email, cls, ctx, decision, tpl, params, now, labels):
    """Returns (subject, body, kb_assumed) or None."""
    if not template_id:
        return None
    first = first_name(email["from_name"])
    received = parse_dt(email["received_at"])
    late = opener(now, received, params["late_after_hours"])
    ent = cls.entities
    followup = fmt_day(add_working_days(now, params["chase_followup_working_days"]))
    wait = f"{ent['waiting_days']} days" if ent.get("waiting_days") else "a while"
    sorry = "Sorry "
    v = {"sorry": sorry, "first": first, "startup": ent.get("startup") or "the startup", "late": late, "followup": followup,
         "wait": wait, "referral_link": params["referral_link"], "answer": "", "extra": "", "feature": "that",
         "delay_line": "", "receipt_line": "", "aged_line": ""}
    kb_assumed = False
    tid = template_id
    body_l = email["body"].lower()
    if tid == "chase_first" and (ctx["thread_n"][email["email_id"]] >= 2 or ent.get("repeat_signal")):
        tid = "chase_repeat"
    if tid == "app_status":
        if re.search(r"confirm|did you get|come through|confirmation email|received", body_l):
            v["receipt_line"] = "Yes, we have your application. "
        if ent.get("waiting_days", 0) >= params["aged_application_days"]:
            v["aged_line"] = " We know it has taken longer than it should, and we've flagged yours to the team."
    if tid == "rejection_ack" and re.search(r"five weeks|weeks after", body_l):
        v["delay_line"] = " and how long they took to reply"
    if tid == "product_ack" and cls.sub == "zero_matches":
        tid = "product_ack_zero"
    if tid == "product_ack":
        v["feature"] = labels.get(cls.sub, "that")
        v["extra"] = ("We're also checking that your profile is visible and set up for matching, and we'll "
                      "email you only if something needs fixing.") if cls.sub == "zero_matches" else ""
    if tid in ("howto", "faq", "prep"):
        kb_assumed = True
        key = {"howto": howto_key(email["body"]), "faq": faq_key(cls.sub, email["body"]),
               "prep": prep_key(email["body"])}[tid]
        v["answer"] = tpl["kb"][tid][key]
    if tid in tpl["templates"]:
        body = tpl["templates"][tid]
    else:
        body = tpl["draft_templates"][tid]
    body = body.format(**v)
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n\n" + tpl["signature"]
    subj = email["subject"]
    subj = subj if subj.lower().startswith("re:") else "Re: " + subj
    return subj, body, kb_assumed
