"""Admin: Mentor Session Requests from goocampus.in (founder 2026-09-11).

A doctor expresses INTEREST in a paid session with a mentor (no time chosen).
The team calls back, coordinates a slot with the mentor, then confirms and sets
the date/time here — which flows back to the doctor's My Bookings on goocampus.in.
True-admin gated (same as the rest of pg_admin; not yet in Access Master).
"""
import logging
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from core.users import get_user

_STATUSES = ['pending', 'contacted', 'confirmed', 'completed', 'rejected', 'cancelled']
_STATUS_LABELS = {
    'pending': 'New — to call', 'contacted': 'Contacted', 'confirmed': 'Confirmed',
    'completed': 'Completed', 'rejected': 'Not available', 'cancelled': 'Cancelled',
}


def _require_admin():
    user = get_user()
    if not user or not user.get('is_admin'):
        return None
    return user


def bookings_admin():
    user = _require_admin()
    if not user:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    status_filter = (request.args.get('status') or '').strip()
    conn = get_db()
    try:
        where, params = [], []
        if status_filter in _STATUSES:
            where.append("status = ?"); params.append(status_filter)
        wsql = ("WHERE " + " AND ".join(where)) if where else ""
        rows = conn.execute(
            f"SELECT * FROM pg_bookings {wsql} ORDER BY "
            "CASE status WHEN 'pending' THEN 0 WHEN 'contacted' THEN 1 ELSE 2 END, id DESC",
            params).fetchall()
        counts = {'all': 0}
        crows = conn.execute("SELECT status, COUNT(*) AS n FROM pg_bookings GROUP BY status").fetchall()
        for cr in crows:
            counts[cr['status']] = cr['n']; counts['all'] += cr['n']
    except Exception as e:
        logging.error(f"bookings_admin: {e}")
        rows, counts = [], {'all': 0}
    finally:
        try: conn.close()
        except Exception: pass
    return render_template('pg_admin/bookings.html', bookings=rows, statuses=_STATUSES,
                           status_labels=_STATUS_LABELS, status_filter=status_filter,
                           counts=counts, active_section='pg_admin')


def booking_update(booking_id):
    user = _require_admin()
    if not user:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        status = (request.form.get('status') or 'pending').strip()
        if status not in _STATUSES:
            status = 'pending'
        conn.execute('''UPDATE pg_bookings SET status = ?, scheduled_date = ?, scheduled_time = ?,
            meeting_link = ?, admin_notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?''',
            (status, (request.form.get('scheduled_date') or '').strip(),
             (request.form.get('scheduled_time') or '').strip(),
             (request.form.get('meeting_link') or '').strip(),
             (request.form.get('admin_notes') or '').strip(), booking_id))
        conn.commit()
        flash('Session request updated', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"booking_update: {e}")
        flash('Could not update the request', 'error')
    finally:
        try: conn.close()
        except Exception: pass
    return redirect(url_for('pg_bookings_admin', status=(request.form.get('return_status') or '')))
