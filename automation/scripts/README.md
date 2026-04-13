# automation/scripts

Python scripts that run on the Mac Mini (or your hotel laptop for first testing).

## Layout

```
scripts/
├── fetch_halifax.py      # Enable Banking poller — fetches new transactions, writes delta CSVs to ../inbox/
├── requirements.txt      # Python dependencies
└── README.md             # this file
```

## First-time setup (5 minutes)

From whichever Mac you're currently on:

```bash
cd "/path/to/Bank Transactions/automation/scripts"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Then copy the env template and fill it in:

```bash
cp ../.env.example ../.env
# edit ../.env in your text editor — set ENABLE_BANKING_KEY_PATH to the
# absolute path of your .pem file. The app_id is already pre-filled.
```

## First run — smoke test against Mock ASPSP (recommended)

The very first thing to run is a smoke test against Enable Banking's "Mock ASPSP",
which is a fake bank that always works in sandbox. This proves your JWT auth,
consent flow, and transaction parsing all work before we ever touch Halifax.

Edit `../.env` and set:

```
ENABLE_BANKING_ASPSP_NAME=Mock ASPSP
```

Then run:

```bash
./venv/bin/python fetch_halifax.py --dry-run
```

The script will:
1. Sign a JWT with your private key
2. List UK ASPSPs and find the mock one
3. Open your browser to the Enable Banking sandbox consent screen
4. Listen on http://localhost:8765/callback for the redirect
5. Exchange the auth code for a session
6. Fetch the fake transactions
7. Print a sample of what it found, **without writing any CSV or state** (dry run)

If all of that works, paste me the output (the "Sample tx keys" and "Sample tx"
lines especially) and I'll confirm the field mapping is correct.

## Second run — switch to Halifax sandbox

Once the Mock ASPSP smoke test passes, edit `../.env` again:

```
ENABLE_BANKING_ASPSP_NAME=Halifax
```

And run:

```bash
./venv/bin/python fetch_halifax.py --consent
```

`--consent` forces a fresh consent flow (needed because we're switching banks).

After that, the normal command for every future run is just:

```bash
./venv/bin/python fetch_halifax.py
```

## Troubleshooting

- **"ASPSP not found"** — the script prints the list of available banks. Copy the
  exact name into `ENABLE_BANKING_ASPSP_NAME`.
- **JWT 401 / 403** — usually means `ENABLE_BANKING_KEY_PATH` is wrong, or the
  key doesn't match the registered application, or the `kid` header doesn't
  match the `app_id`. Double-check the .env values.
- **"Address already in use" on port 8765** — another process is listening.
  Close Chrome, or change the redirect URL in both the Enable Banking control
  panel AND your .env to a different port.
- **Consent opens but hangs forever** — make sure nothing is blocking
  `http://localhost:8765` in your browser (no VPN redirect, no hosts file
  weirdness).
