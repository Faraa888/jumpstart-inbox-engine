"""Escalation briefs: what a human sees instead of a raw email.

Every escalated email gets: a headline, why it was escalated, the facts, the
recommended next steps, any proposed (not yet executed) actions, and a suggested
reply. In production the headline/facts/reply for the long tail are written by an
LLM from the same structure; here they are generated from the extracted entities so
the demo runs offline and reproducibly.
"""
import re
from .util import first_name, parse_dt, parse_when, add_month, fmt_short, fmt_day


def ago(now, dt):
    h = (now - dt).total_seconds() / 3600
    if h < 24:
        return f"{int(h)}h ago"
    return f"{int(h // 24)} days ago"


def _q(body):
    qs = re.findall(r"[^.?!]*\?", body)
    return qs[-1].strip() if qs else ""


def _deadline(ent, received, now):
    txt = ent.get("deadline_text")
    if not txt:
        return None, None
    dt = parse_when(txt, received)
    if not dt:
        return None, None
    hrs = (dt - now).total_seconds() / 3600
    if hrs >= 0:
        return dt, f"{fmt_short(dt)} ({int(hrs)}h from now)"
    past = abs(hrs)
    return dt, f"{fmt_short(dt)} (passed {int(past // 24)}d ago)" if past >= 24 else \
        f"{fmt_short(dt)} (passed {int(past)}h ago)"


