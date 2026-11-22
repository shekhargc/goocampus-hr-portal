"""Tamil Nadu NEET PG 2026-27 Round 2 — Selection Committee / DMER "TENTATIVE VACANCY FOR PG DEGREE/DIPLOMA COURSE
2026-2027 IN … MEDICAL COLLEGES AS ON 21-11-2026" (67 pages, text layer) → the Round 2 vacancy body.

The same tables as the Round 1 list (tamil_nadu.py, "AS ON 31-10-2026"): one block per speciality, columns SNO, COLLEGE,
GOVERNMENT QUOTA OPEN / SERVICE × OC BC BCM MBC/DNC SC SCA ST, CMC 20%, TOTAL, MANAGEMENT QUOTA MQ / CMC 50% / TM MM CM /
NRI / TOTAL, OVER ALL TOTAL. Differences from Round 1:
  * pages are stored upright (rotation 0, 1008 × 612) — same column rules (RULES) as Round 1's turned pages;
  * GOVERNMENT pp 1-35 (37 colleges: Round 1's 26 + 11 new district GMCs that got PG seats for Round 2 under DMER
    notification 1152 / NMC 06.11.2026), SELF FINANCING pp 36-59, PRIVATE pp 60-67 (3 private universities: Sri
    Venkateswaraa + Kanyakumari Medical Mission Research Center + Takshashila Medical College, both new);
  * no CMC 50% split pages — CMC 50% seats are stored with category '' (MNW / IP / S / GM not given in this list);
  * a block's TOTAL line can sit alone at the top of the next page (p58), with no SPECIALITY heading;
  * new speciality M.D. Sports Medicine (→ 'MD - Sports Medicine', as tamil_nadu_added_r2.py).
Maps (COLLEGES, SPECIALITIES, RULES, HEAD, FAMILY, cat_match …) are executed straight from tamil_nadu.py, so names /
quotas / categories equal the Round 1 body. New colleges are only PROPOSED (below) and used with --accept-proposed;
move them into tamil_nadu.py NEW_COLLEGES once confirmed. The PDF is pinned by SHA-256 (inbox 1918).
Body "Tamil Nadu — Round 2 — State Counselling" (round_no 2, list_type vacancy; Round 1 body untouched). It is the
whole Round 2 seat list (Round 1 vacancies + the 214 added government seats), so it REPLACES nothing and needs no merge:
tamil_nadu_added_r2.py (notice 1152, course totals only, no college split) is used here as a cross-check.
new_in_round (per row) = seats above the same college × course × quota × category in the stored Round 1 body (a whole
new college = all its seats). The lower bound of added seats per course × OPEN / SERVICE is compared with notice 1152.
Checks: titles, headings and column positions per block, footer key, SNO per block across pages, every line (OPEN +
SERVICE + CMC 20% = TOTAL, MQ … NRI = management TOTAL, both = OVER ALL TOTAL), every column = the block's TOTAL line,
government pages carry no management seats, CMC quotas only at CMC, output = sum of the printed OVER ALL TOTALs.
    /usr/bin/python3 tools/seat_matrix/tamil_nadu_round2_vacancy.py <vacancy.pdf> <round1_dump.json> <tn_added_r2.json> <cutoffs2025.json> <out.json> [--accept-proposed]
"""
import ast, collections, hashlib, json, os, re, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

args = [a for a in sys.argv[1:] if not a.startswith('--')]
if len(args) != 5:
    raise SystemExit(__doc__)
PDF, R1DUMP, ADDED, CUTS, OUT = args
ACCEPT = '--accept-proposed' in sys.argv
PIN = '1a5f553098cc1b6a2cbded5f4e200ad59abf076979e597ae6d92e0ce3cc483a2'   # inbox 1918
got = hashlib.sha256(open(PDF, 'rb').read()).hexdigest()
if got != PIN:
    raise SystemExit(f'{PDF}: SHA-256 {got} is not the pinned file — DMER re-issued it; re-check the layout')

