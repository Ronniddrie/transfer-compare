#!/bin/bash
set -e
sed -i '' 's|COUNTRY=FI|COUNTRY=GB|' ../.env
sed -i '' 's|ASPSP_NAME=Mock ASPSP|ASPSP_NAME=Halifax|' ../.env
echo "--- .env now set to ---"
grep -E 'COUNTRY|ASPSP' ../.env
echo "------------------------"
./venv/bin/python fetch_halifax.py --dry-run --consent
