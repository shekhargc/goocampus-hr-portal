"""Rajasthan NEET PG 2026 Round 2 provisional seat matrices (RUHS, 14.11.2026) -> Round 2 VACANCY rows for a separate
body "Rajasthan — Round 2 — State Counselling" (round_no 2, list_type 'vacancy' -> superseded=2), exactly like the
Jharkhand / MCC Round 2 bodies. The Round 1 body ("Rajasthan — State Counselling", 749 rows / 2,573 seats) is never
touched. COURSES / COLLEGES / HOSPITALS / DIPLOMA lists are read from rajasthan.py (ast), so both stay in step.

Usage: /usr/bin/python3 rajasthan_round2.py <mdms_r2.pdf> <diploma_dnb_r2.pdf> <round1_rows.json> <cutoffs2025.json> <out.json>

- mdms_r2.pdf  ("MD/MS Seat Matrix (Round-2) 14.11.2026", 3 pages): p1 Government (one 'Total State Quota' column ->
  Government Quota) + RUHS-CMS / Society (State (Govt) -> Government Quota, State (Mgmt) -> Management Quota, Total);
  p2 private colleges (AI -> All India Quota, State -> State Quota, Mgmt -> Management Quota, Total); p3 = the
  summary per course (private colleges' AI nature / State / Mgmt split + the all-college total), cross-checked.
- diploma_dnb_r2.pdf ("Post MBBS DIPLOMA/DNB MATRIX (Round-2)", 1 page, regular in-service only): hospitals x 8 Post-MBBS
  diplomas (-> Diploma Quota (In-service)) + Post-MBBS DNB table (-> DNB Quota (In-service)).
- new_in_round = max(0, Round-2 seats - Round 1 seats) for the same college + course + quota.
Checks (stop on failure): course S.No + wording, every college's Total column = its quota columns, every Total Seats
line, p1+p2 per course = p3 all-college total per course, diploma row totals and table total. The p3 private
AI / State / Mgmt split disagrees with p2 on some courses (2026 R2: p2 cells, per-college totals and line totals all
agree, so p2 is used; the differences are listed in checks).
Colleges not in rajasthan.py (new in Round 2) get plain standard names in NEW_COLLEGES (reported).
"""
import sys, os, re, json, ast, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import college_code

MD, DIP, R1, CUTS, OUT = sys.argv[1:6]
_src = ast.parse(open(os.path.join(os.path.dirname(__file__), 'rajasthan.py')).read())
_lit = {t.id: ast.literal_eval(n.value) for n in _src.body if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name) and t.id in
        ('COURSES', 'RAW_KEY', 'COLLEGES', 'HOSPITALS', 'NEW_NAMES', 'DIPLOMA', 'DIPLOMA_RAW')}
COURSES, RAW_KEY, COLLEGES, HOSPITALS, NEW_NAMES, DIPLOMA, DIPLOMA_RAW = (
    _lit[k] for k in ('COURSES', 'RAW_KEY', 'COLLEGES', 'HOSPITALS', 'NEW_NAMES', 'DIPLOMA', 'DIPLOMA_RAW'))
NEW_COLLEGES = {   # first seen in the Round 2 matrix (not in Round 1, no 2025 cut-off)
    'GMC Alwar': 'Government Medical College, Alwar', 'GMC Sikar': 'Government Medical College, Sikar',
    'JIET Medical College': 'JIET Medical College and Hospital, Jodhpur', 'Vyas Medical College': 'Vyas Medical College, Jodhpur'}
COLLEGES = {**COLLEGES, **NEW_COLLEGES}

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()


def num(s):
    s = clean(s)
    if s in ('', '-'):
        return 0
    if not s.isdigit():
        raise SystemExit(f'not a number: {s!r}')
    return int(s)


def college_for(h):
    h = clean(h)
    hits = [v for k, v in COLLEGES.items() if h.startswith(k)]
    if len(hits) != 1:
        raise SystemExit(f'unknown / ambiguous college header: {h!r}')
    return hits[0]


