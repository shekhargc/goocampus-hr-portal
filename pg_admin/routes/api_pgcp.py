"""Indian PGCP onboarding — doctor-facing API for goocampus.in (X-PG-Key + Bearer).
Login-first, save-and-continue. Matched to a team-created invitation by mobile.
  GET  /api/pg/pgcp/onboarding          → invitation + saved draft
  POST /api/pg/pgcp/onboarding          → save any subset of fields (per step)
  POST /api/pg/pgcp/onboarding/submit   → mark submitted
(founder 2026-09-21)
"""
import re
import json
import secrets
import logging
from flask import request, jsonify
from db import get_db
from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token


def _ensure_pay_cols(conn):
    """Request-time guard: Render cold-start can skip boot DDL, so make sure the
    invitation payment columns exist before the money path touches them."""
    for ddl in (
        "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS payment_status TEXT DEFAULT 'due'",
        "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS paid_online INTEGER DEFAULT 0",
        "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS payment_ref TEXT DEFAULT ''",
        "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS paid_amount NUMERIC(14,2)",
    ):
        try:
            conn.execute(ddl)
        except Exception:
            pass
    try:   # package + instalment columns/tables (2026-10-16)
        from pg_admin.data.pgcp_package import ensure_schema
        ensure_schema(conn)
    except Exception:
        pass


def ensure_paid_invitation(conn, user, plan, amount, payment_ref, source='self-upgrade',
                           client_type='paying', comp=False):
    """Bridge: a website self-upgrade to a counselling plan enters the SAME PGCP
    onboarding pathway as a team invite. Upsert the doctor's invitation (matched by
    mobile) and mark the counselling fee as paid online, so the one onboarding form
    opens with its payment step pre-filled + locked. Idempotent — never duplicates.
    Returns the invitation id (or None if the doctor has no usable mobile).
    (founder 2026-09-25 — unify self-upgrade + invite into one path)

    comp=True (admin grant / complimentary): open the onboarding form WITHOUT recording
    any payment — an existing invite only gets its plan_code updated (client_type and
    every payment field untouched); a new one is created as an unpaid 'internal' invite.
    Fixes comps being mislabelled paid_online=1 with paid_amount = list price. (2026-10-16)

    When the doctor's invite is a team-negotiated PACKAGE (final_amount set), the online
    payment is also added to its instalment ledger and the status recomputed, so the
    package's paid/balance stay right."""
    _ensure_pay_cols(conn)
    mob10 = _digits(user.get('mobile'))[-10:]
    if not mob10:
        return None
    plan_code = (plan or {}).get('code') or ''
    try:
        amt = float(amount) if amount is not None else None
    except (TypeError, ValueError):
        amt = None
    existing = conn.execute(
        "SELECT * FROM pg_pgcp_invitations WHERE status <> 'cancelled' AND "
        "RIGHT(regexp_replace(COALESCE(mobile,''),'\\D','','g'),10) = ? ORDER BY id DESC LIMIT 1",
        [mob10]).fetchone()
    if comp:
        if existing:
            existing = dict(existing)
            conn.execute("UPDATE pg_pgcp_invitations SET plan_code = ? WHERE id = ?",
                         [plan_code or existing.get('plan_code') or '', existing['id']])
            conn.commit()
            return existing['id']
        iid = conn.execute(
            "INSERT INTO pg_pgcp_invitations (token, client_name, mobile, email, client_type, "
            "plan_code, status, payment_status, paid_online, created_by, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
            [secrets.token_urlsafe(12), user.get('name') or '', user.get('mobile') or '',
             user.get('email') or '', 'internal', plan_code, 'invited', 'due', 0,
             f'website ({source})', 'Complimentary — admin plan grant']).fetchone()['id']
        conn.commit()
        return iid
    if existing:
        existing = dict(existing)
        conn.execute(
            "UPDATE pg_pgcp_invitations SET plan_code = ?, "
            "invited_amount = COALESCE(invited_amount, ?), "
            "payment_status = 'paid', paid_online = 1, payment_ref = ?, paid_amount = ? "
            "WHERE id = ?",
            [plan_code or existing.get('plan_code') or '', amt, payment_ref or '', amt, existing['id']])
        conn.commit()   # the paid mark is saved first — the ledger below can never undo it
        if existing.get('final_amount') is not None and amt:
            # Team package: put the online payment into the instalment ledger too.
            try:
                from pg_admin.data import pgcp_package as _pk
                dup = conn.execute("SELECT 1 FROM pg_pgcp_payments WHERE invitation_id = ? "
                                   "AND razorpay_payment_id = ? AND razorpay_payment_id <> ''",
                                   [existing['id'], payment_ref or '']).fetchone()
                if not dup:
                    from datetime import datetime as _dt, timedelta as _td
                    _pk.add_payment(conn, existing['id'], amt,
                                    (_dt.utcnow() + _td(hours=5, minutes=30)).strftime('%Y-%m-%d'),
                                    'online', payment_ref or '', 'Paid online on goocampus.in',
                                    f'website ({source})', razorpay_payment_id=payment_ref or '')
                _pk.refresh_status(conn, existing['id'])
                conn.commit()
            except Exception as _e:
                try: conn.rollback()
                except Exception: pass
                logging.error("ensure_paid_invitation package ledger: %s", _e)
        return existing['id']
    iid = conn.execute(
        "INSERT INTO pg_pgcp_invitations (token, client_name, mobile, email, client_type, "
        "invited_amount, plan_code, status, payment_status, paid_online, payment_ref, paid_amount, created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
        [secrets.token_urlsafe(12), user.get('name') or '', user.get('mobile') or '',
         user.get('email') or '', client_type, amt, plan_code, 'invited', 'paid', 1,
         payment_ref or '', amt, f'website ({source})']).fetchone()['id']
    conn.commit()
    return iid

