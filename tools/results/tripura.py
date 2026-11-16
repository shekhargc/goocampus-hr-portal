"""Tripura (TRMCC / DME Tripura) PG Medical allotment list (Round 1, provisional / provisional revised) -> rows for
POST /api/pg/results/ingest. Authority `dme_tripura`.

Usage: /usr/bin/python3 tripura.py <allotment.pdf> <out.json> --merit <dme_tripura merit rows.json> [--revised]

Page 1 = notice ("Provisional Revised Allotment of Round-1 of Tripura Postgraduate Medical counselling 2026", 16.11.2026).
Pages 2.. = one 13-column table: Sr No, NEET Roll No, Name, NEET Marks, Marks after Incentives, Category, Sub Category,
Domicile, Allotted Category, Allotted Subcategory, Allotted Institute, Allotted Program, Allotment Status.
Name is NEVER read into the output; the roll is used in memory only (to find the merit row) and dropped.
--merit = the loaded Round-1 provisional merit list rows (tools/merit_lists/read_dme_tripura.py output, 162 rows).
- rank = merit Sl no (state merit), rank_ai = merit list NEET AIR; marks after incentives must equal the merit score.
- quota by institute as in tools/seat_matrix/tripura.py / 2025: TMC -> Open Quota, the rest -> State Quota.
- allotted_category = Allotted Category (UR SC ST EWS OBC) + '-PwD' / '-WESM' for the allotted subcategory;
  candidate_category = Category (+ sub category); remarks = Domicile 'Others' + Allotment Status.
- Courses as the seat-matrix reader: NBEMS diplomas -> section 'diploma', Post MBBS DNB -> section 'dnb'.
Strict: anything unexpected -> SystemExit.
"""
import sys, os, re, json, collections
import fitz

INT = re.compile(r'^\d+$')
ROLL = re.compile(r'^2666\d{7}$')
INST = {'AGARTALA GOVERNMENT MEDICAL COLLEGE, AGARTALA, TRIPURA': 'State Quota',
        'TRIPURA MEDICAL COLLEGE & DR. BRAM TEACHING HOSPITAL, HAPANIA, AGARTALA': 'Open Quota',
        'IGM HOSPITAL': 'State Quota',
        'LOKOPRIYA GOPINATH BORDOLOI REGIONAL INSTITUTE OF MEDICAL HEALTH, TEZPUR': 'State Quota',
        'MODERN PSYCHIATRIC HOSPITAL, PO: BIMANGARH, NARSINGARH, AGARTALA, TRIPURA': 'State Quota'}
