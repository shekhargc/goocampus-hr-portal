"""Registered Doctors admin — who has signed up on goocampus.in, and what they get.

pg_users fills up on its own (first WhatsApp-OTP login IS the signup) but until now
there was no screen to see any of it. This is that screen: search, filter by free vs
paid, open a profile, grant or extend a plan, and see exactly what they have used.

Granting a plan from here is deliberate and permanent-looking: it writes a real
pg_subscriptions row with source='admin_grant', so a comped account is visible in
the same reports as a paid one and can never be mistaken for revenue.
"""
import logging
from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, flash, abort
from db import get_db
from core.auth import login_required
from core.users import get_user
from pg_admin.data import entitlements

_PER_PAGE = 50
_PERIOD_DAYS = {'monthly': 30, 'quarterly': 90, 'half_yearly': 182, 'yearly': 365}


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


@login_required
def users_admin():
    user = _require_admin()
    if not user:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))

    q = (request.args.get('q') or '').strip()
    f_plan = (request.args.get('plan') or '').strip()      # 'free' | 'paid' | plan code
    f_status = (request.args.get('status') or '').strip()  # 'active' | 'blocked'
    page = max(1, _int_or_none(request.args.get('page')) or 1)

    conn = get_db()
    users, plans = [], []
    stats = {'total': 0, 'paid': 0, 'free': 0, 'blocked': 0, 'new_30d': 0}
    total_pages = 1
    try:
        plans = [dict(r) for r in conn.execute(
            "SELECT id, code, name, plan_kind, price, billing_period, duration_days "
            "FROM pg_plans WHERE COALESCE(is_active,1)=1 ORDER BY sort_order, id"
        ).fetchall()]

        # One LATERAL join gives every doctor their live plan without N+1 queries —
        # this list has to stay fast as signups grow.
        base = ("FROM pg_users u "
                "LEFT JOIN LATERAL ( "
                "  SELECT s.id, s.plan_id, s.status, s.expires_at, s.started_at, "
                "         s.source, p.name AS plan_name, p.code AS plan_code, "
                "         p.plan_kind "
                "  FROM pg_subscriptions s JOIN pg_plans p ON p.id = s.plan_id "
                "  WHERE s.user_id = u.id AND s.status = 'active' "
                "    AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP) "
                "  ORDER BY s.expires_at DESC NULLS FIRST, s.id DESC LIMIT 1 "
                ") sub ON TRUE ")
        conds, params = [], []
        if q:
            conds.append("(u.name ILIKE ? OR u.mobile ILIKE ? OR u.email ILIKE ? "
                         "OR u.college ILIKE ?)")
            params += [f'%{q}%'] * 4
        if f_plan == 'paid':
            conds.append("sub.id IS NOT NULL AND sub.plan_kind = 'paid'")
        elif f_plan == 'free':
            conds.append("(sub.id IS NULL OR sub.plan_kind = 'free')")
        elif f_plan:
            conds.append("sub.plan_code = ?")
            params.append(f_plan)
        if f_status == 'blocked':
            conds.append("COALESCE(u.is_blocked,0) = 1")
        elif f_status == 'active':
            conds.append("COALESCE(u.is_blocked,0) = 0")
        where = (' WHERE ' + ' AND '.join(conds)) if conds else ''

        row = conn.execute(f"SELECT COUNT(*) AS n {base}{where}", tuple(params)).fetchone()
        total = int((row or {}).get('n') or 0)
        total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
        page = min(page, total_pages)

        users = [dict(r) for r in conn.execute(
            f"SELECT u.*, sub.plan_name, sub.plan_code, sub.plan_kind, "
            f"       sub.expires_at AS plan_expires_at, sub.source AS plan_source "
            f"{base}{where} ORDER BY u.id DESC LIMIT {_PER_PAGE} OFFSET {(page-1)*_PER_PAGE}",
            tuple(params)).fetchall()]

        s = conn.execute(
            "SELECT COUNT(*) AS total, "
            "  COALESCE(SUM(CASE WHEN COALESCE(is_blocked,0)=1 THEN 1 ELSE 0 END),0) AS blocked, "
            "  COALESCE(SUM(CASE WHEN created_at > CURRENT_TIMESTAMP - INTERVAL '30 days' "
            "                    THEN 1 ELSE 0 END),0) AS new_30d "
            "FROM pg_users").fetchone()
        paid = conn.execute(
            "SELECT COUNT(DISTINCT s.user_id) AS n FROM pg_subscriptions s "
            "JOIN pg_plans p ON p.id = s.plan_id WHERE s.status='active' "
            "AND p.plan_kind='paid' AND (s.expires_at IS NULL OR "
            "s.expires_at > CURRENT_TIMESTAMP)").fetchone()
        stats = {
            'total': int(s['total'] or 0), 'blocked': int(s['blocked'] or 0),
            'new_30d': int(s['new_30d'] or 0), 'paid': int((paid or {}).get('n') or 0),
        }
        stats['free'] = max(0, stats['total'] - stats['paid'])
    except Exception as e:
        conn.rollback()
        logging.error("users_admin: %s", e)
        flash('Could not load the doctor list.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return render_template('pg_admin/users.html', user=user, users=users,
                           plans=plans, stats=stats, q=q, f_plan=f_plan,
                           f_status=f_status, page=page, total_pages=total_pages,
                           active_section='goocampus_in')


