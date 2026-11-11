"""Puducherry CENTAC "Draft Merit list of PG NEET Medical (M.D./M.S.) courses (2026 - 2027)" -> rank-bridge rows.

Usage: /usr/bin/python3 read_centac_py.py <list.pdf> [<list.pdf> ...] [--out DIR]
  Detects the list from the title line above the table:
   'GOVERNMENT QUOTA - U.T. - OVERALL' -> centac_gq_draft.json  (quota 'GQ')
   'MANAGEMENT QUOTA - OVERALL'        -> centac_mq_draft.json  (quota 'MQ')
  Any other title (the FF / PwD / ESM / Telugu-minority sub-lists, the 'applied' list) -> SystemExit: the
  sub-lists are subsets of GQ-ALL / MQ-ALL and the applied list has no merit order of its own.

The files are the Google-Drive PDFs linked ("View") from
https://centacpuducherry.in/htmlpages/2026/PgMedical_2026/Draft_merit_list.html (published 06-11-2026).
GQ columns: SL NO, APP NO, NAME, NEET ROLL NO, NEET PERCENTILE (really the NEET score), NEET ALL INDIA RANK,
RESIDENCE, CATEGORY.  MQ columns: the same without RESIDENCE, with AIQ CATEGORY instead of CATEGORY.
Read ONLY: SL NO, roll, score, AIR, residence, category, and whether a '#', '$' or '&' marker is printed after the
name (legend: '#' eligible for private institutions only, '$' residence & community certificate per W.A./W.P.
No.960 of 2026, '&' PwBD verification pending) - counted, never stored with the row. APP NO and NAME are never read
into the output. state_rank = SL NO. Rows are anchored on the roll token; the striped-table finder misses every
other row here, so words are used, not find_tables.
Strict: anything unexpected -> SystemExit.
"""
import sys, os, re, json, collections
import fitz

DEFAULT_OUT = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/nov8/ml/'
ROLL = re.compile(r'^2666\d{7}$')
INT = re.compile(r'^\d+$')
KINDS = {
    'GOVERNMENT QUOTA - U.T. - OVERALL': dict(
        short='gq_draft', quota='GQ', list_name='PG Medical (MD/MS) Draft Merit List - Government Quota (UT, overall)',
        head='SL NO APP NO NAME NEET ROLL NO NEET PERCENTILE NEET ALL INDIA RANK RESIDENCE CATEGORY',
        cols={'sl': (25, 60), 'app': (60, 115), 'name': (115, 340), 'roll': (340, 420), 'score': (420, 520),
              'air': (520, 640), 'res': (640, 720), 'cat': (720, 842)},
        cats={'GENERAL', 'OBC', 'MBC', 'SC', 'ST', 'EBC', 'BCM', 'BT'}, subs={'FF', 'ESM', 'TELUGU', 'PwD'}),
    'MANAGEMENT QUOTA - OVERALL': dict(
        short='mq_draft', quota='MQ', list_name='PG Medical (MD/MS) Draft Merit List - Management Quota (overall)',
        head='SL NO APP NO NAME NEET ROLL NO NEET PERCENTILE NEET ALL INDIA RANK AIQ CATEGORY',
        cols={'sl': (25, 62), 'app': (62, 120), 'name': (120, 400), 'roll': (400, 485), 'score': (485, 595),
              'air': (595, 720), 'cat': (720, 842)},
        cats={'GENERAL', 'OBC', 'SC', 'ST', 'EWS'}, subs=set()),
}


def colof(cols, x):
    for k, (a, b) in cols.items():
        if a <= x < b:
            return k
    return None


