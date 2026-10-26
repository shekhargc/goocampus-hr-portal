"""Indian PGCP counselling — admin (goocampus.in Admin → Indian PGCP).
Create invitations, track the 4-step onboarding, view a doctor's submission.
True-admin gated. (founder 2026-09-21)
"""
import io
import json
import secrets
import logging
from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, flash
from pg_admin.data import pgcp_package as _pkg
from db import get_db
from core.users import get_user
from core.auth import login_required
from core.helpers import format_dr_name


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


def _by(u):
    return _s((u or {}).get('name') or (u or {}).get('username') or '')


def _today_ist():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d')


def _date_or(v, default=''):
    v = _s(v)
    try:
        datetime.strptime(v, '%Y-%m-%d')
        return v
    except ValueError:
        return default


def _counselling_plans(conn):
    """Paid counselling plans (Starter/Standard/Premium) with list price + GST setting.
    Default GST treatment: plan gst_percent > 0 → '+ GST', else 'GST inclusive'."""
    out = []
    for r in conn.execute(
            "SELECT id, code, name, price, COALESCE(gst_percent,0) AS gst_percent, "
            "COALESCE(tagline,'') AS tagline FROM pg_plans WHERE plan_kind = 'counselling' "
            "AND COALESCE(is_active,1) = 1 ORDER BY price").fetchall():
        r = dict(r)
        g = float(r.get('gst_percent') or 0)
        r['price'] = float(r['price'] or 0)
        r['gst_percent'] = g
        r['default_gst_mode'] = 'plus' if g > 0 else 'inclusive'
        r['default_gst_pct'] = g if g > 0 else 18.0
        out.append(r)
    return out


def _coupon_options(conn):
    """ACTIVE, currently-valid, not-used-up coupons for the invite form, with the rules
    the browser needs to compute the discount live (mirrors coupons.compute_discount).
    The server re-validates on save."""
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)   # coupon dates are entered + stored in IST
    links = {}
    try:
        for r in conn.execute("SELECT coupon_id, plan_id FROM pg_coupon_plans").fetchall():
            links.setdefault(r['coupon_id'], []).append(r['plan_id'])
        plan_codes = {r['id']: r['code'] for r in conn.execute("SELECT id, code FROM pg_plans").fetchall()}
        out = []
        for c in conn.execute("SELECT * FROM pg_coupons WHERE COALESCE(is_active,1) = 1 "
                              "ORDER BY code").fetchall():
            c = dict(c)
            if c.get('valid_from') and c['valid_from'] > now:
                continue
            if c.get('valid_until') and c['valid_until'] < now:
                continue
            if c.get('usage_limit_total') is not None and int(c.get('used_count') or 0) >= int(c['usage_limit_total']):
                continue
            out.append({
                'code': c['code'], 'description': c.get('description') or '',
                'type': c.get('discount_type') or 'percent',
                'value': float(c.get('discount_value') or 0),
                'cap': float(c['max_discount_amount']) if c.get('max_discount_amount') is not None else None,
                'min': float(c.get('min_order_amount') or 0),
                'plans': ([plan_codes.get(pid) for pid in links.get(c['id'], []) if plan_codes.get(pid)]
                          if (c.get('applies_to') or 'all') == 'plans' else None),
            })
        return out
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("pgcp _coupon_options: %s", e)
        return []


