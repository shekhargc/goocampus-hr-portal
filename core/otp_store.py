"""
core/otp_store.py — server-side store for login OTP codes (security fix 2026-11-12).

WHY: Flask's default session is a *signed* cookie, not an *encrypted* one — anyone can
base64-decode their own cookie. The login flows used to put the 6-digit WhatsApp code
straight into the session (session['emp_login_otp'] = code …), so whoever requested a code
for someone's mobile could read it from their own browser and log in without the phone.

NOW: the code itself never leaves the server. issue() stores an HMAC hash of it in
`login_otp_codes` and returns a random reference; only that reference goes into the
session. check() verifies the typed code against the hash, enforces expiry, a wrong-try
limit and single use.

Behaviour for users is unchanged (same screens, same 10-minute validity). Password login
is untouched. Only the new table `login_otp_codes` is written — no existing data.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta

from flask import current_app

from db import get_db

CODE_TTL_SECONDS = 600            # same 10 minutes the login flows already used
MAX_WRONG_TRIES = 5               # then the code is burnt — request a new one
MAX_SENDS_PER_WINDOW = 5          # per number/code, to stop WhatsApp flooding
SEND_WINDOW_SECONDS = 900         # … within 15 minutes

_READY = False


def _ensure(conn):
    global _READY
    if _READY:
        return
    pk = 'SERIAL PRIMARY KEY' if getattr(conn, 'is_postgres', False) else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    try:
        conn.execute(f'''CREATE TABLE IF NOT EXISTS login_otp_codes (
            id {pk},
            purpose TEXT NOT NULL,
            ref TEXT NOT NULL,
            subject TEXT,
            code_hash TEXT NOT NULL,
            tries INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP)''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_login_otp_codes_ref ON login_otp_codes (ref)")
        conn.commit()
        _READY = True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"otp_store _ensure: {e}")


def _hash(purpose, ref, code):
    key = current_app.secret_key or 'otp'
    if isinstance(key, str):
        key = key.encode()
    return hmac.new(key, f"{purpose}:{ref}:{code}".encode(), hashlib.sha256).hexdigest()


def _as_dt(v):
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v)[:26])
    except Exception:
        return None


def issue(purpose, code, subject=''):
    """Store `code` (hashed) and return (ref, error). Put ONLY `ref` in the session.
    error is a user-facing message when too many codes were requested or storage failed."""
    now = datetime.utcnow()
    conn = get_db()
    try:
        _ensure(conn)
        subject = str(subject or '')[:120]
        if subject:
            since = now - timedelta(seconds=SEND_WINDOW_SECONDS)
            rows = conn.execute("SELECT created_at FROM login_otp_codes WHERE purpose = ? AND subject = ? "
                                "ORDER BY id DESC LIMIT 20", (purpose, subject)).fetchall()
            recent = sum(1 for r in rows if (_as_dt(r['created_at']) or now) >= since)
            if recent >= MAX_SENDS_PER_WINDOW:
                return None, 'Too many OTPs requested. Please wait 15 minutes, or log in with your password.'
        ref = secrets.token_urlsafe(24)
        conn.execute("INSERT INTO login_otp_codes (purpose, ref, subject, code_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                     (purpose, ref, subject, _hash(purpose, ref, code), now))
        # Housekeeping of THIS table only: codes older than a day are useless.
        conn.execute("DELETE FROM login_otp_codes WHERE created_at < ?", (now - timedelta(days=1),))
        conn.commit()
        return ref, None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"otp_store.issue({purpose}): {e}")
        return None, 'Could not send the OTP right now. Please try again, or log in with your password.'
    finally:
        conn.close()


def check(purpose, ref, code):
    """Verify a typed code against the stored reference. Returns (ok, error_message)."""
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    if not ref or len(str(ref)) < 20:
        # Missing, or an old session from before this fix that still holds a raw code.
        return False, 'Please request a new OTP.'
    conn = get_db()
    try:
        _ensure(conn)
        row = conn.execute("SELECT * FROM login_otp_codes WHERE ref = ? AND purpose = ?", (ref, purpose)).fetchone()
        if not row:
            return False, 'Please request a new OTP.'
        row = dict(row)
        used = int(row.get('used') or 0)
        if used == 1:
            return False, 'This OTP has already been used. Please request a new one.'
        if used:
            if int(row.get('tries') or 0) >= MAX_WRONG_TRIES:
                return False, 'Too many wrong attempts. Please request a new OTP.'
            return False, 'Please request a new OTP.'
        made = _as_dt(row.get('created_at'))
        if not made or (datetime.utcnow() - made).total_seconds() > CODE_TTL_SECONDS:
            conn.execute("UPDATE login_otp_codes SET used = 2 WHERE id = ?", (row['id'],))
            conn.commit()
            return False, 'OTP expired. Please request a new one.'
        tries = int(row.get('tries') or 0)
        if tries >= MAX_WRONG_TRIES:
            return False, 'Too many wrong attempts. Please request a new OTP.'
        if not code or not hmac.compare_digest(_hash(purpose, ref, code), row['code_hash']):
            tries += 1
            conn.execute("UPDATE login_otp_codes SET tries = ?, used = ? WHERE id = ?",
                         (tries, 2 if tries >= MAX_WRONG_TRIES else 0, row['id']))
            conn.commit()
            if tries >= MAX_WRONG_TRIES:
                return False, 'Too many wrong attempts. Please request a new OTP.'
            return False, 'Invalid OTP. Please check and try again.'
        conn.execute("UPDATE login_otp_codes SET used = 1 WHERE id = ?", (row['id'],))
        conn.commit()
        return True, None
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"otp_store.check({purpose}): {e}")
        return False, 'Could not verify the OTP right now. Please try again, or log in with your password.'
    finally:
        conn.close()
