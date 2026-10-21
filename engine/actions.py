"""Stage 4: action layer. Every action is a small adapter with a dry-run implementation.

Each adapter returns the payload it WOULD send to the real system. In production you
swap the body of one function for the real call (Resend, Slack, ATS, Supabase...) and
nothing upstream changes. Every action is keyed by an idempotency key, so a re-run or a
duplicate webhook can never send twice.
"""
import json
from .util import parse_dt, add_month, add_working_days, fmt_day, parse_when


def _p(email, c, **kw):
    d = {"candidate": email["from_name"], "email": email["from_email"], "startup": c.entities.get("startup", "")}
    d.update(kw)
    return d


def a_add_to_startup_digest(e, c, ctx, d, now):
    return _p(e, c, channel="startup digest (daily 08:00)", waiting_days=c.entities.get("waiting_days"),
              round=c.entities.get("round", ""), chased=ctx["thread_n"][e["email_id"]])


def a_log_application_age(e, c, ctx, d, now):
    return _p(e, c, waiting_days=c.entities.get("waiting_days"), store="supabase.applications")


def a_escalate_aged_application(e, c, ctx, d, now):
    return _p(e, c, task="Review aged application", owner="screening", waiting_days=c.entities.get("waiting_days"))


def a_request_startup_feedback(e, c, ctx, d, now):
    return _p(e, c, channel="email to startup founder", ask="share feedback with candidate (their choice)")


def a_log_startup_response_time(e, c, ctx, d, now):
    return _p(e, c, store="startup_stats", note=e["body"][:80])


def a_tag_referrer(e, c, ctx, d, now):
    return _p(e, c, tag="referrer: hired candidate")


def a_tag_product_feedback(e, c, ctx, d, now):
    return _p(e, c, tag=c.sub or c.intent, store="product_feedback")


def a_update_stage_hired(e, c, ctx, d, now):
    return _p(e, c, stage_from=e["candidate_stage"], stage_to="Hired",
              note="needs confirmation" if e["candidate_stage"] == "Offer" else "already Hired")


def a_log_placement(e, c, ctx, d, now):
    return _p(e, c, store="placements", detail=e["body"][:90])


def a_log_sentiment_positive(e, c, ctx, d, now):
    return _p(e, c, store="sentiment")


def a_defer_outreach_until_return(e, c, ctx, d, now):
    return _p(e, c, until=c.entities.get("return_hint", "unknown"), note="no reply sent to auto-responder")


def a_mark_incident_link_resolved(e, c, ctx, d, now):
    return _p(e, c, note="candidate reports resolved")


def a_route_vendor(e, c, ctx, d, now):
    if c.sub == "spam":
        return _p(e, c, route="archive (spam)")
    return _p(e, c, route="forward to partnerships@, no reply sent")


def a_suppress_marketing(e, c, ctx, d, now):
    return _p(e, c, list="global suppression", effective=now.isoformat(), reason=c.intent)


def a_open_erasure_ticket(e, c, ctx, d, now):
    return _p(e, c, due=(parse_dt(e["received_at"]).replace(microsecond=0) + __import__("datetime").timedelta(days=30)
                         ).isoformat(), owner="compliance", note="irreversible step needs approval")


def a_open_sar_ticket(e, c, ctx, d, now):
    return _p(e, c, due=add_month(parse_dt(e["received_at"])).isoformat(), owner="dpo")


def a_send_verification_link(e, c, ctx, d, now):
    return _p(e, c, note="verification sent to CURRENT address; login email is never changed from an email request")


def a_send_fresh_magic_link(e, c, ctx, d, now):
    return _p(e, c, note="new link to registered address")


def a_set_profile_paused(e, c, ctx, d, now):
    return _p(e, c, state="paused", reversible=True)


def a_link_to_incident(e, c, ctx, d, now):
    for cid, inc in ctx["incidents"].items():
        if e["email_id"] in inc["email_ids"]:
            return _p(e, c, incident=cid, is_incident=inc["is_incident"])
    return _p(e, c, incident=None)


def a_check_profile_visibility(e, c, ctx, d, now):
    return _p(e, c, check="profile visible and matchable", result="simulated in dry-run")


def a_page_owner(e, c, ctx, d, now):
    return _p(e, c, channel="#ops-urgent (Slack)", owner=d["owner"], priority=f"P{d['priority']}")


def a_merge_duplicate(e, c, ctx, d, now):
    return _p(e, c, merged_into=ctx["dup_of"].get(e["email_id"]))


ADAPTERS = {k[2:]: v for k, v in globals().items() if k.startswith("a_")}


def execute(e, c, ctx, d, now, db):
    """Run decision actions. Returns list of action records written (new ones only)."""
    written = []

    def rec(action, status, payload, target=""):
        key = f"{e['email_id']}:{action}:{target}"
        cur = db.execute("INSERT OR IGNORE INTO actions(idem_key,email_id,action,status,payload,ts) VALUES(?,?,?,?,?,?)",
                         (key, e["email_id"], action, status, json.dumps(payload), now.isoformat()))
        if cur.rowcount:
            written.append({"email_id": e["email_id"], "action": action, "status": status, "payload": payload})

    lane = d["lane"]
    if lane == "AUTO_REPLY" and d["reply"]:
        rec("send_reply", "dry_run_sent", {"to": e["from_email"], "subject": d["reply"]["subject"],
                                           "provider": "email (dry-run)", "template": d["template"],
                                           "send_at": d.get("send_at")})
    elif lane == "DRAFT" and d["reply"]:
        rec("save_draft", "awaiting_approval", {"to": e["from_email"], "subject": d["reply"]["subject"],
                                                "template": d["template"]})
    elif lane == "HUMAN":
        if d.get("ack"):
            rec("send_acknowledgement", "dry_run_sent", {"to": e["from_email"], "subject": d["ack"]["subject"],
                                                         "when": "immediately", "template": "ack"})
        rec("create_escalation", "queued", {"owner": d["owner"], "priority": f"P{d['priority']}",
                                            "reasons": d["reasons"]})
    for a in d["actions"]:
        payload = ADAPTERS[a](e, c, ctx, d, now) if a in ADAPTERS else _p(e, c)
        rec(a, "dry_run_done", payload)
    for p in d["proposed"]:
        rec(p, "proposed_needs_approval", {"requested_for": e["from_name"], "reason": d["reasons"]}, target="p")
    return written
