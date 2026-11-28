"""College Rankings 2026 — one engine for MCC and every state (founder 2026-11-28).

Founder's rules:
  * Demand = how fast a college's seats go to top rankers. Government seats, general merit (Open / GM / UR …)
    show it best — fees there are low and alike, so the order doctors pick colleges in is their judgement of the
    college. Management / NRI / private-fee seats are ranked in their own lists (fee-driven).
  * Rounds 1 and 2 decide: a seat type's closing rank = the highest rank that got a seat in Round 1 or Round 2
    (mop-up / stray never count, so one late leftover seat can't drag a top college down).
  * 2025 (last year's cut-offs, Rounds 1–2) and 2026 (this year's results, Rounds 1–2 as far as published)
    count EQUALLY. A college new in 2026 is ranked on 2026 alone.
  * Course against course: in every course offered by 2+ colleges, each college's place (0 = filled first,
    1 = last); a year's score = its average place over ALL its courses, clinical courses counting twice;
    the college's score = the average of its 2025 and 2026 scores.
  * Tiers: Top = first 30 %, Good = next 35 %, Average = last 35 %. A tier set by a team member on the Desk
    always wins over the computed one.

Rows carry closing_2025 / closing_2026 (the college's typical closing rank — median over its clinical courses —
or, in a speciality view, that course's closing rank) for the page's last column and the Excel comparison.
"""
import re
import statistics
from collections import defaultdict

YEAR26 = '2026-27'
TOP, GOOD = 0.30, 0.65            # Top 30 % · Good next 35 % · Average last 35 %

# MCC 2026 result quotas → the four ranked MCC lists (recommended.TIER_LISTS keys)
MCC_QUOTA_LIST = {
    'All India Quota': 'aiq_open',
    'Management/Paid Seats Quota': 'deemed_paid_open',
    'NRI Quota': 'nri_deemed',
    'Delhi University Quota': 'ciq_open', 'IP University Quota': 'ciq_open',
    'Banaras Hindu University': 'ciq_open', 'Aligarh Muslim University': 'ciq_open',
}


def norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


def band(i, n):
    return 'Top' if i < n * TOP else 'Good' if i < n * GOOD else 'Average'