# ── Round 1 definitions, executed from tamil_nadu.py ──
WANT = {'nows', 'COLLEGES', 'NEW_COLLEGES', 'TITLE1', 'SPECIALITIES', 'CMC', 'RULES', 'HEAD', 'GROUPS', 'GROUP_COLS',
        'FOOTER', 'CATS', 'OPEN_C', 'MINORITY', 'COLNAME', 'col', 'num', 'FAMILY', 'cat_match'}


def _name(n):
    if isinstance(n, ast.FunctionDef):
        return n.name
    if isinstance(n, ast.Assign):
        t = n.targets[0]
        return t.elts[0].id if isinstance(t, ast.Tuple) else getattr(t, 'id', None)


src = open(os.path.join(os.path.dirname(__file__), 'tamil_nadu.py')).read()
nodes = [n for n in ast.parse(src).body if _name(n) in WANT]
R1 = {'clean': clean, 'grids': grids, 'fitz': fitz, 're': re, 'collections': collections}
exec(compile(ast.Module(body=nodes, type_ignores=[]), 'tamil_nadu.py', 'exec'), R1)
if WANT - set(R1) - {'OPEN_C'} or 'SERV_C' not in R1:
    raise SystemExit(f'not found in tamil_nadu.py: {sorted(WANT - set(R1))}')
nows, col, num, CATS, COLNAME, CMC = R1['nows'], R1['col'], R1['num'], R1['CATS'], R1['COLNAME'], R1['CMC']
RULES, HEAD, GROUPS, GROUP_COLS, FOOTER, TITLE1 = (R1[k] for k in ('RULES', 'HEAD', 'GROUPS', 'GROUP_COLS', 'FOOTER', 'TITLE1'))
OPEN_C, SERV_C, CMC20, GTOT, MQ, CMC50, TM, MM, CM, NRI, MTOT, ALLTOT = (R1[k] for k in (
    'OPEN_C', 'SERV_C', 'CMC20', 'GTOT', 'MQ', 'CMC50', 'TM', 'MM', 'CM', 'NRI', 'MTOT', 'ALLTOT'))
MINORITY = R1['MINORITY']

SPECIALITIES = dict(R1['SPECIALITIES'])
SPECIALITIES['M.D.SportsMedicine'] = ('MD - Sports Medicine', 'mdms')      # new in Round 2 (notice 1152 'SPORTS MEDICINE')
TABLES = {'GOVERNMENT MEDICAL COLLEGES AS ON 21-11-2026': ('govt', 'Government Institute'),
          'SELF FINANCING MEDICAL COLLEGES AS ON 21-11-2026': ('self', 'Private Institute'),
          'PRIVATE MEDICAL COLLEGES AS ON 21-11-2026': ('private', 'State Private University')}
PAGES = {'govt': range(1, 36), 'self': range(36, 60), 'private': range(60, 68)}

# PROPOSED new colleges (not in Round 1, not in the 2025 TN cut-offs) — used only with --accept-proposed.
# Names = the portal's indian_colleges_data.json; the 11 GMCs are also in MCC's Round 2 AIQ seat matrix (2026) under
# their address names. Confirm with the College Database before adding them to tamil_nadu.py NEW_COLLEGES.
PROPOSED = {
    'GOVT. DINDIGUL MEDICAL COLLEGE HOSPITAL, DINDIGUL': 'Government Medical College, Dindigul',
    'GOVT. KRISHNAGIRI MEDICAL COLLEGE HOSPITAL,': 'Government Medical College, Krishnagiri',
    'GOVT. NAGAPATTINAM MEDICAL COLLEGE HOSPITAL,': 'Government Medical College, Nagapattinam',
    'GOVT. NAMAKKAL MEDICAL COLLEGE HOSPITAL, NAMAKKAL.': 'Government Medical College, Namakkal',
    'GOVT. THE NILGIRIS MEDICAL COLLEGE HOSPITAL, THE NILGIRIS': 'Government Medical College, Nilgiris',
    'GOVT. RAMANATHAPURAM MEDICAL COLLEGE HOSPITAL,': 'Government Medical College, Ramanathapuram',
    'GOVT. TIRUPPUR MEDICAL COLLEGE HOSPITAL, TIRUPPUR.': 'Government Medical College, Tiruppur',
    'GOVT. MEDICAL COLLEGE HOSPITAL, VIRUDHUNAGAR.': 'Government Medical College, Virudhunagar',
    'GOVERNMENT MEDICAL COLLEGE, KARUR': 'Government Medical College, Karur',
    'GOVT.ARIYALUR MEDICAL COLLEGE HOSPITAL, ARIYALUR.': 'Government Medical College, Ariyalur',
    'GOVT.KALLAKURUCHI MEDICAL COLLEGE HOSPITAL,': 'Government Medical College, Kallakurichi',
    'KANYAKUMARI MEDICAL MISSION RESEARCH CENTER, KANYAKUMARI (PRIVATE UNIVERSITY)':
        'Kanyakumari Medical Mission Research Center, Kanyakumari',
    'TAKSHASHILA MEDICAL COLLEGE, ONGUR, TINDIVANAM, VILLUPURAM (PRIVATE UNIVERSITY)':
        'Takshashila Medical College'}   # College Database master name (id 2693), 22 Nov 2026
NAMES = {nows(k): v for k, v in list(R1['COLLEGES'].items()) + list(R1['NEW_COLLEGES'].items())}


def page_blocks(page):
    """tamil_nadu.py's page reader for an upright page; a heading-less run of lines above the first SPECIALITY
    (the previous block running on, e.g. only its TOTAL line) is returned as a block with speciality None."""
    where = f'p{page.number + 1}'
    if page.rotation != 0:
        raise SystemExit(f'{where}: page rotation {page.rotation}, expected 0')
    ws = sorted((round(w[1], 1), w[0], w[2], w[4]) for w in page.get_text('words'))
    rules = sorted((r.y0 + r.y1) / 2 for dr in page.get_drawings() for it in dr['items'] if it[0] == 're'
                   for r in [it[1]] if r.height < 3 and r.x0 <= RULES[0] + 1.5 and r.x1 >= RULES[1] - 1)
    title = [' '.join(t for y, x0, x1, t in ws if abs(y - yy) < 1) for yy in sorted({y for y, *_ in ws if y < 40})]
    if len(title) != 2 or clean(title[0]) != TITLE1 or clean(title[1]) not in TABLES:
        raise SystemExit(f'{where}: page title changed: {title}')
    table = TABLES[clean(title[1])][0]
    specs = [w for w in ws if w[3] == 'SPECIALITY:']
    used = {i for i, w in enumerate(ws) if w[0] < 40}

    def read_lines(top, end, label):
        L = []
        for y in (y for y in rules if top < y < end):
            if not L or y - L[-1] > 3:
                L.append(y)
        if len(L) < 2:
            raise SystemExit(f'{label}: no table lines')
        lines = []
        for a, b in zip(L, L[1:]):
            cells = collections.defaultdict(list)
            for i, w in enumerate(ws):
                if a <= w[0] + 1 < b:
                    c = col((w[1] + w[2]) / 2)
                    if c < 0:
                        raise SystemExit(f'{label}: word {w[3]!r} outside the table columns')
                    cells[c].append(w)
                    used.add(i)
            if not cells:
                raise SystemExit(f'{label}: empty table line')
            lines.append({c: ' '.join(w[3] for w in sorted(v)) for c, v in cells.items()})
        return lines, L[-1]

    blocks = []
    first = specs[0][0] if specs else page.rect.height
    if first > 50:                       # lines of the previous page's block, before any heading
        lines, bottom = read_lines(40, first - 1, f'{where} (run-on)')
        blocks.append({'speciality': None, 'lines': lines, 'where': f'{where} (run-on)', 'bottom': bottom})
    for bi, sp in enumerate(specs):
        sy = sp[0]
        end = specs[bi + 1][0] - 1 if bi + 1 < len(specs) else page.rect.height
        sline = [(i, w) for i, w in enumerate(ws) if abs(w[0] - sy) < 1]
        used |= {i for i, w in sline}
        spec = ''.join(w[3] for i, w in sorted(sline, key=lambda t: t[1][1]) if w[3] != 'SPECIALITY:')
        sno = [w for w in ws if w[3] == 'SNO' and sy < w[0] < end]
        if len(sno) != 1 or col((sno[0][1] + sno[0][2]) / 2) != 0:
            raise SystemExit(f'{where} {spec}: SNO heading not found once')
        hy = sno[0][0]
        grp = [(i, w) for i, w in enumerate(ws) if sy + 1 < w[0] < hy - 7]
        heads = [(i, w) for i, w in enumerate(ws) if hy - 7 <= w[0] <= hy + 7]
        used |= {i for i, w in grp + heads}
        gtext = ' '.join(w[3] for i, w in sorted(grp, key=lambda t: (t[1][0], t[1][1])))
        if gtext != GROUPS:
            raise SystemExit(f'{where} {spec}: group headings changed: {gtext!r}')
        for i, w in grp:
            lo, hi = GROUP_COLS[w[3]]
            if not lo <= col((w[1] + w[2]) / 2) <= hi:
                raise SystemExit(f'{where} {spec}: group heading {w[3]!r} moved')
        cells = collections.defaultdict(list)
        for i, w in heads:
            cells[col((w[1] + w[2]) / 2)].append(w)
        hgot = [' '.join(w[3] for w in sorted(cells[c], key=lambda w: (w[0], w[1]))) for c in range(len(HEAD))]
        if hgot != HEAD or set(cells) != set(range(len(HEAD))):
            raise SystemExit(f'{where} {spec}: column headings changed: {hgot}')
        lines, bottom = read_lines(hy + 6, end, f'{where} {spec}')
        blocks.append({'speciality': spec, 'lines': lines, 'where': f'{where} {spec}', 'bottom': bottom})
    if not blocks:
        raise SystemExit(f'{where}: no table')
    rest = [w for i, w in enumerate(ws) if i not in used]
    foot = clean(' '.join(w[3] for w in rest))
    if foot not in (FOOTER, '') or any(w[0] < blocks[-1]['bottom'] for w in rest) or (table != 'govt' and foot != FOOTER):
        raise SystemExit(f'{where}: text outside the tables: {foot!r}')
    return table, blocks


doc = fitz.open(PDF)
if len(doc) != 67:
    raise SystemExit(f'{len(doc)} pages, expected 67')

# ── pre-scan: unknown colleges / specialities are listed before anything else ──
pages = []
unknown = collections.OrderedDict()
for page in doc:
    table, bl = page_blocks(page)
    if page.number + 1 not in PAGES[table]:
        raise SystemExit(f'p{page.number + 1}: {table} page outside pp {PAGES[table]}')
    pages.append((table, bl))
    for b in bl:
        if b['speciality'] is not None and nows(b['speciality']) not in {nows(s) for s in SPECIALITIES}:
            unknown[f'speciality {b["speciality"]!r}'] = page.number + 1
        for ln in b['lines']:
            n = clean(ln.get(1))
            if n != 'TOTAL' and nows(n) not in NAMES:
                unknown[f'{table} college {n!r}' + (f' (proposed: {PROPOSED[n]})' if n in PROPOSED else '')] = page.number + 1
blocking = [u for u in unknown if not (ACCEPT and '(proposed:' in u)]
if blocking:
    raise SystemExit('UNKNOWN — add to tamil_nadu.py maps only after checking (nothing guessed):\n  '
                     + '\n  '.join(f'p{unknown[u]}: {u}' for u in unknown)
                     + ('\n(re-run with --accept-proposed to use the PROPOSED mappings for a dry run)' if not ACCEPT else ''))