# column -> kind: text | int | num | bool | json
_FIELDS = {
    'photo_url': 'text', 'official_name': 'text', 'mobile': 'text', 'email': 'text',
    'state': 'text', 'city': 'text',
    'mbbs_college': 'text', 'mbbs_college_id': 'int', 'mbbs_year': 'text',
    'neet_attempt': 'text', 'prev_year': 'text', 'prev_score': 'text', 'prev_rank': 'text',
    'neetpg2026_score': 'text', 'neetpg2026_rank': 'text',
    'specialities': 'json', 'only_one_speciality': 'bool', 'ack_single': 'bool',
    'fee_bands': 'json', 'preferred_colleges': 'json', 'preferred_states': 'json',
    'anywhere_india': 'bool', 'seat_pref_order': 'json', 'seat_pref_interest': 'json',
    'nri_interested': 'bool', 'sponsor_name': 'text', 'sponsor_relationship': 'text',
    'sponsor_country': 'text',
    'payment_mode': 'text', 'payment_ref': 'text', 'amount_paid': 'num',
}
_JSON_COLS = [c for c, k in _FIELDS.items() if k == 'json']


def _digits(v):
    return re.sub(r'\D', '', str(v or ''))


def _coerce(kind, v):
    if kind == 'json':
        try: return json.dumps(v if v is not None else ([] if isinstance(v, list) else {}))
        except Exception: return '[]'
    if kind == 'bool':
        return 1 if v in (1, '1', True, 'true', 'yes', 'on') else 0
    if kind == 'int':
        try: return int(v)
        except (TypeError, ValueError): return None
    if kind == 'num':
        try: return float(str(v).replace(',', '')) if str(v).strip() != '' else None
        except (TypeError, ValueError): return None
    return (str(v).strip() if v is not None else '')


def _load(conn, user):
    """Match the doctor to an invitation by mobile; find/create their onboarding row."""
    umob = _digits(user.get('mobile'))[-10:]
    inv = None
    if umob:
        inv = conn.execute(
            "SELECT * FROM pg_pgcp_invitations WHERE status <> 'cancelled' AND "
            "RIGHT(regexp_replace(mobile, '\\D', '', 'g'), 10) = ? ORDER BY id DESC LIMIT 1",
            [umob]).fetchone()
    if not inv:
        return None, None
    inv = dict(inv)
    row = conn.execute("SELECT * FROM pg_pgcp_onboarding WHERE invitation_id = ? "
                       "ORDER BY id DESC LIMIT 1", [inv['id']]).fetchone()
    if not row:
        # If the counselling fee is already settled (website Razorpay, or an admin
        # "payment received" toggle), pre-fill the payment step so it opens locked.
        paid = (inv.get('payment_status') == 'paid')
        oid = conn.execute(
            "INSERT INTO pg_pgcp_onboarding (invitation_id, user_id, mobile, email, "
            "payment_mode, payment_ref, amount_paid) VALUES (?,?,?,?,?,?,?) RETURNING id",
            [inv['id'], user['id'], user.get('mobile') or '', user.get('email') or '',
             ('online' if paid and inv.get('paid_online') else ('transfer_declared' if paid else '')),
             (inv.get('payment_ref') or '') if paid else '',
             inv.get('paid_amount') if paid else None]).fetchone()['id']
        conn.execute("UPDATE pg_pgcp_invitations SET status='started' WHERE id=? AND status='invited'",
                     [inv['id']])
        conn.commit()
        row = conn.execute("SELECT * FROM pg_pgcp_onboarding WHERE id = ?", [oid]).fetchone()
    return inv, dict(row)


