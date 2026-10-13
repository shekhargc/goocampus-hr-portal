"""Deadline reminder emails from the Counselling Calendar (founder 2026-10-09).

Every morning (8:00 AM IST) each registered doctor gets ONE digest email listing the
counselling steps that matter to them today:
  - opens today          (registration / document verification / choice filling start)
  - closes in 3 days     (any step with an end date, and payment / reporting last dates)
  - closes today
Authorities a doctor gets: All-India MCC (everyone) + their home state + their counselling
states (pg_doctor_states) + states they follow for news (pg_news_follows).

Safety: OFF until switched on in Counselling Calendar (setting 'deadline_reminders' = on);
runs only on the LIVE service (not staging, which shares the DB); each (doctor, step, kind)
is sent at most once (pg_deadline_reminder_log). A preview can be sent to one address.
"""
import logging
import os
import threading
import time
from datetime import date, timedelta
from html import escape

from db import get_db

logger = logging.getLogger(__name__)
DASHBOARD_URL = "https://goocampus.in"
OPEN_EVENTS = ('registration', 'verification', 'choice_filling', 'choice_locking')
CLOSE_LEAD_DAYS = 3


# ── tables / setting ────────────────────────────────────────────────────────
def ensure_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_kv (key TEXT PRIMARY KEY, value TEXT DEFAULT '',
                    updated_by TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_deadline_reminder_log (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, event_id INTEGER NOT NULL,
        kind TEXT NOT NULL, sent_on DATE DEFAULT CURRENT_DATE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE (user_id, event_id, kind))''')
    conn.commit()


def is_enabled(conn):
    try:
        r = conn.execute("SELECT value FROM pg_kv WHERE key = 'deadline_reminders'").fetchone()
        return bool(r and r['value'] == 'on')
    except Exception:
        conn.rollback()
        return False


def set_enabled(conn, on, who):
    ensure_tables(conn)
    conn.execute("INSERT INTO pg_kv (key, value, updated_by, updated_at) VALUES ('deadline_reminders', ?, ?, "
                 "CURRENT_TIMESTAMP) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
                 "updated_by = EXCLUDED.updated_by, updated_at = CURRENT_TIMESTAMP", ('on' if on else 'off', who))
    conn.commit()


# ── what's due today ────────────────────────────────────────────────────────
def due_items(conn, today=None):
    """[(event_row, kind, when_text)] — steps to remind about today: opens today, and closing
    steps 3 days and 1 day before (website + founder, 2026-10-09)."""
    from pg_admin.data import calendar as CAL
    CAL.ensure_calendar_table(conn)
    today = today or date.today()
    d1, d3 = today + timedelta(days=1), today + timedelta(days=3)
    rows = conn.execute(
        "SELECT * FROM pg_counselling_events WHERE is_active AND (start_date IN (?, ?, ?) OR end_date IN (?, ?))",
        (today, d1, d3, d1, d3)).fetchall()
    closing_single = ('payment', 'reporting', 'registration', 'choice_filling', 'verification', 'choice_locking')
    out = []
    for r in rows:
        r = dict(r)
        s, e = r.get('start_date'), r.get('end_date')
        last = e or (s if r['event'] in closing_single else None)
        if e and s == today and r['event'] in OPEN_EVENTS:
            out.append((r, 'opens', 'opens today'))
        if not e and s == today and r['event'] == 'result':
            out.append((r, 'on', 'today'))
        if last == d3:
            out.append((r, 'close3', f'closes in 3 days ({last.strftime("%d %b")})'))
        if last == d1:
            out.append((r, 'close1', f'closes TOMORROW ({last.strftime("%d %b")})'))
    return out


def _doctor_states(conn):
    """{user_id: set(lowercase states)} from home/counselling states + news follows + profile."""
    m = {}
    for sql in ("SELECT user_id, state FROM pg_doctor_states",
                "SELECT user_id, state FROM pg_news_follows",
                "SELECT id AS user_id, state FROM pg_users WHERE COALESCE(state,'') <> ''"):
        try:
            for r in conn.execute(sql).fetchall():
                if r['state']:
                    m.setdefault(r['user_id'], set()).add(r['state'].strip().lower())
        except Exception:
            conn.rollback()
    return m


def _doctors(conn):
    rows = conn.execute(
        "SELECT u.id, u.name, LOWER(TRIM(u.email)) AS email, "
        "  COALESCE((to_jsonb(u)->>'is_team_member')::int, 0) AS is_team, "
        "  EXISTS (SELECT 1 FROM pg_subscriptions s JOIN pg_plans p ON p.id = s.plan_id "
        "          WHERE s.user_id = u.id AND s.status = 'active' AND p.plan_kind IN ('paid','counselling') "
        "          AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP)) AS has_plan "
        "FROM pg_users u WHERE COALESCE(u.email,'') <> '' AND strpos(u.email, '@') > 0").fetchall()
    seen, out = set(), []
    for r in rows:
        if r['email'] in seen:
            continue
        seen.add(r['email'])
        out.append(dict(r))
    return out


def plan(conn, today=None):
    """{user: [(event_row, kind, when)]} — who gets what today (before de-dup with the log)."""
    from pg_admin.authorities import get_authority
    items = due_items(conn, today)
    if not items:
        return [], items
    states = _doctor_states(conn)
    out = []
    for d in _doctors(conn):
        mine = []
        st = states.get(d['id'], set())
        for r, kind, when in items:
            if r['authority_code'] == 'mcc':
                mine.append((r, kind, when))
            else:
                a = get_authority(r['authority_code']) or {}
                if (a.get('state') or '').strip().lower() in st:
                    mine.append((r, kind, when))
        if mine:
            out.append((d, mine))
    return out, items


# ── email ───────────────────────────────────────────────────────────────────
def build_email(doctor, mine):
    from email_utils import render_branded_email, brand_button
    from pg_admin.authorities import get_authority
    from pg_admin.news_email import _dr_name
    dr = _dr_name(doctor.get('name'))
    rows = []
    for r, kind, when in sorted(mine, key=lambda x: (x[1] != 'close1', x[0]['end_date'] or x[0]['start_date'])):
        a = get_authority(r['authority_code']) or {}
        urgent = kind == 'close1'
        rng = r['start_date'].strftime('%d %b')
        if r.get('end_date'):
            rng += ' – ' + r['end_date'].strftime('%d %b %Y')
        else:
            rng = r['start_date'].strftime('%d %b %Y')
        rnd_txt = (" · " + escape(r["round"])) if r.get("round") else ""
        time_txt = ('<br><span style="color:#64748b;font-size:12px;">' + escape(r["time_text"]) + '</span>'
                    if r.get("time_text") else "")
        rows.append(
            '<tr>'
            f'<td style="padding:9px 10px;border-top:1px solid #fde4cf;font-size:13px;color:#334155;">'
            f'<b>{escape(a.get("name", r["authority_code"]))}</b>{rnd_txt}<br>'
            f'<span style="color:#0f172a;font-size:14px;font-weight:700;">{escape(r.get("label") or "")}</span>'
            f'{time_txt}</td>'
            f'<td style="padding:9px 10px;border-top:1px solid #fde4cf;text-align:right;white-space:nowrap;font-size:13px;">'
            f'{escape(rng)}<br><span style="display:inline-block;margin-top:3px;padding:1px 8px;border-radius:999px;'
            f'font-size:11px;font-weight:800;background:{"#fee2e2" if urgent else "#fff7ed"};'
            f'color:{"#b91c1c" if urgent else "#9a3412"};">{escape(when)}</span></td></tr>')
    table = ('<div style="margin:14px 0;border:2px solid #fb923c;border-radius:12px;overflow:hidden;background:#fffaf5;">'
             '<div style="background:#f97316;color:#fff;padding:9px 12px;font-size:13px;font-weight:800;'
             'text-transform:uppercase;letter-spacing:.04em;">⏰ Your counselling deadlines</div>'
             '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
             + ''.join(rows) + '</table></div>')
    inner = (f'<p style="margin:0 0 6px;color:#0f172a;font-size:15px;">Dear {escape(dr) if dr else "Doctor"},</p>'
             '<p style="margin:0;color:#334155;font-size:14px;line-height:1.6;">Here are the NEET-PG counselling '
             'steps for All-India (MCC) and your states that need your attention:</p>'
             + table + brand_button("Open my counselling dashboard →", DASHBOARD_URL) +
             '<p style="margin:12px 0 0;color:#94a3b8;font-size:12px;text-align:center;">Always confirm dates on the '
             'official counselling website before acting.</p>')
    n_today = sum(1 for _r, k, _w in mine if k == 'close1')
    subject = ((f"⏰ {n_today} NEET-PG deadlines close TOMORROW" if n_today > 1 else "⏰ A NEET-PG deadline closes TOMORROW")
               if n_today
               else "⏰ NEET-PG counselling: your upcoming deadlines")
    return subject, render_branded_email("Your NEET-PG deadlines", inner,
                                         preheader=escape(mine[0][0].get('label') or 'Counselling deadlines'))


def run(today=None, only_email=None):
    """Send today's digests. only_email → a preview of what a doctor would get (any doctor
    who has items today; never logged). Returns a summary dict."""
    from email_utils import send_email
    conn = get_db()
    summary = {'items': 0, 'doctors': 0, 'sent': 0, 'skipped': 0, 'failed': 0}
    try:
        ensure_tables(conn)
        targets, items = plan(conn, today)
        summary['items'] = len(items)
        summary['doctors'] = len(targets)
        if only_email:
            if targets:
                mine = targets[0][1]
            else:   # nothing due today → preview with the next upcoming steps (design check)
                from pg_admin.data import calendar as CAL
                up = conn.execute("SELECT * FROM pg_counselling_events WHERE is_active AND "
                                  "COALESCE(end_date, start_date) >= CURRENT_DATE "
                                  "ORDER BY COALESCE(end_date, start_date) LIMIT 6").fetchall()
                mine = [(dict(r), 'close3', 'upcoming (preview)') for r in up]
            if not mine:
                return summary
            subj, html = build_email({'name': 'Rahul Sharma'}, mine)
            summary['sent'] = 1 if send_email([only_email], '[PREVIEW] ' + subj, html) else 0
            return summary
        for d, mine in targets:
            fresh = []
            for r, kind, when in mine:
                row = conn.execute(
                    "INSERT INTO pg_deadline_reminder_log (user_id, event_id, kind) VALUES (?,?,?) "
                    "ON CONFLICT (user_id, event_id, kind) DO NOTHING RETURNING id", (d['id'], r['id'], kind)).fetchone()
                if row:
                    fresh.append((r, kind, when))
            conn.commit()
            if not fresh:
                summary['skipped'] += 1
                continue
            subj, html = build_email(d, fresh)
            if send_email([d['email']], subj, html):
                summary['sent'] += 1
            else:
                summary['failed'] += 1
            time.sleep(0.4)          # Resend: 2 req/s
        logger.info("deadline reminders: %s", summary)
        return summary
    except Exception as e:
        logger.error("deadline reminders run: %s", e)
        try: conn.rollback()
        except Exception: pass
        summary['error'] = str(e)[:200]
        return summary
    finally:
        conn.close()


def scheduled_run():
    """8 AM IST job: live service only, setting on, one process at a time."""
    if (os.environ.get('RENDER_SERVICE_NAME') or '').endswith('staging'):
        return
    conn = get_db()
    try:
        ensure_tables(conn)
        if not is_enabled(conn):
            return
        got = conn.execute("SELECT pg_try_advisory_lock(hashtext('pg_deadline_reminders')) AS ok").fetchone()['ok']
        if not got:
            return
        try:
            run()
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext('pg_deadline_reminders'))")
            conn.commit()
    except Exception as e:
        logger.error("deadline reminders scheduled_run: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()


def start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        import pytz
        sch = BackgroundScheduler()
        sch.add_job(scheduled_run, CronTrigger(hour=8, minute=0, timezone=pytz.timezone('Asia/Kolkata')),
                    id='pg_deadline_reminders', misfire_grace_time=3600, coalesce=True)
        sch.start()
    except Exception as e:
        logger.warning("deadline reminder scheduler: %s", e)


def run_in_background(**kw):
    threading.Thread(target=run, kwargs=kw, daemon=True, name='pg-deadline-reminders').start()
