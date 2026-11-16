"""Andhra Pradesh (Dr NTRUHS) "No. of seats available for Management Quota PG - Seat Matrix - 2026-27" (inbox 1714,
"PG (Medical) MQ Seat Matrix 2026-27", 3 pages, text layer) -> standardised seat rows for the body
"Andhra Pradesh — State Counselling" (authority `ntruhs`). MANAGEMENT QUOTA ONLY: the Competent Authority (CQ) seat
matrix is not part of this file.

Usage: /usr/bin/python3 andhra_pradesh_mq.py <mq_matrix.pdf> <cutoffs2025.json> <out.json>

Layout (cells read with common.grids): S.No 1..38 (17 clinical degrees, 10 clinical diplomas, 9 non-clinical degrees,
2 non-clinical diplomas) x colleges. Government colleges (GMC Eluru / Machilipatnam / Rajamahendravaram / Vizianagaram
/ Nandyal) print CA-SF / CA-NRI (self-financing seats); private colleges print MQ (= total) + S-1A / S-1B / S-2 / S-3,
the two minority colleges (FIMS Kadapa, NIMRA) MQ + S-1 / S-2 / S-3.
Quota / category in the 2025 AP spellings: S-1, S-1A, S-1B, CA-SF -> 'Management Quota-(Cat-B)'; S-2, CA-NRI ->
'NRI Quota-(Cat-C)'; S-3 -> 'Institutional Quota-(Cat-C)'; category = the printed column (S-1A, CA-SF ...).
College headers are not in the text layer at every column, so each page's college list is fixed here and checked
against the header text that is there. MD (FM) sits under NON-CLINICAL DEGREES (Family Medicine is S.No 11), so it is
Forensic Medicine. Checks: every private college's MQ = S-columns on every line, S.No 1..38 + subject wording per page.
"""
import sys, os, json, re, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import grids, clean, load_cuts, build, report

