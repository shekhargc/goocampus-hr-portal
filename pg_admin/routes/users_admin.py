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

        # goocampus.in signup captures only the mobile (its OTP signup asks no
        # name), so many pg_users have a blank name → the list showed "Unnamed".
        # Fill the DISPLAYED name from a matching counselling-form lead
        # (sales_leads by last-10 of the mobile) — display only, we never write
        # back to the synced pg_users row.
        def _m10(s):
            d = ''.join(ch for ch in (s or '') if ch.isdigit())
            return d[-10:] if len(d) >= 10 else ''
        _need = [u for u in users if not (u.get('name') or '').strip()]
        want = {_m10(u.get('mobile')) for u in _need if _m10(u.get('mobile'))}
        if want:
            ph = ','.join(['?'] * len(want))
            lead_names = {}
            try:
                for r in conn.execute(
                    f"SELECT RIGHT(regexp_replace(COALESCE(phone,''),'[^0-9]','','g'),10) AS m10, "
                    f"       MAX(lead_name) AS lead_name FROM sales_leads "
                    f"WHERE COALESCE(lead_name,'')<>'' "
                    f"  AND RIGHT(regexp_replace(COALESCE(phone,''),'[^0-9]','','g'),10) IN ({ph}) "
                    f"GROUP BY 1", tuple(want)).fetchall():
                    if r['lead_name']:
                        lead_names[r['m10']] = r['lead_name']
            except Exception:
                lead_names = {}
            for u in _need:
                u['name'] = lead_names.get(_m10(u.get('mobile')), '')

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
        # Saved colleges (star) for this doctor — keyed to the unified college master.
        try:
            favorites = [dict(r) for r in conn.execute(
                "SELECT m.id, m.college_name, m.kind, m.city, m.state, m.college_type, f.added_at "
                "FROM pg_college_favorites f JOIN pg_college_master m ON m.id = f.master_id "
                "WHERE f.user_id = ? ORDER BY f.added_at DESC", (user_id,)).fetchall()]
        except Exception:
            conn.rollback(); favorites = []

        # Counselling states the doctor has locked (home + plan-allowed extras).
        try:
            states = [dict(r) for r in conn.execute(
                "SELECT state, role, locked, created_at FROM pg_doctor_states "
                "WHERE user_id = ? ORDER BY (role='home') DESC, created_at", (user_id,)).fetchall()]
        except Exception:
            conn.rollback(); states = []

        # Choice sheets the doctor has built — each set carries its 3 round sheets.
        choice_sets = []
        try:
            _sets = [dict(r) for r in conn.execute(
                "SELECT * FROM pg_choice_sets WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)).fetchall()]
            _items = [dict(r) for r in conn.execute(
                "SELECT i.* FROM pg_choice_items i JOIN pg_choice_sets s ON s.id = i.set_id "
                "WHERE s.user_id = ? ORDER BY i.set_id, i.round, i.position, i.id",
                (user_id,)).fetchall()]
            import json as _json
            def _parse(v, dflt):
                try: return _json.loads(v) if v else dflt
                except Exception: return dflt
            for s in _sets:
                s['specialties'] = _parse(s.get('specialties'), [])
                s['quota_categories'] = _parse(s.get('quota_categories'), [])
                s['rounds'] = {1: [], 2: [], 3: []}
                s['total'] = 0
                choice_sets.append(s)
            _by_id = {s['id']: s for s in choice_sets}
            for it in _items:
                s = _by_id.get(it['set_id'])
                if not s:
                    continue
                s['rounds'].setdefault(it['round'], []).append(it)
                s['total'] += 1
        except Exception:
            conn.rollback(); choice_sets = []

        # JSON-safe copy for the editable in-page UI (renders + re-renders from JS).
        def _item_json(it):
            return {'id': it['id'], 'position': it['position'], 'master_id': it.get('master_id'),
                    'institute': it.get('institute') or '', 'course': it.get('course') or '',
                    'quota': it.get('quota') or '', 'category': it.get('category') or '',
                    'closing_rank': it.get('closing_rank'), 'chance': it.get('chance') or '',
                    'added_by': it.get('added_by') or 'client',
                    'added_by_name': it.get('added_by_name') or ''}
        choice_json = []
        for s in choice_sets:
            choice_json.append({
                'id': s['id'], 'label': s.get('label') or '', 'scope': s.get('scope') or 'mcc',
                'state': s.get('state') or '', 'authority': s.get('authority') or '',
                'rank': s.get('rank'), 'degree_group': s.get('degree_group') or 'mdms',
                'specialties': s.get('specialties') or [], 'total': s.get('total') or 0,
                'team_edited_at': str(s['team_edited_at'])[:16] if s.get('team_edited_at') else '',
                'team_edited_by': s.get('team_edited_by') or '',
                'rounds': {str(r): [_item_json(it) for it in s['rounds'].get(r, [])] for r in (1, 2, 3)},
            })

        # If this doctor was invited into Indian PGCP, surface the invitation + onboarding.
        pgcp_inv = None
        try:
            digits = ''.join(ch for ch in (doctor.get('mobile') or '') if ch.isdigit())[-10:]
            if digits:
                r = conn.execute(
                    "SELECT i.id, i.client_name, i.client_type, i.status, i.invited_amount, i.discount, "
                    "o.step AS onb_step, o.status AS onb_status, o.submitted_at AS onb_submitted "
                    "FROM pg_pgcp_invitations i "
                    "LEFT JOIN pg_pgcp_onboarding o ON o.invitation_id = i.id "
                    "WHERE RIGHT(regexp_replace(COALESCE(i.mobile,''),'\\D','','g'),10) = ? "
                    "ORDER BY i.created_at DESC LIMIT 1", (digits,)).fetchone()
                pgcp_inv = dict(r) if r else None
        except Exception:
            conn.rollback(); pgcp_inv = None
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

    import json as _json2
    # Free-tier clients own their home-state list — the team is view-only on it.
    try:
        choice_team_editable = bool((ent.get('features') or {}).get('dash_choice_list', {}).get('allowed'))
    except Exception:
        choice_team_editable = False
    return render_template('pg_admin/user_detail.html', user=admin, d=doctor,
                           subs=subs, plans=plans, ent=ent, recent=recent,
                           favorites=favorites, states=states, choice_sets=choice_sets,
                           choice_json=_json2.dumps(choice_json), pgcp_inv=pgcp_inv,
                           choice_team_editable=choice_team_editable,
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
        'neet_pg_score': _int_or_none(form.get('neet_pg_score')),
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
        try:
            conn.execute("ALTER TABLE pg_users ADD COLUMN IF NOT EXISTS neet_pg_score INTEGER")
            conn.commit()
        except Exception:
            conn.rollback()
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


def plan_diag():
    """GET /admin/pg/diag/plan?mobile=… — every pg_users row for a mobile + each one's
    active plan. Reveals duplicate accounts / which record got the grant. (founder 2026-09-22)"""
    import re as _re
    admin = _require_admin()
    if not admin:
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    from flask import Response
    # ── Token lookup: what user + plan does the goocampus.in session token resolve to? ──
    token = (request.args.get('token') or '').strip()
    if token:
        from pg_admin.routes.api import _pg_user_by_token
        conn = get_db()
        out = [f"Token lookup: …{token[-8:]}"]
        try:
            u = _pg_user_by_token(conn, token)
            if not u:
                out.append("→ TOKEN INVALID/EXPIRED. The API would return 401 → the frontend falls "
                           "back to Free. Re-login on goocampus.in to mint a fresh token.")
            else:
                u = dict(u)
                out.append(f"→ resolves to user_id={u.get('id')}  name={u.get('name')!r}  "
                           f"mobile={u.get('mobile')!r}")
                sub = conn.execute(
                    "SELECT s.status, p.name AS plan_name, p.code AS plan_code, p.plan_kind "
                    "FROM pg_subscriptions s JOIN pg_plans p ON p.id = s.plan_id "
                    "WHERE s.user_id = ? AND s.status='active' "
                    "AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP) "
                    "ORDER BY s.id DESC LIMIT 1", [u['id']]).fetchone()
                if sub:
                    sub = dict(sub)
                    out.append(f"→ THIS TOKEN'S PLAN: {sub['plan_name']} ({sub['plan_code']}, "
                               f"kind={sub['plan_kind']})  ← what /api/pg/entitlements returns for it")
                else:
                    out.append("→ THIS TOKEN'S PLAN: Free (no active paid subscription on this user)."
                               "  If this user_id is NOT the one you granted Starter to, that's the bug.")
        finally:
            conn.close()
        return Response("\n".join(out), mimetype='text/plain')
    mobile = (request.args.get('mobile') or '').strip()
    digits = _re.sub(r'\D', '', mobile)[-10:]
    conn = get_db()
    rows = []
    try:
        users = conn.execute(
            "SELECT id, name, mobile, email, created_at FROM pg_users "
            "WHERE RIGHT(regexp_replace(COALESCE(mobile,''),'\\D','','g'),10) = ? ORDER BY id",
            [digits]).fetchall() if digits else []
        for u in users:
            subs = [dict(s) for s in conn.execute(
                "SELECT s.id, s.status, s.expires_at, s.source, s.created_at, p.name AS plan_name, "
                "p.code AS plan_code FROM pg_subscriptions s LEFT JOIN pg_plans p ON p.id = s.plan_id "
                "WHERE s.user_id = ? ORDER BY s.id DESC", [u['id']]).fetchall()]
            active = next((x for x in subs if x['status'] == 'active'
                           and (x['expires_at'] is None or True)), None)
            rows.append({'user': dict(u), 'active': active, 'subs': subs})
    finally:
        conn.close()
    # plain-text so it's readable without a template
    out = [f"Mobile query: {mobile}  (matching last-10: {digits})",
           f"pg_users records found: {len(rows)}", ""]
    for r in rows:
        u = r['user']
        out.append(f"• user_id={u['id']}  name={u.get('name')!r}  mobile={u.get('mobile')!r}  "
                   f"created={u.get('created_at')}")
        if r['active']:
            a = r['active']
            out.append(f"    ACTIVE PLAN: {a.get('plan_name')} ({a.get('plan_code')})  "
                       f"source={a.get('source')}  expires={a.get('expires_at')}")
        else:
            out.append("    ACTIVE PLAN: (none → free tier)")
        for s in r['subs']:
            out.append(f"    sub#{s['id']} {s['status']} {s.get('plan_name')} "
                       f"src={s.get('source')} created={s.get('created_at')}")
        out.append("")
    if not rows:
        out.append("→ No pg_users record for this mobile. The doctor must log in on goocampus.in "
                   "with this exact number first (OTP), which creates the account.")
    from flask import Response
    return Response("\n".join(out), mimetype='text/plain')
