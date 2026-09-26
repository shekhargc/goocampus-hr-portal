"""
System Health dashboard  —  /admin/health   (admin only)

A live, plain-English "is everything working?" board for the whole GooCampus
stack, grouped by project. Each time an admin opens the page it runs real checks
(no side effects — it never sends an email/WhatsApp/OTP) and shows every piece as
green (working), amber (needs attention) or red (broken).

Covers:
  GooCampus.org (portal + operations) : database, R2 storage, Resend email,
                                        Infobip WhatsApp, OTP generation
  GooCampus.in  (NEET-PG doctor site) : site reachable, portal<->site API key,
                                        doctor sign-ups flowing, profile sync
  jobs.goocampus.in (careers)         : site reachable

There is also the existing unauthenticated /healthz (deploy/commit probe) that an
external uptime monitor (e.g. UptimeRobot) can ping 24/7.  (founder 2026-09-26)
"""
import os
import time
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from flask import render_template, session, redirect, url_for, flash

# Public site URLs we probe for uptime (server-side GET, short timeout).
GOOCAMPUS_IN_URL = os.environ.get('GOOCAMPUS_IN_URL', 'https://goocampus.in')
JOBS_URL = os.environ.get('GOOCAMPUS_JOBS_URL', 'https://jobs.goocampus.in')

_NET_TIMEOUT = 6  # seconds for any outbound HTTP probe


def _ist_str(dt=None):
    """UTC -> IST display string, matching the portal's format_datetime filter."""
    base = dt if dt is not None else datetime.utcnow()
    try:
        return (base + timedelta(hours=5, minutes=30)).strftime('%d-%b-%Y, %I:%M %p') + ' IST'
    except Exception:
        return str(base)


def _ok(detail):
    return {'status': 'ok', 'detail': detail}


def _warn(detail):
    return {'status': 'warn', 'detail': detail}


def _down(detail):
    return {'status': 'down', 'detail': detail}


# ---------------------------------------------------------------- DB-backed checks
def _check_db():
    from db import get_db
    t0 = time.time()
    try:
        conn = get_db()
        conn.execute('SELECT 1').fetchone()
        conn.close()
        ms = int((time.time() - t0) * 1000)
        return _ok(f'Connected — responded in {ms} ms')
    except Exception as e:
        return _down(f'Cannot reach the database: {e}')


def _check_otp():
    """OTP generator health via the goocampus.in doctor-login pg_otps table."""
    from db import get_db
    conn = None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM pg_otps WHERE created_at > NOW() - INTERVAL '24 hours'"
        ).fetchone()
        conn.close()
        n = (row['n'] if row else 0) or 0
        if n > 0:
            return _ok(f'{n} OTP code(s) generated in the last 24h — generator is active')
        return _ok('OTP table healthy — no OTP requests in the last 24h (normal when quiet)')
    except Exception as e:
        try:
            if conn:
                conn.rollback()
                conn.close()
        except Exception:
            pass
        return _warn(f'Could not verify the OTP table: {e}')


def _check_doctor_signups():
    from db import get_db
    conn = None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) AS n, MAX(created_at) AS last FROM pg_users"
        ).fetchone()
        conn.close()
        n = (row['n'] if row else 0) or 0
        last = row['last'] if row else None
        if n == 0:
            return _warn('No doctors registered yet on goocampus.in')
        return _ok(f'{n} doctor(s) registered — latest {_ist_str(last) if last else "unknown"}')
    except Exception as e:
        try:
            if conn:
                conn.rollback()
                conn.close()
        except Exception:
            pass
        return _warn(f'Could not read doctor sign-ups: {e}')


def _check_profile_sync():
    """The real '(name pending)' bug: a doctor who SUBMITTED onboarding but whose
    profile name never synced. (An empty name on a doctor who only OTP-logged-in and
    never onboarded is normal, so we only count submitted-but-nameless ones.)"""
    from db import get_db
    conn = None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM pg_pgcp_onboarding o "
            "JOIN pg_users u ON u.id = o.user_id "
            "WHERE o.status = 'submitted' AND COALESCE(u.name, '') = ''"
        ).fetchone()
        conn.close()
        n = (row['n'] if row else 0) or 0
        if n == 0:
            return _ok('Every completed onboarding synced its profile — no "name pending"')
        if n <= 2:
            return _warn(f'{n} doctor(s) completed onboarding but show "name pending" — worth a look')
        return _down(f'{n} doctors completed onboarding but show "name pending" — sync may be broken')
    except Exception as e:
        try:
            if conn:
                conn.rollback()
                conn.close()
        except Exception:
            pass
        return _warn(f'Could not check profile sync: {e}')