COURSES = {
    'M.D. (RADIO-DIAGNOSIS)': ('MD - Radio-Diagnosis', 'mdms'), 'M.D. (GENERAL MEDICINE)': ('MD - General Medicine', 'mdms'),
    'M.D. (OBST. AND GYNAE)/MS (OBSTETRICS AND GYNAECOLOGY)': ('MS - Obstetrics and Gynaecology', 'mdms'),
    'M.D. (RADIOTHERAPY/ RADIATION ONCOLOGY)': ('MD - Radiotherapy / Radiation Oncology', 'mdms'),
    'M.S. (ORTHOPAEDICS)': ('MS - Orthopaedics', 'mdms'),
    'M.D. (TUBERCULOSIS AND RESPIRATORY DISEASES)/PULMONARY MEDICINE /M.D. (RESPIRATORY MEDICINE)': ('MD - Respiratory Medicine', 'mdms'),
    'M.S. (GENERAL SURGERY)': ('MS - General Surgery', 'mdms'), 'M.D. (PSYCHIATRY)': ('MD - Psychiatry', 'mdms'),
    'M.D. (PAEDIATRICS)': ('MD - Paediatrics', 'mdms'), 'M.D. (ANAESTHESIOLOGY)': ('MD - Anaesthesiology', 'mdms'),
    'M.D. (PATHOLOGY)': ('MD - Pathology', 'mdms'), 'M.D. (PHARMACOLOGY)': ('MD - Pharmacology', 'mdms'),
    'M.D. (PREVENTIVE AND SOCIAL MEDICINE)/ COMMUNITY MEDICINE': ('MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    'M.S. (OPHTHALMOLOGY)': ('MS - Ophthalmology', 'mdms'), 'M.S. (E.N.T.)': ('MS - ENT (Otorhinolaryngology)', 'mdms'),
    'M.D. (BIOCHEMISTRY)': ('MD - Biochemistry', 'mdms'), 'M.D. (PHYSIOLOGY)': ('MD - Physiology', 'mdms'),
    'M.D. (FORENSIC MEDICINE)': ('MD - Forensic Medicine', 'mdms'), 'M.D. (ANATOMY)': ('MD/MS - Anatomy', 'mdms'),
    'M.D. (MICROBIOLOGY)': ('MD - Microbiology', 'mdms'), 'M.D. (DERMATOLOGY , VENEREOLOGY AND LEPROSY)': ('MD - Dermatology', 'mdms'),
    '(NBEMS-DIPLOMA) OBSTETRICS AND GYNAECOLOGY': ('Diploma in Obstetrics and Gynaecology', 'diploma'),
    '(NBEMS-DIPLOMA) PAEDIATRICS': ('Diploma in Child Health / Paediatrics', 'diploma'),
    '(NBEMS-DIPLOMA) FAMILY MEDICINE': ('Diploma in Family Medicine', 'diploma'),
    'Post MBBS DNB (Psychiatry), NBEMS': ('DNB - Psychiatry (Post-MBBS)', 'dnb')}
CATS = {'UR', 'SC', 'ST', 'EWS', 'OBC'}
SUB = {'NO': '', 'PWD': '-PwD', 'WESM': '-WESM'}
CCAT = {'General': 'General', 'Other Backward Class (OBC)': 'OBC', 'Schedule Caste (SC)': 'SC',
        'Schedule Tribe (ST)': 'ST', 'General-EWS': 'EWS'}
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')


def main():
    a = sys.argv[1:]
    revised = '--revised' in a
    a = [x for x in a if x != '--revised']
    if '--merit' not in a:
        raise SystemExit(__doc__)
    i = a.index('--merit'); merit = json.load(open(a[i + 1])); del a[i:i + 2]
    pdf, out = a
    approved = {c['course'] for c in json.load(open(SHEET))['courses']}
    assert {v[0] for v in COURSES.values() if v[1] != 'dnb'} <= approved
    by_roll = {r['roll']: r for r in merit['rows']}
    d = fitz.open(pdf)
    t0 = ' '.join(d[0].get_text().split())
    m = re.search(r'Provisional (Revised )?[Aa]llotment of Round-1 of Tripura Postgraduate Medical counselling 2026', t0)
    md = re.search(r'Dated-\s*(\d{1,2})(?:st|nd|rd|th)? (\w+) (\d{4})', t0)
    if not m or not md:
        raise SystemExit('notice changed')
    mon = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
           'november', 'december'].index(md.group(2).lower()) + 1
    date = f'{md.group(3)}-{mon:02d}-{int(md.group(1)):02d}'
    rows, srs, text_rolls = [], [], 0
    for p in d:
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        for t in p.find_tables().tables:
            for r in t.extract():
                if len(r) != 13:
                    raise SystemExit(f'p{p.number + 1}: {len(r)} columns')
                c = [' '.join((x or '').split()) for x in r]
                if not INT.match(c[0]):
                    continue                                  # title / header rows
                where = f'p{p.number + 1} sr {c[0]}'
                if not ROLL.match(c[1]):
                    raise SystemExit(f'{where}: row shape')
                if (c[5] not in CCAT or c[6] not in SUB or c[7] not in ('Tripura', 'Others') or c[8] not in CATS
                        or c[9] not in SUB or c[10] not in INST or c[11] not in COURSES or c[12] != 'Fresh'):
                    raise SystemExit(f'{where}: unknown value [{c[5]}|{c[6]}|{c[7]}|{c[8]}|{c[9]}|{c[10]}|{c[11]}|{c[12]}]')
                mr = by_roll.get(c[1])
                if mr is None or abs(float(mr['score']) - float(c[4])) > 0.01:
                    raise SystemExit(f'{where}: not in the merit list with the same marks after incentives')
                course, section = COURSES[c[11]]
                srs.append(int(c[0]))
                rows.append({'sno': int(c[0]), 'rank': mr['state_rank'], 'rank_ai': mr['air'], 'quota_raw': '',
                             'quota': INST[c[10]], 'institute_raw': c[10], 'course_raw': c[11], 'course': course,
                             'section': section, 'allotted_category': c[8] + SUB[c[9]],
                             'allotted_category_raw': ' / '.join(x for x in (c[8], c[9]) if x),
                             'candidate_category': CCAT[c[5]] + SUB[c[6]],
                             'remarks': '; '.join(x for x in ('Domicile: Others' if c[7] == 'Others' else '',
                                                              f'Status: {c[12]}') if x)})
    if srs != list(range(1, len(srs) + 1)) or text_rolls != len(rows):
        raise SystemExit(f'Sr No not 1..n or rolls in text {text_rolls} != rows {len(rows)}')
    if len({r['rank'] for r in rows}) != len(rows):
        raise SystemExit('duplicate merit rank')
    checks = {'pages': d.page_count, 'rows': len(rows), 'rolls_in_pdf_text': text_rolls, 'notice_date': date,
              'revised': bool(m.group(1)),
              'by_quota': dict(collections.Counter(r['quota'] for r in rows).most_common()),
              'by_category': dict(collections.Counter(r['allotted_category'] for r in rows).most_common()),
              'by_institute': dict(collections.Counter(r['institute_raw'] for r in rows).most_common()),
              'by_section': dict(collections.Counter(r['section'] for r in rows).most_common()),
              'merit_found_marks_agree': len(rows),
              'rank': [min(r['rank'] for r in rows), max(r['rank'] for r in rows)],
              'rank_ai': [min(r['rank_ai'] for r in rows), max(r['rank_ai'] for r in rows)]}
    word = 'Provisional Revised' if m.group(1) else 'Provisional'
    body = {'authority_code': 'dme_tripura', 'round': 'Round 1', 'round_order': 1, 'status': 'provisional',
            'title': f'Tripura PG Medical Counselling 2026 — {word} Allotment, Round 1',
            'published_on': date, 'source_file_name': os.path.basename(pdf),
            'notes': (f'TRMCC / DME Tripura Round-1 {word.lower()} allotment (16.11.2026; report to DME by 19.11.2026 5 PM). '
                      'rank = Sl no in the Round-1 provisional merit list (11.11.2026, corrigendum 12.11), rank_ai = its '
                      'NEET AIR; marks after incentives agree for every row. quota by institute (TMC = Open Quota, rest = '
                      'State Quota, as 2025). No names or roll numbers stored.'),
            'rows': rows, 'checks': checks}
    if revised:
        body['revised'] = True
    json.dump(body, open(out, 'w'), indent=1, ensure_ascii=False)
    print(out); print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
