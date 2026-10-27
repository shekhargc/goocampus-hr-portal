"""goocampus.in Dashboard Analytics — how registered doctors use the dashboard: how many come
back (visit days), who uses it most, which sections, free vs paid, email opens/clicks, a daily
trend, and what they search for. Built over pg_user_events (website tracking, since 2026-09-24),
pg_login_log (every OTP sign-in, since 2026-10-27) and pg_email_log (bulk email opens/clicks,
since 2026-10-27). Team members are left out unless ?team=1. (founder 2026-09-24, rebuilt 2026-10-27)

"Visit day" = an IST calendar day on which the doctor signed in or used any dashboard section.
Sessions last 30 days, so a returning doctor often does not sign in again — visit days, not
sign-ins, are the true "came back" measure."""
import io
import logging
from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, flash, send_file
from db import get_db
from core.users import get_user
from core.auth import login_required

IST = "INTERVAL '330 minutes'"
TEAM_SQL = "COALESCE((to_jsonb(u)->>'is_team_member')::int, 0) = 1"

SECTION_LABELS = {
    'predictor': 'College Predictor', 'cutoff_explorer': 'Cut-off Explorer', 'college_db': 'College Database',
    'college_fees': 'College Fees', 'stipend': 'Stipend & Bond', 'choice_list': 'Choice List',
    'team_choice_list': 'Team Choice List', 'mentors': 'Mentors', 'events': 'Events',
    'my_allotments': 'My Allotments', 'counselling_updates': 'Counselling Updates (authorities)',
    'deadlines': 'Deadlines', 'seat_matrix': '2026 PG Seat Matrix', 'results_mdms': '2026 Results (MD/MS)',
    'results_dnb': '2026 Results (DNB)', 'result_analysis': 'Round Analysis', 'rankings': 'College Rankings',
    'official_documents': 'Official Documents', 'news': 'News & Updates', 'aiq': 'AIQ', 'ciq': 'CIQ',
    'state': 'State quota', 'deemed': 'Deemed', 'dashboard_home': 'Dashboard home',
}
EMAIL_KINDS = {'news': 'News alert', 'deadline': 'Deadline reminder', 'announcement': 'Announcement',
               'rankings': 'Rankings email'}
CATEGORY_LABELS = {'paid': 'Paid', 'free': 'Free', 'internal': 'Internal client', 'team': 'Team'}
BUCKETS = [('1 day', 1, 1), ('2 days', 2, 2), ('3–5 days', 3, 5), ('6–10 days', 6, 10), ('11+ days', 11, 10 ** 6)]


def section_label(k):
    k = (k or '').strip()
    return SECTION_LABELS.get(k) or (k.replace('_', ' ').title() if k else '(unlabelled)')


def _admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def _window():
    days = (request.args.get('days') or '30').strip()
    if days == 'all':
        return 'all', None
    try:
        d = max(1, min(int(days), 3650))
    except (TypeError, ValueError):
        d = 30
    return str(d), d


def _tw(col, d):
    return f"{col} >= CURRENT_TIMESTAMP - INTERVAL '{int(d)} days'" if d else "TRUE"


def _ensure(conn):
    try:
        from pg_admin.data.analytics_tables import _ensure_login_log
        from pg_admin import email_tracking as ET
        _ensure_login_log(conn); conn.commit()
        ET.ensure(conn)
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.warning("analytics ensure: %s", e)


def _visits_cte(d, uf):
    """per(user_id, days) — visit days inside the window, team filtered."""
    return (f"v AS (SELECT e.user_id, (e.created_at + {IST})::date AS d FROM pg_user_events e "
            f"      WHERE e.user_id IS NOT NULL AND {_tw('e.created_at', d)} "
            f"      UNION SELECT l.user_id, (l.created_at + {IST})::date FROM pg_login_log l "
            f"      WHERE l.user_id IS NOT NULL AND {_tw('l.created_at', d)}), "
            f"per AS (SELECT v.user_id, COUNT(*) AS days FROM v JOIN pg_users u ON u.id = v.user_id "
            f"        WHERE {uf} GROUP BY v.user_id)")


