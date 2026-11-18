"""Karnataka KEA PGET 2026 — PROVISIONAL SECOND ROUND SEAT MATRIX (vacant seats, 18.11.2026) → seat rows for a
SEPARATE Round 2 body ("Karnataka — Round 2 — Vacant seats", list_type vacancy). The Round 1 body is never touched.

Layout: one table per college ("College: <name>"), one line per course × seat type ("M.D.Anaesthesia(GOVT)", PVT,
MGMT, NRI, …) with the college code (M01 …) and 67 seat-category columns in KEA allotment codes + Total; each
college ends with a "Total" line; the last page has the "Grand Total" line. Course names that wrap onto the next page
("…(N" + "RI)") are joined. Codes:
  1G/1H 2AG/2AH 2BG/2BH 3AG/3AH 3BG/3BH GM/GMH STG/STH  → Government Quota, CAT1 / 2A / 2B / 3A / 3B / GM / ST
  S1G..S4G / S1H..S4H (footer: S1 SCA, S2 SCB, S3 SCC(80%), S4 SCC(20%)) → SC-A / SC-B / SC-C / SC-C (20%); SCG/SCH → SC
  P… (P1G, P2AG, PGM, PGMH, PS1G, PSTG, …) → the same with '-PwD';  …H codes = Kalyana Karnataka → ' (KK)'
  GMP / GMPH → Private Quota - GMP; OPN → Private Quota - Open; NRI → NRI Quota; MNG → Management Quota (category
  'OTH(Q)', Round 1's label for the same column);
  MA MC ME MEH MK MM MMH MU → Private Quota - Minority; RC1-RC3 → Private Quota - Minority (St John's)
  DB / DJ / DM / PH → not mapped (all 0 in this file; a non-zero value stops the run).
Same quota / category spellings as tools/seat_matrix/karnataka.py (Round 1), so the 2025 cut-off bridge is identical.
Checks: every line's columns add to its Total; each college's lines add to its printed Total line (column by column);
every column adds to the Grand Total line; unknown college code / course → SystemExit.
    /usr/bin/python3 tools/seat_matrix/karnataka_round2.py <round2.pdf> <cutoffs2025.json> <out.json>
"""
import ast, collections, json, os, re, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

if len(sys.argv) != 4:
    raise SystemExit(__doc__)
PDF, CUTS, OUT = sys.argv[1:4]
key = lambda s: re.sub(r'[^a-z]', '', (s or '').lower())


def _literal(name):
    """COLLEGES / COURSES dicts straight from the Round 1 reader (one source of truth)."""
    src = open(os.path.join(os.path.dirname(__file__), 'karnataka.py')).read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) == name:
            return ast.literal_eval(node.value)
    raise SystemExit(f'{name} not found in karnataka.py')


COLLEGES = _literal('COLLEGES')
COURSE_BY_NAME = {}
for (code, nm), course in _literal('COURSES').items():
    COURSE_BY_NAME[nm] = course
COURSE_BY_NAME.update({  # Round 2 spellings not printed in Round 1
    'mdanaesthesia': 'MD - Anaesthesiology', 'msent': 'MS - ENT (Otorhinolaryngology)',
    'mdgeriatrics': 'MD - Geriatrics', 'msopthalmology': 'MS - Ophthalmology', 'msophthalmology': 'MS - Ophthalmology',
    'msorthopaedics': 'MS - Orthopaedics', 'mdtbrespiratorymedicine': 'MD - Respiratory Medicine',
    'diplomainpublichealth': 'Diploma in Public Health', 'diplomainclinicalpathology': 'Diploma in Pathology',
    'diplomaintuberculosischestdiseases': 'Diploma in Respiratory Medicine'})

HEAD = ['1G', '1H', '2AG', '2AH', '2BG', '2BH', '3AG', '3AH', '3BG', '3BH', 'DB', 'DJ', 'DM', 'GM', 'GMH', 'GMP', 'GMPH',
        'MA', 'MC', 'ME', 'MEH', 'MK', 'MM', 'MMH', 'MNG', 'MU', 'NRI', 'OPN', 'P1G', 'P1H', 'P2AG', 'P2AH', 'P2BG', 'P2BH',
        'P3AG', 'P3AH', 'P3BG', 'P3BH', 'PGM', 'PGMH', 'PH', 'PS1G', 'PS1H', 'PS2G', 'PS2H', 'PS3G', 'PS3H', 'PS4G', 'PSCG',
        'PSCH', 'PSTG', 'PSTH', 'RC1', 'RC2', 'RC3', 'S1G', 'S1H', 'S2G', 'S2H', 'S3G', 'S3H', 'S4G', 'S4H', 'SCG', 'SCH',
        'STG', 'STH']
