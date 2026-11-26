"""Public /api/pg/seat-matrix* endpoints — the goocampus.in dashboard reads the
raw NEET-PG counselling Seat Matrix here (founder 2026-09-30).

Data is served VERBATIM from pg_seat_matrix (authority's own college/course names,
unmatched to our master). X-PG-Key guarded, except the PDF stream which is a public
government document (so the user's browser can open it directly).
"""
import collections
import logging
from flask import request, jsonify, Response
from db import get_db
from pg_admin.routes.api import _authorized, smart_name_clause, HIDE_DNB

# DNB COURSES (e.g. Rajasthan's Post-MBBS DNB) are hidden from doctors like everywhere else (HIDE_DNB).
# Only the course decides: MCC's "DNB (Govt.) PG" institute type is MD/MS courses at DNB-accredited
# government hospitals — those stay. Param-less (POSITION, no literal %). (2026-10-23)
_NO_DNB = ("(POSITION('DNB' IN UPPER(COALESCE(course_name,''))) <> 1 "
           "AND POSITION('NBEMS' IN UPPER(COALESCE(course_name,''))) = 0 AND COALESCE(section,'') <> 'dnb')")


_ONLY_DNB = "NOT " + _NO_DNB


def _dnb_cond(conn=None, body=None, program=None):
    """DNB on the seat matrix is shown FOR INFORMATION, like results (founder 2026-10-30): program=dnb → only
    the DNB lines; a matrix that is all DNB (MCC's DNB file, section 'dnb') → every line; otherwise DNB is
    left out. Predictor / choice lists / rankings never show DNB (HIDE_DNB elsewhere)."""
    if (program or '').lower() == 'dnb':
        return [_ONLY_DNB]
    if conn is not None and body:
        try:
            r = conn.execute("SELECT COALESCE(section,'') AS section FROM pg_seat_matrix_source "
                             "WHERE counselling_body=? ORDER BY academic_year DESC LIMIT 1", [body]).fetchone()
            if r and r['section'] == 'dnb':
                return []
        except Exception:
            try: conn.rollback()
            except Exception: pass
    return [_NO_DNB] if HIDE_DNB else []

_ROUND_OK = {'v': False}


def _round_cols(conn):
    """True once the later-round columns exist (boot DDL can be skipped on a Render cold start — never let
    the seat matrix break because of it; cached only once present)."""
    if _ROUND_OK['v']:
        return True
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_name='pg_seat_matrix_source' "
                         "AND column_name IN ('round_no','round_label','list_type','pdf_body')").fetchone()['n']
        m = conn.execute("SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_name='pg_seat_matrix' "
                         "AND column_name='new_in_round'").fetchone()['n']
        _ROUND_OK['v'] = (int(n) == 4 and int(m) == 1)
    except Exception:
        try: conn.rollback()
        except Exception: pass
    return _ROUND_OK['v']


