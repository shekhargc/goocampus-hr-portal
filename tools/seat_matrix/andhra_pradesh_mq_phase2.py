"""Andhra Pradesh (Dr NTRUHS) MQ Phase-II seat matrix: "No. of seats available for Management Quota PG - Seat Matrix -
2026-27 (Including Enhanced/Newly Sanctioned Seats)" (inbox 1966, 24-11-2026, 3 pages, text layer) -> body
"Andhra Pradesh — Management Quota — Phase 2" (authority `ntruhs`, round_no 2). It is the FULL MQ matrix again
(Round 1 MQ seats + enhanced / newly sanctioned), so new_in_round = max(0, Phase 2 − Round 1) per college + course
+ quota + category when --round1 is given. Same layout as andhra_pradesh_mq.py (SUBJECTS, QUOTA, column logic are
copied) with three changes: a 6th government college GMCP (Government Medical College, Paderu — new, no 2025 PG
cut-off) printed after GMCN; colleges headed by 4-letter codes (ASRA, NRIM, KONA, GSLR, KATR / PSIM, MAHA, GEMS,
NRVP, GVPT, NARN, PESK / SRMC, VMCK, APLC, BMCT, FIMS, NIMR — same order as Round 1, checked against the page
image); blank cells (BMCT, whose MQ is 0 on those lines) = 0.

Usage: /usr/bin/python3 andhra_pradesh_mq_phase2.py <mq_phase2.pdf> <cutoffs2025.json> <out.json>
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
PAGES = [   # (header code printed, standard college name, column labels) — order as printed (page images)
    [('GMCE', 'Government Medical College, Eluru', G), ('GMCM', 'Government Medical College, Machilipatnam', G),
     ('GMCR', 'Government Medical College, Rajamahendravaram', G), ('GMCV', 'Government Medical College, Vizianagaram', G),
     ('GMCN', 'Government Medical College, Nandyal', G), ('GMCP', 'Government Medical College, Paderu', G),
     ('ASRA', 'Alluri Seetharama Raju Academy of Medical Sciences, Eluru', P5),
     ('NRIM', 'NRI Medical College, Chinnakakani', P5),
     ('KONA', 'Konasema Institute of Medical Sciences and Research Foundation, Amalapuram', P5),
     ('GSLR', 'GSL Medical College, Rajahmundry', P5), ('KATR', 'Katuri Medical College and Hospital, Guntur', P5)],
    [('PSIM', 'Dr. Pinnamaneni Siddhartha Institute of Medical Sciences, Gannavaram', P5),
     ('MAHA', 'Maharaja Institute of Medical Sciences, Vizianagaram', P5),
     ('GEMS', 'Great Eastern Medical School and Hospital, Srikakulam', P5),
     ('NRVP', 'NRI Institute of Medical Sciences, Visakhapatnam', P5),
     ('GVPT', 'Gayatri Vidya Parishad Institute of Health Care and Medical Technology, Visakhapatnam', P5),
     ('NARN', 'Narayana Medical College, Nellore', P5), ('PESK', 'P.E.S. Institute of Medical Sciences and Research, Kuppam', P5)],
    [('SRMC', 'Santhiram Medical College, Nandyal', P5), ('VMCK', 'Viswabharathi Medical College, Kurnool', P5),
     ('APLC', 'Apollo Institute of Medical Sciences and Research, Chittoor', P5),
     ('BMCT', 'Sri Balaji Medical College Hospital and Research Institute, Renigunta, Tirupati', P5),
     ('FIMS', 'Fathima Institute of Medical Sciences, Kadapa', P4),
     ('NIMR', 'Nimra Institute of Medical Sciences, Vijayawada', P4)]]
QUOTA = {'S-1': 'Management Quota-(Cat-B)', 'S-1A': 'Management Quota-(Cat-B)', 'S-1B': 'Management Quota-(Cat-B)',
         'CA-SF': 'Management Quota-(Cat-B)', 'S-2': 'NRI Quota-(Cat-C)', 'CA-NRI': 'NRI Quota-(Cat-C)',
         'S-3': 'Institutional Quota-(Cat-C)'}
norm = lambda s: re.sub(r'\s+', '', s)


def val(s):
    s = clean(s)
    if s == '':
        return 0
    if not s.isdigit():
        raise SystemExit(f'not a number: {s!r}')
    return int(s)


doc = fitz.open(PDF)
if doc.page_count != 3:
    raise SystemExit('expected 3 pages')
rows, checks = [], {}
for pi, colleges in enumerate(PAGES):
    t = grids(doc[pi])[0]
    if 'Management Quota PG - Seat Matrix - 2026-27 (Including Enhanced/Newly Sanctioned Seats)' not in clean(t[0][0]):
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
