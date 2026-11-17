"""Paid 1-on-1 Counselling Session for goocampus.in FREE doctors (founder 2026-11-17).

Product: ₹4,999 INCLUSIVE of GST (₹4,236.44 + 18% GST ₹762.56). At booking the doctor picks:
  * session_1h   — one 1-hour session (counselling rules / authorities / college suggestions)
  * round_choice — choice-entry SUGGESTIONS for one round (we suggest, the doctor fills)
Terms: no seat guarantee; full refund if we can't schedule within 3 days; no refund once the
session has happened. Ashwini S delivers; the team calls to fix a time (no slot picker yet).

Eligibility = the same "free doctor" test as the profile pop-up (api.profile_gate_applies):
not team/desk, not Starter/Standard/Premium (incl. granted), no PGCP invitation.

Upgrade credit: a paid session gives ₹4,999 off ONE Starter/Standard/Premium checkout within 30
days of the session payment (applied in api.api_pg_checkout_create_order, consumed on verify).

Doctor API (X-PG-Key + doctor Bearer):
  GET  /api/pg/session/offer            POST /api/pg/session/create-order
  POST /api/pg/session/verify           GET  /api/pg/my/session-bookings
Desk API (X-PG-Key + desk member Bearer):
  GET  /api/pg/desk/session-bookings    POST /api/pg/desk/session-bookings/<id>
Admin (Registered Doctors → 💳 Paid Sessions tab; admin or the Registered Doctors grant):
  GET  /admin/pg/users/paid-sessions    POST /admin/pg/users/paid-sessions/<id>/update
"""
import hmac
import hashlib
import logging
import os
from datetime import datetime, timedelta

from flask import request, jsonify, render_template, redirect, url_for, flash

from db import get_db
from core.auth import login_required
from core.helpers import format_dr_name as dr_name
from pg_admin.utils import as_dict

SESSION_PRICE_PAISE = 499900          # ₹4,999.00, GST INCLUSIVE
SESSION_PRICE = 4999.00
SESSION_GST_PCT = 18.0
CREDIT_DAYS = 30
DEFAULT_ASSIGNEE = 'Ashwini S'
PRODUCT_NAME = '1-on-1 Counselling Session'

KINDS = {
    'session_1h': 'One 1-hour counselling session',
    'round_choice': 'Choice-entry suggestions for one round',
}
KIND_DETAIL = {
    'session_1h': 'A one-hour call with our counsellor on counselling rules, authorities, '
                  'quotas and college suggestions for your rank.',
    'round_choice': 'Our counsellor suggests your choices for ONE counselling round; '
                    'you fill them in yourself on the authority website.',
}
STATUSES = ['created', 'paid', 'scheduled', 'completed', 'refunded', 'cancelled']
STATUS_LABELS = {
    'created': 'Payment not completed', 'paid': 'Paid — to schedule', 'scheduled': 'Scheduled',
    'completed': 'Completed', 'refunded': 'Refunded', 'cancelled': 'Cancelled',
}
OPEN_STATUSES = ('paid', 'scheduled')                 # a live booking (blocks a second purchase)
CREDIT_STATUSES = ('paid', 'scheduled', 'completed')  # bookings that give the upgrade credit
DESK_SETTABLE = ('scheduled', 'completed', 'cancelled')   # refunds are money → admin only
TERMS = [
    'Suggestions and guidance only — no seat guarantee.',
    'Choice-entry suggestions are for one counselling round; you fill your choices yourself.',
    "Full refund if we can't schedule your session within 3 days of payment.",
    'No refund once the session has taken place.',
    f'Upgrade within {CREDIT_DAYS} days to Starter, Standard or Premium and the ₹4,999 is adjusted '
    'in full against that plan (once).',
]
INCLUDES = [
    'Choose ONE: a 1-hour counselling session OR choice-entry suggestions for one round',
    'With our counsellor (Ashwini S); our team calls you to fix a convenient time',
    'Counselling rules, authorities, quotas and college suggestions for your rank',
]


