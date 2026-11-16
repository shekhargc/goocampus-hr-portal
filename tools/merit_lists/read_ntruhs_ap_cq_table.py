"""Andhra Pradesh Dr NTRUHS PG (Medical) CQ merit list (in-service or non-service; provisional or provisional final)
-> rank-bridge rows, read with the PDF table finder (no NBEMS file needed; the ingest checks AIR by roll).

Usage: /usr/bin/python3 read_ntruhs_ap_cq_table.py <merit.pdf> [--out DIR] [--name-only]
  writes ntruhs_cq_<inservice|nonservice>_<provisional|provisional_final>.json

Columns: Sl.No, NEET Roll No, NEET Rank, NEET Score, Name of the Candidate, Gender, Category, Area, Muslim Minority,
PwBD. Read ONLY Sl.No, roll, rank, score, category, area, minority, PwBD. Name and Gender are never read into the
output, and nothing per-row is printed (counts only).
state_rank = Sl.No; air = NEET Rank; score = NEET Score; category as printed (OC, BC-A..BC-E, SC G-I..G-III, ST);
quota 'In-service' for the in-service list, '' for non-service. The stored list_name is the one the 31.10 list used
('PG Medical CQ Provisional Merit List — In-service' / '— Non-service'), so the 07.11 provisional FINAL list replaces it.
Strict: anything unexpected -> SystemExit.
"""
import sys, os, re, json, collections
import fitz

DEFAULT_OUT = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/results_nov14/out/'
ROLL = re.compile(r'^2666\d{7}$')
INT = re.compile(r'^\d+$')
HEAD = ['Sl.No', 'NEET Roll No', 'NEET Rank', 'NEET Score', 'Name of the Candidate', 'Gender', 'Category', 'Area',
        'Muslim Minority', 'PwBD']
CATS = {'OC', 'BC-A', 'BC-B', 'BC-C', 'BC-D', 'BC-E', 'SC G-I', 'SC G-II', 'SC G-III', 'SC', 'ST', 'EWS'}
AREAS = {'AU', 'SVU', 'APNL', 'OU', 'NL'}
YN = {'Yes', 'No'}


def read(path):
    d = fitz.open(path)
    t0 = ' '.join(d[0].get_text().split()).upper()
    kind = 'inservice' if re.search(r'IN-?\s?SERVICE CANDIDATES', t0) else 'nonservice' if re.search(r'NON-?\s?SERVICE CANDIDATES', t0) else None
    if not kind:
        raise SystemExit('list title not understood (in-service / non-service)')
    stage = 'provisional_final' if 'PROVISIONAL FINAL MERIT' in t0 else 'provisional' if 'PROVISIONAL MERIT' in t0 else None
    if not stage:
        raise SystemExit('list stage not understood')
    recs, text_rolls, heads = [], 0, 0
    for p in d:
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        for t in p.find_tables().tables:
            for r in t.extract():
                c = [' '.join((x or '').split()) for x in r]
                if c == HEAD:
                    heads += 1
                    continue
                if len(c) != 10 or not ROLL.match(c[1]):
                    raise SystemExit(f'p{p.number + 1}: unexpected row')
                if not (INT.match(c[0]) and INT.match(c[2]) and INT.match(c[3])):
                    raise SystemExit(f'p{p.number + 1}: Sl.No / rank / score shape')
                if c[6] not in CATS or c[7] not in AREAS or c[8] not in YN or c[9] not in YN:
                    raise SystemExit(f'p{p.number + 1}: unknown category / area / Yes-No value')
                recs.append({'sl': int(c[0]), 'roll': c[1], 'air': int(c[2]), 'score': int(c[3]), 'cat': c[6],
                             'area': c[7], 'min': c[8] == 'Yes', 'pwbd': c[9] == 'Yes'})
    sl = [r['sl'] for r in recs]
    if not heads or sl != list(range(1, len(sl) + 1)):
        raise SystemExit('headings missing or Sl.No not 1..n')
    if text_rolls != len(recs) or len({r['roll'] for r in recs}) != len(recs):
        raise SystemExit('rolls in text != rows, or duplicate rolls')
    return d, kind, stage, recs


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = sys.argv[1]
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else DEFAULT_OUT
    d, kind, stage, recs = read(path)
    rows = [{'roll': r['roll'], 'air': r['air'], 'state_rank': r['sl'], 'score': r['score'], 'category': r['cat'],
             'quota': 'In-service' if kind == 'inservice' else ''} for r in recs]
    checks = {
        'kind': kind, 'stage': stage, 'page_count': d.page_count, 'row_count': len(rows),
        'air_min': min(r['air'] for r in rows), 'air_max': max(r['air'] for r in rows),
        'air_order_breaks': sum(1 for a, b in zip(rows, rows[1:]) if b['air'] < a['air']),
        'score_order_breaks': sum(1 for a, b in zip(rows, rows[1:]) if b['score'] > a['score']),
        'categories': dict(collections.Counter(r['category'] for r in rows).most_common()),
        'area': dict(collections.Counter(r['area'] for r in recs)),
        'muslim_minority_yes': sum(r['min'] for r in recs), 'pwbd_yes': sum(r['pwbd'] for r in recs),
    }
    name = 'PG Medical CQ Provisional Merit List — ' + ('In-service' if kind == 'inservice' else 'Non-service')
    label = 'provisional FINAL merit list (07.11.2026)' if stage == 'provisional_final' else 'provisional merit list (31.10.2026)'
    notes = (f"Dr NTRUHS CQ 2026-27 {'in-service' if kind == 'inservice' else 'non-service'} {label}; state_rank = Sl.No; "
             "AIR and NEET score printed for every row." + (" Replaces the 31.10 provisional list under the same list name."
                                                            if stage == 'provisional_final' else ''))
    obj = {'authority_code': 'ntruhs', 'list_name': name,
           'published_on': '2026-11-07' if stage == 'provisional_final' else '',
           'source_file_name': f"NTRUHS-PG-Medical-CQ-2026-27-{'InService' if kind == 'inservice' else 'NonService'}-"
                               f"{'Provisional-Final' if stage == 'provisional_final' else 'Provisional'}-Merit-List.pdf",
           'notes': notes, 'row_count': len(rows), 'checks': checks, 'rows': rows}
    fp = os.path.join(out, f'ntruhs_cq_{kind}_{stage}.json')
    with open(fp, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    print(fp)
    print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