def r12(r):
    """2025 closing rank of a seat row after Round 2: the highest rank that got a seat in Round 1 or 2."""
    vals = []
    for k in ('cr_r1', 'cr_r2'):
        try:
            v = int(r.get(k) or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0:
            vals.append(v)
    return max(vals) if vals else None


def college_key_fn(conn):
    from pg_admin.routes.results_api import _college_key_fn
    return _college_key_fn(conn)


def memory_std(conn, names):
    """Read-only: an authority's printed college name → our standard name (Name Matching memory)."""
    keys = {n: norm(n) for n in names if n}
    if not keys:
        return {}
    std = {r['raw_key']: r['std_name'] for r in conn.execute(
        "SELECT raw_key, std_name FROM pg_name_memory WHERE kind='college' AND status='ok' "
        "AND COALESCE(std_name,'')<>'' AND raw_key = ANY(?)", [list(set(keys.values()))]).fetchall()}
    return {n: std[k] for n, k in keys.items() if k in std}


def rounds_done(conn, authority):
    """Highest 2026 round (1 or 2) with a published result for this authority — 0 = none yet."""
    try:
        r = conn.execute("SELECT MAX(round_order) AS m FROM pg_results_source WHERE authority_code=? AND academic_year=? "
                         "AND round_order IN (1,2) AND COALESCE(is_hidden,0)=0", [authority, YEAR26]).fetchone()
        return int(r['m'] or 0)
    except Exception:
        conn.rollback()
        return 0


def closings_2026(conn, authority, classify, ck):
    """{(list_key, category, course_key, college_key): {'rank': closing ALL-INDIA rank, 'rank_state': the same seat's
    state merit rank (state lists), 'name', 'state', 'type'}} from
    this year's Round 1–2 results (every list of those rounds; seats taken IN the round — retained excluded;
    DNB left out). classify(quota, college_type) → list key or None."""
    out = {}
    try:
        rows = conn.execute(
            "SELECT r.institute, r.course, r.quota, r.allotted_category AS cat, r.college_type, r.state, "
            "COALESCE(r.rank_ai, r.rank) AS rank, CASE WHEN r.rank_ai IS NOT NULL AND r.rank_ai <> r.rank THEN r.rank END AS rank_state "
            "FROM pg_results r JOIN pg_results_source s ON s.authority_code=r.authority_code "
            "AND s.academic_year=r.academic_year AND s.round=r.round "
            "WHERE r.authority_code=? AND r.academic_year=? AND s.round_order IN (1,2) AND COALESCE(s.is_hidden,0)=0 "
            "AND COALESCE(r.section,'') <> 'dnb' AND COALESCE(r.round_status,'') <> 'retained' "
            "AND r.rank IS NOT NULL AND r.rank > 0 AND COALESCE(r.institute,'')<>'' AND COALESCE(r.course,'')<>''",
            [authority, YEAR26]).fetchall()
    except Exception:
        conn.rollback()
        return out
    for r in rows:
        lk = classify(r['quota'], r['college_type'])
        if not lk:
            continue
        k = (lk, (r['cat'] or '').strip(), norm(r['course']), ck(r['institute']))
        cur = out.get(k)
        if cur is None or r['rank'] > cur['rank']:          # All-India rank decides; the state rank rides along
            out[k] = {'rank': int(r['rank']), 'rank_state': int(r['rank_state']) if r['rank_state'] else None,
                      'name': r['institute'], 'state': r['state'] or '', 'type': r['college_type'] or '',
                      'course': r['course']}
    return out


def _median(vals):
    return int(statistics.median(vals)) if vals else None


def rank_list(conn, *, key, rows, row_in_list, cat_ok25, c26, cats26, clinical, ck, short_name, type_label,
              speciality=None, spec_match=None):
    """One ranked list.
    rows        2026 seat rows (or 2025 cut-off rows shaped alike) with cr_r1 / cr_r2 = last year's ranks
    row_in_list(r) → the row belongs to this list;  cat_ok25(r) → its 2025 rank counts (category chosen)
    c26         closings_2026(...) for the authority;  cats26 = set of 2026 category codes that count (None = any)
    speciality  only this course (spec_match(course) → bool)
    → {code: entry} with score, closing_2025, closing_2026, new_college, in_2026."""
    by, code_ck = {}, {}
    names_needing_memory = set()
    for r in rows:
        if not row_in_list(r):
            continue
        course = (r.get('cutoff_course') or '').strip()
        if speciality and not (course and spec_match(course)):
            continue
        code = r['college_code']
        d = by.setdefault(code, {
            'college_code': code, 'college': short_name(r['college_name']), 'state': r.get('state') or '',
            'institute_type': type_label(r.get('institute_type')), 'seats': 0, 'hist': False, '_c': set(),
            '_name': r.get('cutoff_institute') or '', '_raw': r.get('college_name') or ''})
        d['seats'] += int(r.get('seats') or 0)
        if course:
            d['_c'].add(course)
        if r.get('has_cutoff') or r.get('cutoff_institute'):
            d['hist'] = True
        if not d['_name']:
            names_needing_memory.add(d['_raw'])
    mem = memory_std(conn, names_needing_memory)
    for code, d in by.items():
        nm = d['_name'] or mem.get(d['_raw']) or d['_raw']
        code_ck[code] = ck(nm)
    ck_code = {}
    for code, k in code_ck.items():
        ck_code.setdefault(k, code)

    best25, best26 = defaultdict(dict), defaultdict(dict)       # course → {college_code: closing (All-India)}
    best26s = defaultdict(dict)                                  # course → {college_code: that seat's state rank}
    for r in rows:
        if not row_in_list(r) or not cat_ok25(r):
            continue
        course = (r.get('cutoff_course') or '').strip()
        if not course or (speciality and not spec_match(course)):
            continue
        v = r12(r)
        code = r['college_code']
        if v and (best25[course].get(code) is None or v < best25[course][code]):
            best25[course][code] = v
    course_label = {norm(c): c for d in by.values() for c in d['_c']}
    for (lk, cat, ckey, colk), v in c26.items():
        if lk != key or (cats26 is not None and cat not in cats26):
            continue
        course = course_label.get(ckey) or v['course']
        if speciality and not spec_match(course):
            continue
        code = ck_code.get(colk)
        if code is None:                         # a college only in 2026 results (no 2026 seat row matched)
            code = 'R26:' + (str(colk[1]) if isinstance(colk, tuple) else norm(colk)[:60])
            if code not in by:
                by[code] = {'college_code': code, 'college': short_name(v['name']), 'state': v['state'],
                            'institute_type': type_label(v['type']), 'seats': 0, 'hist': False, '_c': {course},
                            '_name': v['name'], '_raw': v['name'], 'from_results': True}
                ck_code[colk] = code
        cur = best26[course].get(code)
        if cur is None or v['rank'] < cur:
            best26[course][code] = v['rank']
            if v.get('rank_state'):
                best26s[course][code] = v['rank_state']

    def year_scores(best):
        places = defaultdict(lambda: ([], []))
        for course, cols in best.items():
            if len(cols) < 2:
                continue
            order = sorted(cols, key=lambda c: cols[c])
            for i, c in enumerate(order):
                places[c][0 if clinical(course) else 1].append(i / (len(order) - 1))
        # every course counts, clinical twice — so each college is judged on the same basis (a college whose open
        # seats this year were only in late-filling non-clinical courses is not scored against non-clinical
        # seats alone) while clinical demand still weighs most (2026-11-28)
        return {c: (2 * sum(v[0]) + sum(v[1])) / (2 * len(v[0]) + len(v[1])) for c, v in places.items() if (v[0] or v[1])}

    s25, s26 = year_scores(best25), year_scores(best26)
    clin_any = {c for best in (best25, best26) for course, cols in best.items() if clinical(course) for c in cols}
    for code, d in by.items():
        ys = [s for s in (s25.get(code), s26.get(code)) if s is not None]
        d['score'] = round(sum(ys) / len(ys), 4) if ys else None
        d['score_2025'] = round(s25[code], 4) if code in s25 else None
        d['score_2026'] = round(s26[code], 4) if code in s26 else None

        def typical(best):
            vals = [cols[code] for course, cols in best.items() if code in cols and clinical(course)] or \
                   [cols[code] for cols in best.values() if code in cols]
            return _median(vals)
        d['closing_2025'] = typical(best25)
        d['closing_2026'] = typical(best26)
        d['closing_2026_state'] = typical(best26s)
        d['new_college'] = not d['hist'] and d['closing_2025'] is None
        d['has_clinical'] = code in clin_any       # a clinical seat in this category in 2025 or 2026 Rounds 1–2
        d['courses'] = len(d['_c'])
        d['course_names'] = sorted(d['_c'])
        for k in ('_c', '_name', '_raw'):
            d.pop(k, None)
    return by, best25, best26, best26s


MIN_COURSES = 3      # founder 2026-11-28: 1–2-course institutes are listed apart, not tiered with full colleges


def tiers_for(by, min_courses=0):
    """Computed tier per college (Top 30 / Good 35 / Average 35) over every college with a score and at least
    `min_courses` MD/MS courses in the list."""
    known = sorted([d for d in by.values() if d['score'] is not None and (d.get('courses') or 0) >= min_courses
                    and (d.get('has_clinical') or not min_courses)],
                   key=lambda d: (d['score'], d['closing_2026'] or d['closing_2025'] or 10 ** 9))
    return {d['college_code']: band(i, len(known)) for i, d in enumerate(known)}