def price_split(total=SESSION_PRICE, gst_pct=SESSION_GST_PCT):
    """GST-inclusive total → (base, gst). 4999 → (4236.44, 762.56); base + gst == total."""
    base = round(total / (1 + gst_pct / 100.0), 2)
    return base, round(total - base, 2)


def credit_for(payable, credit=SESSION_PRICE):
    """How much of the session credit applies to a plan payable (GST-inclusive). Never takes the
    payable below ₹1 (Razorpay needs ≥ ₹1), never more than the credit, never negative."""
    try:
        payable = round(float(payable or 0), 2)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, round(min(float(credit), payable - 1.0), 2))


def regrossed(payable_after, gst_pct):
    """Final (taxable, gst) of a GST-inclusive payable after the credit."""
    payable_after = round(float(payable_after or 0), 2)
    if not gst_pct:
        return payable_after, 0.0
    gst = round(payable_after * gst_pct / (100.0 + gst_pct), 2)
    return round(payable_after - gst, 2), gst


# ── schema ──────────────────────────────────────────────────────────────────
_READY = False


def ensure_session_tables(conn, force=False):
    """Additive + cold-start safe; DDL once per process."""
    global _READY
    if _READY and not force:
        return
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_session_bookings (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL DEFAULT 'session_1h',
            round_note TEXT DEFAULT '',
            amount_paise INTEGER DEFAULT 499900,
            gst_inclusive INTEGER DEFAULT 1,
            base_amount NUMERIC(12,2) DEFAULT 0,
            gst_amount NUMERIC(12,2) DEFAULT 0,
            gst_percent NUMERIC(5,2) DEFAULT 18,
            razorpay_order_id TEXT UNIQUE,
            razorpay_payment_id TEXT DEFAULT '',
            status TEXT DEFAULT 'created',
            paid_at TIMESTAMP,
            scheduled_at TIMESTAMP,
            completed_at TIMESTAMP,
            refunded_at TIMESTAMP,
            assigned_to TEXT DEFAULT 'Ashwini S',
            team_notes TEXT DEFAULT '',
            credit_until TIMESTAMP,
            credit_used_order_id TEXT,
            credit_used_at TIMESTAMP,
            alert_sent_at TIMESTAMP,
            created_by TEXT DEFAULT 'goocampus.in',
            updated_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_session_bookings_user ON pg_session_bookings (user_id, id)")
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_session_booking_log (
            id SERIAL PRIMARY KEY,
            booking_id INTEGER NOT NULL,
            field TEXT NOT NULL,
            old_value TEXT DEFAULT '',
            new_value TEXT DEFAULT '',
            changed_by TEXT DEFAULT '',
            source TEXT DEFAULT '',
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_session_booking_log_b ON pg_session_booking_log (booking_id, id)")
        conn.commit()
        _READY = True
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("ensure_session_tables: %s", e)


# ── helpers ─────────────────────────────────────────────────────────────────
def _ist(dt):
    if not dt:
        return ''
    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
        except Exception:
            return dt
    return (dt.replace(tzinfo=None) + timedelta(minutes=330)).strftime('%d %b %Y, %I:%M %p')


def _iso(dt):
    if not dt:
        return None
    if isinstance(dt, str):
        return dt
    return dt.replace(tzinfo=None).isoformat() + 'Z'


def parse_ist_input(raw):
    """'2026-11-20T15:30' (an IST datetime-local) → naive UTC datetime, or None."""
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(raw[:19], fmt) - timedelta(minutes=330)
        except ValueError:
            continue
    raise ValueError('bad_datetime')


def ist_input_value(dt):
    """naive UTC → 'YYYY-MM-DDTHH:MM' in IST for a datetime-local input."""
    if not dt or isinstance(dt, str):
        return ''
    return (dt.replace(tzinfo=None) + timedelta(minutes=330)).strftime('%Y-%m-%dT%H:%M')


def public_booking(b):
    b = dict(b or {})
    return {
        'id': b.get('id'), 'kind': b.get('kind'), 'kind_label': KINDS.get(b.get('kind'), b.get('kind')),
        'round_note': b.get('round_note') or '',
        'status': b.get('status'), 'status_label': STATUS_LABELS.get(b.get('status'), b.get('status')),
        'amount': round((b.get('amount_paise') or 0) / 100.0, 2),
        'base_amount': float(b.get('base_amount') or 0), 'gst_amount': float(b.get('gst_amount') or 0),
        'gst_percent': float(b.get('gst_percent') or 0), 'gst_inclusive': bool(b.get('gst_inclusive')),
        'paid_at': _iso(b.get('paid_at')), 'paid_at_ist': _ist(b.get('paid_at')),
        'scheduled_at': _iso(b.get('scheduled_at')), 'scheduled_at_ist': _ist(b.get('scheduled_at')),
        'completed_at': _iso(b.get('completed_at')),
        'assigned_to': b.get('assigned_to') or DEFAULT_ASSIGNEE,
        'credit_until': _iso(b.get('credit_until')), 'credit_until_ist': _ist(b.get('credit_until')),
        'credit_used': bool(b.get('credit_used_order_id')),
        'payment_ref': b.get('razorpay_payment_id') or '',
    }


def available_credit(conn, user_id):
    """The doctor's unused session credit → {'booking_id', 'amount'} or None. Read-only."""
    try:
        ensure_session_tables(conn)
        r = conn.execute(
            "SELECT id FROM pg_session_bookings WHERE user_id = ? AND status IN ('paid','scheduled','completed') "
            "AND credit_used_order_id IS NULL AND credit_until IS NOT NULL AND credit_until > CURRENT_TIMESTAMP "
            "ORDER BY paid_at ASC, id ASC LIMIT 1", (user_id,)).fetchone()
        return {'booking_id': r['id'], 'amount': SESSION_PRICE} if r else None
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.warning("session available_credit: %s", e)
        return None


def plan_takes_credit(plan):
    code = ((plan or {}).get('code') or '').lower()
    return any(t in code for t in ('starter', 'standard', 'premium'))


def _log(conn, booking_id, field, old, new, who, source):
    if str(old or '') == str(new or ''):
        return
    conn.execute("INSERT INTO pg_session_booking_log (booking_id, field, old_value, new_value, changed_by, source) "
                 "VALUES (?,?,?,?,?,?)", (booking_id, field, str(old or ''), str(new or ''), who or '', source))


def apply_update(conn, booking, form, who, source, allow_statuses):
    """Shared edit (Desk + admin). form: scheduled_at (IST datetime-local), status, team_notes,
    assigned_to. Returns (ok, error). Caller commits."""
    b = dict(booking)
    cur = b.get('status')
    if cur == 'created':
        return False, 'not_paid'
    sch = None
    if 'scheduled_at' in form:
        try:
            sch = parse_ist_input(form.get('scheduled_at'))
        except ValueError:
            return False, 'bad_datetime'
    status = (form.get('status') or '').strip()
    changed = bool(status) and status != cur
    if changed and status not in allow_statuses:
        return False, 'status_not_allowed'
    # Setting a time on a 'paid' booking moves it to 'scheduled' unless another status was chosen.
    if not changed and sch is not None and cur == 'paid':
        status, changed = 'scheduled', True
    sets, params = [], []
    if 'scheduled_at' in form:
        sets.append('scheduled_at = ?'); params.append(sch)
        _log(conn, b['id'], 'scheduled_at', _ist(b.get('scheduled_at')), _ist(sch), who, source)
    if changed:
        sets.append('status = ?'); params.append(status)
        if status == 'completed':
            sets.append('completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)')
        if status == 'refunded':
            sets.append('refunded_at = COALESCE(refunded_at, CURRENT_TIMESTAMP)')
        _log(conn, b['id'], 'status', cur, status, who, source)
    for k in ('team_notes', 'assigned_to'):
        if k in form:
            v = (form.get(k) or '').strip()[:4000]
            if k == 'assigned_to' and not v:
                v = DEFAULT_ASSIGNEE
            sets.append(f'{k} = ?'); params.append(v)
            _log(conn, b['id'], k, b.get(k), v, who, source)
    if not sets:
        return True, None
    sets.append('updated_at = CURRENT_TIMESTAMP'); sets.append('updated_by = ?'); params.append(who or '')
    params.append(b['id'])
    conn.execute(f"UPDATE pg_session_bookings SET {', '.join(sets)} WHERE id = ?", params)
    return True, None


# ── booking alert (OFF until the founder approves) ──────────────────────────
def alerts_enabled():
    """Booking alert emails go out ONLY when PG_SESSION_ALERTS=1 on the service."""
    return (os.environ.get('PG_SESSION_ALERTS') or '').strip() == '1'


def alert_recipients(conn):
    """PG_SESSION_ALERT_EMAILS (comma list) if set, else the Counselling-Desk team accounts' emails."""
    env = [e.strip() for e in (os.environ.get('PG_SESSION_ALERT_EMAILS') or '').split(',') if '@' in e]
    if env:
        return env
    try:
        rows = conn.execute("SELECT email FROM pg_users WHERE COALESCE((to_jsonb(pg_users)->>'desk_access')::int,0) = 1 "
                            "AND COALESCE((to_jsonb(pg_users)->>'is_team_member')::int,0) = 1 "
                            "AND POSITION('@' IN COALESCE(email,'')) > 0").fetchall()
        return [r['email'] for r in rows]
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return []


def send_booking_alert(conn, booking, doctor):
    """Branded email to the team on a new paid booking. No-op unless alerts_enabled()."""
    if not alerts_enabled():
        return False
    to = alert_recipients(conn)
    if not to:
        logging.warning("session alert: no recipients configured")
        return False
    try:
        from html import escape
        from email_utils import send_email, render_branded_email
        name = dr_name(doctor.get('name') or '') if doctor.get('name') else 'A doctor (name pending)'
        b = public_booking(booking)
        rows = [('Doctor', name), ('Mobile', doctor.get('mobile') or ''),
                ('NEET-PG rank', str(doctor.get('neet_pg_rank') or '—')), ('State', doctor.get('state') or '—'),
                ('Chose', b['kind_label']), ('Round / note', b['round_note'] or '—'),
                ('Paid', f"₹{b['amount']:,.2f} (incl. GST) · {b['paid_at_ist']} IST")]
        inner = ("<p>A free doctor has booked a paid counselling session. Please call to fix a time "
                 "within 3 days.</p><table cellpadding='6' style='border-collapse:collapse;font-size:14px;'>"
                 + ''.join(f"<tr><td style='color:#64748b'>{escape(k)}</td><td><b>{escape(v)}</b></td></tr>" for k, v in rows)
                 + "</table><p><a href='https://goocampus.org/admin/pg/users/paid-sessions'>Open Paid Sessions</a></p>")
        html = render_branded_email('New paid counselling session', inner, preheader=f'{name} booked a session')
        ok = send_email(to, f'New paid session — {name}', html)
        if ok:
            conn.execute("UPDATE pg_session_bookings SET alert_sent_at = CURRENT_TIMESTAMP WHERE id = ?", (booking['id'],))
            conn.commit()
        return bool(ok)
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("session alert: %s", e)
        return False


# ── doctor API ──────────────────────────────────────────────────────────────
def _doctor(conn):
    from pg_admin.routes.api import _bearer_token, _pg_user_by_token
    tok = _bearer_token()
    if not tok:
        return None, (jsonify({'ok': False, 'error': 'login_required'}), 401)
    u = _pg_user_by_token(conn, tok)
    if not u:
        return None, (jsonify({'ok': False, 'error': 'invalid_token'}), 401)
    return as_dict(u), None


def _open_booking(conn, uid):
    r = conn.execute("SELECT * FROM pg_session_bookings WHERE user_id = ? AND status IN ('paid','scheduled') "
                     "ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
    return as_dict(r) if r else None


def api_session_offer():
    """GET /api/pg/session/offer → {ok, eligible, reason?, product, price, base, gst, gst_percent,
    gst_inclusive, kinds:[{key,label,detail}], includes, terms, booking, credit}."""
    from pg_admin.routes.api import _authorized, profile_gate_applies
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        ensure_session_tables(conn)
        u, err = _doctor(conn)
        if err:
            return err
        eligible = profile_gate_applies(conn, u)
        booking = _open_booking(conn, u['id'])
        cr = available_credit(conn, u['id'])
        base, gst = price_split()
        return jsonify({'ok': True, 'eligible': bool(eligible) and not booking,
                        'reason': (None if eligible and not booking else
                                   ('already_booked' if booking else 'not_free_plan')),
                        'product': PRODUCT_NAME, 'price': SESSION_PRICE, 'base': base, 'gst': gst,
                        'gst_percent': SESSION_GST_PCT, 'gst_inclusive': True,
                        'kinds': [{'key': k, 'label': v, 'detail': KIND_DETAIL[k]} for k, v in KINDS.items()],
                        'includes': INCLUDES, 'terms': TERMS,
                        'booking': public_booking(booking) if booking else None,
                        'credit': ({'amount': cr['amount'], 'booking_id': cr['booking_id']} if cr else None)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_session_offer: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_session_create_order():
    """POST /api/pg/session/create-order {kind, round_note?} → a ₹4,999 Razorpay order."""
    from pg_admin.routes.api import _authorized, _razorpay_creds, profile_gate_applies
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    key_id, key_secret = _razorpay_creds()
    if not (key_id and key_secret):
        return jsonify({'ok': False, 'error': 'payments_not_configured'}), 503
    data = request.get_json(silent=True) or {}
    kind = (data.get('kind') or '').strip()
    if kind not in KINDS:
        return jsonify({'ok': False, 'error': 'bad_kind'}), 400
    note = (data.get('round_note') or '').strip()[:300]
    conn = get_db()
    try:
        ensure_session_tables(conn)
        u, err = _doctor(conn)
        if err:
            return err
        if not profile_gate_applies(conn, u):
            return jsonify({'ok': False, 'error': 'not_free_plan'}), 403
        if _open_booking(conn, u['id']):
            return jsonify({'ok': False, 'error': 'already_booked'}), 409
        import requests as _rq
        import time as _t
        try:
            rr = _rq.post('https://api.razorpay.com/v1/orders', auth=(key_id, key_secret),
                          json={'amount': SESSION_PRICE_PAISE, 'currency': 'INR',
                                'receipt': f"pgs_{u['id']}_{int(_t.time())}",
                                'notes': {'user_id': str(u['id']), 'product': 'counselling_session', 'kind': kind}},
                          timeout=20)
        except Exception as e:
            logging.error("session razorpay order: %s", e)
            return jsonify({'ok': False, 'error': 'gateway_error'}), 502
        if rr.status_code not in (200, 201):
            logging.error("session razorpay order %s: %s", rr.status_code, rr.text[:300])
            return jsonify({'ok': False, 'error': 'gateway_error'}), 502
        order = rr.json()
        base, gst = price_split()
        row = conn.execute(
            "INSERT INTO pg_session_bookings (user_id, kind, round_note, amount_paise, gst_inclusive, base_amount, "
            " gst_amount, gst_percent, razorpay_order_id, status, assigned_to) "
            "VALUES (?,?,?,?,1,?,?,?,?,'created',?) RETURNING id",
            (u['id'], kind, note, SESSION_PRICE_PAISE, base, gst, SESSION_GST_PCT, order['id'], DEFAULT_ASSIGNEE)).fetchone()
        conn.commit()
        return jsonify({'ok': True, 'booking_id': row['id'], 'order_id': order['id'],
                        'amount': SESSION_PRICE_PAISE, 'currency': 'INR', 'key_id': key_id,
                        'product': PRODUCT_NAME, 'kind': kind, 'kind_label': KINDS[kind],
                        'breakdown': {'total': SESSION_PRICE, 'base': base, 'gst_percent': SESSION_GST_PCT,
                                      'gst': gst, 'gst_inclusive': True},
                        'prefill': {'name': u.get('name') or '', 'email': u.get('email') or '',
                                    'contact': u.get('mobile') or ''}})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_session_create_order: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_session_verify():
    """POST /api/pg/session/verify {razorpay_order_id, razorpay_payment_id, razorpay_signature}
    → signature check → booking 'paid' (+ 30-day upgrade credit). Idempotent."""
    from pg_admin.routes.api import _authorized, _razorpay_creds
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    _kid, key_secret = _razorpay_creds()
    if not key_secret:
        return jsonify({'ok': False, 'error': 'payments_not_configured'}), 503
    data = request.get_json(silent=True) or {}
    oid = (data.get('razorpay_order_id') or '').strip()
    pid = (data.get('razorpay_payment_id') or '').strip()
    sig = (data.get('razorpay_signature') or '').strip()
    if not (oid and pid and sig):
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    expected = hmac.new(key_secret.encode(), f"{oid}|{pid}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return jsonify({'ok': False, 'error': 'signature_mismatch'}), 400
    conn = get_db()
    try:
        ensure_session_tables(conn)
        u, err = _doctor(conn)
        if err:
            return err
        b = conn.execute("SELECT * FROM pg_session_bookings WHERE razorpay_order_id = ?", (oid,)).fetchone()
        if not b:
            return jsonify({'ok': False, 'error': 'order_not_found'}), 404
        b = as_dict(b)
        if b.get('user_id') != u['id']:
            return jsonify({'ok': False, 'error': 'order_mismatch'}), 403
        if b.get('status') != 'created':
            return jsonify({'ok': True, 'already': True, 'booking': public_booking(b)})
        until = datetime.utcnow() + timedelta(days=CREDIT_DAYS)
        conn.execute("UPDATE pg_session_bookings SET status = 'paid', razorpay_payment_id = ?, "
                     "paid_at = CURRENT_TIMESTAMP, credit_until = ?, updated_at = CURRENT_TIMESTAMP, "
                     "updated_by = 'razorpay' WHERE id = ? AND status = 'created'", (pid, until, b['id']))
        _log(conn, b['id'], 'status', 'created', 'paid', 'razorpay', 'verify')
        conn.commit()
        b = as_dict(conn.execute("SELECT * FROM pg_session_bookings WHERE id = ?", (b['id'],)).fetchone())
        send_booking_alert(conn, b, u)       # no-op unless PG_SESSION_ALERTS=1
        return jsonify({'ok': True, 'booking': public_booking(b)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_session_verify: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_my_session_bookings():
    """GET /api/pg/my/session-bookings → {ok, bookings:[...]} (paid onwards, newest first)."""
    from pg_admin.routes.api import _authorized
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        ensure_session_tables(conn)
        u, err = _doctor(conn)
        if err:
            return err
        rows = conn.execute("SELECT * FROM pg_session_bookings WHERE user_id = ? AND status <> 'created' "
                            "ORDER BY id DESC", (u['id'],)).fetchall()
        return jsonify({'ok': True, 'bookings': [public_booking(r) for r in rows]})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_my_session_bookings: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── list query shared by Desk + admin ───────────────────────────────────────
def list_bookings(conn, status=None, include_created=False):
    where, params = [], []
    if status and status in STATUSES:
        where.append('b.status = ?'); params.append(status)
    elif not include_created:
        where.append("b.status <> 'created'")
    wsql = ('WHERE ' + ' AND '.join(where)) if where else ''
    rows = conn.execute(
        "SELECT b.*, u.name AS doctor_name, u.mobile AS doctor_mobile, u.state AS doctor_state, "
        "u.neet_pg_rank AS doctor_rank, u.neet_pg_score AS doctor_score "
        f"FROM pg_session_bookings b LEFT JOIN pg_users u ON u.id = b.user_id {wsql} "
        "ORDER BY CASE b.status WHEN 'paid' THEN 0 WHEN 'scheduled' THEN 1 ELSE 2 END, "
        "b.scheduled_at ASC NULLS LAST, b.id DESC", params).fetchall()
    return [dict(r) for r in rows]


def _row_out(r):
    d = public_booking(r)
    d.update({'doctor_id': r.get('user_id'),
              'doctor_name': dr_name(r['doctor_name']) if r.get('doctor_name') else '(name pending)',
              'mobile': r.get('doctor_mobile') or '', 'state': r.get('doctor_state') or '',
              'rank': r.get('doctor_rank'), 'score': r.get('doctor_score'),
              'team_notes': r.get('team_notes') or '',
              'scheduled_input': ist_input_value(r.get('scheduled_at'))})
    return d


# ── Counselling Desk API (Ashwini) ──────────────────────────────────────────
def desk_session_bookings():
    """GET /api/pg/desk/session-bookings?status= → {ok, bookings:[...], counts:{status:n}}"""
    from pg_admin.routes.api import _authorized
    from pg_admin.routes.desk_api import _desk_member, ensure_desk_columns
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        ensure_desk_columns(conn)
        ensure_session_tables(conn)
        if not _desk_member(conn):
            return jsonify({'ok': False, 'error': 'no_desk_access'}), 403
        rows = list_bookings(conn, (request.args.get('status') or '').strip() or None)
        counts = {r['status']: r['n'] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM pg_session_bookings WHERE status <> 'created' GROUP BY status").fetchall()}
        return jsonify({'ok': True, 'bookings': [_row_out(r) for r in rows], 'counts': counts,
                        'statuses': [{'key': s, 'label': STATUS_LABELS[s]} for s in DESK_SETTABLE]})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("desk_session_bookings: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def desk_session_update(booking_id):
    """POST /api/pg/desk/session-bookings/<id> {scheduled_at?: 'YYYY-MM-DDTHH:MM' IST, status?:
    scheduled|completed|cancelled, team_notes?} → {ok, booking}. Refunds are admin-only."""
    from pg_admin.routes.api import _authorized
    from pg_admin.routes.desk_api import _desk_member, ensure_desk_columns, _actor_name
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        ensure_desk_columns(conn)
        ensure_session_tables(conn)
        m = _desk_member(conn)
        if not m:
            return jsonify({'ok': False, 'error': 'no_desk_access'}), 403
        b = conn.execute("SELECT * FROM pg_session_bookings WHERE id = ?", (booking_id,)).fetchone()
        if not b:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        form = {k: data[k] for k in ('scheduled_at', 'status', 'team_notes') if k in data}
        ok, why = apply_update(conn, b, form, _actor_name(m), 'desk', DESK_SETTABLE)
        if not ok:
            conn.rollback()
            return jsonify({'ok': False, 'error': why}), 400
        conn.commit()
        r = [x for x in list_bookings(conn, include_created=True) if x['id'] == booking_id]
        return jsonify({'ok': True, 'booking': _row_out(r[0]) if r else None})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("desk_session_update: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── Portal admin: Registered Doctors → 💳 Paid Sessions ─────────────────────
@login_required
def paid_sessions_admin():
    from pg_admin.routes.users_admin import _require_users_section
    admin = _require_users_section('view')
    if not admin:
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    status = (request.args.get('status') or '').strip()
    conn = get_db()
    rows, counts = [], {}
    try:
        ensure_session_tables(conn)
        rows = [_row_out(r) for r in list_bookings(conn, status or None)]
        for r in conn.execute("SELECT status, COUNT(*) AS n FROM pg_session_bookings GROUP BY status").fetchall():
            counts[r['status']] = r['n']
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("paid_sessions_admin: %s", e)
    finally:
        conn.close()
    can_refund = bool(admin.get('is_admin'))
    return render_template('pg_admin/paid_sessions.html', rows=rows, counts=counts, status=status,
                           statuses=STATUSES, status_labels=STATUS_LABELS, kinds=KINDS,
                           can_refund=can_refund, price=SESSION_PRICE, base_gst=price_split(),
                           active='sessions', active_section='goocampus_in')


@login_required
def paid_session_update(booking_id):
    from pg_admin.routes.users_admin import _require_users_section
    admin = _require_users_section('edit')
    if not admin:
        flash('Edit access required', 'error'); return redirect(url_for('pg_paid_sessions'))
    allow = tuple(s for s in STATUSES if s != 'created')
    if not admin.get('is_admin'):
        allow = DESK_SETTABLE          # refunds: admin only
    conn = get_db()
    try:
        ensure_session_tables(conn)
        b = conn.execute("SELECT * FROM pg_session_bookings WHERE id = ?", (booking_id,)).fetchone()
        if not b:
            flash('Booking not found', 'error')
        else:
            form = {k: request.form.get(k) for k in ('scheduled_at', 'status', 'team_notes', 'assigned_to')
                    if k in request.form}
            who = admin.get('name') or admin.get('emp_code') or 'admin'
            ok, why = apply_update(conn, b, form, who, 'portal', allow)
            if ok:
                conn.commit(); flash('Session booking saved', 'success')
            else:
                conn.rollback()
                flash({'bad_datetime': 'Please enter a valid date and time.',
                       'status_not_allowed': 'Only an admin can mark a refund.',
                       'not_paid': 'This booking was never paid.'}.get(why, 'Could not save'), 'error')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("paid_session_update: %s", e)
        flash('Could not save the booking', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_paid_sessions', status=request.args.get('status') or None))


def for_user(user_id):
    """Bookings of one doctor for the Registered Doctors profile panel (own connection; never raises)."""
    conn = get_db()
    try:
        ensure_session_tables(conn)
        rows = conn.execute("SELECT * FROM pg_session_bookings WHERE user_id = ? AND status <> 'created' "
                            "ORDER BY id DESC", (user_id,)).fetchall()
        return [dict(public_booking(r), team_notes=(r.get('team_notes') or '')) for r in rows]
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.warning("session for_user: %s", e)
        return []
    finally:
        conn.close()


def register(app):
    rules = [
        ('/api/pg/session/offer', 'api_pg_session_offer', api_session_offer, ['GET']),
        ('/api/pg/session/create-order', 'api_pg_session_create_order', api_session_create_order, ['POST']),
        ('/api/pg/session/verify', 'api_pg_session_verify', api_session_verify, ['POST']),
        ('/api/pg/my/session-bookings', 'api_pg_my_session_bookings', api_my_session_bookings, ['GET']),
        ('/api/pg/desk/session-bookings', 'api_pg_desk_session_bookings', desk_session_bookings, ['GET']),
        ('/api/pg/desk/session-bookings/<int:booking_id>', 'api_pg_desk_session_update', desk_session_update, ['POST']),
        ('/admin/pg/users/paid-sessions', 'pg_paid_sessions', paid_sessions_admin, ['GET']),
        ('/admin/pg/users/paid-sessions/<int:booking_id>/update', 'pg_paid_session_update', paid_session_update, ['POST']),
    ]
    for rule, ep, fn, methods in rules:
        app.add_url_rule(rule, ep, fn, methods=methods)
