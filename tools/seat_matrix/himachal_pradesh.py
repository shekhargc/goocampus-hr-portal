"""Himachal Pradesh PG Medical (MD/MS) State Quota seat matrix 2026 (AMRU, "State Quota Seat matrix for PG MD/MS
Counselling 2026 (on 09.11.2026)", Endst. No. AMRU/(COE)-Admission-129/2026-27 PG(MD/MS) 6999-7007, 9 pages,
SCANNED — the OCR layer is unusable, so every number is hard-coded from the page images and the PDF is pinned to its
SHA-256: a re-issued file stops the script, re-transcribe it) → standardised seat rows, bridged to Himachal Pradesh's
2025 (AMRUHP) cut-offs. Run with /usr/bin/python3 (PyMuPDF):
    himachal_pradesh.py <matrix.pdf> <cutoffs2025.json> <out.json>
Posted as body "Himachal Pradesh — State Counselling", authority_code `amru_hp`, section `state`.

Layout (as printed):
  p1      the notice (50% State Quota seats, Govt + Private colleges; post-MBBS DNB seats and any extra NMC seats only
          from Round 2 — none in this file).
  p2-p7   one table per college ("(State Quota)"): Specility | Total Seats | GDO (UR SC ST PWD Total GDO) |
          Direct (UR SC ST EWS PWD Total Direct). IGMC Shimla, Dr RPGMC Tanda, SLBS Mandi, Dr YSPGMC Nahan (1 line),
          Dr Radhakrishnan GMC Hamirpur, Pt JLN GMC Chamba (2 lines), MMMC Kumarhatti (Solan) State Quota.
  p8      MMMC Management Quota (Resident Indians), Direct Quota: UR SC ST EWS PWD Total Seats.
  p9      MMMC "15% NRI Quota Seats" (one number per speciality, no category split).
Quotas: GDO (government doctors = in-service) → 'In-service Quota (GDO)' (2025 'State Quota-Inservice'); Direct →
'State Quota (Direct)' (2025 'State Quota'); 'Management Quota'; 'NRI Quota'. Categories as printed (UR SC ST EWS PWD;
PWD is its own column inside the seat total; NRI seats carry no category). Bridge UR → 2025 GEN, PWD → GEN-PH, NRI → NRI.
Checks: every line GDO cells = Total GDO, Direct cells = Total Direct, GDO + Direct = Total Seats; every column = the
college's Total line (IGMC, Tanda, Mandi, Hamirpur, MMMC State, MMMC Management, MMMC NRI); every course = 1 of the 21
specialities. Known print gaps (not errors, totals still add): Nahan and Chamba print no Total line and print '-' in
Total GDO / Total Direct cells that hold a seat; Mandi ENT and Psychiatry leave Total Direct blank (0 seats).
2026-27 (09.11.2026): 234 seats — State Quota tables 165 (GDO 110 + Direct 55) + MMMC Management 55 + MMMC NRI 14."""
import hashlib, json, os, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report

PDF, CUTS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
SHA256 = '9844cf57a869d0626345ca4a32ea8b14a794cfa1b87c4d2268efab60f4befb91'

