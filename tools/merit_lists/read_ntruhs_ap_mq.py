"""Andhra Pradesh Dr NTRUHS "PG (Medical) MQ 2026-27 - Provisional Final Merit list" (management quota, Category B /
C seats of private colleges) -> rank-bridge rows.

Usage: /usr/bin/python3 read_ntruhs_ap_mq.py <merit.pdf> [--out DIR]   (writes ntruhs_mq_provisional_final.json)

Text-layer PDF (Microsoft Print to PDF, 83 pages, 12.11.2026). Title: "PROVISIONAL FINAL MERIT LIST OF CANDIDATES
AFTER VERIFICATION OF SCANNED UPLOADED CERTIFICATES AND AFTER EXAMINATION OF THE GRIEVANCES". One 14-column table:
Sl.NO, NEET Roll No, NEET RANK, NEET Score, Name of the Candidate, Gender, Category, Area (Andhra Pradesh / Others),
Muslim Minority, Eligible for Sub Category-1 (S1) S1A / S1B, Claiming NRI (S2) Quota, Claiming Institutional (S3)
Quota, Claiming NRI Lapsed Quota.
Read ONLY: Sl.NO, roll, rank, score, category, area and the Yes/No columns (counted). Name and Gender are never put
in the output (Gender is shape-checked only).
state_rank = Sl.NO (MQ merit order); air = NEET RANK; score = NEET Score; category as printed; quota 'MQ'.
Strict: anything unexpected -> SystemExit.
"""
import sys, os, re, json, collections
import fitz

DEFAULT_OUT = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/results_nov14/out/'
ROLL = re.compile(r'^2666\d{7}$')
INT = re.compile(r'^\d+$')
HEAD = ['Sl.NO', 'NEET Roll No', 'NEET RANK', 'NEET Score', 'Name of the Candidate', 'Gender', 'Category', 'Area',
        'Muslim Minority', 'Eligible for Sub Category-1 (S1)', '', 'Claiming NRI (S2) Quota',
        'Claiming Institutional (S3) Quota', 'Claiming NRI Lapsed Quota']
HEAD2 = ['', '', '', '', '', '', '', '', '', 'S1A', 'S1B', '', '', '']
CATS = {'OC', 'BC-A', 'BC-B', 'BC-C', 'BC-D', 'BC-E', 'SC G-I', 'SC G-II', 'SC G-III', 'SC', 'ST', 'EWS', 'OBC'}
AREAS = {'Andhra Pradesh', 'Others'}
YN = {'Yes', 'No'}


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = sys.argv[1]
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else DEFAULT_OUT
    d = fitz.open(path)
    t0 = ' '.join(d[0].get_text().split()).upper()
    for need in ('PROVISIONAL FINAL MERIT LIST OF CANDIDATES', 'MANAGEMENT', '2026-27'):
        if need not in t0:
            raise SystemExit('title changed: missing ' + need)
    recs, text_rolls, heads = [], 0, 0
    flags = collections.Counter()
    for p in d:
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        for tb in p.find_tables().tables:
            for r in tb.extract():
                c = [' '.join((x or '').split()) for x in r]
                if len(c) != 14:
                    raise SystemExit(f'p{p.number + 1}: table with {len(c)} columns')
                if not INT.match(c[0]):
                    if c == HEAD or c == HEAD2:
                        heads += c == HEAD
                        continue
                    raise SystemExit(f'p{p.number + 1}: unexpected non-data row')
                where = f'p{p.number + 1} sl {c[0]}'
                if not ROLL.match(c[1]) or not INT.match(c[2]) or not INT.match(c[3]):
                    raise SystemExit(f'{where}: roll / rank / score shape')
                if c[5] not in ('MALE', 'FEMALE', 'TRANSGENDER'):
                    raise SystemExit(f'{where}: gender column shape')    # shape check only, never stored
                if c[6] not in CATS or c[7] not in AREAS or any(x not in YN for x in c[8:14]):
                    raise SystemExit(f'{where}: unknown category / area / Yes-No value')
                for i, k in ((8, 'muslim_minority'), (9, 'S1A'), (10, 'S1B'), (11, 'S2_NRI'), (12, 'S3_institutional'),
                             (13, 'NRI_lapsed')):
                    flags[k] += c[i] == 'Yes'
                recs.append({'sl': int(c[0]), 'roll': c[1], 'air': int(c[2]), 'score': int(c[3]), 'cat': c[6],
                             'area': c[7], 's1b': c[10] == 'Yes'})
    if heads != d.page_count:
        raise SystemExit('column headings not on every page')
    sl = [r['sl'] for r in recs]
    if sl != list(range(1, len(sl) + 1)):
        raise SystemExit('Sl.NO is not 1..n in print order')
    if text_rolls != len(recs):
        raise SystemExit(f'rolls in text {text_rolls} != rows {len(recs)}')
    if len({r['roll'] for r in recs}) != len(recs):
        raise SystemExit('duplicate rolls')
    if any((r['area'] == 'Andhra Pradesh') != r['s1b'] for r in recs):
        flags['S1B_differs_from_area'] += 1
    rows = [{'roll': r['roll'], 'air': r['air'], 'state_rank': r['sl'], 'score': r['score'], 'category': r['cat'],
             'quota': 'MQ'} for r in recs]
    checks = {
        'page_count': d.page_count, 'row_count': len(rows), 'rolls_in_pdf_text': text_rolls,
        'state_rank_source': "printed 'Sl.NO' (MQ merit order)", 'air_source': "printed 'NEET RANK'",
        'air_min': min(r['air'] for r in rows), 'air_max': max(r['air'] for r in rows),
        'air_order_breaks_at_sl': [rows[i + 1]['state_rank'] for i in range(len(rows) - 1) if rows[i + 1]['air'] < rows[i]['air']][:30],
        'score_order_breaks_at_sl': [rows[i + 1]['state_rank'] for i in range(len(rows) - 1) if rows[i + 1]['score'] > rows[i]['score']][:30],
        'air_duplicates': [k for k, v in collections.Counter(r['air'] for r in rows).items() if v > 1][:20],
        'categories': dict(collections.Counter(r['category'] for r in rows).most_common()),
        'area': dict(collections.Counter(r['area'] for r in recs)), 'yes_counts': dict(flags),
        'nbems_check': 'not done locally (NBEMS file not on this Mac) - the ingest counts air_mismatch by roll',
    }
    notes = ("Dr NTRUHS PG (Medical) Management Quota 2026-27 provisional FINAL merit list (after certificate "
             "verification and grievances, 12.11.2026). One MQ list (Category B / C seats); state_rank = Sl.NO; AIR and "
             "score printed for every row; quota 'MQ'. Sub-category eligibility (S1A / S1B / S2 NRI / S3 institutional / "
             "NRI lapsed) counted only.")
    obj = {'authority_code': 'ntruhs', 'list_name': 'PG Medical MQ Provisional Final Merit List',
           'published_on': '2026-11-12', 'source_file_name': 'NTRUHS-PG-Medical-MQ-2026-27-Provisional-Final-Merit-List.pdf',
           'notes': notes, 'row_count': len(rows), 'checks': checks, 'rows': rows}
    fp = os.path.join(out, 'ntruhs_mq_provisional_final.json')
    with open(fp, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    print(fp)
    print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