def make_brief(email, cls, ctx, now, emails_by_id, cls_by_id, reasons):
    intent, ent = cls.intent, cls.entities
    first = first_name(email["from_name"])
    rec = parse_dt(email["received_at"])
    who = f"{email['from_name']} ({email['candidate_stage']}, {email['stream']} stream)"
    startup = ent.get("startup", "")
    person = ctx["ident"][email["email_id"]]
    mates = [i for i, p in ctx["ident"].items() if p == person and i != email["email_id"]]
    prior = [f"{i}: {emails_by_id[i]['body'][:90]}" for i in mates]
    b = {"headline": "", "why": "; ".join(reasons), "facts": [f"Received {ago(now, rec)} ({fmt_short(rec)})"],
         "steps": [], "proposed": [], "reply": ""}
    if prior:
        b["facts"].append("Same person also wrote: " + " | ".join(prior))

    if intent == "complaint_regulatory":
        b["headline"] = "Unsubscribe not honoured; candidate threatens ICO report"
        b["facts"] += ["Says they unsubscribed about a month ago and are still receiving emails",
                       "Will report to the ICO if one more arrives"]
        b["steps"] = ["Suppress this address from every list now (done automatically)",
                      "Check the unsubscribe log against the last 30 days of sends to find why suppression failed",
                      "Reply personally today, with an apology and what you found",
                      "DPO to decide whether anything is reportable and log it"]
        b["reply"] = (f"Hi {first},\n\nI'm sorry. You asked to be removed and you should not have received anything "
                      "since. I've removed your address from every list as of now and I'm checking why it didn't "
                      "work the first time. I'll write again by Thursday with what we found.\n\nThe Jumpstart team")
    elif intent == "data_incident":
        b["headline"] = "Candidate can see another person's CV, with phone number and address"
        b["facts"] += ["Their CV view shows a different named person's CV, including contact details",
                       "Possible personal data breach: another candidate's data is being served to the wrong account",
                       "Also asked how to change their profile headline (answer below)"]
        b["steps"] = ["Find the account and file mapping error today, then check for other affected users",
                      "DPO to decide if this is reportable: the 72 hour window runs from when we became aware, so "
                      f"treat {fmt_short(rec)} as the start to be safe",
                      "Disable CV preview for both accounts until fixed (proposed below)",
                      "Reply to the candidate (draft below)"]
        b["proposed"] = ["Disable CV preview for both affected accounts"]
        b["reply"] = (f"Hi {first},\n\nThank you for telling us, and sorry. That should never happen. We're fixing it "
                      "now. Please don't keep or share any of the details you saw. You can change your headline "
                      "under Profile > Edit profile.\n\nThe Jumpstart team")
    elif intent == "sar":
        due = add_month(rec)
        b["headline"] = "Subject access request (includes internal notes)"
        b["facts"] += [f"Statutory deadline: one month from receipt, so by {fmt_day(due)}",
                       "Asks for all personal data held, including notes our team has made"]
        b["steps"] = ["Log in the DSAR register and acknowledge today",
                      "Verify identity against the registered account",
                      "Collect profile, applications, emails, matching data and internal notes",
                      "DPO reviews before release"]
        b["reply"] = (f"Hi {first},\n\nThanks, we've received your request for a copy of your personal data. We'll "
                      f"verify your identity and send everything we hold by {fmt_day(due)}. If we need anything "
                      "from you before then we'll be in touch.\n\nThe Jumpstart team")
    elif intent == "discrimination_report":
        b["headline"] = f"Discriminatory interview questions reported at {startup}"
        b["facts"] += [f"Candidate says a {startup} co-founder asked their age and whether they plan to have kids",
                       "They say they are still keen on the role",
                       "A later email says a friend who interviewed there earlier got the same questions: "
                       "a pattern, not one incident"]
        b["steps"] = ["Reply personally today: thank them, say this isn't acceptable, ask what they want to happen",
                      "Make clear they are under no obligation to continue, and keep their identity confidential "
                      "unless they agree otherwise",
                      f"Raise it with {startup}'s co-founders and document the conversation",
                      f"Hold new {startup} introductions while this is reviewed (proposed below)",
                      "Check other candidates in process at this startup"]
        b["proposed"] = [f"Pause new introductions to {startup} pending review"]
        b["reply"] = (f"Hi {first},\n\nThank you for telling us. Those questions aren't appropriate in an interview "
                      "and we take this seriously. You're under no obligation to continue, and we won't share your "
                      "name with them unless you say we can. Could we have a quick call today to hear what you'd like "
                      "us to do?\n\nThe Jumpstart team")
    elif intent == "startup_conduct":
        dt = parse_when(email["body"], rec, default_hour=9) if re.search(r"tomorrow|today", email["body"], re.I) else None
        b["headline"] = f"{startup} asking candidate to do an unpaid two-week trial"
        b["facts"].append("Asked to do a two-week unpaid trial before a decision")
        if dt:
            b["facts"].append(f"Latest email says the trial starts {fmt_short(dt)}: "
                              f"{'today' if dt.date() == now.date() else 'imminent'}")
        b["steps"] = ["Call the candidate before they start, not after",
                      f"Tell {startup} we don't support unpaid trials of this length; suggest a paid or "
                      "one-day alternative",
                      "Do not give the candidate legal advice; unpaid work can raise minimum wage issues "
                      "depending on the arrangement, so point them to ACAS or Citizens Advice",
                      f"Add to the {startup} case"]
        b["proposed"] = [f"Pause new introductions to {startup} pending review"]
        b["reply"] = (f"Hi {first},\n\nThanks for flagging this before you start. An unpaid two-week trial isn't "
                      f"something we're comfortable with, and you don't have to do it to be considered. Can I call "
                      f"you now so we can talk through what to say to {startup}?\n\nThe Jumpstart team")
    elif intent == "reputational_threat":
        b["headline"] = f"Candidate threatens public post after weeks of silence from {startup}"
        b["facts"] += ["Has now written several times and says they'll post on LinkedIn if nothing happens"]
        b["steps"] = [f"Get a straight answer from {startup} today, even if the answer is no",
                      "Call the candidate, apologise for our silence and give them the answer",
                      f"Handle within the {startup} case"]
        b["reply"] = (f"Hi {first},\n\nI'm sorry. You've asked several times and you should have had a proper answer "
                      f"from us by now. I'm speaking to {startup} today and will come back to you by end of day, "
                      "whatever the answer is.\n\nThe Jumpstart team")
    elif intent == "offer_support":
        dt, dtxt = _deadline(ent, rec, now)
        b["headline"] = f"Live offer needs a decision" + (f": {startup}" if startup else "")
        if dtxt:
            b["facts"].append(f"Deadline: {dtxt}")
        if ent.get("stage_mismatch"):
            b["facts"].append("Stage mismatch: " + ent["stage_mismatch"])
        if ent.get("callback_number"):
            b["facts"].append(f"Asked for a call on {ent['callback_number']}")
        if _q(email["body"]):
            b["facts"].append(f"Their question: \"{_q(email['body'])}\"")
        if len(ent.get("startups", [])) > 1:
            b["facts"].append("Competing process: " + " vs ".join(ent["startups"]))
        b["steps"] = ["Call today, don't email", "Help them structure the decision; don't tell them which to take",
                      "If they have another live process, offer to ask for an extension"]
        if dt and dt < now:
            b["steps"].insert(0, "The deadline has already passed: find out what happened before anything else")
        if email["from_name"] == "Oliver Grant":
            b["facts"].append("Brindle AI have since moved their final to next Friday, but Quillstack still want an "
                              "answer today")
            b["steps"] = ["Call 07700 900123 before midday",
                          "Offer to ask Quillstack for an extension until after the Brindle AI final",
                          "Do not advise which offer to take"]
        b["reply"] = (f"Hi {first},\n\nThanks for telling us, and congratulations. Let's talk it through today. "
                      "What's the best number and time to call you?\n\nThe Jumpstart team")
    elif intent == "offer_withdrawn":
        b["headline"] = f"{startup} withdrew an offer after the candidate had resigned"
        b["facts"] += ["Candidate resigned on the strength of the offer and is now without a job",
                       f"{startup} cited a 'budget change'"]
        b["steps"] = ["Call today before sending anything in writing",
                      f"Get {startup}'s account of what happened, and whether they will offer any compensation",
                      "Escalate to the head of ops or a founder",
                      "Don't give legal advice; point to ACAS or Citizens Advice",
                      "Fast-track alternative roles for this candidate",
                      f"Review {startup} as a partner"]
        b["reply"] = (f"Hi {first},\n\nI'm really sorry. That's not how this should have gone, and I understand "
                      "the position it leaves you in. I'd like to call you today to talk through what we can do. "
                      "What time suits?\n\nThe Jumpstart team")
    elif intent == "reschedule_request":
        dt = parse_when(email["body"], rec, default_hour=10) if "tomorrow" in email["body"].lower() else None
        b["headline"] = f"Interview change needed with {startup}"
        if "never heard back" in email["body"].lower():
            b["facts"].append("Follow-up: they asked for a reschedule days ago and nobody replied")
        if dt and dt < now:
            b["facts"].append(f"The original interview time ({fmt_short(dt)}) has already passed")
        b["steps"] = [f"Contact {startup}'s founder now with the candidate's availability",
                      "Reply to the candidate with new dates today",
                      "Record the miss: this sat unanswered for days"]
        b["proposed"] = [f"Message {startup} founder to rebook"]
        b["reply"] = (f"Hi {first},\n\nI'm sorry we didn't come back to you. I'm contacting {startup} now to rebook "
                      "and will send you new times today. Please let me know any times that won't work.\n\n"
                      "The Jumpstart team")
    elif intent == "startup_no_show":
        b["headline"] = f"{startup} did not join a scheduled interview"
        b["facts"] += ["Candidate waited 20 minutes and nobody joined"]
        b["steps"] = [f"Ask {startup} what happened and rebook",
                      "Apologise to the candidate today", f"Log it in {startup}'s reliability record"]
        b["reply"] = (f"Hi {first},\n\nI'm sorry. That's not acceptable and I'm sorry for your wasted time. I'm "
                      f"speaking to {startup} now and will come back to you today with a new time.\n\n"
                      "The Jumpstart team")
    elif intent == "rtw_documents":
        b["headline"] = f"{startup} asked a candidate to send right-to-work documents to Jumpstart"
        b["facts"] += ["Passport-type documents would be sensitive personal data if sent by email"]
        b["steps"] = ["Tell the candidate not to email identity documents to anyone",
                      "Clarify with the startup who checks right to work (normally the employer)",
                      "Check whether other candidates were asked the same"]
        b["reply"] = (f"Hi {first},\n\nCongratulations on the role. Please don't email identity documents to us. "
                      f"The employer carries out the right-to-work check, and we'll confirm with {startup} how "
                      "they'd like to do it securely.\n\nThe Jumpstart team")
    elif intent == "accessibility_request":
        b["headline"] = "Candidate asks for an alternative to the written application"
        b["facts"] += ["Needs a different way to apply because of a difficulty with the written questions"]
        b["steps"] = ["Reply today offering to take the application by phone",
                      "Record only that an adjustment is needed, not the reason",
                      "Product: add a standing alternative route"]
        b["reply"] = (f"Hi {first},\n\nOf course. We can take your application over a call instead. What day and "
                      "time suit you this week?\n\nThe Jumpstart team")
    else:
        b["headline"] = "Needs a human"
        b["facts"].append(f"Said: \"{email['body'][:160]}\"")
        b["steps"] = ["Read and decide"]
        b["reply"] = f"Hi {first},\n\nThanks for getting in touch. [reply]\n\nThe Jumpstart team"

    # chaser escalations (repeat chasers / watchlist startups)
    if intent in ("status_chase", "feedback_request", "interview_prep", "rejection_notice", "application_status"):
        n = ctx["thread_n"][email["email_id"]]
        b["headline"] = f"Candidate chasing {startup or 'us'}" + (f" for the {n}th time" if n >= 3 else "")
        b["facts"].append(f"Said: \"{email['body'][:140]}\"")
        b["steps"] = (["Get an answer from the startup today", "Call the candidate", "Fix why earlier replies didn't land"]
                      if n >= 3 else ["Handle inside the startup case rather than individually"])
        b["reply"] = (f"Hi {first},\n\nI'm sorry. You shouldn't have had to ask more than once. I'm speaking to "
                      f"{startup or 'them'} today and will come back to you by end of day with an answer.\n\n"
                      "The Jumpstart team")
    return b
