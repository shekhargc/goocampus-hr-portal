"""goocampus.in sign-up WhatsApp messages (founder 2026-11-17; Meta-approved utility templates).

  1. welcometogoocampus   (Infobip/Meta id 1413956730516058) — "Hi Dr. {{1}}, thank you for registering…
                            …for {{2}} and MCC…". Sent ONCE when a new doctor has a name + state.
  2. gc_profile_incomplete (id 1952329065742254) — no variables. Sent to a new FREE doctor whose name or
                            state is still missing 1 hour after sign-up, and once more at 24 hours. Max 2.

Rules
- OFF until an admin switches it on (Registered Doctors → 💬 WhatsApp). Only accounts created AFTER the
  switch-on moment get anything — existing doctors are never messaged by this.
- Team / Counselling-Desk accounts never get either. The reminder only goes to FREE doctors (same test as
  the dashboard pop-up: profile_gate_applies); paid / invited doctors fill the onboarding form instead.
- Runs every 10 minutes on the LIVE service only (staging skips; both share one DB), one process at a time
  (advisory lock), and each (doctor, message) is claimed in pg_wa_nudge_log before sending — never twice.
"""
import logging
import os
import re

from db import get_db

logger = logging.getLogger(__name__)

WELCOME_TPL = 'welcometogoocampus'
INCOMPLETE_TPL = 'gc_profile_incomplete'
TEMPLATE_IDS = {WELCOME_TPL: '1413956730516058', INCOMPLETE_TPL: '1952329065742254'}
SENDER = os.environ.get('PG_WA_SENDER') or '15558246314'
LANGS = ('en', 'en_US', 'en_GB')          # tried in order until Infobip accepts the template
KV_ON, KV_SINCE = 'wa_nudges', 'wa_nudges_since'
KINDS = {'welcome': 'Welcome (name + state added)',
         'incomplete_1h': 'Profile reminder · 1 hour',
         'incomplete_24h': 'Profile reminder · 24 hours',
         'test': 'Test send'}


