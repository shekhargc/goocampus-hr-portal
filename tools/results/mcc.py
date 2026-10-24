"""MCC NEET-PG seat allotment result (provisional / final, any round) → rows for POST /api/pg/results/ingest.
Reads the official PDF (one line per allotted seat: SNo, Rank, Allotted Quota, Allotted Institute, Course,
Allotted Category, Candidate Category, [Remarks — provisional lists only]), maps quota / category / course to the names used in the
2025 cut-offs, and checks the serial numbers run 1..N with none missing. College names are matched on the
portal through the name memory. Run with /usr/bin/python3 (PyMuPDF):
    mcc.py <result.pdf> <out.json>            (add --cache <raw.json> to reuse an earlier read)"""
import json, re, sys, collections
import fitz

PDF, OUT = sys.argv[1], sys.argv[2]
CACHE = sys.argv[sys.argv.index('--cache') + 1] if '--cache' in sys.argv else None

QUOTA = {'All India': 'All India Quota', 'Self-Financed Merit Seat': 'Management/Paid Seats Quota',
         'Non-Resident Indian': 'NRI Quota', 'Delhi University Quota': 'Delhi University Quota',
         'IP University Quota': 'IP University Quota', 'Banaras Hindu University': 'Banaras Hindu University',
         'Aligarh Muslim University': 'Aligarh Muslim University', 'Muslim Minority Quota': 'Muslim Minority Quota',
         'Jain Minority Quota': 'Jain Minority Quota', 'DNB Quota': 'DNB Quota',
         'Armed Forces Medical': 'Armed Forces Medical'}
CATEGORY = {'Open': 'OPEN', 'OBC': 'OBC', 'SC': 'SC', 'ST': 'ST', 'EWS': 'EWS'}
COURSES = {  # MCC wording → approved course name (pg_admin/data/specialty_sheet.json)
    'M.D. Anaesthesiology': 'MD - Anaesthesiology', 'M.D. Anatomy': 'MD/MS - Anatomy',
    'M.D. Bio-Chemistry': 'MD - Biochemistry',
    'M.D. Community Medicine/Social and Preventive Medicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'M.D. Dermatology, Venereology and Leprosy/Dermatology': 'MD - Dermatology',
    'M.D. Emergency Medicine': 'MD - Emergency Medicine', 'M.D. Family Medicine': 'MD - Family Medicine',
    'M.D. Forensic Medicine and Toxicology/Forensic Medicine': 'MD - Forensic Medicine',
    'M.D. General Medicine': 'MD - General Medicine', 'M.D. Geriatrics': 'MD - Geriatrics',
    'M.D. Hospital Administration': 'MD - Hospital Administration',
    'M.D. Immuno Haematology and Blood Transfusion': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'M.D. Laboratory Medicine': 'MD - Laboratory Medicine', 'M.D. Master of Public Health - Epidemiology': 'MPH - Epidemiology',
    'M.D. Microbiology': 'MD - Microbiology', 'M.D. Nuclear Medicine': 'MD - Nuclear Medicine',
    'M.D. Paediatrics': 'MD - Paediatrics', 'M.D. Palliative Medicine': 'MD - Palliative Medicine',
    'M.D. Pathology': 'MD - Pathology', 'M.D. Pharmacology': 'MD - Pharmacology',
    'M.D. Physical Medicine and Rehabilitation': 'MD - Physical Medicine and Rehabilitation',
    'M.D. Physiology': 'MD - Physiology', 'M.D. Psychiatry': 'MD - Psychiatry',
    'M.D. Radiation Oncology/ Radiotherapy': 'MD - Radiotherapy / Radiation Oncology',
    'M.D. Radio-Diagnosis /Radiology': 'MD - Radio-Diagnosis',
    'M.D. Respiratory Medicine/Tuberculosis and Respiratory Diseases': 'MD - Respiratory Medicine',
    'M.D. Sports Medicine': 'MD - Sports Medicine', 'M.D. Tropical Medicine': 'MD - Tropical Medicine',
    'M.D.(COMMUNITY HEALTH ADMN.)': 'MD - Community Health & Administration',
    'M.S. General Surgery': 'MS - General Surgery', 'M.S. Obstetrics and Gynaecology': 'MS - Obstetrics and Gynaecology',
    'M.S. Ophthalmology': 'MS - Ophthalmology', 'M.S. Orthopaedics': 'MS - Orthopaedics',
    'M.S. Otorhinolaryngology/ENT': 'MS - ENT (Otorhinolaryngology)', 'M.S. Traumatology and Surgery': 'MS - Traumatology and Surgery',
    'M.Ch. (Neuro Surgery)': 'MCh - Neuro Surgery',
    'Dermatology, Venereology and Leprosy (D.D.V.L.)': 'Diploma in Dermatology',
    'Diploma in Anaesthesiology (D.A.)': 'Diploma in Anaesthesiology', 'Diploma in Clinical Pathology (D.C.P.)': 'Diploma in Pathology',
    'Diploma in Diabetology': 'Diploma in Diabetology', 'Diploma in Forensic Medicine (D.F.M.)': 'Diploma in Forensic Medicine',
    'Diploma in Health Administration (D.H.A.)': 'Diploma in Health Administration',
    'Diploma in Immuno- Haematology and Blood Transfusion (D.I.H.B.T.)': 'Diploma in Immuno-Haematology and Blood Transfusion',
    'Diploma in Obstetrics and Gynaecology (D.G.O.)': 'Diploma in Obstetrics and Gynaecology',
    'Diploma in Ophthalmology (D.O.)': 'Diploma in Ophthalmology', 'Diploma in Orthopaedics (D.Orth.)': 'Diploma in Orthopaedics',
    'Diploma in Otorhinolaryngology (D.L.O.)': 'Diploma in ENT', 'Diploma in Paediatrics (D.C.H.)': 'Diploma in Child Health / Paediatrics',
    'Diploma in Psychiatry (D.P.M.)': 'Diploma in Psychological Medicine', 'Diploma in Public Health (D.P.H.)': 'Diploma in Public Health',
    'Diploma in Radiation Medicine (D.R.M.)': 'Diploma in Radiation Medicine', 'Diploma in Radiodiagnosis (D.M.R.D.)': 'Diploma in Radio Diagnosis',
    'Diploma in Sport Medicine (D.S.M.)': 'Diploma in Sports Medicine',
    'Diploma in Tuberculosis and Chest Diseases (D.T.C.D.)': 'Diploma in Respiratory Medicine'}

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()


