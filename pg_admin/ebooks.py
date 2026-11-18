"""International pathways + secure e-books inside the goocampus.in dashboard (founder 2026-11-18).

Our own country e-books (UAE, Saudi Arabia, Australia — chapter PDFs) are sold per country or as a bundle of all
three, valid 1 year, and read ONLY inside the dashboard:
  - the PDF never leaves the server; each page is a pre-rendered image (made on the Mac by tools/ebooks/prepare.py,
    stored in R2 under ebooks/<code>/…),
  - every page a doctor opens is re-drawn with their name + last 4 mobile digits burned in (watermark), cached in
    R2 per doctor and handed out through a short-lived signed link,
  - views are logged (page, doctor, time) so a leaked page can be traced.
The chapters double as the steps of the country's pathway map (free to see: title + short summary; the full
chapter needs the e-book).

Tables: pg_ebooks (one row per country book + one bundle row), pg_ebook_chapters, pg_ebook_pages,
pg_ebook_access (who can read what until when), pg_ebook_orders (Razorpay), pg_ebook_progress, pg_ebook_views.
Purchases use their OWN order table (like the ₹4,999 session) — never pg_subscriptions, so buying an e-book never
changes a doctor's plan / category.
"""
import hashlib
import hmac
import io
import json
import logging
import os
import re
import time

from flask import request, jsonify

from db import get_db

logger = logging.getLogger(__name__)

GST_DEFAULT = 18.0
VALIDITY_DAYS = 365
PAGE_URL_TTL = 120                       # seconds a signed page link stays valid
_READY = {'done': False}

# The three books (founder 2026-11-18). Prices are set in the admin (0 = not on sale yet).
SEED = [
    {'code': 'uae', 'country': 'UAE', 'title': 'UAE — IMG Guide for Indian Doctors', 'sort_order': 1},
    {'code': 'saudi', 'country': 'Saudi Arabia', 'title': 'Saudi Arabia — IMG Guide for Indian Doctors', 'sort_order': 2},
    {'code': 'australia', 'country': 'Australia', 'title': 'Australia — IMG Guide for Indian Doctors', 'sort_order': 3},
    {'code': 'all3', 'country': '', 'title': 'All 3 country guides (UAE + Saudi Arabia + Australia)', 'sort_order': 9,
     'is_bundle': True, 'bundle_codes': 'uae,saudi,australia'},
]


