"""Goa (DTE Goa) PG Medical SECOND (or later) ROUND allotment list → rows for POST /api/pg/results/ingest.
The Round 2 layout differs from Round 1 (tools/results/goa.py): no seat table; page 1 = instructions, then one line
per candidate on the merit list under GROUP headings: MERIT NO., REG NO., NAME, CATEGORY 1, CATEGORY 2, NEET PG RANK,
COURSE (programme code, '-' = no seat), REMARKS (documents still due — dropped), ROUND n STATUS
('ALLOTTED IN ROUND 2' / 'RETAINED SEAT FROM ROUND 1' / 'OCNA' / blank).
Reg numbers and names are never kept. Lines without a course are counted and skipped.
round_status: RETAINED → retained (must be the same course as the earlier round row of the same merit no. + NEET
rank); ALLOTTED with an earlier-round seat → upgraded (prev_* filled), without → fresh.
`rank` = MERIT NO., `rank_ai` = printed NEET PG RANK; allotted_category = candidate CATEGORY 2 (seat category is not
printed), the same convention as goa.py.
Run with /usr/bin/python3 (PyMuPDF):
    goa_r2.py <allotment.pdf> <out.json> --prev <earlier round rows.json> [--seat-matrix <Goa seat-matrix rows.json>]
              [--round "Round 2"] [--round-order 2] [--status provisional|final] [--published-on YYYY-MM-DD]
--prev: {"rows": [...]} as /api/pg/results returns them for the earlier round (rank, rank_ai, course, ...)."""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {}
for k in ('--prev', '--seat-matrix', '--round', '--round-order', '--status', '--published-on'):
    if k in args:
        i = args.index(k); opt[k] = args[i + 1]; del args[i:i + 2]
if len(args) != 2 or '--prev' not in opt:
    raise SystemExit(__doc__)
PDF, OUT = args
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SHEET = os.path.join(HERE, '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

ROUND = opt.get('--round') or 'Round 2'
RN = int(opt.get('--round-order') or 2)
HEAD = ['MERIT NO.', 'REG NO.', 'NAME OF THE CANDIDATE (as per MBBS Degree Certificate)', 'CATEGORY 1', 'CATEGORY 2',
        'NEET PG RANK', 'COURSE', 'REMARKS', f'ROUND {RN} STATUS']
# programme code → (printed programme name, approved course name): same map as goa.py
COURSES = {
    'ANA': ('ANAESTHESIOLOGY', 'MD - Anaesthesiology'), 'ANT': ('ANATOMY', 'MD/MS - Anatomy'),
    'BCH': ('BIOCHEMISTRY', 'MD - Biochemistry'), 'DER': ('DERMATOLOGY', 'MD - Dermatology'),
    'FRM': ('FORENSIC MEDICINE', 'MD - Forensic Medicine'), 'MED': ('GENERAL MEDICINE', 'MD - General Medicine'),
    'SUR': ('GENERAL SURGERY', 'MS - General Surgery'), 'GER': ('GERIATRICS', 'MD - Geriatrics'),
    'MBG': ('MICROBIOLOGY', 'MD - Microbiology'), 'OBG': ('OBSTETRICS & GYNAECOLOGY', 'MS - Obstetrics and Gynaecology'),
    'OPT': ('OPHTHALMOLOGY', 'MS - Ophthalmology'), 'ORT': ('ORTHOPAEDICS', 'MS - Orthopaedics'),
    'ORG': ('OTORHINOLARYNGOLOGY (ENT)', 'MS - ENT (Otorhinolaryngology)'), 'PDS': ('PAEDIATRICS', 'MD - Paediatrics'),
    'PAT': ('PATHOLOGY', 'MD - Pathology'), 'PHM': ('PHARMACOLOGY', 'MD - Pharmacology'),
    'PHY': ('PHYSIOLOGY', 'MD - Physiology'),
    'COM': ('PSM (COMMUNITY MEDICINE)', 'MD - Social & Preventive Medicine / Community Medicine'),
    'PSY': ('PSYCHIATRY', 'MD - Psychiatry'), 'RDG': ('RADIOLOGY (RADIO DIAGNOSIS)', 'MD - Radio-Diagnosis'),
    'RBM': ('TB (RESPIRATORY MEDICINE)', 'MD - Respiratory Medicine'),
    'TFM': ('TRANSFUSION MEDICINE (IHBT)', 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion')}
CATEGORY = {'-': 'GEN', 'OBC': 'OBC', 'SC': 'SC', 'ST': 'ST', 'EWS': 'EWS', 'PwD': 'DR-GEN'}
CAT_NO_SEAT_ONLY = {'OBC-O'}
STATUS = {f'ALLOTTED IN ROUND {RN}': 'allotted', f'RETAINED SEAT FROM ROUND {RN - 1}': 'retained',
          'OCNA': 'ocna', '': 'blank'}
COLLEGE = 'GOA MEDICAL COLLEGE'
clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()

doc = fitz.open(PDF)
p1 = clean(doc[0].get_text())
want = {2: 'SECOND', 3: 'THIRD', 4: 'FOURTH'}.get(RN, '')
if 'GOA MEDICAL COLLEGE' not in p1 or f'{want} ROUND ALLOTMENT LIST' not in p1:
    raise SystemExit(f'page 1 is not the DTE Goa {want} ROUND PG allotment list')
title_m = re.search(r'(PG DEGREE ADMISSION \d{4} - \w+ ROUND ALLOTMENT LIST)', p1)
status = opt.get('--status') or ('final' if re.search(r'\bFINAL\b', p1) else 'provisional')
cd = re.match(r'D:(\d{4})(\d{2})(\d{2})', doc.metadata.get('creationDate') or '')
published = opt.get('--published-on') or (f'{cd.group(1)}-{cd.group(2)}-{cd.group(3)}' if cd else '')

lines, group, groups = [], None, collections.Counter()
for pg in doc:
    for tb in pg.find_tables().tables:
        ex = tb.extract()
        if not ex or len(ex[0]) != len(HEAD):
            continue
        for r in ex:
            r = [clean(x) for x in r]
            if r[0].startswith('MERIT'):
                if r != HEAD:
                    raise SystemExit(f'p{pg.number + 1}: column headings changed: {r}')
                continue
            if re.fullmatch(r'GROUP [IVX]+', r[0]):
                if any(r[1:]):
                    raise SystemExit(f'p{pg.number + 1}: group heading line has data')
                group = r[0]; continue
            if not r[0].isdigit():
                raise SystemExit(f'p{pg.number + 1}: a line without a merit number')
            if not group:
                raise SystemExit('a merit line before the first GROUP heading')
            r[1] = r[2] = r[7] = ''            # reg no, name, document remarks: never kept
            lines.append((group, r)); groups[group] += 1
mn = [int(r[0]) for _, r in lines]
if mn != list(range(1, len(mn) + 1)):
    raise SystemExit(f'merit numbers are not 1..{len(mn)} in order — lines missing or read twice')

prev = {(int(x['rank']), int(x['rank_ai'])): x for x in json.load(open(opt['--prev']))['rows']}
approved = {c['course'] for c in json.load(open(SHEET))['courses']}
rows, unknown, no_seat, link = [], collections.Counter(), collections.Counter(), collections.Counter()
left_seat = []
for grp, r in lines:
    merit, _, _, cat1, cat2, air, code, _, st_raw = r
    if not air.isdigit():
        raise SystemExit(f'merit {merit}: NEET rank is not a number')
    merit, air = int(merit), int(air)
    if cat1 != 'GEN':
        unknown['CATEGORY 1: ' + cat1] += 1; continue
    if st_raw not in STATUS:
        unknown['status: ' + st_raw] += 1; continue
    st = STATUS[st_raw]
    p = prev.get((merit, air))
    if code in ('-', ''):
        if st in ('allotted', 'retained'):
            raise SystemExit(f'merit {merit}: status {st_raw!r} but no course')
        if cat2 not in CATEGORY and cat2 not in CAT_NO_SEAT_ONLY:
            unknown['CATEGORY 2: ' + cat2] += 1
        no_seat['OCNA' if st == 'ocna' else 'no course (blank)'] += 1
        if p:
            left_seat.append({'merit': merit, 'round1_course': p['course']})
        continue
    if code not in COURSES:
        unknown['course: ' + code] += 1; continue
    if cat2 not in CATEGORY:
        unknown['CATEGORY 2 (allotted): ' + cat2] += 1; continue
    if st not in ('allotted', 'retained'):
        raise SystemExit(f'merit {merit}: a course but status {st_raw!r}')
    name, std = COURSES[code]
    if std not in approved:
        raise SystemExit(f'{std!r} is not in specialty_sheet.json')
    row = {'sno': merit, 'rank': merit, 'rank_ai': air, 'quota_raw': 'State Quota', 'quota': 'Government Quota',
           'institute_raw': COLLEGE, 'course_raw': name, 'course': std, 'section': 'mdms',
           'allotted_category': CATEGORY[cat2], 'allotted_category_raw': '',
           'candidate_category': cat1 if cat2 == '-' else f'{cat1}/{cat2}', 'remarks': grp.title(),
           'round_status_raw': st_raw}
    if st == 'retained':
        if not p:
            raise SystemExit(f'merit {merit}: retained, but no earlier-round seat with this merit no. + NEET rank')
        if p['course'] != std:
            raise SystemExit(f'merit {merit}: retained, but the earlier-round course was {p["course"]!r}')
        row['round_status'] = 'retained'
    elif p:
        if p['course'] == std:      # the authority says "allotted in this round" for the same course (seat not
            row['round_status'] = 'fresh'   # joined in the earlier round, allotted again) — keep its wording
            row['remarks'] += f'; same course as {ROUND.replace(str(RN), str(RN - 1))}, printed as allotted in this round'
            link['allotted again, same course'] += 1
        else:
            row['round_status'] = 'upgraded'
            row.update(prev_quota_raw=p['quota_raw'], prev_quota=p['quota'], prev_institute_raw=p['institute_raw'],
                       prev_course_raw=p['course_raw'], prev_course=p['course'])
    else:
        row['round_status'] = 'fresh'
    link[row['round_status']] += 1
    rows.append(row)
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
if len(rows) + sum(no_seat.values()) != len(lines):
    raise SystemExit('allotted + no seat ≠ lines')
earlier_kept = sum(1 for x in rows if (x['rank'], x['rank_ai']) in prev)
prev_unaccounted = len(prev) - earlier_kept - len(left_seat)
if prev_unaccounted:
    raise SystemExit(f'{prev_unaccounted} earlier-round seats are on no Round {RN} line')

sm = None
if '--seat-matrix' in opt:
    seats = collections.Counter()
    for x in json.load(open(opt['--seat-matrix'])):
        seats[x['course_name']] += x['seats']
    got = collections.Counter(x['course'] for x in rows)
    sm = {'seat_matrix_seats': sum(seats.values()), 'allotted': len(rows),
          'over_matrix': {c: (got[c], seats[c]) for c in got if got[c] > seats[c]},
          'vacant_after_round': {c: seats[c] - got[c] for c in seats if seats[c] > got[c]}}
    if sm['over_matrix']:
        raise SystemExit(f'more seats allotted than the seat matrix has: {sm["over_matrix"]}')

rows.sort(key=lambda x: x['sno'])
C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'lines': len(lines), 'merit_1_to_n': True, 'groups': dict(groups), 'allotted': len(rows),
          'not_allotted': dict(no_seat), 'by_round_status': C('round_status'),
          'link_to_earlier_round': dict(link), 'earlier_round_seats': len(prev), 'earlier_seat_given_up': len(left_seat),
          'by_course': C('course'), 'by_allotted_category': C('allotted_category'), 'seat_matrix': sm,
          'state_rank': [min(x['rank'] for x in rows), max(x['rank'] for x in rows)],
          'ai_rank': [min(x['rank_ai'] for x in rows), max(x['rank_ai'] for x in rows)]}
out = {'authority_code': 'dte_goa', 'round': ROUND, 'round_order': RN, 'status': status,
       'title': (title_m.group(1).title() if title_m else f'Round {RN} Allotment List') + ' (Goa Medical College)',
       'published_on': published, 'source_file_name': os.path.basename(PDF),
       'notes': (f'Goa Medical College only, state quota. rank = MERIT NO., rank_ai = printed NEET PG RANK. Seat category '
                 f'not printed: allotted_category = candidate CATEGORY 2 ("-" = GEN, PwD = DR-GEN). round_status from '
                 f'the ROUND {RN} STATUS column; upgraded = allotted a different course than the earlier round. Lines '
                 f'without a course (blank / OCNA) are not imported. Reader: tools/results/goa_r2.py.'),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(json.dumps(checks, ensure_ascii=False, indent=1))