COURSES = {   # printed speciality (state / management pages, and the NRI page's own wording) → approved course
    'Anatomy': 'MD/MS - Anatomy', 'Anesthesiology': 'MD - Anaesthesiology', 'Anaesthesia': 'MD - Anaesthesiology',
    'Biochemistry': 'MD - Biochemistry',
    'Community Medicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'Comm. Medicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'Dermatology, Venrology and Leprosy': 'MD - Dermatology', 'Dermatology': 'MD - Dermatology',
    'Forensic Medicine': 'MD - Forensic Medicine', 'General Medicine': 'MD - General Medicine',
    'General Surgery': 'MS - General Surgery', 'Microbiology': 'MD - Microbiology',
    'Obstetrics & Gynecology (OBG)': 'MS - Obstetrics and Gynaecology', 'Obst. & Gynae': 'MS - Obstetrics and Gynaecology',
    'Ophthalmology': 'MS - Ophthalmology', 'Orthopedics': 'MS - Orthopaedics', 'Orthopaedics': 'MS - Orthopaedics',
    'Oto-rhino-Laryngology (ENT)': 'MS - ENT (Otorhinolaryngology)',
    'Oto-Rhino-Laryngology (ENT)': 'MS - ENT (Otorhinolaryngology)',
    'Pathology': 'MD - Pathology', 'Pediatrics': 'MD - Paediatrics', 'Paediatrics': 'MD - Paediatrics',
    'Pharmacology': 'MD - Pharmacology', 'Physiology': 'MD - Physiology', 'Psychiatry': 'MD - Psychiatry',
    'Radio-diagnosis': 'MD - Radio-Diagnosis', 'Radio-Diagnosis': 'MD - Radio-Diagnosis',
    'Radiotherapy': 'MD - Radiotherapy / Radiation Oncology',
    'Tuberculosis & Respiratory Diseases': 'MD - Respiratory Medicine', 'Pulm. Medicine': 'MD - Respiratory Medicine'}

# printed heading → 2025 cut-off name (all seven colleges are in the 2025 AMRUHP cut-offs)
IGMC = 'Indira Gandhi Medical College, Shimla'
TANDA = 'Dr. Rajendra Prasad Government Medical College, Kangra, Tanda'
MANDI = 'Shri Lal Bahadur Shastri Government Medical College and Hospital, Mandi'
NAHAN = 'Dr. YS Parmar Government Medical College, Nahan'
HAMIRPUR = 'Dr. Radhakrishnan Government Medical College, Hamirpur'
CHAMBA = 'Pt. Jawahar Lal Nehru Government Medical College, Chamba'
MMMC = 'Maharishi Markandeshwar Medical College and Hospital, Solan'