def ensure(conn):
    if _READY['done']:
        return
    conn.execute("SET LOCAL lock_timeout = '3s'")
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_ebooks (
        id SERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, country TEXT DEFAULT '', title TEXT DEFAULT '',
        subtitle TEXT DEFAULT '', price NUMERIC(12,2) DEFAULT 0, gst_percent NUMERIC(5,2) DEFAULT 18,
        validity_days INTEGER DEFAULT 365, is_active BOOLEAN DEFAULT FALSE, is_bundle BOOLEAN DEFAULT FALSE,
        bundle_codes TEXT DEFAULT '', sort_order INTEGER DEFAULT 0, blurb TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_ebook_chapters (
        id SERIAL PRIMARY KEY, ebook_code TEXT NOT NULL, chapter_no INTEGER NOT NULL, title TEXT DEFAULT '',
        page_count INTEGER DEFAULT 0, pdf_key TEXT DEFAULT '', summary TEXT DEFAULT '', service_tag TEXT DEFAULT '',
        is_step BOOLEAN DEFAULT TRUE, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (ebook_code, chapter_no))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_ebook_pages (
        id SERIAL PRIMARY KEY, ebook_code TEXT NOT NULL, chapter_no INTEGER NOT NULL, page_no INTEGER NOT NULL,
        image_key TEXT NOT NULL, width INTEGER DEFAULT 0, height INTEGER DEFAULT 0,
        UNIQUE (ebook_code, chapter_no, page_no))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_ebook_access (
        id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, ebook_code TEXT NOT NULL,
        starts_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, expires_at TIMESTAMP, source TEXT DEFAULT '',
        order_id INTEGER, granted_by TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_ebook_access_user ON pg_ebook_access (user_id, ebook_code)")
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_ebook_orders (
        id SERIAL PRIMARY KEY, razorpay_order_id TEXT UNIQUE, user_id INTEGER, ebook_code TEXT,
        amount NUMERIC(12,2) DEFAULT 0, gst NUMERIC(12,2) DEFAULT 0, payable NUMERIC(12,2) DEFAULT 0,
        status TEXT DEFAULT 'created', razorpay_payment_id TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, paid_at TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_ebook_progress (
        user_id INTEGER NOT NULL, ebook_code TEXT NOT NULL, chapter_no INTEGER NOT NULL, page_no INTEGER DEFAULT 1,
        max_page INTEGER DEFAULT 1, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, ebook_code, chapter_no))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_ebook_views (
        id SERIAL PRIMARY KEY, user_id INTEGER, ebook_code TEXT, chapter_no INTEGER, page_no INTEGER,
        at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    for b in SEED:
        conn.execute("INSERT INTO pg_ebooks (code, country, title, sort_order, is_bundle, bundle_codes, validity_days, "
                     "gst_percent) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (code) DO NOTHING",
                     (b['code'], b['country'], b['title'], b['sort_order'], bool(b.get('is_bundle')),
                      b.get('bundle_codes', ''), VALIDITY_DAYS, GST_DEFAULT))
    conn.commit()
    _READY['done'] = True


# ── access ─────────────────────────────────────────────────────────────────
def owned(conn, user_id):
    """{ebook_code: expires_at} — live access only."""
    out = {}
    for r in conn.execute("SELECT ebook_code, MAX(expires_at) AS exp FROM pg_ebook_access WHERE user_id = ? AND "
                          "(expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) GROUP BY ebook_code",
                          (user_id,)).fetchall():
        out[r['ebook_code']] = r['exp']
    return out


def grant(conn, user_id, book, source, order_id=None, by=''):
    """Give access to a book (a bundle grants each of its books). Extends from the current expiry if still live."""
    codes = [c for c in (book.get('bundle_codes') or '').split(',') if c] if book.get('is_bundle') else [book['code']]
    days = int(book.get('validity_days') or VALIDITY_DAYS)
    have = owned(conn, user_id)
    for c in codes:
        start = "GREATEST(CURRENT_TIMESTAMP, ?::timestamp)" if have.get(c) else "CURRENT_TIMESTAMP"
        args = (have[c],) if have.get(c) else ()
        conn.execute(f"INSERT INTO pg_ebook_access (user_id, ebook_code, starts_at, expires_at, source, order_id, granted_by) "
                     f"VALUES (?, ?, CURRENT_TIMESTAMP, {start} + INTERVAL '{days} days', ?, ?, ?)",
                     (user_id, c) + args + (source, order_id, by))
    return codes


def _book(conn, code):
    r = conn.execute("SELECT * FROM pg_ebooks WHERE code = ?", (code,)).fetchone()
    return dict(r) if r else None


def _money(book):
    base = float(book.get('price') or 0)
    gst = round(base * float(book.get('gst_percent') or 0) / 100.0, 2)
    return base, gst, round(base + gst, 2)


# ── who sees the International dashboard (founder 2026-11-18: pilot on live for his own number first) ──
MODES = ('pilot', 'all', 'off')
DEFAULT_PILOT = '9611996500'


def _kv(conn, key, default=''):
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS pg_kv (key TEXT PRIMARY KEY, value TEXT DEFAULT '', "
                     "updated_by TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        r = conn.execute("SELECT value FROM pg_kv WHERE key = ?", (key,)).fetchone()
        return r['value'] if r and r['value'] is not None else default
    except Exception:
        conn.rollback()
        return default


def _set_kv(conn, key, value, who):
    conn.execute("INSERT INTO pg_kv (key, value, updated_by, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                 "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, "
                 "updated_at = CURRENT_TIMESTAMP", (key, value, who))


def gate_settings(conn):
    mode = _kv(conn, 'intl_mode', 'pilot')
    pilots = [m for m in re.split(r'[\s,;]+', _kv(conn, 'intl_pilot', DEFAULT_PILOT)) if m]
    return (mode if mode in MODES else 'pilot'), [re.sub(r'\D', '', m)[-10:] for m in pilots]


def gate(conn, u):
    """(enabled, is_pilot) for this doctor. 'pilot' = only listed mobiles; 'all' = everyone; 'off' = nobody."""
    mode, pilots = gate_settings(conn)
    m10 = re.sub(r'\D', '', str(u.get('mobile') or ''))[-10:]
    is_pilot = bool(m10) and m10 in pilots
    return (mode == 'all' or (mode == 'pilot' and is_pilot)), (is_pilot and mode != 'off')


# ── doctor APIs (X-PG-Key + doctor Bearer token, same as the rest of /api/pg) ─
def _doctor(conn):
    from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token
    if not _authorized():
        return None, (jsonify({'ok': False, 'error': 'unauthorized'}), 401)
    tok = _bearer_token()
    u = _pg_user_by_token(conn, tok) if tok else None
    if not u:
        return None, (jsonify({'ok': False, 'error': 'login_required'}), 401)
    return dict(u), None


def api_list():
    """GET /api/pg/ebooks → the pathway catalogue: each country book with price, whether this doctor owns it (and
    till when), and its chapters = pathway steps (title, summary, service tag, pages). Bundle listed separately."""
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor(conn)
        if err:
            return err
        enabled, is_pilot = gate(conn, u)
        if not enabled:                     # International dashboard not open to this doctor → hide it entirely
            return jsonify({'ok': True, 'enabled': False, 'ebooks': []})
        have = owned(conn, u['id'])
        # pilot doctors also see books not yet switched on for everyone (if they have chapters / are the bundle)
        books = [dict(r) for r in conn.execute(
            "SELECT * FROM pg_ebooks b WHERE is_active OR (? AND (is_bundle OR EXISTS (SELECT 1 FROM pg_ebook_chapters c "
            "WHERE c.ebook_code = b.code))) ORDER BY sort_order, id", (bool(is_pilot),)).fetchall()]
        chs = {}
        for r in conn.execute("SELECT ebook_code, chapter_no, title, page_count, summary, service_tag, is_step "
                              "FROM pg_ebook_chapters ORDER BY ebook_code, chapter_no").fetchall():
            chs.setdefault(r['ebook_code'], []).append({'no': r['chapter_no'], 'title': r['title'],
                                                        'pages': r['page_count'], 'summary': r['summary'] or '',
                                                        'service_tag': r['service_tag'] or '', 'is_step': bool(r['is_step'])})
        prog, last = {}, {}
        for r in conn.execute("SELECT ebook_code, chapter_no, page_no, max_page, updated_at FROM pg_ebook_progress "
                              "WHERE user_id = ? ORDER BY updated_at", (u['id'],)).fetchall():
            prog.setdefault(r['ebook_code'], {})[r['chapter_no']] = {'page': r['page_no'], 'max_page': r['max_page']}
            last[r['ebook_code']] = {'chapter': r['chapter_no'], 'page': r['page_no']}     # newest wins
        out = []
        for b in books:
            base, gst, payable = _money(b)
            item = {'code': b['code'], 'country': b['country'], 'title': b['title'], 'subtitle': b['subtitle'] or '',
                    'blurb': b['blurb'] or '', 'is_bundle': bool(b['is_bundle']),
                    'price': {'base': base, 'gst_percent': float(b['gst_percent'] or 0), 'gst': gst, 'payable': payable},
                    'validity_days': b['validity_days'], 'on_sale': base > 0}
            if b['is_bundle']:
                codes = [c for c in (b['bundle_codes'] or '').split(',') if c]
                item['includes'] = codes
                item['owned'] = all(c in have for c in codes)
            else:
                item['owned'] = b['code'] in have
                item['expires_at'] = have[b['code']].isoformat() if have.get(b['code']) else None
                item['chapters'] = chs.get(b['code'], [])
                item['pages'] = sum(c['pages'] for c in item['chapters'])
                item['progress'] = prog.get(b['code'], {})
                item['last_read'] = last.get(b['code'])          # {chapter, page} of the page opened most recently
            out.append(item)
        return jsonify({'ok': True, 'enabled': True, 'pilot': bool(is_pilot), 'ebooks': out})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api ebooks list: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_create_order():
    """POST /api/pg/ebooks/create-order {code} → Razorpay order for one book or the bundle (price + GST)."""
    from pg_admin.routes.api import _razorpay_creds
    key_id, key_secret = _razorpay_creds()
    if not (key_id and key_secret):
        return jsonify({'ok': False, 'error': 'payments_not_configured'}), 503
    code = str((request.get_json(silent=True) or {}).get('code') or '').strip()
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor(conn)
        if err:
            return err
        enabled, is_pilot = gate(conn, u)
        book = _book(conn, code)
        if not enabled or not book or not (book['is_active'] or is_pilot):
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        base, gst, payable = _money(book)
        if payable <= 0:
            return jsonify({'ok': False, 'error': 'not_on_sale'}), 400
        import requests as _rq
        try:
            rr = _rq.post('https://api.razorpay.com/v1/orders', auth=(key_id, key_secret),
                          json={'amount': int(round(payable * 100)), 'currency': 'INR',
                                'receipt': f"pge_{u['id']}_{int(time.time())}",
                                'notes': {'user_id': str(u['id']), 'product': 'ebook', 'ebook': code}}, timeout=20)
        except Exception as e:
            logger.error("ebook razorpay order: %s", e)
            return jsonify({'ok': False, 'error': 'gateway_error'}), 502
        if rr.status_code not in (200, 201):
            logger.error("ebook razorpay order %s: %s", rr.status_code, rr.text[:300])
            return jsonify({'ok': False, 'error': 'gateway_error'}), 502
        order = rr.json()
        conn.execute("INSERT INTO pg_ebook_orders (razorpay_order_id, user_id, ebook_code, amount, gst, payable) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (order['id'], u['id'], code, base, gst, payable))
        conn.commit()
        return jsonify({'ok': True, 'order_id': order['id'], 'amount': int(round(payable * 100)), 'currency': 'INR',
                        'key_id': key_id, 'product': book['title'],
                        'breakdown': {'base': base, 'gst_percent': float(book['gst_percent'] or 0), 'gst': gst,
                                      'payable': payable},
                        'prefill': {'name': u.get('name') or '', 'email': u.get('email') or '',
                                    'contact': u.get('mobile') or ''}})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api ebook create-order: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_verify():
    """POST /api/pg/ebooks/verify {razorpay_order_id, razorpay_payment_id, razorpay_signature} → access granted
    (1 year; a bundle grants all three). Idempotent."""
    from pg_admin.routes.api import _razorpay_creds
    _, key_secret = _razorpay_creds()
    if not key_secret:
        return jsonify({'ok': False, 'error': 'payments_not_configured'}), 503
    d = request.get_json(silent=True) or {}
    oid, pid, sig = (str(d.get(k) or '').strip() for k in ('razorpay_order_id', 'razorpay_payment_id',
                                                             'razorpay_signature'))
    if not (oid and pid and sig):
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    expected = hmac.new(key_secret.encode(), f"{oid}|{pid}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return jsonify({'ok': False, 'error': 'signature_mismatch'}), 400
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor(conn)
        if err:
            return err
        o = conn.execute("SELECT * FROM pg_ebook_orders WHERE razorpay_order_id = ?", (oid,)).fetchone()
        if not o:
            return jsonify({'ok': False, 'error': 'order_not_found'}), 404
        o = dict(o)
        if o['user_id'] != u['id']:
            return jsonify({'ok': False, 'error': 'order_mismatch'}), 403
        if o['status'] == 'paid':
            return jsonify({'ok': True, 'already': True, 'ebook': o['ebook_code']})
        got = conn.execute("UPDATE pg_ebook_orders SET status = 'paid', razorpay_payment_id = ?, paid_at = CURRENT_TIMESTAMP "
                           "WHERE id = ? AND status <> 'paid' RETURNING id", (pid, o['id'])).fetchone()
        codes = grant(conn, u['id'], _book(conn, o['ebook_code']), 'razorpay', o['id']) if got else []
        conn.commit()
        return jsonify({'ok': True, 'ebook': o['ebook_code'], 'granted': codes})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api ebook verify: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def _wm_name(u):
    try:
        from core.helpers import format_dr_name as _dr
        n = _dr(u.get('name'))
    except Exception:
        n = (u.get('name') or '').strip()
        n = n if n.lower().startswith('dr') else ('Dr. ' + n if n else '')
    return n or 'goocampus.in doctor'


def _watermark(img_bytes, line1, line2):
    """Burn the doctor's identity into the page: a light diagonal repeat across the page + a footer line."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(io.BytesIO(img_bytes)).convert('RGB')
    w, h = im.size
    size = max(16, w // 48)
    try:
        font = ImageFont.load_default(size=size)
        small = ImageFont.load_default(size=max(12, w // 70))
    except TypeError:                                          # very old Pillow
        font = small = ImageFont.load_default()
    text = f"{line1}  |  {line2}"                                # ASCII only (any font has these glyphs)
    tile = Image.new('RGBA', (w * 2, h * 2), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    step_y, step_x = size * 16, int(size * len(text) * 0.9)          # sparse: a few marks per page
    for yy in range(0, h * 2, step_y):
        off = (yy // step_y % 2) * (step_x // 2)
        for xx in range(-step_x, w * 2, step_x):
            td.text((xx + off, yy), text, font=font, fill=(120, 120, 120, 16))   # very faint
    tile = tile.rotate(28, resample=Image.BICUBIC)
    left, top = (tile.width - w) // 2, (tile.height - h) // 2
    tile = tile.crop((left, top, left + w, top + h))
    base = im.convert('RGBA')
    base.alpha_composite(tile)
    d = ImageDraw.Draw(base)
    d.text((int(w * 0.03), h - max(16, w // 55) - 6), f"Licensed to {line1} ({line2}) - goocampus.in - personal reading only, not for sharing",
           font=small, fill=(150, 150, 150, 150))
    out = io.BytesIO()
    base.convert('RGB').save(out, 'WEBP', quality=80)
    return out.getvalue()


def api_page():
    """GET /api/pg/ebooks/page?code=uae&chapter=3&page=2 → {url, expires_in, pages}: a short-lived signed link to
    this page with the doctor's watermark burned in. Only for doctors who own the book (live access)."""
    from core import storage
    code = (request.args.get('code') or '').strip()
    try:
        ch, pg = int(request.args.get('chapter') or 0), int(request.args.get('page') or 0)
    except ValueError:
        return jsonify({'ok': False, 'error': 'bad_page'}), 400
    conn = get_db()
    try:
        ensure(conn)
        u, err = _doctor(conn)
        if err:
            return err
        if not gate(conn, u)[0]:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        if code not in owned(conn, u['id']):
            return jsonify({'ok': False, 'error': 'not_owned'}), 403
        row = conn.execute("SELECT image_key FROM pg_ebook_pages WHERE ebook_code = ? AND chapter_no = ? AND page_no = ?",
                           (code, ch, pg)).fetchone()
        n = conn.execute("SELECT page_count FROM pg_ebook_chapters WHERE ebook_code = ? AND chapter_no = ?",
                         (code, ch)).fetchone()
        if not row:
            return jsonify({'ok': False, 'error': 'page_not_found'}), 404
        mobile = re.sub(r'\D', '', str(u.get('mobile') or ''))
        line1, line2 = _wm_name(u), ('Mob xx' + mobile[-4:]) if mobile else f"ID {u['id']}"
        sig = hashlib.sha256(f"{line1}|{line2}|v1".encode()).hexdigest()[:10]
        wm_key = f"ebook-wm/{code}/{u['id']}/{sig}/c{ch:02d}-p{pg:03d}.webp"
        if not storage.object_size(wm_key):
            src = storage.download_bytes(row['image_key'])
            if not src:
                return jsonify({'ok': False, 'error': 'page_unavailable'}), 503
            if not storage.upload_bytes(wm_key, _watermark(src, line1, line2), 'image/webp'):
                return jsonify({'ok': False, 'error': 'page_unavailable'}), 503
        conn.execute("INSERT INTO pg_ebook_views (user_id, ebook_code, chapter_no, page_no) VALUES (?, ?, ?, ?)",
                     (u['id'], code, ch, pg))
        conn.execute("INSERT INTO pg_ebook_progress (user_id, ebook_code, chapter_no, page_no, max_page) "
                     "VALUES (?, ?, ?, ?, ?) ON CONFLICT (user_id, ebook_code, chapter_no) DO UPDATE SET "
                     "page_no = EXCLUDED.page_no, max_page = GREATEST(pg_ebook_progress.max_page, EXCLUDED.page_no), "
                     "updated_at = CURRENT_TIMESTAMP", (u['id'], code, ch, pg, pg))
        conn.commit()
        url = storage.presigned_get_url(wm_key, ttl_seconds=PAGE_URL_TTL)
        return jsonify({'ok': True, 'url': url, 'expires_in': PAGE_URL_TTL,
                        'pages': n['page_count'] if n else None, 'chapter': ch, 'page': pg})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api ebook page: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── Mac upload tool endpoints (X-News-Key) ─────────────────────────────────
def _news_key_ok():
    from pg_admin.routes.api_news_ingest import _ok
    return _ok()


def api_admin_upload_url():
    """POST /api/pg/ebooks/upload-url {key, content_type} (X-News-Key) → signed PUT link (ebooks/… keys only)."""
    if not _news_key_ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    from core import storage
    b = request.get_json(silent=True) or {}
    key = str(b.get('key') or '')
    if not re.fullmatch(r'ebooks/[a-z0-9_]+/[A-Za-z0-9_./-]+', key) or '..' in key:
        return jsonify({'ok': False, 'error': 'bad_key'}), 400
    have = storage.object_size(key)
    url = None if have else storage.presigned_put_url(key, str(b.get('content_type') or 'image/webp'), 3600)
    return jsonify({'ok': True, 'key': key, 'put_url': url, 'already': bool(have), 'size': have})


def api_admin_register():
    """POST /api/pg/ebooks/register {code, chapter_no, title, pdf_key, pages:[{page_no, key, width, height}]}
    (X-News-Key) — record one prepared chapter (re-running replaces its pages; summary / tags kept)."""
    if not _news_key_ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    b = request.get_json(silent=True) or {}
    code = str(b.get('code') or '').strip()
    try:
        ch = int(b.get('chapter_no'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad_chapter'}), 400
    pages = b.get('pages') or []
    conn = get_db()
    try:
        ensure(conn)
        if not _book(conn, code):
            return jsonify({'ok': False, 'error': 'unknown_ebook'}), 404
        # title / summary / tag from the tool only fill EMPTY fields — an admin edit is never overwritten
        conn.execute("INSERT INTO pg_ebook_chapters (ebook_code, chapter_no, title, page_count, pdf_key, summary, service_tag) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (ebook_code, chapter_no) DO UPDATE SET "
                     "title = CASE WHEN COALESCE(pg_ebook_chapters.title,'') = '' THEN EXCLUDED.title ELSE pg_ebook_chapters.title END, "
                     "summary = CASE WHEN COALESCE(pg_ebook_chapters.summary,'') = '' THEN EXCLUDED.summary ELSE pg_ebook_chapters.summary END, "
                     "service_tag = CASE WHEN COALESCE(pg_ebook_chapters.service_tag,'') = '' THEN EXCLUDED.service_tag ELSE pg_ebook_chapters.service_tag END, "
                     "page_count = EXCLUDED.page_count, pdf_key = EXCLUDED.pdf_key, updated_at = CURRENT_TIMESTAMP",
                     (code, ch, str(b.get('title') or '')[:200], len(pages), str(b.get('pdf_key') or '')[:300],
                      str(b.get('summary') or '')[:1200], str(b.get('service_tag') or '')[:200]))
        conn.execute("DELETE FROM pg_ebook_pages WHERE ebook_code = ? AND chapter_no = ?", (code, ch))
        for p in pages:
            conn.execute("INSERT INTO pg_ebook_pages (ebook_code, chapter_no, page_no, image_key, width, height) "
                         "VALUES (?, ?, ?, ?, ?, ?)", (code, ch, int(p['page_no']), str(p['key'])[:300],
                                                      int(p.get('width') or 0), int(p.get('height') or 0)))
        conn.commit()
        return jsonify({'ok': True, 'code': code, 'chapter_no': ch, 'pages': len(pages)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("api ebook register: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── admin page: goocampus.in Admin → E-books & Pathways ────────────────────
def _admin():
    from core.users import get_user
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def admin_page():
    from flask import render_template, redirect, url_for, flash
    a = _admin()
    if not a:
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    code = (request.args.get('book') or 'uae').strip()
    conn = get_db()
    try:
        ensure(conn)
        books = [dict(r) for r in conn.execute("SELECT * FROM pg_ebooks ORDER BY sort_order, id").fetchall()]
        for b in books:
            b['money'] = _money(b)
            b['chapters_n'] = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(page_count),0) AS p FROM pg_ebook_chapters "
                                           "WHERE ebook_code = ?", (b['code'],)).fetchone()
            b['buyers'] = conn.execute("SELECT COUNT(DISTINCT user_id) AS n FROM pg_ebook_access WHERE ebook_code = ? AND "
                                       "(expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)", (b['code'],)).fetchone()['n']
        chapters = [dict(r) for r in conn.execute("SELECT * FROM pg_ebook_chapters WHERE ebook_code = ? ORDER BY chapter_no",
                                                  (code,)).fetchall()]
        access = [dict(r) for r in conn.execute(
            "SELECT a.*, u.name, u.mobile, (SELECT MAX(updated_at) FROM pg_ebook_progress p WHERE p.user_id = a.user_id "
            "AND p.ebook_code = a.ebook_code) AS last_read, (SELECT COALESCE(SUM(max_page),0) FROM pg_ebook_progress p "
            "WHERE p.user_id = a.user_id AND p.ebook_code = a.ebook_code) AS pages_read "
            "FROM pg_ebook_access a LEFT JOIN pg_users u ON u.id = a.user_id ORDER BY a.id DESC LIMIT 300").fetchall()]
        orders = [dict(r) for r in conn.execute(
            "SELECT o.*, u.name FROM pg_ebook_orders o LEFT JOIN pg_users u ON u.id = o.user_id "
            "WHERE o.status = 'paid' ORDER BY o.id DESC LIMIT 200").fetchall()]
    finally:
        conn.close()
    conn = get_db()
    try:
        mode, pilots = gate_settings(conn)
    finally:
        conn.close()
    return render_template('pg_admin/ebooks.html', books=books, chapters=chapters, access=access, orders=orders,
                           book=code, intl_mode=mode, intl_pilots=pilots, active_section='goocampus_in')


def admin_save_book():
    from flask import redirect, url_for, flash
    a = _admin()
    if not a:
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    f = request.form
    code = (f.get('code') or '').strip()
    try:
        price = max(0.0, float(f.get('price') or 0))
        gst = max(0.0, float(f.get('gst_percent') or GST_DEFAULT))
        days = max(1, int(f.get('validity_days') or VALIDITY_DAYS))
    except ValueError:
        flash('Price / GST / days must be numbers.', 'error'); return redirect(url_for('pg_ebooks_admin', book=code))
    conn = get_db()
    try:
        ensure(conn)
        conn.execute("UPDATE pg_ebooks SET title = ?, subtitle = ?, blurb = ?, price = ?, gst_percent = ?, "
                     "validity_days = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE code = ?",
                     ((f.get('title') or '').strip()[:200], (f.get('subtitle') or '').strip()[:300],
                      (f.get('blurb') or '').strip()[:2000], price, gst, days, f.get('is_active') == '1', code))
        conn.commit()
        flash('Saved.', 'success')
    finally:
        conn.close()
    return redirect(url_for('pg_ebooks_admin', book=code))


def admin_save_chapter():
    from flask import redirect, url_for, flash
    a = _admin()
    if not a:
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    f = request.form
    code = (f.get('code') or '').strip()
    conn = get_db()
    try:
        ensure(conn)
        conn.execute("UPDATE pg_ebook_chapters SET title = ?, summary = ?, service_tag = ?, is_step = ?, "
                     "updated_at = CURRENT_TIMESTAMP WHERE ebook_code = ? AND chapter_no = ?",
                     ((f.get('title') or '').strip()[:200], (f.get('summary') or '').strip()[:1200],
                      (f.get('service_tag') or '').strip()[:200], f.get('is_step') == '1', code,
                      int(f.get('chapter_no') or 0)))
        conn.commit()
        flash('Chapter saved.', 'success')
    finally:
        conn.close()
    return redirect(url_for('pg_ebooks_admin', book=code) + '#ch' + str(f.get('chapter_no') or ''))


def admin_save_gate():
    from flask import redirect, url_for, flash
    a = _admin()
    if not a:
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    mode = request.form.get('mode') if request.form.get('mode') in MODES else 'pilot'
    pilots = [re.sub(r'\D', '', m)[-10:] for m in re.split(r'[\s,;]+', request.form.get('pilots') or '') if m]
    pilots = [m for m in pilots if len(m) == 10]
    conn = get_db()
    try:
        _set_kv(conn, 'intl_mode', mode, a.get('name') or 'admin')
        _set_kv(conn, 'intl_pilot', ','.join(dict.fromkeys(pilots)), a.get('name') or 'admin')
        conn.commit()
        flash({'pilot': f'International dashboard: only {len(pilots)} pilot number(s) see it.',
               'all': 'International dashboard: open to EVERY doctor.',
               'off': 'International dashboard: hidden from everyone.'}[mode], 'success')
    finally:
        conn.close()
    return redirect(url_for('pg_ebooks_admin'))


def admin_grant():
    """Admin gives (or extends) a doctor's access by mobile — e.g. a bank-transfer buyer."""
    from flask import redirect, url_for, flash
    a = _admin()
    if not a:
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    code = (request.form.get('code') or '').strip()
    m10 = re.sub(r'\D', '', request.form.get('mobile') or '')[-10:]
    conn = get_db()
    try:
        ensure(conn)
        book = _book(conn, code)
        u = conn.execute("SELECT id, name FROM pg_users WHERE RIGHT(regexp_replace(COALESCE(mobile,''),'[^0-9]','','g'),10) = ? "
                         "ORDER BY id LIMIT 1", (m10,)).fetchone() if len(m10) == 10 else None
        if not book or not u:
            flash('No goocampus.in account with that mobile.', 'error')
        else:
            grant(conn, u['id'], book, 'admin', None, a.get('name') or 'admin')
            conn.commit()
            flash(f"Access given to {u['name'] or m10} for {book['title']} ({book['validity_days']} days).", 'success')
    finally:
        conn.close()
    return redirect(url_for('pg_ebooks_admin', book=code))


def admin_preview():
    """GET /admin/pg/ebooks/preview?code=uae&chapter=1&page=1 — admin sees a page exactly as a doctor would
    (watermarked with the admin's own name), to check the reader output. Not cached, not logged."""
    from flask import Response, abort
    from core import storage
    a = _admin()
    if not a:
        abort(403)
    code = (request.args.get('code') or 'uae').strip()
    try:
        ch, pg = int(request.args.get('chapter') or 1), int(request.args.get('page') or 1)
    except ValueError:
        abort(400)
    conn = get_db()
    try:
        ensure(conn)
        row = conn.execute("SELECT image_key FROM pg_ebook_pages WHERE ebook_code = ? AND chapter_no = ? AND page_no = ?",
                           (code, ch, pg)).fetchone()
    finally:
        conn.close()
    if not row:
        abort(404)
    src = storage.download_bytes(row['image_key'])
    if not src:
        abort(503)
    mob = re.sub(r'\D', '', str(a.get('mobile') or a.get('phone') or ''))
    img = _watermark(src, _wm_name({'name': a.get('name')}), ('Mob xx' + mob[-4:]) if mob else 'Admin preview')
    return Response(img, mimetype='image/webp', headers={'Cache-Control': 'no-store'})


def register(app):
    from core.auth import login_required
    app.add_url_rule('/api/pg/ebooks', 'api_pg_ebooks', api_list, methods=['GET'])
    app.add_url_rule('/api/pg/ebooks/create-order', 'api_pg_ebooks_order', api_create_order, methods=['POST'])
    app.add_url_rule('/api/pg/ebooks/verify', 'api_pg_ebooks_verify', api_verify, methods=['POST'])
    app.add_url_rule('/api/pg/ebooks/page', 'api_pg_ebooks_page', api_page, methods=['GET'])
    app.add_url_rule('/api/pg/ebooks/upload-url', 'api_pg_ebooks_upload_url', api_admin_upload_url, methods=['POST'])
    app.add_url_rule('/api/pg/ebooks/register', 'api_pg_ebooks_register', api_admin_register, methods=['POST'])
    app.add_url_rule('/admin/pg/ebooks', 'pg_ebooks_admin', login_required(admin_page), methods=['GET'])
    app.add_url_rule('/admin/pg/ebooks/book', 'pg_ebooks_save_book', login_required(admin_save_book), methods=['POST'])
    app.add_url_rule('/admin/pg/ebooks/chapter', 'pg_ebooks_save_chapter', login_required(admin_save_chapter),
                     methods=['POST'])
    app.add_url_rule('/admin/pg/ebooks/grant', 'pg_ebooks_grant', login_required(admin_grant), methods=['POST'])
    app.add_url_rule('/admin/pg/ebooks/gate', 'pg_ebooks_gate', login_required(admin_save_gate), methods=['POST'])
    app.add_url_rule('/admin/pg/ebooks/preview', 'pg_ebooks_preview', login_required(admin_preview), methods=['GET'])
