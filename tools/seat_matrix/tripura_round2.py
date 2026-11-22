"""Tripura PG Medical 2026 Round 2 seat matrix (DME Tripura / TRMCC "SEAT MATRIX OF ROUND-2 OF TRIPURA POSTGRADUATE
MEDICAL COUNSELLING 2026 FOR THE ACADEMIC SESSION 2026-2027, DATE- 21-11-2026", 3 pages, text layer, inbox 1917) → rows
for a SEPARATE body "Tripura — Round 2 — State Counselling" (authority `dme_tripura`, round_no 2, list_type 'vacancy').
The Round 1 body ("Tripura — State Counselling", 77 seats) is never touched.

Four institution tables (AGMC, TMC, IGM Hospital NBEMS diplomas, Modern Psychiatric Hospital DNB — LGBRIMH Tezpur is not
printed in Round 2), columns Sl No / Subject / UR / EWS / ST / SC / OBC-NCL / Total Seat, a Total line under each table.
COLLEGES / COURSES / CATS are read (ast) from tripura.py, so names and quotas equal Round 1 (AGMC + NBEMS hospitals
'State Quota', TMC 'Open Quota'); headings are compared with white space removed (Round 2 prints "DR.BRAM").
Lines printed 0 (AGMC General Medicine, Radio Diagnosis, Radiotherapy) are counted, not stored.
AGMC Dermatology's SC cell is printed '1- WESM' (as Round 1's '01- WESM') — kept as 1 SC seat.

Why 'vacancy': lines are below Round 1 (AGMC General Medicine 6 → 0, TMC General Medicine 6 → 1, LGBRIMH gone) and
above it (AGMC Anaesthesiology 2 → 4, new subjects), so this is Round 1 vacancies + seats added for Round 2, not a
re-issued full matrix. new_in_round = max(0, Round 2 − Round 1 seats of the same college + course), placed on the
categories that went up (a lower bound: an allotted Round 1 seat and an added seat on one course cancel out).

Subjects Round 1 did not print are in PROPOSED_COURSES (not founder-approved yet): a plain run lists them and stops;
--accept-proposed uses them (dry run). After approval move them into tripura.py COURSES and drop the flag.
Checks (stop on failure): sha256, title, headings, Sl No 1…n per table, every row's categories = its Total, every table
column = its Total line, the four tables = 78 (the news post's figure).
Run with /usr/bin/python3 (PyMuPDF):
  tripura_round2.py <round2.pdf> <round1_rows.json> <cutoffs2025.json> <out.json> [--accept-proposed]
  round1_rows.json = the stored Round 1 body (staging seatmatrix-dump?body=Tripura — State Counselling)."""
import ast, collections, hashlib, json, os, re, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report

ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
if len(ARGS) != 4:
    raise SystemExit(__doc__)
PDF, R1, CUTS, OUT = ARGS
ACCEPT = '--accept-proposed' in sys.argv
SHA = '334402131aae1f1e107afe2f4755d533da635f8795389c39d632222bcf84f15c'
GRAND = 78
nows = lambda s: re.sub(r'\s+', '', s or '').upper()

_lit = {}
for _n in ast.parse(open(os.path.join(os.path.dirname(__file__), 'tripura.py')).read()).body:
    if isinstance(_n, ast.Assign) and isinstance(_n.targets[0], ast.Name) and _n.targets[0].id in ('COLLEGES', 'COURSES', 'CATS'):
        _lit[_n.targets[0].id] = ast.literal_eval(_n.value)
COLLEGES, COURSES, CATS = _lit['COLLEGES'], _lit['COURSES'], _lit['CATS']    # CATS = UR EWS ST SC OBC
PROPOSED_COURSES = {
    'Darmatoloty (MD)': ('MD - Dermatology', 'mdms'),          # misprint of "Dermatology (MD)"
    'Physical Medicine & Rehabilitation (MD)': ('MD - Physical Medicine and Rehabilitation', 'mdms')}