if ACCEPT:
    used_p = {k: v for k, v in PROPOSED.items() if any(f'{k!r}' in u for u in unknown)}
    print(f'USING {len(used_p)} PROPOSED (unconfirmed) college names')
    NAMES.update({nows(k): v for k, v in used_p.items()})
NEW_NAMES = {PROPOSED[k] for k in PROPOSED} | set(R1['NEW_COLLEGES'].values())

# ── blocks across pages ──
blocks = collections.OrderedDict()
open_block, last_table = None, None
for table, bl in pages:
    if last_table and table != last_table and open_block:
        raise SystemExit(f'{open_block} has no TOTAL line before the {table} table')
    last_table = table
    for b in bl:
        if b['speciality'] is None:
            if not open_block or b is not bl[0] or open_block[0] != table:
                raise SystemExit(f'{b["where"]}: lines with no SPECIALITY heading and no open block')
            k = open_block
        else:
            k = (table, b['speciality'])
            if open_block:
                if k != open_block or b is not bl[0]:
                    raise SystemExit(f'{b["where"]}: {open_block[1]} block has no TOTAL line')
            elif k in blocks:
                raise SystemExit(f'{b["where"]}: speciality printed twice in the {table} table')
            else:
                blocks[k] = {'lines': [], 'total': None, 'where': b['where']}
        blk = blocks[k]
        for ln in b['lines']:
            if blk['total'] is not None:
                raise SystemExit(f'{b["where"]}: line after the TOTAL line: {ln}')
            if clean(ln.get(1)) == 'TOTAL' and 0 not in ln:
                blk['total'] = ln
            else:
                blk['lines'].append((ln, b['where']))
        open_block = None if blk['total'] is not None else k
if open_block:
    raise SystemExit(f'{open_block}: no TOTAL line at the end')

rows, checks = [], {}
n_lines, printed_all, table_seats = 0, 0, collections.Counter()
college_table = {}
col_sum = collections.defaultdict(lambda: [0] * 26)
col_printed = collections.defaultdict(lambda: [0] * 26)
for (table, spec), blk in blocks.items():
    course, section = SPECIALITIES[next(s for s in SPECIALITIES if nows(s) == nows(spec))]
    sums, seen = [0] * 26, set()
    for i, (ln, where) in enumerate(blk['lines'], 1):
        if clean(ln.get(0)) != str(i):
            raise SystemExit(f'{where}: SNO {ln.get(0)!r}, expected {i} (sequence broken)')
        college = NAMES[nows(clean(ln.get(1)))]
        if college_table.setdefault(college, table) != table:
            raise SystemExit(f'{where}: {college} in two tables')
        if college in seen:
            raise SystemExit(f'{where}: {college} printed twice in {spec}')
        seen.add(college)
        v = [0, 0] + [num(ln.get(c), f'{where} SNO {i} {COLNAME[c]}') for c in range(2, 26)]
        lab = f'{where} SNO {i} {college}'
        if sum(v[c] for c in list(OPEN_C) + list(SERV_C)) + v[CMC20] != v[GTOT]:
            raise SystemExit(f'{lab}: OPEN + SERVICE + CMC 20% ≠ TOTAL {v[GTOT]}')
        if sum(v[MQ:MTOT]) != v[MTOT]:
            raise SystemExit(f'{lab}: MQ … NRI ≠ management TOTAL {v[MTOT]}')
        if v[GTOT] + v[MTOT] != v[ALLTOT] or v[ALLTOT] < 1:
            raise SystemExit(f'{lab}: TOTAL {v[GTOT]} + management {v[MTOT]} ≠ OVER ALL TOTAL {v[ALLTOT]}')
        if table == 'govt' and any(v[MQ:MTOT + 1]):
            raise SystemExit(f'{lab}: management seats on a government page')
        if college != CMC and (v[CMC20] or v[CMC50]):
            raise SystemExit(f'{lab}: CMC 20% / 50% seats outside CMC')
        for c in range(2, 26):
            sums[c] += v[c]
        n_lines += 1
        base = {'college': college, 'course': course, 'section': section, 'table': table}
        for c, cat in zip(OPEN_C, CATS):
            if v[c]:
                rows.append(dict(base, quota='Government Quota', category=cat, seats=v[c]))
        for c, cat in zip(SERV_C, CATS):
            if v[c]:
                rows.append(dict(base, quota='Government Quota-Service', category=cat, seats=v[c]))
        if v[CMC20]:
            rows.append(dict(base, quota='CMC 20% Quota', category='', seats=v[CMC20]))
        if v[MQ]:
            rows.append(dict(base, quota='Management Quota', category='OPEN', seats=v[MQ]))
        if v[CMC50]:          # no MNW / IP / S / GM split in this list
            rows.append(dict(base, quota='CMC 50% Quota', category='', seats=v[CMC50]))
        for c, cat in MINORITY.items():
            if v[c]:
                rows.append(dict(base, quota='Management Quota-Minority', category=cat, seats=v[c]))
        if v[NRI]:
            rows.append(dict(base, quota='NRI Quota', category='NRI', seats=v[NRI]))
    tot = blk['total']
    pv = [0, 0] + [num(tot.get(c), f'{blk["where"]} TOTAL {COLNAME[c]}') for c in range(2, 26)]
    for c in range(2, 26):
        if sums[c] != pv[c]:
            raise SystemExit(f'{blk["where"]}: column {COLNAME[c]} adds to {sums[c]}, TOTAL line {pv[c]}')
        col_sum[table][c] += sums[c]
        col_printed[table][c] += pv[c]
    checks[f'{table} {spec} OVER ALL TOTAL'] = (sums[ALLTOT], pv[ALLTOT])
    printed_all += pv[ALLTOT]
    table_seats[table] += pv[ALLTOT]
