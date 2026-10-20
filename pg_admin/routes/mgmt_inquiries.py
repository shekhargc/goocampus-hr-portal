"""goocampus.in → Management / NRI Inquiries (founder 2026-10-20).

The website's Management / NRI / deemed-quota pages (hub /neet-pg-management-nri-quota-2026, paid-seat
cut-off pages, /management-nri-quota-counselling) send their call-back requests to POST /api/pg/lead
with `interest` + `budget_range`. Those leads must NOT go to Sales → Leads/Inquiries (that board is for
UK/PLAB and consulting) — they land HERE, in their own goocampus.in Admin section, grantable to team
members through Access Master (goocampus.in Admin → "Management / NRI Inquiries").

Follow-ups use the SAME shared thread as Registered Doctors (pg_admin/followups.py, keyed by mobile or
email), so a doctor's history is one story wherever the team opens it.
"""
import logging

from flask import render_template, request, redirect, url_for, flash
from db import get_db
from core.users import get_user
from core.auth import login_required

_PER_PAGE = 50
_READY = False

# Budget bands the website offers — ordered so the list can sort "highest budget first".
BUDGETS = [
    ('above_1cr', 'Above ₹1 crore', 4),
    ('50l_1cr', '₹50 lakh – ₹1 crore', 3),
    ('25_50l', '₹25–50 lakh', 2),
    ('under_25l', 'Under ₹25 lakh', 1),
    ('not_sure', 'Not sure yet', 0),
]


def budget_order(text):
    """Rank a free-text budget band (tolerant of dash/space variants): 4 = highest … 0 = not sure."""
    t = (text or '').lower().replace('–', '-').replace('—', '-')
    if not t.strip():
        return -1
    if 'above' in t or ('1' in t and 'crore' in t and '50' not in t):
        return 4
    if '50' in t and 'crore' in t:
        return 3
    if '25' in t and '50' in t:
        return 2
    if 'under' in t or 'below' in t or 'less' in t:
        return 1
    return 0


def is_mgmt_lead(data):
    """A call-back from the Management / NRI pages (interest names them, or a budget band was given)."""
    interest = str(data.get('interest') or '').lower()
    return bool(str(data.get('budget_range') or '').strip()) or any(
        w in interest for w in ('management', 'nri', 'deemed', 'paid seat'))


