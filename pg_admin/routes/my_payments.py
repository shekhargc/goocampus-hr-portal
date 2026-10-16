"""Doctor's "My plan & payments" card + online balance payment (goocampus.in profile).

Founder 2026-10-16. What the doctor sees in their profile:
  • Paid client with a team package → plan, package amount (GST as agreed), paid so far,
    each payment, balance; "Pay balance ₹X" pays online. When the balance is cleared (online
    OR recorded by the team as received) the button disappears → "Fully paid".
  • Internal client → plan, "Included in your GooCampus package" + the plan's value. No money.
  • Online buyer → plan, amount paid, date, "Paid in full".

Balance payments use their OWN order table (pg_pgcp_balance_orders) — never pg_orders, so the
PG Payments page can't count them twice. Auth: X-PG-Key + the doctor's Bearer token.
"""
import hmac
import hashlib
import logging
from datetime import datetime, timedelta

from flask import request, jsonify
from db import get_db
from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token, _razorpay_creds
from pg_admin.data import pgcp_package as pk

_READY = False


def _ensure(conn):
    global _READY
    if _READY:
        return
    try:
        pk.ensure_schema(conn)
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_pgcp_balance_orders (
            id SERIAL PRIMARY KEY,
            razorpay_order_id TEXT UNIQUE,
            invitation_id INTEGER NOT NULL,
            user_id INTEGER,
            amount NUMERIC(14,2) NOT NULL,
            status TEXT DEFAULT 'created',          -- created | paid
            razorpay_payment_id TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP
        )''')
        conn.commit()
        _READY = True
    except Exception as e:
        logging.warning("my_payments ensure: %s", e)
        try: conn.rollback()
        except Exception: pass


def _user(conn):
    tok = _bearer_token()
    u = _pg_user_by_token(conn, tok) if tok else None
    return dict(u) if u else None


def _m10(v):
    d = ''.join(ch for ch in str(v or '') if ch.isdigit())
    return d[-10:]


def _invite_for(conn, user):
    m = _m10(user.get('mobile'))
    if not m:
        return None
    r = conn.execute(
        "SELECT * FROM pg_pgcp_invitations WHERE status <> 'cancelled' AND "
        "RIGHT(regexp_replace(COALESCE(mobile,''),'\\D','','g'),10) = ? ORDER BY id DESC LIMIT 1", [m]).fetchone()
    return dict(r) if r else None


def _plan(conn, code=None, plan_id=None):
    if code:
        r = conn.execute("SELECT id, code, name, price, COALESCE(gst_percent,0) AS gst_percent FROM pg_plans "
                         "WHERE code = ?", [code]).fetchone()
    elif plan_id:
        r = conn.execute("SELECT id, code, name, price, COALESCE(gst_percent,0) AS gst_percent FROM pg_plans "
                         "WHERE id = ?", [plan_id]).fetchone()
    else:
        return None
    if not r:
        return None
    r = dict(r)
    r['price'] = float(r['price']) if r.get('price') is not None else None
    r['gst_percent'] = float(r['gst_percent'] or 0)
    return r


def _active_plan(conn, uid):
    r = conn.execute("SELECT s.plan_id, s.started_at, s.price_paid, s.source FROM pg_subscriptions s "
                     "WHERE s.user_id = ? AND s.status = 'active' ORDER BY s.id DESC LIMIT 1", [uid]).fetchone()
    return dict(r) if r else None


def _card(conn, user):
    """The doctor's plan & payments picture."""
    _ensure(conn)
    inv = _invite_for(conn, user)
    sub = _active_plan(conn, user['id'])
    plan = (_plan(conn, code=inv.get('plan_code')) if inv and inv.get('plan_code') else None) \
        or (_plan(conn, plan_id=sub['plan_id']) if sub else None)
    out = {'plan': {'code': plan['code'], 'name': plan['name'], 'list_price': plan['price']} if plan else None}
    if inv and (inv.get('client_type') or '') == 'internal':
        out.update(kind='internal', message='Included in your GooCampus package',
                   plan_value=plan['price'] if plan else None)
        return out
    if inv and (inv.get('client_type') or 'paying') == 'paying' and \
            (inv.get('final_amount') is not None or inv.get('invited_amount') is not None
             or (inv.get('payment_status') or '') in ('paid', 'part_paid')):
        sm = pk.summary(conn, inv)
        bal = sm['balance'] if sm['balance'] is not None else 0
        pays = [{'date': p.get('paid_on') or '', 'amount': float(p.get('amount') or 0),
                 'mode': pk.PAY_MODE_LABELS.get(p.get('mode'), p.get('mode') or '')} for p in sm['payments']]
        if sm['legacy'] and (inv.get('payment_status') or '') == 'paid' and not pays and inv.get('paid_amount'):
            pays = [{'date': str(inv.get('created_at') or '')[:10], 'amount': float(inv['paid_amount']),
                     'mode': 'Online' if inv.get('paid_online') else 'Paid to GooCampus'}]
        out.update(kind='package', package={
            'final': sm['final'], 'paid': sm['paid'], 'balance': max(bal, 0) if sm['final'] is not None else None,
            'status': sm['status'], 'status_label': sm['status_label'],
            'gst_mode': inv.get('gst_mode') or '', 'gst_note': 'incl. GST',
            'balance_due_date': inv.get('balance_due_date') or '', 'balance_due_note': inv.get('balance_due_note') or '',
            'balance_requested': bool(inv.get('balance_requested') or 0)},
            payments=pays,
            can_pay_balance=bool(sm['final'] is not None and bal > 0.5 and sm['status'] != 'paid'))
        return out
    if sub and float(sub.get('price_paid') or 0) > 0:
        o = conn.execute("SELECT payable, paid_at FROM pg_orders WHERE user_id = ? AND status = 'paid' "
                         "ORDER BY paid_at DESC NULLS LAST, id DESC LIMIT 1", [user['id']]).fetchone() \
            if _has_orders(conn) else None
        out.update(kind='online', message='Paid in full',
                   paid=float(o['payable']) if o else float(sub['price_paid']),
                   paid_on=(str(o['paid_at'])[:10] if o and o.get('paid_at') else str(sub.get('started_at') or '')[:10]))
        return out
    out.update(kind='free' if not sub else 'complimentary')
    return out


def _has_orders(conn):
    try:
        return bool(conn.execute("SELECT to_regclass('pg_orders') AS t").fetchone()['t'])
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return False


# ── Routes ───────────────────────────────────────────────────────────────────
def api_my_payments():
    """GET /api/pg/my-plan-payments → {ok, kind: internal|package|online|free|complimentary, plan, …}"""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        return jsonify({'ok': True, **_card(conn, user)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_my_payments: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_balance_create_order():
    """POST /api/pg/my-plan-payments/balance/create-order → Razorpay order for the CURRENT balance."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    key_id, key_secret = _razorpay_creds()
    if not (key_id and key_secret):
        return jsonify({'ok': False, 'error': 'payments_not_configured'}), 503
    conn = get_db()
    try:
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        card = _card(conn, user)
        if card.get('kind') != 'package' or not card.get('can_pay_balance'):
            return jsonify({'ok': False, 'error': 'nothing_to_pay', 'message': 'There is no balance to pay.'}), 400
        inv = _invite_for(conn, user)
        amount = round(float(card['package']['balance']), 2)
        import requests as _rq
        rr = _rq.post('https://api.razorpay.com/v1/orders', auth=(key_id, key_secret),
                      json={'amount': int(round(amount * 100)), 'currency': 'INR',
                            'receipt': f"pgbal_{inv['id']}_{user['id']}",
                            'notes': {'user_id': str(user['id']), 'invitation_id': str(inv['id']),
                                      'kind': 'pgcp_balance'}}, timeout=20)
        if rr.status_code not in (200, 201):
            logging.error("balance order %s: %s", rr.status_code, rr.text[:300])
            return jsonify({'ok': False, 'error': 'gateway_error'}), 502
        order = rr.json()
        conn.execute("INSERT INTO pg_pgcp_balance_orders (razorpay_order_id, invitation_id, user_id, amount) "
                     "VALUES (?,?,?,?)", [order['id'], inv['id'], user['id'], amount])
        conn.commit()
        return jsonify({'ok': True, 'order_id': order['id'], 'amount': int(round(amount * 100)), 'currency': 'INR',
                        'key_id': key_id, 'balance': amount, 'plan_name': (card.get('plan') or {}).get('name') or '',
                        'prefill': {'name': user.get('name') or '', 'email': user.get('email') or '',
                                    'contact': user.get('mobile') or ''}})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_balance_create_order: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_balance_verify():
    """POST /api/pg/my-plan-payments/balance/verify {razorpay_order_id, razorpay_payment_id,
    razorpay_signature} → records the payment in the doctor's instalments. Idempotent."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    _kid, key_secret = _razorpay_creds()
    if not key_secret:
        return jsonify({'ok': False, 'error': 'payments_not_configured'}), 503
    d = request.get_json(silent=True) or {}
    oid, pid, sig = (d.get('razorpay_order_id') or '').strip(), (d.get('razorpay_payment_id') or '').strip(), \
        (d.get('razorpay_signature') or '').strip()
    if not (oid and pid and sig):
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    if not hmac.compare_digest(hmac.new(key_secret.encode(), f"{oid}|{pid}".encode(), hashlib.sha256).hexdigest(), sig):
        return jsonify({'ok': False, 'error': 'signature_mismatch'}), 400
    conn = get_db()
    try:
        _ensure(conn)
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        o = conn.execute("SELECT * FROM pg_pgcp_balance_orders WHERE razorpay_order_id = ?", [oid]).fetchone()
        if not o or o['user_id'] != user['id']:
            return jsonify({'ok': False, 'error': 'order_not_found'}), 404
        o = dict(o)
        if o['status'] != 'paid':
            today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d')
            inv = dict(conn.execute("SELECT * FROM pg_pgcp_invitations WHERE id = ?", [o['invitation_id']]).fetchone())
            inv = pk.adopt_legacy(conn, inv, 'goocampus.in (online balance)')
            pk.add_payment(conn, o['invitation_id'], float(o['amount']), today, 'online', pid,
                           'Balance paid online on goocampus.in', 'goocampus.in (doctor)',
                           razorpay_order_id=oid, razorpay_payment_id=pid)
            pk.refresh_status(conn, o['invitation_id'])
            conn.execute("UPDATE pg_pgcp_balance_orders SET status='paid', razorpay_payment_id=?, "
                         "paid_at=CURRENT_TIMESTAMP WHERE id=?", [pid, o['id']])
            conn.commit()
        return jsonify({'ok': True, **_card(conn, user)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_balance_verify: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
