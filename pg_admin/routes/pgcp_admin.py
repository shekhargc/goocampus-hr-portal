"""Indian PGCP counselling — admin (goocampus.in Admin → Indian PGCP).
Create invitations, track the 4-step onboarding, view a doctor's submission.
True-admin gated. (founder 2026-09-21)
"""
import json
import secrets
import logging
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from core.users import get_user
from core.auth import login_required


def _admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def _s(v):
    return (str(v).strip() if v is not None else '')


def _num(v):
    try:
        return float(str(v).replace(',', '').strip()) if _s(v) else None
    except Exception:
        return None


@login_required
def pgcp_admin():
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    rows = []
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT i.*, o.id AS onb_id, o.step AS onb_step, o.status AS onb_status, "
            "o.submitted_at AS onb_submitted "
            "FROM pg_pgcp_invitations i "
            "LEFT JOIN pg_pgcp_onboarding o ON o.invitation_id = i.id "
            "ORDER BY i.created_at DESC").fetchall()]
    except Exception as e:
        logging.error("pgcp_admin: %s", e)
    finally:
        conn.close()
    return render_template('pg_admin/pgcp.html', rows=rows, active_section='goocampus_in')


@login_required
def pgcp_invite_create():
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    mobile = _s(request.form.get('mobile'))
    if not mobile:
        flash('Mobile is required (it links the invite to the doctor login).', 'error')
        return redirect(url_for('pg_pgcp_admin'))
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO pg_pgcp_invitations (token, client_name, mobile, email, client_type, "
            "invited_amount, discount, plan_code, notes, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [secrets.token_urlsafe(12), _s(request.form.get('client_name')), mobile,
             _s(request.form.get('email')),
             _s(request.form.get('client_type')) or 'paying',
             _num(request.form.get('invited_amount')), _num(request.form.get('discount')) or 0,
             _s(request.form.get('plan_code')), _s(request.form.get('notes')),
             _s(u.get('name') or u.get('username') or '')])
        conn.commit()
        flash('Invitation created. The doctor can now log in on goocampus.in and start onboarding.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("pgcp_invite_create: %s", e)
        flash(f'Could not create invitation: {e}', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_pgcp_admin'))


@login_required
def pgcp_invite_cancel(invite_id):
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        conn.execute("UPDATE pg_pgcp_invitations SET status='cancelled' WHERE id = ?", [invite_id])
        conn.commit()
        flash('Invitation cancelled.', 'success')
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return redirect(url_for('pg_pgcp_admin'))


@login_required
def pgcp_submission(invite_id):
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    inv = onb = None
    try:
        inv = conn.execute("SELECT * FROM pg_pgcp_invitations WHERE id = ?", [invite_id]).fetchone()
        if inv:
            inv = dict(inv)
            r = conn.execute("SELECT * FROM pg_pgcp_onboarding WHERE invitation_id = ? "
                             "ORDER BY id DESC LIMIT 1", [invite_id]).fetchone()
            onb = dict(r) if r else None
    finally:
        conn.close()
    if not inv:
        flash('Invitation not found', 'error')
        return redirect(url_for('pg_pgcp_admin'))

    def _j(v, default):
        try: return json.loads(v) if v else default
        except Exception: return default
    parsed = {}
    if onb:
        parsed = {
            'specialities': _j(onb.get('specialities'), []),
            'fee_bands': _j(onb.get('fee_bands'), {}),
            'preferred_colleges': _j(onb.get('preferred_colleges'), []),
            'preferred_states': _j(onb.get('preferred_states'), []),
            'seat_pref_order': _j(onb.get('seat_pref_order'), []),
            'seat_pref_interest': _j(onb.get('seat_pref_interest'), {}),
        }
    return render_template('pg_admin/pgcp_submission.html', inv=inv, onb=onb, parsed=parsed,
                           active_section='goocampus_in')
