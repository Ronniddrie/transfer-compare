# Bank Transactions Automation — Architecture

**Goal.** Halifax transactions land in `Banking Transactions Live.xlsm` automatically, categorised, without Ronnie touching anything. Manual Halifax CSV download stays working as a fallback.

**Runs on.** Mac Mini M4 Pro (already always-on, purchased March 2026).

**Uses.** Ronnie's existing Claude Max subscription — no additional paid APIs, no OpenClaw, no Claude Managed Agents session fees.

---

## Layers

### 1. Data source — Enable Banking personal tier
- Free for personal use, covers Halifax (Lloyds Banking Group).
- Why not GoCardless Bank Account Data: new signups disabled since July 2025.
- Why not TrueLayer/Plaid/Yapily: commercial contracts only, not viable for one person's current account.
- PSD2 requires 90-day consent renewal — unavoidable, one browser flow every 90 days. Automation reminds Ronnie 7 days before expiry.

### 2. Polling — launchd on the Mac Mini
- `com.niddrie.bank-poll.plist` triggers `fetch_halifax.py` every 10 minutes.
- `fetch_halifax.py` is dumb on purpose: hit API, fetch transactions since last successful run, write a timestamped delta CSV to `automation/inbox/`. No AI in this layer — just a plain Python API client. If it fails, it fails cleanly, logs, and tries again in 10 minutes.
- State file (`automation/state.json`) tracks the last successful cursor/timestamp so we never miss or duplicate a transaction.

### 3. Brain — Claude Code scheduled task
- Second launchd entry (or Claude Code's native scheduler, v2.1.72+) fires every 15 minutes.
- Invokes Claude Code with a prompt that says: "Check `automation/inbox/` for new delta CSVs. For each one, use the bank-transactions skill to append to the workbook (preserving slicers), then auto-categorise Column F, then move the CSV to `automation/processed/`."
- Runs under the Max subscription — no API bill.
- If the .xlsm is locked (Excel has it open), Claude logs "locked, retry next cycle" and exits cleanly. Next run picks it up.

### 4. Workbook writes — existing bank-transactions skill
- XML-surgery flow that preserves the four Table Slicers (Year/Month/Category/Type).
- **Mandatory** backup to `automation/backups/YYYY-MM-DD_HHMMSS.xlsm` before every write.
- Append-only — never modifies existing rows.

### 5. Categorisation
- Claude categorises new rows using the existing category list + historical patterns from the workbook.
- Rows where Claude's confidence is low get written with category `REVIEW` and flagged in the run log.
- Weekly (Sunday 09:00) Claude sends a Telegram summary: "3 transactions need review this week."

### 6. Re-consent reminder
- State file tracks the consent expiry date.
- 7 days before expiry, Claude sends a Telegram message with a direct link to the Enable Banking re-consent flow.
- Until Ronnie completes the re-auth, `fetch_halifax.py` logs "consent expired" and the CSV fallback path remains available.

### 7. CSV fallback (unchanged)
- Ronnie can still drop a manually-downloaded Halifax CSV into `automation/inbox/` at any time.
- The same scheduled Claude brain picks it up — it doesn't care whether the CSV came from the API or from a browser download, same skill handles both.
- This path is deliberately preserved so the automation never becomes a single point of failure.

---

## Folder layout

```
Bank Transactions/
├── Banking Transactions Live.xlsm         ← the workbook (unchanged)
├── bank-transactions.skill                     ← existing skill (unchanged)
├── ...existing files...
└── automation/
    ├── docs/
    │   ├── ARCHITECTURE.md                     ← this file
    │   └── SETUP.md                            ← step-by-step setup for Mac Mini
    ├── scripts/
    │   ├── fetch_halifax.py                    ← Enable Banking poller
    │   ├── reauth_reminder.py                  ← 90-day consent check
    │   └── com.niddrie.bank-poll.plist         ← launchd job definition
    ├── inbox/                                  ← delta CSVs waiting to be processed
    ├── processed/                              ← CSVs after Claude has merged them
    ├── backups/                                ← timestamped .xlsm copies
    ├── logs/                                   ← run logs, one file per day
    ├── state.json                              ← last cursor + consent expiry
    └── .env                                    ← Enable Banking API creds (gitignored)
```

---

## Explicit non-goals

- **No writing to Excel while it's open.** Claude waits.
- **No touching historical rows.** Append only.
- **No touching the slicers.** XML-surgery flow from bank-transactions skill only.
- **No cloud dependency beyond Enable Banking.** No GitHub Actions, no VPS, no webhooks from the internet into the house.
- **No pensions.** Separate project (`Pensions Dashboard/`).
- **No trading actions.** Read-only access to Halifax, always.

---

## Cost

| Item | Cost |
|---|---|
| Enable Banking personal tier | £0 |
| Claude Max subscription (already paid) | £0 incremental |
| Mac Mini electricity | pennies |
| **Total ongoing** | **£0** |

One-off setup: ~half a day of Ronnie-time, mostly waiting for Enable Banking signup and running through the Halifax consent flow once.
