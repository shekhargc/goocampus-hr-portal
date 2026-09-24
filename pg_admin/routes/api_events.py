"""Public API for goocampus.in Events — list events + "Reserve your seat" registration
with a unique printable ticket. X-PG-Key guarded; NO doctor login required (open event
sign-up), so it must NOT reuse the counsellor-callback client flow. (founder 2026-09-24)
"""
import re
import json
import logging
from flask import request, jsonify
from db import get_db
from pg_admin.routes.api import _authorized


def _s(v):
    return (str(v).strip() if v is not None else '')


def _int(v):
    try:
        s = _s(v).replace(',', '')
        return int(float(s)) if s != '' else None
    except (ValueError, TypeError):
        return None


def _event_public(r):
    return {'slug': r['slug'], 'title': r['title'], 'venue': r['venue'],
            'city': r['city'], 'state': r['state'], 'date': r['event_date'],
            'time': r['event_time'], 'description': r['description']}


def api_pg_events():
    """GET /api/pg/events → active events for the goocampus.in events page."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM pg_events WHERE COALESCE(is_active,1)=1 "
            "ORDER BY event_date, id").fetchall()]
        return jsonify({'ok': True, 'events': [_event_public(r) for r in rows]})
    except Exception as e:
        logging.error("api_pg_events: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pg_event(slug):
    """GET /api/pg/events/<slug> → one event."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        r = conn.execute("SELECT * FROM pg_events WHERE slug = ? AND COALESCE(is_active,1)=1",
                         (slug,)).fetchone()
        if not r:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        return jsonify({'ok': True, 'event': _event_public(dict(r))})
    finally:
        conn.close()


def api_pg_event_register(slug):
    """POST /api/pg/events/<slug>/register
    {name, email, mobile}  (all required) + optional {rank, score, domicile_state,
    college, target_speciality, city, notes}. Returns a unique printable ticket.
    Idempotent per (event, mobile) — re-registering returns the same ticket."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        ev = conn.execute("SELECT * FROM pg_events WHERE slug = ? AND COALESCE(is_active,1)=1",
                          (slug,)).fetchone()
        if not ev:
            return jsonify({'ok': False, 'error': 'event_not_found'}), 404
        ev = dict(ev)
        body = request.get_json(silent=True) or {}
        name = _s(body.get('name'))
        email = _s(body.get('email'))
        mobile = re.sub(r'\D', '', _s(body.get('mobile')))
        if not name or not email or not mobile:
            return jsonify({'ok': False, 'error': 'missing_required',
                            'message': 'Name, email and mobile are required to reserve a seat.'}), 400

        def _ticket(reg_id):
            return f"{(ev.get('ticket_prefix') or 'GCE')}-{reg_id:05d}"

        # Already registered with this mobile? Return the existing ticket (no duplicate).
        existing = conn.execute(
            "SELECT id, ticket_code, name FROM pg_event_registrations "
            "WHERE event_id = ? AND RIGHT(regexp_replace(COALESCE(mobile,''),'\\D','','g'),10) = RIGHT(?,10) "
            "ORDER BY id LIMIT 1", (ev['id'], mobile)).fetchone()
        if existing:
            existing = dict(existing)
            tc = existing['ticket_code'] or _ticket(existing['id'])
            if not existing['ticket_code']:
                conn.execute("UPDATE pg_event_registrations SET ticket_code = ? WHERE id = ?",
                             (tc, existing['id']))
                conn.commit()
            return jsonify({'ok': True, 'already': True,
                            'ticket': {'code': tc, 'name': existing['name'],
                                       'event': _event_public(ev)}})

        extra = {k: body.get(k) for k in body
                 if k not in ('name', 'email', 'mobile', 'rank', 'score', 'domicile_state',
                              'college', 'target_speciality', 'city', 'notes')}
        reg_id = conn.execute(
            "INSERT INTO pg_event_registrations (event_id, name, email, mobile, rank, score, "
            "domicile_state, college, target_speciality, city, notes, extra) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
            (ev['id'], name, email, mobile, _int(body.get('rank')), _int(body.get('score')),
             _s(body.get('domicile_state')), _s(body.get('college')),
             _s(body.get('target_speciality')), _s(body.get('city')), _s(body.get('notes')),
             json.dumps(extra) if extra else '')).fetchone()['id']
        tc = _ticket(reg_id)
        conn.execute("UPDATE pg_event_registrations SET ticket_code = ? WHERE id = ?", (tc, reg_id))
        conn.commit()
        return jsonify({'ok': True, 'ticket': {'code': tc, 'name': name, 'event': _event_public(ev)}})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_event_register: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pg_event_ticket(ticket_code):
    """GET /api/pg/events/ticket/<ticket_code> → ticket data (for re-printing)."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        r = conn.execute(
            "SELECT r.ticket_code, r.name, r.email, r.mobile, e.* FROM pg_event_registrations r "
            "JOIN pg_events e ON e.id = r.event_id WHERE r.ticket_code = ?",
            (ticket_code,)).fetchone()
        if not r:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        r = dict(r)
        return jsonify({'ok': True, 'ticket': {'code': r['ticket_code'], 'name': r['name'],
                                               'event': _event_public(r)}})
    finally:
        conn.close()
