import re, collections, fitz, json
from sm4_common import *
from sm4_pb import read_main, toi, tof, P
nb = nbems()
def clean_cat(s):
    parts = [p.strip() for p in s.split(',')]
    out = []
    for p in parts:
        q = p.replace(' ', '')
        if re.fullmatch(r'G?Generall?', q): p = 'General'
        elif q == 'PersonWithDisability': p = 'Person With Disability'
        elif q in ('SC', 'BC', 'EWS', 'General'): p = q
        else: raise ValueError('unexpected category fragment: %r' % p)
        if p not in out: out.append(p)
    return ','.join(out)
n, recs, _ = read_main('aba5596c28c0.pdf')
rows, neet, sci, arith_bad = [], [], 0, []
for r in recs:
    air_raw = r['rank'].strip()
    air = toi(air_raw)
    if air is None: sci += 1
    inc = tof(r['inc']) or 0.0
    marks, total = tof(r['marks']), tof(r['total'])
    if abs(marks * (1 + inc / 100) - total) > 0.51: arith_bad.append({'sr': toi(r['sr']), 'marks': marks, 'inc': inc, 'total': total})
    rows.append({'roll': r['roll'], 'air': air, 'state_rank': toi(r['sr']), 'score': total, 'category': clean_cat(r['cat']), 'quota': ''})
    neet.append({'roll': r['roll'], 'neet_score': marks})
chk_printed = air_check(rows, nb)
filled = 0
for row in rows:
    if row['air'] is None and nb.get(row['roll']):
        row['air'] = int(nb[row['roll']]['air']); filled += 1
srt = sorted(rows, key=lambda x: x['state_rank'])
order_breaks = [(a['state_rank'], b['state_rank']) for a, b in zip(srt, srt[1:]) if b['score'] > a['score']]
pcms = collections.Counter(re.sub(r'^N No$', 'No', r['pcms']) for r in recs)
checks = {
    'state_rank_source': 'Sr. No. (no merit-rank column printed; list is in merit order by Total marks)',
    'sno_contiguity': contiguity([r['state_rank'] for r in rows]),
    'merit_order_breaks_total_vs_srno': order_breaks[:20], 'n_merit_order_breaks': len(order_breaks),
    'air': dict(chk_printed, source="printed 'NEET PG Rank' column", printed_as_1E05_unreadable=sci,
                filled_from_roll=filled, note='ranks >= 100000 are printed as 1E+05 (Excel format); those rows got AIR from NBEMS by roll'),
    'neet_score_vs_nbems': score_check(neet, nb),
    'score_definition': 'Total marks = NEET PG marks + incentive % (PCMS in-service incentive)',
    'incentive_arithmetic_mismatches': arith_bad[:20],
    'incentive_pct_counts': dict(collections.Counter(r['inc'] for r in recs)),
    'pcms_candidate': dict(pcms),
    'categories': dict(collections.Counter(r['category'] for r in rows)),
    'category_note': "printed 'Categories' column, multi-valued (e.g. 'BC,General'); OCR-overlap fragments like 'General l' / 'Perso n' cleaned",
    'minority': dict(collections.Counter(re.sub(r'.*Christian.*', 'Christian', r['min']) for r in recs)),
    'published_on_source': "page 1 '(Date 23.10.2026)'",
}
write('bfuhs_r1_main.json', {'authority_code': 'bfuhs', 'list_name': 'Round 1 Provisional Merit List after Objections',
      'published_on': '2026-10-23', 'source_file_name': 'aba5596c28c0.pdf', 'rows': rows, 'checks': checks})
print(json.dumps(checks, indent=1)[:5000])

# NRI
d = fitz.open(P + '572ebae7527b.pdf'); ws = dedupe(vwords(d[0]))
cols = [('sno', 85, 120), ('roll', 120, 195), ('rank', 340, 400), ('marks', 400, 460), ('cat', 460, 500), ('rem', 555, 700)]
recs = rows_v(ws, 85, 120, cols, ymin=160, max_h=30)
nrows, neet = [], []
for i, r in enumerate(recs):
    nrows.append({'roll': r['roll'], 'air': toi(r['rank']), 'state_rank': i + 1, 'score': tof(r['marks']),
                  'category': 'Category ' + r['cat'].strip(), 'quota': 'NRI'})
    neet.append({'roll': r['roll'], 'neet_score': tof(r['marks'])})
assert all(ROLL.fullmatch(r['roll']) for r in nrows)
srt = nrows
ncheck = {
    'state_rank_source': 'list position 1..N; printed S.No restarts per NRI category (Category I: 1-6, Category II: 1)',
    'printed_sno': [toi(r['sno']) for r in recs],
    'state_rank_contiguity': contiguity([r['state_rank'] for r in nrows]),
    'air': dict(air_check(nrows, nb), source="printed 'NEET PG Rank'"),
    'neet_score_vs_nbems': score_check(neet, nb),
    'air_ascending_in_list_order': all(a['air'] < b['air'] for a, b in zip(nrows, nrows[1:])),
    'score_definition': 'NEET PG marks (no incentive column on NRI list)',
    'categories': dict(collections.Counter(r['category'] for r in nrows)),
    'remarks': dict(collections.Counter(r['rem'] for r in recs)),
    'published_on_note': "header says '(19.10.2026)', PDF title says 'Revised ... 21.10.2026', created 22.10.2026; left blank",
}
write('bfuhs_r1_nri.json', {'authority_code': 'bfuhs', 'list_name': 'Round 1 Revised Provisional NRI Merit List',
      'published_on': '', 'source_file_name': '572ebae7527b.pdf', 'rows': nrows, 'checks': ncheck})
print(json.dumps(ncheck, indent=1))
