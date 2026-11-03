"""Assam (DME) "PROVISIONAL MERIT LIST FOR ASSAM STATE QUOTA SEATS (NEET-PG, 2026)" + its notices -> rank-bridge rows.
Usage: /usr/bin/python3 read_dme_assam.py <merit.pdf> <inclusion_notice.pdf> <nbems2026.json> <out.json>
Merit list (79 pages, text layer): page 1 = notice, then one line per candidate in merit order — Roll Number, Name of
Candidate, Gender, Category, NEET-PG 2026 Score, NEET-PG 2026 Rank, State in Permanent Address, MBBS State. Lines are
cut at each roll number; only roll, category, score and rank are read — the name is never read into the output (the
tokens between roll and gender are skipped). No state rank is printed: state_rank = position in the list (the DME's
own notices number it that way, e.g. '87-A').
Notices applied (an 'n-A' rank = placed right after n; stored as integer n, a tie — same rule as Tamil Nadu addenda):
  - 'Notice (Inclusion in Assam State NEET-PG-2026 merit list)' 17.10.2026: one table, SL/roll/name/category/total
    marks/ASSAM STATE RANK/NEET AI RANK → each line added (roll not in the list).
  - 'Notice (Revised Merit Position)' 29.10.2026 (scanned, 3 lines, typed in REVISED below): in-service candidates
    moved to a new state rank with their revised (incentive) score.
Checks: every roll in NBEMS 2026, printed rank = NBEMS AIR and score = NBEMS score for every merit-list line, AIR
strictly ascending, no repeated roll; notice lines' AIR = NBEMS."""
import sys, re, json, collections
import fitz

if len(sys.argv) != 5:
    raise SystemExit(__doc__)
MERIT, INCL, NB, OUT = sys.argv[1:]
ROLL, NUM = re.compile(r'2666\d{7}$'), re.compile(r'-?\d+$')
GENDER = {'MALE', 'FEMALE', 'TRANSGENDER', 'OTHER', 'OTHERS'}
CAT_FIX = {'ENERAL, EWS, Pw': 'GENERAL, EWS, PwD'}           # cell text clipped in the PDF
# 'Notice (Revised Merit Position)' 29.10.2026, No. e.DME/PG/2026/855656/1701: roll → (revised state rank, revised score, AIR)
REVISED = {'26661020225': ('87-A', 518.09, 11168), '26661022410': ('257-A', 472.77, 25245),
           '26661021226': ('481-A', 425.39, 44956)}

nb = {str(x['roll']): x for x in json.load(open(NB))}
toks = [t for p in fitz.open(MERIT) for t in p.get_text().split()]
idx = [i for i, t in enumerate(toks) if ROLL.match(t)]
rows = []
for n, i in enumerate(idx):
    seg = toks[i + 1:(idx[n + 1] if n + 1 < len(idx) else len(toks))]
    g = next((k for k, t in enumerate(seg) if t in GENDER), None)
    if g is None:
        raise SystemExit(f'line {n + 1}: gender not found')
    rest = seg[g + 1:]
    nums = [k for k, t in enumerate(rest) if NUM.match(t)]
    if len(nums) < 2 or nums[1] != nums[0] + 1:
        raise SystemExit(f'line {n + 1}: score / rank not found')
    cat = ' '.join(rest[:nums[0]]).strip(', ')
    rows.append({'roll': toks[i], 'air': int(rest[nums[0] + 1]), 'state_rank': n + 1,
                 'score': float(rest[nums[0]]), 'category': CAT_FIX.get(cat, cat), 'quota': ''})
bad = [r['state_rank'] for r in rows if r['roll'] not in nb or nb[r['roll']].get('air') != r['air']
       or nb[r['roll']].get('score') != r['score']]
if bad:
    raise SystemExit(f'roll / AIR / score differs from NBEMS at positions {bad[:10]}')
a = [r['air'] for r in rows]
if any(y < x for x, y in zip(a, a[1:])) or len({r['roll'] for r in rows}) != len(rows):
    raise SystemExit('list not in AIR order, or a roll repeats')
checks = {'merit_list_rows': len(rows), 'nbems_roll_air_score_match': len(rows), 'air_ascending': True}

applied = []
by_roll = {r['roll']: r for r in rows}
for t in fitz.open(INCL)[0].find_tables().tables:                # inclusion notice
    for c in t.extract()[1:]:
        c = [re.sub(r'\s+', '', x or '') if k in (1, 4, 5, 6) else ' '.join((x or '').split()) for k, x in enumerate(c)]
        roll, cat, marks, srank, air = c[1], c[3], c[4], c[5], c[6]
        if not ROLL.match(roll) or roll in by_roll or nb.get(roll, {}).get('air') != int(air):
            raise SystemExit('inclusion notice line not as expected')
        r = {'roll': roll, 'air': int(air), 'state_rank': int(srank.split('-')[0]), 'score': float(marks),
             'category': cat, 'quota': ''}
        rows.append(r); by_roll[roll] = r
        applied.append({'notice': 'inclusion 17.10.2026', 'printed_state_rank': srank})
for roll, (srank, score, air) in REVISED.items():                 # revised merit position notice
    r = by_roll.get(roll)
    if not r or r['air'] != air:
        raise SystemExit('revised-position roll not in the list or AIR differs')
    applied.append({'notice': 'revised position 29.10.2026', 'from': r['state_rank'], 'printed_state_rank': srank})
    r.update({'state_rank': int(srank.split('-')[0]), 'score': score})
rows.sort(key=lambda r: (r['state_rank'], r['air']))
checks.update({'after_notices': len(rows), 'notices_applied': applied,
               'category': dict(collections.Counter(r['category'] for r in rows).most_common())})
json.dump({'authority_code': 'dme_assam', 'list_name': 'Provisional Merit List for Assam State Quota Seats (NEET-PG 2026)',
           'published_on': '2026-10-13', 'rows': rows, 'checks': checks}, open(OUT, 'w'))
print(json.dumps(checks))
