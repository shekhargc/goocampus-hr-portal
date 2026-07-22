"""Public `/api/pg/*` mentor endpoints — the goocampus.in Next.js user panel calls
these service-to-service. Guarded by the shared secret in the X-PG-Key header
(must equal env PG_API_KEY), exactly like the existing POST /api/pg/lead.

PUBLIC FIELDS ONLY: the mentor JSON never exposes email, phone, medical council
number/state, or admin_notes (see pg_admin/utils.mentor_public_dict). Only mentors
with is_published = TRUE AND is_active = TRUE are visible.
"""
import os
import logging
from flask import request, jsonify, redirect, abort
from db import get_db
from pg_admin.utils import mentor_public_dict, as_dict


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
