"""Kerala NEET PG 2026-27 seat matrix (Government Order G.O.(Ms)No.360/2026/H&FWD, 30-10-2026, "Admission to the
Medical Post Graduate Degree Courses in Government Medical Colleges & Self Financing Medical Educational Institutions
in the State for the academic session 2026-27 - Seat Matrix - approved") → standardised seat rows, bridged to
Kerala's 2025 CEE cut-offs.
Body "Kerala — State Counselling", authority_code `cee_kerala` (Commissioner for Entrance Examinations), section `state`.

The GO is 24 pages: p1-2 the order itself (no seats), then the annexure "PG MEDICAL - 2026", one table per
institute (heading "<CODE>:<name>", then Course / Total / one column per category, one line per course, a Total
line) and a Summary line at the end of each of three groups:
  p3-11  "Category-wise distribution of the State Quota Seats (excluding In-Service quota seats) in Government
          MEDICAL Colleges and RCC" — 10 government medical colleges + RCC Thiruvananthapuram + Malabar Cancer Centre;
          columns UR SC ST EZ BH MU LA BX KU EW, UR-PD SC-PD EZ-PD BH-PD MU-PD LA-PD EW-PD, UR-XS UR-DK.
  p12-15 "... the seats (excluding NRI quota seats) in Self Financing (Non Minority) MEDICAL Colleges" — 6 colleges,
          columns UR SC ST EZ BH MU LA BX KU EW.
  p16-24 "... the seats (excluding Minority/NRI quota seats) in Self Financing (Non Minority & Minority) MEDICAL
          Colleges" — 11 colleges, columns UR SC ST EZ BH MU LA BX KU (no EW column).
So the GO holds ONLY the state-merit seats: no All India Quota (MCC), no in-service, NRI or minority-community seats
(none of those are printed, so none are stored — there are no service-quota rows to keep out of the rankings).

Quotas (2025 Kerala CEE names, matched exactly with '$'):
  government group     → 'Government Quota'  (2025 'Government Quota$' — never 'Government Quota-Inservice')
  both self-financing  → 'Private Quota'     (2025 'Private Quota$' — the state-merit seats; 'Private Quota - Minority'
                                              and the NRI quotas are the excluded seats)
Categories as printed (UR, SC, ST, EZ Ezhava, BH Backward Hindu, MU Muslim, LA Latin Catholic & Anglo Indian,
BX Backward Christian, KU Kudumbi, EW EWS, <cat>-PD PwD, UR-XS ex-serviceman, UR-DK dependant of jawan killed in
action). Bridge: 2025 CEE codes are the same except UR = 'SM' (state merit) and PwD = one 'PD' list; every category
falls back to SM (the open rank — build() does not know 'SM' as general, so SM is always listed last):
  UR → SM · SC → SC, SM · … · X-PD → PD, X, SM · UR-XS / UR-DK → SM.
Courses: printed "M D Anaesthesia[AN]" etc. — the bracket code AND the name must both be in COURSES (unknown → stop).
"Diploma in Clinical Pathology[DP]" → 'Diploma in Pathology' (as 2025 Kerala), section diploma; everything else mdms.
No DNB seats are in the GO.
Colleges: the heading code AND printed name must both be in COLLEGES (unknown → stop) → the 2025 cut-off name, so the
codes are KL-<STANDARD-NAME> (the live 2025-based rankings use KL- codes).

Checks (every printed number): the three group headings and their page ranges, the column headings of every table,
each course line's categories = its Total, each institute's columns = its Total line, each group's columns = its
Summary line, each institute printed once, every number word on pages 3-24 lies inside a parsed table (nothing
outside find_tables()), and the output re-adds to the three Summary totals (no grand total is printed).
Supplementary orders: G.O.(Ms)No.361/2026/H&FWD (02-11-2026) approves "Newly Added Seats (Available from First Phase
Onward)" for Travancore Medical College, Kollam (TRM, self-financing Non Minority & Minority group, columns UR SC ST EZ
BH MU LA) — pass it with --add; its institute Total and Summary line are checked the same way.
Run with /usr/bin/python3 (PyMuPDF):
    kerala.py <go.pdf> <cutoffs2025.json> <out.json> [--add <go361.pdf>]"""
import re, sys, os, json, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

argv = sys.argv[1:]
ADD = []
while '--add' in argv:
    i = argv.index('--add'); ADD.append(argv[i + 1]); del argv[i:i + 2]
if len(argv) != 3:
    raise SystemExit(__doc__)
