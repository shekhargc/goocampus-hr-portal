"""Rajasthan NEET PG 2026 Round 1 provisional seat matrix (pg.neetrajasthan.com, 18.10.2026) → standardised
seat rows, bridged to Rajasthan's 2025 cut-offs. Run with /usr/bin/python3 (PyMuPDF)."""
import json, re, sys, collections
import os
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import college_code

PDF, CUTS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]

COURSES = {  # S.No. on pages 1-2 → approved course name (pg_admin/data/specialty_sheet.json)
    1: 'MD - Anaesthesiology', 2: 'MD/MS - Anatomy', 3: 'MD - Biochemistry', 4: 'MD - Emergency Medicine',
    5: 'MD - Forensic Medicine', 6: 'MD - General Medicine', 7: 'MD - Geriatrics',
    8: 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 9: 'MD - Microbiology',
    10: 'MD - Palliative Medicine', 11: 'MD - Paediatrics', 12: 'MD - Pathology', 13: 'MD - Pharmacology',
    14: 'MD - Physical Medicine and Rehabilitation', 15: 'MD - Physiology',
    16: 'MD - Social & Preventive Medicine / Community Medicine', 17: 'MD - Psychiatry', 18: 'MD - Radio-Diagnosis',
    19: 'MD - Radiotherapy / Radiation Oncology', 20: 'MD - Respiratory Medicine', 21: 'MD - Dermatology',
    22: 'MD - Tropical Medicine', 23: 'MS - ENT (Otorhinolaryngology)', 24: 'MS - General Surgery',
    25: 'MS - Obstetrics and Gynaecology', 26: 'MS - Ophthalmology', 27: 'MS - Orthopaedics',
    28: 'MD - Hospital Administration', 29: 'MD - Family Medicine', 30: 'MD - Laboratory Medicine',
    31: 'MD - Nuclear Medicine', 32: 'MS - Traumatology and Surgery'}
RAW_KEY = {  # the PDF's own wording for each S.No. — checked, so a reordered file can't shift courses
    1: 'ANAESTHESI', 2: 'ANATOMY', 3: 'BIOCHEM', 4: 'EMERGENCY', 5: 'FORENSIC', 6: 'GENERAL MEDICINE', 7: 'GERIATRIC',
    8: 'IMMUNOHAEM', 9: 'MICROBIO', 10: 'PALLIATIVE', 11: 'PAEDIATRIC', 12: 'PATHOLOGY', 13: 'PHARMACOLOGY',
    14: 'PHYSICAL MED', 15: 'PHYSIOLOGY', 16: 'PREVENTIVE', 17: 'PSYCHIATRY', 18: 'RADIO-DIAG', 19: 'RADIOTHERAPY',
    20: 'RESPIRATORY', 21: 'SKIN', 22: 'TROPICAL', 23: 'E.N.T', 24: 'GENERAL SURGERY', 25: 'OBSTETRICS',
    26: 'OPHTHALMOLOGY', 27: 'ORTHOPAEDICS', 28: 'HOSPITAL', 29: 'FAMILY', 30: 'LABORATORY', 31: 'NUCLEAR',
    32: 'TRAUMATOLOGY'}
