"""Season archive of EVERY official PDF we fetch (founder 2026-10-22: authorities remove or archive their
notices, merit lists, results, annexures after counselling — every file of the season must stay in OUR
control, organised, and reachable "in our folder").

Three guarantees:
1. Library complete — every fetched PDF is filed in its authority's Documents. Files that aren't a
   publishable "document" (dismissed notices, page snapshots, notices without a category) are filed as
   hidden `archive_only` items: kept, never shown to doctors, not in the "waiting to publish" list.
2. Backup outside the database — every document's file is also copied to R2 storage under
   archive/<season>/<authority>/<category>/<date>_<title>_<id>.pdf (survives a database problem).
3. One place to find it all — /admin/pg/archive lists every file by season → authority → category with
   a ZIP download (see routes/archive_admin.py).
"""
import logging
import re
import threading
from datetime import date, datetime

SEASON_START_MONTH = 7          # NEET-PG counselling season runs Jul → Jun ('2026-27')
_sync_lock = threading.Lock()
_READY = False


def ensure_cols(conn):
    global _READY
    if _READY:
        return
    for c, t in (('archive_only', 'BOOLEAN DEFAULT FALSE'), ('season', "TEXT DEFAULT ''"),
                 ('backup_r2_key', "TEXT DEFAULT ''"), ('backed_up_at', 'TIMESTAMP'), ('file_size', 'BIGINT')):
        conn.execute(f"ALTER TABLE pg_authority_docs ADD COLUMN IF NOT EXISTS {c} {t}")
    conn.commit()
    _READY = True


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or '').strip()
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y'):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def season_of(d):
    """Counselling season label for a date: Jul 2026 – Jun 2027 → '2026-27'."""
    d = _as_date(d) or date.today()
    y = d.year if d.month >= SEASON_START_MONTH else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def doc_season(row):
    return season_of(_as_date(row.get('doc_date')) or _as_date(row.get('uploaded_at')))


def _safe(s, n=70):
    return re.sub(r'[^A-Za-z0-9._ -]+', '', (s or '').replace('/', '-')).strip().replace(' ', '_')[:n] or 'document'


def backup_key(row):
    d = _as_date(row.get('doc_date')) or _as_date(row.get('uploaded_at'))
    ext = (row.get('file_name') or '').rsplit('.', 1)[-1].lower() if '.' in (row.get('file_name') or '') else 'pdf'
    ext = ext if re.fullmatch(r'[a-z0-9]{2,5}', ext) else 'pdf'
    return (f"archive/{doc_season(row)}/{_safe(row.get('authority_code') or 'other', 20)}/"
            f"{_safe(row.get('category') or 'other', 30)}/"
            f"{d.isoformat() if d else 'undated'}_{_safe(row.get('title'))}_{row['id']}.{ext}")


def backup_doc(conn, doc_id):
    """Copy one document's file to archive/… in R2 (idempotent). Returns the key or ''."""
    from core import storage
    if not storage.is_configured():
        return ''
    ensure_cols(conn)
    from pg_admin.data.big_files import ensure_cols as bf_cols
    bf_cols(conn)
    r = conn.execute("SELECT id, authority_code, category, title, doc_date, uploaded_at, file_name, file_data, "
                     "file_content_type, file_r2_key, backup_r2_key FROM pg_authority_docs WHERE id = ?",
                     (doc_id,)).fetchone()
    if not r:
        return ''
    r = dict(r)
    if r.get('backup_r2_key'):
        return r['backup_r2_key']
    key = backup_key(r)
    ok, size = False, None
    if r.get('file_data'):
        data = bytes(r['file_data'])
        size = len(data)
        ok = storage.upload_bytes(key, data, r.get('file_content_type') or 'application/pdf')
    elif r.get('file_r2_key'):
        try:
            storage.get_client().copy_object(Bucket=storage.get_bucket_name(), Key=key,
                                             CopySource={'Bucket': storage.get_bucket_name(), 'Key': r['file_r2_key']})
            size = storage.object_size(key)
            ok = bool(size)
        except Exception as e:
            logging.warning("archive copy %s: %s", doc_id, e)
    if not ok:
        return ''
    conn.execute("UPDATE pg_authority_docs SET backup_r2_key = ?, backed_up_at = CURRENT_TIMESTAMP, season = ?, "
                 "file_size = COALESCE(file_size, ?) WHERE id = ?", (key, doc_season(r), size, doc_id))
    conn.commit()
    return key


