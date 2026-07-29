"""Coupon admin — create discount codes and watch how they're used.

Built before Razorpay exists (founder 2026-07-28) so the codes, rules and reporting
are ready and tested the day the keys arrive. The discount maths lives in
pg_admin/data/coupons.py; this file is the screen around it.
"""
import logging
import random
import string
from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, jsonify
from db import get_db
from core.auth import login_required
from core.users import get_user
from pg_admin.data import coupons as coupon_lib


def _require_admin():
    user = get_user()
    if not user or not user.get('is_admin'):
        return None
    return user


def _int_or_none(raw):
    raw = (str(raw) if raw is not None else '').strip()
    if raw == '':
        return None
    try:
        return int(float(raw))
    except Exception:
        return None


def _num_or_none(raw):
    raw = (str(raw) if raw is not None else '').strip()
    if raw == '':
        return None
    try:
        return float(raw)
    except Exception:
        return None


def _dt_or_none(raw):
    """<input type="datetime-local"> gives 'YYYY-MM-DDTHH:MM'; a plain date is fine too."""
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _clean_code(raw):
    out = ''.join(ch for ch in (raw or '').upper() if ch.isalnum() or ch in '-_')
    return out[:32]


@login_required
def coupons_admin():
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))

    q = (request.args.get('q') or '').strip()
    f_state = (request.args.get('state') or '').strip()   # live | scheduled | expired | off

    conn = get_db()
    rows, plans, coupon_plans = [], [], {}
    stats = {'total': 0, 'live': 0, 'redemptions': 0, 'discount_given': 0.0}
    try:
        plans = [dict(r) for r in conn.execute(
            "SELECT id, code, name, price FROM pg_plans WHERE COALESCE(is_active,1)=1 "
            "ORDER BY sort_order, id").fetchall()]
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM pg_coupons ORDER BY id DESC").fetchall()]
        for r in conn.execute("SELECT coupon_id, plan_id FROM pg_coupon_plans").fetchall():
            coupon_plans.setdefault(r['coupon_id'], []).append(r['plan_id'])

        now = datetime.utcnow()
        view = []
        for c in rows:
            c['plan_ids'] = coupon_plans.get(c['id'], [])
            if not c.get('is_active'):
                state = 'off'
            elif c.get('valid_from') and c['valid_from'] > now:
                state = 'scheduled'
            elif c.get('valid_until') and c['valid_until'] < now:
                state = 'expired'
            elif (c.get('usage_limit_total') is not None
                  and int(c.get('used_count') or 0) >= int(c['usage_limit_total'])):
                state = 'exhausted'
            else:
                state = 'live'
            c['state'] = state
            if not q or q.upper() in (c['code'] or '').upper() \
                    or q.lower() in (c.get('description') or '').lower():
                if not f_state or f_state == state:
                    view.append(c)
        rows = view

        agg = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(discount_amount),0) AS d "
            "FROM pg_coupon_redemptions").fetchone()
        stats = {
            'total': len(rows),
            'live': sum(1 for c in rows if c['state'] == 'live'),
            'redemptions': int((agg or {}).get('n') or 0),
            'discount_given': float((agg or {}).get('d') or 0),
        }
    except Exception as e:
        conn.rollback()
        logging.error("coupons_admin: %s", e)
        flash('Could not load coupons.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return render_template('pg_admin/coupons.html', user=user, coupons=rows,
                           plans=plans, stats=stats, q=q, f_state=f_state,
                           active_section='goocampus_in')