COLLEGES = {  # PDF header → standard institute name (as in the 2025 cut-offs / college master)
    'Dr SNMC Jodhpur': 'Dr. Sampurnanand Medical College, Jodhpur',
    'GMC Kota': 'Government Medical College, Kota',
    'JLN MC Ajmer': 'Jawahar Lal Nehru Medical College, Ajmer',
    'RNT MC Udaipur': 'RNT Medical College, Udaipur',
    'SMS MC Jaipur': 'SMS Medical College, Jaipur',
    'SPMC Bikaner': 'Sardar Patel Medical College, Bikaner',
    'ESIC Alwar': 'ESIC Medical College and Hospital, Alwar, Rajasthan',
    'RUHS CMS Jaipur': 'RUHS College of Medical Sciences, Jaipur',
    'GMC Bharatpur': 'Government Medical College, Bharatpur (Shree Jagannath Pahadia Medical College)',
    'GMC Bhilwara': 'Government Medical College, Bhilwara',
    'GMC Churu': 'Government Medical College, Churu',
    'GMC Dungarpur': 'Government Medical College, Dungarpur',
    'GMC Pali': 'Government Medical College, Pali',
    'JMC Jhalawar': 'Jhalawar Medical College, Jhalawar',
    'American International': 'American International Institute of Medical Sciences, Bedwas',
    'Ananta Institute': 'Ananta Institute of Medical Sciences & Research Centre, Rajsamand',
    'Dr S S Tantia': 'Dr. S.S. Tantia Medical College, Hospital and Research Center, Sri Ganganagar',
    'Geetanjali': 'Geetanjali Medical College & Hospital, Udaipur',
    'Jaipur National': 'Jaipur National University Institute of Medical Sciences and Research Centre, Jagatpura, Jaipur',
    'Mahatma Gandhi Medical': 'Mahatma Gandhi Medical College and Hospital, Sitapur, Jaipur',
    'National Institute of': 'National Institute of Medical Sciences & Research, Jaipur',
    'Pacific Institute': 'Pacific Institute of Medical Sciences, Umarda, Udaipur',
    'Pacific Medical College': 'Pacific Medical College & Hospital, Bhilo Ka Bedla, Udaipur',
}
HOSPITALS = {  # page 3 (Post-MBBS Diploma, in-service) → standard names; None = not in the 2025 data
    'Rajiv Gandhi Govt. GH Alwar': 'Rajiv Gandhi Government General Hospital, Principal Medical Officer General Hospital, Alwar, Rajasthan',
    'Dist Hosp Baran': 'District Hospital, Baran, Rajasthan',
    'GH Barmer': 'Government Hospital, Near Tilak Nagar Bus Stand, Barmer, Rajasthan',
    'Govt Amrit Kaur Hosp Beawar Dist Ajmer': 'Govt. Amrit Kaur Hospital, Beawar, Rajasthan',
    'GMC Bharatpur': 'Raj Bahadur Memorial Hospital, Vikas Nagar, Bharatpur, Rajasthan',
    'Govt Mahatma Gandhi DH Banswara': 'Govt. Mahatma Gandhi District Hospital, Banswara, Rajasthan',
    'MGH Bhilwara': 'Mahatma Gandhi Hospital, Bhopal Ganj, Bhilwara, Rajasthan',
    'Govt DH Bundi': 'Government District Hospital, Bundi, Rajasthan',
    'SSG Govt DH Chittorgarh': 'SSG Government District Hospital, Senthi, Chittorgarh, Rajasthan',
    'Govt. DB General DH Churu': 'Government DB General Medical Hospital, Churu, Rajasthan',
    'Shri Ramkaran Joshi Govt DH Dausa': 'Shri Ramkaran Joshi Government District Hospital, Dausa, Rajasthan',
    'DH Dholpur': 'District Hospital, Dholpur, Rajasthan',
    'GMC & Assoc. Hosp. Dungarpur': 'Government Medical College and Associated Group of Hospitals, Dungarpur, Rajasthan',
    'Govt Dist civil Hosp Sri Ganganagar': 'Govt. District Civil Hospital, Sri Ganganagar, Rajasthan',
    'MGH Govt DH Hanumangarh Town': 'MGM Govt District Hospital, Hanumangarh, Rajasthan',
    'General Hospital, Jalore': None,
    'Govt BDK Hosp Jhunjhunu': 'Govt. BDK Hospital, Jhunjhunu, Rajasthan',
    'GH Karauli': 'General Hospital, Hinduan Gate, Karauli, Rajasthan',
    'JLN Govt Dist. Hosp. Nagaur': 'JLN Government Hospital, Bikaner Road, Nagaur, Rajasthan',
    'SDH Nathdwara': None,
    'GMC & Bangur Hosp. Pali': None,
    'DH Pratapgarh': 'District Hospital, Pratapgarh, Rajasthan',
    'RK Govt District Hospital Rajsamand': 'R.K. Govt District Hospital, Dhoinda, Rajsamand, Rajasthan',
    'GH Sawai Madhopur': 'Government General Hospital, Sawai Madhopur, Rajasthan',
    'SK Hospital Sikar': 'S.K. Hospital, Silver Jubilee Road, Sikar, Rajasthan',
    'GH Sirohi': 'District Hospital, Sirohi, Rajasthan',
    'Govt Dist Sadat Hosp. Tonk': 'Govt. District Saadat Hospital, Tonk, Rajasthan',
    'Govt DH Kekri': 'Govt. District Hospital, Kekri, Rajasthan',
}
NEW_NAMES = {'General Hospital, Jalore': 'General Hospital, Jalore, Rajasthan',
             'SDH Nathdwara': 'Sub-District Hospital, Nathdwara, Rajasthan',
             'GMC & Bangur Hosp. Pali': 'Bangur Hospital (Government Medical College), Pali, Rajasthan'}
