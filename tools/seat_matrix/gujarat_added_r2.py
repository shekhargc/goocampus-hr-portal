"""Gujarat NEET PG 2026-27 Round 2 — "Newly Added seats for MD/MS/DIPLOMA - 02" (ACPPGMEC, 21-Nov-2026, 5 pages).
Same layout as the Round 1 matrix ("Tentative Vacant Seat for Round - 01"): two columns of course blocks per page, one line
per college code × quota (RMED-GQ …) with OP / SC / ST / SE / EWS / TOT, a total line per course block, the section lines
1-MD/MS and Total (no diploma section — every added seat is MD / MS), then p5 = course × quota and MD / MS × quota summaries
(UQ / GQ / MQ / NQ — no in-service IQ seats were added).
The parsing functions and maps (COLLEGES, QUOTAS, SUBJECTS, side_events, parse_blocks, FAMILY, cat_match) are executed
straight from gujarat.py (Round 1), so names / quotas / categories are exactly the Round 1 body's. The PDF is pinned by
SHA-256 (inbox 1895).
Every college code and course heading is checked up front; anything unknown is LISTED and the run stops. A mapping that
is only PROPOSED (not yet in gujarat.py) is used only with --accept-proposed — move it into gujarat.py COLLEGES once the
founder confirms it, then drop the flag.
Body "Gujarat — Round 2 — State Counselling" (round_no 2, list_type vacancy; Round 1 body untouched): every row is a newly
added seat, so new_in_round = seats. ACPPGMEC has not published a Round 2 vacancy list of Round 1 seats; if it does, those
rows join this body with new_in_round 0.
Checks: every line's categories = its TOT, each course block = its total line, S.No. sequence per block, the 1-MD/MS and
Total section lines, both p5 summaries (every course × quota, MD / MS × quota, Total 305), no IQ / diploma lines.
Round 1 comparison: per college × course × quota × category vs the stored Round 1 body (round1_dump.json = staging
seatmatrix-dump?body=Gujarat — State Counselling).
    /usr/bin/python3 tools/seat_matrix/gujarat_added_r2.py <added.pdf> <round1_dump.json> <cutoffs2025.json> <out.json> [--accept-proposed]
"""
import ast, collections, hashlib, json, os, re, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

args = [a for a in sys.argv[1:] if not a.startswith('--')]
if len(args) != 4:
    raise SystemExit(__doc__)
ADDED, R1DUMP, CUTS, OUT = args
ACCEPT = '--accept-proposed' in sys.argv
PIN = '5a8e8ad9eca02ac0f58840fa0b1d74c2ce564ebc221363545d512621ef227a7a'   # inbox 1895
got = hashlib.sha256(open(ADDED, 'rb').read()).hexdigest()
if got != PIN:
    raise SystemExit(f'{ADDED}: SHA-256 {got} is not the pinned file — ACPPGMEC re-issued it; re-check the layout')

