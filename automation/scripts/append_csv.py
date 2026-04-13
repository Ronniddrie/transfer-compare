#!/usr/bin/env python3
"""
append_csv.py — Append new Halifax CSV transactions into
`Banking Transactions Live.xlsm` using XML surgery, preserving
all four Table Slicers (Year / Month / Category / Type).

Follows the bank-transactions skill workflow exactly:
  1. Back up the .xlsm before touching it.
  2. Parse the CSV (Halifax format).
  3. Unzip the .xlsm to a working dir.
  4. Patch xl/worksheets/sheet2.xml — append <row> elements, move the
     totals row, update <dimension>.
  5. Patch xl/tables/table1.xml — Table4 ref, autoFilter ref.
  6. Delete xl/calcChain.xml and its two manifest references so Excel
     rebuilds it silently on open.
  7. Repack as a standard deflate zip.
  8. Move processed CSVs to processed/.

Usage:
    ./venv/bin/python append_csv.py                 # scans inbox/
    ./venv/bin/python append_csv.py --csv FILE      # single file
    ./venv/bin/python append_csv.py --dry-run       # plan only, no writes

NEVER USE openpyxl ON THIS WORKBOOK — it strips the slicers.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
AUTOMATION_DIR = SCRIPT_DIR.parent
BANK_DIR = AUTOMATION_DIR.parent
WORKBOOK = BANK_DIR / "Banking Transactions Live.xlsm"
INBOX = AUTOMATION_DIR / "inbox"
PROCESSED = AUTOMATION_DIR / "processed"
BACKUPS = AUTOMATION_DIR / "backups"
LOGS = AUTOMATION_DIR / "logs"

# Excel serial day zero = 1899-12-30 (Lotus 1-2-3 bug-compat)
EXCEL_EPOCH = dt.date(1899, 12, 30)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGS.mkdir(parents=True, exist_ok=True)
log_file = LOGS / f"append_{dt.datetime.now():%Y%m%d_%H%M%S}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("append_csv")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def excel_serial(d: dt.date) -> int:
    return (d - EXCEL_EPOCH).days


def xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def row_key(serial: int, desc: str, debit: float, credit: float, balance: float) -> tuple:
    """Canonical tuple for deduping. Descriptions are unescaped and upper-cased,
    amounts rounded to 2dp."""
    return (
        serial,
        html.unescape(desc).strip().upper(),
        round(debit, 2),
        round(credit, 2),
        round(balance, 2),
    )


def load_existing_keys(workbook: Path) -> set[tuple]:
    """Scan the existing workbook and return a set of row_keys for every data
    row in sheet2. Used to dedupe CSV imports against what's already there."""
    with zipfile.ZipFile(workbook) as zf:
        sh = zf.read("xl/worksheets/sheet2.xml").decode("utf-8")
        try:
            ss_xml = zf.read("xl/sharedStrings.xml").decode("utf-8")
        except KeyError:
            ss_xml = ""

    # Parse shared strings (simple: one <t> inside each <si>)
    sstrs = []
    for si in re.findall(r"<si>(.*?)</si>", ss_xml, re.DOTALL):
        m = re.search(r"<t[^>]*>(.*?)</t>", si, re.DOTALL)
        sstrs.append(m.group(1) if m else "")

    keys: set[tuple] = set()
    for rn, rc in re.findall(r'<row r="(\d+)"[^>]*>(.*?)</row>', sh, re.DOTALL):
        if rn == "1":  # header
            continue
        am = re.search(r'<c r="A\d+"[^>]*><v>(\d+)</v>', rc)
        if not am:
            continue  # totals row has no A value
        serial = int(am.group(1))

        # Description in E: either inline string or shared string ref
        desc = ""
        em = re.search(
            r'<c r="E\d+"[^>]*?>(?:<is><t[^>]*>([^<]*)</t></is>|<v>(\d+)</v>)', rc
        )
        if em:
            if em.group(1) is not None:
                desc = em.group(1)
            elif em.group(2) is not None:
                idx = int(em.group(2))
                if 0 <= idx < len(sstrs):
                    desc = sstrs[idx]

        def numc(col: str) -> float:
            mm = re.search(rf'<c r="{col}\d+"[^>]*?><v>([^<]+)</v>', rc)
            return float(mm.group(1)) if mm else 0.0

        keys.add(row_key(serial, desc, numc("G"), numc("H"), numc("I")))
    return keys


