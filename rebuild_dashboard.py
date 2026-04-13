#!/usr/bin/env python3
"""
Rebuild the bank_dashboard.html file from Banking Transactions Live.xlsm.

Safe: reads the .xlsm as a zip (no openpyxl), so it will not touch slicers.
Run this any time new transactions are appended.

Usage:
    python3 rebuild_dashboard.py
"""
import zipfile, re, json, sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

HERE = Path(__file__).parent
SRC = HERE / "Banking Transactions Live.xlsm"
OUT = HERE / "bank_dashboard.html"
TEMPLATE = HERE / "bank_dashboard_template.html"

def extract_transactions(xlsm_path: Path):
    with zipfile.ZipFile(xlsm_path) as z:
        sheet = z.read("xl/worksheets/sheet2.xml").decode("utf-8")
        shared = z.read("xl/sharedStrings.xml").decode("utf-8")

    sst_items = re.findall(r"<si>(.*?)</si>", shared, re.DOTALL)
    def _text(si):
        return "".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.DOTALL))
    sst = [_text(s) for s in sst_items]

    rows = re.findall(r'<row r="(\d+)"[^>]*>(.*?)</row>', sheet, re.DOTALL)

    def cell_val(inner, ctype):
        m = re.search(r"<is><t[^>]*>(.*?)</t></is>", inner, re.DOTALL)
        if m:
            return m.group(1)
        m = re.search(r"<v>(.*?)</v>", inner)
        if not m:
            return ""
        v = m.group(1)
        if ctype == "s":
            return sst[int(v)]
        return v

    EPOCH = datetime(1899, 12, 30)
    out = []
    for rn, row_xml in rows:
        if int(rn) == 1:
            continue
        if "SUBTOTAL" in row_xml.upper():
            continue
        cells = re.findall(
            r'<c r="([A-Z]+)(\d+)"([^/>]*?)(?:/>|>(.*?)</c>)', row_xml, re.DOTALL
        )
        rec = {}
        for col, _n, attrs, inner in cells:
            tm = re.search(r't="(\w+)"', attrs)
            ctype = tm.group(1) if tm else "n"
            rec[col] = cell_val(inner or "", ctype)
        date_s = (rec.get("A", "") or "").strip()
        if not date_s:
            continue
        try:
            serial = float(date_s)
        except ValueError:
            continue
        dt = EPOCH + timedelta(days=serial)
        def _f(k):
            try:
                return float(rec.get(k, "0") or 0)
            except ValueError:
                return 0.0
        out.append({
            "d": dt.strftime("%Y-%m-%d"),
            "ty": rec.get("D", ""),
            "ds": rec.get("E", ""),
            "c": (rec.get("F", "") or "").strip() or "Uncategorised",
            "db": round(_f("G"), 2),
            "cr": round(_f("H"), 2),
            "b": round(_f("I"), 2),
        })
    out.sort(key=lambda r: r["d"])
    return out

def main():
    if not SRC.exists():
        print(f"ERROR: workbook not found at {SRC}", file=sys.stderr)
        sys.exit(1)
    if not TEMPLATE.exists():
        print(f"ERROR: template not found at {TEMPLATE}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {SRC.name} ...")
    txns = extract_transactions(SRC)
    print(f"  -> {len(txns):,} transactions")
    if txns:
        print(f"  -> date range: {txns[0]['d']}  ->  {txns[-1]['d']}")
    cats = Counter(t["c"] for t in txns)
    print(f"  -> {len(cats)} categories")

    tpl = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(txns, separators=(",", ":"))
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = tpl.replace("__DATA__", payload).replace("__GENERATED__", generated)
    OUT.write_text(html, encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT.name} ({size_kb:,.0f} KB)")

if __name__ == "__main__":
    main()
