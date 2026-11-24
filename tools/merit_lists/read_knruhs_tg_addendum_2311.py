"""Telangana KNRUHS CQ "Addendum to Merit List" of 23.11.2026 (inbox 1950, 1 page, 5 candidates "considered as per
court orders", interim High Court orders) -> rows APPENDED to the stored CQ list
"PG Medical CQ Provisional Merit List (MD/MS + PG Diploma)" (POST /api/pg/state-merit/ingest mode append, then finish).

Layout (new again): S.NO, NEET RANK (= AIR), NEET ROLL NO, NAME OF THE CANDIDATE, LOCAL STATUS, REMARKS.
Read ONLY S.No, Rank and Roll No. Name, local status and remarks are never read into the output. No score, category or
service is printed: score/category/quota are left empty (AIR is checked against NBEMS by roll at ingest).
No state rank is printed: like the earlier addenda each row is stored with the S.No of the last base-list row above its
AIR (base = read_knruhs_tg.py output of the 13.11 FINAL list; the earlier addenda rows sit at base S.Nos, so they never
change this placement).
Usage: /usr/bin/python3 read_knruhs_tg_addendum_2311.py <addendum.pdf> <knruhs_cq_final.json> <out.json>
Strict: header words, 2666xxxxxxx rolls, S.No 1..n, one Rank per row, every roll in the text is a row anchor, roll not
in the base list -> otherwise SystemExit."""
import sys, re, json
import fitz

ROLL = re.compile(r'^2666\d{7}$')
HEAD = ['S.NO', 'NEET', 'RANK', 'NEET', 'ROLL', 'NO', 'NAME', 'OF', 'THE', 'CANDIDATE', 'LOCAL', 'STATUS', 'REMARKS']
if len(sys.argv) != 4:
    raise SystemExit(__doc__)
pdf, base, out = sys.argv[1:4]
d = fitz.open(pdf)
if d.page_count != 1:
    raise SystemExit('expected 1 page')
p = d[0]
t = ' '.join(p.get_text().split())
for must in ('ADDENDUM TO MERIT LIST', 'COMPETENT AUTHORITY QUOTA FOR THE AY 2026-27'):
    if must not in t:
        raise SystemExit(f'title changed: {must!r} missing')
ws = p.get_text('words')
hy = [w for w in ws if w[4] == 'S.NO']
if len(hy) != 1:
    raise SystemExit('header not found')
hdr = sorted([w for w in ws if abs(w[3] - hy[0][3]) < 3], key=lambda w: w[0])
if [w[4] for w in hdr] != HEAD:
    raise SystemExit('column headings changed')
x_rank = [w[0] for w in hdr if w[4] == 'RANK'][0]
anchors = sorted([w for w in ws if ROLL.match(w[4])], key=lambda w: w[3])
if len(anchors) != len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text())):
    raise SystemExit('roll outside the table')
add = []
for i, a in enumerate(anchors):
    line = [w for w in ws if abs(w[3] - a[3]) < 3 and w[0] < a[0]]
    sno = [w[4] for w in line if w[0] < x_rank - 20]
    rank = [w[4] for w in line if w[0] >= x_rank - 40]
    if not (sno == [str(i + 1)] and len(rank) == 1 and rank[0].isdigit()):
        raise SystemExit(f'row {i + 1}: shape')
    add.append({'roll': a[4], 'air': int(rank[0])})
rows = json.load(open(base))['rows']
if any(a['roll'] in {r['roll'] for r in rows} for a in add):
    raise SystemExit('addendum candidate already in the base list')
res = []
for a in add:
    before = [r for r in rows if r['air'] < a['air']]
    n = max(r['state_rank'] for r in before) if before else 1
    res.append({'roll': a['roll'], 'air': a['air'], 'state_rank': n, 'score': None, 'category': '', 'quota': ''})
json.dump({'rows': res, 'date': '2026-11-23'}, open(out, 'w'), indent=1)
print('addendum rows', len(res), [{'air': r['air'], 'stored_state_rank': r['state_rank']} for r in res])
