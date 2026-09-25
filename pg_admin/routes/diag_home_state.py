"""Backfill: sync each doctor's LOCKED counselling home state (pg_doctor_states,
role='home') FROM their profile state (pg_users.state).

Doctors who registered before the state edit-sync existed can be stuck: their
counselling home state is missing or wrong, and it's locked so they can't fix it.
This tool (admin only) previews who is affected, then — on Apply — sets their home
state to their profile state. Profile states that aren't a clean canonical state
(e.g. "Panipat haryana") are SKIPPED and flagged for manual review, so junk never
gets locked into the counselling home. (founder 2026-09-25)
"""
import logging
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from core.users import get_user
from core.auth import login_required
from pg_admin.routes.users_admin import _canonical_states


def _admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def _norm(s):
    return str(s or '').strip()


def _analyze(conn):
    canon_lower = {c.lower() for c in _canonical_states()}
    rows = [dict(r) for r in conn.execute(
        "SELECT u.id, u.name, u.mobile, COALESCE(u.state,'') AS profile_state, "
        "h.id AS home_id, h.state AS home_state "
        "FROM pg_users u "
        "LEFT JOIN pg_doctor_states h ON h.user_id = u.id AND h.role = 'home' "
        "WHERE COALESCE(u.state,'') <> '' "
        "ORDER BY u.id DESC").fetchall()]
    out = {'missing': [], 'mismatch': [], 'consistent': [], 'junk': []}
    for r in rows:
        ps, hs = _norm(r['profile_state']), _norm(r['home_state'])
        if ps.lower() not in canon_lower:
            out['junk'].append(r)            # profile state isn't a clean state — manual fix
        elif r['home_id'] is None:
            out['missing'].append(r)          # stuck: no counselling home state yet
        elif hs.lower() != ps.lower():
            out['mismatch'].append(r)         # home locked to a different state
        else:
            out['consistent'].append(r)
    return out


@login_required
def home_state_backfill():
    admin = _admin()
    if not admin:
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        if request.method == 'POST':
            data = _analyze(conn)
            n_new = n_upd = 0
            for r in data['missing']:
                conn.execute("INSERT INTO pg_doctor_states (user_id, state, role, locked) "
                             "VALUES (?, ?, 'home', 1)", (r['id'], _norm(r['profile_state'])))
                n_new += 1
            for r in data['mismatch']:
                conn.execute("UPDATE pg_doctor_states SET state = ? WHERE id = ?",
                             (_norm(r['profile_state']), r['home_id']))
                n_upd += 1
            conn.commit()
            flash(f'Backfill applied — {n_new} home states created, {n_upd} corrected to match '
                  f'the profile state. {len(data["junk"])} skipped (profile state is not a clean '
                  f'state — fix those manually).', 'success')
            return redirect(url_for('pg_home_state_backfill'))

        data = _analyze(conn)
        return render_template('pg_admin/diag_home_state.html', user=admin,
                               active_section='goocampus_in', **data)
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error("home_state_backfill: %s", e)
        flash(f'Backfill error: {e}', 'error')
        return redirect(url_for('pg_users_admin'))
    finally:
        try:
            conn.close()
        except Exception:
            pass
