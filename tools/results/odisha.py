"""Odisha (PG Medical Counselling Committee, MKCG Brahmapur) "COMMON ALLOTMENT" list of the State Quota PG Medical
counselling (Round 1: 04.11.2026) → rows for POST /api/pg/results/ingest. One PDF, three tables:
  COMMON ALLOTMENT- DIRECT CANDIDATES (MD/MS)       ┐ 8 columns: State Application No, Name of the Candidate (Dr),
  COMMON ALLOTMENT- INSERVICE CANDIDATES (MD/MS/DNB) ┘ CMR-UR, Choice No, Allotted College, Allotted Course,
                                                      Alloted Subject, Allotted Category
  SEATS LYING VACANT AFTER ROUND-1 ALLOTMENT          (Type of Seat, College, No of Seat, Course, Subject, Category)
                                                      → only counted into checks, not posted.
PERSONAL DATA: the application number and the name are never read into the output (columns 0 and 1 are blanked
the moment a line is read).

Ranks: `rank` = CMR-UR (the common merit rank, = 'Rank-UR' of the revised merit lists), `rank_ai` = NEET PG AIR
from our stored Odisha merit list of the same kind (direct → direct list, in-service incl. DNB → in-service list),
looked up by that rank. A rank printed 'A<n>' (a candidate added after rank n) is stored as n with no AIR — the
merit list's rank n is someone else.
Quota (2025 Odisha cut-off spellings): direct → Government Quota, in-service → Government Quota-Inservice, a "-MGT"
college → Management Quota / Management Quota-Inservice, DNB → DNB Quota (section dnb). Category as printed
('-PWD' → '-PwD'); candidate category is not printed.
Run with /usr/bin/python3 (PyMuPDF):
    odisha.py <allotment.pdf> <merit_direct.json> <merit_inservice.json> <out.json>
              [--seat-matrix <od seat-matrix dump.json>] [--round "Round 1"] [--round-order 1] [--status provisional]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {'--round': 'Round 1', '--round-order': '1', '--status': 'provisional'}
for f in ('--seat-matrix', '--round', '--round-order', '--status'):
    if f in args:
        i = args.index(f); opt[f] = args[i + 1]; del args[i:i + 2]
if len(args) != 4:
    raise SystemExit(__doc__)
PDF, M_DIRECT, M_INSERVICE, OUT = args

HEAD = ['State Application No', 'Name of the Candidate (Dr)', 'CMR-UR', 'Choice No', 'Allotted College',
        'Allotted Course', 'Alloted Subject', 'Allotted Category']
VAC_HEAD = ['Type of Seat', 'Name of College', 'No of Seat', 'Course', 'Subject', 'Category']
COLLEGES = {  # printed → (standard name = the 2026 seat matrix / 2025 cut-off name, management column?)
    'SCB MCH KATAKA': ('SCB Medical College, Cuttack', False),
    'MKCG MCH BERHAMPUR': ('Maharaja Krushna Chandra Gajapati Medical College and Hospital, Brahmapur', False),
    'VIMSAR BURLA': ('Veer Surendra Sai Institute of Medical Sciences and Research, Burla', False),
    'PGIMER BBSR': ('Postgraduate Institute of Medical Education & Research and Capital Hospital, Bhubaneswar', False),
    'AHRCC KATAKA': ('Acharya Harihar Post Graduate Institute of Cancer, Cuttack', False),
    'FM MCH BALESWAR': ('Fakir Mohan Medical College and Hospital, Balasore, Odisha', False),
    'PRM MCH BARIPADA': ('Pandit Raghunath Murmu Medical College and Hospital, Baripada, Mayurbhanj, Odisha', False),
    'BB MCH BALANGIR': ('Bhima Bhoi Medical College and Hospital, Balangir, Odisha', False),
    'HI-TECH MCH BBSR': ('Hi-Tech Medical College & Hospital, Bhubaneswar', False),
    'HI-TECH MCH RKL': ('Hi-Tech Medical College & Hospital, Rourkela', False),
    'DRIEMS KATAKA': ('DRIEMS Institute Of Health Sciences And Hospital, Tangi, Odisha', False),
    'HITECH-BBSR-MGT': ('Hi-Tech Medical College & Hospital, Bhubaneswar', True),
    'HITECH-RKL-MGT': ('Hi-Tech Medical College & Hospital, Rourkela', True),
    'DRIEMS-KATAKA-MGT': ('DRIEMS Institute Of Health Sciences And Hospital, Tangi, Odisha', True),
    'S J MCH PURI': ('Shri Jagannath Medical College and Hospital, Puri, Odisha', False),
    'SLN MCH KORAPUT': ('Saheed Laxman Nayak Medical College and Hospital, Koraput, Odisha', False)}
MDMS = {
    'ANATOMY': 'MD/MS - Anatomy', 'PHYSIOLOGY': 'MD - Physiology', 'BIOCHEMISTRY': 'MD - Biochemistry',
    'PHARMACOLOGY': 'MD - Pharmacology', 'FMT': 'MD - Forensic Medicine', 'PATHOLOGY': 'MD - Pathology',
    'MICROBIOLOGY': 'MD - Microbiology', 'COMM MEDICINE': 'MD - Social & Preventive Medicine / Community Medicine',
    'GEN MEDICINE': 'MD - General Medicine', 'PEDIATRICS': 'MD - Paediatrics', 'PSYCHIATRY': 'MD - Psychiatry',
    'RESP MEDICINE': 'MD - Respiratory Medicine', 'SKIN VD (DVL)': 'MD - Dermatology',
    'TRANSF MEDICINE': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'OBST & GYN': 'MS - Obstetrics and Gynaecology', 'GEN SURGERY': 'MS - General Surgery',
    'ORTHOPAEDICS': 'MS - Orthopaedics', 'OPHTHALMOLOGY': 'MS - Ophthalmology', 'ENT': 'MS - ENT (Otorhinolaryngology)',
    'ANESTHESIOLOGY': 'MD - Anaesthesiology', 'RADIODIAGNOSIS': 'MD - Radio-Diagnosis',
    'RADIOTHERAPY': 'MD - Radiotherapy / Radiation Oncology'}
DNB = {'GEN MEDICINE': 'DNB - General Medicine (Post-MBBS)', 'OBST & GYN': 'DNB - Obstetrics and Gynaecology (Post-MBBS)',
       'GEN SURGERY': 'DNB - General Surgery (Post-MBBS)', 'PEDIATRICS': 'DNB - Paediatrics (Post-MBBS)',
       'OPHTHALMOLOGY': 'DNB - Ophthalmology (Post-MBBS)', 'RESP MEDICINE': 'DNB - Respiratory Medicine (Post-MBBS)',
       'ANESTHESIOLOGY': 'DNB - Anaesthesiology (Post-MBBS)'}
CATS = {'UR', 'SC', 'ST', 'SEBC', 'EWS'}
SM_QUOTA = {'Government Quota': 'State Quota', 'Government Quota-Inservice': 'In-service Quota',
            'Management Quota': 'Management Quota', 'Management Quota-Inservice': 'Management Quota (In-service)',
            'DNB Quota': 'DNB Quota'}

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()


def category(s):
    s = s.replace('-PWD', '-PwD')
    base = s.split('-')[0]
    if base not in CATS or s.split('-', 1)[-1] not in (base, 'GC', 'ES', 'PwD'):
        raise SystemExit(f'unknown category {s!r}')
    return s


doc = fitz.open(PDF)
cd = re.match(r'D:(\d{4})(\d{2})(\d{2})', doc.metadata.get('creationDate') or '')
published = f'{cd.group(1)}-{cd.group(2)}-{cd.group(3)}' if cd else ''
lines, vacant, sec, titles = [], collections.Counter(), None, []
for pg in doc:
    for tb in pg.find_tables().tables:
        for r in tb.extract():
            c = [clean(x) for x in r]
            if c[0].startswith('COMMON ALLOTMENT- DIRECT'):
                sec = 'direct'; titles.append(c[0]); continue
            if c[0].startswith('COMMON ALLOTMENT- INSERVICE'):
                sec = 'inservice'; titles.append(c[0]); continue
            if c[0].startswith('SEATS LYING VACANT'):
                sec = 'vacant'; titles.append(c[0]); continue
            if c[0] == 'State Application No':
                if c != HEAD:
                    raise SystemExit(f'p{pg.number + 1}: column headings changed')
                continue
            if c[0] == 'Type of Seat':
                if c[:6] != VAC_HEAD:
                    raise SystemExit(f'p{pg.number + 1}: vacancy headings changed')
                continue
            if sec == 'vacant':
                if c[0] not in ('DIRECT', 'INSERVICE') or not c[2].isdigit():
                    raise SystemExit(f'p{pg.number + 1}: unexpected vacancy line')
                vacant[f'{c[0]} {c[3]}'] += int(c[2]); continue
            if sec not in ('direct', 'inservice') or not c[0].isdigit() or len(c) != len(HEAD):
                raise SystemExit(f'p{pg.number + 1}: unexpected line in {sec}')
            c[0] = c[1] = ''                                   # application no + name — never kept
            lines.append((sec, c))
if titles != ['COMMON ALLOTMENT- DIRECT CANDIDATES (MD/MS)-2026-27', 'COMMON ALLOTMENT- INSERVICE CANDIDATES (MD/MS/DNB)-2026-27',
              'SEATS LYING VACANT AFTER ROUND-1 ALLOTMENT']:
    raise SystemExit(f'section titles changed: {titles}')

merit = {'direct': {r['state_rank']: r['air'] for r in json.load(open(M_DIRECT))['rows']},
         'inservice': {r['state_rank']: r['air'] for r in json.load(open(M_INSERVICE))['rows']}}
sm = None
if '--seat-matrix' in opt:
    sm = collections.Counter()
    for x in json.load(open(opt['--seat-matrix']))['rows']:
        sm[(x['college_name'], x['course_name'], x['quota'])] += x['seats']

rows, ver, over = [], collections.Counter(), collections.Counter()
for n, (sec, c) in enumerate(lines, 1):
    rank_raw, inst_raw, course_raw, subj, cat_raw = c[2], c[4], c[5], c[6], c[7]
    if inst_raw not in COLLEGES:
        raise SystemExit(f'unknown college {inst_raw!r}')
    college, mgt = COLLEGES[inst_raw]
    if course_raw == 'MD/MS' and subj in MDMS:
        course, section = MDMS[subj], 'mdms'
    elif course_raw == 'DNB' and subj in DNB and sec == 'inservice':
        course, section = DNB[subj], 'dnb'
    else:
        raise SystemExit(f'unknown course {course_raw!r} / {subj!r} in {sec}')
    if section == 'dnb':
        quota = 'DNB Quota'
    elif mgt:
        quota = 'Management Quota' if sec == 'direct' else 'Management Quota-Inservice'
    else:
        quota = 'Government Quota' if sec == 'direct' else 'Government Quota-Inservice'
    m = re.fullmatch(r'(A?)(\d+)', rank_raw)
    if not m:
        raise SystemExit(f'line {n}: rank {rank_raw!r}')
    rank, after = int(m.group(2)), bool(m.group(1))
    ai = None if after else merit[sec].get(rank)
    ver['AIR from the merit list' if ai else ('added after rank (no AIR)' if after else 'AIR NOT FOUND')] += 1
    if sm is not None:
        over[(college, course, SM_QUOTA[quota])] += 1
    rows.append({'sno': n, 'rank': rank, 'rank_ai': ai, 'quota_raw': ('In-service' if sec == 'inservice' else 'Direct')
                 + (' · Management' if mgt else ''), 'quota': quota, 'institute_raw': inst_raw, 'institute': college,
                 'course_raw': f'{course_raw} {subj}', 'course': course, 'section': section,
                 'allotted_category': category(cat_raw), 'allotted_category_raw': cat_raw, 'candidate_category': '',
                 'remarks': (f'Rank printed {rank_raw} (added after rank {rank}). ' if after else '')
                 + f'Choice no. {c[3]}'})
if ver.get('AIR NOT FOUND'):
    raise SystemExit(f'ranks not in the merit list: {dict(ver)}')
for sec in ('direct', 'inservice'):
    rk = [x['rank'] for x in rows if x['quota_raw'].startswith('Direct' if sec == 'direct' else 'In-service')]
    if len(rk) != len(set(rk)):
        raise SystemExit(f'{sec}: a CMR-UR rank appears twice')
if sm is not None:
    bad = {k: v for k, v in over.items() if v > sm.get(k, 0)}
    if bad:
        raise SystemExit(f'more allotted than seat-matrix seats: {bad}')

C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'allotted': len(rows), 'by_list': dict(collections.Counter(s for s, _ in lines)), 'verification': dict(ver),
          'vacant_after_round': dict(vacant), 'by_quota': C('quota'), 'by_section': C('section'),
          'by_institute': C('institute'), 'by_allotted_category': C('allotted_category'),
          'seat_matrix_checked': sm is not None}
out = {'authority_code': 'ojee', 'round': opt['--round'], 'round_order': int(opt['--round-order']),
       'status': opt['--status'],
       'title': f'Common Allotment — {opt["--round"]}, State Quota PG Medical (Direct + In-service, MD/MS/DNB), Odisha',
       'published_on': published, 'source_file_name': os.path.basename(PDF),
       'notes': ('Odisha PG Medical Counselling Committee, state quota. rank = CMR-UR (common merit rank), rank_ai = NEET '
                 'PG AIR from the revised Odisha merit list of the same kind (direct / in-service). -MGT colleges = '
                 'management seats. Application numbers and names never kept.'),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['status'], out['published_on'])
for k, v in checks.items():
    if k not in ('by_institute',):
        print(k, v)