def ensure_table(conn):
    global _READY
    if _READY:
        return
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_mgmt_inquiries (
        id SERIAL PRIMARY KEY,
        name TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        mobile10 TEXT DEFAULT '',
        email TEXT DEFAULT '',
        neet_pg_year TEXT DEFAULT '',
        neet_pg_rank TEXT DEFAULT '',
        state TEXT DEFAULT '',
        target_speciality TEXT DEFAULT '',
        interest TEXT DEFAULT '',
        budget_range TEXT DEFAULT '',
        budget_order INTEGER DEFAULT -1,
        message TEXT DEFAULT '',
        source_page TEXT DEFAULT '',
        enquiry_count INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_enquiry_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_mgmt_inq_m10 ON pg_mgmt_inquiries (mobile10)")
    conn.commit()
    _READY = True


def _m10(v):
    d = ''.join(ch for ch in str(v or '') if ch.isdigit())
    return d[-10:]


def _s(v, n=500):
    return str(v or '').strip()[:n]


def record_lead(conn, data):
    """Store a Management / NRI call-back (dedupe by mobile or email: a repeat updates the same
    enquiry + bumps the counter + notes it in the shared follow-up thread). Returns the row id."""
    ensure_table(conn)
    name, phone, email = _s(data.get('name'), 200), _s(data.get('phone'), 40), _s(data.get('email'), 200).lower()
    m10 = _m10(phone)
    fields = {
        'neet_pg_year': _s(data.get('neet_pg_year'), 20),
        'neet_pg_rank': _s(data.get('neet_pg_rank') or data.get('rank'), 20),
        'state': _s(data.get('state') or data.get('domicile_state'), 80),
        'target_speciality': _s(data.get('target_speciality'), 200),
        'interest': _s(data.get('interest'), 200),
        'budget_range': _s(data.get('budget_range'), 80),
        'message': _s(data.get('message'), 2000),
        'source_page': _s(data.get('source_page'), 300),
    }
    row = conn.execute("SELECT id FROM pg_mgmt_inquiries WHERE (mobile10 <> '' AND mobile10 = ?) "
                       "OR (? <> '' AND LOWER(email) = ?) ORDER BY id ASC LIMIT 1", (m10, email, email)).fetchone()
    if row:
        iid = row['id']
        sets, vals = ["enquiry_count = COALESCE(enquiry_count,1) + 1", "last_enquiry_at = CURRENT_TIMESTAMP"], []
        for k, v in fields.items():
            if v:                                   # newest non-empty answer wins (budget may change)
                sets.append(f"{k} = ?"); vals.append(v)
        if fields['budget_range']:
            sets.append("budget_order = ?"); vals.append(budget_order(fields['budget_range']))
        if name:
            sets.append("name = CASE WHEN COALESCE(name,'') = '' THEN ? ELSE name END"); vals.append(name)
        conn.execute(f"UPDATE pg_mgmt_inquiries SET {', '.join(sets)} WHERE id = ?", vals + [iid])
        conn.commit()
        try:
            from pg_admin import followups as _fu
            _fu.ensure_followups_schema(conn)
            bits = [b for b in (fields['interest'], fields['budget_range'] and f"Budget: {fields['budget_range']}",
                                fields['source_page'] and f"Page: {fields['source_page']}") if b]
            _fu.add_followup(conn, phone, email, 'Enquired again — ' + (' · '.join(bits) or 'Management / NRI'),
                             '', '', {'name': 'Website'}, src='mgmt')
        except Exception as e:
            logging.warning("mgmt repeat note: %s", e)
            try: conn.rollback()
            except Exception: pass
        return iid
    iid = conn.execute(
        "INSERT INTO pg_mgmt_inquiries (name, phone, mobile10, email, neet_pg_year, neet_pg_rank, state, "
        "target_speciality, interest, budget_range, budget_order, message, source_page) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
        (name, phone, m10, email, fields['neet_pg_year'], fields['neet_pg_rank'], fields['state'],
         fields['target_speciality'], fields['interest'], fields['budget_range'],
         budget_order(fields['budget_range']), fields['message'], fields['source_page'])).fetchone()['id']
    conn.commit()
    return iid


def notify(conn, name, phone, budget, create_notification):
    """Portal bell for admins + everyone granted this section (no email/WhatsApp, like other enquiries)."""
    try:
        ids = {r['id'] for r in conn.execute("SELECT id FROM employees WHERE is_active = 1 AND is_admin = 1").fetchall()}
        for r in conn.execute(
                "SELECT COALESCE(subject_id, employee_id) AS eid FROM user_section_permissions "
                "WHERE main_section = 'goocampus_in' AND sub_section = 'mgmt_inquiries' AND can_view = 1 "
                "AND COALESCE(subject_type,'employee') = 'employee'").fetchall():
            if r['eid']:
                ids.add(r['eid'])
        for eid in ids:
            create_notification(conn, eid, 'New Management / NRI enquiry',
                                f"{name} · {phone}" + (f" · Budget: {budget}" if budget else ''),
                                'lead', '/admin/pg/mgmt-inquiries')
        conn.commit()
    except Exception as e:
        logging.warning("mgmt notify: %s", e)
        try: conn.rollback()
        except Exception: pass


# ── Admin screen ─────────────────────────────────────────────────────────────────────────────
def _require(action='view'):
    """Admin, or an employee granted goocampus.in → 'Management / NRI Inquiries' in Access Master."""
    user = get_user()
    if not user:
        return None
    if user.get('is_admin'):
        return user
    try:
        from app import has_section_permission
        if has_section_permission(user, 'goocampus_in', 'mgmt_inquiries', action):
            return user
    except Exception:
        pass
    return None


_IST_DAY = "(i.created_at + INTERVAL '330 minutes')::date"
_IST_TODAY = "(NOW() AT TIME ZONE 'Asia/Kolkata')::date"
_REG_WINDOWS = {
    'this_week': ('This week', f"{_IST_DAY} >= date_trunc('week', {_IST_TODAY})::date"),
    'last_week': ('Last week', f"{_IST_DAY} >= date_trunc('week', {_IST_TODAY})::date - 7 "
                               f"AND {_IST_DAY} < date_trunc('week', {_IST_TODAY})::date"),
    'last_10': ('Last 10 days', f"{_IST_DAY} >= {_IST_TODAY} - 9"),
    'last_30': ('Last 30 days', f"{_IST_DAY} >= {_IST_TODAY} - 29"),
    'last_month': ('Last month', f"{_IST_DAY} >= (date_trunc('month', {_IST_TODAY}) - INTERVAL '1 month')::date "
                                 f"AND {_IST_DAY} < date_trunc('month', {_IST_TODAY})::date"),
}


def _back_args():
    return {k: (request.values.get(k) or '') for k in ('q', 'status', 'budget', 'reg', 'sort', 'page')
            if request.values.get(k)}


@login_required
def mgmt_inquiries():
    user = _require('view')
    if not user:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    q = (request.args.get('q') or '').strip()
    f_status = (request.args.get('status') or '').strip()
    f_budget = (request.args.get('budget') or '').strip()
    f_reg = (request.args.get('reg') or '').strip()
    sort = (request.args.get('sort') or 'newest').strip()
    try:
        page = max(1, int(request.args.get('page') or 1))
    except ValueError:
        page = 1
    conn = get_db()
    items, total, statuses, can_edit = [], 0, [], False
    try:
        ensure_table(conn)
        from pg_admin import followups as _fu
        _fu.ensure_followups_schema(conn)
        statuses = list(_fu.STATUSES)
        conds, params = [], []
        if q:
            conds.append("(i.name ILIKE ? OR i.phone ILIKE ? OR i.email ILIKE ? OR i.state ILIKE ?)")
            params += [f'%{q}%'] * 4
        bmap = {k: o for k, _l, o in BUDGETS}
        if f_budget in bmap:
            conds.append("i.budget_order = ?"); params.append(bmap[f_budget])
        elif f_budget == 'none':
            conds.append("COALESCE(i.budget_order,-1) < 0")
        if f_reg in _REG_WINDOWS:
            conds.append(_REG_WINDOWS[f_reg][1])
        where = (' WHERE ' + ' AND '.join(conds)) if conds else ''
        order = ("COALESCE(i.budget_order,-1) DESC, i.last_enquiry_at DESC, i.id DESC" if sort == 'budget'
                 else "i.last_enquiry_at DESC, i.id DESC")
        rows = [dict(r) for r in conn.execute(f"SELECT i.* FROM pg_mgmt_inquiries i{where} ORDER BY {order}",
                                              tuple(params)).fetchall()]
        # status from the shared follow-up thread (same as Registered Doctors / Inquiries)
        people = [{'mobile': r['phone'], 'email': r['email']} for r in rows]
        sts = _fu.statuses_for(conn, people) if rows else []
        for r, st in zip(rows, sts):
            r['fu_status'] = st or 'New'
        if f_status in statuses:
            rows = [r for r in rows if r['fu_status'] == f_status]
        total = len(rows)
        page = min(page, max(1, (total + _PER_PAGE - 1) // _PER_PAGE))
        items = rows[(page - 1) * _PER_PAGE: page * _PER_PAGE]
        # registered goocampus.in doctor? (match by last-10 mobile) + full thread for the drawer
        m10s = [r['mobile10'] for r in items if r.get('mobile10')]
        reg = {}
        if m10s:
            for u in conn.execute(
                    "SELECT id, RIGHT(regexp_replace(COALESCE(mobile,''),'\\D','','g'),10) AS m10 FROM pg_users "
                    "WHERE RIGHT(regexp_replace(COALESCE(mobile,''),'\\D','','g'),10) IN (" + ','.join(['?'] * len(m10s)) + ")",
                    tuple(m10s)).fetchall():
                reg.setdefault(u['m10'], u['id'])
        for r in items:
            r['reg_doctor_id'] = reg.get(r.get('mobile10'))
            r['thread'] = [dict(t) for t in _fu.get_thread(conn, r['phone'], r['email'])]
            r['state_now'] = _fu.current_state(conn, r['phone'], r['email'])
        can_edit = bool(_require('edit'))
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("mgmt_inquiries: %s", e)
        flash('Could not load the enquiries.', 'error')
    finally:
        conn.close()
    from pg_admin import followups as _fu2
    return render_template('pg_admin/mgmt_inquiries.html', items=items, total=total, page=page,
                           total_pages=max(1, (total + _PER_PAGE - 1) // _PER_PAGE),
                           q=q, f_status=f_status, f_budget=f_budget, f_reg=f_reg, sort=sort,
                           statuses=statuses, budgets=BUDGETS,
                           reg_options=[(k, v[0]) for k, v in _REG_WINDOWS.items()],
                           time_slots=_fu2.TIME_SLOTS, date_statuses=_fu2.DATE_STATUSES,
                           can_edit=can_edit, open_id=request.args.get('open') or '',
                           active_section='goocampus_in')


@login_required
def mgmt_inquiry_followup(inq_id):
    """Add a note / status / next follow-up to an enquiry (shared thread), then back to the list."""
    user = _require('edit')
    back = _back_args()
    if not user:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    note = (request.form.get('note') or '').strip()
    status = (request.form.get('status') or '').strip()
    _nd = (request.form.get('next_followup_date') or '').strip()
    _nt = (request.form.get('next_followup_time') or '').strip()
    next_date = (_nd + (' ' + _nt if _nt else '')).strip() if _nd else ''
    if status not in ('Follow-up', 'Interested'):
        next_date = ''
    if not note and not status:
        flash('Add a note or a status.', 'error')
        return redirect(url_for('pg_mgmt_inquiries', open=inq_id, **back))
    conn = get_db()
    try:
        ensure_table(conn)
        r = conn.execute("SELECT phone, email FROM pg_mgmt_inquiries WHERE id = ?", (inq_id,)).fetchone()
        if not r:
            flash('Enquiry not found.', 'error')
        else:
            from pg_admin import followups as _fu
            _fu.ensure_followups_schema(conn)
            _fu.add_followup(conn, r['phone'], r['email'], note, status, next_date, dict(user), src='mgmt')
            flash('Follow-up saved.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("mgmt_inquiry_followup: %s", e)
        flash('Could not save the follow-up.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_mgmt_inquiries', **back))
