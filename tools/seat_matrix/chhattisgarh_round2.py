"""Chhattisgarh NEET PG (MD/MS) 2026 Round 2 seats (DME Chhattisgarh "Chhattisgarh NEET PG Round-2 Clear Vacancy Session
2026-27 Dated: 14-11-2026", 11 pages, text layer, inbox 1817) → rows for a separate body "Chhattisgarh — Round 2 — State
Counselling" (round_no 2, list_type 'vacancy'), like the Rajasthan / Jharkhand / J&K / Odisha Round 2 bodies. The Round 1
body ("Chhattisgarh — State Counselling", 453 seats, 10 colleges) is never touched.

Usage: /usr/bin/python3 chhattisgarh_round2.py <cg_r2_vacancy.pdf> <round1_rows.json> <cutoffs2025.json> <out.json>
  round1_rows.json = the stored Round 1 body rows (staging seatmatrix-dump?body=Chhattisgarh — State Counselling).

One table, one line per Institute Name | Program Name | Quota | Category | Subcategory | Clear Vacancy (program names can
wrap onto 2 lines inside the cell). Names are mapped to the Round 1 / 2025 standard names: COLLEGES / COURSES / FAMILY
are read (ast) from chhattisgarh.py (Round 1 reader) and the printed institute / program spellings (same DME portal
format as the allotment lists) from tools/results/chhattisgarh.py (MATRIX_NAME, COURSES), so all three stay in step.
  Quota: govt colleges print only "State Institutional Quota" → Round 1 "State Quota" (Round 1 govt seats had one state
         quota; the 50% All India part is MCC's); private colleges: State / NRI × Institutional / Open → Round 1's
         "State Quota (Institutional)" … "NRI Quota (Open)".
  Category: OP → UR; ST-PVTG → ST-Special (Round 1's "ST Spc" roster seats: every one of Round 1's 9 ST-Special
         college × course × quota lines is printed ST-PVTG here); Subcategory PH → "-PwD" (Round 1's 2 PwD seats are
         printed OP/PH and ST/PH here); NO → none.
Anything not in these maps stops the script (no guessing).
new_in_round = seats of a college + course + quota that the Round 1 body does not have at all.
Checks (stop on failure): sha256, title line, table headings on every page, every line read (rows = Subcategory tokens in
the text layer), the printed TOTAL, and every mapped college / course target known to Round 1 or the approved list.
"""
import ast, collections, hashlib, json, os, re, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report

PDF, R1, CUTS, OUT = sys.argv[1:5]
SHA = '2efa0bcc2dea08724abd336f08a26ed7f4ab56de7e1b83327edb387a8b40350c'
got = hashlib.sha256(open(PDF, 'rb').read()).hexdigest()
if got != SHA:
    raise SystemExit(f'{PDF}: sha256 {got} — not the PDF this reader was written for (14-11-2026, 460 seats)')

HERE = os.path.dirname(os.path.abspath(__file__))


def lits(path, names):
    src = ast.parse(open(path).read())
    return {t.id: ast.literal_eval(n.value) for n in src.body if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name) and t.id in names}


_r1 = lits(os.path.join(HERE, 'chhattisgarh.py'), ('COLLEGES', 'COURSES', 'FAMILY'))
_res = lits(os.path.join(HERE, '..', 'results', 'chhattisgarh.py'), ('COURSES', 'MATRIX_NAME'))
R1_COLLEGES, R1_COURSES, FAMILY = set(_r1['COLLEGES'].values()), set(_r1['COURSES'].values()), _r1['FAMILY']
squash = lambda s: re.sub(r'\s+', '', s)     # the results map was keyed from wrapped cells ('RADIO- DIAGNOSIS')
INST = dict(_res['MATRIX_NAME'])
PROG = {squash(k): v for k, v in _res['COURSES'].items()}
PROG.update({squash(k): v for k, v in {      # spellings first seen in this list
    'MD/MS (Anatomy)': 'MD/MS - Anatomy',
    'MD Immuno Haematology and Blood Transfusion': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'MD Palliative Medicine': 'MD - Palliative Medicine'}.items()})
