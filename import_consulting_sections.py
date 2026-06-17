"""
import_consulting_sections.py — refresh Standard Consulting (pathway='consulting')
data from Zoho exports. Same approach as import_amc_sections.py:
  clients   -> upsert plab_clients (pathway='consulting') from
               "GC CSS Registration Report.xlsx" (FK target, run FIRST).
  sections  -> resolve client reg (embedded GCCSS reg w/ padding/year
               variants -> canonical DB reg; else name/email match),
               wipe pathway='consulting' rows in the target table, insert.
  lookups   -> additively add NEW dropdown values found (never delete).

Sections in this batch: amc_reg, payments, epic, mentorship, call_notes.

Run:
  DATABASE_URL=...  DOWNLOADS=/Users/Santosh/Downloads  python3 import_consulting_sections.py
  DRY_RUN=1 -> parse + match only.   SECTIONS=payments,epic -> subset.
"""
import os, re
from datetime import datetime, date

DL = os.environ.get('DOWNLOADS', '/Users/Santosh/Downloads')
DRY = os.environ.get('DRY_RUN') in ('1', 'true', 'True')

def s(v):
    if v is None: return None
    if isinstance(v, float) and v.is_integer(): return str(int(v))
    return str(v).strip() or None
def d(v):
    if v in (None, ''): return None
    if isinstance(v, (datetime, date)): return v.strftime('%Y-%m-%d')
    return str(v).strip() or None
def num(v):
    if v in (None, ''): return None
    try: return float(str(v).replace(',', '').replace('₹', '').strip())
    except (ValueError, TypeError): return None
def hrs2min(v):
    n = num(v)
    return str(int(round(n * 60))) if n is not None else None
def norm(x): return ' '.join((x or '').strip().lower().split())
def digits(x): return re.sub(r'\D', '', str(x or ''))
CONV = {'s': s, 'd': d, 'num': num, 'hrs2min': hrs2min}

_REG_RE = re.compile(r'(GC[A-Z]*/[0-9A-Za-z-]+/\d+)')
_REG_SPLIT = re.compile(r'^(GC[A-Z]*)/([0-9A-Za-z-]+)/(\d{1,4})$')
_PREFIX_RE = re.compile(r'^(dr|dr\.|mr|mr\.|ms|ms\.|mrs|mrs\.|miss|prof|prof\.)\s+', re.I)

def extract_reg(t):
    if not t: return None
    m = _REG_RE.search(str(t)); return m.group(1) if m else None
def strip_reg(t):
    if not t: return t
    return _REG_RE.sub('', str(t)).rstrip(' -').strip()
def _strip_prefix(t):
    if not t: return t
    return _PREFIX_RE.sub('', str(t).strip()).strip()
def reg_variants(reg):
    seen = set()
    def emit(v):
        if v not in seen: seen.add(v); return True
        return False
    if reg and emit(reg): yield reg
    m = _REG_SPLIT.match(reg or '')
    if not m: return
    prefix, middle, tail = m.group(1), m.group(2), m.group(3)
    try: n = int(tail)
    except ValueError: return
    middles = [middle]
    if '-' not in middle and middle.isdigit() and len(middle) == 4:
        y = int(middle)
        middles.append(f"{y%100:02d}-{(y+1)%100:02d}")
        middles.append(f"{(y-1)%100:02d}-{y%100:02d}")
    elif '-' in middle:
        a = middle.split('-', 1)[0]
        if a.isdigit() and len(a) == 2: middles.append(f"20{int(a):02d}")
    for md in middles:
        for pad in (3, 4, 2, 1):
            v = f"{prefix}/{md}/{n:0{pad}d}"
            if emit(v): yield v

def split_name(full):
    full = strip_reg(full) or ''
    full = ' '.join(full.split())
    prefix = ''
    m = _PREFIX_RE.match(full)
    if m: prefix = full[:m.end()].strip(); full = full[m.end():].strip()
    parts = full.split()
    if not parts: return prefix or 'Dr.', '', ''
    if len(parts) == 1: return prefix or 'Dr.', parts[0], ''
    return prefix or 'Dr.', parts[0], ' '.join(parts[1:])

def _pg():
    import psycopg2
    return psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=20,
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5)

