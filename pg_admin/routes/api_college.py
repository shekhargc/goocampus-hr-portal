"""Public API for the unified PG College Database + Stipend/Bond/Penalty
(founder 2026-09-20). Read-only, X-PG-Key guarded, consumed by goocampus.in.

Backed by pg_college_master / pg_college_course / pg_college_alias (the college
DB) + pg_cutoffs (predictor + stipend). Mirrors the goocampus.org admin screens:
  GET /api/pg/pg-colleges                list + filters + pagination
  GET /api/pg/pg-colleges/facets         states + course-level tab counts
  GET /api/pg/pg-colleges/<id>           full college profile
  GET /api/pg/stipend                    stipend list (family=medical|dnb)
  GET /api/pg/stipend/<id>               per-speciality stipend detail
"""
import logging
from flask import request, jsonify, session
from db import get_db
from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token, smart_name_clause

_PER_PAGE = 100
_CAT_LABELS = [('mbbs', 'MBBS (UG)'), ('mdms', 'MD / MS'),
               ('super', 'Super Speciality'), ('diploma', 'Diploma'), ('dnb', 'DNB')]
_CAT_KEYS = [k for k, _l in _CAT_LABELS]
_NORM = "btrim(regexp_replace(lower(c.institute), '[^a-z0-9]+', ' ', 'g'))"


def _page():
    try:
        return max(1, int(request.args.get('page', 1)))
    except Exception:
        return 1


def _fam(family):
    """(degree-clause, param) for the stipend degree family."""
    if family == 'dnb':
        return "UPPER(COALESCE(c.degree,'')) LIKE ?", '%DNB%'
    return "UPPER(COALESCE(c.degree,'')) NOT LIKE ?", '%DNB%'


def _num(v):
    return float(v) if v is not None else None


