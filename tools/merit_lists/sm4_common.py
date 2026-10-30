import re, json, collections, fitz
ROLL = re.compile(r'2666\d{7}')
NB_PATH = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/neet_result/neet2026.json'
OUT = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/merit/'

def nbems():
    d = json.load(open(NB_PATH))
    return {str(r['roll']): r for r in d}

def rows_by_anchor(page, anchor_x, cols, tol=6, top_pad=3):
    """Group words into rows anchored on integer tokens near anchor_x (S.No column).
    cols: list of (name, x0, x1); returns list of dict name->joined text (words whose x0 in [x0,x1))."""
    words = page.get_text('words')
    anchors = sorted([w for w in words if abs(w[0] - anchor_x) <= tol and re.fullmatch(r'\d+', w[4])], key=lambda w: w[1])
    out = []
    for i, a in enumerate(anchors):
        y0 = a[1] - top_pad
        y1 = anchors[i + 1][1] - top_pad if i + 1 < len(anchors) else 1e9
        band = [w for w in words if y0 <= w[1] < y1]
        if i + 1 == len(anchors):
            # last row on page: limit to ~3 lines after anchor
            band = [w for w in band if w[1] < a[1] + 30]
        rec = {}
        for name, x0, x1 in cols:
            ws = sorted([w for w in band if x0 <= w[0] < x1], key=lambda w: (round(w[1]), w[0]))
            rec[name] = ' '.join(w[4] for w in ws)
        rec['_y'] = a[1]
        out.append(rec)
    return out

def contiguity(nums):
    nums = [n for n in nums if n is not None]
    c = collections.Counter(nums)
    dups = sorted([k for k, v in c.items() if v > 1])
    s = set(nums)
    gaps = sorted(set(range(1, max(s) + 1)) - s) if s else []
    return {'n': len(nums), 'min': min(s) if s else None, 'max': max(s) if s else None,
            'duplicates': dups[:50], 'n_duplicates': len(dups), 'gaps': gaps[:50], 'n_gaps': len(gaps)}

def air_check(rows, nb, printed=True):
    found = notfound = match = mism = 0
    mism_ex, nf_ex = [], []
    for r in rows:
        n = nb.get(r['roll'])
        if not n:
            notfound += 1; nf_ex.append(r['roll']); continue
        found += 1
        if printed and r.get('air') is not None:
            if int(n['air']) == r['air']: match += 1
            else:
                mism += 1; mism_ex.append({'roll': r['roll'], 'printed': r['air'], 'nbems': n['air']})
    return {'rolls_found_in_nbems': found, 'rolls_not_found': notfound, 'not_found_rolls': nf_ex[:30],
            'air_match': match, 'air_mismatch': mism, 'mismatch_examples': mism_ex[:30]}

def score_check(rows, nb, field='neet_score'):
    m = mm = 0; ex = []
    for r in rows:
        n = nb.get(r['roll']); v = r.get(field)
        if n is None or v is None: continue
        if float(n['score']) == float(v): m += 1
        else:
            mm += 1; ex.append({'roll': r['roll'], 'printed': v, 'nbems': n['score']})
    return {'neet_score_match': m, 'neet_score_mismatch': mm, 'examples': ex[:20]}

def write(fname, obj):
    with open(OUT + fname, 'w') as f:
        json.dump(obj, f, indent=1)

def vwords(pg):
    m = pg.rotation_matrix
    out = []
    for w in pg.get_text('words'):
        r = fitz.Rect(w[:4]) * m
        out.append((r.x0, r.y0, r.x1, r.y1, w[4]))
    return out

def rows_v(words, anchor_x0, anchor_x1, cols, top_pad=3, last_h=30, ymin=0, max_h=1e9):
    """rotation-aware variant: words already visual. anchors = integer tokens with x0 in [anchor_x0, anchor_x1)."""
    anchors = sorted([w for w in words if anchor_x0 <= w[0] < anchor_x1 and w[1] >= ymin and re.fullmatch(r'\d+', w[4])], key=lambda w: w[1])
    out = []
    for i, a in enumerate(anchors):
        y0 = a[1] - top_pad
        y1 = anchors[i + 1][1] - top_pad if i + 1 < len(anchors) else a[1] + last_h
        y1 = min(y1, a[1] + max_h)
        band = [w for w in words if y0 <= w[1] < y1]
        rec = {}
        for name, x0, x1 in cols:
            ws = sorted([w for w in band if x0 <= w[0] < x1], key=lambda w: (round(w[1]), w[0]))
            rec[name] = ' '.join(w[4] for w in ws)
        rec['_y'] = a[1]
        out.append(rec)
    return out

def dedupe(words, tol=1.5):
    out = []
    seen = {}
    for w in words:
        k = (w[4], round(w[0] / tol), round(w[1] / tol))
        if k in seen: continue
        seen[k] = 1; out.append(w)
    return out
