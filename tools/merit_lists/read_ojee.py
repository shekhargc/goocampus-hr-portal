"""Odisha PG Medical (OJEE / PG Medical Counselling Committee) final common merit list after grievances.
Usage: read_ojee.py <revised.pdf> [<earlier.pdf>]   Output dir: $MERIT_OUT.

The PDF holds four separate merit lists (plus a rejected-applications list, skipped); one JSON per list.
Kept: roll, printed NEET AIR, 'Rank-UR' (the common merit rank every candidate gets), 'New Score'
(NEET score + in-service weightage %), category. Names, application numbers and sub-categories are never kept."""
import sys, os, re, collections, json
import fitz
from merit_common import nbems, write

ROLL_RE = re.compile(r'^2666\d{7}$')
SECTIONS = [  # (title match, short, list_name, quota)
    ('DIRECT CANDIDATES', 'direct', 'PG Medical Revised Merit List - Direct Candidates (MD/MS/Post-MBBS Diploma)', ''),
    ('INSERVICE CANDIDATES', 'inservice', 'PG Medical Revised Merit List - In-service Candidates (MD/MS/DNB/Post-MBBS Diploma)', 'In-service'),
    ('LIST- DNB', 'dnb', 'PG Medical Revised Merit List - DNB', ''),
    ('POST MBBS-NBEMS DIPLOMA', 'diploma', 'PG Medical Revised Merit List - Post-MBBS NBEMS Diploma', ''),
]
# column order of every section's table (left edges come from the drawn grid)
FIELDS = ['appln', 'roll', 'name', 'course', 'type', 'cat', 'subcat', 'neet', 'wt', 'new', 'air', 'job', 'r_ur', 'r_ur_gc', 'r_ur_es',
          'r_ur_pwd', 'r_sc', 'r_sc_gc', 'r_sc_es', 'r_sc_pwd', 'r_st', 'r_st_gc', 'r_st_es', 'r_st_pwd', 'r_sebc', 'r_sebc_gc', 'r_sebc_es',
          'r_sebc_pwd', 'r_ews', 'r_ews_pwd']
KEEP = ('roll', 'type', 'cat', 'neet', 'wt', 'new', 'air', 'r_ur', 'r_sc', 'r_st', 'r_sebc', 'r_ews')  # never name/appln/subcat


def page_title(ws):
    for w in ws:
        if w[4] in ('LIST-', 'LIST', 'LIST(REVISED)-'):
            return ' '.join(v[4] for v in sorted([v for v in ws if abs(v[1] - w[1]) < 2], key=lambda v: v[0]))
    return ''


def grid(p, first_roll_y):
    xs = set()
    for dr in p.get_drawings():
        for it in dr['items']:
            if it[0] == 're':
                r = it[1]
                if r.width < 2 and r.height > 4 and r.y0 >= 50 and r.y1 <= first_roll_y + 1:
                    xs.add(round((r.x0 + r.x1) / 2))
    return sorted(xs)


def num(s):
    s = s.strip()
    try:
        v = float(s)
        return int(v) if v.is_integer() else v
    except ValueError:
        return None


def parse(path):
    d = fitz.open(path)
    pages = collections.defaultdict(list)  # short -> [page numbers]
    other = {}
    for pn, p in enumerate(d):
        t = page_title(p.get_text('words'))
        sec = next((s for s in SECTIONS if s[0] in t), None)
        if sec: pages[sec[1]].append(pn)
        elif t: other[pn] = t
    out = {}
    for _, short, _, _ in SECTIONS:
        pns = pages[short]
        cols = None
        for pn in pns:  # the grid is drawn as thin rects on all but the first page of a section; take the first full grid
            ws = d[pn].get_text('words')
            ry = min(w[1] for w in ws if ROLL_RE.match(w[4]))
            g = grid(d[pn], ry)
            if len(g) == len(FIELDS):
                cols = g; break
        assert cols, short
        bounds = list(zip(FIELDS, cols, cols[1:] + [10000]))
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
                    if name not in KEEP: continue
                    src = band if name in ('cat', 'type') else line
                    rec[name] = ' '.join(w[4] for w in sorted([w for w in src if x0 - 1 <= w[0] < x1 - 1], key=lambda w: (round(w[1]), w[0])))
                recs.append(rec)
        out[short] = {'pages': [p + 1 for p in pns], 'recs': recs, 'text_rolls': text_rolls}
    return d.page_count, out, other


def category(t):
    u = t.upper()
    for k, v in (('SEBC', 'SEBC'), ('EWS', 'EWS'), ('(UR)', 'UR'), ('ST,', 'ST'), ('SC,', 'SC')):
        if k in u: return v
    m = re.match(r'^(ST|SC)\b', u)
    return m.group(1) if m else None


def contig(v):
    v = [x for x in v if x is not None]
    if not v: return {'n': 0}
    c = collections.Counter(v); s = set(v)
    return {'n': len(v), 'min': min(s), 'max': max(s), 'duplicates': sorted(k for k, x in c.items() if x > 1)[:20],
            'n_gaps': len(set(range(1, max(s) + 1)) - s), 'gaps': sorted(set(range(1, max(s) + 1)) - s)[:20]}


