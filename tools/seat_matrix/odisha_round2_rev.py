"""Odisha NEET PG 2026-27 ROUND 2 seats — REVISED (PG (Medical) Counselling Committee, MKCG Brahmapur, 23.11.2026):
one Round 2 body = (A) the Round 1 seats vacant after Round-1 admission AND resignations + (B) the newly added seats.
Replaces odisha_round2.py's 18.11 inputs (that reader stays as written for the 18.11 PDFs).

  vacant.pdf — "Vacant Seats after Resignation Round-1 (Zero indicates virtual vacancy)", 8 pages, text layer
               (inbox 1943). One line per institute × course × subject × category: No of Seats | Adm R-1 & UGR-1 |
               Vacant for R-2 | Resignation R-1 | Balance after Resign-1. Sections DIRECT (232 / 76 / 156 / 6 / 162),
               IN-SERVICE, DNB (18 / 11 / 7 / 0 / 7) with printed ALL TOTAL lines. Seats stored = the Balance column;
               a 0 there = virtual vacancy (filled now, may be released by an upgrade) → kept out of the rows.
  added.pdf  — No. 104 "Provisional seat matrix … (ROUND - 2) - NEWLY ADDED SEATS ONLY - AFTER REDRESSAL OF
               GRIEVANCES", SCANNED (inbox 1941), transcribed below cell by cell (80 in-service + 79 direct = 159;
               same counts per college/course as No. 97, some categories changed).
Checks: every vacant line seats = admitted + vacant and balance = vacant + resigned; section sums = the printed ALL
TOTAL lines; with --r1 every vacant line's seats equal the loaded Round 1 body's; every added cell count = its
category list; every added row = its Total; every column = the TOTAL row.
  /usr/bin/python3 tools/seat_matrix/odisha_round2_rev.py <vacant.pdf> <added.pdf> <cutoffs2025.json> <out.json> [--r1 <r1_dump.json>]
"""
import collections
import hashlib
import json
import os
import re
import sys

import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import load_cuts, build, report

VAC, ADD, CUTS, OUT = sys.argv[1:5]
R1 = sys.argv[sys.argv.index('--r1') + 1] if '--r1' in sys.argv else None
SHA = {VAC: '531b09c3525dfa09ab2d0da10f1de622394619b98d57b0e3d7312b7f14eecb15', ADD: '9f26b6fff78e965f33db9a6407ba95453b4b5c915c2b0f44fb49556765b5569d'}
for path, sha in SHA.items():
    got = hashlib.sha256(open(path, 'rb').read()).hexdigest()
    if got != sha:
        raise SystemExit(f'{path}: sha256 {got} — not the PDF this reader was written for')

# vacant-list names → the Round 1 / 2025 standard names
INST = {
    'SCB MCH KATAKA': 'SCB Medical College, Cuttack',
    'MKCG MCH BERHAMPUR': 'Maharaja Krushna Chandra Gajapati Medical College and Hospital, Brahmapur',
    'VIMSAR BURLA': 'Veer Surendra Sai Institute of Medical Sciences and Research, Burla',
    'PGIMER BBSR': 'Postgraduate Institute of Medical Education & Research and Capital Hospital, Bhubaneswar',
    'AHRCC KATAKA': 'Acharya Harihar Post Graduate Institute of Cancer, Cuttack',
    'FM MCH BALESWAR': 'Fakir Mohan Medical College and Hospital, Balasore, Odisha',
    'PRM MCH BARIPADA': 'Pandit Raghunath Murmu Medical College and Hospital, Baripada, Mayurbhanj, Odisha',
    'BB MCH BALANGIR': 'Bhima Bhoi Medical College and Hospital, Balangir, Odisha',
    'HI-TECH MCH BBSR': 'Hi-Tech Medical College & Hospital, Bhubaneswar',
    'HI-TECH MCH RKL': 'Hi-Tech Medical College & Hospital, Rourkela',
    'DRIEMS KATAKA': 'DRIEMS Institute Of Health Sciences And Hospital, Tangi, Odisha',
    'HITECH-BBSR-MGT': 'Hi-Tech Medical College & Hospital, Bhubaneswar',
    'HITECH-RKL-MGT': 'Hi-Tech Medical College & Hospital, Rourkela',
    'DRIEMS-KATAKA-MGT': 'DRIEMS Institute Of Health Sciences And Hospital, Tangi, Odisha',
    'S J MCH PURI': 'Shri Jagannath Medical College and Hospital, Puri, Odisha',
    'SLN MCH KORAPUT': 'Saheed Laxman Nayak Medical College and Hospital, Koraput, Odisha'}
