"""Telangana KNRUHS — MEDICAL PG DEGREE/DIPLOMA ADMISSIONS UNDER MANAGEMENT QUOTA FOR THE AY 2026-27 — SEAT MATRIX FOR
FIRST PHASE OF COUNSELLING (18.11.2026, 6 pages, text layer). Stored as its OWN body ("Telangana — Management Quota —
State Counselling", authority knruhs): the Competent Authority body ("Telangana — State Counselling") holds only
convenor seats (State / In-service), no management / NRI / institutional seats.

Layout: each page = 4 colleges (code + "2026-27" over 4 columns MQ1 L | MQ1 UR | MQ2 | MQ3) × 26 course lines; a
blank cell = 0. Mapping to the 2025 KNRUHS cut-off quotas / categories (exact wording):
  MQ1 L  → Management Quota-(Cat-B), MQ1-Local     MQ1 UR → Management Quota-(Cat-B), MQ1-UR
  MQ2    → NRI Quota-(Cat-C), MQ2-UR                MQ3    → Institutional Quota-(Cat-C), MQ3-UR
  Muslim-minority colleges (Deccan, Shadan, Dr. VRK Women's, Ayaan) → MQ1-MSM / MQ1-MSM-UR / MQ2-MSM-UR / MQ3-MSM-UR
  (as in 2025). Bridge: same category, then the non-MSM / UR variant.
The PDF prints NO totals, so the checks are: titles, the college / column headings on every page, every course name
known, every cell blank or a whole number, and every number printed on a page (apart from '2026-27' and the date)
sits in a parsed cell. Unknown college code / course → SystemExit.
    /usr/bin/python3 tools/seat_matrix/telangana_mq.py <mq_phase1.pdf> <cutoffs2025.json> <out.json>
"""
import collections, json, os, re, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

if len(sys.argv) != 4:
    raise SystemExit(__doc__)
PDF, CUTS, OUT = sys.argv[1:4]

COLLEGES = {  # KNRUHS 4-letter code → (2025 KNRUHS cut-off name, Muslim minority?)
    'APLO': ('Apollo Institute of Medical Sciences and Research, Hyderabad', False),
    'BASK': ('Bhaskar Medical College, Moinabad, Ranga Reddy, Hyderabad', False),
    'CARK': ('Chalmeda Anand Rao Insttitute of Medical Sciences, Karimnagar', False),
    'DPMR': ('Dr. Patnam Mahender Reddy Institute of Medical Sciences, Chevella', False),
    'KMHD': ('Kamineni Academy of Medical Sciences & Research Center, Hyderabad', False),
    'KMNI': ('Kamineni Institute of Medical Sciences, Narketpally', False),
    'MAMS': ('Mamata Academy of Medical Sciences, Bachupally', False),
    'MAHE': ('Maheshwara Medical College, Patancheru, Medak', False),
    'MMTA': ('Mamata Medical College, Khammam', False),
    'MNRS': ('MNR Medical College & Hospital, Sangareddy', False),
    'MEDI': ('Mediciti Institute of Medical Sciences, Ghanpur', False),
    'MHVR': ('Mahavir Institute of Medical Sciences, Vikarabad', False),
    'PRTM': ('Prathima Institute of Medical Sciences, Karimnagar', False),
    'RVMC': ('R.V.M. Institute of Medical Sciences and Research Centre, Siddipet', False),
    'SVSM': ('S V S Medical College, Mahabubnagar', False),
    'SURB': ('Surabhi Institute of Medical Sciences, Siddipet', False),
    'DCMS': ('Deccan College of Medical Sciences, Hyderabad', True),
    'TRRM': ('TRR Institute of Medical Sciences, Patancheru', False),
    'CMRM': ('CMR Institute of Medical Sciences, Kandalkoya, Medchal', False),
    'SHDN': ('Shadan Institute of Medical Sciences, Peerancheru', True),
    'VRKW': ('Dr. VRK Womens Medical College, Aziznagar', True),
    'AYAAN': ('Ayaan Institute of Medical Sciences, Kanaka Mamidi', True),
    'NEELIMA': ('Neelima Institute of Medical Sciences, Medchal', False)}
COURSES = {
    'MD (General Medicine)': 'MD - General Medicine', 'MD (Paediatrics)': 'MD - Paediatrics',
    'MD (Anesthesia)': 'MD - Anaesthesiology', 'MD (TB and chest diseases)': 'MD - Respiratory Medicine',
    'MD (Dermatology, Venereology & Leprosy)': 'MD - Dermatology', 'MD (Radio Diagnosis.)': 'MD - Radio-Diagnosis',
    'MD (Psychiatry)': 'MD - Psychiatry', 'MD (Radio therapy) *': 'MD - Radiotherapy / Radiation Oncology',
    'MD (Emergency Medicine)': 'MD - Emergency Medicine',
    'MD (Transfusion Medicine)': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'MD (Hospital Administration)': 'MD - Hospital Administration', 'MD (Nuclear Medicine)': 'MD - Nuclear Medicine',
    'MS (General Surgery)': 'MS - General Surgery', 'MS (Orthopedics)': 'MS - Orthopaedics',
    'MS (Opthalmology)': 'MS - Ophthalmology', 'MS (Oto rhino laryngeology)': 'MS - ENT (Otorhinolaryngology)',
    'MS (Obstetrics and Gynaecology)': 'MS - Obstetrics and Gynaecology', 'MD (Anatomy)': 'MD/MS - Anatomy',
    'MD (Physiology)': 'MD - Physiology', 'MD (Biochemistry)': 'MD - Biochemistry', 'MD (Pathology)': 'MD - Pathology',
    'MD (Microbiology)': 'MD - Microbiology', 'MD (Pharmacology)': 'MD - Pharmacology',
    'MD (Forensic Medicine)': 'MD - Forensic Medicine',
    'MD (Community Medicine)': 'MD - Social & Preventive Medicine / Community Medicine',
    'DPM': 'Diploma in Psychological Medicine'}