NOTES = {'1-WESM': 1}             # AGMC Dermatology SC cell (WESM printed after the number, as in Round 1)
HEAD = ['SlNo', 'Subject', 'UR', 'EWS', 'ST', 'SC', 'OBC-NCL', 'TotalSeat']
TITLE = ('SEAT MATRIX OF ROUND-2 OF TRIPURA POSTGRADUATE MEDICAL COUNSELLING 2026 '
         'FOR THE ACADEMIC SESSION 2026-2027, DATE- 21-11-2026')
NAMES = {nows(k): k for k in COLLEGES}
SUBJ = {nows(k): v for k, v in COURSES.items()}
P_SUBJ = {nows(k): v for k, v in PROPOSED_COURSES.items()}
if set(P_SUBJ) & set(SUBJ):
    raise SystemExit('a PROPOSED subject is already in tripura.py — drop it here')


def num(s):
    s = nows(s)
    if s in NOTES:
        return NOTES[s]
    if not s.isdigit():
        raise SystemExit(f'unexpected cell {s!r}')
    return int(s)


if hashlib.sha256(open(PDF, 'rb').read()).hexdigest() != SHA:
    raise SystemExit('PDF changed (sha256) — re-check the file and update SHA / GRAND')
doc = fitz.open(PDF)
if len(doc) != 3:
    raise SystemExit(f'{len(doc)} pages, expected 3')
if TITLE not in clean(doc[0].get_text()):
    raise SystemExit('title changed')

# pass 1: table lines; unknown subjects listed up front
lines, unknown, college = [], set(), None
for page in doc:
    for t in page.find_tables().tables:
        for r in t.extract():
            r = [clean(c) for c in r]
            ne = [c for c in r if c]
            if not ne:
                continue
            if len(ne) == 1 and nows(ne[0]) in NAMES:
                college = NAMES[nows(ne[0])]
                lines.append(('college', college))
            elif [nows(c) for c in r] == [nows(h) for h in HEAD]:
                lines.append(('head', college))
            elif r[0] == '' and nows(r[1]) == 'TOTAL':
                lines.append(('total', college, r[2:]))
            elif r[0].isdigit():
                if nows(r[1]) not in SUBJ:
                    unknown.add(r[1])
                lines.append(('line', college, r))
            else:
                raise SystemExit(f'p{page.number + 1}: line not understood: {r}')
hard = sorted(s for s in unknown if nows(s) not in P_SUBJ)
if hard:
    raise SystemExit(f'UNKNOWN subjects (add a mapping first): {hard}')
if unknown:
    print('Round 2 subjects not in tripura.py (PROPOSED maps):')
    for s in sorted(unknown):
        print(f'   {s!r} → {P_SUBJ[nows(s)]!r}')
    if not ACCEPT:
        raise SystemExit('stopped: proposed names need approval (dry run: --accept-proposed)')
    SUBJ.update(P_SUBJ)

# pass 2: rows + checks
rows, checks, zero_lines, part, sl, state, tables = [], {}, [], None, 0, None, []
for ln in lines:
    kind, college = ln[0], ln[1]
    if kind == 'college':
        if college in tables or state not in (None, 'done'):
            raise SystemExit(f'{college}: printed twice, or the table before it has no Total line')
        tables.append(college)
        part, sl, state = [0] * 6, 0, 'college'
        continue
    if kind == 'head':
        if state != 'college':
            raise SystemExit(f'{college}: heading not after the institution name')
        state = 'head'
        continue
    if state != 'head' or college is None:
        raise SystemExit(f'{kind} line outside a table: {ln}')
    if kind == 'total':
        vals = [num(v) for v in ln[2]]
        if len(vals) != 6:
            raise SystemExit(f'{college}: total line {ln[2]}')
        for h, g, v in zip(HEAD[2:], part, vals):
            checks[f'{COLLEGES[college][0][:32]} | {h}'] = (g, v)
        state = 'done'
        continue
    r = ln[2]
    sl += 1
    if r[0] != str(sl):
        raise SystemExit(f'{college}: Sl No {r[0]!r}, expected {sl}')
    course, section = SUBJ[nows(r[1])]
    vals = [num(v) for v in r[2:8]]
    if sum(vals[:5]) != vals[5]:
        raise SystemExit(f'{college} / {r[1]}: categories {vals[:5]} add to {sum(vals[:5])}, Total {vals[5]}')
    part = [a + b for a, b in zip(part, vals)]
    name, quota = COLLEGES[college]
    if vals[5] == 0:
        zero_lines.append((name, course))
    for c, n in zip(CATS, vals[:5]):
        if n:
            rows.append({'college': name, 'course': course, 'quota': quota, 'seats': n, 'section': section,
                         'category': c, 'institute_type': 'Government Institute' if quota == 'State Quota' else None})