def check_course(sno, raw):
    if RAW_KEY[sno] not in clean(raw).upper().replace('E.N.T.', 'E.N.T'):
        raise SystemExit(f'course mismatch at S.No. {sno}: {raw!r}')


rows, checks = [], {}
md = fitz.open(MD)
if md.page_count != 3:
    raise SystemExit('MD/MS matrix: expected 3 pages')
for pg in (0, 1):
    if 'Round - 2' not in clean(md[pg].find_tables().tables[0].extract()[0][1 + pg]) and 'Round - 2' not in ' '.join(
            clean(x) for x in md[pg].find_tables().tables[0].extract()[0]):
        raise SystemExit(f'p{pg + 1}: not the Round 2 matrix')
per_course = collections.defaultdict(lambda: collections.Counter())   # sno -> AI / State / Mgmt from p1+p2

# page 1: Government / RUHS-CMS / Society
t = md[0].find_tables().tables[0].extract()
hdr, sub = t[2], t[3]
groups, j = [], 2
while j < len(hdr):
    name = clean(hdr[j])
    if not name:
        j += 1; continue
    if name.startswith('Total'):
        tot_col = j; break
    if clean(sub[j]).startswith('Total State'):
        groups.append((college_for(name), [(j, 'Government Quota')], None)); j += 1
    else:
        if [clean(sub[j]), clean(sub[j + 1]), clean(sub[j + 2])] != ['State (Govt)', 'State (Mgmt)', 'Total State Quota']:
            raise SystemExit(f'p1 sub-headings at {name}: {sub[j:j + 3]}')
        groups.append((college_for(name), [(j, 'Government Quota'), (j + 1, 'Management Quota')], j + 2)); j += 3
p1 = 0
for r in t:
    if not clean(r[0]).isdigit():
        if clean(r[1]).startswith('Total Seats'):
            checks['p1_total'] = (p1, num(r[tot_col]))
        continue
    sno = int(clean(r[0])); check_course(sno, r[1]); line = 0
    for college, cols, tcol in groups:
        part = 0
        for ci, quota in cols:
            n = num(r[ci]); part += n
            if n:
                rows.append({'college': college, 'course': COURSES[sno], 'quota': quota, 'seats': n, 'section': 'mdms'})
                per_course[sno]['all'] += n
        if tcol is not None and part != num(r[tcol]):
            raise SystemExit(f'p1 S.No {sno} {college}: total {num(r[tcol])} != {part}')
        line += part
    if line != num(r[tot_col]):
        raise SystemExit(f'p1 S.No {sno}: line total {num(r[tot_col])} != {line}')
    p1 += line

# page 2: private colleges — AI / State / Mgmt / Total
t = md[1].find_tables().tables[0].extract()
hdr, sub = t[2], t[3]
groups, j = [], 2
while j < len(hdr):
    name = clean(hdr[j])
    if not name:
        j += 1; continue
    if name.startswith('Total'):
        tot_col = j; break
    if [clean(x) for x in sub[j:j + 4]] != ['Al', 'State', 'Mgmt', 'Total Seats']:
        raise SystemExit(f'p2 sub-headings at {name}: {sub[j:j + 4]}')
    groups.append((college_for(name), [(j, 'All India Quota'), (j + 1, 'State Quota'), (j + 2, 'Management Quota')], j + 3)); j += 4
