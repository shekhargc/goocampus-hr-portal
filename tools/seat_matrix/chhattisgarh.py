"""Chhattisgarh NEET PG (MD/MS) 2026 seat matrix (DME Chhattisgarh, 200-point reservation roster, 21.10.2026)
→ standardised seat rows, bridged to Chhattisgarh's 2025 cut-offs. The PDF lists one line per seat; every page
carries a header box (Total / All India / State, or State / NRI) and private-college pages say whether they are
the State or NRI quota and Institutional or Open. Run with /usr/bin/python3 (PyMuPDF)."""
import re, sys, os, json, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report

PDF, CUTS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
COLLEGES = {  # PDF name (start) → standard institute name (2025 cut-offs)
    'Pt. Jawahar Lal Nehru Memorial Medical College': 'Pt. Jawahar Lal Nehru Memorial Medical College, Raipur',
    'Chhattisgarh Institute of Medical Sciences': 'Chhattisgarh Institute of Medical Sciences, Bilaspur',
    'Late Shri Baliram Kashyap Memorial': 'Late Shri Baliram Kashyap Memorial Govt. Medical College, Jagdalpur',
    'Late Shri Lakhi Ram Agrawal Memorial': 'Late Shri Lakhi Ram Agrawal Memorial Govt. Medical College, Raigarh',
    'Bharat Ratna Late Shree Atal Bihari Vajpayee': 'Government Medical College, (Bharat Ratna Shri Atal Bihari Vajpayee Memorial Medical College), Rajnandgaon',
    'Rajmata Smt.Devendra Kumari Singhdeo': 'Rajmata Shrimati Devendra Kumari Singhdeo Government Medical College, Ambikapur',
    'Late Bisahu Das Mahant Memorial': 'Government Medical College, Korba',
    'Raipur Institute of Medical Sciences': 'Raipur Institute of Medical Sciences, Raipur',
    'Shri Shankaracharya Institute of Medical Science': 'Shri Shankaracharya Institute of Medical Sciences, Bhilai',
    'Shri Balaji Institute of Medical Science': 'Shri Balaji Institute of Medical Science, Raipur',
}
COURSES = {
    'MD Anaesthesiology': 'MD - Anaesthesiology', 'MD Anatomy': 'MD/MS - Anatomy', 'MD Biochemistry': 'MD - Biochemistry',
    'MD Dermatology, Venereology & Leprosy': 'MD - Dermatology', 'MD Emergency Medicine': 'MD - Emergency Medicine',
    'MD Forensic Medicine': 'MD - Forensic Medicine', 'MD General Medicine': 'MD - General Medicine',
    'MD Microbiology': 'MD - Microbiology', 'MD Paediatrics': 'MD - Paediatrics', 'MD Pathology': 'MD - Pathology',
    'MD Pharmacology': 'MD - Pharmacology', 'MD Physical Medicine & Rehabilitation': 'MD - Physical Medicine and Rehabilitation',
    'MD Physiology': 'MD - Physiology', 'MD Preventive & Social Medicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'MD Psychiatry': 'MD - Psychiatry', 'MD Radiodiagnosis': 'MD - Radio-Diagnosis',
    'MD Radiotherapy / Radiation Oncology': 'MD - Radiotherapy / Radiation Oncology',
    'MD Respiratory Medicine': 'MD - Respiratory Medicine', 'MS General Surgery': 'MS - General Surgery',
    'MS Obstetrics & Gynaecology': 'MS - Obstetrics and Gynaecology', 'MS Ophthalmology': 'MS - Ophthalmology',
    'MS Orthopaedics': 'MS - Orthopaedics', 'MS Otorhinolaryngology (ENT)': 'MS - ENT (Otorhinolaryngology)'}
