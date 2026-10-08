"""Counselling-notice scraper → News Inbox (founder 2026-10-08).

Watches each counselling authority's notices page and drops every NEW notice into
`pg_news_inbox` for the team to review. Nothing is published automatically: from the
inbox the team clicks "Add to News", which pre-fills the newsroom form (heading,
authority, date, official link) and, for a PDF notice, attaches the PDF on save.

Runs 4x a day on the server — 10:00 AM, 1:00 PM, 6:30 PM and 11:00 PM IST — plus a "Check now"
button. Several processes may start the schedule (2 gunicorn workers x live + staging,
one shared DB), so each run takes a Postgres advisory lock and skips a source that was
checked in the last 20 minutes; inbox rows are unique per (source, item) anyway.

Sources are site-specific (each govt site lays notices out differently), so each
source names a reader. Start: Karnataka KEA — PG Medical/DNB 2026.
"""
import re
import html as _html
import logging
from datetime import datetime, date
from db import get_db

UA = 'Mozilla/5.0 (compatible; GooCampus-NoticeMonitor/1.0; +https://goocampus.in)'
TIMEOUT = 40
RECENT_SKIP_MINUTES = 20

# code → config. authority_code matches pg_admin/authorities.py; news_authority is the
# value the newsroom form's "Counselling Authority" dropdown expects.
SOURCES = {
    'kea_pgmed_2026': {
        'label': 'Karnataka KEA — PG Medical / DNB 2026',
        'authority_code': 'kea',
        'news_authority': 'state:Karnataka',
        'url': 'https://cetonline.karnataka.gov.in/kea/pgetmed2026',
        'reader': 'kea_aspnet',
        'enabled': True,
    },
}


