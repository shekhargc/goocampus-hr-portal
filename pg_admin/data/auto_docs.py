"""Auto-file official PDFs into the authority Documents section (founder 2026-10-13).

Every notice PDF the Mac fetcher brings in carries an AI classification in its draft:
  "document": {"category": <DOC_CATEGORIES code | "none">, "title": "...", "news": true|false}
The PDF is filed under that authority + category, HIDDEN and marked "waiting" until the team
publishes it on the Authority Documents page. A file that is already there (same content —
also manual uploads) is never added twice; existing documents are only read, never changed.
Notices with news=false (merit lists, results, seat matrices…) leave the News Inbox's New tab
and go to its "Documents only" tab instead.
"""
import hashlib
import logging

from pg_admin.authorities import get_authority, valid_category


def sha256(data):
    return hashlib.sha256(bytes(data)).hexdigest() if data else ''


def find_same_file(conn, authority_code, data):
    """id of a document of this authority with exactly this file content, else None (read-only)."""
    h, n = sha256(data), len(data or b'')
    r = conn.execute("SELECT id FROM pg_authority_docs WHERE authority_code = ? AND file_sha256 = ? LIMIT 1",
                     (authority_code, h)).fetchone()
    if r:
        return r['id']
    for r in conn.execute("SELECT id, file_data FROM pg_authority_docs WHERE authority_code = ? "
                          "AND file_sha256 IS NULL AND file_data IS NOT NULL AND octet_length(file_data) = ?",
                          (authority_code, n)).fetchall():
        if sha256(r['file_data']) == h:
            return r['id']
    return None


def ensure_cols(conn):
    conn.execute("ALTER TABLE pg_news_inbox ADD COLUMN IF NOT EXISTS doc_rejected BOOLEAN DEFAULT FALSE")


def file_from_inbox(conn, inbox_id):
    """File one inbox notice's PDF; anything the rules below don't file as a publishable document (no
    category, not news, dismissed, a web-page snapshot) is kept as a hidden ARCHIVE-ONLY document so the
    season's library is complete (founder 2026-10-22). A document the team removed is never re-filed.
    Returns 'filed' | 'archived' | 'duplicate' | 'already' | 'dismissed' | 'skip'. Caller commits."""
    res = _file_from_inbox_core(conn, inbox_id)
    if res in ('skip', 'dismissed'):
        try:
            rej = conn.execute("SELECT COALESCE(doc_rejected, FALSE) AS r FROM pg_news_inbox WHERE id = ?",
                               (inbox_id,)).fetchone()
            if rej and not rej['r']:
                from pg_admin.data.archive import archive_inbox_pdf
                if archive_inbox_pdf(conn, inbox_id) == 'archived':
                    res = 'archived' if res == 'skip' else 'dismissed+archived'
        except Exception as e:
            logging.warning("archive inbox %s: %s", inbox_id, e)
    return res


