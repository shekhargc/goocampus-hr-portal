"""West Bengal NEET PG 2026 Round 2 seat matrix (WBMCC "West Bengal PG Medical Counselling 2026 · Round No: 2 · Seat
Matrix", printed 21/11/2026 18:39, 107 pages, text layer, inbox 1909; 1908 = the "Participating Institute List" — names /
types only, reference) → rows for a SEPARATE body "West Bengal — Round 2 — State Counselling" (authority `wbmcc`,
round_no 2, list_type 'vacancy'). The Round 1 body ("West Bengal — State Counselling", 1,459 seats) is never touched.

Same layout as Round 1 (pages stored rotated 90°, one line per institute × program × quota, SNo, Institute Name / Type,
Program Name, Stream, Quota, UR … ST PwD, Total Seats, NO printed totals). Everything that reads the page — the column
starts, the heading / footer checks and page_lines() — and the COLLEGES / NEW_COLLEGES / PROGRAMS / QUOTAS / TYPES maps
are taken (ast) from west_bengal.py, so both rounds stay in step; only the page heading says "Round No: 2".

Why 'vacancy': Round 2 prints 756 lines / 1,026 seats against Round 1's 878 lines / 1,459 seats; most Round 1 lines are
gone or lower (seats allotted in Round 1), so this is the Round 2 seat list (Round 1 vacancies + seats added for Round 2),
not a re-issued full matrix. new_in_round = seats a college + course did not have in Round 1 = max(0, Round 2 seats −
Round 1 seats of the same college + course, all quotas), placed on the lines whose college × course × quota × category
count went up (a lower bound: a Round 1 seat allotted and a new seat added on the same course cancel out).

Names Round 1 did not have (Round 2 additions, NOT in the 2025 cut-offs) are in PROPOSED_COLLEGES / PROPOSED_PROGRAMS
below. They are not founder-approved yet: a plain run lists them and stops; --accept-proposed uses them (dry run).
After approval move them into west_bengal.py (NEW_COLLEGES / PROGRAMS) and drop the flag.

Checks (stop on failure): sha256 of the PDF, 107 pages, page heading + column headings + "Page No." on every page (Round 1
code), SNo 1…756 continuous, every line's ten categories = its Total Seats, every cell one whole number, the output
re-adds to the Total Seats column, no college × program × quota printed twice, Management / NRI seats only UR, every
In Service DNB Quota line is an NBEMS program, every mapped name used.
Run with /usr/bin/python3 (PyMuPDF):
  west_bengal_round2.py <round2.pdf> <round1_rows.json> <cutoffs2025.json> <out.json> [--accept-proposed]
  round1_rows.json = the stored Round 1 body (staging seatmatrix-dump?body=West Bengal — State Counselling)."""
import ast, collections, hashlib, json, os, re, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report

ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
if len(ARGS) != 4:
    raise SystemExit(__doc__)
PDF, R1, CUTS, OUT = ARGS
ACCEPT = '--accept-proposed' in sys.argv
SHA = '4a1da4e0fdb682118e8beb003fbc2d3f057a332b169eaff872efcf6ef298c1ee'
PAGES, LINES = 107, 756
nows = lambda s: re.sub(r'\s+', '', s or '').upper()

# ---- Round 1 reader: maps, constants and page_lines() (one source of truth) ----
_SRC = os.path.join(os.path.dirname(__file__), 'west_bengal.py')
_tree = ast.parse(open(_SRC).read())
R1NS = {'fitz': fitz, 're': re, 'collections': collections, 'nows': nows}
for _n in _tree.body:
    if isinstance(_n, ast.Assign) and isinstance(_n.targets[0], ast.Name) and _n.targets[0].id in (
            'COLLEGES', 'NEW_COLLEGES', 'PROGRAMS', 'QUOTAS', 'TYPES', 'HEAD', 'CATS', 'TOP', 'COLS', 'BODY'):
        R1NS[_n.targets[0].id] = ast.literal_eval(_n.value)
if 'Round No: 1' not in R1NS['TOP']:
    raise SystemExit('west_bengal.py TOP changed')
