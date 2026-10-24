"""Goa PG Medical seat distribution 2026-27 (DTE Goa) → standardised seat rows, one per course × category,
bridged to Goa's 2025 cut-offs. Only Goa Medical College. Run with /usr/bin/python3 (PyMuPDF)."""
import re, sys, os
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report

PDF, CUTS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
COLLEGE = 'Goa Medical College, Panaji'
COURSES = {  # the PDF's own wording → approved course name
    'ANAESTHESIOLOGY': 'MD - Anaesthesiology', 'ANATOMY': 'MD/MS - Anatomy', 'BIOCHEMISTRY': 'MD - Biochemistry',
    'DERMATOLOGY': 'MD - Dermatology', 'FORENSIC MEDICINE': 'MD - Forensic Medicine',
    'GENERAL MEDICINE': 'MD - General Medicine', 'GENERAL SURGERY': 'MS - General Surgery',
    'GERIATRIC': 'MD - Geriatrics', 'MICROBIOLOGY': 'MD - Microbiology',
    'OBSTETRICS & GYNAECOLOGY': 'MS - Obstetrics and Gynaecology', 'OPTHALMOLOGY': 'MS - Ophthalmology',
    'ORTHOPAEDICS': 'MS - Orthopaedics', 'OTORHINO LARYNGOLOGY(OTO-ENT)': 'MS - ENT (Otorhinolaryngology)',
    'PAEDIATRICS': 'MD - Paediatrics', 'PATHOLOGY': 'MD - Pathology', 'PHARMACOLOGY': 'MD - Pharmacology',
    'PHYSIOLOGY': 'MD - Physiology', 'PSM (COMMUNITY MEDICINE)': 'MD - Social & Preventive Medicine / Community Medicine',
    'PSYCHIATRY': 'MD - Psychiatry', 'RADIOLOGY (RADIO DIAGNOSIS)': 'MD - Radio-Diagnosis',
    'TB (RESPIRATORY MEDICINE)': 'MD - Respiratory Medicine',
    'TRANSFUSION MEDICINE (IHBT)': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion'}
CATS = ['SC', 'ST', 'OBC', 'EWS', 'GEN']


def cell(s):
    """'3' → {'':3}; '1 (PwD)' → {'PwD':1}; '1 +1(PwD)' → {'':1,'PwD':1}; '-' → {}"""
    s = clean(s).replace(' ', '')
    out = {}
    for n, pwd in re.findall(r'(\d+)(\(PwD\))?', s, re.I):
        k = 'PwD' if pwd else ''
        out[k] = out.get(k, 0) + int(n)
    return out


t = fitz.open(PDF)[0].find_tables().tables[0].extract()
if [clean(x) for x in t[1][3:8]] != CATS:
    raise SystemExit(f'category header changed: {t[1]}')
rows, parsed_total, printed = [], 0, {}
for r in t:
    if clean(r[1]) == 'TOTAL':
        printed = {'TOTAL': int(clean(r[2]))} | {c: int(clean(r[3 + i]) or 0) for i, c in enumerate(CATS)}
        continue
    if not clean(r[0]).isdigit():
        continue
    raw = clean(r[1])
    if raw not in COURSES:
        raise SystemExit(f'unknown course {raw!r}')
    row_sum = 0
    for i, cat in enumerate(CATS):
        for kind, n in cell(r[3 + i]).items():
            rows.append({'college': COLLEGE, 'course': COURSES[raw], 'quota': 'Government Quota', 'seats': n,
                         'section': 'mdms', 'category': cat + ('-PwD' if kind else '')})
            row_sum += n
    if row_sum != int(clean(r[2])):
        raise SystemExit(f'{raw}: categories add to {row_sum}, row total {r[2]}')
checks = {'TOTAL': (sum(x['seats'] for x in rows), printed['TOTAL'])}
for c in CATS:
    checks[c] = (sum(x['seats'] for x in rows if x['category'].split('-')[0] == c), printed[c])

cuts = load_cuts(CUTS, 'Goa')
out = build(rows, cuts, 'Goa', 'GA', lambda q: ('Government Quota',),
            lambda x: ('DR-' + x['category'].split('-')[0],) if x['category'].endswith('PwD') else (x['category'],))
import json
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
