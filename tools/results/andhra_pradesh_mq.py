"""Andhra Pradesh (Dr NTRUHS) PG (Medical) MANAGEMENT QUOTA college-wise allotment list -> rows for POST /api/pg/results/ingest.

Usage: /usr/bin/python3 andhra_pradesh_mq.py <allotment.pdf> <out.json> [--seat-matrix <ap_seat_matrix_dump.json>]
       [--published YYYY-MM-DD]

"College wise Final Allotment List of PG (Medical) Admissions, Management Quota Phase-I 2026-27" (inbox 1776, 30 pages,
text layer). One table per college: college row, header, one row per allotted candidate (12 columns: Sl.No, NEET RANK,
NEET Roll No, NEET Score, Name, Gender, Muslim Minority, Category, Local Area, Allotment Details, Branch Name, Phase).
Stored as its own round 'Round 1 (Management Quota)' (round_order 1, like CQ non-service 'Round 1' and CQ in-service
'Round 1 (In-service)' — all three are Phase-I).
- rank = rank_ai = printed NEET RANK (MQ merit is the NEET All-India rank; there is no separate state merit number).
- Allotment Details 'APLC - GM - S1B --- 8' = college code - course code - seat category --- (a running number, not stored).
- quota / category in the 2025 AP spellings (same as tools/seat_matrix/andhra_pradesh_mq.py): S-1A / S-1B / S-1 / CA-SF ->
  'Management Quota-(Cat-B)'; S-2 / CA-NRI -> 'NRI Quota-(Cat-C)'; S-3 -> 'Institutional Quota-(Cat-C)';
  allotted_category = the seat category (S-1A, S-1B, S-2, S-3, CA-SF).
- candidate_category = printed caste category (+ ' (Muslim minority)' when Y); remarks = local area ('AP' / 'Others').
- --seat-matrix (staging seatmatrix-dump of "Andhra Pradesh — State Counselling") checks no college x course x seat
  category is allotted more seats than the 2026 MQ seat matrix holds.
Name, gender and roll are NEVER put in the output or printed. Strict: anything unexpected -> SystemExit.
"""
import sys, os, re, json, collections
import fitz

INT = re.compile(r'^\d+$')
ROLL = re.compile(r'^2666\d{7}$')
DETAIL = re.compile(r'^([A-Z]{3,6}) - ([A-Z]{2,7}) - ([A-Z0-9]{1,6}) (?:---|-- -) (\d+)$')
COURSES = {   # code -> (approved course, printed branch name)
    'GM': ('MD - General Medicine', 'MD (General Medicine)'), 'GS': ('MS - General Surgery', 'MS (General Surgery)'),
    'RD': ('MD - Radio-Diagnosis', 'MD (Radio Diagnosis)'), 'ANES': ('MD - Anaesthesiology', 'MD (Anaesthesiolog y)'),
    'OBG': ('MS - Obstetrics and Gynaecology', 'MS (Obstetrics and Gynecology)'),
    'ORTHO': ('MS - Orthopaedics', 'MS (Orthopaedics)'), 'PAED': ('MD - Paediatrics', 'MD (Paediatrics)'),
    'DVL': ('MD - Dermatology', 'MD (Dermatology, Venerology and Leprosy)'),
    'OPTHAL': ('MS - Ophthalmology', 'MS (Ophthalmology )'), 'ENT': ('MS - ENT (Otorhinolaryngology)', 'MS (ENT)'),
    'PM': ('MD - Respiratory Medicine', 'MD (Pulmonary Medicine)'), 'PSY': ('MD - Psychiatry', 'MD (Psychiatry)'),
    'PATH': ('MD - Pathology', 'MD (Pathology)'), 'EM': ('MD - Emergency Medicine', 'MD (Emergency Medicine)'),
    'RT': ('MD - Radiotherapy / Radiation Oncology', 'MD (Radiotherapy)'),
    'FM': ('MD - Forensic Medicine', 'MD (Forensic Medicine)'), 'FAM': ('MD - Family Medicine', 'MD (Family Medicine)'),
    'SPM': ('MD - Social & Preventive Medicine / Community Medicine', 'MD (Community Medicine)'),
}
SEAT = {'S1A': 'S-1A', 'S1B': 'S-1B', 'S1': 'S-1', 'S2': 'S-2', 'S3': 'S-3', 'CASF': 'CA-SF', 'CANRI': 'CA-NRI'}
QUOTA = {'S-1': 'Management Quota-(Cat-B)', 'S-1A': 'Management Quota-(Cat-B)', 'S-1B': 'Management Quota-(Cat-B)',
         'CA-SF': 'Management Quota-(Cat-B)', 'S-2': 'NRI Quota-(Cat-C)', 'CA-NRI': 'NRI Quota-(Cat-C)',
         'S-3': 'Institutional Quota-(Cat-C)'}