def _package_from_form(conn, form, plan):
    """Parse + compute the negotiated package from the invite / edit form.
    Returns (pkg dict, coupon_result or None, error or None)."""
    list_price = _pkg.D(form.get('list_price'))
    if list_price is None and plan:
        list_price = _pkg.D(plan.get('price'))
    if list_price is None or list_price <= 0:
        return None, None, 'Enter the plan list price.'
    gst_mode = _s(form.get('gst_mode')).lower()
    if gst_mode not in ('plus', 'inclusive'):
        gst_mode = (plan or {}).get('default_gst_mode') or 'plus'
    gst_pct = _pkg.D(form.get('gst_percent'))
    if gst_pct is None:
        gst_pct = _pkg.D((plan or {}).get('default_gst_pct'), _pkg.DEFAULT_GST)
    discount_mode = _s(form.get('discount_mode')).lower()
    coupon_code = _s(form.get('coupon_code')).upper() if discount_mode == 'coupon' else ''
    coupon = None
    if coupon_code:
        if not plan:
            return None, None, 'Pick the plan before applying a coupon.'
        from pg_admin.data import coupons as coupon_lib
        ok, res = coupon_lib.validate(conn, coupon_code, plan_id=plan['id'],
                                      amount=float(list_price), gst_percent=0)
        if not ok:
            return None, None, f"Coupon {coupon_code}: {res.get('error') or 'not valid'}"
        coupon = res
        disc = _pkg.D(res.get('discount'), _pkg.Decimal('0'))
    else:
        discount_mode = 'flat'
        disc = _pkg.D(form.get('discount'), _pkg.Decimal('0'))
    override = form.get('final_amount') if _s(form.get('final_overridden')) == '1' else None
    pkg = _pkg.compute_package(list_price, disc, gst_mode, gst_pct, override_final=override)
    pkg['discount_mode'] = discount_mode
    pkg['coupon_code'] = coupon_code
    return pkg, coupon, None


def _due_from_form(form):
    after = _s(form.get('after_allotment')).lower() in ('1', 'on', 'true', 'yes')
    note = _s(form.get('balance_due_note'))
    if after:
        note = 'After allotment' + ((' — ' + note) if note and note.lower() != 'after allotment' else '')
    return _date_or(form.get('balance_due_date')), note


@login_required
def pgcp_admin():
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    rows, plans, coupons = [], [], []
    try:
        _pkg.ensure_schema(conn)
        rows = [dict(r) for r in conn.execute(
            "SELECT i.*, o.id AS onb_id, o.step AS onb_step, o.status AS onb_status, "
            "o.submitted_at AS onb_submitted "
            "FROM pg_pgcp_invitations i "
            "LEFT JOIN pg_pgcp_onboarding o ON o.invitation_id = i.id "
            "ORDER BY i.created_at DESC").fetchall()]
        plans = _counselling_plans(conn)
        coupons = _coupon_options(conn)
        pays = _pkg.payments_by_invite(conn)
        for r in rows:   # read-only money picture (never writes to old rows)
            if r.get('client_type') != 'internal':
                r['pkg'] = _pkg.summary(conn, r, pays.get(r['id'], []))
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("pgcp_admin: %s", e)
    finally:
        conn.close()
    return render_template('pg_admin/pgcp.html', rows=rows, plans=plans, coupons=coupons,
                           pay_modes=_pkg.PAY_MODES, today=_today_ist(),
                           active_section='goocampus_in')


