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
    inv = None
    try:
        iid = conn.execute(
            "INSERT INTO pg_pgcp_invitations (token, client_name, mobile, email, client_type, "
            "invited_amount, discount, plan_code, notes, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id",
            [secrets.token_urlsafe(12), _s(request.form.get('client_name')), mobile,
             _s(request.form.get('email')),
             _s(request.form.get('client_type')) or 'paying',
             _num(request.form.get('invited_amount')), _num(request.form.get('discount')) or 0,
             _s(request.form.get('plan_code')), _s(request.form.get('notes')),
             _s(u.get('name') or u.get('username') or '')]).fetchone()['id']
        conn.commit()
        inv = dict(conn.execute("SELECT * FROM pg_pgcp_invitations WHERE id = ?", [iid]).fetchone())
        flash('Invitation created. The doctor can now log in on goocampus.in and start onboarding.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("pgcp_invite_create: %s", e)
        flash(f'Could not create invitation: {e}', 'error')
    finally:
        conn.close()
    if inv:   # auto-send the invite email on create
        ok, msg = _send_pgcp_invite_email(inv)
        flash(('Invite email ' + msg) if ok
              else ('Invitation saved, but email not sent (' + msg + '). Use “Send invite” once an email is added.'),
              'success' if ok else 'info')
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


def pgcp_client_search():
    """GET /admin/pg/pgcp/client-search?q= → existing clients (name/mobile/pathway) for the
    internal-invite picker, from the ops client master (plab_clients). (founder 2026-09-23)"""
    from flask import jsonify
    u = _admin()
    if not u:
        return jsonify([]), 403
    q = _s(request.args.get('q'))
    out = []
    if len(q) < 2:
        return jsonify(out)
    conn = get_db()
    try:
        like = f"%{q}%"
        rows = conn.execute(
            "SELECT registration_number AS reg, "
            "TRIM(COALESCE(first_name,'')||' '||COALESCE(last_name,'')) AS name, "
            "COALESCE(pathway,'') AS pathway, mobile, COALESCE(email,'') AS email "
            "FROM plab_clients "
            "WHERE (first_name ILIKE ? OR last_name ILIKE ? OR mobile ILIKE ? OR registration_number ILIKE ?) "
            "AND COALESCE(mobile,'') <> '' ORDER BY first_name LIMIT 30",
            (like, like, like, like)).fetchall()
        seen = set()
        for r in rows:
            r = dict(r)
            key = (r['name'].strip().lower(), (r['mobile'] or '').strip())
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
    except Exception as e:
        logging.error("pgcp_client_search: %s", e)
    finally:
        conn.close()
    return jsonify(out)


_LOGIN_URL = 'https://goocampus.in'


def _send_pgcp_invite_email(inv):
    """Compose + send the branded PGCP invite email. Internal = complimentary Premium
    (included in their existing package); paying = fee + log-in. Returns (ok, msg)."""
    email = _s(inv.get('email'))
    if not email:
        return False, 'no email on file'
    try:
        from email_utils import send_email, render_branded_email, brand_button, brand_callout
    except Exception as e:
        logging.error("pgcp email import: %s", e)
        return False, 'email module unavailable'
    name = _s(inv.get('client_name')) or 'Doctor'
    mobile = _s(inv.get('mobile'))
    if inv.get('client_type') == 'internal':
        subject = 'Your India PG Counselling is included — log in to GooCampus'
        inner = (
            f"<p>Dear {name},</p>"
            "<p>As a valued GooCampus client, we're delighted to include our "
            "<b>Premium India PG Counselling</b> service in your existing package — "
            "<b>at no additional cost</b>.</p>"
            + brand_callout("This Premium India PG Counselling package is normally <b>₹2,00,000</b>. "
                            "For you it is <b>complimentary</b> — included as part of your existing "
                            "consulting package. There is nothing more to pay.")
            + "<p>It gives you the full counselling dashboard: college predictor, cut-off explorer, "
              "stipend / bond / penalty, college database, your round-wise choice lists "
              "(All-India / MCC + all states), mentor access, and expert option-entry support.</p>"
            + f"<p>To get started, simply log in with your mobile number <b>{mobile}</b> — your "
              "Premium access is already active:</p>"
            + brand_button('Log in to your dashboard', _LOGIN_URL)
            + "<p style='font-size:13px;color:#64748b;'>Open goocampus.in on your phone, enter your "
              "mobile, and verify the OTP we send on WhatsApp.</p>"
        )
    else:
        amt = (inv.get('invited_amount') or 0) - (inv.get('discount') or 0)
        disc = inv.get('discount') or 0
        subject = 'Your GooCampus India PG Counselling invitation'
        fee = ''
        if inv.get('invited_amount'):
            fee = brand_callout(f"Your counselling fee: <b>₹{amt:,.0f}</b>"
                                + (f" (after ₹{disc:,.0f} discount)" if disc else ""))
        inner = (
            f"<p>Dear {name},</p>"
            "<p>You're invited to <b>GooCampus India PG Counselling</b>.</p>"
            + fee
            + f"<p>Log in with your mobile <b>{mobile}</b> to complete your onboarding and payment:</p>"
            + brand_button('Log in to your dashboard', _LOGIN_URL)
            + "<p style='font-size:13px;color:#64748b;'>Open goocampus.in on your phone, enter your "
              "mobile, and verify the OTP we send on WhatsApp.</p>"
        )
    body = render_branded_email('GooCampus India PG Counselling', inner)
    try:
        ok = send_email([email], subject, body)
        return bool(ok), ('sent to ' + email if ok else 'send failed')
    except Exception as e:
        logging.error("pgcp send_email: %s", e)
        return False, str(e)


@login_required
def pgcp_send_email(invite_id):
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        inv = conn.execute("SELECT * FROM pg_pgcp_invitations WHERE id = ?", [invite_id]).fetchone()
    finally:
        conn.close()
    if not inv:
        flash('Invitation not found', 'error')
        return redirect(url_for('pg_pgcp_admin'))
    ok, msg = _send_pgcp_invite_email(dict(inv))
    flash(('Invite email ' + msg) if ok else ('Could not send: ' + msg),
          'success' if ok else 'error')
    return redirect(url_for('pg_pgcp_admin'))


def pgcp_test_email():
    """GET /admin/pg/pgcp/test-email?to=…&type=internal|paying — send a SAMPLE invite
    email so the team can preview it. Admin-gated. (founder 2026-09-23)"""
    from flask import Response
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    to = _s(request.args.get('to')) or 'shekhar@goocampus.in'
    ctype = _s(request.args.get('type')) or 'internal'
    sample = {'client_name': 'Dr. Test User', 'mobile': '9611996500', 'email': to,
              'client_type': 'internal' if ctype != 'paying' else 'paying',
              'invited_amount': 30000, 'discount': 5000}
    ok, msg = _send_pgcp_invite_email(sample)
    return Response(("✅ Test invite email (" + sample['client_type'] + ") " + msg
                     + f"\nCheck the inbox of {to}.") if ok
                    else ("❌ Could not send: " + msg), mimetype='text/plain')
