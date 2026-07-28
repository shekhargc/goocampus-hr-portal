"""Aspirant auth for goocampus.in — WhatsApp OTP login over /api/pg/*.

The public site (session 3) calls these service-to-service, so EVERY endpoint is
guarded by the X-PG-Key handshake (same as /api/pg/lead). OTP state lives in the
`pg_otps` table (NOT Flask session — there is no shared browser session here), and
a successful verify mints a bearer token stored (hashed) in `pg_user_sessions`.

Reuses the portal's existing WhatsApp sender `_send_whatsapp_otp` (Infobip) — we do
NOT build a second OTP system.

Aspirant-scoped endpoints (me / profile / logout) require BOTH:
  - X-PG-Key   → service identity (goocampus.in's server)
  - X-PG-Token → the user's bearer token from /otp/verify
"""
import os
import re
import time
import hmac
import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from flask import request, jsonify
from db import get_db

OTP_TTL_SECONDS = 10 * 60          # code valid 10 min
OTP_RESEND_COOLDOWN = 30           # min seconds between sends to one mobile
OTP_MAX_ATTEMPTS = 5               # wrong tries before the code is burned
SESSION_TTL_DAYS = 30


# ── shared guards / helpers ────────────────────────────────────────────────
def _service_authorized():
    expected = os.environ.get('PG_API_KEY') or ''
    got = request.headers.get('X-PG-Key') or ''
    return bool(expected) and got == expected


def _norm_mobile(raw):
    """Indian 10-digit mobile: strip non-digits, drop 91/0 prefixes, keep last 10."""
    digits = re.sub(r'\D', '', raw or '')
    if len(digits) < 10:
        return None
    return digits[-10:]


def _hash(*parts):
    return hashlib.sha256((':'.join(parts)).encode('utf-8')).hexdigest()


def _now():
    return datetime.utcnow()


def _user_public(row):
    # Bracket access (not .get()) so it works on both RealDictCursor (prod) and
    # sqlite3.Row (dev) rows — every column is present via SELECT *.
    return {
        'id': row['id'],
        'mobile': row['mobile'],
        'name': row['name'] or '',
        'email': row['email'] or '',
        'neet_pg_year': row['neet_pg_year'] or '',
        'neet_pg_rank': row['neet_pg_rank'],
        'target_speciality': row['target_speciality'] or '',
    }


def _user_from_token(conn):
    """Resolve the aspirant from the X-PG-Token header (or `token` in the JSON body).
    Returns the pg_users row dict, or None. Touches last_used_at on hit."""
    tok = request.headers.get('X-PG-Token') or ''
    if not tok:
        body = request.get_json(silent=True) or {}
        tok = body.get('token') or ''
    if not tok:
        return None
    th = _hash(tok)
    row = conn.execute(
        "SELECT u.* FROM pg_user_sessions s JOIN pg_users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > CURRENT_TIMESTAMP AND u.is_active",
        (th,)).fetchone()
    if row:
        try:
            conn.execute("UPDATE pg_user_sessions SET last_used_at = CURRENT_TIMESTAMP WHERE token_hash = ?", (th,))
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
    return row


