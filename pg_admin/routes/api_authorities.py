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
from pg_admin.routes.api_choice import _user, _doctor_states
from pg_admin.data import entitlements
from pg_admin.authorities import all_authorities, get_authority, DOC_CATEGORIES, category_label


def _doctor_access(conn):
    """Resolve the requesting doctor (from their Bearer token, if sent) → (user, home_state,
    is_paid). Free = no paid plan: may access only MCC (All-India) + their home state.
    Paid (starter/standard/premium) = all authorities. No token → (None,'',False): the
    caller (frontend) applies its own gating; the list is returned unfiltered."""
    user = _user(conn)
    if not user:
        return None, '', False
    uid = user['id']
    home = ''
    try:
        for st in _doctor_states(conn, uid):
            if (st.get('role') or '') == 'home':
                home = st.get('state') or ''
                break
    except Exception:
        pass
    is_paid = False
    try:
        plan, _sub = entitlements.effective_plan(conn, uid)
        code = (plan.get('code') or '').lower() if plan else ''
        is_paid = any(t in code for t in ('starter', 'standard', 'premium'))
    except Exception:
        pass
    return user, home, is_paid


def _can_access(authority, home, is_paid):
    """Free users: MCC (central) + their own home state only. Paid: everything."""
    if is_paid:
        return True
    if authority['kind'] == 'central':
        return True
    # an authority that serves the doctor's home state (incl. regional ones like RIMS Imphal → 7 NE states)
    serves = {x.strip().lower() for x in (authority.get('covers_states') or [authority.get('state') or ''])}
    return (home or '').strip().lower() in serves


def _file_url(doc_id):
    return f"{request.url_root.rstrip('/')}/api/pg/authority-docs/{doc_id}/file"


def _news_match_sql(authority):
    """(where, params) selecting published news for this authority."""
    if authority['kind'] == 'central':
        return "scope='all_india'", []
    return "scope='state' AND LOWER(TRIM(state))=LOWER(TRIM(?))", [authority['state']]


def _seat_matrix_for(conn, authority):
    """The seat matrix for this authority: by explicit authority_code first (the reliable
    link set at upload), falling back to a name/state match for legacy untagged rows."""
    sel = ("SELECT counselling_body, academic_year, row_count, college_count, total_seats, "
           "(pdf_data IS NOT NULL) AS has_pdf FROM pg_seat_matrix_source ")
    try:
        # Official sectioned matrices (MCC final: AIQ / CIQ / Deemed) → one combined summary.
        # The initial NMC file (section 'nmc_initial') is a separate thing and never counted here.
        from pg_admin.routes.seat_matrix_ingest import ensure_prev_cols, change_payload
        ensure_prev_cols(conn)
        secs = [dict(r) for r in conn.execute(
            "SELECT counselling_body, academic_year, row_count, total_seats, section, college_count, "
            "prev_row_count, prev_college_count, prev_total_seats, prev_replaced_at, prev_source_file_name, "
            "colleges_added, colleges_removed, "
            "(pdf_data IS NOT NULL) AS has_pdf FROM pg_seat_matrix_source WHERE authority_code = ? "
            "AND COALESCE(superseded,0)=0 AND COALESCE(section,'') NOT IN ('', 'nmc_initial') "
            "ORDER BY academic_year DESC, COALESCE(sort_order,0)", (authority['code'],)).fetchall()]
        if secs:
            yr = secs[0]['academic_year']
            secs = [x for x in secs if x['academic_year'] == yr]
            bodies = [x['counselling_body'] for x in secs]
            ph = ','.join(['?'] * len(bodies))
            colleges = conn.execute(
                f"SELECT COUNT(DISTINCT college_code) AS n FROM pg_seat_matrix WHERE counselling_body IN ({ph}) "
                "AND academic_year=?", bodies + [yr]).fetchone()['n']
            return {'counselling_body': bodies[0], 'academic_year': yr,
                    'row_count': sum(x['row_count'] or 0 for x in secs),
                    'college_count': colleges, 'total_seats': sum(x['total_seats'] or 0 for x in secs),
                    'has_pdf': any(x['has_pdf'] for x in secs),
                    'sections': [{'counselling_body': x['counselling_body'], 'section': x['section'],
                                  'total_seats': x['total_seats'], 'has_pdf': bool(x['has_pdf']),
                                  **change_payload(x)} for x in secs]}
        row = conn.execute(sel + "WHERE authority_code = ? AND COALESCE(superseded,0)=0 "
                           "AND COALESCE(section,'') <> 'nmc_initial' ORDER BY academic_year DESC LIMIT 1",
                           (authority['code'],)).fetchone()
        if not row:
            like = f"%{authority['state']}%"
            row = conn.execute(
                sel + "WHERE COALESCE(authority_code,'')='' AND (counselling_body ILIKE ? "
                "OR counselling_body ILIKE ?) ORDER BY academic_year DESC LIMIT 1",
                (like, f"%{authority['name'].split(' ')[0]}%")).fetchone()
        return dict(row) if row else None
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return None


