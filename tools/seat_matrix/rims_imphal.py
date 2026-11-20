"""RIMS Imphal (Regional Institute of Medical Sciences) MD/MS seat matrix 2026 -> one body
"RIMS Imphal — Institutional Seats" (authority rims_imphal, section state, round 1).

Source: "REVISED SEAT MATRIX FOR ADMISSION TO MD/MS COURSE FOR THE ACADEMIC SESSION 2026 AT RIMS, IMPHAL"
(inbox 1584, 1 page, signed Dean (Academics) 04/11/2026). The PDF is a SCAN (no text layer); the table below was
typed from a 130-dpi render and is pinned to the PDF's SHA-256 (a re-issued file stops the script: re-read it).

One table: subject x Sponsored (+ its reservation split) | RIMS Open (+ split) | Non-RIMS Open (+ split) | Total.
Printed totals: Sponsored 61, RIMS Open 17, Non-RIMS Open 5, Total 83. Every row's three blocks must add to its printed
Total and every block's reservation split must add to the block's number.
Quotas (RIMS's own wording): 'Sponsored (NE states)' = seats for candidates sponsored by the north-eastern state
governments; 'RIMS Open' = open seats for RIMS candidates; 'Non-RIMS Open' = open seats for others. These seats are
NOT in any 2025 state cut-off file (RIMS appears there only under MCC's All India Quota), so has_cutoff = False.
  /usr/bin/python3 tools/seat_matrix/rims_imphal.py <1584.pdf> <cutoffs2025.json> <out.json>
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import load_cuts, build, report

PDF, CUTS, OUT = sys.argv[1:4]
got = hashlib.sha256(open(PDF, 'rb').read()).hexdigest()
PINNED = 'eae9f9269badb64d7cf45b3e863499a5d3be43080106175ad6dd6581fc0192a2'
if got != PINNED:
    raise SystemExit(f'{PDF}: sha256 {got} — not the scan this reader was typed from (RIMS Imphal revised MD/MS matrix, 83 seats)')

COLLEGE = 'Regional Institute of Medical Sciences, Imphal'
BLOCKS = ('Sponsored (NE states)', 'RIMS Open', 'Non-RIMS Open')
PRINTED = {'Sponsored (NE states)': 61, 'RIMS Open': 17, 'Non-RIMS Open': 5, 'Total': 83}
# (Sl No, printed subject, approved course, sponsored split, RIMS open split, non-RIMS open split, printed total)
T = [
    (1, 'Anesthesiology', 'MD - Anaesthesiology', {'UR': 2, 'OBC': 2, 'SC': 1, 'EWS': 1}, {'UR': 2, 'OBC': 1}, {'UR': 1}, 10),
    (2, 'Anatomy', 'MD/MS - Anatomy', {'UR': 2, 'OBC': 1}, {}, {}, 3),
    (3, 'Biochemistry', 'MD - Biochemistry', {'UR': 2, 'OBC': 1}, {}, {}, 3),
    (4, 'Community Medicine', 'MD - Social & Preventive Medicine / Community Medicine', {'UR': 2, 'OBC': 1}, {}, {'UR': 1}, 4),
    (5, 'Dermatology & VL', 'MD - Dermatology', {'UR': 1}, {'UR': 1}, {}, 2),
    (6, 'Forensic Medicine & Toxicology', 'MD - Forensic Medicine', {'UR': 1}, {}, {}, 1),
    (7, 'Medicine', 'MD - General Medicine', {'UR': 2, 'OBC': 1, 'SC': 1}, {'UR': 2, 'OBC': 1}, {'UR': 1}, 8),
    (8, 'Microbiology', 'MD - Microbiology', {'UR': 2}, {}, {}, 2),
    (9, 'Obs & Gynae', 'MS - Obstetrics and Gynaecology', {'UR': 2, 'OBC': 2, 'SC': 1}, {'UR': 1, 'OBC': 1}, {}, 7),
    (10, 'Ophthalmology', 'MS - Ophthalmology', {'UR': 1}, {'UR': 1}, {}, 2),
    (11, 'Orthopaedics', 'MS - Orthopaedics', {'UR': 2, 'OBC': 1}, {'UR': 1}, {}, 4),
    (12, 'Otorhinolaryngology', 'MS - ENT (Otorhinolaryngology)', {'UR': 1, 'OBC': 1}, {'UR': 1}, {}, 3),
    (13, 'Pediatrics', 'MD - Paediatrics', {'UR': 1, 'OBC': 1}, {'UR': 1}, {}, 3),
    (14, 'Pathology', 'MD - Pathology', {'UR': 2, 'OBC': 1, 'SC': 1}, {}, {}, 4),
    (15, 'Pharmacology', 'MD - Pharmacology', {'UR': 1, 'OBC': 1}, {}, {}, 2),
    (16, 'Physiology', 'MD - Physiology', {'UR': 1, 'OBC': 1, 'SC': 1}, {}, {'UR': 1}, 4),
    (17, 'Physical Medicine & Rehabilitation', 'MD - Physical Medicine and Rehabilitation', {'UR': 1, 'OBC': 1}, {}, {}, 2),
    (18, 'Psychiatry', 'MD - Psychiatry', {'UR': 1}, {}, {}, 1),
    (19, 'Radiation Oncology', 'MD - Radiotherapy / Radiation Oncology', {'UR': 1, 'OBC': 1}, {}, {}, 2),
    (20, 'Radiodiagnosis', 'MD - Radio-Diagnosis', {'UR': 1, 'OBC': 1}, {'UR': 1}, {}, 3),
    (21, 'Respiratory Medicine', 'MD - Respiratory Medicine', {'UR': 1, 'OBC': 1}, {'UR': 1}, {}, 3),
    (22, 'Sports Medicine', 'MD - Sports Medicine', {'UR': 1}, {}, {}, 1),
    (23, 'Surgery', 'MS - General Surgery', {'UR': 3, 'OBC': 1, 'SC': 1}, {'UR': 1, 'OBC': 1}, {'UR': 1}, 8),
    (24, 'Transfusion Medicine', 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', {'UR': 1}, {}, {}, 1),
]
# printed block numbers per row (Sponsored, RIMS Open, Non-RIMS Open) — the split must add to these
NUMS = {1: (6, 3, 1), 2: (3, 0, 0), 3: (3, 0, 0), 4: (3, 0, 1), 5: (1, 1, 0), 6: (1, 0, 0), 7: (4, 3, 1), 8: (2, 0, 0),
        9: (5, 2, 0), 10: (1, 1, 0), 11: (3, 1, 0), 12: (2, 1, 0), 13: (2, 1, 0), 14: (4, 0, 0), 15: (2, 0, 0),
        16: (3, 0, 1), 17: (2, 0, 0), 18: (1, 0, 0), 19: (2, 0, 0), 20: (2, 1, 0), 21: (2, 1, 0), 22: (1, 0, 0),
        23: (5, 2, 1), 24: (1, 0, 0)}

if [t[0] for t in T] != list(range(1, 25)):
    raise SystemExit('Sl No must run 1..24')
if len({t[2] for t in T}) != len(T):
    raise SystemExit('a course appears twice')
for sno, raw, course, sp, ro, nr, tot in T:
    split = (sum(sp.values()), sum(ro.values()), sum(nr.values()))
    if split != NUMS[sno]:
        raise SystemExit(f'{raw}: reservation split {split} != printed {NUMS[sno]}')
    if sum(split) != tot:
        raise SystemExit(f'{raw}: blocks add to {sum(split)}, printed total {tot}')
checks = {f'{b} column = printed': (sum(NUMS[t[0]][i] for t in T), PRINTED[b]) for i, b in enumerate(BLOCKS)}
checks['Total = printed 83'] = (sum(t[6] for t in T), PRINTED['Total'])

rows = []
for sno, raw, course, *blocks, tot in T:
    for quota, split in zip(BLOCKS, blocks):
        for cat, n in split.items():
            rows.append({'college': COLLEGE, 'course': course, 'course_raw': raw, 'quota': quota, 'category': cat,
                         'seats': n, 'section': 'mdms', 'institute_type': 'Government Institute'})

cuts = load_cuts(CUTS, 'Manipur')          # none in 2025 — every row is reported as new
out = build(rows, cuts, 'Manipur', 'MN', lambda q: (q + '$',), lambda x: (x['category'],))
for o in out:
    o['new_in_round'] = 0
report(out, checks)
print('by course', {t[2]: t[6] for t in T})
json.dump({'rows': out, 'checks': {**{k: list(v) for k, v in checks.items()}, 'sha256': got}},
          open(OUT, 'w'), ensure_ascii=False, indent=1)