def _serialize(onb):
    out = dict(onb)
    for c in _JSON_COLS:
        try: out[c] = json.loads(out.get(c) or ('[]' if c != 'fee_bands' and c != 'seat_pref_interest' else '{}'))
        except Exception: out[c] = [] if c not in ('fee_bands', 'seat_pref_interest') else {}
    for k in ('created_at', 'updated_at', 'submitted_at'):
        if out.get(k) is not None:
            out[k] = str(out[k])
    return out


def _sync_onboarding_to_user(conn, user_id, onb):
    """Mirror the onboarding's profile fields into pg_users so the Registered Doctors list,
    the doctor's dashboard, and the 'complete your profile' gate all reflect what the client
    entered — fixes 'name pending', the missing NEET-PG score, and the home-state being
    re-asked after onboarding. Fills name/email/photo/state only when the profile value is
    empty (never clobbers a self-edited profile); updates score/rank/college/city/speciality.
    (founder 2026-09-25)"""
    try:
        sets, vals = [], []
        def fill(col, val):   # set only when the pg_users value is currently empty
            v = (str(val).strip() if val is not None else '')
            if v:
                sets.append(f"{col} = COALESCE(NULLIF({col}, ''), ?)"); vals.append(v)
        def put(col, val):    # overwrite when provided
            v = (str(val).strip() if val is not None else '')
            if v:
                sets.append(f"{col} = ?"); vals.append(v)
        def put_int(col, val):
            try:
                iv = int(float(str(val).replace(',', ''))) if str(val or '').strip() != '' else None
            except (TypeError, ValueError):
                iv = None
            if iv is not None:
                sets.append(f"{col} = ?"); vals.append(iv)
        fill('name', onb.get('official_name'))
        fill('email', onb.get('email'))
        fill('photo_url', onb.get('photo_url'))
        put('college', onb.get('mbbs_college'))
        put('city', onb.get('city'))
        put_int('neet_pg_score', onb.get('neetpg2026_score'))
        put_int('neet_pg_rank', onb.get('neetpg2026_rank'))
        try:
            specs = json.loads(onb.get('specialities') or '[]')
            if specs:
                fill('target_speciality', specs[0])
        except Exception:
            pass
        st = str(onb.get('state') or '').strip()
        if st:
            fill('state', st)
        if sets:
            conn.execute(f"UPDATE pg_users SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP "
                         "WHERE id = ?", vals + [user_id])
        # Home/domicile state → the doctor's home state (drives the free choice-list), once.
        if st:
            home = conn.execute("SELECT id FROM pg_doctor_states WHERE user_id = ? AND role='home'",
                                [user_id]).fetchone()
            if not home:
                conn.execute("INSERT INTO pg_doctor_states (user_id, state, role, locked) "
                             "VALUES (?, ?, 'home', 1)", [user_id, st])
        conn.commit()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("_sync_onboarding_to_user: %s", e)


def _package_fields(conn, inv):
    try:
        from pg_admin.data import pgcp_package as _pk
        sm = _pk.summary(conn, inv)
        return {'package_final': sm['final'], 'package_paid': sm['paid'],
                'package_balance': sm['balance'], 'package_status': sm['status'],
                'gst_mode': inv.get('gst_mode') or '',
                'balance_due_date': inv.get('balance_due_date') or '',
                'balance_due_note': inv.get('balance_due_note') or '',
                'balance_requested': bool(inv.get('balance_requested') or 0)}
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("pgcp _package_fields: %s", e)
        return {}


