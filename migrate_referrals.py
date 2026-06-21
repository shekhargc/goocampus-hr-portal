"""
migrate_referrals.py — one-time: populate the new referral_* columns on
plab_clients from the existing free-text referral names in the Zoho
registration files, matching each referrer name to a real client in its
source pathway.

For each referred client (a row in a pathway's registration file) that has a
referral name, we set on THAT client:
  referral_source_pathway = the source pathway (where the referrer is)
  referral_client_name    = the referrer's name (verbatim)
  referral_client_reg     = the referrer's reg number (matched by name) or NULL

Unmatched referrers are reported so they can be linked manually.

  DATABASE_URL=...  DRY_RUN=1  python3 migrate_referrals.py
  DATABASE_URL=...               python3 migrate_referrals.py
"""
import os
from import_amc_sections import s, norm, extract_reg, strip_reg, _strip_prefix, _pg

DRY = os.environ.get('DRY_RUN') in ('1', 'true', 'True')
ZD = '/Users/Santosh/Desktop/Zoho Data'

# (file, referred-reg-col, referred-name-col, [(referral-col, source_pathway), ...])
FILES = [
 (f"{ZD}/UK GC/PLAB - Registration list.xlsx", 'Registration Number', 'Candidate Name',
   [('UK Client Referral', 'plab'), ('Portfolio Client Referral', 'portfolio'),
    ('Australia Client Referral', 'australia')]),
 (f"{ZD}/AMC PGCP/AMC - GC AUS Registration Report (1).xlsx", 'Registation Number', 'Candidate Name',
   [('UK Client Name', 'plab'), ('GC Portfolio Client Name', 'portfolio'),
    ('GC AUS Registration', 'australia')]),
 (f"{ZD}/Standard Consulting/Standard Consulting -  Registration list.xlsx", 'Registration Number', 'Candidate Name',
   [('UK Client Referral', 'plab'), ('Portfolio Client Referral', 'portfolio'),
    ('Australia Client Referral:', 'australia')]),
]


def name_index(cur):
    """{pathway: {norm_name: reg}} from the live DB."""
    cur.execute("SELECT registration_number, first_name, last_name, COALESCE(pathway,'plab') pw "
                "FROM plab_clients WHERE registration_number IS NOT NULL")
    idx = {}
    for reg, fn, ln, pw in cur.fetchall():
        full = norm(f"{fn or ''} {ln or ''}")
        if full:
            idx.setdefault(pw, {}).setdefault(full, reg)
    return idx


def run():
    import openpyxl
    conn = _pg(); cur = conn.cursor()
    idx = name_index(cur)
    # also need referred-client reg resolution: by reg directly
    cur.execute("SELECT LOWER(TRIM(registration_number)) FROM plab_clients WHERE registration_number IS NOT NULL")
    known_regs = {r[0] for r in cur.fetchall()}

    linked = unmatched_ref = no_referred = 0
    unmatched_list = []
    for path, reg_col, name_col, refcols in FILES:
        if not os.path.exists(path):
            print(f"MISSING {path}"); continue
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else '' for h in next(it)]
        hi = {h: i for i, h in enumerate(headers)}
        def g(row, h):
            i = hi.get(h)
            return row[i] if (i is not None and i < len(row)) else None
        for r in it:
            referred_reg = s(g(r, reg_col))
            referred_reg = extract_reg(referred_reg) or referred_reg
            if not referred_reg or norm(referred_reg) not in known_regs:
                continue
            for refcol, src_pw in refcols:
                refname = s(g(r, refcol))
                if not refname:
                    continue
                # match the referrer name in the source pathway
                key = norm(_strip_prefix(strip_reg(refname)))
                ref_reg = idx.get(src_pw, {}).get(key)
                if not ref_reg:
                    unmatched_ref += 1
                    unmatched_list.append((referred_reg, src_pw, refname))
                if not DRY:
                    cur.execute(
                        "UPDATE plab_clients SET referral_source_pathway=%s, referral_client_name=%s, "
                        "referral_client_reg=%s WHERE registration_number=%s",
                        (src_pw, refname, ref_reg, referred_reg))
                linked += 1
        wb.close()
    if not DRY:
        conn.commit()
    cur.close(); conn.close()
    print(f"\nReferral links set: {linked}  (matched to a referrer client: {linked - unmatched_ref}, "
          f"name-only/unmatched: {unmatched_ref})  DRY={DRY}")
    if unmatched_list:
        print("\nUnmatched referrers (stored as name only — link manually):")
        for rr, pw, nm in unmatched_list:
            print(f"   referred {rr}  <-  '{nm}' (expected in {pw})")


if __name__ == '__main__':
    run()