@login_required
def user_detail(user_id):
    """One doctor: profile, plan history, and what they've actually used."""
    admin = _require_admin()
    if not admin:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM pg_users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            abort(404)
        doctor = dict(row)
        subs = [dict(r) for r in conn.execute(
            "SELECT s.*, p.name AS plan_name, p.code AS plan_code, p.plan_kind "
            "FROM pg_subscriptions s LEFT JOIN pg_plans p ON p.id = s.plan_id "
            "WHERE s.user_id = ? ORDER BY s.id DESC", (user_id,)).fetchall()]
        plans = [dict(r) for r in conn.execute(
            "SELECT id, code, name, plan_kind, price, billing_period, duration_days "
            "FROM pg_plans WHERE COALESCE(is_active,1)=1 ORDER BY sort_order, id"
        ).fetchall()]
        ent = entitlements.summary(conn, user_id)
        recent = [dict(r) for r in conn.execute(
            "SELECT feature_code, period_key, item_key, hits, first_used_at, last_used_at "
            "FROM pg_usage_items WHERE user_id = ? ORDER BY last_used_at DESC LIMIT 50",
            (user_id,)).fetchall()]
    except Exception as e:
        conn.rollback()
        logging.error("user_detail: %s", e)
        flash('Could not load that doctor.', 'error')
        return redirect(url_for('pg_users_admin'))
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return render_template('pg_admin/user_detail.html', user=admin, d=doctor,
                           subs=subs, plans=plans, ent=ent, recent=recent,
                           active_section='goocampus_in')


@login_required
def user_save(user_id):
    """Edit the profile fields the team maintains (never the mobile — that is the
    login identity and the OTP is bound to it)."""
    admin = _require_admin()
    if not admin:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    form = request.form
    fields = {
        'name': (form.get('name') or '').strip(),
        'email': (form.get('email') or '').strip(),
        'neet_pg_year': (form.get('neet_pg_year') or '').strip(),
        'neet_pg_rank': _int_or_none(form.get('neet_pg_rank')),
        'target_speciality': (form.get('target_speciality') or '').strip(),
        'city': (form.get('city') or '').strip(),
        'state': (form.get('state') or '').strip(),
        'college': (form.get('college') or '').strip(),
        'source': (form.get('source') or '').strip(),
        'tags': (form.get('tags') or '').strip(),
        'admin_notes': (form.get('admin_notes') or '').strip(),
        'updated_by': admin.get('name') or '',
    }
    conn = get_db()
    try:
        sets = ', '.join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE pg_users SET {sets}, updated_at = CURRENT_TIMESTAMP "
                     "WHERE id = ?", tuple(fields.values()) + (user_id,))
        conn.commit()
        flash('Profile saved.', 'success')
    except Exception as e:
        conn.rollback()
        logging.error("user_save: %s", e)
        flash('Could not save the profile.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_user_detail', user_id=user_id))


