"""goocampus.in sign-up WhatsApp messages (founder 2026-11-17; Meta-approved utility templates).

  1. welcometogoocampus   (Infobip/Meta id 1413956730516058) — "Hi Dr. {{1}}, thank you for registering…
                            …for {{2}} and MCC…". Sent ONCE when a new doctor has a name + state.
  2. gc_profile_incomplete_v2 (id 1064689406591742; replaced gc_profile_incomplete 1952329065742254 on 2026-11-18,
                            founder: add "Dear Doctor," + "Thank you for registering with GooCampus.") — no variables. Sent to a new doctor (free OR invited/paid —
                            founder 2026-11-17) whose name or state is still missing 15 minutes after sign-up, and
                            once more at 24 hours. Max 2. ("Who gets it" can narrow it to Free / Paid / Internal.)
  (old rule, before 2026-11-17 night: FREE doctors only, first reminder at 1 hour) — sent to a new FREE doctor whose name or
                            state is still missing 1 hour after sign-up, and once more at 24 hours. Max 2.
  3. gc_enquiry_account    (id 1118950867607827) — "Hi Dr. {{1}}, thank you for your enquiry…". Sent ONCE per
                            mobile to a website enquiry (Sales → Inquiries from goocampus.in, or a Management /
                            NRI call-back) made after its own switch-on. (2026-11-17)
  4. gc_daily_account_update (id 39934717086143575) — "Dr. {{1}}, {{2}} new update(s) for {{3}} were posted…
                            Latest: {{4}}". Since 2026-11-18: after EACH publish batch (15 quiet minutes after the
                            last item), max 3 a day, only to doctors whose MCC / state is in that batch (was: 8 pm digest). Quick reply "Stop updates" (or STOP) → never again (pg_wa_optout,
                            via the Infobip inbound webhook /api/wa/inbound?k=PG_WA_INBOUND_KEY). (2026-11-17)

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
INCOMPLETE_TPL = 'gc_profile_incomplete_v2'      # "Dear Doctor, Thank you for registering…" (2026-11-18; v1 retired)
ENQUIRY_TPL = 'gc_enquiry_account'
DAILY_TPL = 'gc_daily_account_update'
TEMPLATE_IDS = {WELCOME_TPL: '1413956730516058', INCOMPLETE_TPL: '1064689406591742',
                ENQUIRY_TPL: '1118950867607827', DAILY_TPL: '39934717086143575'}
SENDER = os.environ.get('PG_WA_SENDER') or '15558246314'
LANGS = ('en', 'en_US', 'en_GB')          # tried in order until Infobip accepts the template
KV_ON, KV_SINCE = 'wa_nudges', 'wa_nudges_since'
# Each message group has its own ON/OFF switch (+ a start line for the enquiry message).
SWITCHES = {'signup': ('wa_nudges', 'wa_nudges_since'),
            'enquiry': ('wa_enquiry', 'wa_enquiry_since'),
            'daily': ('wa_daily', 'wa_daily_since')}
KINDS = {'welcome': 'Welcome (name + state added)',
         'incomplete_1h': 'Profile reminder · first (15 min)',
         'incomplete_24h': 'Profile reminder · 24 hours',
         'incomplete_72h': 'Profile reminder · 72 hours',
         'enquiry': 'Enquiry → dashboard',
         'daily': 'Daily counselling update',
         'campaign': 'Group send',
         'test': 'Test send'}


def kind_label(kind):
    k = (kind or '').split(':', 1)[0]
    return KINDS.get(k, kind)


# ── tables / setting ────────────────────────────────────────────────────────
_TABLES = {'done': False}


def ensure_tables(conn):
    """Small tables only; once per process (2026-11-17 outage lesson: never DDL on every call)."""
    if _TABLES['done']:
        return
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_wa_optout (mobile10 TEXT PRIMARY KEY, source TEXT DEFAULT '',
                    note TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_kv (key TEXT PRIMARY KEY, value TEXT DEFAULT '',
                    updated_by TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_wa_nudge_log (
        id SERIAL PRIMARY KEY, user_id INTEGER, kind TEXT NOT NULL, template TEXT DEFAULT '',
        mobile TEXT DEFAULT '', status TEXT DEFAULT 'sending', response TEXT DEFAULT '',
        sent_by TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (user_id, kind))''')
    conn.execute("CREATE TABLE IF NOT EXISTS pg_wa_news_done (news_id INTEGER PRIMARY KEY, batch TEXT DEFAULT '', "
                 "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    _TABLES['done'] = True


def _kv(conn, key):
    try:
        r = conn.execute("SELECT value FROM pg_kv WHERE key = ?", (key,)).fetchone()
        return (r['value'] if r else '') or ''
    except Exception:
        conn.rollback()
        return ''


def is_enabled(conn, group='signup'):
    return _kv(conn, SWITCHES[group][0]) == 'on'


def since(conn, group='signup'):
    return _kv(conn, SWITCHES[group][1])


def set_enabled(conn, on, who, group='signup'):
    ensure_tables(conn)
    k_on, k_since = SWITCHES[group]
    conn.execute("INSERT INTO pg_kv (key, value, updated_by, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                 "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, "
                 "updated_at = CURRENT_TIMESTAMP", (k_on, 'on' if on else 'off', who))
    if on and not since(conn, group):
        # First switch-on fixes the start line: only sign-ups / enquiries from now on are messaged.
        conn.execute("INSERT INTO pg_kv (key, value, updated_by, updated_at) "
                     "VALUES (?, to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS'), ?, CURRENT_TIMESTAMP) "
                     "ON CONFLICT (key) DO NOTHING", (k_since, who))
    conn.commit()


def opted_out(conn, mobile):
    m10 = re.sub(r'\D', '', str(mobile or ''))[-10:]
    if not m10:
        return False
    try:
        return bool(conn.execute("SELECT 1 FROM pg_wa_optout WHERE mobile10 = ?", (m10,)).fetchone())
    except Exception:
        conn.rollback()
        return False


def set_optout(conn, mobile, out, source='admin', note=''):
    m10 = re.sub(r'\D', '', str(mobile or ''))[-10:]
    if len(m10) != 10:
        return False
    ensure_tables(conn)
    if out:
        conn.execute("INSERT INTO pg_wa_optout (mobile10, source, note) VALUES (?, ?, ?) "
                     "ON CONFLICT (mobile10) DO NOTHING", (m10, source, (note or '')[:200]))
    else:
        conn.execute("DELETE FROM pg_wa_optout WHERE mobile10 = ?", (m10,))
    conn.commit()
    return True


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


def send_template(to, template, placeholders=None, sender=None, langs=None):
    """Send one Infobip WhatsApp template. Returns (ok, response_text). Tries each language code.
    `sender` = the WhatsApp number the template was approved on (register's sender column; default SENDER)."""
    key = os.environ.get('INFOBIP_API_KEY', '')
    base = os.environ.get('INFOBIP_BASE_URL', '')
    if not key or not base:
        return False, 'Infobip not configured on this service'
    import requests as _rq
    url = f"https://{base}/whatsapp/1/message/template"
    headers = {"Authorization": f"App {key}", "Content-Type": "application/json"}
    last = ''
    for lang in (langs or LANGS):
        payload = {"messages": [{"from": sender or SENDER, "to": to, "content": {
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
    summary = {'welcome': 0, 'incomplete_1h': 0, 'incomplete_24h': 0, 'incomplete_72h': 0, 'failed': 0}
    conn = get_db()
    try:
        ensure_tables(conn)
        start = since(conn)
        if not start:
            return summary
        base = ("SELECT * FROM pg_users WHERE created_at >= ?::timestamp "
                "AND COALESCE(is_blocked,0) = 0 "
                "")      # team / Desk now decided by each message's "Who gets it" (Team tick box), 2026-11-18
        has_both = "TRIM(COALESCE(name,'')) <> '' AND TRIM(COALESCE(state,'')) <> ''"

        # 1. Welcome — name + state present, signed up in the last 7 days, not yet welcomed.
        rows = conn.execute(base + "AND " + has_both + " AND created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days' "
                            "AND NOT EXISTS (SELECT 1 FROM pg_wa_nudge_log l WHERE l.user_id = pg_users.id "
                            "AND l.kind = 'welcome') ORDER BY id LIMIT 200", (start,)).fetchall()
        from pg_admin import wa_campaigns as wc
        aud = wc.get_aud(conn, 'welcome')
        cats = wc.categories(conn, [u['id'] for u in rows]) if rows else {}
        for u in rows:
            name, state = welcome_name(u.get('name')), clean_placeholder(u.get('state'))
            if not name or not state:
                continue
            if not wc.aud_allows(aud, cats.get(u['id'], 'free'), u.get('state')):
                continue
            res = _deliver(conn, u, 'welcome', WELCOME_TPL, [name, state])
            summary['welcome' if res == 'sent' else 'failed'] += res in ('sent', 'failed')

        # 2. Reminders — FREE doctors still missing name or state.
        # kind 'incomplete_1h' kept as the log key (history continuity) — the first reminder now goes at 15 min.
        windows = (('incomplete_1h', "INTERVAL '15 minutes'", "INTERVAL '23 hours'"),
                   ('incomplete_24h', "INTERVAL '24 hours'", "INTERVAL '48 hours'"),
                   ('incomplete_72h', "INTERVAL '72 hours'", "INTERVAL '96 hours'"))     # founder 2026-11-18
        aud_inc = wc.get_aud(conn, 'incomplete')
        if not aud_inc['types']:
            windows = ()                     # "who gets it" = nobody → reminder off
        for kind, older_than, newer_than in windows:
            rows = conn.execute(
                base + "AND NOT (" + has_both + ") "
                f"AND created_at <= CURRENT_TIMESTAMP - {older_than} "
                f"AND created_at >= CURRENT_TIMESTAMP - {newer_than} "
                "AND NOT EXISTS (SELECT 1 FROM pg_wa_nudge_log l WHERE l.user_id = pg_users.id AND l.kind = ?) "
                "ORDER BY id LIMIT 200", (start, kind)).fetchall()
            cats_inc = wc.categories(conn, [u['id'] for u in rows]) if rows else {}
            for u in rows:
                if not wc.aud_allows(aud_inc, cats_inc.get(u['id'], 'free'), ''):
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


def enquiry_run(conn):
    """Website enquiries made after the enquiry switch-on → one gc_enquiry_account per mobile, ever.
    Sources: Sales → Inquiries rows from goocampus.in + Management / NRI call-backs."""
    sent = failed = 0
    start = since(conn, 'enquiry')
    if not start:
        return 0, 0
    leads = []
    from pg_admin import wa_campaigns as wc
    srcs = wc.get_aud(conn, 'enquiry')['sources']
    for src, sql in zip(('website', 'mgmt'), ("SELECT lead_name AS name, phone FROM sales_leads WHERE COALESCE(is_inquiry,0) = 1 "
                "AND source = 'NEET PG Website (goocampus.in)' AND created_at >= ?::timestamp ORDER BY id LIMIT 200",
                "SELECT name, phone FROM pg_mgmt_inquiries WHERE created_at >= ?::timestamp ORDER BY id LIMIT 200")):
        if src not in srcs:
            continue
        try:
            leads += [dict(r) for r in conn.execute(sql, (start,)).fetchall()]
        except Exception as e:
            conn.rollback()
            logger.warning("wa enquiry source: %s", e)
    seen = set()
    for ld in leads:
        to = mobile_to(ld.get('phone'))
        if not to or to in seen:
            continue
        seen.add(to)
        name = welcome_name(ld.get('name'))
        if not name or opted_out(conn, to):
            continue
        res = _deliver(conn, {'id': 0, 'mobile': to}, 'enquiry:' + to[-10:], ENQUIRY_TPL, [name])
        sent += res == 'sent'
        failed += res == 'failed'
    return sent, failed


def _ist_today():
    from datetime import datetime, timedelta
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()


def daily_plan(conn, day=None):
    """[(doctor_row, count, label, latest_heading)] for news POSTED on `day` (IST, default today) — used for the
    page's "today's audience" number."""
    day = day or _ist_today()
    news = [dict(r) for r in conn.execute(
        "SELECT id, scope, COALESCE(state,'') AS state, heading, created_at FROM pg_news "
        "WHERE COALESCE(is_published, TRUE) AND (to_jsonb(pg_news)->>'deleted_at') IS NULL "
        "AND (created_at + INTERVAL '330 minutes')::date = ? ORDER BY created_at DESC", (day,)).fetchall()]
    return plan_for_news(conn, news)


def plan_for_news(conn, news):
    """[(doctor_row, count, label, latest_heading)] for a list of news items (newest first):
    MCC / All-India items for everyone + each doctor's own states (home, counselling states, follows)."""
    from pg_admin.deadline_reminders import _doctor_states
    if not news:
        return []
    states = _doctor_states(conn)
    docs = conn.execute(
        "SELECT * FROM pg_users WHERE COALESCE(is_blocked,0) = 0 "
        "AND TRIM(COALESCE(name,'')) <> '' AND COALESCE(mobile,'') <> '' ORDER BY id").fetchall()
    from pg_admin import wa_campaigns as wc
    aud = wc.get_aud(conn, 'daily')
    cats = wc.categories(conn)
    out = []
    for d in docs:
        if not wc.aud_allows(aud, cats.get(d['id'], 'free'), d.get('state')):
            continue
        st = states.get(d['id'], set())
        mine = [n for n in news if n['scope'] == 'all_india' or (n['state'] or '').strip().lower() in st]
        if not mine:
            continue
        labels = []
        if any(n['scope'] == 'all_india' for n in mine):
            labels.append('MCC')
        for n in mine:
            if n['scope'] != 'all_india' and n['state'] and n['state'] not in labels:
                labels.append(n['state'])
        label = ' & '.join(labels[:3]) + (' + more' if len(labels) > 3 else '')
        out.append((dict(d), len(mine), label, mine[0]['heading']))
    return out


def daily_run():
    """8 pm IST: one daily update per doctor with news today. Claimed per (doctor, day) — never twice."""
    summary = {'daily': 0, 'failed': 0, 'skipped': 0}
    conn = get_db()
    try:
        ensure_tables(conn)
        day = _ist_today()
        for d, n, label, latest in daily_plan(conn, day):
            if opted_out(conn, d.get('mobile')):
                summary['skipped'] += 1
                continue
            ph = [welcome_name(d.get('name')), str(n), clean_placeholder(label, 60), clean_placeholder(latest, 120)]
            res = _deliver(conn, d, 'daily:' + day.isoformat(), DAILY_TPL, ph)
            if res == 'sent':
                summary['daily'] += 1
            elif res == 'failed':
                summary['failed'] += 1
        logger.info("wa daily: %s", summary)
        return summary
    except Exception as e:
        logger.error("wa daily run: %s", e)
        try: conn.rollback()
        except Exception: pass
        summary['error'] = str(e)[:200]
        return summary
    finally:
        conn.close()


NEWS_QUIET_MIN = 15      # a "bulk publish" is over when nothing new was published for this many minutes
NEWS_MAX_PER_DAY = 3     # at most this many news updates per doctor per IST day


def news_batch_run(conn):
    """Founder 2026-11-18: "every time I publish news in bulk — if I do it twice or thrice, send it."
    Every 10 min: news published (after the switch-on, last 24 h) that no WhatsApp went out for yet. Once nothing new
    has been published for NEWS_QUIET_MIN minutes, the whole batch = ONE message per doctor whose MCC / state is in it
    (gc_daily_account_update; {{2}} = items in this batch). Max NEWS_MAX_PER_DAY a day per doctor; STOP respected."""
    ensure_tables(conn)
    start = since(conn, 'daily')
    if not start:
        return {}
    news = [dict(r) for r in conn.execute(
        "SELECT id, scope, COALESCE(state,'') AS state, heading, COALESCE(published_at, created_at) AS pub FROM pg_news n "
        "WHERE COALESCE(is_published, TRUE) AND (to_jsonb(n)->>'deleted_at') IS NULL "
        "AND COALESCE(published_at, created_at) >= ?::timestamp "
        "AND COALESCE(published_at, created_at) >= CURRENT_TIMESTAMP - INTERVAL '24 hours' "
        "AND COALESCE(published_at, created_at) <= CURRENT_TIMESTAMP "
        "AND NOT EXISTS (SELECT 1 FROM pg_wa_news_done d WHERE d.news_id = n.id) "
        "ORDER BY COALESCE(published_at, created_at) DESC, id DESC", (start,)).fetchall()]
    if not news:
        return {}
    quiet = conn.execute("SELECT ?::timestamp <= CURRENT_TIMESTAMP - INTERVAL '%d minutes' AS ok" % NEWS_QUIET_MIN,
                         (news[0]['pub'],)).fetchone()['ok']
    if not quiet:
        return {'waiting': len(news)}            # still publishing — wait for the batch to finish
    batch = 'b%d' % max(n['id'] for n in news)
    for n in news:
        conn.execute("INSERT INTO pg_wa_news_done (news_id, batch) VALUES (?, ?) ON CONFLICT (news_id) DO NOTHING",
                     (n['id'], batch))
    conn.commit()
    summary = {'sent': 0, 'failed': 0, 'skipped': 0, 'capped': 0}
    day_start = conn.execute("SELECT (date_trunc('day', CURRENT_TIMESTAMP + INTERVAL '330 minutes') "
                             "- INTERVAL '330 minutes') AS t").fetchone()['t']
    for d, cnt, label, latest in plan_for_news(conn, news):
        if opted_out(conn, d.get('mobile')):
            summary['skipped'] += 1
            continue
        today_n = conn.execute("SELECT COUNT(*) AS n FROM pg_wa_nudge_log WHERE user_id = ? AND kind LIKE ? "
                               "AND status = 'sent' AND created_at >= ?", (d['id'], 'daily:%', day_start)).fetchone()['n']
        if today_n >= NEWS_MAX_PER_DAY:
            summary['capped'] += 1
            continue
        ph = [welcome_name(d.get('name')), str(cnt), clean_placeholder(label, 60), clean_placeholder(latest, 120)]
        res = _deliver(conn, d, 'daily:' + batch, DAILY_TPL, ph)
        if res in ('sent', 'failed'):
            summary[res] += 1
    logger.info("wa news batch %s (%s items): %s", batch, len(news), summary)
    return summary


def scheduled_daily():
    """Cron 20:00 IST — live service only, switched on, one process at a time."""
    if (os.environ.get('RENDER_SERVICE_NAME') or '').endswith('staging'):
        return
    conn = get_db()
    try:
        ensure_tables(conn)
        if not is_enabled(conn, 'daily'):
            return
        if not conn.execute("SELECT pg_try_advisory_lock(hashtext('pg_wa_daily')) AS ok").fetchone()['ok']:
            return
        try:
            daily_run()
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext('pg_wa_daily'))")
            conn.commit()
    except Exception as e:
        logger.error("wa daily scheduled: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()


def scheduled_run():
    """Every 10 minutes: live service only, switched on, one process at a time."""
    if (os.environ.get('RENDER_SERVICE_NAME') or '').endswith('staging'):
        return
    conn = get_db()
    try:
        ensure_tables(conn)
        from pg_admin import wa_campaigns as wc
        wc.resume_stalled(conn)              # group sends whose runner died (deploy / restart)
        signup, enquiry = is_enabled(conn), is_enabled(conn, 'enquiry')
        news_on = is_enabled(conn, 'daily')
        if not (signup or enquiry or news_on):
            return
        got = conn.execute("SELECT pg_try_advisory_lock(hashtext('pg_wa_nudges')) AS ok").fetchone()['ok']
        if not got:
            return
        try:
            if signup:
                run()
            if enquiry:
                s_, f_ = enquiry_run(conn)
                if s_ or f_:
                    logger.info("wa enquiry: sent %s failed %s", s_, f_)
            if news_on:
                news_batch_run(conn)
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
        # (8 pm IST daily digest retired 2026-11-18 — news updates now go per publish batch, see news_batch_run)
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
    switches, optouts, today_plan = {}, 0, None
    auds, aud_labels = {}, {}
    try:
        ensure_tables(conn)
        on, start = is_enabled(conn), since(conn)
        switches = {g: {'on': is_enabled(conn, g), 'since': since(conn, g)} for g in SWITCHES}
        for r in conn.execute("SELECT split_part(kind, ':', 1) AS k, status, COUNT(*) AS n FROM pg_wa_nudge_log "
                              "GROUP BY 1, status").fetchall():
            counts.setdefault(r['k'], {})[r['status']] = r['n']
        optouts = conn.execute("SELECT COUNT(*) AS n FROM pg_wa_optout").fetchone()['n']
        try:
            today_plan = len(daily_plan(conn))
        except Exception:
            conn.rollback()
            today_plan = None
        from pg_admin import wa_campaigns as wc
        auds = {m: wc.get_aud(conn, m) for m in wc.AUTO_MSGS}
        aud_labels = {m: wc.aud_label(m, a) for m, a in auds.items()}
        rows = conn.execute(
            "SELECT l.*, u.name AS doctor_name FROM pg_wa_nudge_log l LEFT JOIN pg_users u ON u.id = l.user_id "
            "WHERE l.kind NOT LIKE ? ORDER BY l.id DESC LIMIT 60", ('campaign:%',)).fetchall()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("wa nudges admin: %s", e)
    finally:
        conn.close()
    return render_template('pg_admin/wa_nudges.html', rows=rows, counts=counts, on=on, start=start,
                           kinds=KINDS, kind_label=kind_label, can_edit=bool(admin.get('is_admin')),
                           welcome_tpl=WELCOME_TPL, incomplete_tpl=INCOMPLETE_TPL, enquiry_tpl=ENQUIRY_TPL,
                           daily_tpl=DAILY_TPL, template_ids=TEMPLATE_IDS, switches=switches, optouts=optouts,
                           today_plan=today_plan, auds=auds, aud_labels=aud_labels,
                           states=_states(), enq_sources=_enq_sources(), inbound_ready=bool(os.environ.get('PG_WA_INBOUND_KEY')),
                           active='wa', active_section='goocampus_in')


def _states():
    from pg_admin.routes.users_admin import _canonical_states
    return _canonical_states()


def _enq_sources():
    from pg_admin import wa_campaigns as wc
    return wc.ENQ_SOURCES


def admin_toggle():
    from flask import request, redirect, url_for, flash
    admin = _admin()
    if not admin or not admin.get('is_admin'):
        flash('Only an admin can switch the WhatsApp messages on or off.', 'error')
        return redirect(url_for('pg_wa_nudges'))
    on = request.form.get('on') == '1'
    group = request.form.get('group') or 'signup'
    if group not in SWITCHES:
        group = 'signup'
    names = {'signup': 'sign-up messages', 'enquiry': 'enquiry message', 'daily': 'daily counselling update'}
    conn = get_db()
    try:
        set_enabled(conn, on, admin.get('name') or admin.get('emp_code') or 'admin', group)
        flash(f"WhatsApp {names[group]}: {'ON' if on else 'OFF'}.", 'success')
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
    elif tpl == ENQUIRY_TPL:
        ph = [welcome_name(request.form.get('name') or 'Test') or 'Test']
    elif tpl == DAILY_TPL:
        ph = [welcome_name(request.form.get('name') or 'Test') or 'Test', '3',
              clean_placeholder((request.form.get('state') or 'Karnataka')) and
              ('MCC & ' + clean_placeholder(request.form.get('state') or 'Karnataka')),
              'MCC Round 2 result kept on hold — Madras High Court order (17 Nov)']
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


_STOP_RE = re.compile(r'(stop|stop updates?|unsubscribe)[.! ]*')


def handle_inbound(conn, from_phone, msg, text=''):
    """One inbound WhatsApp message: 'Stop updates' (button) / STOP → opted out of the daily update.
    Used by /api/wa/inbound AND the existing /whatsapp/webhook (whichever URL Infobip posts to)."""
    if not from_phone:
        return 0
    vals = [str((msg or {}).get(k) or '').strip().lower() for k in ('text', 'payload', 'title')] + [
        str(text or '').strip().lower()]
    hit = next((v for v in vals if v and _STOP_RE.fullmatch(v)), '')
    if not hit:
        return 0
    ensure_tables(conn)
    return 1 if set_optout(conn, from_phone, True, 'whatsapp', hit[:40]) else 0


def inbound():
    """POST /api/wa/inbound?k=<PG_WA_INBOUND_KEY> — Infobip WhatsApp inbound messages (set this URL in Infobip).
    'Stop updates' (quick-reply button) or a message STOP → this number never gets the daily update again."""
    from flask import request, jsonify
    key = os.environ.get('PG_WA_INBOUND_KEY') or ''
    if not key or request.args.get('k') != key:
        return jsonify({'ok': False}), 401
    data = request.get_json(silent=True) or {}
    stopped = 0
    conn = get_db()
    try:
        for m in data.get('results') or []:
            stopped += handle_inbound(conn, m.get('from'), m.get('message') or {})
    except Exception as e:
        logger.error("wa inbound: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    return jsonify({'ok': True, 'stopped': stopped})


def admin_optout():
    """Admin marks a number as opted out of the daily update (or back in)."""
    from flask import request, redirect, url_for, flash
    admin = _admin()
    if not admin or not admin.get('is_admin'):
        flash('Only an admin can change this.', 'error'); return redirect(url_for('pg_wa_nudges'))
    out = request.form.get('out') == '1'
    conn = get_db()
    try:
        ok = set_optout(conn, request.form.get('mobile'), out, 'admin',
                        admin.get('name') or admin.get('emp_code') or 'admin')
        flash(('Stopped daily updates for that number.' if out else 'Daily updates allowed again for that number.')
              if ok else 'Enter a 10-digit mobile number.', 'success' if ok else 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_wa_nudges'))


def register(app):
    from core.auth import login_required
    app.add_url_rule('/admin/pg/users/whatsapp', 'pg_wa_nudges', login_required(admin_page), methods=['GET'])
    app.add_url_rule('/admin/pg/users/whatsapp/toggle', 'pg_wa_nudges_toggle', login_required(admin_toggle),
                     methods=['POST'])
    app.add_url_rule('/admin/pg/users/whatsapp/test', 'pg_wa_nudges_test', login_required(admin_test),
                     methods=['POST'])
    app.add_url_rule('/admin/pg/users/whatsapp/optout', 'pg_wa_nudges_optout', login_required(admin_optout),
                     methods=['POST'])
    app.add_url_rule('/api/wa/inbound', 'pg_wa_inbound', inbound, methods=['POST'])
    from pg_admin import wa_campaigns
    wa_campaigns.register(app)
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true' or os.environ.get('DATABASE_URL'):
        start_scheduler()     # every 10 min; no-op unless switched ON + live service