SUBJ = {'ANATOMY': 'MD/MS - Anatomy', 'PHYSIOLOGY': 'MD - Physiology', 'BIOCHEMISTRY': 'MD - Biochemistry',
        'PHARMACOLOGY': 'MD - Pharmacology', 'FMT': 'MD - Forensic Medicine', 'PATHOLOGY': 'MD - Pathology',
        'MICROBIOLOGY': 'MD - Microbiology', 'COMM MEDICINE': 'MD - Social & Preventive Medicine / Community Medicine',
        'GEN MEDICINE': 'MD - General Medicine', 'PEDIATRICS': 'MD - Paediatrics', 'PSYCHIATRY': 'MD - Psychiatry',
        'RESP MEDICINE': 'MD - Respiratory Medicine', 'SKIN VD (DVL)': 'MD - Dermatology',
        'TRANSF MEDICINE': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
        'OBST & GYN': 'MS - Obstetrics and Gynaecology', 'GEN SURGERY': 'MS - General Surgery',
        'ORTHOPAEDICS': 'MS - Orthopaedics', 'OPHTHALMOLOGY': 'MS - Ophthalmology', 'ENT': 'MS - ENT (Otorhinolaryngology)',
        'ANESTHESIOLOGY': 'MD - Anaesthesiology', 'RADIODIAGNOSIS': 'MD - Radio-Diagnosis',
        'RADIOTHERAPY': 'MD - Radiotherapy / Radiation Oncology'}
DNB_SUBJ = {'GEN MEDICINE': 'DNB - General Medicine (Post-MBBS)', 'OBST & GYN': 'DNB - Obstetrics and Gynaecology (Post-MBBS)',
            'GEN SURGERY': 'DNB - General Surgery (Post-MBBS)', 'PEDIATRICS': 'DNB - Paediatrics (Post-MBBS)',
            'OPHTHALMOLOGY': 'DNB - Ophthalmology (Post-MBBS)', 'RESP MEDICINE': 'DNB - Respiratory Medicine (Post-MBBS)',
            'ANESTHESIOLOGY': 'DNB - Anaesthesiology (Post-MBBS)'}
CAT_SUFFIX = {'ES': 'ES', 'GC': 'GC', 'PWD': 'PwD'}


def norm_cat(c):
    base, _, sub = c.partition('-')
    if base not in ('UR', 'SC', 'ST', 'SEBC', 'EWS') or (sub and sub not in CAT_SUFFIX):
        raise SystemExit(f'unknown category {c!r}')
    return base + ('-' + CAT_SUFFIX[sub] if sub else '')


