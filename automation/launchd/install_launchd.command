#!/bin/bash
# Double-click this file in Finder to install the BankImport launchd watcher.
#
# What this does:
#   1. Creates ~/Library/Application Support/BankImport/ (outside iCloud)
#   2. Creates ~/Library/Application Support/BankImport/Inbox/ (the watched folder)
#   3. Copies inbox_handler.sh from the iCloud source bundle to that folder
#   4. Writes com.ronaldniddrie.bankimport.plist to ~/Library/LaunchAgents/
#   5. Loads the agent with launchctl
#   6. Migrates any CSVs from the OLD iCloud CSV Inbox to the new local Inbox
#
# Why outside iCloud: macOS TCC blocks user launchd agents from executing
# scripts stored inside iCloud Drive (it's a protected location). Moving the
# handler to ~/Library/Application Support/ bypasses that restriction.
# The Excel workbook and dashboard HTML stay in iCloud so they still sync
# between Macs.
#
# Idempotent — safe to run multiple times. Does not delete anything.

echo "BankImport launchd installer"
echo "============================"
echo ""

# ---- paths ----
SRC_HANDLER="/Users/ronaldniddrie/Library/Mobile Documents/com~apple~CloudDocs/Documents/Claude/Projects/Bank Transactions/automation/scripts/inbox_handler.sh"
OLD_INBOX="/Users/ronaldniddrie/Library/Mobile Documents/com~apple~CloudDocs/Documents/Claude/Projects/Bank Transactions/CSV Inbox"

APP_SUPPORT="$HOME/Library/Application Support/BankImport"
LOCAL_HANDLER="$APP_SUPPORT/inbox_handler.sh"
LOCAL_INBOX="$APP_SUPPORT/Inbox"
LOCAL_PROCESSED="$LOCAL_INBOX/Processed"

LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLIST="$LAUNCH_AGENTS/com.ronaldniddrie.bankimport.plist"
AGENT_LABEL="com.ronaldniddrie.bankimport"

# ---- 1. source handler must exist ----
if [ ! -f "$SRC_HANDLER" ]; then
    echo "ERROR: source handler not found at:"
    echo "  $SRC_HANDLER"
    echo ""
    echo "Press any key to close..."
    read -n 1 -s
    exit 1
fi

# ---- 2. ensure ~/Library/LaunchAgents is a directory ----
if [ -e "$LAUNCH_AGENTS" ] && [ ! -d "$LAUNCH_AGENTS" ]; then
    BACKUP="${LAUNCH_AGENTS}.NOT-A-DIR-$(date +%Y%m%d-%H%M%S)"
    echo "Found a non-directory at $LAUNCH_AGENTS — renaming to:"
    echo "  $BACKUP"
    mv "$LAUNCH_AGENTS" "$BACKUP"
fi
mkdir -p "$LAUNCH_AGENTS"

# ---- 3. create local Application Support folder + Inbox ----
echo "Creating $APP_SUPPORT"
mkdir -p "$APP_SUPPORT"
mkdir -p "$LOCAL_INBOX"
mkdir -p "$LOCAL_PROCESSED"

# ---- 4. copy handler script from iCloud source to local ----
echo "Copying handler to $LOCAL_HANDLER"
cp "$SRC_HANDLER" "$LOCAL_HANDLER"
if [ $? -ne 0 ]; then
    echo "ERROR: failed to copy handler"
    read -n 1 -s
    exit 1
fi
chmod +x "$LOCAL_HANDLER"

# ---- 5. migrate any CSVs from the old iCloud inbox to the new local inbox ----
if [ -d "$OLD_INBOX" ]; then
    shopt -s nullglob nocaseglob
    old_csvs=("$OLD_INBOX"/*.csv)
    shopt -u nocaseglob
    if [ "${#old_csvs[@]}" -gt 0 ]; then
        echo "Migrating ${#old_csvs[@]} CSV(s) from old iCloud inbox to local inbox..."
        for f in "${old_csvs[@]}"; do
            mv "$f" "$LOCAL_INBOX/"
            echo "  moved: $(basename "$f")"
        done
    fi
fi

# ---- 6. unload existing agent if any ----
if launchctl list 2>/dev/null | grep -q "$AGENT_LABEL"; then
    echo "Unloading existing agent..."
    launchctl unload "$PLIST" 2>/dev/null
fi

# ---- 7. write the plist (generated from heredoc so paths can be dynamic) ----
echo "Writing plist to $PLIST"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${AGENT_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${LOCAL_HANDLER}</string>
    </array>

    <key>WatchPaths</key>
    <array>
        <string>${LOCAL_INBOX}</string>
    </array>

    <key>ThrottleInterval</key>
    <integer>5</integer>

    <key>StandardOutPath</key>
    <string>${APP_SUPPORT}/launchd.out.log</string>

    <key>StandardErrorPath</key>
    <string>${APP_SUPPORT}/launchd.err.log</string>
</dict>
</plist>
PLIST_EOF

# ---- 8. load the agent ----
echo "Loading agent with launchctl..."
launchctl load "$PLIST"
LOAD_RC=$?

# ---- 9. verify ----
echo ""
echo "Verifying..."
if launchctl list 2>/dev/null | grep "$AGENT_LABEL"; then
    echo ""
    echo "✅ Installed successfully."
    echo ""
    echo "Local BankImport setup:"
    echo "  Handler: $LOCAL_HANDLER"
    echo "  Inbox:   $LOCAL_INBOX"
    echo "  Logs:    $APP_SUPPORT/inbox_handler.log"
    echo ""
    echo "Drop any Halifax CSV into the local Inbox folder and the import"
    echo "will fire automatically within ~5 seconds."
    echo ""
    echo "If imports fail with permission errors when reading the xlsm,"
    echo "open System Settings → Privacy & Security → Full Disk Access"
    echo "and add: $LOCAL_HANDLER"
else
    echo ""
    echo "⚠ Could not verify agent is loaded (launchctl load rc=$LOAD_RC)"
    echo "  Check: launchctl list | grep $AGENT_LABEL"
fi

echo ""
echo "Press any key to close this window..."
read -n 1 -s
