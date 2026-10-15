"""Public /api/pg/seat-matrix* endpoints — the goocampus.in dashboard reads the
raw NEET-PG counselling Seat Matrix here (founder 2026-09-30).

Data is served VERBATIM from pg_seat_matrix (authority's own college/course names,
unmatched to our master). X-PG-Key guarded, except the PDF stream which is a public
government document (so the user's browser can open it directly).
"""
import logging
from flask import request, jsonify, Response
from db import get_db
from pg_admin.routes.api import _authorized, smart_name_clause

DEFAULT_BODY = 'All India MCC'
DEFAULT_YEAR = '2026-27'


def _s(v):
    return (str(v).strip() if v is not None else '')


def _default_body(conn, year):
    """The current (non-superseded) matrix to show first: lowest sort_order, MCC first.
    Falls back to the legacy 'All India MCC' name."""
    try:
        r = conn.execute(
            "SELECT counselling_body FROM pg_seat_matrix_source WHERE academic_year=? "
            "AND COALESCE(superseded,0)=0 ORDER BY (COALESCE(authority_code,'')<>'mcc'), "
            "COALESCE(sort_order,0), counselling_body LIMIT 1", [year]).fetchone()
        return r['counselling_body'] if r else DEFAULT_BODY
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return DEFAULT_BODY