def sync_backups(limit=None):
    """Back up every document that has a file but no backup yet. Safe to call often (one at a time)."""
    from db import get_db
    if not _sync_lock.acquire(blocking=False):
        return 0
    n = 0
    conn = get_db()
    try:
        ensure_cols(conn)
        from pg_admin.data.big_files import ensure_cols as bf_cols
        bf_cols(conn)
        ids = [r['id'] for r in conn.execute(
            "SELECT id FROM pg_authority_docs WHERE COALESCE(backup_r2_key,'') = '' AND "
            "(file_data IS NOT NULL OR COALESCE(file_r2_key,'') <> '') ORDER BY id").fetchall()]
        for i in ids[:limit] if limit else ids:
            try:
                if backup_doc(conn, i):
                    n += 1
            except Exception as e:
                logging.warning("archive backup %s: %s", i, e)
                try: conn.rollback()
                except Exception: pass
    finally:
        conn.close()
        _sync_lock.release()
    return n


def kick_sync():
    """Background backup sweep (never blocks a request)."""
    threading.Thread(target=sync_backups, daemon=True).start()


def archive_inbox_pdf(conn, inbox_id, title=None):
    """File an inbox notice's PDF as a hidden archive-only document of its authority, unless that exact
    file is already in the authority's Documents. Returns 'archived' | 'duplicate' | 'already' | 'skip'.
    Caller commits."""
    from pg_admin import news_scraper as NS
    from pg_admin.authorities import get_authority
    from pg_admin.data.big_files import ensure_cols as bf_cols
    ensure_cols(conn); bf_cols(conn)
    r = conn.execute("SELECT id, source_code, title, url, kind, notice_date, draft_json, pdf_data, pdf_name, "
                     "pdf_r2_key, pdf_sha256 FROM pg_news_inbox WHERE id = ?", (inbox_id,)).fetchone()
    if not r:
        return 'skip'
    r = dict(r)
    if not r.get('pdf_data') and not r.get('pdf_r2_key'):
        return 'skip'
    code = (NS.SOURCES.get(r['source_code']) or {}).get('authority_code')
    if not code:
        return 'skip'
    if conn.execute("SELECT 1 FROM pg_authority_docs WHERE auto_inbox_id = ? AND COALESCE(auto_kind,'pdf') NOT IN "
                    "('reg_list','snapshot') LIMIT 1", (inbox_id,)).fetchone():
        return 'already'
    from pg_admin.data.auto_docs import find_same_file, sha256
    if r.get('pdf_data'):
        if find_same_file(conn, code, r['pdf_data']):
            return 'duplicate'
        sha = sha256(r['pdf_data'])
    else:
        sha = r.get('pdf_sha256') or ''
        if conn.execute("SELECT 1 FROM pg_authority_docs WHERE authority_code = ? AND (file_r2_key = ? OR "
                        "(COALESCE(file_sha256,'') <> '' AND file_sha256 = ?)) LIMIT 1",
                        (code, r['pdf_r2_key'], sha)).fetchone():
            return 'duplicate'
    import json
    try:
        dj = json.loads(r.get('draft_json') or '{}') or {}
    except Exception:
        dj = {}
    from pg_admin.authorities import valid_category
    cat = ((dj.get('document') or {}).get('category') or '').strip()
    cat = cat if valid_category(cat) else 'other'
    t = (title or (dj.get('document') or {}).get('title') or dj.get('headline') or r['title'] or 'Notice')[:300]
    if r.get('kind') == 'link':
        t = ('Web page snapshot — ' + t)[:300]
    nd = r['notice_date'].isoformat() if r.get('notice_date') else ''
    conn.execute(
        "INSERT INTO pg_authority_docs (authority_code, authority_name, category, title, doc_date, note, file_name, "
        "file_data, file_content_type, is_published, uploaded_by, auto_inbox_id, file_sha256, source_url, "
        "review_pending, auto_kind, file_r2_key, archive_only, season, file_size) "
        "VALUES (?,?,?,?,?,?,?,?,?,FALSE,?,?,?,?,FALSE,'pdf',?,TRUE,?,?)",
        (code, (get_authority(code) or {}).get('name', ''), cat, t, nd, 'Archived automatically (kept, not published)',
         (r.get('pdf_name') or 'document.pdf')[:200], r.get('pdf_data'), 'application/pdf', 'Archive (auto)',
         inbox_id, sha or None, (r.get('url') or '')[:1000], r.get('pdf_r2_key') if not r.get('pdf_data') else None,
         season_of(r.get('notice_date')), len(r['pdf_data']) if r.get('pdf_data') else None))
    return 'archived'