# ── tables ───────────────────────────────────────────────────────────────────
def ensure_news_inbox_tables(conn=None):
    own = conn is None
    conn = conn or get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_news_inbox (
            id SERIAL PRIMARY KEY,
            source_code TEXT NOT NULL,
            authority_code TEXT DEFAULT '',
            item_key TEXT NOT NULL,                 -- the site's own id, else the link
            title TEXT NOT NULL DEFAULT '',
            raw_title TEXT DEFAULT '',
            url TEXT DEFAULT '',
            kind TEXT DEFAULT 'link',               -- 'pdf' | 'link'
            notice_date DATE,
            status TEXT DEFAULT 'new',              -- new | posted | dismissed
            news_id INTEGER,
            reviewed_by TEXT DEFAULT '',
            reviewed_at TIMESTAMP,
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (source_code, item_key)
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_news_inbox_status ON pg_news_inbox (status, first_seen_at)")
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_news_scrape_runs (
            id SERIAL PRIMARY KEY,
            source_code TEXT NOT NULL,
            ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ok BOOLEAN DEFAULT TRUE,
            found INTEGER DEFAULT 0,
            new_count INTEGER DEFAULT 0,
            error TEXT DEFAULT '',
            trigger TEXT DEFAULT 'schedule'
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_news_scrape_runs ON pg_news_scrape_runs (source_code, ran_at)")
        conn.commit()
    except Exception as e:
        logging.warning("ensure_news_inbox_tables: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        if own:
            conn.close()


# ── parsing helpers ──────────────────────────────────────────────────────────
_DATE_RE = re.compile(r'(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(20\d{2})')


def _text(fragment):
    return re.sub(r'\s+', ' ', _html.unescape(re.sub(r'<[^>]+>', ' ', fragment or ''))).strip()


def split_title_date(raw):
    """'PG MEDICAL 2026 NOTIFICATION.06-10-2026' → ('PG MEDICAL 2026 NOTIFICATION', date(2026,10,6)).
    Takes the LAST date in the text; leaves the title alone if none parses."""
    ms = list(_DATE_RE.finditer(raw or ''))
    if not ms:
        return (raw or '').strip(), None
    m = ms[-1]
    try:
        d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return (raw or '').strip(), None
    title = re.sub(r'[(\[]\s*[.,]?\s*[)\]]', '', raw[:m.start()] + raw[m.end():]).strip()   # "()" left by "(date)"
    for _ in range(3):                                         # "(dd-mm-yyyy)" leaves "(" + ")"
        title = re.sub(r'[\s.,:;\-–(\[]+$', '', title).strip()
        if title.endswith(')') and title.count(')') > title.count('('):
            title = title[:-1]
    return (title or raw.strip()), d


def norm_title(t):
    """For repeat detection: case/punctuation/space-insensitive."""
    return re.sub(r'[^a-z0-9]+', ' ', (t or '').lower()).strip()


def is_repeat(conn, code, it):
    """A notice the site RE-POSTED under a new id (founder: only fresh news): the same PDF
    file again, or the same title with the same date / same link. A new title on an old
    link (e.g. 'Round 2 payment' on the same portal) is fresh news, not a repeat."""
    nt = norm_title(it['title'])
    for r in conn.execute("SELECT title, url, kind, notice_date FROM pg_news_inbox WHERE source_code = ? "
                          "AND (url = ? OR LOWER(title) = LOWER(?) OR notice_date = ?)",
                          (code, it['url'], it['title'], it['notice_date'])).fetchall():
        if it['kind'] == 'pdf' and r['url'] == it['url']:
            return True
        if norm_title(r['title']) == nt and (r['url'] == it['url'] or
                                             (it['notice_date'] and r['notice_date'] == it['notice_date'])):
            return True
    return False


def _kind(url):
    return 'pdf' if re.search(r'\.pdf($|[?#])', url or '', re.I) else 'link'


# ── readers ──────────────────────────────────────────────────────────────────
def read_kea_aspnet(url):
    """KEA (cetonline.karnataka.gov.in/kea/...) — ASP.NET page, Kannada by default.
    Switch to English via the language postback, then read the notice accordion:
    <a id='lnk<ID>' href='<pdf or page>'>TITLE dd-mm-yyyy</a>."""
    import requests
    s = requests.Session()
    s.headers['User-Agent'] = UA
    r = s.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    page = r.text
    hidden = dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', page))
    if '__VIEWSTATE' in hidden and 'ddlLanguage' in page:
        data = dict(hidden)
        data.update({'__EVENTTARGET': 'ctl00$ddlLanguage', '__EVENTARGUMENT': '', 'ctl00$ddlLanguage': 'E'})
        try:
            r2 = s.post(r.url, data=data, timeout=TIMEOUT)
            if r2.ok and 'lnk' in r2.text:
                page = r2.text
        except Exception as e:                     # fall back to the Kannada page
            logging.warning("kea english switch failed: %s", e)
    items = []
    for item_id, href, inner in re.findall(
            r"<a\s+id=['\"]lnk(\d+)['\"]\s+href=['\"]([^'\"]*)['\"][^>]*>(.*?)</a>", page, re.S | re.I):
        raw = _text(inner)
        href = _html.unescape(href).strip()
        if not raw or not href or href == '#':
            continue
        if not href.lower().startswith('http'):
            from urllib.parse import urljoin
            href = urljoin(r.url, href)
        title, d = split_title_date(raw)
        items.append({'item_key': 'lnk' + item_id, 'raw_title': raw, 'title': title,
                      'url': href, 'kind': _kind(href), 'notice_date': d})
    if not items:
        raise ValueError('No notices found on the page — the site layout may have changed.')
    return items


READERS = {'kea_aspnet': read_kea_aspnet}


# ── running ──────────────────────────────────────────────────────────────────
def _lock_key(code):
    return 'pg_news_scrape:' + code


def run_source(code, trigger='schedule'):
    """Check one source; insert new notices. Returns {'ok','found','new','error','skipped'}."""
    src = SOURCES.get(code)
    out = {'source': code, 'ok': False, 'found': 0, 'new': 0, 'error': '', 'skipped': ''}
    if not src:
        out['error'] = 'unknown source'; return out
    conn = get_db()
    locked = False
    try:
        ensure_news_inbox_tables(conn)
        try:
            locked = bool(conn.execute("SELECT pg_try_advisory_lock(hashtext(?)) AS ok",
                                       (_lock_key(code),)).fetchone()['ok'])
        except Exception:
            conn.rollback(); locked = True          # non-Postgres (local) — no locking
        if not locked:
            out['skipped'] = 'another check is running'; return out
        if trigger == 'schedule':
            recent = conn.execute(
                "SELECT COUNT(*) AS n FROM pg_news_scrape_runs WHERE source_code = ? AND ok "
                f"AND ran_at > CURRENT_TIMESTAMP - INTERVAL '{RECENT_SKIP_MINUTES} minutes'",
                (code,)).fetchone()['n']
            if recent:
                out['skipped'] = 'checked recently'; return out
        try:
            items = READERS[src['reader']](src['url'])
        except Exception as e:
            out['error'] = str(e)[:400]
            conn.execute("INSERT INTO pg_news_scrape_runs (source_code, ok, error, trigger) VALUES (?,?,?,?)",
                         (code, False, out['error'], trigger))
            conn.commit()
            logging.warning("news scrape %s failed: %s", code, e)
            return out
        new = 0
        for it in items:
            if conn.execute("SELECT 1 FROM pg_news_inbox WHERE source_code = ? AND item_key = ?",
                            (code, it['item_key'])).fetchone():
                continue                                    # already have this exact notice
            if is_repeat(conn, code, it):
                continue                                    # re-posted copy of an earlier notice
            row = conn.execute(
                "INSERT INTO pg_news_inbox (source_code, authority_code, item_key, title, raw_title, url, "
                "kind, notice_date) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT (source_code, item_key) DO NOTHING RETURNING id",
                (code, src['authority_code'], it['item_key'], it['title'][:500], it['raw_title'][:800],
                 it['url'][:1000], it['kind'], it['notice_date'])).fetchone()
            new += 1 if row else 0
        conn.execute("INSERT INTO pg_news_scrape_runs (source_code, ok, found, new_count, trigger) "
                     "VALUES (?,?,?,?,?)", (code, True, len(items), new, trigger))
        conn.commit()
        out.update(ok=True, found=len(items), new=new)
        if new:
            logging.info("news scrape %s: %d new notice(s)", code, new)
        return out
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        out['error'] = str(e)[:400]
        logging.error("run_source %s: %s", code, e)
        return out
    finally:
        if locked:
            try:
                conn.execute("SELECT pg_advisory_unlock(hashtext(?))", (_lock_key(code),))
                conn.commit()
            except Exception:
                pass
        conn.close()


def run_all(trigger='schedule'):
    return [run_source(c, trigger) for c, s in SOURCES.items() if s.get('enabled')]


def start_scheduler():
    """10:00 AM, 1:00 PM, 6:30 PM, 11:00 PM IST. Safe to call in every process (see module doc)."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        sch = BackgroundScheduler()
        for jid, (h, m) in {'am': (10, 0), 'pm': (13, 0), 'eve': (18, 30), 'night': (23, 0)}.items():
            sch.add_job(run_all, CronTrigger(hour=h, minute=m, timezone=ist),
                        id=f'pg_news_scrape_{jid}', misfire_grace_time=1800, coalesce=True)
        sch.start()
        logging.info("PG news scraper scheduled (10:00, 13:00, 18:30, 23:00 IST)")
    except ImportError:
        logging.warning("APScheduler not installed — news scraper schedule disabled")
    except Exception as e:
        logging.error("news scraper schedule failed: %s", e)


# ── "Add to News" helper ─────────────────────────────────────────────────────
MAX_PDF_BYTES = 25 * 1024 * 1024


def fetch_pdf(url):
    """Download an official notice PDF → (bytes, filename) or (None, reason)."""
    import requests
    try:
        r = requests.get(url, timeout=60, headers={'User-Agent': UA}, stream=True)
        r.raise_for_status()
        buf = bytearray()
        for chunk in r.iter_content(64 * 1024):
            buf.extend(chunk)
            if len(buf) > MAX_PDF_BYTES:
                return None, 'PDF is larger than 25 MB'
        data = bytes(buf)
        if not data.startswith(b'%PDF'):
            return None, 'the link did not return a PDF'
        name = (url.split('?')[0].rstrip('/').rsplit('/', 1)[-1] or 'notice.pdf')[:200]
        return data, (name if name.lower().endswith('.pdf') else name + '.pdf')
    except Exception as e:
        return None, str(e)[:200]
