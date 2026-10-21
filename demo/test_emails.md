# Demo emails

Send each from your own email address to the demo inbox, one at a time. Subject and body as written.
With `DEMO_DELAY=1`, automatic replies arrive about a minute later, from onboarding@resend.dev. Critical acknowledgements arrive straight away. Check spam the first time.

| # | Subject | Body | Expected | Result |
|---|---|---|---|---|
| 1 | Quick question about my profile | Hi! How do I change my headline? Also, when I open my CV it shows someone called Rachel Green's CV instead, with her phone number and address on it. | **Person, critical.** Slack alert with brief. Acknowledgement in your inbox immediately. No how-to answer. | |
| 2 | Video upload | My intro video won't upload, it just gets stuck at 90%. | **Automatic.** Reply about the known outage, about a minute later. | |
| 3 | Offer from Quillstack | Quillstack have offered me the Account Executive role and want an answer by 5pm tomorrow. Should I accept or wait for Brindle? | **Person, talent partner.** Slack alert with the deadline. | |
| 4 | Visa | Can I see roles that offer visa sponsorship? | **Person, missing fact.** Slack alert with an "Answer once" link. Open it, type: There isn't a sponsorship filter yet, but these startups have told us they sponsor visas. Save. | |
| 4b | Visa again | Do any of the startups sponsor Skilled Worker visas? | **Automatic,** using the fact you just saved. | |
| 5 | Any update? | Hi, any news from Copperleaf? It's been a week since my interview. | **Automatic.** Holding reply with a follow-up date. | |
| 6 | Stop | Please stop sending me emails. | **Automatic.** Confirmation, and you're suppressed from marketing. | |
| 7 | Thanks | Thanks so much for the help last week! | **Automatic.** One-line close-the-loop reply. | |

Live moment for the Loom, using the n8n test form (open the form URL from the "Live test form" node):
| L | Privacy | My phone number and CV are showing up on Google when I search my name. | **Person, critical.** | |

After the emails: open the "Review and send" link in the Slack alert for email 1, edit the reply, click Send reply, and check it arrives in your inbox. Then run the reminder node by hand to see "N emails need you today" in Slack.

To reset the facts database after the demo: restore `config/facts.json` from the zip (the "Answer once" page writes to it).
