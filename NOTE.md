# Jumpstart candidate inbox: one-page note

**What I built.** An engine that reads every candidate email, checks it for risk, finds the answer and either replies or hands a person a ready brief. It runs on all 510 emails, and live: n8n watches an inbox, the engine decides, Resend sends replies, and Slack is where people work.

**The principle.** Escalate decisions, not emails. Every human gets a reply. A person only sees an email for five reasons: it's critical (data, discrimination, legal, threats, distress), a fact we need isn't in our database yet, the reviewer agent disagreed with the drafted reply, it couldn't be classified, or it's a live offer, which goes to the talent partner rather than ops.

**Result on the 510 emails.** 422 answered automatically, 70 need no reply (auto-responders, spam, duplicates, and repeat chasers merged into one reply), 13 to ops and 5 offers to the talent partner. About an hour of person time. The 8 critical emails get an acknowledgement immediately, and the protective step (lock the record, alert the data protection officer) is done before a person opens them.

**What made the difference.**
1. Risk is scanned on every email, never inferred from the subject. Another candidate's CV and address sat inside a "quick question" (E117).
2. Patterns become cases. 32 video reports are one incident. Driftwell's unpaid trials and ghosting trigger one alert to the account owner.
3. Facts are asked once. Visa and salary questions are answered from a facts database. The first email needing a missing fact goes to a person; the answer is saved and every later email gets it automatically. Startups are never chased for it.
4. Workflows replace judgement where the process is known: a rebooking link for reschedules and no-shows, a secure upload link for documents, a statutory data export signed off with one click a day.
5. Two checks before anything is sent. A separate reviewer agent reads the email and reply cold and looks for reasons not to send. Upset senders get a reply written for upset senders.
6. Replies wait 5 to 30 minutes, inside working hours, so they read like a person's, and two quick emails from the same person get one answer.

**10x.** I ran 5,100 emails through the full engine: under 2 seconds. Person time is about 5 hours a week (80 critical emails, mostly a handful of startup-level decisions applied many times; 20 reviewer holds; one-click daily sign-offs), against about 340 hours by hand. Missing facts caused 12 escalations in week 1 and none in week 2. Running cost is under £100 a month: self-hosted n8n, Resend for sending (Gmail's 500-a-day cap would not survive 10x), a small Claude model for the reviewer.

**How far to trust it.** The rules were written from these emails, so the 98% match on my 100 labelled emails is in-sample, and the labels were updated for the new policy (every change is logged). On 24 emails written to break it, it passed 23 first time; I fixed the miss, so that set is spent. The number to trust is a blind relabel of fresh emails, which the repo supports. Facts and help text are placeholders.

**Beyond the inbox.** Most of these emails shouldn't exist. 37% are candidates asking where they stand, 22% are questions the product should answer, 15% are email hygiene and privacy, and 8% are one bug reported by candidates before monitoring caught it. An application tracker with automatic updates, startup response targets, a help centre, one-click unsubscribe and a status page would remove roughly half the inbound before any automation (docs/BEYOND_THE_INBOX.md). The engine keeps counting the causes, so the inbox becomes product insight rather than cost.

**Next.** Connect the candidate database and applicant tracking system so stage and interview data are read, not inferred. Collect startup facts at onboarding so gaps close before anyone asks. Track override rate weekly and promote categories to automatic only after they've earned it.