p2 = 0
for r in t:
    if not clean(r[0]).isdigit():
        if clean(r[1]).startswith('Total Seats'):
            checks['p2_total'] = (p2, num(r[tot_col]))
        continue
    sno = int(clean(r[0])); check_course(sno, r[1]); line = 0
    for college, cols, tcol in groups:
        part = 0
        for ci, quota in cols:
            n = num(r[ci]); part += n
            if n:
                rows.append({'college': college, 'course': COURSES[sno], 'quota': quota, 'seats': n, 'section': 'mdms'})
                per_course[sno][{'All India Quota': 'AI', 'State Quota': 'State', 'Management Quota': 'Mgmt'}[quota]] += n
                per_course[sno]['all'] += n
        if part != num(r[tcol]):
            raise SystemExit(f'p2 S.No {sno} {college}: total {num(r[tcol])} != {part}')
        line += part
    if line != num(r[tot_col]):
        raise SystemExit(f'p2 S.No {sno}: line total {num(r[tot_col])} != {line}')
    p2 += line

# page 3: summary per course
t = md[2].find_tables().tables[0].extract()
p3, p3_split_diff = 0, []
for r in t:
    if not clean(r[0]).isdigit():
        if clean(r[1]).startswith('Total Seats'):
            checks['p3_total'] = (p1 + p2, num(r[5]))
        continue
    sno = int(clean(r[0])); check_course(sno, r[1])
    ai, st, mg, tot = (num(r[i]) for i in (2, 3, 4, 5))
    pc = per_course[sno]          # p3: private-college AI / State / Mgmt split + the all-college total
    if tot != pc['all']:
        raise SystemExit(f'p3 S.No {sno}: summary total {tot} != pages 1-2 {pc["all"]}')
    if (ai, st, mg) != (pc['AI'], pc['State'], pc['Mgmt']):   # PDF slip: p3's private split is not always p2's
        p3_split_diff.append((sno, (ai, st, mg), (pc['AI'], pc['State'], pc['Mgmt'])))
    p3 += tot
checks['p3_private_split_differs_from_p2'] = p3_split_diff
for k in ('p1_total', 'p2_total', 'p3_total'):
    if k not in checks or checks[k][0] != checks[k][1]:
        raise SystemExit(f'{k}: {checks.get(k)}')

# Post-MBBS Diploma + DNB (in-service)
dp = fitz.open(DIP)
tabs = dp[0].find_tables().tables
t = [x for tb in tabs for x in tb.extract()]
if 'Round-2' not in clean(t[0][1]):
    raise SystemExit('diploma: not the Round 2 matrix')
for i, raw in enumerate(DIPLOMA_RAW):
    if raw.lower() not in clean(t[1][2 + i]).lower():
        raise SystemExit(f'diploma column {i} is {t[1][2 + i]!r}')
dip, dip_tot, k = 0, None, 2
while k < len(t):
    r = t[k]; k += 1
    if not clean(r[0]).isdigit():
        if 'Total' in clean(r[1]):
            dip_tot = num(r[10]); break
        if 'DNB' in clean(r[1]):
            break
        continue
    hosp = clean(r[1])
    if hosp not in HOSPITALS:
        raise SystemExit(f'unknown hospital {hosp!r}')
    name = HOSPITALS[hosp] or NEW_NAMES[hosp]
    vals = [num(r[2 + i]) for i in range(8)]
    if sum(vals) != num(r[10]):
        raise SystemExit(f'diploma {hosp}: row total')
    for course, n in zip(DIPLOMA, vals):
        if n:
            rows.append({'college': name, 'course': course, 'quota': 'Diploma Quota (In-service)', 'seats': n, 'section': 'diploma'})
    dip += sum(vals)
checks['diploma_total'] = (dip, dip_tot if dip_tot is not None else dip)
if checks['diploma_total'][0] != checks['diploma_total'][1]:
    raise SystemExit(f'diploma total {checks["diploma_total"]}')
dnb = 0
for r in t[k:]:
    c = [clean(x) for x in r]
    if c[0].isdigit():
        if 'Jaipuria' not in c[1]:
            raise SystemExit(f'DNB hospital {c[1]!r}')
        for course, n in (('DNB - Emergency Medicine (Post-MBBS)', num(c[2])), ('DNB - Family Medicine (Post-MBBS)', num(c[3]))):
            if n:
                rows.append({'college': 'Government RDBP Jaipuria Hospital, Jaipur, Rajasthan', 'course': course,
                             'quota': 'DNB Quota (In-service)', 'seats': n, 'section': 'dnb'})
                dnb += n
