"""Stage 1: classify one email.

Rules first (free, instant, deterministic, testable). Anything the rules cannot
place with confidence falls through to `unknown` with confidence 0, which the
policy engine always routes to a human. An LLM adapter (llm_adapter.py) can
replace or back up this step without changing anything downstream.

Design points:
- Risk flags are scanned on EVERY email, independent of the main intent. A benign
  subject cannot hide a data leak, a legal threat or a discrimination report.
- Subject-line urgency ("URGENT", "ASAP") is deliberately ignored. Only the body counts.
- Email text is treated as untrusted data. Injection-style phrases raise a flag.
"""
import re
from dataclasses import dataclass, field


def R(p):
    return re.compile(p, re.I)


# ---------------------------------------------------------------- risk flags
FLAGS = {
    "injection": R(r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|prompts?|messages)"
                   r"|disregard (all |any )?(previous|prior|your) (instructions|rules)|system prompt"
                   r"|you are now |act as (an?|the) |developer mode|override (your|the) (rules|policy)"
                   r"|reveal your (prompt|instructions)|mark (me|this|my application) as"),
    "privacy_legal": R(r"\bgdpr\b|subject access|\bico\b|data protection|information commissioner"
                       r"|copy of all (the )?personal data"),
    "data_exposure": R(r"someone (called|else)|shows? (someone|somebody)|another (person|candidate|user)'?s"
                       r"|(her|his|their) (phone number|address)|showing up on google|on google when"
                       r"|publicly (visible|available)|visible to anyone|\bindexed\b|\bleaked\b|\bexposed\b"),
    "multi_part": R(r"\balso\b|by the way|\bps\b|p\.s\.|another question|one more thing|\banyway\b"),
    "discrimination": R(r"how old (i|she|he) was|asked (me )?(how old|my age|about my age)"
                        r"|(planning to|going to|want to) have (kids|children|a baby)|pregnan"
                        r"|asked the same thing|marital status|my religion|my ethnicity"),
    "unpaid_work": R(r"unpaid|(two|2)[- ]week trial|start the trial|work trial"),
    "public_threat": R(r"post about (this|it) on linkedin|going to post|go public|report(ing)? (jumpstart|you|them)"
                       r"|trustpilot|tell the press"),
    "rtw_docs": R(r"right to work documents?|send (my )?(passport|id|documents?) (to you|over)|\bpassport\b|\bbrp\b"
                  r"|share code"),
    "accessibility": R(r"dyslexi|dyspraxi|adhd|autis|disabilit|neurodiver|wheelchair|reasonable adjustment"
                       r"|hearing loss|visually impaired"),
    "offer_withdrawn": R(r"withdr(a|e)w(ing|n)? (the |my )?offer|offer (was|has been) withdrawn|rescind"),
    "frustration": R(r"third time|fourth time|\d(st|nd|rd|th) time|is anyone reading|pretty poor|ghosted"
                     r"|still nothing from .* or from you|no feedback at all|second time asking|fed up"
                     r"|unacceptable|disgrace|gone silent|should i assume it's a no"),
    "wellbeing": R(r"don'?t see the point|can'?t go on|end it all|kill myself|suicid|self[- ]?harm|hurt myself"
                   r"|no reason to live|want to die|feel hopeless|can'?t cope"),
    "frustration_strong": R(r"ghosted|gone silent|or from you|third time|fourth time|no feedback at all|pretty poor"
                            r"|is anyone reading|third email"),
    "time_critical": R(r"tomorrow|tonight|today|in an hour|by (5pm|midday|noon)"),
}
# Any of these forces a human, whatever the main intent is.
HARD_FLAGS = {"wellbeing", "injection", "privacy_legal", "data_exposure", "discrimination", "unpaid_work",
              "public_threat", "rtw_docs", "accessibility", "offer_withdrawn"}

# flag -> intent it promotes to (highest severity wins as primary intent)
FLAG_INTENT = [
    ("wellbeing", "wellbeing_concern"),
    ("public_threat", "reputational_threat"),
    ("data_exposure", "data_incident"),
    ("discrimination", "discrimination_report"),
    ("offer_withdrawn", "offer_withdrawn"),
    ("unpaid_work", "startup_conduct"),
    ("rtw_docs", "rtw_documents"),
    ("accessibility", "accessibility_request"),
]

# ---------------------------------------------------------------- patterns
OOO_SUBJ = R(r"^(automatic reply|auto-?reply|out of office)")
OOO_BODY = R(r"out of (the )?office|annual leave|parental leave|limited access to email|away until|on holiday")
SAR = R(r"subject access|copy of all (the )?personal data")
COMPLAINT = R(r"\bico\b|formal complaint|solicitor|lawyer|legal action|report(ing)? jumpstart")
DELETE = R(r"delete my (account|data|profile)|remove my profile|close my account|profile and data removed"
           r"|delete my data|account and (all )?(the )?data|please delete")