def parse_halifax_csv(path: Path) -> list[dict]:
    """Halifax columns: Transaction Date, Transaction Type, Sort Code,
    Account Number, Transaction Description, Debit Amount, Credit Amount,
    Balance. Date format DD/MM/YYYY."""
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            date_str = (r.get("Transaction Date") or "").strip()
            if not date_str:
                continue
            try:
                d = dt.datetime.strptime(date_str, "%d/%m/%Y").date()
            except ValueError:
                log.warning("Bad date %r in %s — skipping row", date_str, path.name)
                continue

            def num(key: str) -> float:
                v = (r.get(key) or "").strip()
                if not v:
                    return 0.0
                try:
                    return float(v)
                except ValueError:
                    return 0.0

            rows.append(
                {
                    "date": d,
                    "serial": excel_serial(d),
                    "month": d.strftime("%B"),
                    "year": d.year,
                    "type": (r.get("Transaction Type") or "").strip(),
                    "desc": (r.get("Transaction Description") or "").strip(),
                    "debit": num("Debit Amount"),
                    "credit": num("Credit Amount"),
                    "balance": num("Balance"),
                }
            )
    return rows


def build_row_xml(n: int, rec: dict) -> str:
    """Emit one <row> element matching the skill's approved cell patterns.
    Inline strings for text, plain (non-shared) formulas on B/C."""
    parts = [f'<row r="{n}" spans="1:9" x14ac:dyDescent="0.2">']
    parts.append(f'<c r="A{n}" s="2"><v>{rec["serial"]}</v></c>')
    parts.append(
        f'<c r="B{n}" s="2" t="str"><f>TEXT(A{n},"mmmm")</f><v>{rec["month"]}</v></c>'
    )
    parts.append(f'<c r="C{n}" s="3"><f>YEAR(A{n})</f><v>{rec["year"]}</v></c>')
    if rec["type"]:
        parts.append(
            f'<c r="D{n}" s="2" t="inlineStr"><is><t>{xml_escape(rec["type"])}</t></is></c>'
        )
    if rec["desc"]:
        parts.append(
            f'<c r="E{n}" s="2" t="inlineStr"><is><t xml:space="preserve">{xml_escape(rec["desc"])}</t></is></c>'
        )
    # F (Category) left blank — Ronnie's rule: fill later, not on ingest.
    if rec["debit"]:
        parts.append(f'<c r="G{n}" s="4"><v>{rec["debit"]}</v></c>')
    if rec["credit"]:
        parts.append(f'<c r="H{n}" s="4"><v>{rec["credit"]}</v></c>')
    # Balance always present
    parts.append(f'<c r="I{n}" s="4"><v>{rec["balance"]}</v></c>')
    parts.append("</row>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Core workflow
# ---------------------------------------------------------------------------
def backup_workbook() -> Path:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUPS / f"Banking Transactions Live.{ts}.xlsm"
    shutil.copy2(WORKBOOK, dest)
    log.info("Backed up workbook -> %s", dest.name)
    return dest


def check_locks() -> None:
    for lock in BANK_DIR.glob(".~lock*.xlsm#"):
        log.error("Stale lock file present: %s", lock.name)
        log.error("Close Excel and delete the lock before running.")
        sys.exit(2)
    for lock in BANK_DIR.glob("~$*.xlsm"):
        log.error("Office lock file present: %s", lock.name)
        log.error("Close Excel and delete the lock before running.")
        sys.exit(2)


def patch_sheet2(sheet_xml: str, records: list[dict]) -> tuple[str, int, int]:
    """Return (new_xml, first_new_row, new_totals_row)."""
    # Find current totals row (last <row> in sheetData).
    row_matches = list(re.finditer(r'<row r="(\d+)"[^>]*>.*?</row>', sheet_xml, re.DOTALL))
    if not row_matches:
        raise RuntimeError("No rows found in sheet2.xml")

    last_row_match = row_matches[-1]
    last_row_num = int(last_row_match.group(1))
    last_row_xml = last_row_match.group(0)
    log.info("Current last row in sheet2: %d (totals row)", last_row_num)

    # First new data row = last_row_num (overwriting totals spot), then shift totals down.
    first_new = last_row_num
    new_rows_xml = []
    for i, rec in enumerate(records):
        n = first_new + i
        new_rows_xml.append(build_row_xml(n, rec))

    new_totals_num = first_new + len(records)
    # Rewrite totals row with new row number, preserving its inner content.
    totals_inner = re.search(
        r'<row r="\d+"([^>]*)>(.*?)</row>', last_row_xml, re.DOTALL
    )
    if not totals_inner:
        raise RuntimeError("Could not parse totals row")
    attrs = totals_inner.group(1)
    inner = totals_inner.group(2)
    # Renumber cell refs inside totals row: r="A17545" -> r="A{new_totals_num}"
    inner = re.sub(
        r'r="([A-Z]+)' + str(last_row_num) + r'"',
        lambda m: f'r="{m.group(1)}{new_totals_num}"',
        inner,
    )
    # Reset cached SUBTOTAL values to 0 so Excel recalculates on open
    inner = re.sub(r"(<f>SUBTOTAL\([^<]*</f>)<v>[^<]*</v>", r"\1<v>0</v>", inner)
    new_totals_xml = f'<row r="{new_totals_num}"{attrs}>{inner}</row>'

    replacement = "".join(new_rows_xml) + new_totals_xml
    new_xml = sheet_xml[: last_row_match.start()] + replacement + sheet_xml[last_row_match.end() :]

    # Update <dimension ref="...">
    new_xml = re.sub(
        r'<dimension ref="A1:([A-Z]+)\d+"',
        rf'<dimension ref="A1:\g<1>{new_totals_num}"',
        new_xml,
        count=1,
    )

    return new_xml, first_new, new_totals_num


def patch_table1(table_xml: str, new_totals_row: int) -> str:
    autofilter_last = new_totals_row - 1
    table_xml = re.sub(
        r'(name="Table4"[^>]*?ref=")A1:I\d+(")',
        rf'\g<1>A1:I{new_totals_row}\g<2>',
        table_xml,
    )
    table_xml = re.sub(
        r'(<autoFilter ref=")A1:I\d+(")',
        rf'\g<1>A1:I{autofilter_last}\g<2>',
        table_xml,
    )
    return table_xml


def remove_calcchain(workdir: Path) -> None:
    calc = workdir / "xl" / "calcChain.xml"
    if calc.exists():
        calc.unlink()
        log.info("Removed xl/calcChain.xml")

    ct_path = workdir / "[Content_Types].xml"
    if ct_path.exists():
        ct = ct_path.read_text(encoding="utf-8")
        ct = re.sub(
            r'<Override PartName="/xl/calcChain\.xml"[^/]*/>',
            "",
            ct,
        )
        ct_path.write_text(ct, encoding="utf-8")

    rels_path = workdir / "xl" / "_rels" / "workbook.xml.rels"
    if rels_path.exists():
        rels = rels_path.read_text(encoding="utf-8")
        rels = re.sub(
            r'<Relationship[^/]*Target="calcChain\.xml"[^/]*/>',
            "",
            rels,
        )
        rels_path.write_text(rels, encoding="utf-8")


def repack(workdir: Path, dest: Path) -> None:
    tmp_out = dest.with_suffix(dest.suffix + ".tmp")
    with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(workdir.rglob("*")):
            if p.is_file():
                arc = p.relative_to(workdir).as_posix()
                zf.write(p, arc)
    tmp_out.replace(dest)
    log.info("Repacked workbook -> %s", dest.name)


def process_csv(csv_paths: list[Path], dry_run: bool) -> None:
    check_locks()

    all_records: list[dict] = []
    for p in csv_paths:
        recs = parse_halifax_csv(p)
        log.info("%s: %d rows parsed", p.name, len(recs))
        all_records.extend(recs)

    if not all_records:
        log.warning("No records to append. Exiting.")
        return

    # Dedupe against what's already in the workbook
    log.info("Scanning existing workbook for dedup...")
    existing = load_existing_keys(WORKBOOK)
    log.info("Existing rows in workbook: %d", len(existing))

    before = len(all_records)
    deduped: list[dict] = []
    skipped = 0
    for r in all_records:
        k = row_key(serial=r["serial"], desc=r["desc"], debit=r["debit"], credit=r["credit"], balance=r["balance"])
        if k in existing:
            skipped += 1
            continue
        deduped.append(r)
    all_records = deduped
    log.info("Dedupe: %d CSV rows -> %d new (%d already in workbook)", before, len(all_records), skipped)

    if not all_records:
        log.warning("Nothing new to append after dedup. Exiting.")
        return

    # Sort by date ascending so the appended block is chronological
    # (though Ronnie's sheet is not strictly ordered anyway).
    all_records.sort(key=lambda r: r["date"])
    log.info(
        "Total to append: %d rows spanning %s → %s",
        len(all_records),
        all_records[0]["date"],
        all_records[-1]["date"],
    )

    if dry_run:
        log.info("Dry run — not modifying workbook. Sample rows:")
        for r in all_records[:3] + all_records[-3:]:
            log.info(
                "  %s %s £%s £%s bal=%s",
                r["date"],
                r["desc"][:30],
                r["debit"],
                r["credit"],
                r["balance"],
            )
        return

    backup_workbook()

    with tempfile.TemporaryDirectory(prefix="xlsm_append_") as td:
        workdir = Path(td)
        with zipfile.ZipFile(WORKBOOK, "r") as zf:
            zf.extractall(workdir)

        sheet_path = workdir / "xl" / "worksheets" / "sheet2.xml"
        sheet_xml = sheet_path.read_text(encoding="utf-8")
        new_sheet, first_new, new_totals = patch_sheet2(sheet_xml, all_records)
        sheet_path.write_text(new_sheet, encoding="utf-8")
        log.info(
            "sheet2.xml patched: rows %d-%d appended, totals moved to %d",
            first_new,
            first_new + len(all_records) - 1,
            new_totals,
        )

        table_path = workdir / "xl" / "tables" / "table1.xml"
        table_xml = table_path.read_text(encoding="utf-8")
        table_path.write_text(patch_table1(table_xml, new_totals), encoding="utf-8")
        log.info("table1.xml patched: Table4 ref -> A1:I%d", new_totals)

        remove_calcchain(workdir)

        repack(workdir, WORKBOOK)

    # Move processed CSVs out of the inbox
    PROCESSED.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    for p in csv_paths:
        if p.parent == INBOX:
            dest = PROCESSED / f"{ts}_{p.name}"
            shutil.move(str(p), dest)
            log.info("Archived %s -> processed/%s", p.name, dest.name)

    # Fill blank Category cells using the learning map + explicit rules.
    fill_categories()

    # Run the SortByDateDesc VBA macro so new rows jump to the top.
    # Only attempts on macOS; non-fatal if Excel isn't available.
    run_sort_macro()

    # Rebuild the HTML dashboard against the updated workbook.
    rebuild_dashboard()

    log.info("Done. Open the workbook to verify — slicers should be intact.")


# ---------------------------------------------------------------------------
# Category fill
# ---------------------------------------------------------------------------
def fill_categories() -> None:
    """Fill blank Category cells using the learning map + explicit rules.

    Best-effort: logs a warning on failure rather than aborting the run,
    since the workbook itself is already saved at this point.
    """
    try:
        from fill_categories import run_fill
        count = run_fill()
        if count:
            log.info("Category fill: %d cells filled", count)
        else:
            log.info("Category fill: no blank rows to fill")
    except Exception as e:
        log.warning("Category fill failed: %s — fill manually if needed", e)


# ---------------------------------------------------------------------------
# Post-append sort via VBA macro
# ---------------------------------------------------------------------------
def run_sort_macro() -> None:
    """Open the workbook in Excel and run SortAndSave via AppleScript.

    The macro lives in VBAProject(Banking Transactions Live.xlsm) -> module
    SortByDateDesc. It sorts Table4 by Transaction Date descending and saves.

    This is best-effort: on a headless Mac Mini without Excel, or on any
    non-macOS host, the call is skipped with a warning. The XML surgery
    has already succeeded at this point so the workbook is still valid.
    """
    if sys.platform != "darwin":
        log.info("Skipping auto-sort: not running on macOS (%s)", sys.platform)
        return

    if shutil.which("osascript") is None:
        log.info("Skipping auto-sort: osascript not available")
        return

    wb_posix = str(WORKBOOK)
    # AppleScript-escape any embedded quotes/backslashes
    wb_escaped = wb_posix.replace("\\", "\\\\").replace('"', '\\"')

    script = f'''
    tell application "Microsoft Excel"
        activate
        set wb to open workbook workbook file name "{wb_escaped}"
        run VB macro "SortAndSave"
    end tell
    '''

    log.info("Running SortAndSave macro via AppleScript...")
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            log.info("Auto-sort done (Table4 sorted newest-first, workbook saved)")
        else:
            log.warning(
                "Auto-sort AppleScript returned %d: %s",
                result.returncode,
                result.stderr.strip() or result.stdout.strip(),
            )
            log.warning("Workbook is still valid — sort it manually via Alt+F8 -> SortByDateDesc")
    except subprocess.TimeoutExpired:
        log.warning("Auto-sort timed out after 120s — sort manually if needed")
    except Exception as e:  # pragma: no cover — belt and braces
        log.warning("Auto-sort failed: %s — sort manually if needed", e)


# ---------------------------------------------------------------------------
# Dashboard rebuild
# ---------------------------------------------------------------------------
def rebuild_dashboard() -> None:
    """Regenerate bank_dashboard.html from the updated workbook.

    Best-effort: logs a warning on failure rather than aborting the run,
    since the workbook itself is already saved by this point.
    """
    rebuild_script = BANK_DIR / "rebuild_dashboard.py"
    if not rebuild_script.exists():
        log.info("Skipping dashboard rebuild: %s not found", rebuild_script)
        return

    log.info("Rebuilding dashboard...")
    try:
        result = subprocess.run(
            [sys.executable, str(rebuild_script)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(BANK_DIR),
        )
        if result.returncode == 0:
            # Pass through the rebuild script's own summary line
            tail = result.stdout.strip().splitlines()[-1:] if result.stdout else []
            for line in tail:
                log.info("  %s", line)
            log.info("Dashboard rebuilt: %s", BANK_DIR / "bank_dashboard.html")
        else:
            log.warning(
                "Dashboard rebuild returned %d: %s",
                result.returncode,
                result.stderr.strip() or result.stdout.strip(),
            )
    except subprocess.TimeoutExpired:
        log.warning("Dashboard rebuild timed out after 120s")
    except Exception as e:  # pragma: no cover
        log.warning("Dashboard rebuild failed: %s", e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, help="Single CSV to append")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not WORKBOOK.exists():
        log.error("Workbook not found: %s", WORKBOOK)
        return 1

    if args.csv:
        csv_paths = [args.csv]
    else:
        INBOX.mkdir(parents=True, exist_ok=True)
        csv_paths = sorted(INBOX.glob("*.csv"))
        if not csv_paths:
            log.info("Inbox is empty: %s", INBOX)
            return 0

    log.info("Processing %d CSV file(s)", len(csv_paths))
    process_csv(csv_paths, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