# ── POST /api/pg/otp/send ──────────────────────────────────────────────────
def api_pg_otp_send():
    if not _service_authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    mobile = _norm_mobile(data.get('mobile'))
    name = (data.get('name') or '').strip()
    if not mobile:
        return jsonify({'ok': False, 'error': 'valid 10-digit mobile required'}), 400

    otp = str(secrets.randbelow(900000) + 100000)   # 6-digit, cryptographically random
    otp_hash = _hash(mobile, otp)
    expires = _now() + timedelta(seconds=OTP_TTL_SECONDS)

    conn = get_db()
    try:
        existing = conn.execute("SELECT id, last_sent_at FROM pg_otps WHERE mobile = ?", (mobile,)).fetchone()
        if existing and existing['last_sent_at']:
            last = existing['last_sent_at']
            if isinstance(last, str):
                try: last = datetime.fromisoformat(last.replace('Z', '')[:19])
                except Exception: last = None
            if last and (_now() - last).total_seconds() < OTP_RESEND_COOLDOWN:
                return jsonify({'ok': False, 'error': 'please wait before requesting another code'}), 429
        if existing:
            conn.execute("UPDATE pg_otps SET otp_hash = ?, pending_name = ?, expires_at = ?, "
                         "attempts = 0, last_sent_at = CURRENT_TIMESTAMP WHERE mobile = ?",
                         (otp_hash, name, expires, mobile))
        else:
            conn.execute("INSERT INTO pg_otps (mobile, otp_hash, pending_name, expires_at) VALUES (?, ?, ?, ?)",
                         (mobile, otp_hash, name, expires))
        conn.commit()
    except Exception as e:
        try: conn.rollback(); conn.close()
        except Exception: pass
        logging.error("api_pg_otp_send store: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass

    # Reuse the portal's live WhatsApp OTP sender (Infobip). Lazy import avoids a
    # circular import at module load (app.py imports pg_admin).
    try:
        from app import _send_whatsapp_otp
        ok, err = _send_whatsapp_otp(mobile, otp)
    except Exception as e:
        logging.error("api_pg_otp_send send: %s", e)
        ok, err = False, 'Failed to send OTP.'
    if not ok:
        return jsonify({'ok': False, 'error': err or 'could not send OTP'}), 502
    return jsonify({'ok': True}), 200


# ── POST /api/pg/otp/verify ────────────────────────────────────────────────
def api_pg_otp_verify():
    if not _service_authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    mobile = _norm_mobile(data.get('mobile'))
    otp = re.sub(r'\D', '', data.get('otp') or '')
    name = (data.get('name') or '').strip()
    if not mobile or not otp:
        return jsonify({'ok': False, 'error': 'mobile and otp required'}), 400

    conn = get_db()
    try:
        rec = conn.execute("SELECT * FROM pg_otps WHERE mobile = ?", (mobile,)).fetchone()
        if not rec:
            return jsonify({'ok': False, 'error': 'no code requested'}), 400
        exp = rec['expires_at']
        if isinstance(exp, str):
            try: exp = datetime.fromisoformat(exp.replace('Z', '')[:19])
            except Exception: exp = None
        if exp and _now() > exp:
            conn.execute("DELETE FROM pg_otps WHERE mobile = ?", (mobile,)); conn.commit()
            return jsonify({'ok': False, 'error': 'code expired'}), 400
        if (rec['attempts'] or 0) >= OTP_MAX_ATTEMPTS:
            conn.execute("DELETE FROM pg_otps WHERE mobile = ?", (mobile,)); conn.commit()
            return jsonify({'ok': False, 'error': 'too many attempts — request a new code'}), 429
        if not hmac.compare_digest(rec['otp_hash'], _hash(mobile, otp)):
            conn.execute("UPDATE pg_otps SET attempts = attempts + 1 WHERE mobile = ?", (mobile,)); conn.commit()
            return jsonify({'ok': False, 'error': 'incorrect code'}), 401

        # Correct — burn the OTP, upsert the user, mint a session token.
        final_name = name or (rec['pending_name'] or '')
        conn.execute("DELETE FROM pg_otps WHERE mobile = ?", (mobile,))
        user = conn.execute("SELECT * FROM pg_users WHERE mobile = ?", (mobile,)).fetchone()
        if user:
            if final_name and not (user['name'] or ''):
                conn.execute("UPDATE pg_users SET name = ?, last_login_at = CURRENT_TIMESTAMP, "
                             "updated_at = CURRENT_TIMESTAMP WHERE id = ?", (final_name, user['id']))
            else:
                conn.execute("UPDATE pg_users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?", (user['id'],))
            user_id = user['id']
            is_new = False
        else:
            row = conn.execute("INSERT INTO pg_users (mobile, name, last_login_at) "
                               "VALUES (?, ?, CURRENT_TIMESTAMP) RETURNING id", (mobile, final_name)).fetchone()
            user_id = row['id'] if row else None
            is_new = True

        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO pg_user_sessions (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
                     (user_id, _hash(token), _now() + timedelta(days=SESSION_TTL_DAYS)))
        conn.commit()
        urow = conn.execute("SELECT * FROM pg_users WHERE id = ?", (user_id,)).fetchone()
        return jsonify({'ok': True, 'token': token, 'is_new': is_new, 'user': _user_public(urow)}), 200
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_otp_verify: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass


# ── GET /api/pg/me ─────────────────────────────────────────────────────────
def api_pg_me():
    if not _service_authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        u = _user_from_token(conn)
        if not u:
            return jsonify({'ok': False, 'error': 'invalid_token'}), 401
        return jsonify({'ok': True, 'user': _user_public(u)}), 200
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_me: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass


# ── POST /api/pg/me — update the logged-in aspirant's profile ──────────────
def api_pg_me_update():
    if not _service_authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        u = _user_from_token(conn)
        if not u:
            return jsonify({'ok': False, 'error': 'invalid_token'}), 401
        sets, vals = [], []
        for field in ('name', 'email', 'neet_pg_year', 'target_speciality'):
            if field in data:
                sets.append(f"{field} = ?"); vals.append((data.get(field) or '').strip())
        if 'neet_pg_rank' in data:
            rank = data.get('neet_pg_rank')
            try:
                rank = int(rank) if rank not in (None, '') else None
            except Exception:
                rank = None
            sets.append("neet_pg_rank = ?"); vals.append(rank)
        if not sets:
            return jsonify({'ok': True, 'user': _user_public(u)}), 200
        conn.execute(f"UPDATE pg_users SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     vals + [u['id']])
        conn.commit()
        urow = conn.execute("SELECT * FROM pg_users WHERE id = ?", (u['id'],)).fetchone()
        return jsonify({'ok': True, 'user': _user_public(urow)}), 200
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_me_update: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass


# ── POST /api/pg/logout — revoke the current token ─────────────────────────
def api_pg_logout():
    if not _service_authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    tok = request.headers.get('X-PG-Token') or (request.get_json(silent=True) or {}).get('token') or ''
    if not tok:
        return jsonify({'ok': True}), 200
    conn = get_db()
    try:
        conn.execute("DELETE FROM pg_user_sessions WHERE token_hash = ?", (_hash(tok),))
        conn.commit()
        return jsonify({'ok': True}), 200
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_logout: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass
