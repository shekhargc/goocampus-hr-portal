"""Jharkhand NEET PG 2026 "Provisional Vacant Seat Matrix for Second Round of NEET (PG)-2026" (JCECEB, first seen
13.11.2026, 1 page, text layer) → Round 2 VACANCY rows, bridged to Jharkhand's 2025 cut-offs exactly like the Round 1
reader (jharkhand.py — its COLLEGES / COURSES dicts are read from that file, so both stay in step).

Same table as Round 1 plus a "Vacancy For 2nd Round" column: per institute, per course "50% State Quota Seats" (the
Round 2 matrix), "Vacancy For 2nd Round" (State Quota vacancies) and "In Service" (in-service vacancies), a Total line
under each institute. Rows stored = the vacancies only (State Quota from the vacancy column, In-service Quota from the
In Service column); blank cells = 0.

new_in_round (as MCC Round 2): seats that did not exist in Round 1 = max(0, Round-2 "50% State Quota Seats" − Round 1
seats of the same college + course, all quotas). A new seat was never allotted, so the line's vacancy must be at least
that (checked). Round 1 rows come from the stored Round 1 body (seatmatrix-dump rowsof=…, MD/MS + DNB).

Checks: title + column headings, Sl. No. 1…n per institute, every institute's Total line (all three columns, a blank
printed total = 0), vacancy ≤ seats on every line, new seats ≤ vacancy. Store as its own body with round_no 2 /
list_type 'vacancy' (superseded=2) — never replaces the Round 1 body. Run with /usr/bin/python3 (PyMuPDF):
  jharkhand_round2.py <vacancy.pdf> <round1_rows.json> <cutoffs2025.json> <out.json>"""
import sys, os, json, ast, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

PDF, R1, CUTS, OUT = sys.argv[1:5]
_src = ast.parse(open(os.path.join(os.path.dirname(__file__), 'jharkhand.py')).read())
_lit = {t.id: ast.literal_eval(n.value) for n in _src.body if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name) and t.id in ('COLLEGES', 'COURSES')}
COLLEGES, COURSES = _lit['COLLEGES'], _lit['COURSES']
COURSES.setdefault('M.D. (Biochemistry)', ('MD - Biochemistry', 'mdms'))


def val(s):
    s = clean(s)
    if s == '':
        return 0
    if not s.isdigit():
        raise SystemExit(f'not a number: {s!r}')
    return int(s)


doc = fitz.open(PDF)
if len(doc) != 1:
    raise SystemExit(f'expected 1 page, got {len(doc)}')
t = grids(doc[0])[0]
if clean(t[0][0]) not in ('Provisional Vacant Seat Matrix for Second Round of NEET (PG)-2026',
                          'Revised Provisional Vacant Seat Matrix for Second Round of NEET (PG)-2026'):   # revised 23.11.2026
    raise SystemExit(f'title changed: {t[0][0]!r}')
if [clean(x) for x in t[1]] != ['Sl. No.', 'Name of the Institute / College', 'Sl. No.', 'Name of the Course',
                                 '50% State Quota Seats', 'Vacancy For 2nd Round', 'In Service']:
    raise SystemExit(f'column headings changed: {t[1]}')
r1 = collections.Counter()
for x in json.load(open(R1)):
    r1[(x['college_name'], x['course_name'])] += int(x['seats'])
COLS = (('matrix', 4), ('State Quota', 5), ('In-service Quota', 6))
rows, checks, college, part, sl, lines = [], {}, None, None, 0, []
for r in t[2:]:
    if not any(clean(c) for c in r if c is not None):
        continue
    if clean(r[1]):
        name = clean(r[1])
        if name not in COLLEGES:
            raise SystemExit(f'unknown institute {name!r}')
        college, part, sl = COLLEGES[name], collections.Counter(), 0
    if clean(r[3]) == 'Total':
        for k, i in COLS:
            checks[f'{college} | {k}'] = (part[k], val(r[i]))
        continue
    sl += 1
    if clean(r[2]) != str(sl):
        raise SystemExit(f'Sl. No. out of sequence at {r}')
    raw = clean(r[3])
    if raw not in COURSES:
        raise SystemExit(f'unknown course {raw!r}')
    course, section = COURSES[raw]
    seats, vac, ins = (val(r[i]) for _, i in COLS)
    for k, n in zip(('matrix', 'State Quota', 'In-service Quota'), (seats, vac, ins)):
        part[k] += n
    if vac + ins > seats:
        raise SystemExit(f'vacancy above the seats on {r}')
    new = max(0, seats - r1.get((college, course), 0))
    if new > vac + ins:
        raise SystemExit(f'{new} new seat(s) but only {vac + ins} vacant on {r}')
    lines.append((college, course, seats, r1.get((college, course), 0), new))
    for quota, n in (('State Quota', vac), ('In-service Quota', ins)):
        if n:
            nn = min(new, n)
            new -= nn
            rows.append({'college': college, 'course': course, 'quota': quota, 'seats': n, 'section': section,
                         'category': '', 'institute_type': 'Government Institute', 'new_in_round': nn})

FAMILY = {'State Quota': ('Government Quota$',), 'In-service Quota': ('Government Quota-Inservice',)}
cuts = load_cuts(CUTS, 'Jharkhand')
out = build(rows, cuts, 'Jharkhand', 'JH', lambda q: FAMILY[q])     # no categories in the PDF → the UR rank
for o, x in zip(out, rows):
    o['new_in_round'] = x['new_in_round']
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('Round-2 matrix column', sum(x[2] for x in lines), '| Round 1 stored', sum(r1.values()),
      '| lines with more seats than Round 1:', [(c[:20], co, s, a) for c, co, s, a, n in lines if n])
print('vacancies by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')},
      '| new_in_round', sum(r['new_in_round'] for r in out))
gone = sorted(k for k in r1 if k not in {(c, co) for c, co, *_ in lines})
if gone:
    print('Round 1 lines not printed in Round 2:', gone)
