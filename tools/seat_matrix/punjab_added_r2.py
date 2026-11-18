"""Punjab (BFUHS) NEET PG 2026 — newly approved seats added for the 2nd round (Public Notice 03 BFUHS/Admin/PG/2026/607,
18.11.2026) → a CHECKED RECORD (not seat-matrix rows): Punjab has no seat-matrix body on the site yet (its Round 1
matrix was never loaded), so the 42 added seats are kept by college × speciality × quota / category for when the
Punjab matrix (Round 1 or Round 2) is loaded — then they can be checked off as new_in_round.

The notice has three college tables (text layer):
  GGS Medical College Faridkot / Dr. B.R. Ambedkar SIMS Mohali — Speciality | Total increased | AIQ | State Quota |
     IP | SC | BC   (IP + SC + BC = State Quota; IP = institutional preference / general)
  Adesh IMSR Bathinda (private) — Speciality | Total intake | General Merit (50%): IP SC BC PWD(IP) Total |
     Open Merit (All India basis): Open SC BC PWD Total   (General + Open = Total intake)
Checks: every row adds up both ways. AIQ seats go to MCC, not to Punjab's state counselling.
  /usr/bin/python3 tools/seat_matrix/punjab_added_r2.py <notice.pdf> <out.json>
"""
import hashlib
import json
import re
import sys

import fitz

PDF, OUT = sys.argv[1:3]
SHA = 'f02956caf0b66042b8d3bf17a98fe13bb25e3624881492357099f24dcd8c56f2'
if hashlib.sha256(open(PDF, 'rb').read()).hexdigest() != SHA:
    raise SystemExit('not the notice this reader was written for (re-check it)')
text = ' '.join(fitz.open(PDF)[0].get_text().split())

COLLEGES = {'faridkot': 'Guru Govind Singh Medical College, Faridkot',
            'mohali': 'Dr. B.R. Ambedkar State Institute of Medical Sciences, Mohali',
            'adesh': 'Adesh Institute of Medical Sciences & Research, Bhatinda'}
COURSE = {'IHBT': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
          'Peadiatrics': 'MD - Paediatrics', 'Physiology': 'MD - Physiology', 'Pharmacology': 'MD - Pharmacology',
          'Anatomy': 'MD/MS - Anatomy', 'Biochemistry': 'MD - Biochemistry', 'Pathology': 'MD - Pathology',
          'General Medicine': 'MD - General Medicine', 'Psychiatric': 'MD - Psychiatry',
          'General Surgery': 'MS - General Surgery', 'Orthopaedics': 'MS - Orthopaedics'}

i_f = text.index('Guru Gobind Singh Medical College Faridkot')
i_m = text.index('Dr. B. R. Ambedkar State Institute')
i_a = text.index('Adesh Institute of Medical Sciences')
i_end = text.index('Sd/-')
blocks = {'faridkot': text[i_f:i_m], 'mohali': text[i_m:i_a], 'adesh': text[i_a:i_end]}
NAME = '|'.join(sorted((re.escape(k) for k in COURSE), key=len, reverse=True))

rec, problems = [], []
for key in ('faridkot', 'mohali'):
    for m in re.finditer(rf'({NAME}) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+)', blocks[key]):
        name, tot, aiq, state, ip, sc, bc = m.group(1), *map(int, m.groups()[1:])
        if aiq + state != tot or ip + sc + bc != state:
            problems.append((key, name, m.groups()))
        rec.append({'college': COLLEGES[key], 'course': COURSE[name], 'total': tot, 'aiq': aiq, 'state_quota': state,
                    'state_split': {'IP': ip, 'SC': sc, 'BC': bc}})
for m in re.finditer(rf'({NAME}) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+)', blocks['adesh']):
    name, tot, g_ip, g_sc, g_bc, g_pwd, g_tot, o_open, o_sc, o_bc, o_pwd, o_tot = m.group(1), *map(int, m.groups()[1:])
    if g_ip + g_sc + g_bc + g_pwd != g_tot or o_open + o_sc + o_bc + o_pwd != o_tot or g_tot + o_tot != tot:
        problems.append(('adesh', name, m.groups()))
    rec.append({'college': COLLEGES['adesh'], 'course': COURSE[name], 'total': tot,
                'general_merit': {'IP': g_ip, 'SC': g_sc, 'BC': g_bc, 'PWD(IP)': g_pwd, 'total': g_tot},
                'open_merit_all_india': {'Open': o_open, 'SC': o_sc, 'BC': o_bc, 'PWD': o_pwd, 'total': o_tot}})
if problems:
    raise SystemExit(f'rows that do not add up: {problems}')
by = {c: sum(r['total'] for r in rec if r['college'] == c) for c in COLLEGES.values()}
state = sum(r.get('state_quota', 0) for r in rec) + sum(r['total'] for r in rec if r['college'] == COLLEGES['adesh'])
out = {'notice': 'BFUHS Public Notice 03 BFUHS/Admin/PG/2026/607 (18.11.2026) — inbox 1790, news #368',
       'rows': rec, 'total_added': sum(r['total'] for r in rec), 'by_college': by,
       'aiq_part_to_mcc': sum(r.get('aiq', 0) for r in rec), 'punjab_counselling_part': state,
       'note': 'Punjab has no seat-matrix body loaded; keep for the Punjab Round 1 / Round 2 matrix (new_in_round).'}
json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False), '| rows', len(rec))