def read(pdf):
    out = []
    for pg in fitz.open(pdf):
        for t in pg.find_tables().tables:
            for r in t.extract():
                # provisional lists have a Remarks column (8); the final list drops it (7)
                if len(r) in (7, 8) and clean(r[0]).isdigit():
                    out.append([clean(x) for x in r] + ([''] if len(r) == 7 else []))
    return out


raw = json.load(open(CACHE)) if CACHE else read(PDF)
if CACHE is not None and not raw:
    raise SystemExit('empty cache')
sn = sorted(int(r[0]) for r in raw)
if sn != list(range(1, len(sn) + 1)):
    raise SystemExit(f'serial numbers are not 1..{len(sn)} — rows missing or read twice')
rows, unknown = [], collections.Counter()
for r in raw:
    sno, rank, quota, inst, course, acat, ccat, rem = r
    if quota not in QUOTA:
        unknown['quota: ' + quota] += 1; continue
    base, pwd = re.fullmatch(r'(Open|OBC|SC|ST|EWS)( PwD)?', acat).groups() if re.fullmatch(
        r'(Open|OBC|SC|ST|EWS)( PwD)?', acat) else (None, None)
    if not base:
        unknown['category: ' + acat] += 1; continue
    if course.startswith('(NBEMS'):
        dip = course.startswith('(NBEMS-DIPLOMA)')
        title = course.split(')', 1)[1].strip().title().replace('Otorhinolaryngolo Gy', 'Otorhinolaryngology')
        std, section = ('DNB Diploma - ' if dip else 'DNB - ') + title, 'dnb'
    elif course in COURSES:
        std = COURSES[course]
        section = 'diploma' if std.startswith('Diploma') else 'mdms'
    else:
        unknown['course: ' + course] += 1; continue
    if not rank.isdigit():
        unknown['rank: ' + rank] += 1; continue
    rows.append({'sno': int(sno), 'rank': int(rank), 'quota_raw': quota, 'quota': QUOTA[quota], 'institute_raw': inst,
                 'course_raw': course, 'course': std, 'section': 'dnb' if quota == 'DNB Quota' else section,
                 'allotted_category': CATEGORY[base] + (' PwD' if pwd else ''), 'allotted_category_raw': acat,
                 'candidate_category': ccat, 'remarks': rem})
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
json.dump({'rows': rows}, open(OUT, 'w'), ensure_ascii=False)
print('rows', len(rows), '| by section', dict(collections.Counter(r['section'] for r in rows)))
print('by quota', dict(collections.Counter(r['quota'] for r in rows)))
print('by allotted category', dict(collections.Counter(r['allotted_category'] for r in rows)))
print('colleges', len({r['institute_raw'] for r in rows}), '| ranks', min(r['rank'] for r in rows), '-', max(r['rank'] for r in rows))
