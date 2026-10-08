"""News Inbox ingest — the founder's Mac pushes counselling notices + AI drafts here
(founder 2026-10-08). The Mac fetches (Indian IP; the sites block our server) and a Claude
Code scheduled task drafts each new notice; the portal only stores + shows them for review.

Auth: header X-News-Key must equal env NEWS_INGEST_KEY (separate from PG_API_KEY).
  GET  /api/pg/news-inbox/known?source=<code>  → item_keys already held (dedupe on the Mac)
  POST /api/pg/news-inbox/ingest               → one notice (+ optional draft + PDF)
"""
import os
import hmac
import json
import base64
import logging
from datetime import date
from flask import request, jsonify
from db import get_db
from pg_admin import news_scraper as NS

CATEGORIES = ('registration', 'choice_filling', 'seat_allotment', 'fee_payment', 'reporting',
              'notification', 'other')
DATE_FIELDS = ('registration_start', 'registration_end', 'choice_filling_start', 'choice_filling_end',
               'payment_last_date', 'reporting_last_date', 'result_date')
MAX_PDF = 25 * 1024 * 1024


def _ok():
    want = (os.environ.get('NEWS_INGEST_KEY') or '').strip()
    got = (request.headers.get('X-News-Key') or '').strip()
    return bool(want) and hmac.compare_digest(want, got)


def _d(v):
    """'YYYY-MM-DD' → date, else None."""
    try:
        y, m, d = str(v or '').strip()[:10].split('-')
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def _clean_draft(dr):
    """Whitelist + trim the AI draft so nothing odd is stored. Returns dict or None."""
    if not isinstance(dr, dict):
        return None
    out = {
        'headline': str(dr.get('headline') or '').strip()[:160],
        'summary': str(dr.get('summary') or '').strip()[:300],
        'article': str(dr.get('article') or '').strip()[:6000],
        'category': (dr.get('category') if dr.get('category') in CATEGORIES else 'other'),
        'applies_to': str(dr.get('applies_to') or '').strip()[:300],
        'action': str(dr.get('action') or '').strip()[:300],
        'dates': {},
    }
    for k in DATE_FIELDS:
        v = (dr.get('dates') or {}).get(k)
        if isinstance(v, dict) and _d(v.get('date')):
            out['dates'][k] = {'date': _d(v.get('date')).isoformat(),
                               'time': str(v.get('time') or '').strip()[:20],
                               'quote': str(v.get('quote') or '').strip()[:400]}
    if not out['headline'] and not out['article']:
        return None
    return out


def api_news_inbox_known():
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    code = (request.args.get('source') or '').strip()
    conn = get_db()
    try:
        NS.ensure_news_inbox_tables(conn)
        rows = conn.execute("SELECT item_key, (draft_json IS NOT NULL) AS drafted FROM pg_news_inbox "
                            "WHERE source_code = ?", (code,)).fetchall()
        return jsonify({'ok': True, 'source': code, 'known': [r['item_key'] for r in rows],
                        'drafted': [r['item_key'] for r in rows if r['drafted']]})
    finally:
        conn.close()


def api_news_inbox_ingest():
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    b = request.get_json(silent=True) or {}
    code = (b.get('source_code') or '').strip()
    key = (b.get('item_key') or '').strip()
    if code not in NS.SOURCES or not key:
        return jsonify({'ok': False, 'error': 'unknown source or missing item_key'}), 400
    src = NS.SOURCES[code]
    title = str(b.get('title') or '').strip()[:500]
    url = str(b.get('url') or '').strip()[:1000]
    kind = 'pdf' if b.get('kind') == 'pdf' else 'link'
    nd = _d(b.get('notice_date'))
    status = 'seen' if b.get('status') == 'seen' else 'new'      # 'seen' = baseline, never drafted
    draft = _clean_draft(b.get('draft'))
    pdf = None
    if b.get('pdf_b64'):
        try:
            pdf = base64.b64decode(b['pdf_b64'])
            if len(pdf) > MAX_PDF or not pdf.startswith(b'%PDF'):
                pdf = None
        except Exception:
            pdf = None
    pdf_name = str(b.get('pdf_name') or '').strip()[:200]
    conn = get_db()
    try:
        NS.ensure_news_inbox_tables(conn)
        row = conn.execute("SELECT id, status, draft_json FROM pg_news_inbox WHERE source_code = ? AND item_key = ?",
                           (code, key)).fetchone()
        if row:
            # Known notice — only fill in what's missing (a draft / PDF from a later run).
            sets, vals = [], []
            if draft and not row['draft_json']:
                sets += ["draft_json = ?", "drafted_at = CURRENT_TIMESTAMP"]; vals.append(json.dumps(draft))
            if pdf:
                sets += ["pdf_data = COALESCE(pdf_data, ?)", "pdf_name = COALESCE(NULLIF(pdf_name,''), ?)"]
                vals += [pdf, pdf_name]
            if sets:
                conn.execute(f"UPDATE pg_news_inbox SET {', '.join(sets)} WHERE id = ?", vals + [row['id']])
                conn.commit()
            return jsonify({'ok': True, 'id': row['id'], 'result': 'updated' if sets else 'known'})
        it = {'item_key': key, 'title': title, 'url': url, 'kind': kind, 'notice_date': nd}
        if status == 'new' and NS.is_repeat(conn, code, it):
            status = 'seen'                                       # site re-posted an earlier notice
        new_id = conn.execute(
            "INSERT INTO pg_news_inbox (source_code, authority_code, item_key, title, raw_title, url, kind, "
            "notice_date, status, draft_json, drafted_at, pdf_data, pdf_name) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
            (code, src['authority_code'], key, title, str(b.get('raw_title') or title)[:800], url, kind, nd,
             status, json.dumps(draft) if draft else None, None, pdf, pdf_name)).fetchone()['id']
        if draft:
            conn.execute("UPDATE pg_news_inbox SET drafted_at = CURRENT_TIMESTAMP WHERE id = ?", (new_id,))
        conn.commit()
        return jsonify({'ok': True, 'id': new_id, 'result': status})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news ingest: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_news_inbox_heartbeat():
    """The Mac reports each run (even when nothing is new) so the inbox shows it's alive."""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    b = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        NS.ensure_news_inbox_tables(conn)
        for r in (b.get('sources') or []):
            code = r.get('source')
            if code not in NS.SOURCES:
                continue
            conn.execute("INSERT INTO pg_news_scrape_runs (source_code, ok, found, new_count, error, trigger) "
                         "VALUES (?,?,?,?,?,?)",
                         (code, bool(r.get('ok')), int(r.get('found') or 0), int(r.get('new') or 0),
                          str(r.get('error') or '')[:400], 'mac'))
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news heartbeat: %s", e)
        return jsonify({'ok': False}), 500
    finally:
        conn.close()