def _rounds(conn, year):
    """Every counselling round with a seat list, per authority (founder 2026-11-11): round 1 = the full
    matrices (current cards), later rounds = the vacancy lists stored with superseded=2.
    [{authority_code, round_no, round_label, list_type, bodies:[{counselling_body, section, total_seats,
      dnb_seats, has_pdf, uploaded_at, new_in_round_seats, round1_seats}]}]"""
    if not _round_cols(conn):
        return []
    src = [dict(r) for r in conn.execute(
        "SELECT counselling_body, COALESCE(authority_code,'') AS authority_code, COALESCE(section,'') AS section, "
        "COALESCE(round_no,1) AS round_no, COALESCE(round_label,'') AS round_label, COALESCE(list_type,'') AS list_type, "
        "COALESCE(sort_order,0) AS sort_order, (pdf_data IS NOT NULL OR COALESCE(pdf_body,'')<>'') AS has_pdf, "
        "uploaded_at, total_seats FROM pg_seat_matrix_source WHERE academic_year=? "
        "AND COALESCE(superseded,0) IN (0,2) AND COALESCE(section,'') <> 'nmc_initial' "
        "ORDER BY (COALESCE(authority_code,'')<>'mcc'), authority_code, COALESCE(round_no,1), "
        "COALESCE(sort_order,0), counselling_body", [year]).fetchall()]
    if not src:
        return []
    agg = {r['counselling_body']: r for r in conn.execute(
        "SELECT counselling_body, COALESCE(SUM(CASE WHEN " + _NO_DNB + " THEN seats ELSE 0 END),0) AS md, "
        "COALESCE(SUM(CASE WHEN " + _ONLY_DNB + " THEN seats ELSE 0 END),0) AS dnb, "
        "COALESCE(SUM(CASE WHEN " + _NO_DNB + " THEN COALESCE(new_in_round,0) ELSE 0 END),0) AS nr, "
        "COALESCE(SUM(CASE WHEN " + _ONLY_DNB + " THEN COALESCE(new_in_round,0) ELSE 0 END),0) AS nr_dnb, "
        "COUNT(DISTINCT CASE WHEN " + _NO_DNB + " THEN COALESCE(NULLIF(college_code,''), college_name) END) AS c_md, "
        "COUNT(DISTINCT CASE WHEN " + _ONLY_DNB + " THEN COALESCE(NULLIF(college_code,''), college_name) END) AS c_dnb "
        "FROM pg_seat_matrix WHERE academic_year=? GROUP BY counselling_body", [year]).fetchall()}
    def seats(b, section):
        a = agg.get(b)
        if not a:
            return 0, 0, 0
        md, dn = int(a['md'] or 0), int(a['dnb'] or 0)
        nr = int((a['nr_dnb'] if section == 'dnb' else a['nr']) or 0)     # DNB body counts its DNB lines
        return (dn if section == 'dnb' else md), dn, nr
    r1 = {}
    for x in src:
        if x['round_no'] == 1:
            r1[(x['authority_code'], x['section'])] = seats(x['counselling_body'], x['section'])[0]
    out, idx = [], {}
    for x in src:
        k = (x['authority_code'], x['round_no'])
        if k not in idx:
            idx[k] = {'authority_code': x['authority_code'], 'round_no': x['round_no'],
                      'round_label': x['round_label'] or ('Round 1 — full seat matrix' if x['round_no'] == 1
                                                          else f"Round {x['round_no']}"),
                      'list_type': x['list_type'] or ('matrix' if x['round_no'] == 1 else 'vacancy'), 'bodies': []}
            out.append(idx[k])
        tot, dn, nr = seats(x['counselling_body'], x['section'])
        _a = agg.get(x['counselling_body']) or {}
        cc = int((_a.get('c_dnb') if x['section'] == 'dnb' else _a.get('c_md')) or 0)   # colleges in this list (2026-11-19)
        idx[k]['bodies'].append({
            'counselling_body': x['counselling_body'], 'section': x['section'], 'total_seats': tot,
            'college_count': cc,
            'dnb_seats': dn, 'has_pdf': bool(x['has_pdf']), 'uploaded_at': str(x['uploaded_at'] or '')[:16],
            'new_in_round_seats': nr if x['round_no'] > 1 else 0,
            'round1_seats': r1.get((x['authority_code'], x['section'])) if x['round_no'] > 1 else None})
    return out


# Round summary line (founder 2026-11-26, MCC first — other authorities after he reviews it): under each round's
# seat list, how many seats were allotted and how many are left. MD/MS + Diploma only (DNB hidden, like the lists).
#   Round 1:  seats = full matrix; allotted = Round 1 result lines; left = seats - allotted (exact).
#   Round 2+: seats = that round's official vacant list; the round also re-allots the seats doctors give up when they
#             upgrade, so available = list + upgraded; allotted = fresh + upgraded; left = available - allotted,
#             floored at 0 — an ESTIMATE (joining / not joining / resignations are unknown) until the authority
#             publishes the next round's list, then left = that list minus its newly added seats (OFFICIAL).
#   back_on_next_list: the share of this round's seats that came back on the next official list (clinical /
#   non-clinical split) — the market trend.
SUMMARY_AUTHS = ('mcc',)


