"""Email open / click tracking for the bulk emails we send doctors (news alerts, deadline reminders,
announcements, rankings). Each email gets a row in pg_email_log + a token; the HTML gets an invisible
1x1 image (open) and our goocampus.in / goocampus.org links are routed through a redirect (click).
Read on /admin/pg/analytics. (founder 2026-10-27)

Opens are approximate: Apple Mail pre-loads images (counts as opened), and a doctor whose mail app
blocks images is only counted once they click. Clicks are the reliable number."""
import base64
import html as _html
import logging
import re
import secrets
from urllib.parse import quote, urlparse

from flask import request, redirect, Response
from db import get_db

logger = logging.getLogger(__name__)

BASE = 'https://goocampus.org'          # one shared DB → every send logs here, live or staging
_ALLOWED_HOSTS = {'goocampus.in', 'www.goocampus.in', 'goocampus.org', 'www.goocampus.org'}
_TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{10,64}$')
_HREF_RE = re.compile(r'''(href=["'])(https?://[^"']+)(["'])''', re.I)
_GIF = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')
_ready = False


def ensure(conn):
    global _ready
    if _ready:
        return
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_email_log (
        id SERIAL PRIMARY KEY,
        token TEXT UNIQUE NOT NULL,
        kind TEXT DEFAULT '',               -- news | deadline | announcement | rankings
        ref_id INTEGER,                     -- news id / rankings log id (NULL when none)
        ref_label TEXT DEFAULT '',          -- heading / announcement key / reminder date
        subject TEXT DEFAULT '',
        email TEXT DEFAULT '',
        user_id INTEGER,                    -- pg_users.id (NULL for staff)
        sent_ok INTEGER DEFAULT 0,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        opened_at TIMESTAMP,
        last_open_at TIMESTAMP,
        open_count INTEGER DEFAULT 0,
        clicked_at TIMESTAMP,
        last_click_at TIMESTAMP,
        click_count INTEGER DEFAULT 0,
        last_url TEXT DEFAULT ''
    )''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_email_log_camp ON pg_email_log (kind, ref_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_email_log_user ON pg_email_log (user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_email_log_sent ON pg_email_log (sent_at)")
    conn.commit()
    _ready = True


def _host_ok(url):
    try:
        return (urlparse(url).hostname or '').lower() in _ALLOWED_HOSTS
    except Exception:
        return False


def user_id_for_email(conn, email):
    try:
        r = conn.execute("SELECT id FROM pg_users WHERE LOWER(TRIM(email)) = LOWER(TRIM(?)) "
                         "ORDER BY id LIMIT 1", [email or '']).fetchone()
        return r['id'] if r else None
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return None


def tag(html, token):
    """Route our own links through the click redirect and add the open pixel."""
    def _sub(m):
        url = _html.unescape(m.group(2))
        if not _host_ok(url) or '/e/c/' in url:
            return m.group(0)
        return f"{m.group(1)}{BASE}/e/c/{token}?u={quote(url, safe='')}{m.group(3)}"
    out = _HREF_RE.sub(_sub, html or '')
    pixel = (f'<img src="{BASE}/e/o/{token}.gif" width="1" height="1" alt="" '
             'style="display:block;width:1px;height:1px;border:0;opacity:0;">')
    i = out.lower().rfind('</body>')
    return out[:i] + pixel + out[i:] if i >= 0 else out + pixel


def wrap(conn, html, *, kind, email, subject='', ref_id=None, ref_label='', user_id=None):
    """Log one outgoing email and return (tracked_html, token). On any failure the email still
    goes out untracked: returns (html, None)."""
    try:
        ensure(conn)
        if user_id is None:
            user_id = user_id_for_email(conn, email)
        token = secrets.token_urlsafe(18)
        conn.execute("INSERT INTO pg_email_log (token, kind, ref_id, ref_label, subject, email, user_id) "
                     "VALUES (?,?,?,?,?,?,?)",
                     [token, kind, ref_id, (ref_label or '')[:300], (subject or '')[:300],
                      (email or '').strip().lower(), user_id])
        conn.commit()
        return tag(html, token), token
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning("email tracking wrap: %s", e)
        return html, None


def mark_sent(conn, token, ok):
    if not token:
        return
    try:
        conn.execute("UPDATE pg_email_log SET sent_ok = ? WHERE token = ?", [1 if ok else 0, token])
        conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass


# ── public endpoints (no login: they are hit from the doctor's mail app) ──

def email_open(token):
    if _TOKEN_RE.match(token or ''):
        conn = get_db()
        try:
            conn.execute("UPDATE pg_email_log SET open_count = COALESCE(open_count,0) + 1, "
                         "opened_at = COALESCE(opened_at, CURRENT_TIMESTAMP), last_open_at = CURRENT_TIMESTAMP "
                         "WHERE token = ?", [token])
            conn.commit()
        except Exception as e:
            try: conn.rollback()
            except Exception: pass
            logger.warning("email_open: %s", e)
        finally:
            conn.close()
    resp = Response(_GIF, mimetype='image/gif')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


def email_click(token):
    url = request.args.get('u') or ''
    if not _host_ok(url):
        url = 'https://goocampus.in'
    if _TOKEN_RE.match(token or ''):
        conn = get_db()
        try:
            # A click proves the email was opened, even when the mail app blocked the image.
            conn.execute("UPDATE pg_email_log SET click_count = COALESCE(click_count,0) + 1, "
                         "clicked_at = COALESCE(clicked_at, CURRENT_TIMESTAMP), last_click_at = CURRENT_TIMESTAMP, "
                         "opened_at = COALESCE(opened_at, CURRENT_TIMESTAMP), last_url = ? WHERE token = ?",
                         [url[:500], token])
            conn.commit()
        except Exception as e:
            try: conn.rollback()
            except Exception: pass
            logger.warning("email_click: %s", e)
        finally:
            conn.close()
    return redirect(url, 302)