def api_pg_college_lookup():
    """GET /api/pg/college-lookup?q=&limit=  — type-ahead search over the MEDICAL college
    master, for the MBBS-college picker on the goocampus.in onboarding form.

    Punctuation-insensitive + token-AND matching across the college name AND its aliases:
    the query and the names are normalised (lowercased, every run of non-alphanumerics →
    a single space), then EACH typed word must appear somewhere. So 'al ameen' finds
    'Al-Ameen Medical College' (hyphen ignored), 'ameen bijapur' finds it too (any order),
    and a middle/last word alone matches. Auth: X-PG-Key OR a logged-in admin/team
    session (so the portal's own screens can reuse it). (founder 2026-10-05)"""
    if not (_authorized() or session.get('is_admin')):
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    import re
    raw = (request.args.get('q') or '').strip()
    qn = re.sub(r'[^a-z0-9]+', ' ', raw.lower()).strip()
    tokens = [t for t in qn.split() if t][:6]        # cap at 6 words
    try:
        limit = min(int(request.args.get('limit') or 20), 50)
    except (TypeError, ValueError):
        limit = 20
    if len(qn) < 2 or not tokens:
        return jsonify({'ok': True, 'colleges': [], 'count': 0})
    conn = get_db()
    try:
        norm = "btrim(regexp_replace(lower(m.college_name), '[^a-z0-9]+', ' ', 'g'))"
        hay = (norm + " || ' ' || COALESCE((SELECT string_agg(a.alias_key, ' ') "
               "FROM pg_college_alias a WHERE a.master_id = m.id), '')")
        inner = (f"SELECT m.id, m.college_name, m.city, m.state, {norm} AS nname, {hay} AS hay "
                 f"FROM pg_college_master m WHERE m.kind = 'medical'")
        # Match if EITHER every typed word appears somewhere (any order) OR — for a run-on
        # query like 'alameen' — the whole thing (spaces removed) is a substring of the
        # name with spaces removed. The run-on branch only kicks in at 4+ chars so short
        # queries don't match half the list.
        token_cond = "(" + " AND ".join(["s.hay LIKE ?"] * len(tokens)) + ")"
        params = ['%' + t + '%' for t in tokens]
        despaced = qn.replace(' ', '')
        conds = [token_cond]
        if len(despaced) >= 4:
            conds.append("replace(s.hay, ' ', '') LIKE ?")
            params.append('%' + despaced + '%')
        where = "(" + " OR ".join(conds) + ")"
        sql = (f"SELECT s.id, s.college_name, s.city, s.state FROM ({inner}) s "
               f"WHERE {where} "
               f"ORDER BY (CASE WHEN s.nname LIKE ? THEN 0 ELSE 1 END), "
               f"length(s.college_name), s.college_name LIMIT ?")
        params = params + [qn + '%', limit]
        rows = [dict(x) for x in conn.execute(sql, params).fetchall()]
        out = [{'id': r['id'], 'name': r['college_name'],
                'city': r.get('city') or '', 'state': r.get('state') or ''} for r in rows]
        return jsonify({'ok': True, 'colleges': out, 'count': len(out)})
    except Exception as e:
        logging.error("api_pg_college_lookup: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── College Database ─────────────────────────────────────────────────────────
def api_pg_pg_colleges():
    """GET /api/pg/pg-colleges?cat=&state=&q=&page="""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    cat = (request.args.get('cat') or '').strip()
    state = (request.args.get('state') or '').strip()
    q = (request.args.get('q') or '').strip()
    page = _page()
    conn = get_db()
    try:
        where, params = ["1=1"], []
        if q:
            frag, fp = smart_name_clause("m.college_name", q); where.append(frag); params.extend(fp)
        if cat in _CAT_KEYS:
            where.append("EXISTS (SELECT 1 FROM pg_college_course cc "
                         "WHERE cc.master_id = m.id AND cc.course_category = ?)")
            params.append(cat)
        if state:
            where.append("m.state = ?"); params.append(state)
        wsql = " WHERE " + " AND ".join(where)
        total = conn.execute("SELECT COUNT(*) AS n FROM pg_college_master m" + wsql,
                             params).fetchone()['n']
        offset = (page - 1) * _PER_PAGE
        rows = conn.execute(
            "SELECT m.id, m.college_name, m.kind, m.city, m.state, m.college_type, m.logo_url, "
            "(SELECT COUNT(*) FROM pg_college_course c WHERE c.master_id = m.id) AS n_courses "
            "FROM pg_college_master m" + wsql +
            " ORDER BY m.college_name LIMIT ? OFFSET ?", params + [_PER_PAGE, offset]).fetchall()
        ids = [r['id'] for r in rows]
        cats = {}
        if ids:
            ph = ','.join(['?'] * len(ids))
            order = {k: i for i, (k, _l) in enumerate(_CAT_LABELS)}
            for r in conn.execute(f"SELECT DISTINCT master_id, course_category FROM pg_college_course "
                                  f"WHERE master_id IN ({ph})", ids).fetchall():
                cats.setdefault(r['master_id'], set()).add(r['course_category'])
            cats = {k: sorted([c for c in v if c in order], key=lambda c: order[c])
                    for k, v in cats.items()}
        fav = set()
        u = _fav_user(conn)
        if u:
            fav = _fav_ids(conn, u['id'])
        colleges = [{
            'id': r['id'], 'name': r['college_name'], 'kind': r['kind'],
            'city': r['city'], 'state': r['state'], 'college_type': r['college_type'],
            'logo_url': r['logo_url'], 'n_courses': r['n_courses'],
            'categories': cats.get(r['id'], []),
            'is_favorite': r['id'] in fav,
        } for r in rows]
    except Exception as e:
        logging.error("api_pg_pg_colleges: %s", e)
        conn.close()
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass
    pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
    return jsonify({'ok': True, 'colleges': colleges, 'count': len(colleges),
                    'total': total, 'page': page, 'pages': pages, 'per_page': _PER_PAGE})


def api_pg_pg_colleges_facets():
    """GET /api/pg/pg-colleges/facets → states + course-level tab counts."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    out = {'ok': True, 'states': [], 'categories': [], 'total': 0}
    try:
        out['states'] = [r['state'] for r in conn.execute(
            "SELECT DISTINCT state FROM pg_college_master WHERE COALESCE(state,'') <> '' ORDER BY state").fetchall()]
        counts = {r['course_category']: r['n'] for r in conn.execute(
            "SELECT course_category, COUNT(DISTINCT master_id) AS n FROM pg_college_course "
            "GROUP BY course_category").fetchall()}
        out['categories'] = [{'key': k, 'label': lbl, 'count': counts.get(k, 0)} for k, lbl in _CAT_LABELS]
        out['total'] = conn.execute("SELECT COUNT(*) AS n FROM pg_college_master").fetchone()['n']
    except Exception as e:
        logging.error("api_pg_pg_colleges_facets: %s", e)
    finally:
        conn.close()
    return jsonify(out)


def api_pg_pg_college_detail(college_id):
    """GET /api/pg/pg-colleges/<id> → full profile + courses + cut-offs + stipend."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        m = conn.execute("SELECT * FROM pg_college_master WHERE id = ?", [college_id]).fetchone()
        if not m:
            conn.close()
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        college = dict(m)
        courses = [dict(r) for r in conn.execute(
            "SELECT course, course_level, course_stream, seat_intake, exam_type, entrance_exams, "
            "entrance_exam_eligibility, academic_eligibility, duration_years, duration_months, course_category "
            "FROM pg_college_course WHERE master_id = ? ORDER BY course", [college_id]).fetchall()]
        aliases = [r['alias_name'] for r in conn.execute(
            "SELECT alias_name FROM pg_college_alias WHERE master_id = ? ORDER BY alias_name",
            [college_id]).fetchall()]
        names = [r['alias_name'] for r in conn.execute(
            "SELECT alias_name FROM pg_college_alias WHERE master_id = ?", [college_id]).fetchall()]
        cutoffs, stipend = [], []
        if names:
            ph = ','.join(['?'] * len(names))
            cutoffs = [dict(r) for r in conn.execute(
                f"SELECT course, category, quota, seat_type, authority, state, "
                f"r1, r2, r3, r4, stray, closing_rank, degree "
                f"FROM pg_cutoffs WHERE institute IN ({ph}) "
                f"ORDER BY authority, course, category, quota", names).fetchall()]
            stipend = [dict(r) for r in conn.execute(
                f"SELECT c.course AS course, MAX(c.degree) AS degree, MAX(c.stipend) AS stipend_yr1, "
                f"MAX(c.stipend_yr2) AS stipend_yr2, MAX(c.stipend_yr3) AS stipend_yr3, "
                f"MAX(c.bond_years) AS bond_years, MAX(c.penalty) AS penalty "
                f"FROM pg_cutoffs c WHERE c.institute IN ({ph}) "
                f"AND (c.stipend IS NOT NULL OR c.bond_years IS NOT NULL OR c.penalty IS NOT NULL) "
                f"GROUP BY c.course ORDER BY c.course", names).fetchall()]
    except Exception as e:
        logging.error("api_pg_pg_college_detail: %s", e)
        conn.close()
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass
    is_fav = False
    try:
        conn2 = get_db()
        u = _fav_user(conn2)
        if u:
            is_fav = college_id in _fav_ids(conn2, u['id'])
        conn2.close()
    except Exception:
        pass
    return jsonify({'ok': True, 'college': college, 'courses': courses,
                    'cutoffs': cutoffs, 'stipend': stipend, 'aliases': aliases,
                    'is_favorite': is_fav})


# ── Stipend · Bond · Penalty ─────────────────────────────────────────────────
def api_pg_stipend():
    """GET /api/pg/stipend?family=medical|dnb&state=&q=&page= → one row per college
    with min–max stipend/bond/penalty across its specialities."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    family = (request.args.get('family') or 'medical').strip()
    if family not in ('medical', 'dnb'):
        family = 'medical'
    state = (request.args.get('state') or '').strip()
    q = (request.args.get('q') or '').strip()
    page = _page()
    deg_clause, deg_param = _fam(family)
    conn = get_db()
    try:
        where = [deg_clause,
                 "(c.stipend IS NOT NULL OR c.bond_years IS NOT NULL OR c.penalty IS NOT NULL)"]
        params = [deg_param]
        if state:
            where.append("c.state = ?"); params.append(state)
        if q:
            frag, fp = smart_name_clause("c.institute", q); where.append(frag); params.extend(fp)
        wsql = " WHERE " + " AND ".join(where)
        total = conn.execute("SELECT COUNT(DISTINCT c.institute) AS n FROM pg_cutoffs c" + wsql,
                             params).fetchone()['n']
        offset = (page - 1) * _PER_PAGE
        rows = conn.execute(
            "SELECT c.institute AS institute, MAX(c.state) AS state, "
            "MIN(c.stipend) AS s1_min, MAX(c.stipend) AS s1_max, "
            "MIN(c.stipend_yr2) AS s2_min, MAX(c.stipend_yr2) AS s2_max, "
            "MIN(c.stipend_yr3) AS s3_min, MAX(c.stipend_yr3) AS s3_max, "
            "MIN(c.bond_years) AS b_min, MAX(c.bond_years) AS b_max, "
            "MIN(c.penalty) AS p_min, MAX(c.penalty) AS p_max, "
            "COUNT(DISTINCT c.course) AS n_courses, MAX(a.master_id) AS id "
            "FROM pg_cutoffs c "
            f"LEFT JOIN pg_college_alias a ON a.alias_key = {_NORM}"
            + wsql + " GROUP BY c.institute ORDER BY c.institute LIMIT ? OFFSET ?",
            params + [_PER_PAGE, offset]).fetchall()
        fav = set()
        u = _fav_user(conn)
        if u:
            fav = _fav_ids(conn, u['id'])
        colleges = [{
            'id': r['id'], 'name': r['institute'], 'state': r['state'], 'n_courses': r['n_courses'],
            'stipend_yr1': [_num(r['s1_min']), _num(r['s1_max'])],
            'stipend_yr2': [_num(r['s2_min']), _num(r['s2_max'])],
            'stipend_yr3': [_num(r['s3_min']), _num(r['s3_max'])],
            'bond_years': [_num(r['b_min']), _num(r['b_max'])],
            'penalty': [_num(r['p_min']), _num(r['p_max'])],
            'is_favorite': (r['id'] in fav) if r['id'] else False,
        } for r in rows]
    except Exception as e:
        logging.error("api_pg_stipend: %s", e)
        conn.close()
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass
    pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
    return jsonify({'ok': True, 'family': family, 'colleges': colleges, 'count': len(colleges),
                    'total': total, 'page': page, 'pages': pages, 'per_page': _PER_PAGE})


def api_pg_stipend_detail(college_id):
    """GET /api/pg/stipend/<master_id>?family=medical|dnb → per-speciality figures."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    family = (request.args.get('family') or 'medical').strip()
    if family not in ('medical', 'dnb'):
        family = 'medical'
    deg_clause, deg_param = _fam(family)
    conn = get_db()
    try:
        m = conn.execute("SELECT id, college_name, kind, city, state FROM pg_college_master "
                         "WHERE id = ?", [college_id]).fetchone()
        if not m:
            conn.close()
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        names = [r['alias_name'] for r in conn.execute(
            "SELECT alias_name FROM pg_college_alias WHERE master_id = ?", [college_id]).fetchall()]
        specialities = []
        if names:
            ph = ','.join(['?'] * len(names))
            specialities = [dict(r) for r in conn.execute(
                f"SELECT c.course AS course, MAX(c.degree) AS degree, MAX(c.stipend) AS stipend_yr1, "
                f"MAX(c.stipend_yr2) AS stipend_yr2, MAX(c.stipend_yr3) AS stipend_yr3, "
                f"MAX(c.bond_years) AS bond_years, MAX(c.penalty) AS penalty "
                f"FROM pg_cutoffs c WHERE c.institute IN ({ph}) AND " + deg_clause +
                " AND (c.stipend IS NOT NULL OR c.bond_years IS NOT NULL OR c.penalty IS NOT NULL) "
                " GROUP BY c.course ORDER BY c.course", names + [deg_param]).fetchall()]
    except Exception as e:
        logging.error("api_pg_stipend_detail: %s", e)
        conn.close()
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass
    return jsonify({'ok': True, 'family': family, 'college': dict(m), 'specialities': specialities})


# ── Fee explorer (course × college fees by quota / category) ─────────────────
def _fee_filters():
    """Common filters for the fee endpoints, from the query string."""
    return {
        'family': (request.args.get('family') or '').strip(),
        'authority': (request.args.get('authority') or '').strip(),
        'state': (request.args.get('state') or '').strip(),
        'course': (request.args.get('course') or '').strip(),
        'quota': (request.args.get('quota') or '').strip(),
        'category': (request.args.get('category') or '').strip(),
        'college_type': (request.args.get('college_type') or '').strip(),
        'q': (request.args.get('q') or '').strip(),
    }


def _fee_where(f):
    """Build the WHERE for a fee query. Only real, priced seats."""
    # fee > 1 drops the ~148 placeholder ₹1 rows (fee not filled in the source) + blanks,
    # so the explorer only shows genuine tuition (there is a clean gap: no real fee is ≤ ₹1).
    where = ["COALESCE(c.is_reference,0)=0", "c.fee IS NOT NULL", "c.fee > 1"]
    params = []
    if f['family'] in ('medical', 'dnb'):
        dc, dp = _fam(f['family']); where.append(dc); params.append(dp)
    if f['authority']:
        where.append("c.authority ILIKE ?"); params.append('%' + f['authority'] + '%')
    if f['state']:
        where.append("c.state = ?"); params.append(f['state'])
    if f['course']:
        where.append("c.course ILIKE ?"); params.append('%' + f['course'] + '%')
    if f['quota']:
        where.append("LOWER(TRIM(c.quota)) = LOWER(TRIM(?))"); params.append(f['quota'])
    if f['category']:
        where.append("LOWER(TRIM(c.category)) = LOWER(TRIM(?))"); params.append(f['category'])
    if f['college_type']:
        where.append("LOWER(TRIM(c.institute_type)) = LOWER(TRIM(?))"); params.append(f['college_type'])
    if f['q']:
        fi, pi = smart_name_clause("c.institute", f['q'])
        fc, pc = smart_name_clause("c.course", f['q'])
        where.append(f"({fi} OR {fc})"); params.extend(pi + pc)
    return where, params


def _int_arg(name):
    try:
        v = request.args.get(name)
        return int(float(v)) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None


def api_pg_fees():
    """GET /api/pg/fees — course-vs-college fee structure by quota/category.

    One row per (college × course × quota × category) with its fee, so a doctor can
    explore/compare fees. Filters: family=medical|dnb, state, course, quota, category,
    q (name search), fee_min, fee_max; sort=fee_asc|fee_desc|college; paginated.
    Reads pg_cutoffs.fee (the same cut-off library) — nothing extra to upload.
    """
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    f = _fee_filters()
    fee_min, fee_max = _int_arg('fee_min'), _int_arg('fee_max')
    sort = (request.args.get('sort') or 'fee_asc').strip()
    page = _page()
    where, params = _fee_where(f)
    wsql = " WHERE " + " AND ".join(where)
    having, hparams = [], []
    if fee_min is not None:
        having.append("MAX(c.fee) >= ?"); hparams.append(fee_min)
    if fee_max is not None:
        having.append("MAX(c.fee) <= ?"); hparams.append(fee_max)
    hsql = (" HAVING " + " AND ".join(having)) if having else ""
    order = {'fee_desc': "fee DESC NULLS LAST",
             'college': "institute ASC, course ASC",
             'fee_asc': "fee ASC NULLS LAST"}.get(sort, "fee ASC NULLS LAST")
    grp = " GROUP BY c.institute, c.course, c.quota, c.category "
    conn = get_db()
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM (SELECT 1 FROM pg_cutoffs c" + wsql + grp + hsql + ") t",
            params + hparams).fetchone()['n']
        offset = (page - 1) * _PER_PAGE
        rows = conn.execute(
            "SELECT c.institute AS institute, c.course AS course, MAX(c.degree) AS degree, "
            "c.quota AS quota, c.category AS category, MAX(c.state) AS state, "
            "MAX(c.institute_type) AS institute_type, MAX(c.seat_type) AS seat_type, "
            "MAX(c.fee) AS fee, MAX(c.year) AS fee_year, MAX(a.master_id) AS id "
            "FROM pg_cutoffs c "
            f"LEFT JOIN pg_college_alias a ON a.alias_key = {_NORM}"
            + wsql + grp + hsql + f" ORDER BY {order}, institute ASC LIMIT ? OFFSET ?",
            params + hparams + [_PER_PAGE, offset]).fetchall()
        out = [{'id': r['id'], 'institute': r['institute'], 'course': r['course'],
                'degree': r['degree'], 'quota': r['quota'], 'category': r['category'],
                'state': r['state'], 'institute_type': r['institute_type'],
                'seat_type': r['seat_type'], 'fee': _num(r['fee']),
                'fee_year': r['fee_year'], 'fee_period': 'year'} for r in rows]
    except Exception as e:
        logging.error("api_pg_fees: %s", e)
        conn.close()
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass
    pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
    return jsonify({'ok': True, 'rows': out, 'count': len(out), 'total': total,
                    'page': page, 'pages': pages, 'per_page': _PER_PAGE})


