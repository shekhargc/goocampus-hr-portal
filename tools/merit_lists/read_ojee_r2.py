"""Odisha PG Medical — REVISED COMMON MERIT LIST (AFTER NEW REGISTRATION BEFORE ROUND-2), 23.11.2026 (inbox 1940).
Usage: read_ojee_r2.py <pdf> [--out DIR]   (default DIR = $MERIT_OUT or the current directory)

Same four lists as the 31 Oct file read by read_ojee.py (Direct / In-service / DNB / Post-MBBS NBEMS Diploma) plus a
rejected-applications list (skipped), but a different layout:
  * page 1 is a scanned cover notice (no text layer) — skipped;
  * only the FIRST page of each list carries the list title, the following pages continue that list;
  * the drawn grid has 29 vertical lines = left edges of NEET Roll No … Rank-EWS + the right border
    (no Appln-No left edge, no EWS-PwD column), so the fields are read_ojee.FIELDS[1:-1].
Kept: roll, printed NEET AIR, 'Rank-CMR' (the common merit rank every candidate gets), New Score, category.
Names, application numbers and sub-categories are never read into the output (nor printed).
AIR is checked against the NBEMS result server-side at ingest (POST /api/pg/state-merit/ingest → air_mismatch)."""
import collections
import json
import os
import re
import sys

import fitz
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_ojee import FIELDS, ROLL_RE, page_title, grid, num, category, contig

PDF = sys.argv[1]
OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else os.environ.get('MERIT_OUT', '.')
FIELDS_R2 = FIELDS[1:-1]
KEEP = ('roll', 'type', 'cat', 'neet', 'wt', 'new', 'air', 'r_ur', 'r_sc', 'r_st', 'r_sebc', 'r_ews')
SECTIONS = [  # (title match, short, list_name, quota)
    ('DIRECT CANDIDATES', 'direct', 'PG Medical Round 2 Revised Merit List - Direct Candidates (MD/MS/Post-MBBS Diploma)', ''),
    ('INSERVICE CANDIDATES', 'inservice', 'PG Medical Round 2 Revised Merit List - In-service Candidates (MD/MS/DNB/Post-MBBS Diploma)', 'In-service'),
    ('LIST- DNB', 'dnb', 'PG Medical Round 2 Revised Merit List - DNB', ''),
    ('POST MBBS-NBEMS DIPLOMA', 'diploma', 'PG Medical Round 2 Revised Merit List - Post-MBBS NBEMS Diploma', ''),
]
STOP = 'REJECTED'


def parse(path):
    d = fitz.open(path)
    pages, cur, other = collections.defaultdict(list), None, {}
    for pn, p in enumerate(d):
        ws = p.get_text('words')
        if not ws:
            other[pn + 1] = '(scanned cover notice)'; continue
        t = page_title(ws)
        if t:
            sec = next((s for s in SECTIONS if s[0] in t), None)
            cur = sec[1] if sec else None
            if not sec:
                other[pn + 1] = t[:80]
        if cur:
            pages[cur].append(pn)
    out = {}
    for _, short, _, _ in SECTIONS:
        pns, cols = pages[short], None
        for pn in pns:
            ws = d[pn].get_text('words')
            ry = min(w[1] for w in ws if ROLL_RE.match(w[4]))
            g = grid(d[pn], ry)
            if len(g) == len(FIELDS_R2) + 1:
                cols = g; break
        assert cols, short
        bounds = list(zip(FIELDS_R2, cols, cols[1:]))
        recs, text_rolls = [], 0
        for pn in pns:
            ws = d[pn].get_text('words')
            text_rolls += sum(1 for w in ws if ROLL_RE.match(w[4]))
            anchors = sorted([w for w in ws if ROLL_RE.match(w[4])], key=lambda w: w[1])
            for i, a in enumerate(anchors):
                y0 = (anchors[i - 1][1] + a[1]) / 2 if i else a[1] - 6
                y1 = (anchors[i + 1][1] + a[1]) / 2 if i + 1 < len(anchors) else a[1] + 9
                line = [w for w in ws if abs(w[1] - a[1]) < 2]
                band = [w for w in ws if y0 <= w[1] < y1]
                rec = {'_page': pn}
                for name, x0, x1 in bounds:
                    if name not in KEEP:
                        continue
                    src = band if name in ('cat', 'type') else line
                    rec[name] = ' '.join(w[4] for w in sorted([w for w in src if x0 - 1 <= w[0] < x1 - 1],
                                                               key=lambda w: (round(w[1]), w[0])))
                recs.append(rec)
        out[short] = {'pages': [p + 1 for p in pns], 'recs': recs, 'text_rolls': text_rolls}
    return d.page_count, out, other


def main():
    pc, secs, other = parse(PDF)
    for _, short, list_name, quota in SECTIONS:
        s = secs[short]
        rows, raw, unparsed = [], [], []
        for r in s['recs']:
            cat = category(r['cat'])
            if not (ROLL_RE.match(r['roll']) and num(r['r_ur']) is not None and num(r['new']) is not None and cat):
                unparsed.append({'page': r['_page'] + 1, 'have_rank': num(r['r_ur']) is not None,
                                 'have_score': num(r['new']) is not None, 'cat_ok': bool(cat)})
                continue
            rows.append({'roll': r['roll'], 'air': num(r['air']), 'state_rank': num(r['r_ur']), 'score': num(r['new']),
                         'category': cat, 'quota': quota})
            raw.append(r)
        wt_bad = [x['roll'] for x, r in zip(rows, raw)
                  if num(r['neet']) is None or abs(num(r['neet']) * (1 + (num(r['wt']) or 0) / 100) - x['score']) > 0.011]
        srt = sorted(rows, key=lambda r: r['state_rank'])
        checks = {
            'pages': s['pages'], 'rows': len(rows), 'rolls_in_pdf_text': s['text_rolls'], 'unparsed': len(unparsed),
            'unparsed_rows': unparsed[:20],
            'state_rank_source': "printed 'Rank-CMR' column = the common merit rank given to every candidate in this list",
            'state_rank_contiguity': contig([r['state_rank'] for r in rows]),
            'duplicate_rolls': [k for k, v in collections.Counter(r['roll'] for r in rows).items() if v > 1],
            'air_blank': sum(1 for r in rows if not r['air']),
            'weightage_arithmetic_mismatches': len(wt_bad),
            'merit_order_breaks_score_vs_rank': sum(1 for a, b in zip(srt, srt[1:]) if b['score'] > a['score']),
            'categories': dict(collections.Counter(r['category'] for r in rows)),
            'category_rank_contiguity': {k: contig([num(r[f]) for r in raw])
                                         for k, f in (('SC', 'r_sc'), ('ST', 'r_st'), ('SEBC', 'r_sebc'), ('EWS', 'r_ews'))},
            'type_dir_ins': dict(collections.Counter((re.findall(r'\b(DIR|INS)\b', r['type']) or ['?'])[-1] for r in raw)),
        }
        path = os.path.join(OUT, f'ojee_r2_{short}.json')
        json.dump({'authority_code': 'ojee', 'list_name': list_name, 'published_on': '2026-11-23',
                   'source_file_name': os.path.basename(PDF), 'rows': rows, 'checks': checks}, open(path, 'w'), indent=1)
        print(path); print(json.dumps(checks, indent=1))
    print('other pages (skipped):', other)


if __name__ == '__main__':
    main()