UNSUB = R(r"^\s*stop\s*[.!]?\s*$|unsubscribe|take me off|stop (sending|emailing|messaging)|stop these|stop the emails"
          r"|stop emails|off your mailing list|remove me from")
OFFER_LANG = R(r"\boffered me\b|offer letter|received an offer|got an offer|i('ve| have) (an|got an|received an) offer"
               r"|have offers?\b")
SUCCESS = R(r"(just )?accepted (the |my )?offer|i('ve| have) accepted|start date is|\bi start (on|monday|tuesday|next)"
            r"|i got it|got the job")
NO_SHOW = R(r"nobody joined|didn't turn up|no one (joined|turned up)|nobody turned up|waited \d+ minutes")
RESCHEDULE = R(r"reschedul|can't make my interview")
LISTING = R(r"can't (see|find) the .* role|role is still missing|missing from my dashboard|can't find it"
            r"|hidden the listing|went ahead in the end")
VIDEO_WORD = R(r"video|upload")
VIDEO_FAIL = R(r"won't upload|upload (just )?(spins|fails|failed|error|isn't|broken|still)|stuck|freezes|error \d{3}"
               r"|fails at|keeps (failing|saying)|isn't working|not working|won't load|not loading|is blank|site down"
               r"|is the site down|upload down|broken|can't upload|just spins|still not|upload bar"
               r"|third email about this|same as before|tried (three|\d|a few|5)|another way to send")
VIDEO_RESOLVED = R(r"uploaded fine|it worked when|worked when i compressed|ignore my last email")
VIDEO_CHECK = R(r"can someone check it saved|can't see it on my profile")
VIDEO_FAQ = R(r"compulsory|how long should|professional|from (my|a) phone|re-?record|what should i talk|"
              r"before my cv|camera shy")
APPLY_BTN = R(r"apply button")
LOGIN = R(r"password|\blog ?in\b|login|magic link")
CHANGE_EMAIL = R(r"change (of )?(my )?(login )?email|update my email")
PAUSE = R(r"pause (my )?(account|profile)")
STREAM = R(r"different stream|change stream|two streams|in both|marketing roles too")
HOWTO = R(r"(headline|profile photo|photo|linkedin|phone number|second language|font|new version of my cv"
          r"|my name as|shows my name|upload a new version)")
CHASE = R(r"any (update|news|idea)|haven't heard|heard back|hear back|made a decision|decision yet|checking in"
          r"|following up|still (waiting|nothing|no news)|chase|nudge|where i stand|assume it's a no|take a look"
          r"|when i'll hear|get back to me|gone silent|ghosted|decision after|still open|still hiring|just following up"
          r"|third time asking|will i hear")
APP_STATUS = R(r"applied|application|under review|confirmation email|where i am in the process|reapply")
FEEDBACK = R(r"feedback|why .* said no|find out why")
PREP = R(r"\btips?\b|advice|thank-you note|what should i (wear|say)|how many interviews|is that normal"
         r"|should i (send|say)|case study")
SALARY = R(r"salary|what should i say")
REFERENCE = R(r"reference")
MATCH = R(r"match(es)?\b|weekly roles|filter|minimum salary|visa sponsorship|roles outside|very junior|remote-only"
          r"|none of them are in")
VISA = R(r"visa|sponsor")
ELIG = R(r"right to work|relocat|age limit|moving to london|join now|more than one role|same startup|two streams")
REFERRAL = R(r"refer a friend|referral|can i refer")
EVENTS = R(r"\bevents?\b")
FAQ = R(r"how does the matching|is jumpstart free|do i have to pay|what time do you send|free for candidates"
        r"|is the video compulsory|how long should|age limit|do startups see")
THANKS = R(r"^(thanks|thank you|really enjoyed|great newsletter|loved this|just wanted to say|the founder interview"
           r"|quick thank you)|thanks for (the|your)|thank you for")
CONTENT_REQ = R(r"could you do one on")
NEG_EXP = R(r"bad experience|do startups actually look|only heard back from")
VENDOR = R(r"partnership|podcast|careers fair|speaking opportunity|traffic|leads|stand at our")

STAGE_SOURCE_NOTE = "stage from candidate_stage column (system of record), never inferred from email text"

NUM_WORDS = {"a": 1, "one": 7, "two": 14, "three": 21, "four": 28, "five": 35}


