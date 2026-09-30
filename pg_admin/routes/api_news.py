"""Public /api/pg/news* endpoints — the goocampus.in dashboard news feed + a
doctor's saved state subscriptions (founder 2026-09-30).

Feed model: every doctor sees All-India news + their home-state news by default.
Paid doctors (dash_news_follow) can FOLLOW extra states — saved to their profile,
so the admin sees the subscription on the Registered Doctors page and it persists.
The "add a state" picker only offers states that actually have published news.

X-PG-Key guards the reads; the follow endpoints ALSO need the doctor's Bearer token.
The PDF stream is public.
"""
import logging
from flask import request, jsonify, Response
from db import get_db
from pg_admin.routes.api import _authorized
from pg_admin.routes.api_choice import _user, _plan_has, _doctor_states


def _s(v):
    return (str(v).strip() if v is not None else '')


def _home_state(conn, uid):
    try:
        for st in _doctor_states(conn, uid):
            if (st.get('role') or '') == 'home':
                return st.get('state')
    except Exception:
        pass
    return None


def _follows(conn, uid):
    try:
        return [r['state'] for r in conn.execute(
            "SELECT state FROM pg_news_follows WHERE user_id=? ORDER BY state", [uid]).fetchall()]
    except Exception:
        return []


def _states_with_news(conn):
    """States that currently have published state-scoped news (for the picker)."""
    try:
        return [r['state'] for r in conn.execute(
            "SELECT DISTINCT state FROM pg_news WHERE is_published AND scope='state' "
            "AND COALESCE(state,'')<>'' ORDER BY state").fetchall()]
    except Exception:
        return []


def api_pg_news():
    """GET /api/pg/news — the filtered feed.
    Params:
      states   comma-separated states to include (optional)
      all      '0' to hide All-India items (default: include them)
      body     optional exact body_label filter
      page, page_size (<=100)
    If the doctor's Bearer token is present, their home state + followed states are
    added automatically (so the site can just send the token)."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    states = [s.strip() for s in _s(request.args.get('states')).split(',') if s.strip()]
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

    conn = get_db()
    try:
        # Fold in the doctor's own home + followed states when a token is supplied.
        user = _user(conn)
        if user:
            hs = _home_state(conn, user['id'])
            if hs:
                states.append(hs)
            states.extend(_follows(conn, user['id']))
        states = list({s for s in states if s})

        scope_parts = []
        params = []
        if include_all:
            scope_parts.append("scope = 'all_india'")
        if states:
            placeholders = ','.join(['?'] * len(states))
            scope_parts.append(f"(scope = 'state' AND state IN ({placeholders}))")
            params.extend(states)
        if not scope_parts:
            scope_parts.append("scope = 'all_india'")
        where = "is_published AND (" + " OR ".join(scope_parts) + ")"
        if body:
            where += " AND body_label = ?"; params.append(body)

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


def api_pg_news_states():
    """GET /api/pg/news/states — states that have published news (for the picker)."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        return jsonify({'ok': True, 'states': _states_with_news(conn)}), 200
    finally:
        try: conn.close()
        except Exception: pass


def api_pg_news_follows():
    """GET/POST/DELETE /api/pg/news/follows — a doctor's saved state subscriptions.
    GET  → {home_state, follows[], can_follow, available[]}
    POST {state} → add (paid only; state must have news)
    DELETE {state} → remove"""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        uid = user['id']
        can_follow = _plan_has(conn, uid, 'dash_news_follow')

        if request.method == 'GET':
            avail = _states_with_news(conn)
            home = _home_state(conn, uid)
            follows = _follows(conn, uid)
            # picker = states with news, minus home + already followed
            skip = {(home or '').strip().lower()} | {f.strip().lower() for f in follows}
            available = [s for s in avail if s.strip().lower() not in skip]
            return jsonify({'ok': True, 'home_state': home, 'follows': follows,
                            'can_follow': can_follow, 'available': available,
                            'tier': ('paid' if can_follow else 'free')}), 200

        state = _s((request.get_json(silent=True) or {}).get('state') or request.form.get('state'))
        if not state:
            return jsonify({'ok': False, 'error': 'state_required'}), 400

        if request.method == 'DELETE':
            conn.execute("DELETE FROM pg_news_follows WHERE user_id=? AND state=?", (uid, state))
            conn.commit()
            return jsonify({'ok': True, 'follows': _follows(conn, uid)}), 200

        # POST (add)
        if not can_follow:
            return jsonify({'ok': False, 'error': 'upgrade_required',
                            'message': 'Following other states’ news is a paid feature. '
                                       'You already get All-India and your home-state news.'}), 403
        if state not in _states_with_news(conn):
            return jsonify({'ok': False, 'error': 'no_news_for_state',
                            'message': 'No news is available for that state yet.'}), 400
        home = _home_state(conn, uid)
        if home and state.strip().lower() == home.strip().lower():
            return jsonify({'ok': True, 'follows': _follows(conn, uid),
                            'message': 'That is already your home state.'}), 200
        try:
            conn.execute("INSERT INTO pg_news_follows (user_id, state) VALUES (?, ?) "
                         "ON CONFLICT DO NOTHING", (uid, state))
            conn.commit()
        except Exception:
            conn.rollback()
        return jsonify({'ok': True, 'follows': _follows(conn, uid)}), 200
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_news_follows: %s", e)
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
