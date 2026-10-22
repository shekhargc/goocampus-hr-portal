"""Bandwidth meter (founder 2026-10-22: the Render workspace used its 25 GB/month of outbound data —
which pages / data feeds / files send the most?).

A thin WSGI wrapper counts the bytes each response actually sends (after gzip, including streamed
files) and adds them to an in-memory tally of (day, service, path pattern, caller). A background
flush writes the tally to `bandwidth_daily` once a minute — never per request, never blocking one.
Live and staging share the database, so every row carries the Render service name.

Caller: 'website' (goocampus.in server, X-PG-Key / X-News-Key) · 'bot' (crawler user-agent) ·
'signed_in' (portal session cookie) · 'public'.

/admin/bandwidth (admin only): totals per day and the top paths, split by caller.
Note: only what the portal itself sends. goocampus.in's own pages are a separate Render service,
and files served straight from R2 (big PDFs, ZIPs) don't count against Render.
"""
import os
import re
import threading
import time
import logging
from datetime import datetime, timedelta

from flask import render_template, request, session, redirect, url_for, flash

_LOCK = threading.Lock()
_TALLY = {}                 # (day, path, caller) -> [hits, bytes]
_FLUSH_EVERY = 60           # seconds
_last_flush = [time.time()]
_SERVICE = (os.environ.get('RENDER_SERVICE_NAME') or 'local')[:60]
_BOT = re.compile(r'bot|crawl|spider|slurp|bingpreview|facebookexternalhit|semrush|ahrefs|mj12|'
                  r'petal|bytespider|gptbot|claudebot|python-requests|curl|wget|headless|uptime', re.I)
_ID = re.compile(r'/(\d+|[0-9a-f]{16,}|[A-Za-z0-9_-]{24,})(?=/|$)')


def _pattern(path):
    """'/admin/pg/users/123/edit' → '/admin/pg/users/<id>/edit'; static files grouped by folder."""
    path = (path or '/')[:300]
    if path.startswith('/static/'):
        parts = path.split('/')
        return '/'.join(parts[:3]) + '/…' if len(parts) > 3 else path
    return _ID.sub('/<id>', path)[:160]


def _caller(environ):
    if environ.get('HTTP_X_PG_KEY') or environ.get('HTTP_X_NEWS_KEY'):
        return 'website'
    if _BOT.search(environ.get('HTTP_USER_AGENT') or ''):
        return 'bot'
    if 'session=' in (environ.get('HTTP_COOKIE') or ''):
        return 'signed_in'
    return 'public'


def _add(path, caller, n):
    day = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date().isoformat()     # IST day
    with _LOCK:
        t = _TALLY.setdefault((day, path, caller), [0, 0])
        t[0] += 1
        t[1] += n
    if time.time() - _last_flush[0] >= _FLUSH_EVERY:
        _last_flush[0] = time.time()
        threading.Thread(target=flush, daemon=True).start()


def ensure_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS bandwidth_daily (day DATE NOT NULL, service TEXT NOT NULL, "
                 "path TEXT NOT NULL, caller TEXT NOT NULL, hits BIGINT DEFAULT 0, bytes BIGINT DEFAULT 0, "
                 "PRIMARY KEY (day, service, path, caller))")
    conn.commit()


def flush():
    with _LOCK:
        items = list(_TALLY.items())
        _TALLY.clear()
    if not items:
        return
    try:
        from db import get_db
        conn = get_db()
        try:
            ensure_table(conn)
            for (day, path, caller), (hits, nbytes) in items:
                conn.execute("INSERT INTO bandwidth_daily (day, service, path, caller, hits, bytes) VALUES (?,?,?,?,?,?) "
                             "ON CONFLICT (day, service, path, caller) DO UPDATE SET hits = bandwidth_daily.hits + "
                             "EXCLUDED.hits, bytes = bandwidth_daily.bytes + EXCLUDED.bytes",
                             (day, _SERVICE, path, caller, hits, nbytes))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logging.warning("bandwidth flush: %s", e)      # a lost minute of tallies is acceptable


