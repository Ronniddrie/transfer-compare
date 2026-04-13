#!/usr/bin/env python3
"""
fix_bankimport_drops.py — Fix BankImport.app drag-and-drop support.

Strategy:
1. Try to rebuild with Platypus CLI (best fix — fresh binary with proper drop handling)
2. If CLI unavailable, patch the Info.plist to add CSV extensions and re-register

Run:  python3 "path/to/fix_bankimport_drops.py"
"""

import plistlib
import subprocess
import shutil
import os
import sys

APP_PATH = "/Applications/BankImport.app"
PLIST_PATH = os.path.join(APP_PATH, "Contents", "Info.plist")
ICON_PATH = os.path.join(APP_PATH, "Contents", "Resources", "AppIcon.icns")
BANK_DIR = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Claude/Projects/Bank Transactions"
)
SCRIPT_SRC = os.path.join(BANK_DIR, "automation", "scripts", "platypus_script")
LSREGISTER = (
    "/System/Library/Frameworks/CoreServices.framework"
    "/Frameworks/LaunchServices.framework/Support/lsregister"
)

def find_platypus_cli():
    """Find the Platypus command-line tool."""
    candidates = [
        "/usr/local/bin/platypus",
        "/opt/homebrew/bin/platypus",
        os.path.expanduser("~/bin/platypus"),
    ]
    # Also check inside Platypus.app bundle
    for app_loc in ["/Applications/Platypus.app", os.path.expanduser("~/Applications/Platypus.app")]:
        candidates.append(os.path.join(app_loc, "Contents", "Resources", "platypus_clt"))

    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def rebuild_with_cli(cli_path):
    """Rebuild BankImport.app from scratch using the Platypus CLI."""
    print(f"  Using Platypus CLI: {cli_path}")

    if not os.path.isfile(SCRIPT_SRC):
        print(f"  ERROR: Script not found at {SCRIPT_SRC}")
        return False

    # Back up existing icon
    icon_backup = "/tmp/BankImport_AppIcon.icns"
    if os.path.isfile(ICON_PATH):
        shutil.copy2(ICON_PATH, icon_backup)
        print("  Backed up custom icon.")

    # Remove existing app
    if os.path.isdir(APP_PATH):
        shutil.rmtree(APP_PATH)
        print("  Removed existing app.")

    # Build
    cmd = [
        cli_path,
        "--name", "BankImport",
        "--interface-type", "Web View",
        "--interpreter", "/bin/bash",
        "--bundle-identifier", "org.ronaldniddrie.BankImport",
        "--author", "ronald niddrie",
        "--app-version", "2.0",
        "--droppable",
        "--suffixes", "csv CSV",
        "--uniform-type-identifiers", "public.comma-separated-values-text public.item",
        "--remains-running",
        "--overwrite",
        SCRIPT_SRC,
        APP_PATH,
    ]
    if os.path.isfile(icon_backup):
        cmd.insert(-2, "--app-icon")
        cmd.insert(-2, icon_backup)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Platypus build failed: {result.stderr}")
        return False

    # Restore custom icon (in case Platypus didn't use it)
    if os.path.isfile(icon_backup):
        dest_icon = os.path.join(APP_PATH, "Contents", "Resources", "AppIcon.icns")
        shutil.copy2(icon_backup, dest_icon)
        print("  Restored custom icon.")

    print("  App rebuilt successfully.")
    return True


def patch_plist():
    """Patch the existing Info.plist to add CSV file type extensions."""
    if not os.path.isfile(PLIST_PATH):
        print(f"  ERROR: Info.plist not found at {PLIST_PATH}")
        return False

    # Back up
    backup = PLIST_PATH + ".bak"
    shutil.copy2(PLIST_PATH, backup)
    print(f"  Backed up Info.plist to {backup}")

    with open(PLIST_PATH, "rb") as f:
        plist = plistlib.load(f)

    # Fix CFBundleDocumentTypes — add CSV extensions
    doc_types = plist.get("CFBundleDocumentTypes", [])
    if doc_types:
        dt = doc_types[0]
        # Add file extensions
        dt["CFBundleTypeExtensions"] = ["csv", "CSV"]
        # Ensure content types include CSV
        uti_list = dt.get("LSItemContentTypes", [])
        if "public.comma-separated-values-text" not in uti_list:
            uti_list.append("public.comma-separated-values-text")
        dt["LSItemContentTypes"] = uti_list
        dt["CFBundleTypeRole"] = "Editor"  # Editor allows drops better than Viewer
    else:
        # Create document types from scratch
        plist["CFBundleDocumentTypes"] = [{
            "CFBundleTypeExtensions": ["csv", "CSV"],
            "CFBundleTypeRole": "Editor",
            "LSItemContentTypes": [
                "public.comma-separated-values-text",
                "public.item",
                "public.folder",
            ],
        }]

    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(plist, f, fmt=plistlib.FMT_BINARY)

    print("  Patched Info.plist with CSV extensions.")
    return True


def remove_quarantine():
    """Remove macOS quarantine extended attribute."""
    try:
        subprocess.run(
            ["xattr", "-cr", APP_PATH],
            capture_output=True, check=False
        )
        print("  Removed quarantine attributes.")
    except Exception as e:
        print(f"  Warning: Could not remove quarantine: {e}")


def reregister_with_launchservices():
    """Force LaunchServices to re-read the app's document types."""
    try:
        subprocess.run(
            [LSREGISTER, "-f", APP_PATH],
            capture_output=True, check=False
        )
        print("  Re-registered with LaunchServices.")
    except Exception as e:
        print(f"  Warning: Could not re-register: {e}")


def touch_app():
    """Touch the app to invalidate icon caches."""
    try:
        subprocess.run(["touch", APP_PATH], check=False)
    except:
        pass


def main():
    print("=" * 60)
    print("BankImport.app — Drag-and-Drop Fix")
    print("=" * 60)

    if not os.path.isdir(APP_PATH):
        print(f"\nERROR: {APP_PATH} not found.")
        sys.exit(1)

    # Step 1: Try full rebuild with Platypus CLI
    cli = find_platypus_cli()
    if cli:
        print(f"\n[1/3] Rebuilding app with Platypus CLI...")
        if rebuild_with_cli(cli):
            print("\n[2/3] Removing quarantine...")
            remove_quarantine()
            print("\n[3/3] Re-registering with LaunchServices...")
            reregister_with_launchservices()
            touch_app()
            print("\n" + "=" * 60)
            print("DONE — Full rebuild complete.")
            print("Open BankImport and try dragging a CSV onto the window.")
            print("=" * 60)
            return
        else:
            print("  Rebuild failed. Falling back to plist patch...")

    # Step 2: Fallback — patch the plist
    print(f"\n[1/3] Patching Info.plist (Platypus CLI not found)...")
    if not patch_plist():
        print("ERROR: Could not patch Info.plist")
        sys.exit(1)

    print("\n[2/3] Removing quarantine...")
    remove_quarantine()

    print("\n[3/3] Re-registering with LaunchServices...")
    reregister_with_launchservices()
    touch_app()

    print("\n" + "=" * 60)
    print("DONE — Plist patched with CSV extensions.")
    print("")
    print("NOTE: For best results, install the Platypus command-line")
    print("tool: open Platypus.app > Preferences > Install CLI Tool,")
    print("then re-run this script for a full rebuild.")
    print("")
    print("For now, try:")
    print("  - Dragging a CSV onto the app DOCK ICON (should work)")
    print("  - Dragging a CSV onto the app WINDOW (may need rebuild)")
    print("=" * 60)


if __name__ == "__main__":
    main()
