"""Rajasthan: Revised Provisional State Merit List (Round 1). Usage: read_ruhs.py <pdf>"""
import sys, os, collections
from merit_common import table_rows, num, check_rows, write

path = sys.argv[1]
pages, trs, text_rolls = table_rows(path)
rows, snos, neet, bad = [], [], [], []
cnt = collections.defaultdict(collections.Counter)
bonus_bad = 0
fixed_cat = 0
import re
KNOWN = re.compile(r'(General|OBC NCL|MBC NCL|EWS|SC|ST)$')
for pn, r in trs:
    if not r or not r[0].isdigit():
        continue
    if len(r) != 16:
        bad.append((pn, len(r))); continue
    sno, _reg, roll, _name, _gender, dom, cat, addf, addv, svc, exp, rank, marks, bonus, total, sm = r
    # 'Madhya Pradesh' wraps in the Domicile cell and its trailing 'h' bleeds into the category cell ('hGeneral').
    m = KNOWN.search(cat)
    if not m:
        bad.append((pn, 'unknown category')); continue
    if m.group(0) != cat:
        fixed_cat += 1
    c = m.group(0)
    if addv.lower().startswith('eligible') and addf not in ('', '-'):
        c = f'{cat} / {addf}'
    rows.append({'roll': roll, 'air': num(rank), 'state_rank': num(sm), 'score': num(total), 'category': c, 'quota': ''})
    snos.append(int(sno)); neet.append(num(marks))
    cnt['domicile'][dom] += 1; cnt['additional_filled/verified'][f'{addf}|{addv}'] += 1
    cnt['service_status'][svc] += 1
    b = num(bonus) or 0
    if num(marks) is not None and num(total) is not None and abs(num(marks) + b - num(total)) > 0.051:
        bonus_bad += 1
print('pages', pages, 'rows', len(rows), 'text rolls', sum(text_rolls.values()), 'bad', bad[:5])
sr_ne = sum(1 for s, r in zip(snos, rows) if r['state_rank'] != s)
extra = {'state_rank_source': "printed 'State Merit' column",
         'rows_where_state_rank_ne_sno': sr_ne,
         'rows_where_neet_plus_bonus_ne_total': bonus_bad,
         'category_cells_cleaned_of_domicile_bleed': fixed_cat,
         'score_definition': "'Total Marks' = NEET marks + bonus marks (in-service rural weightage)",
         'category_note': "printed 'Provisional Considered Category'; ' / <additional category>' appended when Additional Category (Verified) starts with 'Eligible' (STA filled but unverified is not appended)",
         **{k: dict(v) for k, v in cnt.items()}, 'malformed_table_rows': bad[:20]}
c = check_rows(rows, snos, pages, sum(text_rolls.values()), extra, neet_scores=neet)
write('ruhs', 'r1_state_merit_revised', 'Round 1 State Merit List (Revised Provisional)', '2026-10-28', os.path.basename(path), rows, c)