GDO_CATS = ['UR', 'SC', 'ST', 'PWD']
DIR_CATS = ['UR', 'SC', 'ST', 'EWS', 'PWD']
# State Quota tables (p2-p7): 'Total | GDO UR SC ST PWD TotalGDO | Direct UR SC ST EWS PWD TotalDirect'
# '-' = printed dash (0); '_' = blank cell (0); '-*' = '-' printed in a Total cell whose line holds a seat (print gap)
STATE = [
    (2, 'Indira Gandhi Medical College, Shimla (State Quota)', IGMC, [
        ('Anatomy', '1 | 1 - - - 1 | - - - - - 0'),
        ('Anesthesiology', '8 | 4 1 - 1 6 | 2 - - - - 2'),
        ('Biochemistry', '0 | - - - - 0 | - - - - - 0'),
        ('Community Medicine', '2 | 2 - - - 2 | - - - - - 0'),
        ('Dermatology, Venrology and Leprosy', '2 | - - 1 - 1 | 1 - - - - 1'),
        ('Forensic Medicine', '0 | - - - - 0 | - - - - - 0'),
        ('General Medicine', '8 | 5 - - - 5 | 1 1 1 - - 3'),
        ('General Surgery', '7 | 4 1 - - 5 | 1 - 1 - - 2'),
        ('Microbiology', '2 | 1 - - - 1 | 1 - - - - 1'),
        ('Obstetrics & Gynecology (OBG)', '7 | 3 1 - - 4 | 3 - - - - 3'),
        ('Ophthalmology', '2 | 1 - - - 1 | 1 - - - - 1'),
        ('Orthopedics', '3 | 1 1 - - 2 | 1 - - - - 1'),
        ('Oto-rhino-Laryngology (ENT)', '2 | 1 - 1 - 2 | - - - - - 0'),
        ('Pathology', '3 | 2 - - - 2 | 1 - - - - 1'),
        ('Pediatrics', '7 | 3 1 1 - 5 | 1 - - 1 - 2'),
        ('Pharmacology', '1 | - - - - 0 | 1 - - - - 1'),
        ('Physiology', '2 | - 1 - - 1 | 1 - - - - 1'),
        ('Psychiatry', '1 | 1 - - - 1 | - - - - - 0'),
        ('Radio-diagnosis', '8 | 4 1 - - 5 | 1 - 1 - 1 3'),
        ('Radiotherapy', '2 | 1 - 1 - 2 | - - - - - 0'),
        ('Tuberculosis & Respiratory Diseases', '2 | 2 - - - 2 | - - - - - 0')],
     '70 | 36 7 4 1 48 | 16 1 3 1 1 22'),
    (3, 'Dr. Rajendra Prasad Government Medical College Kangra at Tanda (HP) (State Quota)', TANDA, [
        ('Anatomy', '1 | - - 1 - 1 | - - - - - 0'),
        ('Anesthesiology', '6 | 4 - - - 4 | - 1 1 - - 2'),
        ('Biochemistry', '1 | 1 - - - 1 | - - - - - 0'),
        ('Community Medicine', '2 | - 1 - - 1 | 1 - - - - 1'),
        ('Dermatology, Venrology and Leprosy', '2 | 1 - - 1 2 | - - - - - 0'),
        ('Forensic Medicine', '1 | 1 - - - 1 | - - - - - 0'),
        ('General Medicine', '5 | 2 1 - - 3 | 2 - - - - 2'),
        ('General Surgery', '4 | 2 - - - 2 | 2 - - - - 2'),
        ('Microbiology', '1 | - - - 1 1 | - - - - - 0'),
        ('Obstetrics & Gynecology (OBG)', '8 | 5 - 1 - 6 | 1 1 - - - 2'),
        ('Ophthalmology', '2 | 1 - 1 - 2 | - - - - - 0'),
        ('Orthopedics', '3 | 2 - - - 2 | 1 - - - - 1'),
        ('Oto-rhino-Laryngology (ENT)', '2 | - - - 1 1 | - - - 1 - 1'),
        ('Pathology', '1 | 1 - - - 1 | - - - - - 0'),
        ('Pediatrics', '6 | 2 1 - 1 4 | 2 - - - - 2'),
        ('Pharmacology', '1 | 1 - - - 1 | - - - - - 0'),
        ('Physiology', '0 | - - - - 0 | - - - - - 0'),
        ('Psychiatry', '2 | 1 - - - 1 | 1 - - - - 1'),
        ('Radio-diagnosis', '4 | 3 - - - 3 | 1 - - - - 1'),
        ('Radiotherapy', '0 | - - - - 0 | - - - - - 0'),
        ('Tuberculosis & Respiratory Diseases', '0 | - - - - 0 | - - - - - 0')],
     '52 | 27 3 3 4 37 | 11 2 1 1 0 15'),
    (4, 'Shri Lal Bahadur Shastri Govt. Medical College & Hospital. Mandi (State Quota)', MANDI, [
        ('Anesthesiology', '0 | - - - - 0 | - - - - - 0'),
        ('General Medicine', '2 | 2 - - - 2 | - - - - - 0'),
        ('General Surgery', '2 | 1 1 - - 2 | - - - - - 0'),
        ('Microbiology', '2 | - 1 - - 1 | 1 - - - - 1'),
        ('Obstetrics & Gynecology (OBG)', '0 | - - - - 0 | - - - - - 0'),
        ('Orthopedics', '2 | 1 - - - 1 | 1 - - - - 1'),
        ('Oto-rhino-Laryngology (ENT)', '1 | 1 - - - 1 | - - - - - _'),
        ('Pediatrics', '0 | - - - - 0 | - - - - - 0'),
        ('Pharmacology', '2 | - - 1 - 1 | 1 - - - - 1'),
        ('Psychiatry', '1 | - 1 - - 1 | - - - - - _'),
        ('Tuberculosis & Respiratory Diseases', '1 | - - - - 0 | 1 - - - - 1')],
     '13 | 5 3 1 0 9 | 4 0 0 0 0 4'),
    (5, 'Dr. Yashwant Singh Parmar Govt. Medical College & Hospital, Nahan (H.P) (State Quota)', NAHAN, [
        ('Community Medicine', '1 | 1 - - - -* | - - - - - -')],
     None),
    (5, 'Dr. Radhakrishnan Government Medical College Hamirpur', HAMIRPUR, [
        ('Anesthesiology', '0 | - - - - 0 | - - - - - 0'),
        ('Dermatology, Venrology and Leprosy', '1 | - - - - 0 | 1 - - - - 1'),
        ('General Medicine', '0 | - - - - 0 | - - - - - 0'),
        ('General Surgery', '0 | - - - - 0 | - - - - - 0'),
        ('Microbiology', '0 | - - - - 0 | - - - - - 0'),
        ('Obstetrics & Gynecology (OBG)', '2 | - - - 1 1 | - - - 1 - 1'),
        ('Pediatrics', '0 | - - - - 0 | - - - - - 0'),
        ('Physiology', '1 | 1 - - - 1 | - - - - - 0')],
     '4 | 1 0 0 1 2 | 1 0 0 1 0 2'),
    (6, 'Pt. Jawaharlal Nehru Govt. Medical College, Chamba', CHAMBA, [
        ('General Medicine', '1 | - - - - - | - - - - 1 -*'),
        ('Orthopedics', '1 | - 1 - - -* | - - - - - -')],
     None),
    (7, 'Maharishi Markandeshwar Medical College & Hospital, Kumarhatti, Distt. Solan State Quota', MMMC, [
        ('Anatomy', '1 | - - - - 0 | 1 - - - - 1'),
        ('Anesthesiology', '2 | - 1 - - 1 | 1 - - - - 1'),
        ('Biochemistry', '1 | - - - - 0 | 1 - - - - 1'),
        ('Community Medicine', '1 | - - - - 0 | 1 - - - - 1'),
        ('Dermatology, Venrology and Leprosy', '1 | - 1 - - 1 | - - - - - 0'),
        ('Forensic Medicine', '1 | 1 - - - 1 | - - - - - 0'),
        ('General Medicine', '2 | 1 1 - - 2 | - - - - - 0'),
        ('General Surgery', '2 | - - 1 - 1 | 1 - - - - 1'),
        ('Microbiology', '1 | 1 - - - 1 | - - - - - 0'),
        ('Obstetrics & Gynecology (OBG)', '1 | - 1 - - 1 | - - - - - 0'),
        ('Ophthalmology', '0 | - - - - 0 | - - - - - 0'),
        ('Orthopedics', '2 | 1 - - - 1 | 1 - - - - 1'),
        ('Oto-rhino-Laryngology (ENT)', '1 | - - - - 0 | - 1 - - - 1'),
        ('Pathology', '1 | - - - - 0 | 1 - - - - 1'),
        ('Pediatrics', '1 | - - - - 0 | - 1 - - - 1'),
        ('Pharmacology', '1 | 1 - - - 1 | - - - - - 0'),
        ('Physiology', '1 | - - - - 0 | 1 - - - - 1'),
        ('Psychiatry', '1 | 1 - - - 1 | - - - - - 0'),
        ('Radio-diagnosis', '2 | - 1 - - 1 | 1 - - - - 1'),
        ('Radiotherapy', '0 | - - - - 0 | - - - - - 0'),
        ('Tuberculosis & Respiratory Diseases', '0 | - - - - 0 | - - - - - 0')],
     '23 | 6 5 1 0 12 | 9 2 0 0 0 11')]
# Total cells printed '-' although the line holds a seat (the line's Total Seats and category cells agree)
PRINT_GAPS = {(NAHAN, 'Community Medicine', 'GDO'), (CHAMBA, 'General Medicine', 'Direct'),
              (CHAMBA, 'Orthopedics', 'GDO')}

# p8 MMMC Management Quota (Resident Indians), Direct Quota: 'UR SC ST EWS PWD Total'
MGMT = [
    (1, 'Anatomy', '- 1 - - 1 2'), (2, 'Anesthesiology', '5 1 1 - - 7'), (3, 'Biochemistry', '2 - - - - 2'),
    (4, 'Community Medicine', '2 - - - - 2'), (5, 'Dermatology, Venrology and Leprosy', '1 - - - - 1'),
    (6, 'Forensic Medicine', '1 1 - - - 2'), (7, 'General Medicine', '4 - 1 - 1 6'),
    (8, 'General Surgery', '5 2 - - - 7'), (9, 'Microbiology', '2 - - - - 2'),
    (10, 'Obstetrics & Gynecology (OBG)', '3 - 1 - - 4'), (11, 'Ophthalmology', '1 - - - - 1'),
    (12, 'Orthopedics', '2 1 - - - 3'), (13, 'Oto-rhino-Laryngology (ENT)', '- - - - - 0'),
    (14, 'Pathology', '2 1 - - 1 4'), (15, 'Pediatrics', '3 - 1 - - 4'), (16, 'Pharmacology', '1 1 - - - 2'),
    (17, 'Physiology', '2 - - - - 2'), (18, 'Psychiatry', '- - - - - 0'), (19, 'Radio-diagnosis', '3 - - - - 3'),
    (20, 'Radiotherapy', '- - - - - 0'), (21, 'Tuberculosis & Respiratory Diseases', '- 1 - - - 1')]
