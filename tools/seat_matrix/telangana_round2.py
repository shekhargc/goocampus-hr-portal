"""Telangana KNRUHS "MEDICAL PG DEGREE DIPLOMA ADMISSIONS UNDER COMPETENT AUTHORITY QUOTA FOR THE AY 2026-27 —
VACANCIES FOR SECOND PHASE OF COUNSELLING" (23.11.2026, inbox 1947, 17 pages, text layer) → seat rows for a SEPARATE
Round 2 body "Telangana — Round 2 — State Counselling" (list_type vacancy). The Round 1 body is never touched.

Layout: header "COLL CRS FEE SPCAT" + 24 category columns
  OCG OCF SC1G SC1F SC2G SC2F SC3G SC3F STG STF BCAG BCAF BCBG BCBF BCCG BCCF BCDG BCDF BCEG BCEF MING MINF BCPG BCPF
then one line per college × course × FEE (S = service, NS = non-service) × SPCAT (blank or PHO): 24 whole numbers.
College / course codes = KNRUHS allotment-list codes (COLLEGES / COURSES dicts read from tools/results/telangana.py).
Quota: NS → State Quota, S → In-service Quota; MIN columns → '... (Muslim Minority)'. Categories in KNRUHS 2025 wording
as the Round 1 body (OCG → OPEN-GEN, SC1F → SC1-FEM, BCAG + PHO → BCA-GEN-PHO, MING → MIN-GEN-MSM, BCPG → BC-POOL).
A zero is not a seat. The 2025 cut-off bridge is built exactly as the Round 1 reader (common.build, same quota family
and category fallbacks), so codes and bridges match the Round 1 body. The Round 1 body is read only for an
informational compare (lines with no Round 1 line = seats that changed category or the enhanced private seats).
College code AIMD is NOT in the Phase-1 allotment list, the Round 1 matrix or the 2025 cut-offs, and the PDF prints
no college names: its cells are HELD OUT (listed in checks.held_out) until the name is confirmed — nothing guessed.
Checks: every token sits in a parsed line (24 numbers after FEE[/PHO]), every college / course code known, page
headers unchanged.
    /usr/bin/python3 tools/seat_matrix/telangana_round2.py <vacancies.pdf> <round1_body_dump.json> <cutoffs2025.json> <out.json>
"""
import ast, collections, hashlib, json, os, re, sys
import fitz

if len(sys.argv) != 5:
    raise SystemExit(__doc__)
PDF, R1, CUTS, OUT = sys.argv[1:5]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_cuts, build, report


def _literal(name):
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results', 'telangana.py')).read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) == name:
            return ast.literal_eval(node.value)
    raise SystemExit(f'{name} not found')


COLLEGES, COURSES = _literal('COLLEGES'), _literal('COURSES')
HOLD = {'AIMD'}   # code with no known college name — held out   # codes new in Phase 2 (not in the Phase-1 allotment list) -> standard name
COURSES['FAM'] = ('FAM', 'MD - Family Medicine', 'mdms')   # Round 1 matrix 'FAMILYMEDICINE' (not in the Phase-1 allotment)
PROBE = os.environ.get('TG_PROBE') == '1'
COLS = 'OCG OCF SC1G SC1F SC2G SC2F SC3G SC3F STG STF BCAG BCAF BCBG BCBF BCCG BCCF BCDG BCDF BCEG BCEF MING MINF BCPG BCPF'.split()
HEADER = ['COLL', 'CRS', 'FEE', 'SPCAT'] + COLS
FOOT = ['KALOJI NARAYANA RAO UNIVERSITY OF HEALTH SCIENCES, TELANGANA',
        'MEDICAL PG DEGREE DIPLOMA ADMISSIONS UNDER COMPETENT AUTHORITY QUOTA FOR THE AY 2026-27',
        'VACANCIES FOR SECOND PHASE OF COUNSELLING', 'DATE: 23.11.2026', 'Sd/-', 'REGISTRAR']


def cat(col, pho):
    if col in ('MING', 'MINF'):
        c = 'MIN-' + ('GEN' if col == 'MING' else 'FEM') + '-MSM'
    elif col in ('BCPG', 'BCPF'):
        c = 'BC-POOL' if col == 'BCPG' else 'BC-POOL-FEM'
    else:
        m = re.fullmatch(r'(OC|SC[1-3]|ST|BC[A-E])([GF])', col)
        c = ('OPEN' if m.group(1) == 'OC' else m.group(1)) + '-' + ('GEN' if m.group(2) == 'G' else 'FEM')
    return c + ('-PHO' if pho else '')


