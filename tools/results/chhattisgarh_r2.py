"""Chhattisgarh (DME CG) NEET-PG (MD/MS) Round 2 (and later) seat allotment result → rows for POST /api/pg/results/ingest.

From Round 2 the list prints 19 columns — SN, Candidate Roll No, Candidate Category, PH, Allotted institute Name/Round-1 Seat
Retained, Allotted Program, Candidate Preference, Alloted Quota, Alloted Cat., Allotted Gender, Candidate Gender, Neet Rank,
NEET Score, Bonus %, Bonus Marks, Total Marks, State Rank, Candidature Type, Remark — and Remark says
  'Fresh Allotment'              → round_status fresh
  'Upgraded'                     → round_status upgraded (prev_* = the Round 1 seat, found by All-India rank)
  'Not Upgraded (Seat Retained)' → round_status retained; the line prints NO seat ('Round-1 Seat Retained', '_'), so the
                                   seat, quota and category are copied from the Round 1 result line of the same All-India rank.
No names are printed. Roll numbers are used only in memory (optional --merit check) and dropped; candidate gender dropped.
`rank` = printed State Rank (Round 2 merit), `rank_ai` = printed Neet Rank (AIR). Course / candidature / category maps are
read from chhattisgarh.py (ast) so both readers stay in step.
Run with /usr/bin/python3 (PyMuPDF):
    chhattisgarh_r2.py <allotment.pdf> <round1_rows.json (chhattisgarh.py output)> <out.json>
                       [--merit merit.json (rows: roll, air, state_rank)] [--matrix round2_seat_matrix.json]"""
import json, os, re, sys, ast, collections
import fitz

args = sys.argv[1:]
opt = {}
for f in ('--merit', '--matrix'):
    if f in args:
        i = args.index(f); opt[f] = args[i + 1]; del args[i:i + 2]
if len(args) != 3:
    raise SystemExit(__doc__)
PDF, R1, OUT = args
HERE = os.path.dirname(os.path.abspath(__file__))
SHEET = os.path.join(HERE, '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')
_src = ast.parse(open(os.path.join(HERE, 'chhattisgarh.py')).read())
_lit = {t.id: ast.literal_eval(n.value) for n in _src.body if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name) and t.id in ('CANDIDATURE', 'SEAT_QUOTA', 'CAND_CAT', 'COURSES', 'MATRIX_NAME')}
CANDIDATURE, SEAT_QUOTA, CAND_CAT, COURSES, MATRIX_NAME = (
    _lit[k] for k in ('CANDIDATURE', 'SEAT_QUOTA', 'CAND_CAT', 'COURSES', 'MATRIX_NAME'))
COURSES = {**COURSES, 'MD Palliative Medicine': 'MD - Palliative Medicine'}   # first seen in Round 2
SEAT_QUOTA = set(SEAT_QUOTA) | {'NRI Open Quota', 'NRI Institutional Quota'}
CATEGORY = {f'{c}-{g}': (c + ('-F' if g == 'Female' else ''), 'F' if g == 'Female' else 'B')
            for c in ('UR', 'OBC', 'SC', 'ST', 'EWS') for g in ('NC', 'Female')}
HEAD = ['SN', 'Candidate Roll No', 'Candidate Category', 'PH', 'Allotted institute Name/Round-1 Seat Retained',
        'Allotted Program', 'Candidate Preference', 'Alloted Quota', 'Alloted Cat.', 'Allotted Gender', 'Candidate Gender',
        'Neet Rank', 'NEET Score', 'Bonus %', 'Bonus Marks', 'Total Marks (NEET Score + Bonus Marks)', 'State Rank',
        'Candidature Type', 'Remark']
CAND_ALIAS = {'BC': 'OBC', 'EW': 'EWS'}      # Round 2 prints 2-letter candidate categories for these
norm_ct = lambda s: re.sub(r'-\s+', '-', s)   # 'NMC- recognised' vs 'NMC-recognised'
CANDIDATURE = {norm_ct(k): v for k, v in CANDIDATURE.items()}
REMARK = {'Fresh Allotment': 'fresh', 'Upgraded': 'upgraded', 'Not Upgraded (Seat Retained)': 'retained'}
clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()
ROLL = re.compile(r'\d{11}')


def quota_for(seat_quota, ctype):
    """2025 cut-off spelling: Government Quota-<candidature>; NRI seats → NRI Quota-<candidature>."""
    q = CANDIDATURE[ctype]
    return q.replace('Government Quota', 'NRI Quota', 1) if seat_quota.startswith('NRI') else q


