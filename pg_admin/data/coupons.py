"""Coupon validation + redemption.

The whole discount calculation lives here (founder 2026-07-28). Used by the live
Razorpay checkout on goocampus.in (/api/pg/checkout/create-order + verify), by the
admin editor's preview, and by team PGCP invites (a coupon as the package discount —
see pg_admin/data/pgcp_package.py, which burns the use with the invite noted).

    ok, result = validate(conn, 'LAUNCH50', plan_id=3, user_id=17)
    -> result['discount'], result['payable'], or result['error'] in plain English

`redeem` is called only after a payment actually succeeds. Validation is free and
repeatable; redemption is the thing that burns a use.
"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP


def _money(val):
    try:
        return Decimal(str(val or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


def find(conn, code):
    if not (code or '').strip():
        return None
    try:
        row = conn.execute("SELECT * FROM pg_coupons WHERE UPPER(code) = UPPER(?)",
                           (code.strip(),)).fetchone()
        return dict(row) if row else None
    except Exception as e:
        conn.rollback()
        logging.error("coupons.find: %s", e)
        return None


def compute_discount(coupon, amount):
    """The money maths, isolated so it can be unit-checked and reused by the admin
    preview. Never discounts more than the order itself."""
    amount = _money(amount)
    value = _money(coupon.get('discount_value'))
    if (coupon.get('discount_type') or 'percent') == 'percent':
        disc = (amount * value / Decimal('100')).quantize(Decimal('0.01'),
                                                          rounding=ROUND_HALF_UP)
        cap = coupon.get('max_discount_amount')
        if cap is not None:
            disc = min(disc, _money(cap))
    else:
        disc = value
    return max(Decimal('0.00'), min(disc, amount))


def validate(conn, code, plan_id=None, user_id=None, amount=None, gst_percent=None):
    """(ok, dict). On failure dict['error'] is a sentence we can show a doctor.
    Discount applies to the base price; GST (gst_percent) is then added ON TOP of
    the discounted amount — so payable = (price - discount) * (1 + gst%/100)."""
    coupon = find(conn, code)
    if not coupon:
        return False, {'error': 'That coupon code is not valid.'}
    if not coupon.get('is_active'):
        return False, {'error': 'This coupon is no longer active.'}

    now = datetime.utcnow() + timedelta(hours=5, minutes=30)   # coupon dates are entered + stored in IST
    if coupon.get('valid_from') and coupon['valid_from'] > now:
        return False, {'error': 'This coupon is not available yet.'}
    if coupon.get('valid_until') and coupon['valid_until'] < now:
        return False, {'error': 'This coupon has expired.'}

    total_cap = coupon.get('usage_limit_total')
    if total_cap is not None and int(coupon.get('used_count') or 0) >= int(total_cap):
        return False, {'error': 'This coupon has been fully claimed.'}

    # Plan restriction
    if (coupon.get('applies_to') or 'all') == 'plans':
        try:
            rows = conn.execute("SELECT plan_id FROM pg_coupon_plans WHERE coupon_id = ?",
                                (coupon['id'],)).fetchall()
            allowed = {r['plan_id'] for r in rows}
        except Exception:
            conn.rollback()
            allowed = set()
        if plan_id is not None and int(plan_id) not in allowed:
            return False, {'error': 'This coupon does not apply to the selected plan.'}

    if user_id:
        per_user = coupon.get('usage_limit_per_user')
        if per_user is not None:
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM pg_coupon_redemptions "
                    "WHERE coupon_id = ? AND user_id = ?",
                    (coupon['id'], user_id)).fetchone()
                if int(row['n'] or 0) >= int(per_user):
                    return False, {'error': 'You have already used this coupon.'}
            except Exception:
                conn.rollback()
        if coupon.get('first_time_only'):
            # Only a real PAID purchase counts as "bought before" — a comp / internal
            # auto-grant / free plan / ₹0 coupon order does not. (2026-10-16)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM pg_subscriptions WHERE user_id = ? "
                    "AND COALESCE(price_paid,0) > 0 AND source IN ('razorpay','prepaid_grant')",
                    (user_id,)).fetchone()
                bought = int(row['n'] or 0) > 0
                if not bought:
                    try:
                        row = conn.execute(
                            "SELECT COUNT(*) AS n FROM pg_orders WHERE user_id = ? "
                            "AND status = 'paid' AND COALESCE(payable,0) > 0", (user_id,)).fetchone()
                        bought = int(row['n'] or 0) > 0
                    except Exception:
                        conn.rollback()   # pg_orders may not exist yet
                if bought:
                    return False, {'error': 'This coupon is for first-time purchases only.'}
            except Exception:
                conn.rollback()

    # Amount + GST — resolve from the plan when the caller didn't pass them.
    if (amount is None or gst_percent is None) and plan_id is not None:
        try:
            row = conn.execute("SELECT price, gst_percent FROM pg_plans WHERE id = ?",
                               (plan_id,)).fetchone()
            if amount is None:
                amount = row['price'] if row else 0
            if gst_percent is None:
                gst_percent = (row['gst_percent'] if row else 0)
        except Exception:
            conn.rollback()
            if amount is None:
                amount = 0
    amount = _money(amount)
    gst_pct = _money(gst_percent or 0)

    min_order = _money(coupon.get('min_order_amount'))
    if min_order > 0 and amount < min_order:
        return False, {'error': f'This coupon needs a minimum order of ₹{min_order:.0f}.'}

    disc = compute_discount(coupon, amount)
    taxable = amount - disc
    gst = (taxable * gst_pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    payable = taxable + gst
    return True, {
        'code': coupon['code'],
        'coupon_id': coupon['id'],
        'description': coupon.get('description') or '',
        'discount_type': coupon.get('discount_type'),
        'discount_value': float(_money(coupon.get('discount_value'))),
        'amount': float(amount),
        'discount': float(disc),
        'taxable': float(taxable),
        'gst_percent': float(gst_pct),
        'gst': float(gst),
        'payable': float(payable),
    }


def redeem(conn, coupon_id, user_id=None, plan_id=None, subscription_id=None,
           order_amount=0, discount_amount=0, code=''):
    """Burn one use. Call ONLY after the payment/grant has actually gone through."""
    try:
        conn.execute(
            "INSERT INTO pg_coupon_redemptions (coupon_id, coupon_code, user_id, "
            "subscription_id, plan_id, order_amount, discount_amount) "
            "VALUES (?,?,?,?,?,?,?)",
            (coupon_id, code, user_id, subscription_id, plan_id,
             float(_money(order_amount)), float(_money(discount_amount))))
        conn.execute("UPDATE pg_coupons SET used_count = COALESCE(used_count,0) + 1 "
                     "WHERE id = ?", (coupon_id,))
        return True
    except Exception as e:
        conn.rollback()
        logging.error("coupons.redeem: %s", e)
        return False
