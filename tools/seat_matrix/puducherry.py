"""Puducherry PG Medical 2026-27 seat matrix (Health Secretariat letter No. 27209/Health/HS/2026-27 dt 06.11.2026 to
CENTAC, 5 pages, SCANNED — the text layer is unusable OCR) → standardised seat rows, bridged to Puducherry's 2025
(CENTAC) cut-offs. Run with /usr/bin/python3 (PyMuPDF):
    puducherry.py <matrix.pdf> <cutoffs2025.json> <out.json>
The numbers below were read off the page images and are checked against every total the PDF prints:
  p2  overview: course × college (PIMS / SMVMC / SVMC: Total, Govt Quota, Management quota — SVMC's is
      'Linguistic Minority'; IGMCRI: Total, Govt Quota, All India Quota) + 'Overall Govt. Quota Seats' column,
      TOTAL A / B / GRAND TOTAL lines and the footer '62+128+132+73 = 395; Govt 197; Management 161; AIQ 37'.
  p4-5 Government-quota category matrix (course × college: GEN OBC MBC SC BCM EBC ST BT vertical, FF PH EXM MSP
      horizontal — horizontal seats sit INSIDE the vertical ones, so they add no seats) + its TOTAL lines and the
      horizontal-reservation box (197 → FF 8, PH 10, EXM 2, MSP 2).
  p3  SVMC detail sheet (Total / Govt / Linguistic Minority (Telugu)) — same totals, but its Govt/minority split
      differs from p2 + p4-5 for 12 courses; p2 and p4-5 agree cell for cell, so they are used and p3's
      differences are printed (not stored).
Stored: Government Quota (197, per category), Management Quota (PIMS + SMVMC, 95), Management Quota-Telugu Minority
(SVMC, 66) = 358. IGMCRI's 37 All India Quota seats are MCC's (checked, not stored)."""
import json, os, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report

PDF, CUTS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
COLLEGES = {   # short name in the PDF → (2025 cut-off name, management quota as in the 2025 cut-offs)
    'PIMS': ('Puducherry Institute of Medical Sciences, Puducherry', 'Management Quota'),
    'SMVMC': ('Sri Manakula Vinayagar Medical College & Hospital, Puducherry', 'Management Quota'),
    'SVMC': ('Sri Venkateswaraa Medical College, Hospital & Research Centre, Puducherry',
             'Management Quota-Telugu Minority'),
    'IGMCRI': ('Indira Gandhi Medical College and Research Institute, Puducherry', None)}   # 2nd column = AIQ (MCC)
ORDER = ['PIMS', 'SMVMC', 'SVMC', 'IGMCRI']
COURSES = {   # printed course → approved course name (all section mdms)
    'MD - Anesthesiology': 'MD - Anaesthesiology', 'MD - D.V.L.': 'MD - Dermatology',
    'MD - Emergency Medicine': 'MD - Emergency Medicine', 'MD - ENT/Oto-Rhino-Laryngology': 'MS - ENT (Otorhinolaryngology)',
    'MD - General Medicine': 'MD - General Medicine', 'MS - General Surgery': 'MS - General Surgery',
    'MS - Obs. & Gyn.': 'MS - Obstetrics and Gynaecology', 'MS - Ophthalmology': 'MS - Ophthalmology',
    'MS - Orthopedics': 'MS - Orthopaedics', 'MD - Pediatrics': 'MD - Paediatrics', 'MD - Psychiatry': 'MD - Psychiatry',
    'MD - Radio Diagnosis': 'MD - Radio-Diagnosis',
    'MD - Pulmonary Medicine/Respiratory Medicine/ TB & Chest disease': 'MD - Respiratory Medicine',
    'MD - Anatomy': 'MD/MS - Anatomy', 'MD - Bio-Chemistry': 'MD - Biochemistry',
    'MD - Community Medicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'MD - Microbiology': 'MD - Microbiology', 'MD - Pathology': 'MD - Pathology', 'MD - Pharmacology': 'MD - Pharmacology',
    'MD - Physiology': 'MD - Physiology', 'MD Forensic medicine': 'MD - Forensic Medicine'}