@dataclass
class Result:
    intent: str = "unknown"
    sub: str = ""
    confidence: float = 0.0
    rule: str = ""
    flags: list = field(default_factory=list)
    secondary: str = ""
    entities: dict = field(default_factory=dict)


def match_sub(b):
    if re.search(r"\b0 matches|no matches|very few matches|is my profile visible|profile ok", b, re.I):
        return "zero_matches"
    if re.search(r"minimum salary|£\d+k", b, re.I):
        return "filter_salary"
    if re.search(r"remote", b, re.I):
        return "filter_remote"
    if re.search(r"location|manchester|outside london|bristol", b, re.I):
        return "filter_location"
    if re.search(r"engineering|my stream|stream", b, re.I):
        return "stream_relevance"
    if re.search(r"junior", b, re.I):
        return "seniority"
    return "other"


def extract(subject, body, stage, startup_col, startups):
    t = f"{subject} {body}"
    ent = {}
    found = [s for s in startups if s.lower() in t.lower()]
    cols = [x.strip() for x in str(startup_col).split(";")] if startup_col and str(startup_col) != "nan" else []
    ent["startups"] = found or cols
    ent["startup"] = (found or cols or [""])[0]
    wn = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    m = re.search(r"\b(\d+|a|one|two|three|four|five) (day|week|month)s? (ago|since)"
                  r"|been (\d+|a|one|two|three|four|five) (day|week|month)s?", t, re.I)
    if m:
        g = [x for x in m.groups() if x]
        n = int(g[0]) if g[0].isdigit() else wn[g[0].lower()]
        ent["waiting_days"] = n * {"day": 1, "week": 7, "month": 30}[g[1].lower()]
    elif re.search(r"almost a month", t, re.I):
        ent["waiting_days"] = 28
    m = re.search(r"(first|second|final) (round|interview)|final round|my final", t, re.I)
    if m:
        ent["round"] = m.group(1).lower() if m.group(1) else "final"
    if re.search(r"\bagain\b|still nothing|second time|third time|fourth time|still no news|third email", body, re.I):
        ent["repeat_signal"] = True
    m = re.search(r"(answer|sign|reply|respond)[^.]*?\bby\s+([^.?,]+)", body, re.I) or \
        re.search(r"want an answer on ([^.?,]+)", body, re.I)
    if m:
        ent["deadline_text"] = m.group(m.lastindex).strip()
    m = re.search(r"\b(0\d{3,4} ?\d{3} ?\d{3,4})\b", body)
    if m:
        ent["callback_number"] = m.group(1)
    m = re.search(r"(?:until|back|returning)\s+(?:on\s+)?((?:\d{1,2} \w+)|(?:\w+day)|next week|january)", t, re.I)
    if m:
        ent["return_hint"] = m.group(1)
    m = re.search(r"£\s?(\d+)k", body)
    if m:
        ent["salary_k"] = int(m.group(1))
    return ent