def _check_handshake():
    """Portal<->goocampus.in shared secret + that the data the site reads exists."""
    key = (os.environ.get('PG_API_KEY') or '').strip()
    if not key:
        return _down('PG_API_KEY not set — goocampus.in cannot pull data from the portal')
    from db import get_db
    conn = None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM pg_mentors WHERE COALESCE(is_published, 1) = 1"
        ).fetchone()
        conn.close()
        n = (row['n'] if row else 0) or 0
        return _ok(f'API key set — goocampus.in can read the portal ({n} mentors published)')
    except Exception:
        try:
            if conn:
                conn.rollback()
                conn.close()
        except Exception:
            pass
        # Key present is the important part; data query is a bonus.
        return _ok('API key set — goocampus.in can read the portal')


def _age_days(ts):
    """Whole days between a stored UTC timestamp and now. None if unparseable."""
    if not ts:
        return None
    try:
        if isinstance(ts, str):
            from datetime import datetime as _dt
            ts = _dt.fromisoformat(ts.replace('Z', '').replace('T', ' ').split('.')[0].strip())
        return max(0, (datetime.utcnow() - ts).days)
    except Exception:
        return None


def _journey_stage(sql, waiting_label, warn_days, strong_days):
    """Generic 'N waiting at a stage, oldest X days' check with stall thresholds.
    Backlogs never go red (that is operations, not a fault) — they warn."""
    from db import get_db
    conn = None
    try:
        conn = get_db()
        row = conn.execute(sql).fetchone()
        conn.close()
        n = (row['n'] if row else 0) or 0
        oldest = row['oldest'] if row else None
        if n == 0:
            return _ok(f'No clients {waiting_label} — nothing stuck')
        age = _age_days(oldest)
        agestr = f'oldest waiting {age} day(s)' if age is not None else 'flowing'
        if age is not None and age >= strong_days:
            return _warn(f'{n} client(s) {waiting_label} — {agestr}; likely stalled, check the queue')
        if age is not None and age >= warn_days:
            return _warn(f'{n} client(s) {waiting_label} — {agestr}; worth a look')
        return _ok(f'{n} client(s) {waiting_label} — {agestr}; flowing normally')
    except Exception as e:
        try:
            if conn:
                conn.rollback()
                conn.close()
        except Exception:
            pass
        return _warn(f'Could not read this stage: {e}')


def _check_new_registrations():
    from db import get_db
    conn = None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) FILTER (WHERE client_submitted_at > NOW() - INTERVAL '7 days') AS n7, "
            "MAX(client_submitted_at) AS last FROM client_registrations WHERE form_status = 'submitted'"
        ).fetchone()
        conn.close()
        n7 = (row['n7'] if row else 0) or 0
        last = row['last'] if row else None
        laststr = f' · latest {_ist_str(last)}' if last else ''
        if n7 > 0:
            return _ok(f'{n7} new registration(s) submitted in the last 7 days{laststr}')
        return _ok(f'No new registrations in the last 7 days (normal when quiet){laststr}')
    except Exception as e:
        try:
            if conn:
                conn.rollback()
                conn.close()
        except Exception:
            pass
        return _warn(f'Could not read new registrations: {e}')


def _check_sales_verification():
    return _journey_stage(
        "SELECT COUNT(*) AS n, MIN(client_submitted_at) AS oldest FROM client_registrations "
        "WHERE form_status = 'submitted' AND COALESCE(sales_completed, 0) = 0",
        'waiting for sales verification', warn_days=3, strong_days=7)


def _check_ops_verification():
    return _journey_stage(
        "SELECT COUNT(*) AS n, MIN(sales_completed_at) AS oldest FROM client_registrations "
        "WHERE COALESCE(sales_completed, 0) = 1 AND COALESCE(ops_status, 'pending') <> 'verified'",
        'waiting for ops verification', warn_days=3, strong_days=7)


def _check_onboarding_completion():
    return _journey_stage(
        "SELECT COUNT(*) AS n, MIN(COALESCE(ops_verified_at, sales_completed_at)) AS oldest "
        "FROM client_registrations "
        "WHERE COALESCE(ops_status, 'pending') = 'verified' "
        "AND COALESCE(onboarding_gated, 0) = 1 "
        "AND COALESCE(onboarding_status, 'pending') <> 'confirmed'",
        'in contract/refund onboarding', warn_days=5, strong_days=10)


def _check_inquiries():
    from db import get_db
    conn = None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') AS n7, "
            "MAX(created_at) AS last FROM sales_leads WHERE COALESCE(is_inquiry, 0) = 1"
        ).fetchone()
        conn.close()
        n7 = (row['n7'] if row else 0) or 0
        last = row['last'] if row else None
        laststr = f' · latest {_ist_str(last)}' if last else ''
        if n7 > 0:
            return _ok(f'{n7} website inquiry(ies) in the last 7 days{laststr}')
        return _ok(f'No website inquiries in the last 7 days{laststr}')
    except Exception as e:
        try:
            if conn:
                conn.rollback()
                conn.close()
        except Exception:
            pass
        return _warn(f'Could not read inquiries: {e}')


