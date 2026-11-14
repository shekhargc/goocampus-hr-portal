"""Manipur (DME / DHS Manipur) Round 1 State Level Medical PG Counselling 2026-27 merit lists -> rank-bridge rows.

Usage: /usr/bin/python3 read_dhs_manipur.py <annexure.pdf> [<annexure.pdf> ...] [--out DIR]
  writes one dhs_manipur_r1_<annexure>.json per file.

Notification No. DME-5/1/2026-HEALTH, Imphal 13.11.2026 (a scan, linked from manipurhealthdirectorate.mn.gov.in/news/592
together with nine text-layer PDFs, uploads/media/2026/11/14/m*.pdf). One merit list per institute x category:
  A RIMS Graduate Open, B Non-RIMS Open, C RIMS In-service (RIMS, Imphal); D JNIMS Direct, E JNIMS Institutional
  Preference, F JNIMS In-service (JNIMS, Porompat); G SAHS State Quota Direct, H SAHS State Quota In-service,
  I SAHS Management Quota (SAHS, Langol).
Columns: State Merit Rank, NEET-PG Roll No, Candidate Name, Category, Sub- Category, Is PwD, NEET-PG Score,
[Inceptive marks, Total NEET-PG Score - in-service lists], NEET-PG AIR; Management (I): State Merit Rank, Roll, Name,
NEET-PG Score, NEET-PG AIR. Candidate Name is never read into the output.
state_rank = printed State Merit Rank (1..n WITHIN each list); air = printed NEET-PG AIR; score = Total NEET-PG Score
(in-service lists, incl. incentive) else NEET-PG Score; category = Category + '/' + Sub-Category when printed
(OBC-M, OBC-MP, EWS ...) + ' PwD' when Is PwD is YES/TRUE; quota = the list (e.g. 'RIMS Graduate Open').
Each list is stored under its own list_name, since the ranks restart in every list.
Strict: anything unexpected -> SystemExit.
"""
import sys, os, re, json, collections
import fitz

DEFAULT_OUT = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/results_nov14/out/'
ROLL = re.compile(r'^2666\d{7}$')
INT = re.compile(r'^\d+$')
NUM = re.compile(r'^\d+(\.\d+)?$')
KINDS = {   # title text -> (annexure, quota label)
    'RIMS GRADUATE OPEN CATEGORY': ('A', 'RIMS Graduate Open'), 'NON-RIMS OPEN CATEGORY': ('B', 'Non-RIMS Open'),
    'RIMS IN-SERVICE CATEGORY': ('C', 'RIMS In-service'), 'JNIMS DIRECT CATEGORY': ('D', 'JNIMS Direct'),
    'JNIMS INSTITUTIONAL PREFERENCE CATEGORY': ('E', 'JNIMS Institutional Preference'),
    'JNIMS IN-SERVICE CATEGORY': ('F', 'JNIMS In-service'), 'SAHS STATE QUOTA DIRECT CATEGORY': ('G', 'SAHS State Quota Direct'),
    'SAHS STATE QUOTA IN-SERVICE CATEGORY': ('H', 'SAHS State Quota In-service'),
    'SAHS MANAGEMENT QUOTA': ('I', 'SAHS Management Quota'),
}
H8 = ['State Merit Rank', 'NEET-PG Roll No', 'Candidate Name', 'Category', 'Sub- Category', 'Is PwD', 'NEET-PG Score',
      'NEET-PG AIR']
H10 = H8[:7] + ['Inceptive marks', 'Total NEET-PG Score', 'NEET-PG AIR']
H5 = ['State Merit Rank', 'NEET-PG Roll No', 'Candidate Name', 'NEET-PG Score', 'NEET-PG AIR']
CATS = {'GENERAL', 'OBC', 'SC', 'ST'}
SUBS = {'-', 'OBC-M', 'OBC-MP', 'OBC', 'EWS'}
PWD = {'NO': False, 'YES': True, 'TRUE': True, 'FALSE': False}


