"""goocampus.in Events admin — create events + see who reserved a seat (per event),
separate from the client/counsellor flow. (founder 2026-09-24)"""
import io
import re
import logging
from flask import render_template, request, redirect, url_for, flash, Response
from db import get_db
from core.users import get_user
from core.auth import login_required


def _admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def _s(v):
    return (str(v).strip() if v is not None else '')


def _slugify(t):
    s = re.sub(r'[^a-z0-9]+', '-', _s(t).lower()).strip('-')
    return s[:60] or 'event'


@login_required
def events_admin():
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    try:
        sel = int(request.args.get('event') or 0)
    except (TypeError, ValueError):
        sel = 0
    conn = get_db()
    events, event, regs = [], None, []
    try:
        events = [dict(r) for r in conn.execute(
            "SELECT e.*, (SELECT COUNT(*) FROM pg_event_registrations r WHERE r.event_id=e.id) AS n "
            "FROM pg_events e ORDER BY e.created_at DESC").fetchall()]
        if sel:
            ev = conn.execute("SELECT * FROM pg_events WHERE id = ?", (sel,)).fetchone()
            event = dict(ev) if ev else None
            if event:
                regs = [dict(r) for r in conn.execute(
                    "SELECT * FROM pg_event_registrations WHERE event_id = ? ORDER BY id DESC",
                    (sel,)).fetchall()]
    finally:
        conn.close()
    return render_template('pg_admin/events.html', events=events, event=event, regs=regs,
                           active_section='goocampus_in')


@login_required
def event_create():
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    title = _s(request.form.get('title'))
    if not title:
        flash('Event title is required.', 'error'); return redirect(url_for('pg_events_admin'))
    conn = get_db()
    try:
        base = _slugify(title)
        slug = base
        i = 2
        while conn.execute("SELECT 1 FROM pg_events WHERE slug = ?", (slug,)).fetchone():
            slug = f"{base}-{i}"; i += 1
        conn.execute(
            "INSERT INTO pg_events (slug, title, venue, city, state, event_date, event_time, "
            "description, ticket_prefix) VALUES (?,?,?,?,?,?,?,?,?)",
            (slug, title, _s(request.form.get('venue')), _s(request.form.get('city')),
             _s(request.form.get('state')), _s(request.form.get('event_date')),
             _s(request.form.get('event_time')), _s(request.form.get('description')),
             (_s(request.form.get('ticket_prefix')) or 'GCE').upper()[:8]))
        conn.commit()
        flash(f'Event created. Slug: {slug} — the goocampus.in events page can point at /api/pg/events/{slug}.', 'success')
    except Exception as e:
        conn.rollback(); logging.error("event_create: %s", e)
        flash(f'Could not create event: {e}', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_events_admin'))


@login_required
def event_toggle(event_id):
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        conn.execute("UPDATE pg_events SET is_active = 1 - COALESCE(is_active,1) WHERE id = ?", (event_id,))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return redirect(url_for('pg_events_admin', event=event_id))


@login_required
def event_export(event_id):
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    import openpyxl
    conn = get_db()
    try:
        ev = conn.execute("SELECT * FROM pg_events WHERE id = ?", (event_id,)).fetchone()
        regs = [dict(r) for r in conn.execute(
            "SELECT ticket_code, name, email, mobile, rank, score, domicile_state, college, "
            "target_speciality, city, notes, created_at FROM pg_event_registrations "
            "WHERE event_id = ? ORDER BY id", (event_id,)).fetchall()]
    finally:
        conn.close()
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Registrations'
    cols = ['ticket_code', 'name', 'email', 'mobile', 'rank', 'score', 'domicile_state',
            'college', 'target_speciality', 'city', 'notes', 'created_at']
    ws.append(['Ticket', 'Name', 'Email', 'Mobile', 'Rank', 'Score', 'Domicile', 'College',
               'Target Speciality', 'City', 'Notes', 'Registered'])
    for r in regs:
        ws.append([str(r.get(c)) if r.get(c) is not None else '' for c in cols])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    fname = _slugify((ev['title'] if ev else 'event')) + '-registrations.xlsx'
    return Response(buf.read(),
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': f'attachment; filename="{fname}"'})
