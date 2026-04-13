#!/usr/bin/env python3
"""
fetch_halifax.py — Enable Banking poller for Ronnie's Halifax automation.

WHAT IT DOES
  1. On first run (or when consent has expired), starts the Enable Banking
     consent flow: opens the Halifax (sandbox) authorisation URL in your
     browser, listens on http://localhost:8765/callback for the auth code,
     exchanges it for a session, and saves the session_id + expiry.
  2. On every run, fetches new Halifax transactions since the last cursor,
     writes them as a delta CSV into ../inbox/, updates ../state.json.
  3. Never writes to the .xlsm. That's Claude Code's job, downstream.
  4. If called with --dry-run, does everything except write the CSV or
     update state.json. Use this on first run to verify auth works.

INVOCATION
  ./venv/bin/python fetch_halifax.py          # real run
  ./venv/bin/python fetch_halifax.py --dry-run
  ./venv/bin/python fetch_halifax.py --consent  # force new consent flow

ENVIRONMENT (in ../.env, loaded automatically)
  ENABLE_BANKING_APP_ID      = 2c12fbfa-0d98-4945-9b5a-177dcca7f116
  ENABLE_BANKING_KEY_PATH    = /absolute/path/to/sandbox_private_key.pem
  ENABLE_BANKING_ENV         = sandbox | production
  ENABLE_BANKING_COUNTRY     = GB
  ENABLE_BANKING_ASPSP_NAME  = Halifax          # or "Mock ASPSP" for first test
  ENABLE_BANKING_REDIRECT    = http://localhost:8765/callback

DEPENDS ON
  requests, PyJWT, cryptography, python-dotenv
  (install with: pip install -r requirements.txt)
"""

from __future__ import annotations

import argparse
import csv
import http.server
import json
import os
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import requests
from dotenv import load_dotenv

# ---------- paths ----------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent          # automation/
STATE_PATH = PROJECT_DIR / "state.json"
INBOX_DIR = PROJECT_DIR / "inbox"
LOG_DIR = PROJECT_DIR / "logs"
ENV_PATH = PROJECT_DIR / ".env"

INBOX_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(ENV_PATH)

# ---------- config ----------

API_BASE = "https://api.enablebanking.com"
APP_ID = os.environ.get("ENABLE_BANKING_APP_ID", "").strip()
KEY_PATH = os.environ.get("ENABLE_BANKING_KEY_PATH", "").strip()
ENVIRONMENT = os.environ.get("ENABLE_BANKING_ENV", "sandbox").strip().lower()
COUNTRY = os.environ.get("ENABLE_BANKING_COUNTRY", "GB").strip().upper()
ASPSP_NAME = os.environ.get("ENABLE_BANKING_ASPSP_NAME", "Halifax").strip()
REDIRECT_URI = os.environ.get(
    "ENABLE_BANKING_REDIRECT", "http://localhost:8765/callback"
).strip()

# ---------- logging ----------