# ── (A) vacant list, from the text layer by column position ──
def read_vacant(path):
    rows = []
    for pno, pg in enumerate(fitz.open(path), 1):
        ws = pg.get_text('words')
        srt = sorted(ws, key=lambda w: w[0])
        marks = []
        for w in ws:
            if w[4] in ('CANDIDATES', 'SEATS') and w[1] > 95:
                line = ' '.join(x[4] for x in srt if abs(x[1] - w[1]) < 2)
                val = 'DNB' if line.startswith('DNB') else line.split(' CANDIDATES')[0].replace('-', '').strip()
                marks.append({'y': w[1], 'mark': 'SECT', 'val': val})
            if w[4] == 'ALL':
                marks.append({'y': w[1], 'mark': 'TOTAL',
                              'val': [int(x[4]) for x in srt if abs(x[1] - w[1]) < 3 and x[4].isdigit()]})
        anchors = []
        for c in (w for w in ws if 125 <= w[0] < 163 and w[4] in ('MD/MS', 'DNB')):
            y = c[1]
            get = lambda a, b: ' '.join(x[4] for x in srt if a <= x[0] < b and abs(x[1] - y) < 2.5)
            a = {'y': y, 'page': pno, 'inst': get(0, 125), 'course': c[4], 'subj': get(180, 270), 'cat': get(270, 330),
                 'seats': get(330, 365), 'adm': get(365, 400), 'vac': get(400, 440), 'res': get(440, 480),
                 'bal': get(480, 540)}
            for key, (lo, hi) in (('bal', (480, 540)), ('vac', (400, 440)), ('adm', (365, 400)), ('res', (440, 480))):
                if not a[key]:   # a number drawn a little off its line
                    cands = [x for x in ws if lo <= x[0] < hi and x[4].isdigit() and abs(x[1] - y) < 7]
                    if cands and key in ('bal', 'vac'):
                        a[key] = min(cands, key=lambda x: abs(x[1] - y))[4]
            anchors.append(a)
        rows += sorted(anchors + marks, key=lambda a: a['y'])
    return rows


rows, checks, virtual = [], {}, collections.Counter()
sect, sums = None, collections.defaultdict(lambda: [0, 0, 0, 0, 0])
vac_lines = []
for r in read_vacant(VAC):
    if r.get('mark') == 'SECT':
        sect = r['val']; continue
    if r.get('mark') == 'TOTAL':
        checks[f'Vacant {sect} | seats'] = (sums[sect][0], r['val'][0])
        checks[f'Vacant {sect} | admitted'] = (sums[sect][1], r['val'][1])
        checks[f'Vacant {sect} | vacant'] = (sums[sect][2], r['val'][2])
        checks[f'Vacant {sect} | resigned'] = (sums[sect][3], r['val'][3])
        checks[f'Vacant {sect} | balance'] = (sums[sect][4], r['val'][4])
        continue
    seats, adm, vac0, res, vac = (int(r[k] or 0) for k in ('seats', 'adm', 'vac', 'res', 'bal'))
    if seats != adm + vac0 or vac != vac0 + res:
        raise SystemExit(f'vacant line p{r["page"]} {r["inst"]} {r["subj"]} {r["cat"]}: {seats}/{adm}/{vac0}/{res}/{vac}')
    s = sums[sect]; s[0] += seats; s[1] += adm; s[2] += vac0; s[3] += res; s[4] += vac
    if r['inst'] not in INST:
        raise SystemExit(f'unknown institute {r["inst"]!r}')
    dnb = r['course'] == 'DNB'
    subj = (DNB_SUBJ if dnb else SUBJ).get(r['subj'])
    if not subj:
        raise SystemExit(f'unknown subject {r["subj"]!r} ({r["course"]})')
    mgt = r['inst'].endswith('-MGT')
    quota = 'DNB Quota' if dnb else (('Management Quota (In-service)' if mgt else 'In-service Quota')
                                     if sect == 'INSERVICE' else ('Management Quota' if mgt else 'State Quota'))
    # Round 1 stores the private MGT columns with no category (counts only)
    cat = '' if mgt else norm_cat(r['cat'])
    vac_lines.append({'college': INST[r['inst']], 'course': subj, 'quota': quota, 'category': cat, 'r1_seats': seats})
    if vac == 0:
        virtual[sect] += 1
        continue
    rows.append({'college': INST[r['inst']], 'course': subj, 'quota': quota, 'seats': vac,
                 'section': 'dnb' if dnb else 'mdms', 'category': cat, 'new_in_round': 0})
checks['virtual_vacancy_rows'] = dict(virtual)