def _doctor_rows(conn, d, uf, limit=None, active_only=True):
    """One row per doctor: visit days, actions, sections, favourite section, sign-ins, last seen."""
    from pg_admin.routes.users_admin import _category_case
    sql = (f"WITH {_visits_cte(d, uf)}, "
           f"ev AS (SELECT user_id, COUNT(*) AS actions, COUNT(DISTINCT NULLIF(TRIM(section),'')) AS sections, "
           f"       MAX(created_at) AS last_seen FROM pg_user_events WHERE user_id IS NOT NULL "
           f"       AND {_tw('created_at', d)} GROUP BY user_id), "
           f"lg AS (SELECT user_id, COUNT(*) AS logins, MAX(created_at) AS last_login FROM pg_login_log "
           f"       WHERE {_tw('created_at', d)} GROUP BY user_id), "
           f"fav AS (SELECT DISTINCT ON (user_id) user_id, section FROM ("
           f"         SELECT user_id, section, COUNT(*) AS c FROM pg_user_events WHERE user_id IS NOT NULL "
           f"         AND COALESCE(TRIM(section),'') <> '' AND {_tw('created_at', d)} GROUP BY 1, 2) t "
           f"       ORDER BY user_id, c DESC) "
           f"SELECT u.id, u.name, u.mobile, u.email, u.state, u.created_at, ({_category_case('u')}) AS cat, "
           f"  COALESCE(per.days, 0) AS days, COALESCE(ev.actions, 0) AS actions, COALESCE(ev.sections, 0) AS sections, "
           f"  fav.section AS fav, COALESCE(lg.logins, 0) AS logins, "
           f"  GREATEST(ev.last_seen, lg.last_login) AS last_seen "
           f"FROM pg_users u LEFT JOIN per ON per.user_id = u.id LEFT JOIN ev ON ev.user_id = u.id "
           f"LEFT JOIN lg ON lg.user_id = u.id LEFT JOIN fav ON fav.user_id = u.id "
           f"WHERE {uf} {'AND per.user_id IS NOT NULL' if active_only else ''} "
           f"ORDER BY COALESCE(per.days,0) DESC, COALESCE(ev.actions,0) DESC, u.id"
           + (f" LIMIT {int(limit)}" if limit else ""))
    out = []
    for r in conn.execute(sql).fetchall():
        r = dict(r)
        r['fav_label'] = section_label(r['fav']) if r.get('fav') else ''
        r['cat_label'] = CATEGORY_LABELS.get(r['cat'], r['cat'])
        out.append(r)
    return out


