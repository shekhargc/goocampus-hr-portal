"""NEET-PG 2026 counselling RESULTS — import + the dashboard / counsellor APIs (founder 2026-10-24).

Import (X-News-Key, from the team's Mac — tools/results/):
  POST /api/pg/results/ingest       one authority + round: rows as published + the official PDF.
                                    College and course names are resolved here through the name memory
                                    (pg_admin/name_memory.py) so every authority's spelling lands on one
                                    standard name; unsure names wait in /admin/pg/name-memory.
Read (X-PG-Key, goocampus.in dashboard + Counselling Desk):
  GET /api/pg/results/rounds        which results exist (authority, round, provisional/final)
  GET /api/pg/results               search allotments (rank, college, course, quota, category, state, type)
  GET /api/pg/results/facets        filter values for one round
  GET /api/pg/results/rank          every allotment for one rank (also ?me=1 with the doctor's token)
  GET /api/pg/results/cutoffs       2026 closing rank per college × course × quota × category, next to the
                                    2025 closing rank of the SAME round, with the change (+ ?rank= "open at
                                    your rank")
  GET /api/pg/results/trends        the same comparison summed up by course / state / college type + movers
  GET /api/pg/results/leftover      seat matrix seats minus seats allotted so far = seats left for next round
DNB courses stay hidden from doctors (HIDE_DNB), like everywhere else.
"""
import base64
import logging
import statistics
from collections import defaultdict, Counter
from flask import request, jsonify, render_template, redirect, url_for, flash
from db import get_db
from core.auth import login_required
from pg_admin import name_memory as NM

YEAR = '2026-27'
ROUND_COL = {1: 'r1', 2: 'r2', 3: 'r3', 4: 'r4'}      # 2025 cut-off column for the same round


def _s(v):
    return str(v).strip() if v is not None else ''


def _int(v):
    try:
        return int(str(v).replace(',', '').strip())
    except (TypeError, ValueError):
        return None


def _college_type(it):
    it = (it or '').lower()
    if 'deemed' in it:
        return 'Deemed'
    if it.startswith('central'):
        return 'Central University'
    if 'private' in it:
        return 'Private'
    if 'afms' in it or 'armed' in it:
        return 'Armed Forces'
    return 'Government' if it else ''


def cutoff_authority(code):
    """Our authority code → the authority label used in the 2025 cut-offs ('MCC (All India)', 'Karnataka', …)."""
    if code == 'mcc':
        return 'MCC (All India)'
    from pg_admin.authorities import get_authority
    a = get_authority(code) or {}
    return (a.get('state') if isinstance(a, dict) else a[2]) or ''


def _qn(q):
    """2025 cut-offs split NRI into 'NRI Quota - Priority 1/2'; results and comparisons use one 'NRI Quota'."""
    return 'NRI Quota' if (q or '').startswith('NRI Quota') else (q or '')


def _college_info(conn, names):
    """standard name → (state, college type), from the cut-offs, else the College Database."""
    out = {}
    if not names:
        return out
    for r in conn.execute("SELECT institute, MAX(state) AS state, MAX(institute_type) AS it FROM pg_cutoffs "
                          "WHERE institute = ANY(?) GROUP BY institute", [list(names)]).fetchall():
        out[r['institute']] = (r['state'] or '', _college_type(r['it']))
    rest = [n for n in names if n not in out]
    if rest:
        for r in conn.execute("SELECT college_name, MAX(state) AS state, MAX(college_type) AS it FROM pg_college_master "
                              "WHERE kind='medical' AND college_name = ANY(?) GROUP BY college_name", [rest]).fetchall():
            out[r['college_name']] = (r['state'] or '', _college_type(r['it']))
    return out


def _display_college(r):
    """Standard name, else the name exactly as published. DNB hospitals are never renamed: always MCC's full text
    (founder 2026-10-24 — the site bolds the part before the first comma)."""
    if r.get('section') == 'dnb':
        return r.get('institute_raw') or ''
    return r.get('institute') or r.get('institute_raw') or ''


def _program(a):
    """program=dnb → DNB seats only (DNB quota: DNB, DNB Diploma, post-MBBS DNB); default MD/MS + diploma."""
    return ["COALESCE(r.section,'') = 'dnb'"] if _s(a.get('program')).lower() == 'dnb' else _hide_dnb()


def _apply_memory(conn, fixed):
    """Write newly matched names onto results already imported (+ state / type), and refresh match counts."""
    for (kind, raw_key), std in fixed.items():
        col, scol = ('institute', 'institute_raw') if kind == 'college' else ('course', 'course_raw')
        conn.execute(f"UPDATE pg_results SET {col}=? WHERE COALESCE({col},'')='' AND "
                     f"btrim(regexp_replace(lower({scol}), '[^a-z0-9]+', ' ', 'g'))=?", [std, raw_key])
        if kind == 'college':
            info = _college_info(conn, {std}).get(std)
            if info:
                conn.execute("UPDATE pg_results SET state=?, college_type=? WHERE institute=?", [info[0], info[1], std])
    conn.execute("UPDATE pg_results_source s SET matched_rows=(SELECT COUNT(*) FROM pg_results r WHERE "
                 "r.authority_code=s.authority_code AND r.academic_year=s.academic_year AND r.round=s.round "
                 "AND (r.section='dnb' OR (COALESCE(r.institute,'')<>'' AND COALESCE(r.course,'')<>'')))")


def _ensure():
    from pg_admin.data.results_tables import ensure_results_tables
    ensure_results_tables()


# ───────────────────────────── import ─────────────────────────────
_ROW = ('sno', 'rank', 'quota_raw', 'quota', 'institute_raw', 'course_raw', 'section', 'allotted_category',
        'allotted_category_raw', 'candidate_category', 'remarks')


