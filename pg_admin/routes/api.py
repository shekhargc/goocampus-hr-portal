"""Public `/api/pg/*` mentor endpoints — the goocampus.in Next.js user panel calls
these service-to-service. Guarded by the shared secret in the X-PG-Key header
(must equal env PG_API_KEY), exactly like the existing POST /api/pg/lead.

PUBLIC FIELDS ONLY: the mentor JSON never exposes email, phone, medical council
number/state, or admin_notes (see pg_admin/utils.mentor_public_dict). Only mentors
with is_published = TRUE AND is_active = TRUE are visible.
"""
import os
import re
import json
import random
import secrets
import logging
from datetime import datetime, timedelta
from flask import request, jsonify, redirect, abort, Response
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
    sname = (data.get('name') or '').strip()[:120]   # optional: goocampus.in may send the name at signup
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
            uid, uname = user['id'], (user['name'] or '')
            # If the site now sends a name and we don't have one, capture it.
            if sname and not uname:
                conn.execute("UPDATE pg_users SET name = ?, session_token = ?, token_expires_at = ?, "
                             "last_login_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                             (sname, token, token_exp, uid))
                uname = sname
            else:
                conn.execute("UPDATE pg_users SET session_token = ?, token_expires_at = ?, "
                             "last_login_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                             (token, token_exp, uid))
        else:
            uid = conn.execute("INSERT INTO pg_users (mobile, name, session_token, token_expires_at, last_login_at) "
                               "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) RETURNING id",
                               (mobile, sname, token, token_exp)).fetchone()['id']
            uname = sname
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
    mtype = (request.args.get('type') or '').strip()
    if mtype in ('specialist', 'peer_to_peer'):
        conds.append("mentor_type = ?")
        params.append(mtype)

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
            "SELECT photo_url, source_photo_url FROM pg_mentors "
            "WHERE id = ? AND is_published AND is_active",
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
    if not row:
        abort(404)
    key = row.get('photo_url')
    if key and key.startswith('pg_mentors/'):
        url = storage.presigned_get_url(key)
        if url:
            return redirect(url, code=302)
    # No migrated photo. Serve a generated initials avatar rather than 404 or a
    # redirect to the old goocampus-s3bucket — that bucket is PRIVATE (403), so
    # redirecting there just renders a broken image on every card. This makes
    # <img src=".../photo"> always work; consumers that want their own placeholder
    # can still branch on the JSON's photo_url being null. (founder 2026-07-28)
    name = (row.get('name') or '').strip()
    parts = [p for p in name.replace('.', ' ').split() if p]
    initials = ((parts[0][0] + parts[-1][0]) if len(parts) > 1 else
                (parts[0][:2] if parts else '?')).upper()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">'
        '<rect width="256" height="256" fill="#FFF7ED"/>'
        '<circle cx="128" cy="128" r="120" fill="#FFEDD5" stroke="#FED7AA" stroke-width="4"/>'
        f'<text x="50%" y="50%" dy=".35em" text-anchor="middle" '
        f'font-family="system-ui,-apple-system,Segoe UI,Arial,sans-serif" '
        f'font-size="96" font-weight="700" fill="#F97316">{initials}</text></svg>'
    )
    return Response(svg, mimetype='image/svg+xml',
                    headers={'Cache-Control': 'public, max-age=3600'})


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
    quota = (request.args.get('quota') or '').strip()
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
        if quota and quota.lower() not in ('any', 'any quota'):
            where.append("quota ILIKE ?"); params.append(f"%{quota}%")
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
    """GET /api/pg/predictor/filters[?authority=&quota=]

    CASCADING option lists, straight from the loaded dataset (founder 2026-07-28):
      - no args      -> authorities (+ all categories/states, for compatibility)
      - ?authority=  -> the quotas that actually exist for THAT authority
      - ?authority=&quota= -> the categories that exist for that authority+quota

    So the dropdowns only ever offer combinations that return results, instead of
    a flat list where most choices find nothing.
    """
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    authority = (request.args.get('authority') or '').strip()
    quota = (request.args.get('quota') or '').strip()
    conn = get_db()
    out = {'ok': True, 'year': None, 'authorities': [], 'quotas': [],
           'categories': [], 'states': []}
    try:
        yr = conn.execute("SELECT COALESCE(MAX(year), 0) AS y FROM pg_cutoffs").fetchone()
        year = int(yr['y']) if yr and yr['y'] else 0
        out['year'] = year or None
        if not year:
            return jsonify(out)

        def _distinct(col, extra_where='', extra_params=()):
            return [r[col] for r in conn.execute(
                f"SELECT DISTINCT {col} FROM pg_cutoffs "
                f" WHERE year = ? AND COALESCE({col},'') <> '' {extra_where} "
                f" ORDER BY {col}", (year,) + tuple(extra_params)).fetchall()]

        out['authorities'] = _distinct('authority')
        out['states'] = _distinct('state')
        if authority:
            out['quotas'] = _distinct('quota', 'AND authority = ?', (authority,))
            if quota:
                out['categories'] = _distinct(
                    'category', 'AND authority = ? AND quota = ?', (authority, quota))
            else:
                out['categories'] = _distinct('category', 'AND authority = ?', (authority,))
        else:
            out['quotas'] = _distinct('quota')
            out['categories'] = _distinct('category')
    except Exception as e:
        logging.error("api_pg_predictor_filters: %s", e)
    finally:
        conn.close()
    return jsonify(out)


def api_pg_predictor_courses():
    """GET /api/pg/predictor/courses?q=&authority=&limit=

    Speciality/course names matching a typed fragment — powers the type-ahead on
    the site so a doctor picks a real course instead of guessing a keyword that
    may match nothing. Scoped to the chosen authority when given.
    (founder 2026-07-28)"""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    q = (request.args.get('q') or '').strip()
    authority = (request.args.get('authority') or '').strip()
    try:
        limit = min(int(request.args.get('limit') or 20), 50)
    except (TypeError, ValueError):
        limit = 20
    conn = get_db()
    courses = []
    try:
        yr = conn.execute("SELECT COALESCE(MAX(year), 0) AS y FROM pg_cutoffs").fetchone()
        year = int(yr['y']) if yr and yr['y'] else 0
        if year:
            where = ["year = ?", "COALESCE(course,'') <> ''"]
            params = [year]
            if q:
                where.append("course ILIKE ?")
                params.append(f"%{q}%")
            if authority:
                where.append("authority = ?")
                params.append(authority)
            # Most-offered courses first: a doctor typing 'radio' should see the
            # common MD Radiodiagnosis before a one-off variant.
            courses = [r['course'] for r in conn.execute(
                f"SELECT course, COUNT(*) AS n FROM pg_cutoffs "
                f" WHERE {' AND '.join(where)} "
                f" GROUP BY course ORDER BY n DESC, course ASC LIMIT ?",
                params + [limit]).fetchall()]
    except Exception as e:
        logging.error("api_pg_predictor_courses: %s", e)
    finally:
        conn.close()
    return jsonify({'ok': True, 'courses': courses})


def api_pg_neetpg_pdfs():
    """GET /api/pg/neetpg-pdfs?category=&specialty=&state=&q=

    The NEET-PG cut-off PDF library for the goocampus.in user dashboard.

    Reads the SAME neetpg_pdfs library the goocampus.org page serves — one library,
    two front-ends — so uploads made in the existing admin appear on both. The
    goocampus.org page keeps its own behaviour untouched.

    Difference on .in (founder 2026-07-28): only REAL files are returned —
    published AND actually carrying a file — so the site never shows a
    "coming soon" placeholder. Metadata only; bytes come from /file.
    """
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    # Every filter the goocampus.org cut-off library exposes, so the .in dashboard
    # can reproduce the SAME UI (doc-type tabs, NEET-PG/DNB split, State, Specialty,
    # Quota & Category). category = 'neetpg'|'dnb'; doc_type = cutoff|mcc_profile|…
    category = (request.args.get('category') or '').strip()
    doc_type = (request.args.get('doc_type') or '').strip()
    specialty = (request.args.get('specialty') or '').strip()
    state = (request.args.get('state') or '').strip()
    quota = (request.args.get('quota') or request.args.get('quota_category') or '').strip()
    q = (request.args.get('q') or '').strip()

    where = ["COALESCE(is_active, 1) = 1", "COALESCE(is_published, 0) = 1",
             "file_data IS NOT NULL", "COALESCE(file_size, 0) > 0"]
    params = []
    if category:
        where.append("category = ?"); params.append(category)
    if doc_type:
        where.append("doc_type = ?"); params.append(doc_type)
    if specialty:
        where.append("specialty = ?"); params.append(specialty)
    if state:
        where.append("state = ?"); params.append(state)
    if quota:
        where.append("quota_category = ?"); params.append(quota)
    if q:
        where.append("(title ILIKE ? OR specialty ILIKE ? OR file_name ILIKE ?)")
        params.extend([f"%{q}%"] * 3)

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, title, category, doc_type, specialty, quota_category, state, "
            "       file_name, file_size, upload_date, published_at, "
            "       COALESCE(download_count,0) AS download_count "
            f"  FROM neetpg_pdfs WHERE {' AND '.join(where)} "
            "  ORDER BY state ASC, specialty ASC, title ASC", params).fetchall()
        # Filter values that actually exist, so the site's controls never offer a
        # choice that returns nothing. Keyed to match the .org UI's four filters.
        facets = {}
        for col in ('category', 'doc_type', 'specialty', 'state', 'quota_category'):
            facets[col + 's'] = [r[col] for r in conn.execute(
                f"SELECT DISTINCT {col} FROM neetpg_pdfs "
                "  WHERE COALESCE(is_active,1)=1 AND COALESCE(is_published,0)=1 "
                f"    AND file_data IS NOT NULL AND COALESCE({col},'') <> '' "
                f"  ORDER BY {col}").fetchall()]
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        conn.close()
        logging.error("api_pg_neetpg_pdfs: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    conn.close()

    base = _photo_base()
    pdfs = []
    for r in rows:
        d = as_dict(r)
        d['file_url'] = f"{base}/api/pg/neetpg-pdfs/{r['id']}/file"
        d['file_size_kb'] = round((r['file_size'] or 0) / 1024)
        if d.get('upload_date') is not None:
            d['upload_date'] = str(d['upload_date'])[:10]
        pdfs.append(d)
    return jsonify({'ok': True, 'count': len(pdfs), 'pdfs': pdfs, **facets})


def api_pg_neetpg_pdf_file(pdf_id):
    """GET /api/pg/neetpg-pdfs/:id/file — stream one PDF and count the download.

    Public (no key): it's the file itself, and only published+active rows with real
    bytes are ever served — the same content the goocampus.org library hands out."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT title, file_name, file_data FROM neetpg_pdfs "
            "  WHERE id = ? AND COALESCE(is_active,1)=1 AND COALESCE(is_published,0)=1",
            (pdf_id,)).fetchone()
        if not row or not row['file_data']:
            conn.close()
            abort(404)
        try:
            conn.execute("UPDATE neetpg_pdfs SET download_count = COALESCE(download_count,0)+1 "
                         "WHERE id = ?", (pdf_id,))
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
        data = bytes(row['file_data'])
        fname = (row['file_name'] or f"{row['title']}.pdf").replace('"', '')
    except Exception as e:
        try: conn.close()
        except Exception: pass
        logging.error("api_pg_neetpg_pdf_file(%s): %s", pdf_id, e)
        abort(404)
    conn.close()
    return Response(data, mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="{fname}"',
                             'Cache-Control': 'public, max-age=3600'})


# ══════════════════════════════════════════════════════════════════════════════
# Pricing, entitlements & coupons — the goocampus.in site + user dashboard call
# these. Everything below is X-PG-Key guarded like the rest of this file. Endpoints
# that act on a specific doctor also resolve that doctor from their login token.
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_pg_user(conn):
    """The logged-in doctor for this request, or None.

    The site holds the session token issued at OTP verify. It forwards it as
    X-PG-User-Token (or ?token= / body token). A None result means "treat as a
    logged-out free visitor" — never an error, so public pricing still renders.
    """
    token = request.headers.get('X-PG-User-Token') or request.args.get('token')
    if not token and request.is_json:
        token = (request.get_json(silent=True) or {}).get('token')
    if not token:
        return None
    try:
        row = conn.execute(
            "SELECT id FROM pg_users WHERE session_token = ? "
            "AND (token_expires_at IS NULL OR token_expires_at > CURRENT_TIMESTAMP) "
            "AND COALESCE(is_blocked,0) = 0", (token,)).fetchone()
        return row['id'] if row else None
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return None


def api_pg_plans():
    """GET /api/pg/plans → the public pricing cards, exactly as configured in admin.

    Only active + public plans, each with its feature list resolved to plain values
    the site can render without knowing the schema. This is what a doctor sees on
    the pricing page.
    """
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        plans = [dict(r) for r in conn.execute(
            "SELECT * FROM pg_plans WHERE COALESCE(is_active,1)=1 AND COALESCE(is_public,1)=1 "
            "ORDER BY sort_order, id").fetchall()]
        feats = {r['code']: dict(r) for r in conn.execute(
            "SELECT * FROM pg_features WHERE COALESCE(is_active,1)=1 "
            "ORDER BY sort_order, id").fetchall()}
        matrix = {}
        for r in conn.execute("SELECT * FROM pg_plan_features").fetchall():
            matrix.setdefault(r['plan_id'], {})[r['feature_code']] = dict(r)
        out = []
        for p in plans:
            grants = matrix.get(p['id'], {})
            features = []
            for code, f in feats.items():
                g = grants.get(code)
                if not g or g['value_type'] == 'off':
                    included, display = False, None
                elif g['value_type'] == 'unlimited':
                    included, display = True, 'Unlimited'
                elif f['unit'] == 'boolean':
                    included, display = True, 'Included'
                elif g['limit_value'] is not None:
                    included, display = True, int(g['limit_value'])
                else:
                    included, display = True, 'Unlimited'
                features.append({'code': code, 'name': f['name'], 'unit': f['unit'],
                                 'included': included, 'value': display,
                                 'note': g['note'] if g else ''})
            try:
                highlights = json.loads(p.get('highlights') or '[]')
            except Exception:
                highlights = []
            out.append({
                'id': p['id'], 'code': p['code'], 'name': p['name'],
                'tagline': p.get('tagline') or '', 'description': p.get('description') or '',
                'plan_kind': p.get('plan_kind') or 'paid',
                'price': float(p.get('price') or 0),
                'compare_at_price': float(p['compare_at_price']) if p.get('compare_at_price') else None,
                'currency': p.get('currency') or 'INR',
                'billing_period': p.get('billing_period') or 'one_time',
                'badge_text': p.get('badge_text') or '', 'badge_color': p.get('badge_color') or '',
                'accent_color': p.get('accent_color') or '', 'is_featured': bool(p.get('is_featured')),
                'cta_label': p.get('cta_label') or '', 'highlights': highlights,
                'features': features,
            })
        return jsonify({'ok': True, 'plans': out})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_plans: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pg_entitlements():
    """GET /api/pg/entitlements → this doctor's plan + every limit/used/remaining.

    One call powers the whole dashboard: which sections to show, what to grey out,
    and the "2 of 3 PDFs used — upgrade for the rest" nudges.
    """
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    from pg_admin.data import entitlements
    conn = get_db()
    try:
        uid = _resolve_pg_user(conn)
        return jsonify({'ok': True, 'logged_in': bool(uid),
                        'entitlements': entitlements.summary(conn, uid)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_entitlements: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pg_entitlement_consume():
    """POST /api/pg/entitlements/consume {feature, item_key?} → allow + record.

    The gate the site calls the instant a doctor opens a gated thing (a PDF, a new
    state). It re-checks server-side — the front-end greying-out is a courtesy, this
    is the real fence — and only records usage when it actually allows the action.
    Returns 402 with the entitlement info when blocked, so the site can show the
    right upgrade prompt.
    """
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    from pg_admin.data import entitlements
    data = request.get_json(silent=True) or {}
    feature = (data.get('feature') or '').strip()
    item_key = data.get('item_key')
    if not feature:
        return jsonify({'ok': False, 'error': 'feature required'}), 400
    conn = get_db()
    try:
        uid = _resolve_pg_user(conn)
        if not uid:
            return jsonify({'ok': False, 'allowed': False, 'reason': 'login_required'}), 401
        allowed, info = entitlements.check(conn, uid, feature, item_key=item_key)
        if not allowed:
            return jsonify({'ok': True, 'allowed': False, 'info': info}), 402
        entitlements.consume(conn, uid, feature, item_key=item_key)
        conn.commit()
        return jsonify({'ok': True, 'allowed': True, 'info': info})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_entitlement_consume: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pg_coupon_validate():
    """POST /api/pg/coupons/validate {code, plan_id} → discount + payable.

    Read-only: it prices the discount so the checkout can show it, but never burns
    a use. Redemption happens only after payment succeeds (built with the Razorpay
    step, not here). Works for logged-out visitors too, so the pricing page can
    preview a code before login.
    """
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    from pg_admin.data import coupons as coupon_lib
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or '').strip()
    plan_id = data.get('plan_id')
    conn = get_db()
    try:
        uid = _resolve_pg_user(conn)
        ok, res = coupon_lib.validate(conn, code, plan_id=plan_id, user_id=uid)
        return jsonify({'ok': ok, 'result': res})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_coupon_validate: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def _bearer_token():
    """The doctor's session token from an Authorization: Bearer header — the form
    goocampus.in's dashboard uses — falling back to X-PG-User-Token / ?token=."""
    auth = request.headers.get('Authorization') or ''
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return (request.headers.get('X-PG-User-Token') or request.args.get('token') or '').strip()


# ── Doctor profile field blueprint ──────────────────────────────────────────
# SINGLE source of truth for what the doctor's profile is, shared by BOTH the
# goocampus.org admin (pg_users) and the goocampus.in Edit Profile. GET returns
# this blueprint + the doctor's current values so the site renders the form
# dynamically — add a field here (and its pg_users column) and it auto-appears on
# goocampus.in with no change on their side. 'editable': False = show read-only.
PG_PROFILE_BLUEPRINT = [
    {'key': 'name',              'label': 'Full Name',         'type': 'text',   'editable': True,  'required': True},
    {'key': 'email',             'label': 'Email',             'type': 'email',  'editable': True},
    {'key': 'mobile',            'label': 'Mobile',            'type': 'tel',    'editable': False},
    {'key': 'neet_pg_year',      'label': 'NEET-PG Year',      'type': 'text',   'editable': True},
    {'key': 'neet_pg_rank',      'label': 'NEET-PG Rank',      'type': 'number', 'editable': True},
    {'key': 'target_speciality', 'label': 'Target Speciality', 'type': 'text',   'editable': True},
    {'key': 'college',           'label': 'MBBS College',      'type': 'text',   'editable': True},
    {'key': 'state',             'label': 'State',             'type': 'text',   'editable': True},
    {'key': 'city',              'label': 'City',              'type': 'text',   'editable': True},
    {'key': 'photo_url',         'label': 'Profile Photo',     'type': 'image',  'editable': True},
]
_PG_INT_FIELDS = {'neet_pg_rank'}


def _pg_user_by_token(conn, token):
    return conn.execute(
        "SELECT * FROM pg_users WHERE session_token = ? "
        "AND (token_expires_at IS NULL OR token_expires_at > CURRENT_TIMESTAMP) "
        "AND COALESCE(is_blocked,0) = 0", (token,)).fetchone()


def api_pg_profile():
    """Two-way doctor profile sync with the goocampus.in dashboard, on the SAME
    pg_users record the /admin/pg/users screen shows — so the two always match.

      GET  /api/pg/profile → {ok, fields:[blueprint], values:{key:value}}  (render the form)
      POST /api/pg/profile → saves the editable fields (whitelisted to the blueprint)

    Auth: X-PG-Key handshake + the doctor's session token (Bearer).
    Back-compat: old payloads with first_name/last_name/mbbs_college still work."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    token = _bearer_token()
    if not token:
        return jsonify({'ok': False, 'error': 'no_token'}), 401
    conn = get_db()
    try:
        row = _pg_user_by_token(conn, token)
        if not row:
            return jsonify({'ok': False, 'error': 'invalid_token'}), 401
        row = as_dict(row)

        if request.method == 'GET':
            values = {}
            for f in PG_PROFILE_BLUEPRINT:
                v = row.get(f['key'])
                values[f['key']] = '' if v is None else v
            return jsonify({'ok': True, 'fields': PG_PROFILE_BLUEPRINT, 'values': values})

        # POST — save the doctor's edits.
        data = request.get_json(silent=True) or {}
        # Back-compat aliases from the old goocampus.in payload shape.
        if 'name' not in data and (data.get('first_name') or data.get('last_name')):
            data['name'] = ((data.get('first_name') or '') + ' ' + (data.get('last_name') or '')).strip()
        if 'college' not in data and data.get('mbbs_college'):
            data['college'] = data.get('mbbs_college')

        sets, params = [], []
        for f in PG_PROFILE_BLUEPRINT:
            if not f.get('editable') or f['key'] not in data:
                continue
            k = f['key']
            val = data.get(k)
            if k in _PG_INT_FIELDS:
                s = str(val).strip() if val is not None else ''
                try:
                    val = int(s) if s != '' else None
                except (ValueError, TypeError):
                    val = None
            else:
                val = (str(val).strip() if val is not None else '')
            sets.append(f"{k} = ?")
            params.append(val)
        if not sets:
            return jsonify({'ok': True, 'updated': 0})
        params.append(row['id'])
        conn.execute(
            f"UPDATE pg_users SET {', '.join(sets)}, updated_by = 'goocampus.in', "
            f"updated_at = CURRENT_TIMESTAMP WHERE id = ?", params)
        conn.commit()
        return jsonify({'ok': True, 'updated': len(sets)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_profile: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── Razorpay checkout ────────────────────────────────────────────────────────
# Payment lives on the portal (server-side) so the Razorpay SECRET never touches
# the goocampus.in browser. Flow: create-order (server makes a Razorpay order for
# the plan price − coupon) → the site opens Razorpay Checkout with the public
# key_id → verify (server checks the signature, starts the subscription, burns the
# coupon). No SDK needed: REST via `requests`, signature via stdlib HMAC.

def _razorpay_creds():
    return ((os.environ.get('RAZORPAY_KEY_ID') or '').strip(),
            (os.environ.get('RAZORPAY_KEY_SECRET') or '').strip())


def _ensure_pg_orders(conn):
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_orders (
            id SERIAL PRIMARY KEY,
            razorpay_order_id TEXT UNIQUE,
            user_id INTEGER,
            plan_id INTEGER,
            amount NUMERIC(12,2) DEFAULT 0,
            discount NUMERIC(12,2) DEFAULT 0,
            payable NUMERIC(12,2) DEFAULT 0,
            coupon_code TEXT DEFAULT '',
            coupon_id INTEGER,
            status TEXT DEFAULT 'created',
            razorpay_payment_id TEXT DEFAULT '',
            subscription_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP
        )''')
        conn.commit()
    except Exception:
        conn.rollback()


def _start_pg_subscription(conn, user_id, plan, price_paid, discount, coupon_code, payment_ref, source):
    """Insert an active subscription for the plan; returns its id."""
    from datetime import datetime as _dt, timedelta as _td
    exp = None
    if plan.get('duration_days'):
        try:
            exp = (_dt.utcnow() + _td(days=int(plan['duration_days']))).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            exp = None
    row = conn.execute(
        "INSERT INTO pg_subscriptions (user_id, plan_id, status, expires_at, price_paid, "
        " discount_amount, coupon_code, payment_ref, source) "
        "VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?) RETURNING id",
        (user_id, plan['id'], exp, float(price_paid or 0), float(discount or 0),
         coupon_code or '', payment_ref or '', source)).fetchone()
    return row['id']


def api_pg_checkout_create_order():
    """POST /api/pg/checkout/create-order {plan_id, coupon_code?} → a Razorpay order
    for the plan price minus any coupon. Auth: X-PG-Key + the doctor's login token.
    If a coupon makes it free, the subscription is started immediately (no payment)."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    key_id, key_secret = _razorpay_creds()
    if not (key_id and key_secret):
        return jsonify({'ok': False, 'error': 'payments_not_configured'}), 503
    token = _bearer_token()
    if not token:
        return jsonify({'ok': False, 'error': 'login_required'}), 401
    from pg_admin.data import coupons as coupon_lib
    data = request.get_json(silent=True) or {}
    plan_id = data.get('plan_id')
    code = (data.get('coupon_code') or '').strip()
    conn = get_db()
    try:
        _ensure_pg_orders(conn)
        user = as_dict(_pg_user_by_token(conn, token) or {})
        if not user:
            return jsonify({'ok': False, 'error': 'invalid_token'}), 401
        uid = user['id']
        plan = conn.execute("SELECT * FROM pg_plans WHERE id = ? AND COALESCE(is_active,1) = 1", (plan_id,)).fetchone()
        if not plan:
            return jsonify({'ok': False, 'error': 'plan_not_found'}), 404
        plan = as_dict(plan)
        amount = float(plan.get('price') or 0)
        if (plan.get('plan_kind') or 'paid') == 'free' or amount <= 0:
            return jsonify({'ok': False, 'error': 'plan_is_free'}), 400

        discount = 0.0
        coupon_id = None
        coupon_code = ''
        if code:
            ok, res = coupon_lib.validate(conn, code, plan_id=plan_id, user_id=uid)
            if not ok:
                return jsonify({'ok': False, 'error': res.get('error') or 'invalid_coupon'}), 400
            discount = float(res.get('discount') or 0)
            coupon_id = res.get('coupon_id')
            coupon_code = res.get('code') or code
        payable = round(amount - discount, 2)

        # Fully covered by the coupon → activate now, no Razorpay charge.
        if payable <= 0:
            sub_id = _start_pg_subscription(conn, uid, plan, 0, discount, coupon_code, '', 'coupon_free')
            if coupon_id:
                coupon_lib.redeem(conn, coupon_id, user_id=uid, plan_id=plan['id'],
                                  subscription_id=sub_id, order_amount=amount,
                                  discount_amount=discount, code=coupon_code)
            conn.commit()
            return jsonify({'ok': True, 'free': True, 'subscription_id': sub_id, 'plan_id': plan['id']})

        paise = int(round(payable * 100))
        import requests as _rq
        try:
            rr = _rq.post('https://api.razorpay.com/v1/orders',
                          auth=(key_id, key_secret),
                          json={'amount': paise, 'currency': (plan.get('currency') or 'INR'),
                                'receipt': f'pg_{uid}_{plan_id}',
                                'notes': {'user_id': str(uid), 'plan_id': str(plan_id)}},
                          timeout=20)
        except Exception as e:
            logging.error("razorpay order request: %s", e)
            return jsonify({'ok': False, 'error': 'gateway_error'}), 502
        if rr.status_code not in (200, 201):
            logging.error("razorpay order %s: %s", rr.status_code, rr.text[:300])
            return jsonify({'ok': False, 'error': 'gateway_error'}), 502
        order = rr.json()
        conn.execute(
            "INSERT INTO pg_orders (razorpay_order_id, user_id, plan_id, amount, discount, "
            " payable, coupon_code, coupon_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'created')",
            (order['id'], uid, plan_id, amount, discount, payable, coupon_code, coupon_id))
        conn.commit()
        return jsonify({'ok': True, 'order_id': order['id'], 'amount': paise,
                        'currency': order.get('currency', 'INR'), 'key_id': key_id,
                        'plan_name': plan.get('name') or '',
                        'prefill': {'name': user.get('name') or '',
                                    'email': user.get('email') or '',
                                    'contact': user.get('mobile') or ''}})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_checkout_create_order: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pg_checkout_verify():
    """POST /api/pg/checkout/verify {razorpay_order_id, razorpay_payment_id,
    razorpay_signature} → verify the signature, start the subscription, burn the
    coupon. Auth: X-PG-Key + the doctor's login token. Idempotent."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    key_id, key_secret = _razorpay_creds()
    if not key_secret:
        return jsonify({'ok': False, 'error': 'payments_not_configured'}), 503
    token = _bearer_token()
    if not token:
        return jsonify({'ok': False, 'error': 'login_required'}), 401
    data = request.get_json(silent=True) or {}
    oid = (data.get('razorpay_order_id') or '').strip()
    pid = (data.get('razorpay_payment_id') or '').strip()
    sig = (data.get('razorpay_signature') or '').strip()
    if not (oid and pid and sig):
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    import hmac as _hmac, hashlib as _hl
    expected = _hmac.new(key_secret.encode(), f"{oid}|{pid}".encode(), _hl.sha256).hexdigest()
    if not _hmac.compare_digest(expected, sig):
        return jsonify({'ok': False, 'error': 'signature_mismatch'}), 400
    from pg_admin.data import coupons as coupon_lib
    conn = get_db()
    try:
        _ensure_pg_orders(conn)
        user = as_dict(_pg_user_by_token(conn, token) or {})
        if not user:
            return jsonify({'ok': False, 'error': 'invalid_token'}), 401
        order = conn.execute("SELECT * FROM pg_orders WHERE razorpay_order_id = ?", (oid,)).fetchone()
        if not order:
            return jsonify({'ok': False, 'error': 'order_not_found'}), 404
        order = as_dict(order)
        if order.get('user_id') != user['id']:
            return jsonify({'ok': False, 'error': 'order_mismatch'}), 403
        if order.get('status') == 'paid':
            return jsonify({'ok': True, 'already': True, 'subscription_id': order.get('subscription_id'),
                            'plan_id': order.get('plan_id')})
        plan = as_dict(conn.execute("SELECT * FROM pg_plans WHERE id = ?", (order['plan_id'],)).fetchone() or {})
        sub_id = _start_pg_subscription(conn, user['id'], plan, order.get('payable'),
                                        order.get('discount'), order.get('coupon_code'), pid, 'razorpay')
        if order.get('coupon_id'):
            coupon_lib.redeem(conn, order['coupon_id'], user_id=user['id'], plan_id=order['plan_id'],
                              subscription_id=sub_id, order_amount=order.get('amount'),
                              discount_amount=order.get('discount'), code=order.get('coupon_code') or '')
        conn.execute("UPDATE pg_orders SET status='paid', razorpay_payment_id=?, subscription_id=?, "
                     "paid_at=CURRENT_TIMESTAMP WHERE id=?", (pid, sub_id, order['id']))
        conn.commit()
        return jsonify({'ok': True, 'subscription_id': sub_id, 'plan_id': order['plan_id']})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_checkout_verify: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