# ---- p2 overview: course: overall govt | PIMS T G M | SMVMC T G M | SVMC T G M | IGMCRI T G AIQ
P2 = {'A': [
    ('MD - Anesthesiology', '18 | 6 3 3 | 12 6 6 | 13 7 6 | 4 2 2'),
    ('MD - D.V.L.', '8 | 3 1 2 | 5 3 2 | 4 2 2 | 3 2 1'),
    ('MD - Emergency Medicine', '2 | 0 0 0 | 3 1 2 | 3 1 2 | 0 0 0'),
    ('MD - ENT/Oto-Rhino-Laryngology', '7 | 3 1 2 | 6 3 3 | 3 2 1 | 3 1 2'),
    ('MD - General Medicine', '24 | 4 2 2 | 18 9 9 | 19 10 9 | 6 3 3'),
    ('MS - General Surgery', '22 | 6 3 3 | 13 7 6 | 19 9 10 | 6 3 3'),
    ('MS - Obs. & Gyn.', '13 | 2 1 1 | 6 3 3 | 11 6 5 | 7 3 4'),
    ('MS - Ophthalmology', '9 | 3 2 1 | 5 3 2 | 5 2 3 | 4 2 2'),
    ('MS - Orthopedics', '10 | 2 1 1 | 6 3 3 | 8 4 4 | 4 2 2'),
    ('MD - Pediatrics', '13 | 3 2 1 | 12 6 6 | 9 4 5 | 2 1 1'),
    ('MD - Psychiatry', '6 | 3 1 2 | 6 3 3 | 3 2 1 | 0 0 0'),
    ('MD - Radio Diagnosis', '10 | 3 2 1 | 8 4 4 | 9 4 5 | 0 0 0'),
    ('MD - Pulmonary Medicine/Respiratory Medicine/ TB & Chest disease', '5 | 3 2 1 | 3 1 2 | 2 1 1 | 2 1 1')],
    'B': [
    ('MD - Anatomy', '6 | 2 1 1 | 4 2 2 | 3 2 1 | 2 1 1'),
    ('MD - Bio-Chemistry', '4 | 2 1 1 | 3 1 2 | 2 1 1 | 2 1 1'),
    ('MD - Community Medicine', '9 | 4 2 2 | 3 1 2 | 4 2 2 | 8 4 4'),
    ('MD - Microbiology', '7 | 4 2 2 | 2 1 1 | 4 2 2 | 4 2 2'),
    ('MD - Pathology', '9 | 3 1 2 | 6 3 3 | 4 2 2 | 6 3 3'),
    ('MD - Pharmacology', '7 | 2 1 1 | 4 2 2 | 4 2 2 | 4 2 2'),
    ('MD - Physiology', '6 | 4 2 2 | 3 2 1 | 3 1 2 | 2 1 1'),
    ('MD Forensic medicine', '2 | 0 0 0 | 0 0 0 | 0 0 0 | 4 2 2')]}
P2_TOTALS = {'A': '147 | 41 21 20 | 103 52 51 | 108 54 54 | 41 20 21',
             'B': '50 | 21 10 11 | 25 12 13 | 24 12 12 | 32 16 16',
             'GRAND': '197 | 62 31 31 | 128 64 64 | 132 66 66 | 73 36 37'}
FOOTER = {'total': (395, (62, 128, 132, 73)), 'govt': (197, (31, 64, 66, 36)), 'mgmt': (161, (31, 64, 66)), 'aiq': (37, ())}

