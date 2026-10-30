"""MP: Revised Merit List of Registered Candidates. Usage: read_dme_mp.py <pdf> [--count-only]"""
import sys, os, re
from merit_common import table_rows, num, check_rows, write

path = sys.argv[1]
count_only = '--count-only' in sys.argv
pages, trs, text_rolls = table_rows(path)
rows, snos, neet, other_sr, ctype = [], [], [], [], {}
bad = []
for pn, r in trs:
    if not r or not r[0].isdigit():
        continue
    if len(r) != 15:
        bad.append((pn, len(r))); continue
    sno, roll, sr, air, typ, _name, cat, _mp, ais, _pct, _wm, final = r[:12]
    # Category as printed ends with a gender letter (_M/_F); strip it (privacy). Keep the rest (e.g. IN_OBC_X).
    cat_out = re.sub(r'_[MF]$', '', cat)
    rows.append({'roll': roll, 'air': num(air), 'state_rank': num(sr), 'score': num(final),
                 'category': cat_out, 'quota': ''})
    snos.append(int(sno)); neet.append(num(ais))
    ctype[typ] = ctype.get(typ, 0) + 1
    if num(sr) != int(sno):
        other_sr.append(int(sno))
print('pages', pages, 'rows', len(rows), 'text rolls', sum(text_rolls.values()), 'bad rows', bad[:5])
if count_only:
    sys.exit()
extra = {'state_rank_source': "printed 'State Common Merit Rank' column",
         'rows_where_state_rank_ne_sno': len(other_sr),
         'candidate_types': ctype,
         'category_note': "printed 'Eligible Category' with the trailing gender letter (_M/_F) removed",
         'score_definition': "'Final Score' = NEET AI score (/720) + in-service weightage marks",
         'malformed_table_rows': bad[:20]}
c = check_rows(rows, snos, pages, sum(text_rolls.values()), extra, neet_scores=neet)
write('dme_mp', 'registered_revised', 'Merit List of Registered Candidates (Revised)', '2026-10-27',
      os.path.basename(path), rows, c)
