"""Pricing & Plans admin — design a plan and decide exactly what it unlocks.

One screen does the whole job (founder 2026-07-28): the list of plans with a live
card preview of how each will look on the site, and an editor where every plan is
fully customisable — price, struck-through "was" price, Bestseller ribbon, colour,
selling-point bullets — plus the feature matrix that decides what the plan actually
gives (predictor states, PDFs, mentor sessions, ...).

The feature matrix is driven by the pg_features catalogue, so it grows a new row on
its own whenever a new gateable thing is added. See pg_admin/data/plans_tables.py.
"""
import json
import logging
from flask import render_template, request, redirect, url_for, flash, jsonify
from db import get_db
from core.auth import login_required
from core.users import get_user
from pg_admin.data import entitlements

_PLAN_KINDS = ('free', 'paid')
_BILLING = ('one_time', 'monthly', 'quarterly', 'half_yearly', 'yearly', 'lifetime')
_BILLING_LABELS = {
    'one_time': 'One-time', 'monthly': 'Monthly', 'quarterly': 'Quarterly',
    'half_yearly': 'Half-yearly', 'yearly': 'Yearly', 'lifetime': 'Lifetime',
}
# How long access lasts when the founder doesn't set an explicit duration.
_PERIOD_DAYS = {'monthly': 30, 'quarterly': 90, 'half_yearly': 182, 'yearly': 365}
_VALUE_TYPES = ('off', 'limited', 'unlimited')


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


def _slug(raw):
    out = []
    for ch in (raw or '').lower().strip():
        if ch.isalnum():
            out.append(ch)
        elif ch in ' -_' and out and out[-1] != '_':
            out.append('_')
    return ''.join(out).strip('_') or 'plan'


def _as_list(raw):
    if isinstance(raw, list):
        return raw
    try:
        out = json.loads(raw or '[]')
        return out if isinstance(out, list) else []
    except Exception:
        return []


def plans_admin():
    """List + editor. Everything a plan needs is on this one page."""
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))

    conn = get_db()
    plans, features, matrix = [], [], {}
    stats = {'total': 0, 'active': 0, 'paid': 0, 'subscribers': 0}
    try:
        plans = [dict(r) for r in conn.execute(
            "SELECT * FROM pg_plans ORDER BY sort_order, id").fetchall()]
        features = [dict(r) for r in conn.execute(
            "SELECT * FROM pg_features WHERE COALESCE(is_active,1)=1 "
            "ORDER BY sort_order, id").fetchall()]
        for r in conn.execute("SELECT * FROM pg_plan_features").fetchall():
            matrix.setdefault(r['plan_id'], {})[r['feature_code']] = dict(r)
        # Live subscriber count per plan — the founder's first question about any
        # plan is "how many people are on it".
        counts = {}
        for r in conn.execute(
                "SELECT plan_id, COUNT(*) AS n FROM pg_subscriptions "
                "WHERE status='active' AND (expires_at IS NULL OR "
                "expires_at > CURRENT_TIMESTAMP) GROUP BY plan_id").fetchall():
            counts[r['plan_id']] = r['n']
        for p in plans:
            p['subscribers'] = counts.get(p['id'], 0)
            p['highlights_list'] = _as_list(p.get('highlights'))
            p['features'] = matrix.get(p['id'], {})
        stats = {
            'total': len(plans),
            'active': sum(1 for p in plans if p.get('is_active')),
            'paid': sum(1 for p in plans if (p.get('plan_kind') or '') == 'paid'),
            'subscribers': sum(counts.values()),
        }
    except Exception as e:
        conn.rollback()
        logging.error("plans_admin: %s", e)
        flash('Could not load plans.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return render_template('pg_admin/plans.html', user=user, plans=plans,
                           features=features, billing=_BILLING,
                           billing_labels=_BILLING_LABELS, plan_kinds=_PLAN_KINDS,
                           value_types=_VALUE_TYPES, stats=stats,
                           active_section='goocampus_in')