def api_pgcp_onboarding():
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    tok = _bearer_token()
    if not tok:
        return jsonify({'ok': False, 'error': 'no_token'}), 401
    conn = get_db()
    try:
        user = _pg_user_by_token(conn, tok)
        if not user:
            return jsonify({'ok': False, 'error': 'invalid_token'}), 401
        inv, onb = _load(conn, user)
        if not inv:
            return jsonify({'ok': True, 'invited': False,
                            'message': 'No PGCP invitation found for this mobile.'})

        if request.method == 'POST':
            body = request.get_json(silent=True) or {}
            # Payment already settled (paid online / admin-declared)? Lock those fields
            # server-side so the client cannot overwrite the recorded payment.
            pay_locked = (inv.get('payment_status') == 'paid')
            sets, vals = [], []
            for col, kind in _FIELDS.items():
                if col in body:
                    if pay_locked and col in ('payment_mode', 'payment_ref', 'amount_paid'):
                        continue
                    sets.append(f"{col} = ?"); vals.append(_coerce(kind, body[col]))
            try:
                step = int(body.get('step'))
                sets.append("step = GREATEST(step, ?)"); vals.append(max(1, min(4, step)))
            except (TypeError, ValueError):
                pass
            if sets:
                sets.append("updated_at = CURRENT_TIMESTAMP")
                vals.append(onb['id'])
                conn.execute(f"UPDATE pg_pgcp_onboarding SET {', '.join(sets)} WHERE id = ?", vals)
                conn.commit()
                onb = dict(conn.execute("SELECT * FROM pg_pgcp_onboarding WHERE id = ?",
                                        [onb['id']]).fetchone())
                _sync_onboarding_to_user(conn, user['id'], onb)   # mirror into the doctor's profile
            return jsonify({'ok': True, 'saved': True})

        # Resolve the plan's display name + price so the site can label the plan
        # without mapping plan_code itself. (goocampus.in ask 2026-09-25)
        _plan_name, _plan_price = '', None
        if inv.get('plan_code'):
            _pr = conn.execute("SELECT name, price FROM pg_plans WHERE code = ?",
                               [inv['plan_code']]).fetchone()
            if _pr:
                _pr = dict(_pr)
                _plan_name = _pr.get('name') or ''
                try:
                    _plan_price = float(_pr['price']) if _pr.get('price') is not None else None
                except (TypeError, ValueError):
                    _plan_price = None
        return jsonify({
            'ok': True, 'invited': True,
            'invitation': {'client_type': inv['client_type'],
                           'invited_amount': float(inv['invited_amount']) if inv['invited_amount'] is not None else None,
                           'discount': float(inv['discount']) if inv['discount'] is not None else 0,
                           'plan_code': inv['plan_code'], 'plan_name': _plan_name, 'plan_price': _plan_price,
                           'status': inv['status'],
                           'client_name': inv['client_name'],
                           'payment_status': inv.get('payment_status') or 'due',
                           'paid': (inv.get('payment_status') == 'paid'),
                           'paid_online': bool(inv.get('paid_online')),
                           'payment_ref': inv.get('payment_ref') or '',
                           'paid_amount': float(inv['paid_amount']) if inv.get('paid_amount') is not None else None,
                           # Negotiated package (additive, 2026-10-16) — final incl. GST,
                           # paid so far, balance, due info; a part-paid client has full access.
                           **_package_fields(conn, inv)},
            'onboarding': _serialize(onb)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pgcp_onboarding: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pgcp_submit():
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    tok = _bearer_token()
    if not tok:
        return jsonify({'ok': False, 'error': 'no_token'}), 401
    conn = get_db()
    try:
        user = _pg_user_by_token(conn, tok)
        if not user:
            return jsonify({'ok': False, 'error': 'invalid_token'}), 401
        inv, onb = _load(conn, user)
        if not inv:
            return jsonify({'ok': False, 'error': 'no_invitation'}), 404
        conn.execute("UPDATE pg_pgcp_onboarding SET status='submitted', step=4, "
                     "submitted_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     [onb['id']])
        conn.execute("UPDATE pg_pgcp_invitations SET status='submitted' WHERE id=? "
                     "AND status IN ('invited','started')", [inv['id']])
        conn.commit()
        onb = dict(conn.execute("SELECT * FROM pg_pgcp_onboarding WHERE id = ?", [onb['id']]).fetchone())
        _sync_onboarding_to_user(conn, user['id'], onb)   # mirror the final data into the profile
        return jsonify({'ok': True, 'submitted': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pgcp_submit: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def auto_grant_internal_premium(conn, user_id, mobile):
    """On login: upgrade the doctor to their PGCP plan when their mobile has either an
    INTERNAL invitation (free) or a PRE-PAID one (team ticked "payment received"), and
    they're not already on an active paid counselling plan. Grants the invitation's
    plan_code (internal legacy invites with no plan default to Premium). Idempotent, and
    works for both a dropdown-picked internal client and a freshly-typed pre-paid client.
    (name kept for the login call site; generalised beyond internal-only, founder 2026-09-25)"""
    from datetime import datetime as _dt, timedelta as _td
    try:
        mob = re.sub(r'\D', '', str(mobile or ''))[-10:]
        if not mob:
            return
        # Internal (free Premium) OR pre-paid (payment_status 'paid', or 'part_paid' —
        # a part-paid client gets FULL access, founder 2026-10-16) — either upgrades.
        inv = conn.execute(
            "SELECT id, client_type, plan_code, paid_amount, client_name, email, "
            "COALESCE(payment_status,'due') AS payment_status "
            "FROM pg_pgcp_invitations WHERE status <> 'cancelled' "
            "AND (client_type = 'internal' OR COALESCE(payment_status,'due') IN ('paid','part_paid')) "
            "AND RIGHT(regexp_replace(COALESCE(mobile,''),'\\D','','g'),10) = ? "
            "ORDER BY id DESC LIMIT 1", [mob]).fetchone()
        if not inv:
            return
        inv = dict(inv)
        # Backfill the doctor's name/email from the invite when their profile is blank, so an
        # invited client isn't "name pending" in Registered Doctors before they onboard. (2026-09-25)
        try:
            _inm, _iem = (inv.get('client_name') or '').strip(), (inv.get('email') or '').strip()
            if _inm or _iem:
                conn.execute("UPDATE pg_users SET name = COALESCE(NULLIF(name,''), ?), "
                             "email = COALESCE(NULLIF(email,''), ?), updated_at = CURRENT_TIMESTAMP "
                             "WHERE id = ?", [_inm, _iem, user_id])
                conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
        # Already on an active PAID counselling plan? Respect it — don't override.
        active = conn.execute(
            "SELECT p.plan_kind FROM pg_subscriptions s JOIN pg_plans p ON p.id = s.plan_id "
            "WHERE s.user_id = ? AND s.status = 'active' "
            "AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP) LIMIT 1",
            [user_id]).fetchone()
        if active and (active['plan_kind'] or '') == 'counselling':
            return
        # Grant the invitation's plan; internal legacy invites with no plan → Premium.
        code = (inv.get('plan_code') or '').strip() or 'pgcp_premium'
        plan = conn.execute("SELECT id, duration_days FROM pg_plans "
                            "WHERE code = ? AND COALESCE(is_active,1)=1", [code]).fetchone()
        if not plan and code != 'pgcp_premium':
            plan = conn.execute("SELECT id, duration_days FROM pg_plans "
                                "WHERE code = 'pgcp_premium' AND COALESCE(is_active,1)=1").fetchone()
        if not plan:
            return
        exp = None
        if plan['duration_days']:
            try:
                exp = (_dt.utcnow() + _td(days=int(plan['duration_days']))).strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                exp = None
        internal = (inv.get('client_type') == 'internal')
        try:
            price = float(inv['paid_amount']) if (not internal and inv.get('paid_amount') is not None) else 0
        except (TypeError, ValueError):
            price = 0
        source = 'internal_auto' if internal else 'prepaid_grant'
        conn.execute("UPDATE pg_subscriptions SET status = 'cancelled', cancelled_at = CURRENT_TIMESTAMP "
                     "WHERE user_id = ? AND status = 'active'", [user_id])
        conn.execute("INSERT INTO pg_subscriptions (user_id, plan_id, status, expires_at, price_paid, source) "
                     "VALUES (?, ?, 'active', ?, ?, ?)", [user_id, plan['id'], exp, price, source])
        # Internal keeps its existing 'completed' mark; a pre-paid paying client's
        # invitation stays in the onboarding lifecycle (invited→started→submitted) so
        # they still complete the form.
        if internal:
            conn.execute("UPDATE pg_pgcp_invitations SET status = 'completed' WHERE id = ?", [inv['id']])
        conn.commit()
        logging.info("PGCP plan '%s' auto-granted to user_id=%s (source=%s)", code, user_id, source)
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("auto_grant (pgcp): %s", e)
