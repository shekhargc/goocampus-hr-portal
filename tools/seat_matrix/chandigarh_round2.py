"""Chandigarh GMCH-32 NEET PG 2026 SECOND counselling State Quota seats → one Round 2 body
"Chandigarh — Round 2 — State Counselling" (authority gmch_chd, section state, round_no 2, list_type 'vacancy').

Source: "Seat Matrix for Second Counselling for State Quota seats of MD/MS Admission-2026", Government Medical College &
Hospital, Sector 32, Chandigarh (inbox 1854, 1 page). The PDF is a SCAN (no text layer) and the scan is rotated ~2.1°
(values sit below their course labels), so the table was read from a DESKEWED 300-dpi render (rotate by atan(68/1850)),
where every value sits inside its grid cell — the transcription below is pinned to the PDF's SHA-256 (a re-issued
file stops the script: re-read it).

One table: course × Gen | PwBD | OBC-NCL | SC | EWS, printed totals 52 | 4 | 6 | 8 | 4 (= 74). One college only.
Dermatology's EWS seat is printed "01* Reserved #": "# Seat has been kept reserved in compliance to interim order passed
by Hon'ble Punjab and Haryana High court, Chandigarh in CWP No. 37988 of 2026 Title 'Mihir Jain Vs. Union of India and
Ors.'" — it is KEPT in the seats (it is in the printed EWS total 4) and flagged in the body notes.

Names follow the 2025 Chandigarh cut-offs and tools/results/chandigarh.py (Round 1 results, authority gmch_chd):
college 'Government Medical College and Hospital, Chandigarh'; quota 'State Quota-IP Pool' (the only 2025 / Round 1
quota). Categories use the seat-matrix convention UR / OBC / SC / EWS and 'UR-PwD' for the separate PwBD column (2025
has GEN_PwD, i.e. the PwD seat is a general one); they bridge to 2025 GEN / GEN_PwD / OBC_NCL / SC / EWS.
There is NO Chandigarh Round 1 seat-matrix body, so new_in_round = 0 for every row.
  /usr/bin/python3 tools/seat_matrix/chandigarh_round2.py <1854.pdf> <cutoffs2025.json> <out.json>
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import load_cuts, build, report

PDF, CUTS, OUT = sys.argv[1:4]
SHA = '37441ed3b2a34582fe8477030a246ecb69bfd436c281141e98a8f786b3f6a6ae'
got = hashlib.sha256(open(PDF, 'rb').read()).hexdigest()
if got != SHA:
    raise SystemExit(f'{PDF}: sha256 {got} — not the scan this reader was typed from (GMCH-32 second counselling, 74 seats)')

COLLEGE = 'Government Medical College and Hospital, Chandigarh'
QUOTA = 'State Quota-IP Pool'
COLS = ('UR', 'UR-PwD', 'OBC', 'SC', 'EWS')          # printed Gen | PwBD | OBC-NCL | SC | EWS
PRINTED_TOTAL = (52, 4, 6, 8, 4)
# (Sr No, printed course, approved course, Gen, PwBD, OBC-NCL, SC, EWS) — read from the deskewed scan
T = [
    (1, 'Anaesthesiology', 'MD - Anaesthesiology', 8, 0, 0, 1, 0),
    (2, 'Anatomy', 'MD/MS - Anatomy', 0, 0, 0, 1, 0),
    (3, 'Biochemistry', 'MD - Biochemistry', 0, 0, 1, 1, 0),
    (4, 'Community Medicine', 'MD - Social & Preventive Medicine / Community Medicine', 3, 0, 1, 1, 0),
    (5, 'Dermatology', 'MD - Dermatology', 0, 0, 1, 0, 1),            # EWS "01* Reserved #" (court order)
    (6, 'Forensic Medicine', 'MD - Forensic Medicine', 1, 0, 1, 1, 0),
    (7, 'General Medicine', 'MD - General Medicine', 4, 0, 1, 0, 0),
    (8, 'General Surgery', 'MS - General Surgery', 4, 0, 1, 0, 0),     # PwBD cell printed blank
    (9, 'Microbiology', 'MD - Microbiology', 2, 1, 0, 1, 0),
    (10, 'Obstetrics & Gynecology', 'MS - Obstetrics and Gynaecology', 2, 1, 0, 0, 1),
    (11, 'Ophthalmology', 'MS - Ophthalmology', 3, 1, 0, 0, 0),
    (12, 'Orthopaedics', 'MS - Orthopaedics', 1, 1, 0, 0, 1),
    (13, 'OtoRhinoLaryngology', 'MS - ENT (Otorhinolaryngology)', 2, 0, 0, 0, 0),
    (14, 'Paediatrics', 'MD - Paediatrics', 5, 0, 0, 1, 0),
    (15, 'Pathology', 'MD - Pathology', 3, 0, 0, 1, 0),
    (16, 'Pharmacology', 'MD - Pharmacology', 2, 0, 0, 0, 0),
    (17, 'Physiology', 'MD - Physiology', 3, 0, 0, 0, 0),
    (18, 'Psychiatry', 'MD - Psychiatry', 3, 0, 0, 0, 1),
    (19, 'Radiodiagnosis', 'MD - Radio-Diagnosis', 1, 0, 0, 0, 0),
    (20, 'Radiotherapy', 'MD - Radiotherapy / Radiation Oncology', 2, 0, 0, 0, 0),
    (21, 'Transfusion Medicine', 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 3, 0, 0, 0, 0),
]
RESERVED = {('MD - Dermatology', 'EWS')}   # kept reserved (P&H High Court interim order, CWP 37988 of 2026)

if [t[0] for t in T] != list(range(1, 22)):
    raise SystemExit('Sr No must run 01..21')
if len({t[2] for t in T}) != len(T):
    raise SystemExit('a course appears twice')
col_tot = tuple(sum(t[3 + i] for t in T) for i in range(5))
checks = {f'{c} column = printed Total': (col_tot[i], PRINTED_TOTAL[i]) for i, c in enumerate(COLS)}
checks['all seats = 74'] = (sum(col_tot), sum(PRINTED_TOTAL))

rows = []
for sno, raw, course, *vals in T:
    for cat, n in zip(COLS, vals):
        if n:
            rows.append({'college': COLLEGE, 'course': course, 'course_raw': raw, 'quota': QUOTA, 'category': cat,
                         'seats': n, 'section': 'mdms', 'institute_type': 'Government Institute'})

cuts = load_cuts(CUTS, 'Chandigarh')
if COLLEGE not in {c['institute'] for c in cuts}:
    raise SystemExit(f'{COLLEGE!r} is not the 2025 Chandigarh cut-off institute name')
if {c['quota'] for c in cuts} != {QUOTA}:
    raise SystemExit(f"2025 Chandigarh quotas changed: {sorted({c['quota'] for c in cuts})}")
CAT = {'UR': ('GEN',), 'UR-PwD': ('GEN_PwD', 'GEN'), 'OBC': ('OBC_NCL', 'OBC'), 'SC': ('SC',), 'EWS': ('EWS',)}
out = build(rows, cuts, 'Chandigarh', 'CH', lambda q: (q + '$',), lambda x: CAT[x['category']])
for o in out:
    o['new_in_round'] = 0
report(out, checks)
print('reserved (court order, kept in seats):', [(r['course_name'], r['category'], r['seats']) for r in out
                                                  if (r['course_name'], r['category']) in RESERVED])
print('by course', {t[2]: sum(t[3:]) for t in T})
json.dump({'rows': out, 'checks': {**{k: list(v) for k, v in checks.items()}, 'sha256': got}},
          open(OUT, 'w'), ensure_ascii=False, indent=1)
