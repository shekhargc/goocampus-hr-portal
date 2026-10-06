"""Person-level follow-up thread, SHARED between Sales → Inquiries and the Registered
Doctors profile so a team member's calls, status and next-follow-up stay in sync across
both screens. Identity = mobile (last 10) OR email, so the same person is recognised
whichever number/email they used. One store (pg_followups); the current status + next
follow-up date are derived from the latest entries. (founder 2026-10-05)
"""
import re
import logging
from db import get_db

# Shared with the inquiry board (sales_leads.inquiry_status) so the two map 1:1.
# 'New' is the automatic default (never picked manually); PICK_STATUSES are what the
# team actually selects. A next-follow-up date+time applies to these statuses.
STATUSES = ['New', 'Did not pick up', 'Contacted', 'Follow-up', 'Interested', 'Not Interested', 'Converted']
PICK_STATUSES = [s for s in STATUSES if s != 'New']
DATE_STATUSES = ('Follow-up', 'Interested')   # these keep a next-follow-up date+time


def _time_slots():
    """12-hour time labels every 30 min from 10:00 AM to 11:00 PM (call-hours window)."""
    out = []
    for h in range(10, 24):            # 10:00 .. 23:00
        for m in (0, 30):
            if h == 23 and m == 30:
                continue               # stop at 11:00 PM
            ap = 'AM' if h < 12 else 'PM'
            h12 = h % 12 or 12
            out.append(f"{h12}:{m:02d} {ap}")
    return out


TIME_SLOTS = _time_slots()


def ensure_followups_schema(conn):
    """Create the shared follow-up table (Render cold-start safe) + migrate the existing
    inquiry follow-ups in once, so history is unified from day one."""
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_followups (
            id SERIAL PRIMARY KEY,
            mobile10 TEXT DEFAULT '',
            email TEXT DEFAULT '',
            note TEXT DEFAULT '',
            status TEXT DEFAULT '',
            next_followup_date TEXT DEFAULT '',
            created_by_id INTEGER,
            created_by_name TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            src TEXT DEFAULT 'doctor',
            src_ref INTEGER
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_followups_m10 ON pg_followups (mobile10)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_followups_email ON pg_followups (email)")
        # Office-visit intent per entry — for the Office Visits CRM tab. (founder 2026-10-06)
        conn.execute("ALTER TABLE pg_followups ADD COLUMN IF NOT EXISTS visit_office TEXT DEFAULT ''")   # '' | 'yes' | 'no'
        conn.execute("ALTER TABLE pg_followups ADD COLUMN IF NOT EXISTS visit_date TEXT DEFAULT ''")     # YYYY-MM-DD
        conn.commit()
    except Exception as e:
        logging.error("ensure_followups_schema: %s", e)
        try: conn.rollback()
        except Exception: pass
    _migrate_inquiry_followups(conn)


def _migrate_inquiry_followups(conn):
    """One-time, additive, idempotent: copy existing sales_lead_followups into the shared
    store (keyed by the lead's mobile10 + email). Originals are NOT modified; re-runs skip
    rows already copied (dedupe on src_ref)."""
    try:
        conn.execute(
            "INSERT INTO pg_followups (mobile10, email, note, created_by_id, created_by_name, "
            "created_at, src, src_ref) "
            "SELECT RIGHT(regexp_replace(COALESCE(sl.phone,''),'\\D','','g'),10), "
            "       LOWER(TRIM(COALESCE(sl.email,''))), f.note, f.created_by_id, f.created_by_name, "
            "       f.created_at, 'migrated', f.id "
            "FROM sales_lead_followups f JOIN sales_leads sl ON sl.id = f.lead_id "
            "WHERE NOT EXISTS (SELECT 1 FROM pg_followups p WHERE p.src='migrated' AND p.src_ref = f.id)")
        conn.commit()
    except Exception as e:
        # sales_lead_followups may not exist yet on a fresh DB — harmless.
        logging.info("followup migrate skipped/failed: %s", e)
        try: conn.rollback()
        except Exception: pass


def m10(v):
    return re.sub(r'\D', '', str(v or ''))[-10:]


def norm_email(v):
    return str(v or '').strip().lower()


def _match(mob10, email):
    """(sql, params) matching pg_followups rows for this person by mobile10 OR email."""
    conds, params = [], []
    if mob10:
        conds.append("mobile10 = ?"); params.append(mob10)
    if email:
        conds.append("email = ?"); params.append(email)
    if not conds:
        return ("1=0", [])      # no identity → nothing
    return ("(" + " OR ".join(conds) + ")", params)


def get_thread(conn, mobile, email):
    """Full follow-up history for a person (newest first)."""
    clause, params = _match(m10(mobile), norm_email(email))
    try:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM pg_followups WHERE {clause} ORDER BY created_at DESC, id DESC",
            params).fetchall()]
    except Exception as e:
        logging.error("get_thread: %s", e)
        try: conn.rollback()
        except Exception: pass
        return []