@login_required
def pgcp_backfill_profiles():
    """One-time backfill: push each existing PGCP onboarding's fields into the doctor's
    pg_users profile (name / NEET-PG score+rank / college / city / home state / photo /
    speciality) so Registered Doctors + the dashboard reflect what the client entered.
    Preview (GET) then Apply (POST). Additive — fills blanks, updates score/rank. (2026-09-25)"""
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    from pg_admin.routes.api_pgcp import _sync_onboarding_to_user
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT o.*, u.name AS u_name, u.neet_pg_score AS u_score, u.neet_pg_rank AS u_rank "
            "FROM pg_pgcp_onboarding o LEFT JOIN pg_users u ON u.id = o.user_id "
            "WHERE o.user_id IS NOT NULL ORDER BY o.id DESC").fetchall()]
        if request.method == 'POST':
            n = 0
            for r in rows:
                _sync_onboarding_to_user(conn, r['user_id'], r); n += 1
            flash(f'Backfilled {n} onboarding(s) into doctor profiles.', 'success')
            return redirect(url_for('pg_pgcp_backfill_profiles'))
        esc = lambda s: (str(s) if s is not None else '').replace('<', '&lt;')
        def cell(v, good=False):
            v = esc(v).strip()
            return ("<td style='color:#166534'>" if good else "<td>") + (v or '—') + "</td>"
        trs = ''.join(
            "<tr><td>" + str(r['user_id']) + "</td>"
            + ("<td style='color:#b91c1c;font-weight:700'>(name pending)</td>" if not (r.get('u_name') or '').strip()
               else "<td>" + esc(r['u_name']) + "</td>")
            + cell(r.get('official_name'), True)
            + cell(r.get('u_score')) + cell(r.get('neetpg2026_score'), True)
            + cell(r.get('u_rank')) + cell(r.get('neetpg2026_rank'), True)
            + cell(r.get('state'), True) + "</tr>"
            for r in rows)
        from flask import get_flashed_messages
        fl = ''.join("<div style='padding:9px 13px;border-radius:8px;margin-bottom:10px;background:#dcfce7;color:#166534'>"
                     + esc(m) + "</div>" for c, m in get_flashed_messages(with_categories=True))
        return ("<!doctype html><meta charset=utf-8><title>PGCP profile backfill</title>"
                "<body style='font-family:system-ui;padding:24px;color:#1e293b;max-width:1000px;margin:auto'>"
                "<h2>PGCP onboarding &rarr; doctor profile backfill</h2>" + fl
                + "<p>" + str(len(rows)) + " onboarding(s). Apply copies each one's name / NEET-PG score+rank / "
                "college / city / home state / photo / speciality into the doctor's profile "
                "(fills blanks, updates score/rank) so Registered Doctors + their dashboard reflect it. "
                "Never clobbers a self-edited name/state.</p>"
                "<form method=POST onsubmit=\"return confirm('Sync " + str(len(rows)) + " onboarding(s) into doctor profiles?')\">"
                "<button style='padding:9px 16px;background:#F58220;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:700'>"
                "Apply backfill &rarr; " + str(len(rows)) + " profiles</button></form>"
                "<table border=1 cellpadding=6 cellspacing=0 style='border-collapse:collapse;margin-top:14px;font-size:13px'>"
                "<tr style='background:#f1f5f9'><th>user</th><th>name now</th><th>onboarding name</th>"
                "<th>score now</th><th>onb score</th><th>rank now</th><th>onb rank</th><th>onb home state</th></tr>"
                + trs + "</table></body>")
    finally:
        conn.close()


