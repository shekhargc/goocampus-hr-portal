"""Speed helpers for the public goocampus.in APIs (speed audit 2026-10-09).

- ttl_cache: tiny per-worker in-memory cache (dict + expiry), keyed by the cut-off
  dataset version so an upload invalidates everything automatically.
- cutoffs_version(): cheap fingerprint of pg_cutoffs (row count + max id), re-checked at
  most every 30 s per worker.
- register(app): gzip for JSON on /api/pg/* + Cache-Control on read-only public GETs.
"""
import gzip
import time
import threading

_LOCK = threading.Lock()
_CACHE = {}            # key -> (expires_at, value)
_MAX_ENTRIES = 2000
_VER = {'at': 0.0, 'v': None}


def cache_get(key):
    hit = _CACHE.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def cache_set(key, value, ttl=600):
    with _LOCK:
        if len(_CACHE) >= _MAX_ENTRIES:
            now = time.time()
            for k in [k for k, (exp, _v) in _CACHE.items() if exp <= now][:500] or list(_CACHE)[:200]:
                _CACHE.pop(k, None)
        _CACHE[key] = (time.time() + ttl, value)
    return value


def cutoffs_version(conn):
    """'<count>:<max id>' of pg_cutoffs — changes on every upload. Checked ≤ every 30 s."""
    now = time.time()
    if _VER['v'] is not None and now - _VER['at'] < 30:
        return _VER['v']
    try:
        r = conn.execute("SELECT COUNT(*) AS n, COALESCE(MAX(id),0) AS m FROM pg_cutoffs").fetchone()
        v = f"{r['n']}:{r['m']}"
    except Exception:
        try: conn.rollback()
        except Exception: pass
        v = 'x'
    _VER.update(at=now, v=v)
    return v


# Read-only, non-personal public GETs (server-to-server with X-PG-Key) that the site may
# cache for a few minutes. Anything token/doctor-specific is NOT listed.
_CACHEABLE = (
    '/api/pg/cutoff-explorer', '/api/pg/predictor/filters', '/api/pg/predictor/courses',
    '/api/pg/seat-matrix', '/api/pg/pg-colleges', '/api/pg/stipend', '/api/pg/fees',
    '/api/pg/college-lookup', '/api/pg/authorities', '/api/pg/mentors',
    '/api/pg/news/deadlines',
)


def register(app):
    @app.after_request
    def _pg_api_speed(resp):
        try:
            from flask import request
            path = request.path or ''
            if not path.startswith('/api/pg/') or request.method != 'GET' or resp.status_code != 200:
                return resp
            personal = bool(request.headers.get('Authorization'))
            if (not personal and 'Cache-Control' not in resp.headers
                    and any(path == p or path.startswith(p + '/') for p in _CACHEABLE)
                    and not path.endswith('/photo')):
                resp.headers['Cache-Control'] = 'public, max-age=300, stale-while-revalidate=600'
            # gzip JSON (big lists compress ~8-10x)
            if (resp.mimetype == 'application/json' and not resp.direct_passthrough
                    and 'gzip' in (request.headers.get('Accept-Encoding') or '').lower()
                    and 'Content-Encoding' not in resp.headers):
                data = resp.get_data()
                if len(data) > 1400:
                    resp.set_data(gzip.compress(data, compresslevel=5))
                    resp.headers['Content-Encoding'] = 'gzip'
                    resp.headers['Content-Length'] = str(len(resp.get_data()))
                    vary = resp.headers.get('Vary')
                    resp.headers['Vary'] = (vary + ', Accept-Encoding') if vary else 'Accept-Encoding'
        except Exception:
            pass
        return resp