# ---- p4-5 Government quota by category: course (printed total): college (printed n): 12 cells, '-' = 0
VCATS = ['GEN', 'OBC', 'MBC', 'SC', 'BCM', 'EBC', 'ST', 'BT']
HCATS = ['FF', 'PH', 'EXM', 'MSP']
GQ = [
    ('MD - D.V.L.', 8, [('IGMCRI', 2, '1 - 1 - - - - - - - - -'), ('PIMS', 1, '1 - - - - - - - - - - -'),
                        ('SMVMC', 3, '2 - 1 - - - - - - - - -'), ('SVMC', 2, '1 - 1 - - - - - - - - -')]),
    ('MD - Emergency Medicine', 2, [('SMVMC', 1, '- - 1 - - - - - - - - -'), ('SVMC', 1, '1 - - - - - - - - - - -')]),
    ('MD - ENT/Oto-Rhino-Laryngology', 7, [('IGMCRI', 1, '1 - - - - - - - - - - -'), ('PIMS', 1, '- - 1 - - - - - - - - -'),
                                           ('SMVMC', 3, '2 - 1 - - - - - - - - -'), ('SVMC', 2, '1 - - 1 - - - - - - - -')]),
    ('MD - General Medicine', 24, [('IGMCRI', 3, '1 - 1 1 - - - - - 1 - -'), ('PIMS', 2, '1 - 1 - - - - - - - - -'),
                                   ('SMVMC', 9, '4 - 2 3 - - - - - 1 - -'), ('SVMC', 10, '5 - 3 2 - - - - 1 - - -')]),
    ('MS - General Surgery', 22, [('IGMCRI', 3, '2 - 1 - - - - - - - - -'), ('PIMS', 3, '2 - - 1 - - - - - - - -'),
                                  ('SMVMC', 7, '4 1 1 1 - - - - 1 - - -'), ('SVMC', 9, '4 2 1 2 - - - - - - - -')]),
    ('MS - Obs. & Gyn.', 13, [('IGMCRI', 3, '1 1 - 1 - - - - - - - -'), ('PIMS', 1, '- - 1 - - - - - - - - -'),
                              ('SMVMC', 3, '1 1 1 - - - - - - - - -'), ('SVMC', 6, '3 1 1 1 - - - - 1 - - -')]),
    ('MS - Ophthalmology', 9, [('IGMCRI', 2, '1 - 1 - - - - - - - - -'), ('PIMS', 2, '1 - - 1 - - - - - - - -'),
                               ('SMVMC', 3, '2 - - 1 - - - - - - - -'), ('SVMC', 2, '1 - 1 - - - - - - - - -')]),
    ('MS - Orthopedics', 10, [('IGMCRI', 2, '1 - - 1 - - - - - - - -'), ('PIMS', 1, '1 - - - - - - - - - - -'),
                              ('SMVMC', 3, '1 1 1 - - - - - - - - -'), ('SVMC', 4, '2 1 - 1 - - - - - - 1 -')]),
    ('MD - Pediatrics', 13, [('IGMCRI', 1, '1 - - - - - - - - - - -'), ('PIMS', 2, '1 1 - - - - - - - 1 - -'),
                             ('SMVMC', 6, '3 1 1 1 - - - - - - - 1'), ('SVMC', 4, '2 - 1 1 - - - - - 1 - -')]),
    ('MD - Psychiatry', 6, [('PIMS', 1, '- - 1 - - - - - - - - -'), ('SMVMC', 3, '2 - - 1 - - - - - - - -'),
                            ('SVMC', 2, '1 1 - - - - - - - - - -')]),
    ('MD - Radio Diagnosis', 10, [('PIMS', 2, '1 - - 1 - - - - - - - -'), ('SMVMC', 4, '2 1 1 - - - - - 1 - - -'),
                                  ('SVMC', 4, '2 - 1 1 - - - - - - - -')]),
    ('MD - Pulmonary Medicine/Respiratory Medicine/ TB & Chest disease', 5, [
        ('IGMCRI', 1, '- 1 - - - - - - - - - -'), ('PIMS', 2, '1 1 - - - - - - - - - -'),
        ('SMVMC', 1, '- - - 1 - - - - - - - -'), ('SVMC', 1, '1 - - - - - - - - - - -')]),
    ('MD - Anesthesiology', 18, [('IGMCRI', 2, '1 - - - - 1 - - - - - -'), ('PIMS', 3, '1 - - - 1 1 - - - - 1 -'),
                                 ('SMVMC', 6, '3 1 - - 1 - 1 - - 1 - -'), ('SVMC', 7, '3 1 - - 1 1 - 1 - 1 - -')]),
    ('MD - Bio-Chemistry', 4, [('IGMCRI', 1, '1 - - - - - - - - - - -'), ('PIMS', 1, '1 - - - - - - - - - - -'),
                               ('SMVMC', 1, '1 - - - - - - - - - - -'), ('SVMC', 1, '1 - - - - - - - - - - -')]),
    ('MD - Community Medicine', 9, [('IGMCRI', 4, '2 - 1 1 - - - - 1 - - -'), ('PIMS', 2, '1 - 1 - - - - - - 1 - -'),
                                    ('SMVMC', 1, '- - 1 - - - - - - - - -'), ('SVMC', 2, '1 - 1 - - - - - - - - -')]),
    ('MD Forensic medicine', 2, [('IGMCRI', 2, '1 - - 1 - - - - - - - -')]),
    ('MD - Microbiology', 7, [('IGMCRI', 2, '1 1 - - - - - - - 1 - -'), ('PIMS', 2, '1 - 1 - - - - - 1 - - -'),
                              ('SMVMC', 1, '1 - - - - - - - - - - -'), ('SVMC', 2, '1 - - 1 - - - - - - - -')]),
    ('MD - Pathology', 9, [('IGMCRI', 3, '1 - 1 1 - - - - - - - -'), ('PIMS', 1, '- - - 1 - - - - - - - 1'),
                           ('SMVMC', 3, '1 - 1 1 - - - - 1 - - -'), ('SVMC', 2, '1 1 - - - - - - - - - -')]),
    ('MD - Pharmacology', 7, [('IGMCRI', 2, '1 1 - - - - - - - - - -'), ('PIMS', 1, '1 - - - - - - - - - - -'),
                              ('SMVMC', 2, '1 - - 1 - - - - - 1 - -'), ('SVMC', 2, '1 - 1 - - - - - 1 - - -')]),
    ('MD - Physiology', 6, [('IGMCRI', 1, '1 - - - - - - - - - - -'), ('PIMS', 2, '1 - - 1 - - - - - - - -'),
                            ('SMVMC', 2, '1 1 - - - - - - - - - -'), ('SVMC', 1, '- - - 1 - - - - - - - -')]),
    ('MD - Anatomy', 6, [('IGMCRI', 1, '- - - - 1 - - - - - - -'), ('PIMS', 1, '- 1 - - - - - - - - - -'),
                         ('SMVMC', 2, '1 - - - - 1 - - - - - -'), ('SVMC', 2, '1 1 - - - - - - - 1 - -')])]