COLS = ['MQ1 L', 'MQ1 UR', 'MQ2', 'MQ3']
QUOTA = {'MQ1 L': 'Management Quota-(Cat-B)', 'MQ1 UR': 'Management Quota-(Cat-B)', 'MQ2': 'NRI Quota-(Cat-C)',
         'MQ3': 'Institutional Quota-(Cat-C)'}
CAT = {False: {'MQ1 L': 'MQ1-Local', 'MQ1 UR': 'MQ1-UR', 'MQ2': 'MQ2-UR', 'MQ3': 'MQ3-UR'},
       True: {'MQ1 L': 'MQ1-MSM', 'MQ1 UR': 'MQ1-MSM-UR', 'MQ2': 'MQ2-MSM-UR', 'MQ3': 'MQ3-MSM-UR'}}

doc = fitz.open(PDF)
alltext = clean(' '.join(p.get_text() for p in doc))
for t in ('KALOJI NARAYANA RAO UNIVERSITY OF HEALTH SCIENCES, TELANGANA', 'ADMISSIONS UNDER MANAGEMENT QUOTA FOR THE AY 2026-27',
          'SEAT MATRIX FOR FIRST PHASE OF COUNSELLING'):
    if t not in alltext:
        raise SystemExit(f'title {t!r} not found')
rows, seen, checks, per_col = [], [], {}, collections.Counter()
for pno, page in enumerate(doc, 1):
    g = grids(page)
    if len(g) != 1:
        raise SystemExit(f'p{pno}: {len(g)} tables')
    t = g[0]
    top = [clean(x) if x is not None else None for x in t[0]]
    codes = [re.sub(r'\s*2026-\s*27$', '', x) for x in top[1::4]]
    if top[0] != '' or any(top[i] is not None for i in range(1, len(top)) if (i - 1) % 4) or \
            any(not re.search(r'2026-\s*27$', x or '') for x in top[1::4]):
        raise SystemExit(f'p{pno}: college heading row changed {top}')
    if [clean(x) for x in t[1]] != ['Course'] + COLS * len(codes):
        raise SystemExit(f'p{pno}: column headings changed {t[1]}')
    for c in codes:
        if c not in COLLEGES:
            raise SystemExit(f'p{pno}: unknown college code {c!r}')
        seen.append(c)
    cells_read, courses_here = 0, []
    for r in t[2:]:
        cname = clean(r[0])
        if cname not in COURSES:
            raise SystemExit(f'p{pno}: unknown course {cname!r}')
        courses_here.append(cname)
        for j, raw in enumerate(r[1:]):
            v = clean(raw)
            if v == '':
                continue
            if not v.isdigit():
                raise SystemExit(f'p{pno}: {cname} cell {j}: not a number {v!r}')
            cells_read += 1
            n = int(v)
            if not n:
                continue
            code, col = codes[j // 4], COLS[j % 4]
            name, msm = COLLEGES[code]
            per_col[col] += n
            rows.append({'college': name, 'course': COURSES[cname], 'quota': QUOTA[col], 'category': CAT[msm][col],
                         'seats': n, 'section': 'diploma' if COURSES[cname].startswith('Diploma') else 'mdms',
                         'institute_type': 'Private Institute'})
    if courses_here != list(COURSES):
        raise SystemExit(f'p{pno}: course lines changed {courses_here}')
    # every number on the page (apart from 2026-27 and the date) is a parsed cell
    txt = re.sub(r'2026-\s*27|18\.11\.2026', ' ', page.get_text())
    printed = len(re.findall(r'(?<![\w.])\d+(?![\w.])', txt))
    checks[f'p{pno} numbers printed = cells read'] = (cells_read, printed)
if len(set(seen)) != len(seen):
    raise SystemExit(f'college printed twice: {seen}')
checks['colleges'] = (len(seen), len(COLLEGES))

cuts = load_cuts(CUTS, 'Telangana')
FAMILY = {q: (q + '$',) for q in set(QUOTA.values())}


def cat_match(x):
    c = x['category']
    base = c.replace('-MSM', '')
    return tuple(dict.fromkeys([c, c + '-UR' if not c.endswith('UR') else c, base, base.split('-')[0] + '-UR',
                                base.split('-')[0]]))


out = build(rows, cuts, 'Telangana', 'TS', lambda q: FAMILY[q], cat_match, default_type='Private Institute')
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by column', dict(per_col))
