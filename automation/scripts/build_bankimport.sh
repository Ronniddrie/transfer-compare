#!/bin/bash
# build_bankimport.sh — Compile the native Swift BankImport app
# This replaces the Platypus version with a native app that properly
# supports drag-and-drop of CSV files onto the window.
set -euo pipefail

BANK_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/Documents/Claude/Projects/Bank Transactions"
SCRIPTS="$BANK_DIR/automation/scripts"
SWIFT_SRC="$SCRIPTS/BankImportApp.swift"
APP_DEST="/Applications/BankImport.app"
BINARY_NAME="BankImport"

echo "========================================"
echo "Building native BankImport.app"
echo "========================================"

# --- Check for Swift compiler ---
if ! command -v swiftc &>/dev/null; then
    echo "ERROR: swiftc not found. Install Xcode Command Line Tools:"
    echo "  xcode-select --install"
    exit 1
fi

# --- Back up existing icon ---
ICON_SRC="$APP_DEST/Contents/Resources/AppIcon.icns"
ICON_BACKUP="/tmp/BankImport_AppIcon.icns"
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$ICON_BACKUP"
    echo "  Backed up existing icon."
fi

# --- Remove existing app ---
if [ -d "$APP_DEST" ]; then
    rm -rf "$APP_DEST"
    echo "  Removed old app."
fi

# --- Create app bundle structure ---
echo "  Creating app bundle..."
mkdir -p "$APP_DEST/Contents/MacOS"
mkdir -p "$APP_DEST/Contents/Resources"

# --- Compile Swift ---
echo "  Compiling Swift (this may take a moment)..."
swiftc \
    -O \
    -framework Cocoa \
    -framework WebKit \
    -o "$APP_DEST/Contents/MacOS/$BINARY_NAME" \
    "$SWIFT_SRC"

echo "  Compiled successfully."

# --- Write Info.plist ---
cat > "$APP_DEST/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleDisplayName</key>
    <string>BankImport</string>
    <key>CFBundleDocumentTypes</key>
    <array>
        <dict>
            <key>CFBundleTypeExtensions</key>
            <array>
                <string>csv</string>
                <string>CSV</string>
            </array>
            <key>CFBundleTypeName</key>
            <string>CSV Document</string>
            <key>CFBundleTypeRole</key>
            <string>Editor</string>
            <key>LSItemContentTypes</key>
            <array>
                <string>public.comma-separated-values-text</string>
                <string>public.item</string>
            </array>
        </dict>
    </array>
    <key>CFBundleExecutable</key>
    <string>BankImport</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIconName</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>org.ronaldniddrie.BankImport</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>BankImport</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>3.0</string>
    <key>CFBundleVersion</key>
    <string>3</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsArbitraryLoads</key>
        <true/>
    </dict>
    <key>NSHumanReadableCopyright</key>
    <string>© 2026 Ronald Niddrie</string>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

echo "  Wrote Info.plist."

# --- Restore icon ---
if [ -f "$ICON_BACKUP" ]; then
    cp "$ICON_BACKUP" "$APP_DEST/Contents/Resources/AppIcon.icns"
    echo "  Restored custom icon."
fi

# --- Remove quarantine & re-register ---
xattr -cr "$APP_DEST" 2>/dev/null || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_DEST" 2>/dev/null || true

echo ""
echo "========================================"
echo "  BankImport.app built successfully!"
echo "  Version: 3.0 (native Swift)"
echo "  Location: $APP_DEST"
echo ""
echo "  Features:"
echo "  - Drag CSV files onto the window"
echo "  - Drop CSV on dock icon"
echo "  - Right-click CSV > Open With > BankImport"
echo "  - Dashboard auto-reloads after import"
echo "========================================"
echo ""
echo "Opening BankImport..."
open "$APP_DEST"