doc = fitz.open(PDF)
t0 = clean(doc[0].get_text())
m = re.search(r'Chhattisgarh NEET PG \(MD/MS\) (20\d\d) Round-(\d+) (Provisional|Final) Allotment List', t0)
if not m:
    raise SystemExit('title line changed')
YEAR, ROUND, STATUS, TITLE = m.group(1), int(m.group(2)), m.group(3).lower(), m.group(0)
if ROUND < 2:
    raise SystemExit('Round 1 list — use chhattisgarh.py')
pdate = re.match(r"D:(\d{4})(\d\d)(\d\d)", doc.metadata.get('creationDate') or '')

lines, rolls_text = [], 0
for pg in doc:
    rolls_text += len(set(ROLL.findall(pg.get_text())))
    for t in pg.find_tables().tables:
        for r in t.extract():
            if len(r) != 19:
                raise SystemExit(f'p{pg.number + 1}: a table line has {len(r)} columns')
            r = [clean(x) for x in r]
            if r[0] == 'SN':
                if r != HEAD:
                    raise SystemExit(f'p{pg.number + 1}: column headings changed: {r}')
            elif r[0].isdigit():
                lines.append(r)
            elif r[0] != TITLE or any(r[1:]):
                raise SystemExit(f'p{pg.number + 1}: unexpected table line')
sn = sorted(int(r[0]) for r in lines)
if sn != list(range(1, len(sn) + 1)):
    raise SystemExit(f'SN is not 1..{len(sn)} — lines missing or read twice')
if rolls_text != len(lines):
    raise SystemExit(f'{rolls_text} roll numbers in the page text but {len(lines)} table lines read')

r1 = json.load(open(R1))
if r1.get('authority_code') != 'dme_cg' or r1.get('round_order') != ROUND - 1:
    raise SystemExit('round_rows.json is not the previous Chhattisgarh round')
prev = {}
for x in r1['rows']:
    if x['rank_ai'] in prev:
        raise SystemExit(f"AIR {x['rank_ai']} twice in the earlier round")
    prev[x['rank_ai']] = x
mr = None
if '--merit' in opt:
    mr = {x['roll']: (x['state_rank'], x['air']) for x in json.load(open(opt['--merit']))['rows']}
ver = collections.Counter()
approved = {c['course'] for c in json.load(open(SHEET))['courses']}
rows, unknown, link = [], collections.Counter(), collections.Counter()
for r in lines:
    sno, roll, ccat, ph, inst, prog, _pref, squota, acat, agender, _cg, air, _s, _bp, _bm, _t, srank, ctype, rem = r
    w = f'SN {sno}'
    if not ROLL.fullmatch(roll):
        raise SystemExit(f'{w}: roll number has an unexpected shape')
    if not (air.isdigit() and srank.isdigit()):
        raise SystemExit(f'{w}: ranks not numbers')
    air, srank = int(air), int(srank)
    ccat, ctype = CAND_ALIAS.get(ccat, ccat), norm_ct(ctype)
    if mr is not None:
        ver['merit ' + ('match' if mr.get(roll) == (srank, air) else 'not found' if roll not in mr else 'MISMATCH')] += 1
    roll = None
    if rem not in REMARK:
        unknown['remark: ' + rem] += 1; continue
    status = REMARK[rem]
    if ctype not in CANDIDATURE:
        unknown['candidature: ' + ctype] += 1; continue
    if ccat not in CAND_CAT or ph not in ('N', 'Y'):
        unknown[f'candidate category {ccat} / PH {ph}'] += 1; continue
    p = prev.get(air)
    link[f'{status}: ' + ('in earlier round' if p else 'not in earlier round')] += 1
    row = {'sno': int(sno), 'rank': srank, 'rank_ai': air, 'candidate_category': ccat, 'remarks': ctype,
           'round_status': status, 'round_status_raw': rem, 'section': 'mdms'}
    if status == 'retained':
        if (inst, prog, squota, acat) != ('Round-1 Seat Retained', '_', '_', '_'):
            raise SystemExit(f'{w}: a retained line prints a seat')
        if not p:
            raise SystemExit(f'{w}: retained, but AIR {air} has no earlier-round seat')
        for k in ('quota_raw', 'quota', 'institute_raw', 'course_raw', 'course', 'allotted_category', 'allotted_category_raw'):
            row[k] = p[k]
        if norm_ct(p['remarks']) != ctype:
            link['retained: candidature changed since the earlier round'] += 1
    else:
        if squota not in SEAT_QUOTA:
            unknown['quota: ' + squota] += 1; continue
        if acat not in CATEGORY:
            unknown[f'category: {acat}'] += 1; continue
        cat, g = CATEGORY[acat]
        if agender != g:
            raise SystemExit(f'{w}: allotted category {acat} with allotted gender {agender}')
        base = cat.split('-')[0]
        if base != 'UR' and base != {'GN': 'UR'}.get(ccat, ccat):
            raise SystemExit(f'{w}: {base} seat to a {ccat} candidate')
        if prog not in COURSES:
            unknown['course: ' + prog] += 1; continue
        if COURSES[prog] not in approved:
            raise SystemExit(f'{COURSES[prog]!r} is not in specialty_sheet.json')
        if inst not in MATRIX_NAME:
            unknown['institute: ' + inst] += 1; continue
        row.update({'quota_raw': squota, 'quota': quota_for(squota, ctype), 'institute_raw': inst, 'course_raw': prog,
                    'course': COURSES[prog], 'allotted_category': cat + ('-PwD' if ph == 'Y' else ''),
                    'allotted_category_raw': acat + (' PH' if ph == 'Y' else '')})
        if status == 'upgraded':
            if not p:
                raise SystemExit(f'{w}: upgraded, but AIR {air} has no earlier-round seat')
            if (p['institute_raw'], p['course_raw']) == (inst, prog):
                link['upgraded: same college + course as before (quota/category change)'] += 1
            row.update({'prev_quota_raw': p['quota_raw'], 'prev_quota': p['quota'], 'prev_institute_raw': p['institute_raw'],
                        'prev_course_raw': p['course_raw'], 'prev_course': p['course'], 'prev_remarks': 'Round 1 seat'})
    rows.append(row)
del lines, mr
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
if any(k.endswith('MISMATCH') for k in ver):
    raise SystemExit(f'printed ranks disagree with the merit list: {dict(ver)}')

matrix = None
if '--matrix' in opt:      # seats newly taken in this round (fresh + upgraded) must fit the round's vacancy matrix
    mx = collections.Counter()
    for x in json.load(open(opt['--matrix']))['rows']:
        mx[(x['college_name'], x['course_name'])] += x['seats']
    got = collections.Counter((MATRIX_NAME[x['institute_raw']], x['course']) for x in rows if x['round_status'] != 'retained')
    over = {' | '.join(k): (n, mx.get(k, 0)) for k, n in got.items() if n > mx.get(k, 0)}
    matrix = {'groups': len(got), 'within_matrix': not over, 'over': over,
              'taken_this_round': sum(got.values()), 'seats_in_matrix': sum(mx.values())}

rows.sort(key=lambda x: x['sno'])
C = lambda f, rs=rows: dict(collections.Counter(x[f] for x in rs).most_common())
checks = {'lines': len(rows), 'sn_1_to_n': True, 'rolls_in_page_text': rolls_text, 'pages': len(doc),
          'by_round_status': C('round_status'), 'link_to_earlier_round': dict(link),
          'by_quota': C('quota'), 'by_quota_raw': C('quota_raw'), 'by_allotted_category': C('allotted_category'),
          'by_course': C('course'), 'colleges': len({x['institute_raw'] for x in rows}),
          'rank_ai': {'source': "printed 'Neet Rank' column", 'filled': len(rows), 'of': len(rows), 'verified_by_roll': dict(ver)},
          'seat_matrix': matrix,
          'state_rank': [min(x['rank'] for x in rows), max(x['rank'] for x in rows)],
          'ai_rank': [min(x['rank_ai'] for x in rows), max(x['rank_ai'] for x in rows)]}
out = {'authority_code': 'dme_cg', 'round': f'Round {ROUND}', 'round_order': ROUND, 'status': STATUS, 'title': TITLE,
       'published_on': f'{pdate.group(1)}-{pdate.group(2)}-{pdate.group(3)}' if pdate else None,
       'source_file_name': os.path.basename(PDF),
       'notes': 'DME Chhattisgarh Round 2+. quota = 2025 cut-off spelling from the Candidature Type column (NRI seats → '
                'NRI Quota-<candidature>); printed seat quota in quota_raw, candidature type in remarks. rank = State Rank '
                '(this round\'s merit list), rank_ai = printed Neet Rank. Retained lines print no seat — seat copied from the '
                'earlier round\'s line of the same AIR. published_on = PDF creation date.',
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
for k in ('lines', 'by_round_status', 'link_to_earlier_round', 'by_quota', 'by_quota_raw', 'by_allotted_category',
          'colleges', 'rank_ai', 'seat_matrix', 'state_rank', 'ai_rank'):
    print(k, checks[k])
print(out['status'], out['published_on'], TITLE)