R1NS['TOP'] = R1NS['TOP'].replace('Round No: 1', 'Round No: 2')
exec(compile(ast.Module(body=[n for n in _tree.body if isinstance(n, ast.FunctionDef) and n.name == 'page_lines'],
                        type_ignores=[]), _SRC, 'exec'), R1NS)
page_lines = R1NS['page_lines']
COLLEGES, NEW_COLLEGES, PROGRAMS = R1NS['COLLEGES'], R1NS['NEW_COLLEGES'], R1NS['PROGRAMS']
QUOTAS, TYPES, HEAD, CATS = R1NS['QUOTAS'], R1NS['TYPES'], R1NS['HEAD'], R1NS['CATS']

# ---- Round 2 names Round 1 did not print — PROPOSED, awaiting founder approval (none is in the 2025 cut-offs) ----
PROPOSED_COLLEGES = {
    # Round 1 printed this institute as 'DEBEN MAHATO SADAR HOSPITAL, PURULIA' (NBEMS DNB / diploma seats, standard name
    # 'Deben Mahato Sadar Hospital, Purulia'). Round 2 adds MD/MS lines under the medical-college name; the brackets name
    # the Round 1 hospital. MCC DNB 2026 lists it as "Deben Mahata Government Medical College and Hospital (Formerly
    # known as Purulia Government Medical College and Hospital), Purulia". Kept on the Round 1 standard name so the
    # college code (WB-DEBEN-MAHATO-SADAR-HOSPITAL-PURULIA) and the Round 1 comparison stay the same.
    # 22 Nov 2026: College Database master names (single-source rule) — Purulia GMC & Hospital = master id 2531,
    # Jhargram = 2345, Uluberia = 2599. The Round 1 body keeps its own 'Deben Mahato Sadar Hospital, Purulia' (not touched).
    'DEBEN MAHATO GOVERNMENT MEDICAL COLLEGE AND HOSPITAL (DEBEN MAHATO SADAR HOSPITAL, PURULIA)':
        'Purulia Government Medical College & Hospital',
    'JHARGRAM GOVERNMENT MEDICAL COLLEGE & HOSPITAL': 'Jhargram Government Medical College & Hospital',
    'SARAT CHANDRA CHATTOPADHYAY GOVERNMENT MEDICAL COLLEGE AND HOSPITAL':
        'Sarat Chandra Chattopadhyay Government Medical College & Hospital, Uluberia'}   # 1908: Uluberia, Howrah
PROPOSED_PROGRAMS = {'M.D. IN NUCLEAR MEDICINE (N-ME)': ('MD - Nuclear Medicine', 'mdms')}

for m in (COLLEGES, NEW_COLLEGES, PROGRAMS, PROPOSED_COLLEGES, PROPOSED_PROGRAMS):
    if len({nows(k) for k in m}) != len(m):
        raise SystemExit('two mapping keys are the same without spaces')
NAMES = {nows(k): v for k, v in list(COLLEGES.items()) + list(NEW_COLLEGES.items())}
PROGS = {nows(k): v for k, v in PROGRAMS.items()}
P_NAMES = {nows(k): v for k, v in PROPOSED_COLLEGES.items()}
P_PROGS = {nows(k): v for k, v in PROPOSED_PROGRAMS.items()}
if set(P_NAMES) & set(NAMES) or set(P_PROGS) & set(PROGS):
    raise SystemExit('a PROPOSED name is already in west_bengal.py — drop it here')

if hashlib.sha256(open(PDF, 'rb').read()).hexdigest() != SHA:
    raise SystemExit('PDF changed (sha256) — re-check the file and update SHA / PAGES / LINES')
doc = fitz.open(PDF)
if len(doc) != PAGES:
    raise SystemExit(f'{len(doc)} pages, expected {PAGES}')

# pass 1: every line; unknown names listed up front
lines, unknown = [], collections.defaultdict(set)
for page in doc:
    for ln in page_lines(page):
        ln['page'] = page.number + 1
        lines.append(ln)
        inst, prog = clean(ln.get(1, '')), clean(ln.get(3, ''))
        if nows(inst) not in NAMES:
            unknown['institute' if nows(inst) not in P_NAMES else 'institute (proposed)'].add(inst)
        if nows(prog) not in PROGS:
            unknown['program' if nows(prog) not in P_PROGS else 'program (proposed)'].add(prog)
