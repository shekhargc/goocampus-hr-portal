"""
import_plab_payments.py -- refresh PLAB payments in ops_payments from a
Zoho "All_Payments Report.xlsx" export.

This is a REPLACE for pathway='plab': it deletes all existing
pathway='plab' rows in ops_payments and re-inserts every payment row from
the Excel that can be matched to an existing PLAB client. (Australia /
consulting payment rows are untouched.)

Excel columns
=============
  Enter Candidate Name | Registration Number | Total Package | Instalment |
  Total Amount Paid | Payment Date | Amount Paid | GST Paid |
  Payment Method | Notes

ops_payments mapping
====================
  registration_number <- canonical reg that exists in plab_clients
  payment_date        <- Payment Date (ISO yyyy-mm-dd)
  amount_paid         <- Amount Paid
  gst_paid            <- GST Paid
  total_amount_paid   <- Total Amount Paid
  instalment          <- Instalment
  payment_method      <- Payment Method
  total_package       <- Total Package
  notes               <- Notes
  pathway             <- 'plab'

Run
===
  DATABASE_URL=postgresql://...  python3 import_plab_payments.py
  Add DRY_RUN=1 to validate matching only (no writes).
  Override file with PAYMENTS=/path/to/All_Payments Report.xlsx
"""

import os
import re
import sys
import datetime

from db import get_db

DEFAULT_FILE = "/Users/Santosh/Desktop/Zoho Data/UK GC/All_Payments Report.xlsx"

_REG_RE = re.compile(r'(GC[A-Z]*/[0-9A-Za-z-]+/\d+)')
_REG_SPLIT_RE = re.compile(r'^(GC[A-Z]*)/([0-9A-Za-z-]+)/(\d{1,4})$')


def extract_reg(text):
    if not text:
        return None
    m = _REG_RE.search(str(text))
    return m.group(1) if m else None


def _reg_variants(reg):
    seen = set()

    def emit(v):
        if v not in seen:
            seen.add(v)
            return True
        return False

    if emit(reg):
        yield reg
    m = _REG_SPLIT_RE.match(reg)
    if not m:
        return
    prefix, middle, tail = m.group(1), m.group(2), m.group(3)
    try:
        n = int(tail)
    except ValueError:
        return
    middles = [middle]
    if '-' not in middle and middle.isdigit() and len(middle) == 4:
        y = int(middle); yy = y % 100; yyn = (y + 1) % 100
        middles.append(f"{yy:02d}-{yyn:02d}")
    elif '-' in middle:
        start = middle.split('-', 1)[0]
        if start.isdigit() and len(start) == 2:
            middles.append(f"20{int(start):02d}")
    for md in middles:
        for pad in (3, 4, 2, 1):
            v = f"{prefix}/{md}/{n:0{pad}d}"
            if emit(v):
                yield v


def build_reg_lookup(conn):
    """normalized reg -> canonical reg string that exists in plab_clients."""
    rows = conn.execute(
        "SELECT registration_number FROM plab_clients "
        "WHERE COALESCE(pathway,'plab')='plab' AND registration_number IS NOT NULL"
    ).fetchall()
    lookup = {}
    for r in rows:
        reg = (r['registration_number'] or '').strip()
        if reg:
            lookup.setdefault(reg.upper(), reg)
    return lookup


def resolve_reg(lookup, reg):
    """Return the canonical DB reg for an excel reg, via variants."""
    if not reg:
        return None
    for variant in _reg_variants(reg):
        canon = lookup.get(variant.strip().upper())
        if canon:
            return canon
    return None


def num(v):
    if v in (None, ''):
        return 0
    if isinstance(v, (int, float)):
        return v
    s = str(v).replace(',', '').replace('₹', '').strip()
    try:
        return float(s)
    except ValueError:
        return 0


def to_date(v):
    if v in (None, ''):
        return None
    if isinstance(v, datetime.datetime):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, datetime.date):
        return v.strftime('%Y-%m-%d')
    return str(v).strip()