CLIENT_FILE = "GC CSS Registration Report.xlsx"
CLIENT_MAP = {
    'customer_id': ('Customer ID', 's'),
    'registration_date': ('Registration Date (Payment Date)', 'd'),
    'mobile': ('Mobile Number', 's'), 'email': ('Candidate Email', 's'),
    'plan_type': ('Plan Type', 's'),
    'package_amount': ('Package (Mention Actual Package)', 'num'),
    'final_package': ('Final Package', 'num'),
    'discount_allowed': ('Discount Allowed (Discount Offer + Stage Discount)', 'num'),
    'account_status': ('Account Status', 's'), 'counsellor': ('Counsellor Name', 's'),
    'current_stage': ('Stage (Current Status)', 's'),
    'dob': ('D.O.B', 'd'), 'city': ('CITY', 's'), 'joined_stage': ('Joined Stage', 's'),
    'lead_source': ('Lead Source', 's'), 'state': ('STATE', 's'),
    'whatsapp1': ('Whats App Number', 's'),
    'instagram': ('Instgram Account Name', 's'), 'facebook': ('Facebook Account Name', 's'),
    'linkedin': ('LinkedIn Account Name', 's'),
    'father_name': ('Fathers Name', 's'), 'father_phone': ('Fathers Mobile Number', 's'),
    'mother_name': ('Mothers Name', 's'), 'mother_phone': ('Mothers Mobile Number', 's'),
    'parents_email': ('Parents Email ID', 's'),
    'counsellor_number': ('Counsellor Number', 's'), 'counsellor_email': ('Counsellor Email', 's'),
    'portfolio_referral': ('GC Portfolio Client Name', 's'),
    'additional_package_notes': ('Discount Notes', 's'),
    'inst1_amount': ('1st Installment', 'num'), 'inst1_date': ('1st Installment Date', 'd'), 'inst1_note': ('1st Installment Note', 's'),
    'inst2_amount': ('2nd Installment', 'num'), 'inst2_date': ('2nd Installment Date', 'd'), 'inst2_note': ('2nd Installment Note', 's'),
    'additional_notes': ('Notes', 's'),
}

def step_clients():
    import openpyxl
    wb = openpyxl.load_workbook(os.path.join(DL, CLIENT_FILE), read_only=True, data_only=True); ws = wb.active
    it = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else '' for h in next(it)]
    hi = {h: i for i, h in enumerate(headers)}
    def g(row, h):
        i = hi.get(h); return row[i] if (i is not None and i < len(row)) else None
    rows = [r for r in it if any(v not in (None, '') for v in r)]
    wb.close()
    conn = _pg(); cur = conn.cursor()
    cur.execute("SELECT registration_number FROM plab_clients WHERE COALESCE(pathway,'plab')='consulting'")
    existing = set((r[0] or '').strip() for r in cur.fetchall())
    ins = upd = skip = 0
    for r in rows:
        reg = extract_reg(g(r, 'Registration Number')) or s(g(r, 'Registration Number'))
        if not reg: skip += 1; continue
        prefix, first, last = split_name(g(r, 'Candidate Name'))
        data = {'prefix': prefix, 'first_name': first, 'last_name': last}
        for col, (h, k) in CLIENT_MAP.items():
            data[col] = CONV[k](g(r, h))
        if DRY:
            upd += (reg in existing); ins += (reg not in existing); continue
        if reg in existing:
            sets = ', '.join(f"{c}=%s" for c in data)
            cur.execute(f"UPDATE plab_clients SET {sets}, updated_at=NOW() WHERE registration_number=%s AND COALESCE(pathway,'plab')='consulting'",
                        list(data.values()) + [reg]); upd += 1
        else:
            cols = ['registration_number', 'pathway'] + list(data.keys())
            cur.execute(f"INSERT INTO plab_clients ({','.join(cols)}) VALUES ({','.join(['%s']*len(cols))})",
                        [reg, 'consulting'] + list(data.values()))
            existing.add(reg); ins += 1
    if not DRY: conn.commit()
    cur.close(); conn.close()
    print(f"[clients] inserted={ins} updated={upd} skipped(no reg)={skip}  (DRY={DRY})")

def build_index():
    conn = _pg(); cur = conn.cursor()
    cur.execute("SELECT registration_number, first_name, last_name, email, mobile, id "
                "FROM plab_clients WHERE COALESCE(pathway,'plab')='consulting'")
    by_reg = {}; by_name = {}; by_email = {}; by_mobile = {}; by_cid = {}
    for reg, fn, ln, email, mob, cid in cur.fetchall():
        if not reg: continue
        canon = reg.strip(); by_cid[norm(canon)] = cid
        for v in reg_variants(canon): by_reg.setdefault(norm(v), canon)
        for key in (f"{fn or ''} {ln or ''}", f"{ln or ''} {fn or ''}"):
            k = norm(key)
            if k: by_name.setdefault(k, canon)
        if email: by_email.setdefault(norm(email), canon)
        if mob:
            dm = digits(mob)[-10:]
            if dm: by_mobile.setdefault(dm, canon)
    cur.close(); conn.close()
    return by_reg, by_name, by_email, by_mobile, by_cid

