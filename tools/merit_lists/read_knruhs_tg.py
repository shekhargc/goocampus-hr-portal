"""Telangana KNRUHS "MEDICAL PG DEGREE/DIPLOMA ADMISSIONS UNDER COMPETENT AUTHORITY QUOTA FOR THE AY 2026-27 -
PROVISIONAL MERIT LIST OF REGISTERED CANDIDATES" -> rank-bridge rows.

Usage: /usr/bin/python3 read_knruhs_tg.py <merit.pdf> [--out DIR]   (writes knruhs_cq_provisional.json)

Columns printed: S.No, Rank (NEET PG AIR), Roll No, Score, Name of the Candidate, Gender, Category, Local, Minority,
Service, Remarks. Read ONLY S.No, Rank, Roll No, Score, Category, Local, Minority, Service and whether a remark is
printed. Name and Gender are never read into the output. state_rank = S.No (one common merit list; in-service
candidates ('S') are in the same order and get quota 'In-service', non-service ('NS') get quota '').
Rows are anchored on the roll-number token (x ~86); remarks wrap onto the lines below a row.
Strict: any row that does not have exactly one S.No / Rank / Score token, a 2666xxxxxxx roll, a known category,
local / minority / service value -> SystemExit. The 07.11.2026 list: 3,518 rows on 104 pages.
"""
import sys, os, re, json, collections
import fitz

DEFAULT_OUT = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/nov8/ml/'
ROLL = re.compile(r'^2666\d{7}$')
INT = re.compile(r'^\d+$')
CATS = {'OC', 'BCA', 'BCB', 'BCC', 'BCD', 'BCE', 'SC1', 'SC2', 'SC3', 'ST', 'EWS'}
HEAD = ['S.No', 'Rank', 'Roll', 'No', 'Score', 'Name', 'of', 'the', 'Candidate', 'Gender', 'Category', 'Local',
        'Minority', 'Service', 'Remarks']
# column x-ranges (page is 792 x 612 landscape); checked against the header words on every page
COLS = {'sno': (15, 50), 'rank': (48, 85), 'score': (145, 175), 'gender': (460, 495), 'cat': (495, 548),
        'local': (548, 578), 'min': (578, 628), 'serv': (628, 660), 'rem': (660, 792)}


