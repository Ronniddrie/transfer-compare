# Bank Transactions Automation — Setup Guide

Step-by-step. Follow in order. Each step has a ☑ box so you can track progress.

---

## Phase 1 — Enable Banking signup (~30 minutes, Ronnie only)

This bit I can't do for you — it needs your identity and a real browser session on your own machine.

- [ ] Go to https://enablebanking.com/ and click **Sign up** (developer / personal account).
- [ ] Use `ronniddrie@aol.com` so it ends up in the inbox we already watch.
- [ ] Create an "application" in their dashboard. Name it `NiddrieBankAutomation`. Select **UK** as the region. Select **AIS (Account Information Services)** only — you do NOT need PIS (payments) and we never want write access.
- [ ] Copy the **Application ID** and **API key** / **private key**. Paste them into `automation/.env` on the Mac Mini (template in Phase 2).
- [ ] In the Enable Banking app dashboard, add **Halifax** as a connected institution and run their test connection flow. This will bounce you through the Halifax Open Banking consent screen (SCA via the Halifax app). Confirm transactions come back in their sandbox.
- [ ] Note the **consent expiry date** (90 days from today) and write it in `automation/state.json` (template in Phase 2).

**If Enable Banking won't approve you for personal use** (some providers are picky): tell me which error you see and we'll swap to the closest alternative. The rest of the architecture doesn't change — only the poller script.

---

## Phase 2 — Mac Mini prep (~20 minutes)

- [ ] Make sure Python 3.11+ is installed: `python3 --version`. If not, `brew install python`.
- [ ] `cd` into `Bank Transactions/automation/scripts`.
- [ ] Create a Python virtualenv: `python3 -m venv venv && source venv/bin/activate`.
- [ ] Install dependencies: `pip install requests python-dotenv cryptography`.
- [ ] Create `automation/.env` with:
  ```
  ENABLE_BANKING_APP_ID=...
  ENABLE_BANKING_KEY_PATH=/absolute/path/to/your/private_key.pem
  ENABLE_BANKING_ACCOUNT_ID=...      # filled in after first consent
  TELEGRAM_BOT_TOKEN=...             # reuse the @ronniddriebot one
  TELEGRAM_CHAT_ID=...               # your chat id
  ```
- [ ] Create `automation/state.json`:
  ```json
  {
    "last_cursor": null,
    "consent_expires": "2026-07-10",
    "last_successful_run": null
  }
  ```

---

## Phase 3 — Install the poller (~10 minutes)

- [ ] Copy `fetch_halifax.py` into `automation/scripts/` (I'll write this once Phase 1 is done and we know the exact Enable Banking auth shape — their docs drift).
- [ ] Run it once by hand: `./venv/bin/python fetch_halifax.py --dry-run`. Confirm it logs "would fetch N transactions" without writing anything.
- [ ] Run it for real: `./venv/bin/python fetch_halifax.py`. Check that a delta CSV appears in `automation/inbox/`.

---

## Phase 4 — Schedule it (~10 minutes)

- [ ] Copy `com.niddrie.bank-poll.plist` into `~/Library/LaunchAgents/`.
- [ ] Load it: `launchctl load ~/Library/LaunchAgents/com.niddrie.bank-poll.plist`.
- [ ] Verify it's registered: `launchctl list | grep niddrie`.
- [ ] Wait 15 minutes, then check `automation/logs/` for a fresh run log.

---

## Phase 5 — Wire Claude Code as the brain (~15 minutes)

- [ ] In Claude Code on the Mac Mini, run `/schedule` and create a recurring task titled `Bank Transactions Merge`, interval `every 15 minutes`, prompt:
  > Check `Bank Transactions/automation/inbox/` for any delta CSVs. For each one, use the bank-transactions skill to append rows to the workbook (preserving slicers) and auto-categorise Column F. Move processed CSVs to `automation/processed/`. Log what you did to `automation/logs/YYYY-MM-DD.log`. If the workbook is locked, log "locked" and exit cleanly — next run will retry.
- [ ] Drop a test delta CSV into `automation/inbox/` manually and wait for the next 15-minute tick.
- [ ] Confirm the workbook updated, a backup was created, and the CSV moved to `processed/`.

---

## Phase 6 — Re-consent reminder (~5 minutes)

- [ ] Add a second Claude Code scheduled task titled `Bank Re-consent Check`, interval `daily at 08:00`, prompt:
  > Read `Bank Transactions/automation/state.json`. If `consent_expires` is within 7 days, send me a Telegram message with the Enable Banking re-consent URL and the exact expiry date. Don't send again once reminded today.

---

## Phase 7 — Acceptance test (Ronnie's checklist)

- [ ] Open the Halifax app on your phone and make a small real transaction (e.g. buy a coffee).
- [ ] Wait 10–15 minutes.
- [ ] Check `Banking Transactions Live.xlsm` — the row should be there with a sensible category.
- [ ] Check `automation/logs/` — you should see a clean log entry.
- [ ] Check `automation/backups/` — there should be a fresh timestamped backup.
- [ ] Close the workbook, drop a manually-downloaded CSV into `automation/inbox/`, and confirm the fallback path still works.

Once all seven phases pass, the automation is live and you can forget about it. Which is the whole point.
