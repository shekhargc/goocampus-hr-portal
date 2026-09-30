"""Public /api/pg/news* endpoints — the goocampus.in dashboard news feed
(founder 2026-09-30).

A doctor sees All-India news always, plus news for the states they follow (home
state by default; the dashboard can pass more). X-PG-Key guarded, except the PDF
stream which is public.
"""
import logging
from flask import request, jsonify, Response
from db import get_db
from pg_admin.routes.api import _authorized


def _s(v):
    return (str(v).strip() if v is not None else '')


def api_pg_news():
    """GET /api/pg/news — the filtered feed.
    Params:
      states   comma-separated list of states the doctor follows (e.g. home state)
      all      '0' to hide All-India items (default: include them)
      body     optional exact body_label filter
      page, page_size (<=100)
    """
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    states_raw = _s(request.args.get('states'))
    states = [s.strip() for s in states_raw.split(',') if s.strip()]
    include_all = _s(request.args.get('all')) != '0'
    body = _s(request.args.get('body'))
    try:
        page = max(1, int(request.args.get('page', 1)))
    except Exception:
        page = 1
    try:
        page_size = min(100, max(1, int(request.args.get('page_size', 20))))
    except Exception:
        page_size = 20

    # Build the scope filter: all_india (optional) OR state IN (...).
    scope_parts = []
    params = []
    if include_all:
        scope_parts.append("scope = 'all_india'")
    if states:
        placeholders = ','.join(['?'] * len(states))
        scope_parts.append(f"(scope = 'state' AND state IN ({placeholders}))")
        params.extend(states)
    if not scope_parts:
        # nothing requested → just All-India
        scope_parts.append("scope = 'all_india'")
    where = "is_published AND (" + " OR ".join(scope_parts) + ")"
    if body:
        where += " AND body_label = ?"; params.append(body)

    conn = get_db()
    try:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM pg_news WHERE {where}", params).fetchone()['n']
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT id, scope, state, body_label, heading, body_text, pdf_name, "
            f"(pdf_data IS NOT NULL) AS has_pdf, published_at "
            f"FROM pg_news WHERE {where} ORDER BY published_at DESC, id DESC "
            f"LIMIT {page_size} OFFSET {offset}", params).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d['pdf_url'] = (f"/api/pg/news/{d['id']}/pdf" if d.get('has_pdf') else None)
            items.append(d)
        return jsonify({'ok': True, 'items': items, 'count': len(items),
                        'total': total, 'page': page, 'page_size': page_size,
                        'total_pages': (total + page_size - 1) // page_size if page_size else 1}), 200
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_news: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass


def api_pg_news_pdf(news_id):
    """GET /api/pg/news/<id>/pdf — stream a news attachment. Public (no key)."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT pdf_name, pdf_data, pdf_content_type FROM pg_news "
            "WHERE id=? AND is_published", (news_id,)).fetchone()
    except Exception as e:
        logging.error("api_pg_news_pdf: %s", e)
        row = None
    finally:
        try: conn.close()
        except Exception: pass
    if not row or not row['pdf_data']:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    return Response(bytes(row['pdf_data']), mimetype=row['pdf_content_type'] or 'application/pdf',
                    headers={'Content-Disposition': f'inline; filename="{row["pdf_name"] or "news.pdf"}"'})
