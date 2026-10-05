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
    out = {'status': '', 'next_followup_date': '', 'last_by': '', 'last_at': None}
    for r in get_thread(conn, mobile, email):
        if not out['last_at']:
            out['last_by'] = r.get('created_by_name') or ''
            out['last_at'] = r.get('created_at')
        if not out['status'] and (r.get('status') or ''):
            out['status'] = r['status']
        if not out['next_followup_date'] and (r.get('next_followup_date') or ''):
            out['next_followup_date'] = r['next_followup_date']
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


def add_followup(conn, mobile, email, note, status, next_date, user, src='doctor'):
    """Append a follow-up entry + (when a status is given) sync it onto any matching website
    inquiry so the inquiry board stays in step. Returns the new entry dict."""
    mob10, em = m10(mobile), norm_email(email)
    status = status if status in STATUSES else ''
    next_date = (next_date or '').strip().replace('T', ' ')   # datetime-local → "YYYY-MM-DD HH:MM"
    uid = (user or {}).get('id')
    uname = (user or {}).get('name') or ''
    conn.execute(
        "INSERT INTO pg_followups (mobile10, email, note, status, next_followup_date, "
        "created_by_id, created_by_name, src) VALUES (?,?,?,?,?,?,?,?)",
        (mob10, em, (note or '').strip(), status, next_date, uid, uname, src))
    conn.commit()
    if status:
        _sync_inquiry_status(conn, mob10, em, status)
    return {'note': (note or '').strip(), 'status': status, 'next_followup_date': next_date,
            'created_by_name': uname}


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