@login_required
def pgcp_invite_create():
    """Create an invite. INTERNAL clients: unchanged (no money). PAYING clients: a
    negotiated package — plan list price, discount (flat ₹ or a coupon), GST treatment
    ('plus' / 'inclusive'), final package (auto, or the team's negotiated figure), an
    optional payment received now, and the balance due date / 'after allotment'.
    invited_amount = list price and discount = discount amount are still written for
    backward compatibility. (founder 2026-10-16)"""
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    f = request.form
    mobile = _s(f.get('mobile'))
    if not mobile:
        flash('Mobile is required (it links the invite to the doctor login).', 'error')
        return redirect(url_for('pg_pgcp_admin'))
    ctype = _s(f.get('client_type')) or 'paying'
    ctype = ctype if ctype in ('paying', 'internal') else 'paying'
    plan_code = _s(f.get('plan_code'))
    by = _by(u)
    conn = get_db()
    inv = None
    try:
        try:
            from pg_admin.routes.api_pgcp import _ensure_pay_cols
            _ensure_pay_cols(conn)   # cold-start guard for the payment columns
        except Exception:
            pass
        _pkg.ensure_schema(conn)
        base_vals = [secrets.token_urlsafe(12), _s(f.get('client_name')), mobile,
                     _s(f.get('email')), ctype]
        if ctype == 'internal':
            iid = conn.execute(
                "INSERT INTO pg_pgcp_invitations (token, client_name, mobile, email, client_type, "
                "plan_code, notes, created_by, payment_status, paid_online) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id",
                base_vals + [plan_code, _s(f.get('notes')), by, 'due', 0]).fetchone()['id']
            conn.commit()
            pay_amt = None
        else:
            plan = next((p for p in _counselling_plans(conn) if p['code'] == plan_code), None)
            pkg, coupon, err = _package_from_form(conn, f, plan)
            if err:
                flash(err, 'error')
                return redirect(url_for('pg_pgcp_admin'))
            due_date, due_note = _due_from_form(f)
            iid = conn.execute(
                "INSERT INTO pg_pgcp_invitations (token, client_name, mobile, email, client_type, "
                "invited_amount, discount, plan_code, notes, created_by, payment_status, paid_online, "
                "list_price, gst_mode, gst_percent, discount_mode, coupon_code, final_amount, "
                "balance_due_date, balance_due_note, package_updated_by, package_updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP) RETURNING id",
                base_vals + [pkg['list_price'], pkg['discount'], plan_code, _s(f.get('notes')), by,
                             'due', 0, pkg['list_price'], pkg['gst_mode'], pkg['gst_percent'],
                             pkg['discount_mode'], pkg['coupon_code'], pkg['final'],
                             due_date, due_note, by]).fetchone()['id']
            _pkg.log(conn, iid, 'created',
                     f"Package: list ₹{pkg['list_price']:,.2f} − discount ₹{pkg['discount']:,.2f}"
                     + (f" (coupon {pkg['coupon_code']})" if pkg['coupon_code'] else '')
                     + (f" · + GST {pkg['gst_percent']:g}%" if pkg['gst_mode'] == 'plus'
                        else f" · GST inclusive ({pkg['gst_percent']:g}%)")
                     + f" → final ₹{pkg['final']:,.2f}"
                     + (f" (negotiated; calculated ₹{pkg['computed_final']:,.2f})" if pkg['overridden'] else '')
                     + (f" · balance due {due_date}" if due_date else '')
                     + (f" · {due_note}" if due_note else ''), by)
            pay_amt = _pkg.D(f.get('pay_amount'))
            if pay_amt is not None and pay_amt > 0:
                _pkg.add_payment(conn, iid, pay_amt, _date_or(f.get('pay_date'), _today_ist()),
                                 _s(f.get('pay_mode')) or 'bank', _s(f.get('pay_ref')),
                                 'Received at invite', by)
            _pkg.refresh_status(conn, iid)
            if coupon:
                if not _pkg.redeem_coupon_for_invite(conn, coupon, iid, plan['id'],
                                                     pkg['list_price'], pkg['discount'], by):
                    conn.rollback()
                    flash(f"Coupon {pkg['coupon_code']} has just been fully used — invitation not created.", 'error')
                    return redirect(url_for('pg_pgcp_admin'))
            conn.commit()
        inv = dict(conn.execute("SELECT * FROM pg_pgcp_invitations WHERE id = ?", [iid]).fetchone())
        flash('Invitation created. The doctor can now log in on goocampus.in and start onboarding.'
              + (f' Payment of ₹{pay_amt:,.0f} recorded.' if (pay_amt and pay_amt > 0) else ''), 'success')
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
    name = format_dr_name(inv.get('client_name')) or 'Doctor'
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
            + "<p>With Premium, our counselling team <b>personally hand-holds you end to end</b> "
              "through the entire India PG counselling journey — we don't just give you tools, "
              "we do it <i>with</i> you:</p>"
            + "<ul style='color:#334155;font-size:14px;line-height:1.75;padding-left:20px;'>"
              "<li>Guidance on <b>which colleges to choose</b> and building your <b>round-wise choice lists</b></li>"
              "<li>Support across <b>every round</b> and <b>all counselling bodies</b> — All-India / MCC and each state</li>"
              "<li>By your side from <b>registration → choice filling → seat allotment → post-admission support</b></li>"
              "<li>Plus your own dashboard: college predictor, cut-off explorer, stipend / bond / penalty and college database</li>"
              "</ul>"
            + f"<p>To get started, simply log in with your mobile number <b>{mobile}</b> — your "
              "Premium access is already active, and our team will take it from there:</p>"
            + brand_button('Log in to your dashboard', _LOGIN_URL)
            + "<p style='font-size:13px;color:#64748b;'>Open goocampus.in on your phone, enter your "
              "mobile, and verify the OTP we send on WhatsApp.</p>"
        )
    else:
        amt = (inv.get('invited_amount') or 0) - (inv.get('discount') or 0)
        disc = inv.get('discount') or 0
        subject = 'Your GooCampus India PG Counselling invitation'
        fee = ''
        if inv.get('final_amount') is not None:
            # Negotiated package (2026-10-16): show the agreed final figure (GST included).
            amt = float(inv.get('final_amount') or 0)
            paid = float(inv.get('paid_amount') or 0) if inv.get('id') else 0
            fee = brand_callout(f"Your counselling package: <b>₹{amt:,.0f}</b> (incl. GST)"
                                + (f" (after ₹{float(disc):,.0f} discount)" if disc else "")
                                + (f"<br>Received so far: <b>₹{paid:,.0f}</b> · Balance: <b>₹{max(amt - paid, 0):,.0f}</b>"
                                   if paid > 0 else ""))
        elif inv.get('invited_amount'):
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