def _file_from_inbox_core(conn, inbox_id):
    """File one inbox notice's PDF. Returns 'filed' | 'duplicate' | 'already' | 'skip'. Caller commits."""
    import json
    from pg_admin import news_scraper as NS
    from pg_admin.data.authority_docs_tables import ensure_pg_authority_docs
    ensure_pg_authority_docs(conn)
    ensure_cols(conn)
    from pg_admin.data.big_files import ensure_cols as _bf_cols
    _bf_cols(conn)
    r = conn.execute("SELECT id, source_code, status, title, url, notice_date, draft_json, pdf_data, pdf_name, "
                     "pdf_r2_key, pdf_sha256, pdf_doc_id, "
                     "COALESCE(doc_rejected, FALSE) AS doc_rejected FROM pg_news_inbox WHERE id = ?",
                     (inbox_id,)).fetchone()
    if not r or not r['draft_json'] or r['doc_rejected']:
        return 'skip'
    r2_key = r.get('pdf_r2_key') or ''            # big PDF archived in R2 instead of the database (2026-10-17)
    if not r['pdf_data'] and not r2_key and not r.get('pdf_doc_id'):   # no PDF (a link) — only typed lists
        try:
            file_reg_lists(conn, r, json.loads(r['draft_json']) or {})
        except Exception:
            pass
        return 'skip'
    try:
        dj = json.loads(r['draft_json']) or {}
        doc = dj.get('document') or {}
    except Exception:
        return 'skip'
    file_reg_lists(conn, r, dj)
    cat = (doc.get('category') or '').strip()
    code = (NS.SOURCES.get(r['source_code']) or {}).get('authority_code')
    not_pg = (dj.get('summary') or '').strip().lower().startswith('not a pg medical')
    if (doc.get('news') is False or not_pg) and not valid_category(cat) and r['status'] == 'new':
        # not news AND nothing to file (a duplicate / superseded / non-PG notice) → set aside so it
        # never sits in New looking postable (founder 2026-10-14: duplicates got published)
        conn.execute("UPDATE pg_news_inbox SET status = 'dismissed', reviewed_by = 'AI (auto)', "
                     "reviewed_at = CURRENT_TIMESTAMP, history_note = ? WHERE id = ?",
                     ((dj.get('summary') or 'Duplicate / superseded — set aside automatically')[:300], inbox_id))
        return 'dismissed'
    if not code or not valid_category(cat):
        return 'skip'
    news_only_doc = doc.get('news') is False
    prev = conn.execute("SELECT id, COALESCE(to_jsonb(pg_authority_docs)->>'archive_only','false') AS ao "
                        "FROM pg_authority_docs WHERE auto_inbox_id = ? AND COALESCE(auto_kind,'') NOT IN "
                        "('reg_list','snapshot') ORDER BY id LIMIT 1", (inbox_id,)).fetchone()
    if prev and prev['ao'] == 'true':
        # kept earlier as archive-only (no category then) — the re-read found its category: move it
        # into the library, waiting to publish (same stored file, no second copy) (2026-10-22)
        title = (str(doc.get('title') or '').strip() or r['title'] or 'Document')[:300]
        conn.execute("UPDATE pg_authority_docs SET archive_only = FALSE, category = ?, title = ?, note = '', "
                     "review_pending = TRUE, uploaded_by = 'AI (auto)', backup_r2_key = '' WHERE id = ?",
                     (cat, title, prev['id']))
        res = 'filed'
    elif prev:
        res = 'already'
    elif r['pdf_data'] and find_same_file(conn, code, r['pdf_data']):
        res = 'duplicate'
    elif not r['pdf_data'] and not r2_key and r.get('pdf_doc_id'):
        res = 'duplicate'                       # its one copy already lives in Documents (the pointer)
    elif not r['pdf_data'] and conn.execute(
            "SELECT 1 FROM pg_authority_docs WHERE authority_code = ? AND (file_r2_key = ? OR "
            "(file_sha256 = ? AND COALESCE(file_sha256,'') <> '')) LIMIT 1",
            (code, r2_key, r.get('pdf_sha256') or '')).fetchone():
        res = 'duplicate'
    else:
        title = (str(doc.get('title') or '').strip() or r['title'] or 'Document')[:300]
        conn.execute(
            "INSERT INTO pg_authority_docs (authority_code, authority_name, category, title, doc_date, note, "
            "file_name, file_data, file_content_type, is_published, uploaded_by, auto_inbox_id, file_sha256, "
            "source_url, review_pending, auto_kind, file_r2_key) VALUES (?,?,?,?,?,?,?,?,?,FALSE,?,?,?,?,TRUE,'pdf',?)",
            (code, (get_authority(code) or {}).get('name', ''), cat, title,
             r['notice_date'].isoformat() if r['notice_date'] else '', '',
             (r['pdf_name'] or 'document.pdf')[:200], r['pdf_data'], 'application/pdf', 'AI (auto)',
             inbox_id, sha256(r['pdf_data']) if r['pdf_data'] else (r.get('pdf_sha256') or None),
             (r['url'] or '')[:1000], (r2_key or None) if not r['pdf_data'] else None))
        res = 'filed'
    if news_only_doc and r['status'] == 'new':
        conn.execute("UPDATE pg_news_inbox SET status = 'document' WHERE id = ?", (inbox_id,))
    return res


