"""Himachal Pradesh (AMRU) "Provisional Seat Allocation list of PG MD/MS/DNB 1st round Counselling 2026" -> rows for
POST /api/pg/results/ingest. Authority `amru_hp`.

Usage: /usr/bin/python3 himachal_pradesh.py <allocation.pdf> <out.json> --merit <amru_hp merit rows.json>

Page 1 = notice (No. AMRU/(COE)-Admission-129/2026-27(PG MD/MS)7190, 16.11.2026). Pages 2.. = one 10-column table:
Sr No, Merit No., Application No., Name Of Student, Institute Name, Degree, Admission Type of Application, Category of
Application, Admission Type, Category. Application No and Name are NEVER read into the output.
--merit = the rank-bridge rows of the loaded AMRU HP revised final merit list (12.11.2026; tools/merit_lists/
read_amru_hp.py output: state_rank, air, quota, category).
- rank = Merit No. (state merit), rank_ai = AIR of that merit no. in the merit list; the candidate's quota and
  category in the merit list must equal 'Admission Type of Application' / 'Category of Application'.
- quota = SEAT Admission Type in 2025 HP spellings: HP Quota - Direct -> State Quota, HP Quota In- service -> State
  Quota-Inservice, Management Quota -> Management Quota (quota_raw = seat type; remarks = the candidate's own type
  when it differs, e.g. a Direct candidate on a Management seat).
- allotted_category = SEAT Category (General -> GEN, Physically Handicapped -> GEN-PH, EWS, SC, ST as 2025);
  candidate_category = Category of Application.
Strict: anything unexpected -> SystemExit.
"""
import sys, os, re, json, collections
import fitz

INT = re.compile(r'^\d+$')
HEAD = ['Sr No', 'Merit No.', 'Application No.', 'Name Of Student', 'Institute Name', 'Degree',
        'Admission Type of Application', 'Category of Application', 'Admission Type', 'Category']
QUOTA = {'HP Quota - Direct': 'State Quota', 'HP Quota In- service': 'State Quota-Inservice',
         'Management Quota': 'Management Quota'}
# Final list (17.11.2026) prints these labels, but the columns hold the SAME data in the SAME order as the provisional
# list (candidate quota, candidate category, seat quota, seat category) — checked: seat quota / seat category counts equal
# the provisional's 90/49/29 and 136/17/11/3/1, and every row agrees with the merit list's quota + category.
HEAD_FINAL = ['Sr No', 'Merit No.', 'Institute Name', 'Degree', 'Applied Quota', 'Allotted Quota', 'Admitted Quota',
              'Applied Category']
MQUOTA = {'HP Quota - Direct': 'HP Direct', 'HP Quota In- service': 'In-service', 'Management Quota': 'Management'}
CAT = {'General': 'GEN', 'SC': 'SC', 'ST': 'ST', 'EWS': 'EWS', 'Physically Handicapped': 'GEN-PH',
       'Single Girl child': 'Single Girl Child'}
CAT_NORM = {'Economicaly Weaker Sections': 'EWS', 'Economically Weaker Sections': 'EWS'}
COURSES = {
    'MD General Medicine': 'MD - General Medicine', 'MS Obstetrics and Gynaecology': 'MS - Obstetrics and Gynaecology',
    'MS General Surgery': 'MS - General Surgery', 'MD Anaesthesiology': 'MD - Anaesthesiology',
    'MD Radio Diagnosis': 'MD - Radio-Diagnosis', 'MD Paediatrics': 'MD - Paediatrics', 'MS Orthopaedics': 'MS - Orthopaedics',
    'MD Dermatology, Venereology & Leprosy': 'MD - Dermatology', 'MD Psychiatry': 'MD - Psychiatry',
    'MS Ophthalmology': 'MS - Ophthalmology', 'MD Pathology': 'MD - Pathology',
    'MD Community Medicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'MS Otorhinolaryngology': 'MS - ENT (Otorhinolaryngology)', 'MD Pulmonary Medicine': 'MD - Respiratory Medicine',
    'MD Microbiology': 'MD - Microbiology', 'MD Physiology': 'MD - Physiology',
    'MD Radiotherapy': 'MD - Radiotherapy / Radiation Oncology', 'MD Pharmacology': 'MD - Pharmacology',
    'MD Forensic Medicine': 'MD - Forensic Medicine', 'MD Biochemistry': 'MD - Biochemistry',
    'MD Anatomy': 'MD/MS - Anatomy', 'MS Anatomy': 'MD/MS - Anatomy', 'MD Emergency Medicine': 'MD - Emergency Medicine',
}
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')


def cell(x):
    s = ' '.join((x or '').split())
    s = s.replace('Otorhinolaryngolo gy', 'Otorhinolaryngology').replace('Handicapp ed', 'Handicapped')
    s = s.replace('Economica ly', 'Economicaly').replace('Manageme nt', 'Management')
    if s == 'HP Quota In-service':          # final list spelling
        s = 'HP Quota In- service'
    return CAT_NORM.get(s, s)