NONCLIN = {c for c, _ in P2['B']}
GQ_TOTALS = {'clinical': (147, '73 16 27 23 3 3 1 1 4 6 2 1'), 'non-clinical': (50, '25 6 8 9 1 1 0 0 4 4 0 1')}
HORIZ_BOX = {'FF': 8, 'PH': 10, 'EXM': 2, 'MSP': 2}   # 197 × 4% / 5% / 1% / 1%, rounded

# ---- p3 SVMC detail sheet: course: total govt telugu-minority
P3_SVMC = {'MD - Anesthesiology': (13, 6, 7), 'MD - D.V.L.': (4, 2, 2), 'MD - Emergency Medicine': (3, 2, 1),
           'MD - ENT/Oto-Rhino-Laryngology': (3, 1, 2), 'MD - General Medicine': (19, 9, 10),
           'MS - General Surgery': (19, 10, 9), 'MS - Obs. & Gyn.': (11, 5, 6), 'MS - Ophthalmology': (5, 3, 2),
           'MS - Orthopedics': (8, 4, 4), 'MD - Pediatrics': (9, 5, 4), 'MD - Psychiatry': (3, 1, 2),
           'MD - Radio Diagnosis': (9, 5, 4), 'MD - Pulmonary Medicine/Respiratory Medicine/ TB & Chest disease': (2, 1, 1),
           'MD - Anatomy': (3, 1, 2), 'MD - Bio-Chemistry': (2, 1, 1), 'MD - Community Medicine': (4, 2, 2),
           'MD - Microbiology': (4, 2, 2), 'MD - Pathology': (4, 2, 2), 'MD - Pharmacology': (4, 2, 2),
           'MD - Physiology': (3, 2, 1)}
P3_TOTALS = {'A': (108, 54, 54), 'B': (24, 12, 12), 'ALL': (132, 66, 66)}


def cells(s):
    return [0 if x == '-' else int(x) for x in s.split()]


