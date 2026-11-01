"""Tamil Nadu special-quota eligibility lists (CMC 20% GQ; Christian minority, Telugu minority, NRI - MQ).
Usage: MERIT_OUT=<dir> sm4_tn_special.py
These lists print only S.No / APP_NO / NAME, in application-number order: no roll, no rank, no score. So they carry no
merit order of their own and no rank-bridge list is made from them. This script only checks, by application number
held in memory (never written or printed), how many of their candidates are already in the GQ / MQ rank lists.
Output: counts only (tn_special_lists_check.json)."""
import os, re, json, collections
import fitz
from sm4_tn import read, GQCOLS, MQCOLS, GQAPP, MQAPP

ML2 = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/nov1/ml2/'
OUT = os.environ.get('MERIT_OUT') or ML2
APP = re.compile(r'^26PG\d{6}$')
LISTS = [('tn_cmc20_gq.pdf', 'GQ', 'CMC 20% eligible (Govt Quota)'),
         ('tn_christian_minority_mq.pdf', 'MQ', 'Christian minority eligible (Management Quota)'),
         ('tn_telugu_minority_mq.pdf', 'MQ', 'Telugu minority eligible (Management Quota)'),
         ('tn_nri_mq_latest.pdf', 'MQ', 'NRI quota eligible (Management Quota) - latest, 31 Oct 18:26'),
         ('tn_nri_mq_earlier.pdf', 'MQ', 'NRI quota eligible (Management Quota) - earlier, 31 Oct 11:01')]
GQ_FILES = ['cd488e3665c3.pdf', 'dd546004ecc3.pdf', ML2 + 'tn_gq_addendum_a.pdf', ML2 + 'tn_gq_addendum_b.pdf']


def elig(path):
    d = fitz.open(path); apps, snos, cols = [], [], set()
    for pg in d:
        ws = pg.get_text('words')
        hdr = [w[4] for w in ws if w[4] in ('SNO', 'APP_NO', 'NAME', 'RANK', 'ROLL', 'SCORE', 'MARKS')]
        cols.update(hdr)
        for w in ws:
            if APP.match(w[4]):
                apps.append(w[4])
                s = [v[4] for v in ws if abs(v[1] - w[1]) < 2 and v[0] < w[0] and v[4].isdigit()]
                snos.append(int(s[0]) if s else None)
    rolls = sum(1 for pg in d for w in pg.get_text('words') if re.fullmatch(r'2666\d{7}', w[4]))
    return d.page_count, apps, snos, sorted(cols), rolls


gq_apps = {r['app'] for fn in GQ_FILES for r in read(fn, GQCOLS + [GQAPP])}
mq_apps = {r['app'] for r in read('e6df5a89bbbc.pdf', MQCOLS + [MQAPP])}
assert all(APP.match(a) for a in gq_apps | mq_apps)
first_ad = {r['roll'] for r in read('dd546004ecc3.pdf', GQCOLS)}
ab = {r['roll'] for fn in GQ_FILES[2:] for r in read(fn, GQCOLS)}
out = {'gq_list_app_count': len(gq_apps), 'mq_list_app_count': len(mq_apps),
       'addenda_a_b_rolls_also_in_first_addendum': len(first_ad & ab), 'lists': {}}
sets = {}
for fn, base, desc in LISTS:
    pc, apps, snos, cols, rolls = elig(ML2 + fn)
    s = set(apps); sets[fn] = s
    ref = gq_apps if base == 'GQ' else mq_apps
    other = mq_apps if base == 'GQ' else gq_apps
    out['lists'][fn] = {
        'description': desc, 'pages': pc, 'rows': len(apps), 'unique_app_nos': len(s),
        'columns_printed': cols, 'roll_numbers_printed': rolls,
        'sno_contiguous_1_to_n': snos == list(range(1, len(snos) + 1)),
        'ordered_by_app_no': apps == sorted(apps),
        f'in_{base}_rank_list': len(s & ref), f'not_in_{base}_rank_list': len(s - ref),
        f'in_other_list_({"MQ" if base == "GQ" else "GQ"})': len(s & other),
    }
a, b = sets['tn_nri_mq_latest.pdf'], sets['tn_nri_mq_earlier.pdf']
out['nri_latest_vs_earlier'] = {'latest': len(a), 'earlier': len(b), 'only_in_latest': len(a - b), 'only_in_earlier': len(b - a), 'common': len(a & b)}
p = os.path.join(OUT, 'tn_special_lists_check.json')
json.dump(out, open(p, 'w'), indent=1)
print(p); print(json.dumps(out, indent=1))