def current_state(conn, mobile, email):
    """Derived current status + next follow-up date for a person: the latest entry that set
    a status / a date. Falls back to a matching inquiry's inquiry_status if the shared thread
    has no status yet (so migrated-only people still show their inquiry status)."""
    mob10, em = m10(mobile), norm_email(email)
    out = {'status': '', 'next_followup_date': '', 'visit_office': '', 'visit_date': '',
           'last_by': '', 'last_at': None}
    for r in get_thread(conn, mobile, email):
        if not out['last_at']:
            out['last_by'] = r.get('created_by_name') or ''
            out['last_at'] = r.get('created_at')
        if not out['status'] and (r.get('status') or ''):
            out['status'] = r['status']
        if not out['next_followup_date'] and (r.get('next_followup_date') or ''):
            out['next_followup_date'] = r['next_followup_date']
        if not out['visit_office'] and (r.get('visit_office') or ''):
            out['visit_office'] = r['visit_office']; out['visit_date'] = r.get('visit_date') or ''
    if not out['status']:
        clause, params = _match(mob10, em)
        lead_clause = clause.replace('mobile10', "RIGHT(regexp_replace(COALESCE(phone,''),'\\D','','g'),10)") \
                            .replace('email = ?', "LOWER(TRIM(COALESCE(email,''))) = ?")
        try:
            r = conn.execute(
                f"SELECT inquiry_status FROM sales_leads WHERE COALESCE(is_inquiry,0)=1 AND {lead_clause} "
                f"AND COALESCE(inquiry_status,'') <> '' ORDER BY id DESC LIMIT 1", params).fetchone()
            if r and dict(r).get('inquiry_status'):
                out['status'] = dict(r)['inquiry_status']
        except Exception:
            try: conn.rollback()
            except Exception: pass
    if not out['status']:
        out['status'] = 'New'       # automatic default when nothing has been set
    return out


def statuses_for(conn, people):
    """Bulk current-status lookup for a list of people (each a dict with 'mobile'+'email').
    Returns a list of status strings in the SAME order — latest shared-thread status, else a
    matching inquiry's status, else 'New'. Two queries total, so a list page stays fast.
    (founder 2026-10-05)"""
    norm = [(m10(p.get('mobile')), norm_email(p.get('email'))) for p in people]
    m10s = {mm for mm, _ in norm if mm}
    emails = {ee for _, ee in norm if ee}
    fu_by_m, fu_by_e, inq_by_m, inq_by_e = {}, {}, {}, {}
    if not (m10s or emails):
        return ['New'] * len(people)
    try:
        ensure_followups_schema(conn)
        conds, params = [], []
        if m10s:
            conds.append("mobile10 IN (%s)" % ','.join(['?'] * len(m10s))); params += list(m10s)
        if emails:
            conds.append("email IN (%s)" % ','.join(['?'] * len(emails))); params += list(emails)
        for r in conn.execute(
                "SELECT mobile10, email, status FROM pg_followups WHERE status <> '' "
                "AND (" + " OR ".join(conds) + ") ORDER BY created_at DESC, id DESC", params).fetchall():
            r = dict(r)
            if r['mobile10'] and r['mobile10'] not in fu_by_m: fu_by_m[r['mobile10']] = r['status']
            if r['email'] and r['email'] not in fu_by_e: fu_by_e[r['email']] = r['status']
    except Exception as e:
        logging.error("statuses_for (followups): %s", e)
        try: conn.rollback()
        except Exception: pass
    try:
        conds, params = [], []
        if m10s:
            conds.append("RIGHT(regexp_replace(COALESCE(phone,''),'\\D','','g'),10) IN (%s)" % ','.join(['?'] * len(m10s))); params += list(m10s)
        if emails:
            conds.append("LOWER(TRIM(COALESCE(email,''))) IN (%s)" % ','.join(['?'] * len(emails))); params += list(emails)
        for r in conn.execute(
                "SELECT RIGHT(regexp_replace(COALESCE(phone,''),'\\D','','g'),10) AS m10, "
                "LOWER(TRIM(COALESCE(email,''))) AS em, inquiry_status FROM sales_leads "
                "WHERE COALESCE(is_inquiry,0)=1 AND COALESCE(inquiry_status,'') <> '' "
                "AND (" + " OR ".join(conds) + ") ORDER BY id DESC", params).fetchall():
            r = dict(r)
            if r['m10'] and r['m10'] not in inq_by_m: inq_by_m[r['m10']] = r['inquiry_status']
            if r['em'] and r['em'] not in inq_by_e: inq_by_e[r['em']] = r['inquiry_status']
    except Exception as e:
        logging.error("statuses_for (inquiry): %s", e)
        try: conn.rollback()
        except Exception: pass
    return [(fu_by_m.get(mm) or fu_by_e.get(ee) or inq_by_m.get(mm) or inq_by_e.get(ee) or 'New')
            for mm, ee in norm]