def main():
    a = sys.argv[1:]
    if '--merit' not in a:
        raise SystemExit(__doc__)
    i = a.index('--merit'); merit = json.load(open(a[i + 1])); del a[i:i + 2]
    pdf, out = a
    approved = {c['course'] for c in json.load(open(SHEET))['courses']}
    assert set(COURSES.values()) <= approved
    by_rank = {r['state_rank']: r for r in merit['rows']}
    if len(by_rank) != len(merit['rows']):
        raise SystemExit('merit: duplicate state_rank')
    d = fitz.open(pdf)
    t0 = ' '.join(d[0].get_text().split())
    m = re.search(r'(Provisional|Final) Seat Allocation list of PG MD/MS/DNB 1st round', t0, re.I)
    md = re.search(r'Dated:\s*(\d{2})\.(\d{2})\.(\d{4})', t0)
    if not m or not md:
        raise SystemExit('notice changed')
    status = 'final' if m.group(1).lower() == 'final' else 'provisional'
    rows, srs, mism = [], [], collections.Counter()
    for p in d:
        for t in p.find_tables().tables:
            for r in t.extract():
                if len(r) != 10:
                    raise SystemExit(f'p{p.number + 1}: {len(r)} columns')
                c = [cell(x) for x in r]
                if not any(c[1:]) and not INT.match(c[0]):
                    continue    # Final list (17.11): the notice text runs into a table on page 2 (column 1 only)
                if c[0] == 'Sr No':
                    if [c[0], c[1], c[4], c[5], c[6], c[7], c[8], c[9]] not in ([HEAD[0], HEAD[1]] + HEAD[4:], HEAD_FINAL):
                        raise SystemExit('header changed')
                    continue
                where = f'p{p.number + 1} sr {c[0] if INT.match(c[0]) else "?"}'
                if not (INT.match(c[0]) and INT.match(c[1])):
                    raise SystemExit(f'{where}: row shape')
                if c[5] not in COURSES or c[6] not in QUOTA or c[8] not in QUOTA or c[7] not in CAT or c[9] not in CAT:
                    raise SystemExit(f'{where}: unknown degree / quota / category [{c[5]}|{c[6]}|{c[7]}|{c[8]}|{c[9]}]')
                mr = by_rank.get(int(c[1]))
                if mr is None:
                    raise SystemExit(f'{where}: merit no. not in the merit list')
                if mr['quota'] != MQUOTA[c[6]]:
                    mism['quota'] += 1
                if (CAT_NORM.get(mr['category'], mr['category'])) != c[7]:
                    mism['category'] += 1
                srs.append(int(c[0]))
                rows.append({'sno': int(c[0]), 'rank': int(c[1]), 'rank_ai': mr['air'], 'quota_raw': c[8],
                             'quota': QUOTA[c[8]], 'institute_raw': c[4], 'course_raw': c[5], 'course': COURSES[c[5]],
                             'section': 'mdms', 'allotted_category': CAT[c[9]], 'allotted_category_raw': c[9],
                             'candidate_category': c[7],
                             'remarks': '' if c[6] == c[8] else f'Candidate type: {c[6]}'})
    if srs != list(range(1, len(srs) + 1)):
        raise SystemExit('Sr No not 1..n')
    if len({r['rank'] for r in rows}) != len(rows):
        raise SystemExit('duplicate merit no.')
    if mism:
        raise SystemExit(f'merit list disagrees: {dict(mism)}')
    checks = {'pages': d.page_count, 'rows': len(rows), 'status': status,
              'notice_date': f'{md.group(3)}-{md.group(2)}-{md.group(1)}',
              'by_quota': dict(collections.Counter(r['quota'] for r in rows).most_common()),
              'by_category': dict(collections.Counter(r['allotted_category'] for r in rows).most_common()),
              'by_institute': dict(collections.Counter(r['institute_raw'] for r in rows).most_common()),
              'by_course': dict(collections.Counter(r['course'] for r in rows).most_common()),
              'candidate_type_differs': sum(1 for r in rows if r['remarks']),
              'merit_found_quota_category_agree': len(rows),
              'rank': [min(r['rank'] for r in rows), max(r['rank'] for r in rows)],
              'rank_ai': [min(r['rank_ai'] for r in rows), max(r['rank_ai'] for r in rows)]}
    body = {'authority_code': 'amru_hp', 'round': 'Round 1', 'round_order': 1, 'status': status,
            'title': f'AMRU HP PG MD/MS/DNB 2026 — {status.title()} Seat Allocation List, 1st Round',
            'published_on': checks['notice_date'], 'source_file_name': os.path.basename(pdf),
            'notes': (('AMRU Himachal Pradesh 1st round FINAL seat allocation (notice dated 17.11.2026; report to the allotted '
                       'institute by 18.11.2026; last HP Direct seat at IGMC Shimla and RPGMC Tanda held for Single Girl Child). '
                       if status == 'final' else
                       'AMRU Himachal Pradesh 1st round seat allocation (notice 129/2026-27-7190, 16.11.2026; objections by '
                       '11 AM 17.11.2026; last HP Direct seat at IGMC Shimla and RPGMC Tanda held for Single Girl Child). ') +
                      'rank = Merit No. of the revised final merit list (12.11.2026), rank_ai = that list\'s AIR. quota = '
                      'seat Admission Type (2025 spelling); remarks give the candidate\'s own type when it differs. '
                      'No DNB seats in this list. No application numbers or names stored.'),
            'rows': rows, 'checks': checks}
    json.dump(body, open(out, 'w'), indent=1, ensure_ascii=False)
    print(out); print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