def api_pg_fees_facets():
    """GET /api/pg/fees/facets?family= → distinct states/courses/quotas/categories that
    have priced seats, to populate the explorer's filter dropdowns."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    fam = (request.args.get('family') or '').strip()
    base = ["COALESCE(is_reference,0)=0", "fee IS NOT NULL", "fee > 1"]
    params = []
    if fam in ('medical', 'dnb'):
        base.append("UPPER(COALESCE(degree,'')) " + ("LIKE ?" if fam == 'dnb' else "NOT LIKE ?"))
        params.append('%DNB%')
    wsql = " WHERE " + " AND ".join(base)
    conn = get_db()
    out = {'ok': True, 'states': [], 'courses': [], 'quotas': [], 'categories': [],
           'college_types': [], 'authorities': []}
    try:
        def distinct(col):
            return [r[col] for r in conn.execute(
                f"SELECT DISTINCT {col} FROM pg_cutoffs" + wsql
                + f" AND COALESCE({col},'')<>'' ORDER BY {col}", params).fetchall()]
        out['states'] = distinct('state')
        out['courses'] = distinct('course')
        out['quotas'] = distinct('quota')
        out['categories'] = distinct('category')
        out['college_types'] = distinct('institute_type')
        out['authorities'] = distinct('authority')
    except Exception as e:
        logging.error("api_pg_fees_facets: %s", e)
    finally:
        conn.close()
    return jsonify(out)


def api_pg_fees_college(college_id):
    """GET /api/pg/fees/<master_id>?family= → every priced course × quota × category for
    one college (the drill-down from the explorer)."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    fam = (request.args.get('family') or '').strip()
    conn = get_db()
    try:
        m = conn.execute("SELECT id, college_name, kind, city, state FROM pg_college_master "
                         "WHERE id = ?", [college_id]).fetchone()
        if not m:
            conn.close()
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        names = [r['alias_name'] for r in conn.execute(
            "SELECT alias_name FROM pg_college_alias WHERE master_id = ?", [college_id]).fetchall()]
        rows = []
        if names:
            ph = ','.join(['?'] * len(names))
            extra, xp = "", []
            if fam in ('medical', 'dnb'):
                extra = " AND UPPER(COALESCE(c.degree,'')) " + ("LIKE ?" if fam == 'dnb' else "NOT LIKE ?")
                xp.append('%DNB%')
            rows = [{'course': r['course'], 'degree': r['degree'], 'quota': r['quota'],
                     'category': r['category'], 'fee': _num(r['fee']),
                     'fee_year': r['fee_year'], 'fee_period': 'year'} for r in conn.execute(
                "SELECT c.course AS course, MAX(c.degree) AS degree, c.quota AS quota, "
                "c.category AS category, MAX(c.fee) AS fee, MAX(c.year) AS fee_year FROM pg_cutoffs c "
                f"WHERE c.institute IN ({ph}) AND COALESCE(c.is_reference,0)=0 "
                "AND c.fee IS NOT NULL AND c.fee > 1" + extra +
                " GROUP BY c.course, c.quota, c.category ORDER BY c.course, c.quota, c.category",
                names + xp).fetchall()]
    except Exception as e:
        logging.error("api_pg_fees_college: %s", e)
        conn.close()
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass
    return jsonify({'ok': True, 'college': dict(m), 'fees': rows})


