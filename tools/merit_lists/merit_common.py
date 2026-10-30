"""Shared helpers for the state-merit readers. Outputs ONLY roll/air/state_rank/score/category/quota.
No names, parent names, DOB, gender or application IDs are ever kept or printed."""
import json, os, re, collections
import fitz

NBEMS_PATH = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/neet_result/neet2026.json'
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
ROLL_RE = re.compile(r'^2666\d{7}$')
_nb = None


def nbems():
    global _nb
    if _nb is None:
        _nb = {r['roll']: r for r in json.load(open(NBEMS_PATH))}
    return _nb


def cell(c):
    return ' '.join((c or '').split())


def num(s):
    s = cell(s)
    if s in ('', '-', 'NA', 'N/A'):
        return None
    try:
        v = float(s)
        return int(v) if v.is_integer() else v
    except ValueError:
        return None


def table_rows(path):
    """Yield (page_no, row_cells) for every table row of every page, plus per-page roll counts from raw text."""
    d = fitz.open(path)
    text_rolls = {}
    out = []
    for pn, p in enumerate(d):
        text_rolls[pn] = len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        for t in p.find_tables().tables:
            for r in t.extract():
                out.append((pn, [cell(c) for c in r]))
    return d.page_count, out, text_rolls


def check_rows(rows, snos, page_count, text_rolls_total, extra=None, score_is_neet=False, neet_scores=None):
    """rows: output rows; snos: printed serial numbers (parallel). neet_scores: printed NEET score per row (or None)."""
    nb = nbems()
    n = len(rows)
    sno_ok = snos == list(range(1, n + 1))
    dup_sno = [k for k, v in collections.Counter(snos).items() if v > 1]
    gaps = sorted(set(range(1, max(snos) + 1)) - set(snos)) if snos else []
    sr = [r['state_rank'] for r in rows]
    dup_sr = [k for k, v in collections.Counter(sr).items() if v > 1]
    rolls = [r['roll'] for r in rows]
    dup_roll = [k for k, v in collections.Counter(rolls).items() if v > 1]
    bad_roll = [x for x in rolls if not ROLL_RE.match(x or '')]
    air_match = air_mis = missing = air_blank = 0
    mism = []
    sc_match = sc_mis = 0
    sc_mism = []
    for i, r in enumerate(rows):
        ref = nb.get(r['roll'])
        if ref is None:
            missing += 1
            mism.append({'roll': r['roll'], 'issue': 'roll not in NBEMS'})
            continue
        if r['air'] is None:
            air_blank += 1
        elif r['air'] == ref['air']:
            air_match += 1
        else:
            air_mis += 1
            mism.append({'roll': r['roll'], 'printed_air': r['air'], 'nbems_air': ref['air']})
        ns = neet_scores[i] if neet_scores else None
        if ns is not None:
            if ns == ref['score']:
                sc_match += 1
            else:
                sc_mis += 1
                sc_mism.append({'roll': r['roll'], 'printed_neet_score': ns, 'nbems_score': ref['score']})
    # merit-order sanity: score non-increasing along state_rank
    order = sorted(rows, key=lambda r: r['state_rank'])
    inv = sum(1 for a, b in zip(order, order[1:]) if a['score'] is not None and b['score'] is not None and b['score'] > a['score'])
    c = {
        'page_count': page_count, 'row_count': n, 'rolls_in_pdf_text': text_rolls_total,
        'sno_contiguous_1_to_n': sno_ok, 'sno_duplicates': dup_sno[:20], 'sno_gaps': gaps[:20],
        'state_rank_unique': not dup_sr, 'state_rank_duplicates': dup_sr[:20],
        'state_rank_min': min(sr) if sr else None, 'state_rank_max': max(sr) if sr else None,
        'duplicate_rolls': dup_roll[:20], 'malformed_rolls': bad_roll[:20],
        'air_match_nbems': air_match, 'air_mismatch_nbems': air_mis, 'air_blank_in_list': air_blank,
        'roll_missing_in_nbems': missing, 'air_mismatches': mism[:50],
        'neet_score_match_nbems': sc_match, 'neet_score_mismatch_nbems': sc_mis, 'neet_score_mismatches': sc_mism[:50],
        'score_order_inversions_by_state_rank': inv,
        'categories': dict(collections.Counter(r['category'] for r in rows).most_common()),
        'quotas': dict(collections.Counter(r['quota'] for r in rows).most_common()),
    }
    if extra:
        c.update(extra)
    return c


def write(authority, short, list_name, published_on, source_file, rows, checks):
    path = os.path.join(OUT_DIR, f'{authority}_{short}.json')
    with open(path, 'w') as f:
        json.dump({'authority_code': authority, 'list_name': list_name, 'published_on': published_on,
                   'source_file_name': source_file, 'rows': rows, 'checks': checks}, f, indent=1)
    s = {k: v for k, v in checks.items() if k not in ('air_mismatches', 'neet_score_mismatches')}
    print(path)
    print(json.dumps(s, indent=1))
    if checks['air_mismatches']:
        print('AIR issues (first 10):', checks['air_mismatches'][:10])
    if checks['neet_score_mismatches']:
        print('NEET score issues (first 10):', checks['neet_score_mismatches'][:10])
    return path
