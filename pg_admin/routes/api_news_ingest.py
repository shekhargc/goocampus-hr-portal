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
    if not out['headline'] and not out['article']:
        return None
    return out


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
        rows = conn.execute("SELECT item_key, url, title, kind, notice_date, (draft_json IS NOT NULL) AS drafted, "
                            "COALESCE(redraft_requested, FALSE) AS redraft FROM pg_news_inbox "
                            "WHERE source_code = ?", (code,)).fetchall()
        return jsonify({'ok': True, 'source': code, 'known': [r['item_key'] for r in rows],
                        'drafted': [r['item_key'] for r in rows if r['drafted']],
                        # notices the founder asked to re-draft ("↻ Re-draft with AI")
                        'redraft': [{'item_key': r['item_key'], 'url': r['url'], 'title': r['title'],
                                     'kind': r['kind'],
                                     'notice_date': r['notice_date'].isoformat() if r['notice_date'] else None}
                                    for r in rows if r['redraft']]})
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
        row = conn.execute("SELECT id, status, draft_json, COALESCE(redraft_requested, FALSE) AS redraft "
                           "FROM pg_news_inbox WHERE source_code = ? AND item_key = ?", (code, key)).fetchone()
        if row:
            # Known notice — only fill in what's missing (a draft / PDF from a later run), or
            # take the fresh draft the founder asked for (Re-draft with AI).
            sets, vals = [], []
            if draft and (not row['draft_json'] or row['redraft']):
                sets += ["draft_json = ?", "drafted_at = CURRENT_TIMESTAMP", "redraft_requested = FALSE"]
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
            if pdf:
                sets += ["pdf_data = COALESCE(pdf_data, ?)", "pdf_name = COALESCE(NULLIF(pdf_name,''), ?)"]
                vals += [pdf, pdf_name]
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
            if sets:
                conn.execute(f"UPDATE pg_news_inbox SET {', '.join(sets)} WHERE id = ?", vals + [row['id']])
                conn.commit()
                if draft and draft.get('events'):
                    _auto_calendar(conn, row['id'])
                if row['status'] != 'seen':
                    from pg_admin.data.auto_docs import file_safely
                    file_safely(conn, row['id'])
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
        if status == 'new' and draft and draft.get('events'):
            _auto_calendar(conn, new_id)
        doc_res = None
        if status == 'new' and draft:
            from pg_admin.data.auto_docs import file_safely
            doc_res = file_safely(conn, new_id)                  # PDF → authority Documents (hidden)
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
                            'news': len(body.get('news') or []), 'keys': sorted(body.keys())}
                out['api:' + path] = {'status': r.status_code, 'body': body}
            r = c.get('/api/pg/authorities', query_string={'all': '1'}, environ_overrides={'pg.internal_check': True})
            out['api:/api/pg/authorities?all=1'] = {'status': r.status_code, 'authorities': [
                {'code': x.get('code'), 'has_content': x.get('has_content'), 'watched': x.get('watched'),
                 'covers': len(x.get('covers_states') or [])}
                for x in ((r.get_json(silent=True) or {}).get('authorities') or [])]}
    except Exception as e:
        out['api_error'] = str(e)[:300]
    return jsonify(out)
