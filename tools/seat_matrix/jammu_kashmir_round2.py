"""Jammu & Kashmir NEET PG 2026 Round 2 seat matrix (BOPEE "OPERATIVE V 2.0", 17.11.2026) → Round 2 rows for a separate
body "Jammu & Kashmir — Round 2 — State Counselling" (round_no 2, list_type 'vacancy' → superseded=2), like the
Rajasthan / Jharkhand / MCC Round 2 bodies. The Round 1 body ("Jammu & Kashmir — State Counselling", 407 seats) is
never touched. COLLEGES / COURSES are read from jammu_kashmir.py (ast), so both stay in step.

Usage: /usr/bin/python3 jammu_kashmir_round2.py <bopee_r2.pdf> <round1_rows.json> <cutoffs2025.json> <out.json>

Same two pages as Round 1 (p1 MD/MS, p2 PG Diploma + category table) but every government cell is now COLOUR-coded,
and the page-2 table explains the colours (SM 2R OLC = VACANT IN 1R OLC + SHORTFALL OF 1R OLC + ADD. SEATS):
  - OM column: red numbers (ff0000) = Round 1 shortfall OM seats, blue (0070c0) = additional OM seats.
  - CAT. & UT LADAKH column: dark-red category names (c00000; ALC, SC, ST1, ST2, OBC, EWS, RBA, STK, STL — one seat
    each) = Round 1 shortfall seats of that category; purple numbers (7030a0) = seats left VACANT in Round 1 (their
    categories are only given state-wide in the table); blue numbers = additional seats (category split state-wide).
  - TOTAL column (black) = all of the above.
Seats whose category is not printed per cell (purple / blue in the CAT column) keep Round 1's category
"Reserved (CAT & UT Ladakh)" and bridge to the 2025 OM rank; named seats take the 2025 category (ST1 → ST-I, ALC →
ALC-IB …). new_in_round = the blue (additional) seats of the row.
Checks (stop on failure): every cell (TOTAL = OM + CAT parts), every column against the printed Total row, ASCOMS
Total = OM(G)+OM(M)+HM+NRI, and the category table: per category the named shortfall seats, the OM red / blue seats,
the purple total (= VACANT IN 1R OLC), the blue total (= ADD. SEATS) and SM 2R OLC grand total (govt MD/MS + diploma).
"""
import sys, os, re, json, ast, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report

PDF, R1, CUTS, OUT = sys.argv[1:5]
_src = ast.parse(open(os.path.join(os.path.dirname(__file__), 'jammu_kashmir.py')).read())
_lit = {t.id: ast.literal_eval(n.value) for n in _src.body if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name) and t.id in ('COLLEGES', 'COURSES', 'ASCOMS', 'RESERVED')}
COLLEGES, COURSES, ASCOMS, RESERVED = (_lit[k] for k in ('COLLEGES', 'COURSES', 'ASCOMS', 'RESERVED'))
COURSES = {**COURSES,     # first offered in Round 2 (SKIMS Srinagar)
           'MD Nuclear Medicine': 'MD - Nuclear Medicine', 'MD Geriatrics': 'MD - Geriatrics',
           'MD Palliative Medicine': 'MD - Palliative Medicine',
           'MD Physical Medicine and Rehabilitation': 'MD - Physical Medicine and Rehabilitation'}
# Cell TOTALs printed wrong in V 2.0 — the cell's own parts, the college's printed column totals (TOTAL 55, CAT 36)
# and the category table all agree on the corrected figure (checked below; reported in checks).
TOTAL_TYPOS = {('SKIMS-SRINAGAR', 'MD - Social & Preventive Medicine / Community Medicine'): (2, 3)}   # ST2 + 2 vacant
RED, BLUE, PURPLE, DARKRED, BLACK = 'ff0000', '0070c0', '7030a0', 'c00000', '000000'
NAME_CAT = {'ALC': 'ALC-IB', 'SC': 'SC', 'ST1': 'ST-I', 'ST2': 'ST-II', 'OBC': 'OBC', 'EWS': 'EWS', 'RBA': 'RBA',
            'STK': 'STK', 'STL': 'STL'}
TABLE_CAT = {'OM': 'OM', 'EWS': 'EWS', 'SC': 'SC', 'ST-I': 'ST-I', 'ST-II': 'ST-II', 'RBA': 'RBA', 'ALC/IB': 'ALC-IB',
             'OBC': 'OBC', 'STK/STL': 'STK/STL'}