@login_required
def user_block(user_id):
    admin = _require_admin()
    if not admin:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        conn.execute("UPDATE pg_users SET is_blocked = CASE WHEN COALESCE(is_blocked,0)=1 "
                     "THEN 0 ELSE 1 END, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (user_id,))
        conn.commit()
        flash('Access updated.', 'success')
    except Exception as e:
        conn.rollback()
        logging.error("user_block: %s", e)
        flash('Could not update access.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_user_detail', user_id=user_id))


@login_required
def user_grant_plan(user_id):
    """Put a doctor on a plan by hand — for a comp, a refund fix, or a sale closed
    over the phone before online payment exists."""
    admin = _require_admin()
    if not admin:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))

    plan_id = _int_or_none(request.form.get('plan_id'))
    if not plan_id:
        flash('Choose a plan first.', 'error')
        return redirect(url_for('pg_user_detail', user_id=user_id))

    conn = get_db()
    try:
        plan = conn.execute("SELECT * FROM pg_plans WHERE id = ?", (plan_id,)).fetchone()
        if not plan:
            flash('Plan not found.', 'error')
            return redirect(url_for('pg_user_detail', user_id=user_id))
        plan = dict(plan)

        days = _int_or_none(request.form.get('duration_days'))
        if days is None:
            days = plan.get('duration_days') or _PERIOD_DAYS.get(plan.get('billing_period'))
        expires = (datetime.utcnow() + timedelta(days=int(days))) if days else None

        # Only one plan can be live at a time, or entitlements become ambiguous.
        conn.execute("UPDATE pg_subscriptions SET status = 'cancelled', "
                     "cancelled_at = CURRENT_TIMESTAMP WHERE user_id = ? "
                     "AND status = 'active'", (user_id,))
        conn.execute(
            "INSERT INTO pg_subscriptions (user_id, plan_id, status, expires_at, "
            "price_paid, source, notes, granted_by) VALUES (?,?,?,?,?,?,?,?)",
            (user_id, plan_id, 'active', expires, 0, 'admin_grant',
             (request.form.get('notes') or '').strip(), admin.get('name') or ''))
        conn.commit()
        when = expires.strftime('%d %b %Y') if expires else 'no expiry'
        flash(f"{plan['name']} granted ({when}).", 'success')
    except Exception as e:
        conn.rollback()
        logging.error("user_grant_plan: %s", e)
        flash('Could not grant the plan.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_user_detail', user_id=user_id))


@login_required
def subscription_cancel(sub_id):
    admin = _require_admin()
    if not admin:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    uid = None
    try:
        row = conn.execute("SELECT user_id FROM pg_subscriptions WHERE id = ?",
                           (sub_id,)).fetchone()
        uid = (row or {}).get('user_id')
        conn.execute("UPDATE pg_subscriptions SET status = 'cancelled', "
                     "cancelled_at = CURRENT_TIMESTAMP WHERE id = ?", (sub_id,))
        conn.commit()
        flash('Subscription cancelled — the doctor drops back to the free plan.',
              'success')
    except Exception as e:
        conn.rollback()
        logging.error("subscription_cancel: %s", e)
        flash('Could not cancel that subscription.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_user_detail', user_id=uid) if uid
                    else url_for('pg_users_admin'))


@login_required
def user_reset_usage(user_id):
    """Clear a doctor's counters — the support fix for "it says I've used my 3 PDFs
    but I only opened one"."""
    admin = _require_admin()
    if not admin:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    code = (request.form.get('feature_code') or '').strip()
    conn = get_db()
    try:
        if code:
            conn.execute("DELETE FROM pg_usage_items WHERE user_id = ? AND "
                         "feature_code = ?", (user_id, code))
        else:
            conn.execute("DELETE FROM pg_usage_items WHERE user_id = ?", (user_id,))
        conn.commit()
        flash('Usage reset.', 'success')
    except Exception as e:
        conn.rollback()
        logging.error("user_reset_usage: %s", e)
        flash('Could not reset usage.', 'error')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return redirect(url_for('pg_user_detail', user_id=user_id))