def p2row(s):
    parts = s.split('|')
    if len(parts) != 5:
        raise SystemExit(f'bad p2 row {s!r}')
    overall = int(parts[0])
    cols = {k: tuple(cells(p)) for k, p in zip(ORDER, parts[1:])}
    if any(len(v) != 3 for v in cols.values()):
        raise SystemExit(f'bad p2 row {s!r}')
    return overall, cols


# the stored PDF must be this letter (scanned; its OCR text is only good enough to identify it)
doc = fitz.open(PDF)
txt = clean(' '.join(p.get_text() for p in doc))
for need in ('06.11.2026', 'CENTAC', 'Seat Matrix', '395', 'GOVERNMENT OF PUDUCHERRY', 'HORIZONTAL RESERVATION'):
    if need not in txt:
        raise SystemExit(f'not the 06.11.2026 Puducherry letter? missing {need!r}')
if len(doc) != 5:
    raise SystemExit(f'expected 5 pages, got {len(doc)}')
if set(COURSES) != {c for blk in P2.values() for c, _ in blk}:
    raise SystemExit('course map ≠ p2 course list')

checks = {}
# ---- p2: every row Total = Govt + other, Overall Govt = Σ govt, TOTAL A / B / GRAND per column, footer
p2 = {}
for blk, lines in P2.items():
    acc = [0] * 13
    for course, s in lines:
        overall, cols = p2row(s)
        for k, (t, g, o) in cols.items():
            if t != g + o:
                raise SystemExit(f'p2 {course} {k}: {t} != {g} + {o}')
        if overall != sum(g for _, g, _ in cols.values()):
            raise SystemExit(f'p2 {course}: overall govt {overall} != Σ govt')
        p2[course] = cols
        flat = [overall] + [x for k in ORDER for x in cols[k]]
        acc = [a + b for a, b in zip(acc, flat)]
    want = [int(x) for x in P2_TOTALS[blk].replace('|', ' ').split()]
    checks[f'p2 TOTAL {blk}'] = (acc, want)
grand = [int(x) for x in P2_TOTALS['GRAND'].replace('|', ' ').split()]
a = [int(x) for x in P2_TOTALS['A'].replace('|', ' ').split()]
b = [int(x) for x in P2_TOTALS['B'].replace('|', ' ').split()]
checks['p2 GRAND = A + B'] = ([x + y for x, y in zip(a, b)], grand)
col = lambda k, i: sum(p2[c][k][i] for c in p2)
checks['footer total 395'] = (sum(col(k, 0) for k in ORDER), FOOTER['total'][0])
checks['footer total by college'] = ([col(k, 0) for k in ORDER], list(FOOTER['total'][1]))
checks['footer govt 197'] = ([col(k, 1) for k in ORDER], list(FOOTER['govt'][1]))
checks['footer govt sum'] = (sum(FOOTER['govt'][1]), FOOTER['govt'][0])
checks['footer management 161'] = ([col(k, 2) for k in ORDER[:3]], list(FOOTER['mgmt'][1]))
checks['footer management sum'] = (sum(FOOTER['mgmt'][1]), FOOTER['mgmt'][0])
checks['footer AIQ 37 (IGMCRI, MCC — not stored)'] = (col('IGMCRI', 2), FOOTER['aiq'][0])

# ---- p4-5: each college line adds to its (n) over the vertical columns, each course to its (N), each block to TOTAL,
#      each (n) equals p2's Govt Quota cell, horizontal totals equal the box
rows, seen = [], set()
blk_acc = {'clinical': [0] * 12, 'non-clinical': [0] * 12}
for course, n_course, lines in GQ:
    if course not in COURSES:
        raise SystemExit(f'unknown course {course!r}')
    blk = 'non-clinical' if course in NONCLIN else 'clinical'
    s_course = 0
    for k, n, s in lines:
        v = cells(s)
        if len(v) != 12:
            raise SystemExit(f'{course} {k}: {len(v)} cells')
        if sum(v[:8]) != n:
            raise SystemExit(f'{course} {k}: vertical categories add to {sum(v[:8])}, printed ({n})')
        if sum(v[8:]) > n:
            raise SystemExit(f'{course} {k}: more horizontal than seats')
        if p2[course][k][1] != n:
            raise SystemExit(f'{course} {k}: govt quota p4-5 ({n}) != p2 ({p2[course][k][1]})')
        seen.add((course, k))
        s_course += n
        blk_acc[blk] = [x + y for x, y in zip(blk_acc[blk], v)]
        for cat, m in zip(VCATS, v[:8]):
            if m:
                rows.append({'college': COLLEGES[k][0], 'course': COURSES[course], 'quota': 'Government Quota',
                             'seats': m, 'section': 'mdms', 'category': cat})
    if s_course != n_course:
        raise SystemExit(f'{course}: colleges add to {s_course}, printed ({n_course})')