hard = {k: sorted(v) for k, v in unknown.items() if '(proposed)' not in k}
if hard:
    raise SystemExit(f'UNKNOWN names (add a mapping first): {hard}')
if unknown:
    print('Round 2 names not in west_bengal.py (PROPOSED maps):')
    for k, v in unknown.items():
        for s in sorted(v):
            src = P_NAMES.get(nows(s)) or P_PROGS.get(nows(s))
            print(f'   {k}: {s!r} → {src!r}')
    if not ACCEPT:
        raise SystemExit('stopped: proposed names need approval (dry run: --accept-proposed)')
    NAMES.update(P_NAMES)
    PROGS.update(P_PROGS)

# pass 2: rows (same rules as west_bengal.py)
rows, checks, printed_total, sno, seen = [], {}, 0, 0, set()
for ln in lines:
    s = ln.get(0, '')
    if not s.isdigit() or int(s) != sno + 1:
        raise SystemExit(f'p{ln["page"]}: SNo {s!r} after {sno} (sequence broken)')
    sno = int(s)
    where = f'p{ln["page"]} SNo {sno}'
    inst, itype, prog, stream, quota = (clean(ln.get(c, '')) for c in range(1, 6))
    itype = next((t for t in TYPES if nows(t) == nows(itype)), itype)
    if itype not in TYPES:
        raise SystemExit(f'{where}: unknown institute type {itype!r}')
    if nows(stream) != 'PGMEDICAL':
        raise SystemExit(f'{where}: unknown stream {stream!r}')
    quota = next((t for t in QUOTAS if nows(t) == nows(quota)), quota)
    if quota not in QUOTAS:
        raise SystemExit(f'{where}: unknown quota {quota!r}')
    vals = []
    for c in range(6, 17):
        v = ln.get(c, '')
        if v and not v.isdigit():
            raise SystemExit(f'{where}: column {HEAD[c]} is not one whole number: {v!r}')
        vals.append(int(v) if v else 0)
    cats, total = vals[:10], vals[10]
    if total < 1 or sum(cats) != total:
        raise SystemExit(f'{where}: categories {cats} add to {sum(cats)}, Total Seats {total}')
    course, section = PROGS[nows(prog)]
    if (quota == 'In Service DNB Quota') != nows(prog).startswith('(NBEMS'):
        raise SystemExit(f'{where}: quota {quota!r} with program {prog!r}')
    q = QUOTAS[quota] or ('DNB Quota (In-service)' if section == 'dnb' else 'Diploma Quota (In-service)')
    if q in ('Management Quota', 'NRI Quota') and cats[0] != total:
        raise SystemExit(f'{where}: {q} seats outside UR')
    college = NAMES[nows(inst)]
    k = (college, course, q)
    if k in seen:
        raise SystemExit(f'{where}: {k} printed twice')
    seen.add(k)
    printed_total += total
    for cat, n in zip(CATS, cats):
        if n:
            rows.append({'college': college, 'course': course, 'quota': q, 'seats': n, 'section': section,
                         'category': cat, 'pdf_type': TYPES[itype]})
checks['SNo 1…N continuous (lines parsed, last SNo)'] = (len(seen), sno)
checks['lines printed'] = (sno, LINES)
checks['seat rows re-added = sum of the Total Seats column'] = (sum(x['seats'] for x in rows), printed_total)
checks['pages read (Page No. 1…N each checked)'] = (len(doc), PAGES)
used = {x['college'] for x in rows}
if ACCEPT and set(P_NAMES.values()) - used:
    raise SystemExit(f'PROPOSED names not used: {sorted(set(P_NAMES.values()) - used)}')

# ---- Round 1 comparison + new_in_round ----
r1rows = json.load(open(R1))
r1rows = r1rows['rows'] if isinstance(r1rows, dict) else r1rows
r1_cc, r1_line = collections.Counter(), collections.Counter()
for x in r1rows:
    r1_cc[(x['college_name'], x['course_name'])] += int(x['seats'])
    r1_line[(x['college_name'], x['course_name'], x['quota'], x['category'])] += int(x['seats'])