# ── tables / setting ────────────────────────────────────────────────────────
def ensure_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_kv (key TEXT PRIMARY KEY, value TEXT DEFAULT '',
                    updated_by TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_wa_nudge_log (
        id SERIAL PRIMARY KEY, user_id INTEGER, kind TEXT NOT NULL, template TEXT DEFAULT '',
        mobile TEXT DEFAULT '', status TEXT DEFAULT 'sending', response TEXT DEFAULT '',
        sent_by TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (user_id, kind))''')
    conn.commit()


def _kv(conn, key):
    try:
        r = conn.execute("SELECT value FROM pg_kv WHERE key = ?", (key,)).fetchone()
        return (r['value'] if r else '') or ''
    except Exception:
        conn.rollback()
        return ''


def is_enabled(conn):
    return _kv(conn, KV_ON) == 'on'


def since(conn):
    return _kv(conn, KV_SINCE)


def set_enabled(conn, on, who):
    ensure_tables(conn)
    conn.execute("INSERT INTO pg_kv (key, value, updated_by, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                 "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, "
                 "updated_at = CURRENT_TIMESTAMP", (KV_ON, 'on' if on else 'off', who))
    if on and not since(conn):
        # First switch-on fixes the start line: only doctors who sign up from now on are messaged.
        conn.execute("INSERT INTO pg_kv (key, value, updated_by, updated_at) "
                     "VALUES (?, to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'), ?, CURRENT_TIMESTAMP) "
                     "ON CONFLICT (key) DO NOTHING", (KV_SINCE, who))
    conn.commit()


# ── helpers ─────────────────────────────────────────────────────────────────
def mobile_to(mobile):
    """Indian WhatsApp number '91XXXXXXXXXX' from whatever is stored, or '' if it isn't a 10-digit Indian mobile."""
    d = re.sub(r'\D', '', str(mobile or ''))
    if len(d) == 12 and d.startswith('91'):
        d = d[2:]
    elif len(d) == 11 and d.startswith('0'):
        d = d[1:]
    return '91' + d if (len(d) == 10 and d[0] in '6789') else ''


def clean_placeholder(s, limit=60):
    """WhatsApp placeholders: no newlines/tabs, no runs of spaces, trimmed."""
    s = re.sub(r'[\r\n\t]+', ' ', str(s or ''))
    s = re.sub(r'\s{2,}', ' ', s).strip()
    return s[:limit].strip()


def welcome_name(name):
    """The template already says 'Dr. {{1}}', so drop a typed 'Dr' / 'Dr.' prefix."""
    n = clean_placeholder(name)
    n = re.sub(r'^(dr\.\s*|dr\s+)+', '', n, flags=re.I).strip(' .')
    return n


def send_template(to, template, placeholders=None):
    """Send one Infobip WhatsApp template. Returns (ok, response_text). Tries each language code."""
    key = os.environ.get('INFOBIP_API_KEY', '')
    base = os.environ.get('INFOBIP_BASE_URL', '')
    if not key or not base:
        return False, 'Infobip not configured on this service'
    import requests as _rq
    url = f"https://{base}/whatsapp/1/message/template"
    headers = {"Authorization": f"App {key}", "Content-Type": "application/json"}
    last = ''
    for lang in LANGS:
        payload = {"messages": [{"from": SENDER, "to": to, "content": {
            "templateName": template, "language": lang,
            "templateData": {"body": {"placeholders": list(placeholders or [])}}}}]}
        try:
            r = _rq.post(url, json=payload, headers=headers, timeout=15)
        except Exception as e:
            return False, f'network: {e}'[:400]
        last = f'{r.status_code} [{lang}] {r.text[:500]}'
        if r.status_code < 300:
            return True, last
        # Only retry another language when Infobip says the template/language wasn't found.
        if not re.search(r'templat|language|not\s*found|does not exist', r.text, re.I):
            break
    return False, last


def _claim(conn, user_id, kind, template, to, who='system'):
    row = conn.execute("INSERT INTO pg_wa_nudge_log (user_id, kind, template, mobile, status, sent_by) "
                       "VALUES (?, ?, ?, ?, 'sending', ?) ON CONFLICT (user_id, kind) DO NOTHING RETURNING id",
                       (user_id, kind, template, to[-4:] if to else '', who)).fetchone()
    conn.commit()
    return row['id'] if row else None


def _finish(conn, log_id, ok, resp):
    conn.execute("UPDATE pg_wa_nudge_log SET status = ?, response = ? WHERE id = ?",
                 ('sent' if ok else 'failed', (resp or '')[:900], log_id))
    conn.commit()


def _deliver(conn, user, kind, template, placeholders):
    to = mobile_to(user.get('mobile'))
    if not to:
        return 'skipped'
    log_id = _claim(conn, user['id'], kind, template, to)
    if not log_id:
        return 'already'
    ok, resp = send_template(to, template, placeholders)
    _finish(conn, log_id, ok, resp)
    if not ok:
        logger.warning("wa nudge %s user %s failed: %s", kind, user['id'], resp[:200])
    return 'sent' if ok else 'failed'


# ── the sweep ───────────────────────────────────────────────────────────────
def run():
    """One pass: welcome messages + 1h / 24h profile reminders for doctors created after switch-on."""
    summary = {'welcome': 0, 'incomplete_1h': 0, 'incomplete_24h': 0, 'failed': 0}
    conn = get_db()
    try:
        ensure_tables(conn)
        start = since(conn)
        if not start:
            return summary
        from pg_admin.routes.api import profile_gate_applies
        base = ("SELECT * FROM pg_users WHERE created_at >= ?::timestamp "
                "AND COALESCE(is_blocked,0) = 0 "
                "AND COALESCE((to_jsonb(pg_users)->>'is_team_member')::int,0) = 0 "
                "AND COALESCE((to_jsonb(pg_users)->>'desk_access')::int,0) = 0 ")
        has_both = "TRIM(COALESCE(name,'')) <> '' AND TRIM(COALESCE(state,'')) <> ''"

        # 1. Welcome — name + state present, signed up in the last 7 days, not yet welcomed.
        rows = conn.execute(base + "AND " + has_both + " AND created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days' "
                            "AND NOT EXISTS (SELECT 1 FROM pg_wa_nudge_log l WHERE l.user_id = pg_users.id "
                            "AND l.kind = 'welcome') ORDER BY id LIMIT 200", (start,)).fetchall()
        for u in rows:
            name, state = welcome_name(u.get('name')), clean_placeholder(u.get('state'))
            if not name or not state:
                continue
            res = _deliver(conn, u, 'welcome', WELCOME_TPL, [name, state])
            summary['welcome' if res == 'sent' else 'failed'] += res in ('sent', 'failed')

        # 2. Reminders — FREE doctors still missing name or state.
        windows = (('incomplete_1h', "INTERVAL '60 minutes'", "INTERVAL '23 hours'"),
                   ('incomplete_24h', "INTERVAL '24 hours'", "INTERVAL '48 hours'"))
        for kind, older_than, newer_than in windows:
            rows = conn.execute(
                base + "AND NOT (" + has_both + ") "
                f"AND created_at <= CURRENT_TIMESTAMP - {older_than} "
                f"AND created_at >= CURRENT_TIMESTAMP - {newer_than} "
                "AND NOT EXISTS (SELECT 1 FROM pg_wa_nudge_log l WHERE l.user_id = pg_users.id AND l.kind = ?) "
                "ORDER BY id LIMIT 200", (start, kind)).fetchall()
            for u in rows:
                if not profile_gate_applies(conn, u):
                    continue
                res = _deliver(conn, u, kind, INCOMPLETE_TPL, [])
                summary[kind if res == 'sent' else 'failed'] += res in ('sent', 'failed')
        if any(summary.values()):
            logger.info("wa nudges: %s", summary)
        return summary
    except Exception as e:
        logger.error("wa nudges run: %s", e)
        try: conn.rollback()
        except Exception: pass
        summary['error'] = str(e)[:200]
        return summary
    finally:
        conn.close()


def scheduled_run():
    """Every 10 minutes: live service only, switched on, one process at a time."""
    if (os.environ.get('RENDER_SERVICE_NAME') or '').endswith('staging'):
        return
    conn = get_db()
    try:
        ensure_tables(conn)
        if not is_enabled(conn):
            return
        got = conn.execute("SELECT pg_try_advisory_lock(hashtext('pg_wa_nudges')) AS ok").fetchone()['ok']
        if not got:
            return
        try:
            run()
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext('pg_wa_nudges'))")
            conn.commit()
    except Exception as e:
        logger.error("wa nudges scheduled_run: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()


def start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        sch = BackgroundScheduler()
        sch.add_job(scheduled_run, 'interval', minutes=10, id='pg_wa_nudges',
                    coalesce=True, max_instances=1, misfire_grace_time=600)
        sch.start()
    except Exception as e:
        logger.warning("wa nudge scheduler: %s", e)


# ── admin page: Registered Doctors → 💬 WhatsApp ────────────────────────────
def _admin():
    from pg_admin.routes.users_admin import _require_users_section
    return _require_users_section('view')


def admin_page():
    from flask import render_template, redirect, url_for, flash
    admin = _admin()
    if not admin:
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    rows, counts, on, start = [], {}, False, ''
    try:
        ensure_tables(conn)
        on, start = is_enabled(conn), since(conn)
        for r in conn.execute("SELECT kind, status, COUNT(*) AS n FROM pg_wa_nudge_log GROUP BY kind, status").fetchall():
            counts.setdefault(r['kind'], {})[r['status']] = r['n']
        rows = conn.execute(
            "SELECT l.*, u.name AS doctor_name FROM pg_wa_nudge_log l LEFT JOIN pg_users u ON u.id = l.user_id "
            "ORDER BY l.id DESC LIMIT 60").fetchall()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("wa nudges admin: %s", e)
    finally:
        conn.close()
    return render_template('pg_admin/wa_nudges.html', rows=rows, counts=counts, on=on, start=start,
                           kinds=KINDS, can_edit=bool(admin.get('is_admin')), welcome_tpl=WELCOME_TPL,
                           incomplete_tpl=INCOMPLETE_TPL, template_ids=TEMPLATE_IDS,
                           active='wa', active_section='goocampus_in')


def admin_toggle():
    from flask import request, redirect, url_for, flash
    admin = _admin()
    if not admin or not admin.get('is_admin'):
        flash('Only an admin can switch the WhatsApp messages on or off.', 'error')
        return redirect(url_for('pg_wa_nudges'))
    on = request.form.get('on') == '1'
    conn = get_db()
    try:
        set_enabled(conn, on, admin.get('name') or admin.get('emp_code') or 'admin')
        flash('WhatsApp sign-up messages are ON — new sign-ups from now on.' if on
              else 'WhatsApp sign-up messages are OFF.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("wa nudges toggle: %s", e)
        flash('Could not save the setting', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_wa_nudges'))


def admin_test():
    """Admin sends ONE template to a number they type (their own phone) to check it arrives."""
    from flask import request, redirect, url_for, flash
    admin = _admin()
    if not admin or not admin.get('is_admin'):
        flash('Only an admin can send a test.', 'error'); return redirect(url_for('pg_wa_nudges'))
    to = mobile_to(request.form.get('mobile'))
    tpl = request.form.get('template')
    if not to:
        flash('Enter a 10-digit Indian mobile number.', 'error'); return redirect(url_for('pg_wa_nudges'))
    if tpl == WELCOME_TPL:
        ph = [welcome_name(request.form.get('name') or 'Test') or 'Test',
              clean_placeholder(request.form.get('state') or 'Karnataka')]
    elif tpl == INCOMPLETE_TPL:
        ph = []
    else:
        flash('Pick a message.', 'error'); return redirect(url_for('pg_wa_nudges'))
    ok, resp = send_template(to, tpl, ph)
    conn = get_db()
    try:
        ensure_tables(conn)
        conn.execute("INSERT INTO pg_wa_nudge_log (user_id, kind, template, mobile, status, response, sent_by) "
                     "VALUES (NULL, 'test', ?, ?, ?, ?, ?)",
                     (tpl, to[-4:], 'sent' if ok else 'failed', resp[:900],
                      admin.get('name') or admin.get('emp_code') or 'admin'))
        conn.commit()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning("wa test log: %s", e)
    finally:
        conn.close()
    flash(('Test accepted by WhatsApp provider — check the phone. ' if ok else 'Test FAILED: ') + resp[:300],
          'success' if ok else 'error')
    return redirect(url_for('pg_wa_nudges'))


def register(app):
    from core.auth import login_required
    app.add_url_rule('/admin/pg/users/whatsapp', 'pg_wa_nudges', login_required(admin_page), methods=['GET'])
    app.add_url_rule('/admin/pg/users/whatsapp/toggle', 'pg_wa_nudges_toggle', login_required(admin_toggle),
                     methods=['POST'])
    app.add_url_rule('/admin/pg/users/whatsapp/test', 'pg_wa_nudges_test', login_required(admin_test),
                     methods=['POST'])
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true' or os.environ.get('DATABASE_URL'):
        start_scheduler()     # every 10 min; no-op unless switched ON + live service