def read(path, out):
    d = fitz.open(path)
    p0 = d[0].get_text('words')
    hy = [w for w in p0 if w[4] == 'SL']
    if len(hy) != 1:
        raise SystemExit(f'{os.path.basename(path)}: header row not found')
    ttl = ' '.join(w[4] for w in sorted(p0, key=lambda w: w[0]) if abs(w[1] - (hy[0][1] - 17)) < 4)
    m = re.match(r'(.*?)\s+DATE\s*:\s*(\d{2})-(\d{2})-(\d{4})$', ttl)
    if not m or m.group(1) not in KINDS:
        raise SystemExit(f'{os.path.basename(path)}: not GQ-ALL / MQ-ALL (title: {m.group(1) if m else ttl[:60]})')
    K = KINDS[m.group(1)]
    published = f'{m.group(4)}-{m.group(3)}-{m.group(2)}'
    top = ' '.join(w[4] for w in p0 if w[1] < hy[0][1] - 20)
    # 10-11-2026 REVISED draft list drops the '(2026 - 2027)' from the title — same list, replaces the draft
    if 'Draft Merit list of PG NEET Medical (M.D./M.S.) courses' not in top:
        raise SystemExit('page title changed')
    recs, text_rolls, markers, ended = [], 0, collections.Counter(), False
    for p in d:
        ws = p.get_text('words')
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        h = [w for w in ws if w[4] == 'SL']
        if len(h) != 1:
            raise SystemExit(f'p{p.number + 1}: header row not found')
        hdr = ' '.join(w[4] for w in sorted(ws, key=lambda w: w[0]) if abs(w[1] - h[0][1]) < 3)
        if hdr.replace('NEET SCORE', 'NEET PERCENTILE') != K['head']:      # revised list renamed the column
            raise SystemExit(f'p{p.number + 1}: column headings changed')
        end = [w for w in ws if w[4] == '***']
        y_end = min(w[1] for w in end) if end else 1e9
        ended = ended or bool(end)
        foot = [w for w in ws if w[4] == 'NOTE' and w[0] < 60]
        y_end = min([y_end] + [w[1] for w in foot])
        body = [w for w in ws if h[0][1] + 5 < w[1] < y_end - 2]
        anchors = sorted([w for w in body if ROLL.match(w[4])], key=lambda w: w[1])
        used = set()
        for i, a in enumerate(anchors):
            y0 = a[1] - 4
            y1 = anchors[i + 1][1] - 4 if i + 1 < len(anchors) else a[1] + 12
            band = [w for w in body if y0 <= w[1] < y1]
            used.update(id(w) for w in band)
            g = collections.defaultdict(list)
            for w in sorted(band, key=lambda w: (round(w[1]), w[0])):
                c = colof(K['cols'], w[0])
                if c is None:
                    raise SystemExit(f'p{p.number + 1}: word outside the columns')
                if abs(w[1] - a[1]) >= 3 and c not in ('name', 'cat'):
                    raise SystemExit(f'p{p.number + 1}: wrapped text outside Name / Category')
                g[c].append(w[4])
            where = f'p{p.number + 1} row {i + 1}'
            for k in ('sl', 'app', 'score', 'air'):
                if len(g[k]) != 1 or not INT.match(g[k][0]):
                    raise SystemExit(f'{where}: {k} not one integer')
            if g['roll'] != [a[4]]:
                raise SystemExit(f'{where}: roll column shape')
            if 'res' in K['cols']:
                if g['res'][:1] != ['PY']:
                    raise SystemExit(f'{where}: residence not PY')
                g['cat'] = g['res'][1:] + g['cat']   # a long category ('GENERAL/') can start left of its column
            cat = ''.join(g['cat'])
            parts = cat.split('/')
            if not parts[0] in K['cats'] or len(parts) > 2 or (len(parts) == 2 and parts[1] not in K['subs']):
                raise SystemExit(f'{where}: unknown category')
            for mk in '#$&':
                if any(t.endswith(mk) for t in g['name']):
                    markers[mk] += 1
            recs.append({'sl': int(g['sl'][0]), 'roll': a[4], 'score': int(g['score'][0]), 'air': int(g['air'][0]),
                         'cat': cat})
        for w in body:
            if id(w) not in used:
                raise SystemExit(f'p{p.number + 1}: stray word in data region')
    if not ended:
        raise SystemExit("'*** End of The Report ***' not found")
    sl = [r['sl'] for r in recs]
    if sl != list(range(1, len(sl) + 1)):
        raise SystemExit('SL NO is not 1..n in print order')
    if text_rolls != len(recs):
        raise SystemExit(f'rolls in text {text_rolls} != rows {len(recs)}')
    if len({r['roll'] for r in recs}) != len(recs):
        raise SystemExit('duplicate rolls')
    rows = [{'roll': r['roll'], 'air': r['air'], 'state_rank': r['sl'], 'score': r['score'], 'category': r['cat'],
             'quota': K['quota']} for r in recs]
    checks = {
        'page_count': d.page_count, 'row_count': len(rows), 'rolls_in_pdf_text': text_rolls,
        'printed_total': "none printed; last SL NO = row count; '*** End of The Report ***' present",
        'state_rank_1_to_n': True, 'state_rank_source': "printed 'SL NO' (list printed in merit order)",
        'air_source': "printed 'NEET ALL INDIA RANK'", 'air_printed': len(rows), 'air_blank': 0,
        'air_min': min(r['air'] for r in rows), 'air_max': max(r['air'] for r in rows),
        'air_order_breaks_at_state_rank': [rows[i + 1]['state_rank'] for i in range(len(rows) - 1)
                                           if rows[i + 1]['air'] < rows[i]['air']][:50],
        'score_order_breaks_at_state_rank': [rows[i + 1]['state_rank'] for i in range(len(rows) - 1)
                                             if rows[i + 1]['score'] > rows[i]['score']][:50],
        'air_duplicates': [k for k, v in collections.Counter(r['air'] for r in rows).items() if v > 1][:20],
        'score_definition': "column headed 'NEET PERCENTILE' holds the NEET PG score (cut-offs GE 262 / GE-PH 244 / "
                            "reserved 226 printed in the same marks)",
        'min_score': min(r['score'] for r in rows),
        'categories': dict(collections.Counter(r['category'] for r in rows).most_common()),
        'quotas': dict(collections.Counter(r['quota'] for r in rows).most_common()),
        'name_markers': dict(markers),
        'marker_legend': "'#' eligible for private institutions only; '$' residence & community certificate per "
                         "W.P. No.960 of 2026; '&' PwBD verification pending",
        'nbems_check': 'not done locally (NBEMS file not on this Mac) - the ingest counts air_mismatch by roll',
    }
    which = ('Government Quota UT overall (category as printed, sub-category after /: FF / ESM / TELUGU / PwD)'
             if K['quota'] == 'GQ' else 'Management Quota overall (AIQ category)')
    notes = ("CENTAC Puducherry PG Medical (MD/MS) 2026-27 draft merit list, " + which + "; state_rank = SL NO; AIR "
             "printed for every row. Objections till 5 PM 09-11-2026. Sub-lists (FF/PwD/ESM/Telugu MQ) are subsets "
             "of GQ-ALL / MQ-ALL.")
    obj = {'authority_code': 'centac', 'list_name': K['list_name'], 'published_on': published,
           'source_file_name': os.path.basename(path), 'notes': notes, 'row_count': len(rows), 'checks': checks,
           'rows': rows}
    fp = os.path.join(out, f"centac_{K['short']}.json")
    with open(fp, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    print(fp)
    print(json.dumps(checks, indent=1, ensure_ascii=False))


def main():
    args = sys.argv[1:]
    out = DEFAULT_OUT
    if '--out' in args:
        i = args.index('--out')
        out = args[i + 1]
        args = args[:i] + args[i + 2:]
    if not args:
        raise SystemExit(__doc__)
    for a in args:
        read(a, out)


if __name__ == '__main__':
    main()
