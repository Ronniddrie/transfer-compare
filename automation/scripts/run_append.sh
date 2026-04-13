#!/bin/bash
# Thin wrapper for append_csv.py — activates the venv and processes inbox/.
# Usage:
#   ./run_append.sh              # process everything in ../inbox
#   ./run_append.sh --dry-run    # plan only
#   ./run_append.sh --csv FILE   # process a single file

set -e
cd "$(dirname "$0")"
./venv/bin/python append_csv.py "$@"
