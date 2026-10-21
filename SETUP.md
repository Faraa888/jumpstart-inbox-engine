# Setup: getting the inbox engine running live

Two parts. Part A is sign-ups (about 20 min, do now). Part B is wiring it up on your laptop with Claude Code (about 40 min, after the final build arrives).

---

## Part A: sign-ups and installs

Keep a note open called `keys.txt` on your desktop. Paste each key or password into it as you go. Never put it in the repo.

### 1. A demo inbox (a label in your own Gmail), 5 min
The engine only reads the Gmail label `Jumpstart Demo`, never your inbox.
1. Demo address: `faraazanjum.consulting+jumpstart@gmail.com`. Mail to it arrives in your Gmail.
2. Gmail > search bar options (sliders icon) > To: `faraazanjum.consulting+jumpstart@gmail.com` > Create filter > tick Skip the Inbox, Apply the label > New label `Jumpstart Demo` > Create filter.
3. Gmail > Settings > See all settings > Forwarding and POP/IMAP > Enable IMAP > Save.
4. myaccount.google.com > Security > 2-Step Verification on. Then search "App passwords" > name `n8n` > Create. Copy the 16 characters into `keys.txt`. Delete it after the demo.
5. Test: email the demo address from your live.co.uk account. It should appear under the `Jumpstart Demo` label, not in your inbox.

### 2. Slack, 5 min
1. Create a free workspace at slack.com, for example `Jumpstart Ops Demo`.
2. Create a channel `#talent-ops`.
3. Go to api.slack.com/apps > Create New App > From scratch. Name it `Inbox Engine` and pick the workspace.
4. In the app: Incoming Webhooks > switch on > Add New Webhook to Workspace > choose `#talent-ops` > Allow.
5. Copy the webhook URL (starts `https://hooks.slack.com/services/...`) into `keys.txt`.

### 3. Resend (sends the replies), 5 min
Gmail caps sending at about 500 a day; Resend Pro sends 50,000 a month, which is what makes 10x work.
1. Sign up at resend.com **with your live.co.uk address**. Without a verified domain, Resend only delivers to the account's own email, so this must be the address you send test emails from.
2. API Keys > Create API Key > name `inbox-engine`, permission "Sending access" > Create. Copy the key (starts `re_`) into `keys.txt`.

### 4. Anthropic API key, 5 min
This makes the reviewer agent real rather than mocked.
1. Sign up at console.anthropic.com.
2. Billing: add the minimum credit (about $5 covers the demo many times over).
3. API Keys > Create Key, name `inbox-engine`. Copy it into `keys.txt` (starts `sk-ant-`).

### 5. GitHub, 3 min
1. Sign up or sign in at github.com.
2. Create a new public repository called `jumpstart-inbox-engine`. Leave it empty (no README).

### 6. Installs on your laptop, 5 min
Check in a terminal:
- `python3 --version`: needs 3.10 or newer.
- `node --version`: needs 20 or newer. If missing or older, install the LTS from nodejs.org.
- Claude Code: installed and signed in.
- Loom: desktop app installed and signed in.

When Part A is done, `keys.txt` should hold: Gmail app password, Slack webhook URL, Resend API key, Anthropic API key.

---

## Part B: wiring it up with Claude Code

Why this is a separate step: the engine is built and tested in the cloud, but the live demo has to run on your laptop, signed into your own Gmail and Slack. Nobody else can sign in for you. This part is setup plus an end-to-end test.

### What runs where

```
Your own email (as candidate)
      | email
      v
Demo inbox (Gmail) --IMAP--> n8n (localhost:5678) --HTTP--> engine (localhost:8080)
                                  |                              |
                                  | <------- decision -----------+
                                  |
          +-----------------------+------------------------+
          v                       v                        v
   wait 5-30 min,          Slack #talent-ops         silent: logged only
   reply via Resend        brief + agents' reasoning
                           + "Review and send" link
```

### Do this
1. Unzip `inbox-engine.zip` into a folder, for example `~/jumpstart-inbox-engine`.
2. Open a terminal in that folder and start Claude Code (`claude`).
3. Paste the prompt below, then paste in your keys when it asks.

### Prompt to paste into Claude Code

```
This folder is a Python inbox triage engine plus an n8n workflow. Read README.md and SETUP.md first.
Get the live demo running on this laptop, step by step. Stop and ask me whenever you need a key or a click in a browser.

1. Copy .env.example to .env. I'll paste in ANTHROPIC_API_KEY. Check .env is in .gitignore.
2. Run: python3 run.py, python3 tests/test_invariants.py, python3 eval/score.py, python3 eval/scale_test.py,
   python3 build_console.py. All must pass.
3. In its own terminal, start the engine: python3 serve.py. Check http://localhost:8080 returns ok, then open
   http://localhost:8080/console in my browser (it should say it's waiting for email).
4. In another terminal, start n8n: npx n8n. Tell me when to open http://localhost:5678 and create the owner account.
5. Walk me through: Workflows > Import from file > n8n/inbox_engine.workflow.json. Then create two credentials:
   - IMAP: imap.gmail.com, port 993, SSL on, user faraazanjum.consulting@gmail.com, password = Gmail app password.
     Attach it to "New email in demo inbox" (it reads the Gmail label "Jumpstart Demo").
   - Header Auth, named "Resend API key": Name = Authorization, Value = Bearer <my Resend key>.
     Attach it to the three "(Resend)" nodes.
   In the three Slack nodes ("Post to Slack #talent-ops", "Post reminder to Slack", "Post summary to Slack")
   replace PASTE_SLACK_WEBHOOK_URL with my Slack webhook URL.
   If n8n complains about any node's version or fields, fix the node in the editor and tell me what changed.
6. In Gmail, open the "Jumpstart Demo" label and mark everything there as read. Then activate the workflow.
7. Replay test: python3 replay.py --limit 20. Check 20 executions in n8n, Slack alerts in #talent-ops, the console
   filling, and the summary message in Slack. Then the full run: python3 replay.py (about 2 minutes).
8. Live test: I'll send the emails in demo/test_emails.md from my live.co.uk address to
   faraazanjum.consulting+jumpstart@gmail.com. For each, check the n8n execution, Slack, the console and my inbox,
   and fill in the Result column. For one Slack alert, open its "Review and send" link, edit, Send, and check the
   reply arrives. Run the "9am and 3pm" reminder node once by hand and check Slack.
9. If anything fails, fix it, re-run the tests, and tell me what you changed.
Do not commit or push anything. Keys only go in .env or in n8n credentials, never in other files.
```

### What "done" looks like
- Every test email in `demo/test_emails.md` gives the expected result. With `DEMO_DELAY=1` in `.env`, automatic replies arrive about a minute later instead of 5 to 30.
- Critical emails hit Slack within seconds, with the brief.
- `python3 eval/scale_test.py` prints the 10x run.

Then Step 4 (push to GitHub, console on GitHub Pages) and Step 5 (Loom, then email Bethan).
