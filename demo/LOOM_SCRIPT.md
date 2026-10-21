# Loom script (about 9 to 10 minutes)

Screens open: console (out/console.html), n8n, Slack #talent-ops, your inbox, terminal.

**1. The problem (45s), console header.**
"510 emails in a week from 468 people, and nobody has replied. The job isn't writing 510 replies. It's making sure the handful that matter reach a person today, and everyone else gets a good answer without one."

**2. The answer (60s), the bar and the numbers.**
"422 are answered automatically. 70 need no reply: out-of-office messages, spam, duplicates, and people who chased twice before we replied, who get one answer. 13 reach ops, about an hour of work. 5 live offers go to the talent partner. The rule is: escalate decisions, not emails."

**3. Why subject lines lie (60s), Needs a person, E117.**
"This says 'quick question'. Inside is another candidate's CV and home address. Every email is scanned for risk whatever the subject says. The candidate was acknowledged instantly, the record is locked, and a person makes the call with the facts already laid out."

**4. The five reasons a person sees an email (45s), scroll the queue groups.**
"Critical. A fact we don't hold yet. The reviewer agent disagreed. Couldn't classify. Or a live offer, which isn't inbox work, so it goes to the talent partner."

**5. Facts are asked once (45s), Facts database tab.**
"This is what I'd start collecting: visa sponsorship, salary ranges, interview process, per startup. It's a mock with real gaps. The first candidate who needs a missing fact goes to a person. Their answer is saved, and nobody needs a person for it again. We never chase the startup for it."

**6. It runs (2 min), terminal + n8n + Slack + console.**
Run `python3 replay.py`. "This feeds the 510 emails through the live system as if they'd arrived over the week. Every one goes through n8n and the engine exactly like a real email. Watch Slack and the dashboard." Let it run; show the summary in Slack: "If this had been running all week: about 450 answered within half an hour of arriving, 22 for a person."
"Now a real one. I'm emailing the demo inbox as a candidate." Send email 1 and email 2. Show the Slack brief and the instant acknowledgement, then the automatic reply about a minute later.
Open the Slack alert: "Here's how the agents got here: the triage agent read it as a data incident, the reviewer was never asked, because critical emails never get an automatic reply." Click "Review and send", tweak a line, Send. "That went out from Gmail. The person works entirely from Slack and never opens the inbox. Every morning and afternoon, Slack tells them what's still waiting."
Then the form: type the "showing up on Google" email live. "A phrasing it's never seen, and it still goes to a person."
"Replies go out through Resend after 5 to 30 minutes in real use, so they read like a person's; I've set it to one minute for the video. Pointing this at Jumpstart's inbox is a credentials change."

**7. Architecture (30s).**
"The engine decides, n8n moves the email, Resend sends it. All the logic lives in a repo with a policy file ops can edit and 16 safety tests. Gmail to Outlook, or Slack to Teams, is one node."

**8. 10x (60s), terminal then the 510 vs 5,100 tab.**
Run `python3 eval/scale_test.py`. "5,100 emails in under 2 seconds. Person time about 5 hours a week, against 340 by hand. Critical emails are the floor, and they're mostly a few startup-level decisions applied many times. Missing facts: 12 in week one, zero in week two. Under £100 a month in software. Gmail caps sending at 500 a day, which is why replies go through Resend: 50,000 a month for $20."

**9. Honesty (30s), How it works tab.**
"The rules were written from these emails, so the accuracy is in-sample. On 24 emails written to break it, it passed 23 first time, and I fixed the miss. The number I'd trust is a blind relabel of fresh emails, and the repo has the tool for it."

**10. Beyond the inbox (60s), Results, "most of these emails shouldn't exist".**
"At 10x the clogged inbox is solved. But the emails are symptoms. 37% are candidates asking where they stand: that's an application tracker with automatic updates, plus response targets for startups. 22% are questions the product should answer. 15% is email hygiene, including an unsubscribe ignored for a month that's now an ICO threat. And candidates found the video outage before our monitoring did. Fixing those removes about half the inbound before any automation. Then there's startup conduct: unpaid trials and discriminatory questions need a code of conduct, not better email."

**11. Next (15s).**
"Connect the candidate database, collect startup facts at onboarding, and promote categories to automatic only once they've earned it."