def file_all_unfiled(conn):
    """Backfill: every inbox PDF not yet in Documents → archive-only document. Returns counts."""
    out = {'archived': 0, 'duplicate': 0, 'already': 0, 'skip': 0}
    from pg_admin.data.big_files import ensure_cols as bf_cols
    ensure_cols(conn); bf_cols(conn)
    ids = [x['id'] for x in conn.execute(
        "SELECT i.id FROM pg_news_inbox i WHERE i.status <> 'seen' AND (i.pdf_data IS NOT NULL OR "
        "COALESCE(i.pdf_r2_key,'') <> '') AND COALESCE(i.doc_rejected, FALSE) = FALSE AND NOT EXISTS ("
        "SELECT 1 FROM pg_authority_docs d WHERE d.auto_inbox_id = i.id AND COALESCE(d.auto_kind,'pdf') NOT IN "
        "('reg_list','snapshot')) "
        "ORDER BY i.id").fetchall()]
    for i in ids:
        try:
            res = archive_inbox_pdf(conn, i)
            out[res] = out.get(res, 0) + 1
            conn.commit()
        except Exception as e:
            logging.warning("archive file %s: %s", i, e)
            try: conn.rollback()
            except Exception: pass
            out['skip'] += 1
    return out


def archive_snapshot(conn, inbox_id, data, name=''):
    """A web-page notice (no PDF of its own) printed to PDF on the Mac → hidden archive-only document
    (auto_kind 'snapshot'), so the page's text survives after the authority edits or removes it.
    Never touches the inbox row's own PDF (a snapshot is not "the notice PDF" for news).
    Returns 'archived' | 'duplicate' | 'already' | 'skip'. Caller commits."""
    from pg_admin import news_scraper as NS
    from pg_admin.authorities import get_authority
    from pg_admin.data.big_files import ensure_cols as bf_cols
    from pg_admin.data.auto_docs import find_same_file, sha256
    ensure_cols(conn); bf_cols(conn)
    if not data or not bytes(data[:5]).startswith(b'%PDF'):
        return 'skip'
    r = conn.execute("SELECT id, source_code, title, url, notice_date, draft_json FROM pg_news_inbox WHERE id = ?",
                     (inbox_id,)).fetchone()
    if not r:
        return 'skip'
    code = (NS.SOURCES.get(r['source_code']) or {}).get('authority_code')
    if not code:
        return 'skip'
    if conn.execute("SELECT 1 FROM pg_authority_docs WHERE auto_inbox_id = ? AND auto_kind = 'snapshot' LIMIT 1",
                    (inbox_id,)).fetchone():
        return 'already'
    if find_same_file(conn, code, data):
        return 'duplicate'
    import json
    try:
        dj = json.loads(r['draft_json'] or '{}') or {}
    except Exception:
        dj = {}
    t = ('Web page snapshot — ' + (dj.get('headline') or r['title'] or 'Notice'))[:300]
    nd = r['notice_date'].isoformat() if r['notice_date'] else ''
    conn.execute(
        "INSERT INTO pg_authority_docs (authority_code, authority_name, category, title, doc_date, note, file_name, "
        "file_data, file_content_type, is_published, uploaded_by, auto_inbox_id, file_sha256, source_url, "
        "review_pending, auto_kind, archive_only, season, file_size) "
        "VALUES (?,?,'other',?,?,?,?,?,'application/pdf',FALSE,'Archive (auto)',?,?,?,FALSE,'snapshot',TRUE,?,?)",
        (code, (get_authority(code) or {}).get('name', ''), t, nd,
         'Snapshot of the official web page, saved automatically (kept, not published)',
         (name or 'web-page.pdf')[:200], bytes(data), inbox_id, sha256(data), (r['url'] or '')[:1000],
         season_of(r['notice_date']), len(data)))
    return 'archived'
