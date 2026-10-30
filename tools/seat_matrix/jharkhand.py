"""Jharkhand NEET PG 2026 institution-wise / course-wise seat matrix of the State Quota (Health, Medical Education
& Family Welfare Dept. letters 615 (9) of 15.10.2026 and 616 (9) of 16.10.2026) → standardised seat rows, bridged
to Jharkhand's 2025 cut-offs. One table: per institute, per course "50% State Quota Seats" and "In Service", with
a Total line under each institute (no categories, no grand total printed). Checks: every institute's Total line,
and the whole matrix = 122 State Quota + 7 In-service. Run with /usr/bin/python3 (PyMuPDF):
  jharkhand.py <jh.pdf> <cutoffs2025.json> <out.json>"""
import sys, os, json
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

PDF, CUTS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
COLLEGES = {  # PDF institute → standard institute name (2025 cut-offs where it exists)
    'Rajendra Institute of Medical Sciences, Ranchi': 'Rajendra Institute of Medical Sciences, Ranchi',
    'Mahatma Gandhi Memorial Medical College, Jamshedpur': 'Mahatma Gandhi Memorial Medical College, Jamshedpur',
    'SNMMCH Dhanbad': 'Shaheed Nirmal Mahto Medical College & Hospital, Dhanbad',
    'Sadar Hospital, Ranchi': 'Sadar Hospital, Ranchi',                                                     # new
    'RINPAS, Kanke, Ranchi': 'Ranchi Institute of Neuro-Psychiatry and Allied Sciences, Kanke, Ranchi'}  # new
COURSES = {  # PDF course → (approved course name, section)
    'M.D. (General Medicine)': ('MD - General Medicine', 'mdms'), 'M.D. (Paediatrics)': ('MD - Paediatrics', 'mdms'),
    'M.S. (Orthopedics)': ('MS - Orthopaedics', 'mdms'), 'M.S. (General Surgery)': ('MS - General Surgery', 'mdms'),
    'M.D. (Obs. & Gynae.)': ('MS - Obstetrics and Gynaecology', 'mdms'),
    'M.D./ M.S. (Obs. & Gynae.)': ('MS - Obstetrics and Gynaecology', 'mdms'),
    'M.S. (Ophthalmology)': ('MS - Ophthalmology', 'mdms'), 'M.S. (ENT)': ('MS - ENT (Otorhinolaryngology)', 'mdms'),
    'M.S. (Otorhinolaryngology)': ('MS - ENT (Otorhinolaryngology)', 'mdms'),
    'M.D. (Derm., Ven. & Leprosy)': ('MD - Dermatology', 'mdms'), 'M.D. (Anesthesiology)': ('MD - Anaesthesiology', 'mdms'),
    'M.D. (Radio-Diagnosis)': ('MD - Radio-Diagnosis', 'mdms'),
    'M.D. (Community Medicine)': ('MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    'M.D./ M.S. (Anatomy)': ('MD/MS - Anatomy', 'mdms'), 'M.D. (Physiology)': ('MD - Physiology', 'mdms'),
    'M.D. (Pathology)': ('MD - Pathology', 'mdms'), 'M.D. (Microbiology)': ('MD - Microbiology', 'mdms'),
    'M.D. (Pharmacology)': ('MD - Pharmacology', 'mdms'), 'M.D. (Biochemistry)': ('MD - Biochemistry', 'mdms'),
    'M.D. (Forensic Medicine)': ('MD - Forensic Medicine', 'mdms'),
    'Phychiatry': ('MD - Psychiatry', 'mdms'),          # RINPAS — printed without "M.D." (and misspelt)
    'D.G.O.': ('Diploma in Obstetrics and Gynaecology', 'diploma'),
    'D.C.H.': ('Diploma in Child Health / Paediatrics', 'diploma'),
    'D.M.R.D.': ('Diploma in Radio Diagnosis', 'diploma'),
    'Post M.B.B.S DNB (Obs. & Gynae.)': ('DNB - Obstetrics and Gynaecology (Post-MBBS)', 'dnb')}
EXPECTED = {'State Quota': 122, 'In-service Quota': 7}   # the notice: 122 State Quota seats + 7 in-service


def val(s):
    s = clean(s)
    if not s.isdigit():
        raise SystemExit(f'not a number: {s!r}')
    return int(s)


doc = fitz.open(PDF)
if len(doc) != 1:
    raise SystemExit(f'expected 1 page, got {len(doc)}')
t = grids(doc[0])[0]
if 'Seat Matrix of State Quota PG Medical' not in clean(t[0][0]):
    raise SystemExit(f'title changed: {t[0][0]!r}')
if [clean(x) for x in t[1]] != ['Sl. No.', 'Name of the Institute / College', 'Sl. No.', 'Name of the Course',
                                 '50% State Quota Seats', 'In Service']:
    raise SystemExit(f'column headings changed: {t[1]}')
rows, checks, college, part = [], {}, None, None
for r in t[2:]:
    if clean(r[1]):
        name = clean(r[1])
        if name not in COLLEGES:
            raise SystemExit(f'unknown institute {name!r}')
        college, part = COLLEGES[name], {'State Quota': 0, 'In-service Quota': 0}
    if clean(r[3]) == 'Total':
        for k, i in (('State Quota', 4), ('In-service Quota', 5)):
            checks[f'{college} | {k}'] = (part[k], val(r[i]))
        continue
    if not clean(r[2]).isdigit():
        raise SystemExit(f'unexpected row {r}')
    raw = clean(r[3])
    if raw not in COURSES:
        raise SystemExit(f'unknown course {raw!r}')
    course, section = COURSES[raw]
    for quota, i in (('State Quota', 4), ('In-service Quota', 5)):
        n = val(r[i])
        part[quota] += n
        if n:
            rows.append({'college': college, 'course': course, 'quota': quota, 'seats': n, 'section': section,
                         'category': '', 'institute_type': 'Government Institute'})
for k, n in EXPECTED.items():
    checks[f'all institutes | {k} (notice: 122 + 7)'] = (sum(x['seats'] for x in rows if x['quota'] == k), n)

# 2025: 'Government Quota' is a prefix of 'Government Quota-Inservice' → '$' = exact match
FAMILY = {'State Quota': ('Government Quota$',), 'In-service Quota': ('Government Quota-Inservice',)}
cuts = load_cuts(CUTS, 'Jharkhand')
out = build(rows, cuts, 'Jharkhand', 'JH', lambda q: FAMILY[q])     # no categories in the PDF → the UR rank
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})