class _Counted:
    """Wraps the response body iterator; counts bytes as they go out."""
    def __init__(self, it, path, caller):
        self._it, self._path, self._caller, self._n = it, path, caller, 0

    def __iter__(self):
        for chunk in self._it:
            self._n += len(chunk)
            yield chunk

    def close(self):
        try:
            if hasattr(self._it, 'close'):
                self._it.close()
        finally:
            try:
                _add(self._path, self._caller, self._n)
            except Exception:
                pass


class BandwidthMiddleware:
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        try:
            path, caller = _pattern(environ.get('PATH_INFO')), _caller(environ)
        except Exception:
            return self.wsgi_app(environ, start_response)
        return _Counted(self.wsgi_app(environ, start_response), path, caller)


def bandwidth_page():
    if not session.get('is_admin'):
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    try:
        days = max(1, min(int(request.args.get('days') or 7), 90))
    except ValueError:
        days = 7
    svc = (request.args.get('service') or '').strip()
    flush()                                            # include this worker's last minute
    from db import get_db
    conn = get_db()
    try:
        ensure_table(conn)
        since = ((datetime.utcnow() + timedelta(hours=5, minutes=30)).date() - timedelta(days=days - 1)).isoformat()
        where, params = "day >= ?", [since]
        if svc:
            where += " AND service = ?"; params.append(svc)
        services = [r['service'] for r in conn.execute(
            "SELECT service, SUM(bytes) AS b FROM bandwidth_daily GROUP BY service ORDER BY b DESC").fetchall()]
        by_day = [dict(r) for r in conn.execute(
            f"SELECT day, SUM(bytes) AS bytes, SUM(hits) AS hits FROM bandwidth_daily WHERE {where} "
            f"GROUP BY day ORDER BY day DESC", params).fetchall()]
        by_caller = [dict(r) for r in conn.execute(
            f"SELECT caller, SUM(bytes) AS bytes, SUM(hits) AS hits FROM bandwidth_daily WHERE {where} "
            f"GROUP BY caller ORDER BY bytes DESC", params).fetchall()]
        by_service = [dict(r) for r in conn.execute(
            "SELECT service, SUM(bytes) AS bytes, SUM(hits) AS hits FROM bandwidth_daily WHERE day >= ? "
            "GROUP BY service ORDER BY bytes DESC", (since,)).fetchall()]
        top = [dict(r) for r in conn.execute(
            f"SELECT path, SUM(bytes) AS bytes, SUM(hits) AS hits, "
            f"SUM(CASE WHEN caller='website' THEN bytes ELSE 0 END) AS website, "
            f"SUM(CASE WHEN caller='bot' THEN bytes ELSE 0 END) AS bot, "
            f"SUM(CASE WHEN caller='signed_in' THEN bytes ELSE 0 END) AS signed_in, "
            f"SUM(CASE WHEN caller='public' THEN bytes ELSE 0 END) AS public "
            f"FROM bandwidth_daily WHERE {where} GROUP BY path ORDER BY bytes DESC LIMIT 60", params).fetchall()]
        first = conn.execute("SELECT MIN(day) AS d FROM bandwidth_daily").fetchone()['d']
    finally:
        conn.close()
    total = sum(int(r['bytes'] or 0) for r in by_day)
    return render_template('admin_bandwidth.html', days=days, svc=svc, services=services, by_day=by_day,
                           by_caller=by_caller, by_service=by_service, top=top, total=total, since=since,
                           first=first)


def register_bandwidth(app):
    app.wsgi_app = BandwidthMiddleware(app.wsgi_app)
    app.add_url_rule('/admin/bandwidth', endpoint='bandwidth_dashboard', view_func=bandwidth_page, methods=['GET'])

    @app.template_filter('human_bytes')
    def _human_bytes(n):
        n = float(n or 0)
        for unit in ('B', 'KB', 'MB', 'GB'):
            if n < 1024 or unit == 'GB':
                return f"{n:.0f} {unit}" if unit in ('B', 'KB') else f"{n:.1f} {unit}"
            n /= 1024