checks['dnb'] = (dnb, dnb)

# new_in_round vs Round 1 (same college + course + quota)
r1 = collections.Counter()
for x in json.load(open(R1)):
    r1[(x['college_name'], x['course_name'], x['quota'])] += int(x['seats'])
for x in rows:
    x['new_in_round'] = max(0, x['seats'] - r1.get((x['college'], x['course'], x['quota']), 0))

# bridge to 2025 cut-offs (same rule as rajasthan.py)
cuts = [c for c in json.load(open(CUTS))['rows'] if c['authority'] and 'rajasthan' in c['authority'].lower()]
inst_type = {c['institute']: c['institute_type'] for c in cuts}
by = collections.defaultdict(list)
for c in cuts:
    by[(c['institute'], c['course'])].append(c)
fam = {'Government Quota': 'Government Quota', 'Management Quota': 'Management Quota', 'All India Quota': 'All India Quota',
       'State Quota': 'State Quota', 'Diploma Quota (In-service)': 'Diploma Quota'}
all_courses = {c['course'] for c in json.load(open(CUTS))['rows'] if c['course']}
out = []
for i, x in enumerate(rows, 1):
    cand = [c for c in by.get((x['college'], x['course']), []) if c['quota'].startswith(fam.get(x['quota'], '~'))]
    pick = (sorted(cand, key=lambda c: (c['category'] != 'GEN', 'Non Service' not in c['quota'],
                                        -(c['closing_rank'] or 0)))[:1] or [None])[0]
    known = x['college'] in inst_type
    out.append({'sl_no': i, 'college_code': college_code('RJ', x['college']), 'state': 'Rajasthan',
                'college_name': x['college'], 'category': '', 'course_name': x['course'], 'seats': x['seats'],
                'section': x['section'],
                'institute_type': inst_type.get(x['college'], 'Private Institute' if x['quota'] == 'All India Quota' else 'Government Institute'),
                'quota': x['quota'], 'category_code': '', 'course_code': '',
                'cutoff_institute': x['college'] if known else '',
                'cutoff_course': x['course'] if (pick or x['course'] in all_courses) else '',
                'cutoff_quota': pick['quota'] if pick else '', 'cutoff_category': pick['category'] if pick else '',
                'has_cutoff': 1 if pick else 0,
                'new_reason': '' if pick else ('new_college' if not known else
                                               ('new_course' if not by.get((x['college'], x['course'])) else 'new_quota_category')),
                'cr_r1': pick['r1'] if pick else None, 'cr_r2': pick['r2'] if pick else None,
                'cr_r3': pick['r3'] if pick else None, 'cr_closing': pick['closing_rank'] if pick else None,
                'cutoff_fee': pick['fee'] if pick else None, 'new_in_round': x['new_in_round']})
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
print('checks (parsed, printed):', checks)
print('rows', len(out), 'seats', sum(r['seats'] for r in out), 'colleges', len({r['college_name'] for r in out}))
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
print('by quota', {q: sum(r['seats'] for r in out if r['quota'] == q) for q in sorted({r['quota'] for r in out})})
print('linked to a 2025 cut-off:', sum(1 for r in out if r['has_cutoff']), '| new:',
      dict(collections.Counter(r['new_reason'] for r in out if not r['has_cutoff'])))
print('new_in_round seats', sum(r['new_in_round'] for r in out), 'by college',
      dict(collections.Counter({c: sum(r['new_in_round'] for r in out if r['college_name'] == c) for c in {r['college_name'] for r in out}}).most_common(12)))
print('new colleges (not in Round 1):', sorted({r['college_name'] for r in out} - {k[0] for k in r1}))