@login_required
def coupon_save():
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))

    form = request.form
    edit_id = _int_or_none(form.get('edit_id'))
    code = _clean_code(form.get('code'))
    if not code:
        code = 'GC' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

    dtype = (form.get('discount_type') or 'percent').strip()
    dtype = dtype if dtype in ('percent', 'fixed') else 'percent'
    value = _num_or_none(form.get('discount_value')) or 0
    if dtype == 'percent':
        value = max(0.0, min(100.0, value))   # a 150% discount would pay the doctor

    applies_to = (form.get('applies_to') or 'all').strip()
    applies_to = applies_to if applies_to in ('all', 'plans') else 'all'

    fields = {
        'description': (form.get('description') or '').strip(),
        'discount_type': dtype,
        'discount_value': value,
        'max_discount_amount': _num_or_none(form.get('max_discount_amount')),
        'min_order_amount': _num_or_none(form.get('min_order_amount')) or 0,
        'valid_from': _dt_or_none(form.get('valid_from')),
        'valid_until': _dt_or_none(form.get('valid_until')),
        'usage_limit_total': _int_or_none(form.get('usage_limit_total')),
        'usage_limit_per_user': _int_or_none(form.get('usage_limit_per_user')),
        'applies_to': applies_to,
        'first_time_only': 1 if form.get('first_time_only') else 0,
        'is_active': 1 if form.get('is_active') else 0,
    }

    conn = get_db()
    try:
        if edit_id:
            sets = ', '.join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE pg_coupons SET {sets}, updated_at = CURRENT_TIMESTAMP "
                         "WHERE id = ?", tuple(fields.values()) + (edit_id,))
            coupon_id = edit_id
        else:
            if conn.execute("SELECT 1 FROM pg_coupons WHERE UPPER(code) = ?",
                            (code,)).fetchone():
                flash(f'A coupon with the code {code} already exists.', 'error')
                return redirect(url_for('pg_coupons_admin'))
            cols = ['code'] + list(fields.keys()) + ['created_by']
            vals = [code] + list(fields.values()) + [user.get('name') or '']
            conn.execute(f"INSERT INTO pg_coupons ({', '.join(cols)}) VALUES "
                         f"({', '.join('?' * len(cols))})", tuple(vals))
            coupon_id = conn.execute("SELECT id FROM pg_coupons WHERE code = ?",
                                     (code,)).fetchone()['id']

        conn.execute("DELETE FROM pg_coupon_plans WHERE coupon_id = ?", (coupon_id,))
        if applies_to == 'plans':
            for pid in form.getlist('plan_ids'):
                p = _int_or_none(pid)
                if p:
                    conn.execute("INSERT INTO pg_coupon_plans (coupon_id, plan_id) "
                                 "VALUES (?,?) ON CONFLICT DO NOTHING", (coupon_id, p))
        conn.commit()
        flash(f'Coupon {code} saved.', 'success')
    except Exception as e:
        conn.rollback()
        logging.error("coupon_save: %s", e)
        flash(f'Could not save the coupon: {e}', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_coupons_admin'))


@login_required
def coupon_toggle(coupon_id):
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        conn.execute("UPDATE pg_coupons SET is_active = CASE WHEN COALESCE(is_active,1)=1 "
                     "THEN 0 ELSE 1 END, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (coupon_id,))
        conn.commit()
        flash('Coupon updated.', 'success')
    except Exception as e:
        conn.rollback()
        logging.error("coupon_toggle: %s", e)
        flash('Could not update the coupon.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_coupons_admin'))


@login_required
def coupon_delete(coupon_id):
    """Refused once redeemed — the redemption history is the record of a discount
    actually given, and deleting the coupon would orphan it."""
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM pg_coupon_redemptions "
                           "WHERE coupon_id = ?", (coupon_id,)).fetchone()
        if int((row or {}).get('n') or 0) > 0:
            conn.execute("UPDATE pg_coupons SET is_active = 0 WHERE id = ?", (coupon_id,))
            conn.commit()
            flash('That coupon has been used, so it was switched off instead of '
                  'deleted — the redemption history stays.', 'info')
        else:
            conn.execute("DELETE FROM pg_coupon_plans WHERE coupon_id = ?", (coupon_id,))
            conn.execute("DELETE FROM pg_coupons WHERE id = ?", (coupon_id,))
            conn.commit()
            flash('Coupon deleted.', 'success')
    except Exception as e:
        conn.rollback()
        logging.error("coupon_delete: %s", e)
        flash('Could not delete the coupon.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_coupons_admin'))


@login_required
def coupon_redemptions(coupon_id):
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    coupon, rows = None, []
    try:
        c = conn.execute("SELECT * FROM pg_coupons WHERE id = ?", (coupon_id,)).fetchone()
        coupon = dict(c) if c else None
        rows = [dict(r) for r in conn.execute(
            "SELECT r.*, u.name AS user_name, u.mobile, p.name AS plan_name "
            "FROM pg_coupon_redemptions r "
            "LEFT JOIN pg_users u ON u.id = r.user_id "
            "LEFT JOIN pg_plans p ON p.id = r.plan_id "
            "WHERE r.coupon_id = ? ORDER BY r.id DESC", (coupon_id,)).fetchall()]
    except Exception as e:
        conn.rollback()
        logging.error("coupon_redemptions: %s", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not coupon:
        flash('Coupon not found.', 'error')
        return redirect(url_for('pg_coupons_admin'))
    return render_template('pg_admin/coupon_redemptions.html', user=user,
                           coupon=coupon, rows=rows, active_section='goocampus_in')


@login_required
def coupon_preview():
    """Live 'what would this actually cost' check inside the editor, so the founder
    can see the real payable figure before a doctor ever sees the code."""
    if not _require_admin():
        return jsonify({'ok': False}), 403
    code = (request.args.get('code') or '').strip()
    plan_id = _int_or_none(request.args.get('plan_id'))
    conn = get_db()
    try:
        ok, res = coupon_lib.validate(conn, code, plan_id=plan_id)
        return jsonify({'ok': ok, 'result': res})
    finally:
        try:
            conn.close()
        except Exception:
            pass
