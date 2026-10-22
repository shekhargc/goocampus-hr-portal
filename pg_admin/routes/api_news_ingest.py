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

CATEGORIES = ('registration', 'verification', 'bulletin', 'choice_filling', 'seat_allotment', 'fee_payment', 'reporting',
              'notification', 'other')
DATE_FIELDS = ('registration_start', 'registration_end', 'verification_start', 'verification_end',
               'choice_filling_start', 'choice_filling_end', 'payment_last_date', 'reporting_last_date',
               'result_date')
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
            from pg_admin.data.calendar import norm_round
            out['dates'][k] = {'date': _d(v.get('date')).isoformat(),
                               'time': str(v.get('time') or '').strip()[:40],
                               'round': norm_round(v.get('round')) or None,
                               'quote': str(v.get('quote') or '').strip()[:400]}
    sch = dr.get('schedule')
    if isinstance(sch, dict) and isinstance(sch.get('rows'), list):
        cols = [str(c).strip()[:60] for c in (sch.get('columns') or [])][:8]
        rows = [[str(c).strip()[:160] for c in r][:8] for r in sch['rows'] if isinstance(r, list)][:40]
        if rows:
            out['schedule'] = {'title': str(sch.get('title') or '').strip()[:120], 'columns': cols, 'rows': rows}
    from pg_admin.data.calendar import clean_events
    ev = clean_events(dr.get('events'))
    if ev:
        out['events'] = ev
    # which Documents bucket the PDF belongs in + whether it is news at all (2026-10-13)
    doc = dr.get('document')
    if isinstance(doc, dict):
        from pg_admin.authorities import valid_category
        cat = str(doc.get('category') or '').strip()
        out['document'] = {'category': cat if valid_category(cat) else 'none',
                           'title': str(doc.get('title') or '').strip()[:300],
                           'news': doc.get('news') is not False}
    # documents required for registration, read out of a bulletin / prospectus / checklist (2026-10-13)
    regs = []
    for g in (dr.get('registration_documents') or [])[:4]:
        if isinstance(g, dict):
            its = [str(x).strip()[:300] for x in (g.get('items') or []) if str(x).strip()][:60]
            if its:
                regs.append({'title': str(g.get('title') or '').strip()[:200], 'items': its})
    if regs:
        out['registration_documents'] = regs
    # the date printed ON the notice — used when the website lists it without a date (2026-10-17)
    iss = dr.get('issued_on')
    if isinstance(iss, dict) and _d(iss.get('date')):
        out['issued_on'] = {'date': _d(iss.get('date')).isoformat(), 'quote': str(iss.get('quote') or '').strip()[:300]}
    # notes meant for the team never stay in doctor-facing text (founder 2026-10-22: a Kerala summary
    # read "Reviewer: check the time…") — kept separately, shown in the Inbox, never published
    import re as _re
    notes = [str(dr.get('review_note') or '').strip()]
    for k in ('summary', 'article', 'action'):
        found = _re.findall(r'(?:^|(?<=[.!?\n]))\s*((?:Note to |Note for )?(?:the )?reviewer\b[^.!?\n]*[.!?]?)', out[k], _re.I)
        for f in found:
            notes.append(f.strip())
            out[k] = out[k].replace(f, '').replace('  ', ' ').strip()
    note = ' '.join(n for n in notes if n)[:600]
    if note:
        out['review_note'] = note
    if not out['headline'] and not out['article']:
        return None
    return out


HOLD_BY = 'AI (waiting for PDF)'


def api_news_inbox_review():
    """GET /api/pg/news-inbox/review (X-News-Key) — READ-ONLY: every notice in New / Documents-only
    with its link, kind, whether we hold the PDF and the AI headline, for an inbox audit. (2026-10-17)"""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        NS.ensure_news_inbox_tables(conn)
        from pg_admin.data.big_files import ensure_cols as _bf_cols
        _bf_cols(conn)
        out = []
        for r in conn.execute("SELECT id, source_code, status, title, url, kind, notice_date, draft_json, "
                              "(pdf_data IS NOT NULL OR COALESCE(pdf_r2_key,'') <> '' OR pdf_doc_id IS NOT NULL) AS has_pdf "
                              "FROM pg_news_inbox WHERE status IN ('new','document') ORDER BY source_code, id").fetchall():
            try: d = json.loads(r['draft_json'] or '{}') or {}
            except Exception: d = {}
            out.append({'id': r['id'], 'source_code': r['source_code'], 'status': r['status'], 'title': r['title'],
                        'url': r['url'], 'kind': r['kind'], 'has_pdf': bool(r['has_pdf']),
                        'date': str(r['notice_date'] or ''), 'headline': d.get('headline') or '',
                        'summary': d.get('summary') or ''})
        return jsonify({'ok': True, 'count': len(out), 'items': out})
    finally:
        conn.close()