# ── Favourites (doctor's saved colleges, keyed to the master) ────────────────
def _fav_user(conn):
    """Resolve the logged-in doctor from the Bearer token, or None (optional)."""
    tok = _bearer_token()
    if not tok:
        return None
    try:
        return _pg_user_by_token(conn, tok)
    except Exception:
        return None


def _fav_ids(conn, user_id):
    return {r['master_id'] for r in conn.execute(
        "SELECT master_id FROM pg_college_favorites WHERE user_id = ?", [user_id]).fetchall()}


def api_pg_college_favorites():
    """/api/pg/college-favorites  (X-PG-Key + doctor Bearer token)
       GET  → { ok, favorites:[ {id, name, kind, city, state, college_type, logo_url, added_at} ] }
       POST { master_id } → idempotent add
    """
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    tok = _bearer_token()
    if not tok:
        return jsonify({'ok': False, 'error': 'no_token'}), 401
    conn = get_db()
    try:
        user = _pg_user_by_token(conn, tok)
        if not user:
            return jsonify({'ok': False, 'error': 'invalid_token'}), 401
        uid = user['id']
        if request.method == 'GET':
            rows = conn.execute(
                "SELECT m.id, m.college_name, m.kind, m.city, m.state, m.college_type, "
                "m.logo_url, f.added_at "
                "FROM pg_college_favorites f JOIN pg_college_master m ON m.id = f.master_id "
                "WHERE f.user_id = ? ORDER BY f.added_at DESC", [uid]).fetchall()
            favs = [{'id': r['id'], 'name': r['college_name'], 'kind': r['kind'],
                     'city': r['city'], 'state': r['state'], 'college_type': r['college_type'],
                     'logo_url': r['logo_url'], 'added_at': str(r['added_at'])} for r in rows]
            return jsonify({'ok': True, 'favorites': favs, 'count': len(favs)})
        # POST — add one
        body = request.get_json(silent=True) or {}
        try:
            mid = int(body.get('master_id'))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'master_id required'}), 400
        if not conn.execute("SELECT 1 FROM pg_college_master WHERE id = ?", [mid]).fetchone():
            return jsonify({'ok': False, 'error': 'unknown master_id'}), 404
        conn.execute("INSERT INTO pg_college_favorites (user_id, master_id) VALUES (?, ?) "
                     "ON CONFLICT (user_id, master_id) DO NOTHING", [uid, mid])
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_college_favorites: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pg_college_favorite_delete(master_id):
    """DELETE /api/pg/college-favorites/<master_id> → remove one (X-PG-Key + Bearer)."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    tok = _bearer_token()
    if not tok:
        return jsonify({'ok': False, 'error': 'no_token'}), 401
    conn = get_db()
    try:
        user = _pg_user_by_token(conn, tok)
        if not user:
            return jsonify({'ok': False, 'error': 'invalid_token'}), 401
        conn.execute("DELETE FROM pg_college_favorites WHERE user_id = ? AND master_id = ?",
                     [user['id'], master_id])
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_college_favorite_delete: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