NOT_IN_R1 = {'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'MD - Palliative Medicine'}
bad = sorted(set(INST.values()) - R1_COLLEGES)
if bad:
    raise SystemExit(f'institute map targets not in the Round 1 colleges: {bad}')
bad = sorted(set(PROG.values()) - R1_COURSES - NOT_IN_R1)
if bad:
    raise SystemExit(f'program map targets not in the Round 1 courses: {bad}')
PRIVATE = {'Raipur Institute of Medical Sciences, Raipur', 'Shri Shankaracharya Institute of Medical Sciences, Bhilai',
           'Shri Balaji Institute of Medical Science, Raipur'}
QUOTA_PRIVATE = {'State Institutional Quota': 'State Quota (Institutional)', 'State Open Quota': 'State Quota (Open)',
                 'NRI Institutional Quota': 'NRI Quota (Institutional)', 'NRI Open Quota': 'NRI Quota (Open)'}
QUOTA_GOVT = {'State Institutional Quota': 'State Quota'}
CATEGORY = {'OP': 'UR', 'SC': 'SC', 'ST': 'ST', 'OBC': 'OBC', 'EWS': 'EWS', 'ST-PVTG': 'ST-Special'}
SUBCAT = {'NO': '', 'PH': '-PwD'}
HEAD = ['Institute Name', 'Program Name', 'Quota', 'Category', 'Subcategory', 'Clear Vacancy']
TITLE = 'Chhattisgarh NEET PG Round-2 Clear Vacancy Session 2026-27 Dated: 14-11-2026'

doc = fitz.open(PDF)
if len(doc) != 11:
    raise SystemExit(f'expected 11 pages, got {len(doc)}')
lines, printed_total, unknown = [], None, collections.Counter()
text_tokens = 0
for pno, page in enumerate(doc, 1):
    if TITLE not in clean(page.get_text()):
        raise SystemExit(f'p{pno}: title line changed')
    text_tokens += sum(1 for w in page.get_text().split('\n') if w.strip() in SUBCAT)
    tabs = page.find_tables().tables
    if len(tabs) != 1:
        raise SystemExit(f'p{pno}: {len(tabs)} tables')
    seen_head = False
    for r in tabs[0].extract():
        r = [clean(x) for x in r]
        if len(r) != 6:
            raise SystemExit(f'p{pno}: row with {len(r)} cells: {r}')
        if r == HEAD:
            seen_head = True; continue
        if r[0] == TITLE and not any(r[1:]):
            continue
        if r[:4] == ['', '', '', ''] and r[4] == 'TOTAL':
            printed_total = int(r[5]); continue
        if not r[5].isdigit():
            raise SystemExit(f'p{pno}: unreadable line {r}')
        inst, prog, quota, cat, sub, n = r
        college = INST.get(inst)
        course = PROG.get(squash(prog))
        private = college in PRIVATE
        q = (QUOTA_PRIVATE if private else QUOTA_GOVT).get(quota)
        for ok, what in ((college, f'institute: {inst}'), (course, f'program: {prog}'),
                         (q, f'quota: {quota} ({"private" if private else "govt"})'),
                         (cat in CATEGORY, f'category: {cat}'), (sub in SUBCAT, f'subcategory: {sub}')):
            if not ok:
                unknown[what] += 1
        if college and course and q and cat in CATEGORY and sub in SUBCAT:
            lines.append({'college': college, 'course': course, 'quota': q, 'seats': int(n), 'section': 'mdms',
                          'category': CATEGORY[cat] + SUBCAT[sub],
                          'institute_type': 'Private Institute' if private else 'Government Institute'})
    if not seen_head:
        raise SystemExit(f'p{pno}: table headings changed')
if unknown:
    raise SystemExit('NOT IN THE MAPS (add them only after checking):\n  ' +
                     '\n  '.join(f'{k}  ×{v}' for k, v in sorted(unknown.items())))

checks = {'lines read = Subcategory tokens in the text layer': (len(lines), text_tokens),
          'seats = printed TOTAL': (sum(x['seats'] for x in lines), printed_total)}

# merge repeats (same college × course × quota × category)
agg = collections.OrderedDict()
for x in lines:
    k = (x['college'], x['course'], x['quota'], x['category'])
    if k in agg:
        agg[k]['seats'] += x['seats']
    else:
        agg[k] = dict(x)
rows = list(agg.values())

# Round 1 body: institute type must agree; new_in_round = seats at college + course + quota not in Round 1
r1 = json.load(open(R1))
r1 = r1['rows'] if isinstance(r1, dict) else r1
r1_type = {x['college_name']: x['institute_type'] for x in r1}
for c in {x['college'] for x in rows}:
    want = 'Private Institute' if c in PRIVATE else 'Government Institute'
    if r1_type.get(c) != want:
        raise SystemExit(f'{c}: Round 1 institute_type {r1_type.get(c)!r}, this reader says {want!r}')
r1_ccq = collections.Counter()
r1_cell = collections.Counter()
for x in r1:
    r1_ccq[(x['college_name'], x['course_name'], x['quota'])] += int(x['seats'])
    r1_cell[(x['college_name'], x['course_name'], x['quota'], x['category'])] += int(x['seats'])
for x in rows:
    x['new_in_round'] = 0 if (x['college'], x['course'], x['quota']) in r1_ccq else x['seats']
bad = {k: v for k, v in checks.items() if v[0] != v[1]}
if bad:
    raise SystemExit(f'checks failed: {bad}')

cuts = load_cuts(CUTS, 'Chhattisgarh')
newp = {(x['college'], x['course'], x['quota'], x['category']): x['new_in_round'] for x in rows}
out = build(rows, cuts, 'Chhattisgarh', 'CG', lambda q: FAMILY[q], lambda x: (x['category'].split('-')[0],))
for o in out:
    o['new_in_round'] = newp[(o['college_name'], o['course_name'], o['quota'], o['category'])]
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)

print('by college', {c: sum(r['seats'] for r in out if r['college_name'] == c) for c in sorted({r['college_name'] for r in out})})
print('new_in_round', sum(r['new_in_round'] for r in out), [(r['college_name'], r['course_name'], r['quota'], r['category'],
                                                              r['new_in_round']) for r in out if r['new_in_round']])
r2_ccq = collections.Counter()
for r in out:
    r2_ccq[(r['college_name'], r['course_name'], r['quota'])] += r['seats']
over = {' | '.join(k): (n, r1_ccq[k]) for k, n in r2_ccq.items() if k in r1_ccq and n > r1_ccq[k]}
print('college + course + quota above its Round 1 seats (Round 2, Round 1):', over or 'none')
cell_new = sum(r['seats'] for r in out if (r['college_name'], r['course_name'], r['quota'], r['category']) not in r1_cell
               and not r['new_in_round'])
print('seats at a Round 1 college + course + quota but a category Round 1 did not have there (info):', cell_new)
print('Round 1 colleges with no Round 2 vacancy:', sorted(R1_COLLEGES - {r['college_name'] for r in out}) or 'none')