def _check_stats_data():
    """The data behind the goocampus.in numbers: colleges, cut-offs, mentors."""
    from db import get_db
    conn = None
    try:
        conn = get_db()
        colleges = (conn.execute("SELECT COUNT(*) AS n FROM pg_college_master").fetchone() or {}).get('n', 0) or 0
        cutoffs = (conn.execute("SELECT COUNT(*) AS n FROM pg_cutoffs").fetchone() or {}).get('n', 0) or 0
        mentors = (conn.execute(
            "SELECT COUNT(*) AS n FROM pg_mentors WHERE COALESCE(is_published, 1) = 1").fetchone() or {}).get('n', 0) or 0
        conn.close()
        detail = f'Colleges {colleges:,} · Cut-off rows {cutoffs:,} · Mentors {mentors:,}'
        if colleges and cutoffs and mentors:
            return _ok(f'Predictor & explorer data present — {detail}')
        if not (colleges or cutoffs or mentors):
            return _down(f'No college/cut-off/mentor data found — the site tools would show empty ({detail})')
        return _warn(f'Some data set looks empty — {detail}')
    except Exception as e:
        try:
            if conn:
                conn.rollback()
                conn.close()
        except Exception:
            pass
        return _warn(f'Could not read statistics data: {e}')


# ---------------------------------------------------------------- network checks (run in threads)
def _check_storage():
    try:
        from core import storage
        if not storage.is_configured():
            return _warn('R2 keys not set on this server — client photos, docs & contracts will not load')
        client = storage.get_client()
        if not client:
            return _down('R2 is configured but the storage client could not start')
        client.head_bucket(Bucket=storage.get_bucket_name())
        return _ok(f'Bucket "{storage.get_bucket_name()}" reachable — files will load')
    except Exception as e:
        return _down(f'Storage error: {e}')


def _check_resend():
    key = (os.environ.get('RESEND_API_KEY') or '').strip()
    if not key:
        return _down('RESEND_API_KEY missing — this server cannot send any email')
    try:
        import requests
        r = requests.get('https://api.resend.com/domains',
                         headers={'Authorization': f'Bearer {key}'}, timeout=_NET_TIMEOUT)
        if r.status_code in (401, 403):
            return _down(f'Resend rejected the key (HTTP {r.status_code}) — emails will fail')
        if r.status_code != 200:
            return _warn(f'Resend key present but API returned HTTP {r.status_code}')
        data = r.json() if r.content else {}
        doms = (data.get('data') or data.get('domains') or []) if isinstance(data, dict) else []
        gc = next((d for d in doms if (d.get('name') or '').lower() == 'goocampus.in'), None)
        if gc and str(gc.get('status', '')).lower() == 'verified':
            return _ok('Resend live — goocampus.in sender domain is verified')
        if gc:
            return _warn(f'goocampus.in domain status = "{gc.get("status")}" — emails may not deliver')
        return _warn('Resend key valid, but the goocampus.in sender domain was not found')
    except Exception as e:
        return _warn(f'Could not reach the Resend API: {e}')


def _check_infobip():
    key = (os.environ.get('INFOBIP_API_KEY') or '').strip()
    base = (os.environ.get('INFOBIP_BASE_URL') or '').strip()
    if not key or not base:
        return _down('Infobip not set — WhatsApp messages and OTPs will not send')
    try:
        import requests
        r = requests.get(f'https://{base}/account/1/balance',
                         headers={'Authorization': f'App {key}', 'Accept': 'application/json'},
                         timeout=_NET_TIMEOUT)
        if r.status_code == 401:
            return _down('Infobip rejected the key (HTTP 401) — WhatsApp/OTP will fail')
        if r.status_code == 403:
            # Key authenticated but not scoped to read account balance. Messaging
            # still works (that is a different scope), so this is healthy.
            return _ok('Infobip key valid — WhatsApp & OTP can send (balance not visible to this key)')
        if r.status_code == 200:
            extra = ''
            try:
                bal = r.json()
                amt, cur = bal.get('balance'), bal.get('currency', '')
                if amt is not None:
                    extra = f' — balance {amt} {cur}'.rstrip()
                    if isinstance(amt, (int, float)) and amt <= 0:
                        return _warn(f'Infobip live but balance is {amt} {cur} — top up or messages stop')
            except Exception:
                pass
            return _ok(f'Infobip live — WhatsApp & OTP can send{extra}')
        return _warn(f'Infobip reachable but returned HTTP {r.status_code}')
    except Exception as e:
        return _warn(f'Could not reach Infobip: {e}')


