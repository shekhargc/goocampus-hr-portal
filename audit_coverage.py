"""
audit_coverage.py — COMPLETE no-loose-ends audit of dropdown coverage for
both pathways. READ-ONLY.

For every section file (PLAB + AMC) it reads the Drop Down sheet and classifies
each field with master values as:
   MAPPED   -> a lookup_options category (will sync to Field Manager)
   VENDOR   -> centralised vendors_providers
   REFERENCE-> handled outside lookups on purpose (CITY/STATE/etc.)
   *** UNMAPPED *** -> a dropdown the importer would silently drop (LOOSE END)

Then it cross-checks that the key client-form categories are read pathway-scoped.
"""
import os
os.environ.setdefault('UK_DIR', '/Users/Santosh/Desktop/Zoho Data/UK GC')
os.environ.setdefault('AMC_DIR', '/Users/Santosh/Desktop/Zoho Data/AMC PGCP')
import import_master_dropdowns_vendors as M

# Columns that are deliberately NOT lookup_options (handled elsewhere) so they
# should NOT be flagged as loose ends.
REFERENCE_OK = {
    'city', 'state',                       # states/cities tables
    'customer id', 'registation number', 'registration number', 'candidate name',
    'candidate email', 'mobile number', 'whats app number', 'd.o.b', 'dob',
    'registration id', 'gc aus registration', 'gc uk registration',
    'package', 'final package', 'discount allowed', 'notes', 'additional notes',
}


def is_reference(h):
    hl = h.strip().lower()
    if hl in REFERENCE_OK:
        return True
    for kw in ('name', 'email', 'number', 'date', 'package', 'note', 'id',
               'amount', 'installment', 'instalment', 'topic', 'address',
               'password', 'login', 'score', 'reference', 'pwd', 'answer',
               'question', 'hint', 'journal', 'hospital', 'college', 'remark'):
        if kw in hl:
            return True
    return False


def audit(pathway, sections):
    folder = M.PATHWAY_DIRS[pathway]
    loose = []
    n_mapped = n_vendor = n_ref = 0
    print(f"\n{'='*74}\nPATHWAY: {pathway}\n{'='*74}")
    for sec in sections:
        path = os.path.join(folder, sec['file'])
        if not os.path.exists(path):
            print(f"  [{sec['section']:26}] FILE MISSING: {sec['file']}")
            continue
        _, headers, per_vals, per_tag = M.read_dropdown_sheet(path)
        cols = sec['cols']
        sec_loose = []
        for h in headers:
            vals = per_vals.get(h, [])
            if not vals:
                continue
            tag = per_tag.get(h, '')
            cat = cols.get(h)
            if cat == '__VENDOR__' or cat in M.VENDOR_BACKED_CATEGORIES or (cat is None and M.is_vendor_column(h, tag) and vals):
                n_vendor += 1
            elif cat:
                n_mapped += 1
            elif is_reference(h):
                n_ref += 1
            else:
                sec_loose.append((h, len(vals), vals[:5]))
        if sec_loose:
            print(f"  [{sec['section']:26}] *** {len(sec_loose)} UNMAPPED dropdown field(s):")
            for h, n, sample in sec_loose:
                print(f"        - {h!r}  ({n} values)  e.g. {sample}")
            loose.extend((pathway, sec['section'], h) for h, _, _ in sec_loose)
    print(f"  --> mapped={n_mapped}  vendor={n_vendor}  reference={n_ref}  LOOSE_ENDS={len(loose)}")
    return loose


all_loose = []
all_loose += audit('plab', M.PLAB_SECTIONS)
all_loose += audit('australia', M.AMC_SECTIONS)

print(f"\n{'#'*74}\nTOTAL LOOSE ENDS (unmapped dropdown fields): {len(all_loose)}")
for pw, sec, h in all_loose:
    print(f"   {pw:10} | {sec:26} | {h}")

# ── Form-read alignment: are the client-form dropdowns read pathway-scoped? ──
print(f"\n{'#'*74}\nFORM-READ / PATHWAY-SCOPING CHECK (australia)")
from db import get_db
conn = get_db()
for cat in ('plan_type', 'joined_stage', 'switched_program', 'account_status',
            'current_stage', 'counsellor', 'lead_source'):
    try:
        au = M.existing_lookup_values(conn, cat, 'australia')
        pl = M.existing_lookup_values(conn, cat, 'plab')
        print(f"   {cat:18} australia={sum(1 for v in au.values() if v):3} active | plab={sum(1 for v in pl.values() if v):3} active")
    except Exception as e:
        print(f"   {cat}: {e}")
conn.close()
