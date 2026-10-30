"""UP: State Merit List Round-1 (MD/MS/Diploma: 10 cols with weightage; DNB: 8 cols).
Usage: read_dmetup.py <pdf> <short> <list_name>"""
import sys, os, collections
from merit_common import table_rows, num, check_rows, write

path, short, list_name = sys.argv[1], sys.argv[2], sys.argv[3]
pages, trs, text_rolls = table_rows(path)
rows, snos, neet, bad = [], [], [], []
cnt = collections.defaultdict(collections.Counter)
wt_bad = 0
ncols = None
for pn, r in trs:
    if not r or not r[0].isdigit():
        continue
    ncols = ncols or len(r)
    if len(r) != ncols or len(r) not in (8, 10):
        bad.append((pn, len(r))); continue
    sno, roll, _name, _father, cat, sub, marks, rank = r[:8]
    if len(r) == 10:
        wmarks, wpct = num(r[8]), num(r[9])
        score = wmarks
        cnt['weightage_pct'][str(wpct)] += 1
        if num(marks) is not None and wmarks is not None and abs(num(marks) * (1 + (wpct or 0) / 100) - wmarks) > 0.51:
            wt_bad += 1
    else:
        score = num(marks)
    cnt['sub_category'][sub] += 1
    rows.append({'roll': roll, 'air': num(rank), 'state_rank': int(sno), 'score': score,
                 'category': cat if sub in ('', 'OP') else f'{cat}-{sub}', 'quota': ''})
    snos.append(int(sno)); neet.append(num(marks))
# merit order: score non-increasing; within equal score AIR ascending
tie_inv = sum(1 for a, b in zip(rows, rows[1:]) if a['score'] == b['score'] and a['air'] and b['air'] and b['air'] < a['air'])
air_inv = sum(1 for a, b in zip(rows, rows[1:]) if a['air'] and b['air'] and b['air'] < a['air'])
print('pages', pages, 'rows', len(rows), 'text rolls', sum(text_rolls.values()), 'bad', bad[:5])
extra = {'state_rank_source': 'SrNo (no explicit state-rank column; list verified to be in merit order)',
         'air_order_inversions_tie_on_score': tie_inv, 'air_order_inversions_overall': air_inv,
         'score_definition': ("'Marks with weightage' (NEET marks + in-service weightage %)" if ncols == 10 else "'Neet Marks' (no weightage column printed)"),
         'rows_where_weighted_ne_marks_x_pct': wt_bad if ncols == 10 else None,
         'category_note': "printed 'UP Category'; '-<UP Sub Category>' appended when sub category is not OP",
         **{k: dict(v) for k, v in cnt.items()}, 'malformed_table_rows': bad[:20]}
c = check_rows(rows, snos, pages, sum(text_rolls.values()), extra, neet_scores=neet)
write('dmetup', short, list_name, '2026-10-26', os.path.basename(path), rows, c)