GO, CUTS, OUT = argv
key = lambda s: re.sub(r'[^a-z]', '', (s or '').lower())

COLLEGES = {  # GO institute code → (name exactly as printed, standard name = the 2025 Kerala CEE cut-off name)
    'ALP': ('Govt. Medical College, Alappuzha', 'T D Medical College, Alappuzha'),
    'CMC': ('Govt. Medical College, Ernakulam', 'Government Medical College, Ernakulam'),
    'KKM': ('Govt. Medical College, Kozhikode', 'Government Medical College, Kozhikode'),
    'KLM': ('Govt. Medical College, Parippally, Kollam', 'Government Medical College, Kollam'),
    'KNM': ('Govt. Medical College, Kannur', 'Government Medical College, Kannur'),
    'KTM': ('Govt. Medical College, Kottayam', 'Government Medical College, Kottayam'),
    'MCG': ('Malabar Cancer Centre, Thalassery', 'Malabar Cancer Centre, Thalassery, Kerala'),
    'MLP': ('Government Medical College,Malappuram', 'Government Medical College, Manjeri'),   # GMC Manjeri, Malappuram
    'PKM': ('Govt. Medical College, Palakkad', 'Government Medical College, Palakkad'),
    'RCC': ('Regional Cancer Centre, Thiruvananthapuram', 'Regional Cancer Centre, Thiruvananthapuram'),
    'TCM': ('Govt. Medical College, Thrissur', 'Government Medical College, Thrissur'),
    'TVM': ('Govt. Medical College, Thiruvananthapuram', 'Government Medical College, Thiruvananthapuram'),
    'DMM': ("Dr Moopen's Medical College & Hospital, Wayanad", 'Dr Moopens Medical College, Meppadi, Wayanad'),
    'GMC': ('Sree Gokulam Medical College & Research Foundation, Venjaramoodu.', 'Sree Gokulam Medical College Trust & Research Foundation, Trivandrum'),
    'KDM': ('P K Das Institute of Medical Sciences, Vaniyamkulam, Ottapalam, Palakkad.', 'P K Das Institute of Medical Sciences, Ottapalam'),
    'MMH': ('Malabar Medical College Hospital & Research Centre, Kozhikkode', 'Malabar Medical College Hospital, Kozhikkode'),
    'SIM': ('Sree Narayana Institute of Medical Sciences, Ernakulam.', 'Sree Narayana Institute of Medical Sciences, Ernakulam'),
    'SUC': ('SUT Academy of Medical Sciences, Vattappara, Thiruvananthapuram', 'SUT Accademy of Medical Sciences, Thiruvananthapuram'),
    'AAM': ('Al Azhar Medical college & Super speciality Hospital, Ezhalloor, Thodupuzha, Idukki.', 'Al Azhar Medical College, Thodupuzha'),
    'AMC': ('Amala Institute of Medical Sciences, Amala Nagar, Thrissur', 'Amala Institute of Medical Sciences, Thrissur'),
    'AZC': ('Azeezia Institute of Medical Sciences & Research, Meeyannoor, Kollam.', 'Azeezia Institute of Medical Science, Meyyannoor, Kollam'),
    'BCM': ('Believers Church Medical College Hospital, Kuttapuzha, Thiruvalla', 'Believers Church Medical College Hospital, Thiruvalla'),
    'EMC': ('MES Medical College, Perinthalmanna, Malappuram.', 'MES Medical College, Perinthalmanna, Malappuram'),
    'JMC': ('Jubilee Mission Medical College & Research Institute, Thrissur', 'Jubilee Mission Medical College, Thrisur'),
    'KCM': ('KMCT Medical College, Mukkom, Kozhikode.', 'KMCT Medical College, Kozhikode'),
    'MMC': ('Malankara Orthodox Syrian Church Medical College, Kolenchery, Ernakulam', 'Malankara Orthodox Syrian Church Medical College, Kolenchery'),
    'MZM': ('Mount Zion Medical College, Pathanamthitta', 'Mount Zion Medical College, Pathanamthitta'),
    'PMC': ('Pushpagiri Institute of Medical Science & Research Centre, Thiruvalla', 'Pushpagiri Institute of Medical Science, Thiruvalla'),
    'SMC': ('Dr. Somervell Memorial CSI Medical College, Karakonam, Thiruvananthapuram', 'Dr. Somervell Memorial CSI Medical College, Karakonam')}