def api_news_inbox_hold():
    """POST /api/pg/news-inbox/hold {ids:[...], note} (X-News-Key) — move New notices whose PDF link has
    no file yet out of New (Dismissed, by 'AI (waiting for PDF)'). They stay watched: the day the
    PDF appears it is archived and the notice returns to New by itself. Only touches New notices
    that have no PDF; never a posted one. (founder 2026-10-17)"""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    b = request.get_json(silent=True) or {}
    ids = [int(x) for x in (b.get('ids') or []) if str(x).isdigit()][:300]
    note = str(b.get('note') or 'The authority link has no file yet — held until the PDF is online.').strip()[:300]
    if not ids:
        return jsonify({'ok': False, 'error': 'no ids'}), 400
    conn = get_db()
    try:
        from pg_admin.data.big_files import ensure_cols as _bf_cols
        _bf_cols(conn)
        n = 0
        for i in ids:
            cur = conn.execute("UPDATE pg_news_inbox SET status = 'dismissed', reviewed_by = ?, "
                               "reviewed_at = CURRENT_TIMESTAMP, history_note = ? WHERE id = ? AND status = 'new' "
                               "AND kind = 'pdf' AND pdf_data IS NULL AND COALESCE(pdf_r2_key,'') = '' RETURNING id",
                               (HOLD_BY, note, i)).fetchone()
            n += 1 if cur else 0
        conn.commit()
        return jsonify({'ok': True, 'held': n})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news hold: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def _attach_to_news(conn, news_id, pdf, r2_key, pdf_name, inbox_id=None):
    """A notice was posted before its PDF was online; the PDF has now arrived → attach it to the
    posted news too (only when that news has no PDF yet — a hand-attached file is never replaced).
    The PDF is also filed into the authority's Documents by the usual auto-filing. (2026-10-17)"""
    try:
        from pg_admin.routes.api_news import ensure_news_seo_cols
        ensure_news_seo_cols(conn)
        doc_id = None
        if inbox_id:                     # filed in Documents → the news links that one file (no copy, 2026-10-22)
            from pg_admin.data.auto_docs import doc_for_inbox
            doc_id = doc_for_inbox(conn, inbox_id)
        if doc_id:
            conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS authority_doc_id INTEGER")
            conn.execute("UPDATE pg_news SET authority_doc_id = ?, pdf_name = ?, updated_at = CURRENT_TIMESTAMP "
                         "WHERE id = ? AND pdf_data IS NULL AND COALESCE(pdf_r2_key,'') = '' AND authority_doc_id IS NULL",
                         (doc_id, pdf_name or 'notice.pdf', news_id))
        elif pdf:
            conn.execute("UPDATE pg_news SET pdf_data = ?, pdf_name = ?, pdf_content_type = 'application/pdf', "
                         "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND pdf_data IS NULL "
                         "AND COALESCE(pdf_r2_key,'') = ''", (pdf, pdf_name or 'notice.pdf', news_id))
        elif r2_key:
            conn.execute("UPDATE pg_news SET pdf_r2_key = ?, pdf_name = ?, pdf_content_type = 'application/pdf', "
                         "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND pdf_data IS NULL "
                         "AND COALESCE(pdf_r2_key,'') = ''", (r2_key, pdf_name or 'notice.pdf', news_id))
        conn.commit()
    except Exception as e:
        logging.warning("attach late pdf to news %s: %s", news_id, e)
        try: conn.rollback()
        except Exception: pass


def _issued(draft):
    """The notice's own printed date from a cleaned draft (or None) — only a plausible one."""
    v = _d(((draft or {}).get('issued_on') or {}).get('date'))
    if v and date(2024, 1, 1) <= v <= date.today():
        return v
    return None


def _auto_calendar(conn, inbox_id):
    """The AI's schedule goes straight into the Counselling Calendar (no posting needed)."""
    try:
        from pg_admin.data.calendar import sync_from_inbox
        n = sync_from_inbox(conn, inbox_id)
        conn.commit()
        logging.info("calendar auto-fill: inbox %s → %d rows", inbox_id, n)
    except Exception as e:
        logging.warning("calendar auto-fill %s: %s", inbox_id, e)
        try: conn.rollback()
        except Exception: pass


