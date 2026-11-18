"""Tamil Nadu NEET PG 2026 — seats ADDED for Round 2 (DMER Notification No. 1152/SCSII(1)/2026, 16.11.2026, per NMC
notice M-19011/20/2025-PGMARB of 06.11.2026): "INCREASE OF SEATS IN GOVT. MEDICAL COLLEGES FOR ROUND 2 COUNSELLING".
One table, SPECIALITY × SQ (total) / OPEN / SERVICE — NO college split, so these are NOT seat-matrix rows (every row
needs a college). Output = per-course totals for the record / the Round 2 cross-check; the college-wise Round 2
vacancy list, when DMER publishes it, is loaded as "Tamil Nadu — Round 2 — State Counselling" and must contain them
(OPEN → Government Quota, SERVICE → Government Quota-Service; Government colleges).
Checks: every line SQ = OPEN + SERVICE, the TOTAL line (214 = 109 + 105), course names approved.
Usage: /usr/bin/python3 tamil_nadu_added_r2.py <notice.pdf> <out.json>
"""
import sys, os, re, json
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import approved_courses

PDF, OUT = sys.argv[1:3]
COURSES = {'ANAESTHESIOLOGY': 'MD - Anaesthesiology', 'GENERAL MEDICINE': 'MD - General Medicine',
           'PAEDIATRICS': 'MD - Paediatrics', 'RADIODIAGNOSIS': 'MD - Radio-Diagnosis',
           'RADIATION ONCOLOGY': 'MD - Radiotherapy / Radiation Oncology', 'EMERGENCY MEDICINE': 'MD - Emergency Medicine',
           'IMMUNO & TRANS. MED.': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
           'FORENSIC MEDICINE': 'MD - Forensic Medicine', 'NUCLEAR MEDICINE': 'MD - Nuclear Medicine',
           'SPORTS MEDICINE': 'MD - Sports Medicine', 'GENERAL SURGERY': 'MS - General Surgery',
           'OBSTETRICS & GYNAECOLOGY': 'MS - Obstetrics and Gynaecology', 'ORTHOPAEDICS': 'MS - Orthopaedics'}
doc = fitz.open(PDF)
txt = doc[0].get_text()
if '1152/SCSII(1)/2026' not in txt or 'INCREASE OF SEATS' not in txt:
    raise SystemExit('not DMER notification 1152 (increase of seats)')
bad = sorted(set(COURSES.values()) - approved_courses())
if bad:
    raise SystemExit(f'course names not approved: {bad}')
t = [[re.sub(r'\s+', ' ', (c or '')).strip() for c in r] for r in doc[0].find_tables().tables[0].extract()]
rows, total = [], None
for r in t:
    if r[0].isdigit():
        name = r[1].upper()
        if name not in COURSES:
            raise SystemExit(f'unknown speciality {r[1]!r}')
        sq, op, sv = (int(x or 0) for x in r[2:5])
        if op + sv != sq:
            raise SystemExit(f'{name}: OPEN {op} + SERVICE {sv} ≠ SQ {sq}')
        rows.append({'sl_no': int(r[0]), 'speciality_raw': r[1], 'course_name': COURSES[name], 'seats': sq,
                     'open': op, 'service': sv})
    elif 'TOTAL' in ' '.join(r).upper():
        total = [int(x) for x in r[2:5] if x]
if total is None:
    raise SystemExit('no TOTAL line')
got = [sum(x[k] for x in rows) for k in ('seats', 'open', 'service')]
if got != total:
    raise SystemExit(f'totals {got} ≠ printed {total}')
json.dump({'notice': 'DMER TN Notification No. 1152/SCSII(1)/2026 (16.11.2026)', 'colleges': 'Government Medical Colleges '
           '(college split not published)', 'rows': rows, 'totals': dict(zip(('seats', 'open', 'service'), got))},
          open(OUT, 'w'), ensure_ascii=False, indent=1)
print('specialities', len(rows), 'seats', got[0], '(OPEN', got[1], '+ SERVICE', got[2], ') — matches TOTAL', total)
for x in rows:
    print(f"  {x['seats']:>3}  {x['course_name']}  (open {x['open']}, service {x['service']})")