def col(x):
    for k, (a, b) in COLS.items():
        if a <= x < b:
            return k
    return None


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = sys.argv[1]
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else DEFAULT_OUT
    d = fitz.open(path)
    title = ' '.join(d[0].get_text().split()).upper()
    for need in ('KALOJI NARAYANA RAO UNIVERSITY', 'COMPETENT AUTHORITY QUOTA', 'AY 2026-27', 'PROVISIONAL MERIT LIST'):
        if need not in title:
            raise SystemExit('title changed: missing ' + need)
    last = ' '.join(d[-1].get_text().split())
    m = re.search(r'Date\s*:\s*(\d{2})\.(\d{2})\.(\d{4})', last, re.I)
    published = f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else ''
    recs, text_rolls, hc_remarks = [], 0, 0
    for p in d:
        ws = p.get_text('words')
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        hc_remarks += len(re.findall(r'HIGH\s+COURT', p.get_text()))
        hy = [w for w in ws if w[4] == 'S.No']
        if len(hy) != 1:
            raise SystemExit(f'p{p.number + 1}: header row not found')
        hdr = sorted([w for w in ws if abs(w[1] - hy[0][1]) < 3], key=lambda w: w[0])
        if [w[4] for w in hdr] != HEAD:
            raise SystemExit(f'p{p.number + 1}: column headings changed')
        hx = {w[4]: w[0] for w in hdr}
        for k, x in (('Gender', 460), ('Category', 502), ('Local', 550), ('Minority', 582), ('Service', 629), ('Remarks', 699)):
            if abs(hx[k] - x) > 4:
                raise SystemExit(f'p{p.number + 1}: column {k} moved')
        anchors = sorted([w for w in ws if ROLL.match(w[4]) and 80 <= w[0] < 100], key=lambda w: w[1])
        stray_rolls = [w for w in ws if re.fullmatch(r'2666\d{7}', w[4]) and not (80 <= w[0] < 100)]
        if stray_rolls:
            raise SystemExit(f'p{p.number + 1}: roll outside the roll column')
        used = set()
        for i, a in enumerate(anchors):
            y0 = a[1] - 4
            y1 = anchors[i + 1][1] - 4 if i + 1 < len(anchors) else a[1] + 40
            band = [w for w in ws if y0 <= w[1] < y1 and w[1] > hy[0][1] + 5]
            if i + 1 == len(anchors):   # last row on the page: only its own line + wrapped Remarks (not the footer)
                band = [w for w in band if abs(w[1] - a[1]) < 3 or (col(w[0]) == 'rem' and w[4] not in ('Sd/-', 'REGISTRAR'))]
            used.update(id(w) for w in band)
            line = [w for w in band if abs(w[1] - a[1]) < 3]          # the row's own line
            g = collections.defaultdict(list)
            for w in line:
                c = col(w[0])
                if c:
                    g[c].append(w[4])
            wrapped = [w for w in band if abs(w[1] - a[1]) >= 3]
            if any(col(w[0]) not in ('rem',) for w in wrapped):
                raise SystemExit(f'p{p.number + 1} row {i + 1}: wrapped text outside Remarks')
            where = f'p{p.number + 1} row {i + 1}'
            for k in ('sno', 'rank', 'score'):
                if len(g[k]) != 1 or not INT.match(g[k][0]):
                    raise SystemExit(f'{where}: {k} not one integer ({len(g[k])} tokens)')
            if len(g['cat']) != 1 or g['cat'][0] not in CATS:
                raise SystemExit(f'{where}: unknown category')
            if g['local'] not in (['OU'], ['-']):
                raise SystemExit(f'{where}: unknown Local value')
            if g['min'] not in ([], ['MSM']):
                raise SystemExit(f'{where}: unknown Minority value')
            if g['serv'] not in (['NS'], ['S']):
                raise SystemExit(f'{where}: unknown Service value')
            if len(g['gender']) != 1 or g['gender'][0] not in ('M', 'F', 'T'):
                raise SystemExit(f'{where}: Gender column shape')   # shape check only, never stored
            recs.append({'sno': int(g['sno'][0]), 'rank': int(g['rank'][0]), 'roll': a[4], 'score': int(g['score'][0]),
                         'cat': g['cat'][0], 'local': g['local'][0], 'min': bool(g['min']), 'serv': g['serv'][0],
                         'remark': bool(g['rem'] or wrapped)})
        if anchors:
            top, bot = anchors[0][1] - 4, anchors[-1][1] + 3
            for w in ws:
                if top <= w[1] < bot and id(w) not in used and w[1] > hy[0][1] + 5:
                    raise SystemExit(f'p{p.number + 1}: stray word in data region')

    rows = [{'roll': r['roll'], 'air': r['rank'], 'state_rank': r['sno'], 'score': r['score'], 'category': r['cat'],
             'quota': 'In-service' if r['serv'] == 'S' else ''} for r in recs]
    sn = [r['state_rank'] for r in rows]
    if sn != list(range(1, len(sn) + 1)):
        raise SystemExit('S.No is not 1..n in print order')
    dup = [k for k, v in collections.Counter(r['roll'] for r in rows).items() if v > 1]
    if dup:
        raise SystemExit(f'{len(dup)} duplicate rolls')
    if text_rolls != len(rows):
        raise SystemExit(f'rolls in text {text_rolls} != rows {len(rows)}')
    air_breaks = [rows[i + 1]['state_rank'] for i in range(len(rows) - 1) if rows[i + 1]['air'] < rows[i]['air']]
    score_breaks = [rows[i + 1]['state_rank'] for i in range(len(rows) - 1) if rows[i + 1]['score'] > rows[i]['score']]
    air_dup = [k for k, v in collections.Counter(r['air'] for r in rows).items() if v > 1]
    checks = {
        'page_count': d.page_count, 'row_count': len(rows), 'rolls_in_pdf_text': text_rolls,
        'printed_total_expected': 3518, 'state_rank_1_to_n': True,
        'state_rank_source': "printed 'S.No' (list printed in merit order)",
        'air_source': "printed 'Rank' column (NEET PG AIR)", 'air_printed': sum(1 for r in rows if r['air']),
        'air_blank': sum(1 for r in rows if not r['air']), 'air_duplicates': air_dup[:20],
        'air_order_breaks_at_state_rank': air_breaks[:50], 'score_order_breaks_at_state_rank': score_breaks[:50],
        'air_min': min(r['air'] for r in rows), 'air_max': max(r['air'] for r in rows),
        'score_definition': "printed NEET PG 'Score'",
        'categories': dict(collections.Counter(r['category'] for r in rows).most_common()),
        'quotas': dict(collections.Counter(r['quota'] or '(non-service)' for r in rows).most_common()),
        'local_OU': sum(1 for r in recs if r['local'] == 'OU'), 'local_dash': sum(1 for r in recs if r['local'] == '-'),
        'high_court_remarks_in_text': hc_remarks,
        'minority_MSM': sum(1 for r in recs if r['min']),
        'nbems_check': 'not done locally (NBEMS file not on this Mac) - the ingest counts air_mismatch by roll',
    }
    if hc_remarks != checks['local_dash']:
        raise SystemExit("High Court remarks != Local '-' rows")
    if len(rows) != checks['printed_total_expected']:
        raise SystemExit(f'row count {len(rows)} != 3518 announced')
    notes = ("KNRUHS CQ MD/MS + PG Diploma 2026-27 provisional merit list of registered candidates. state_rank = S.No; "
             "AIR printed for every row; in-service (Service 'S') rows quota 'In-service'. Local '-' rows are the "
             "non-local candidates listed 'as per the directions of the Hon'ble High Court'. Grievances till 4 PM 09.11.2026.")
    obj = {'authority_code': 'knruhs', 'list_name': 'PG Medical CQ Provisional Merit List (MD/MS + PG Diploma)',
           'published_on': published, 'source_file_name': os.path.basename(path), 'notes': notes,
           'row_count': len(rows), 'checks': checks, 'rows': rows}
    fp = os.path.join(out, 'knruhs_cq_provisional.json')
    with open(fp, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    print(fp)
    print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