def add_followup(conn, mobile, email, note, status, next_date, user, src='doctor',
                 visit_office='', visit_date=''):
    """Append a follow-up entry + (when a status is given) sync it onto any matching website
    inquiry so the inquiry board stays in step. Returns the new entry dict."""
    mob10, em = m10(mobile), norm_email(email)
    status = status if status in STATUSES else ''
    next_date = (next_date or '').strip().replace('T', ' ')   # datetime-local → "YYYY-MM-DD HH:MM"
    visit_office = visit_office if visit_office in ('yes', 'no') else ''
    visit_date = (visit_date or '').strip() if visit_office == 'yes' else ''
    uid = (user or {}).get('id')
    uname = (user or {}).get('name') or ''
    conn.execute(
        "INSERT INTO pg_followups (mobile10, email, note, status, next_followup_date, "
        "visit_office, visit_date, created_by_id, created_by_name, src) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (mob10, em, (note or '').strip(), status, next_date, visit_office, visit_date, uid, uname, src))
    conn.commit()
    if status:
        _sync_inquiry_status(conn, mob10, em, status)
    return {'note': (note or '').strip(), 'status': status, 'next_followup_date': next_date,
            'visit_office': visit_office, 'visit_date': visit_date, 'created_by_name': uname}


def _sync_inquiry_status(conn, mob10, em, status):
    """Mirror the status onto matching website inquiries (so the Inquiries board reflects
    a status set from the doctor profile, and vice-versa)."""
    if status not in STATUSES:
        return
    conds, params = [], []
    if mob10:
        conds.append("RIGHT(regexp_replace(COALESCE(phone,''),'\\D','','g'),10) = ?"); params.append(mob10)
    if em:
        conds.append("LOWER(TRIM(COALESCE(email,''))) = ?"); params.append(em)
    if not conds:
        return
    try:
        conn.execute(
            f"UPDATE sales_leads SET inquiry_status = ? WHERE COALESCE(is_inquiry,0)=1 "
            f"AND ({' OR '.join(conds)})", [status] + params)
        conn.commit()
    except Exception as e:
        logging.error("_sync_inquiry_status: %s", e)
        try: conn.rollback()
        except Exception: pass


# ── Registered-Doctors CRM tabs (work queue by week + office visits) ──────────
from datetime import date as _date, datetime as _dtm, timedelta as _td


def ist_today():
    """Today's date in IST (server stores UTC)."""
    return (_dtm.utcnow() + _td(hours=5, minutes=30)).date()


def _parse_date(s):
    s = (s or '').strip()[:10]
    if not s:
        return None
    try:
        return _dtm.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        return None


def week_bucket(s, today=None):
    """Classify a YYYY-MM-DD(…) date string into overdue/this/next/later (Mon–Sun weeks);
    '' if no/invalid date."""
    d = _parse_date(s)
    if not d:
        return ''
    today = today or ist_today()
    monday = today - _td(days=today.weekday())
    sunday = monday + _td(days=6)
    next_sunday = sunday + _td(days=7)
    if d < monday:
        return 'overdue'
    if d <= sunday:
        return 'this'
    if d <= next_sunday:
        return 'next'
    return 'later'


def crm_rows(conn):
    """Per-person (keyed by mobile last-10) current snapshot for the CRM tabs: latest status +
    its next-follow-up date, latest office-visit intent, name + links to the doctor profile /
    inquiry. People with only an email (no mobile) are not aggregated here (doctors have mobiles)."""
    ensure_followups_schema(conn)
    try:
        status_rows = [dict(r) for r in conn.execute(
            "SELECT DISTINCT ON (mobile10) mobile10, status, next_followup_date, created_by_name, created_at "
            "FROM pg_followups WHERE mobile10 <> '' AND status <> '' "
            "ORDER BY mobile10, created_at DESC, id DESC").fetchall()]
        visit_rows = [dict(r) for r in conn.execute(
            "SELECT DISTINCT ON (mobile10) mobile10, visit_office, visit_date "
            "FROM pg_followups WHERE mobile10 <> '' AND visit_office <> '' "
            "ORDER BY mobile10, created_at DESC, id DESC").fetchall()]
    except Exception as e:
        logging.error("crm_rows snapshot: %s", e)
        try: conn.rollback()
        except Exception: pass
        return []
    visit_by = {r['mobile10']: r for r in visit_rows}
    rows = {}
    for r in status_rows:
        rows[r['mobile10']] = {
            'mobile10': r['mobile10'], 'status': r['status'],
            'next_followup_date': r.get('next_followup_date') or '',
            'visit_office': '', 'visit_date': '',
            'last_by': r.get('created_by_name') or '', 'last_at': r.get('created_at'),
            'name': '', 'doctor_id': None, 'inquiry_id': None}
    for mv, v in visit_by.items():
        if mv in rows:
            rows[mv]['visit_office'] = v.get('visit_office') or ''
            rows[mv]['visit_date'] = v.get('visit_date') or ''
        elif v.get('visit_office') == 'yes':
            rows[mv] = {'mobile10': mv, 'status': 'New', 'next_followup_date': '',
                        'visit_office': 'yes', 'visit_date': v.get('visit_date') or '',
                        'last_by': '', 'last_at': None, 'name': '', 'doctor_id': None, 'inquiry_id': None}
    out = list(rows.values())
    m10s = [r['mobile10'] for r in out]
    if m10s:
        ph = ','.join(['?'] * len(m10s))
        docs = {}
        try:
            for d in conn.execute(
                    f"SELECT id, name, RIGHT(regexp_replace(COALESCE(mobile,''),'\\D','','g'),10) AS m10 "
                    f"FROM pg_users WHERE RIGHT(regexp_replace(COALESCE(mobile,''),'\\D','','g'),10) IN ({ph})",
                    m10s).fetchall():
                d = dict(d); docs.setdefault(d['m10'], d)
        except Exception:
            try: conn.rollback()
            except Exception: pass
        leads = {}
        try:
            for l in conn.execute(
                    f"SELECT id, lead_name, RIGHT(regexp_replace(COALESCE(phone,''),'\\D','','g'),10) AS m10 "
                    f"FROM sales_leads WHERE COALESCE(is_inquiry,0)=1 AND "
                    f"RIGHT(regexp_replace(COALESCE(phone,''),'\\D','','g'),10) IN ({ph}) ORDER BY id DESC",
                    m10s).fetchall():
                l = dict(l); leads.setdefault(l['m10'], l)
        except Exception:
            try: conn.rollback()
            except Exception: pass
        for r in out:
            d = docs.get(r['mobile10']); l = leads.get(r['mobile10'])
            if d:
                r['doctor_id'] = d['id']; r['name'] = d.get('name') or ''
            if l:
                r['inquiry_id'] = l['id']; r['name'] = r['name'] or (l.get('lead_name') or '')
            if not r['name']:
                r['name'] = '+91 ' + r['mobile10']
    return out


def crm_counts(rows):
    """Tally crm_rows() into the CRM tab badges."""
    c = {'did': 0, 'contacted': 0, 'followups': 0, 'visits': 0, 'converted': 0}
    for r in rows:
        s = r.get('status')
        if s == 'Did not pick up':
            c['did'] += 1
        elif s == 'Contacted':
            c['contacted'] += 1
        elif s in ('Follow-up', 'Interested'):
            c['followups'] += 1
        elif s == 'Converted':
            c['converted'] += 1
        if r.get('visit_office') == 'yes' and (r.get('visit_date') or ''):
            c['visits'] += 1
    return c