# ── Package + instalment payments for one invite (founder 2026-10-16) ─────────
def _fmt_money(v):
    try:
        return f"₹{float(v):,.2f}"
    except (TypeError, ValueError):
        return '—'


@login_required
def pgcp_payments(invite_id):
    """GET/POST /admin/pg/pgcp/<id>/payments — package breakdown, payments, balance,
    and actions: add payment · delete payment · edit package · toggle 'balance
    requested'. Every change is written to the append-only pg_pgcp_payment_log."""
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    by = _by(u)
    conn = get_db()
    try:
        try:
            from pg_admin.routes.api_pgcp import _ensure_pay_cols
            _ensure_pay_cols(conn)
        except Exception:
            pass
        _pkg.ensure_schema(conn)
        row = conn.execute("SELECT * FROM pg_pgcp_invitations WHERE id = ?", [invite_id]).fetchone()
        if not row:
            flash('Invitation not found', 'error')
            return redirect(url_for('pg_pgcp_admin'))
        inv = dict(row)
        plans = _counselling_plans(conn)
        plan = next((p for p in plans if p['code'] == (inv.get('plan_code') or '')), None)

        if request.method == 'POST':
            action = _s(request.form.get('action'))
            back = redirect(url_for('pg_pgcp_payments', invite_id=invite_id))
            if inv.get('client_type') == 'internal':
                flash('Internal (complimentary) invites have no package to track.', 'error')
                return back
            try:
                if action == 'add_payment':
                    inv = _pkg.adopt_legacy(conn, inv, by)
                    if inv.get('final_amount') is None:
                        conn.rollback()
                        flash('Set the final package amount first (Edit package), then record payments.', 'error')
                        return back
                    _pkg.add_payment(conn, invite_id, request.form.get('amount'),
                                     _date_or(request.form.get('paid_on'), _today_ist()),
                                     _s(request.form.get('mode')), _s(request.form.get('ref')),
                                     _s(request.form.get('note')), by)
                    st = _pkg.refresh_status(conn, invite_id)
                    conn.commit()
                    flash(f'Payment recorded. Status: {_pkg.STATUS_LABELS.get(st, st)}.', 'success')
                elif action == 'delete_payment':
                    pid = _num(request.form.get('payment_id'))
                    p = conn.execute("SELECT * FROM pg_pgcp_payments WHERE id = ? AND invitation_id = ?",
                                     [int(pid or 0), invite_id]).fetchone()
                    if not p:
                        flash('Payment not found.', 'error'); return back
                    p = dict(p)
                    conn.execute("DELETE FROM pg_pgcp_payments WHERE id = ?", [p['id']])
                    _pkg.log(conn, invite_id, 'payment_delete',
                             f"Deleted payment {_fmt_money(p.get('amount'))} of {p.get('paid_on') or '—'} "
                             f"({_pkg.PAY_MODE_LABELS.get(p.get('mode'), p.get('mode'))}"
                             + (f", ref {p.get('ref')}" if p.get('ref') else '') + ")"
                             + (f" — reason: {_s(request.form.get('reason'))}" if _s(request.form.get('reason')) else ''),
                             by)
                    st = _pkg.refresh_status(conn, invite_id)
                    conn.commit()
                    flash(f'Payment deleted. Status: {_pkg.STATUS_LABELS.get(st, st)}.', 'success')
                elif action == 'edit_package':
                    inv = _pkg.adopt_legacy(conn, inv, by)
                    form = request.form.to_dict()
                    # Keep an already-redeemed coupon as the label; the team edits the ₹ amount.
                    form['discount_mode'] = 'flat'
                    pkg, _c, err = _package_from_form(conn, form, plan)
                    if err:
                        conn.rollback(); flash(err, 'error'); return back
                    due_date, due_note = _due_from_form(request.form)
                    dmode = inv.get('discount_mode') or 'flat'
                    ccode = inv.get('coupon_code') or ''
                    if dmode == 'coupon' and _pkg.D(inv.get('discount')) != _pkg.D(pkg['discount']):
                        dmode = 'flat'   # discount changed by hand → no longer the coupon's figure
                    conn.execute(
                        "UPDATE pg_pgcp_invitations SET list_price = ?, invited_amount = ?, discount = ?, "
                        "gst_mode = ?, gst_percent = ?, discount_mode = ?, final_amount = ?, "
                        "balance_due_date = ?, balance_due_note = ?, package_updated_by = ?, "
                        "package_updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        [pkg['list_price'], pkg['list_price'], pkg['discount'], pkg['gst_mode'],
                         pkg['gst_percent'], dmode, pkg['final'], due_date, due_note, by, invite_id])
                    changes = []
                    def _chg(label, old, new, money=True):
                        o = _pkg.D(old) if money else _s(old)
                        n = _pkg.D(new) if money else _s(new)
                        if o != n:
                            changes.append(f"{label}: {(_fmt_money(o) if o is not None else '—') if money else (o or '—')} → "
                                           f"{(_fmt_money(n) if n is not None else '—') if money else (n or '—')}")
                    _chg('List price', inv.get('list_price'), pkg['list_price'])
                    _chg('Discount', inv.get('discount'), pkg['discount'])
                    _chg('GST', f"{inv.get('gst_mode') or ''} {inv.get('gst_percent') or ''}".strip(),
                         f"{pkg['gst_mode']} {pkg['gst_percent']:.2f}", money=False)
                    _chg('Final package', inv.get('final_amount'), pkg['final'])
                    _chg('Balance due date', inv.get('balance_due_date'), due_date, money=False)
                    _chg('Balance note', inv.get('balance_due_note'), due_note, money=False)
                    if ccode and dmode != 'coupon':
                        changes.append(f"Discount no longer the coupon {ccode} figure")
                    _pkg.log(conn, invite_id, 'package_edit',
                             '; '.join(changes) if changes else 'Saved (no changes)', by)
                    st = _pkg.refresh_status(conn, invite_id)
                    conn.commit()
                    flash(f'Package saved. Status: {_pkg.STATUS_LABELS.get(st, st)}.', 'success')
                elif action == 'toggle_balance_requested':
                    newv = 0 if int(inv.get('balance_requested') or 0) else 1
                    conn.execute("UPDATE pg_pgcp_invitations SET balance_requested = ? WHERE id = ?",
                                 [newv, invite_id])
                    _pkg.log(conn, invite_id, 'balance_request',
                             'Balance payment requested from the doctor' if newv
                             else 'Balance request withdrawn', by)
                    conn.commit()
                    flash('Balance request ' + ('switched on — the doctor will see a Pay balance button.'
                                                if newv else 'switched off.'), 'success')
                else:
                    flash('Unknown action.', 'error')
            except ValueError as ve:
                try: conn.rollback()
                except Exception: pass
                flash(str(ve), 'error')
            except Exception as e:
                try: conn.rollback()
                except Exception: pass
                logging.error("pgcp_payments %s: %s", action, e)
                flash(f'Could not save: {e}', 'error')
            return back

        summ = _pkg.summary(conn, inv)
        if summ['legacy']:
            # Old invite: show the old figures in the package boxes (read-only view).
            pkg = _pkg.compute_package(inv.get('invited_amount') or 0, inv.get('discount') or 0,
                                       'inclusive', 18)
        else:
            pkg = _pkg.compute_package(inv.get('list_price') or 0, inv.get('discount') or 0,
                                       inv.get('gst_mode') or 'plus', inv.get('gst_percent'),
                                       override_final=inv.get('final_amount'))
        logs = [dict(r) for r in conn.execute(
            "SELECT * FROM pg_pgcp_payment_log WHERE invitation_id = ? ORDER BY id DESC",
            [invite_id]).fetchall()]
    finally:
        conn.close()
    return render_template('pg_admin/pgcp_payments.html', inv=inv, plan=plan, summ=summ, pkg=pkg,
                           logs=logs, pay_modes=_pkg.PAY_MODES, mode_labels=_pkg.PAY_MODE_LABELS,
                           today=_today_ist(), active_section='goocampus_in')


