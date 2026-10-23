"""Madhya Pradesh NEET PG 2026-27 First Round seat distribution (DME MP, 21.10.2026) → standardised seat rows,
bridged to MP's 2025 cut-offs. Three PDFs:
  govt     — Government & Autonomous colleges: Open / PWD / 30% In-service Open / In-service PWD (4 pages)
  private  — Private colleges: overview total (p1, used only as a check), NRI (p2), then by category:
             In-service Institutional Open / PWD, Open Institutional / PWD, Non-Institutional Open / PWD (p3-8)
  district — District Hospital Bhopal Post-MBBS DNB (p1) + District Hospital Post-MBBS Diploma (p2)
Every page is checked: each college row adds up to its printed total, every column adds up to the printed
"Total" row, and the Grand Total columns equal the sum of the colleges.
Run with /usr/bin/python3 (PyMuPDF):  madhya_pradesh.py <govt.pdf> <private.pdf> <district.pdf> <cutoffs2025.json> <out.json>"""
import re, sys, os, json, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

GOVT, PRIV, DIST, CUTS, OUT = sys.argv[1:6]
COLLEGES = {  # PDF column heading → standard institute name (2025 cut-offs)
    'BHOPAL': 'Gandhi Medical College, Bhopal', 'INDORE': 'Mahatma Gandhi Memorial Medical College, Indore',
    'GWALIOR': 'Gajra Raja Medical College, Gwalior', 'JABALPUR': 'Netaji Subhash Chandra Bose Medical College, Jabalpur',
    'REWA': 'Shyam Shah Medical College, Rewa', 'SAGAR': 'Bundelkhand Medical College, Sagar',
    'RATLAM MC': 'Government Medical College, Ratlam', 'SATNA MC': 'Government Medical College, Satna',
    'DATIA': 'Government Medical College, Datia', 'VIDISHA MC': 'Atal Bihari Vajpayee Government Medical College, Vidisha',
    'GWALIOR MANSIK AROGYA SALA': 'Gwalior Mansik Arogyashala, Gwalior',
    'KHANDWA MC': 'Nandkumar Singh Chauhan, Government Medical College, Khandwa',
    'SHIVPURI MC': 'Government Medical College, Shivpuri', 'SHAHDOL MC': 'Government Medical College, Shahdol',
    'CHHINDWARA MC': 'Chhindwara Institute of Medical Sciences, Chhindwara',
    'PCMS': 'Peoples College of Medical Sciences and Research Centre, Bhanpur, Bhopal',
    'CHIRAYU': 'Chirayu Medical College and Hospital, Bairagarh, Bhopal',
    'LNMC': 'L.N. Medical College and Research Centre, Bhopal', 'LNMC BHOPAL': 'L.N. Medical College and Research Centre, Bhopal',
    'RD GARDI': 'Ruxmaniben Deepchand Gardi Medical College, Ujjain', 'RD GARDI MC': 'Ruxmaniben Deepchand Gardi Medical College, Ujjain',
    'SAIMS': 'Sri Aurobindo Medical College and Post Graduate Institute, Indore',
    'INDEX': 'Index Medical College Hospital and Research Centre, Indore', 'INDEX MC': 'Index Medical College Hospital and Research Centre, Indore',
    'AMALTAS': 'Amaltas Institute of Medical Sciences, Dewas', 'AMALTAS MC': 'Amaltas Institute of Medical Sciences, Dewas',
    'RKDF': 'RKDF Medical College and Research Centre, Bhopal', 'RKDF MC': 'RKDF Medical College and Research Centre, Bhopal',
    'LNCT': 'LNCT Medical College and Sewakunj Hospital, Indore', 'LNCT INDORE': 'LNCT Medical College and Sewakunj Hospital, Indore',
    'MAHAVEER': 'Mahaveer Institute of Medical Sciences and Research, Bhopal',
    'SUKHSAGAR': 'Sukh Sagar Medical College and Hospital, Jabalpur',
    'RAMAKRISH NA': 'Ram Krishna College Hospital and Research Centre, Bhopal',
    'RAMKRISHNA': 'Ram Krishna College Hospital and Research Centre, Bhopal'}