UNMAPPED = {'DB', 'DJ', 'DM', 'PH'}
ROOTCAT = {'1': 'CAT1', '2A': '2A', '2B': '2B', '3A': '3A', '3B': '3B', 'GM': 'GM', 'ST': 'ST', 'S1': 'SC-A', 'S2': 'SC-B',
           'S3': 'SC-C', 'S4': 'SC-C (20%)', 'SC': 'SC'}
PRIV = {'GMP': 'Private Quota - GMP', 'GMPH': 'Private Quota - GMP', 'OPN': 'Private Quota - Open', 'NRI': 'NRI Quota',
        'MNG': 'Management Quota'}
MINORITY = {'MA', 'MC', 'ME', 'MEH', 'MK', 'MM', 'MMH', 'MU', 'RC1', 'RC2', 'RC3'}


def quota_cat(code):
    if code == 'MNG':                      # Round 1 printed this column as OTH(Q) — same label so rounds compare
        return 'Management Quota', 'OTH(Q)'
    if code in PRIV:
        return PRIV[code], code
    if code in MINORITY:
        return 'Private Quota - Minority', code
    pwd = code.startswith('P') and code not in ('PH',)
    c = code[1:] if pwd else code
    if c in ('GM', 'GMH'):
        root, kk = 'GM', c == 'GMH'
    else:
        root, kk = c[:-1], c.endswith('H')
        if not c.endswith(('G', 'H')) or root not in ROOTCAT:
            raise SystemExit(f'unknown seat code {code!r}')
    return 'Government Quota', ROOTCAT[root] + ('-PwD' if pwd else '') + (' (KK)' if kk else '')


nows = lambda s: re.sub(r'\s+', '', clean(s))
num = lambda s, where: int(nows(s)) if nows(s).isdigit() else (_ for _ in ()).throw(SystemExit(f'{where}: not a number {s!r}'))

doc = fitz.open(PDF)
if 'PROVISIONAL SECOND ROUND SEAT MATRIX' not in clean(doc[0].get_text()):
    raise SystemExit('title changed')
lines, college_totals, grand, last = [], collections.defaultdict(lambda: [0] * 68), None, None
seat_types = collections.Counter()
for pno, page in enumerate(doc, 1):
    for t in grids(page):
        h = [nows(x) for x in t[0]]
        if h[0] == 'GrandTotal':
            if h[1:] != HEAD + ['Total']:
                raise SystemExit(f'p{pno}: grand-total headings changed {h}')
            grand = [num(x, f'p{pno} grand') for x in t[1][1:]]
            continue
        if h[:2] != ['CourseName', 'CollegeCode'] or h[2:] != HEAD + ['Total']:
            raise SystemExit(f'p{pno}: column headings changed {h}')
        for r in t[1:]:
            name, code = clean(r[0]), nows(r[1])
            if name == 'Total' and not code:
                vals = [num(x, f'p{pno} college total') for x in r[2:]]
                college_totals[last] = [a + b for a, b in zip(college_totals[last], vals)] if last in college_totals else vals
                college_totals[(last, 'printed')] = vals
                continue
            if not code:                                   # wrapped course name continued from the previous page
                if not lines or any(nows(x) for x in r[2:]):
                    raise SystemExit(f'p{pno}: stray line {r[:3]}')
                lines[-1]['name'] += name
                continue
            if code not in COLLEGES:
                raise SystemExit(f'p{pno}: unknown college code {code!r} ({name})')
            vals = [num(x, f'p{pno} {code} {name}') for x in r[2:]]
            if sum(vals[:-1]) != vals[-1]:
                raise SystemExit(f'p{pno}: {code} {name}: columns add to {sum(vals[:-1])}, Total {vals[-1]}')
            lines.append({'code': code, 'name': name, 'vals': vals, 'page': pno})
            last = code

# per-college printed Total lines = sum of that college's lines
sums = collections.defaultdict(lambda: [0] * 68)
for ln in lines:
    sums[ln['code']] = [a + b for a, b in zip(sums[ln['code']], ln['vals'])]
checks = {}
for code, s in sums.items():
    p = college_totals.get((code, 'printed'))
    if p is None:
        raise SystemExit(f'{code}: no college Total line')
    checks[f'college {code} total'] = (s[-1], p[-1])
    if s != p:
        raise SystemExit(f'{code}: lines add to {s}, printed Total {p}')
