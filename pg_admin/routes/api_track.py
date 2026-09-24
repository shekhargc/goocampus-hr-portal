"""goocampus.in usage tracking ingest. The frontend POSTs a small event whenever a
doctor opens a section, searches, runs the predictor, opens a college, or filters fees.
X-PG-Key + optional doctor Bearer (→ user_id). Fire-and-forget: never blocks the UI,
never errors loudly. (founder 2026-09-24)"""
import json
import logging
from flask import request, jsonify
from db import get_db
from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token


def _s(v, n=300):
    return (str(v).strip()[:n] if v is not None else '')


def _num(v):
    try:
        s = str(v).replace(',', '').strip()
        return float(s) if s not in ('', 'None') else None
    except (TypeError, ValueError):
        return None


def _int(v):
    try:
        s = str(v).replace(',', '').strip()
        return int(float(s)) if s not in ('', 'None') else None
    except (TypeError, ValueError):
        return None


def api_pg_track():
    """POST /api/pg/track  {section, event_type, q?, college_id?, college_name?, speciality?,
    quota?, category?, state?, authority?, fee_min?, fee_max?, rank?, session_id?, detail?}"""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    body = request.get_json(silent=True) or {}
    section = _s(body.get('section'), 60)
    event_type = _s(body.get('event_type'), 40)
    if not section and not event_type:
        return jsonify({'ok': False, 'error': 'nothing_to_track'}), 400
    conn = get_db()
    try:
        uid = None
        tok = _bearer_token()
        if tok:
            try:
                u = _pg_user_by_token(conn, tok)
                uid = u['id'] if u else None
            except Exception:
                uid = None
        extra = body.get('detail')
        detail = ''
        if extra not in (None, ''):
            try:
                detail = json.dumps(extra)[:2000] if not isinstance(extra, str) else extra[:2000]
            except Exception:
                detail = ''
        conn.execute(
            "INSERT INTO pg_user_events (user_id, session_id, section, event_type, q, college_id, "
            "college_name, speciality, quota, category, state, authority, fee_min, fee_max, rank, detail) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, _s(body.get('session_id'), 80), section, event_type, _s(body.get('q')),
             _int(body.get('college_id')), _s(body.get('college_name')), _s(body.get('speciality')),
             _s(body.get('quota'), 80), _s(body.get('category'), 80), _s(body.get('state'), 80),
             _s(body.get('authority'), 80), _num(body.get('fee_min')), _num(body.get('fee_max')),
             _int(body.get('rank')), detail))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.warning("api_pg_track: %s", e)   # never break the UI over analytics
        return jsonify({'ok': True})              # fail-safe: pretend success
    finally:
        conn.close()