def api_news_inbox_known():
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    code = (request.args.get('source') or '').strip()
    conn = get_db()
    try:
        NS.ensure_news_inbox_tables(conn)
        from pg_admin.data.big_files import ensure_cols as _bf_cols
        _bf_cols(conn)
        from pg_admin.data.archive import ensure_cols as _ar_cols
        _ar_cols(conn)
        from pg_admin.ai_redraft import ensure_cols as _ai_cols, _schedule
        _ai_cols(conn)
        rows = conn.execute("SELECT i.id, item_key, url, title, kind, notice_date, status, (draft_json IS NOT NULL) AS drafted, "
                            "COALESCE(redraft_requested, FALSE) AS redraft, COALESCE(redraft_note,'') AS redraft_note, "
                            "(pdf_data IS NOT NULL OR COALESCE(pdf_r2_key,'') <> '' OR pdf_doc_id IS NOT NULL) AS has_pdf, "
                            "EXISTS (SELECT 1 FROM pg_authority_docs d WHERE d.auto_inbox_id = i.id AND "
                            "d.auto_kind = 'snapshot') AS has_snap FROM pg_news_inbox i "
                            "WHERE source_code = ?", (code,)).fetchall()
        return jsonify({'ok': True, 'source': code, 'known': [r['item_key'] for r in rows],
                        'drafted': [r['item_key'] for r in rows if r['drafted']],
                        # notices the founder asked to re-draft ("↻ Re-draft with AI") — and New
                        # notices that never got a draft (a run cut short), 2026-10-17
                        'redraft': [{'item_key': r['item_key'], 'url': r['url'], 'title': r['title'],
                                     'kind': r['kind'], 'inbox_id': r['id'], 'has_stored_pdf': bool(r['has_pdf']),
                                     'note': r['redraft_note'] if r['redraft'] else '',
                                     'notice_date': r['notice_date'].isoformat() if r['notice_date'] else None}
                                    for r in rows if r['redraft'] or (r['status'] == 'new' and not r['drafted'])],
                        # the authority's calendar steps — a re-draft reuses the same round/event/label (2026-10-22)
                        'schedule': _schedule(conn, (NS.SOURCES.get(code) or {}).get('authority_code') or ''),
                        # PDF notices we still don't hold a copy of (link not online yet, too big before,
                        # download failed) — the Mac retries every run and sends the file when it
                        # appears; every authority PDF must be archived (founder 2026-10-17)
                        'need_pdf': [{'item_key': r['item_key'], 'url': r['url'], 'title': r['title']}
                                     for r in rows if r['kind'] == 'pdf' and r['status'] != 'seen'
                                     and not r['has_pdf'] and r['url']],
                        # web-page notices (no PDF of their own) not yet saved as a PDF snapshot —
                        # the Mac prints the page and sends it (archive-only, founder 2026-10-22)
                        'need_snapshot': [{'item_key': r['item_key'], 'url': r['url'], 'title': r['title']}
                                          for r in rows if r['kind'] == 'link' and r['status'] != 'seen'
                                          and not r['has_pdf'] and not r['has_snap'] and r['url']]})
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
    # a big PDF the Mac already uploaded to R2 (see api_news_inbox_upload_url) — 2026-10-17
    r2_key = str(b.get('pdf_r2_key') or '').strip()[:400]
    r2_sha = str(b.get('pdf_sha256') or '').strip()[:64]
    if r2_key:
        from core import storage
        if not r2_key.startswith('authority-pdfs/') or not storage.object_size(r2_key):
            r2_key = ''                                           # not uploaded / not ours → ignore
    conn = get_db()
    try:
        NS.ensure_news_inbox_tables(conn)
        from pg_admin.data.big_files import ensure_cols as _bf_cols
        _bf_cols(conn)
        from pg_admin.ai_redraft import ensure_cols as _ai_cols
        _ai_cols(conn)
        row = conn.execute("SELECT id, status, draft_json, notice_date, news_id, reviewed_by, COALESCE(redraft_requested, FALSE) AS redraft, "
                           "(pdf_data IS NOT NULL OR COALESCE(pdf_r2_key,'') <> '' OR pdf_doc_id IS NOT NULL) AS has_pdf "
                           "FROM pg_news_inbox WHERE source_code = ? AND item_key = ?", (code, key)).fetchone()
        if row:
            # Known notice — only fill in what's missing (a draft / PDF from a later run), or
            # take the fresh draft the founder asked for (Re-draft with AI).
            sets, vals = [], []
            if draft and (not row['draft_json'] or row['redraft']):
                sets += ["draft_json = ?", "drafted_at = CURRENT_TIMESTAMP", "redraft_requested = FALSE"]
                if row['redraft']:
                    sets += ["redraft_status = 'done'", "redraft_error = ''", "redraft_at = CURRENT_TIMESTAMP"]
                vals.append(json.dumps(draft))
            elif draft and (draft.get('document') or draft.get('events')) and row['draft_json']:
                # a draft from before documents were filed: add ONLY the missing document
                # classification, nothing else in the reviewed draft changes (2026-10-13)
                try:
                    old = json.loads(row['draft_json']) or {}
                except Exception:
                    old = {}
                if isinstance(old, dict) and (not old.get('document') or
                                              (draft.get('registration_documents') and not old.get('registration_documents')) or
                                              (draft.get('events') and not old.get('events'))):
                    if draft.get('document'):
                        old.setdefault('document', draft['document'])
                    if draft.get('events'):
                        old.setdefault('events', draft['events'])
                    if draft.get('registration_documents'):
                        old.setdefault('registration_documents', draft['registration_documents'])
                    sets.append("draft_json = ?"); vals.append(json.dumps(old))
            if pdf and not row['has_pdf']:
                sets += ["pdf_data = COALESCE(pdf_data, ?)", "pdf_name = COALESCE(NULLIF(pdf_name,''), ?)"]
                vals += [pdf, pdf_name]
            elif r2_key and not row['has_pdf']:
                sets += ["pdf_r2_key = ?", "pdf_sha256 = ?", "pdf_size = ?", "pdf_name = COALESCE(NULLIF(pdf_name,''), ?)"]
                vals += [r2_key, r2_sha, int(b.get('pdf_size') or 0), pdf_name]
            if (pdf or r2_key) and not row['has_pdf'] and row['status'] != 'seen' and not draft \
                    and "redraft_requested = TRUE" not in sets:
                # the PDF arrived AFTER the notice was drafted (from its title only) → re-read it:
                # the next run re-drafts from the real PDF before anything is final (founder 2026-10-18)
                sets.append("redraft_requested = TRUE")
            if (pdf or r2_key) and not row['has_pdf'] and row['status'] == 'dismissed' \
                    and (row['reviewed_by'] or '') == HOLD_BY:
                # held because its file wasn't online — the PDF is here now → back to New, re-drafted
                # from the real PDF at the next run (founder 2026-10-17)
                sets = [x for x in sets if x != "redraft_requested = TRUE"]
                sets += ["status = 'new'", "history_note = ?", "redraft_requested = TRUE"]
                vals.append('The PDF is now online on the authority site — brought back to New automatically.')
            if b.get('force_events') and draft and draft.get('events') and row['draft_json'] and not sets:
                # corrected calendar dates for an already-received notice (operator back-check, 2026-10-14):
                # replace ONLY the draft's events; the calendar merge then updates the entries in place
                try:
                    old = json.loads(row['draft_json']) or {}
                except Exception:
                    old = {}
                if isinstance(old, dict):
                    old['events'] = draft['events']
                    sets.append("draft_json = ?"); vals.append(json.dumps(old))
            if b.get('revive') and row['status'] == 'seen' and draft:
                # a notice set aside as "already seen" on a source's first run, brought back on
                # the founder's request (2026-10-13) — it lands in New like any fresh notice
                sets.append("status = 'new'")
                if "draft_json = ?" not in sets:
                    sets += ["draft_json = ?", "drafted_at = CURRENT_TIMESTAMP"]; vals.append(json.dumps(draft))
                row = dict(row); row['status'] = 'new'
            if not row['notice_date'] and row['status'] != 'posted' and _issued(draft):
                # the website listed it without a date → use the date printed on the notice (2026-10-17)
                sets += ["notice_date = ?", "notice_date_source = 'notice'"]; vals.append(_issued(draft))
            if sets:
                conn.execute(f"UPDATE pg_news_inbox SET {', '.join(sets)} WHERE id = ?", vals + [row['id']])
                conn.commit()
                new_file = bool((pdf or r2_key) and not row['has_pdf'])
                if draft and draft.get('events'):
                    _auto_calendar(conn, row['id'])
                if row['status'] != 'seen':
                    from pg_admin.data.auto_docs import file_safely
                    file_safely(conn, row['id'], release=new_file)    # a newly arrived PDF is kept once
                if new_file and row['news_id']:
                    _attach_to_news(conn, row['news_id'], pdf, r2_key, pdf_name, inbox_id=row['id'])
            return jsonify({'ok': True, 'id': row['id'], 'result': 'updated' if sets else 'known'})
        it = {'item_key': key, 'title': title, 'url': url, 'kind': kind, 'notice_date': nd}
        if status == 'new' and NS.is_repeat(conn, code, it):
            status = 'seen'                                       # site re-posted an earlier notice
        nd_src = ''
        if not nd and _issued(draft):
            nd, nd_src = _issued(draft), 'notice'                 # undated on the site → date on the notice
        new_id = conn.execute(
            "INSERT INTO pg_news_inbox (source_code, authority_code, item_key, title, raw_title, url, kind, "
            "notice_date, status, draft_json, drafted_at, pdf_data, pdf_name) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
            (code, src['authority_code'], key, title, str(b.get('raw_title') or title)[:800], url, kind, nd,
             status, json.dumps(draft) if draft else None, None, pdf, pdf_name)).fetchone()['id']
        if draft:
            conn.execute("UPDATE pg_news_inbox SET drafted_at = CURRENT_TIMESTAMP WHERE id = ?", (new_id,))
        if nd_src:
            conn.execute("UPDATE pg_news_inbox SET notice_date_source = ? WHERE id = ?", (nd_src, new_id))
        if r2_key and not pdf:
            conn.execute("UPDATE pg_news_inbox SET pdf_r2_key = ?, pdf_sha256 = ?, pdf_size = ? WHERE id = ?",
                         (r2_key, r2_sha, int(b.get('pdf_size') or 0), new_id))
        conn.commit()
        if status == 'new' and draft and draft.get('events'):
            _auto_calendar(conn, new_id)
        doc_res = None
        if status == 'new' and (draft or pdf or r2_key):      # no draft → still archived (2026-10-22)
            from pg_admin.data.auto_docs import file_safely
            doc_res = file_safely(conn, new_id, release=True)    # PDF → authority Documents (hidden), kept once
        return jsonify({'ok': True, 'id': new_id, 'result': status, 'document': doc_res})
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