for table in ('govt', 'self', 'private'):
    for c in range(2, 26):
        checks[f'{table} column {COLNAME[c]} = sum of the speciality TOTAL lines'] = (col_sum[table][c], col_printed[table][c])
checks['lines whose columns add to TOTAL / management TOTAL / OVER ALL TOTAL'] = (n_lines, n_lines)
checks['seat rows = sum of the printed OVER ALL TOTAL lines (grand total)'] = (sum(x['seats'] for x in rows), printed_all)

cuts = load_cuts(CUTS, 'Tamil Nadu')
known = {c['institute'] for c in cuts}
clash = sorted(NEW_NAMES & known)
if clash:
    raise SystemExit(f'proposed new names that are in the 2025 cut-offs: {clash}')
TYPE = {t: it for t, it in TABLES.values()}
for x in rows:
    t = x.pop('table')
    if x['college'] not in known:
        x['institute_type'] = TYPE[t]
out = build(rows, cuts, 'Tamil Nadu', 'TN', lambda q: R1['FAMILY'][q], R1['cat_match'])
codes = collections.defaultdict(set)
for r in out:
    codes[r['college_code']].add(r['college_name'])
if any(len(v) > 1 for v in codes.values()):
    raise SystemExit(f'two colleges share a college code: {[v for v in codes.values() if len(v) > 1]}')

# ── Round 1 comparison → new_in_round ──
r1 = json.load(open(R1DUMP))['rows']
r1_line, r1_cq, r1_cc = collections.Counter(), collections.Counter(), collections.Counter()
for x in r1:
    r1_line[(x['college_name'], x['course_name'], x['quota'], x['category'])] += x['seats']
    r1_cq[(x['college_name'], x['course_name'], x['quota'])] += x['seats']
    r1_cc[(x['college_name'], x['course_name'])] += x['seats']
r1_colleges = {x['college_name'] for x in r1}
r2_cq = collections.Counter()
for r in out:
    r2_cq[(r['college_name'], r['course_name'], r['quota'])] += r['seats']