r1_colleges = {c for c, _ in r1_cc}
r2_cc = collections.Counter()
for x in rows:
    r2_cc[(x['college'], x['course'])] += x['seats']
for x in rows:
    x['new_in_round'] = 0
for cc, n2 in r2_cc.items():
    new = max(0, n2 - r1_cc.get(cc, 0))
    for x in sorted((x for x in rows if (x['college'], x['course']) == cc),
                    key=lambda x: (x['quota'] != 'State Quota', CATS.index(x['category']))):
        up = max(0, x['seats'] - r1_line.get((x['college'], x['course'], x['quota'], x['category']), 0))
        take = min(new, up)
        x['new_in_round'], new = take, new - take
    if new:
        raise SystemExit(f'{cc}: {new} new seat(s) could not be placed on a line above Round 1')

cuts = load_cuts(CUTS, 'West Bengal')
known = {c['institute'] for c in cuts}
if sorted(set(COLLEGES.values()) - known):
    raise SystemExit('college map points at names not in the 2025 WB cut-offs')
if (set(NEW_COLLEGES.values()) | set(P_NAMES.values())) & known:
    raise SystemExit('a new-college name is in the 2025 cut-offs (move it to COLLEGES)')
for x in rows:
    if x['college'] not in known:
        x['institute_type'] = x['pdf_type']

FAMILY = {'State Quota': ('State Quota$',), 'In-service Quota': ('State Quota-Inservice$',),
          'Management Quota': ('Management Quota$',), 'NRI Quota': ('NRI Quota$',),
          'DNB Quota (In-service)': ('DNB',), 'Diploma Quota (In-service)': ('Diploma Quota',)}


def cat_match(x):     # = west_bengal.py
    if x['quota'] == 'Management Quota':
        return ('MQ',)
    if x['quota'] == 'NRI Quota':
        return ('UR', 'NRI')
    base = x['category'].split('-')[0]
    same = ('OBC', 'OBC-A', 'OBC-B') if base == 'OBC' else (base,)
    return (base + '-PH',) + same if x['category'].endswith('-PwD') else same


out = build(rows, cuts, 'West Bengal', 'WB', lambda q: FAMILY[q], cat_match)
for o, x in zip(out, rows):
    o['new_in_round'] = x['new_in_round']
codes = collections.defaultdict(set)
for r in out:
    codes[r['college_code']].add(r['college_name'])
if any(len(v) > 1 for v in codes.values()):
    raise SystemExit(f'two colleges share a college code: {[v for v in codes.values() if len(v) > 1]}')
r1_codes = {x['college_code'] for x in r1rows}
cmp = {'round1_seats': sum(r1_cc.values()), 'round2_seats': sum(r2_cc.values()),
       'round1_lines_cc': len(r1_cc), 'round2_lines_cc': len(r2_cc),
       'cc_above_round1': sorted([c, co, r1_cc.get((c, co), 0), n] for (c, co), n in r2_cc.items() if n > r1_cc.get((c, co), 0)),
       'cc_equal_round1': sum(1 for k, n in r2_cc.items() if n == r1_cc.get(k, 0)),
       'cc_below_round1': sum(1 for k, n in r2_cc.items() if 0 < r1_cc.get(k, 0) and n < r1_cc[k]),
       'cc_round1_only': sum(1 for k in r1_cc if k not in r2_cc),
       'colleges_new_vs_round1': sorted(used - r1_colleges), 'colleges_round1_only': sorted(r1_colleges - used),
       'codes_new_vs_round1': sorted({r['college_code'] for r in out} - r1_codes),
       'new_in_round': sum(x['new_in_round'] for x in rows)}
json.dump({'rows': out, 'checks': checks, 'round1_comparison': cmp}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
print('lines', sno, '| institutes', len(used), f'({len(used & known)} in 2025, {len(used - known)} new vs 2025)')
print('Round 1 vs 2 (college × course):', {k: v for k, v in cmp.items() if k != 'cc_above_round1'})
print('college × course above Round 1 (college, course, R1, R2):')
for c, co, a, b in cmp['cc_above_round1']:
    print(f'   {c[:45]:45} | {co:45} | {a} → {b}')
