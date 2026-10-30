"""Shared bits for the state seat-matrix importers: text cleanup, stable college codes, and the bridge
from a parsed seat row to last year's (2025) cut-off for the same college + course + quota family."""
import json, re, collections

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()
num = lambda s: int(clean(s)) if clean(s).isdigit() else 0
APPROVED = None
ALL_COURSES = set()   # every course name in the cut-off file (any authority) — "linked to a cut-off course"


def approved_courses():
    """Approved course names (pg_admin/data/specialty_sheet.json) — every parsed row must use one."""
    global APPROVED
    if APPROVED is None:
        import os
        p = os.path.join(os.path.dirname(__file__), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')
        APPROVED = {c['course'] for c in json.load(open(p))['courses']}
    return APPROVED


def grids(page):
    """Every table on a PDF page as rows of cell text, built from the words whose centre falls in each cell.
    (PyMuPDF's own extract() drops numbers printed on coloured cell fills, e.g. MP's red PwD seats.)"""
    words = page.get_text('words')

    def text(b):
        if b is None:
            return None
        x0, y0, x1, y1 = b
        return ' '.join(w[4] for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1)
    return [[[text(c) for c in r.cells] for r in t.rows] for t in page.find_tables().tables]


def load_cuts(path, authority):
    rows = json.load(open(path))['rows']
    ALL_COURSES.update(c['course'] for c in rows if c['course'])
    return [c for c in rows if (c['authority'] or '').lower() == authority.lower()]


def college_code(prefix, name):
    return prefix + '-' + re.sub(r'[^A-Z0-9]+', '-', name.upper()).strip('-')[:40]   # same 40-char cut as the live Rajasthan codes


def build(rows, cuts, state, prefix, quota_family, cat_match=None, default_type='Government Institute'):
    """rows: dicts with college, course, quota, seats, section and optional category / institute_type.
    quota_family(seat_quota) → tuple of 2025 cut-off quota prefixes that count as the same quota (best first).
    cat_match(seat_row) → tuple of 2025 categories that are the same category (first = best);
    with no category match the open / general rank is used and cutoff_category says which it is.
    A family entry ending in '$' must match the 2025 quota exactly (e.g. 'Government Quota$' keeps
    'Government Quota-Inservice' out); every other entry is a prefix."""
    hit = lambda q, f: q == f[:-1] if f.endswith('$') else q.startswith(f)
    ok = approved_courses()
    bad = sorted({x['course'] for x in rows if x['course'] not in ok and not x['course'].startswith('DNB')})
    if bad:
        raise SystemExit(f'course names not in the approved list: {bad}')
    inst_type = {c['institute']: c['institute_type'] for c in cuts}
    by = collections.defaultdict(list)
    for c in cuts:
        by[(c['institute'], c['course'])].append(c)
    general = ('GEN', 'UR', 'UR/X/OP', 'IN_UR/X/OP', 'UR/NRI/OP', 'OPEN', 'OP')
    out = []
    for i, x in enumerate(rows, 1):
        fams = quota_family(x['quota'])
        cand = [c for c in by.get((x['college'], x['course']), []) if any(hit(c['quota'], f) for f in fams)]
        want = cat_match(x) if cat_match else ()

        def rank(c):   # same category first, then the open rank; earlier quota prefix wins; then the later round
            cat = c['category'] or ''
            return (0 if cat in want else (1 if cat in general else 2), want.index(cat) if cat in want else 0,
                    [i for i, f in enumerate(fams) if hit(c['quota'], f)][0], -(c['closing_rank'] or 0))
        pick = (sorted(cand, key=rank)[:1] or [None])[0]
        known = x['college'] in inst_type
        out.append({
            'sl_no': i, 'college_code': college_code(prefix, x['college']), 'state': state,
            'college_name': x['college'], 'category': x.get('category', ''), 'course_name': x['course'],
            'seats': x['seats'], 'section': x['section'],
            'institute_type': x.get('institute_type') or inst_type.get(x['college'], default_type),
            'quota': x['quota'], 'category_code': '', 'course_code': '',
            'cutoff_institute': x['college'] if known else '', 'cutoff_course': x['course'] if pick or x['course'] in ALL_COURSES else '',
            'cutoff_quota': pick['quota'] if pick else '', 'cutoff_category': pick['category'] if pick else '',
            'has_cutoff': 1 if pick else 0,
            'new_reason': '' if pick else ('new_college' if not known else
                                           ('new_course' if not by.get((x['college'], x['course'])) else 'new_quota_category')),
            'cr_r1': pick['r1'] if pick else None, 'cr_r2': pick['r2'] if pick else None,
            'cr_r3': pick['r3'] if pick else None, 'cr_closing': pick['closing_rank'] if pick else None,
            'cutoff_fee': pick['fee'] if pick else None})
    return out


def report(out, checks):
    bad = {k: v for k, v in checks.items() if v[0] != v[1]}
    print('checks (parsed, printed total):', checks)
    if bad:
        raise SystemExit(f'TOTALS DO NOT MATCH THE PDF: {bad}')
    print('rows', len(out), 'seats', sum(r['seats'] for r in out), 'colleges', len({r['college_name'] for r in out}))
    print('by quota', {q: sum(r['seats'] for r in out if r['quota'] == q) for q in sorted({r['quota'] for r in out})})
    cats = sorted({r['category'] for r in out})
    if cats != ['']:
        print('by category', {c: sum(r['seats'] for r in out if r['category'] == c) for c in cats})
    print('linked to a 2025 cut-off:', sum(r['seats'] for r in out if r['has_cutoff']), 'seats | new:',
          dict(collections.Counter(r['new_reason'] for r in out if not r['has_cutoff'])))
    for name in sorted({r['college_name'] for r in out if r['new_reason'] == 'new_college'}):
        print('   new college (not in 2025 cut-offs):', name)
