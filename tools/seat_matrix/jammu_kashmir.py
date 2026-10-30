"""Jammu & Kashmir NEET PG 2026 Round 1 seat matrix (BOPEE, "OPERATIVE V 1.0", 28.10.2026) → standardised seat
rows, bridged to J&K's 2025 cut-offs. Two pages, same layout:
  p1 — MD/MS, p2 — PG Diploma (+ the category table). Government colleges (GMC Jammu / Kathua / Rajouri /
  Srinagar, SKIMS, GMC Anantnag / Baramulla): per course TOTAL, OM, "CAT. & UT LADAKH" (all reserved
  categories together — the PDF does not split them per college). ASCOMS Jammu (private): Total, Govt. seats
  OM (G), Management seats OM (M), HM (Hindu Minority), NRI.
Checks: every college row (TOTAL = OM + CAT; ASCOMS Total = OM(G)+OM(M)+HM+NRI), every column against the
printed Total row, and the state category table (OM / reserved split of all government seats, its own total,
and the PG Diploma category column). Run with /usr/bin/python3 (PyMuPDF):
  jammu_kashmir.py <bopee.pdf> <cutoffs2025.json> <out.json>"""
import re, sys, os, json, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

PDF, CUTS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
COLLEGES = {  # PDF heading → standard institute name (2025 cut-offs)
    'GMC-JAMMU': 'Government Medical College, Jammu', 'GMC-KATHUA': 'Government Medical College, Kathua',
    'GMC-RAJOURI': 'Government Medical College, Rajouri', 'GMC-SRINAGAR': 'Government Medical College, Srinagar',
    'SKIMS-SRINAGAR': 'Sher-I-Kashmir Institute of Medical Sciences, Srinagar',
    'GMC-ANANTNAG': 'Government Medical College, Anantnag', 'GMC-BARAMULLA': 'Government Medical College, Baramulla'}
ASCOMS = 'Acharya Shri Chander College of Medical Sciences, Jammu'
COURSES = {  # PDF discipline → approved course name
    'MD/MS Anatomy': 'MD/MS - Anatomy', 'MD Anaesthesiology': 'MD - Anaesthesiology',
    'MD Dermatology, Venereology & Leprosy': 'MD - Dermatology', 'MS ENT': 'MS - ENT (Otorhinolaryngology)',
    'MD Hospital Administration': 'MD - Hospital Administration', 'MD General Medicine': 'MD - General Medicine',
    'MD Microbiology': 'MD - Microbiology', 'MD/MS Obstetrtics & Gynaecology': 'MS - Obstetrics and Gynaecology',
    'MD/MS Ophthalmology': 'MS - Ophthalmology', 'MS Orthopaedics': 'MS - Orthopaedics',
    'MD Social & Preventive Medicine/Community Medicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'MD Pathology': 'MD - Pathology', 'MD Pediatrics': 'MD - Paediatrics', 'MD Pharmacology': 'MD - Pharmacology',
    'MD Physiology': 'MD - Physiology', 'MD Psychiatry': 'MD - Psychiatry',
    'MD Radio Diagnosis/Radiology': 'MD - Radio-Diagnosis', 'MD Radiation Oncology': 'MD - Radiotherapy / Radiation Oncology',
    'MS General Surgery': 'MS - General Surgery',
    'MD Immuno Haematology & Blood Transfusion': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'MD Respiratory Medicine/Pulmonary Medicine': 'MD - Respiratory Medicine', 'MD Biochemistry': 'MD - Biochemistry',
    'PG DIPLOMA Ophthalmology': 'Diploma in Ophthalmology', 'PG DIPLOMA Dermatology': 'Diploma in Dermatology',
    'PG DIPLOMA Immuno Haematology & Blood Transfusion': 'Diploma in Immuno-Haematology and Blood Transfusion'}
RESERVED = 'Reserved (CAT & UT Ladakh)'   # the PDF's "CAT. & UT LADAKH" column: all reserved categories together
CATS = ['OM', 'EWS', 'SC', 'ST-I', 'ST-II', 'RBA', 'ALC/IB', 'OBC', 'STK/STL']


def val(s):
    s = clean(s)
    if s == '':
        return 0
    if not s.isdigit():
        raise SystemExit(f'not a number: {s!r}')
    return int(s)


doc = fitz.open(PDF)
if len(doc) != 2:
    raise SystemExit(f'expected 2 pages, got {len(doc)}')