def api_pg_authorities():
    """List authorities that have content, with per-segment counts, for the dashboard.
    ?all=1 → EVERY active authority (also those with nothing published yet), each with has_content,
    so the site can show regional coverage + "updates awaited" from day one (2026-10-13)."""
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
        sm_codes = set()
        try:
            smrows = [dict(r) for r in conn.execute(
                "SELECT counselling_body, COALESCE(authority_code,'') AS authority_code "
                "FROM pg_seat_matrix_source").fetchall()]
            sm_bodies = [(r['counselling_body'] or '').lower() for r in smrows]
            sm_codes = {r['authority_code'] for r in smrows if r['authority_code']}
        except Exception:
            try: conn.rollback()
            except Exception: pass
    except Exception as e:
        logging.error("api_pg_authorities: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    # Doctor context for access gating (free = MCC + home state; paid = all).
    conn2 = get_db()
    try:
        user, home, is_paid = _doctor_access(conn2)
    finally:
        try: conn2.close()
        except Exception: pass

    want_all = (request.args.get('all') or '').strip() == '1'
    from pg_admin import news_scraper as _NS        # authorities whose official site we follow
    watched = {x.get('authority_code') for x in _NS.SOURCES.values() if x.get('enabled')}
    out = []
    for a in all_authorities():
        docs = doc_counts.get(a['code'], 0)
        has_news = (a['kind'] == 'central' and mcc_news) or (a['state'].lower() in news_states)
        sm = (a['code'] in sm_codes) or any(
            a['state'].lower() in b or a['name'].split(' ')[0].lower() in b for b in sm_bodies)
        has_content = bool(docs or has_news or sm)
        if has_content or want_all:
            # locked only matters when we know the doctor (token sent). No token → not locked
            # (the frontend gates). Paid or MCC or home state → open.
            locked = bool(user) and not _can_access(a, home, is_paid)
            out.append({**a, 'doc_count': docs, 'has_news': bool(has_news),
                        'has_seat_matrix': bool(sm), 'locked': locked, 'has_content': has_content,
                        'watched': a['code'] in watched})
    return jsonify({'ok': True, 'authorities': out,
                    'viewer': {'is_paid': is_paid, 'home_state': home,
                               'known': bool(user)}}), 200


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
    # Access gating: a free doctor may open only MCC + their home state. When a doctor token
    # is sent and the authority is locked for them, return it flagged locked with no content
    # (the frontend shows an upgrade prompt); paid doctors and service calls get everything.
    try:
        user, home, is_paid = _doctor_access(conn)
    except Exception:
        user, home, is_paid = None, '', False
    if user and not _can_access(authority, home, is_paid):
        try: conn.close()
        except Exception: pass
        return jsonify({'ok': True, 'authority': authority, 'locked': True,
                        'document_groups': [], 'news': [], 'seat_matrix': None,
                        'viewer': {'is_paid': is_paid, 'home_state': home}}), 200
    main_brochure, main_brochures = None, []
    try:
        try:
            conn.execute("ALTER TABLE pg_authority_docs ADD COLUMN IF NOT EXISTS is_main BOOLEAN DEFAULT FALSE")
            conn.execute("ALTER TABLE pg_authority_docs ADD COLUMN IF NOT EXISTS main_label TEXT DEFAULT ''")
        except Exception:
            conn.rollback()
        rows = [dict(r) for r in conn.execute(
            "SELECT id, category, title, doc_date, note, body_text, file_name, "
            "COALESCE(is_main, FALSE) AS is_main, COALESCE(main_label, '') AS main_label "
            "FROM pg_authority_docs WHERE authority_code=? AND COALESCE(is_published,TRUE) "
            "ORDER BY category, COALESCE(is_main, FALSE) DESC, sort_order, id DESC", (authority['code'],)).fetchall()]
        by_cat = {}
        for r in rows:
            has_file = bool(r.get('file_name'))
            by_cat.setdefault(r['category'], []).append({
                'id': r['id'], 'title': r['title'], 'date': r['doc_date'] or '',
                'note': r['note'] or '', 'body_text': r.get('body_text') or '',
                'file_name': r['file_name'] or '',
                'file_url': _file_url(r['id']) if has_file else '',
                'is_main': bool(r.get('is_main')),
                'main_label': (r.get('main_label') or '') if r.get('is_main') else '',
            })
            if r.get('is_main') and has_file:
                main_brochures.append({'id': r['id'], 'title': r['title'], 'date': r['doc_date'] or '',
                                       'label': r.get('main_label') or 'Information Bulletin',
                                       'file_url': _file_url(r['id'])})
        # several main bulletins (founder 2026-10-13, e.g. TN Government quota + Management/NRI quota):
        # general bulletin / government quota first; main_brochure (singular) stays = the first one
        _ord = {'information bulletin': 0, 'prospectus': 1, 'government quota': 2, 'management / nri quota': 3, 'user guide': 9}
        main_brochures.sort(key=lambda m: (_ord.get((m['label'] or '').lower(), 5), m['id']))
        main_brochure = main_brochures[0] if main_brochures else None
        for cat, label in DOC_CATEGORIES:
            if by_cat.get(cat):
                groups.append({'category': cat, 'label': label, 'documents': by_cat[cat]})

        nwhere, nparams = _news_match_sql(authority)
        try:
            from pg_admin.routes.api_news import ensure_news_seo_cols
            ensure_news_seo_cols(conn)
            news = [dict(r) for r in conn.execute(
                "SELECT id, heading, body_text, source_url, published_at, "
                "COALESCE(category,'') AS category, COALESCE(summary,'') AS summary, "
                "COALESCE(key_dates,'') AS key_dates, COALESCE(schedule,'') AS schedule, "
                "(pdf_data IS NOT NULL OR COALESCE(pdf_r2_key,'') <> '' OR authority_doc_id IS NOT NULL) AS has_pdf FROM pg_news "
                f"WHERE COALESCE(is_published,TRUE) AND deleted_at IS NULL AND {nwhere} "
                "ORDER BY published_at DESC NULLS LAST, id DESC LIMIT 20", nparams).fetchall()]
            import json as _json
            for n in news:
                n['published_at'] = str(n['published_at'])[:10] if n.get('published_at') else ''
                try:
                    n['key_dates'] = _json.loads(n.get('key_dates') or '{}') or {}
                except Exception:
                    n['key_dates'] = {}
                from pg_admin.routes.api_news import parse_schedule
                n['schedule'] = parse_schedule(n.get('schedule'))
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
    return jsonify({'ok': True, 'authority': authority, 'locked': False,
                    'main_brochure': main_brochure, 'main_brochures': main_brochures,
                    'document_groups': groups, 'news': news, 'seat_matrix': seat_matrix,
                    'viewer': {'is_paid': is_paid, 'home_state': home}}), 200


def api_pg_authority_doc_file(doc_id):
    """GET /api/pg/authority-docs/<id>/file — stream a published document. Public (no key),
    so the doctor's browser can open/download it directly (same as the news PDF stream)."""
    from pg_admin.routes.api import file_key_block
    blk = file_key_block()
    if blk:
        return blk
    conn = get_db()
    try:
        from pg_admin.data.big_files import ensure_cols as _bf_cols
        _bf_cols(conn)
        row = conn.execute(
            "SELECT file_name, file_data, file_content_type, file_r2_key FROM pg_authority_docs "
            "WHERE id=? AND COALESCE(is_published,TRUE)", (doc_id,)).fetchone()
    except Exception as e:
        logging.error("api_pg_authority_doc_file: %s", e); row = None
    finally:
        try: conn.close()
        except Exception: pass
    if row and not row['file_data'] and row.get('file_r2_key'):     # big file kept in R2 (2026-10-17)
        from pg_admin.data.big_files import r2_redirect
        rr = r2_redirect(row['file_r2_key'])
        if rr:
            return rr
    if not row or not row['file_data']:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    return Response(bytes(row['file_data']),
                    mimetype=row['file_content_type'] or 'application/octet-stream',
                    headers={'Content-Disposition': f'inline; filename="{row["file_name"] or "document"}"'})