def plan_save():
    """Create or update a plan AND its whole feature matrix in one transaction.

    Saving the matrix as one unit matters: a half-saved plan would silently give
    away or withhold access, and nobody would notice until a doctor complained.
    """
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))

    form = request.form
    edit_id = _int_or_none(form.get('edit_id'))
    name = (form.get('name') or '').strip()
    if not name:
        flash('Plan name is required.', 'error')
        return redirect(url_for('pg_plans_admin'))

    kind = (form.get('plan_kind') or 'paid').strip()
    if kind not in _PLAN_KINDS:
        kind = 'paid'
    billing = (form.get('billing_period') or 'one_time').strip()
    if billing not in _BILLING:
        billing = 'one_time'

    duration = _int_or_none(form.get('duration_days'))
    if duration is None:
        duration = _PERIOD_DAYS.get(billing)   # blank = derive from the billing period

    price = _num_or_none(form.get('price')) or 0
    compare = _num_or_none(form.get('compare_at_price'))
    # A "was" price that isn't higher than the price shows a nonsense discount on
    # the site, so drop it rather than render "was ₹99, now ₹499".
    if compare is not None and compare <= price:
        compare = None

    highlights = [h.strip() for h in (form.get('highlights') or '').splitlines()
                  if h.strip()]

    code = (form.get('code') or '').strip() or _slug(name)

    fields = {
        'name': name,
        'tagline': (form.get('tagline') or '').strip(),
        'description': (form.get('description') or '').strip(),
        'plan_kind': kind,
        'price': price,
        'compare_at_price': compare,
        'currency': (form.get('currency') or 'INR').strip() or 'INR',
        'billing_period': billing,
        'duration_days': duration,
        'badge_text': (form.get('badge_text') or '').strip(),
        'badge_color': (form.get('badge_color') or '#F57C1F').strip(),
        'accent_color': (form.get('accent_color') or '#2952A3').strip(),
        'is_featured': 1 if form.get('is_featured') else 0,
        'highlights': json.dumps(highlights),
        'cta_label': (form.get('cta_label') or '').strip(),
        'seats_limit': _int_or_none(form.get('seats_limit')),
        'razorpay_plan_id': (form.get('razorpay_plan_id') or '').strip(),
        'is_active': 1 if form.get('is_active') else 0,
        'is_public': 1 if form.get('is_public') else 0,
        'sort_order': _int_or_none(form.get('sort_order')) or 100,
    }

    conn = get_db()
    try:
        if edit_id:
            sets = ', '.join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE pg_plans SET {sets}, updated_at = CURRENT_TIMESTAMP "
                         "WHERE id = ?", tuple(fields.values()) + (edit_id,))
            plan_id = edit_id
        else:
            # A duplicate code would collide on the unique index — make it unique.
            base, n = code, 2
            while conn.execute("SELECT 1 FROM pg_plans WHERE code = ?",
                               (code,)).fetchone():
                code, n = f"{base}_{n}", n + 1
            cols = ['code'] + list(fields.keys()) + ['created_by']
            vals = [code] + list(fields.values()) + [user.get('name') or '']
            conn.execute(f"INSERT INTO pg_plans ({', '.join(cols)}) VALUES "
                         f"({', '.join('?' * len(cols))})", tuple(vals))
            plan_id = conn.execute("SELECT id FROM pg_plans WHERE code = ?",
                                   (code,)).fetchone()['id']

        # ── the feature matrix ────────────────────────────────────────────────
        feats = conn.execute(
            "SELECT code, unit FROM pg_features WHERE COALESCE(is_active,1)=1"
        ).fetchall()
        for f in feats:
            fcode = f['code']
            vtype = (form.get(f'feat_{fcode}_type') or 'off').strip()
            if vtype not in _VALUE_TYPES:
                vtype = 'off'
            limit = _int_or_none(form.get(f'feat_{fcode}_limit'))
            if f['unit'] == 'boolean':
                limit = None
            note = (form.get(f'feat_{fcode}_note') or '').strip()
            if vtype == 'off':
                conn.execute("DELETE FROM pg_plan_features WHERE plan_id = ? "
                             "AND feature_code = ?", (plan_id, fcode))
            else:
                conn.execute(
                    "INSERT INTO pg_plan_features (plan_id, feature_code, value_type, "
                    "limit_value, note) VALUES (?,?,?,?,?) "
                    "ON CONFLICT (plan_id, feature_code) DO UPDATE SET "
                    "value_type = EXCLUDED.value_type, limit_value = EXCLUDED.limit_value, "
                    "note = EXCLUDED.note",
                    (plan_id, fcode, vtype, limit, note))

        conn.commit()
        flash(f'Plan "{name}" saved.', 'success')
    except Exception as e:
        conn.rollback()
        logging.error("plan_save: %s", e)
        flash(f'Could not save the plan: {e}', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_plans_admin'))


def plan_toggle(plan_id):
    """Activate / deactivate. Deactivating hides it from the site but leaves every
    existing subscriber's history intact — never delete a plan people have paid for."""
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        conn.execute("UPDATE pg_plans SET is_active = CASE WHEN COALESCE(is_active,1)=1 "
                     "THEN 0 ELSE 1 END, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (plan_id,))
        conn.commit()
        flash('Plan updated.', 'success')
    except Exception as e:
        conn.rollback()
        logging.error("plan_toggle: %s", e)
        flash('Could not update the plan.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_plans_admin'))


def plan_delete(plan_id):
    """Delete — refused when anyone has ever been on the plan.

    Deleting a plan with subscribers would orphan their entitlements and destroy
    the record of what they bought, so we deactivate instead and say so.
    """
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM pg_subscriptions WHERE plan_id = ?",
                           (plan_id,)).fetchone()
        if int((row or {}).get('n') or 0) > 0:
            conn.execute("UPDATE pg_plans SET is_active = 0 WHERE id = ?", (plan_id,))
            conn.commit()
            flash('That plan has subscribers, so it was deactivated instead of '
                  'deleted — their records stay intact.', 'info')
        else:
            conn.execute("DELETE FROM pg_plan_features WHERE plan_id = ?", (plan_id,))
            conn.execute("DELETE FROM pg_coupon_plans WHERE plan_id = ?", (plan_id,))
            conn.execute("DELETE FROM pg_plans WHERE id = ?", (plan_id,))
            conn.commit()
            flash('Plan deleted.', 'success')
    except Exception as e:
        conn.rollback()
        logging.error("plan_delete: %s", e)
        flash('Could not delete the plan.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_plans_admin'))


