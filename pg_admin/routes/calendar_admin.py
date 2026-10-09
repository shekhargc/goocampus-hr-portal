"""Admin: Counselling Calendar — every dated counselling step per authority and round
(founder 2026-10-09). Filled automatically when an AI-drafted schedule notice is posted;
this page shows it round-by-round and lets the team add / fix / remove a date. Admin-only.
"""
import logging
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from core.users import get_user
from core.auth import login_required
from pg_admin.data import calendar as CAL
from pg_admin.authorities import all_authorities, get_authority


def _admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


@login_required
def calendar_admin():
    user = _admin()
    if not user:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    code = (request.args.get('authority') or 'mcc').strip().lower()
    auth = get_authority(code) or get_authority('mcc')
    conn = get_db()
    events, counts = [], {}
    rem = {'on': False, 'today_doctors': 0, 'today_items': 0}
    try:
        CAL.ensure_calendar_table(conn)
        try:   # catch up any AI drafts whose schedule isn't in the calendar yet (idempotent)
            if CAL.sync_from_inbox(conn):
                conn.commit()
        except Exception as _se:
            logging.warning("calendar sync: %s", _se)
            conn.rollback()
        try:
            from pg_admin import deadline_reminders as DR
            DR.ensure_tables(conn)
            rem['on'] = DR.is_enabled(conn)
            targets, items = DR.plan(conn)
            rem['today_doctors'], rem['today_items'] = len(targets), len(items)
        except Exception as _re:
            logging.warning("calendar reminders status: %s", _re)
            conn.rollback()
        events = CAL.events_for(conn, [auth['code']])
        for r in conn.execute("SELECT authority_code, COUNT(*) AS n FROM pg_counselling_events "
                              "WHERE is_active GROUP BY authority_code").fetchall():
            counts[r['authority_code']] = r['n']
    except Exception as e:
        logging.error("calendar_admin: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    # group by round, rounds in counselling order
    order = {r: i for i, r in enumerate(CAL.ROUNDS)}
    rounds = {}
    for e in events:
        rounds.setdefault(e['round'] or '', []).append(e)
    grouped = sorted(rounds.items(), key=lambda kv: order.get(kv[0], 50))
    from datetime import date as _date
    return render_template('pg_admin/calendar.html', auth=auth, authorities=all_authorities(), today=_date.today(),
                           counts=counts, grouped=grouped, event_types=CAL.EVENT_TYPES,
                           rounds=[r for r in CAL.ROUNDS if r], rem=rem, active_section='goocampus_in')


@login_required
def calendar_save():
    user = _admin()
    if not user:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    f = request.form
    code = (f.get('authority') or '').strip().lower()
    if not get_authority(code):
        flash('Pick an authority.', 'error'); return redirect(url_for('pg_calendar_admin'))
    ev = CAL.clean_events([{'round': f.get('round'), 'event': f.get('event'), 'label': f.get('label'),
                            'start': f.get('start_date'), 'end': f.get('end_date'), 'time': f.get('time')}])
    if not ev:
        flash('Enter at least a start date.', 'error')
        return redirect(url_for('pg_calendar_admin', authority=code))
    e = ev[0]
    who = user.get('name') or user.get('emp_code') or 'admin'
    eid = (f.get('id') or '').strip()
    conn = get_db()
    try:
        CAL.ensure_calendar_table(conn)
        if eid.isdigit():
            conn.execute("UPDATE pg_counselling_events SET round=?, event=?, label=?, start_date=?, end_date=?, "
                         "time_text=?, note=?, updated_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (e['round'], e['event'], e['label'], e['start'], e['end'] or None, e['time'],
                          (f.get('note') or '').strip()[:300], who, int(eid)))
            flash('Date updated.', 'success')
        else:
            conn.execute("INSERT INTO pg_counselling_events (authority_code, round, event, label, start_date, "
                         "end_date, time_text, note, created_by, updated_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (code, e['round'], e['event'], e['label'], e['start'], e['end'] or None, e['time'],
                          (f.get('note') or '').strip()[:300], who, who))
            flash('Date added.', 'success')
        conn.commit()
    except Exception as ex:
        try: conn.rollback()
        except Exception: pass
        logging.error("calendar_save: %s", ex)
        flash('Could not save.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_calendar_admin', authority=code))


@login_required
def calendar_remove():
    user = _admin()
    if not user:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    code = (request.form.get('authority') or 'mcc').strip().lower()
    try:
        eid = int(request.form.get('id') or 0)
    except ValueError:
        eid = 0
    conn = get_db()
    try:
        conn.execute("UPDATE pg_counselling_events SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP "
                     "WHERE id = ?", (eid,))
        conn.commit()
        flash('Date removed from the calendar.', 'success')
    except Exception as ex:
        try: conn.rollback()
        except Exception: pass
        logging.error("calendar_remove: %s", ex)
        flash('Could not remove.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_calendar_admin', authority=code))


@login_required
def calendar_reminders_toggle():
    user = _admin()
    if not user:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    on = request.form.get('on') == '1'
    from pg_admin import deadline_reminders as DR
    conn = get_db()
    try:
        DR.set_enabled(conn, on, user.get('name') or user.get('emp_code') or 'admin')
        flash('Deadline reminder emails are ON — sent every morning at 8:00 AM IST.' if on
              else 'Deadline reminder emails are OFF.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("calendar_reminders_toggle: %s", e)
        flash('Could not change the setting.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_calendar_admin', authority=request.form.get('authority') or 'mcc'))


@login_required
def calendar_reminders_preview():
    user = _admin()
    if not user:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    to = (request.form.get('to') or '').strip()
    if '@' not in to:
        flash('Enter an email address for the preview.', 'error')
    else:
        from pg_admin import deadline_reminders as DR
        r = DR.run(only_email=to)
        flash(f'Preview sent to {to}.' if r.get('sent') else
              'Nothing to preview yet — add dates to the calendar first.', 'success' if r.get('sent') else 'error')
    return redirect(url_for('pg_calendar_admin', authority=request.form.get('authority') or 'mcc'))