COURSES = {  # (bracket code, printed name in lower-case letters) → approved course name
    ('AN', 'mdanaesthesia'): 'MD - Anaesthesiology', ('BI', 'mdbiochemistry'): 'MD - Biochemistry',
    ('CM', 'mdcommunitymedicine'): 'MD - Social & Preventive Medicine / Community Medicine',
    ('VL', 'mddermatologyvenereologyleprosy'): 'MD - Dermatology', ('EM', 'mdemergencymedicine'): 'MD - Emergency Medicine',
    ('FM', 'mdfamilymedicine'): 'MD - Family Medicine', ('FO', 'mdforensicmedicine'): 'MD - Forensic Medicine',
    ('GM', 'mdgeneralmedicine'): 'MD - General Medicine', ('MI', 'mdmicrobiology'): 'MD - Microbiology',
    ('PD', 'mdpaediatrics'): 'MD - Paediatrics', ('PT', 'mdpathology'): 'MD - Pathology',
    ('PH', 'mdpharmacology'): 'MD - Pharmacology', ('PM', 'mdphysicalmedicineandrehabilitation'): 'MD - Physical Medicine and Rehabilitation',
    ('PY', 'mdphysiology'): 'MD - Physiology', ('PS', 'mdpsychiatry'): 'MD - Psychiatry',
    ('RD', 'mdradiodiagnosis'): 'MD - Radio-Diagnosis', ('RT', 'mdradiotherapy'): 'MD - Radiotherapy / Radiation Oncology',
    ('TB', 'mdrespiratorymedicine'): 'MD - Respiratory Medicine',
    ('TM', 'mdtransfusionmedicine'): 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    ('GE', 'mdgeriatrics'): 'MD - Geriatrics', ('NM', 'mdnuclearmedicine'): 'MD - Nuclear Medicine',
    ('AT', 'msanatomy'): 'MD/MS - Anatomy', ('GS', 'msgeneralsurgery'): 'MS - General Surgery',
    ('OB', 'msobstetricsgynaecology'): 'MS - Obstetrics and Gynaecology', ('OP', 'msophthalmology'): 'MS - Ophthalmology',
    ('OR', 'msorthopaedics'): 'MS - Orthopaedics', ('ET', 'msotorhinolaryngology'): 'MS - ENT (Otorhinolaryngology)',
    ('DP', 'diplomainclinicalpathology'): 'Diploma in Pathology'}
ADD_GOS = {  # supplementary order → (must-read phrases, page (0-based), institute code, printed name, standard name, cats)
    'G.O.(Ms)No.361/2026/H&FWD': (('Travancore Medical College, Kollam', 'seat matrix for admission to Medical Post'), 2,
                                  'TRM', 'Travancore Medical College, Mylapore, Umayanalloor P O, Kollam.',
                                  'Travancore Medical College, Kollam', ['UR', 'SC', 'ST', 'EZ', 'BH', 'MU', 'LA'])}
BASE = ['UR', 'SC', 'ST', 'EZ', 'BH', 'MU', 'LA', 'BX', 'KU']
GROUPS = [  # (label, heading on the group's first page, pages (0-based), category columns, quota)
    ('Government', 'Category-wise distribution of the State Quota Seats (excluding In-Service quota seats) in Government '
                   'MEDICAL Colleges and RCC', range(2, 11),
     BASE + ['EW', 'UR-PD', 'SC-PD', 'EZ-PD', 'BH-PD', 'MU-PD', 'LA-PD', 'EW-PD', 'UR-XS', 'UR-DK'], 'Government Quota'),
    ('Self Financing (Non Minority)', 'Category-wise distribution of the seats (excluding NRI quota seats) in Self '
                                      'Financing (Non Minority) MEDICAL Colleges', range(11, 15), BASE + ['EW'], 'Private Quota'),
    ('Self Financing (Non Minority & Minority)', 'Category-wise distribution of the seats (excluding Minority/NRI quota '
                                                 'seats) in Self Financing (Non Minority & Minority) MEDICAL Colleges',
     range(15, 24), BASE, 'Private Quota')]


def val(s, label):
    s = clean(s)
    if s == '--':
        return 0
    if not s.isdigit():
        raise SystemExit(f'{label}: not a number: {s!r}')
    return int(s)


doc = fitz.open(GO)
p1 = clean(doc[0].get_text())
for must in ('G.O.(Ms)No.360/2026/H&FWD', '30-10- 2026', 'Seat Matrix - approved',
             'Medical Post Graduate Degree Courses in Government Medical Colleges & Self Financing Medical Educational Institutions'):
    if must not in p1:
        raise SystemExit(f'GO page 1 changed: {must!r} not found')
if len(doc) != 24:
    raise SystemExit(f'GO has {len(doc)} pages, expected 24')

