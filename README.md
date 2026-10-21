# Jumpstart inbox engine

**Loom walkthrough:** https://www.loom.com/share/f7e54ad6d51c48aca17e6a5835c84350
**Live console:** https://faraa888.github.io/jumpstart-inbox-engine/out/console.html

Every candidate email is read, checked for risk and resolved. Most are answered automatically, a few go to a person, and nothing a person has answered once needs a person again.

On the case data (510 emails, one week): **422 answered automatically, 70 silent (auto-responders, spam, duplicates, merged), 13 to ops and 5 live offers to the talent partner. About 1 hour of person time.**
At 10x (5,100 emails): **processed in under 2 seconds, about 5 hours of person time a week**, against about 340 by hand.

## Check it in 2 minutes

No installs, no keys. Python 3.10+.

    python3 run.py                    # triage the 510 emails -> out/
    python3 tests/test_invariants.py  # 16 safety rules
    python3 eval/score.py             # accuracy on labelled emails + 24 adversarial ones
    python3 eval/scale_test.py        # the 10x run, twice (before and after the facts database fills)
    python3 build_console.py          # out/console.html: open in any browser, works offline

## How an email moves

1. **Arrives.** Stored once under its ID; a repeat or re-run never acts twice.
2. **Who is it.** Matched to the candidate: stage, startup, past emails.
3. **What do they want.** Rules first (free, instant, testable). What they can't place goes to a person. `engine/llm_adapter.py` lets Claude take that tail first (written, not yet wired in).
4. **Risk scan, every email.** Data exposure, discrimination, legal or regulator threats, public threats, distress, unpaid work, instructions aimed at the system. Subject lines are ignored.
5. **Context.** Repeat chasers, outages (32 video reports become one incident), startup patterns.
6. **Find the answer.** Approved templates, the facts database (`config/facts.json`), or a workflow: rebooking link, secure upload link, data export.
7. **Second opinion.** A reviewer agent reads the email and the reply cold and looks for reasons not to send (`engine/reviewer.py`). Offline it runs rule checks; with `REVIEWER=claude` and an API key, Claude does it.
8. **Send through Resend after 5 to 30 minutes**, 8am to 7pm, so replies don't feel robotic. If the person writes again first, one reply covers both. Critical acknowledgements go instantly.
9. **A person only for five reasons:** critical, missing fact, reviewer disagreed, could not classify, live offer (to the talent partner).
10. **Learn.** A missing fact is answered once and saved, so later emails get it automatically.

**The person works from Slack.** Each escalation arrives with the agents' reasoning and a "Review and send" link: edit the reply, click Send, and it goes out from Gmail. At 9am and 3pm on weekdays Slack lists anything still waiting.

The engine decides; n8n moves email in and out (`n8n/inbox_engine.workflow.json`); Resend sends. Swapping the inbox, Slack or the sender is one node.

## Run it live

`SETUP.md` covers the accounts and wiring. Then `python3 serve.py`, `npx n8n`, and `python3 replay.py` feeds the 510 sample emails through the live workflow in about two minutes while Slack and `http://localhost:8080/console` fill. Replies to the sample's fictional addresses are logged; emails you send to the demo inbox get real replies.

Two views of the same week, both from the same engine:
- **Backlog (Monday 9am, `run.py`):** everything answered at once, so a person who wrote three times gets one reply. 422 answered, 70 no reply, 18 to a person.
- **Real time (`replay.py`):** each email answered as it arrives, as if the system had run all week. About 450 answered, 38 no reply, 22 to a person, including every visa question until someone answers the missing visa fact once.

## At 10x

- Engine: 5,100 emails a week in under 2 seconds (`eval/scale_test.py`). In production it reads history from a database instead of re-running the batch per email, as `serve.py` does for the demo.
- Sending: Resend Pro, 50,000 emails a month for $20; Gmail's 500 a day would not survive 10x.
- n8n: self-hosted, no run cap (n8n Cloud Pro stops at 10,000 runs a month).
- People: about 5 hours a week, mostly critical cases that are a handful of startup-level decisions.

## Files

- `engine/classify.py` rules classifier and risk scan
- `engine/cases.py` identity, duplicates, incidents, startup patterns
- `engine/policy.py` + `config/policy.json` first decision: owner, priority, SLA. Ops can edit the JSON
- `engine/resolve.py` the three outcomes, facts lookups, workflows, delay, merging
- `engine/reviewer.py` the second opinion
- `config/templates.json` approved reply text; `config/facts.json` mock facts database with deliberate gaps
- `serve.py` the engine as a web service for n8n, the live console, the review-and-send and "answer once" pages
- `replay.py` feeds the 510 sample emails through the live workflow
- `n8n/inbox_engine.workflow.json` live wiring: inbox in, engine, wait, Resend out, Slack, reminders, run summary
- `SETUP.md` how to run the live demo; `demo/test_emails.md` the demo emails

## Honest limits

- The rules were written from these emails, so scores on my 100 labelled emails are in-sample. The labels were updated for the new policy and every change is listed in `eval/gold_v2.csv`. For an independent number, label 50 emails blind with `eval/make_label_sheet.py` and run `eval/score.py --gold eval/my_labels.csv`.
- The adversarial set scored 23/24 on its first run; the miss was fixed, so it is no longer a clean test.
- Facts and help text are invented placeholders for Jumpstart to confirm.
- In batch runs every action is a dry run. Live, Resend sends real replies; without a verified domain it only delivers to the Resend account's own address, which is the tester's.
- Person minutes per item are assumptions, listed in `engine/resolve.py`.
- The 10x run clones today's mix of topics. Real growth brings new phrasings, so more emails would go to a person.
