#!/bin/bash
# Triggered by launchd WatchPaths whenever the local BankImport inbox changes.
# Imports any CSVs found, moves them to Inbox/Processed/, then rebuilds the dashboard.
#
# NOTE: This script is COPIED to ~/Library/Application Support/BankImport/
# by install_launchd.command. macOS TCC blocks launchd from executing scripts
# stored inside iCloud Drive, so the runtime copy MUST live in a non-iCloud
# location. The copy in iCloud is the source-of-truth for re-installation.
#
# TCC WORKAROUND: run_append.sh and venv/python are ALSO in iCloud and TCC
# would block child-bash reads of them. So we skip the wrapper entirely and
# invoke Homebrew python3.11 directly on append_csv.py. FDA must be granted
# to the Python.app bundle at:
#   /opt/homebrew/Cellar/python@3.11/3.11.6/Frameworks/Python.framework/Versions/3.11/Resources/Python.app
# The /opt/homebrew/opt/python@3.11/bin/python3.11 symlink below resolves
# to the binary inside that .app, so the FDA grant applies.
set -u

# Local (non-iCloud, not TCC-protected)
APP_SUPPORT="$HOME/Library/Application Support/BankImport"
INBOX="$APP_SUPPORT/Inbox"
PROCESSED="$INBOX/Processed"
LOG="$APP_SUPPORT/inbox_handler.log"

# iCloud (workbook + python scripts live here, synced across Macs)
BANK_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/Claude/Projects/Bank Transactions"
APPEND_CSV="$BANK_DIR/automation/scripts/append_csv.py"

# Homebrew python3.11 — FDA is granted to the Python.app inside its framework.
PYTHON="/opt/homebrew/opt/python@3.11/bin/python3.11"

mkdir -p "$PROCESSED"

{
    echo "===="
    date "+%Y-%m-%d %H:%M:%S"
} >> "$LOG"

shopt -s nullglob nocaseglob
csvs=("$INBOX"/*.csv)
shopt -u nocaseglob

if [ "${#csvs[@]}" -eq 0 ]; then
    echo "  no CSVs in inbox — nothing to do" >> "$LOG"
    exit 0
fi

for f in "${csvs[@]}"; do
    echo "  processing: $f" >> "$LOG"
    # append_csv.py handles: backup, append, sort-macro, dashboard rebuild.
    if "$PYTHON" "$APPEND_CSV" --csv "$f" >> "$LOG" 2>&1; then
        ts=$(date "+%Y%m%d-%H%M%S")
        base=$(basename "$f")
        mv "$f" "$PROCESSED/${ts}__${base}"
        echo "  ok -> moved to Processed/${ts}__${base}" >> "$LOG"
    else
        echo "  FAILED for $f (left in inbox)" >> "$LOG"
    fi
done