def api_results_ingest():
    """POST /api/pg/results/ingest (X-News-Key)
    {authority_code, year, round, round_order, status: provisional|final, title, published_on,
     source_file_name, pdf_name, pdf_b64, notes, rows:[{sno, rank, quota_raw, quota, institute_raw,
     course_raw, section, allotted_category, allotted_category_raw, candidate_category, remarks}]}
    Replaces that one (authority, year, round). Big lists go in parts so no request runs long:
    mode 'start' (clears the round, inserts its rows) → 'append' … → 'finish' (rows optional; saves the
    source row + PDF, counts taken from what is stored). No mode = all in one call."""
    from pg_admin.routes.api_news_ingest import _ok
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    d = request.get_json(silent=True) or {}
    auth, rnd = _s(d.get('authority_code')), _s(d.get('round'))
    year = _s(d.get('year')) or YEAR
    rows = d.get('rows') or []
    mode = _s(d.get('mode')) or 'all'
    if mode not in ('all', 'start', 'append', 'finish'):
        return jsonify({'ok': False, 'error': 'bad mode'}), 400
    if not auth or not rnd or (not rows and mode != 'finish'):
        return jsonify({'ok': False, 'error': 'authority_code, round and rows required'}), 400
    pdf = None
    if d.get('pdf_b64'):
        try:
            pdf = base64.b64decode(d['pdf_b64'])
        except Exception:
            return jsonify({'ok': False, 'error': 'bad pdf_b64'}), 400
    _ensure()
    conn = get_db()
    try:
        # DNB hospitals are hidden from doctors and are not in our college list — keep them as published
        # (matching them would only flood the review queue). An importer's explicit standard name wins
        # and is remembered.
        if mode in ('all', 'start'):
            NM.seed(conn)                 # what the seat matrices already matched (never overwrites)
        listed = [r for r in rows if _s(r.get('section')) != 'dnb']
        for kind, raw_f, std_f in (('college', 'institute_raw', 'institute'), ('course', 'course_raw', 'course')):
            for raw, std in {(_s(r.get(raw_f)), _s(r.get(std_f))) for r in listed if _s(r.get(std_f)) and _s(r.get(raw_f))}:
                NM.teach(conn, kind, raw, std, auth)
        colleges = NM.resolve(conn, 'college', [_s(r.get('institute_raw')) for r in listed], auth)
        courses = NM.resolve(conn, 'course', [_s(r.get('course_raw')) for r in listed], auth)
        info = _college_info(conn, {v['std'] for v in colleges.values() if v['std']})
        old = conn.execute("SELECT status, row_count FROM pg_results_source WHERE authority_code=? AND academic_year=? "
                           "AND round=?", [auth, year, rnd]).fetchone()
        if mode in ('all', 'start'):
            conn.execute("DELETE FROM pg_results WHERE authority_code=? AND academic_year=? AND round=?", [auth, year, rnd])
        batch, matched = [], 0
        for r in rows:
            ir, cr = _s(r.get('institute_raw')), _s(r.get('course_raw'))
            dnb = _s(r.get('section')) == 'dnb'
            inst = '' if dnb else (colleges.get(ir) or {}).get('std', '')
            course = _s(r.get('course')) if dnb else (courses.get(cr) or {}).get('std', '')
            st, ct = info.get(inst, ('', ''))
            matched += 1 if (inst and course) or dnb else 0
            batch.append([auth, year, rnd, _int(r.get('sno')), _int(r.get('rank')), _int(r.get('rank_ai')),
                          _s(r.get('quota_raw')),
                          _s(r.get('quota')), ir, inst, st, ct, cr, course, _s(r.get('section')) or 'mdms',
                          _s(r.get('allotted_category')), _s(r.get('allotted_category_raw')),
                          _s(r.get('candidate_category')), _s(r.get('remarks'))])
        if batch:
            conn.execute_batch(
                "INSERT INTO pg_results (authority_code, academic_year, round, sno, rank, rank_ai, quota_raw, quota, "
                "institute_raw, institute, state, college_type, course_raw, course, section, allotted_category, "
                "allotted_category_raw, candidate_category, remarks) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                batch, page_size=1000)
        if mode in ('start', 'append'):
            conn.commit()
            return jsonify({'ok': True, 'mode': mode, 'rows': len(rows), 'matched_rows': matched,
                            'colleges_to_review': sorted({k for k, v in colleges.items() if v['status'] != 'ok'})})
        if mode == 'finish':        # counts from everything stored for this round
            t = conn.execute("SELECT COUNT(*) AS n, SUM(CASE WHEN section='dnb' OR (COALESCE(institute,'')<>'' AND "
                             "COALESCE(course,'')<>'') THEN 1 ELSE 0 END) AS m FROM pg_results WHERE authority_code=? "
                             "AND academic_year=? AND round=?", [auth, year, rnd]).fetchone()
            n_rows, matched = int(t['n'] or 0), int(t['m'] or 0)
        else:
            n_rows = len(rows)
        vals = [int(d.get('round_order') or 1), _s(d.get('status')) or 'provisional', _s(d.get('title')),
                _s(d.get('published_on')), _s(d.get('source_file_name')), _s(d.get('pdf_name')), n_rows, matched,
                _s(d.get('notes'))]
        src = conn.execute("SELECT id FROM pg_results_source WHERE authority_code=? AND academic_year=? AND round=?",
                           [auth, year, rnd]).fetchone()
        if src:
            conn.execute("UPDATE pg_results_source SET round_order=?, status=?, title=?, published_on=?, "
                         "source_file_name=?, pdf_name=?, row_count=?, matched_rows=?, notes=?, "
                         "uploaded_at=CURRENT_TIMESTAMP WHERE id=?", vals + [src['id']])
            sid = src['id']
        else:
            sid = conn.execute("INSERT INTO pg_results_source (round_order, status, title, published_on, source_file_name, "
                               "pdf_name, row_count, matched_rows, notes, authority_code, academic_year, round) "
                               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id", vals + [auth, year, rnd]).fetchone()['id']
        if old:
            conn.execute("UPDATE pg_results_source SET prev_status=?, prev_row_count=?, prev_replaced_at=CURRENT_TIMESTAMP "
                         "WHERE id=?", [old['status'] or '', old['row_count'], sid])
        if pdf:
            conn.execute("UPDATE pg_results_source SET pdf_data=? WHERE id=?", [pdf, sid])
        conn.commit()
        need = sorted({k for k, v in colleges.items() if v['status'] != 'ok'})
        needc = sorted({k for k, v in courses.items() if v['status'] != 'ok'})
        how = defaultdict(int)
        for v in colleges.values():
            how[v['how'] + ('' if v['status'] == 'ok' else '_' + v['status'])] += 1
        return jsonify({'ok': True, 'rows': n_rows, 'matched_rows': matched, 'colleges': len(colleges),
                        'college_match': dict(how), 'colleges_to_review': need[:60], 'colleges_to_review_n': len(need),
                        'courses_to_review': needc, 'replaced': dict(old) if old else None})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_results_ingest: %s", e)
        return jsonify({'ok': False, 'error': 'server_error', 'detail': str(e)[:300]}), 500
    finally:
        conn.close()


def api_name_memory_seed():
    """POST /api/pg/name-memory/seed (X-News-Key) — fill the memory from what is already matched."""
    from pg_admin.routes.api_news_ingest import _ok
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    _ensure()
    conn = get_db()
    try:
        n = NM.seed(conn)
        fixed = NM.rematch_pending(conn)          # review names that today's standards now recognise
        _apply_memory(conn, fixed)
        n['rematched'] = {k[1]: v for k, v in fixed.items()}
        conn.commit()
        tot = conn.execute("SELECT kind, status, COUNT(*) AS n FROM pg_name_memory GROUP BY kind, status").fetchall()
        return jsonify({'ok': True, 'seeded': n, 'memory': [dict(r) for r in tot]})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_name_memory_seed: %s", e)
        return jsonify({'ok': False, 'error': 'server_error', 'detail': str(e)[:300]}), 500
    finally:
        conn.close()


# ───────────────────────────── read APIs ─────────────────────────────
def _auth():
    from pg_admin.routes.api import _authorized
    return _authorized()


def _hide_dnb():
    from pg_admin.routes.api import HIDE_DNB
    return ["COALESCE(r.section,'') <> 'dnb'"] if HIDE_DNB else []


def _pick_round(conn, auth, year, rnd):
    """The round asked for, else the latest published round of that authority."""
    q = ("SELECT round, round_order, status FROM pg_results_source WHERE authority_code=? AND academic_year=? "
         "AND COALESCE(is_hidden,0)=0")
    if rnd:
        r = conn.execute(q + " AND round=?", [auth, year, rnd]).fetchone()
    else:
        r = conn.execute(q + " ORDER BY round_order DESC LIMIT 1", [auth, year]).fetchone()
    return dict(r) if r else None


def _filters(a, conds, params):
    for key, col in (('quota', 'r.quota'), ('category', 'r.allotted_category'), ('course', 'r.course'),
                     ('state', 'r.state'), ('college_type', 'r.college_type')):
        v = _s(a.get(key))
        if v:
            conds.append(f"{col} = ?"); params.append(v)
    q = _s(a.get('q'))
    if q:
        from pg_admin.routes.api import smart_name_clause
        f1, p1 = smart_name_clause("r.institute", q)
        f2, p2 = smart_name_clause("r.institute_raw", q)
        conds.append(f"(({f1}) OR ({f2}))"); params.extend(p1 + p2)


def api_results_rounds():
    if not _auth():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    _ensure()
    from pg_admin.authorities import get_authority
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT authority_code, academic_year, round, round_order, status, title, published_on, row_count, "
            "matched_rows, (pdf_data IS NOT NULL) AS has_pdf, uploaded_at, prev_status FROM pg_results_source "
            "WHERE COALESCE(is_hidden,0)=0 ORDER BY (authority_code<>'mcc'), authority_code, round_order").fetchall()
        out = []
        for r in rows:
            r = dict(r)
            a = get_authority(r['authority_code'])
            r['authority_name'] = (a.get('name') if isinstance(a, dict) else (a[1] if a else '')) or r['authority_code']
            r['state'] = (a.get('state') if isinstance(a, dict) else (a[2] if a else '')) or ''
            r['uploaded_at'] = str(r['uploaded_at'])[:16] if r.get('uploaded_at') else ''
            out.append(r)
        return jsonify({'ok': True, 'rounds': out})
    finally:
        conn.close()


def api_results():
    """GET /api/pg/results?authority=mcc&round=Round 1&rank=&rank_from=&rank_to=&q=&course=&quota=&category=
    &state=&college_type=&page=&page_size="""
    if not _auth():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    _ensure()
    a = request.args
    auth, year = _s(a.get('authority')) or 'mcc', _s(a.get('year')) or YEAR
    conn = get_db()
    try:
        rd = _pick_round(conn, auth, year, _s(a.get('round')))
        if not rd:
            return jsonify({'ok': True, 'round': None, 'rows': [], 'total_matched': 0})
        conds = ["r.authority_code=?", "r.academic_year=?", "r.round=?"] + _program(a)
        params = [auth, year, rd['round']]
        rank, rf, rt = _int(a.get('rank')), _int(a.get('rank_from')), _int(a.get('rank_to'))
        if rank:
            conds.append("r.rank = ?"); params.append(rank)
        if rf:
            conds.append("r.rank >= ?"); params.append(rf)
        if rt:
            conds.append("r.rank <= ?"); params.append(rt)
        _filters(a, conds, params)
        where = " AND ".join(conds)
        page = max(1, _int(a.get('page')) or 1)
        size = min(500, max(1, _int(a.get('page_size')) or 100))
        total = conn.execute(f"SELECT COUNT(*) AS n FROM pg_results r WHERE {where}", params).fetchone()['n']
        rows = conn.execute(
            f"SELECT r.sno, r.rank, r.rank_ai, r.quota, r.quota_raw, r.institute, r.institute_raw, r.state, r.college_type, "
            f"r.course, r.course_raw, r.section, r.allotted_category, r.candidate_category, r.remarks FROM pg_results r "
            f"WHERE {where} ORDER BY r.rank ASC NULLS LAST, r.sno LIMIT {size} OFFSET {(page - 1) * size}",
            params).fetchall()
        out = []
        for r in rows:
            r = dict(r)
            r['college'] = _display_college(r)       # standard name, else as published (DNB: before the first comma)
            r['program'] = 'dnb' if r.get('section') == 'dnb' else 'mdms'
            r['course_name'] = r['course'] or r['course_raw']
            out.append(r)
        return jsonify({'ok': True, 'authority': auth, 'round': rd, 'rows': out, 'total_matched': total,
                        'page': page, 'page_size': size, 'total_pages': (total + size - 1) // size})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_results: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_results_facets():
    if not _auth():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    _ensure()
    a = request.args
    auth, year = _s(a.get('authority')) or 'mcc', _s(a.get('year')) or YEAR
    conn = get_db()
    try:
        rd = _pick_round(conn, auth, year, _s(a.get('round')))
        if not rd:
            return jsonify({'ok': True, 'round': None})
        base = " AND ".join(["r.authority_code=?", "r.academic_year=?", "r.round=?"] + _program(a))
        p = [auth, year, rd['round']]
        out = {'ok': True, 'round': rd}
        for key, col in (('quotas', 'r.quota'), ('categories', 'r.allotted_category'), ('courses', 'r.course'),
                         ('states', 'r.state'), ('college_types', 'r.college_type')):
            out[key] = [[x['v'], x['n']] for x in conn.execute(
                f"SELECT {col} AS v, COUNT(*) AS n FROM pg_results r WHERE {base} AND COALESCE({col},'')<>'' "
                f"GROUP BY {col} ORDER BY {col}", p).fetchall()]
        t = conn.execute(f"SELECT COUNT(*) AS n, MIN(rank) AS lo, MAX(rank) AS hi, COUNT(DISTINCT institute_raw) AS c "
                         f"FROM pg_results r WHERE {base}", p).fetchone()
        out['totals'] = {'allotted': t['n'], 'first_rank': t['lo'], 'last_rank': t['hi'], 'colleges': t['c']}
        return jsonify(out)
    finally:
        conn.close()


def api_results_rank():
    """GET /api/pg/results/rank?rank=1234 (or ?me=1 with X-PG-User-Token) → every allotment for that rank,
    all authorities and rounds (newest round first)."""
    if not _auth():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    _ensure()
    conn = get_db()
    try:
        rank = _int(request.args.get('rank'))
        if not rank and _s(request.args.get('me')) in ('1', 'true'):
            from pg_admin.routes.api import _resolve_pg_user
            uid = _resolve_pg_user(conn)
            if uid:
                u = conn.execute("SELECT neet_pg_rank FROM pg_users WHERE id=?", [uid]).fetchone()
                rank = u['neet_pg_rank'] if u else None
        if not rank:
            return jsonify({'ok': True, 'rank': None, 'allotments': []})
        rows = conn.execute(
            "SELECT r.authority_code, r.round, s.round_order, s.status, s.published_on, r.section, r.quota, r.institute, "
            "r.institute_raw, r.state, r.college_type, r.course, r.course_raw, r.allotted_category, "
            "r.candidate_category, r.remarks FROM pg_results r JOIN pg_results_source s ON s.authority_code=r.authority_code "
            "AND s.academic_year=r.academic_year AND s.round=r.round WHERE COALESCE(r.rank_ai, r.rank)=? "
            "AND COALESCE(s.is_hidden,0)=0 "
            "ORDER BY s.round_order DESC", [rank]).fetchall()
        out = []
        for r in rows:
            r = dict(r)
            r['college'] = _display_college(r)
            r['course_name'] = r['course'] or r['course_raw']
            r['program'] = 'dnb' if r.get('section') == 'dnb' else 'mdms'
            out.append(r)
        return jsonify({'ok': True, 'rank': rank, 'allotments': out,
                        'note': 'Matched on the NEET-PG All-India rank (state lists also print a state merit rank).'})
    finally:
        conn.close()


def api_results_colleges():
    """GET /api/pg/results/colleges?authority=&round=&program=dnb|mdms&q=&state=&course=&quota=&category=&page=
    → the colleges / hospitals with allotments in this round: {college, state, college_type, allotted, courses[],
    opening, closing}, most seats first."""
    if not _auth():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    _ensure()
    a = request.args
    auth, year = _s(a.get('authority')) or 'mcc', _s(a.get('year')) or YEAR
    conn = get_db()
    try:
        rd = _pick_round(conn, auth, year, _s(a.get('round')))
        if not rd:
            return jsonify({'ok': True, 'round': None, 'rows': []})
        conds = ["r.authority_code=?", "r.academic_year=?", "r.round=?"] + _program(a)
        params = [auth, year, rd['round']]
        _filters(a, conds, params)
        g = {}
        for r in conn.execute(
                f"SELECT r.institute, r.institute_raw, r.section, MAX(r.state) AS state, MAX(r.college_type) AS ct, "
                f"r.course, COALESCE(NULLIF(r.course,''), r.course_raw) AS cname, COUNT(*) AS n, MIN(r.rank) AS lo, "
                f"MAX(r.rank) AS hi FROM pg_results r WHERE {' AND '.join(conds)} "
                f"GROUP BY r.institute, r.institute_raw, r.section, r.course, r.course_raw", params).fetchall():
            name = _display_college(dict(r))
            c = g.setdefault(name, {'college': name, 'state': '', 'college_type': '', 'allotted': 0, 'courses': set(),
                                    'opening': r['lo'], 'closing': r['hi']})
            c['state'] = c['state'] or r['state'] or ''
            c['college_type'] = c['college_type'] or r['ct'] or ''
            c['allotted'] += int(r['n'] or 0)
            c['courses'].add(r['cname'])
            c['opening'] = min(c['opening'], r['lo']) if r['lo'] is not None else c['opening']
            c['closing'] = max(c['closing'], r['hi']) if r['hi'] is not None else c['closing']
        rows = sorted(g.values(), key=lambda c: (-c['allotted'], c['college']))
        for c in rows:
            c['courses'] = sorted(c['courses'])
        page = max(1, _int(a.get('page')) or 1)
        size = min(500, max(1, _int(a.get('page_size')) or 100))
        total = len(rows)
        return jsonify({'ok': True, 'authority': auth, 'round': rd,
                        'program': 'dnb' if _s(a.get('program')).lower() == 'dnb' else 'mdms',
                        'rows': rows[(page - 1) * size: page * size], 'total_matched': total, 'page': page,
                        'page_size': size, 'total_pages': (total + size - 1) // size})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_results_colleges: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def _was_in_note(auths):
    """'In 2025: Tamil Nadu state counselling' / 'In 2025: MCC (All India)' for a college new to this authority."""
    names = sorted(a for a in auths if a)
    if not names:
        return 'New to this counselling in 2026'
    return 'In 2025: ' + ', '.join(a if a.startswith('MCC') else f'{a} state counselling' for a in names)


def _closing_rows(conn, auth, year, rd, a):
    """2026 opening/closing per college × course × quota × category for this round, joined to the 2025
    closing rank of the same round."""
    conds = ["r.authority_code=?", "r.academic_year=?", "r.round=?", "COALESCE(r.course,'')<>''",
             "COALESCE(r.rank_ai, r.rank) IS NOT NULL"] + _hide_dnb()
    params = [auth, year, rd['round']]
    _filters(a, conds, params)
    # a college without a standard name only counts when the team CONFIRMED it is not in our list (a genuinely
    # new college); names still waiting in the review queue stay out until they are matched
    confirmed_new = {r['raw_key'] for r in conn.execute(
        "SELECT raw_key FROM pg_name_memory WHERE kind='college' AND status='unmatched' AND how='confirmed'").fetchall()}
    rows = []
    for r in conn.execute(
            f"SELECT r.institute, r.institute_raw, r.course, r.quota, r.allotted_category AS category, MAX(r.state) AS state, "
            f"MAX(r.college_type) AS college_type, COUNT(*) AS allotted, MIN(COALESCE(r.rank_ai, r.rank)) AS opening, "
            f"MAX(COALESCE(r.rank_ai, r.rank)) AS closing "
            f"FROM pg_results r WHERE {' AND '.join(conds)} "
            f"GROUP BY r.institute, r.institute_raw, r.course, r.quota, r.allotted_category", params).fetchall():
        r = dict(r)
        if not r['institute']:
            if NM.norm(r['institute_raw']) not in confirmed_new:
                continue
            r['institute'], r['unlisted'] = r['institute_raw'].split(',')[0].strip(), True
        rows.append(r)
    merged = {}
    for r in rows:   # one line per standard college (several MCC spellings can map to one college)
        k = (r['institute'], r['course'], r['quota'], r['category'])
        if k in merged:
            m = merged[k]
            m['allotted'] += r['allotted']; m['opening'] = min(m['opening'], r['opening'])
            m['closing'] = max(m['closing'], r['closing'])
        else:
            merged[k] = r
    rows = list(merged.values())
    col = ROUND_COL.get(int(rd.get('round_order') or 1), 'closing_rank')
    rnd_no = int(rd.get('round_order') or 1)
    # all of last year's cut-off lines for this authority, to say WHY a seat type has no direct comparison
    # and to give the nearest 2025 reference (founder 2026-10-24: keep new colleges apart from the comparison)
    prev, later, by_icq, inst, ic, icq = {}, {}, defaultdict(list), set(), set(), set()
    # every college in ANY authority's 2025 cut-offs — only a college missing from all of them is "new in 2026"
    # + where each one was counselled, for the "New in 2026" note (founder 2026-10-27: a college with no 2025
    # result HERE goes to the New tab even if another authority had it — the note says where it was)
    here = cutoff_authority(auth)
    auths_2025 = defaultdict(set)
    for c in conn.execute("SELECT DISTINCT institute, authority FROM pg_cutoffs "
                          "WHERE year=2025 AND COALESCE(institute,'')<>''").fetchall():
        auths_2025[c['institute']].add(c['authority'] or '')
    known_2025 = set(auths_2025)
    for c in conn.execute(
            "SELECT institute, course, quota, category, r1, r2, r3, r4, stray, closing_rank, fee FROM pg_cutoffs "
            "WHERE authority=? AND year=2025", [cutoff_authority(auth)]).fetchall():
        q = _qn(c['quota'])
        k = (c['institute'], c['course'], q, c['category'])
        inst.add(c['institute']); ic.add(k[:2]); icq.add(k[:3])
        v = c[col]
        if v is not None:
            if k not in prev or v > (prev[k][0] or 0):
                prev[k] = (v, c['fee'])
            by_icq[k[:3]].append((c['category'], v))
        else:
            # filled only in a later round in 2025 → the first later round that has a closing rank
            for n, rc in ((2, 'r2'), (3, 'r3'), (4, 'r4'), (5, 'stray')):
                if n > rnd_no and c[rc] is not None:
                    later.setdefault(k, (c[rc], 'Stray' if rc == 'stray' else f'Round {n}', c['fee']))
                    break
    out = []
    for r in rows:
        r.pop('institute_raw', None)
        unlisted = r.pop('unlisted', False)
        k = (r['institute'], r['course'], r['quota'], r['category'])
        p = prev.get(k)
        r['closing_2025'] = r['closing_2025_round'] = r['change'] = r['change_pct'] = None
        r['fee_2025'] = float(p[1]) if p and p[1] is not None else None
        r['filled_earlier'] = False
        if p and p[0]:
            # same seat type, same round last year — the true like-for-like comparison
            r['closing_2025'], r['closing_2025_round'], r['compare'] = p[0], rd['round'], 'direct'
        elif k in later:
            # last year this seat type was first filled in a later round → show THAT closing, with its round
            # (founder 2026-10-24: "show the rank with a bracket saying Round 2 / Round 3 / mop-up")
            v, rn, fee = later[k]
            r['closing_2025'], r['closing_2025_round'], r['compare'] = v, rn, 'later_round'
            r['fee_2025'] = float(fee) if fee is not None else r['fee_2025']
            r['filled_earlier'] = True        # 2025: needed a later round · 2026: gone in this round
        elif unlisted or r['institute'] not in known_2025:
            r['compare'] = 'new_college'      # in no authority's 2025 cut-offs — a genuinely new college
            r['new_note'] = 'New college'
        elif r['institute'] not in inst:
            r['compare'] = 'new_to_authority'  # existed in 2025 (another authority, e.g. state quota) but not here
            r['new_note'] = _was_in_note(auths_2025[r['institute']] - {here})
        elif k[:2] not in ic:
            r['compare'] = 'new_course'       # course new at this college
        elif k[:3] not in icq:
            r['compare'] = 'new_quota'        # quota not offered for this course in 2025
        else:
            r['compare'] = 'no_2025_seat'     # 2025 had this course + quota, but no seat in this category
        if r['closing_2025']:
            r['change'] = r['closing'] - r['closing_2025']           # + = closed at a higher rank (easier)
            r['change_pct'] = round(100.0 * r['change'] / r['closing_2025'], 1)
            r['trend'] = 'easier' if r['change'] > 0 else 'tougher' if r['change'] < 0 else 'same'
        elif r['compare'] in ('new_college', 'new_to_authority'):
            r['trend'] = 'new'
        else:
            r['trend'] = r['compare']         # no_2025_seat | new_course | new_quota
        # New tab = a college with no 2025 result at THIS authority (new college, or counselled elsewhere in 2025 —
        # see new_note); an old college's new course / quota stays in the table (founder 2026-10-27, option B)
        r['compare_group'] = 'new' if r['compare'] in ('new_college', 'new_to_authority') else 'compared'
        r.setdefault('new_note', None)
        out.append(r)
    return out


def api_results_cutoffs():
    """GET /api/pg/results/cutoffs?authority=&round=&q=&course=&quota=&category=&state=&college_type=
    &trend=tougher|easier|same|new&rank=<open at your rank>&sort=closing (default, lowest first)|change|change_pct|institute&page=
    &compare_group=compared|new  (new = a college with no 2025 result at THIS authority — compare 'new_college'
    (in no authority's 2025 cut-offs) or 'new_to_authority' (counselled elsewhere in 2025); each has new_note,
    e.g. 'New college' / 'In 2025: Tamil Nadu state counselling'. Everything else is compared: closing_2025 is last year's closing in the SAME round, or — when that seat type was first filled in
    a later round — that later closing with closing_2025_round 'Round 2' / 'Round 3' / 'Stray' and filled_earlier;
    trend 'no_2025_seat' = 2025 had the course + quota but no seat in this category; 'new_course' / 'new_quota' =
    an existing college's course / quota not offered in 2025)
    &compare=direct|later_round|no_2025_seat|new_course|new_quota|new_to_authority|new_college. Has group_counts."""
    if not _auth():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    _ensure()
    a = request.args
    auth, year = _s(a.get('authority')) or 'mcc', _s(a.get('year')) or YEAR
    conn = get_db()
    try:
        rd = _pick_round(conn, auth, year, _s(a.get('round')))
        if not rd:
            return jsonify({'ok': True, 'round': None, 'rows': []})
        rows = _closing_rows(conn, auth, year, rd, a)
        trend, rank = _s(a.get('trend')), _int(a.get('rank'))
        if trend:
            rows = [r for r in rows if r['trend'] == trend]
        if rank:
            rows = [r for r in rows if r['closing'] >= rank]
        group_counts = dict(Counter(r['compare_group'] for r in rows))     # for the tab badges
        reason_counts = dict(Counter(r['compare'] for r in rows))
        grp, cmp_ = _s(a.get('compare_group')), _s(a.get('compare'))
        if grp:                                   # compared | new
            rows = [r for r in rows if r['compare_group'] == grp]
        if cmp_:
            rows = [r for r in rows if r['compare'] == cmp_]
        sort = _s(a.get('sort')) or 'closing'     # default: lowest 2026 closing rank first (founder 2026-10-24)
        key = {'closing': lambda r: r['closing'], 'change': lambda r: (r['change'] is None, r['change'] or 0),
               'change_pct': lambda r: (r['change_pct'] is None, r['change_pct'] or 0),
               'institute': lambda r: (r['institute'], r['course'], r['quota'], r['category'])}.get(sort)
        rows.sort(key=key or (lambda r: r['institute']), reverse=_s(a.get('desc')) in ('1', 'true'))
        page = max(1, _int(a.get('page')) or 1)
        size = min(500, max(1, _int(a.get('page_size')) or 100))
        total = len(rows)
        return jsonify({'ok': True, 'authority': auth, 'round': rd, 'compared_with': f"2025 {rd['round']}",
                        'group_counts': group_counts, 'reason_counts': reason_counts,
                        'rows': rows[(page - 1) * size: page * size], 'total_matched': total, 'page': page,
                        'page_size': size, 'total_pages': (total + size - 1) // size})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_results_cutoffs: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def _summary(rows, key):
    g = defaultdict(list)
    for r in rows:
        g[r.get(key) or '—'].append(r)
    out = []
    for k, rs in g.items():
        comp = [r for r in rs if r['compare'] == 'direct']      # medians: same round both years only
        pct = [r['change_pct'] for r in comp]
        out.append({key: k, 'seat_types': len(rs), 'compared': len(comp),
                    'tougher': sum(1 for r in comp if r['change'] < 0), 'easier': sum(1 for r in comp if r['change'] > 0),
                    'median_closing_2026': int(statistics.median([r['closing'] for r in rs])),
                    'median_closing_2025': int(statistics.median([r['closing_2025'] for r in comp])) if comp else None,
                    'median_change_pct': round(statistics.median(pct), 1) if pct else None})
    # toughest first; groups with fewer than 5 comparable seat types (noisy) go after the rest
    out.sort(key=lambda x: (x['median_change_pct'] is None, x['compared'] < 5, x['median_change_pct'] or 0))
    return out


def api_results_trends():
    """GET /api/pg/results/trends?authority=&round=&quota=&category= → 2026 vs 2025 (same round) by course,
    state and college type, + the biggest movers. median_change_pct < 0 = tougher in 2026."""
    if not _auth():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    _ensure()
    a = request.args
    auth, year = _s(a.get('authority')) or 'mcc', _s(a.get('year')) or YEAR
    conn = get_db()
    try:
        rd = _pick_round(conn, auth, year, _s(a.get('round')))
        if not rd:
            return jsonify({'ok': True, 'round': None})
        rows = _closing_rows(conn, auth, year, rd, a)
        comp = [r for r in rows if r['compare'] == 'direct']
        # movers: seat types with 2+ seats and a 2025 closing beyond rank 100 (a single seat swings wildly)
        mv = sorted([r for r in comp if r['allotted'] >= 2 and (r['closing_2025'] or 0) >= 100],
                    key=lambda r: r['change_pct'])
        return jsonify({'ok': True, 'authority': auth, 'round': rd, 'compared_with': f"2025 {rd['round']}",
                        'totals': {'seat_types': len(rows), 'compared': len(comp),
                                   'tougher': sum(1 for r in comp if r['change'] < 0),
                                   'easier': sum(1 for r in comp if r['change'] > 0),
                                   'new': sum(1 for r in rows if r['trend'] == 'new'),
                                   'filled_earlier': sum(1 for r in rows if r['filled_earlier']),
                                   'no_2025_seat': sum(1 for r in rows if r['compare'] == 'no_2025_seat'),
                                   'by_group': dict(Counter(r['compare_group'] for r in rows)),
                                   'by_reason': dict(Counter(r['compare'] for r in rows))},
                        'by_course': _summary(rows, 'course'), 'by_state': _summary(rows, 'state'),
                        'by_college_type': _summary(rows, 'college_type'),
                        'most_tougher': mv[:25], 'most_easier': mv[::-1][:25]})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_results_trends: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_results_leftover():
    """GET /api/pg/results/leftover?authority=&round=&q=&course=&quota=&category=&state=&college_type=
    → seats in the authority's current seat matrix minus seats allotted up to this round."""
    if not _auth():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    _ensure()
    a = request.args
    auth, year = _s(a.get('authority')) or 'mcc', _s(a.get('year')) or YEAR
    conn = get_db()
    try:
        rd = _pick_round(conn, auth, year, _s(a.get('round')))
        if not rd:
            return jsonify({'ok': True, 'round': None, 'rows': []})
        from pg_admin.routes.api_seat_matrix import _NO_DNB
        from pg_admin.routes.api import HIDE_DNB
        no_dnb = _NO_DNB.replace('course_name', 'm.course_name').replace("COALESCE(section", "COALESCE(m.section")
        seats = defaultdict(int)
        meta = {}
        for m in conn.execute(
                "SELECT m.cutoff_institute AS i, m.cutoff_course AS c, m.cutoff_quota AS q, m.cutoff_category AS k, "
                "m.state, m.institute_type, SUM(m.seats) AS s FROM pg_seat_matrix m JOIN pg_seat_matrix_source s "
                "ON s.counselling_body=m.counselling_body AND s.academic_year=m.academic_year "
                "WHERE m.authority_code=? AND m.academic_year=? AND COALESCE(s.superseded,0)=0 "
                "AND COALESCE(m.cutoff_institute,'')<>'' " + (f"AND {no_dnb} " if HIDE_DNB else "") +
                "GROUP BY 1,2,3,4,5,6", [auth, year]).fetchall():
            k = (m['i'], m['c'], _qn(m['q']), m['k'])
            seats[k] += int(m['s'] or 0)
            meta[k] = (m['state'] or '', _college_type(m['institute_type']))
        # seats taken in this round and every earlier one (a later round lists only its own allotments)
        taken = defaultdict(int)
        for r in conn.execute(
                "SELECT r.institute, r.course, r.quota, r.allotted_category, COUNT(*) AS n FROM pg_results r "
                "JOIN pg_results_source s ON s.authority_code=r.authority_code AND s.academic_year=r.academic_year "
                "AND s.round=r.round WHERE r.authority_code=? AND r.academic_year=? AND s.round_order<=? "
                "AND COALESCE(r.institute,'')<>'' GROUP BY 1,2,3,4",
                [auth, year, int(rd['round_order'] or 1)]).fetchall():
            taken[(r['institute'], r['course'], _qn(r['quota']), r['allotted_category'])] += int(r['n'])
        f = {k: _s(a.get(k)) for k in ('course', 'quota', 'category', 'state', 'college_type')}
        q = NM.norm(_s(a.get('q')))
        rows = []
        for k, s in seats.items():
            st, ct = meta[k]
            left = s - taken.get(k, 0)
            if left <= 0:
                continue
            row = {'institute': k[0], 'course': k[1], 'quota': k[2], 'category': k[3], 'state': st,
                   'college_type': ct, 'seats': s, 'allotted': taken.get(k, 0), 'left': left}
            if any(f[x] and row[{'category': 'category'}.get(x, x)] != f[x] for x in f):
                continue
            if q and not all(w in NM.norm(k[0]) for w in q.split()):
                continue
            rows.append(row)
        rows.sort(key=lambda r: (r['state'], r['institute'], r['course'], r['quota'], r['category']))
        page = max(1, _int(a.get('page')) or 1)
        size = min(500, max(1, _int(a.get('page_size')) or 100))
        return jsonify({'ok': True, 'authority': auth, 'round': rd, 'seats_in_matrix': sum(seats.values()),
                        'seats_allotted': sum(min(taken.get(k, 0), s) for k, s in seats.items()),
                        'seats_left': sum(r['left'] for r in rows), 'rows': rows[(page - 1) * size: page * size],
                        'total_matched': len(rows), 'page': page, 'total_pages': (len(rows) + size - 1) // size,
                        'note': 'Seat matrix minus seats allotted so far. Seats freed by resignations / non-joining '
                                'are not in this count until the authority publishes them.'})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_results_leftover: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_results_pdf():
    """GET /api/pg/results/pdf?authority=&round=&year= — the official result PDF (file lock like every other
    PG document file: X-PG-Key unless PG_FILES_PUBLIC)."""
    from pg_admin.routes.api import file_key_block
    from flask import Response
    blk = file_key_block()
    if blk:
        return blk
    _ensure()
    a = request.args
    conn = get_db()
    try:
        row = conn.execute("SELECT pdf_name, pdf_data FROM pg_results_source WHERE authority_code=? AND academic_year=? "
                           "AND round=?", [_s(a.get('authority')) or 'mcc', _s(a.get('year')) or YEAR,
                                           _s(a.get('round')) or 'Round 1']).fetchone()
    finally:
        conn.close()
    if not row or not row['pdf_data']:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    return Response(bytes(row['pdf_data']), mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename="{row["pdf_name"] or "result.pdf"}"'})


def api_announce():
    """POST /api/pg/announce (X-News-Key) {key, mode: status | test | all, to?, confirm?}
    One-off announcement email to all goocampus.in users (pg_admin/announce_email.py). 'test' sends to one
    address; 'all' needs confirm == "SEND <key>" and never emails anyone twice."""
    from pg_admin.routes.api_news_ingest import _ok
    from pg_admin import announce_email as AE
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    d = request.get_json(silent=True) or {}
    key, mode = _s(d.get('key')), _s(d.get('mode')) or 'status'
    if key not in AE.ANNOUNCEMENTS:
        return jsonify({'ok': False, 'error': 'unknown announcement'}), 400
    try:
        if mode == 'test':
            to = _s(d.get('to'))
            if '@' not in to:
                return jsonify({'ok': False, 'error': 'to required'}), 400
            return jsonify({'ok': AE.send_test(key, to), 'sent_to': to})
        if mode == 'all':
            if _s(d.get('confirm')) != f'SEND {key}':
                return jsonify({'ok': False, 'error': f'confirm must be "SEND {key}"'}), 400
            AE.start_send_all(key)
            return jsonify({'ok': True, 'started': True, **AE.status(key)})
        return jsonify({'ok': True, **AE.status(key)})
    except Exception as e:
        logging.error("api_announce: %s", e)
        return jsonify({'ok': False, 'error': 'server_error', 'detail': str(e)[:200]}), 500


# ───────────────────────────── admin: name memory review ─────────────────────────────
def _require_admin():
    from core.users import get_user
    u = get_user()
    return u if (u and u.get('is_admin')) else None


@login_required
def name_memory_admin():
    if not _require_admin():
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    _ensure()
    kind = _s(request.args.get('kind')) or 'college'
    show = _s(request.args.get('show')) or 'review'
    conn = get_db()
    try:
        counts = {(r['kind'], r['status']): r['n'] for r in conn.execute(
            "SELECT kind, status, COUNT(*) AS n FROM pg_name_memory GROUP BY kind, status").fetchall()}
        where, params = "kind=?", [kind]
        if show in ('review', 'unmatched'):
            where += " AND status=?"; params.append(show)
        elif show == 'learned':
            where += " AND how IN ('exact','fuzzy','confirmed')"
        rows = [dict(r) for r in conn.execute(
            f"SELECT id, raw_name, raw_key, std_name, authority_code, how, score, status, candidates, seen_count, "
            f"confirmed_by, confirmed_at, first_seen FROM pg_name_memory WHERE {where} "
            f"ORDER BY (status='review') DESC, seen_count DESC, raw_name LIMIT 500", params).fetchall()]
        import json as _j
        for r in rows:
            try:
                r['cands'] = _j.loads(r['candidates'] or '[]')
            except Exception:
                r['cands'] = []
        std = NM.standard_names(conn, kind)
        rounds = [dict(r) for r in conn.execute(
            "SELECT authority_code, academic_year, round, status, row_count, matched_rows, uploaded_at FROM pg_results_source "
            "ORDER BY uploaded_at DESC").fetchall()]
        return render_template('pg_admin/name_memory.html', rows=rows, std=sorted(std), kind=kind, show=show,
                               counts=counts, rounds=rounds)
    finally:
        conn.close()


@login_required
def name_memory_confirm():
    u = _require_admin()
    if not u:
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    kind = _s(request.form.get('kind')) or 'college'
    raw_key, std = _s(request.form.get('raw_key')), _s(request.form.get('std_name'))
    conn = get_db()
    try:
        if std and std not in set(NM.standard_names(conn, kind)):
            flash(f'"{std}" is not one of our standard names — pick it from the list.', 'error')
            return redirect(request.referrer or url_for('pg_name_memory'))
        NM.confirm(conn, kind, raw_key, std, u.get('name') or u.get('emp_code') or 'admin')
        # results already imported with this spelling pick up the decision straight away
        col, scol = ('institute', 'institute_raw') if kind == 'college' else ('course', 'course_raw')
        conn.execute(f"UPDATE pg_results SET {col}=? WHERE btrim(regexp_replace(lower({scol}), '[^a-z0-9]+', ' ', 'g'))=?",
                     [std, raw_key])
        if kind == 'college' and std:
            info = _college_info(conn, {std}).get(std)
            if info:
                conn.execute("UPDATE pg_results SET state=?, college_type=? WHERE institute=?", [info[0], info[1], std])
        conn.execute("UPDATE pg_results_source s SET matched_rows=(SELECT COUNT(*) FROM pg_results r WHERE "
                     "r.authority_code=s.authority_code AND r.academic_year=s.academic_year AND r.round=s.round "
                     "AND COALESCE(r.institute,'')<>'' AND COALESCE(r.course,'')<>'')")
        conn.commit()
        flash('Saved — this spelling will be recognised in every future file.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("name_memory_confirm: %s", e)
        flash('Could not save — please try again.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_name_memory', kind=kind, show=_s(request.form.get('show')) or 'review'))
