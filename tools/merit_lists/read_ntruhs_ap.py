"""Andhra Pradesh Dr NTRUHS PG Medical (Convener / Competent Authority Quota) provisional merit lists -> rank-bridge rows.

Usage: read_ntruhs_ap.py <pdf> [--out DIR]
  Detects the list from the page-1 title:
   - 'MERIT LIST OF NON-SERVICE CANDIDATES' -> ntruhs_cq_nonservice_provisional.json (quota '')
   - 'MERIT LIST OF IN-SERVICE CANDIDATES'  -> ntruhs_cq_inservice_provisional.json (quota 'In-service')

Columns printed: Sl.No, RegistrationID, NEET Roll No, NEET Rank, NEET Score, Name, Gender, Category, Area,
Muslim Minority, PwBD. Read ONLY: Sl.No, roll, rank, score, category, area, minority, PwBD. Registration ID,
Name and Gender are never kept or printed (Gender is only used as the left edge of the Category column).
Rows are grouped by roll-number anchors (band = midpoint to the neighbouring roll).
"""
import sys, os, re, json, collections
import fitz
from sm4_common import nbems, contiguity, air_check, score_check

DEFAULT_OUT = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/nov1/ml1/'
ROLL = re.compile(r'^2666\d{7}$')
INT = re.compile(r'^\d+$')
CATS = {'OC', 'BC-A', 'BC-B', 'BC-C', 'BC-D', 'BC-E', 'SC G-I', 'SC G-II', 'SC G-III', 'SC', 'ST', 'EWS'}
AREAS = {'AU', 'SVU', 'APNL', 'OU', 'NL'}
YN = {'Yes', 'No'}