def plan_duplicate(plan_id):
    """Copy a plan, features and all — the fastest way to build a tier ladder."""
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        src = conn.execute("SELECT * FROM pg_plans WHERE id = ?", (plan_id,)).fetchone()
        if not src:
            flash('Plan not found.', 'error')
            return redirect(url_for('pg_plans_admin'))
        src = dict(src)
        base = f"{src['code']}_copy"
        code, n = base, 2
        while conn.execute("SELECT 1 FROM pg_plans WHERE code = ?", (code,)).fetchone():
            code, n = f"{base}{n}", n + 1
        cols = [c for c in src.keys() if c not in ('id', 'created_at', 'updated_at',
                                                   'code', 'name', 'is_public')]
        vals = [src[c] for c in cols]
        conn.execute(
            f"INSERT INTO pg_plans (code, name, is_public, {', '.join(cols)}) "
            f"VALUES (?,?,?,{', '.join('?' * len(cols))})",
            tuple([code, f"{src['name']} (copy)", 0] + vals))
        new_id = conn.execute("SELECT id FROM pg_plans WHERE code = ?",
                              (code,)).fetchone()['id']
        conn.execute(
            "INSERT INTO pg_plan_features (plan_id, feature_code, value_type, "
            "limit_value, note) SELECT ?, feature_code, value_type, limit_value, note "
            "FROM pg_plan_features WHERE plan_id = ?", (new_id, plan_id))
        conn.commit()
        flash('Plan duplicated — it starts hidden from the site so you can edit it '
              'first.', 'success')
    except Exception as e:
        conn.rollback()
        logging.error("plan_duplicate: %s", e)
        flash('Could not duplicate the plan.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_plans_admin'))