# ── (B) No. 104 (23.11, after grievances) newly added seats (scanned), transcribed. Columns: SCB VIMSAR PGIMER AHRCC FM PRM BB SLN PMP SLS GMCH DD
ADD_COLS = ['SCB', 'VIMSAR', 'PGIMER', 'AHRCC', 'FM', 'PRM', 'BB', 'SLN', 'PMP', 'SLS', 'GMCH', 'DD']
ADD_COLLEGE = {'SCB': INST['SCB MCH KATAKA'], 'VIMSAR': INST['VIMSAR BURLA'], 'PGIMER': INST['PGIMER BBSR'],
               'AHRCC': INST['AHRCC KATAKA'], 'FM': INST['FM MCH BALESWAR'], 'PRM': INST['PRM MCH BARIPADA'],
               'BB': INST['BB MCH BALANGIR'], 'SLN': INST['SLN MCH KORAPUT'],
               # new MD/MS colleges in 2026 (not in the 2025 cut-offs) — names to be confirmed against the College DB
               'PMP': 'Pabitra Mohan Pradhan Medical College and Hospital, Talcher, Odisha',
               'SLS': 'Swami Laxmanananda Saraswati Government Medical College and Hospital, Phulbani, Odisha',
               'GMCH': 'Government Medical College and Hospital, Sundargarh, Odisha',
               'DD': 'Dharanidhar Medical College and Hospital, Keonjhar, Odisha'}
ADD_COURSE = {'Anatomy': 'ANATOMY', 'Physiology': 'PHYSIOLOGY', 'Biochemistry': 'BIOCHEMISTRY',
              'Pharmacology': 'PHARMACOLOGY', 'Forensic Medicine': 'FMT', 'Pathology': 'PATHOLOGY',
              'Microbiology': 'MICROBIOLOGY', 'Community Medicine': 'COMM MEDICINE', 'General Medicine': 'GEN MEDICINE',
              'Pediatrics': 'PEDIATRICS', 'Psychiatry': 'PSYCHIATRY', 'Respiratory Medicine': 'RESP MEDICINE',
              'Skin & VD [DVL]': 'SKIN VD (DVL)', 'Transfusion Medicine': 'TRANSF MEDICINE', 'Obst. & Gyn.': 'OBST & GYN',
              'General Surgery': 'GEN SURGERY', 'Orthopaedics': 'ORTHOPAEDICS', 'Ophthalmology': 'OPHTHALMOLOGY',
              'ENT': 'ENT', 'Anesthesiology': 'ANESTHESIOLOGY', 'Radiodiagnosis': 'RADIODIAGNOSIS',
              'Radiotherapy': 'RADIOTHERAPY'}