missing = [(c, k) for c in p2 for k in ORDER if p2[c][k][1] and (c, k) not in seen]
if missing:
    raise SystemExit(f'p2 govt seats with no p4-5 line: {missing}')
for blk, (n, s) in GQ_TOTALS.items():
    checks[f'p4-5 {blk} TOTAL ({n})'] = (blk_acc[blk], cells(s))
    checks[f'p4-5 {blk} vertical = ({n})'] = (sum(blk_acc[blk][:8]), n)
for i, h in enumerate(HCATS):
    checks[f'horizontal {h} (inside vertical, no extra seats)'] = (
        blk_acc['clinical'][8 + i] + blk_acc['non-clinical'][8 + i], HORIZ_BOX[h])

# ---- management / minority rows from p2 (no category printed → OPEN)
for course, cols in p2.items():
    for k in ORDER[:3]:
        m = cols[k][2]
        if m:
            rows.append({'college': COLLEGES[k][0], 'course': COURSES[course], 'quota': COLLEGES[k][1],
                         'seats': m, 'section': 'mdms', 'category': 'OPEN'})

# ---- p3 SVMC detail: same per-course totals and block totals; its Govt / minority split is reported, not used
checks['p3 SVMC course totals = p2'] = ([P3_SVMC.get(c, (0, 0, 0))[0] for c in p2], [p2[c]['SVMC'][0] for c in p2])
for c, (t, g, m) in P3_SVMC.items():
    if t != g + m:
        raise SystemExit(f'p3 SVMC {c}: {t} != {g} + {m}')
for blk, want in P3_TOTALS.items():
    cs = [c for c in P3_SVMC if blk == 'ALL' or (c in NONCLIN) == (blk == 'B')]
    checks[f'p3 SVMC TOTAL {blk}'] = ([sum(P3_SVMC[c][i] for c in cs) for i in range(3)], list(want))
diff = [f'{COURSES[c]} {p2[c]["SVMC"][1]}/{p2[c]["SVMC"][2]} vs p3 {g}/{m}'
        for c, (t, g, m) in P3_SVMC.items() if (g, m) != p2[c]['SVMC'][1:]]
print(f'NOTE p3 SVMC sheet splits Govt/Minority differently for {len(diff)} courses (p2 + p4-5 used):')
for d in diff:
    print('   ', d)

checks['stored seats (395 − 37 AIQ)'] = (sum(x['seats'] for x in rows), 358)

cuts = load_cuts(CUTS, 'Puducherry')
UCAT = {'GEN': 'UGE', 'OBC': 'UOB', 'MBC': 'UMB', 'SC': 'USC', 'BCM': 'UBM', 'EBC': 'UEB', 'ST': 'UST', 'BT': 'UBT'}
fam = {'Government Quota': ('Government Quota$',), 'Management Quota': ('Management Quota$',),
       'Management Quota-Telugu Minority': ('Management Quota-Telugu Minority$', 'Management Quota$')}
cat = lambda x: ('AGE', 'UGE') if x['category'] == 'OPEN' else (UCAT[x['category']], 'UGE')
out = build(rows, cuts, 'Puducherry', 'PY', lambda q: fam[q], cat)
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
for c in ORDER:
    name = COLLEGES[c][0]
    print(f'   {c}: {sum(r["seats"] for r in out if r["college_name"] == name)} seats,',
          {q: sum(r['seats'] for r in out if r['college_name'] == name and r['quota'] == q)
           for q in sorted({r['quota'] for r in out if r['college_name'] == name})})