def feature_save():
    """Add or edit a catalogue entry — this is how a NEW gateable thing appears in
    every plan editor without a deploy."""
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    form = request.form
    name = (form.get('name') or '').strip()
    if not name:
        flash('Feature name is required.', 'error')
        return redirect(url_for('pg_plans_admin'))
    edit_id = _int_or_none(form.get('feature_edit_id'))
    unit = (form.get('unit') or 'quota').strip()
    unit = unit if unit in ('boolean', 'quota') else 'quota'
    reset = (form.get('reset_period') or 'lifetime').strip()
    reset = reset if reset in ('lifetime', 'monthly', 'daily', 'plan_period') else 'lifetime'

    conn = get_db()
    try:
        if edit_id:
            # code is deliberately NOT editable — it's the key every gate refers to,
            # and renaming it would silently unlock or lock features in live plans.
            conn.execute(
                "UPDATE pg_features SET name = ?, description = ?, unit = ?, "
                "reset_period = ?, resource_kind = ?, sort_order = ?, is_active = ? "
                "WHERE id = ?",
                (name, (form.get('description') or '').strip(), unit, reset,
                 (form.get('resource_kind') or '').strip(),
                 _int_or_none(form.get('sort_order')) or 100,
                 1 if form.get('is_active') else 0, edit_id))
        else:
            code = _slug(form.get('code') or name)
            base, n = code, 2
            while conn.execute("SELECT 1 FROM pg_features WHERE code = ?",
                               (code,)).fetchone():
                code, n = f"{base}_{n}", n + 1
            conn.execute(
                "INSERT INTO pg_features (code, name, description, unit, reset_period, "
                "resource_kind, sort_order, is_active) VALUES (?,?,?,?,?,?,?,1)",
                (code, name, (form.get('description') or '').strip(), unit, reset,
                 (form.get('resource_kind') or '').strip(),
                 _int_or_none(form.get('sort_order')) or 100))
        conn.commit()
        flash('Feature saved. Set what each plan gives on the plan editor.', 'success')
    except Exception as e:
        conn.rollback()
        logging.error("feature_save: %s", e)
        flash('Could not save the feature.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_plans_admin'))


@login_required
def plan_compare():
    """JSON the page uses to render the side-by-side comparison table."""
    if not _require_admin():
        return jsonify({'ok': False}), 403
    conn = get_db()
    try:
        plans = [dict(r) for r in conn.execute(
            "SELECT id, code, name, price, plan_kind FROM pg_plans "
            "WHERE COALESCE(is_active,1)=1 ORDER BY sort_order, id").fetchall()]
        feats = [dict(r) for r in conn.execute(
            "SELECT code, name, unit FROM pg_features WHERE COALESCE(is_active,1)=1 "
            "ORDER BY sort_order, id").fetchall()]
        matrix = {}
        for r in conn.execute("SELECT * FROM pg_plan_features").fetchall():
            matrix.setdefault(r['plan_id'], {})[r['feature_code']] = {
                'value_type': r['value_type'], 'limit': r['limit_value']}
        for p in plans:
            p['price'] = float(p['price'] or 0)
            p['features'] = matrix.get(p['id'], {})
        return jsonify({'ok': True, 'plans': plans, 'features': feats})
    except Exception as e:
        conn.rollback()
        logging.error("plan_compare: %s", e)
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass
