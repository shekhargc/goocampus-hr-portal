"""Goa (DTE Goa) PG Medical allotment list (any round) → rows for POST /api/pg/results/ingest. One official PDF
(only Goa Medical College): page 1 instructions, page 2 the seat table (programme name, state-quota seats,
programme code), then one line per candidate on the merit list, under GROUP headings: MERIT NO., REG NO., NAME,
CATEGORY 1, CATEGORY 2, NEET PG RANK, COURSE ALLOTTED (a programme code; blank or OCNA = no seat).
Reg numbers and names are never kept. Blank / OCNA lines are counted and skipped.
`rank` = MERIT NO. (Goa state merit position — what My Allotments matches a doctor's home-state rank against),
`rank_ai` = the printed NEET PG RANK (the 2025 Goa cut-offs hold All-India ranks).
The list does NOT print the category of the seat a candidate got (the page-7 colour key only colours the candidate's
own category cell). allotted_category is therefore the candidate's reservation category (CATEGORY 2; '-' = GEN,
PwD = DR-GEN as in the 2025 Goa cut-offs); --seat-matrix walks the 2026 seat matrix (course × category seats) in
merit order and reports where that walk would put a candidate on a different seat (checks.seat_matrix_walk).
Run with /usr/bin/python3 (PyMuPDF):
    goa.py <allotment.pdf> <out.json> [--seat-matrix <Goa seat-matrix rows.json>] [--nbems <neet2026.json>]
           [--round "Round 1"] [--round-order 1] [--status provisional|final] [--published-on YYYY-MM-DD]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {}
for k in ('--seat-matrix', '--nbems', '--round', '--round-order', '--status', '--published-on'):
    if k in args:
        i = args.index(k); opt[k] = args[i + 1]; del args[i:i + 2]
if len(args) != 2:
    raise SystemExit(__doc__)
PDF, OUT = args
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

SEAT_HEAD = ['NAME OF PG DEGREE PROG.', 'NOS. OF STATE QUOTA SEATS', 'PROGRAMME CODE']
HEAD = ['MERIT NO.', 'REG NO.', 'NAME OF THE CANDIDATE (as per MBBS Degree Certificate)', 'CATEGORY 1', 'CATEGORY 2',
        'NEET PG RANK', 'COURSE ALLOTTED']
KEY = ['GEN', 'EWS', 'OBC', 'SC', 'ST', 'PwD']               # page-7 colour key (category cells only)
COURSES = {  # programme code → (printed programme name, approved course name)
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
NO_SEAT = {'': 'no seat (blank)', 'OCNA': 'OCNA'}
# CATEGORY 2 → 2025 Goa cut-off category (2025: GEN OBC SC ST DR-GEN; EWS is new). OBC-O (not a reservation
# category in the colour key) is accepted only on lines without a seat — an allotted OBC-O line stops the run.
CATEGORY = {'-': 'GEN', 'OBC': 'OBC', 'SC': 'SC', 'ST': 'ST', 'EWS': 'EWS', 'PwD': 'DR-GEN'}
CAT_NO_SEAT_ONLY = {'OBC-O'}
COLLEGE = 'GOA MEDICAL COLLEGE'          # as printed in the instructions (the list is for this one college)

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()


def num(s, what):
    if not re.fullmatch(r'\d+', s):
        raise SystemExit(f'{what} is not a number: {s!r}')
    return int(s)


doc = fitz.open(PDF)
p1 = clean(doc[0].get_text())
if 'PG MEDICAL ALLOTMENT LIST' not in p1 or 'GOA MEDICAL COLLEGE' not in p1:
    raise SystemExit('page 1 is not the DTE Goa PG medical allotment list')
title_m = re.search(r'(PG DEGREE ADMISSION \d{4} - PG MEDICAL ALLOTMENT LIST)', p1)
status = opt.get('--status') or ('final' if re.search(r'\bFINAL\b', p1) else 'provisional')
cd = re.match(r'D:(\d{4})(\d{2})(\d{2})', doc.metadata.get('creationDate') or '')
published = opt.get('--published-on') or (f'{cd.group(1)}-{cd.group(2)}-{cd.group(3)}' if cd else '')

# ── page 2: seats per programme ──
seats, printed_total = {}, None
t = doc[1].find_tables().tables[0].extract()
if [clean(x) for x in t[0]] != SEAT_HEAD:
    raise SystemExit(f'seat table headings changed: {t[0]}')
for r in t[1:]:
    name, n, code = [clean(x) for x in r]
    if name == 'TOTAL':
        printed_total = num(n, 'TOTAL seats'); continue
    if code not in COURSES or COURSES[code][0] != name:
        raise SystemExit(f'unknown programme {code!r} {name!r}')
    seats[code] = num(n, f'{code} seats')
if printed_total != sum(seats.values()):
    raise SystemExit(f'seat table adds to {sum(seats.values())}, TOTAL {printed_total}')

# ── colour key (page with the key): only to confirm the layout is unchanged ──
key_ok = any([clean(x) for x in tb.extract()[0]] == KEY for pg in doc for tb in pg.find_tables().tables
             if tb.extract() and len(tb.extract()[0]) == len(KEY))

# ── merit list; reg no + name dropped as each line is read ──
lines, group, groups = [], None, collections.Counter()
for pg in doc[2:]:
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
            r[1] = r[2] = ''
            lines.append((group, r)); groups[group] += 1
mn = [int(r[0]) for _, r in lines]
if mn != list(range(1, len(mn) + 1)):
    raise SystemExit(f'merit numbers are not 1..{len(mn)} in order — lines missing or read twice')
order_breaks = [int(b[1][0]) for a, b in zip(lines, lines[1:]) if a[0] == b[0] and int(a[1][5]) > int(b[1][5])]

approved = {c['course'] for c in json.load(open(SHEET))['courses']}
rows, unknown, no_seat = [], collections.Counter(), collections.Counter()
for grp, r in lines:
    merit, _, _, cat1, cat2, air, code = r
    merit, air = int(merit), num(air, f'merit {merit} NEET rank')
    if cat1 != 'GEN':
        unknown['CATEGORY 1: ' + cat1] += 1; continue
    if code in NO_SEAT:
        if cat2 not in CATEGORY and cat2 not in CAT_NO_SEAT_ONLY:
            unknown['CATEGORY 2: ' + cat2] += 1
        no_seat[NO_SEAT[code]] += 1
        continue
    if code not in COURSES:
        unknown['course: ' + code] += 1; continue
    if cat2 not in CATEGORY:
        unknown['CATEGORY 2 (allotted): ' + cat2] += 1; continue
    name, std = COURSES[code]
    if std not in approved:
        raise SystemExit(f'{std!r} is not in specialty_sheet.json')
    rows.append({'sno': merit, 'rank': merit, 'rank_ai': air, 'quota_raw': 'State Quota', 'quota': 'Government Quota',
                 'institute_raw': COLLEGE, 'course_raw': name, 'course': std, 'section': 'mdms',
                 'allotted_category': CATEGORY[cat2], 'allotted_category_raw': '',
                 'candidate_category': cat1 if cat2 == '-' else f'{cat1}/{cat2}', 'remarks': grp.title()})
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
if len(rows) + sum(no_seat.values()) != len(lines):
    raise SystemExit('allotted + no seat ≠ lines')
got = collections.Counter(next(c for c, v in COURSES.items() if v[0] == x['course_raw']) for x in rows)
seat_check = {c: (got.get(c, 0), seats.get(c, 0)) for c in set(seats) | set(got) if got.get(c, 0) != seats.get(c, 0)}
if seat_check:
    raise SystemExit(f'allotted per programme ≠ printed seats (parsed, printed): {seat_check}')

# ── optional: walk the 2026 seat matrix in merit order (GEN seat first, then own category, then PwD seats) ──
walk = None
if '--seat-matrix' in opt:
    left = collections.defaultdict(collections.Counter)
    for x in json.load(open(opt['--seat-matrix'])):
        left[x['course_name']][x['category']] += x['seats']
    sm_total = sum(sum(v.values()) for v in left.values())
    differs = []
    for x in rows:
        own = {'DR-GEN': 'GEN'}.get(x['allotted_category'], x['allotted_category'])
        order = ['GEN'] + ([own] if own != 'GEN' else []) + ['GEN-PwD'] + ([own + '-PwD'] if own != 'GEN' else [])
        seat = next((o for o in order if left[x['course']][o] > 0), None)
        if seat:
            left[x['course']][seat] -= 1
        else:     # no GEN / own-category seat left — the seat must have been a de-reserved one
            seat = next((o for o, n in left[x['course']].items() if n > 0), None)
            if seat:
                left[x['course']][seat] -= 1
        if (seat or '').split('-')[0] != own:
            differs.append({'merit': x['sno'], 'course': x['course'], 'candidate': x['allotted_category'],
                            'walk_seat': seat})
    walk = {'seat_matrix_seats': sm_total, 'same_category': len(rows) - len(differs), 'differs': differs,
            'seats_left': {c: {k: n for k, n in v.items() if n} for c, v in left.items() if +v}}

nb_check = None
if '--nbems' in opt:
    airs = {x['air'] for x in json.load(open(opt['--nbems']))}
    nb_check = {'printed_ai_rank_in_nbems': sum(1 for x in rows if x['rank_ai'] in airs),
                'not_in_nbems_merit': [x['sno'] for x in rows if x['rank_ai'] not in airs]}

rows.sort(key=lambda x: x['sno'])
C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'lines': len(lines), 'merit_1_to_n': True, 'neet_rank_order_breaks_within_group': order_breaks,
          'groups': dict(groups), 'allotted': len(rows), 'not_allotted': dict(no_seat),
          'seats_printed': printed_total, 'allotted_per_programme_equals_seats': True, 'colour_key_found': key_ok,
          'by_section': C('section'), 'by_quota': C('quota'), 'by_allotted_category': C('allotted_category'),
          'by_course': C('course'), 'allotted_category_method': 'candidate CATEGORY 2 (seat category not printed)',
          'seat_matrix_walk': walk,
          'rank_ai': {'rank_ai_source': 'printed NEET PG RANK column', 'printed': len(rows), 'nbems': nb_check},
          'state_rank': [min(x['rank'] for x in rows), max(x['rank'] for x in rows)],
          'ai_rank': [min(x['rank_ai'] for x in rows), max(x['rank_ai'] for x in rows)]}
out = {'authority_code': 'dte_goa', 'round': opt.get('--round') or 'Round 1',
       'round_order': int(opt.get('--round-order') or 1), 'status': status,
       'title': (title_m.group(1) if title_m else 'PG Medical Allotment List') + ' (Goa Medical College)',
       'published_on': published, 'source_file_name': os.path.basename(PDF),
       'notes': ('Goa Medical College only, state quota. rank = MERIT NO., rank_ai = printed NEET PG RANK. The list '
                 'prints no seat category: allotted_category = the candidate\'s own category (CATEGORY 2, "-" = GEN, '
                 'PwD = DR-GEN); allotted_category_raw left empty. remarks = merit group. Lines without a seat '
                 '(blank / OCNA) are not imported.'),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['round'], out['status'], out['published_on'])
print('lines', len(lines), '| allotted', len(rows), '| no seat', dict(no_seat), '| groups', dict(groups))
print('seats printed', printed_total, '| allotted per programme = seats ✓ | colour key found', key_ok,
      '| NEET-rank order breaks', order_breaks)
print('by allotted category', checks['by_allotted_category'])
if walk:
    print('seat-matrix walk:', walk['same_category'], 'same category,', len(walk['differs']), 'differ',
          [(d['merit'], d['course'], d['candidate'], d['walk_seat']) for d in walk['differs']], '| left', walk['seats_left'])
print('rank_ai', checks['rank_ai'], '| merit', checks['state_rank'], '| AI', checks['ai_rank'])