def classify(subject, body, stage, startup_col, startups):
    subject, body = str(subject), str(body)
    t = f"{subject} {body}"
    r = Result()
    r.entities = extract(subject, body, stage, startup_col, startups)
    r.flags = [k for k, rx in FLAGS.items() if rx.search(body) or (k in ("privacy_legal", "public_threat")
                                                                  and rx.search(subject))]

    def done(intent, conf, rule, sub=""):
        r.intent, r.confidence, r.rule, r.sub = intent, conf, rule, sub
        return r

    # 1. auto-replies: never answer, never loop
    if OOO_SUBJ.search(subject) or (OOO_BODY.search(body) and len(body) < 160 and not CHASE.search(body)):
        r.flags = []
        return done("ooo_autoreply", 0.98, "ooo")

    # 2. vendors / non-candidates
    if stage == "Not a candidate":
        sub = "spam" if re.search(r"traffic|leads|10x|double your", t, re.I) else "opportunity"
        return done("vendor_inbound", 0.95, "stage-not-candidate", sub)

    # 3. hard-flag promotion (highest severity is the primary intent)
    if SAR.search(t):
        return done("sar", 0.97, "sar")
    if COMPLAINT.search(t) and ("privacy_legal" in r.flags or "public_threat" in r.flags):
        return done("complaint_regulatory", 0.97, "complaint")
    for flag, intent in FLAG_INTENT:
        if flag in r.flags:
            if intent == "data_incident":
                r.secondary = "account_admin"
            return done(intent, 0.95, f"flag:{flag}")

    # 4. offers
    if stage == "Offer" or SUCCESS.search(body) or OFFER_LANG.search(body):
        if SUCCESS.search(body):
            return done("placement_success", 0.93, "success")
        if stage != "Offer":
            r.entities["stage_mismatch"] = f"email describes an offer but stage is '{stage}'"
        sub = "deadline" if r.entities.get("deadline_text") else ("callback" if r.entities.get("callback_number")
                                                                    else "advice")
        return done("offer_support", 0.95, "stage-offer", sub)

    # 5. time-critical interview problems
    if NO_SHOW.search(body):
        return done("startup_no_show", 0.95, "no-show")
    if RESCHEDULE.search(t):
        return done("reschedule_request", 0.95, "reschedule")

    # 6. privacy requests
    if DELETE.search(body):
        return done("data_deletion", 0.95, "delete")
    if UNSUB.search(body) and len(body) < 120:
        return done("unsubscribe", 0.95, "unsub-body")
    if UNSUB.search(subject) and len(body) < 80:
        return done("unsubscribe", 0.85, "unsub-subject")

    # 7. platform problems
    if VIDEO_RESOLVED.search(body):
        return done("video_resolved", 0.9, "video-resolved")
    if VIDEO_WORD.search(t) and VIDEO_FAIL.search(t) and not VIDEO_FAQ.search(body):
        return done("platform_bug", 0.93, "video-bug", "video_upload")
    if VIDEO_CHECK.search(body):
        return done("platform_bug", 0.88, "video-check", "video_check")
    if APPLY_BTN.search(body):
        return done("platform_bug", 0.93, "apply-button", "apply_button")
    if LISTING.search(body) and "Harbourlight" in t:
        sub = "resolved" if re.search(r"went ahead|hidden the listing", body, re.I) else "listing_missing"
        return done("platform_bug", 0.92, "listing", sub)
    if CHANGE_EMAIL.search(t):
        return done("account_admin", 0.93, "change-email", "change_email")
    if LOGIN.search(t) and stage == "Onboarded":
        return done("account_admin", 0.9, "login", "login")

    # 8. stage-specific
    if stage == "Rejected":
        if THANKS.search(body):
            return done("thanks", 0.88, "thanks")
        if FEEDBACK.search(t):
            return done("feedback_request", 0.95, "feedback")
        if re.search(r"rejected|said no|a no", body, re.I):
            return done("rejection_notice", 0.85, "rejection-info")
    if stage == "Applied" and (APP_STATUS.search(t) or CHASE.search(body)) and not re.search(r"refer|events|free|visa|right to work|relocat|"
                                                                       r"accessib|age limit|more than one|two streams", t, re.I):
        return done("application_status", 0.93, "app-status")
    if stage == "Interviewing":
        if REFERENCE.search(body) and re.search(r"manager|redundan", body, re.I):
            return done("reference_help", 0.9, "reference-sensitive")
        if SALARY.search(t) and re.search(r"salary|expectation", body, re.I):
            return done("salary_guidance", 0.92, "salary")
        if PREP.search(t) and not CHASE.search(body):
            return done("interview_prep", 0.9, "prep")
        if CHASE.search(body):
            sub = "asks_to_chase" if re.search(r"chase|nudge", body, re.I) else ""
            return done("status_chase", 0.93, "chase", sub)
        if THANKS.search(body):
            return done("thanks", 0.88, "thanks")

    # 9. account admin
    if PAUSE.search(body):
        return done("account_admin", 0.93, "pause", "pause_profile")
    if STREAM.search(body):
        return done("account_admin", 0.9, "stream", "stream_change")
    if HOWTO.search(body) and not MATCH.search(body):
        return done("account_admin", 0.9, "howto", "howto")

    # 10. product, eligibility, faq
    if NEG_EXP.search(body):
        return done("negative_experience", 0.88, "neg-exp")
    if CONTENT_REQ.search(body):
        return done("product_feedback", 0.85, "content-request", "content")
    if THANKS.search(body) and len(body) < 120:
        return done("thanks", 0.9, "thanks")
    if VISA.search(body) and re.search(r"sponsor|graduate visa|skilled worker", body, re.I):
        return done("visa_sponsorship", 0.9, "visa")
    if re.search(r"what time do you send", body, re.I):
        return done("faq", 0.92, "email-timing", "general")
    if MATCH.search(body) or re.search(r"\bfilter\b|roles by location", body, re.I):
        return done("product_feedback", 0.9, "match-quality", match_sub(body))
    if REFERRAL.search(body):
        return done("referral", 0.93, "referral")
    if EVENTS.search(body):
        return done("faq", 0.9, "events", "events")
    if ELIG.search(body):
        return done("faq", 0.9, "eligibility", "eligibility")
    if FAQ.search(body) or VIDEO_FAQ.search(body):
        return done("faq", 0.9, "faq", "video" if re.search(r"video|re-?record", body, re.I) else "general")

    # 11. fail safe
    return done("unknown", 0.0, "no-rule")
