"""Chhattisgarh DME NEET PG (MD/MS) Round 1 Provisional Merit List. Usage: read_dme_cg.py <pdf>
The list prints no names. Kept: roll, NEET AIR, CG State Rank, Total Marks (NEET + bonus), category. Output dir: $MERIT_OUT."""
import sys, os, re, collections
import fitz
from merit_common import nbems, write

path = sys.argv[1]
COLS = [('sno', 10, 45), ('roll', 45, 100), ('air', 100, 135), ('neet', 135, 155), ('bpct', 155, 185), ('bmarks', 185, 230),
        ('total', 230, 300), ('cand', 300, 445), ('nat', 445, 488), ('cat', 488, 520), ('sr', 520, 560), ('catrank', 560, 600),
        ('cls', 600, 645), ('course', 645, 700), ('quota', 700, 800)]
ROLL_RE = re.compile(r'^2666\d{7}$')


def n(s):
    s = s.strip()
    try:
        v = float(s)
        return int(v) if v.is_integer() else v
    except ValueError:
        return None


d = fitz.open(path)
recs, text_rolls = [], 0
for pn, pg in enumerate(d):
    ws = pg.get_text('words')
    text_rolls += sum(1 for w in ws if ROLL_RE.match(w[4]))
    anchors = sorted([w for w in ws if 10 <= w[0] < 45 and re.fullmatch(r'\d+', w[4])
                      and any(ROLL_RE.match(v[4]) and abs(v[1] - w[1]) < 2 for v in ws)], key=lambda w: w[1])
    for i, a in enumerate(anchors):
        # one-line numeric fields sit on the anchor's baseline; wrapped text cells straddle it, so take the anchor line only
        line = [w for w in ws if abs(w[1] - a[1]) < 2]
        rec = {'_page': pn}
        for name, x0, x1 in COLS:
            rec[name] = ' '.join(w[4] for w in sorted(line, key=lambda w: w[0]) if x0 <= w[0] < x1)
        # quota / course / candidature text wraps: collect the band between the previous and next anchor midpoints
        y0 = (anchors[i - 1][1] + a[1]) / 2 if i else a[1] - 8
        y1 = (anchors[i + 1][1] + a[1]) / 2 if i + 1 < len(anchors) else a[1] + 14
        band = [w for w in ws if y0 <= w[1] < y1]
        for name in ('cand', 'course', 'quota'):
            x0, x1 = [(c[1], c[2]) for c in COLS if c[0] == name][0]
            rec[name] = ' '.join(w[4] for w in sorted([w for w in band if x0 <= w[0] < x1], key=lambda w: (round(w[1]), w[0])))
        recs.append(rec)

nb = nbems()
rows, unparsed = [], []
for r in recs:
    ok = ROLL_RE.match(r['roll']) and n(r['sno']) and n(r['air']) is not None and n(r['total']) is not None and n(r['sr']) is not None
    if not ok:
        unparsed.append({'page': r['_page'], 'sno': r['sno']}); continue
    rows.append({'roll': r['roll'], 'air': n(r['air']), 'state_rank': n(r['sr']), 'score': n(r['total']),
                 'category': r['cat'], 'quota': ''})


def contig(v):
    c = collections.Counter(v); s = set(v)
    return {'n': len(v), 'min': min(s), 'max': max(s), 'duplicates': sorted(k for k, x in c.items() if x > 1)[:20],
            'gaps': sorted(set(range(1, max(s) + 1)) - s)[:20]}


air_m = air_mm = nf = 0; mism = []
sc_m = sc_mm = 0; sc_mism = []
for r, rec in zip(rows, [x for x in recs if ROLL_RE.match(x['roll'])]):
    ref = nb.get(r['roll'])
    if not ref:
        nf += 1; mism.append({'roll': r['roll'], 'issue': 'not in NBEMS'}); continue
    if r['air'] == ref['air']: air_m += 1
    else: air_mm += 1; mism.append({'roll': r['roll'], 'printed_air': r['air'], 'nbems_air': ref['air']})
    if n(rec['neet']) == ref['score']: sc_m += 1
    else: sc_mm += 1; sc_mism.append({'roll': r['roll'], 'printed': rec['neet'], 'nbems': ref['score']})

good = [x for x in recs if ROLL_RE.match(x['roll'])]
bonus_bad = [x['roll'] for x in good if abs(n(x['neet']) + n(x['bmarks']) - n(x['total'])) > 0.051
             or abs(n(x['neet']) * n(x['bpct']) / 100 - n(x['bmarks'])) > 0.051]
srt = sorted(rows, key=lambda r: r['state_rank'])
inv = sum(1 for a, b in zip(srt, srt[1:]) if b['score'] > a['score'])
# category rank contiguity per category
cr = collections.defaultdict(list)
for x in good:
    m = re.fullmatch(r'(\S+) (\d+)', x['catrank'])
    if m: cr[m.group(1)].append(int(m.group(2)))
checks = {
    'page_count': d.page_count, 'rows': len(rows), 'rolls_in_pdf_text': text_rolls, 'unparsed': len(unparsed), 'unparsed_rows': unparsed[:20],
    'state_rank_source': "printed 'CG State Rank' column",
    'sno_contiguity': contig([n(x['sno']) for x in good]),
    'state_rank_contiguity': contig([r['state_rank'] for r in rows]),
    'state_rank_equals_sno': sum(1 for x in good if x['sr'] == x['sno']),
    'duplicate_rolls': [k for k, v in collections.Counter(r['roll'] for r in rows).items() if v > 1],
    'air': {'source': 'printed NEET Overall RANK', 'match_nbems': air_m, 'mismatch_nbems': air_mm, 'roll_not_in_nbems': nf, 'issues': mism[:30]},
    'neet_score_vs_nbems': {'match': sc_m, 'mismatch': sc_mm, 'examples': sc_mism[:20]},
    'score_definition': 'Total Marks = NEET PG score + bonus marks (in-service bonus %, of the NEET score)',
    'bonus_arithmetic_mismatches': bonus_bad[:20],
    'bonus_pct_counts': dict(collections.Counter(x['bpct'] for x in good)),
    'merit_order_breaks_total_vs_state_rank': inv,
    'categories': dict(collections.Counter(r['category'] for r in rows)),
    'category_rank_by_category': {k: contig(v) for k, v in cr.items()},
    'candidature_types': dict(collections.Counter(x['cand'] for x in good)),
    'nationality': dict(collections.Counter(x['nat'] for x in good)),
    'applied_course_quota': dict(collections.Counter(' '.join((x['course'] + ' ' + x['quota']).split()) for x in good)),
    'class_rows': sum(1 for x in good if x['cls']),
    'quota_note': "single combined merit list; quota left blank. 'Applied Quota' (Govt / Govt & Private / Private) is the candidate's application choice, counted above. Note on last page: no NRI-quota candidates eligible for Round 1.",
    'published_on_note': 'no date printed; PDF created 2026-10-30 23:49 IST',
}
write('dme_cg', 'r1_provisional', 'Round 1 Provisional Merit List', '2026-10-30', os.path.basename(path), rows,
      dict(checks, air_mismatches=mism[:50], neet_score_mismatches=sc_mism[:50]))
