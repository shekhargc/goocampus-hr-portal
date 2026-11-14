"""Tripura (TRMCC / DME Tripura) "Provisional Merit List of Round-1 of Tripura Postgraduate Medical Counselling 2026"
-> rank-bridge rows.

Usage: /usr/bin/python3 read_dme_tripura.py <merit.pdf> [--out DIR]   (writes dme_tripura_r1_provisional.json)

Text-layer PDF (Microsoft Print to PDF, 10 pages, created 11.11.2026), one 9-column table: Sl no, NEET Roll No,
Candidate Name, Category, Sub Category, NEET Rank, NEET Marks, Marks After Incentive, Domicile.
Read ONLY: Sl no, roll, category, sub category, NEET rank (AIR), NEET marks, marks after incentive, domicile.
Candidate Name is never read into the output.

Corrigendum F.5(6)-DME/NEETPG/Counselling/2026/6948 dated 12.11.2026 (a one-page scan): the inclusion of one SC
candidate "stands withdrawn". That row is dropped here, matched by the SHA-256 of the roll number (no roll or name is
kept in this file); the reader stops if the hashed roll is not found exactly once or is not SC.
state_rank = printed Sl no (kept as printed - the withdrawn row leaves a gap); air = printed NEET Rank;
score = Marks After Incentive (the merit basis); category = Category (+ '-PwD' / '-WESM' for the sub category) in
short codes General / SC / ST / OBC / EWS; quota = '' for Tripura domicile, 'Other domicile' for Domicile 'Others'.
Strict: anything unexpected -> SystemExit.
"""
import sys, os, re, json, hashlib, collections
import fitz

DEFAULT_OUT = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/results_nov14/out/'
ROLL = re.compile(r'^2666\d{7}$')
INT = re.compile(r'^\d+$')
NUM = re.compile(r'^\d+(\.\d+)?$')
HEAD = ['Sl no', 'NEET Roll No', 'Candidate Name', 'Category', 'Sub Category', 'NEET Rank', 'NEET Marks',
        'Marks After Incentive', 'Domicile']
TITLE = 'Provisional Merit List of Round-1 of Tripura Postgraduate Medical Counselling 2026'
CATS = {'General': 'General', 'Schedule Tribe (ST)': 'ST', 'Schedule Caste (SC)': 'SC',
        'Other Backward Class (OBC)': 'OBC', 'General-EWS': 'EWS'}