def main():
    path = sys.argv[1]
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else DEFAULT_OUT
    d = fitz.open(path)
    title = ' '.join(d[0].get_text().split()).upper()
    if 'MERIT LIST OF IN-SERVICE CANDIDATES' in title:
        kind = 'inservice'
    elif 'MERIT LIST OF NON-SERVICE CANDIDATES' in title:
        kind = 'nonservice'
    else:
        sys.exit('unknown list title')
    nb = nbems()
    recs, unparsed = [], []
    text_rolls = 0
    sl_tokens = 0
    for pn, p in enumerate(d):
        ws = p.get_text('words')
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        hdr = {w[4]: w for w in ws if w[4] in ('Sl.No', 'Category', 'Area', 'Gender', 'PwBD')}
        anchors = sorted([w for w in ws if ROLL.match(w[4])], key=lambda w: w[1])
        if not anchors:
            continue
        if not all(k in hdr for k in ('Sl.No', 'Category', 'Area', 'Gender')):
            unparsed.append({'page': pn + 1, 'issue': 'header not found'}); continue
        cat_x = hdr['Category'][0] - 6
        sl_x1 = anchors[0][0] - 60  # Sl.No sits well left of the RegistrationID / roll
        sl_tokens += sum(1 for w in ws if w[0] < hdr['Sl.No'][2] + 15 and INT.match(w[4]) and w[1] > hdr['Sl.No'][1])
        used = set()
        for i, a in enumerate(anchors):
            y0 = (anchors[i - 1][1] + a[1]) / 2 if i else a[1] - 8
            y1 = (anchors[i + 1][1] + a[1]) / 2 if i + 1 < len(anchors) else a[1] + 8
            band = sorted([w for w in ws if y0 <= w[1] < y1], key=lambda w: (w[0], w[1]))
            used.update(id(w) for w in band)
            left = [w for w in band if w[0] < a[0] and INT.match(w[4]) and w[0] < hdr['Sl.No'][2] + 15]
            nums = [w for w in band if a[0] < w[0] < a[0] + 130 and INT.match(w[4]) and w is not a]
            right = [w for w in band if w[0] >= cat_x]
            right.sort(key=lambda w: (w[0], w[1]))
            issue = None
            if len(left) != 1:
                issue = f'sl tokens={len(left)}'
            elif len(nums) != 2:
                issue = f'rank/score tokens={len(nums)}'
            # right side: category tokens..., area, minority, pwbd
            toks = [w[4] for w in right]
            if not issue:
                if len(toks) < 4 or toks[-1] not in YN or toks[-2] not in YN or toks[-3] not in AREAS:
                    issue = 'right columns shape: ' + ' '.join('Y/N' if t in YN else (t if (t in AREAS or t in CATS or re.fullmatch(r'[A-Z]{2}(-[A-E])?|G-I+', t)) else '?') for t in toks)
                else:
                    cat = ' '.join(toks[:-3])
                    if cat not in CATS:
                        issue = 'unknown category ' + re.sub(r'[a-z]', 'a', cat)[:12]
            if issue:
                unparsed.append({'page': pn + 1, 'roll': a[4], 'issue': issue}); continue
            recs.append({'sl': int(left[0][4]), 'roll': a[4], 'rank': int(nums[0][4]), 'score': int(nums[1][4]),
                         'category': cat, 'area': toks[-3], 'minority': toks[-2], 'pwbd': toks[-1], 'page': pn + 1})
        top, bot = anchors[0][1] - 8, anchors[-1][1] + 8
        for w in ws:
            if top <= w[1] < bot and id(w) not in used:
                unparsed.append({'page': pn + 1, 'issue': 'stray word in data region', 'x': round(w[0]), 'y': round(w[1])})

    quota = 'In-service' if kind == 'inservice' else ''
    rows = [{'roll': r['roll'], 'air': r['rank'], 'state_rank': r['sl'], 'score': r['score'], 'category': r['category'], 'quota': quota}
            for r in recs]
    neet = [{'roll': r['roll'], 'neet_score': r['score']} for r in rows]
    sls = [r['state_rank'] for r in rows]
    ac = air_check(rows, nb)
    roll_dup = [k for k, v in collections.Counter(r['roll'] for r in rows).items() if v > 1]
    checks = {
        'page_count': d.page_count, 'rows_read': len(rows), 'rolls_in_pdf_text': text_rolls, 'sl_no_tokens_in_column': sl_tokens,
        'unparsed': len(unparsed), 'unparsed_examples': unparsed[:20],
        'state_rank_source': "printed 'Sl.No' (the list is printed in merit order; no separate merit/rank column)",
        'state_rank_contiguity': contiguity(sls),
        'state_rank_in_print_order_consecutive': all(b == a + 1 for a, b in zip(sls, sls[1:])),
        'merit_order_breaks_score': sum(1 for a, b in zip(rows, rows[1:]) if b['score'] > a['score']),
        'merit_order_breaks_air': sum(1 for a, b in zip(rows, rows[1:]) if b['air'] < a['air']),
        'duplicate_rolls': roll_dup[:20],
        'air': dict(ac, source="printed 'NEET Rank' column"),
        'neet_score_vs_nbems': score_check(neet, nb),
        'score_definition': "'NEET Score' as printed (no weightage column)",
        'categories': dict(collections.Counter(r['category'] for r in rows).most_common()),
        'category_note': "printed 'Category' as is (OC, BC-A..BC-E, SC G-I/G-II/G-III, ST)",
        'area': dict(collections.Counter(r['area'] for r in recs).most_common()),
        'area_note': 'local area (AU / SVU / APNL) is not stored in the row format; counts only',
        'muslim_minority_yes': sum(1 for r in recs if r['minority'] == 'Yes'),
        'pwbd_yes': sum(1 for r in recs if r['pwbd'] == 'Yes'),
        'published_on_note': 'no list date printed; grievance deadline 01:00 PM 03.11.2026; PDF created ' + (d.metadata.get('creationDate') or '')[2:10],
    }
    short = 'cq_inservice_provisional' if kind == 'inservice' else 'cq_nonservice_provisional'
    name = 'PG Medical CQ Provisional Merit List — In-service' if kind == 'inservice' else 'PG Medical CQ Provisional Merit List — Non-service'
    obj = {'authority_code': 'ntruhs', 'list_name': name, 'published_on': '',
           'source_file_name': os.path.basename(path), 'rows': rows, 'checks': checks}
    fp = os.path.join(out, f'ntruhs_{short}.json')
    with open(fp, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    print(fp)
    print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