MGMT_TOTAL = '39 9 4 0 3 55'

# p9 MMMC 15% NRI Quota Seats (Sr. No. as printed — 14 / 15 are swapped on the page)
NRI = [(1, 'Anatomy', 0), (2, 'Anaesthesia', 1), (3, 'Biochemistry', 0), (4, 'Comm. Medicine', 0),
       (5, 'Dermatology', 1), (6, 'Forensic Medicine', 0), (7, 'General Medicine', 2), (8, 'General Surgery', 1),
       (9, 'Microbiology', 0), (10, 'Obst. & Gynae', 1), (11, 'Ophthalmology', 1), (12, 'Orthopaedics', 1),
       (13, 'Oto-Rhino-Laryngology (ENT)', 1), (15, 'Paediatrics', 1), (14, 'Pharmacology', 0), (16, 'Pathology', 0),
       (17, 'Physiology', 0), (18, 'Psychiatry', 1), (19, 'Pulm. Medicine', 1), (20, 'Radio-Diagnosis', 2)]
NRI_TOTAL = 14
GRAND = 234   # not printed: 70 + 52 + 13 + 1 + 4 + 2 + 23 (State Quota) + 55 (Management) + 14 (NRI)

GDO_Q, DIR_Q, MGMT_Q, NRI_Q = 'In-service Quota (GDO)', 'State Quota (Direct)', 'Management Quota', 'NRI Quota'


def cell(s):
    return 0 if s in ('-', '_', '-*') else int(s)


# the stored PDF must be this notice (scanned; its OCR text is only good enough to identify it)
if hashlib.sha256(open(PDF, 'rb').read()).hexdigest() != SHA256:
    raise SystemExit('PDF is not the 09.11.2026 AMRU State Quota matrix this script was transcribed from — re-transcribe')
doc = fitz.open(PDF)
if len(doc) != 9:
    raise SystemExit(f'expected 9 pages, got {len(doc)}')
txt = clean(' '.join(p.get_text() for p in doc))
for need in ('State Quota Seat matrix for PG MD/MS', '09.11.2026', 'Management Quota (Resident Indians)', 'NRI'):
    if need not in txt:
        raise SystemExit(f'not the AMRU 09.11.2026 notice? missing {need!r}')

rows, checks, gaps = [], {}, set()


def add(college, printed, quota, cat, n, p):
    if printed not in COURSES:
        raise SystemExit(f'unknown speciality {printed!r}')
    if n:
        rows.append({'college': college, 'course': COURSES[printed], 'quota': quota, 'seats': n, 'section': 'mdms',
                     'category': cat, 'p': p})


