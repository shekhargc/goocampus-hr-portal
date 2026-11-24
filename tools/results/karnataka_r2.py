"""Karnataka (KEA) Round 2+ seat allotment ("PG NEET -2026 MEDICAL (MD/MS) 2st ROUND PROVISIONAL SEAT ALLOTMENT",
published 23-11-2026 — KEA prints "2st") → rows for POST /api/pg/results/ingest. Same 8-column table as Round 1
(karnataka.py: colleges, courses, seat types and category rules are identical and kept in step by copy), plus:
  * Status column: 'Allotted' (seat given in this round) or 'Reported' (the candidate reported to a Round 1 seat and
    keeps it). Stored as round_status_raw.
  * round_status by comparing with the Round 1 list (--prev <Round 1 rows.json from karnataka.py>), matched by AIR:
      no Round 1 line → fresh; same college + course + quota as Round 1 → retained; otherwise → upgraded, with the
      Round 1 seat in prev_institute_raw / prev_course_raw / prev_quota_raw.
  * The title accepts "<n>(st|nd|rd|th) ROUND PROVISIONAL" and "<n>.. ROUND FINAL"; --round must agree with <n>.
No name, roll or application number is printed.
    karnataka_r2.py <allotment.pdf> <out.json> --prev <round1_rows.json> [--seat-matrix <dump.json>]
                    [--round "Round 2"] [--round-order 2] [--status provisional|final]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {'--round': 'Round 2', '--round-order': '2'}
for f in ('--seat-matrix', '--round', '--round-order', '--status', '--prev'):
    if f in args:
        i = args.index(f); opt[f] = args[i + 1]; del args[i:i + 2]
if len(args) != 2:
    raise SystemExit(__doc__)
PDF, OUT = args
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

HEAD = ['SL.NO', 'All India Rank', 'Course Code', 'Name of the College Allotted.', 'Course Name', 'Allotted Category',
        'Course fees', 'Status']
TITLE = re.compile(r'PG NEET -2026 MEDICAL \(MD/MS\) (\d+)(?:st|nd|rd|th) ROUND (PROVISIONAL|FINAL) SEAT ALLOTMENT')
COLLEGES = {  # KEA college code → (name exactly as printed, standard name = 2025 KEA cut-off / 2026 seat-matrix name)
    'M01': ('Bangalore Medical College and Research Institute, Bangalore', 'Bangalore Medical College and Research Institute, Bangalore'),
    'M02': ('Mysore Medical College and Research Instt. (Prev.name Government Medical College), Mysore', 'Mysore Medical College and Research Institute, Mysore'),
    'M03': ('Karnataka Medical College and Research Institute, Hubballi, Karnataka', 'Karnataka Institute of Medical Sciences, Hubballi'),
    'M04': ('Vijaynagar Institute of Medical Sciences, Bellary', 'Vijayanagar Institute of Medical Sciences, Ballari'),
    'M05': ('Mandya Institute of Medical Sciences, Mandya', 'Mandya Institute of Medical Sciences, Mandya'),
    'M06': ('Belagavi Institute of Medical Sciences, Belagavi', 'Belagavi Institute of Medical Sciences, Belagavi'),
    'M07': ('Hassan Institute of Medical Sciences, Hassan', 'Hassan Institute of Medical Sciences, Hassan'),
    'M08': ('Shimoga Institute of Medical Sciences, Shimoga', 'Shimoga Institute of Medical Sciences, Shimoga'),
    'M09': ('Raichur Institute of Medical Sciences, Raichur', 'Raichur Institute of Medical Sciences, Raichur'),
    'M10': ('Bidar Institute of Medical Sciences, Bidar', 'Bidar Institute of Medical Sciences, Bidar'),
    'M11': ('Kidwai Memorial Institute of Oncology, Bangalore', 'Kidwai Memorial Institute of Oncology, Bangalore'),
    'M12': ('Indira Gandhi Institute of Child Health, Bangalore', 'Indira Gandhi Institute of Child Health, Bangalore'),
    'M13': ('Employees State Insurance Corporation Medical College, Gulbarga', 'Employees State Insurance Corporation Medical College, Gulbarga'),
    'M14': ('JJM Medical College, Davangere', 'JJM Medical College, Davangere'),
    'M15': ('M S Ramaiah Medical College, Bangalore', 'M.S. Ramaiah Medical College, Bangalore'),
    'M16': ('Kempegowda Institute of Medical Sciences, Bangalore', 'Kempegowda Institute of Medical Sciences, Bangalore'),
    'M17': ('Mahadevappa Rampure Medical College, Kalaburagi, Gulbarga', 'Mahadevappa Rampure Medical College, Gulbarga'),
    'M18': ('Adichunchanagiri Institute of Medical Sciences, Bellur', 'Adichunchanagiri Institute of Medical Sciences, Bellur, Mandya'),
    'M19': ('K V G Medical College, Sullia', 'KVG Medical College and Hospital, Sullia'),
    'M20': ('Dr BR Ambedkar Medical College, Bangalore', 'Dr. BR Ambedkar Medical College, Bangalore'),
    'M21': ('S S Institute of Medical Sciences& Research Centre, Davangere', 'S S Institute of Medical Sciences & Research Centre, Davangere'),
    'M22': ('S. Nijalingappa Medical College & HSK Hospital & Research Centre, Bagalkot', 'S. Nijalingappa Medical College & HSK Hospital & Research Centre, Bagalkot'),
    'M23': ('Basaveswara Medical College and Hospital, Chitradurga', 'Basaveswara Medical College and Hospital, Chitradurga'),
    'M24': ('Al-Ameen Medical College, Bijapur', 'Al-Ameen Medical College, Bijapur'),
    'M25': ('Father Mullers Medical College, Mangalore', 'Father Mullers Institue of Medical Education and Research, Mangalore'),
    'M26': ('Vydehi Institute Of Medical Sciences & Research Centre, Bangalore', 'Vydehi Institute of Medical Sciences & Research Centre, Bangalore'),
    'M27': ('SDM College of Medical Sciences & Hospital, Sattur, Dharwad', 'SDM College of Medical Sciences and Hospital, Dharwad'),
    'M28': ('MVJ Medical College and Research Hospital, Bangalore', 'MVJ Medical College and Research Hospital, Bangalore'),
    'M30': ('Navodaya Medical College, Raichur', 'Navodaya Medical College, Raichur'),
    'M31': ('A J Institute of Medical Sciences & Research Centre, Mangalore', 'A.J. Institute of Medical Sciences and Research Centre, Mangalore'),
    'M32': ('Kasturba Medical College, Mangalore', 'Kasturba Medical College, Mangalore'),
    'M33': ('Kasturba Medical College, Manipal', 'Kasturba Medical College, Manipal'),
    'M34': ('Sanjay Gandhi Institute of Trauma and Orthopaedics, Bangalore', 'Sanjay Gandhi Institute of Trauma and Orthopaedics, Bangalore'),
    'M35': ('JSS Medical College, Mysore', 'JSS Medical College, Mysore'),
    'M36': ('K S Hegde Medical Academy, Mangalore', 'K S Hegde Medical Academy, Mangalore'),
    'M37': ('Yenepoya Medical College, Mangalore', 'Yenepoya Medical College, Mangalore'),
    'M38': ('Employees State Insurance Corporation Medical College, Bangalore', 'Employees State Insurance Corporation Medical College, Bangalore'),
    'M39': ('Khaja Bandanawaz University - Faculty of Medical Sciences, Gulbarga', 'Khaja Bandanawaz University Faculty of Medical Sciences, Gulbarga'),
    'M40': ('Shri B M Patil Medical College, Hospital & Research Centre, Vijayapura (Bijapur', 'Shri B M Patil Medical College, Hospital & Research Centre, Vijayapura (Bijapur)'),
    'M43': ('Sapthagiri Institute of Medical Sciences & Research Centre, Bangalore', 'Sapthagiri Institute of Medical Sciences & Research Centre, Bangalore'),
    'M46': ('BGS Global Institute of Medical Sciences, Bangalore', 'BGS Global Institute of Medical Sciences, Bangalore'),
    'M47': ('Srinivas Institute of Medical Research Centre, Srinivasnagar, Mangalore', 'Srinivas Institute of Medical Sciences and Research Centre, Mangalore'),
    'M48': ('St. Johns Medical College, Bangalore', 'St. Johns Medical College, Bangalore'),
    'M49': ('Dharwad Institute of Mental Health and Neuro Sciences, Dharwad', 'Dharwad Institute of Mental Health and Neurosciences (DIMHANS), Dharwad'),
    'M50': ('K.H. Patil Institute of Medical Sciences (previously Gadag Institute of Medical Sciences, Mallasamudra, Mulgund Road, Gadag)', 'Gadag Institute of Medical Sciences, Gadag'),
    'M51': ('SDS Tuberculosis Research Centre and Rajiv Gandhi Institute of Chest Diseases, Bangalore', 'SDS Tuberculosis Research Centre and Rajiv Gandhi Institute of Chest Diseases, Bangalore'),
    'M52': ('Akash Institute of Medical Sciences & Research Centre, Devanhalli, Bangalore, Karnataka', 'Akash Institute of Medical Sciences and Research Centre, Bangalore'),
    'M53': ('The Oxford Medical College, Hospital & Research Centre, Bangalore', 'The Oxford Medical College, Hospital & Research Centre, Bangalore'),
    'M54': ('Shridevi Institute of Medical Sciences & Research Hospital, Tumkur', 'Shridevi Institute of Medical Sciences & Research Hospital, Tumkur'),
    'M55': ('Gulbarga Institute of Medical Sciences, Gulbarga', 'Gulbarga Institute of Medical Sciences, Gulbarga'),
    'M57': ('Koppal Institute of Medical Sciences, Koppal', 'Koppal Institute of Medical Sciences, Koppal'),
    'M58': ('Kanachur Institute of Medical Sciences, Mangalore', 'Kanachur Institute of Medical Sciences, Mangalore'),
    'M59': ('Subbaiah Institute of Medical Sciences, Shimoga, Karnataka', 'Subbaiah Institute of Medical Sciences, Shimoga'),
    'M60': ('Karwar Institute of Medical Sciences, Karwar', 'Karwar Institute of Medical Sciences, Karwar'),
    'M61': ('Kodagu Institute of Medical Sciences, Kodagu', 'Kodagu Institute of Medical Sciences, Kodagu'),
    'M62': ('Chamrajanagar Institute of Medical Sciences, Karnataka', 'Chamarajanagar Institute of Medical Sciences, Chamarajanagar'),
    'M63': ('East Point College of Medical Sciences & Research Centre, Bangalore', 'East Point College of Medical Sciences & Research Centre, Bangalore'),
    'M64': ('Shri Atal Bihari Vajpayee Medical College & Research Institute', 'Shri Atal Bihari Vajpayee Medical College and Research Institute, Bangalore'),
    'M65': ('Dr. Chandramma Dayananda Sagar Instt. of Medical Education & Research, Harohalli, Hubli', 'Dr. Chandramma Dayananda Sagar Institute of Medical Education & Research, Harohalli'),
    'M66': ('Chikkamagaluru Institute of Medical Sciences, Chikkamagaluru', 'Chikkamagaluru Institute of Medical Sciences, Chikkamagaluru'),
    'M67': ('Nandi Medical College and Research Institute Chikkaballapura (Chikkaballapura Institute of Medical Sciences Chikkaballapura )', 'Chikkaballapura Institute of Medical Sciences, Chikkaballapura'),
    'M68': ('Haveri Institute of Medical Sciences, Haveri', 'Haveri Institute of Medical Sciences, Haveri'),
    'M69': ('Siddaganga Medical College and Research Institute, Tumakuru', 'Siddaganga Medical College and Research Institute, Tumakuru'),
    'M70': ('Sri Chamundeshwari Medical College Hospital & Research Institute', 'Sri Chamundeshwari Medical College Hospital & Research Institute, Channapatna'),
    'M71': ('Sri Madhusudan Sai Institute of Medical Sciences & Research, Chikballapur', 'Sri Madhusudan Sai Institute of Medical Sciences and Research, Chikkaballapura'),
    # new in Round 2 (KEA additional college list, 20-11-2026) — names as in the Round 2 seat matrix
    'M76': ('BGS Medical College and Hospital, Nagaruru, Bangalore', 'BGS Medical College & Hospital, Nagaruru'),
    'M77': ('PES University Institute Of Medical Sciences and Research, Bangalore', 'PES University Institute of Medical Sciences and Research, Bangalore'),
    'M79': ('S R Patil Medical College and Hospital District Bagalkot', 'S R Patil Medical College, Bagalkot'),
}
COURSES = {  # KEA course code → (name exactly as printed, approved course name, section)
    'A1': ('M.D. Anatomy', 'MD/MS - Anatomy', 'mdms'), 'A2': ('M.D. Physiology', 'MD - Physiology', 'mdms'),
    'A3': ('M.D. Biochemistry', 'MD - Biochemistry', 'mdms'), 'B1': ('M.D. Pharmacology', 'MD - Pharmacology', 'mdms'),
    'B2': ('M.D. Pathology', 'MD - Pathology', 'mdms'), 'B3': ('M.D. Microbiology', 'MD - Microbiology', 'mdms'),
    'B4': ('M.D. Community Medicine', 'MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    'B5': ('M.D. Forensic Medicine', 'MD - Forensic Medicine', 'mdms'), 'C1': ('M.D. Dermatology', 'MD - Dermatology', 'mdms'),
    'C2': ('M.D. Radio Therapy', 'MD - Radiotherapy / Radiation Oncology', 'mdms'),
    'C3': ('M.D. Paediatrics', 'MD - Paediatrics', 'mdms'), 'C4': ('M.D. General Medicine', 'MD - General Medicine', 'mdms'),
    'C5': ('M.D. Radio Diagnosis', 'MD - Radio-Diagnosis', 'mdms'), 'C6': ('M.D. Psychiatry', 'MD - Psychiatry', 'mdms'),
    'C7': ('M.D. Respiratory Medicine', 'MD - Respiratory Medicine', 'mdms'),
    'C8': ('M.D Hospital Administration', 'MD - Hospital Administration', 'mdms'),
    'C9': ('M.D Emergency Medicine', 'MD - Emergency Medicine', 'mdms'),
    'D0': ('M.D. Family Medicine', 'MD - Family Medicine', 'mdms'), 'D1': ('M.S. Opthalamology', 'MS - Ophthalmology', 'mdms'),
    'D2': ('M.S. ENT', 'MS - ENT (Otorhinolaryngology)', 'mdms'), 'D3': ('M.S. Orthopedics', 'MS - Orthopaedics', 'mdms'),
    'D4': ('M.D. Anaesthesia', 'MD - Anaesthesiology', 'mdms'), 'D5': ('M.S. General Surgery', 'MS - General Surgery', 'mdms'),
    'D6': ('M.S. Obstetrics and Gynecology', 'MS - Obstetrics and Gynaecology', 'mdms'),
    'D7': ('M.D Immuno Haemotology', 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'mdms'),
    'D8': ('M.D. Physical and Rehablitation', 'MD - Physical Medicine and Rehabilitation', 'mdms'),
    'DA': ('M.D. Sports Medicine', 'MD - Sports Medicine', 'mdms'), 'H1': ('M.D Geritrics', 'MD - Geriatrics', 'mdms'),
    'H2': ('Palliative Medicine', 'MD - Palliative Medicine', 'mdms'), 'H3': ('M.D. Laboratory Medicine', 'MD - Laboratory Medicine', 'mdms'),
    'H4': ('M.D. Nuclear Medicine', 'MD - Nuclear Medicine', 'mdms'),
    'E1': ('Diploma in Clinical Pathology', 'Diploma in Pathology', 'diploma'),
    'E4': ('Diploma in Public Health', 'Diploma in Public Health', 'diploma'),
    'F4': ('Diploma in TB and Chest Diseases', 'Diploma in Respiratory Medicine', 'diploma')}
GOV_ROOT = {'GM': ('GM', 'GM'), '1': ('1', 'CAT1'), '2A': ('2A', '2A'), '2B': ('2B', '2B'), '3A': ('3A', '3A'),
            '3B': ('3B', '3B'), 'ST': ('ST', 'ST'),        # KEA root → (2025 cut-off root, seat-matrix category)
            'S1': ('SC-A', 'SC-A'), 'S2': ('SC-B', 'SC-B'), 'S3': ('SC-C', 'SC-C'), 'S4': ('SC-C (20%)', 'SC-C (20%)')}
PRIVATE = {'GMP': 'Private Quota - GMP', 'GMPH': 'Private Quota - GMP', 'OPN': 'Private Quota - Open',
           **{c: 'Private Quota - Minority' for c in ('ME', 'MEH', 'MM', 'MMH', 'MU', 'MC', 'MA', 'MK', 'RC1', 'RC2', 'RC3')}}
SEAT_TYPE = {'G': 'Government seat', 'P': 'Private seat', 'Q': 'Management seat', 'N': 'NRI seat'}

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()


def seat(stype, cat):
    """→ (quota, allotted_category in 2025 spelling, seat-matrix quota, seat-matrix category, region)."""
    if stype == 'G':
        m = re.fullmatch(r'(P?)(GM|1|2A|2B|3A|3B|ST|S1|S2|S3|S4)([GH]?)', cat)
        if not m or m.group(3) not in (('', 'H') if m.group(2) == 'GM' else ('G', 'H')):
            raise SystemExit(f'unknown government-seat category {cat!r}')
        pwd, (root25, rootsm), kk = m.group(1), GOV_ROOT[m.group(2)], m.group(3) == 'H'
        code = pwd + (('GMH' if kk else 'GM') if root25 == 'GM' else root25 + ('H' if kk else 'G'))
        return ('Government Quota', code, 'Government Quota',
                rootsm + ('-PwD' if pwd else '') + (' (KK)' if kk else ''), 'KK' if kk else 'RK')
    if stype == 'P' and cat in PRIVATE:
        return PRIVATE[cat], cat, PRIVATE[cat], cat, ''
    if stype == 'Q' and cat == 'MNG':
        return 'Management Quota', 'MNG', 'Management Quota', 'OTH(Q)', ''
    if stype == 'N' and cat == 'NRI':
        return 'NRI Quota', 'NRI', 'NRI Quota', 'NRI', ''
    raise SystemExit(f'category {cat!r} does not belong to seat type {stype!r}')


approved = {c['course'] for c in json.load(open(SHEET))['courses']}
bad = [v[1] for v in COURSES.values() if v[1] not in approved]
if bad:
    raise SystemExit(f'not in specialty_sheet.json: {bad}')

doc = fitz.open(PDF)
lines, dates, titles = [], set(), set()
for pg in doc:
    text = clean(pg.get_text())
    d = re.findall(r'PUBLISHED ON \[ (\d\d)-(\d\d)-(\d{4}) \]', text)
    t = TITLE.findall(text)
    if 'Karnataka Examinations Authority' not in text or len(t) != 1 or len(d) != 1:
        raise SystemExit(f'p{pg.number + 1}: page header changed')
    dates.add(d[0]); titles.add(t[0])
    for tb in pg.find_tables().tables:
        for r in tb.extract():
            c = [clean(x) for x in r]
            if c[0] == 'SL.NO':
                if c != HEAD:
                    raise SystemExit(f'p{pg.number + 1}: column headings changed')
                continue
            if len(c) != len(HEAD) or not c[0].isdigit() or not c[1].isdigit():
                raise SystemExit(f'p{pg.number + 1}: unexpected line')
            lines.append(c)
if len(dates) != 1:
    raise SystemExit(f'more than one PUBLISHED ON date: {dates}')
if len(titles) != 1:
    raise SystemExit(f'more than one page title: {titles}')
round_no, kind = titles.pop()
list_status = 'final' if kind == 'FINAL' else 'provisional'   # (not `status`: the row loop reads a Status column)
if opt.get('--status', list_status) != list_status:
    raise SystemExit(f'--status {opt["--status"]} but the list says {list_status}')
if round_no and opt['--round'] != f'Round {round_no}':
    raise SystemExit(f'--round {opt["--round"]!r} but the list says round {round_no}')
dd, mm, yyyy = dates.pop()
published = f'{yyyy}-{mm}-{dd}'

rows, fees = [], []
for n, c in enumerate(lines, 1):
    sl, air, code, inst_raw, course_raw, cat_raw, fee, status = c
    if int(sl) != n:
        raise SystemExit(f'SL.NO {sl} where {n} was expected')
    if status not in ('Allotted', 'Reported'):
        raise SystemExit(f'SL.NO {sl}: status {status!r}')
    if not re.fullmatch(r'\d+', fee.replace(' ', '')):    # a long fee wraps ('1004075 0'); never stored
        raise SystemExit(f'SL.NO {sl}: fee {fee!r}')
    fees.append(int(fee.replace(' ', '')))
    m = re.fullmatch(r'(M\d\d)([GPQN])([A-H][0-9A])', code)
    if not m:
        raise SystemExit(f'SL.NO {sl}: course code {code!r}')
    ccode, stype, crs = m.groups()
    if ccode not in COLLEGES or COLLEGES[ccode][0] != inst_raw:
        raise SystemExit(f'SL.NO {sl}: college {ccode} {inst_raw!r} not known')
    if crs not in COURSES or COURSES[crs][0] != course_raw:
        raise SystemExit(f'SL.NO {sl}: course {crs} {course_raw!r} not known')
    quota, cat, sm_q, sm_c, region = seat(stype, cat_raw)
    _, course, section = COURSES[crs]
    rows.append({'sno': n, 'rank': int(air), 'rank_ai': int(air), 'quota_raw': SEAT_TYPE[stype], 'quota': quota,
                 'institute_raw': inst_raw, 'institute': COLLEGES[ccode][1], 'course_raw': course_raw, 'course': course,
                 'section': section, 'allotted_category': cat, 'allotted_category_raw': cat_raw,
                 'candidate_category': '', 'remarks': f'Course code {code}', 'round_status_raw': status, '_sm': (sm_q, sm_c), '_region': region})

a = [x['rank'] for x in rows]
if any(y <= x for x, y in zip(a, a[1:])):
    raise SystemExit('All India Rank not strictly ascending (a rank repeats or the order breaks)')
checks = {'allotted': len(rows), 'sl_no_1_to_n': True, 'air_ascending_unique': True, 'published_on_pdf': published,
          'pdf_pages': len(doc), 'fee_range_not_stored': [min(fees), max(fees)]}
if '--prev' not in opt:
    raise SystemExit('--prev <Round 1 rows.json> is required')
prev = {x['rank']: x for x in json.load(open(opt['--prev']))['rows']}
requota = 0
for x in rows:
    p = prev.get(x['rank'])
    same_seat = bool(p) and (p['institute'], p['course']) == (x['institute'], x['course'])
    if not p:
        x['round_status'] = 'fresh'
    elif same_seat and (p['quota'] == x['quota'] or x['round_status_raw'] == 'Reported'):
        # 'Reported' = kept the reported Round 1 seat; KEA sometimes reprints its quota (unfilled GMP / minority seat
        # converted to Open) — the candidate did not move, so still retained (Round 1 quota kept in remarks)
        x['round_status'] = 'retained'
        if p['quota'] != x['quota']:
            requota += 1
            x['remarks'] += f" · Round 1 quota {p['quota']} ({p['allotted_category']}), reprinted as {x['quota']}"
    else:
        x['round_status'] = 'upgraded'
    if p and x['round_status'] != 'retained':
        x.update(prev_institute_raw=p['institute_raw'], prev_course_raw=p['course_raw'], prev_course=p['course'],
                 prev_quota_raw=p['quota_raw'], prev_quota=p['quota'])
    if x['round_status_raw'] == 'Reported' and x['round_status'] != 'retained':
        raise SystemExit(f"SL.NO {x['sno']}: 'Reported' but not the Round 1 seat")
checks['reported_quota_reprinted'] = requota
checks['by_round_status'] = dict(collections.Counter(x['round_status'] for x in rows))
checks['by_status_column'] = dict(collections.Counter(x['round_status_raw'] for x in rows))
checks['round1_not_in_round2'] = len(set(prev) - {x['rank'] for x in rows})
if '--seat-matrix' in opt:
    sm, sm_ic = collections.Counter(), collections.Counter()
    for x in json.load(open(opt['--seat-matrix']))['rows']:
        sm[(x['college_name'], x['course_name'], x['quota'], x['category'])] += x['seats']
        sm_ic[(x['college_name'], x['course_name'])] += x['seats']
    got = collections.Counter((x['institute'], x['course']) + x['_sm'] for x in rows if x['round_status'] != 'retained')
    bad = {' · '.join(k): f'{v} allotted / {sm.get(k, 0)} seats' for k, v in got.items() if v > sm.get(k, 0)}
    checks['over_matrix_informational'] = len(bad)   # Round 2 also fills seats vacated during the round
    ic = {k[:2] for k in got}
    checks['seat_matrix'] = (f'{len(got) - len(bad)}/{len(got)} college × course × quota × category groups of fresh + '
                             f'upgraded seats within the Round 2 matrix ({sum(sm.values())} seats); {len(bad)} over')

C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks.update({'by_quota': C('quota'), 'by_section': C('section'), 'by_seat_type': C('quota_raw'),
               'government_seats_by_region': dict(collections.Counter(x['_region'] for x in rows if x['_region'])),
               'by_allotted_category': C('allotted_category'), 'by_institute': C('institute')})
for x in rows:
    del x['_sm'], x['_region']
out = {'authority_code': 'kea', 'round': opt['--round'], 'round_order': int(opt['--round-order']),
       'status': list_status,
       'title': f'{list_status.title()} Seat Allotment — {opt["--round"]}, PG NEET 2026 Medical (MD/MS + Diploma), Karnataka (KEA)',
       'published_on': published, 'source_file_name': os.path.basename(PDF),
       'notes': (f'KEA PG NEET-2026 Medical (MD/MS) {opt["--round"]} {list_status} seat allotment. Status column Allotted / Reported (Reported = kept the reported Round 1 seat); fresh / upgraded / retained by AIR against the Round 1 final list. rank = rank_ai = the printed All '
                 'India Rank. Quota from the seat-type letter of the course code (M01GC5: G government → Government '
                 'Quota, P private → Private Quota - GMP / Open / Minority by category, Q → Management Quota (MNG), '
                 'N → NRI Quota). Categories in the 2025 KEA code spellings (GM, 2AG, GMH = Kalyana Karnataka, PGM = '
                 'PwD); KEA\'s new S1–S4 codes = SC-A, SC-B, SC-C, SC-C (20%) (stored SC-AG … , SC-C (20%)G). The list '
                 'prints no names or roll numbers and no in-service / DNB lines; course fees are printed but not '
                 'stored.' ),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['status'], out['published_on'])
for k, v in checks.items():
    if k != 'by_institute':
        print(k, v)