DIPLOMA = ['Diploma in Obstetrics and Gynaecology', 'Diploma in Child Health / Paediatrics', 'Diploma in Anaesthesiology',
           'Diploma in Ophthalmology', 'Diploma in ENT', 'Diploma in Respiratory Medicine', 'Diploma in Radio Diagnosis',
           'Diploma in Family Medicine']
DIPLOMA_RAW = ['Obs', 'Paediatrics', 'Anaesthesia', 'Ophthalmology', 'ENT', 'TB', 'Radio', 'Family']

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()
num = lambda s: int(clean(s)) if clean(s).isdigit() else 0
cuts = [c for c in json.load(open(CUTS))['rows'] if c['authority'] and 'rajasthan' in c['authority'].lower()]
inst_type = {c['institute']: c['institute_type'] for c in cuts}


def college_for(header):
    h = clean(header)
    for k, v in COLLEGES.items():
        if h.startswith(k):
            return v
    raise SystemExit(f'unknown college header: {h!r}')


def check_course(sno, raw):
    if RAW_KEY[sno] not in clean(raw).upper().replace('E.N.T.', 'E.N.T'):
        raise SystemExit(f'course mismatch at S.No. {sno}: {raw!r}')


doc = fitz.open(PDF)
rows, checks = [], {}

# ── page 1: Government (State Quota) / RUHS-CMS + Society (State Govt + State Mgmt) ──
t = doc[0].find_tables().tables[0].extract()
hdr, sub = t[2], t[3]
groups, j = [], 2
while j < len(hdr) - 1:
    name = clean(hdr[j])
    if not name:
        j += 1; continue
    if clean(sub[j]).startswith('Total State'):
        groups.append((college_for(name), [(j, 'Government Quota')])); j += 1
    else:   # State (Govt) | State (Mgmt) | Total
        groups.append((college_for(name), [(j, 'Government Quota'), (j + 1, 'Management Quota')])); j += 3
p1_total = 0
for r in t:
    if not clean(r[0]).isdigit():
        if clean(r[1]).startswith('Total Seats'):
            p1_total = num(r[-1])
        continue
    sno = int(clean(r[0])); check_course(sno, r[1])
    for college, cols in groups:
        for ci, quota in cols:
            n = num(r[ci])
            if n:
                rows.append({'college': college, 'course': COURSES[sno], 'quota': quota, 'seats': n, 'section': 'mdms'})
checks['page1'] = (sum(x['seats'] for x in rows), p1_total)

# ── page 2: private colleges — AI (all-India nature) / State / Mgmt ──
t = doc[1].find_tables().tables[0].extract()
hdr = t[2]
groups = []
for j in range(2, len(hdr)):
    nm = clean(hdr[j])
    if nm and not nm.startswith(('Total', 'Distribution')) and j + 3 < len(hdr):
        groups.append((college_for(nm), [(j, 'All India Quota'), (j + 1, 'State Quota'), (j + 2, 'Management Quota')]))
before = len(rows); p2_total = 0
for r in t:
    if not clean(r[0]).isdigit():
        if clean(r[1]).startswith('Total Seats'):
            p2_total = num(r[2 + 4 * len(groups)])        # "Total PG seats in Pvt colleges"
        continue
    sno = int(clean(r[0])); check_course(sno, r[1])
    for college, cols in groups:
        for ci, quota in cols:
            n = num(r[ci])
            if n:
                rows.append({'college': college, 'course': COURSES[sno], 'quota': quota, 'seats': n, 'section': 'mdms'})
checks['page2'] = (sum(x['seats'] for x in rows[before:]), p2_total)

# ── page 3: Post-MBBS Diploma (in-service) + Post-MBBS DNB (in-service) ──
tabs = doc[2].find_tables().tables
t = tabs[0].extract()
for i, raw in enumerate(DIPLOMA_RAW):
    if raw.lower() not in clean(t[1][2 + i]).lower():
        raise SystemExit(f'diploma column {i} is {t[1][2 + i]!r}')
