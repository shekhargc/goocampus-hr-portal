"""Maharashtra CET Cell NEET-PG state merit lists -> rank-bridge rows.

Usage: read_cetcell_mh.py <pdf> [--out DIR]
  Detects the list from the page-1 title:
   - 'Common Provisional State Merit List'            -> cetcell_mh_common_provisional.json (quota '')
   - 'Provisional State Merit List of In-Service ...'  -> cetcell_mh_inservice_provisional.json (quota 'In-service')
  The 'Final Provisional State Merit List …' issues (02.11.2026) read the same way and keep the same list_name, so
  loading them replaces the earlier provisional list (the ingest's 'start' clears that list_name).

Reads ONLY: SML (merit no.), NEET PG rank, NEET PG score, roll no., category merit cell, NRI cell, candidature type,
remark and the @/$/d markers. The App. No. and Name columns are never read or printed (x-ranges skipped).
Rows are grouped by roll-number anchors (band = midpoint to the neighbouring roll).
"""
import sys, os, re, json, collections
import fitz
from sm4_common import nbems, contiguity, air_check, score_check

DEFAULT_OUT = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/nov1/ml1/'
ROLL = re.compile(r'^2666\d{7}$')
# x-ranges (pt) per layout; 'skip' ranges are App. No. + Name (never read)
LAYOUTS = {
    'common': dict(sml=(0, 48), rank=(48, 100), score=(100, 145), roll=(145, 200), cat=(200, 300), nri=(300, 335),
                   skip=(335, 495), ctype=(495, 543), remark=(543, 600)),
    'inservice': dict(sml=(0, 52), mark=(52, 75), rank=(75, 140), score=(140, 198), roll=(198, 265), cat=(265, 345),
                      skip=(345, 530), remark=(530, 600)),
}
TAG = re.compile(r'^(OBC|SC|ST|SEBC|EWS|NT\([A-D]\)|DT-VJ\(A\)|VJ|SBC|Muslim|PWD|Orphan|NRI)-(\d+)$')
CATS = {'OPEN', 'OBC', 'SC', 'ST', 'SEBC', 'EWS', 'NT(B)', 'NT(C)', 'NT(D)', 'DT-VJ(A)', 'VJ', 'SBC'}
EXTRA_TAGS = {'Muslim', 'PWD', 'Orphan'}


def cell(band, rng):
    x0, x1 = rng
    return ' '.join(w[4] for w in sorted([w for w in band if x0 <= w[0] < x1], key=lambda w: (round(w[1]), w[0])))


def num(s):
    s = s.strip()
    if not s:
        return None
    try:
        v = float(s)
        return int(v) if v.is_integer() else v
    except ValueError:
        return None


