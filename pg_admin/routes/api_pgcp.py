"""Indian PGCP onboarding — doctor-facing API for goocampus.in (X-PG-Key + Bearer).
Login-first, save-and-continue. Matched to a team-created invitation by mobile.
  GET  /api/pg/pgcp/onboarding          → invitation + saved draft
  POST /api/pg/pgcp/onboarding          → save any subset of fields (per step)
  POST /api/pg/pgcp/onboarding/submit   → mark submitted
(founder 2026-09-21)
"""
import re
import json
import logging
from flask import request, jsonify
from db import get_db
from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token

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
        oid = conn.execute(
            "INSERT INTO pg_pgcp_onboarding (invitation_id, user_id, mobile, email) "
            "VALUES (?,?,?,?) RETURNING id",
            [inv['id'], user['id'], user.get('mobile') or '', user.get('email') or '']).fetchone()['id']
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
            sets, vals = [], []
            for col, kind in _FIELDS.items():
                if col in body:
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
            return jsonify({'ok': True, 'saved': True})

        return jsonify({
            'ok': True, 'invited': True,
            'invitation': {'client_type': inv['client_type'],
                           'invited_amount': float(inv['invited_amount']) if inv['invited_amount'] is not None else None,
                           'discount': float(inv['discount']) if inv['discount'] is not None else 0,
                           'plan_code': inv['plan_code'], 'status': inv['status'],
                           'client_name': inv['client_name']},
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
        return jsonify({'ok': True, 'submitted': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pgcp_submit: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