SUBJECTS = {  # PDF subject, lower-case letters only → approved course name
    'anaesthesiology': 'MD - Anaesthesiology', 'anesthesiology': 'MD - Anaesthesiology', 'anatomy': 'MD/MS - Anatomy',
    'biochemistry': 'MD - Biochemistry', 'communitymedicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'dermatology': 'MD - Dermatology', 'dermatologyvenereologyandleprosy': 'MD - Dermatology',
    'emergencymedicine': 'MD - Emergency Medicine', 'forensicmedicineandtoxicology': 'MD - Forensic Medicine',
    'generalmedicine': 'MD - General Medicine', 'generalsurgery': 'MS - General Surgery',
    'immunohaematologybloodtransfusion': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'immunohaematologybt': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'mdimmunohaematologybloodtransfusion': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'microbiology': 'MD - Microbiology', 'obstetricsandgynaecology': 'MS - Obstetrics and Gynaecology',
    'ophthalmology': 'MS - Ophthalmology', 'opthalmology': 'MS - Ophthalmology', 'orthopaedics': 'MS - Orthopaedics',
    'otorhinolaryngology': 'MS - ENT (Otorhinolaryngology)', 'paediatrics': 'MD - Paediatrics',
    'pathology': 'MD - Pathology', 'pharmacology': 'MD - Pharmacology', 'physiology': 'MD - Physiology',
    'psychiatry': 'MD - Psychiatry', 'radiationoncology': 'MD - Radiotherapy / Radiation Oncology',
    'radiodiagnosis': 'MD - Radio-Diagnosis', 'respiratorymedicine': 'MD - Respiratory Medicine'}
DIPLOMA = {'paediatrics': 'Diploma in Child Health / Paediatrics', 'obgy': 'Diploma in Obstetrics and Gynaecology',
           'opthalmology': 'Diploma in Ophthalmology', 'anesthesiology': 'Diploma in Anaesthesiology',
           'familymedicine': 'Diploma in Family Medicine', 'ent': 'Diploma in ENT'}
HOSPITALS = {'DH Bhopal': 'District Hospital, Bhopal, Madhya Pradesh', 'DH Jabalpur': 'District Hospital (Victoria), Jabalpur, Madhya Pradesh',
             'Civil Hospital Jabalpur': 'Civil Hospital, Jabalpur, Madhya Pradesh', 'DH Guna': 'District Hospital, Guna, Madhya Pradesh',
             'DH Gwalior': 'District Hospital, Gwalior, Madhya Pradesh', 'DH Ratlam': 'District Hospital, Ratlam, Madhya Pradesh',
             'DH Rewa': 'District Hospital, Rewa, Madhya Pradesh', 'DH Sagar': 'District Hospital, Sagar, Madhya Pradesh',
             'DH Satna': 'District Hospital, Satna, Madhya Pradesh', 'DH Shivpuri': 'District Hospital, Shivpuri, Madhya Pradesh',
             'DH Ujjain': 'District Hospital, Ujjain, Madhya Pradesh', 'DH Vidisha': 'District Hospital, Vidisha, Madhya Pradesh'}
key = lambda s: re.sub(r'[^a-z]', '', (s or '').lower())


def val(s):
    s = clean(s)
    if s == '':
        return 0
    if not s.isdigit():
        raise SystemExit(f'not a number: {s!r}')
    return int(s)


def subject(s, table=SUBJECTS):
    if key(s) not in table:
        raise SystemExit(f'unknown subject {s!r}')
    return table[key(s)]


def college(h):
    h = clean(h).upper()
    if h not in COLLEGES:
        raise SystemExit(f'unknown college heading {h!r}')
    return COLLEGES[h]


def category_grid(g, cats, label):
    """One college × category grid (a table whose header carries college names, then a category row).
    Returns {(college, course, category): seats}, the printed total, and per course the colleges' sum and the
    Grand Total block (the govt pages split the colleges over two tables, so the caller compares those)."""
    width = len(cats) + 1                        # categories + Total
    head = next(r for r in g if any(clean(x).upper() in COLLEGES for x in r if x))
    names = [clean(x) for x in head if x and (clean(x).upper() in COLLEGES or clean(x).lower().startswith('grand tot'))]
    n = len(names) * width
    catrow = next(r for r in g if sum(clean(x).upper() in ('UR', 'EWS', 'ST', 'SC', 'OBC') for x in r if x) >= 3)
    labels = [clean(x).upper() for x in catrow[-n:]]
    want = (cats + ['TOTAL']) * len(names)
    if any(a != b and not (i == 0 and a in ('', 'SUBJECT UR')) for i, (a, b) in enumerate(zip(labels, want))):
        raise SystemExit(f'{label}: column headings changed: {labels}')
    seats, totals, across_all, grand_all = {}, None, {}, {}
    sums = collections.defaultdict(int)
    for r in g:
        if len(r) < n:
            continue
        lead = [clean(x) for x in r[:-n] if x]
        if any(x.lower().startswith('total') for x in lead):
            totals = [val(x) if clean(x) else None for x in r[-n:]]   # a few printed totals are left blank
            continue
        if not any(x.isdigit() for x in lead) or not any(re.search('[a-z]', x) for x in lead):
            continue
        vals = [val(x) for x in r[-n:]]
        course = subject(next(x for x in lead if re.search('[a-z]', x)))
        across = [0] * width
        for gi, name in enumerate(names):
            block = vals[gi * width:(gi + 1) * width]
            if sum(block[:-1]) != block[-1]:
                raise SystemExit(f'{label}: {name} {course} categories {block[:-1]} ≠ total {block[-1]}')
            for ci, cat in enumerate(cats + ['TOTAL']):
                sums[(gi, ci)] += block[ci]
            if name.lower().startswith('grand'):
                grand_all[course] = block
                continue
            across = [a + b for a, b in zip(across, block)]
            for ci, cat in enumerate(cats):
                if block[ci]:
                    k = (college(name), course, cat)
                    seats[k] = seats.get(k, 0) + block[ci]
        across_all[course] = across
    if totals is None:
        raise SystemExit(f'{label}: no Total row')
    for gi, name in enumerate(names):
        for ci in range(width):
            if totals[gi * width + ci] is not None and sums[(gi, ci)] != totals[gi * width + ci]:
                raise SystemExit(f'{label}: {name} column {(cats + ["TOTAL"])[ci]} adds to {sums[(gi, ci)]}, printed {totals[gi * width + ci]}')
    grand = names.index(next(x for x in names if x.lower().startswith('grand'))) if any(
        x.lower().startswith('grand') for x in names) else None
    printed = totals[grand * width + width - 1] if grand is not None else sum(
        totals[gi * width + width - 1] for gi in range(len(names)))
    return seats, printed, across_all, grand_all