# seat quota → 2025 cut-off quota prefixes, best first (2025 split state seats into MBBS-passout / domicile / non-domicile)
FAMILY = {
    'State Quota': ('Government Quota-MBBS Passout', 'Government Quota-Domicile', 'Government Quota-Non-Domicile'),
    'State Quota (Institutional)': ('Government Quota-MBBS Passout', 'Government Quota-Domicile'),
    'State Quota (Open)': ('Government Quota-Non-Domicile', 'Government Quota-Domicile', 'Government Quota-MBBS Passout'),
    'NRI Quota (Institutional)': ('NRI Quota-MBBS Passout', 'NRI Quota'),
    'NRI Quota (Open)': ('NRI Quota-Non-Domicile', 'NRI Quota')}


def college_for(raw):
    for k, v in COLLEGES.items():
        if raw.startswith(k):
            return v
    raise SystemExit(f'unknown institute {raw!r}')


def category(raw):
    """'UR 3' → UR · 'ST Spc 1' → ST-Special · 'UR 20 (PwBD)' → UR-PwD"""
    m = re.fullmatch(r'(UR|ST|SC|OBC|EWS)( Spc)? \d+( \(PwBD\))?', raw)
    if not m:
        raise SystemExit(f'unknown category {raw!r}')
    return m.group(1) + ('-Special' if m.group(2) else '') + ('-PwD' if m.group(3) else '')


doc = fitz.open(PDF)
rows, box = [], {}               # box: college → printed header numbers
counted = collections.Counter()  # (college, State/NRI) → parsed seats
printed_split = {}               # (college, State/NRI, Institutional/Open) → "N Seats" printed on the page
for pg in doc:
    text = clean(pg.get_text())
    side = re.findall(r'- (State|NRI) Quota', text)
    split = re.findall(r'(Institutional|Open) Quota: (\d+) Seats?', text)
    tabs = pg.find_tables().tables
    head = {clean(a): int(clean(b)) for a, b in tabs[0].extract()}
    t = tabs[1].extract()
    h = [clean(x) for x in t[0]]
    si = next(i for i, x in enumerate(h) if x.startswith('Subject'))
    qi = h.index('Allotted Quota') if 'Allotted Quota' in h else None
    for r in t[1:]:
        if clean(r[0]) == 'S.No.' or not clean(r[0]).isdigit():
            continue
        college = college_for(clean(r[si + 1]))
        subj = clean(r[si])
        if subj not in COURSES:
            raise SystemExit(f'unknown subject {subj!r}')
        private = qi is not None
        s = side[0] if side else 'State'
        quota = f'{s} Quota ({clean(r[qi])})' if private else 'State Quota'
        rows.append({'college': college, 'course': COURSES[subj], 'quota': quota, 'seats': 1, 'section': 'mdms',
                     'category': category(clean(r[si + 2])),
                     'institute_type': 'Private Institute' if private else 'Government Institute'})
        counted[(college, s)] += 1
        box[college] = head
    if split:
        printed_split[(college, side[0], split[0][0])] = int(split[0][1])

# merge one-seat lines into college × course × quota × category rows
agg = collections.OrderedDict()
for x in rows:
    k = (x['college'], x['course'], x['quota'], x['category'])
    if k in agg:
        agg[k]['seats'] += 1
    else:
        agg[k] = dict(x)
rows = list(agg.values())

checks = {}
for college, head in box.items():
    checks[f'{college} | State Quota'] = (counted[(college, 'State')], head['State Quota'])
    if 'NRI Quota' in head:
        checks[f'{college} | NRI Quota'] = (counted[(college, 'NRI')], head['NRI Quota'])
for (college, s, part), n in printed_split.items():
    checks[f'{college} | {s} {part}'] = (sum(x['seats'] for x in rows if x['college'] == college
                                             and x['quota'] == f'{s} Quota ({part})'), n)

cuts = load_cuts(CUTS, 'Chhattisgarh')
out = build(rows, cuts, 'Chhattisgarh', 'CG', lambda q: FAMILY[q],
            lambda x: (x['category'].split('-')[0],))
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