if grand is None:
    raise SystemExit('no Grand Total line')
col = [sum(ln['vals'][i] for ln in lines) for i in range(68)]
for i, c in enumerate(HEAD + ['Total']):
    checks[f'grand {c}'] = (col[i], grand[i])

rows = []
for ln in lines:
    m = re.fullmatch(r'(.+?)\((.+)\)', nows(ln['name']))
    if not m:
        raise SystemExit(f'p{ln["page"]}: course without seat type {ln["name"]!r}')
    cname, stype = m.group(1), m.group(2)
    seat_types[stype] += ln['vals'][-1]
    course = COURSE_BY_NAME.get(key(cname))
    if not course:
        raise SystemExit(f'p{ln["page"]}: unknown course {cname!r}')
    sec = 'diploma' if course.startswith('Diploma') else 'mdms'
    for c, v in zip(HEAD, ln['vals'][:-1]):
        if not v:
            continue
        if c in UNMAPPED:
            raise SystemExit(f'p{ln["page"]}: {ln["code"]} {cname}: {v} seat(s) in unmapped column {c}')
        q, cat = quota_cat(c)
        rows.append({'college': COLLEGES[ln['code']][1], 'course': course, 'quota': q, 'seats': v, 'section': sec,
                     'category': cat, 'seat_type': stype})
checks['all seats'] = (sum(x['seats'] for x in rows), grand[-1])

agg = collections.OrderedDict()
for x in rows:
    k = (x['college'], x['course'], x['quota'], x['category'])
    if k in agg:
        agg[k]['seats'] += x['seats']
    else:
        agg[k] = {kk: vv for kk, vv in x.items() if kk != 'seat_type'}
rows = list(agg.values())

FAMILY = {'Government Quota': ('Government Quota$',), 'Private Quota - GMP': ('Private Quota - GMP$',),
          'Private Quota - Open': ('Private Quota - Open$',), 'NRI Quota': ('NRI Quota$',),
          'Management Quota': ('Management Quota$',), 'Private Quota - Minority': ('Private Quota - Minority$',)}
ROOT = {'GM': 'GM', 'CAT1': '1', '2A': '2A', '2B': '2B', '3A': '3A', '3B': '3B', 'ST': 'ST', 'SC-A': 'SC-A',
        'SC-B': 'SC-B', 'SC-C': 'SC-C', 'SC-C (20%)': 'SC-C', 'SC': 'SC'}


def kea(root, kk, pwd):
    c = ('GMH' if kk else 'GM') if root == 'GM' else root + ('H' if kk else 'G')
    return ('P' if pwd else '') + c


def cat_match(x):
    cat = x['category']
    if x['quota'] == 'Private Quota - GMP':
        return ('GMPH', 'GMP') if cat == 'GMPH' else ('GMP',)
    if x['quota'] == 'Management Quota':
        return ('MNG',)
    if x['quota'] in ('Private Quota - Open', 'NRI Quota', 'Private Quota - Minority'):
        return {'MMH': ('MMH', 'MM'), 'MEH': ('MEH', 'ME')}.get(cat, (cat,))
    m = re.fullmatch(r'(.+?)(-PwD)?( \(KK\))?', cat)
    root, pwd, kk = ROOT[m.group(1)], bool(m.group(2)), bool(m.group(3))
    seq = []
    for p in ((True, False) if pwd else (False,)):
        seq += [kea(root, kk, p), kea('GM', kk, p)] + ([kea(root, False, p), kea('GM', False, p)] if kk else [])
    return tuple(dict.fromkeys(seq))


cuts = load_cuts(CUTS, 'Karnataka')
cut_type = {c['institute']: c['institute_type'] for c in cuts}
out = build(rows, cuts, 'Karnataka', 'KA', lambda q: FAMILY[q], cat_match)
CODE_FIX = {'Employees State Insurance Corporation Medical College, Bangalore': 'KA-ESIC-MEDICAL-COLLEGE-BANGALORE',
            'Employees State Insurance Corporation Medical College, Gulbarga': 'KA-ESIC-MEDICAL-COLLEGE-GULBARGA'}
for r in out:
    r['college_code'] = CODE_FIX.get(r['college_name'], r['college_code'])
json.dump({'rows': out, 'checks': checks, 'seat_types': seat_types}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('seat types (course suffix):', dict(seat_types))