for page, heading, college, lines, total in STATE:
    if clean(heading).split(' (')[0][:25] not in txt:
        raise SystemExit(f'heading not found on the PDF text layer: {heading!r}')
    acc = [0] * 12
    for printed, s in lines:
        parts = [p.split() for p in s.split('|')]
        if [len(p) for p in parts] != [1, 5, 6]:
            raise SystemExit(f'{college} / {printed}: bad line {s!r}')
        tot, g, d = parts
        gv, dv = [cell(x) for x in g[:4]], [cell(x) for x in d[:5]]
        for kind, vals, tcell in (('GDO', gv, g[4]), ('Direct', dv, d[5])):
            if tcell == '-*':
                if not sum(vals):
                    raise SystemExit(f'{college} / {printed}: -* on an empty {kind} group')
                gaps.add((college, printed, kind))
            elif sum(vals) != cell(tcell):
                raise SystemExit(f'{college} / {printed}: {kind} cells add to {sum(vals)}, Total {kind} {tcell}')
        if sum(gv) + sum(dv) != int(tot[0]):
            raise SystemExit(f'{college} / {printed}: GDO + Direct = {sum(gv) + sum(dv)}, Total Seats {tot[0]}')
        acc = [a + b for a, b in zip(acc, [int(tot[0])] + gv + [sum(gv)] + dv + [sum(dv)])]
        for c, n in zip(GDO_CATS, gv):
            add(college, printed, GDO_Q, c, n, page)
        for c, n in zip(DIR_CATS, dv):
            add(college, printed, DIR_Q, c, n, page)
    if total:
        want = [int(x) for x in total.replace('|', ' ').split()]
        checks[f'p{page} {college[:28]} Total line'] = (acc, want)
    checks[f'p{page} {college[:28]} seats'] = (sum(x['seats'] for x in rows if x['p'] == page and x['college'] == college),
                                               acc[0])
if gaps != PRINT_GAPS:
    raise SystemExit(f'print gaps changed: {gaps ^ PRINT_GAPS}')

acc = [0] * 6
for i, (sr, printed, s) in enumerate(MGMT, 1):
    v = [cell(x) for x in s.split()]
    if sr != i or len(v) != 6 or sum(v[:5]) != v[5]:
        raise SystemExit(f'MMMC management {sr} {printed}: {s!r}')
    acc = [a + b for a, b in zip(acc, v)]
    for c, n in zip(DIR_CATS, v[:5]):
        add(MMMC, printed, MGMT_Q, c, n, 8)
checks['p8 MMMC Management Quota Total line'] = (acc, [int(x) for x in MGMT_TOTAL.split()])

if sorted(sr for sr, _, _ in NRI) != list(range(1, 21)):
    raise SystemExit('NRI Sr. No. not 1…20')
for sr, printed, n in NRI:
    add(MMMC, printed, NRI_Q, '', n, 9)
checks['p9 MMMC NRI Quota Total'] = (sum(n for _, _, n in NRI), NRI_TOTAL)
checks['MATRIX (sum of every table)'] = (sum(x['seats'] for x in rows), GRAND)
for x in rows:
    del x['p']

cuts = load_cuts(CUTS, 'Himachal Pradesh')
fam = {GDO_Q: ('State Quota-Inservice$',), DIR_Q: ('State Quota$',), MGMT_Q: ('Management Quota$',),
       NRI_Q: ('NRI Quota$',)}
CAT = {'UR': ('GEN',), 'PWD': ('GEN-PH',), '': ('NRI',)}
out = build(rows, cuts, 'Himachal Pradesh', 'HP', lambda q: fam[q], lambda x: CAT.get(x['category'], (x['category'],)))
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
for name in (IGMC, TANDA, MANDI, NAHAN, HAMIRPUR, CHAMBA, MMMC):
    print(f'   {name}: {sum(r["seats"] for r in out if r["college_name"] == name)} seats,',
          {q: sum(r['seats'] for r in out if r['college_name'] == name and r['quota'] == q)
           for q in sorted({r['quota'] for r in out if r['college_name'] == name})})