def resolve_reg(idx, reg_val, name_val, email_val, mobile_val):
    by_reg, by_name, by_email, by_mobile, _ = idx
    emb = extract_reg(name_val) or extract_reg(reg_val) or reg_val
    if emb:
        for v in reg_variants(emb):
            c = by_reg.get(norm(v))
            if c: return c
    nm = norm(_strip_prefix(strip_reg(name_val)))
    if nm and nm in by_name: return by_name[nm]
    if email_val and norm(email_val) in by_email: return by_email[norm(email_val)]
    if mobile_val:
        dm = digits(mobile_val)[-10:]
        if dm and dm in by_mobile: return by_mobile[dm]
    return None

SECTIONS = {
 'amc_reg': ("All Amc Registrations.xlsx", "ops_amc_registration", None, "Enter Candidate Name", None, None, {
    'amc_reference_number':('AMC Reference Number','s'),'login_pwd':('Login Password','s'),
    'amc_setup':('AMC Setup Status','s'),'registration_date':('Registration Date','d'),
 }),
 'payments': ("All Clients Payments.xlsx", "ops_payments", "Registration Number", "Enter Candidate Name", None, None, {
    'payment_date':('Payment Date','d'),'total_package':('Total Package','num'),
    'instalment':('Instalment','s'),'total_amount_paid':('Total Amount Paid','num'),
    'amount_paid':('Amount Paid','num'),'gst_paid':('GST Paid','num'),
    'payment_method':('Payment Method','s'),'notes':('Notes','s'),
 }),
 'epic': ("All Epic Verifications.xlsx", "ops_epic_registration", None, "Enter Candidate Name", None, None, {
    'login_id':('Login ID','s'),'login_pwd':('Login Password','s'),
    'secret_question_1':('Secret Question 1','s'),'secret_answer_1':('Secret Answer 1','s'),
    'secret_question_2':('Secret Question 2','s'),'secret_answer_2':('Secret Answer 2','s'),
    'secret_question_3':('Secret Question 3','s'),'secret_answer_3':('Secret Answer 3','s'),
    'secret_question_4':('Secret Question 4','s'),'secret_answer_4':('Secret Answer 4','s'),
    'notary_camp_login':('Notary Cam Login','s'),'notary_camp_password':('Notary Cam Password','s'),
    'epic_registration':('Epic Registration Status','s'),'registration_date':('Registration Date','d'),
    'epic_id_number':('EPIC ID Number','s'),'epic_status':('EPIC Status','s'),
    'notary_camp':('Notary Cam Status','s'),'documents_stage':('Document Stage','s'),
    'document_stage_status':('Document Stage Status','s'),
 }),
 'mentorship': ("All Mentorship Sessions.xlsx", "ops_mentorship", None, "candidate name", None, None, {
    'session_date':('Date','d'),'duration_minutes':('Duration (In Hours)','hrs2min'),
    'amount_paid':('Amount Paid','num'),'program_provider':('Session Name','s'),
    'mentor_attendance':('Mentor Name','s'),'additional_notes':('Additional Notes','s'),
 }),
 'call_notes': ("Client Call Notes Report (1).xlsx", "ops_call_notes", None, "Candidate Name", None, None, {
    'call_date':('Call Date','d'),'call_note':('Call Notes','s'),'added_by':('Added User','s'),
 }),
}