def grand_check(label, parts):
    across, grand = collections.defaultdict(lambda: None), {}
    for _, _, a, g in parts:
        for c, v in a.items():
            across[c] = v if across[c] is None else [x + y for x, y in zip(across[c], v)]
        grand.update(g)
    for c, g in grand.items():
        if across[c] != g:
            raise SystemExit(f'{label}: {c} colleges add to {across[c]}, Grand Total {g}')
    if not grand:
        raise SystemExit(f'{label}: no Grand Total column')


def simple_grid(g, label):
    """College-per-column table (private overview / NRI): returns {(college, course): seats}, printed total."""
    head = next(r for r in g if any(clean(x).upper() in COLLEGES for x in r if x))
    cols = [(i, college(x)) for i, x in enumerate(head) if x and clean(x).upper() in COLLEGES]
    ti = max(i for i, x in enumerate(head) if x and clean(x).lower() in ('total', 'grand total'))
    seats, sums, printed = {}, collections.Counter(), None
    for r in g:
        if clean(r[0]).lower() == 'total':
            for i, c in cols:
                if sums[c] != val(r[i]):
                    raise SystemExit(f'{label}: {c} adds to {sums[c]}, printed {r[i]}')
            printed = val(r[ti])
            continue
        if not clean(r[0]).isdigit():
            continue
        course = subject(r[1])
        row = 0
        for i, c in cols:
            v = val(r[i]); row += v; sums[c] += v
            if v:
                seats[(c, course)] = seats.get((c, course), 0) + v
        if row != val(r[ti]):
            raise SystemExit(f'{label}: {course} adds to {row}, printed {r[ti]}')
    return seats, printed


rows, checks = [], {}


def add(seats, quota, pwd=False, section='mdms'):
    for (c, course, cat), n in seats.items():
        rows.append({'college': c, 'course': course, 'quota': quota, 'seats': n, 'section': section,
                     'category': cat + ('-PwD' if pwd else '')})


# ── Government & Autonomous ──
G = ['UR', 'EWS', 'ST', 'SC', 'OBC']
for p, (quota, pwd, lab) in enumerate([('State Quota', False, 'govt Open'), ('State Quota', True, 'govt PWD'),
                                       ('In-service Quota', False, 'govt In-service Open'),
                                       ('In-service Quota', True, 'govt In-service PWD')]):
    page_seats, printed, parts = {}, 0, []
    for g in grids(fitz.open(GOVT)[p]):
        parts.append(category_grid(g, G, lab))
        for k, v in parts[-1][0].items():
            page_seats[k] = page_seats.get(k, 0) + v
        printed = parts[-1][1]           # the Grand Total sits in the second (lower) table
    grand_check(lab, parts)
    add(page_seats, quota, pwd)
    checks[lab] = (sum(page_seats.values()), printed)

# ── Private ──
doc = fitz.open(PRIV)
overview, ov_total = simple_grid(grids(doc[0])[0], 'private overview')
nri, nri_total = simple_grid(grids(doc[1])[0], 'private NRI')
for (c, course), n in nri.items():
    rows.append({'college': c, 'course': course, 'quota': 'NRI Quota', 'seats': n, 'section': 'mdms', 'category': ''})
