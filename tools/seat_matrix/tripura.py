"""Tripura PG Medical Round 1 seat matrix (DME Tripura, 04.11.2026) → standardised seat rows, one per college ×
course × category, bridged to Tripura's 2025 cut-offs. Run with /usr/bin/python3 (PyMuPDF):
    tripura.py <matrix.pdf> <cutoffs2025.json> <out.json>
Five institution tables (AGMC, TMC, IGM Hospital NBEMS diplomas, Modern Psychiatric Hospital DNB, LGBRIMH Tezpur),
columns UR / EWS / ST / SC / OBC-NCL / Total. Category cells are read by the header's column position (a blank
cell = 0, dashes = 0); the Total is the row's last filled cell. AGMC Community Medicine prints its UR seat as '01- WESM' — kept as 1 UR seat (the suffix is noted).
Checks: every row adds to its Total, every table to its TOTAL SEATS line, and the whole matrix to 77."""
import json, os, re, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report

PDF, CUTS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
# printed heading → (college as in the 2025 cut-offs / standard name, quota as in the 2025 cut-offs)
COLLEGES = {
    'AGARTALA GOVERNMENT MEDICAL COLLEGE & GBP HOSPITAL': ('Agartala Government Medical College, Agartala', 'State Quota'),
    'TRIPURA MEDICAL COLLEGE & DR. BRAM TEACHING HOSPITAL':
        ('Tripura Medical College and Dr. BRAM Teaching Hospital, Agartala', 'Open Quota'),
    'INDIRA GANDHI MEMORIAL HOSPITAL': ('Indira Gandhi Memorial Hospital, Agartala, Tripura', 'State Quota'),
    'MODERN PSYCHIATRIC HOSPITAL, NARSINGARH': ('Modern Psychiatric Hospital, Narsingarh, Tripura', 'State Quota'),
    'LOKOPRIYA GOPINATH BORDOLOI REGIONAL INSTITUTE OF MENTAL HEALTH (LGBRIMH), TEZPUR, ASSAM':
        ('Lokopriya Gopinath Bordoloi Regional Institute Of Medical Health, Tezpur', 'State Quota')}
COURSES = {  # printed subject → (approved course name, section)
    'Anesthesiology (MD)': ('MD - Anaesthesiology', 'mdms'), 'General Medicine (MD)': ('MD - General Medicine', 'mdms'),
    'Obst & Gynae (MS)': ('MS - Obstetrics and Gynaecology', 'mdms'), 'Ophthalmology (MS)': ('MS - Ophthalmology', 'mdms'),
    'Orthopedics (MS)': ('MS - Orthopaedics', 'mdms'), 'Otorhinolaryngology (MS)': ('MS - ENT (Otorhinolaryngology)', 'mdms'),
    'Pediatrics (MD)': ('MD - Paediatrics', 'mdms'), 'Psychiatry (MD)': ('MD - Psychiatry', 'mdms'),
    'Radio Diagnosis (MD)': ('MD - Radio-Diagnosis', 'mdms'), 'General Surgery (MS)': ('MS - General Surgery', 'mdms'),
    'Community Medicine (MD)': ('MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    'Anatomy (MD)': ('MD/MS - Anatomy', 'mdms'), 'Physiology (MD)': ('MD - Physiology', 'mdms'),
    'Biochemistry (MD)': ('MD - Biochemistry', 'mdms'), 'Forensic Medicine (MD)': ('MD - Forensic Medicine', 'mdms'),
    'Microbiology (MD)': ('MD - Microbiology', 'mdms'), 'Pathology (MD)': ('MD - Pathology', 'mdms'),
    'Pharmacology (MD)': ('MD - Pharmacology', 'mdms'), 'Respiratory Medicine (MD)': ('MD - Respiratory Medicine', 'mdms'),
    'Radiotherapy (MD)': ('MD - Radiotherapy / Radiation Oncology', 'mdms'),
    'Family Medicine, D. Fam, NBEMS': ('Diploma in Family Medicine', 'diploma'),
    'Obstetrics and Gynecology, DGO, NBEMS': ('Diploma in Obstetrics and Gynaecology', 'diploma'),
    'Pediatrics, DCH, NBEMS': ('Diploma in Child Health / Paediatrics', 'diploma'),
    'DNB, Psychiatry (Post MBBS), NBEMS': ('DNB - Psychiatry (Post-MBBS)', 'dnb')}
CATS = ['UR', 'EWS', 'ST', 'SC', 'OBC']
NOTES = {'01- WESM': 1}          # AGMC Community Medicine UR cell


def num(s):
    s = clean(s).replace(' ', '')
    if s in NOTES or s.replace(' ', '') in {k.replace(' ', '') for k in NOTES}:
        return 1
    if not s or set(s) <= {'-'}:
        return 0
    if not s.isdigit():
        raise SystemExit(f'unexpected cell {s!r}')
    return int(s)


rows, checks, college, cols = [], {}, None, None
for page in fitz.open(PDF):
    for t in page.find_tables().tables:
        for r in t.extract():
            r = [clean((c or '').replace('\n', ' ')) for c in r]
            ne = [c for c in r if c]
            if len(ne) == 1 and ne[0] in COLLEGES:
                college, cols = ne[0], None
                continue
            if ne and ne[0] == 'SL. No':
                idx = {}
                for i, c in enumerate(r):
                    k = 'OBC' if c.startswith('OBC') else ('TOT' if c.startswith('Total') else c)
                    if k in CATS + ['TOT', 'Subject']:
                        idx[k] = i
                if sorted(idx) != sorted(CATS + ['TOT', 'Subject']):
                    raise SystemExit(f'header changed: {r}')
                cols = idx
                continue
            if 'TOTAL SEATS' in ne:
                vals = ne[ne.index('TOTAL SEATS') + 1:]
                if len(vals) != 6:
                    raise SystemExit(f'total line {ne}')
                got = [sum(x['seats'] for x in rows if x['p_college'] == college and x['category'] == c) for c in CATS]
                checks[college[:30] + ' total'] = (sum(got), num(vals[5]))
                for c, g, v in zip(CATS, got, vals):
                    checks[college[:30] + ' ' + c] = (g, num(v))
                continue
            if not ne or not re.fullmatch(r'\d+\.', ne[0]) or cols is None or college is None:
                continue
            subj = r[cols['Subject']]
            if subj not in COURSES:
                raise SystemExit(f'unknown subject {subj!r}')
            course, section = COURSES[subj]
            name, quota = COLLEGES[college]
            s = 0
            for c in CATS:
                n = num(r[cols[c]])
                s += n
                if n:
                    rows.append({'college': name, 'course': course, 'quota': quota, 'seats': n, 'section': section,
                                 'category': c, 'p_college': college})
            tot = ne[-1]                     # the Total cell sits a column left of its header on page 2
            if s != num(tot):
                raise SystemExit(f'{college} / {subj}: categories add to {s}, total {tot}')
checks['MATRIX'] = (sum(x['seats'] for x in rows), 77)
if {x['p_college'] for x in rows} != set(COLLEGES):
    raise SystemExit('an institution table was not read')
for x in rows:
    del x['p_college']

cuts = load_cuts(CUTS, 'Tripura')
cat = lambda x: ('OBC-NCL', 'OBC') if x['category'] == 'OBC' else (x['category'],)
out = build(rows, cuts, 'Tripura', 'TR', lambda q: (q,), cat)
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
