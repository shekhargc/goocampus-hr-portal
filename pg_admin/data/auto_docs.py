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
    """File one inbox notice's PDF. Returns 'filed' | 'duplicate' | 'already' | 'skip'. Caller commits."""
    import json
    from pg_admin import news_scraper as NS
    from pg_admin.data.authority_docs_tables import ensure_pg_authority_docs
    ensure_pg_authority_docs(conn)
    ensure_cols(conn)
    r = conn.execute("SELECT id, source_code, status, title, url, notice_date, draft_json, pdf_data, pdf_name, "
                     "COALESCE(doc_rejected, FALSE) AS doc_rejected FROM pg_news_inbox WHERE id = ?",
                     (inbox_id,)).fetchone()
    if not r or not r['draft_json'] or r['doc_rejected']:
        return 'skip'
    if not r['pdf_data']:                       # no PDF (a link) — only typed lists can be filed
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
    if conn.execute("SELECT 1 FROM pg_authority_docs WHERE auto_inbox_id = ? AND COALESCE(auto_kind,'') <> 'reg_list' "
                    "LIMIT 1", (inbox_id,)).fetchone():
        res = 'already'
    elif find_same_file(conn, code, r['pdf_data']):
        res = 'duplicate'
    else:
        title = (str(doc.get('title') or '').strip() or r['title'] or 'Document')[:300]
        conn.execute(
            "INSERT INTO pg_authority_docs (authority_code, authority_name, category, title, doc_date, note, "
            "file_name, file_data, file_content_type, is_published, uploaded_by, auto_inbox_id, file_sha256, "
            "source_url, review_pending, auto_kind) VALUES (?,?,?,?,?,?,?,?,?,FALSE,?,?,?,?,TRUE,'pdf')",
            (code, (get_authority(code) or {}).get('name', ''), cat, title,
             r['notice_date'].isoformat() if r['notice_date'] else '', '',
             (r['pdf_name'] or 'document.pdf')[:200], r['pdf_data'], 'application/pdf', 'AI (auto)',
             inbox_id, sha256(r['pdf_data']), (r['url'] or '')[:1000]))
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


def file_safely(conn, inbox_id):
    try:
        res = file_from_inbox(conn, inbox_id)
        conn.commit()
        return res
    except Exception as e:
        logging.warning("auto-file inbox %s: %s", inbox_id, e)
        try: conn.rollback()
        except Exception: pass
        return 'error'