rows, checks = [], {}
seen_codes = []
for label, heading, pages, cats, quota in GROUPS:
    head = ['Course', 'Total'] + cats
    first = clean(doc[pages[0]].get_text())
    if 'PG MEDICAL - 2026' not in first or heading not in first:
        raise SystemExit(f'{label}: group heading not on p{pages[0] + 1}')
    for p in range(2, 24):
        if p != pages[0] and heading in clean(doc[p].get_text()):
            raise SystemExit(f'{label}: heading repeated on p{p + 1}')
    group_sum, summary, college = [0] * (len(cats) + 1), None, None
    for p in pages:
        page = doc[p]
        tabs = page.find_tables().tables
        # every number / '--' printed on the page must lie inside a parsed table (the "2026" of the page title aside)
        for w in page.get_text('words'):
            if re.fullmatch(r'\d+|--', w[4]) and not (w[4] == '2026' and p == pages[0] and w[1] < tabs[0].bbox[1]):
                cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
                if not any(t.bbox[0] <= cx <= t.bbox[2] and t.bbox[1] <= cy <= t.bbox[3] for t in tabs):
                    raise SystemExit(f'p{p + 1}: number {w[4]!r} outside every table')
        g = grids(page)
        if not g:
            raise SystemExit(f'p{p + 1}: no table')
        for t in g:
            i = 0
            while i < len(t):
                r = [clean(c) if c is not None else None for c in t[i]]
                if r[0] == 'Summary' and all(c is None for c in r[1:]):
                    if college is not None or summary is not None:
                        raise SystemExit(f'p{p + 1}: Summary inside an institute table / printed twice')
                    if t[i + 1][1:] and [clean(c) for c in t[i + 1][1:]] != ['Total'] + cats or clean(t[i + 2][0]) != 'Total':
                        raise SystemExit(f'p{p + 1}: Summary headings changed: {t[i + 1]} / {t[i + 2]}')
                    summary = [val(c, f'{label} Summary') for c in t[i + 2][1:]]
                    i += 3
                    continue
                m = re.fullmatch(r'([A-Z]{3}):(.+)', r[0] or '')
                if m and all(c is None for c in r[1:]):
                    if college is not None:
                        raise SystemExit(f'p{p + 1}: {college[0]} has no Total line')
                    code, name = m.group(1), m.group(2)
                    if code not in COLLEGES or COLLEGES[code][0] != name:
                        raise SystemExit(f'p{p + 1}: unknown institute {code!r} {name!r}')
                    if code in seen_codes:
                        raise SystemExit(f'p{p + 1}: {code} printed twice')
                    seen_codes.append(code)
                    if [clean(c) for c in t[i + 1]] != head:
                        raise SystemExit(f'p{p + 1}: {code} column headings changed: {t[i + 1]}')
                    college, acc = (code, COLLEGES[code][1]), [0] * (len(cats) + 1)
                    i += 2
                    continue
                if college is None:
                    raise SystemExit(f'p{p + 1}: line outside an institute table: {r}')
                if len(r) != len(head):
                    raise SystemExit(f'p{p + 1}: {college[0]} line has {len(r)} cells: {r}')
                if r[0] == 'Total':
                    printed = [val(c, f'{college[0]} Total') for c in r[1:]]
                    if acc != printed:
                        raise SystemExit(f'{college[0]}: course lines add to {acc}, Total line {printed}')
                    checks[f'{label} {college[0]} Total'] = (acc[0], printed[0])
                    group_sum = [a + b for a, b in zip(group_sum, acc)]
                    college = None
                    i += 1
                    continue
                cm = re.fullmatch(r'(.+)\[([A-Z]{2})\]', r[0] or '')
                if not cm or (cm.group(2), key(cm.group(1))) not in COURSES:
                    raise SystemExit(f'p{p + 1}: {college[0]} unknown course {r[0]!r}')
                course = COURSES[(cm.group(2), key(cm.group(1)))]
                v = [val(c, f'{college[0]} {r[0]}') for c in r[1:]]
                if sum(v[1:]) != v[0] or v[0] == 0:
                    raise SystemExit(f'{college[0]} {r[0]}: categories {v[1:]} add to {sum(v[1:])}, Total {v[0]}')
                if any(x['college'] == college[1] and x['course'] == course for x in rows):
                    raise SystemExit(f'{college[0]}: {course} printed twice')
                acc = [a + b for a, b in zip(acc, v)]
                for cat, n in zip(cats, v[1:]):
                    if n:
                        rows.append({'college': college[1], 'course': course, 'quota': quota, 'seats': n, 'category': cat,
                                     'section': 'diploma' if course.startswith('Diploma') else 'mdms', 'group': label})
                i += 1
    if college is not None:
        raise SystemExit(f'{label}: {college[0]} has no Total line')
    if summary is None:
        raise SystemExit(f'{label}: no Summary line')
    for c, a, b in zip(['Total'] + cats, group_sum, summary):
        checks[f'{label} Summary {c}'] = (a, b)
    checks[f'{label} seats'] = (sum(x['seats'] for x in rows if x['group'] == label), summary[0])
