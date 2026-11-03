"""Jharkhand (JCECEB) provisional seat allotment list of the State Quota PG Medical counselling (any round) → rows for
POST /api/pg/results/ingest. One table, 20 columns per allotted candidate: Sl. No., App. No., Roll No., Name, Gender,
D.O.B., Category, Is EWS, Is PWD, DisabilityType, Incentive %, CML Rank, Category Rank, EWS Rank, PTG Rank, D.Q. Rank,
Allotted Institute, Allotted Course, Seat Opted Category, Roster Point. PERSONAL DATA: App. No., name, gender and date
of birth are never read into the output; the roll number is held in memory only, to look the AIR up, and dropped.

Ranks: `rank` = CML Rank (the JCECEB state common merit list rank), `rank_ai` = NEET PG All India Rank from the NBEMS
2026 result by roll. Quota: the list prints none. A seat is 'Government Quota-Inservice' (2025 spelling) when the
2026 seat matrix has ONLY in-service seats for that institute + course (MGM diplomas, Sadar Hospital and RINPAS
Post-MBBS DNB); a course with both kinds of seat stops the run (never guessed). Category = Seat Opted Category
(2025 spellings: UR ST SC EWS BC-I BC-II; UR-PH is new — 2025 has only BC-I-PH); candidate category → candidate_category.
Run with /usr/bin/python3 (PyMuPDF):
    jharkhand.py <allotment.pdf> <out.json> --seat-matrix <jh seat-matrix out.json> [--nbems neet2026.json]
                 [--round "Round 1"] [--round-order 1] [--status provisional|final]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {'--round': 'Round 1', '--round-order': '1', '--status': 'provisional'}
for f in ('--seat-matrix', '--nbems', '--round', '--round-order', '--status'):
    if f in args:
        i = args.index(f); opt[f] = args[i + 1]; del args[i:i + 2]
if len(args) != 2 or '--seat-matrix' not in opt:
    raise SystemExit(__doc__)
PDF, OUT = args
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

HEAD = ['Sl. No.', 'App. No.', 'Roll No.', 'Name of the Candidate', 'Gender', 'D.O.B.', 'Category', 'Is EWS', 'Is PWD',
        'DisabilityType', 'Incentive %', 'CML Rank', 'Category Rank', 'EWS Rank', 'PTG Rank', 'D.Q. Rank',
        'Allotted Institute', 'Allotted Course', 'Seat Opted Category', 'Roster Point']
COLLEGES = {  # printed institute → standard name (same as the 2026 seat matrix / 2025 cut-offs)
    'Rajendra Institute of Medical Sciences, Ranchi': 'Rajendra Institute of Medical Sciences, Ranchi',
    'Mahatma Gandhi Memorial Medical College, Jamshedpur': 'Mahatma Gandhi Memorial Medical College, Jamshedpur',
    'SNMMCH, Dhanbad': 'Shaheed Nirmal Mahto Medical College & Hospital, Dhanbad',
    'Sadar Hospital Ranchi': 'Sadar Hospital, Ranchi',
    'Ranchi Institute of Nuero- Psychiatry and Allied Sciences, Kanke,Ranchi':
        'Ranchi Institute of Neuro-Psychiatry and Allied Sciences, Kanke, Ranchi'}
COURSES = {  # printed course → (approved course name, section)
    'M.D. (General Medicine)': ('MD - General Medicine', 'mdms'), 'M.D. (Paediatrics)': ('MD - Paediatrics', 'mdms'),
    'M.S. (Orthopedics)': ('MS - Orthopaedics', 'mdms'), 'M.S. (General Surgery)': ('MS - General Surgery', 'mdms'),
    'M.D. (Obs. & Gynae.)': ('MS - Obstetrics and Gynaecology', 'mdms'),
    'M.D./ M.S. (Obs. & Gynae.)': ('MS - Obstetrics and Gynaecology', 'mdms'),
    'M.S. (Ophthalmology) EYE': ('MS - Ophthalmology', 'mdms'), 'M.S. (ENT)': ('MS - ENT (Otorhinolaryngology)', 'mdms'),
    'M.S. (Otorhinolaryngology) ENT': ('MS - ENT (Otorhinolaryngology)', 'mdms'),
    'M.D. (Derm., Ven. & Leprosy)': ('MD - Dermatology', 'mdms'), 'M.D. (Anesthesiology)': ('MD - Anaesthesiology', 'mdms'),
    'M.D. (Radio-Diagnosis)': ('MD - Radio-Diagnosis', 'mdms'),
    'M.D. (Community Medicine)': ('MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    'M.D./ M.S. (Anatomy)': ('MD/MS - Anatomy', 'mdms'), 'M.D. (Physiology)': ('MD - Physiology', 'mdms'),
    'M.D. (Pathology)': ('MD - Pathology', 'mdms'), 'M.D. (Microbiology)': ('MD - Microbiology', 'mdms'),
    'M.D. (Pharmacology)': ('MD - Pharmacology', 'mdms'), 'M.D. (Biochemistry)': ('MD - Biochemistry', 'mdms'),
    'M.D. (Forensic Medicine)': ('MD - Forensic Medicine', 'mdms'),
    'D.G.O.': ('Diploma in Obstetrics and Gynaecology', 'diploma'),
    'D.C.H.': ('Diploma in Child Health / Paediatrics', 'diploma'),
    'D.M.R.D.': ('Diploma in Radio Diagnosis', 'diploma'),
    'Post M.B.B.S D.N.B (Obst. & Gyne)': ('DNB - Obstetrics and Gynaecology (Post-MBBS)', 'dnb'),
    'Post M.B.B.S D.N.B . (General Surgery)': ('DNB - General Surgery (Post-MBBS)', 'dnb'),
    'Post M.B.B.S D.N.B. (Pathology)': ('DNB - Pathology (Post-MBBS)', 'dnb'),
    'Post M.B.B.S D.N.B. (Psychiatry)': ('DNB - Psychiatry (Post-MBBS)', 'dnb')}
CATEGORY = {'UR': 'UR', 'ST': 'ST', 'SC': 'SC', 'EWS': 'EWS', 'BC-I': 'BC-I', 'BC-II': 'BC-II', 'UR-PH': 'UR-PH',
            'BC-I-PH': 'BC-I-PH'}

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()

doc = fitz.open(PDF)
cd = re.match(r'D:(\d{4})(\d{2})(\d{2})', doc.metadata.get('creationDate') or '')
published = f'{cd.group(1)}-{cd.group(2)}-{cd.group(3)}' if cd else ''
lines = []
for pg in doc:
    for tb in pg.find_tables().tables:
        for r in tb.extract():
            c = [clean(x) for x in r]
            if c[0] == 'Sl. No.':
                if c != HEAD:
                    raise SystemExit(f'p{pg.number + 1}: column headings changed: {c}')
                continue
            if not c[0].isdigit():
                raise SystemExit(f'p{pg.number + 1}: a line without a serial number')
            if len(c) != len(HEAD):
                raise SystemExit(f'p{pg.number + 1}: {len(c)} columns')
            c[1] = c[3] = c[4] = c[5] = ''                     # app no, name, gender, DOB — never kept
            lines.append(c)
sl = [int(c[0]) for c in lines]
if sl != list(range(1, len(sl) + 1)):
    raise SystemExit(f'serial numbers are not 1..{len(sl)} in order — lines missing or read twice')

# seat matrix: which institute + course has which kinds of seat
kinds = collections.defaultdict(set)
for x in json.load(open(opt['--seat-matrix']))['rows']:
    kinds[(x['cutoff_institute'] or x['college_name'], x['course_name'])].add(x['quota'])
nbems = {str(x['roll']): x.get('air') for x in json.load(open(opt['--nbems']))} if '--nbems' in opt else {}

approved = {c['course'] for c in json.load(open(SHEET))['courses']}
rows, unknown, ver = [], collections.Counter(), collections.Counter()
for c in lines:
    sno, roll, ccat, ews, pwd, inc, cml = c[0], re.sub(r'\D', '', c[2]), c[6], c[7], c[8], c[10], c[11]
    inst, course_raw, seat_cat = c[16], c[17], c[18]
    if inst not in COLLEGES: unknown['institute: ' + inst] += 1; continue
    if course_raw not in COURSES: unknown['course: ' + course_raw] += 1; continue
    if seat_cat not in CATEGORY: unknown['seat category: ' + seat_cat] += 1; continue
    college, (course, section) = COLLEGES[inst], COURSES[course_raw]
    if section != 'dnb' and course not in approved:          # Post-MBBS DNB names follow the seat matrix
        raise SystemExit(f'{course!r} is not in specialty_sheet.json')
    k = kinds.get((college, course))
    if not k:
        raise SystemExit(f'line {sno}: {college} | {course} is not in the 2026 seat matrix')
    if k == {'In-service Quota'}:
        quota = 'Government Quota-Inservice'; ver['in-service (matrix has only in-service seats)'] += 1
    elif k == {'State Quota'}:
        quota = 'Government Quota'
    else:
        raise SystemExit(f'line {sno}: {college} | {course} has both state and in-service seats — quota not printed')
    ai = nbems.get(roll)
    ver['AIR found in NBEMS by roll' if ai else 'AIR NOT found in NBEMS'] += 1
    cand = ccat + ('/EWS' if ews == 'YES' else '') + ('/PwD' if pwd == 'YES' else '')
    rows.append({'sno': int(sno), 'rank': int(cml), 'rank_ai': int(ai) if ai else None,
                 'quota_raw': '', 'quota': quota, 'institute_raw': inst, 'institute': college,
                 'course_raw': course_raw, 'course': course, 'section': section,
                 'allotted_category': CATEGORY[seat_cat], 'allotted_category_raw': seat_cat,
                 'candidate_category': cand,
                 'remarks': f'In-service incentive {inc}%' if inc not in ('', '0') else ''})
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
if len(set(x['rank'] for x in rows)) != len(rows):
    raise SystemExit('a CML rank appears twice')

C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'lines': len(lines), 'serial_1_to_n': True, 'allotted': len(rows), 'verification': dict(ver),
          'by_institute': C('institute'), 'by_quota': C('quota'), 'by_section': C('section'),
          'by_allotted_category': C('allotted_category'), 'by_course': C('course'),
          'state_rank': [min(x['rank'] for x in rows), max(x['rank'] for x in rows)],
          'ai_rank': [min(x['rank_ai'] for x in rows if x['rank_ai']), max(x['rank_ai'] for x in rows if x['rank_ai'])]
          if any(x['rank_ai'] for x in rows) else None}
out = {'authority_code': 'jceceb', 'round': opt['--round'], 'round_order': int(opt['--round-order']),
       'status': opt['--status'],
       'title': f'Provisional Seat Allotment List — {opt["--round"]}, State Quota PG Medical (JCECEB)',
       'published_on': published, 'source_file_name': os.path.basename(PDF),
       'notes': ('JCECEB Jharkhand, state quota. rank = CML Rank (state merit), rank_ai = NEET PG AIR from NBEMS 2026 by '
                 'roll. Quota not printed: in-service where the 2026 seat matrix has only in-service seats for that '
                 'institute + course. allotted_category = Seat Opted Category. Names, app numbers, DOB never kept.'),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['status'], out['published_on'])
for k, v in checks.items():
    if k not in ('by_course',):
        print(k, v)