def file_reg_lists(conn, r, dj):
    """'Documents required for registration' lists the AI read out of a bulletin / checklist →
    typed list entries (no file) under Registration Documents, hidden + waiting. One per list title."""
    from pg_admin import news_scraper as NS
    code = (NS.SOURCES.get(r['source_code']) or {}).get('authority_code')
    if not code:
        return 0
    n = 0
    auth = (get_authority(code) or {}).get('name', code)
    for g in (dj.get('registration_documents') or []):
        items = [str(x).strip() for x in (g.get('items') or []) if str(x).strip()]
        if not items:
            continue
        title = (str(g.get('title') or '').strip() or f'{auth} — Documents required for registration')[:300]
        if conn.execute("SELECT 1 FROM pg_authority_docs WHERE auto_inbox_id = ? AND auto_kind = 'reg_list' "
                        "AND title = ? LIMIT 1", (r['id'], title)).fetchone():
            continue
        body = '\n'.join(f'{i}. {x}' for i, x in enumerate(items, 1))
        conn.execute(
            "INSERT INTO pg_authority_docs (authority_code, authority_name, category, title, doc_date, note, body_text, "
            "file_name, is_published, uploaded_by, auto_inbox_id, source_url, review_pending, auto_kind) "
            "VALUES (?,?,'registration',?,?,?,?,'',FALSE,'AI (auto)',?,?,TRUE,'reg_list')",
            (code, auth, title, r['notice_date'].isoformat() if r['notice_date'] else '',
             'Read from the official notice — check against the PDF before publishing.', body,
             r['id'], (r['url'] or '')[:1000]))
        n += 1
    return n


def doc_for_inbox(conn, inbox_id):
    """The authority document holding this inbox notice's PDF: its auto-filed document, else the
    document the inbox points to (pdf_doc_id). None when not filed. Read-only."""
    try:
        r = conn.execute("SELECT id FROM pg_authority_docs WHERE auto_inbox_id = ? AND COALESCE(auto_kind,'pdf') = 'pdf' "
                         "AND (file_data IS NOT NULL OR COALESCE(to_jsonb(pg_authority_docs)->>'file_r2_key','') <> '') "
                         "ORDER BY id LIMIT 1", (inbox_id,)).fetchone()
        if r:
            return r['id']
        p = conn.execute("SELECT to_jsonb(pg_news_inbox)->>'pdf_doc_id' AS d FROM pg_news_inbox WHERE id = ?",
                         (inbox_id,)).fetchone()
        return int(p['d']) if p and p['d'] else None
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return None


def release_inbox_copy(conn, inbox_id):
    """Store each PDF ONCE (founder 2026-10-22): once the notice's PDF is safely in the authority's
    Documents with byte-for-byte the same file, the inbox keeps a pointer (pdf_doc_id) instead of its
    own copy. Only called for a PDF that just arrived — older inbox copies wait for the approved
    clean-up. Never clears anything unless the document's copy is verified identical. Caller commits."""
    from pg_admin import news_scraper as NS
    from pg_admin.data.big_files import ensure_cols as _bf_cols
    _bf_cols(conn)
    r = conn.execute("SELECT id, source_code, pdf_data, pdf_r2_key FROM pg_news_inbox WHERE id = ?",
                     (inbox_id,)).fetchone()
    if not r or not r['pdf_data']:
        return False                  # nothing held in the database (an R2 file is already shared by key)
    code = (NS.SOURCES.get(r['source_code']) or {}).get('authority_code')
    h, n = sha256(r['pdf_data']), len(r['pdf_data'])
    doc_id = None
    a = doc_for_inbox(conn, inbox_id)
    for cand in ([a] if a else []) + ([find_same_file(conn, code, r['pdf_data'])] if code else []):
        if not cand:
            continue
        d = conn.execute("SELECT file_data FROM pg_authority_docs WHERE id = ?", (cand,)).fetchone()
        if d and d['file_data'] and len(d['file_data']) == n and sha256(d['file_data']) == h:
            doc_id = cand
            break
    if not doc_id:
        return False
    conn.execute("UPDATE pg_news_inbox SET pdf_doc_id = ?, pdf_sha256 = ?, pdf_size = ?, pdf_data = NULL "
                 "WHERE id = ? AND pdf_data IS NOT NULL", (doc_id, h, n, inbox_id))
    return True


def file_safely(conn, inbox_id, release=False):
    try:
        res = file_from_inbox(conn, inbox_id)
        conn.commit()
        if release and res in ('filed', 'archived', 'dismissed+archived', 'duplicate', 'already'):
            try:
                if release_inbox_copy(conn, inbox_id):
                    conn.commit()
            except Exception as e:
                logging.warning("release inbox copy %s: %s", inbox_id, e)
                try: conn.rollback()
                except Exception: pass
        if res in ('filed', 'archived', 'dismissed+archived'):
            from pg_admin.data.archive import kick_sync
            kick_sync()                        # backup copy to R2 archive/… in the background
        return res
    except Exception as e:
        logging.warning("auto-file inbox %s: %s", inbox_id, e)
        try: conn.rollback()
        except Exception: pass
        return 'error'
