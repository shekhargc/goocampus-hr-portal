"""West Bengal (WBMCC) "Seat Allotment Result" of the State Quota PG Medical counselling (Round 1: 04.11.2026)
→ rows for POST /api/pg/results/ingest. One table on every page, 9 columns:
  ROUND, ALL INDIA RANK, CHOICE NO., INSTITUTE, COURSE, ALLOTTED QUOTA, ALLOTTED CATEGORY, CANDIDATE CATEGORY, STATUS
No name, roll or application number is printed — nothing personal to drop.

Ranks: `rank` = `rank_ai` = the printed All India Rank (WBMCC ranks by AIR; 2025 WB cut-offs are AIR).
Quota (2025 WB cut-off spellings): Open Quota → State Quota, In-service Quota → State Quota-Inservice, Private
Management Quota → Management Quota, In-service DNB Quota → DNB Quota-Inservice (section dnb, hidden from doctors).
Category: 'OBC (Non-Creamy Layer)' → OBC, 'UR PwD' → UR-PwD (the 2026 seat-matrix spelling), else as printed.
Courses → the WB 2026 seat-matrix names; (NBEMS) / (NBEMS-DIPLOMA) courses → section dnb.
Checks: ROUND = 1 on every line, AIR strictly ascending (no rank twice), every AIR in the NBEMS 2026 result
(--nbems), and allotted ≤ seat-matrix seats per college × course (--seat-matrix, all quotas together — the matrix
files college diplomas and NBEMS diplomas under different quota labels than the result).
Run with /usr/bin/python3 (PyMuPDF):
    west_bengal.py <result.pdf> <out.json> [--seat-matrix <WB seat-matrix dump.json>] [--nbems <neet2026.json>]
                   [--round "Round 1"] [--round-order 1] [--status provisional]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {'--round': 'Round 1', '--round-order': '1', '--status': 'provisional'}
for f in ('--seat-matrix', '--nbems', '--round', '--round-order', '--status'):
    if f in args:
        i = args.index(f); opt[f] = args[i + 1]; del args[i:i + 2]
if len(args) != 2:
    raise SystemExit(__doc__)
PDF, OUT = args

HEAD = ['ROUND', 'ALL INDIA RANK', 'CHOICE NO.', 'INSTITUTE', 'COURSE', 'ALLOTTED QUOTA', 'ALLOTTED CATEGORY',
        'CANDIDATE CATEGORY', 'STATUS']
COLLEGES = {  # printed → the 2026 WB seat-matrix / 2025 cut-off name
    'ALL INDIA INSTITUTE OF HYGIENE AND PUBLIC HEALTH': 'All India Institute of Hygiene and Public Health, Kolkata',
    'ASANSOL DISTRICT HOSPITAL': 'Asansol District Hospital, Asansol',
    'BANKURA SAMMILANI MEDICAL COLLEGE': 'Bankura Sammilani Medical College, Bankura',
    'BARASAT GOVERNMENT MEDICAL COLLEGE AND HOSPITAL': 'Barasat Government Medical College and Hospital, Barasat',
    'BURDWAN MEDICAL COLLEGE': 'Burdwan Medical College, Burdwan',
    'CALCUTTA NATIONAL MEDICAL COLLEGE KOLKATA': 'Calcutta National Medical College, Kolkata',
    'CHITTARANJAN SEVA SADAN COLLEGE OF OBS. GYNAE AND CHILD HEALTH,KOLKATA': 'Chittaranjan Seva Sadan Hospital, Kolkata',
    'COLLEGE OF MEDICINE AND JNM HOSPITAL KALYANI': 'College of Medicine and JNM Hospital, Kalyani, Nadia, West Bengal',
    'COLLEGE OF MEDICINE AND SAGORE DUTTA HOSPITAL': 'College of Medicine and Sagore Dutta Hospital, Kolkata',
    'COMMAND HOSPITAL EC, ALIPORE, KOLKATA': 'Command Hospital (Eastern Command), Kolkata',
    'DEBEN MAHATO SADAR HOSPITAL, PURULIA': 'Deben Mahato Sadar Hospital, Purulia',
    'DIAMOND HARBOUR GOVERNMENT MEDICAL COLLEGE AND HOSPITAL':
        'Diamond Harbour Government Medical College and Hospital, South 24 Parganas, West Bengal',
    'DISTRICT HOSPITAL HOWRAH': 'District Hospital, Howrah',
    'DISTRICT HOSPITAL NADIA': 'District Hospital, Krishnagar, Nadia',
    'DR. B C ROY POST GRADUATE INSTITUTE OF PAEDIATRIC SCIENCES': 'Dr. B C Roy Post Graduate Institute of Paediatric Sciences, Kolkata',
    'ESI PGIMSR AND ESIC MEDICAL COLLEGE JOKA KOLKATA': 'Employees State Insurance Corporation Medical College, Joka, Kolkata',
    'GOURI DEVI INSTITUTE OF MEDICAL SCIENCES AND HOSPITAL': 'Gouri Devi Institute of Medical Sciences and Hospital, Durgapur',
    'ICARE INSTITUTE OF MEDICAL SCIENCES AND RESEARCH HALDIA': 'ICARE Institute of Medical Sciences & Research, Haldia, Purba Midanpore',
    'IMAMBARA DISTRICT HOSPITAL': 'Imambara District Hospital, Hooghly',
    'INFECTIOUS DISEASES AND BELIAGHATA GENERAL HOSPITAL': 'Infectious Diseases and Beliaghata General Hospital, Kolkata',
    'INSTITUTE OF CHILD HEALTH': 'Institute of Child Health, Ballygunge, Kolkata, West Bengal',
    'INSTITUTE OF POST GRADUATE MEDICAL EDUCATION AND RESEARCH KOLKATA': 'Institute of Postgraduate Medical Education & Research, Kolkata',
    'IQ CITY MEDICAL COLLEGE, DURGAPUR': 'IQ-City Medical College, Burdwan',
    'JAGANNATH GUPTA INSTITUTE OF MEDICAL SCIENCES AND HOSPITAL':
        'Jagannath Gupta Institute of Medical Sciences and Hospital, Buita, Kolkata, West Bengal',
    'JIS SCHOOL OF MEDICAL SCIENCE & RESEARCH': 'JIS School of Medical Science & Research, Howrah',
    'Jalpaiguri Government Medical College and Hospital (Formerly DISTRICT HOSPITAL) JALPAIGURI':
        'Jalpaiguri Government Medical College and Hospital, Jalpaiguri',
    'KPC MEDICAL COLLEGE': 'KPC Medical College, Jadavpur, Kolkata',
    'M R BANGUR HOSPITAL': 'M R Bangur Hospital, Kolkata',
    'MAHARAJA JITENDRA NARAYAN MEDICAL COLLEGE AND HOSPITAL': 'Maharaja Jitendra Narayan Medical College and Hospital, Cooch Behar',
    'MALDA MEDICAL COLLEGE AND HOSPITAL': 'Malda Medical College & Hospital, Malda',
    'MEDICAL COLLEGE KOLKATA': 'Government Medical College, Kolkata',
    'MIDNAPORE MEDICAL COLLEGE': 'Midnapore Medical College, Midnapore',
    'MURSHIDABAD MEDICAL COLLEGE AND HOSPITAL': 'Murshidabad Medical College & Hospitals, Murshidabad',
    'NIL RATAN SIRCAR MEDICAL COLLEGE': 'Nil Ratan Sircar Medical College, Kolkata',
    'NORTH BENGAL MEDICAL COLLEGE AND HOSPITAL': 'North Bengal Medical College, Darjeeling',
    'R G KAR MEDICAL COLLEGE': 'RG Kar Medical College, Kolkata',
    'RAIGANJ GOVERNMENT MEDICAL COLLEGE AND HOSPITAL': 'Raiganj Government Medical College and Hospital, Raiganj',
    'RAMAKRISHNA MISSION SEVA PRATISHTHAN VIVEKANANDA INSTITUTE OF MEDICAL SCIENCES, KOLKATA':
        'Ramakrishna Mission Seva Pratishthan, Vivekananda Institute of Medical Sciences, Kolkata',
    'RAMPURHAT GOVT. MEDICAL COLLEGE AND HOSPITAL': 'Rampurhat Government Medical College and Hospital, Rampurhat',
    'SCHOOL OF TROPICAL MEDICINE, KOLKATA': 'Calcutta School of Tropical Medicine, West Bengal',
    'SHRI RAMKRISHNA INSTITUTE OF MEDICAL SCIENCES & SANAKA HOSPITALS': 'Shri Ramkrishna Institute of Medical Sciences & Sanaka Hospitals, Durgapur',
    'SURI SADAR HOSPITAL': 'Suri Sadar Hospital, Birbhum',
    'TAMRALIPTO GOVERNMENT MEDICAL COLLEGE': 'Tamralipto Government Medical College, Tamluk'}
COURSES = {  # printed → (seat-matrix course name, section)
    'M.D. (OBST. AND GYNAE)/MS (OBSTETRICS AND GYNAECOLOGY)': ('MS - Obstetrics and Gynaecology', 'mdms'),
    'M.D. (GENERAL MEDICINE)': ('MD - General Medicine', 'mdms'),
    'M.S. (GENERAL SURGERY)': ('MS - General Surgery', 'mdms'),
    'M.D. (PAEDIATRICS)': ('MD - Paediatrics', 'mdms'),
    'M.D. (ANAESTHESIOLOGY)': ('MD - Anaesthesiology', 'mdms'),
    'M.S. (ORTHOPAEDICS)': ('MS - Orthopaedics', 'mdms'),
    'M.S. (OPHTHALMOLOGY)': ('MS - Ophthalmology', 'mdms'),
    'M.D. (RADIO- DIAGNOSIS)': ('MD - Radio-Diagnosis', 'mdms'),
    'M.D. (DERM.,VENE. AND LEPROSY)/ (DERMATOLOGY)/ (SKIN AND VENEREAL DISEASES)/ (VENEREOLOGY)': ('MD - Dermatology', 'mdms'),
    'M.D. (PATHOLOGY)': ('MD - Pathology', 'mdms'),
    'M.S. (E.N.T.)': ('MS - ENT (Otorhinolaryngology)', 'mdms'),
    'M.D. (PSYCHIATRY)': ('MD - Psychiatry', 'mdms'),
    'M.D. (TUBERCULOSIS AND RESPIRATORY DISEASES)/PULMONA RY MEDICINE /M.D. (RESPIRATORY MEDICINE)':
        ('MD - Respiratory Medicine', 'mdms'),
    'M.D. (PREVENTIVE AND SOCIAL MEDICINE)/ COMMUNITY MEDICINE': ('MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    'M.D. (RADIOTHERAPY/ RADIATION ONCOLOGY)': ('MD - Radiotherapy / Radiation Oncology', 'mdms'),
    'M.D. (MICROBIOLOGY)': ('MD - Microbiology', 'mdms'),
    'M.D. (PHARMACOLOGY)': ('MD - Pharmacology', 'mdms'),
    'M.D. (BIOCHEMISTRY)': ('MD - Biochemistry', 'mdms'),
    'M.D. (PHYSIOLOGY)': ('MD - Physiology', 'mdms'),
    'MD/MS (ANATOMY)': ('MD/MS - Anatomy', 'mdms'),
    'M.D. (PHYSICAL MED. AND REHABILITATION)': ('MD - Physical Medicine and Rehabilitation', 'mdms'),
    'M.D. (TROPICAL MEDICINE)': ('MD - Tropical Medicine', 'mdms'),
    'M.D. (FORENSIC MEDICINE)': ('MD - Forensic Medicine', 'mdms'),
    'M.D. (EMERGENCY AND CRITICAL CARE)/M.D. (EMERGENCY MEDICINE)': ('MD - Emergency Medicine', 'mdms'),
    'M.P.H. (EPIDEMIOLOGY)': ('MPH - Epidemiology', 'mdms'),
    'M.D. IN TRANSFUSION MEDICINE/ IMMUNO- HAEMATOLOGY AND BLOOD TRANSFUSION':
        ('MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'mdms'),
    'M.D. GERIATRICS': ('MD - Geriatrics', 'mdms'),
    'DIP.IN GYNAE. AND OBST.': ('Diploma in Obstetrics and Gynaecology', 'diploma'),
    'DIPLOMA IN OPHTHALMOLOGY/DO MS': ('Diploma in Ophthalmology', 'diploma'),
    'DIPLOMA IN ANAESTHESIOLOGY': ('Diploma in Anaesthesiology', 'diploma'),
    'DIPLOMA IN ORTHOPAEDICS': ('Diploma in Orthopaedics', 'diploma'),
    'DIPLOMA IN CHILD HEALTH/ PAEDIATRICS': ('Diploma in Child Health / Paediatrics', 'diploma'),
    'DIPLOMA IN CLINICAL PATHOLOGY': ('Diploma in Pathology', 'diploma'),
    'DIPLOMA IN OTO- RHINO- LARYNGOLOGY': ('Diploma in ENT', 'diploma'),
    '(NBEMS) GENERAL MEDICINE': ('DNB - General Medicine (Post-MBBS)', 'dnb'),
    '(NBEMS) PAEDIATRICS': ('DNB - Paediatrics (Post-MBBS)', 'dnb'),
    '(NBEMS) OBSTETRICS AND GYNAECOLOGY': ('DNB - Obstetrics and Gynaecology (Post-MBBS)', 'dnb'),
    '(NBEMS) ORTHOPAEDICS': ('DNB - Orthopaedics (Post-MBBS)', 'dnb'),
    '(NBEMS) GENERAL SURGERY': ('DNB - General Surgery (Post-MBBS)', 'dnb'),
    '(NBEMS) OPHTHALMOLOGY': ('DNB - Ophthalmology (Post-MBBS)', 'dnb'),
    '(NBEMS) CARDIO VASCULAR AND THORACIC SURGERY (DIRECT 6 YEARS COURSE)':
        ('DNB - Cardio Vascular And Thoracic Surgery (Direct 6 Years Course)', 'dnb'),
    '(NBEMS-DIPLOMA) RADIO-DIAGNOSIS': ('Diploma in Radio Diagnosis', 'dnb'),
    '(NBEMS-DIPLOMA) PAEDIATRICS': ('Diploma in Child Health / Paediatrics', 'dnb')}
QUOTAS = {'Open Quota': 'State Quota', 'In-service Quota': 'State Quota-Inservice',
          'Private Management Quota': 'Management Quota', 'In-service DNB Quota': 'DNB Quota-Inservice'}
CATS = {'UR': 'UR', 'SC': 'SC', 'ST': 'ST', 'EWS': 'EWS', 'OBC (Non-Creamy Layer)': 'OBC', 'UR PwD': 'UR-PwD'}
CAND_CATS = {'General', 'SC', 'ST', 'EWS', 'OBC (Non-Creamy Layer)', 'General PwD', 'OBC (Non-Creamy Layer) PwD',
             'SC PwD', 'ST PwD', 'EWS PwD'}

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()

doc = fitz.open(PDF)
cd = re.match(r'D:(\d{4})(\d{2})(\d{2})', doc.metadata.get('creationDate') or '')
published = f'{cd.group(1)}-{cd.group(2)}-{cd.group(3)}' if cd else ''
lines = []
for pg in doc:
    for tb in pg.find_tables().tables:
        for r in tb.extract():
            c = [clean(x) for x in r]
            if c[0] == 'ROUND':
                if c != HEAD:
                    raise SystemExit(f'p{pg.number + 1}: column headings changed')
                continue
            if len(c) != len(HEAD) or not c[1].isdigit():
                raise SystemExit(f'p{pg.number + 1}: unexpected line')
            lines.append(c)

round_no = re.search(r'\d+', opt['--round']).group(0)
rows = []
for n, c in enumerate(lines, 1):
    rnd, air, choice, inst_raw, course_raw, quota_raw, cat_raw, cand, status = c
    if rnd != round_no or status != 'Fresh Allotment':
        raise SystemExit(f'line {n}: round {rnd!r} / status {status!r}')
    if inst_raw not in COLLEGES:
        raise SystemExit(f'unknown institute {inst_raw!r}')
    if course_raw not in COURSES:
        raise SystemExit(f'unknown course {course_raw!r}')
    if quota_raw not in QUOTAS or cat_raw not in CATS or cand not in CAND_CATS:
        raise SystemExit(f'line {n}: quota / category {quota_raw!r} {cat_raw!r} {cand!r}')
    course, section = COURSES[course_raw]
    if (section == 'dnb') != (quota_raw == 'In-service DNB Quota'):
        raise SystemExit(f'line {n}: NBEMS course outside the DNB quota (or the reverse)')
    rows.append({'sno': n, 'rank': int(air), 'rank_ai': int(air), 'quota_raw': quota_raw, 'quota': QUOTAS[quota_raw],
                 'institute_raw': inst_raw, 'institute': COLLEGES[inst_raw], 'course_raw': course_raw, 'course': course,
                 'section': section, 'allotted_category': CATS[cat_raw], 'allotted_category_raw': cat_raw,
                 'candidate_category': cand, 'remarks': f'Choice no. {choice}'})

a = [x['rank'] for x in rows]
if any(y <= x for x, y in zip(a, a[1:])):
    raise SystemExit('All India Rank not strictly ascending (a rank repeats or the order breaks)')
checks = {'allotted': len(rows), 'air_ascending_unique': True}
if '--nbems' in opt:
    airs = {x['air'] for x in json.load(open(opt['--nbems'])) if x.get('air')}
    miss = [x['rank'] for x in rows if x['rank'] not in airs]
    if miss:
        raise SystemExit(f'AIR not in the NBEMS 2026 result: {miss[:10]}')
    checks['air_in_nbems'] = len(rows)
if '--seat-matrix' in opt:
    sm = collections.Counter()
    for x in json.load(open(opt['--seat-matrix']))['rows']:
        sm[(x['college_name'], x['course_name'])] += x['seats']
    got = collections.Counter((x['institute'], x['course']) for x in rows)
    bad = {f'{k[0]} · {k[1]}': f'{v} allotted / {sm.get(k, 0)} seats' for k, v in got.items() if v > sm.get(k, 0)}
    if bad:
        raise SystemExit(f'more allotted than seat-matrix seats: {bad}')
    checks['seat_matrix'] = f'{len(got)} college × course groups within the matrix ({sum(sm.values())} seats)'

C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks.update({'by_quota': C('quota'), 'by_section': C('section'), 'by_allotted_category': C('allotted_category'),
               'by_institute': C('institute')})
out = {'authority_code': 'wbmcc', 'round': opt['--round'], 'round_order': int(opt['--round-order']),
       'status': opt['--status'],
       'title': f'Seat Allotment Result — {opt["--round"]}, State Quota PG Medical (MD/MS/Diploma/DNB), West Bengal',
       'published_on': published, 'source_file_name': os.path.basename(PDF),
       'notes': ('WBMCC state quota. rank = rank_ai = the printed All India Rank. Open → State Quota, In-service → '
                 'State Quota-Inservice, Private Management → Management Quota, In-service DNB → DNB Quota-Inservice '
                 '(NBEMS courses, hidden). The list prints no names or roll numbers.'),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['status'], out['published_on'])
for k, v in checks.items():
    if k != 'by_institute':
        print(k, v)
