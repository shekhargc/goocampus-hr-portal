"""Mock package store APIs for goocampus.in (same X-PG-Key + Bearer handshake as every /api/pg/* call).

  GET  /api/pg/mocks/packages                     the packages + what the doctor already holds
  POST /api/pg/mocks/packages/<code>/quote        price for this doctor (upgrade credit, coupon) — read-only
  POST /api/pg/mocks/packages/<code>/order        Razorpay order (or an instant grant when the price is ₹0)
  POST /api/pg/mocks/packages/verify              verify the Razorpay payment and unlock the package (idempotent)
Uses the portal's Razorpay keys and coupon codes; records its own orders (ex_orders) and purchases
(ex_package_purchases) so counselling plans are never affected.
"""
import hashlib
import hmac
import logging

from flask import request, jsonify

from db import get_db
from exam_engine import packages as K
from exam_engine.doctor_api import _doctor, _err, _close, EXAM_CODE
from exam_engine.tables import TENANT_GOOCAMPUS_IN


def _creds():
    from pg_admin.routes.api import _razorpay_creds
    return _razorpay_creds()


def _pkg(conn, code):
    r = conn.execute("SELECT * FROM ex_packages WHERE tenant_id=? AND exam_code=? AND code=? AND is_active=1",
                     (TENANT_GOOCAMPUS_IN, EXAM_CODE, (code or '').strip().lower())).fetchone()
    return dict(r) if r else None


def _body():
    return request.get_json(silent=True) or {}


def api_packages():
    conn = get_db()
    try:
        user, err = _doctor(conn)
        if err:
            return err
        ent = K.entitlement(conn, user['id'], TENANT_GOOCAMPUS_IN, EXAM_CODE)
        pk = K.all_packages(conn, TENANT_GOOCAMPUS_IN, EXAM_CODE)
        out = []
        for p in pk:
            v = K.public_view(p, ent)
            ok, q = K.quote(conn, user['id'], p)
            v['your_price'] = q['payable'] if ok else None
            v['upgrade_credit'] = q['upgrade_credit'] if ok else 0
            v['included_in_yours'] = (not ok and q.get('error') == 'already_owned')
            out.append(v)
        return jsonify({'ok': True, 'packages': out,
                        'mine': {'full_mocks': ent['full_mocks'], 'subject_tests': ent['subject_tests'],
                                 'mini_tests': ent['mini_tests'], 'packages': ent['packages']}})
    finally:
        _close(conn)


def api_package_quote(code):
    conn = get_db()
    try:
        user, err = _doctor(conn)
        if err:
            return err
        p = _pkg(conn, code)
        if not p:
            return _err('not_found', 'This package is not available.', 404)
        ok, q = K.quote(conn, user['id'], p, _body().get('coupon_code') or '')
        if not ok:
            return _err(q['error'], q['message'], 400)
        q.pop('coupon_id', None)
        return jsonify({'ok': True, **q})
    finally:
        _close(conn)


def api_package_order(code):
    conn = get_db()
    try:
        user, err = _doctor(conn)
        if err:
            return err
        p = _pkg(conn, code)
        if not p:
            return _err('not_found', 'This package is not available.', 404)
        ok, q = K.quote(conn, user['id'], p, _body().get('coupon_code') or '')
        if not ok:
            return _err(q['error'], q['message'], 400)
        if q['payable'] <= 0:      # a 100% coupon (or full upgrade credit) — unlock now, no charge
            oid = conn.execute(
                "INSERT INTO ex_orders (tenant_id, user_id, package_id, amount, credit, discount, payable, gst_included, "
                "coupon_code, coupon_id, status, paid_at) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, 'paid', CURRENT_TIMESTAMP) "
                "RETURNING id", (TENANT_GOOCAMPUS_IN, user['id'], p['id'], q['amount'], q['upgrade_credit'], q['discount'],
                                 q['coupon_code'], q['coupon_id'])).fetchone()['id']
            pid = K.grant(conn, user['id'], p, 'coupon_free', 0, oid)
            conn.execute("UPDATE ex_orders SET purchase_id=? WHERE id=?", (pid, oid))
            if q['coupon_id']:
                from pg_admin.data import coupons as coupon_lib
                coupon_lib.redeem(conn, q['coupon_id'], user_id=user['id'], order_amount=q['amount'],
                                  discount_amount=q['discount'], code=q['coupon_code'])
            conn.commit()
            return jsonify({'ok': True, 'free': True, 'purchase_id': pid, 'package': p['code']})
        key_id, key_secret = _creds()
        if not (key_id and key_secret):
            return _err('payments_not_configured', 'Payments are not switched on yet.', 503)
        import requests
        try:
            rr = requests.post('https://api.razorpay.com/v1/orders', auth=(key_id, key_secret), timeout=20,
                               json={'amount': int(round(q['payable'] * 100)), 'currency': 'INR',
                                     'receipt': f"mock_{user['id']}_{p['code']}"[:40],
                                     'notes': {'kind': 'mock_package', 'user_id': str(user['id']), 'package': p['code']}})
        except Exception as e:
            logging.error(f'mock package razorpay order: {e}')
            return _err('gateway_error', 'Could not reach the payment gateway — please try again.', 502)
        if rr.status_code not in (200, 201):
            logging.error(f'mock package razorpay order {rr.status_code}: {rr.text[:300]}')
            return _err('gateway_error', 'The payment gateway refused the order — please try again.', 502)
        order = rr.json()
        conn.execute(
            "INSERT INTO ex_orders (tenant_id, user_id, package_id, razorpay_order_id, amount, credit, discount, payable, "
            "gst_included, coupon_code, coupon_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (TENANT_GOOCAMPUS_IN, user['id'], p['id'], order['id'], q['amount'], q['upgrade_credit'], q['discount'],
             q['payable'], q['gst_included'], q['coupon_code'], q['coupon_id']))
        conn.commit()
        return jsonify({'ok': True, 'order_id': order['id'], 'amount': int(round(q['payable'] * 100)), 'currency': 'INR',
                        'key_id': key_id, 'name': f"GooCampus NEET PG Mocks — {p['name']}",
                        'breakdown': {k: q[k] for k in ('amount', 'upgrade_credit', 'discount', 'payable', 'gst_included')},
                        'prefill': {'name': user.get('name') or '', 'email': user.get('email') or '',
                                    'contact': user.get('mobile') or ''}})
    except Exception as e:
        logging.exception('mock package order')
        try:
            conn.rollback()
        except Exception:
            pass
        return _err('server_error', f'Could not create the order ({e.__class__.__name__}).', 500)
    finally:
        _close(conn)