# ── Round 1 definitions, executed from gujarat.py ──
WANT = {'COLLEGES', 'QUOTAS', 'key', 'SUBJECTS', 'CATS', 'side_events', 'subject', 'parse_blocks', 'FAMILY', 'cat_match'}
src = open(os.path.join(os.path.dirname(__file__), 'gujarat.py')).read()
nodes = [n for n in ast.parse(src).body
         if (isinstance(n, ast.FunctionDef) and n.name in WANT)
         or (isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', None) in WANT)]
R1 = {'clean': clean, 'grids': grids, 'fitz': fitz, 're': re, 'collections': collections}
exec(compile(ast.Module(body=nodes, type_ignores=[]), 'gujarat.py', 'exec'), R1)
if WANT - set(R1):
    raise SystemExit(f'not found in gujarat.py: {sorted(WANT - set(R1))}')
COLLEGES, QUOTAS, CATS, SUBJECTS, key = R1['COLLEGES'], R1['QUOTAS'], R1['CATS'], R1['SUBJECTS'], R1['key']

# PROPOSED, not yet confirmed (used only with --accept-proposed). PLMED is new in Round 2 (not in Round 1, not in the 2025
# cut-offs). ACPPGMEC codes are <town>MED (BHUMED Bhuj, PATMED Patan, AMRMED Amreli …); the only medical college in
# Palanpur is Banas Medical College and Research Institute (private, self-financed — it has UQ / GQ / MQ lines, no '*').
# Name as in the portal's indian_colleges_data.json.
PROPOSED = {'PLMED': 'Banas Medical College and Research Institute, Palanpur'}

doc = fitz.open(ADDED)
if len(doc) != 5 or any('Newly Added seats for MD/MS/DIPLOMA - 02' not in clean(p.get_text()) for p in doc):
    raise SystemExit('title / page count changed')
if '21-Nov-2026' not in doc[0].get_text():
    raise SystemExit('date line changed')
COLS = [153, 178, 202, 226, 254, 285]          # same grid as the Round 1 matrix

# ── pre-scan: every college code / quota / course heading must be known ──
unknown = collections.OrderedDict()
for p in range(4):
    for w in doc[p].get_text('words'):
        m = re.fullmatch(r'([A-Z]+)-([A-Z]+)', w[4])
        if m:
            if m.group(2) not in QUOTAS:
                unknown[f'quota {w[4]}'] = p + 1
            elif m.group(1) not in COLLEGES:
                unknown[f'college code {m.group(1)}' + (f' (proposed: {PROPOSED[m.group(1)]})' if m.group(1) in PROPOSED else '')] = p + 1
    for e in R1['side_events'](doc[p], COLS):
        if e[0] == 'course' and key(e[2]) not in SUBJECTS:
            unknown[f'course {e[2]!r}'] = p + 1
blocking = [u for u in unknown if not (ACCEPT and any(f'college code {c} ' in u + ' ' for c in PROPOSED))]
if blocking:
    raise SystemExit('UNKNOWN — add to gujarat.py maps only after checking (nothing guessed):\n  '
                     + '\n  '.join(f'p{unknown[u]}: {u}' for u in unknown)
                     + ('\n(re-run with --accept-proposed to use the PROPOSED mapping for a dry run)' if not ACCEPT else ''))
if ACCEPT:
    used = [c for c in PROPOSED if any(f'college code {c} ' in u + ' ' for u in unknown)]
    print('USING PROPOSED (unconfirmed) mappings:', {c: PROPOSED[c] for c in used})
    COLLEGES.update({c: PROPOSED[c] for c in used})

checks = {}
lines, star, sections, _ = R1['parse_blocks'](doc, range(4), COLS, 5, 'added')
for code, s in star.items():
    if len(s) != 1:
        raise SystemExit(f'{code} is starred on some lines only')
if any(q == 'IQ' for _, _, q in lines):
    raise SystemExit('in-service IQ lines present — the p5 summary has no IQ column')
if any(c.startswith('Diploma') for c, _, _ in lines):
    raise SystemExit('diploma lines present — no 2-Diploma section was printed')
col_sum = [sum(v[i] for v in lines.values()) for i in range(6)]
if sorted(sections) != ['1-MD/MS', 'Total']:
    raise SystemExit(f'section lines found: {sorted(sections)}')
for lab in ('1-MD/MS', 'Total'):
    for i, cat in enumerate(CATS + ['TOT']):
        checks[f'{lab} {cat}'] = (col_sum[i], sections[lab][i])

# ── p5 summaries ──
QORDER = ['UQ', 'GQ', 'MQ', 'NQ']
by_cq = collections.Counter()
for (c, code, q), v in lines.items():
    by_cq[(c, q)] += v[-1]
g = grids(doc[4])
if len(g) != 2 or [clean(x) for x in g[0][0][2:7]] != QORDER + ['Total'] or [clean(x) for x in g[1][0][1:6]] != QORDER + ['Total']:
    raise SystemExit('p5 summary layout changed')
grp = lambda c: 'MD' if c.startswith('MD') else 'MS'      # MD/MS - Anatomy counts under MD, as in Round 1
for tab, cells, keyfn, pick in ((0, lambda r: (clean(r[1]), r[2:7]), R1['subject'], lambda k: lambda c: c == k),
                                (1, lambda r: (clean(r[0]), r[1:6]), lambda s: s, lambda k: lambda c: grp(c) == k)):
    seen = set()
    for r in g[tab][1:]:
        name, vals = cells(r)
        vals = [int(clean(x)) for x in vals]
        if sum(vals[:4]) != vals[4]:
            raise SystemExit(f'p5 table {tab + 1}: {name} quotas {vals[:4]} ≠ total {vals[4]}')
        if name == 'Total':
            gotq = [sum(v for (c, q), v in by_cq.items() if q == qq) for qq in QORDER]
            for qq, a, b in zip(QORDER + ['Total'], gotq + [sum(gotq)], vals):
                checks[f'p5 table {tab + 1} Total {qq}'] = (a, b)
            continue
        k = keyfn(name)
        seen.add(k)
        gotq = [sum(v for (c, q), v in by_cq.items() if q == qq and pick(k)(c)) for qq in QORDER]
        if gotq + [sum(gotq)] != vals:
            raise SystemExit(f'p5 table {tab + 1}: {name} parsed {gotq + [sum(gotq)]}, printed {vals}')
        if tab == 1:
            checks[f'p5 {name}'] = (sum(gotq), vals[4])
    every = {c for c, q in by_cq} if tab == 0 else {grp(c) for c, q in by_cq}
    if seen != every:
        raise SystemExit(f'p5 table {tab + 1} rows {sorted(seen)} ≠ parsed {sorted(every)}')
checks['course blocks (each = its total line) = p5 course rows'] = (len({c for c, q in by_cq}), 23)

rows = []
for (c, code, q), v in lines.items():
    for cat, n in zip(CATS, v[:5]):
        if n:
            rows.append({'college': COLLEGES[code], 'course': c, 'quota': QUOTAS[q], 'seats': n, 'section': 'mdms',
                         'category': cat,
                         # the 2025 cut-offs call every non-starred college 'Private Institute'; a new one stays the same
                         'institute_type': None if code not in PROPOSED else 'Private Institute'})
checks['seats'] = (sum(x['seats'] for x in rows), 305)

cuts = load_cuts(CUTS, 'Gujarat')
out = build(rows, cuts, 'Gujarat', 'GJ', lambda q: R1['FAMILY'][q], R1['cat_match'])
for r in out:
    r['new_in_round'] = r['seats']                  # every seat in this file is newly added for Round 2

# ── Round 1 comparison ──
r1 = json.load(open(R1DUMP))['rows']
r1_line = collections.Counter()
r1_cc = collections.Counter()
for x in r1:
    r1_line[(x['college_name'], x['course_name'], x['quota'], x['category'])] += x['seats']
    r1_cc[(x['college_name'], x['course_name'])] += x['seats']
r1_colleges = {x['college_name'] for x in r1}
new_colleges = sorted({r['college_name'] for r in out} - r1_colleges)
cc = collections.Counter()
for r in out:
    cc[(r['college_name'], r['course_name'])] += r['seats']
on_existing_line = sum(r['seats'] for r in out if r1_line[(r['college_name'], r['course_name'], r['quota'], r['category'])])
new_cc = {k: v for k, v in cc.items() if not r1_cc[k]}
cmp = {'round1_seats': sum(x['seats'] for x in r1), 'round1_colleges': len(r1_colleges),
       'added_seats': sum(r['seats'] for r in out), 'new_colleges': new_colleges,
       'added_on_existing_round1_line': on_existing_line,
       'added_college_courses_not_in_round1': len(new_cc), 'seats_on_those': sum(new_cc.values()),
       'per_college': {c: sum(v for (cn, _), v in cc.items() if cn == c) for c in sorted({k[0] for k in cc})}}

json.dump({'rows': out, 'checks': checks, 'round1_comparison': cmp}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by quota × category', dict(collections.Counter((r['quota'], r['category']) for r in out for _ in range(r['seats']))))
print('Round 1 comparison:', {k: v for k, v in cmp.items() if k != 'per_college'})
for c, n in cmp['per_college'].items():
    print(f'   {n:>3}  {c}' + ('   (NEW college — not in Round 1)' if c in new_colleges else ''))
print('college × course lines with no Round 1 seats (new course at the college):')
for (c, k), v in sorted(new_cc.items()):
    print(f'   {v:>3}  {c} | {k}')