def log(msg: str, level: str = "INFO") -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp} [{level}] {msg}"
    print(line, flush=True)
    day = datetime.now().strftime("%Y-%m-%d")
    with open(LOG_DIR / f"{day}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def die(msg: str, code: int = 1) -> None:
    log(msg, "ERROR")
    sys.exit(code)


# ---------- state ----------


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {
            "session_id": None,
            "session_expires": None,
            "consent_expires": None,
            "last_cursor": None,   # ISO date — "fetch tx after this"
            "last_successful_run": None,
            "account_ids": [],
        }
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    tmp.replace(STATE_PATH)


# ---------- JWT ----------


def make_jwt(ttl_seconds: int = 3600) -> str:
    """
    Enable Banking auth: RS256 signed JWT, kid header = application_id,
    iss = enablebanking.com, aud = api.enablebanking.com.
    Sent as Authorization: Bearer <jwt>. Max TTL 86400s.
    """
    if not APP_ID:
        die("ENABLE_BANKING_APP_ID is not set in .env")
    if not KEY_PATH or not Path(KEY_PATH).exists():
        die(f"Private key not found at ENABLE_BANKING_KEY_PATH={KEY_PATH}")

    with open(KEY_PATH, "rb") as f:
        private_key = f.read()

    now = int(time.time())
    payload = {
        "iss": "enablebanking.com",
        "aud": "api.enablebanking.com",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    headers = {"kid": APP_ID, "typ": "JWT"}
    token = jwt.encode(payload, private_key, algorithm="RS256", headers=headers)
    # PyJWT < 2 returns bytes, >= 2 returns str
    return token if isinstance(token, str) else token.decode("utf-8")


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {make_jwt()}"}


# ---------- API helpers ----------


def api_get(path: str, params: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    r = requests.get(url, headers=auth_headers(), params=params, timeout=30)
    if not r.ok:
        die(f"GET {path} → {r.status_code} {r.text[:400]}")
    return r.json()


def api_post(path: str, body: dict) -> dict:
    url = f"{API_BASE}{path}"
    r = requests.post(url, headers=auth_headers(), json=body, timeout=30)
    if not r.ok:
        die(f"POST {path} → {r.status_code} {r.text[:400]}")
    return r.json()


# ---------- consent flow ----------


def find_halifax_aspsp() -> dict:
    """
    Fetch the list of ASPSPs and locate the Halifax one matching the
    configured environment. In sandbox, Enable Banking exposes both real
    bank sandboxes and a generic 'Mock ASPSP'. We match on name and country.
    """
    log(f"Listing ASPSPs for country={COUNTRY} env={ENVIRONMENT}")
    data = api_get("/aspsps", params={"country": COUNTRY})
    candidates = data.get("aspsps") or data.get("data") or []
    if not candidates:
        die(f"No ASPSPs returned for country={COUNTRY}. Response: {data!r:.300}")

    for a in candidates:
        name = (a.get("name") or "").lower()
        if ASPSP_NAME.lower() in name:
            log(f"Matched ASPSP: {a.get('name')} ({a.get('country')})")
            return a

    # Fallback: log available names so Ronnie can see what to set
    available = ", ".join(sorted({a.get("name", "?") for a in candidates}))
    die(
        f"ASPSP '{ASPSP_NAME}' not found in country={COUNTRY}. "
        f"Available: {available}. "
        f"Set ENABLE_BANKING_ASPSP_NAME in .env to one of those."
    )
    return {}  # unreachable


class CallbackCapture:
    """Tiny one-shot HTTP server that captures ?code=... from the redirect."""

    def __init__(self, port: int = 8765):
        self.port = port
        self.code: str | None = None
        self.state: str | None = None
        self.error: str | None = None

    def run(self, timeout_seconds: int = 300) -> None:
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a, **k):
                pass  # silence default noise

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                outer.code = (params.get("code") or [None])[0]
                outer.state = (params.get("state") or [None])[0]
                outer.error = (params.get("error") or [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                body = (
                    "<html><body style='font-family:sans-serif;padding:40px'>"
                    "<h2>Consent captured.</h2>"
                    "<p>You can close this tab and return to the terminal.</p>"
                    "</body></html>"
                )
                self.wfile.write(body.encode("utf-8"))

        with socketserver.TCPServer(("127.0.0.1", self.port), Handler) as httpd:
            httpd.timeout = 1
            deadline = time.time() + timeout_seconds
            while self.code is None and self.error is None:
                if time.time() > deadline:
                    die(f"Consent flow timed out after {timeout_seconds}s")
                httpd.handle_request()


def start_consent_flow(state: dict) -> None:
    aspsp = find_halifax_aspsp()

    log("Starting authorization session")
    now = datetime.now(timezone.utc)
    body = {
        "access": {
            "valid_until": (now + timedelta(days=90)).isoformat().replace("+00:00", "Z")
        },
        "aspsp": {"name": aspsp["name"], "country": aspsp["country"]},
        "state": "niddrie",
        "redirect_url": REDIRECT_URI,
        "psu_type": "personal",
    }
    resp = api_post("/auth", body)
    url = resp.get("url") or resp.get("authorization_url")
    if not url:
        die(f"/auth did not return a consent URL. Full response: {resp!r:.400}")

    log(f"Opening browser: {url}")
    print("\n=== ACTION REQUIRED ===")
    print("A browser window is opening for you to authorise Halifax sandbox access.")
    print("If it doesn't open automatically, copy this URL into a browser:\n")
    print(f"  {url}\n")
    print("After you complete the sandbox consent, control will return here.\n")

    capture = CallbackCapture(port=8765)
    server_thread = threading.Thread(target=capture.run, kwargs={"timeout_seconds": 300})
    server_thread.start()
    time.sleep(0.5)  # let server bind before opening browser
    webbrowser.open(url)
    server_thread.join()

    if capture.error:
        die(f"Consent returned an error: {capture.error}")
    if not capture.code:
        die("No auth code captured from redirect")

    log("Exchanging auth code for session")
    session_resp = api_post("/sessions", {"code": capture.code})
    session_id = session_resp.get("session_id") or session_resp.get("id")
    accounts = session_resp.get("accounts") or []
    if not session_id:
        die(f"/sessions did not return session_id. Response: {session_resp!r:.400}")

    state["session_id"] = session_id
    state["session_expires"] = (
        (datetime.now(timezone.utc) + timedelta(days=90)).isoformat().replace("+00:00", "Z")
    )
    state["consent_expires"] = state["session_expires"]
    state["account_ids"] = [a.get("uid") or a.get("id") for a in accounts if a]
    log(
        f"Consent complete. session_id={session_id[:8]}... "
        f"accounts={len(state['account_ids'])} expires={state['session_expires']}"
    )


# ---------- transaction fetch ----------


def fetch_transactions_for_account(account_id: str, date_from: str) -> list[dict]:
    """Fetch all transactions for one account from date_from to today, paginated."""
    all_tx: list[dict] = []
    continuation = None
    while True:
        params: dict = {
            "date_from": date_from,
            "date_to": datetime.now(timezone.utc).date().isoformat(),
        }
        if continuation:
            params["continuation_key"] = continuation
        data = api_get(f"/accounts/{account_id}/transactions", params=params)
        page = data.get("transactions") or []
        all_tx.extend(page)
        continuation = data.get("continuation_key")
        if not continuation:
            break
    return all_tx


def write_delta_csv(transactions: list[dict]) -> Path:
    """
    Write a delta CSV in a shape the bank-transactions skill already understands.
    Halifax CSV headers historically: Date, Transaction Type, Sort Code, Account
    Number, Transaction Description, Debit Amount, Credit Amount, Balance.
    We normalise Enable Banking's JSON into those columns.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = INBOX_DIR / f"halifax_delta_{stamp}.csv"

    cols = [
        "Date",
        "Transaction Type",
        "Sort Code",
        "Account Number",
        "Transaction Description",
        "Debit Amount",
        "Credit Amount",
        "Balance",
    ]

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for t in transactions:
            # Enable Banking field names vary slightly by ASPSP — be defensive.
            booking = t.get("booking_date") or t.get("value_date") or ""
            amount = t.get("transaction_amount", {}).get("amount") or t.get("amount") or "0"
            try:
                amt = float(amount)
            except (TypeError, ValueError):
                amt = 0.0
            debit = f"{-amt:.2f}" if amt < 0 else ""
            credit = f"{amt:.2f}" if amt > 0 else ""
            desc = (
                t.get("remittance_information")
                or t.get("creditor", {}).get("name")
                or t.get("debtor", {}).get("name")
                or t.get("description")
                or ""
            )
            if isinstance(desc, list):
                desc = " ".join(str(x) for x in desc)
            ttype = t.get("credit_debit_indicator") or t.get("bank_transaction_code") or ""
            w.writerow([booking, ttype, "", "", desc, debit, credit, ""])

    return out_path


# ---------- main ----------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="fetch but don't write CSV or state")
    parser.add_argument("--consent", action="store_true", help="force new consent flow")
    args = parser.parse_args()

    log(f"fetch_halifax starting (dry_run={args.dry_run}, force_consent={args.consent})")
    state = load_state()

    # Decide whether we need to run the consent flow
    need_consent = args.consent or not state.get("session_id")
    if state.get("session_expires"):
        try:
            expiry = datetime.fromisoformat(state["session_expires"].replace("Z", "+00:00"))
            if expiry < datetime.now(timezone.utc):
                log("Session expired — new consent required")
                need_consent = True
        except Exception:
            need_consent = True

    if need_consent:
        start_consent_flow(state)

    if not state.get("account_ids"):
        die("No account IDs in state after consent. Re-run with --consent.")

    # Determine window
    if state.get("last_cursor"):
        date_from = state["last_cursor"]
    else:
        # First run: pull last 90 days so we have something to test with
        date_from = (datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat()
    log(f"Fetching transactions since {date_from}")

    all_new: list[dict] = []
    for account_id in state["account_ids"]:
        log(f"  account {account_id[:8]}...")
        txs = fetch_transactions_for_account(account_id, date_from)
        log(f"    {len(txs)} transactions")
        all_new.extend(txs)

    if not all_new:
        log("No new transactions.")
        if not args.dry_run:
            state["last_successful_run"] = datetime.now(timezone.utc).isoformat()
            save_state(state)
        return 0

    if args.dry_run:
        log(f"Dry run — would write {len(all_new)} transactions to inbox")
        sample = all_new[0]
        log(f"Sample tx keys: {sorted(sample.keys())}")
        log(f"Sample tx: {json.dumps(sample, indent=2)[:1000]}")
        return 0

    out = write_delta_csv(all_new)
    log(f"Wrote {len(all_new)} transactions to {out.name}")

    state["last_cursor"] = datetime.now(timezone.utc).date().isoformat()
    state["last_successful_run"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("Interrupted", "WARN")
        sys.exit(130)
    except Exception as e:
        log(f"Unhandled exception: {e}", "ERROR")
        raise