# ── PG payments overview (team packages + online self-purchases) ──────────────
def _pg_payment_rows(conn):
    """One row per paying team invite + one per paid online order (pg_orders) that is
    not already represented by an invite's payment. Read-only."""
    _pkg.ensure_schema(conn)
    plan_by_code, plan_by_id = {}, {}
    for r in conn.execute("SELECT id, code, name FROM pg_plans").fetchall():
        plan_by_code[r['code']] = r['name']
        plan_by_id[r['id']] = r['name']
    pays = _pkg.payments_by_invite(conn)
    rows, seen_refs = [], set()
    for inv in conn.execute("SELECT * FROM pg_pgcp_invitations WHERE COALESCE(client_type,'paying') <> 'internal' "
                            "AND COALESCE(status,'') <> 'cancelled' ORDER BY id DESC").fetchall():
        inv = dict(inv)
        # Website-created invites (self-purchase bridge) are shown via their pg_orders row.
        if _pkg.is_legacy(inv) and _s(inv.get('created_by')).startswith('website ('):
            continue
        sm = _pkg.summary(conn, inv, pays.get(inv['id'], []))
        if inv.get('payment_ref'):
            seen_refs.add(inv['payment_ref'])
        for p in sm['payments']:
            if p.get('razorpay_payment_id'):
                seen_refs.add(p['razorpay_payment_id'])
        rows.append({
            'kind': 'invite', 'id': inv['id'], 'name': inv.get('client_name') or '',
            'mobile': inv.get('mobile') or '', 'plan': plan_by_code.get(inv.get('plan_code') or '', inv.get('plan_code') or ''),
            'source': 'Team package' + (' (old)' if sm['legacy'] else ''),
            'final': sm['final'], 'paid': sm['paid'], 'balance': sm['balance'],
            'status': sm['status'], 'status_label': sm['status_label'],
            'due': ' · '.join(x for x in [inv.get('balance_due_date') or '', inv.get('balance_due_note') or ''] if x),
            'last_paid': sm['last_paid_on'], 'created_at': inv.get('created_at'),
            'balance_requested': int(inv.get('balance_requested') or 0),
        })
    try:
        orders = [dict(r) for r in conn.execute(
            "SELECT o.*, u.name AS u_name, u.mobile AS u_mobile FROM pg_orders o "
            "LEFT JOIN pg_users u ON u.id = o.user_id WHERE o.status = 'paid' "
            "ORDER BY o.paid_at DESC").fetchall()]
    except Exception as e:   # pg_orders may not exist yet on a fresh DB
        try: conn.rollback()
        except Exception: pass
        logging.info("pg payments: pg_orders unavailable (%s)", e)
        orders = []
    for o in orders:
        if o.get('razorpay_payment_id') and o['razorpay_payment_id'] in seen_refs:
            continue
        amt = float(o.get('payable') or 0)
        paid_at = o.get('paid_at')
        last = ''
        if paid_at:
            try:
                last = (paid_at + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d')
            except Exception:
                last = str(paid_at)[:10]
        rows.append({
            'kind': 'order', 'id': o['id'], 'name': o.get('u_name') or '', 'mobile': o.get('u_mobile') or '',
            'plan': plan_by_id.get(o.get('plan_id'), ''), 'source': 'Online (full)',
            'final': amt, 'paid': amt, 'balance': 0.0, 'status': 'paid', 'status_label': 'Paid',
            'due': '', 'last_paid': last, 'created_at': o.get('created_at'), 'balance_requested': 0,
            'coupon': o.get('coupon_code') or '',
        })
    return rows


def _filter_pg_payment_rows(rows, args):
    st = _s(args.get('status'))
    due_only = _s(args.get('balance_due')) in ('1', 'on', 'true')
    q = _s(args.get('q')).lower()
    qd = ''.join(ch for ch in q if ch.isdigit())
    out = []
    for r in rows:
        if st in ('due', 'part_paid', 'paid') and r['status'] != st:
            continue
        if due_only and not ((r['balance'] or 0) > 0):
            continue
        if q:
            mob = ''.join(ch for ch in (r['mobile'] or '') if ch.isdigit())
            if q not in (r['name'] or '').lower() and not (qd and qd in mob):
                continue
        out.append(r)
    return out


@login_required
def pg_payments_admin():
    """GET /admin/pg/payments — every NEET-PG payment: team packages (instalments) and
    online self-purchases. Filters + totals + Excel. Admin only. (founder 2026-10-16)"""
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    rows = []
    try:
        rows = _pg_payment_rows(conn)
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("pg_payments_admin: %s", e)
        flash('Could not load payments.', 'error')
    finally:
        conn.close()
    view = _filter_pg_payment_rows(rows, request.args)
    totals = {
        'packages': sum((r['final'] or 0) for r in view),
        'collected': sum((r['paid'] or 0) for r in view),
        'outstanding': sum(max(r['balance'] or 0, 0) for r in view),
        'count': len(view),
    }
    return render_template('pg_admin/pg_payments.html', rows=view, totals=totals,
                           f_status=_s(request.args.get('status')),
                           f_due=_s(request.args.get('balance_due')) in ('1', 'on', 'true'),
                           q=_s(request.args.get('q')), active_section='goocampus_in')


@login_required
def pg_payments_export():
    """GET /admin/pg/payments/export — the filtered list as Excel (Client Name + Mobile first)."""
    from flask import send_file
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.styles import Font
    conn = get_db()
    try:
        rows = _filter_pg_payment_rows(_pg_payment_rows(conn), request.args)
    finally:
        conn.close()

    def clean(v):
        if isinstance(v, str):
            return ILLEGAL_CHARACTERS_RE.sub('', v)
        return v
    wb = Workbook()
    ws = wb.active
    ws.title = 'PG payments'
    head = ['Client Name', 'Mobile', 'Plan', 'Source', 'Final Package (Rs)', 'Paid (Rs)',
            'Balance (Rs)', 'Status', 'Balance Due', 'Last Payment', 'Balance Requested']
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([clean(x) for x in [
            format_dr_name(r['name']) if r['name'] else '', r['mobile'], r['plan'], r['source'],
            r['final'], r['paid'], r['balance'], r['status_label'], r['due'], r['last_paid'],
            'Yes' if r['balance_requested'] else '']])
    for col, w in zip('ABCDEFGHIJK', (28, 16, 22, 18, 16, 14, 14, 12, 26, 14, 10)):
        ws.column_dimensions[col].width = w
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    fname = 'pg_payments_' + _today_ist() + '.xlsx'
    return send_file(bio, as_attachment=True, download_name=fname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
