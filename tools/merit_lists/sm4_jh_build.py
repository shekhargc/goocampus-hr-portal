import re, collections, fitz
from sm4_common import *
from sm4_jh import read, toi, tof, P
nb = nbems()
_, rev = read('888bb086e06c.pdf')
_, fin = read('62076b896af5.pdf')
prov = fitz.open(P + 'fdaeb96ff287.pdf')
prov_rolls = [w[4] for pg in prov for w in pg.get_text('words') if ROLL.fullmatch(w[4])]
rows, catrank_stats = [], collections.defaultdict(list)
for r in rev:
    row = {'roll': r['roll'], 'air': toi(r['air']), 'state_rank': toi(r['cml']), 'score': tof(r['total']),
           'category': r['cat'].strip(), 'quota': ''}
    rows.append(row)
    cr = toi(r['catrank'])
    if cr is not None: catrank_stats[row['category']].append(cr)
neet = [{'roll': r['roll'], 'neet_score': tof(r['score'])} for r in rev]
# incentive arithmetic check: total == score*(1+inc/100)
arith_bad = [r['roll'] for r in rev if abs(tof(r['score']) * (1 + tof(r['inc']) / 100) - tof(r['total'])) > 0.051]
# merit order check: total non-increasing by CML
srt = sorted(rows, key=lambda x: x['state_rank'])
order_breaks = sum(1 for a, b in zip(srt, srt[1:]) if b['score'] > a['score'])
fmap = {r['roll']: r for r in fin}
diffs = collections.Counter()
for r in rev:
    f = fmap.get(r['roll'])
    if not f: diffs['roll_not_in_final'] += 1; continue
    for k in ('cml', 'cat', 'neetcat', 'catrank', 'total', 'air', 'ews', 'ins'):
        if f[k] != r[k]: diffs['changed_' + k] += 1
cr_checks = {}
for cat, v in catrank_stats.items():
    cr_checks[cat] = contiguity(v)
checks = {
    'state_rank_source': 'CML Rank column (equals Sl. No. on all rows)',
    'sno_contiguity': contiguity([toi(r['sno']) for r in rev]),
    'state_rank_contiguity': contiguity([r['state_rank'] for r in rows]),
    'cml_equals_sno': sum(1 for r in rev if r['cml'] == r['sno']),
    'air': dict(air_check(rows, nb), source='printed in list'),
    'neet_score_vs_nbems': score_check(neet, nb),
    'score_definition': 'Total Score With Incentive (NEET PG score + in-service incentive % of score)',
    'incentive_arithmetic_mismatches': arith_bad,
    'merit_order_breaks_total_vs_cml': order_breaks,
    'categories': dict(collections.Counter(r['category'] for r in rows)),
    'category_note': "category = state 'Category' column; the list also prints a separate NEET PG 2026 category",
    'ews_yes': sum(1 for r in rev if r['ews'] == 'YES'),
    'in_service_yes': sum(1 for r in rev if r['ins'] == 'YES'),
    'incentive_pct_counts': dict(collections.Counter(r['inc'] for r in rev)),
    'category_rank_rows': sum(len(v) for v in catrank_stats.values()),
    'category_rank_by_category': cr_checks,
    'compare_final_62076b896af5': {'rows': len(fin), 'same_roll_set': set(fmap) == {r['roll'] for r in rev}, 'diffs': dict(diffs)},
    'compare_provisional_fdaeb96ff287': {'rolls': len(prov_rolls), 'unique_rolls': len(set(prov_rolls)),
        'rolls_in_revised': len(set(prov_rolls) & {r['roll'] for r in rev}),
        'revised_rolls_not_in_provisional': len({r['roll'] for r in rev} - set(prov_rolls))},
}
obj = {'authority_code': 'jceceb', 'list_name': 'Round 1 Final State Merit List (Revised)', 'published_on': '2026-10-28',
       'source_file_name': '888bb086e06c.pdf', 'rows': rows, 'checks': checks}
write('jceceb_r1_revised.json', obj)
import json
c = dict(checks); print(json.dumps(c, indent=1)[:6000])