if state != 'done':
    raise SystemExit('last table has no Total line')
if len(tables) != 4 or set(tables) != set(COLLEGES) - {'LOKOPRIYA GOPINATH BORDOLOI REGIONAL INSTITUTE OF MENTAL HEALTH (LGBRIMH), TEZPUR, ASSAM'}:
    raise SystemExit(f'institution tables read: {tables}')
checks['MATRIX (four tables, news post 78)'] = (sum(x['seats'] for x in rows), GRAND)
for x in rows:
    if x['institute_type'] is None:
        del x['institute_type']        # TMC: 2025 cut-off type (Private Institute) via common.build

# ---- Round 1 comparison + new_in_round ----
r1rows = json.load(open(R1))
r1rows = r1rows['rows'] if isinstance(r1rows, dict) else r1rows
r1_cc, r1_line = collections.Counter(), collections.Counter()
for x in r1rows:
    r1_cc[(x['college_name'], x['course_name'])] += int(x['seats'])
    r1_line[(x['college_name'], x['course_name'], x['quota'], x['category'])] += int(x['seats'])
r2_cc = collections.Counter()
for x in rows:
    r2_cc[(x['college'], x['course'])] += x['seats']
for cc, n2 in r2_cc.items():
    new = max(0, n2 - r1_cc.get(cc, 0))
    for x in sorted((x for x in rows if (x['college'], x['course']) == cc), key=lambda x: CATS.index(x['category'])):
        take = min(new, max(0, x['seats'] - r1_line.get((x['college'], x['course'], x['quota'], x['category']), 0)))
        x['new_in_round'], new = take, new - take
    if new:
        raise SystemExit(f'{cc}: {new} new seat(s) could not be placed on a category above Round 1')

cuts = load_cuts(CUTS, 'Tripura')
cat = lambda x: ('OBC-NCL', 'OBC') if x['category'] == 'OBC' else (x['category'],)     # = tripura.py
out = build(rows, cuts, 'Tripura', 'TR', lambda q: (q,), cat)
for o, x in zip(out, rows):
    o['new_in_round'] = x['new_in_round']
r1_colleges = {c for c, _ in r1_cc}
used = {x['college'] for x in rows}
cmp = {'round1_seats': sum(r1_cc.values()), 'round2_seats': sum(r2_cc.values()),
       'cc_above_round1': sorted([c, co, r1_cc.get((c, co), 0), n] for (c, co), n in r2_cc.items() if n > r1_cc.get((c, co), 0)),
       'cc_below_round1': sorted([c, co, r1_cc[(c, co)], r2_cc.get((c, co), 0)] for (c, co) in r1_cc
                                 if r2_cc.get((c, co), 0) < r1_cc[(c, co)]),
       'printed_zero': zero_lines, 'colleges_new_vs_round1': sorted(used - r1_colleges),
       'colleges_round1_only': sorted(r1_colleges - used), 'new_in_round': sum(x['new_in_round'] for x in rows)}
json.dump({'rows': out, 'checks': checks, 'round1_comparison': cmp}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
print('lines printed 0 (not stored):', zero_lines)
print('Round 1', cmp['round1_seats'], '→ Round 2', cmp['round2_seats'], '| new_in_round', cmp['new_in_round'],
      '| colleges new', cmp['colleges_new_vs_round1'], '| Round 1 only', cmp['colleges_round1_only'])
for k in ('cc_above_round1', 'cc_below_round1'):
    print(k, '(college, course, R1, R2):')
    for c, co, a, b in cmp[k]:
        print(f'   {c[:40]:40} | {co:45} | {a} → {b}')