def main():
    path = os.environ.get('PAYMENTS', DEFAULT_FILE)
    dry_run = os.environ.get('DRY_RUN') in ('1', 'true', 'True')

    if not os.path.isfile(path):
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get('DATABASE_URL'):
        print("ERROR: DATABASE_URL required.", file=sys.stderr)
        sys.exit(1)

    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else '' for h in next(it)]
    hidx = {h: i for i, h in enumerate(headers)}

    def col(name):
        return hidx.get(name)

    c_reg = col('Registration Number')
    c_pkg = col('Total Package')
    c_inst = col('Instalment')
    c_tot = col('Total Amount Paid')
    c_date = col('Payment Date')
    c_amt = col('Amount Paid')
    c_gst = col('GST Paid')
    c_method = col('Payment Method')
    c_notes = col('Notes')
    if c_reg is None or c_amt is None:
        print(f"ERROR: required columns missing. Headers: {headers}", file=sys.stderr)
        sys.exit(1)

    rows = []
    for r in it:
        if not any(v not in (None, '') for v in r):
            continue

        def g(i):
            return r[i] if (i is not None and i < len(r)) else None
        rows.append(r)
    wb.close()
    print(f"Excel data rows: {len(rows)}")

    conn = get_db()
    lookup = build_reg_lookup(conn)
    print(f"PLAB clients indexed by reg: {len(lookup)}")

    matched = []
    unmatched_regs = {}
    for r in rows:
        reg_raw = r[c_reg]
        reg = extract_reg(reg_raw)
        canon = resolve_reg(lookup, reg)
        if not canon:
            unmatched_regs[reg or str(reg_raw)] = unmatched_regs.get(reg or str(reg_raw), 0) + 1
            continue
        matched.append((
            canon,
            to_date(r[c_date]),
            num(r[c_amt]),
            num(r[c_gst]),
            num(r[c_tot]),
            (str(r[c_inst]).strip() if c_inst is not None and r[c_inst] not in (None, '') else None),
            (str(r[c_method]).strip() if c_method is not None and r[c_method] not in (None, '') else None),
            num(r[c_pkg]),
            (str(r[c_notes]).strip() if c_notes is not None and r[c_notes] not in (None, '') else None),
        ))

    print(f"Matched payment rows: {len(matched)}")
    print(f"Unmatched regs ({len(unmatched_regs)}): "
          f"{sorted(unmatched_regs.items(), key=lambda x:-x[1])[:10]}")
    skipped_rows = sum(unmatched_regs.values())
    print(f"Skipped rows (unmatched client): {skipped_rows}")

    if dry_run:
        print("\nDRY RUN -- no changes written.")
        conn.close()
        return

    existing = conn.execute(
        "SELECT COUNT(*) n FROM ops_payments WHERE COALESCE(pathway,'plab')='plab'"
    ).fetchone()['n']
    print(f"\nDeleting {existing} existing pathway='plab' payment rows...")
    conn.execute("DELETE FROM ops_payments WHERE COALESCE(pathway,'plab')='plab'")
    conn.commit()

    ins = 0
    for m in matched:
        try:
            conn.execute(
                "INSERT INTO ops_payments "
                "  (registration_number, payment_date, amount_paid, gst_paid, "
                "   total_amount_paid, instalment, payment_method, total_package, "
                "   notes, pathway) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'plab')",
                m,
            )
            ins += 1
        except Exception as e:
            print(f"  insert failed ({m[0]}): {e}")
            conn.rollback()
    conn.commit()
    final = conn.execute(
        "SELECT COUNT(*) n FROM ops_payments WHERE COALESCE(pathway,'plab')='plab'"
    ).fetchone()['n']
    conn.close()

    print()
    print("=== PLAB Payments Refresh Summary ===")
    print(f"  Excel rows:              {len(rows)}")
    print(f"  Inserted (plab):         {ins}")
    print(f"  Skipped (no client):     {skipped_rows}")
    print(f"  Final plab payment rows: {final}")


if __name__ == '__main__':
    main()
