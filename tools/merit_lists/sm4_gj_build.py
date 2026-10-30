import re, collections, fitz, json, math
from sm4_common import *
from sm4_gj import read, P
from sm4_gj_cmp import genmap
nb = nbems()
d, recs = read('6a13452c9929.pdf')
dates = collections.Counter(w[4] for pg in d for w in pg.get_text('words') if re.fullmatch(r'\d{1,2}-[A-Za-z]{3}-20\d\d', w[4]))
CATMAP = {'SE': 'SEBC', 'EW': 'EWS', 'SC': 'SC', 'ST': 'ST'}
rows, frac, airbad, neet = [], [], [], []
for r in recs:
    gm = float(r['gen'])
    if gm != int(gm): frac.append(r['gen'])
    a = r['air'].strip()
    air = float(a)
    if air != int(air): airbad.append(a)
    cats = [t.split('-')[0] for t in r['cat'].split() if re.match(r'^(SE|EW|SC|ST)-', t)]
    cats2 = [t.split('-')[0] for t in r['unicat'].split() if re.match(r'^(SE|EW|SC|ST)-', t)]
    cat = CATMAP[cats[0]] if cats else (CATMAP[cats2[0]] if cats2 else 'OPEN')
    rows.append({'roll': r['roll'], 'air': int(air), 'state_rank': int(math.floor(gm)), 'score': float(r['score']), 'category': cat, 'quota': ''})
    neet.append({'roll': r['roll'], 'neet_score': float(r['score'])})
# cat vs unicat consistency
incons = sum(1 for r in recs if ([t[:2] for t in r['cat'].split() if re.match(r'^(SE|EW|SC|ST)-', t)] or [''])[0] != ([t[:2] for t in r['unicat'].split() if re.match(r'^(SE|EW|SC|ST)-', t)] or [''])[0])
gens = [float(r['gen']) for r in recs]
order = sum(1 for a, b in zip(gens, gens[1:]) if b < a)
sorted_rows = sorted(zip(gens, rows), key=lambda x: x[0])
score_breaks = sum(1 for (g1, a), (g2, b) in zip(sorted_rows, sorted_rows[1:]) if b['score'] > a['score'])
air_breaks = sum(1 for (g1, a), (g2, b) in zip(sorted_rows, sorted_rows[1:]) if b['air'] < a['air'])
ints = [int(g) for g in gens if g == int(g)]
remarks = collections.Counter(r['remark'] for r in recs)
codes = collections.Counter(c for r in recs for c in re.findall(r'-(\d)', r['remark']))
# previous version compare
_, _, prev, _, _ = genmap('6c472630f30a.pdf')
_, _, old, _, _ = genmap('a58d3f021a25.pdf')
cur = {r['roll']: g for r, g in zip(rows, gens)}
fr_rolls = {r['roll'] for r, g in zip(rows, gens) if g != int(g)}
checks = {
    'columns_printed': 'User ID (skipped), Roll No, GEN MERIT, CAT MERIT, Uni. MERIT, Uni.Cat MERIT, All India Overall Rank, Score, NAME (skipped), Pass Institute Name (skipped), Remark',
    'state_rank_source': "GEN MERIT column. 125 rows carry half merit numbers (e.g. 256.50 = inserted between 256 and 257 in the updated list); stored as floor (tie with the integer merit)",
    'gen_merit_in_print_order_ascending': order == 0,
    'integer_merit_contiguity': contiguity(ints),
    'half_merit_rows': len(frac), 'half_merit_examples': frac[:10],
    'state_rank_after_floor': {k: v for k, v in contiguity([r['state_rank'] for r in rows]).items() if k != 'duplicates'},
    'merit_order_breaks_score': score_breaks, 'merit_order_breaks_air': air_breaks,
    'air': dict(air_check(rows, nb), source="printed 'All India Overall Rank' (formatted with .00)", non_integer_air=airbad[:10]),
    'neet_score_vs_nbems': score_check(neet, nb),
    'score_definition': 'Score column = NEET PG score (no incentive column in this list)',
    'categories': dict(collections.Counter(r['category'] for r in rows)),
    'category_note': "not printed as a column; derived from the CAT MERIT prefix (SE=SEBC, EW=EWS, SC, ST); no category merit = OPEN",
    'cat_vs_unicat_prefix_inconsistent': incons,
    'remark_codes': dict(codes), 'remark_values': dict(remarks),
    'remark_legend': '(1) reserved category claim subject to verification (2) PwD (3) eligible only NRI seats (4) eligible NRI+GQ+MQ seats (5) eligible only reserved category seats',
    'dates_printed': dict(dates),
    'compare_previous_general_6c472630f30a': {'rows': len(prev), 'same_rolls': set(prev) == set(cur), 'gen_merit_changed': sum(1 for k in cur if k in prev and prev[k] != cur[k])},
    'compare_first_general_a58d3f021a25': {'rows': len(old), 'rolls_added_since': len(set(cur) - set(old)), 'rolls_removed_since': len(set(old) - set(cur)),
        'added_are_the_half_merit_rows': (set(cur) - set(old)) == fr_rolls, 'gen_merit_changed_for_common': sum(1 for k in cur if k in old and old[k] != cur[k])},
    'category_lists': 'see acpmec_category_lists_compare.json: every SC/ST/SEBC/EWS/PwD/NRI/In-service list GEN MERIT equals this list\'s GEN MERIT for every roll',
}
pub = max(dates, key=dates.get) if dates else ''
write('acpmec_r1_general.json', {'authority_code': 'acpmec', 'list_name': 'Round 1 Provisional General Merit List', 'published_on': '2026-10-27' if pub == '27-Oct-2026' else '',
      'source_file_name': '6a13452c9929.pdf', 'rows': rows, 'checks': checks})
print(json.dumps(checks, indent=1))