def main():
    path = sys.argv[1]
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else DEFAULT_OUT
    d = fitz.open(path)
    title = ' '.join(d[0].get_text().split()[:60])
    kind = 'inservice' if 'In-Service Candidates' in title else 'common'
    L = LAYOUTS[kind]
    m = re.search(r'Dated\s+(\d{2})/(\d{2})/(\d{4})', title)
    published = f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else ''
    nb = nbems()

    recs, unparsed, no_sml = [], [], []
    text_rolls = 0
    for pn, p in enumerate(d):
        ws = p.get_text('words')
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        anchors = sorted([w for w in ws if ROLL.match(w[4]) and L['roll'][0] <= w[0] < L['roll'][1]], key=lambda w: w[1])
        if not anchors:
            continue
        used = set()
        for i, a in enumerate(anchors):
            y0 = (anchors[i - 1][1] + a[1]) / 2 if i else a[1] - 8
            y1 = (anchors[i + 1][1] + a[1]) / 2 if i + 1 < len(anchors) else a[1] + 8
            band = [w for w in ws if y0 <= w[1] < y1]
            used.update(id(w) for w in band)
            r = {k: cell(band, v) for k, v in L.items() if k != 'skip'}
            r['roll'] = a[4]
            r['_page'] = pn + 1
            # roll cell may also hold the start of a wide category-merit cell (e.g. 'OBC-1234' starts at x~215)
            r['cat'] = cell([w for w in band if w is not a], (L['roll'][0], L['cat'][1])) if kind == 'common' else r['cat']
            smls = re.findall(r'\d+', r['sml'])
            r['marks'] = ''.join(t for t in r['sml'].split() if not t.isdigit()) + r.get('mark', '')
            if kind == 'inservice':
                r['marks'] = r['mark']
                r['aghoshit'] = '¥' in r['rank']
                r['rank'] = r['rank'].replace('¥', '').strip()
            if len(smls) != 1:
                (no_sml if not smls else unparsed).append({'page': pn + 1, 'roll': r['roll'], 'issue': f'sml tokens={len(smls)}'})
                r['sml_n'] = None
            else:
                r['sml_n'] = int(smls[0])
            if num(r['rank']) is None or num(r['score']) is None:
                unparsed.append({'page': pn + 1, 'roll': r['roll'], 'issue': 'rank/score not numeric'})
            recs.append(r)
        # words in the data region that fell outside every row band
        top = anchors[0][1] - 8
        bot = anchors[-1][1] + 8
        stray = [w for w in ws if top <= w[1] < bot and id(w) not in used]
        for w in stray:
            unparsed.append({'page': pn + 1, 'issue': 'stray word in data region', 'x': round(w[0]), 'y': round(w[1])})

    # ---- category
    tagnums = collections.defaultdict(list)
    extra_tags = collections.Counter()
    converted = 0
    unknown_cat = []
    rows, neet = [], []
    printed_vs = []
    for r in recs:
        toks = r['cat'].split()
        main, conv = None, False
        for t in toks:
            if t == '(converted)':
                conv = True; continue
            mt = TAG.match(t)
            if kind == 'inservice' and t in CATS:
                main = main or t; continue
            if not mt:
                unknown_cat.append({'roll': r['roll'], 'cell_shape': re.sub(r'\d', '9', r['cat'])}); continue
            tg, n = mt.group(1), int(mt.group(2))
            if r['sml_n'] is not None:
                tagnums[tg].append(n)
            if tg in EXTRA_TAGS or tg == 'NRI':
                extra_tags[tg] += 1
            else:
                main = main or tg
        if conv:
            converted += 1
            main = 'OPEN'
        r['category'] = main or 'OPEN'
        for t in r.get('nri', '').split():
            mt = TAG.match(t)
            if mt and mt.group(1) == 'NRI':
                extra_tags['NRI'] += 1
                if r['sml_n'] is not None:
                    tagnums['NRI'].append(int(mt.group(2)))
            elif t:
                unknown_cat.append({'roll': r['roll'], 'nri_cell_shape': re.sub(r'\d', '9', t)})
        if r['sml_n'] is None:
            continue
        rk = num(r['rank'])
        printed_rank = int(rk) if rk is not None else None
        if kind == 'inservice':
            # The in-service 'rank' is CET Cell's equivalent rank of the WEIGHTED score (tie-split, e.g. 108331.2),
            # not the NEET AIR - so AIR is filled from NBEMS by roll; the printed rank is only compared in checks.
            ref = nb.get(r['roll'])
            air = int(ref['air']) if ref else None
            printed_vs.append((r['roll'], printed_rank, air, r.get('aghoshit')))
        else:
            air = printed_rank
        rows.append({'roll': r['roll'], 'air': air, 'state_rank': r['sml_n'], 'score': num(r['score']),
                     'category': r['category'], 'quota': 'In-service' if kind == 'inservice' else ''})
        neet.append({'roll': r['roll'], 'neet_score': num(r['score'])})

    kept = [r for r in recs if r['sml_n'] is not None]
    order_breaks_score = sum(1 for a, b in zip(rows, rows[1:]) if b['score'] > a['score'])
    sr_seq = [r['state_rank'] for r in rows]
    order_breaks_sml = sum(1 for a, b in zip(sr_seq, sr_seq[1:]) if b != a + 1)
    air_breaks = sum(1 for a, b in zip(rows, rows[1:]) if a['air'] and b['air'] and b['air'] < a['air'])
    ac = air_check(rows, nb, printed=(kind != 'inservice'))
    # printed decimal suffix on the in-service list rank (e.g. 108331.2)
    dec_ranks = [r['rank'] for r in kept if '.' in r['rank']]
    sc = score_check(neet, nb) if kind == 'common' else None
    roll_dup = [k for k, v in collections.Counter(r['roll'] for r in rows).items() if v > 1]
    checks = {
        'page_count': d.page_count, 'rows_read': len(recs), 'rows_kept': len(rows), 'rolls_in_pdf_text': text_rolls,
        'rows_without_merit_no_left_out': len(no_sml),
        'rows_without_merit_no_all_after_last_numbered': all(i > max((j for j, r in enumerate(recs) if r['sml_n'] is not None), default=-1)
                                                             for i, r in enumerate(recs) if r['sml_n'] is None),
        'rows_without_merit_no_remarks_approx': dict(collections.Counter(r['remark'] for r in recs if r['sml_n'] is None)),
        'rows_without_merit_no_note': 'printed with no SML number (Invalid / Not Eligible remarks); left out as they have no state rank' if no_sml else '',
        'unparsed': len(unparsed), 'unparsed_examples': unparsed[:20],
        'state_rank_source': "printed 'SML' (state merit list number) column" if kind == 'common' else "printed 'Prov Inser SML' column (in-service merit no.)",
        'state_rank_contiguity': contiguity(sr_seq),
        'state_rank_in_print_order_consecutive': order_breaks_sml == 0,
        'merit_order_breaks_score': order_breaks_score, 'merit_order_breaks_air': air_breaks,
        'duplicate_rolls': roll_dup[:20],
        'air': dict(ac, source="printed 'NEET PG 2026 Rank' column") if kind == 'common' else dict(ac,
            source='filled from NBEMS by roll: the printed rank column is CET Cell\'s equivalent rank of the weighted (in-service) score, not the AIR',
            filled_from_roll=sum(1 for r in rows if r['air'] is not None),
            printed_rank_eq_nbems_air=sum(1 for _, pr, a, _ag in printed_vs if pr == a),
            printed_rank_eq_nbems_air_aghoshit=sum(1 for _, pr, a, ag in printed_vs if ag and pr == a),
            aghoshit_total=sum(1 for *_x, ag in printed_vs if ag),
            printed_rank_lt_nbems_air=sum(1 for _, pr, a, _ag in printed_vs if pr is not None and a is not None and pr < a),
            printed_rank_gt_nbems_air=sum(1 for _, pr, a, _ag in printed_vs if pr is not None and a is not None and pr > a)),
        'neet_score_vs_nbems': sc if kind == 'common' else {'note': 'score = weighted score; see weighted_score_check'},
        'score_definition': "'NEET PG Score' as printed" if kind == 'common' else "printed 'NEET PG Score' = NEET score x (1 + in-service incentive %); equals the NEET score for Aghoshit (no incentive) rows",
        'categories': dict(collections.Counter(r['category'] for r in rows).most_common()),
        'category_note': ("'Category Merit No.' cell (e.g. 'OBC-123', 'EWS-12 Muslim-5'); category = first vertical tag; blank = OPEN; "
                          "'(converted)' = reserved claim converted to OPEN -> OPEN. Muslim/PWD/Orphan/NRI tags are not kept in category (counted below)")
                         if kind == 'common' else "printed 'Category'; 'OPEN (converted)' -> OPEN",
        'converted_to_open': converted,
        'extra_tag_counts': dict(extra_tags),
        'category_merit_contiguity': {k: {kk: vv for kk, vv in contiguity(v).items() if kk in ('n', 'min', 'max', 'n_duplicates', 'n_gaps', 'gaps')} for k, v in sorted(tagnums.items())},
        'unknown_category_tokens': unknown_cat[:20],
        'inservice_markers': dict(collections.Counter(r['marks'] for r in kept)),
        'marker_legend': ('@ = in-service, eligible for in-service quota; $ = in-service, not eligible; d = eligible for particular degree'
                          if kind == 'common' else '@ = eligible for in-service quota; @d = eligible for particular degree; ¥ (in rank column) = Aghoshit candidate'),
        'remarks_approx': dict(collections.Counter(r['remark'] for r in kept).most_common(25)),
        'remarks_note': 'remark cells wrap over 2-3 lines and can bleed into the neighbouring row band; counts are indicative only',
    }
    if kind == 'common':
        checks['candidature_type'] = dict(collections.Counter(r['ctype'] for r in kept))
    else:
        checks['aghoshit_rows'] = sum(1 for r in kept if r.get('aghoshit'))
        checks['decimal_rank_rows'] = len(dec_ranks)
        pct = collections.Counter()
        arith_bad = []
        for r in rows:
            ref = nb.get(r['roll'])
            if not ref or not ref['score']:
                continue
            p = round((r['score'] / ref['score'] - 1) * 100, 2)
            pct[p] += 1
            if p != int(p) or abs(ref['score'] * (1 + int(p) / 100) - r['score']) > 0.011:
                arith_bad.append({'roll': r['roll'], 'nbems_score': ref['score'], 'printed': r['score']})
        checks['weighted_score_check'] = {'implied_incentive_pct_counts': {str(k): v for k, v in sorted(pct.items())},
                                          'rows_not_equal_nbems_x_whole_pct': len(arith_bad), 'examples': arith_bad[:10]}
    short = 'inservice_provisional' if kind == 'inservice' else 'common_provisional'
    name = 'PGM-CET In-Service Provisional State Merit List' if kind == 'inservice' else 'PGM-CET Common Provisional State Merit List'
    obj = {'authority_code': 'cetcell_mh', 'list_name': name, 'published_on': published,
           'source_file_name': os.path.basename(path), 'rows': rows, 'checks': checks}
    fp = os.path.join(out, f'cetcell_mh_{short}.json')
    with open(fp, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    print(fp)
    print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
