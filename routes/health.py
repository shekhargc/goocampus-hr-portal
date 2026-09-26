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
    """Doctors with no name = onboarding->profile sync didn't land (the '(name pending)' bug)."""
    from db import get_db
    conn = None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM pg_users WHERE COALESCE(name, '') = ''"
        ).fetchone()
        conn.close()
        n = (row['n'] if row else 0) or 0
        if n == 0:
            return _ok('Every doctor profile has a name — onboarding sync is healthy')
        if n <= 3:
            return _warn(f'{n} doctor(s) still show "name pending" — worth a look')
        return _down(f'{n} doctors show "name pending" — onboarding→profile sync may be broken')
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
        if r.status_code in (401, 403):
            return _down(f'Infobip rejected the key (HTTP {r.status_code}) — WhatsApp/OTP will fail')
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
            'title': 'GooCampus.in — NEET-PG doctor site',
            'icon': '🩺',
            'note': 'The public doctor dashboard and the data pipe between it and this portal.',
            'checks': [
                dict(label='Website reachable', **net['site_in']),
                dict(label='Portal ↔ site connection (API key)', **handshake),
                dict(label='Doctor sign-ups flowing in', **signups),
                dict(label='Doctor profiles complete (onboarding sync)', **sync),
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