def api_package_verify():
    conn = get_db()
    try:
        user, err = _doctor(conn)
        if err:
            return err
        b = _body()
        oid, pay_id, sig = (str(b.get(k) or '').strip() for k in ('razorpay_order_id', 'razorpay_payment_id',
                                                                  'razorpay_signature'))
        if not (oid and pay_id and sig):
            return _err('missing_fields', 'Payment details are missing.', 400)
        _, key_secret = _creds()
        if not key_secret:
            return _err('payments_not_configured', 'Payments are not switched on yet.', 503)
        expected = hmac.new(key_secret.encode(), f'{oid}|{pay_id}'.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return _err('signature_mismatch', 'The payment could not be verified.', 400)
        o = conn.execute("SELECT * FROM ex_orders WHERE razorpay_order_id=?", (oid,)).fetchone()
        if not o:
            return _err('order_not_found', 'Order not found.', 404)
        o = dict(o)
        if o['user_id'] != user['id']:
            return _err('order_mismatch', 'This order belongs to another account.', 403)
        if o['status'] == 'paid':
            return jsonify({'ok': True, 'already': True, 'purchase_id': o['purchase_id']})
        claimed = conn.execute("UPDATE ex_orders SET status='paid', razorpay_payment_id=?, paid_at=CURRENT_TIMESTAMP "
                               "WHERE id=? AND status <> 'paid' RETURNING id", (pay_id, o['id'])).fetchone()
        if not claimed:        # a parallel verify got there first
            conn.rollback()
            o = dict(conn.execute("SELECT purchase_id FROM ex_orders WHERE id=?", (o['id'],)).fetchone())
            return jsonify({'ok': True, 'already': True, 'purchase_id': o['purchase_id']})
        p = dict(conn.execute("SELECT * FROM ex_packages WHERE id=?", (o['package_id'],)).fetchone())
        pid = K.grant(conn, user['id'], p, 'razorpay', o['payable'], o['id'])
        conn.execute("UPDATE ex_orders SET purchase_id=? WHERE id=?", (pid, o['id']))
        if o.get('coupon_id'):
            from pg_admin.data import coupons as coupon_lib
            coupon_lib.redeem(conn, o['coupon_id'], user_id=user['id'], order_amount=o['amount'],
                              discount_amount=o['discount'], code=o.get('coupon_code') or '')
        conn.commit()
        return jsonify({'ok': True, 'purchase_id': pid, 'package': p['code']})
    except Exception as e:
        logging.exception('mock package verify')
        try:
            conn.rollback()
        except Exception:
            pass
        return _err('server_error', f'Could not confirm the payment ({e.__class__.__name__}). If money was taken, '
                                    'it will be confirmed — please contact us.', 500)
    finally:
        _close(conn)


def register_routes(app):
    r = app.add_url_rule
    r('/api/pg/mocks/packages', 'api_ex_packages', api_packages, methods=['GET'])
    r('/api/pg/mocks/packages/<code>/quote', 'api_ex_package_quote', api_package_quote, methods=['POST'])
    r('/api/pg/mocks/packages/<code>/order', 'api_ex_package_order', api_package_order, methods=['POST'])
    r('/api/pg/mocks/packages/verify', 'api_ex_package_verify', api_package_verify, methods=['POST'])