COLLEGES = {   # allotment code -> (printed heading prefix, seat-matrix college name)
    'APLC': ('Apollo Institute of Medical Sciences and Research', 'Apollo Institute of Medical Sciences and Research, Chittoor'),
    'ASRA': ('Alluri Seetharama Raju Academy of Medical Sciences', 'Alluri Seetharama Raju Academy of Medical Sciences, Eluru'),
    'BMCT': ('Sri Balaji Medical College Hospital and Research Institute', 'Sri Balaji Medical College Hospital and Research Institute, Renigunta, Tirupati'),
    'FIMS': ('Fathima Institute of Medical Sciences', 'Fathima Institute of Medical Sciences, Kadapa'),
    'GEMS': ('Great Eastern Medical School and Hospital', 'Great Eastern Medical School and Hospital, Srikakulam'),
    'GMCE': ('Govt. Medical College, Eluru', 'Government Medical College, Eluru'),
    'GMCM': ('Govt. Medical College, Machilipatnam', 'Government Medical College, Machilipatnam'),
    'GMCN': ('Govt. Medical College, Nandyal', 'Government Medical College, Nandyal'),
    'GMCR': ('Govt. Medical College, Rajahmundry', 'Government Medical College, Rajamahendravaram'),
    'GMCV': ('Govt. Medical College, Vizianagaram', 'Government Medical College, Vizianagaram'),
    'GSLR': ('GSL Medical College', 'GSL Medical College, Rajahmundry'),
    'GVPT': ('Gayatri Vidya Parishad Inst.', 'Gayatri Vidya Parishad Institute of Health Care and Medical Technology, Visakhapatnam'),
    'KATR': ('Katuri Medical College and Hospital', 'Katuri Medical College and Hospital, Guntur'),
    'KONA': ('Konasema Institute of Medical Sciences', 'Konasema Institute of Medical Sciences and Research Foundation, Amalapuram'),
    'MAHA': ('Maharaja Institute of Medical Sciences', 'Maharaja Institute of Medical Sciences, Vizianagaram'),
    'NARN': ('Narayana Medical College', 'Narayana Medical College, Nellore'),
    'NIMR': ('Nimra Institute of Medical Sciences', 'Nimra Institute of Medical Sciences, Vijayawada'),
    'NRIM': ('NRI Medical College', 'NRI Medical College, Chinnakakani'),
    'NRVP': ('NRI Institute of Medical Sciences', 'NRI Institute of Medical Sciences, Visakhapatnam'),
    'PESK': ('P.E.S. Institute of Medical Sciences', 'P.E.S. Institute of Medical Sciences and Research, Kuppam'),
    'PSIM': ('Dr. Pinnamaneni Siddhartha Institute', 'Dr. Pinnamaneni Siddhartha Institute of Medical Sciences, Gannavaram'),
    'SRMC': ('Santhiram Medical College', 'Santhiram Medical College, Nandyal'),
    'VMCK': ('Viswabharathi Medical College', 'Viswabharathi Medical College, Kurnool'),
}
CATS = {'OC', 'BC-A', 'BC-B', 'BC-C', 'BC-D', 'BC-E', 'SC', 'ST', 'OBC', 'EWS', 'SC G-I', 'SC G-II', 'SC G-III'}
HEAD = ('Sl.No.', 'S.No.')


SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')


def read(path):
    approved = {c['course'] for c in json.load(open(SHEET))['courses']}
    if not {v[0] for v in COURSES.values()} <= approved:
        raise SystemExit('a course name is not in specialty_sheet.json')
    d = fitz.open(path)
    full = ' '.join(' '.join(p.get_text().split()) for p in d)
    m = re.search(r'College wise (Final|Provisional) Allotment List of PG \(Medical\) Admissions, Management Quota Phase-I 2026-27', full)
    if not m:
        raise SystemExit('title changed (expected Management Quota Phase-I 2026-27)')
    status = m.group(1).lower()
    rows, college, code_of, unk, text_rolls = [], None, {}, collections.Counter(), 0
    for p in d:
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        for t in p.find_tables().tables:
            for r in t.extract():
                c = [' '.join((x or '').split()) for x in r]
                if len(c) != 12:
                    raise SystemExit(f'p{p.number + 1}: table with {len(c)} columns')
                if c[0] and not any(c[1:]):
                    college = c[0]; continue
                if c[0] in HEAD:
                    continue
                where = f'p{p.number + 1} sno {c[0] if INT.match(c[0]) else "?"}'
                if not (INT.match(c[0]) and INT.match(c[1]) and ROLL.match(c[2]) and INT.match(c[3])):
                    raise SystemExit(f'{where}: unexpected row shape')
                if c[5] not in ('M', 'F', 'T') or c[6] not in ('Y', 'N') or c[7] not in CATS or c[8] not in ('AP', 'Others') \
                        or c[11] != 'Phase-1':
                    raise SystemExit(f'{where}: gender / minority / category / area / phase [{c[6]}|{c[7]}|{c[8]}|{c[11]}]')
                dm = DETAIL.match(c[9])
                if not dm:
                    raise SystemExit(f'{where}: allotment details shape [{c[9]}]')
                ccode, course, seat, _n = dm.groups()
                if ccode not in COLLEGES or course not in COURSES or seat not in SEAT:
                    unk[(ccode, course, seat)] += 1; continue
                if college is None or not college.replace('  ', ' ').startswith(COLLEGES[ccode][0]) \
                        or code_of.setdefault(ccode, college) != college:
                    raise SystemExit(f'{where}: college code {ccode} does not match its college heading')
                if c[10] != COURSES[course][1]:
                    raise SystemExit(f'{where}: branch name [{c[10]}] does not match course code {course}')
                cat = SEAT[seat]
                rows.append({'sno': len(rows) + 1, 'rank': int(c[1]), 'rank_ai': int(c[1]), 'quota_raw': seat,
                             'quota': QUOTA[cat], 'institute_raw': college, 'course_raw': c[10],
                             'course': COURSES[course][0], 'section': 'mdms', 'allotted_category': cat,
                             'allotted_category_raw': f'{ccode} - {course} - {seat}',
                             'candidate_category': c[7] + (' (Muslim minority)' if c[6] == 'Y' else ''),
                             'remarks': c[8], '_sno': int(c[0]), '_code': ccode, '_course': course})
    if unk:
        raise SystemExit(f'unknown college / course / seat category: {dict(unk)}')
    if text_rolls != len(rows):
        raise SystemExit(f'rolls in text {text_rolls} != rows {len(rows)}')
    by_col = collections.defaultdict(list)
    for r in rows:
        by_col[r['institute_raw']].append(r['_sno'])
    bad = [k for k, v in by_col.items() if v != list(range(1, len(v) + 1))]
    if bad:
        raise SystemExit(f'S.No not 1..n within {len(bad)} colleges')
    # Within a college the list is in NEET-rank order (merit order).
    for k in by_col:
        ranks = [r['rank'] for r in rows if r['institute_raw'] == k]
        if ranks != sorted(ranks):
            raise SystemExit(f'{k}: NEET ranks not in merit order')
    checks = {
        'pages': d.page_count, 'rows': len(rows), 'rolls_in_pdf_text': text_rolls, 'status': status,
        'colleges': len(by_col),
        'by_quota': dict(collections.Counter(r['quota'] for r in rows).most_common()),
        'by_allotted_category': dict(collections.Counter(r['allotted_category'] for r in rows).most_common()),
        'by_candidate_category': dict(collections.Counter(r['candidate_category'] for r in rows).most_common()),
        'by_local_area': dict(collections.Counter(r['remarks'] for r in rows).most_common()),
        'by_course': dict(collections.Counter(r['course'] for r in rows).most_common()),
        'rank_ai': [min(r['rank_ai'] for r in rows), max(r['rank_ai'] for r in rows)],
    }
    return status, rows, checks