def build(recs, nb):
    rows, unparsed = [], []
    for r in recs:
        cat = category(r['cat'])
        ok = ROLL_RE.match(r['roll']) and num(r['r_ur']) is not None and num(r['new']) is not None and cat
        if not ok:
            unparsed.append({'page': r['_page'] + 1, 'have_rank': num(r['r_ur']) is not None, 'have_score': num(r['new']) is not None, 'cat_ok': bool(cat)})
            continue
        rows.append(({'roll': r['roll'], 'air': num(r['air']), 'state_rank': num(r['r_ur']), 'score': num(r['new']), 'category': cat, 'quota': ''}, r))
    return rows, unparsed


def main():
    path = sys.argv[1]
    earlier = sys.argv[2] if len(sys.argv) > 2 else None
    nb = nbems()
    pc, secs, other = parse(path)
    old = parse(earlier)[1] if earlier else None
    for _, short, list_name, quota in SECTIONS:
        s = secs[short]
        pairs, unparsed = build(s['recs'], nb)
        rows = [dict(p[0], quota=quota) for p in pairs]
        raw = [p[1] for p in pairs]
        am = amm = nf = 0; mism = []; sm = smm = 0; smism = []; wt_bad = []
        for row, r in zip(rows, raw):
            ref = nb.get(row['roll'])
            if not ref:
                nf += 1; mism.append({'roll': row['roll'], 'issue': 'not in NBEMS'}); continue
            if row['air'] == ref['air']: am += 1
            else: amm += 1; mism.append({'roll': row['roll'], 'printed_air': row['air'], 'nbems_air': ref['air']})
            if num(r['neet']) == ref['score']: sm += 1
            else: smm += 1; smism.append({'roll': row['roll'], 'printed': r['neet'], 'nbems': ref['score']})
            wt = num(r['wt']) or 0
            if abs(num(r['neet']) * (1 + wt / 100) - row['score']) > 0.011: wt_bad.append(row['roll'])
        srt = sorted(rows, key=lambda r: r['state_rank'])
        inv = sum(1 for a, b in zip(srt, srt[1:]) if b['score'] > a['score'])
        # tie handling: equal New Score -> AIR order?
        tie_air_inv = sum(1 for a, b in zip(srt, srt[1:]) if b['score'] == a['score'] and a['air'] and b['air'] and b['air'] < a['air'])
        catr = {}
        for k, f in (('SC', 'r_sc'), ('ST', 'r_st'), ('SEBC', 'r_sebc'), ('EWS', 'r_ews')):
            catr[k] = contig([num(r[f]) for r in raw])
        checks = {
            'pages': s['pages'], 'rows': len(rows), 'rolls_in_pdf_text': s['text_rolls'], 'unparsed': len(unparsed), 'unparsed_rows': unparsed[:20],
            'state_rank_source': "printed 'Rank-UR' column = the common merit rank given to every candidate in this list",
            'state_rank_contiguity': contig([r['state_rank'] for r in rows]),
            'duplicate_rolls': [k for k, v in collections.Counter(r['roll'] for r in rows).items() if v > 1],
            'air': {'source': 'printed NEET AIR', 'match_nbems': am, 'mismatch_nbems': amm, 'roll_not_in_nbems': nf},
            'neet_score_vs_nbems': {'match': sm, 'mismatch': smm, 'examples': smism[:20]},
            'score_definition': "'New Score' = NEET score + weightage % of it (in-service weightage; 0 for direct candidates)",
            'weightage_arithmetic_mismatches': wt_bad[:20],
            'weightage_counts': dict(collections.Counter(r['wt'] for r in raw).most_common(15)),
            'merit_order_breaks_score_vs_rank': inv, 'equal_score_air_order_breaks': tie_air_inv,
            'categories': dict(collections.Counter(r['category'] for r in rows)),
            'category_note': 'category read from the Category cell (General (UR) / SEBC / SC / ST / EWS); sub-category not kept',
            'category_rank_contiguity': catr,
            'type_dir_ins': dict(collections.Counter((re.findall(r'\b(DIR|INS)\b', r['type']) or ['?'])[-1] for r in raw)),
            'published_on_note': 'cover notice No. 63 dated 30 Oct 2026; this revised file was produced 2026-10-30 18:09 UTC (published 31 Oct)',
        }
        if old is not None:
            opairs, _ = build(old[short]['recs'], nb)
            om = {p[0]['roll']: p[0] for p in opairs}
            nm = {r['roll']: r for r in rows}
            diff = collections.Counter()
            ex = []
            for k, r in nm.items():
                o = om.get(k)
                if not o: diff['added'] += 1; ex.append({'roll': k, 'change': 'added', 'rank': r['state_rank']}); continue
                for f in ('state_rank', 'score', 'category', 'air'):
                    if o[f] != r[f]:
                        diff['changed_' + f] += 1
                        if f != 'state_rank': ex.append({'roll': k, 'field': f, 'old': o[f], 'new': r[f]})
            for k in om:
                if k not in nm: diff['removed'] += 1; ex.append({'roll': k, 'change': 'removed', 'old_rank': om[k]['state_rank']})
            checks['compare_30oct'] = {'rows_30oct': len(om), 'rows_31oct': len(nm), 'diffs': dict(diff), 'examples': ex[:40],
                                       'note': 'changed_state_rank = rows whose common rank moved (e.g. shifted by an insertion)'}
        write('ojee', short, list_name, '2026-10-30', os.path.basename(path), rows,
              dict(checks, air_mismatches=mism[:50], neet_score_mismatches=smism[:50]))
    print('other titled pages (skipped):', other)


if __name__ == '__main__':
    main()
