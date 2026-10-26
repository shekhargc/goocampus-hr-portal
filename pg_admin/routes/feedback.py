"""Doctor feedback on the goocampus.in dashboard + Google review invites (founder 2026-10-26).

When: once, after the doctor's 3rd visit day OR as soon as they have a seat allotment (whichever first) — plus a
Feedback button any time. Never shown again automatically after they answer or close it.
What: 1–5 stars + what they like (tick the sections from LIKE_OPTIONS + an optional "Other" line) + what to improve
(+ may we call). Stored here; the team works it on
/admin/pg/feedback (status, notes, Excel).
Google review (founder's rule): invited only when the doctor has a seat allotment AND rated 4–5 stars. A 1–3 star
rating raises a team alert (portal bell) for a call-back; once the team marks it Resolved, the doctor is offered the
Google review on their next visit. Clicks on the Google link are counted.

Doctor APIs (X-PG-Key + doctor token):
  GET  /api/pg/my/feedback            → {show_prompt, trigger, like_options, review:{show, url, qr_image}, given}
  POST /api/pg/my/feedback            {rating, liked_tags:[...], liked (Other text), improve, call_ok, page, trigger}
                                      → {ok, show_google, ...}
  POST /api/pg/my/feedback-prompt     {action:'close'} — closed without answering: never auto-shown again
  POST /api/pg/my/review-click        — counts the Google click (and stops re-offering)
"""
import io
import logging
from flask import request, jsonify, render_template, redirect, url_for, flash, send_file
from db import get_db
from core.auth import login_required

REVIEW_URL = 'https://g.page/r/CWVb6jAK7SwKEBM/review'
REVIEW_QR_URL = REVIEW_URL + '?utm_source=gbp&utm_medium=reviews&utm_campaign=qr'   # the link the QR encodes
QR_IMAGE_PATH = '/static/img/google-review-qr.png'     # public PNG of that QR (no key needed)


def _qr_image():
    return request.url_root.rstrip('/') + QR_IMAGE_PATH
VISIT_DAYS = 3
# "What do you like?" tick boxes — the website renders this list as-is, so rename/add sections here only.
# Kept short (founder): the main sections only; anything else goes in the "Other" line.
LIKE_OPTIONS = ['College Predictor', 'Cut-offs', 'Seat Matrix', 'Counselling Results', 'News & Updates',
                'Counselling team support']
STATUSES = ('New', 'Call back', 'Reviewed', 'Planned', 'Done', 'Resolved')


def _s(v):
    return str(v).strip() if v is not None else ''


def ensure(conn):
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_feedback (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            rating INTEGER,
            liked TEXT DEFAULT '',
            improve TEXT DEFAULT '',
            call_ok INTEGER DEFAULT 0,
            page TEXT DEFAULT '',
            trigger TEXT DEFAULT '',            -- visits | allotment | button
            doctor_type TEXT DEFAULT '',        -- internal | paid | free | team (at the time)
            has_allotment INTEGER DEFAULT 0,
            status TEXT DEFAULT 'New',
            team_notes TEXT DEFAULT '',
            handled_by TEXT DEFAULT '',
            handled_at TIMESTAMP,
            review_offered INTEGER DEFAULT 0,   -- Google invite shown with this feedback / after it was resolved
            review_clicked_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_feedback_user ON pg_feedback (user_id)")
        if not conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name='pg_feedback' "
                            "AND column_name='liked_tags'").fetchone():
            conn.execute("ALTER TABLE pg_feedback ADD COLUMN IF NOT EXISTS liked_tags TEXT DEFAULT ''")
        for col, typ in (('feedback_prompt_closed_at', 'TIMESTAMP'), ('feedback_given_at', 'TIMESTAMP')):
            if not conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name='pg_users' "
                                "AND column_name=?", [col]).fetchone():
                conn.execute(f"ALTER TABLE pg_users ADD COLUMN IF NOT EXISTS {col} {typ}")
        conn.commit()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("feedback.ensure: %s", e)


def _doctor(conn):
    from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token
    if not _authorized():
        return None, (jsonify({'ok': False, 'error': 'unauthorized'}), 401)
    tok = _bearer_token()
    u = _pg_user_by_token(conn, tok) if tok else None
    if not u:
        return None, (jsonify({'ok': False, 'error': 'invalid_token'}), 401)
    return dict(u), None