cq_excess = {k: v - r1_cq[k] for k, v in r2_cq.items() if v > r1_cq[k]}
# new_in_round: the college × course × quota excess over Round 1, put on the categories that grew most (never more than
# a row's own growth over its Round 1 category line, never more than the group excess) — so it sums to the excess.
groups = collections.defaultdict(list)
for r in out:
    r['new_in_round'] = 0
    groups[(r['college_name'], r['course_name'], r['quota'])].append(r)
for k, e in cq_excess.items():
    grow = sorted(groups[k], key=lambda r: -(r['seats'] - r1_line[(r['college_name'], r['course_name'], r['quota'], r['category'])]))
    for r in grow:
        n = min(e, max(0, r['seats'] - r1_line[(r['college_name'], r['course_name'], r['quota'], r['category'])]))
        r['new_in_round'], e = n, e - n
    if e:
        raise SystemExit(f'{k}: excess left after the category lines: {e}')
added = json.load(open(ADDED))
notice = {x['course_name']: x for x in added['rows']}
qmap = {'Government Quota': 'open', 'Government Quota-Service': 'service'}
bound = collections.Counter()           # lower bound of added seats per course × open / service, GOVERNMENT colleges only
for (c, k, q), e in cq_excess.items():   # (notice 1152 is the government colleges' increase)
    if q in qmap and college_table[c] == 'govt':
        bound[(k, qmap[q])] += e
vs_notice = {k: {'notice_open': notice[k]['open'] if k in notice else 0, 'excess_open': bound[(k, 'open')],
                 'notice_service': notice[k]['service'] if k in notice else 0, 'excess_service': bound[(k, 'service')]}
             for k in sorted(set(notice) | {k for k, _ in bound})}
new_colleges = sorted({r['college_name'] for r in out} - r1_colleges)
gone_colleges = sorted(r1_colleges - {r['college_name'] for r in out})
cmp = {'round1_seats': sum(x['seats'] for x in r1), 'round2_seats': sum(r['seats'] for r in out),
       'new_in_round_rows_total': sum(r['new_in_round'] for r in out),
       'excess_over_round1_college_course_quota': sum(cq_excess.values()),
       'new_colleges': {c: sum(r['seats'] for r in out if r['college_name'] == c) for c in new_colleges},
       'round1_colleges_with_no_vacancy': gone_colleges,
       'added_lower_bound_vs_notice_1152': vs_notice,
       'excess_by_table': {t: sum(e for (c, k, q), e in cq_excess.items() if college_table[c] == t) for t in ('govt', 'self', 'private')},
       'excess_outside_government_colleges': {f'{c} | {k} | {q}': e for (c, k, q), e in cq_excess.items()
                                              if college_table[c] != 'govt'}}
json.dump({'rows': out, 'checks': checks, 'round1_comparison': cmp}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma')})
print('by table', dict(table_seats), '| colleges', len(college_table))
print('Round 1 → Round 2:', {k: cmp[k] for k in ('round1_seats', 'round2_seats', 'new_in_round_rows_total',
                                                 'excess_over_round1_college_course_quota')})
print('new colleges:', cmp['new_colleges'])
print('Round 1 colleges with no Round 2 vacancy:', gone_colleges)
print('added-seat lower bound (Round 2 − Round 1 per college × course × quota) vs notice 1152 (open / service):')
for k, v in vs_notice.items():
    flag = '' if (v['excess_open'], v['excess_service']) == (v['notice_open'], v['notice_service']) else '   <-- differs'
    print(f"   {k}: notice {v['notice_open']}/{v['notice_service']}, excess {v['excess_open']}/{v['excess_service']}{flag}")
print('excess over Round 1 by table:', cmp['excess_by_table'])
per = collections.Counter()
for k, e in cmp['excess_outside_government_colleges'].items():
    per[k.split(' | ')[0]] += e
print('excess outside the government colleges (not in notice 1152), per college:', dict(per))