rows, checks = [], {}
gov_om = gov_res = 0
dip_om = dip_res = 0
cat_table = None
for p, (section, label) in enumerate((('mdms', 'MD/MS'), ('diploma', 'PG Diploma'))):
    g = grids(doc[p])
    t = g[0]
    head = next(r for r in t if r[2] and clean(r[2]) in COLLEGES)
    names = [clean(head[i]) for i in range(2, 23, 3)]
    if names != list(COLLEGES) or 'Payment Seats' not in clean(head[23]):
        raise SystemExit(f'{label}: college headings changed: {head}')
    sub = next(r for r in t if clean(r[0]) == 'S.No.')
    if [clean(x) for x in sub[2:5]] != ['TOTAL', 'OM', 'CAT. & UT LADAKH'] or \
            [clean(x) for x in sub[23:28]] != ['ASCOMS-J (G+Mgt. +HM+NRI)', 'OM (G)', 'OM (M)', 'HM', 'NRI']:
        raise SystemExit(f'{label}: column headings changed: {sub}')
    sums, printed = collections.Counter(), None
    for r in t:
        lead = clean(r[0]) or clean(r[1])
        if lead.startswith('Total'):
            printed = [val(x) for x in r[2:28]]
            break                          # the NOTE lines below are numbered too
        if not clean(r[0]).isdigit():
            continue
        course = COURSES.get(clean(r[1]))
        if not course:
            raise SystemExit(f'unknown discipline {r[1]!r}')
        v = [val(x) for x in r[2:28]]
        for i, x in enumerate(v):
            sums[i] += x
        for ci, name in enumerate(COLLEGES):
            tot, om, res = v[ci * 3:ci * 3 + 3]
            if om + res != tot:
                raise SystemExit(f'{label} {name} {course}: OM {om} + CAT {res} ≠ TOTAL {tot}')
            for cat, n in (('OM', om), (RESERVED, res)):
                if n:
                    rows.append({'college': COLLEGES[name], 'course': course, 'quota': 'Government Quota', 'seats': n,
                                 'section': section, 'category': cat})
            if section == 'mdms':
                gov_om += om; gov_res += res
            else:
                dip_om += om; dip_res += res
        tot, og, om_m, hm, nri = v[21:26]
        if og + om_m + hm + nri != tot:
            raise SystemExit(f'{label} ASCOMS {course}: {og}+{om_m}+{hm}+{nri} ≠ Total {tot}')
        for quota, cat, n in (('Government Quota', 'OM', og), ('Management Quota', 'OM', om_m),
                              ('Hindu Minority Quota', '', hm), ('NRI Quota', '', nri)):
            if n:
                rows.append({'college': ASCOMS, 'course': course, 'quota': quota, 'seats': n, 'section': section,
                             'category': cat, 'institute_type': 'Private Institute'})
    if printed is None:
        raise SystemExit(f'{label}: no Total row')
    for ci, name in enumerate(COLLEGES):
        for k, part in enumerate(('TOTAL', 'OM', 'CAT')):
            if printed[ci * 3 + k] or sums[ci * 3 + k]:
                checks[f'{label} | {name} {part}'] = (sums[ci * 3 + k], printed[ci * 3 + k])
    for k, part in enumerate(('Total', 'OM (G)', 'OM (M)', 'HM', 'NRI')):
        if printed[21 + k] or sums[21 + k]:
            checks[f'{label} | ASCOMS {part}'] = (sums[21 + k], printed[21 + k])
    if p == 1:
        cat_table = g[1]

# state category table (page 2): left = MD/MS + PG Diploma government seats, right = PG Diploma only
hdr = [clean(x) for x in cat_table[0]]
if not hdr[0].startswith('CATEGORY') or hdr[9] != 'PG DIPLOMA':
    raise SystemExit(f'category table headings changed: {hdr}')
left, right = {}, {}
for r in cat_table[1:]:
    c = clean(r[0])
    if c.startswith('TOTAL'):
        left_total, right_total = val(r[1]), val(r[10])
        continue
    if c not in CATS or clean(r[9]) != c:
        raise SystemExit(f'category table row changed: {r}')
    left[c], right[c] = val(r[1]), val(r[10])
checks['category table | all categories add to TOTAL J&K & LADAKH'] = (sum(left.values()), left_total)
checks['category table | OM = government OM seats (MD/MS + diploma)'] = (gov_om + dip_om, left['OM'])
checks['category table | reserved = government CAT. & UT LADAKH seats'] = (gov_res + dip_res, left_total - left['OM'])
checks['category table | PG Diploma total'] = (dip_om + dip_res, right_total)
checks['category table | PG Diploma OM'] = (dip_om, right['OM'])
# the only reserved PG Diploma seat takes the one reserved category the diploma column names (RBA)
dip_cats = [c for c in CATS if c != 'OM' and right[c]]
if dip_res == 1 and len(dip_cats) == 1 and right[dip_cats[0]] == 1:
    for x in rows:
        if x['section'] == 'diploma' and x['category'] == RESERVED:
            x['category'] = dip_cats[0]

FAMILY = {'Government Quota': ('Government Quota$',), 'Management Quota': ('Management Quota$',),
          'Hindu Minority Quota': ('Hindu Minority Quota$',), 'NRI Quota': ('NRI Quota$',)}


def cat_match(x):
    if x['quota'] == 'Hindu Minority Quota':
        return ('HM',)
    if x['quota'] == 'NRI Quota':
        return ('NRI',)
    if x['category'] == RESERVED:      # categories not split per college → the open (OM) rank
        return ('OM',)
    return (x['category'], 'OM')


cuts = load_cuts(CUTS, 'Jammu and Kashmir')
out = build(rows, cuts, 'Jammu and Kashmir', 'JK', lambda q: FAMILY[q], cat_match)
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
print('category table (govt MD/MS + diploma):', left, '| PG Diploma:', {k: v for k, v in right.items() if v})