PDF, CUTS, OUT = sys.argv[1:4]
SUBJECTS = [   # S.No -> (printed subject, approved course, section)
    ('MD (Gen.Med)', 'MD - General Medicine', 'mdms'), ('MD (Paed)', 'MD - Paediatrics', 'mdms'),
    ('MD (Anes)', 'MD - Anaesthesiology', 'mdms'), ('MD (P.M.) T. B', 'MD - Respiratory Medicine', 'mdms'),
    ('MD DVL', 'MD - Dermatology', 'mdms'), ('MD (R.D.)', 'MD - Radio-Diagnosis', 'mdms'),
    ('MD (Psy.)', 'MD - Psychiatry', 'mdms'), ('MD(RT) Radiation oncology', 'MD - Radiotherapy / Radiation Oncology', 'mdms'),
    ('MD (Emer.Med)', 'MD - Emergency Medicine', 'mdms'),
    ('MD (Transfusion Medicine)', 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'mdms'),
    ('MD (Familly Medicine)', 'MD - Family Medicine', 'mdms'), ('MS (Gen.Surg)', 'MS - General Surgery', 'mdms'),
    ('MS (Ortho.)', 'MS - Orthopaedics', 'mdms'), ('MS (Opthal)', 'MS - Ophthalmology', 'mdms'),
    ('MS (ENT)', 'MS - ENT (Otorhinolaryngology)', 'mdms'), ('MS (O B&G)', 'MS - Obstetrics and Gynaecology', 'mdms'),
    ('MD (Nuclear Medicine)', 'MD - Nuclear Medicine', 'mdms'),
    ('DCH', 'Diploma in Child Health / Paediatrics', 'diploma'), ('DA', 'Diploma in Anaesthesiology', 'diploma'),
    ('DTCD', 'Diploma in Respiratory Medicine', 'diploma'), ('DDVL', 'Diploma in Dermatology', 'diploma'),
    ('DMRD', 'Diploma in Radio Diagnosis', 'diploma'), ('DPM', 'Diploma in Psychological Medicine', 'diploma'),
    ('D Ortho', 'Diploma in Orthopaedics', 'diploma'), ('DO', 'Diploma in Ophthalmology', 'diploma'),
    ('DLO', 'Diploma in ENT', 'diploma'), ('DGO', 'Diploma in Obstetrics and Gynaecology', 'diploma'),
    ('MD (Antomy)', 'MD/MS - Anatomy', 'mdms'), ('MD (Physio.)', 'MD - Physiology', 'mdms'),
    ('MD (Biochem.)', 'MD - Biochemistry', 'mdms'), ('MD (Path)', 'MD - Pathology', 'mdms'),
    ('MD (Micro.Bio)', 'MD - Microbiology', 'mdms'), ('MD (Pharma)', 'MD - Pharmacology', 'mdms'),
    ('MD (FM)', 'MD - Forensic Medicine', 'mdms'),
    ('MD(Community Medicine)', 'MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    ('MD (Hos.Adm)', 'MD - Hospital Administration', 'mdms'), ('DCP', 'Diploma in Pathology', 'diploma'),
    ('DPH', 'Diploma in Public Health', 'diploma')]
G = ['CA-SF', 'CA-NRI']
P5 = ['MQ', 'S-1A', 'S-1B', 'S-2', 'S-3']
P4 = ['MQ', 'S-1', 'S-2', 'S-3']
PAGES = [   # (header text to find, standard college name, column labels)
    [('GMCE', 'Government Medical College, Eluru', G), ('GMCM', 'Government Medical College, Machilipatnam', G),
     ('GMCR', 'Government Medical College, Rajamahendravaram', G), ('GMCV', 'Government Medical College, Vizianagaram', G),
     ('GMCN', 'Government Medical College, Nandyal', G),
     ('ASRAM Elur', 'Alluri Seetharama Raju Academy of Medical Sciences, Eluru', P5),
     ('NRI Mangal', 'NRI Medical College, Chinnakakani', P5),
     ('KIMS Amala', 'Konasema Institute of Medical Sciences and Research Foundation, Amalapuram', P5),
     ('GSL RAJAHM', 'GSL Medical College, Rajahmundry', P5), ('KATURI Gun', 'Katuri Medical College and Hospital, Guntur', P5)],
    [('Dr. PSIMS', 'Dr. Pinnamaneni Siddhartha Institute of Medical Sciences, Gannavaram', P5),
     ('MIMS Vizia', 'Maharaja Institute of Medical Sciences, Vizianagaram', P5),
     ('GEMS Srika', 'Great Eastern Medical School and Hospital, Srikakulam', P5),
     ('NRI,Visakh', 'NRI Institute of Medical Sciences, Visakhapatnam', P5),
     ('GVPT, Viza', 'Gayatri Vidya Parishad Institute of Health Care and Medical Technology, Visakhapatnam', P5),
     ('NMC Nellor', 'Narayana Medical College, Nellore', P5), ('PES Kuppam', 'P.E.S. Institute of Medical Sciences and Research, Kuppam', P5)],
    [('SANTHIRAM', 'Santhiram Medical College, Nandyal', P5), ('VMC Kurnoo', 'Viswabharathi Medical College, Kurnool', P5),
     ('APOLLO Chi', 'Apollo Institute of Medical Sciences and Research, Chittoor', P5),
     ('BMC, Tirup', 'Sri Balaji Medical College Hospital and Research Institute, Renigunta, Tirupati', P5),
     ('FIMS Kadap', 'Fathima Institute of Medical Sciences, Kadapa', P4),
     ('NIMRA Ibra', 'Nimra Institute of Medical Sciences, Vijayawada', P4)]]
QUOTA = {'S-1': 'Management Quota-(Cat-B)', 'S-1A': 'Management Quota-(Cat-B)', 'S-1B': 'Management Quota-(Cat-B)',
         'CA-SF': 'Management Quota-(Cat-B)', 'S-2': 'NRI Quota-(Cat-C)', 'CA-NRI': 'NRI Quota-(Cat-C)',
         'S-3': 'Institutional Quota-(Cat-C)'}
norm = lambda s: re.sub(r'\s+', '', s)


def val(s):
    s = clean(s)
    if not s.isdigit():
        raise SystemExit(f'not a number: {s!r}')
    return int(s)


doc = fitz.open(PDF)
if doc.page_count != 3:
    raise SystemExit('expected 3 pages')
rows, checks = [], {}
for pi, colleges in enumerate(PAGES):
    t = grids(doc[pi])[0]
    if 'Management Quota PG - Seat Matrix - 2026-27' not in clean(t[0][0]):
        raise SystemExit(f'p{pi + 1}: title changed')
    head = ' '.join(clean(x) for x in t[1])
    labels = [clean(x) for x in t[2][2:]]
    want = [c for _, _, cols in colleges for c in cols]
    if labels != want:
        raise SystemExit(f'p{pi + 1}: column labels {labels}')
    for key, _, _ in colleges:
        if key not in head:
            raise SystemExit(f'p{pi + 1}: college header {key!r} not found')
    sno = 0
    for r in t[3:]:
        c = [clean(x) for x in r]
        if not c[0].isdigit():
            continue
        sno += 1
        if int(c[0]) != sno or norm(c[1]) != norm(SUBJECTS[sno - 1][0]):
            raise SystemExit(f'p{pi + 1}: S.No {c[0]} subject {c[1]!r}')
        _, course, section = SUBJECTS[sno - 1]
        j = 2
        for _, college, cols in colleges:
            vals = dict(zip(cols, (val(x) for x in c[j:j + len(cols)]))); j += len(cols)
            if 'MQ' in vals and vals['MQ'] != sum(v for k, v in vals.items() if k != 'MQ'):
                raise SystemExit(f'p{pi + 1} S.No {sno} {college}: MQ {vals["MQ"]} != split {vals}')
            checks[f'{college} | MQ total'] = tuple(
                a + b for a, b in zip(checks.get(f'{college} | MQ total', (0, 0)),
                                      (sum(v for k, v in vals.items() if k != 'MQ'), vals.get('MQ', sum(vals.values())))))
            for k, n in vals.items():
                if k != 'MQ' and n:
                    rows.append({'college': college, 'course': course, 'quota': QUOTA[k], 'category': k, 'seats': n,
                                 'section': section,
                                 'institute_type': 'Government Institute' if k.startswith('CA-') else 'Private Institute'})
    if sno != 38:
        raise SystemExit(f'p{pi + 1}: {sno} subject lines')

FAMILY = {'Management Quota-(Cat-B)': ('Management Quota-(Cat-B)',), 'NRI Quota-(Cat-C)': ('NRI Quota-(Cat-C)',),
          'Institutional Quota-(Cat-C)': ('Institutional Quota-(Cat-C)',)}
cuts = load_cuts(CUTS, 'Andhra Pradesh')
out = build(rows, cuts, 'Andhra Pradesh', 'AP', lambda q: FAMILY[q],
            cat_match=lambda x: (x['category'],) + (('S-1', 'S-1B', 'S-1A') if x['category'].startswith('S-1') else ()))
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