def read(path, out):
    d = fitz.open(path)
    t0 = ' '.join(d[0].get_text().split())
    m = re.search(r'MERIT LIST OF CANDIDATES APPLYING FOR (.+?) ANNEXURE-([A-I])\b', t0)
    if not m or m.group(1) not in KINDS or KINDS[m.group(1)][0] != m.group(2):
        raise SystemExit(f'{os.path.basename(path)}: list title not understood')
    ann, label = KINDS[m.group(1)]
    recs, text_rolls, heads = [], 0, 0
    for p in d:
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        for t in p.find_tables().tables:
            for r in t.extract():
                c = [' '.join((x or '').split()) for x in r]
                c = [x.replace('NEET- PG', 'NEET-PG') for x in c] if not ROLL.match(c[1] if len(c) > 1 else '') else c
                if c in (H8, H10, H5):
                    heads += 1
                    width = len(c)
                    continue
                if len(c) < 2 or not ROLL.match(c[1]):
                    raise SystemExit(f'p{p.number + 1}: unexpected non-data row')
                where = f'{ann} p{p.number + 1} rank {c[0] if INT.match(c[0]) else "?"}'
                if not heads or len(c) != width or not INT.match(c[0]) or not INT.match(c[-1]):
                    raise SystemExit(f'{where}: row shape')
                if width == 5:
                    if not INT.match(c[3]):
                        raise SystemExit(f'{where}: score not numeric')
                    cat, score = '', float(c[3])
                else:
                    if c[3] not in CATS or c[4] not in SUBS or c[5] not in PWD:
                        raise SystemExit(f'{where}: unknown category / sub-category / PwD')
                    if not all(NUM.match(x) for x in c[6:-1]):
                        raise SystemExit(f'{where}: score columns not numeric')
                    score = float(c[8]) if width == 10 else float(c[6])
                    if width == 10 and abs(float(c[6]) + float(c[7]) - float(c[8])) > 0.01:
                        raise SystemExit(f'{where}: score + incentive != total')
                    cat = c[3] + ('' if c[4] == '-' else '/' + c[4]) + (' PwD' if PWD[c[5]] else '')
                recs.append({'rank': int(c[0]), 'roll': c[1], 'air': int(c[-1]), 'score': score, 'cat': cat})
    ranks = [r['rank'] for r in recs]
    if ranks != list(range(1, len(ranks) + 1)):
        raise SystemExit(f'{ann}: State Merit Rank not 1..n')
    if text_rolls != len(recs) or len({r['roll'] for r in recs}) != len(recs):
        raise SystemExit(f'{ann}: rolls in text {text_rolls} / rows {len(recs)} / duplicates')
    rows = [{'roll': r['roll'], 'air': r['air'], 'state_rank': r['rank'], 'score': int(r['score']) if r['score'].is_integer()
             else r['score'], 'category': r['cat'], 'quota': label} for r in recs]
    checks = {
        'annexure': ann, 'list': label, 'page_count': d.page_count, 'row_count': len(rows), 'rolls_in_pdf_text': text_rolls,
        'state_rank_1_to_n': True, 'air_min': min(r['air'] for r in rows), 'air_max': max(r['air'] for r in rows),
        'air_order_breaks_at_rank': [rows[i + 1]['state_rank'] for i in range(len(rows) - 1) if rows[i + 1]['air'] < rows[i]['air']][:30],
        'score_order_breaks_at_rank': [rows[i + 1]['state_rank'] for i in range(len(rows) - 1) if rows[i + 1]['score'] > rows[i]['score']][:30],
        'categories': dict(collections.Counter(r['category'] for r in rows).most_common()),
        'nbems_check': 'not done locally (NBEMS file not on this Mac) - the ingest counts air_mismatch by roll',
    }
    notes = (f"DME Manipur Round 1 State Level Medical PG Counselling 2026-27 merit list, Annexure-{ann}: {label} "
             "(notification DME-5/1/2026-HEALTH, 13.11.2026). state_rank = State Merit Rank within this list; score = "
             "NEET-PG score (in-service lists: total incl. incentive); AIR printed for every row.")
    obj = {'authority_code': 'dhs_manipur', 'list_name': f'Round 1 Merit List - Annexure {ann}: {label}',
           'published_on': '2026-11-13', 'source_file_name': f'Manipur-PG-2026-R1-Merit-Annexure-{ann}.pdf',
           'notes': notes, 'row_count': len(rows), 'checks': checks, 'rows': rows}
    fp = os.path.join(out, f'dhs_manipur_r1_{ann}.json')
    with open(fp, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    print(fp, json.dumps({k: checks[k] for k in ('list', 'row_count', 'air_order_breaks_at_rank', 'score_order_breaks_at_rank')}))
    return checks


def main():
    args = sys.argv[1:]
    out = DEFAULT_OUT
    if '--out' in args:
        i = args.index('--out'); out = args[i + 1]; args = args[:i] + args[i + 2:]
    if not args:
        raise SystemExit(__doc__)
    for a in args:
        read(a, out)


if __name__ == '__main__':
    main()
