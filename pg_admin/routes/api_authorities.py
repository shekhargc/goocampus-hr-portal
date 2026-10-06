"""Public/keyed APIs for the per-authority counselling sections on goocampus.in
(founder 2026-10-06).

- GET /api/pg/authorities            → authorities that have ANY content (docs/news/seat
                                        matrix), with per-segment counts. X-PG-Key.
- GET /api/pg/authority/<code>       → one authority's documents (grouped by category) +
                                        its news + seat-matrix availability. X-PG-Key.
- GET /api/pg/authority-docs/<id>/file → stream a published document (public, so the
                                         browser can open/download it directly).
"""

import logging
from flask import request, jsonify, Response
from db import get_db
from pg_admin.routes.api import _authorized
from pg_admin.authorities import all_authorities, get_authority, DOC_CATEGORIES, category_label


def _file_url(doc_id):
    return f"{request.url_root.rstrip('/')}/api/pg/authority-docs/{doc_id}/file"


def _news_match_sql(authority):
    """(where, params) selecting published news for this authority."""
    if authority['kind'] == 'central':
        return "scope='all_india'", []
    return "scope='state' AND LOWER(TRIM(state))=LOWER(TRIM(?))", [authority['state']]


def _seat_matrix_for(conn, authority):
    """Best-effort: is there a seat matrix for this authority? Match the authority's
    state or short name against the free-text counselling_body."""
    try:
        like = f"%{authority['state']}%"
        row = conn.execute(
            "SELECT counselling_body, academic_year, row_count, college_count, total_seats, "
            "(pdf_data IS NOT NULL) AS has_pdf FROM pg_seat_matrix_source "
            "WHERE counselling_body ILIKE ? OR counselling_body ILIKE ? "
            "ORDER BY academic_year DESC LIMIT 1",
            (like, f"%{authority['name'].split(' ')[0]}%")).fetchone()
        return dict(row) if row else None
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return None


def api_pg_authorities():
    """List authorities that have content, with per-segment counts, for the dashboard."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    doc_counts, news_states, mcc_news = {}, set(), 0
    sm_bodies = []
    try:
        for r in conn.execute(
                "SELECT authority_code, COUNT(*) AS n FROM pg_authority_docs "
                "WHERE COALESCE(is_published,TRUE) GROUP BY authority_code").fetchall():
            doc_counts[r['authority_code']] = r['n']
        for r in conn.execute(
                "SELECT DISTINCT scope, LOWER(TRIM(state)) AS st FROM pg_news "
                "WHERE COALESCE(is_published,TRUE)").fetchall():
            if r['scope'] == 'all_india':
                mcc_news = 1
            elif r['st']:
                news_states.add(r['st'])
        try:
            sm_bodies = [(r['counselling_body'] or '').lower() for r in conn.execute(
                "SELECT counselling_body FROM pg_seat_matrix_source").fetchall()]
        except Exception:
            try: conn.rollback()
            except Exception: pass
    except Exception as e:
        logging.error("api_pg_authorities: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    out = []
    for a in all_authorities():
        docs = doc_counts.get(a['code'], 0)
        has_news = (a['kind'] == 'central' and mcc_news) or (a['state'].lower() in news_states)
        sm = any(a['state'].lower() in b or a['name'].split(' ')[0].lower() in b for b in sm_bodies)
        if docs or has_news or sm:
            out.append({**a, 'doc_count': docs, 'has_news': bool(has_news),
                        'has_seat_matrix': bool(sm)})
    return jsonify({'ok': True, 'authorities': out}), 200


def api_pg_authority(code):
    """One authority: documents grouped by category + its news + seat-matrix availability."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    authority = get_authority(code)
    if not authority:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    conn = get_db()
    groups = []
    news = []
    seat_matrix = None
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, category, title, doc_date, note, file_name "
            "FROM pg_authority_docs WHERE authority_code=? AND COALESCE(is_published,TRUE) "
            "ORDER BY category, sort_order, id DESC", (authority['code'],)).fetchall()]
        by_cat = {}
        for r in rows:
            by_cat.setdefault(r['category'], []).append({
                'id': r['id'], 'title': r['title'], 'date': r['doc_date'] or '',
                'note': r['note'] or '', 'file_name': r['file_name'] or '',
                'file_url': _file_url(r['id']),
            })
        for cat, label in DOC_CATEGORIES:
            if by_cat.get(cat):
                groups.append({'category': cat, 'label': label, 'documents': by_cat[cat]})

        nwhere, nparams = _news_match_sql(authority)
        try:
            news = [dict(r) for r in conn.execute(
                "SELECT id, heading, body_text, source_url, published_at, "
                "(pdf_data IS NOT NULL) AS has_pdf FROM pg_news "
                f"WHERE COALESCE(is_published,TRUE) AND {nwhere} "
                "ORDER BY published_at DESC NULLS LAST, id DESC LIMIT 20", nparams).fetchall()]
            for n in news:
                n['published_at'] = str(n['published_at'])[:10] if n.get('published_at') else ''
                n['pdf_url'] = (f"{request.url_root.rstrip('/')}/api/pg/news/{n['id']}/pdf"
                                if n.get('has_pdf') else '')
        except Exception:
            try: conn.rollback()
            except Exception: pass
            news = []

        seat_matrix = _seat_matrix_for(conn, authority)
    except Exception as e:
        logging.error("api_pg_authority(%s): %s", code, e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    return jsonify({'ok': True, 'authority': authority, 'document_groups': groups,
                    'news': news, 'seat_matrix': seat_matrix}), 200


def api_pg_authority_doc_file(doc_id):
    """GET /api/pg/authority-docs/<id>/file — stream a published document. Public (no key),
    so the doctor's browser can open/download it directly (same as the news PDF stream)."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT file_name, file_data, file_content_type FROM pg_authority_docs "
            "WHERE id=? AND COALESCE(is_published,TRUE)", (doc_id,)).fetchone()
    except Exception as e:
        logging.error("api_pg_authority_doc_file: %s", e); row = None
    finally:
        try: conn.close()
        except Exception: pass
    if not row or not row['file_data']:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    return Response(bytes(row['file_data']),
                    mimetype=row['file_content_type'] or 'application/octet-stream',
                    headers={'Content-Disposition': f'inline; filename="{row["file_name"] or "document"}"'})
