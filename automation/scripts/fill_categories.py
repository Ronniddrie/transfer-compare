#!/usr/bin/env python3
"""
fill_categories.py — Fill blank Category cells (column F) in
`Banking Transactions Live.xlsm` using XML surgery.

Strategy (three tiers, applied in order):
  1. Explicit rules — hardcoded substring→category mappings.
  2. Exact match — description matches a previously categorised row exactly.
  3. Partial match — a known keyword from column E appears inside the description.

If none match, the cell is left blank (Ronnie's preference).

Usage:
    python3 fill_categories.py              # fill blanks in the live workbook
    python3 fill_categories.py --dry-run    # preview what would be filled
    python3 fill_categories.py --stats      # show learning map stats only

NEVER USE openpyxl ON THIS WORKBOOK — it strips the slicers.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import logging
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
AUTOMATION_DIR = SCRIPT_DIR.parent
BANK_DIR = AUTOMATION_DIR.parent
WORKBOOK = BANK_DIR / "Banking Transactions Live.xlsm"
BACKUPS = AUTOMATION_DIR / "backups"
LOGS = AUTOMATION_DIR / "logs"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGS.mkdir(parents=True, exist_ok=True)
log_file = LOGS / f"fill_cat_{dt.datetime.now():%Y%m%d_%H%M%S}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("fill_categories")


# ---------------------------------------------------------------------------
# Explicit category rules (substring in description → category)
# Order matters: first match wins.
# ---------------------------------------------------------------------------
EXPLICIT_RULES: list[tuple[list[str], str]] = [
    # People / standing orders
    (["ALANA"], "Alana"),
    (["ADAM NIDDRIE"], "Adam"),
    # Food shopping
    (["TESCO", "ASDA", "MORRISONS", "MARKS&SPENCER", "CO-OP", "SAINSBURYS", "ALDI", "LIDL"], "Food Shopping"),
    # Subscriptions / entertainment
    (["APPLE.COM/BILL", "ITUNES.COM/BILL"], "Apple Hardware"),
    (["SKY DIGITAL", "SKY TV"], "Sky TV"),
    (["NETFLIX"], "Netflix"),
    (["PRIME VIDEO", "AMAZON PRIME"], "Prime Video"),
    (["SPOTIFY"], "Spotify"),
    (["TV LICENCE", "TV LICENSING"], "TV Licence"),
    # Shopping — all Amazon entries under one category
    (["AMAZON"], "Amazon"),  # catches Amazon, Amazon Shopping, Amazon Prime, Amazon Music, etc.
    (["NEXT ", "JACAMO"], "Next"),
    (["B & Q", "B&Q"], "DIY"),
    # Lotto
    (["POSTCODE LOTTERY", "ALLWYN ENT LTD"], "Lotto"),
    # Dining
    (["LA CIGALE"], "La Cigale"),
]


# Normalize variant category names to a single canonical name
CATEGORY_NORMALIZE: dict[str, str] = {
    "Amazon Shopping": "Amazon",
    "Amazon Music": "Amazon",
    "Amazon Prime": "Amazon",
}


def xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


# ---------------------------------------------------------------------------
# Build learning map from existing categorised rows
# ---------------------------------------------------------------------------
def build_learning_map(workbook: Path) -> dict[str, str]:
    """Scan every row in sheet2 where column F has a value.
    Return {UPPER(description): most_common_category} for entries with count >= 2."""

    with zipfile.ZipFile(workbook) as zf:
        sh = zf.read("xl/worksheets/sheet2.xml").decode("utf-8")
        try:
            ss_xml = zf.read("xl/sharedStrings.xml").decode("utf-8")
        except KeyError:
            ss_xml = ""

    # Parse shared strings
    sstrs: list[str] = []
    for si in re.findall(r"<si>(.*?)</si>", ss_xml, re.DOTALL):
        m = re.search(r"<t[^>]*>(.*?)</t>", si, re.DOTALL)
        sstrs.append(html.unescape(m.group(1)) if m else "")

    def resolve_cell(col: str, row_xml: str) -> str:
        """Extract text value from a cell in a row. Handles shared strings,
        inline strings, and formula-generated string values."""
        # Inline string: <c r="E123" ...><is><t>TEXT</t></is></c>
        m = re.search(rf'<c r="{col}\d+"[^>]*?t="inlineStr"[^>]*?>.*?<is><t[^>]*?>(.*?)</t></is>', row_xml, re.DOTALL)
        if m:
            return html.unescape(m.group(1))

        # Shared string: <c r="E123" ... t="s"><v>INDEX</v></c>
        m = re.search(rf'<c r="{col}\d+"[^>]*?t="s"[^>]*?><v>(\d+)</v>', row_xml)
        if m:
            idx = int(m.group(1))
            if 0 <= idx < len(sstrs):
                return sstrs[idx]
            return ""

        # Formula-generated string: <c r="E123" ... t="str"><f>...</f><v>VALUE</v></c>
        m = re.search(rf'<c r="{col}\d+"[^>]*?t="str"[^>]*?>.*?<v>(.*?)</v>', row_xml, re.DOTALL)
        if m:
            return html.unescape(m.group(1))

        return ""

    # Scan rows: collect (description, category) pairs
    desc_cat: dict[str, list[str]] = collections.defaultdict(list)
    for rn, rc in re.findall(r'<row r="(\d+)"[^>]*>(.*?)</row>', sh, re.DOTALL):
        if rn == "1":
            continue
        desc = resolve_cell("E", rc).strip()
        cat = resolve_cell("F", rc).strip()
        if desc and cat:
            desc_cat[desc.upper()].append(cat)

    # Build map: keep most common category where count >= 2
    learning_map: dict[str, str] = {}
    for desc_upper, cats in desc_cat.items():
        counter = collections.Counter(cats)
        top_cat, top_count = counter.most_common(1)[0]
        if top_count >= 2:
            learning_map[desc_upper] = top_cat

    return learning_map


# ---------------------------------------------------------------------------
# Category assignment logic
# ---------------------------------------------------------------------------
def assign_category(desc: str, learning_map: dict[str, str]) -> str | None:
    """Return the category for a description, or None if no confident match."""
    desc_upper = desc.strip().upper()
    if not desc_upper:
        return None

    # Tier 0: Explicit rules (substring match)
    for substrings, category in EXPLICIT_RULES:
        for sub in substrings:
            if sub in desc_upper:
                return category

    # Tier 1: Exact match against learning map
    if desc_upper in learning_map:
        return learning_map[desc_upper]

    # Tier 2: Partial match — check if any learned description appears
    # inside this description, or if this description appears inside
    # a learned one. Longest match wins to avoid false positives.
    best_match: str | None = None
    best_len = 0
    for known_desc, category in learning_map.items():
        if len(known_desc) < 4:
            continue  # skip very short keys to avoid false positives
        if known_desc in desc_upper or desc_upper in known_desc:
            if len(known_desc) > best_len:
                best_len = len(known_desc)
                best_match = category

    if best_match:
        return CATEGORY_NORMALIZE.get(best_match, best_match)
    return None


# ---------------------------------------------------------------------------
# Find blank F cells and fill them
# ---------------------------------------------------------------------------
def find_blank_f_rows(sheet_xml: str, sstrs: list[str]) -> list[tuple[int, str, str]]:
    """Return [(row_num, description, row_xml_match)] for rows with no F cell."""
    results = []
    for m in re.finditer(r'<row r="(\d+)"[^>]*>(.*?)</row>', sheet_xml, re.DOTALL):
        rn = int(m.group(1))
        rc = m.group(2)
        if rn == 1:
            continue

        # Check if F cell already exists
        if re.search(rf'<c r="F{rn}"', rc):
            continue

        # Check row has data (has an A cell with a value)
        if not re.search(r'<c r="A\d+"[^>]*><v>\d+</v>', rc):
            continue

        # Get description from E
        desc = ""
        em = re.search(r'<c r="E\d+"[^>]*?t="inlineStr"[^>]*?>.*?<is><t[^>]*?>(.*?)</t></is>', rc, re.DOTALL)
        if em:
            desc = html.unescape(em.group(1))
        else:
            em = re.search(r'<c r="E\d+"[^>]*?t="s"[^>]*?><v>(\d+)</v>', rc)
            if em:
                idx = int(em.group(1))
                if 0 <= idx < len(sstrs):
                    desc = sstrs[idx]

        if desc:
            results.append((rn, desc, m.group(0)))

    return results


def fill_categories_in_xml(sheet_xml: str, sstrs: list[str], learning_map: dict[str, str],
                           dry_run: bool = False) -> tuple[str, int, dict[str, int]]:
    """Fill blank F cells. Returns (new_xml, count_filled, {category: count})."""
    blank_rows = find_blank_f_rows(sheet_xml, sstrs)
    log.info("Found %d rows with blank Category column", len(blank_rows))

    fills: list[tuple[int, str, str, str]] = []  # (row_num, desc, category, old_row_xml)
    cat_counts: dict[str, int] = collections.defaultdict(int)

    for row_num, desc, row_xml in blank_rows:
        category = assign_category(desc, learning_map)
        if category:
            fills.append((row_num, desc, category, row_xml))
            cat_counts[category] += 1

    log.info("Will fill %d of %d blank rows (%d left blank)",
             len(fills), len(blank_rows), len(blank_rows) - len(fills))

    if dry_run:
        log.info("--- Dry run preview (first 20) ---")
        for row_num, desc, category, _ in fills[:20]:
            log.info("  Row %d: %s -> %s", row_num, desc[:40], category)
        if len(fills) > 20:
            log.info("  ... and %d more", len(fills) - 20)
        return sheet_xml, len(fills), dict(cat_counts)

    # Apply fills: insert F cell into each row's XML
    new_xml = sheet_xml
    for row_num, desc, category, old_row_xml in fills:
        # Build F cell as inline string
        f_cell = f'<c r="F{row_num}" s="3" t="inlineStr"><is><t>{xml_escape(category)}</t></is></c>'

        # Insert F cell after E cell (or after D if no E)
        # Find position after the last cell before G
        insert_after = None
        for col in ["E", "D", "C", "B", "A"]:
            pat = re.search(rf'<c r="{col}{row_num}"[^>]*?(?:/>|>.*?</c>)', old_row_xml, re.DOTALL)
            if pat:
                insert_after = pat
                break

        if insert_after:
            new_row_xml = (
                old_row_xml[:insert_after.end()] +
                f_cell +
                old_row_xml[insert_after.end():]
            )
            new_xml = new_xml.replace(old_row_xml, new_row_xml, 1)
            # Update old_row_xml reference for any subsequent rows
            # (not needed since we replace in the full XML, not iteratively)

    # Verify no duplicate F cells were created
    dupes = re.findall(r'<c r="F(\d+)"', new_xml)
    dupe_counts = collections.Counter(dupes)
    bad = {rn: c for rn, c in dupe_counts.items() if c > 1}
    if bad:
        log.error("DUPLICATE F cells detected in rows: %s — aborting!", bad)
        raise RuntimeError(f"Duplicate F cells: {bad}")

    return new_xml, len(fills), dict(cat_counts)


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------
def run_fill(dry_run: bool = False, stats_only: bool = False) -> int:
    """Fill categories. Returns count of cells filled (0 if dry_run/stats_only)."""
    if not WORKBOOK.exists():
        log.error("Workbook not found: %s", WORKBOOK)
        return 0

    log.info("Building learning map from existing categories...")
    learning_map = build_learning_map(WORKBOOK)
    log.info("Learning map: %d unique description->category mappings", len(learning_map))

    if stats_only:
        # Show top categories in the learning map
        cat_summary: dict[str, int] = collections.defaultdict(int)
        for cat in learning_map.values():
            cat_summary[cat] += 1
        log.info("--- Learning map categories (by # of distinct descriptions) ---")
        for cat, count in sorted(cat_summary.items(), key=lambda x: -x[1])[:30]:
            log.info("  %-25s %d descriptions", cat, count)
        return 0

    # Read the workbook
    with zipfile.ZipFile(WORKBOOK) as zf:
        sheet_xml = zf.read("xl/worksheets/sheet2.xml").decode("utf-8")
        try:
            ss_xml = zf.read("xl/sharedStrings.xml").decode("utf-8")
        except KeyError:
            ss_xml = ""

    # Parse shared strings
    sstrs: list[str] = []
    for si in re.findall(r"<si>(.*?)</si>", ss_xml, re.DOTALL):
        m = re.search(r"<t[^>]*>(.*?)</t>", si, re.DOTALL)
        sstrs.append(html.unescape(m.group(1)) if m else "")

    # Fill categories
    new_xml, count, cat_counts = fill_categories_in_xml(sheet_xml, sstrs, learning_map, dry_run)

    if dry_run:
        log.info("--- Category breakdown ---")
        for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
            log.info("  %-25s %d rows", cat, cnt)
        return count

    if count == 0:
        log.info("No blank rows to fill — all categories are up to date.")
        return 0

    # Back up before writing
    BACKUPS.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dest = BACKUPS / f"Banking Transactions Live.{ts}.xlsm"
    shutil.copy2(WORKBOOK, backup_dest)
    log.info("Backed up workbook -> %s", backup_dest.name)

    # Repack with updated sheet2.xml
    with tempfile.TemporaryDirectory(prefix="xlsm_catfill_") as td:
        workdir = Path(td)
        with zipfile.ZipFile(WORKBOOK, "r") as zf:
            zf.extractall(workdir)

        sheet_path = workdir / "xl" / "worksheets" / "sheet2.xml"
        sheet_path.write_text(new_xml, encoding="utf-8")

        # Remove calcChain to avoid repair dialog
        calc = workdir / "xl" / "calcChain.xml"
        if calc.exists():
            calc.unlink()
        ct_path = workdir / "[Content_Types].xml"
        if ct_path.exists():
            ct = ct_path.read_text(encoding="utf-8")
            ct = re.sub(r'<Override PartName="/xl/calcChain\.xml"[^/]*/>', "", ct)
            ct_path.write_text(ct, encoding="utf-8")
        rels_path = workdir / "xl" / "_rels" / "workbook.xml.rels"
        if rels_path.exists():
            rels = rels_path.read_text(encoding="utf-8")
            rels = re.sub(r'<Relationship[^/]*Target="calcChain\.xml"[^/]*/>', "", rels)
            rels_path.write_text(rels, encoding="utf-8")

        # Repack
        tmp_out = WORKBOOK.with_suffix(WORKBOOK.suffix + ".tmp")
        with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(workdir.rglob("*")):
                if p.is_file():
                    arc = p.relative_to(workdir).as_posix()
                    zf.write(p, arc)
        tmp_out.replace(WORKBOOK)

    log.info("Filled %d category cells:", count)
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        log.info("  %-25s %d rows", cat, cnt)

    return count


def main() -> int:
    ap = argparse.ArgumentParser(description="Fill blank Category cells in the bank workbook")
    ap.add_argument("--dry-run", action="store_true", help="Preview what would be filled")
    ap.add_argument("--stats", action="store_true", help="Show learning map stats only")
    args = ap.parse_args()

    run_fill(dry_run=args.dry_run, stats_only=args.stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
