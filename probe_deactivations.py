"""Read-only probe: print the EXACT lookup values that the master importer
would DEACTIVATE (and the vendor names), per category, for review.
Reuses the importer's parsing + DB helpers. Writes nothing."""
import os
os.environ.setdefault('UK_DIR', '/Users/Santosh/Desktop/Zoho Data/UK GC')
import import_master_dropdowns_vendors as M

pathways = os.environ.get('PATHWAYS', 'plab').split(',')
conn = M.get_conn()

for pw in pathways:
    print(f"\n{'='*70}\nPATHWAY: {pw}\n{'='*70}")
    for sec in M.PATHWAY_SECTIONS[pw]:
        path = os.path.join(M.PATHWAY_DIRS[pw], sec['file'])
        if not os.path.exists(path):
            continue
        _, headers, per_vals, per_tag = M.read_dropdown_sheet(path)
        for h, cat in sec['cols'].items():
            if cat in ('__VENDOR__',) or cat in M.VENDOR_BACKED_CATEGORIES or cat in M.HARDCODED_NONLOOKUP:
                continue
            vals = per_vals.get(h, [])
            if not vals:
                continue
            master = {v.lower(): v for v in vals}
            existing = M.existing_lookup_values(conn, cat, pw)
            tc = M.CATEGORY_INUSE.get(cat)
            used = M.inuse_values(conn, tc[0], tc[1], pw) if tc else set()
            deact = [existing_k for existing_k in existing
                     if existing_k not in master and existing_k not in used and existing.get(existing_k)]
            if deact:
                # show original-cased existing values where possible
                print(f"\n[{sec['section']}] {cat}  (field '{h}')  DEACTIVATE {len(deact)}:")
                for k in deact:
                    print(f"     - {k}")

print(f"\n{'='*70}\nVENDOR deactivations\n{'='*70}")
for pw in pathways:
    country = M.COUNTRY[pw]
    for sec in M.PATHWAY_SECTIONS[pw]:
        vp = sec.get('vp_category')
        if not vp:
            continue
        path = os.path.join(M.PATHWAY_DIRS[pw], sec['file'])
        if not os.path.exists(path):
            continue
        _, headers, per_vals, per_tag = M.read_dropdown_sheet(path)
        # rebuild vendor master like the importer does
        vmaster = {}
        for hh in headers:
            tag = per_tag.get(hh, '')
            cat = sec['cols'].get(hh)
            if cat == '__VENDOR__' or cat in M.VENDOR_BACKED_CATEGORIES or (cat is None and M.is_vendor_column(hh, tag) and per_vals.get(hh)):
                for v in per_vals.get(hh, []):
                    if v and v.lower() not in M._NON_VENDOR:
                        vmaster[v.lower()] = v
        existing_v = M.existing_vendor_names(conn, country, vp)
        vt = M.VENDOR_INUSE.get(vp)
        used_v = M.inuse_values(conn, vt[0], vt[1], pw) if vt else set()
        deact = [k for k in existing_v if k not in vmaster and k not in used_v and existing_v.get(k)]
        if deact:
            print(f"\n[{sec['section']}] vendors '{vp}' DEACTIVATE {len(deact)}:")
            for k in deact:
                print(f"     - {k}")

if conn:
    conn.close()