def _round_summaries(conn, year, rounds):
    from pg_admin.data import specialty_groups as SG
    by_auth = {}
    for rd in rounds:
        if rd['authority_code'] in SUMMARY_AUTHS:
            by_auth.setdefault(rd['authority_code'], {})[int(rd['round_no'])] = rd
    if not by_auth:
        return
    ctx = None
    for auth, rds in by_auth.items():
        try:
            res = collections.defaultdict(collections.Counter)
            rinfo = {}
            for r in conn.execute(
                    "SELECT s.round_order AS ro, s.round, s.status, COALESCE(r.round_status,'') AS st, COUNT(*) AS n "
                    "FROM pg_results r JOIN pg_results_source s ON s.authority_code=r.authority_code "
                    "AND s.academic_year=r.academic_year AND s.round=r.round WHERE r.authority_code=? "
                    "AND r.academic_year=? AND COALESCE(s.is_hidden,0)=0 AND s.round NOT LIKE '%%(%%' "
                    "AND COALESCE(r.section,'')<>'dnb' GROUP BY 1,2,3,4", [auth, year]).fetchall():
                res[int(r['ro'])][r['st']] += int(r['n'])
                rinfo[int(r['ro'])] = {'round': r['round'], 'status': r['status'] or 'provisional'}
            per_course = {}
            for r in conn.execute(
                    "SELECT COALESCE(s.round_no,1) AS rn, COALESCE(NULLIF(m.cutoff_course,''), m.course_name) AS c, "
                    "SUM(m.seats) AS n, SUM(COALESCE(m.new_in_round,0)) AS nr FROM pg_seat_matrix m "
                    "JOIN pg_seat_matrix_source s ON s.counselling_body=m.counselling_body AND s.academic_year=m.academic_year "
                    "WHERE s.academic_year=? AND COALESCE(s.authority_code,'')=? AND COALESCE(s.superseded,0) IN (0,2) "
                    "AND COALESCE(s.section,'') NOT IN ('nmc_initial','dnb') AND " + _NO_DNB.replace('course_name', 'm.course_name')
                    .replace("COALESCE(section", "COALESCE(m.section") + " GROUP BY 1,2", [year, auth]).fetchall():
                per_course.setdefault(int(r['rn']), {})[r['c']] = (int(r['n'] or 0), int(r['nr'] or 0))
        except Exception as e:
            try: conn.rollback()
            except Exception: pass
            logging.warning("_round_summaries %s: %s", auth, e)
            continue
        if ctx is None:
            ctx = SG.context(conn, year)
        def split(rn, net=False):
            out = collections.Counter()
            for c, (n, nr) in (per_course.get(rn) or {}).items():
                g = SG.public_group(SG.group_of(c, ctx)) or 'clinical'
                out[g] += (n - nr) if net else n
            return out
        for rn, rd in sorted(rds.items()):
            seats = sum(b['total_seats'] for b in rd['bodies'] if b['section'] != 'dnb')
            added = sum(b['new_in_round_seats'] for b in rd['bodies'] if b['section'] != 'dnb')
            c = res.get(rn)
            sm = {'seats': seats, 'added_seats': added, 'result': rinfo.get(rn)}
            if not c:
                sm.update(allotted=None, left=None, basis='results_awaited')
            elif rn == 1:
                al = sum(c.values())
                sm.update(allotted=al, left=max(0, seats - al), basis='exact',
                          pct_allotted=round(100 * al / seats) if seats else None)
            else:
                fresh, up, kept = c.get('fresh', 0), c.get('upgraded', 0), c.get('retained', 0)
                al, avail = fresh + up, seats + up
                sm.update(allotted=al, fresh=fresh, upgraded=up, retained=kept, freed_by_upgrades=up,
                          available=avail, left=max(0, avail - al), basis='estimate',
                          over_available=max(0, al - avail),
                          pct_allotted=min(100, round(100 * al / avail)) if avail else None)
            nxt = rds.get(rn + 1)
            if nxt:
                nb = sum(b['total_seats'] for b in nxt['bodies'] if b['section'] != 'dnb')
                na = sum(b['new_in_round_seats'] for b in nxt['bodies'] if b['section'] != 'dnb')
                back = max(0, nb - na)
                a, b2 = split(rn), split(rn + 1, net=True)
                sm['back_on_next_list'] = {
                    'round_no': rn + 1, 'seats': back, 'pct': round(100 * back / seats) if seats else None,
                    'clinical_pct': round(100 * b2['clinical'] / a['clinical']) if a['clinical'] else None,
                    'non_clinical_pct': round(100 * b2['non_clinical'] / a['non_clinical']) if a['non_clinical'] else None}
                if rn >= 2 and c:          # the next official list replaces the estimate
                    sm.update(left=back, basis='official',
                              pct_allotted=round(100 * (1 - back / sm['available'])) if sm.get('available') else None)
            rd['summary'] = sm


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
    new_round_only = _s(request.args.get('new_round_only')) in ('1', 'true', 'yes')
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

    program = _s(request.args.get('program'))
    _c = get_db()
    try:
        dnb = _dnb_cond(_c, body, program)
    finally:
        _c.close()
    conds = ["counselling_body = ?", "academic_year = ?"] + dnb
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
    _c = get_db()
    try:
        has_round = _round_cols(_c)
    finally:
        _c.close()
    if new_round_only and has_round:          # seats NEWLY ADDED in this later round (2026-11-11)
        conds.append("COALESCE(new_in_round,0) > 0")
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
            f"institute_type, quota, category_code, course_code, has_cutoff, new_reason, cutoff_institute, cutoff_course, "
            f"cr_r1, cr_r2, cr_r3, cr_closing, cutoff_fee, cutoff_quota"
            f"{', COALESCE(new_in_round,0) AS new_in_round' if has_round else ''} "
            f"FROM pg_seat_matrix WHERE {where} "
            f"ORDER BY state ASC, college_name ASC, course_name ASC, id ASC "
            f"LIMIT {page_size} OFFSET {offset}", params).fetchall()
        out = []
        for r in rows:
            r = dict(r)
            if r.get('cutoff_fee') is not None:
                r['cutoff_fee'] = float(r['cutoff_fee'])
            # has_cutoff: 1 = bridged to the 2025 cut-off; 0 = new in 2026; None = not analysed
            r['is_new'] = (r.get('has_cutoff') == 0)
            r['new_in_round'] = int(r.get('new_in_round') or 0)      # later round: newly added seats on this line
            # Simple type for "seats by college type" splits (MCC's institute_type is only
            # All-India / Central University / Deemed University).
            it = (r.get('institute_type') or '').lower()
            r['college_type'] = ('Deemed' if 'deemed' in it else 'Central University' if it.startswith('central')
                                 else 'Private' if 'private' in it else 'Government' if it else '')
            out.append(r)
        # 2025 closing ranks: All-India first + the state rank for state-rank authorities (founder 2026-11-01)
        from pg_admin.data import rank_bridge as _RB
        _RB.present_seat_rows(conn, body, out)
        # fee to show: the verified 2026-27 fee for this seat, else the 2025 cut-off fee (cutoff_fee stays = 2025)
        from pg_admin.data import fees as _FEES
        for r in out:
            r['fee'] = r.get('cutoff_fee')
            r['fee_year'] = 2025 if r.get('cutoff_fee') is not None else None
        _FEES.attach(conn, out, authority=_FEES.seat_matrix_authority(body), inst='college_name',
                     course='course_name', quota='quota', category='category',
                     alt=('cutoff_institute', 'cutoff_course', 'cutoff_quota'))
        for r in out:
            r.pop('cutoff_quota', None)
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
        dnb = _dnb_cond(conn, body, request.args.get('program'))
        base = "FROM pg_seat_matrix WHERE counselling_body=? AND academic_year=?" + \
               ''.join(' AND ' + c for c in dnb)
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
        from pg_admin.routes.seat_matrix_ingest import ensure_prev_cols, change_payload
        ensure_prev_cols(conn)
        src = conn.execute(
            "SELECT source_file_name, pdf_name, uploaded_at, "
            "(pdf_data IS NOT NULL) AS has_pdf, row_count, college_count, total_seats, "
            "prev_row_count, prev_college_count, prev_total_seats, prev_replaced_at, prev_source_file_name, "
            "colleges_added, colleges_removed "
            "FROM pg_seat_matrix_source WHERE counselling_body=? AND academic_year=?",
            (body, year)).fetchone()
        src = dict(src) if src else None
        if src and dnb:                  # the file's totals as doctors see them (this view's DNB rule)
            src['row_count'], src['college_count'], src['total_seats'] = \
                int(agg['rows'] or 0), int(agg['colleges'] or 0), int(agg['seats'] or 0)
        chg = change_payload(src)
        rounds, this_round = [], None
        if _round_cols(conn):
            rounds = _rounds(conn, year)
            _round_summaries(conn, year, rounds)
            tr = conn.execute(
                "SELECT COALESCE(round_no,1) AS round_no, COALESCE(round_label,'') AS round_label, "
                "COALESCE(list_type,'') AS list_type, COALESCE(pdf_body,'') AS pdf_body, "
                "COALESCE(authority_code,'') AS authority_code, COALESCE(section,'') AS section "
                "FROM pg_seat_matrix_source WHERE counselling_body=? AND academic_year=?", (body, year)).fetchone()
            if tr:
                this_round = dict(tr)
                nr = conn.execute(f"SELECT COALESCE(SUM(COALESCE(new_in_round,0)),0) AS n {base}", p).fetchone()
                this_round['new_in_round_seats'] = int(nr['n'] or 0)
                if this_round['round_no'] > 1:
                    for rd in rounds:
                        for b in rd['bodies']:
                            if b['counselling_body'] == body:
                                this_round['round1_seats'] = b['round1_seats']
        # All bodies/years available (for a top-level switcher)
        # Current matrices only (an older provisional one that was superseded is hidden).
        available = [dict(r) for r in conn.execute(
            "SELECT counselling_body, academic_year, row_count, college_count, total_seats, "
            "(pdf_data IS NOT NULL) AS has_pdf, uploaded_at, COALESCE(section,'') AS section, "
            "COALESCE(authority_code,'') AS authority_code, COALESCE(sort_order,0) AS sort_order, "
            "COALESCE(to_jsonb(pg_seat_matrix_source)->>'display_label', '') AS label, "
            "prev_row_count, prev_college_count, prev_total_seats, prev_replaced_at, prev_source_file_name, "
            "colleges_added, colleges_removed "
            "FROM pg_seat_matrix_source WHERE COALESCE(superseded,0)=0 "
            "ORDER BY academic_year DESC, (COALESCE(authority_code,'')<>'mcc'), "
            "COALESCE(sort_order,0), counselling_body ASC").fetchall()]
        if HIDE_DNB and available:       # every card's totals without DNB courses (one grouped query)
            live = {(r['counselling_body'], r['academic_year']): r for r in conn.execute(
                "SELECT counselling_body, academic_year, COUNT(*) AS n, COALESCE(SUM(seats),0) AS s, "
                "COUNT(DISTINCT college_code||'|'||college_name) AS c FROM pg_seat_matrix WHERE " + _NO_DNB +
                " GROUP BY counselling_body, academic_year").fetchall()}
            dnb_seats = {(r['counselling_body'], r['academic_year']): int(r['s'] or 0) for r in conn.execute(
                "SELECT counselling_body, academic_year, COALESCE(SUM(seats),0) AS s FROM pg_seat_matrix WHERE "
                + _ONLY_DNB + " GROUP BY counselling_body, academic_year").fetchall()}
            for a in available:
                k = (a['counselling_body'], a['academic_year'])
                a['dnb_seats'] = dnb_seats.get(k, 0)      # DNB lines in this file (view with program=dnb)
                v = live.get(k)
                if v and a['section'] != 'dnb':          # an all-DNB matrix (MCC DNB) keeps the file's totals
                    a['row_count'], a['total_seats'], a['college_count'] = int(v['n']), int(v['s']), int(v['c'])
        return jsonify({
            'ok': True,
            'counselling_body': body, 'academic_year': year,
            'states': states, 'categories': categories, 'courses': courses,
            'quotas': quotas, 'institute_types': itypes,
            'totals': {'rows': agg['rows'], 'colleges': agg['colleges'],
                       'seats': int(agg['seats'] or 0),
                       'new_seats': int(agg['new_seats'] or 0),
                       'new_colleges': int(agg['new_colleges'] or 0)},
            'source': ({k: v for k, v in src.items() if not k.startswith('prev_') and k not in
                        ('colleges_added', 'colleges_removed')} if src else None),
            # "what changed" vs the version this file replaced (null when there was none) — 2026-10-21
            'previous': chg['previous'], 'change': chg['change'],
            'available': [{**{k: v for k, v in a.items() if not k.startswith('prev_') and k not in
                              ('colleges_added', 'colleges_removed')}, **change_payload(a)} for a in available],
            'has_pdf': bool(src and src['has_pdf']) or bool(this_round and this_round.get('pdf_body')),
            # counselling rounds (Round 1 full matrix, Round 2 vacancy, ...) for a Round switch — 2026-11-11
            'round': this_round, 'rounds': rounds,
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
    from pg_admin.routes.api import file_key_block
    blk = file_key_block()
    if blk:
        return blk
    year = _s(request.args.get('year')) or DEFAULT_YEAR
    conn = get_db()
    try:
        body = _s(request.args.get('body')) or _default_body(conn, year)
        row = conn.execute(
            "SELECT pdf_name, pdf_data, pdf_content_type FROM pg_seat_matrix_source "
            "WHERE counselling_body=? AND academic_year=?", (body, year)).fetchone()
        if (not row or not row['pdf_data']) and _round_cols(conn):
            # one official file split into sections (MCC Round 2 vacancy) → serve the body that holds it
            pb = conn.execute("SELECT COALESCE(pdf_body,'') AS b FROM pg_seat_matrix_source "
                              "WHERE counselling_body=? AND academic_year=?", (body, year)).fetchone()
            if pb and pb['b']:
                row = conn.execute(
                    "SELECT pdf_name, pdf_data, pdf_content_type FROM pg_seat_matrix_source "
                    "WHERE counselling_body=? AND academic_year=?", (pb['b'], year)).fetchone()
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