def step_sections(idx):
    import openpyxl
    from psycopg2.extras import execute_values
    only = os.environ.get('SECTIONS')
    only = set(only.split(',')) if only else None
    summary = []
    for key, cfg in SECTIONS.items():
        if only and key not in only: continue
        fname, table, reg_col, name_col, email_col, mobile_col, mapping = cfg
        path = os.path.join(DL, fname)
        if not os.path.exists(path): print(f"[{key}] MISSING {fname}"); continue
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True); ws = wb.active
        headers = [str(c.value).strip() if c.value is not None else '' for c in next(ws.iter_rows(min_row=1, max_row=1))]
        hidx = {h: i for i, h in enumerate(headers)}
        cols = ['registration_number'] + list(mapping.keys()) + ['pathway']
        batch = []; unmatched = blank = 0; unm = []
        for rcells in ws.iter_rows(min_row=2):
            vals = [c.value for c in rcells]
            if not any(v not in (None, '') for v in vals): continue
            def g(h):
                i = hidx.get(h); return vals[i] if (i is not None and i < len(vals)) else None
            reg_val = s(g(reg_col)) if reg_col else None
            name_val = s(g(name_col)) if name_col else None
            email_val = s(g(email_col)) if email_col else None
            mobile_val = s(g(mobile_col)) if mobile_col else None
            if not (reg_val or name_val or email_val or mobile_val): blank += 1; continue
            reg = resolve_reg(idx, reg_val, name_val, email_val, mobile_val)
            if not reg:
                unmatched += 1
                if len(unm) < 8: unm.append(name_val or reg_val)
                continue
            batch.append(tuple([reg] + [CONV[k](g(h)) for (h, k) in mapping.values()] + ['consulting']))
        wb.close()
        if DRY:
            print(f"[{key:11s}] {table:24s} would_insert={len(batch):5d} unmatched={unmatched:3d} blank={blank}  {unm[:3]}")
            summary.append((key, len(batch), unmatched)); continue
        conn = _pg(); conn.autocommit = False; cur = conn.cursor()
        try:
            cur.execute(f"DELETE FROM {table} WHERE COALESCE(pathway,'plab')='consulting'")
            if batch:
                tmpl = "(" + ",".join(["%s"]*len(cols)) + ")"
                execute_values(cur, f"INSERT INTO {table} ({','.join(cols)}) VALUES %s", batch, template=tmpl, page_size=500)
            conn.commit()
            print(f"[{key:11s}] {table:24s} inserted={len(batch):5d} unmatched={unmatched:3d} blank={blank}")
            summary.append((key, len(batch), unmatched))
        except Exception as e:
            conn.rollback(); print(f"[{key}] FAILED: {e}"); summary.append((key, -1, unmatched))
        finally:
            cur.close(); conn.close()
    print("\n=== SECTION SUMMARY ===")
    for k, n, u in summary: print(f"  {k:12s} {n:6d} inserted, {u} unmatched")

LOOKUP_SRC = [
    ('ops_payments','payment_method','payment_method'), ('ops_payments','instalment','instalment'),
    ('ops_epic_registration','epic_status','epic_status'),
    ('ops_mentorship','program_provider','mentorship_program'),
    ('plab_clients','account_status','account_status'), ('plab_clients','current_stage','current_stage'),
    ('plab_clients','plan_type','plan_type'), ('plab_clients','counsellor','counsellor'),
    ('plab_clients','lead_source','lead_source'),
]
def step_lookups():
    conn = _pg(); cur = conn.cursor(); added = 0
    for table, col, cat in LOOKUP_SRC:
        try:
            cur.execute(f"SELECT DISTINCT {col} FROM {table} WHERE COALESCE(pathway,'plab')='consulting' AND {col} IS NOT NULL AND TRIM({col})<>''")
        except Exception:
            conn.rollback(); continue
        vals = [r[0].strip() for r in cur.fetchall() if r[0] and r[0].strip()]
        cur.execute("SELECT LOWER(TRIM(value)) FROM lookup_options WHERE category=%s AND COALESCE(pathway,'plab')='consulting'", (cat,))
        have = set(r[0] for r in cur.fetchall())
        for v in vals:
            if len(v) > 120 or v.lower() in have: continue
            if not DRY:
                cur.execute("INSERT INTO lookup_options (category,label,value,pathway,is_active) VALUES (%s,%s,%s,'consulting',true)", (cat, v, v))
            have.add(v.lower()); added += 1
    if not DRY: conn.commit()
    cur.close(); conn.close()
    print(f"[lookups] new dropdown values added={added}  (DRY={DRY})")

def main():
    step = os.environ.get('STEP', 'all')
    print(f"=== Standard Consulting refresh — STEP={step} DRY_RUN={DRY} ===")
    if step in ('all', 'clients'): step_clients()
    idx = build_index()
    print(f"index: {len(idx[0])} reg-variants, {len(idx[1])} names, {len(idx[4])} client_ids")
    if step in ('all', 'sections'): step_sections(idx)
    if step in ('all', 'lookups'): step_lookups()

if __name__ == '__main__':
    main()
