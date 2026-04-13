#!/bin/bash
set -e
sed -i '' 's|COUNTRY=GB|COUNTRY=FI|' ../.env
cat ../.env | grep -E 'COUNTRY|ASPSP'
./venv/bin/python fetch_halifax.py --dry-run