def cell_spans(page):
    """Each table cell as a list of (colour, text) spans (span centre inside the cell box)."""
    spans = []
    for b in page.get_text('dict')['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                if s['text'].strip():
                    x0, y0, x1, y1 = s['bbox']
                    spans.append(((x0 + x1) / 2, (y0 + y1) / 2, '%06x' % s['color'], s['text']))
    out = []
    for t in page.find_tables().tables:
        rows = []
        for r in t.rows:
            row = []
            for c in r.cells:
                if c is None:
                    row.append(None); continue
                x0, y0, x1, y1 = c
                row.append([(col, txt) for cx, cy, col, txt in spans if x0 <= cx <= x1 and y0 <= cy <= y1])
            rows.append(row)
        out.append(rows)
    return out


def text(cell):
    return clean(' '.join(t for _, t in (cell or [])))


def nums(cell, colour):
    return sum(int(v) for c, t in (cell or []) if c == colour for v in re.findall(r'\d+', t))


def names(cell):
    got = []
    for c, t in (cell or []):
        for nm in re.findall(r'[A-Z][A-Z0-9]+', t):
            if c == DARKRED or nm in NAME_CAT:
                if nm not in NAME_CAT:
                    raise SystemExit(f'unknown category name {nm!r} in {t!r}')
                got.append(NAME_CAT[nm])
    return got


def plain(cell):
    s = text(cell)
    if s == '':
        return 0
    if not s.isdigit():
        raise SystemExit(f'not a number: {s!r}')
    return int(s)


doc = fitz.open(PDF)
if len(doc) != 2:
    raise SystemExit(f'expected 2 pages, got {len(doc)}')
hdr0 = doc[0].get_text()
if 'V 2.0' not in hdr0 or '17-11-2026' not in hdr0:
    raise SystemExit('not the V 2.0 (17-11-2026) matrix')
rows, checks = [], {}
tot = collections.Counter()           # state-wide parts for the category-table checks
named = collections.Counter()
for p, (section, label) in enumerate((('mdms', 'MD/MS'), ('diploma', 'PG Diploma'))):
    tables = cell_spans(doc[p])
    t = tables[0]
    head = next(r for r in t if r[2] and text(r[2]) in COLLEGES)
    hnames = [text(head[i]) for i in range(2, 23, 3)]
    if hnames != list(COLLEGES):
        raise SystemExit(f'{label}: college headings changed: {hnames}')
    sums, printed = collections.Counter(), None
    for r in t:
        lead = text(r[0]) or text(r[1])
        if lead.startswith('Total'):
            if len(re.findall(r'\d+', text(r[24]))) == 2 and not text(r[25]):   # Total row: OM (G) + OM (M) in one box
                g_, m_ = re.findall(r'\d+', text(r[24]))
                r = list(r); r[24] = [(BLACK, g_)]; r[25] = [(BLACK, m_)]
            printed = [plain(x) for x in r[2:28]]
            break
        if not text(r[0]).isdigit():
            continue
        course = COURSES.get(text(r[1]))
        if not course:
            raise SystemExit(f'unknown discipline {text(r[1])!r}')
        for ci, name in enumerate(COLLEGES):
            ctot, com, ccat = r[2 + ci * 3:5 + ci * 3]
            total = plain(ctot)
            if (name, course) in TOTAL_TYPOS:
                was, fixed = TOTAL_TYPOS[(name, course)]
                if total != was:
                    raise SystemExit(f'{name} {course}: expected the printed typo {was}, got {total}')
                checks[f'typo | {name} {course} TOTAL printed {was} → {fixed} (parts + column totals)'] = (fixed, fixed)
                total = fixed
            om_short, om_add = nums(com, RED), nums(com, BLUE)
            if nums(com, PURPLE) or nums(com, BLACK) or nums(com, DARKRED):
                raise SystemExit(f'{label} {name} {course}: unexpected colour in OM cell {com}')
            nm = names(ccat)
            vac, add = nums(ccat, PURPLE), nums(ccat, BLUE)
            if nums(ccat, RED) or nums(ccat, BLACK):
                raise SystemExit(f'{label} {name} {course}: unexpected number colour in CAT cell {ccat}')
            if om_short + om_add + len(nm) + vac + add != total:
                raise SystemExit(f'{label} {name} {course}: OM {om_short}+{om_add} + named {nm} + vacant {vac} + '
                                 f'added {add} ≠ TOTAL {total}')
            sums[ci * 3] += total
            sums[ci * 3 + 1] += om_short + om_add
            sums[ci * 3 + 2] += len(nm) + vac + add
            tot['om_short'] += om_short; tot['om_add'] += om_add; tot['vacant'] += vac; tot['add_res'] += add
            named.update(nm)
            parts = collections.Counter()
            newp = collections.Counter()
            parts['OM'] += om_short + om_add; newp['OM'] += om_add
            for c in nm:
                parts[c] += 1
            parts[RESERVED] += vac + add; newp[RESERVED] += add
            for cat, n in parts.items():
                if n:
                    rows.append({'college': COLLEGES[name], 'course': course, 'quota': 'Government Quota', 'seats': n,
                                 'section': section, 'category': cat, 'new_in_round': newp[cat]})
        a = [plain(x) for x in r[23:28]]
        sums[21] += a[0]
        for k in range(1, 5):
            sums[21 + k] += a[k]
        if sum(a[1:]) != a[0]:
            raise SystemExit(f'{label} ASCOMS {course}: {a[1:]} ≠ Total {a[0]}')
        for quota, cat, n in (('Government Quota', 'OM', a[1]), ('Management Quota', 'OM', a[2]),
                              ('Hindu Minority Quota', '', a[3]), ('NRI Quota', '', a[4])):
            if n:
                rows.append({'college': ASCOMS, 'course': course, 'quota': quota, 'seats': n, 'section': section,
                             'category': cat, 'institute_type': 'Private Institute', 'new_in_round': 0})
    if printed is None:
        raise SystemExit(f'{label}: no Total row')
    for ci, name in enumerate(COLLEGES):
        for k, part in enumerate(('TOTAL', 'OM', 'CAT')):
            if printed[ci * 3 + k] or sums[ci * 3 + k]:
                checks[f'{label} | {name} {part}'] = (sums[ci * 3 + k], printed[ci * 3 + k])
    for k, part in enumerate(('Total', 'OM (G)', 'OM (M)', 'HM', 'NRI')):
        if printed[21 + k] or sums[21 + k]:
            checks[f'{label} | ASCOMS {part}'] = (sums[21 + k], printed[21 + k])
    if p == 1:
        cat_table = tables[1]

# page-2 category table: CATEGORY | seats to be allotted | vacant in 1R | filled 1R | shortfall | V+SF | ADD | SM 2R | …
heads = [text(x) for x in cat_table[0]]
if not heads[0].startswith('CATEGORY') or 'SM 2R' not in ' '.join(heads[:8]):
    raise SystemExit(f'category table headings changed: {heads}')
table = {}
for r in cat_table[1:]:
    c = text(r[0])
    if c.startswith('TOTAL'):
        table['TOTAL'] = [plain(x) for x in r[1:8]]
        continue
    if c not in TABLE_CAT:
        raise SystemExit(f'category table row {c!r}')
    table[c] = [plain(x) for x in r[1:8]]
# columns: 0 seats to be allotted, 1 vacant in 1R, 2 filled, 3 shortfall, 4 V+SF, 5 ADD, 6 SM 2R
for c in TABLE_CAT:
    if c == 'OM':
        checks['table | OM shortfall = red OM seats'] = (tot['om_short'], table['OM'][3])
        checks['table | OM added = blue OM seats'] = (tot['om_add'], table['OM'][5])
        continue
    got = named.get(TABLE_CAT[c], 0) if c != 'STK/STL' else named.get('STK', 0) + named.get('STL', 0)
    checks[f'table | {c} shortfall = named seats'] = (got, table[c][3])
checks['table | vacant in 1R = purple seats'] = (tot['vacant'], table['TOTAL'][1])
checks['table | added = blue seats (OM + reserved)'] = (tot['om_add'] + tot['add_res'], table['TOTAL'][5])
checks['table | SM 2R = all government seats (MD/MS + diploma)'] = (
    sum(x['seats'] for x in rows if x['college'] != ASCOMS), table['TOTAL'][6])
checks['table | each row V+SF + ADD = SM 2R'] = (
    sum(1 for c in TABLE_CAT if table[c][4] + table[c][5] == table[c][6]), len(TABLE_CAT))
bad = {k: v for k, v in checks.items() if v[0] != v[1]}
if bad:
    raise SystemExit(f'checks failed: {bad}')

FAMILY = {'Government Quota': ('Government Quota$',), 'Management Quota': ('Management Quota$',),
          'Hindu Minority Quota': ('Hindu Minority Quota$',), 'NRI Quota': ('NRI Quota$',)}


def cat_match(x):
    if x['quota'] == 'Hindu Minority Quota':
        return ('HM',)
    if x['quota'] == 'NRI Quota':
        return ('NRI',)
    if x['category'] == RESERVED:
        return ('OM',)
    return (x['category'], 'OM')


cuts = load_cuts(CUTS, 'Jammu and Kashmir')
newp = {(x['college'], x['course'], x['quota'], x['category']): x['new_in_round'] for x in rows}
out = build(rows, cuts, 'Jammu and Kashmir', 'JK', lambda q: FAMILY[q], cat_match)
for o in out:
    o['new_in_round'] = newp.get((o['college_name'], o['course_name'], o['quota'], o['category']), 0)
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
r1 = collections.Counter()
for x in json.load(open(R1)):
    r1[(x['college_name'], x['course_name'])] += int(x['seats'])
r2 = collections.Counter()
for x in out:
    r2[(x['college_name'], x['course_name'])] += x['seats']
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma')})
print('government', sum(r['seats'] for r in out if r['college_name'] != ASCOMS), '| ASCOMS',
      sum(r['seats'] for r in out if r['college_name'] == ASCOMS), '| added (new_in_round)',
      sum(r['new_in_round'] for r in out), '| vacant-in-R1', tot['vacant'], '| shortfall',
      tot['om_short'] + sum(named.values()))
print('courses not in Round 1 at that college:', sorted(f'{c} — {k}' for c, k in r2 if (c, k) not in r1))
