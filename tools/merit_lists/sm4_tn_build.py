"""Tamil Nadu (DME/selection committee) PG GQ + MQ provisional rank lists -> rank-bridge rows.
Usage: MERIT_OUT=<dir> sm4_tn_build.py [--gq-only] [--first-addendum-only]
AIR is not printed (filled from NBEMS by roll). Addendum 'nA' ranks are stored as integer n (tie with rank n)."""
import os, sys, re, collections, json
from sm4_common import *
from sm4_tn import read, GQCOLS, MQCOLS
nb = nbems()
toi = lambda s: int(s) if re.fullmatch(r'\d+', s.strip()) else None
tof = lambda s: float(s) if re.fullmatch(r'[\d.]+', s.strip()) else None
ML2 = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/nov1/ml2/'
ML3 = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/nov3/dl2/'
# GQ base list + addenda, applied in publication order (first addendum 29 Oct; addenda A and B 31 Oct, B repeats A's rows;
# 02 Nov: one more GQ addendum (5963A) and the first MQ addendum (898A) — inbox 1559 / 1558)
ADDENDA_FILES = ['dd546004ecc3.pdf'] + ([] if '--first-addendum-only' in sys.argv else [ML2 + 'tn_gq_addendum_a.pdf', ML2 + 'tn_gq_addendum_b.pdf', ML3 + '1559.pdf'])
MQ_ADDENDA_FILES = [] if '--first-addendum-only' in sys.argv else [ML3 + '1558.pdf']
gq = read('cd488e3665c3.pdf', GQCOLS); mq = read('e6df5a89bbbc.pdf', MQCOLS)
ADDENDA = [(fn, read(fn, GQCOLS)) for fn in ADDENDA_FILES]

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
# ---- apply addenda in order. Each row of an addendum is: added (roll not in list), corrected in place (same plain
# rank), re-ranked ('nA' label or a different rank -> moved to sit right after rank n), or a duplicate of a row an
# earlier addendum already applied (same label and values -> no-op).
FIELDS = ('comm', 'svc', 'inc', 'total', 'crank')


def label(r):
    return r.get('_label') or r['rank']


def apply_addendum(final, ad):
    applied = []
    for a in ad:
        lab = a['rank']; base = int(lab.rstrip('A'))
        cur = next((r for r in final if r['roll'] == a['roll']), None)
        if cur is not None and label(cur) == lab and all(cur[k] == a[k] for k in FIELDS):
            applied.append({'type': 'duplicate (already applied)', 'roll': a['roll'], 'printed_rank': lab}); continue
        if cur is not None and not lab.endswith('A') and cur['rank'] == lab:
            ch = {k: (cur[k], a[k]) for k in FIELDS if cur[k] != a[k]}
            cur.update({k: a[k] for k in FIELDS})
            applied.append({'type': 'corrected in place', 'roll': a['roll'], 'printed_rank': lab, 'changes': ch}); continue
        if cur is not None:
            ch = {k: (cur[k], a[k]) for k in ('rank',) + FIELDS if cur[k] != a[k]}
            final.remove(cur)
            applied.append({'type': 're-ranked', 'roll': a['roll'], 'printed_rank': lab, 'old_rank': label(cur), 'changes': ch})
        else:
            applied.append({'type': 'added', 'roll': a['roll'], 'printed_rank': lab, 'state_rank_stored': base, 'community': a['comm'], 'comm_rank': a['crank']})
        a = dict(a); a['_label'] = lab; a['rank'] = str(base)
        pos = max(i for i, r in enumerate(final) if toi(r['rank']) <= base) + 1  # right after the last row ranked <= n
        final.insert(pos, a)
    return applied


final = [dict(r) for r in gq]
addenda_log = {}
for fn, ad in ADDENDA:
    applied = apply_addendum(final, ad)
    addenda_log[os.path.basename(fn)] = {'rows': len(ad), 'applied': applied,
                                         'summary': dict(collections.Counter(x['type'] for x in applied))}
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
    'addenda': addenda_log,
    'rank_after_addendum': rk_after,
    'merit_order_breaks_after_addendum': order_after,
    'rows_before_addendum': len(gq), 'rows_after_addendum': len(rows),
    'published_on_note': 'no date printed; PDF created 2026-10-28 (first addendum PDF created 2026-10-29; addenda A/B 2026-10-31)',
}
write('dmer_tn_gq.json', {'authority_code': 'dmer_tn', 'list_name': 'PG Government Quota Provisional Rank List', 'published_on': '',
      'source_file_name': 'cd488e3665c3.pdf (+ addenda ' + ', '.join(os.path.basename(f) for f in ADDENDA_FILES) + ')', 'rows': rows, 'checks': checks})
print(json.dumps(checks, indent=1, default=str)[:9000])
if '--gq-only' in sys.argv:
    sys.exit()
# ---- MQ (+ addenda: an 'nA' line for a roll not in the list is added right after rank n, stored as n)
mq_log = []
for fn in MQ_ADDENDA_FILES:
    for a in read(fn, MQCOLS):
        lab = a['rank']; base = int(lab.rstrip('A'))
        if any(r['roll'] == a['roll'] for r in mq) or not lab.endswith('A'):
            raise SystemExit(f'MQ addendum {os.path.basename(fn)}: only additions are handled ({lab})')
        a = dict(a); a['rank'] = str(base)
        mq.insert(max(i for i, r in enumerate(mq) if toi(r['rank']) <= base) + 1, a)
        mq_log.append({'file': os.path.basename(fn), 'type': 'added', 'printed_rank': lab, 'state_rank_stored': base})
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
    'addenda': mq_log,
    'published_on_note': 'no date printed; PDF created 2026-10-28',
}
write('dmer_tn_mq.json', {'authority_code': 'dmer_tn', 'list_name': 'PG Management Quota Provisional Rank List', 'published_on': '',
      'source_file_name': 'e6df5a89bbbc.pdf', 'rows': mrows, 'checks': mchecks})
print(json.dumps(mchecks, indent=1))
