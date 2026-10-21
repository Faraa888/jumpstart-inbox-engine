# Beyond the inbox: what to fix next

The engine clears the inbox at today's volume and at 10x. But most of these emails shouldn't exist. They're symptoms of a handful of gaps in the product and the process. At 10x, the cheapest email to answer is the one that's never sent.

Counts are from the 510 emails. "Could remove" is my estimate, to validate.

| # | Root cause | Evidence in the 510 | What to build | Could remove |
|---|---|---|---|---|
| 1 | Candidates can't see where they stand | 190 emails (37%): 99 chasing a startup, 62 asking about an application, 29 asking for feedback | **Application tracker**: every application shows its stage, when it last moved and what happens next, plus an automatic email whenever it changes, and a nudge to the startup when it stalls | about 130 |
| 2 | Startups don't reply on time | Chases cluster: Fennel Labs 15, Nimbleway 12, Quillstack, Pinecart and Kestrel Labs 11 each. Driftwell ghosting after final rounds | **Startup response targets and a scorecard**: agreed reply times by stage, automatic reminders, a response-time score that affects how candidates are matched to them | follows from 1 |
| 3 | No line on startup conduct | Driftwell asking for unpaid two-week trials; Saltmarsh asking about age and family plans; Pinecart withdrawing an offer after the candidate resigned | **Startup code of conduct** signed at onboarding, a candidate report button, and a clear process to pause a startup | few emails, high risk |
| 4 | Answers that should be self-serve | 111 emails (22%): 48 how-to and account changes, 48 general questions (20 about the intro video), 15 interview prep | **Help centre and in-app profile editing**, a short video guide, an interview prep hub | about 65 |
| 5 | Bugs found by candidates, not by us | 42 emails (8%): 31 about one video upload outage, apply button failing on mobile, a listing hidden by a startup | **Error monitoring and a status page**: the outage should page engineering before the first email, and candidates should see "known issue, fix due" in the product | about 35 |
| 6 | Email hygiene and privacy | 74 emails (15%): 31 unsubscribes (one ignored for a month, now an ICO threat), 34 auto-replies, 6 deletion requests, a subject access request, and another candidate's CV and address shown to the wrong person | **Preference centre with one-click unsubscribe** that actually works, mailing-list hygiene, self-service data requests, and a fix and audit for the CV mix-up | about 50 |
| 7 | Matching gaps | 36 emails (7%): no visa sponsorship filter, location, salary and remote filters, irrelevant streams, zero matches | **Filters and match-quality alerts** in the product; the engine already counts every request for the product team | about 15 |
| 8 | Offers handled ad hoc | 5 live offers with deadlines, 1 withdrawn offer, 4 placements announced by email | **Offer support playbook** owned by talent partners: deadline tracking, a negotiation guide, a policy for withdrawn offers | few emails, high value |

**Together that's roughly half the inbound gone before any automation.** At 10x that means about 2,500 fewer emails a week, and the engine handles the rest.

## The order I'd do it

1. **Now:** the engine (this build), the unsubscribe fix, and the CV mix-up audit. The last two are legal exposure.
2. **Next 3 months:** the application tracker plus startup response targets. This is the biggest single cut in volume, and it also makes the candidate experience better.
3. **Then:** help centre and in-app editing, monitoring and a status page, the startup code of conduct.
4. **Ongoing:** the engine's counts feed product priorities every week, so the inbox becomes a source of product insight rather than a cost.
