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


def _require_events_section(action='view'):
    """Admin OR an employee granted goocampus.in → 'Events'. Returns the user or None,
    so an Access Master grant lets a team member see event sign-ups. (founder 2026-09-28)"""
    u = get_user()
    if not u:
        return None
    if u.get('is_admin'):
        return u
    try:
        from app import has_section_permission
        if has_section_permission(u, 'goocampus_in', 'events', action):
            return u
    except Exception:
        pass
    return None


def _s(v):
    return (str(v).strip() if v is not None else '')


def _slugify(t):
    s = re.sub(r'[^a-z0-9]+', '-', _s(t).lower()).strip('-')
    return s[:60] or 'event'


@login_required
def events_admin():
    u = _require_events_section("view")
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    try:
        sel = int(request.args.get('event') or 0)
    except (TypeError, ValueError):
        sel = 0
    conn = get_db()
    events, event, regs, summary = [], None, [], {}
    try:
        _ensure_reg_fields(conn)
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
                summary = {
                    'total': len(regs),
                    'attended': sum(1 for r in regs if r.get('attendance') == 'attended'),
                    'not_attended': sum(1 for r in regs if r.get('attendance') == 'not_attended'),
                    'online': sum(1 for r in regs if r.get('session_mode') == 'online'),
                    'offline': sum(1 for r in regs if r.get('session_mode') == 'offline'),
                    'spoken': sum(1 for r in regs if r.get('contact_status') == 'spoken'),
                    'completed': sum(1 for r in regs if r.get('contact_status') == 'completed'),
                    'not_spoken': sum(1 for r in regs if r.get('contact_status') == 'not_spoken'),
                }
    finally:
        conn.close()
    return render_template('pg_admin/events.html', events=events, event=event, regs=regs,
                           summary=summary, active_section='goocampus_in')


@login_required
def event_create():
    u = _require_events_section("edit")
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
            "description, ticket_prefix, powered_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (slug, title, _s(request.form.get('venue')), _s(request.form.get('city')),
             _s(request.form.get('state')), _s(request.form.get('event_date')),
             _s(request.form.get('event_time')), _s(request.form.get('description')),
             (_s(request.form.get('ticket_prefix')) or 'GCE').upper()[:8],
             _s(request.form.get('powered_by'))))
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
    u = _require_events_section("edit")
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
def event_toggle_registration(event_id):
    """Close / re-open NEW registrations for an event without hiding it (recap + ticket
    reprint keep working). (founder 2026-10-04)"""
    u = _require_events_section("edit")
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        conn.execute("ALTER TABLE pg_events ADD COLUMN IF NOT EXISTS reg_closed INTEGER DEFAULT 0")
        conn.execute("UPDATE pg_events SET reg_closed = 1 - COALESCE(reg_closed,0) WHERE id = ?", (event_id,))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return redirect(url_for('pg_events_admin', event=event_id))


# Team working-list fields — the only columns event_reg_update may write, each mapped
# to the set of values it accepts ('' = cleared). Keeps the endpoint from being used to
# overwrite the registrant's own data. (founder 2026-10-04)
_REG_FIELDS = {
    'attendance':     {'', 'attended', 'not_attended'},
    'session_mode':   {'', 'offline', 'online'},
    'contact_status': {'', 'not_spoken', 'spoken', 'completed'},
    'staff_notes':    None,   # free text
}

# Human labels for the Excel export.
_REG_LABELS = {
    'attendance': {'attended': 'Attended', 'not_attended': 'Not attended'},
    'session_mode': {'offline': 'Offline', 'online': 'Online'},
    'contact_status': {'not_spoken': 'Not spoken', 'spoken': 'Spoken', 'completed': 'Completed'},
}


def _ensure_reg_fields(conn):
    """Request-time guard: the team columns may be missing if the boot migration was
    skipped on a Render cold start. (reference: Render cold-start migrations)"""
    for col in ('attendance', 'session_mode', 'contact_status', 'staff_notes', 'edited_by'):
        conn.execute(f"ALTER TABLE pg_event_registrations ADD COLUMN IF NOT EXISTS {col} TEXT DEFAULT ''")
    conn.execute("ALTER TABLE pg_event_registrations ADD COLUMN IF NOT EXISTS edited_by_id INTEGER")
    conn.execute("ALTER TABLE pg_event_registrations ADD COLUMN IF NOT EXISTS edited_at TIMESTAMP")