checks['private NRI'] = (sum(nri.values()), nri_total)
P = ['UR', 'ST', 'SC', 'OBC']
for p, (quota, pwd, lab) in enumerate([
        ('In-service Quota (Institutional)', False, 'private In-service Institutional Open'),
        ('In-service Quota (Institutional)', True, 'private In-service Institutional PWD'),
        ('State Quota (Institutional)', False, 'private Open Institutional'),
        ('State Quota (Institutional)', True, 'private Institutional PWD'),
        ('State Quota (Non-Institutional)', False, 'private Non-Institutional Open'),
        ('State Quota (Non-Institutional)', True, 'private Non-Institutional PWD')], start=2):
    part = category_grid(grids(doc[p])[0], P, lab)
    grand_check(lab, [part])
    s, printed = part[0], part[1]
    add(s, quota, pwd)
    checks[lab] = (sum(s.values()), printed)
# the overview page must equal NRI + all six category pages, college by college and course by course
got = collections.Counter()
for x in rows:
    if x['college'] in {c for c, _ in overview}:
        got[(x['college'], x['course'])] += x['seats']
diff = {k: (got[k], overview.get(k, 0)) for k in set(got) | set(overview) if got[k] != overview.get(k, 0)}
if diff:
    raise SystemExit(f'private pages do not add up to the overview page: {diff}')
checks['private overview'] = (sum(got.values()), ov_total)

# ── District hospitals: Post-MBBS DNB (Bhopal) + Post-MBBS Diploma ──
doc = fitz.open(DIST)
g = grids(doc[0])[0]
if 'Post MBBS DNB' not in clean(g[0][1]):
    raise SystemExit(f'district p1 heading changed: {g[0][1]!r}')
hdr = [clean(x) for x in g[1]]
for r in g[2:]:
    vals = [val(x) for x in r[2:]]
    if sum(vals[:-1]) != vals[-1]:
        raise SystemExit(f'district DNB row {r}')
    for cat, n in zip(hdr[2:-1], vals[:-1]):
        if n:
            rows.append({'college': 'District Hospital, Bhopal, Madhya Pradesh', 'course': f'DNB - {clean(r[1])} (Post-MBBS)',
                         'quota': 'DNB Quota', 'seats': n, 'section': 'dnb', 'category': cat})
g = grids(doc[1])[0]
hdr = [clean(x).upper() for x in g[0]]
if hdr[2:] != ['UR', 'ST', 'ST PWD', 'SC', 'OBC', 'EWS', 'TOTAL']:
    raise SystemExit(f'district diploma headings changed: {hdr}')
hosp, dip, dip_printed = None, 0, None
for r in g[1:]:
    if clean(r[1]).lower() == 'total':
        dip_printed = val(r[-1]); continue
    hosp = clean(r[0]) or hosp
    if hosp not in HOSPITALS:
        raise SystemExit(f'unknown hospital {hosp!r}')
    vals = [val(x) for x in r[2:]]
    if sum(vals[:-1]) != vals[-1]:
        raise SystemExit(f'district diploma row {r}')
    for cat, n in zip(['UR', 'ST', 'ST-PwD', 'SC', 'OBC', 'EWS'], vals[:-1]):
        if n:
            rows.append({'college': HOSPITALS[hosp], 'course': subject(r[1], DIPLOMA), 'quota': 'Diploma Quota',
                         'seats': n, 'section': 'diploma', 'category': cat})
            dip += n
checks['district Post-MBBS Diploma'] = (dip, dip_printed)

# merge rows that repeat (same college × course × quota × category)
agg = collections.OrderedDict()
for x in rows:
    k = (x['college'], x['course'], x['quota'], x['category'])
    if k in agg:
        agg[k]['seats'] += x['seats']
    else:
        agg[k] = dict(x)
rows = list(agg.values())

FAMILY = {'State Quota': ('Institutional Quota', 'Government Quota'), 'In-service Quota': ('Government Quota-Inservice',),
          'NRI Quota': ('NRI Quota',), 'In-service Quota (Institutional)': ('Private Quota-Inservice',),
          'State Quota (Institutional)': ('Institutional Quota',), 'State Quota (Non-Institutional)': ('Private Quota',),
          'Diploma Quota': ('Diploma',), 'DNB Quota': ('DNB',)}


def cat_match(x):
    base, pwd = x['category'].split('-')[0], x['category'].endswith('PwD')
    pre = 'IN_' if x['quota'].startswith('In-service') else ''
    if not base:
        return ('UR/NRI/OP',)
    return ((f'{pre}{base}/PH/OP',) if pwd else ()) + (f'{pre}{base}/X/OP',)


cuts = load_cuts(CUTS, 'Madhya Pradesh')
out = build(rows, cuts, 'Madhya Pradesh', 'MP', lambda q: FAMILY[q], cat_match)
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
