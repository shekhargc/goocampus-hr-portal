"""Public API for goocampus.in Events — list events + "Reserve your seat" registration
with a unique printable ticket. X-PG-Key guarded; NO doctor login required (open event
sign-up), so it must NOT reuse the counsellor-callback client flow. (founder 2026-09-24)
"""
import re
import json
import logging
from flask import request, jsonify
from db import get_db
from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token


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
            'time': r['event_time'], 'description': r['description'],
            'powered_by': (r.get('powered_by') or '')}


def _send_ticket_email(to_email, name, ticket_code, ev):
    """Email the seat confirmation / printable ticket to the registrant. Best-effort:
    a mail failure must never break the registration. (founder 2026-09-25)"""
    if not to_email:
        return
    try:
        from email_utils import send_email, render_branded_email, brand_callout
        title = ev.get('title') or 'GooCampus Event'
        bits = []
        when = ' · '.join([x for x in [ev.get('event_date'), ev.get('event_time')] if x])
        where = ', '.join([x for x in [ev.get('venue'), ev.get('city'), ev.get('state')] if x])
        rows = [
            ('Ticket', ticket_code),
            ('Event', title),
            ('When', when or '—'),
            ('Venue', where or '—'),
        ]
        table = ''.join(
            f'<tr><td style="padding:6px 14px 6px 0;color:#64748b;font-size:13px;white-space:nowrap;vertical-align:top;">{k}</td>'
            f'<td style="padding:6px 0;color:#0f172a;font-size:14px;font-weight:600;">{v}</td></tr>'
            for k, v in rows)
        ticket_box = (
            '<div style="border:2px dashed #F58220;border-radius:12px;padding:18px 20px;margin:6px 0 4px;">'
            '<div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#F58220;font-weight:700;">Your seat is reserved</div>'
            f'<div style="font-size:26px;font-weight:800;color:#0f172a;margin:6px 0 12px;letter-spacing:.02em;">{ticket_code}</div>'
            f'<table style="border-collapse:collapse;">{table}</table>'
            '</div>')
        inner = (
            f'<p style="margin:0 0 14px;">Hi {name or "there"},</p>'
            f'<p style="margin:0 0 16px;">Thank you for reserving your seat for <strong>{title}</strong>. '
            'Please show this ticket at the venue entrance.</p>'
            + ticket_box)
        pb = ev.get('powered_by') or ''
        if pb:
            inner += brand_callout(f'Powered by {pb}', color='#F8FAFC', border='#E2E8F0', tcolor='#475569')
        inner += '<p style="margin:16px 0 0;font-size:13px;color:#64748b;">See you there! — Team GooCampus</p>'
        html = render_branded_email(f'🎟️ {title} — Seat Confirmed', inner,
                                    preheader=f'Your ticket {ticket_code} for {title}')
        send_email([to_email], f'Your seat is reserved — {title} ({ticket_code})', html)
    except Exception as e:
        logging.error("event ticket email (%s): %s", ticket_code, e)


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

        # Logged-in doctor? Tie this registration to them so it shows on their
        # dashboard's "My tickets". Optional — guests can still reserve. (2026-09-25)
        user_id = None
        token = _bearer_token()
        if token:
            u = _pg_user_by_token(conn, token)
            if u:
                user_id = dict(u)['id']

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
            # Backfill the ticket code and/or link to the now-logged-in doctor.
            conn.execute(
                "UPDATE pg_event_registrations SET ticket_code = ?, "
                "user_id = COALESCE(user_id, ?) WHERE id = ?",
                (tc, user_id, existing['id']))
            conn.commit()
            return jsonify({'ok': True, 'already': True,
                            'ticket': {'code': tc, 'name': existing['name'],
                                       'event': _event_public(ev)}})

        extra = {k: body.get(k) for k in body
                 if k not in ('name', 'email', 'mobile', 'rank', 'score', 'domicile_state',
                              'college', 'target_speciality', 'city', 'notes')}
        reg_id = conn.execute(
            "INSERT INTO pg_event_registrations (event_id, user_id, name, email, mobile, rank, score, "
            "domicile_state, college, target_speciality, city, notes, extra) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
            (ev['id'], user_id, name, email, mobile, _int(body.get('rank')), _int(body.get('score')),
             _s(body.get('domicile_state')), _s(body.get('college')),
             _s(body.get('target_speciality')), _s(body.get('city')), _s(body.get('notes')),
             json.dumps(extra) if extra else '')).fetchone()['id']
        tc = _ticket(reg_id)
        conn.execute("UPDATE pg_event_registrations SET ticket_code = ? WHERE id = ?", (tc, reg_id))
        conn.commit()
        _send_ticket_email(email, name, tc, ev)   # best-effort, after commit
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


def api_pg_event_registrations():
    """GET /api/pg/events/registrations → the logged-in doctor's event tickets, for
    the goocampus.in dashboard. Auth: X-PG-Key + doctor Bearer token.
    Matches on user_id (tickets reserved while logged in) OR the doctor's mobile
    last-10 (tickets reserved as a guest with the same number). (founder 2026-09-25)"""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    token = _bearer_token()
    if not token:
        return jsonify({'ok': False, 'error': 'no_token'}), 401
    conn = get_db()
    try:
        u = _pg_user_by_token(conn, token)
        if not u:
            return jsonify({'ok': False, 'error': 'invalid_token'}), 401
        u = dict(u)
        umobile = re.sub(r'\D', '', _s(u.get('mobile')))
        rows = [dict(x) for x in conn.execute(
            "SELECT r.ticket_code, r.name, e.* FROM pg_event_registrations r "
            "JOIN pg_events e ON e.id = r.event_id "
            "WHERE (r.user_id = ? "
            "   OR (LENGTH(?) >= 10 AND RIGHT(regexp_replace(COALESCE(r.mobile,''),'\\D','','g'),10) = RIGHT(?,10))) "
            "AND r.ticket_code IS NOT NULL "
            "ORDER BY e.event_date DESC, r.id DESC",
            (u['id'], umobile, umobile)).fetchall()]
        regs = [{'code': x['ticket_code'], 'name': x['name'], 'event': _event_public(x)}
                for x in rows]
        return jsonify({'ok': True, 'registrations': regs})
    except Exception as e:
        logging.error("api_pg_event_registrations: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
