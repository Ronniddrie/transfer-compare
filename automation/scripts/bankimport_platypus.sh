#!/bin/bash
# Wrapper script for BankImport.app (Platypus Web View + Droppable).
#
# On launch: outputs the dashboard HTML to stdout — Platypus renders it.
# On drop:   receives dropped file paths as $@ — imports any CSVs, then
#            outputs the refreshed dashboard.
#
# Platypus calls this script each time the app is launched OR files are
# dropped on the icon/window. Whatever it prints to stdout becomes the
# web view's content.

set -u

BANK_DIR="/Users/ronaldniddrie/Library/Mobile Documents/com~apple~CloudDocs/Documents/Claude/Projects/Bank Transactions"
RUN_APPEND="$BANK_DIR/automation/scripts/run_append.sh"
DASHBOARD="$BANK_DIR/bank_dashboard.html"
LOG="$BANK_DIR/automation/bankimport_platypus.log"

{
    echo "----"
    date "+%Y-%m-%d %H:%M:%S"
    echo "args: $*"
} >> "$LOG"

# Process any dropped files — the append script handles CSV validation,
# XML surgery, the sort macro, and the dashboard rebuild.
for f in "$@"; do
    case "$f" in
        *.csv|*.CSV)
            "$RUN_APPEND" --csv "$f" >> "$LOG" 2>&1 || echo "  import FAILED for $f" >> "$LOG"
            ;;
        *)
            echo "  skipping non-CSV: $f" >> "$LOG"
            ;;
    esac
done

# Always emit the (possibly updated) dashboard.
if [ -f "$DASHBOARD" ]; then
    cat "$DASHBOARD"
else
    cat <<EOF
<!doctype html>
<html><head><meta charset="utf-8"><title>BankImport</title>
<style>body{font-family:-apple-system,sans-serif;background:#0f1420;color:#e6e9f2;padding:40px}</style>
</head><body>
<h1>Dashboard not found</h1>
<p>Expected <code>$DASHBOARD</code> — run <code>rebuild_dashboard.py</code> first.</p>
</body></html>
EOF
fi