def api_news_inbox_upload_url():
    """POST /api/pg/news-inbox/upload-url {source_code, item_key, sha256, name, size} (X-News-Key) →
    {put_url, key}: a signed link the Mac PUTs a big PDF to (straight into R2 — too big to send
    through the portal), then it calls /ingest with pdf_r2_key. (founder 2026-10-17: archive every
    authority PDF whatever its size)"""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    from core import storage
    from pg_admin.data.big_files import make_key
    b = request.get_json(silent=True) or {}
    code = (b.get('source_code') or '').strip()
    sha = ''.join(ch for ch in str(b.get('sha256') or '').lower() if ch in '0123456789abcdef')[:64]
    if code not in NS.SOURCES or len(sha) != 64:
        return jsonify({'ok': False, 'error': 'need source_code + sha256'}), 400
    if not storage.is_configured():
        return jsonify({'ok': False, 'error': 'storage_not_configured'}), 503
    key = make_key(NS.SOURCES[code].get('authority_code') or code, sha, str(b.get('name') or 'notice.pdf'))
    have = storage.object_size(key)
    url = None if have else storage.presigned_put_url(key, 'application/pdf', 3600)
    if not have and not url:
        return jsonify({'ok': False, 'error': 'could_not_sign'}), 502
    return jsonify({'ok': True, 'key': key, 'put_url': url, 'already': bool(have)})