@login_required
def analytics_admin():
    u = _admin()
    if not u:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    days, d = _window()
    team = request.args.get('team') == '1'
    uf = "TRUE" if team else f"NOT ({TEAM_SQL})"
    conn = get_db()
    data = {'days': days, 'team': team}
    try:
        _ensure(conn)

        def rows(sql, p=()):
            return [dict(r) for r in conn.execute(sql, p).fetchall()]

        def one(sql, p=()):
            r = conn.execute(sql, p).fetchone()
            return dict(r) if r else {}

        V = _visits_cte(d, uf)
        r = one("SELECT MIN(created_at) AS a FROM pg_user_events")
        data['tracking_since'] = r.get('a')
        data['registered'] = one(f"SELECT COUNT(*) AS c FROM pg_users u WHERE {uf}")['c']
        data['new_signups'] = one(f"SELECT COUNT(*) AS c FROM pg_users u WHERE {uf} AND {_tw('u.created_at', d)}")['c']
        s = one(f"WITH {V} SELECT COUNT(*) AS active, COUNT(*) FILTER (WHERE days >= 2) AS ret, "
                f"COUNT(*) FILTER (WHERE days >= 3) AS ret3, COUNT(*) FILTER (WHERE days = 1) AS once, "
                f"ROUND(AVG(days)::numeric, 1) AS avg_days FROM per")
        data.update(active=s.get('active') or 0, returning=s.get('ret') or 0, returning3=s.get('ret3') or 0,
                    once=s.get('once') or 0, avg_days=s.get('avg_days') or 0)
        data['never'] = one(
            f"SELECT COUNT(*) AS c FROM pg_users u WHERE {uf} "
            f"AND NOT EXISTS (SELECT 1 FROM pg_user_events e WHERE e.user_id = u.id) "
            f"AND NOT EXISTS (SELECT 1 FROM pg_login_log l WHERE l.user_id = u.id)")['c']
        data['logins'] = one(f"SELECT COUNT(*) AS c, COUNT(DISTINCT l.user_id) AS doctors FROM pg_login_log l "
                             f"JOIN pg_users u ON u.id = l.user_id WHERE {uf} AND {_tw('l.created_at', d)}")
        data['login_since'] = one("SELECT MIN(created_at) AS a FROM pg_login_log").get('a')

        # How often doctors come back (visit days inside the window)
        per = rows(f"WITH {V} SELECT days, COUNT(*) AS n FROM per GROUP BY days")
        buckets = []
        for lbl, lo, hi in BUCKETS:
            buckets.append({'label': lbl, 'n': sum(x['n'] for x in per if lo <= x['days'] <= hi)})
        buckets.insert(0, {'label': 'Never used the dashboard' if not d else 'Did not visit in this period',
                           'n': (data['never'] if not d else max(0, data['registered'] - data['active'])),
                           'muted': True})
        data['buckets'] = buckets

        # Daily trend (IST days): doctors active, new sign-ups, actions
        n = min(d or 90, 90)
        today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
        start = today - timedelta(days=n - 1)
        act = {x['d']: x['n'] for x in rows(
            f"WITH v AS (SELECT e.user_id, (e.created_at + {IST})::date AS d FROM pg_user_events e "
            f"  WHERE e.user_id IS NOT NULL AND e.created_at >= ?::date - INTERVAL '1 day' "
            f"  UNION SELECT l.user_id, (l.created_at + {IST})::date FROM pg_login_log l "
            f"  WHERE l.created_at >= ?::date - INTERVAL '1 day') "
            f"SELECT v.d, COUNT(DISTINCT v.user_id) AS n FROM v JOIN pg_users u ON u.id = v.user_id "
            f"WHERE {uf} AND v.d >= ? GROUP BY v.d", (start, start, start))}
        sig = {x['d']: x['n'] for x in rows(
            f"SELECT (u.created_at + {IST})::date AS d, COUNT(*) AS n FROM pg_users u "
            f"WHERE {uf} AND (u.created_at + {IST})::date >= ? GROUP BY 1", (start,))}
        trend = []
        for i in range(n):
            day = start + timedelta(days=i)
            trend.append({'d': day, 'active': act.get(day, 0), 'signups': sig.get(day, 0)})
        data['trend'] = trend
        data['trend_max'] = max([t['active'] for t in trend] + [t['signups'] for t in trend] + [1])

        # Sections: doctors using each, repeat users (2+ days), actions
        secs = rows(
            f"WITH s AS (SELECT e.section, e.user_id, COUNT(*) AS acts, "
            f"  COUNT(DISTINCT (e.created_at + {IST})::date) AS dd FROM pg_user_events e "
            f"  JOIN pg_users u ON u.id = e.user_id WHERE {uf} AND {_tw('e.created_at', d)} "
            f"  AND COALESCE(TRIM(e.section),'') <> '' GROUP BY 1, 2) "
            f"SELECT section, COUNT(*) AS doctors, COUNT(*) FILTER (WHERE dd >= 2) AS rep2, "
            f"SUM(acts) AS actions FROM s GROUP BY section ORDER BY doctors DESC, actions DESC")
        for x in secs:
            x['label'] = section_label(x['section'])
        data['sections'] = secs

        # Free vs paid
        from pg_admin.routes.users_admin import _category_case
        cats = rows(
            f"WITH {V} SELECT x.cat, COUNT(*) AS registered, COUNT(per.user_id) AS active, "
            f"COUNT(*) FILTER (WHERE per.days >= 2) AS ret2 "
            f"FROM (SELECT u.id, ({_category_case('u')}) AS cat FROM pg_users u WHERE {uf}) x "
            f"LEFT JOIN per ON per.user_id = x.id GROUP BY x.cat ORDER BY registered DESC")
        for x in cats:
            x['label'] = CATEGORY_LABELS.get(x['cat'], x['cat'])
        data['cats'] = cats

        data['doctors'] = _doctor_rows(conn, d, uf, limit=50)

        # Emails: one row per campaign
        camps = rows(
            f"SELECT kind, COALESCE(ref_id, 0) AS ref_id, ref_label, MAX(subject) AS subject, "
            f"MIN(sent_at) AS first_sent, COUNT(*) FILTER (WHERE sent_ok = 1) AS sent, "
            f"COUNT(*) FILTER (WHERE sent_ok = 1 AND opened_at IS NOT NULL) AS opened, "
            f"COUNT(*) FILTER (WHERE sent_ok = 1 AND clicked_at IS NOT NULL) AS clicked "
            f"FROM pg_email_log WHERE {_tw('sent_at', d)} GROUP BY 1, 2, 3 "
            f"ORDER BY MIN(sent_at) DESC LIMIT 40")
        for x in camps:
            x['kind_label'] = EMAIL_KINDS.get(x['kind'], x['kind'])
        data['camps'] = camps
        data['email_tot'] = {k: sum(x[k] or 0 for x in camps) for k in ('sent', 'opened', 'clicked')}
        data['email_since'] = one("SELECT MIN(sent_at) AS a FROM pg_email_log").get('a')
        ek = request.args.get('ek')
        if ek:
            try:
                er = int(request.args.get('er') or 0)
            except ValueError:
                er = 0
            el = request.args.get('el') or ''
            data['camp_sel'] = {'kind': ek, 'ref_id': er, 'ref_label': el,
                                'kind_label': EMAIL_KINDS.get(ek, ek)}
            data['camp_rows'] = rows(
                "SELECT g.email, g.user_id, g.sent_at, g.opened_at, g.open_count, g.clicked_at, g.click_count, "
                "COALESCE(pu.name, '') AS name FROM pg_email_log g LEFT JOIN pg_users pu ON pu.id = g.user_id "
                "WHERE g.kind = ? AND COALESCE(g.ref_id, 0) = ? AND g.ref_label = ? AND g.sent_ok = 1 "
                "ORDER BY (g.clicked_at IS NULL), (g.opened_at IS NULL), g.email", (ek, er, el))

        # What doctors look for (all tracked events in the window)
        base = f"FROM pg_user_events WHERE {_tw('created_at', d)}"

        def top(col):
            return rows(f"SELECT {col} AS v, COUNT(DISTINCT COALESCE(user_id::text, session_id)) AS c {base} "
                        f"AND COALESCE(TRIM({col}),'') <> '' GROUP BY {col} ORDER BY c DESC LIMIT 12")
        data['specialities'] = top('speciality')
        data['colleges'] = top('college_name')
        data['quotas'] = top('quota')
        data['states'] = top('state')
        rr = one(f"SELECT COUNT(*) AS c, ROUND(AVG(rank)) AS avg_rank {base} AND rank IS NOT NULL")
        data['ranks'] = rr
        data['recent'] = rows(
            "SELECT e.created_at, e.section, e.event_type, e.q, e.college_name, e.speciality, "
            "e.quota, e.category, e.state, e.rank, e.user_id, pu.name AS who "
            "FROM pg_user_events e LEFT JOIN pg_users pu ON pu.id = e.user_id "
            "WHERE e.event_type <> 'filter' ORDER BY e.id DESC LIMIT 40")
        for x in data['recent']:
            x['label'] = section_label(x['section'])
    except Exception as e:
        logging.error("analytics_admin: %s", e)
        try: conn.rollback()
        except Exception: pass
        flash(f'Analytics query failed: {e}', 'error')
    finally:
        conn.close()
    return render_template('pg_admin/analytics.html', d=data, active_section='goocampus_in')


