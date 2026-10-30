import re, collections, json
from sm4_common import *
from sm4_tn import read, GQCOLS, MQCOLS
nb = nbems()
toi = lambda s: int(s) if re.fullmatch(r'\d+', s.strip()) else None
tof = lambda s: float(s) if re.fullmatch(r'[\d.]+', s.strip()) else None
gq = read('cd488e3665c3.pdf', GQCOLS); ad = read('dd546004ecc3.pdf', GQCOLS); mq = read('e6df5a89bbbc.pdf', MQCOLS)

def crank_check(recs):
    by = collections.defaultdict(list)
    for r in recs:
        c = toi(r['crank'])
        if c is not None: by[r['comm']].append(c)
    return {k: contiguity(v) for k, v in by.items()}, collections.Counter(r['comm'] for r in recs if not r['crank'].strip())

def arith(recs):
    bad = []
    for r in recs:
        n = nb.get(r['roll'])
        if not n: continue
        inc = tof(r['inc']) or 0.0
        if abs(n['score'] * (1 + inc / 100) - tof(r['total'])) > 0.011: bad.append({'rank': r['rank'], 'roll': r['roll'], 'nbems_score': n['score'], 'inc': inc, 'total': r['total']})
    return bad

# ---- GQ (before addendum) checks
gq_rank = contiguity([toi(r['rank']) for r in gq])
gq_order = sum(1 for a, b in zip(gq, gq[1:]) if tof(b['total']) > tof(a['total']))
crk_before, crk_blank = crank_check(gq)
arith_bad = arith(gq)
# ---- apply addendum
byroll = {r['roll']: r for r in gq}
applied = []
final = [dict(r) for r in gq]
idx = {r['roll']: i for i, r in enumerate(final)}
remove = set()
inserts = []
for a in ad:
    lab = a['rank']; base = int(lab.rstrip('A'))
    if a['roll'] in byroll:
        g = byroll[a['roll']]
        ch = {k: (g[k], a[k]) for k in ('rank', 'comm', 'svc', 'inc', 'total', 'crank') if g[k] != a[k]}
        if lab.endswith('A'):
            remove.add(a['roll']); inserts.append((base, a))
            applied.append({'type': 're-ranked', 'roll': a['roll'], 'printed_rank': lab, 'old_rank': g['rank'], 'changes': ch})
        else:
            final[idx[a['roll']]].update({k: a[k] for k in ('comm', 'svc', 'inc', 'total', 'crank')})
            applied.append({'type': 'corrected in place', 'roll': a['roll'], 'printed_rank': lab, 'changes': ch})
    else:
        inserts.append((base, a))
        applied.append({'type': 'added', 'roll': a['roll'], 'printed_rank': lab, 'state_rank_stored': base, 'community': a['comm'], 'comm_rank': a['crank']})
final = [r for r in final if r['roll'] not in remove]
for base, a in inserts:
    a = dict(a); a['_label'] = a['rank']; a['rank'] = str(base)
    # insert right after the row with rank == base
    pos = max(i for i, r in enumerate(final) if toi(r['rank']) <= base) + 1
    final.insert(pos, a)
rows = []
for r in final:
    n = nb.get(r['roll'])
    rows.append({'roll': r['roll'], 'air': int(n['air']) if n else None, 'state_rank': toi(r['rank']), 'score': tof(r['total']),
                 'category': r['comm'], 'quota': ''})
order_after = sum(1 for a, b in zip(rows, rows[1:]) if b['score'] > a['score'])
rk_after = contiguity([r['state_rank'] for r in rows])
ac = air_check(rows, nb, printed=False)
checks = {
    'state_rank_source': "printed RANK column (overall GQ rank). Addendum 'nA' ranks (inserted after rank n) are stored as integer n, i.e. a tie with rank n",
    'rank_contiguity_before_addendum': gq_rank,
    'merit_order_breaks_before_addendum': gq_order,
    'air': {'source': 'not printed; filled from NBEMS by roll', 'filled_from_roll': sum(1 for r in rows if r['air']),
            'rolls_found_in_nbems': ac['rolls_found_in_nbems'], 'rolls_not_found': ac['rolls_not_found'], 'not_found_rolls': ac['not_found_rolls']},
    'score_definition': 'TOTAL MARKS = NEET PG score + service incentive % (in-service candidates); equals NEET score otherwise',
    'total_vs_nbems_score_x_incentive_mismatches': arith_bad[:20], 'n_total_arith_mismatches': len(arith_bad),
    'categories': dict(collections.Counter(r['category'] for r in rows)),
    'category_note': 'COMMUNITY column as printed',
    'in_service_yes': sum(1 for r in final if r['svc'] == 'YES'),
    'incentive_pct_counts': dict(collections.Counter(r['inc'] for r in final if r['svc'] == 'YES')),
    'community_rank_before_addendum': crk_before, 'community_rank_blank_by_community': dict(crk_blank),
    'addendum_dd546004ecc3': {'rows': len(ad), 'applied': applied,
        'summary': collections.Counter(x['type'] for x in applied)},
    'rank_after_addendum': rk_after,
    'merit_order_breaks_after_addendum': order_after,
    'rows_before_addendum': len(gq), 'rows_after_addendum': len(rows),
    'published_on_note': 'no date printed; PDF created 2026-10-28 (addendum PDF created 2026-10-29)',
}
write('dmer_tn_gq.json', {'authority_code': 'dmer_tn', 'list_name': 'PG Government Quota Provisional Rank List', 'published_on': '',
      'source_file_name': 'cd488e3665c3.pdf (+ addendum dd546004ecc3.pdf)', 'rows': rows, 'checks': checks})
print(json.dumps(checks, indent=1, default=str)[:9000])
# ---- MQ
mrows = []
for r in mq:
    n = nb.get(r['roll'])
    mrows.append({'roll': r['roll'], 'air': int(n['air']) if n else None, 'state_rank': toi(r['rank']), 'score': tof(r['score']),
                  'category': r['comm'], 'quota': 'Management'})
mac = air_check(mrows, nb, printed=False)
msc = score_check([{'roll': r['roll'], 'neet_score': r['score']} for r in mrows], nb)
gqrolls = {r['roll'] for r in rows}
mchecks = {
    'state_rank_source': 'printed RANK column',
    'rank_contiguity': contiguity([r['state_rank'] for r in mrows]),
    'merit_order_breaks': sum(1 for a, b in zip(mrows, mrows[1:]) if b['score'] > a['score']),
    'air': {'source': 'not printed; filled from NBEMS by roll', 'filled_from_roll': sum(1 for r in mrows if r['air']),
            'rolls_found_in_nbems': mac['rolls_found_in_nbems'], 'rolls_not_found': mac['rolls_not_found'], 'not_found_rolls': mac['not_found_rolls']},
    'score_definition': 'NEET score column (no incentive on MQ list)',
    'neet_score_vs_nbems': msc,
    'categories': dict(collections.Counter(r['category'] for r in mrows)),
    'also_in_gq_list': len({r['roll'] for r in mrows} & gqrolls),
    'published_on_note': 'no date printed; PDF created 2026-10-28',
}
write('dmer_tn_mq.json', {'authority_code': 'dmer_tn', 'list_name': 'PG Management Quota Provisional Rank List', 'published_on': '',
      'source_file_name': 'e6df5a89bbbc.pdf', 'rows': mrows, 'checks': mchecks})
print(json.dumps(mchecks, indent=1))
