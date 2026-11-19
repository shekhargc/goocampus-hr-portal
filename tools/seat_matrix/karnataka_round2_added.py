"""Karnataka KEA PGET 2026 Round 2 — the ADDITIONAL seats (19.11.2026) added onto the Round 2 vacant-seat body.

  additional.pdf — "PG MEDICAL ADDITINAL [sic] PROVISIONAL SEAT MATRIX - 2026 (19/11/2026)", 17 pages: the Round 1
                   medical layout exactly (KK / RK line pair per college × course, NON-INSERVICE / INSERVICE / PWD ×
                   11 categories + HK-RK, private columns GMP … ME + Total Seats on the RK line, GRAND TOTAL lines).
  stjohns.pdf    — "PG MEDICAL ADDITIONAL PROVISIONAL SEAT MATRIX - 2026 (19/11/2026)", St John's (M48) RC1 / RC2 / RC3.
  round2.json    — the output of karnataka_round2.py on KEA's 18.11.2026 provisional second-round vacant-seat matrix
                   (the live body "Karnataka — Round 2 — State Counselling", 2,583 seats); its rows are kept as they are.
Combined body = the vacancy rows (new_in_round unchanged) + the additional seats with new_in_round = their seats. An
additional seat on an existing college × course × quota × category line is added to it (seats += n, new_in_round += n);
otherwise it becomes a new line, bridged to the 2025 cut-off like every other line.
The parsing functions, maps and the 2025 cut-off bridge are executed straight from karnataka.py (Round 1) — one source
of truth, so names / quotas / categories are exactly Round 1's and the 18-Nov body's. Both PDFs are pinned by SHA-256.
Every college code, printed college name, course (code + printed name) and course type is checked up front; anything
unknown is LISTED and the run stops (nothing is guessed).
    /usr/bin/python3 tools/seat_matrix/karnataka_round2_added.py <additional.pdf> <stjohns.pdf> <round2.json> <cutoffs2025.json> <out.json>
"""
import ast, collections, hashlib, json, os, re, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

if len(sys.argv) != 6:
    raise SystemExit(__doc__)
ADD, SJ, R2, CUTS, OUT = sys.argv[1:6]
PIN = {ADD: '74a6be6bc59094764582eef7fe386ef00f08d84e3df8b755b4d90aa1965510ce',     # inbox 1849
       SJ: '6f5414afa3258fb874feeea67ae912f8bd1687395bb1ac7a78cc5335a5714b78'}      # inbox 1850
for p, h in PIN.items():
    got = hashlib.sha256(open(p, 'rb').read()).hexdigest()
    if got != h:
        raise SystemExit(f'{p}: SHA-256 {got} is not the pinned file {h} — KEA re-issued it; re-check the layout')

# ── Round 1 definitions, executed from karnataka.py ──
WANT = {'COLLEGES', 'COURSES', 'COURSE_TYPE', 'CAT', 'G1', 'G2', 'PRIV', 'PRIV_QUOTA', 'LEAD', 'MED_HEAD', 'FAMILY', 'ROOT',
        'key', 'nows', 'val', 'page_table', 'read_kkrk', 'kk_cat', 'kea', 'cat_match'}