@login_required
def analytics_doctors_xlsx():
    """Every registered doctor with their usage for the chosen period (incl. those who never came)."""
    if not _admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    days, d = _window()
    team = request.args.get('team') == '1'
    uf = "TRUE" if team else f"NOT ({TEAM_SQL})"
    conn = get_db()
    try:
        _ensure(conn)
        docs = _doctor_rows(conn, d, uf, active_only=False)
    finally:
        conn.close()
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from core.helpers import format_dr_name
    try:
        from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE as _BAD
    except Exception:
        _BAD = None

    def clean(v):
        return _BAD.sub('', v) if (_BAD and isinstance(v, str)) else v

    def ist(v):
        return (v + timedelta(hours=5, minutes=30)).strftime('%d-%b-%Y %I:%M %p') if v else ''
    wb = Workbook(); ws = wb.active; ws.title = 'Doctor usage'
    ws.append(['Name', 'Mobile', 'Email', 'Type', 'Home state', 'Signed up (IST)', 'Visit days',
               'Actions', 'Sections used', 'Most-used section', 'Sign-ins (tracked from 27 Oct 2026)',
               'Last seen (IST)'])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in docs:
        nm = r.get('name') or ''
        ws.append([clean(nm if r['cat'] == 'team' else format_dr_name(nm)), r.get('mobile') or '',
                   clean(r.get('email') or ''), r['cat_label'], clean(r.get('state') or ''), ist(r.get('created_at')),
                   r['days'], r['actions'], r['sections'], r['fav_label'], r['logins'], ist(r.get('last_seen'))])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    lbl = 'all-time' if not d else f'last-{d}-days'
    return send_file(buf, as_attachment=True, download_name=f'goocampus-doctor-usage-{lbl}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