def _has_allotment(conn, u):
    try:
        from pg_admin import allotments as AL
        AL.ensure(conn)
        return bool([a for a in AL.for_users(conn, [u]).get(u['id'], []) if a['verdict'] != 'not_me'])
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return False


def _visit_days(conn, uid):
    try:
        r = conn.execute("SELECT COUNT(DISTINCT (created_at + INTERVAL '330 minutes')::date) AS n FROM pg_user_events "
                         "WHERE user_id = ?", [uid]).fetchone()
        return int(r['n'] or 0)
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return 0


def _doctor_type(conn, uid):
    try:
        from pg_admin.routes.users_admin import _category_case
        r = conn.execute(f"SELECT ({_category_case('u')}) AS t FROM pg_users u WHERE u.id = ?", [uid]).fetchone()
        return r['t'] if r else ''
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return ''


def _pending_review(conn, uid):
    """A resolved low rating → offer the Google review once, on the next visit."""
    return conn.execute("SELECT id FROM pg_feedback WHERE user_id = ? AND status = 'Resolved' AND review_offered = 0 "
                        "ORDER BY id DESC LIMIT 1", [uid]).fetchone()


def my_feedback_state():
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor(conn)
        if err:
            return err
        given = u.get('feedback_given_at') is not None
        closed = u.get('feedback_prompt_closed_at') is not None
        allotted = _has_allotment(conn, u)
        days = _visit_days(conn, u['id'])
        trigger = 'allotment' if allotted else ('visits' if days >= VISIT_DAYS else '')
        show = (not given) and (not closed) and bool(trigger)
        pend = _pending_review(conn, u['id'])
        if pend:          # shown now — mark offered so it appears only once
            conn.execute("UPDATE pg_feedback SET review_offered = 1 WHERE id = ?", [pend['id']])
            conn.commit()
        return jsonify({'ok': True, 'show_prompt': show, 'trigger': trigger, 'given': given,
                        'like_options': LIKE_OPTIONS,
                        'review': {'show': bool(pend), 'url': REVIEW_URL, 'qr_url': REVIEW_QR_URL,
                                   'qr_image': _qr_image(),
                                   'message': 'Thank you for giving us the chance to make it right. Would you share '
                                              'your experience on Google?' if pend else ''}})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("my_feedback_state: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def my_feedback_submit():
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor(conn)
        if err:
            return err
        d = request.get_json(silent=True) or {}
        try:
            rating = int(d.get('rating'))
        except (TypeError, ValueError):
            rating = 0
        if rating < 1 or rating > 5:
            return jsonify({'ok': False, 'error': 'bad_rating', 'message': 'Please choose 1 to 5 stars.'}), 400
        allotted = _has_allotment(conn, u)
        show_google = allotted and rating >= 4
        low = rating <= 3
        dtype = _doctor_type(conn, u['id'])
        tags = d.get('liked_tags') or []
        if isinstance(tags, str):
            tags = tags.split(',')
        tags = [t for t in LIKE_OPTIONS if t in {_s(x) for x in tags}]     # only known sections, in list order
        fid = conn.execute(
            "INSERT INTO pg_feedback (user_id, rating, liked_tags, liked, improve, call_ok, page, trigger, doctor_type, "
            "has_allotment, status, review_offered) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
            [u['id'], rating, ','.join(tags), _s(d.get('liked'))[:2000], _s(d.get('improve'))[:2000],
             1 if d.get('call_ok') else 0,
             _s(d.get('page'))[:200], _s(d.get('trigger'))[:20], dtype, 1 if allotted else 0,
             'Call back' if low else 'New', 1 if show_google else 0]).fetchone()['id']
        conn.execute("UPDATE pg_users SET feedback_given_at = CURRENT_TIMESTAMP WHERE id = ?", [u['id']])
        conn.commit()
        if low:
            _alert_team(conn, u, rating, fid)
        return jsonify({'ok': True, 'id': fid, 'show_google': show_google,
                        'google_url': REVIEW_URL if show_google else '',
                        'google_qr_url': REVIEW_QR_URL if show_google else '',
                        'google_qr_image': _qr_image() if show_google else '',
                        'message': ('Thank you! Would you share your experience on Google? It helps other doctors '
                                    'find us.' if show_google else
                                    ('Sorry we fell short. Our counselling team will call you within 24 hours to '
                                     'make it right.' if low else 'Thank you for your feedback!'))})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("my_feedback_submit: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def _alert_team(conn, u, rating, fid):
    """Portal bell for admins + everyone granted goocampus.in → Doctor Feedback."""
    try:
        from app import create_notification
        ids = {r['id'] for r in conn.execute("SELECT id FROM employees WHERE is_active = 1 AND is_admin = 1").fetchall()}
        for r in conn.execute(
                "SELECT COALESCE(subject_id, employee_id) AS eid FROM user_section_permissions "
                "WHERE main_section = 'goocampus_in' AND sub_section = 'doctor_feedback' AND can_view = 1 "
                "AND COALESCE(subject_type,'employee') = 'employee'").fetchall():
            if r['eid']:
                ids.add(r['eid'])
        from core.helpers import format_dr_name as dr_name
        who = dr_name(u.get('name') or '') if (u.get('name') or '').strip() else (u.get('mobile') or 'A doctor')
        for eid in ids:
            create_notification(conn, eid, f'{rating}★ feedback — call back within 24 h',
                                f"{who} · {u.get('mobile') or ''}", 'lead', f'/admin/pg/feedback?open={fid}')
        conn.commit()
    except Exception as e:
        logging.warning("feedback alert: %s", e)
        try: conn.rollback()
        except Exception: pass


def my_feedback_prompt():
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor(conn)
        if err:
            return err
        conn.execute("UPDATE pg_users SET feedback_prompt_closed_at = COALESCE(feedback_prompt_closed_at, "
                     "CURRENT_TIMESTAMP) WHERE id = ?", [u['id']])
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("my_feedback_prompt: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def my_review_click():
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor(conn)
        if err:
            return err
        conn.execute("UPDATE pg_feedback SET review_clicked_at = COALESCE(review_clicked_at, CURRENT_TIMESTAMP) "
                     "WHERE id = (SELECT id FROM pg_feedback WHERE user_id = ? AND review_offered = 1 "
                     "ORDER BY id DESC LIMIT 1)", [u['id']])
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("my_review_click: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── Admin: Doctor Feedback ────────────────────────────────────────────────────
def _require(action='view'):
    from core.users import get_user
    user = get_user()
    if not user:
        return None
    if user.get('is_admin'):
        return user
    try:
        from app import has_section_permission
        if has_section_permission(user, 'goocampus_in', 'doctor_feedback', action):
            return user
    except Exception:
        pass
    return None


def _rows(conn, a):
    conds, params = ['1=1'], []
    if _s(a.get('rating')):
        r = _s(a.get('rating'))
        if r == 'low':
            conds.append('f.rating <= 3')
        elif r == 'high':
            conds.append('f.rating >= 4')
        elif r.isdigit():
            conds.append('f.rating = ?'); params.append(int(r))
    if _s(a.get('status')):
        conds.append('f.status = ?'); params.append(_s(a.get('status')))
    if _s(a.get('type')):
        conds.append('f.doctor_type = ?'); params.append(_s(a.get('type')))
    if _s(a.get('likes')):
        conds.append("(',' || COALESCE(f.liked_tags,'') || ',') LIKE ?"); params.append('%,' + _s(a.get('likes')) + ',%')
    if _s(a.get('q')):
        conds.append("(u.name ILIKE ? OR u.mobile ILIKE ? OR f.liked ILIKE ? OR f.liked_tags ILIKE ? OR f.improve ILIKE ?)")
        params += ['%' + _s(a.get('q')) + '%'] * 5
    return [dict(r) for r in conn.execute(
        "SELECT f.*, u.name, u.mobile, u.email, u.state FROM pg_feedback f LEFT JOIN pg_users u ON u.id = f.user_id "
        f"WHERE {' AND '.join(conds)} ORDER BY f.id DESC LIMIT 1000", params).fetchall()]


@login_required
def feedback_admin():
    user = _require('view')
    if not user:
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        ensure(conn)
        rows = _rows(conn, request.args)
        s = conn.execute(
            "SELECT COUNT(*) AS n, ROUND(AVG(rating)::numeric, 2) AS avg, "
            "COALESCE(SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END),0) AS happy, "
            "COALESCE(SUM(CASE WHEN rating <= 3 THEN 1 ELSE 0 END),0) AS low, "
            "COALESCE(SUM(CASE WHEN status = 'Call back' THEN 1 ELSE 0 END),0) AS callback, "
            "COALESCE(SUM(review_offered),0) AS invited, "
            "COALESCE(SUM(CASE WHEN review_clicked_at IS NOT NULL THEN 1 ELSE 0 END),0) AS clicked "
            "FROM pg_feedback").fetchone()
        like_counts = {t: 0 for t in LIKE_OPTIONS}          # how many doctors ticked each section (all feedback)
        for x in conn.execute("SELECT liked_tags FROM pg_feedback WHERE COALESCE(liked_tags,'') <> ''").fetchall():
            for t in (x['liked_tags'] or '').split(','):
                if t in like_counts:
                    like_counts[t] += 1
    finally:
        conn.close()
    from core.helpers import format_dr_name as dr_name
    for r in rows:
        r['display_name'] = dr_name(r['name']) if (r.get('name') or '').strip() else (r.get('mobile') or '—')
    return render_template('pg_admin/feedback.html', rows=rows, stats=dict(s), statuses=STATUSES, a=request.args,
                           like_options=LIKE_OPTIONS, like_counts=like_counts,
                           open_id=_s(request.args.get('open')), review_url=REVIEW_URL,
                           can_edit=bool(_require('edit')), active_section='goocampus_in')


@login_required
def feedback_update(fid):
    user = _require('edit')
    if not user:
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    f = request.form
    status = _s(f.get('status'))
    conn = get_db()
    try:
        ensure(conn)
        cur = conn.execute("SELECT team_notes FROM pg_feedback WHERE id = ?", [fid]).fetchone()
        if not cur:
            flash('Not found.', 'error')
            return redirect(url_for('pg_feedback_admin'))
        note = _s(f.get('note'))
        from datetime import datetime, timedelta
        stamp = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%d-%b-%Y %I:%M %p')
        who = user.get('name') or user.get('emp_code') or 'team'
        notes = (cur['team_notes'] or '')
        if note:
            notes = (f"[{stamp} · {who}] {note}\n" + notes)[:8000]   # append-only, newest first
        if status in STATUSES:
            notes = (f"[{stamp} · {who}] status → {status}\n" + notes)[:8000]
            conn.execute("UPDATE pg_feedback SET status = ?, team_notes = ?, handled_by = ?, handled_at = CURRENT_TIMESTAMP "
                         "WHERE id = ?", [status, notes, who, fid])
        else:
            conn.execute("UPDATE pg_feedback SET team_notes = ?, handled_by = ?, handled_at = CURRENT_TIMESTAMP "
                         "WHERE id = ?", [notes, who, fid])
        conn.commit()
        flash('Saved.' + (' The doctor will be offered the Google review on their next visit.'
                          if status == 'Resolved' else ''), 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("feedback_update: %s", e)
        flash('Could not save.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_feedback_admin'))


@login_required
def feedback_download():
    if not _require('view'):
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    from openpyxl import Workbook
    conn = get_db()
    try:
        ensure(conn)
        rows = _rows(conn, request.args)
    finally:
        conn.close()
    from core.helpers import format_dr_name as dr_name
    wb = Workbook()
    ws = wb.active
    ws.title = 'Doctor feedback'
    ws.append(['Date (IST)', 'Doctor', 'Mobile', 'Email', 'State', 'Type', 'Rating', 'Sections they like', 'Other likes',
               'What to improve', 'May we call', 'Page', 'Asked because', 'Has allotment', 'Status',
               'Google invite shown', 'Clicked Google', 'Team notes'])
    from datetime import timedelta
    for r in rows:
        ws.append([(r['created_at'] + timedelta(hours=5, minutes=30)).strftime('%d-%b-%Y %H:%M') if r.get('created_at') else '',
                   dr_name(r['name']) if (r.get('name') or '').strip() else '', r.get('mobile') or '',
                   r.get('email') or '', r.get('state') or '', r.get('doctor_type') or '', r['rating'],
                   (r.get('liked_tags') or '').replace(',', ', '), r.get('liked') or '', r.get('improve') or '',
                   'Yes' if r.get('call_ok') else 'No', r.get('page') or '',
                   r.get('trigger') or '', 'Yes' if r.get('has_allotment') else 'No', r.get('status') or '',
                   'Yes' if r.get('review_offered') else 'No', 'Yes' if r.get('review_clicked_at') else 'No',
                   r.get('team_notes') or ''])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name='GooCampus_Doctor_Feedback.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