src = open(os.path.join(os.path.dirname(__file__), 'karnataka.py')).read()
nodes = [n for n in ast.parse(src).body
         if (isinstance(n, ast.FunctionDef) and n.name in WANT)
         or (isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', None) in WANT)]
R1 = {'clean': clean, 'grids': grids, 'fitz': fitz, 're': re, 'collections': collections}
exec(compile(ast.Module(body=nodes, type_ignores=[]), 'karnataka.py', 'exec'), R1)
missing = WANT - set(R1)
if missing:
    raise SystemExit(f'not found in karnataka.py: {sorted(missing)}')
COLLEGES, COURSES, COURSE_TYPE, key = R1['COLLEGES'], R1['COURSES'], R1['COURSE_TYPE'], R1['key']
nows, val = R1['nows'], R1['val']
G1, G2, PRIV, PRIV_QUOTA = R1['G1'], R1['G2'], R1['PRIV'], R1['PRIV_QUOTA']
TITLE = 'PG MEDICAL ADDITINAL PROVISIONAL SEAT MATRIX - 2026'          # KEA's spelling
GROUPS = {6: 'NON- INSERVICE SEATS', 18: 'INSERVICE SEATS', 29: 'PWD SEATS', 41: 'PRIVATE, MANEGEMANET,NRI'}

# ── pre-scan: list every unknown college / name / course / course type before parsing ──
doc = fitz.open(ADD)
if TITLE not in clean(doc[0].get_text()):
    raise SystemExit('additional: title changed')
unknown = collections.OrderedDict()
for pno, page in enumerate(doc, 1):
    for r in R1['page_table'](page, R1['MED_HEAD'], GROUPS, f'additional p{pno}'):
        code, name = clean(r[1]), clean(r[2])
        if code and code not in COLLEGES:
            unknown[f'college code {code} {name!r}'] = pno
        elif code and name != COLLEGES[code][0]:
            unknown[f'college {code}: printed name {name!r} (Round 1: {COLLEGES[code][0]!r})'] = pno
        if clean(r[3]) and (clean(r[3]), key(r[4])) not in COURSES:
            unknown[f'course {clean(r[3])} {clean(r[4])!r}'] = pno
        if clean(r[3]) and key(r[5]) not in COURSE_TYPE:
            unknown[f'course type {clean(r[5])!r}'] = pno
sjdoc = fitz.open(SJ)
if len(sjdoc) != 1 or 'PG MEDICAL ADDITIONAL PROVISIONAL SEAT MATRIX - 2026' not in clean(sjdoc[0].get_text()):
    raise SystemExit('stjohns: layout / title changed')
g = grids(sjdoc[0])
if len(g) != 1 or [nows(x) for x in g[0][0]] != ['SrNo', 'CLGCODE', 'CLGNAME', 'CRSCODE', 'CRSNAME', 'COURSETYPE',
                                                  'RC1', 'RC2', 'RC3', 'TOTALSEATS']:
    raise SystemExit(f'stjohns: column headings changed: {g[0][0] if g else g}')
for r in g[0][1:]:
    if clean(r[0]) != 'GRAND TOTAL' and (clean(r[3]), key(r[4])) not in COURSES:
        unknown[f'stjohns course {clean(r[3])} {clean(r[4])!r}'] = 1
if unknown:
    raise SystemExit('UNKNOWN — add to karnataka.py maps only after checking (nothing guessed):\n  '
                     + '\n  '.join(f'p{p}: {u}' for u, p in unknown.items()))

# ── additional medical seats ──
med, mg, n_med = R1['read_kkrk'](ADD, R1['MED_HEAD'], GROUPS, COLLEGES, TITLE, 'additional')
rows, checks, institute_type, types = [], {}, {}, collections.defaultdict(set)
for c in med:
    course, college = COURSES[(c['code'], key(c['name']))], COLLEGES[c['college']][1]
    types[college].add(c['type'])
    sec = 'diploma' if course.startswith('Diploma') else 'mdms'
    for kk, vals in ((True, c['kk']), (False, c['rk'])):
        for i, v in enumerate(vals):
            if v:
                grp, ci = divmod(i, 11)
                rows.append({'college': college, 'course': course, 'section': sec, 'seats': v,
                             'quota': 'In-service Quota' if grp == 1 else 'Government Quota',
                             'category': R1['kk_cat']((G1 if grp == 0 else G2)[ci], kk, grp == 2), 'file': 'additional'})
    for lab, v in zip(PRIV, c['priv']):
        if v:
            rows.append({'college': college, 'course': course, 'section': sec, 'seats': v, 'category': lab,
                         'quota': PRIV_QUOTA.get(lab, 'Private Quota - Minority'), 'file': 'additional'})
for college, ts in types.items():
    if len(ts) != 1:
        raise SystemExit(f'additional: {college} printed with course types {ts}')
    institute_type[college] = COURSE_TYPE[ts.pop()][0]
checks['additional seats'] = (sum(x['seats'] for x in rows), mg['RK'][-1])
checks['additional colleges (Sr No 1..n)'] = (len({c['college'] for c in med}), n_med)
for i, lab in enumerate(['NI ' + x for x in G1] + ['IS ' + x for x in G2] + ['PWD ' + x for x in G2] + ['HK-RK']):
    checks[f'additional GRAND TOTAL KK {lab}'] = (sum(c['kk'][i] if i < 33 else c['kk_tot'] for c in med), mg['KK'][i])
    checks[f'additional GRAND TOTAL RK {lab}'] = (sum(c['rk'][i] if i < 33 else c['rk_tot'] for c in med), mg['RK'][i])
for i, lab in enumerate(PRIV):
    checks[f'additional GRAND TOTAL {lab}'] = (sum(c['priv'][i] for c in med), mg['RK'][34 + i])

# ── St John's additional RC seats ──
sj, sj_grand = collections.Counter(), None
for r in g[0][1:]:
    if clean(r[0]) == 'GRAND TOTAL':
        sj_grand = [val(x, 'stjohns grand') for x in r[6:10]]
        continue
    if clean(r[1]) and (clean(r[1]) != 'M48' or clean(r[2]) != COLLEGES['M48'][0]):
        raise SystemExit(f'stjohns: unexpected college {r[1:3]}')
    if key(r[5]) != 'privateunaided':
        raise SystemExit(f'stjohns: course type {r[5]!r}')
    k = (clean(r[3]), key(r[4]))
    v = [val(x, f'stjohns {k}') for x in r[6:10]]
    if sum(v[:3]) != v[3]:
        raise SystemExit(f'stjohns: {k} RC1-3 {v[:3]} ≠ total {v[3]}')
    for lab, n in zip(('RC1', 'RC2', 'RC3'), v[:3]):
        if n:
            rows.append({'college': COLLEGES['M48'][1], 'course': COURSES[k], 'quota': 'Private Quota - Minority',
                         'seats': n, 'section': 'mdms', 'category': lab, 'file': 'stjohns'})
    for lab, n in zip(('RC1', 'RC2', 'RC3', 'TOTAL'), v):
        sj[lab] += n
if sj_grand is None:
    raise SystemExit('stjohns: no GRAND TOTAL line')
for lab, b in zip(('RC1', 'RC2', 'RC3', 'TOTAL'), sj_grand):
    checks[f'stjohns GRAND TOTAL {lab}'] = (sj[lab], b)

# merge repeats inside the additional files (same college × course × quota × category) — none expected
agg = collections.OrderedDict()
for x in rows:
    k = (x['college'], x['course'], x['quota'], x['category'])
    if k in agg:
        agg[k]['seats'] += x['seats']
    else:
        agg[k] = dict(x)
add_rows = list(agg.values())
checks['additional + stjohns seats'] = (sum(x['seats'] for x in add_rows), mg['RK'][-1] + sj_grand[3])

# ── bridge the additional seats exactly like Round 1 / the 18-Nov body ──
cuts = load_cuts(CUTS, 'Karnataka')
cut_type = {c['institute']: c['institute_type'] for c in cuts}
for x in add_rows:
    if x['college'] not in cut_type:
        x['institute_type'] = institute_type.get(x['college'], 'Private Institute')
add_out = build([{k: v for k, v in x.items() if k != 'file'} for x in add_rows], cuts, 'Karnataka', 'KA',
                lambda q: R1['FAMILY'][q], R1['cat_match'])
CODE_FIX = {'Employees State Insurance Corporation Medical College, Bangalore': 'KA-ESIC-MEDICAL-COLLEGE-BANGALORE',
            'Employees State Insurance Corporation Medical College, Gulbarga': 'KA-ESIC-MEDICAL-COLLEGE-GULBARGA'}
for r in add_out:
    r['college_code'] = CODE_FIX.get(r['college_name'], r['college_code'])

# ── combine with the 18-Nov vacancy body ──
base = json.load(open(R2))['rows']
if (len(base), sum(r['seats'] for r in base)) != (2080, 2583):
    raise SystemExit(f'round2.json is not the 18-Nov vacancy output (2,080 rows / 2,583 seats): {len(base)} / '
                     f'{sum(r["seats"] for r in base)}')
K = lambda r: (r['college_name'], r['course_name'], r['quota'], r['category'])
out = [dict(r, new_in_round=r.get('new_in_round') or 0) for r in base]
at = {K(r): r for r in out}
if len(at) != len(out):
    raise SystemExit('round2.json has repeated lines')
merged, merged_seats, new_lines, new_seats = [], 0, [], 0
for r in add_out:
    if K(r) in at:
        e = at[K(r)]
        if e['section'] != r['section'] or e['college_code'] != r['college_code']:
            raise SystemExit(f'merge mismatch {K(r)}: {e["section"]}/{e["college_code"]} vs {r["section"]}/{r["college_code"]}')
        e['seats'] += r['seats']
        e['new_in_round'] += r['seats']
        merged.append(K(r))
        merged_seats += r['seats']
    else:
        r['new_in_round'] = r['seats']
        out.append(r)
        at[K(r)] = r
        new_lines.append(K(r))
        new_seats += r['seats']
for i, r in enumerate(out, 1):
    r['sl_no'] = i
codes = collections.defaultdict(set)
for r in out:
    codes[r['college_code']].add(r['college_name'])
if any(len(v) > 1 for v in codes.values()):
    raise SystemExit(f'two colleges share a college code: {[v for v in codes.values() if len(v) > 1]}')
checks['combined seats = vacancy 2,583 + additional + stjohns'] = (sum(r['seats'] for r in out),
                                                                   2583 + mg['RK'][-1] + sj_grand[3])
checks['new_in_round = additional + stjohns'] = (sum(r['new_in_round'] for r in out), mg['RK'][-1] + sj_grand[3])

summary = {
    'additional_by_quota': {q: sum(r['seats'] for r in add_out if r['quota'] == q) for q in sorted({r['quota'] for r in add_out})},
    'additional_lines': len(add_out), 'additional_colleges': len({r['college_name'] for r in add_out}),
    'merged_lines': len(merged), 'merged_seats': merged_seats, 'new_lines': len(new_lines), 'new_seats': new_seats,
    'additional_linked_to_2025_cutoff_seats': sum(r['seats'] for r in add_out if r['has_cutoff']),
    'additional_new_reason': dict(collections.Counter(r['new_reason'] for r in add_out if not r['has_cutoff'])),
    'additional_new_reason_seats': {k: sum(r['seats'] for r in add_out if r['new_reason'] == k)
                                    for k in sorted({r['new_reason'] for r in add_out if not r['has_cutoff']})},
    'colleges_new_to_round2_body': sorted({r['college_name'] for r in add_out} - {r['college_name'] for r in base})}
json.dump({'rows': out, 'checks': checks, 'summary': summary}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('summary', json.dumps(summary, ensure_ascii=False, indent=1))
print('combined new_in_round', sum(r['new_in_round'] for r in out), '| cutoff-linked lines', sum(r['has_cutoff'] for r in out),
      'seats', sum(r['seats'] for r in out if r['has_cutoff']))