# per course: "college=list; …" | printed Total
ADD_IN_SERVICE = """
Anatomy              | FM=1-UR; PMP=1-SC(PwD); SLS=1-ST | 3
Physiology           | FM=1-UR; PRM=1-ST | 2
Biochemistry         | BB=1-UR; SLN=1-SEBC | 2
Pharmacology         | FM=1-SC; PRM=1-UR; BB=1-UR; PMP=1-ST; SLS=1-UR; GMCH=1-UR | 6
Forensic Medicine    | PRM=1-UR; BB=1-UR; SLN=1-ST(ES); DD=1-SC | 4
Pathology            | FM=1-ST,1-UR; BB=1-UR; SLN=1-UR; GMCH=1-SEBC; DD=1-ST(GC),1-UR | 7
Microbiology         | BB=1-SEBC(GC),1-UR; SLN=1-SC | 3
Community Medicine   | FM=1-SC; PRM=1-UR; BB=1-SC,1-UR; SLN=1-UR; PMP=1-UR; SLS=1-UR; GMCH=1-ST; DD=1-SEBC,1-UR | 10
General Medicine     | FM=2-UR; PRM=1-SEBC; BB=1-ST; PMP=1-UR(GC); SLS=1-UR; GMCH=1-SC; DD=1-ST,1-UR | 9
Pediatrics           | PRM=1-ST; PMP=1-UR; SLS=1-SEBC; DD=1-SC | 4
Psychiatry           | | 0
Respiratory Medicine | PGIMER=1-SC | 1
Skin & VD [DVL]      | SCB=1-UR; SLN=1-UR(PwD) | 2
Transfusion Medicine | | 0
Obst. & Gyn.         | BB=1-ST; PMP=1-ST; GMCH=1-UR; DD=1-UR | 4
General Surgery      | PGIMER=1-UR; FM=1-ST,1-UR; SLS=1-SC; GMCH=1-UR(ES) | 5
Orthopaedics         | FM=1-SC; PRM=1-UR(GC); PMP=1-UR; SLS=1-ST; DD=1-SEBC | 5
Ophthalmology        | SCB=1-UR; VIMSAR=1-SC; SLN=1-UR | 3
ENT                  | SCB=1-ST | 1
Anesthesiology       | AHRCC=1-ST; PRM=1-SC; BB=1-UR; PMP=1-SEBC; DD=1-UR | 5
Radiodiagnosis       | SCB=1-SEBC; VIMSAR=1-UR; AHRCC=1-UR(PwD) | 3
Radiotherapy         | VIMSAR=1-ST(PwD) | 1
TOTAL                | SCB=4; VIMSAR=3; PGIMER=2; AHRCC=2; FM=11; PRM=8; BB=11; SLN=7; PMP=8; SLS=7; GMCH=6; DD=11 | 80
"""
ADD_DIRECT = """
Anatomy              | BB=1-ST; PMP=1-UR | 2
Physiology           | FM=1-UR; SLN=1-ST; PMP=1-SEBC | 3
Biochemistry         | SLN=1-UR | 1
Pharmacology         | FM=1-ST,1-UR; PRM=1-UR; BB=1-UR; SLN=1-UR(PwD); SLS=1-SC | 6
Forensic Medicine    | FM=1-SEBC; PRM=1-UR; PMP=1-SC(PwD); DD=1-ST,1-UR | 5
Pathology            | AHRCC=1-UR; FM=1-ST(ES),1-UR; PRM=1-UR; BB=1-SC; SLN=1-ST; GMCH=1-UR; DD=1-SEBC | 8
Microbiology         | BB=1-UR; SLN=1-SC | 2
Community Medicine   | FM=1-UR; PRM=1-UR; BB=1-ST(PwD),1-UR; SLN=1-SEBC; PMP=1-UR; SLS=1-ST(GC); GMCH=1-SC; DD=1-UR | 9
General Medicine     | PGIMER=1-SC; FM=1-SC,1-UR; PRM=1-UR; BB=1-SEBC,1-UR; PMP=1-ST; SLS=1-UR(ES); GMCH=1-UR; DD=1-ST | 10
Pediatrics           | PGIMER=1-UR; SLS=1-UR; GMCH=1-ST; DD=1-SC | 4
Psychiatry           | SCB=1-SC | 1
Respiratory Medicine | | 0
Skin & VD [DVL]      | SCB=1-UR; SLS=1-SEBC; DD=1-UR | 3
Transfusion Medicine | | 0
Obst. & Gyn.         | SCB=1-ST; PGIMER=1-ST; BB=1-UR(GC); PMP=1-SC; DD=1-UR(PwD) | 5
General Surgery      | FM=1-SC,1-UR; PRM=1-ST; SLS=1-UR | 4
Orthopaedics         | PRM=1-SEBC(ES); PMP=1-ST; SLS=1-UR; DD=1-UR | 4
Ophthalmology        | BB=1-UR; SLN=1-UR; DD=1-SC | 3
ENT                  | PRM=1-ST | 1
Anesthesiology       | AHRCC=1-UR(GC); BB=1-ST; PMP=1-UR; GMCH=1-SEBC; DD=1-ST | 5
Radiodiagnosis       | VIMSAR=2-UR; AHRCC=1-SEBC | 3
Radiotherapy         | | 0
TOTAL                | SCB=3; VIMSAR=2; PGIMER=3; AHRCC=3; FM=11; PRM=8; BB=11; SLN=7; PMP=8; SLS=7; GMCH=5; DD=11 | 79
"""
TOKEN = re.compile(r'(\d+)-(UR|SC|ST|SEBC|EWS)(?:\((GC|ES|PwD)\))?$')


def cat_list(s):
    out = collections.Counter()
    for tok in s.split(','):
        m = TOKEN.match(tok.strip())
        if not m:
            raise SystemExit(f'bad category token {tok!r}')
        out[m.group(2) + ('-' + m.group(3) if m.group(3) else '')] += int(m.group(1))
    return out


for label, text, quota in (('In-service', ADD_IN_SERVICE, 'In-service Quota'), ('Direct', ADD_DIRECT, 'State Quota')):
    col, tot = collections.Counter(), 0
    for line in text.strip().splitlines():
        name, cells, total = [x.strip() for x in line.split('|')]
        parts = [p.strip() for p in cells.split(';') if p.strip()]
        if name == 'TOTAL':
            for p in parts:
                c, n = p.split('=')
                checks[f'Added {label} | {c}'] = (col[c], int(n))
            checks[f'Added {label} | Total'] = (tot, int(total))
            continue
        course = SUBJ[ADD_COURSE[name]]
        row = 0
        for p in parts:
            c, lst = p.split('=', 1)
            if c not in ADD_COLS:
                raise SystemExit(f'unknown added-seat column {c!r}')
            for cat, n in cat_list(lst).items():
                rows.append({'college': ADD_COLLEGE[c], 'course': course, 'quota': quota, 'seats': n,
                             'section': 'mdms', 'category': cat, 'new_in_round': n})
                col[c] += n; row += n
        if row != int(total):
            raise SystemExit(f'Added {label} {name}: cells add to {row}, printed Total {total}')
        tot += row

# ── cross-check (A) against the loaded Round 1 body ──
if R1:
    r1 = collections.Counter()
    for x in json.load(open(R1))['rows']:
        r1[(x['college_name'], x['course_name'], x['quota'], x['category'])] += x['seats']
    want = collections.Counter()
    for v in vac_lines:
        want[(v['college'], v['course'], v['quota'], v['category'])] += v['r1_seats']
    diff = {' | '.join(k): (n, r1.get(k, 0)) for k, n in want.items() if r1.get(k, 0) != n}
    checks['vacant list vs Round 1 body (lines differing)'] = (len(diff), 0)
    if diff:
        print('vacant list seats vs Round 1 body (vacant, R1):')
        for k, v in sorted(diff.items()):
            print('   ', k, v)

# merge repeats (same college × course × quota × category): seats = vacant + added, new_in_round = the added part
agg = collections.OrderedDict()
for x in rows:
    k = (x['college'], x['course'], x['quota'], x['category'])
    if k in agg:
        agg[k]['seats'] += x['seats']; agg[k]['new_in_round'] += x['new_in_round']
    else:
        agg[k] = dict(x)
rows = list(agg.values())

FAMILY = {'State Quota': ('Government Quota$',), 'In-service Quota': ('Government Quota-Inservice',),
          'Management Quota': ('Management Quota$',), 'Management Quota (In-service)': ('Management Quota-Inservice',),
          'DNB Quota': ('DNB',)}
HORIZONTAL = {'GC': ('GCH', 'GC'), 'ES': ('ES',), 'PwD': ('PH',)}


def cat_match(x):
    if not x['category']:
        return ()
    base, _, sub = x['category'].partition('-')
    return HORIZONTAL.get(sub, ()) + (base,)


cuts = load_cuts(CUTS, 'Odisha')
out = build(rows, cuts, 'Odisha', 'OD', lambda q: FAMILY[q], cat_match)
for o, x in zip(out, rows):
    o['new_in_round'] = x['new_in_round']
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, {k: v for k, v in checks.items() if isinstance(v, tuple)})
print('virtual-vacancy lines (0, not stored):', dict(virtual))
print('vacant seats:', sum(x['seats'] - x['new_in_round'] for x in rows),
      '| newly added:', sum(x['new_in_round'] for x in rows))
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'dnb')})