def check_matrix(rows, dump_path):
    """Allotted per (college, course, seat category) must be <= the 2026 MQ seat matrix seats."""
    d = json.load(open(dump_path))
    seats = collections.Counter()
    for x in d.get('rows') or []:
        if x.get('quota') in set(QUOTA.values()):
            seats[(x['college_name'], x['course_name'], x['category'])] += int(x.get('seats') or 0)
    got = collections.Counter((COLLEGES[r['_code']][1], r['course'], r['allotted_category']) for r in rows)
    over, missing = [], []
    for k, n in got.items():
        cap = seats.get(k)
        if cap is None and k[2] in ('S-1A', 'S-1B'):              # minority colleges print S-1 in the matrix
            cap = seats.get((k[0], k[1], 'S-1'))
        if cap is None:
            missing.append({'college': k[0], 'course': k[1], 'category': k[2], 'allotted': n})
        elif n > cap:
            over.append({'college': k[0], 'course': k[1], 'category': k[2], 'allotted': n, 'seats': cap})
    total_mq = sum(seats.values())
    return {'matrix_mq_seats': total_mq, 'allotted': len(rows), 'fill_pct': round(100 * len(rows) / total_mq, 1) if total_mq else None,
            'over_seat_matrix': over, 'not_in_seat_matrix': missing}


def main():
    a = sys.argv[1:]
    sm = pub = None
    if '--seat-matrix' in a:
        i = a.index('--seat-matrix'); sm = a[i + 1]; del a[i:i + 2]
    if '--published' in a:
        i = a.index('--published'); pub = a[i + 1]; del a[i:i + 2]
    if len(a) != 2:
        raise SystemExit(__doc__)
    pdf, out = a
    status, rows, checks = read(pdf)
    if sm:
        checks['seat_matrix'] = check_matrix(rows, sm)
    for r in rows:
        del r['_sno'], r['_code'], r['_course']
    body = {'authority_code': 'ntruhs', 'round': 'Round 1 (Management Quota)', 'round_order': 1, 'status': status,
            'title': f'PG (Medical) MQ 2026-27 - Phase-I College wise {status.title()} Allotment List',
            'published_on': pub or '', 'source_file_name': os.path.basename(pdf),
            'notes': ('Dr NTRUHS Management Quota (Cat-B S-1A / S-1B / CA-SF, NRI Cat-C S-2, Institutional Cat-C S-3), '
                      'Phase-I (= Round 1), college-wise list. Its own round, separate from CQ non-service (Round 1) and '
                      'CQ in-service (Round 1 (In-service)). rank = rank_ai = printed NEET AIR. quota / allotted_category in '
                      'the 2025 AP spellings; candidate_category = caste category (+ Muslim minority); remarks = local area. '
                      'No names, roll numbers or gender stored.'),
            'rows': rows, 'checks': checks}
    json.dump(body, open(out, 'w'), indent=1, ensure_ascii=False)
    print(out); print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
