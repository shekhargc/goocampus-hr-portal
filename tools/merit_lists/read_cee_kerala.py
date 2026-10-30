"""Kerala: State Merit List of NEET PG 2026 (final, 29-10-2026). Usage: read_cee_kerala.py <final_pdf> <provisional_pdf>
Main list = first run of Sl.No 1..N. A second run restarting at 1 on the last page holds 'Not Qualified'
candidates marked '# Provisionally Included. Subject to the decision of screening committee' -> excluded from rows."""
import sys, os
from merit_common import table_rows, num, check_rows, write, nbems

def runs(path, roll_col, rank_col, score_col=None):
    pages, trs, text_rolls = table_rows(path)
    out, cur = [], None
    for pn, r in trs:
        if not r or not r[0].isdigit():
            continue
        sl = int(r[0])
        if sl == 1 or cur is None:
            cur = []; out.append(cur)
        cur.append({'sl': sl, 'roll': r[roll_col], 'rank_raw': r[rank_col],
                    'score': num(r[score_col]) if score_col is not None else None, 'page': pn, 'ncols': len(r)})
    return pages, out, sum(text_rolls.values())

fin, prov = sys.argv[1], sys.argv[2]
pages, fruns, ntext = runs(fin, 3, 4, 2)
print('final runs', [len(x) for x in fruns], 'text rolls', ntext, 'ncols', {c['ncols'] for x in fruns for c in x})
main = fruns[0]
printed_snos = [x['sl'] for x in main]
sno_contig_printed = printed_snos == list(range(1, len(main) + 1))
# 'Withheld' rows: roll printed as '-', no rank, no score -> no bridge value; excluded (their Sl.No stays reserved).
withheld = [x for x in main if x['rank_raw'].lower() == 'withheld']
kept = [x for x in main if x['rank_raw'].lower() != 'withheld']
# Ranks printed with a trailing '#' = "Provisionally Included. Subject to the decision of screening committee".
hash_ranks = [x['sl'] for x in kept if x['rank_raw'].endswith('#')]
def air_of(x):
    return num(x['rank_raw'].rstrip('#'))
rows = [{'roll': x['roll'], 'air': air_of(x), 'state_rank': x['sl'], 'score': x['score'],
         'category': '', 'quota': ''} for x in kept]
snos = list(range(1, len(rows) + 1))  # check_rows' contiguity test is replaced by the printed-Sl.No test below
neet = [x['score'] for x in kept]
air_inv = sum(1 for a, b in zip(rows, rows[1:]) if a['air'] and b['air'] and b['air'] < a['air'])
nonnum_rank_main = sum(1 for x in kept if air_of(x) is None)
# second run: provisionally included, not qualified
nb = nbems()
extra_run = fruns[1] if len(fruns) > 1 else []
ex = {'rows': len(extra_run), 'printed_rank_values': sorted({x['rank_raw'] for x in extra_run}),
      'rolls_found_in_nbems': sum(1 for x in extra_run if x['roll'] in nb),
      'nbems_air_present': sum(1 for x in extra_run if nb.get(x['roll'], {}).get('air')),
      'neet_score_match_nbems': sum(1 for x in extra_run if nb.get(x['roll'], {}).get('score') == x['score']),
      'score_range': [min(x['score'] for x in extra_run), max(x['score'] for x in extra_run)] if extra_run else None}
# provisional comparison (row counts / roll overlap only)
ppages, pruns, pntext = runs(prov, 3, 4)
pmain = pruns[0]
fs, ps = {x['roll'] for x in main if x['roll'] != '-'}, {x['roll'] for x in pmain if x['roll'] != '-'}
pos_f, pos_p = {x['roll']: x['sl'] for x in main}, {x['roll']: x['sl'] for x in pmain}
pcmp = {'provisional_pages': ppages, 'provisional_runs_row_counts': [len(x) for x in pruns],
        'final_main_rows': len(main), 'provisional_main_rows': len(pmain),
        'in_final_not_provisional': len(fs - ps), 'in_provisional_not_final_now_withheld_dash': len(ps - fs),
        'sl_no_changed_for_common_rolls': sum(1 for k in fs & ps if pos_f[k] != pos_p[k]),
        'provisional_withheld': sum(1 for x in pmain if x['rank_raw'].lower() == 'withheld'),
        'final_withheld': len(withheld)}
print('provisional compare', pcmp)
extra = {'state_rank_source': 'Sl.No. (no explicit state-rank column; list verified to be in merit order: NEET score non-increasing, AIR ascending)',
         'printed_sl_no_contiguous_1_to_n': sno_contig_printed, 'printed_sl_no_max': len(main),
         'withheld_rows_excluded': len(withheld), 'withheld_sl_nos': [x['sl'] for x in withheld],
         'withheld_rows_roll_printed': sorted({x['roll'] for x in withheld}),
         'rank_marked_hash_provisionally_included': len(hash_ranks),
         'hash_note': "AIR printed with trailing '#' (provisionally included, subject to screening committee); '#' stripped, row kept",
         'air_order_inversions': air_inv, 'rows_with_non_numeric_rank_in_main_list': nonnum_rank_main,
         'score_definition': "'NEET Score' (no state weightage printed)",
         'category_note': 'no category column in this list (Kerala publishes a separate Category List on the candidate portal); category left blank',
         'excluded_second_list_not_qualified_provisionally_included': ex,
         'provisional_vs_final': pcmp}
c = check_rows(rows, snos, pages, ntext, extra, neet_scores=neet)
c['sno_contiguous_1_to_n'] = sno_contig_printed  # printed Sl.No 1..5665 incl. the excluded Withheld rows
c['sno_note'] = 'contiguity tested on all printed Sl.No (incl. Withheld rows); rows kept = printed rows - Withheld'
write('cee_kerala', 'state_merit_final', 'Kerala State Merit List of NEET PG 2026 (Final)', '2026-10-29',
      os.path.basename(fin), rows, c)