def _ist_str(dt):
    """A UTC datetime → 'DD-Mon-YYYY, hh:mm AM/PM IST' (matches the format_datetime filter)."""
    from datetime import timedelta
    if not dt:
        return ''
    try:
        return (dt + timedelta(hours=5, minutes=30)).strftime('%d-%b-%Y, %I:%M %p') + ' IST'
    except (AttributeError, ValueError, TypeError):
        return ''


@login_required
def event_reg_update(reg_id):
    """POST {attendance, session_mode, contact_status, staff_notes} — save the team
    working-list fields for ONE registrant (from the row drawer, an explicit Save).
    Only the fields present in the form are written. Stamps who edited + when (UTC),
    so the team sees which member last updated the row. Team-editable (Events 'edit')."""
    from flask import jsonify
    from datetime import datetime
    u = _require_events_section("edit")
    if not u:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    u = dict(u)
    sets, params = [], []
    for field, allowed in _REG_FIELDS.items():
        if field not in request.form:          # drawer sends all 4; absent = leave untouched
            continue
        value = _s(request.form.get(field))
        if allowed is not None and value not in allowed:
            return jsonify({'ok': False, 'error': 'bad_value', 'field': field}), 400
        sets.append(f"{field} = ?"); params.append(value)
    if not sets:
        return jsonify({'ok': False, 'error': 'nothing_to_save'}), 400
    now = datetime.utcnow()
    editor = u.get('name') or 'Team'
    sets += ["edited_by = ?", "edited_by_id = ?", "edited_at = ?"]
    params += [editor, u.get('id'), now]
    params.append(reg_id)
    conn = get_db()
    try:
        _ensure_reg_fields(conn)
        conn.execute(f"UPDATE pg_event_registrations SET {', '.join(sets)} WHERE id = ?", tuple(params))
        conn.commit()
        return jsonify({'ok': True, 'edited_by': editor, 'edited_at': _ist_str(now)})
    except Exception as e:
        conn.rollback(); logging.error("event_reg_update: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


@login_required
def event_export(event_id):
    u = _require_events_section("view")
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    import openpyxl
    conn = get_db()
    try:
        _ensure_reg_fields(conn)
        ev = conn.execute("SELECT * FROM pg_events WHERE id = ?", (event_id,)).fetchone()
        regs = [dict(r) for r in conn.execute(
            "SELECT ticket_code, name, email, mobile, rank, score, domicile_state, college, "
            "target_speciality, city, attendance, session_mode, contact_status, staff_notes, "
            "notes, edited_by, edited_at, created_at FROM pg_event_registrations "
            "WHERE event_id = ? ORDER BY id", (event_id,)).fetchall()]
    finally:
        conn.close()
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Registrations'
    cols = ['ticket_code', 'name', 'email', 'mobile', 'rank', 'score', 'domicile_state',
            'college', 'target_speciality', 'city', 'attendance', 'session_mode',
            'contact_status', 'staff_notes', 'notes', 'edited_by', 'edited_at', 'created_at']
    ws.append(['Ticket', 'Name', 'Email', 'Mobile', 'Rank', 'Score', 'Domicile', 'College',
               'Target Speciality', 'City', 'Attendance', 'Session mode', 'Contact status',
               'Team notes', 'Registrant note', 'Last edited by', 'Last edited (IST)', 'Registered'])
    for r in regs:
        row = []
        for c in cols:
            v = r.get(c)
            if c == 'edited_at':
                v = _ist_str(v)
            else:
                v = '' if v is None else str(v)
                if c in _REG_LABELS:        # show the friendly label, not the code
                    v = _REG_LABELS[c].get(v, v)
            row.append(v)
        ws.append(row)
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    fname = _slugify((ev['title'] if ev else 'event')) + '-registrations.xlsx'
    return Response(buf.read(),
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': f'attachment; filename="{fname}"'})
