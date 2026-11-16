"""Telangana KNRUHS "MEDICAL PG DEGREE/DIPLOMA ADMISSIONS UNDER MANAGEMENT QUOTA FOR THE AY 2026-27 - PROVISIONAL MERIT
LIST OF CANDIDATES REGISTERED" (inbox 1727, 51 pages, 16.11.2026) -> rank-bridge rows under its OWN list_name
('PG Medical MQ Provisional Merit List (MD/MS + PG Diploma)'), so the CQ final list (3,613 rows) is not replaced.

Usage: /usr/bin/python3 read_knruhs_tg_mq.py <mq_merit.pdf> <out.json>

Columns: S.No, Rank (NEET PG AIR), Roll No, Score, Name, Gender, Category, Local, Muslim Minority, NRI Eligible,
Institutional Quota as per Applications. Read ONLY S.No, Rank, Roll, Score, Category, Local and the three YES flags
(by x position, checked against the header words on every page). Name and Gender are never read into the output, and
nothing per row is printed (counts only).
state_rank = S.No (one MQ merit list); air = Rank; score = Score; category as printed (OC, BC, OBC, SC, ST);
quota = the flags printed for the candidate ('Muslim Minority' / 'NRI eligible' / 'Institutional', joined by ', ') or ''.
Strict: S.No 1..n, one token per numeric column, known category / local, AIR never repeats -> else SystemExit.
"""
import sys, os, re, json, collections
import fitz

ROLL = re.compile(r'^2666\d{7}$')
INT = re.compile(r'^\d+$')
CATS = {'OC', 'BC', 'OBC', 'SC', 'ST'}
COLS = {'sno': (25, 70), 'rank': (70, 110), 'score': (175, 212), 'cat': (555, 600), 'local': (600, 628),
        'min': (628, 672), 'nri': (672, 708), 'inst': (708, 775)}
HDR = {'S.No': 33, 'Rank': 76, 'Roll': 127, 'Score': 183, 'Muslim': 631, 'Eligibl': 675, 'Application': 712}
FLAG = (('min', 'Muslim Minority'), ('nri', 'NRI eligible'), ('inst', 'Institutional'))


def main():
    pdf, out = sys.argv[1:3]
    d = fitz.open(pdf)
    t0 = ' '.join(d[0].get_text().split()).upper()
    for need in ('KALOJI NARAYANA RAO UNIVERSITY', 'UNDER MANAGEMENT QUOTA FOR THE AY 2026-27',
                 'PROVISIONAL MERIT LIST OF CANDIDATES REGISTERED'):
        if need not in t0:
            raise SystemExit('title changed: missing ' + need)
    md = re.search(r'06\.00 PM on (\d{2})\.(\d{2})\.(\d{4})', ' '.join(d[0].get_text().split()))
    rows, text_rolls = [], 0
    for p in d:
        ws = p.get_text('words')
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        hx = {w[4]: w[0] for w in ws if w[4] in HDR}
        if any(abs(hx.get(k, -99) - x) > 4 for k, x in HDR.items()):
            raise SystemExit(f'p{p.number + 1}: header positions moved')
        for r in [w for w in ws if ROLL.match(w[4])]:
            line = [w for w in ws if abs(w[1] - r[1]) < 2 and w is not r]
            cell = collections.defaultdict(list)
            for w in line:
                for k, (a, b) in COLS.items():
                    if a <= w[0] < b:
                        cell[k].append(w[4])
            where = f'p{p.number + 1}'
            if any(len(cell[k]) != 1 for k in ('sno', 'rank', 'score', 'cat', 'local')) or not all(
                    INT.match(cell[k][0]) for k in ('sno', 'rank', 'score')):
                raise SystemExit(f'{where}: row shape')
            if cell['cat'][0] not in CATS or cell['local'][0] not in ('OU', 'NL'):
                raise SystemExit(f'{where}: category / local value')
            if any(cell[k] not in ([], ['YES']) for k, _ in FLAG):
                raise SystemExit(f'{where}: flag value')
            rows.append({'roll': r[4], 'air': int(cell['rank'][0]), 'state_rank': int(cell['sno'][0]),
                         'score': int(cell['score'][0]), 'category': cell['cat'][0],
                         'quota': ', '.join(lbl for k, lbl in FLAG if cell[k]), '_local': cell['local'][0]})
    if text_rolls != len(rows) or len({r['roll'] for r in rows}) != len(rows):
        raise SystemExit('rolls in text != rows, or duplicate rolls')
    if [r['state_rank'] for r in rows] != list(range(1, len(rows) + 1)):
        raise SystemExit('S.No not 1..n in page order')
    if len({r['air'] for r in rows}) != len(rows):
        raise SystemExit('AIR repeats')
    checks = {'pages': d.page_count, 'row_count': len(rows), 'rolls_in_pdf_text': text_rolls,
              'by_category': dict(collections.Counter(r['category'] for r in rows)),
              'local': dict(collections.Counter(r['_local'] for r in rows)),
              'muslim_minority': sum('Muslim' in r['quota'] for r in rows),
              'nri_eligible': sum('NRI' in r['quota'] for r in rows),
              'institutional': sum('Institutional' in r['quota'] for r in rows),
              'air_range': [min(r['air'] for r in rows), max(r['air'] for r in rows)],
              'air_ascending_breaks': sum(1 for a, b in zip(rows, rows[1:]) if b['air'] < a['air'])}
    for r in rows:
        del r['_local']
    obj = {'authority_code': 'knruhs', 'list_name': 'PG Medical MQ Provisional Merit List (MD/MS + PG Diploma)',
           'published_on': f'{md.group(3)}-{md.group(2)}-{md.group(1)}' if md else '2026-11-16',
           'source_file_name': os.path.basename(pdf),
           'notes': ('KNRUHS MANAGEMENT QUOTA MD/MS + PG Diploma 2026-27 provisional merit list of registered candidates '
                     '(grievances till 6 PM 16.11.2026). Own list name - the CQ final merit list is separate. state_rank = '
                     'S.No; air = printed Rank; quota = the printed flags (Muslim Minority / NRI eligible / Institutional) '
                     'or empty.'),
           'row_count': len(rows), 'checks': checks, 'rows': rows}
    json.dump(obj, open(out, 'w'), indent=1, ensure_ascii=False)
    print(out); print(json.dumps(checks, indent=1))


if __name__ == '__main__':
    main()
