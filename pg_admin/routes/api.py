"""Public `/api/pg/*` mentor endpoints — the goocampus.in Next.js user panel calls
these service-to-service. Guarded by the shared secret in the X-PG-Key header
(must equal env PG_API_KEY), exactly like the existing POST /api/pg/lead.

PUBLIC FIELDS ONLY: the mentor JSON never exposes email, phone, medical council
number/state, or admin_notes (see pg_admin/utils.mentor_public_dict). Only mentors
with is_published = TRUE AND is_active = TRUE are visible.
"""
import os
import re
import random
import secrets
import logging
from datetime import datetime, timedelta
from flask import request, jsonify, redirect, abort
from db import get_db
from pg_admin.utils import mentor_public_dict, as_dict


def _norm_mobile(v):
    """Digits only, last 10 (drops +91 / country code)."""
    return re.sub(r'\D', '', str(v or ''))[-10:]


def api_pg_otp_send():
    """POST /api/pg/otp/send  {mobile}  → {ok:true}. Sends a WhatsApp OTP for the
    goocampus.in doctor login. X-PG-Key guarded. (founder 2026-07-24)"""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    mobile = _norm_mobile(data.get('mobile'))
    if len(mobile) != 10:
        return jsonify({'ok': False, 'error': 'A valid 10-digit mobile number is required.'}), 400
    otp = str(random.randint(100000, 999999))
    expires = datetime.utcnow() + timedelta(minutes=5)
    conn = get_db()
    try:
        conn.execute("DELETE FROM pg_otps WHERE mobile = ?", (mobile,))
        conn.execute("INSERT INTO pg_otps (mobile, otp_code, expires_at) VALUES (?, ?, ?)",
                     (mobile, otp, expires))
        conn.commit()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        conn.close()
        logging.error("api_pg_otp_send store: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    conn.close()
    try:
        from app import _send_whatsapp_otp  # reuse the portal's live WhatsApp OTP sender
        ok, err = _send_whatsapp_otp(mobile, otp)
    except Exception as e:
        logging.error("api_pg_otp_send send: %s", e)
        ok, err = False, 'Could not send the code. Please try again.'
    if not ok:
        return jsonify({'ok': False, 'error': err or 'Could not send the code.'}), 502
    return jsonify({'ok': True})


def api_pg_otp_verify():
    """POST /api/pg/otp/verify  {mobile, otp}  → {ok:true, token, user{id,name,mobile}}.
    A verified new mobile creates a pg_users row (first login = signup). Returns an
    opaque 30-day session token the site stores in an httpOnly cookie. X-PG-Key
    guarded. (founder 2026-07-24)"""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    mobile = _norm_mobile(data.get('mobile'))
    otp = re.sub(r'\D', '', str(data.get('otp', '')))
    if len(mobile) != 10 or not otp:
        return jsonify({'ok': False, 'error': 'Mobile and code are required.'}), 400
    conn = get_db()
    try:
        row = conn.execute("SELECT id, otp_code, expires_at FROM pg_otps "
                           "WHERE mobile = ? ORDER BY id DESC LIMIT 1", (mobile,)).fetchone()
        if not row:
            conn.close()
            return jsonify({'ok': False, 'error': 'Please request a new code.'}), 400
        exp = row['expires_at']
        if isinstance(exp, str):
            try: exp = datetime.strptime(exp[:19], '%Y-%m-%d %H:%M:%S')
            except Exception: exp = None
        if exp and datetime.utcnow() > exp:
            conn.execute("DELETE FROM pg_otps WHERE mobile = ?", (mobile,)); conn.commit(); conn.close()
            return jsonify({'ok': False, 'error': 'Incorrect or expired code.'}), 400
        if str(row['otp_code']) != otp:
            conn.execute("UPDATE pg_otps SET attempts = COALESCE(attempts,0)+1 WHERE id = ?", (row['id'],))
            conn.commit(); conn.close()
            return jsonify({'ok': False, 'error': 'Incorrect or expired code.'}), 400
        # Valid — clear codes, upsert the user, issue a token.
        conn.execute("DELETE FROM pg_otps WHERE mobile = ?", (mobile,))
        token = secrets.token_urlsafe(32)
        token_exp = datetime.utcnow() + timedelta(days=30)
        user = conn.execute("SELECT id, name FROM pg_users WHERE mobile = ?", (mobile,)).fetchone()
        if user:
            conn.execute("UPDATE pg_users SET session_token = ?, token_expires_at = ?, "
                         "last_login_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (token, token_exp, user['id']))
            uid, uname = user['id'], (user['name'] or '')
        else:
            uid = conn.execute("INSERT INTO pg_users (mobile, session_token, token_expires_at, last_login_at) "
                               "VALUES (?, ?, ?, CURRENT_TIMESTAMP) RETURNING id",
                               (mobile, token, token_exp)).fetchone()['id']
            uname = ''
        conn.commit()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        conn.close()
        logging.error("api_pg_otp_verify: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    conn.close()
    return jsonify({'ok': True, 'token': token,
                    'user': {'id': uid, 'name': uname, 'mobile': mobile}})


def _authorized():
    """True if the request carries the correct X-PG-Key handshake."""
    expected = os.environ.get('PG_API_KEY') or ''
    got = request.headers.get('X-PG-Key') or ''
    return bool(expected) and got == expected


def _photo_base():
    """Absolute origin for building stable photo URLs (e.g. https://goocampus.org)."""
    return request.url_root.rstrip('/')


def api_pg_mentors():
    """GET /api/pg/mentors?specialization=&q=&available=
    Published + active mentors, public fields only. Sorted by rating desc, then name."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401

    specialization = (request.args.get('specialization') or '').strip()
    q = (request.args.get('q') or '').strip()
    available = (request.args.get('available') or '').strip().lower()

    conds = ["is_published", "is_active"]
    params = []
    if specialization:
        conds.append("specialization = ?")
        params.append(specialization)
    if q:
        conds.append("(name ILIKE ? OR specialization ILIKE ? OR bio ILIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if available in ('1', 'true', 'yes'):
        conds.append("is_available")

    where = " AND ".join(conds)
    conn = get_db()
    try:
        rows = conn.execute(
            f"SELECT * FROM pg_mentors WHERE {where} "
            f"ORDER BY rating DESC, name ASC",
            params
        ).fetchall()
        base = _photo_base()
        mentors = [mentor_public_dict(r, base) for r in rows]
        return jsonify({'ok': True, 'mentors': mentors, 'count': len(mentors)}), 200
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error("api_pg_mentors: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


def api_pg_mentor_detail(mentor_id):
    """GET /api/pg/mentors/:id — one published mentor's public profile (+ availability)."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM pg_mentors WHERE id = ? AND is_published AND is_active",
            (mentor_id,)
        ).fetchone()
        if not row:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        data = mentor_public_dict(row, _photo_base())
        # Availability is needed by the booking UI and isn't sensitive — include on detail.
        data['availability'] = as_dict(row.get('availability'))
        return jsonify({'ok': True, 'mentor': data}), 200
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error("api_pg_mentor_detail(%s): %s", mentor_id, e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


def api_pg_mentor_photo(mentor_id):
    """GET /api/pg/mentors/:id/photo — 302 to a fresh presigned R2 URL.

    Deliberately UNKEYED: it's referenced directly from <img> tags on goocampus.in,
    where the browser can't send X-PG-Key. Only published + active mentors' photos
    are served, so nothing private leaks. Returns 404 when no photo/not published.
    """
    from core import storage
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT photo_url FROM pg_mentors WHERE id = ? AND is_published AND is_active",
            (mentor_id,)
        ).fetchone()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error("api_pg_mentor_photo(%s): %s", mentor_id, e)
        row = None
    finally:
        try:
            conn.close()
        except Exception:
            pass
    key = row.get('photo_url') if row else None
    if not key:
        abort(404)
    url = storage.presigned_get_url(key)
    if not url:
        abort(404)
    return redirect(url, code=302)


def api_pg_predictor():
    """GET /api/pg/predictor?rank=&authority=&category=&state=&q=&year=&limit=

    Colleges within reach for a NEET-PG rank, from the pg_cutoffs dataset uploaded
    in the portal (Predictor Data admin). Replaces the 10 MB JSON the site used to
    ship in its own repo — which was .gitignored and so never reached production,
    leaving the live predictor stuck in "Preview mode". (founder 2026-07-24)

    A row is "within reach" when the user's rank is at or better than the seat's
    last-round closing rank, with a small stretch band so near-misses still show
    (labelled honestly rather than dropped).
    """
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    try:
        rank = int(request.args.get('rank') or 0)
    except (TypeError, ValueError):
        rank = 0
    if rank <= 0:
        return jsonify({'ok': False, 'error': 'A valid rank is required.'}), 400
    authority = (request.args.get('authority') or '').strip()
    category = (request.args.get('category') or '').strip()
    state = (request.args.get('state') or '').strip()
    q = (request.args.get('q') or '').strip()
    try:
        limit = min(int(request.args.get('limit') or 800), 2000)
    except (TypeError, ValueError):
        limit = 800

    conn = get_db()
    try:
        year_row = conn.execute(
            "SELECT COALESCE(MAX(year), 0) AS y FROM pg_cutoffs").fetchone()
        year = int(request.args.get('year') or (year_row['y'] if year_row else 0) or 0)
        if not year:
            conn.close()
            return jsonify({'ok': True, 'year': None, 'count': 0, 'results': [],
                            'note': 'No cut-off dataset has been uploaded yet.'})
        # closing_rank is the WORST (last-round) closing rank, so `rank <= closing_rank`
        # is exactly "at least one round is clearable" — the same test the site's
        # engine applies per round. Keeping it exact (no stretch band) means the
        # total below is a true count, not an approximation.
        where = ["year = ?", "closing_rank IS NOT NULL", "closing_rank >= ?"]
        params = [year, rank]
        if authority and authority.lower() not in ('all', 'all authorities'):
            where.append("authority ILIKE ?"); params.append(f"%{authority}%")
        if category and category.lower() not in ('any', 'any category'):
            where.append("category ILIKE ?"); params.append(f"%{category}%")
        if state:
            where.append("state ILIKE ?"); params.append(f"%{state}%")
        if q:
            where.append("(course ILIKE ? OR institute ILIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        where_sql = ' AND '.join(where)
        # Exact match count (not just the page) so the site can say "N within reach"
        # truthfully even though only `limit` rows are returned for display.
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM pg_cutoffs WHERE {where_sql}", params).fetchone()['c']
        rows = conn.execute(
            "SELECT institute, authority, quota, category, degree, course, state, "
            "       fee, stipend, bond_years, penalty, r1, r2, r3, r4, stray, closing_rank "
            f"  FROM pg_cutoffs WHERE {where_sql} "
            "  ORDER BY closing_rank ASC LIMIT ?", params + [limit]).fetchall()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        conn.close()
        logging.error("api_pg_predictor: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    conn.close()

    def _chance(closing):
        """Honest banding — never a false-precision percentage."""
        if not closing:
            return 'unknown'
        if rank <= closing * 0.75:
            return 'high'
        if rank <= closing:
            return 'good'
        return 'reach'

    results = []
    for r in rows:
        d = as_dict(r)
        d['chance'] = _chance(d.get('closing_rank'))
        results.append(d)
    return jsonify({'ok': True, 'year': year, 'rank': rank,
                    'count': len(results), 'total': total,
                    'truncated': total > len(results), 'results': results})


def api_pg_predictor_filters():
    """GET /api/pg/predictor/filters — the authority / category / state option lists
    actually present in the loaded dataset, so the site's dropdowns match the data."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    out = {'ok': True, 'year': None, 'authorities': [], 'categories': [], 'states': []}
    try:
        yr = conn.execute("SELECT COALESCE(MAX(year), 0) AS y FROM pg_cutoffs").fetchone()
        year = int(yr['y']) if yr and yr['y'] else 0
        out['year'] = year or None
        if year:
            for key, col in (('authorities', 'authority'), ('categories', 'category'),
                             ('states', 'state')):
                out[key] = [r[col] for r in conn.execute(
                    f"SELECT DISTINCT {col} FROM pg_cutoffs "
                    f" WHERE year = ? AND COALESCE({col},'') <> '' ORDER BY {col}",
                    (year,)).fetchall()]
    except Exception as e:
        logging.error("api_pg_predictor_filters: %s", e)
    finally:
        conn.close()
    return jsonify(out)