before = len(rows); p3_total = 0
dnb = []
for k, r in enumerate(t):
    if not clean(r[0]).isdigit():
        if 'Total' in clean(r[1]) and not p3_total:
            p3_total = num(r[-1])
            dnb = t[k + 1:]            # the Post-MBBS DNB table follows in the same grid
            break
        continue
    hosp = clean(r[1])
    if hosp not in HOSPITALS:
        raise SystemExit(f'unknown hospital {hosp!r}')
    name = HOSPITALS[hosp] or NEW_NAMES[hosp]
    for i, course in enumerate(DIPLOMA):
        n = num(r[2 + i])
        if n:
            rows.append({'college': name, 'course': course, 'quota': 'Diploma Quota (In-service)', 'seats': n,
                         'section': 'diploma'})
checks['page3_diploma'] = (sum(x['seats'] for x in rows[before:]), p3_total)
dnb += [x for tb in tabs[1:] for x in tb.extract()]
for r in dnb:
    if clean(r[0]).isdigit():
        for course, n in (('DNB - Emergency Medicine (Post-MBBS)', num(r[2])), ('DNB - Family Medicine (Post-MBBS)', num(r[3]))):
            if n:
                rows.append({'college': 'Government RDBP Jaipuria Hospital, Jaipur, Rajasthan', 'course': course,
                             'quota': 'DNB Quota (In-service)', 'seats': n, 'section': 'dnb'})

# ── bridge to 2025 Rajasthan cut-offs: same college + course + quota family; GEN non-service ranks ──
by = collections.defaultdict(list)
for c in cuts:
    by[(c['institute'], c['course'])].append(c)
fam = {'Government Quota': 'Government Quota', 'Management Quota': 'Management Quota', 'All India Quota': 'All India Quota',
       'State Quota': 'State Quota', 'Diploma Quota (In-service)': 'Diploma Quota'}
out = []
for i, x in enumerate(rows, 1):
    cand = [c for c in by.get((x['college'], x['course']), []) if c['quota'].startswith(fam.get(x['quota'], '~'))]
    pick = (sorted(cand, key=lambda c: (c['category'] != 'GEN', 'Non Service' not in c['quota'],
                                        -(c['closing_rank'] or 0)))[:1] or [None])[0]
    known_inst = x['college'] in inst_type
    row = {'sl_no': i, 'college_code': '', 'state': 'Rajasthan', 'college_name': x['college'], 'category': '',
           'course_name': x['course'], 'seats': x['seats'], 'section': x['section'],
           'institute_type': inst_type.get(x['college'], 'Government Institute'), 'quota': x['quota'],
           'category_code': '', 'course_code': '', 'cutoff_institute': x['college'] if known_inst else '',
           'cutoff_course': x['course'] if pick else '', 'cutoff_quota': pick['quota'] if pick else '',
           'cutoff_category': pick['category'] if pick else '', 'has_cutoff': 1 if pick else 0,
           'new_reason': '' if pick else ('new_college' if not known_inst else
                                          ('new_course' if not by.get((x['college'], x['course'])) else 'new_quota_category')),
           'cr_r1': pick['r1'] if pick else None, 'cr_r2': pick['r2'] if pick else None,
           'cr_r3': pick['r3'] if pick else None, 'cr_closing': pick['closing_rank'] if pick else None,
           'cutoff_fee': pick['fee'] if pick else None}
    out.append(row)
all_courses = {c['course'] for c in json.load(open(CUTS))['rows'] if c['course']}
for row in out:   # stable college code; course "linked" when the name exists anywhere in the cut-offs
    row['college_code'] = college_code('RJ', row['college_name'])
    if row['course_name'] in all_courses:
        row['cutoff_course'] = row['course_name']
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
print('checks (parsed, printed total):', checks)
print('rows', len(out), 'seats', sum(r['seats'] for r in out), 'colleges', len({r['college_name'] for r in out}))
print('by section', dict(collections.Counter(r['section'] for r in out)),
      {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
print('by quota', {q: sum(r['seats'] for r in out if r['quota'] == q) for q in sorted({r['quota'] for r in out})})
print('linked to a 2025 cut-off:', sum(1 for r in out if r['has_cutoff']), '| new:', dict(collections.Counter(r['new_reason'] for r in out if not r['has_cutoff'])))
for r in out:
    if not r['has_cutoff'] and r['new_reason'] == 'new_college':
        print('   new college:', r['college_name'], '|', r['course_name'], r['seats'])