def api_pg_seat_matrix():
    """GET /api/pg/seat-matrix — filtered, paginated seat-matrix rows.
    Params: body, year, state, category, course, q (college name/code search),
    page (1-based), page_size (<=500)."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    year = _s(request.args.get('year')) or DEFAULT_YEAR
    body = _s(request.args.get('body'))
    if not body:
        _c = get_db()
        try:
            body = _default_body(_c, year)
        finally:
            _c.close()
    state = _s(request.args.get('state'))
    quota = _s(request.args.get('quota'))
    itype = _s(request.args.get('institute_type'))
    new_only = _s(request.args.get('new_only')) in ('1', 'true', 'yes')
    category = _s(request.args.get('category'))
    course = _s(request.args.get('course'))
    q = _s(request.args.get('q'))
    try:
        page = max(1, int(request.args.get('page', 1)))
    except Exception:
        page = 1
    try:
        page_size = min(500, max(1, int(request.args.get('page_size', 100))))
    except Exception:
        page_size = 100

    conds = ["counselling_body = ?", "academic_year = ?"]
    params = [body, year]
    if state:
        conds.append("state = ?"); params.append(state)
    if category:
        conds.append("category = ?"); params.append(category)
    if course:
        conds.append("course_name = ?"); params.append(course)
    if quota:
        conds.append("quota = ?"); params.append(quota)
    if itype:
        conds.append("institute_type = ?"); params.append(itype)
    if new_only:
        conds.append("has_cutoff = 0")
    if q:
        fn, pn = smart_name_clause("college_name", q)
        conds.append(f"({fn} OR college_code ILIKE ?)"); params.extend(pn + [f"%{q}%"])
    where = " AND ".join(conds)

    conn = get_db()
    try:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM pg_seat_matrix WHERE {where}",
                             params).fetchone()['n']
        seats = conn.execute(f"SELECT COALESCE(SUM(seats),0) AS s FROM pg_seat_matrix WHERE {where}",
                             params).fetchone()['s']
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT sl_no, college_code, state, college_name, category, course_name, seats, "
            f"institute_type, quota, has_cutoff, new_reason, cutoff_institute, cutoff_course, "
            f"cr_r1, cr_r2, cr_r3, cr_closing, cutoff_fee "
            f"FROM pg_seat_matrix WHERE {where} "
            f"ORDER BY state ASC, college_name ASC, course_name ASC "
            f"LIMIT {page_size} OFFSET {offset}", params).fetchall()
        out = []
        for r in rows:
            r = dict(r)
            if r.get('cutoff_fee') is not None:
                r['cutoff_fee'] = float(r['cutoff_fee'])
            # has_cutoff: 1 = bridged to the 2025 cut-off; 0 = new in 2026; None = not analysed
            r['is_new'] = (r.get('has_cutoff') == 0)
            out.append(r)
        return jsonify({
            'ok': True,
            'counselling_body': body, 'academic_year': year,
            'rows': out, 'count': len(out),
            'total_matched': total, 'seats_matched': int(seats or 0),
            'page': page, 'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size if page_size else 1,
        }), 200
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_seat_matrix: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass


def api_pg_seat_matrix_facets():
    """GET /api/pg/seat-matrix/facets — filter options + totals for a body+year,
    so the dashboard can build its dropdowns and headline stats in one call."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    year = _s(request.args.get('year')) or DEFAULT_YEAR
    conn = get_db()
    try:
        body = _s(request.args.get('body')) or _default_body(conn, year)
        base = "FROM pg_seat_matrix WHERE counselling_body=? AND academic_year=?"
        p = [body, year]
        states = [r['state'] for r in conn.execute(
            f"SELECT DISTINCT state {base} AND state<>'' ORDER BY state", p).fetchall()]
        categories = [r['category'] for r in conn.execute(
            f"SELECT DISTINCT category {base} AND category<>'' ORDER BY category", p).fetchall()]
        courses = [r['course_name'] for r in conn.execute(
            f"SELECT DISTINCT course_name {base} AND course_name<>'' ORDER BY course_name", p).fetchall()]
        quotas = [r['quota'] for r in conn.execute(
            f"SELECT DISTINCT quota {base} AND COALESCE(quota,'')<>'' ORDER BY quota", p).fetchall()]
        itypes = [r['institute_type'] for r in conn.execute(
            f"SELECT DISTINCT institute_type {base} AND COALESCE(institute_type,'')<>'' "
            f"ORDER BY institute_type", p).fetchall()]
        agg = conn.execute(
            f"SELECT COUNT(*) AS rows, COUNT(DISTINCT college_code||'|'||college_name) AS colleges, "
            f"COALESCE(SUM(seats),0) AS seats, "
            f"COALESCE(SUM(CASE WHEN has_cutoff=0 THEN seats ELSE 0 END),0) AS new_seats, "
            f"COUNT(DISTINCT CASE WHEN new_reason='new_college' THEN college_code END) AS new_colleges {base}",
            p).fetchone()
        src = conn.execute(
            "SELECT source_file_name, pdf_name, uploaded_at, "
            "(pdf_data IS NOT NULL) AS has_pdf, row_count, college_count, total_seats "
            "FROM pg_seat_matrix_source WHERE counselling_body=? AND academic_year=?",
            (body, year)).fetchone()
        # All bodies/years available (for a top-level switcher)
        # Current matrices only (an older provisional one that was superseded is hidden).
        available = [dict(r) for r in conn.execute(
            "SELECT counselling_body, academic_year, row_count, college_count, total_seats, "
            "(pdf_data IS NOT NULL) AS has_pdf, uploaded_at, COALESCE(section,'') AS section, "
            "COALESCE(authority_code,'') AS authority_code, COALESCE(sort_order,0) AS sort_order "
            "FROM pg_seat_matrix_source WHERE COALESCE(superseded,0)=0 "
            "ORDER BY academic_year DESC, (COALESCE(authority_code,'')<>'mcc'), "
            "COALESCE(sort_order,0), counselling_body ASC").fetchall()]
        return jsonify({
            'ok': True,
            'counselling_body': body, 'academic_year': year,
            'states': states, 'categories': categories, 'courses': courses,
            'quotas': quotas, 'institute_types': itypes,
            'totals': {'rows': agg['rows'], 'colleges': agg['colleges'],
                       'seats': int(agg['seats'] or 0),
                       'new_seats': int(agg['new_seats'] or 0),
                       'new_colleges': int(agg['new_colleges'] or 0)},
            'source': (dict(src) if src else None),
            'available': available,
            'has_pdf': bool(src and src['has_pdf']),
        }), 200
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_seat_matrix_facets: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass


def api_pg_seat_matrix_pdf():
    """GET /api/pg/seat-matrix/pdf?body=&year= — stream the official authority PDF.
    Public (no key): it is a published government document."""
    year = _s(request.args.get('year')) or DEFAULT_YEAR
    conn = get_db()
    try:
        body = _s(request.args.get('body')) or _default_body(conn, year)
        row = conn.execute(
            "SELECT pdf_name, pdf_data, pdf_content_type FROM pg_seat_matrix_source "
            "WHERE counselling_body=? AND academic_year=?", (body, year)).fetchone()
    except Exception as e:
        logging.error("api_pg_seat_matrix_pdf: %s", e)
        row = None
    finally:
        try: conn.close()
        except Exception: pass
    if not row or not row['pdf_data']:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    fname = row['pdf_name'] or 'seat-matrix.pdf'
    return Response(bytes(row['pdf_data']),
                    mimetype=row['pdf_content_type'] or 'application/pdf',
                    headers={'Content-Disposition': f'inline; filename="{fname}"'})