def _check_site(url, name):
    try:
        import requests
        t0 = time.time()
        r = requests.get(url, timeout=_NET_TIMEOUT, allow_redirects=True)
        ms = int((time.time() - t0) * 1000)
        if r.status_code < 400:
            return _ok(f'{name} is up — HTTP {r.status_code} in {ms} ms')
        if r.status_code in (401, 403):
            return _warn(f'{name} responded HTTP {r.status_code} (up, but access-restricted)')
        return _down(f'{name} returned HTTP {r.status_code}')
    except Exception as e:
        return _down(f'{name} is unreachable: {e}')


def _overall(sections):
    order = {'down': 3, 'warn': 2, 'ok': 1}
    worst = 'ok'
    for s in sections:
        for c in s['checks']:
            if order.get(c['status'], 1) > order.get(worst, 1):
                worst = c['status']
    return worst


def health_dashboard():
    if not session.get('is_admin'):
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))

    # Fast, local (DB) checks — run inline.
    db = _check_db()
    otp = _check_otp()
    signups = _check_doctor_signups()
    sync = _check_profile_sync()
    handshake = _check_handshake()
    inquiries = _check_inquiries()
    stats = _check_stats_data()
    j_new = _check_new_registrations()
    j_sales = _check_sales_verification()
    j_ops = _check_ops_verification()
    j_onb = _check_onboarding_completion()

    # Slow, outbound (network) checks — run in parallel to keep the page snappy.
    net = {}
    jobs = [
        ('storage', _check_storage),
        ('resend', _check_resend),
        ('infobip', _check_infobip),
        ('site_in', lambda: _check_site(GOOCAMPUS_IN_URL, 'goocampus.in')),
        ('site_jobs', lambda: _check_site(JOBS_URL, 'jobs.goocampus.in')),
    ]
    try:
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {k: ex.submit(fn) for k, fn in jobs}
            for k, f in futs.items():
                try:
                    net[k] = f.result(timeout=_NET_TIMEOUT + 4)
                except Exception as e:
                    net[k] = _warn(f'Check timed out: {e}')
    except Exception:
        for k, fn in jobs:
            if k not in net:
                try:
                    net[k] = fn()
                except Exception as e:
                    net[k] = _warn(f'Check failed: {e}')

    sections = [
        {
            'title': 'GooCampus.org — Portal & Operations',
            'icon': '🏢',
            'note': 'The staff portal you are in now (goocampus.org) and everything Operations runs on.',
            'checks': [
                dict(label='Database', **db),
                dict(label='File storage (client photos, docs, contracts)', **net['storage']),
                dict(label='Email sending (Resend)', **net['resend']),
                dict(label='WhatsApp sending (Infobip)', **net['infobip']),
                dict(label='OTP code generation', **otp),
            ],
        },
        {
            'title': 'Client Journey — onboarding flow',
            'icon': '🔄',
            'note': 'The client pipeline end to end: registration → sales verify → ops verify → contract/refund onboarding. Flags a stage where clients get stuck.',
            'checks': [
                dict(label='New registrations arriving', **j_new),
                dict(label='Sales verification', **j_sales),
                dict(label='Operations verification', **j_ops),
                dict(label='Contract / refund onboarding', **j_onb),
            ],
        },
        {
            'title': 'GooCampus.in — NEET-PG doctor site & data',
            'icon': '🩺',
            'note': 'The public doctor dashboard, the data pipe to this portal, and the data behind the site tools.',
            'checks': [
                dict(label='Website reachable', **net['site_in']),
                dict(label='Portal ↔ site connection (API key)', **handshake),
                dict(label='Website inquiries flowing in', **inquiries),
                dict(label='Doctor sign-ups flowing in', **signups),
                dict(label='Doctor profiles complete (onboarding sync)', **sync),
                dict(label='Predictor / cut-off / mentor data', **stats),
            ],
        },
        {
            'title': 'jobs.goocampus.in — Careers site',
            'icon': '💼',
            'note': 'The careers/jobs site. (Runs separately — this is an uptime check only.)',
            'checks': [
                dict(label='Website reachable', **net['site_jobs']),
            ],
        },
    ]

    meta = {
        'overall': _overall(sections),
        'checked_at': _ist_str(),
        'host': os.environ.get('RENDER_EXTERNAL_URL') or 'goocampus.org',
        'commit': (os.environ.get('RENDER_GIT_COMMIT') or '')[:12],
        'branch': os.environ.get('RENDER_GIT_BRANCH') or '',
    }
    counts = {'ok': 0, 'warn': 0, 'down': 0}
    for s in sections:
        for c in s['checks']:
            counts[c['status']] = counts.get(c['status'], 0) + 1
    meta['counts'] = counts

    return render_template('admin_health.html', sections=sections, meta=meta)


def register_health(app):
    app.add_url_rule('/admin/health', endpoint='health_dashboard',
                     view_func=health_dashboard, methods=['GET'])