if sorted(seen_codes) != sorted(COLLEGES):
    raise SystemExit(f'institutes in COLLEGES but not in the GO: {sorted(set(COLLEGES) - set(seen_codes))}')
checks['institutes'] = (len(seen_codes), len(COLLEGES))
summ = sum(checks[f'{g[0]} Summary Total'][1] for g in GROUPS)
checks['all seats = sum of the three Summary totals'] = (sum(x['seats'] for x in rows), summ)

# supplementary orders (newly added seats) — one institute table + a Summary line, every number checked
for path in ADD:
    d2 = fitz.open(path)
    t1 = clean(d2[0].get_text())
    go = next((g for g in ADD_GOS if g in t1), None)
    if not go:
        raise SystemExit(f'{path}: not a known supplementary GO')
    must, pg, code, printed_name, std, cats = ADD_GOS[go]
    if not all(m in clean(' '.join(x.get_text() for x in d2)) for m in must):
        raise SystemExit(f'{go}: wording changed')
    t = [[clean(c) if c is not None else None for c in r] for g in grids(d2[pg]) for r in g]
    if t[0][0] != f'{code}:{printed_name}' or t[1] != ['Course', 'Total'] + cats:
        raise SystemExit(f'{go}: table heading changed: {t[0][0]!r} / {t[1]}')
    acc, n0, i = [0] * (len(cats) + 1), len(rows), 2
    while t[i][0] != 'Total':
        cm = re.fullmatch(r'(.+)\[([A-Z]{2})\]', t[i][0] or '')
        if not cm or (cm.group(2), key(cm.group(1))) not in COURSES:
            raise SystemExit(f'{go}: unknown course {t[i][0]!r}')
        course = COURSES[(cm.group(2), key(cm.group(1)))]
        v = [val(c, f'{code} {t[i][0]}') for c in t[i][1:]]
        if sum(v[1:]) != v[0] or v[0] == 0:
            raise SystemExit(f'{go} {t[i][0]}: categories add to {sum(v[1:])}, Total {v[0]}')
        if any(x['college'] == std and x['course'] == course for x in rows):
            raise SystemExit(f'{go}: {course} at {std} already in the matrix')
        acc = [a + b for a, b in zip(acc, v)]
        for cat, n in zip(cats, v[1:]):
            if n:
                rows.append({'college': std, 'course': course, 'quota': 'Private Quota', 'seats': n, 'category': cat,
                             'section': 'diploma' if course.startswith('Diploma') else 'mdms'})
        i += 1
    printed = [val(c, f'{code} Total') for c in t[i][1:]]
    if acc != printed or t[i + 1][0] != 'Summary' or [val(c, 'Summary') for c in t[i + 3][1:]] != printed:
        raise SystemExit(f'{go}: course lines {acc} / Total {printed} / Summary disagree')
    checks[f'{go} {code} newly added seats'] = (sum(x['seats'] for x in rows[n0:]), printed[0])
for x in rows:
    x.pop('group', None)

FAMILY = {'Government Quota': ('Government Quota$',), 'Private Quota': ('Private Quota$',)}


def cat_match(x):
    c = x['category']
    if c in ('UR', 'UR-XS', 'UR-DK'):
        return ('SM',)
    if c.endswith('-PD'):
        b = c[:-3]
        return ('PD',) + ((b,) if b != 'UR' else ()) + ('SM',)
    return (c, 'SM')


cuts = load_cuts(CUTS, 'Kerala')
known = {c['institute'] for c in cuts}
missing = sorted({v[1] for v in COLLEGES.values()} - known)
if missing:
    raise SystemExit(f'college map points at names not in the 2025 cut-offs: {missing}')
out = build(rows, cuts, 'Kerala', 'KL', lambda q: FAMILY[q], cat_match)
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
print('2025 Kerala institutes not in the 2026 GO(s):', sorted(known - {v[1] for v in COLLEGES.values()} - {x['college'] for x in rows}))