SUBS = {'None': '', 'Person with Disability': '-PwD', 'Ward of Ex-Service Man (WESM)': '-WESM'}
DOMICILE = {'Tripura': '', 'Others': 'Other domicile'}
# corrigendum 12.11.2026 (No. .../6948): withdrawn inclusion, SC - sha256 of the roll number
WITHDRAWN = {'f685454683194aa279fec05f984731938cd0e5d3cf937a29efe9a12f49cb72ca': 'SC'}


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = sys.argv[1]
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else DEFAULT_OUT
    d = fitz.open(path)
    recs, text_rolls, head_seen, title_seen = [], 0, 0, 0
    for p in d:
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        for tb in p.find_tables().tables:
            for r in tb.extract():
                c = [' '.join((x or '').split()) for x in r]
                if len(c) != 9:
                    raise SystemExit(f'p{p.number + 1}: table with {len(c)} columns')
                if not INT.match(c[0]):
                    if c == HEAD:
                        head_seen += 1
                    elif c[0] == TITLE and not any(c[1:]):
                        title_seen += 1
                    else:
                        raise SystemExit(f'p{p.number + 1}: unexpected non-data row')
                    continue
                where = f'p{p.number + 1} sl {c[0]}'
                if not ROLL.match(c[1]):
                    raise SystemExit(f'{where}: roll shape')
                if c[3] not in CATS or c[4] not in SUBS or c[8] not in DOMICILE:
                    raise SystemExit(f'{where}: unknown category / sub category / domicile')
                if not INT.match(c[5]) or not NUM.match(c[6]) or not NUM.match(c[7]):
                    raise SystemExit(f'{where}: rank / marks not numeric')
                recs.append({'sl': int(c[0]), 'roll': c[1], 'cat': CATS[c[3]] + SUBS[c[4]], 'cat_main': CATS[c[3]],
                             'air': int(c[5]), 'neet': float(c[6]), 'total': float(c[7]), 'dom': DOMICILE[c[8]]})
    if title_seen != 1 or head_seen < 1:
        raise SystemExit('title / column headings not found')
    sl = [r['sl'] for r in recs]
    if sl != list(range(1, len(sl) + 1)):
        raise SystemExit('Sl no is not 1..n in print order')
    if text_rolls != len(recs):
        raise SystemExit(f'rolls in text {text_rolls} != rows {len(recs)}')
    if len({r['roll'] for r in recs}) != len(recs):
        raise SystemExit('duplicate rolls')
    h = lambda s: hashlib.sha256(s.encode()).hexdigest()
    withdrawn = [r for r in recs if h(r['roll']) in WITHDRAWN]
    if len(withdrawn) != len(WITHDRAWN) or any(r['cat_main'] != WITHDRAWN[h(r['roll'])] for r in withdrawn):
        raise SystemExit('corrigendum row not found exactly once with its category')
    keep = [r for r in recs if h(r['roll']) not in WITHDRAWN]
    total_breaks = [recs[i + 1]['sl'] for i in range(len(recs) - 1) if recs[i + 1]['total'] > recs[i]['total']]
    inc = [r for r in recs if r['total'] != r['neet']]
    rows = [{'roll': r['roll'], 'air': r['air'], 'state_rank': r['sl'], 'score': r['total'], 'category': r['cat'],
             'quota': r['dom']} for r in keep]
    checks = {
        'page_count': d.page_count, 'rows_printed': len(recs), 'rolls_in_pdf_text': text_rolls,
        'withdrawn_by_corrigendum_12_11_2026': [{'state_rank': r['sl'], 'category': r['cat']} for r in withdrawn],
        'row_count': len(rows), 'state_rank_source': "printed 'Sl no' (gap where the withdrawn row was)",
        'air_source': "printed 'NEET Rank'", 'air_min': min(r['air'] for r in rows), 'air_max': max(r['air'] for r in rows),
        'air_order_breaks_at_sl': [recs[i + 1]['sl'] for i in range(len(recs) - 1) if recs[i + 1]['air'] < recs[i]['air']][:30],
        'score_definition': "'Marks After Incentive' (merit basis)",
        'score_order_breaks_at_sl': total_breaks[:30], 'rows_with_incentive': len(inc),
        'categories': dict(collections.Counter(r['category'] for r in rows).most_common()),
        'quotas': dict(collections.Counter(r['quota'] or 'Tripura domicile' for r in rows).most_common()),
        'nbems_check': 'not done locally (NBEMS file not on this Mac) - the ingest counts air_mismatch by roll',
    }
    notes = ("DME Tripura (TRMCC) Round-1 provisional merit list of Tripura PG Medical Counselling 2026 (PDF of "
             "11.11.2026), with the corrigendum 6948 of 12.11.2026 applied (one SC inclusion withdrawn). state_rank = "
             "printed Sl no; score = marks after incentive; quota 'Other domicile' = Domicile 'Others' (blank = Tripura).")
    obj = {'authority_code': 'dme_tripura', 'list_name': 'PG Medical Round-1 Provisional Merit List',
           'published_on': '2026-11-11', 'source_file_name': 'TRMCC-PG-2026-Round1-Provisional-Merit-List.pdf',
           'notes': notes, 'row_count': len(rows), 'checks': checks, 'rows': rows}
    fp = os.path.join(out, 'dme_tripura_r1_provisional.json')
    with open(fp, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    print(fp)
    print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