# Course-name tables a rename must keep in step (the cut-off rows, the college master's course list,
# and doctors' saved choice items that point at those rows).
_COURSE_TABLES = (('pg_cutoffs', 'course'), ('pg_college_course', 'course'), ('pg_choice_items', 'course'))


def api_maint_course_rename():
    """POST /api/pg/maint/course-rename {from, to, apply} (X-News-Key) — fix a wrongly-named course in the
    cut-off data (e.g. 'M.D. Fecal Microbiota Transplantation' = MD (FMT) Forensic Medicine, founder
    2026-10-21). Without apply=true it only COUNTS the matching rows (preview); with apply=true it renames
    exactly those rows in every course table above and logs it. `to` must already be an existing course
    name, so a typo can't invent a new speciality. (2026-10-21)"""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    b = request.get_json(silent=True) or {}
    old = str(b.get('from') or '').strip()
    new = str(b.get('to') or '').strip()
    apply = b.get('apply') is True
    if not old or not new or old == new:
        return jsonify({'ok': False, 'error': 'need from + to (different)'}), 400
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM pg_cutoffs WHERE course = ? LIMIT 1", (new,)).fetchone():
            return jsonify({'ok': False, 'error': f'"{new}" is not an existing course name'}), 400
        counts = {}
        for t, col in _COURSE_TABLES:
            try:
                counts[t] = int(conn.execute(f"SELECT COUNT(*) AS n FROM {t} WHERE {col} = ?", (old,)).fetchone()['n'])
            except Exception:
                conn.rollback(); counts[t] = None
        # a college whose course catalogue ALREADY lists the target course keeps that line; its old
        # mis-named line is left for review (never a duplicate on the college page)
        try:
            dup = int(conn.execute(
                "SELECT COUNT(*) AS n FROM pg_college_course c WHERE c.course = ? AND EXISTS ("
                "SELECT 1 FROM pg_college_course x WHERE x.master_id = c.master_id AND x.course = ?)",
                (old, new)).fetchone()['n'])
        except Exception:
            conn.rollback(); dup = None
        if apply:
            for t, col in _COURSE_TABLES:
                if not counts.get(t):
                    continue
                if t == 'pg_college_course':
                    conn.execute("UPDATE pg_college_course SET course = ? WHERE course = ? AND NOT EXISTS ("
                                 "SELECT 1 FROM pg_college_course x WHERE x.master_id = pg_college_course.master_id "
                                 "AND x.course = ?)", (new, old, new))
                else:
                    conn.execute(f"UPDATE {t} SET {col} = ? WHERE {col} = ?", (new, old))
            if b.get('drop_duplicates') is True and dup:
                # founder-approved (2026-10-21): the mis-named line of a college that ALREADY lists the
                # target course is a duplicate → remove it (the correct line stays)
                conn.execute("DELETE FROM pg_college_course WHERE course = ? AND EXISTS ("
                             "SELECT 1 FROM pg_college_course x WHERE x.master_id = pg_college_course.master_id "
                             "AND x.course = ?)", (old, new))
                counts['pg_college_course_duplicates_removed'] = dup
            conn.execute("CREATE TABLE IF NOT EXISTS pg_course_rename_log (id SERIAL PRIMARY KEY, old_name TEXT, "
                         "new_name TEXT, counts TEXT, done_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("INSERT INTO pg_course_rename_log (old_name, new_name, counts) VALUES (?,?,?)",
                         (old, new, json.dumps(counts)))
            conn.commit()
            try:
                from pg_admin import perf
                perf._VER.update(at=0, v=None)          # course lists rebuild on the next request
            except Exception:
                pass
        return jsonify({'ok': True, 'applied': apply, 'from': old, 'to': new, 'rows': counts,
                        'college_course_already_listed': dup})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("course rename: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_news_inbox_undated():
    """GET /api/pg/news-inbox/undated (X-News-Key) — unpublished notices the website listed without
    a date (New / Documents only), so the Mac can read the date printed on each PDF. (2026-10-17)"""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        NS.ensure_news_inbox_tables(conn)
        from pg_admin.data.big_files import ensure_cols as _bf_cols
        _bf_cols(conn)
        rows = [{'id': r['id'], 'source_code': r['source_code'], 'item_key': r['item_key'], 'title': r['title'],
                 'url': r['url'], 'kind': r['kind'], 'status': r['status'], 'pdf': bool(r['has_pdf']),
                 'found': str(r['first_seen_at'] or '')[:10]}
                for r in conn.execute("SELECT id, source_code, item_key, title, url, kind, status, first_seen_at, "
                                      "(pdf_data IS NOT NULL OR pdf_doc_id IS NOT NULL) AS has_pdf FROM pg_news_inbox "
                                      "WHERE notice_date IS NULL AND status IN ('new','document') "
                                      "ORDER BY id").fetchall()]
        return jsonify({'ok': True, 'count': len(rows), 'items': rows})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news undated: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_news_inbox_set_date():
    """POST /api/pg/news-inbox/set-date {id, date: YYYY-MM-DD, quote} (X-News-Key) — fill in the date
    printed on the notice for an UNPUBLISHED, UNDATED inbox notice. Never overwrites a date the
    website gave, never touches a posted notice. (founder 2026-10-17)"""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    b = request.get_json(silent=True) or {}
    try:
        iid = int(b.get('id') or 0)
    except (TypeError, ValueError):
        iid = 0
    v = _issued({'issued_on': {'date': b.get('date')}})
    if not iid or not v:
        return jsonify({'ok': False, 'error': 'need id + a valid past date'}), 400
    quote = str(b.get('quote') or '').strip()[:300]
    conn = get_db()
    try:
        NS.ensure_news_inbox_tables(conn)
        row = conn.execute("SELECT id, status, notice_date, draft_json FROM pg_news_inbox WHERE id = ?", (iid,)).fetchone()
        if not row:
            return jsonify({'ok': False, 'error': 'not found'}), 404
        if row['notice_date'] or row['status'] not in ('new', 'document'):
            return jsonify({'ok': True, 'result': 'unchanged'})
        try:
            dr = json.loads(row['draft_json'] or '{}') or {}
        except Exception:
            dr = {}
        if isinstance(dr, dict) and dr:
            dr['issued_on'] = {'date': v.isoformat(), 'quote': quote}
            conn.execute("UPDATE pg_news_inbox SET draft_json = ? WHERE id = ?", (json.dumps(dr), iid))
        conn.execute("UPDATE pg_news_inbox SET notice_date = ?, notice_date_source = 'notice' "
                     "WHERE id = ? AND notice_date IS NULL", (v, iid))
        conn.commit()
        return jsonify({'ok': True, 'result': 'dated', 'date': v.isoformat()})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news set-date: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def admin_news_key_check():
    """Admin-only: is NEWS_INGEST_KEY set, and its fingerprint (sha256 prefix + length) — to
    match against the Mac's copy without ever showing the key. (2026-10-08)"""
    from core.users import get_user
    import hashlib
    u = get_user()
    if not (u and u.get('is_admin')):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    raw = os.environ.get('NEWS_INGEST_KEY') or ''
    k = raw.strip()
    return jsonify({'ok': True, 'configured': bool(k), 'length': len(k), 'raw_length': len(raw),
                    'fingerprint': hashlib.sha256(k.encode()).hexdigest()[:12] if k else ''})


def api_news_inbox_status():
    """GET /api/pg/news-inbox/status?authority=<code> (X-News-Key) — READ-ONLY check of what the
    pipeline produced for an authority: inbox notices, calendar steps, documents (incl. waiting)
    and exactly what the website receives from /api/pg/authority/<code>. (2026-10-13)"""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    from pg_admin.authorities import get_authority
    code = (request.args.get('authority') or '').strip().lower()
    if not get_authority(code):
        return jsonify({'ok': False, 'error': 'unknown authority'}), 400
    srcs = [c for c, s in NS.SOURCES.items() if s.get('authority_code') == code]
    out = {'ok': True, 'authority': code}
    conn = get_db()
    try:
        inbox = []
        for r in conn.execute("SELECT id, status, title, notice_date, news_id, draft_json, (pdf_data IS NOT NULL) AS has_pdf "
                              "FROM pg_news_inbox WHERE source_code IN (" + ','.join(['?'] * len(srcs)) + ") "
                              "AND status <> 'seen' ORDER BY notice_date DESC NULLS LAST, id DESC", srcs).fetchall() if srcs else []:
            try: d = json.loads(r['draft_json'] or '{}') or {}
            except Exception: d = {}
            inbox.append({'id': r['id'], 'status': r['status'], 'title': (r['title'] or '')[:120],
                          'date': str(r['notice_date'] or ''), 'news_id': r['news_id'], 'pdf': bool(r['has_pdf']),
                          'events': len(d.get('events') or []), 'doc': (d.get('document') or {}).get('category')})
        out['inbox'] = inbox
        out['calendar'] = [{'round': r['round'], 'event': r['event'], 'label': r['label'], 'start': str(r['start_date']),
                            'end': str(r['end_date'] or ''), 'active': r['is_active']}
                           for r in conn.execute("SELECT round, event, label, start_date, end_date, is_active FROM "
                                                 "pg_counselling_events WHERE authority_code = ? ORDER BY start_date",
                                                 (code,)).fetchall()]
        out['documents'] = [{'id': r['id'], 'category': r['category'], 'title': (r['title'] or '')[:120],
                             'published': r['is_published'], 'waiting': r['rp'], 'main': r['is_main'],
                             'file': bool(r['file_name']), 'auto': r['auto_inbox_id']}
                            for r in conn.execute("SELECT id, category, title, is_published, COALESCE(review_pending,FALSE) AS rp, "
                                                  "COALESCE(is_main,FALSE) AS is_main, file_name, auto_inbox_id "
                                                  "FROM pg_authority_docs WHERE authority_code = ? ORDER BY category, id",
                                                  (code,)).fetchall()]
        out['news'] = [{'id': r['id'], 'heading': (r['heading'] or '')[:120], 'published': r['is_published'],
                        'deleted': bool(r['deleted_at']), 'state': r['state'], 'scope': r['scope']}
                       for r in conn.execute("SELECT id, heading, is_published, deleted_at, state, scope FROM pg_news "
                                             "ORDER BY id DESC LIMIT 60").fetchall()
                       if (code == 'mcc' and r['scope'] == 'all_india') or
                          (code != 'mcc' and (r['state'] or '').lower() == (get_authority(code)['state'] or '').lower())]
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        out['db_error'] = str(e)[:300]
    finally:
        conn.close()
    # what the website actually gets (server-internal call, same as the site would see)
    from flask import current_app
    try:
        with current_app.test_client() as c:
            for path in (f'/api/pg/authority/{code}', '/api/pg/counselling-status', '/api/pg/calendar'):
                r = c.get(path, query_string={'authority': code}, environ_overrides={'pg.internal_check': True})
                body = r.get_json(silent=True) or {}
                if path.startswith('/api/pg/authority/'):
                    body = {'main_brochure': body.get('main_brochure'),
                            'document_groups': [{'category': g.get('category'), 'n': len(g.get('documents') or []),
                                                 'titles': [x.get('title') for x in (g.get('documents') or [])][:6]}
                                                for g in (body.get('document_groups') or [])],
                            'news': len(body.get('news') or []), 'keys': sorted(body.keys()),
                            'seat_matrix': body.get('seat_matrix')}
                out['api:' + path] = {'status': r.status_code, 'body': body}
            r = c.get('/api/pg/authorities', query_string={'all': '1'}, environ_overrides={'pg.internal_check': True})
            out['api:/api/pg/authorities?all=1'] = {'status': r.status_code, 'authorities': [
                {'code': x.get('code'), 'has_content': x.get('has_content'), 'watched': x.get('watched'),
                 'covers': len(x.get('covers_states') or [])}
                for x in ((r.get_json(silent=True) or {}).get('authorities') or [])]}
    except Exception as e:
        out['api_error'] = str(e)[:300]
    return jsonify(out)


def api_news_inbox_snapshot():
    """POST /api/pg/news-inbox/snapshot {source_code, item_key, pdf_b64, name} (X-News-Key) — the Mac's
    PDF print of a web-page notice → kept as a hidden archive-only document of the authority
    (founder 2026-10-22: every notice must stay in our control after the site changes)."""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    b = request.get_json(silent=True) or {}
    code = (b.get('source_code') or '').strip()
    key = (b.get('item_key') or '').strip()
    try:
        data = base64.b64decode(b.get('pdf_b64') or '')
    except Exception:
        data = b''
    if code not in NS.SOURCES or not key or not data.startswith(b'%PDF') or len(data) > MAX_PDF:
        return jsonify({'ok': False, 'error': 'bad request'}), 400
    conn = get_db()
    try:
        r = conn.execute("SELECT id FROM pg_news_inbox WHERE source_code = ? AND item_key = ?", (code, key)).fetchone()
        if not r:
            return jsonify({'ok': False, 'error': 'unknown notice'}), 404
        from pg_admin.data.archive import archive_snapshot, kick_sync
        res = archive_snapshot(conn, r['id'], data, str(b.get('name') or '')[:200])
        conn.commit()
        if res == 'archived':
            kick_sync()
        return jsonify({'ok': True, 'result': res})
    except Exception as e:
        logging.warning("news snapshot %s/%s: %s", code, key, e)
        try: conn.rollback()
        except Exception: pass
        return jsonify({'ok': False, 'error': str(e)[:200]}), 500
    finally:
        conn.close()


def api_news_inbox_redraft_queue():
    """GET /api/pg/news-inbox/redraft-queue (X-News-Key) — how many notices the team asked to re-draft.
    The Mac's watcher polls this every 2 minutes (cheap, no AI) and starts a run only when it is > 0."""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        from pg_admin.ai_redraft import ensure_cols as _ai_cols
        _ai_cols(conn)
        rows = conn.execute("SELECT id, source_code, title FROM pg_news_inbox WHERE COALESCE(redraft_requested, FALSE) "
                            "ORDER BY id").fetchall()
        return jsonify({'ok': True, 'count': len(rows),
                        'items': [{'id': r['id'], 'source_code': r['source_code'], 'title': r['title']} for r in rows]})
    finally:
        conn.close()


def api_news_inbox_stored_pdf():
    """GET /api/pg/news-inbox/stored-pdf?id=<inbox id> (X-News-Key) — the PDF we hold for a notice (inbox copy,
    its Documents file, R2, or the page snapshot), for a re-draft when the authority has removed the file."""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    try:
        iid = int(request.args.get('id') or 0)
    except ValueError:
        iid = 0
    conn = get_db()
    try:
        from pg_admin.data.big_files import ensure_cols as _bf_cols
        _bf_cols(conn)
        row = conn.execute("SELECT * FROM pg_news_inbox WHERE id = ?", (iid,)).fetchone()
        if not row:
            return jsonify({'ok': False, 'error': 'not found'}), 404
        from pg_admin.ai_redraft import _pdf_bytes
        data = _pdf_bytes(conn, dict(row))
    finally:
        conn.close()
    if not data:
        return jsonify({'ok': False, 'error': 'no stored file'}), 404
    from flask import Response
    return Response(data, mimetype='application/pdf')
