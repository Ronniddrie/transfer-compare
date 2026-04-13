#!/bin/bash
# rebuild_bankimport.sh — Rebuild BankImport.app with Platypus CLI
# Ensures drag-and-drop onto the app window works for CSV files.
#
# Run this from Terminal:
#   bash "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/Claude/Projects/Bank Transactions/automation/scripts/rebuild_bankimport.sh"

set -euo pipefail

BANK_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/Claude/Projects/Bank Transactions"
SCRIPTS="$BANK_DIR/automation/scripts"
SCRIPT_SRC="$SCRIPTS/platypus_script"
ICON_SRC="/Applications/BankImport.app/Contents/Resources/AppIcon.icns"
APP_DEST="/Applications/BankImport.app"

# --- Locate the Platypus command-line tool ---
PLATYPUS_CLI=""
for candidate in \
    "/usr/local/bin/platypus" \
    "/opt/homebrew/bin/platypus" \
    "/Applications/Platypus.app/Contents/Resources/platypus_clt"; do
    if [ -x "$candidate" ]; then
        PLATYPUS_CLI="$candidate"
        break
    fi
done

if [ -z "$PLATYPUS_CLI" ]; then
    echo "ERROR: Platypus command-line tool not found."
    echo "Open Platypus.app → Preferences → Install the command-line tool."
    exit 1
fi
echo "Using Platypus CLI: $PLATYPUS_CLI"

# --- Verify source script exists ---
if [ ! -f "$SCRIPT_SRC" ]; then
    echo "ERROR: Script not found at $SCRIPT_SRC"
    exit 1
fi

# --- Back up existing icon before overwriting ---
ICON_FLAG=""
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "/tmp/BankImport_AppIcon.icns"
    ICON_FLAG="--app-icon /tmp/BankImport_AppIcon.icns"
    echo "Backed up existing icon."
fi

# --- Remove existing app (Platypus --overwrite) ---
if [ -d "$APP_DEST" ]; then
    echo "Removing existing $APP_DEST ..."
    rm -rf "$APP_DEST"
fi

# --- Build the app ---
echo "Building BankImport.app ..."
$PLATYPUS_CLI \
    --name 'BankImport' \
    --interface-type 'Web View' \
    --interpreter '/bin/bash' \
    $ICON_FLAG \
    --bundle-identifier 'org.ronaldniddrie.BankImport' \
    --author 'ronald niddrie' \
    --app-version '2.0' \
    --droppable \
    --suffixes 'csv CSV' \
    --uniform-type-identifiers 'public.comma-separated-values-text public.item' \
    --remains-running \
    --overwrite \
    "$SCRIPT_SRC" \
    "$APP_DEST"

RESULT=$?
if [ $RESULT -ne 0 ]; then
    echo "ERROR: Platypus build failed (exit $RESULT)"
    exit $RESULT
fi

# --- Restore the custom icon ---
if [ -f "/tmp/BankImport_AppIcon.icns" ]; then
    cp "/tmp/BankImport_AppIcon.icns" "$APP_DEST/Contents/Resources/AppIcon.icns"
    echo "Restored custom icon."
fi

# --- Force LaunchServices to re-register the app ---
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_DEST" 2>/dev/null || true

echo ""
echo "✅ BankImport.app rebuilt successfully at $APP_DEST"
echo "   Interface: Web View + Droppable (CSV files)"
echo "   You can now drag CSV files onto the app window or dock icon."
echo ""
echo "Try it: open the app, then drag a .csv file onto the window."
