"""Telangana KNRUHS CQ "Addendum to Merit List" of 15.11.2026 (inbox 1729, 1 page, 6 candidates) -> merged into the
already-read FINAL CQ merit list rows (read_knruhs_tg.py output knruhs_cq_final.json), written as a new JSON that is
re-posted under the SAME list_name (so it replaces the stored list with list + both addenda).

This addendum has a different layout from the 13.11 one: S.No, Rank (NEET PG AIR), Roll No, Score, Name, Gender,
Category, Minority, Service, Remarks. Read ONLY S.No, Rank, Roll No, Score, Category, Minority, Service. Name, Gender
and the remark text are never read into the output.
No state rank is printed: like the 13.11 addendum, each row is stored with the S.No of the last list row above its AIR.

Usage: /usr/bin/python3 read_knruhs_tg_addendum.py <addendum.pdf> <knruhs_cq_final.json> <out.json>
Strict: header words, 2666xxxxxxx rolls, S.No 1..n, one Rank/Score/Category/Service per row, known category, roll not
already in the list -> otherwise SystemExit."""
import sys, os, re, json
import fitz

ROLL = re.compile(r'^2666\d{7}$')
INT = re.compile(r'^\d+$')
CATS = {'OC', 'BCA', 'BCB', 'BCC', 'BCD', 'BCE', 'SC1', 'SC2', 'SC3', 'ST', 'EWS'}
HEAD = ['S.No', 'Rank', 'Roll', 'No', 'Score', 'Name', 'Gender', 'Category', 'Minority', 'Service', 'Remarks']


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    pdf, base, out = sys.argv[1:4]
    d = fitz.open(pdf)
    if d.page_count != 1:
        raise SystemExit('expected 1 page')
    p = d[0]
    t = ' '.join(p.get_text().split())
    m = re.search(r'DATE\s*:\s*(\d{2})\.(\d{2})\.(\d{4})', t, re.I)
    if not m:
        raise SystemExit('date not found')
    ws = p.get_text('words')
    hy = [w for w in ws if w[4] == 'S.No']
    if len(hy) != 1:
        raise SystemExit('header not found')
    hdr = sorted([w for w in ws if abs(w[3] - hy[0][3]) < 3], key=lambda w: w[0])
    if [w[4] for w in hdr] != HEAD:
        raise SystemExit('column headings changed')
    hx = {w[4]: w[0] for w in hdr}
    anchors = sorted([w for w in ws if ROLL.match(w[4])], key=lambda w: w[3])
    if len(anchors) != len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text())):
        raise SystemExit('roll outside the table')
    add = []
    for i, a in enumerate(anchors):
        line = [w for w in ws if abs(w[3] - a[3]) < 3]
        pick = lambda lo, hi: [w[4] for w in line if lo <= w[0] < hi]
        sno = pick(0, hx['Rank'] - 4)
        rank = pick(hx['Rank'] - 4, a[0] - 1)          # the roll starts left of its own heading
        score = pick(hx['Score'] - 4, hx['Name'] - 4)
        cat = pick(hx['Category'] - 4, hx['Minority'] - 4)
        mino = pick(hx['Minority'] - 4, hx['Service'] - 4)
        serv = pick(hx['Service'] - 4, hx['Remarks'] - 4)
        if not (sno == [str(i + 1)] and len(rank) == 1 and INT.match(rank[0]) and len(score) == 1 and INT.match(score[0])
                and len(cat) == 1 and cat[0] in CATS and mino in ([], ['MSM']) and serv in (['NS'], ['S'])):
            raise SystemExit(f'row {i + 1}: shape')
        add.append({'roll': a[4], 'air': int(rank[0]), 'score': int(score[0]), 'cat': cat[0],
                    'quota': 'In-service' if serv == ['S'] else ''})
    obj = json.load(open(base))
    rows = obj['rows']
    known = {r['roll'] for r in rows}
    if any(a['roll'] in known for a in add):
        raise SystemExit('addendum candidate already in the merit list')
    placed = []
    for a in add:
        before = [r for r in rows if r['air'] < a['air']]
        n = max(r['state_rank'] for r in before) if before else 1
        rows.append({'roll': a['roll'], 'air': a['air'], 'state_rank': n, 'score': a['score'], 'category': a['cat'],
                     'quota': a['quota']})
        placed.append({'air': a['air'], 'category': a['cat'], 'stored_state_rank': n})
    rows.sort(key=lambda r: (r['state_rank'], r['air']))
    date = f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
    obj['checks']['addendum_2'] = {'file': os.path.basename(pdf), 'date': date, 'rows': len(add), 'placed': placed,
                                   'how': 'no state rank printed: stored with the S.No of the last list row above its AIR'}
    obj['checks']['row_count'] = obj['row_count'] = len(rows)
    obj['notes'] = obj['notes'].replace('Replaces the provisional', f'+ addendum of {m.group(1)}.{m.group(2)}.{m.group(3)} '
                                        f'({len(add)} candidates, stored at the S.No above their AIR). Replaces the provisional')
    obj['source_file_name'] = obj['source_file_name'].replace('-plus-Addendum', '-plus-Addenda')
    json.dump(obj, open(out, 'w'), indent=1, ensure_ascii=False)
    print(out)
    print(json.dumps({'rows': len(rows), 'addendum_2': obj['checks']['addendum_2']}, indent=1))


if __name__ == '__main__':
    main()