text = '\n'.join(p.get_text() for p in fitz.open(PDF))
for f in FOOT:
    text = text.replace(f, ' ')
toks = text.split()
lines, i, headers = [], 0, 0
while i < len(toks):
    if toks[i:i + len(HEADER)] == HEADER:
        headers += 1; i += len(HEADER); continue
    coll, crs, fee = toks[i], toks[i + 1], toks[i + 2]
    if coll not in COLLEGES and coll not in HOLD: raise SystemExit(f'unknown college code {coll!r} (token {i})')
    if crs not in COURSES: raise SystemExit(f'unknown course code {crs!r} at {coll}')
    if fee not in ('S', 'NS'): raise SystemExit(f'FEE {fee!r} at {coll} {crs}')
    j = i + 3
    pho = toks[j] == 'PHO'
    if pho: j += 1
    nums = toks[j:j + 24]
    if len(nums) != 24 or not all(n.isdigit() for n in nums): raise SystemExit(f'bad numbers at {coll} {crs} {fee}')
    lines.append((coll, crs, fee, pho, [int(n) for n in nums]))
    i = j + 24
if headers < 2: raise SystemExit(f'only {headers} header lines')
key = collections.Counter((l[0], l[1], l[2], l[3]) for l in lines)
dup = [k for k, n in key.items() if n > 1]
if dup: raise SystemExit(f'repeated lines {dup[:5]}')


r1 = json.load(open(R1))['rows']
R1K = {(x['college_name'], x['course_name'], x['quota'], x['category']): int(x['seats']) for x in r1}
rows, held, new_line, over = [], [], [], []
for coll, crs, fee, pho, nums in lines:
    for col, n in zip(COLS, nums):
        if not n: continue
        minority = col.startswith('MIN')
        quota = ('State Quota' if fee == 'NS' else 'In-service Quota') + (' (Muslim Minority)' if minority else '')
        if coll in HOLD:
            held.append({'code': coll, 'course': COURSES[crs][1], 'quota': quota, 'category': cat(col, pho), 'seats': n}); continue
        x = {'college': COLLEGES[coll], 'course': COURSES[crs][1], 'quota': quota, 'seats': n, 'section': COURSES[crs][2],
             'category': cat(col, pho),
             'category_code': ('MIN' if minority else col[:-1]) + ('_PH' if pho else '') + '_' + col[-1]}
        k = (x['college'], x['course'], quota, x['category'])
        if k not in R1K: new_line.append(k + (n,))
        elif n > R1K[k]: over.append(k + (n, R1K[k]))
        rows.append(x)

FAMILY = {'State Quota': ('Govt Quota - Non Service-Local$',), 'In-service Quota': ('Govt Quota - Service-Local$',),
          'State Quota (Muslim Minority)': ('Govt Quota - Non Service-Local$',),
          'In-service Quota (Muslim Minority)': ('Govt Quota - Service-Local$',)}


def cat_match(x):            # same fallbacks as tools/seat_matrix/telangana.py
    c = x['category']
    if c.startswith('BC-POOL'):
        return ('OPEN-GEN',)
    if c.startswith('MIN-'):
        return tuple(dict.fromkeys((c, c.replace('-PHO', ''), c.replace('FEM', 'GEN').replace('-PHO', ''))))
    base, sex = c.split('-')[0], c.split('-')[1]
    return tuple(dict.fromkeys((c, f'{base}-{sex}', f'{base}-GEN', f'OPEN-{sex}', 'OPEN-GEN')))


cuts = load_cuts(CUTS, 'Telangana')
out = build(rows, cuts, 'Telangana', 'TS', lambda q: FAMILY[q], cat_match)
for o, x in zip(out, rows):
    o['category_code'] = x['category_code']; o['new_in_round'] = 0
checks = {'lines': len(lines), 'held_out': held, 'held_out_seats': sum(h['seats'] for h in held),
          'not_in_round1': len(new_line), 'not_in_round1_seats': sum(k[-1] for k in new_line), 'over_round1': over}
json.dump({'rows': out, 'checks': checks, 'sha256': hashlib.sha256(open(PDF, 'rb').read()).hexdigest()},
          open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, {})
q = collections.Counter(); sec = collections.Counter()
for r in out: q[r['quota']] += r['seats']; sec[r['section']] += r['seats']
print('lines', len(lines), 'rows', len(out), 'seats', sum(r['seats'] for r in out),
      'colleges', len({r['college_name'] for r in out}), dict(q), dict(sec))
print('held out (AIMD):', checks['held_out_seats'], 'seats;', 'not in Round 1:', checks['not_in_round1'], 'lines /',
      checks['not_in_round1_seats'], 'seats; over Round 1:', over)
