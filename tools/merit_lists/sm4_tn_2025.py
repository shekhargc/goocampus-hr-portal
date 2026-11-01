"""Tamil Nadu PG GQ + MQ provisional rank lists, 2025-26 session (Selection Committee release of 8 Nov 2025;
copies from Medical Dialogues, the official site no longer hosts them) -> rank-bridge rows.
Usage: MERIT_OUT=<dir> sm4_tn_2025.py [<gq.pdf> <mq.pdf>]
Same approach as sm4_tn_build.py (sm4_tn.read), with the 2025 column positions. AIR is not printed: it is filled
from the NBEMS 2025 master result by roll number. Names / app numbers are never written or printed."""
import os, sys, re, collections, json
import fitz
from sm4_common import contiguity, air_check, score_check, dedupe, vwords
from sm4_tn import read, COMM_OK

S = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/'
GQ_PDF, MQ_PDF = (sys.argv[1:3] if len(sys.argv) >= 3 else [S + 'tn2025/dl/md_8-307384.pdf', S + 'tn2025/dl/md_9-307386.pdf'])
NB_PATH = S + 'neet_result/neet2025.json'
OUT = os.path.join(os.environ.get('MERIT_OUT') or S + 'tn2025', '')
ROLL = re.compile(r'2566\d{7}')
# 2025 layout (portrait A4, "Microsoft: Print To PDF"). x ranges of the word's left edge.
GQ_ANCHOR = (12, 48)
GQCOLS = [('rank', 12, 48), ('roll', 112, 180), ('comm', 340, 400), ('svc', 400, 440), ('inc', 440, 480),
          ('total', 480, 525), ('crank', 525, 600)]
MQ_ANCHOR = (15, 65)  # COMMUNITY header at x436; long names run to x435, so the column starts at 438
MQCOLS = [('rank', 15, 65), ('roll', 145, 225), ('comm', 438, 500), ('score', 500, 600)]
HEADER_Y, FOOTER_Y = 66, 790  # column header ends ~y61; "Page n of m" footer at ~y798

toi = lambda s: int(s) if re.fullmatch(r'\d+', s.strip()) else None
tof = lambda s: float(s) if re.fullmatch(r'\d+(\.\d+)?', s.strip()) else None
nb = {str(r['roll']): r for r in json.load(open(NB_PATH))}


def leftovers(fn, anchor):
    """Words in the table area that fall in no row band (same banding as sm4_tn.read). Returns count + pages."""
    d = fitz.open(fn); n = 0; pages = []
    for i, pg in enumerate(d):
        ws = dedupe(vwords(pg))
        hy = min([w[1] for w in ws if w[4] == 'RANK'] or [0])
        an = sorted([w for w in ws if anchor[0] <= w[0] < anchor[1] and w[1] > hy + 10 and re.fullmatch(r'\d+A?', w[4])], key=lambda w: w[1])
        bands = [(a[1] - 6, (an[j + 1][1] - 6) if j + 1 < len(an) else a[1] + 14) for j, a in enumerate(an)]
        lost = [w for w in ws if HEADER_Y < w[1] < FOOTER_Y and not any(y0 <= w[1] < y1 for y0, y1 in bands)]
        if lost: n += len(lost); pages.append(i + 1)
    return {'words_outside_any_row': n, 'pages': pages[:20]}


def field_problems(recs, spec):
    bad = collections.Counter(); ex = []
    for r in recs:
        for k, rx in spec.items():
            if not re.fullmatch(rx, r[k]):
                bad[k] += 1
                if len(ex) < 20: ex.append({'page': r['_page'] + 1, 'rank': r['rank'] if k != 'rank' else '?', 'field': k,
                                            'value': re.sub(r'[A-Za-z]', 'x', r[k]) if k not in ('comm', 'svc') else r[k]})
    return dict(bad), ex


def inrank_order(rows, key):
    return sum(1 for a, b in zip(rows, rows[1:]) if b[key] > a[key])


def dup_rolls(rows):
    c = collections.Counter(r['roll'] for r in rows)
    return [k for k, v in c.items() if v > 1]


# ---------------- GQ
gq = read(GQ_PDF, GQCOLS, anchor=GQ_ANCHOR)
gq_bad, gq_bad_ex = field_problems(gq, {'rank': r'\d+A?', 'roll': ROLL.pattern, 'comm': COMM_OK.pattern, 'svc': r'(YES)?',
                                         'inc': r'(\d+(\.\d+)?)?', 'total': r'\d+\.\d\d', 'crank': r'\d*'})
rows = []
for r in gq:
    n = nb.get(r['roll'])
    rows.append({'roll': r['roll'], 'air': int(n['air']) if n and n.get('air') is not None else None,
                 'state_rank': toi(r['rank'].rstrip('A')), 'score': tof(r['total']), 'category': r['comm'], 'quota': ''})
arith_bad = []; arith_ok = 0; plain_eq = 0
for r in gq:
    n = nb.get(r['roll'])
    if not n or tof(r['total']) is None: continue
    inc = tof(r['inc']) or 0.0
    if abs(float(n['score']) * (1 + inc / 100) - tof(r['total'])) > 0.011:
        arith_bad.append({'rank': r['rank'], 'roll': r['roll'], 'nbems_score': n['score'], 'inc': inc, 'total': r['total']})
    else:
        arith_ok += 1
        if inc == 0: plain_eq += 1
by_c = collections.defaultdict(list)
for r in gq:
    if toi(r['crank']) is not None: by_c[r['comm']].append(toi(r['crank']))
crk = {k: contiguity(v) for k, v in by_c.items()}
crk_blank = collections.Counter(r['comm'] for r in gq if not r['crank'].strip())
ac = air_check(rows, nb, printed=False)
nb_status = collections.Counter(nb[r['roll']].get('status') or 'ok' for r in rows if r['roll'] in nb)
checks = {
    'state_rank_source': 'printed RANK column (overall GQ rank)',
    'rank_contiguity': contiguity([r['state_rank'] for r in rows]),
    'rank_labels_with_A_suffix': sum(1 for r in gq if r['rank'].endswith('A')),
    'merit_order_breaks': inrank_order(rows, 'score'),
    'unparsed': {'field_format_problems': gq_bad, 'examples': gq_bad_ex, **leftovers(GQ_PDF, GQ_ANCHOR)},
    'duplicate_rolls_in_list': dup_rolls(rows),
    'air': {'source': 'not printed; filled from NBEMS 2025 master result by roll', 'filled_from_roll': sum(1 for r in rows if r['air']),
            'rolls_found_in_nbems': ac['rolls_found_in_nbems'], 'rolls_not_found': ac['rolls_not_found'], 'not_found_rolls': ac['not_found_rolls'],
            'nbems_status_of_found': dict(nb_status)},
    'score_definition': 'TOTAL MARKS = NEET PG 2025 score x (1 + service incentive %/100) for in-service candidates; equals the NEET score otherwise',
    'total_vs_nbems_score_x_incentive': {'match': arith_ok, 'match_without_incentive': plain_eq, 'mismatch': len(arith_bad), 'mismatch_examples': arith_bad[:20]},
    'categories': dict(collections.Counter(r['category'] for r in rows)),
    'category_note': 'COMMUNITY column as printed',
    'in_service_yes': sum(1 for r in gq if r['svc'] == 'YES'),
    'incentive_pct_counts': dict(collections.Counter(r['inc'] for r in gq if r['svc'] == 'YES')),
    'community_rank': crk, 'community_rank_blank_by_community': dict(crk_blank),
    'rows': len(rows), 'pages': len(fitz.open(GQ_PDF)),
    'published_on_note': 'no date printed; Selection Committee release of 8 Nov 2025 (PDF created 2025-11-04); file is the Medical Dialogues copy',
}
with open(OUT + 'dmer_tn_gq_2025.json', 'w') as f:
    json.dump({'authority_code': 'dmer_tn', 'list_name': 'PG Government Quota Provisional Rank List', 'published_on': '2025-11-08',
               'source_file_name': os.path.basename(GQ_PDF), 'rows': rows, 'checks': checks}, f, indent=1)
print('GQ', json.dumps(checks, indent=1, default=str))

# ---------------- MQ
mq = read(MQ_PDF, MQCOLS, anchor=MQ_ANCHOR)
mq_bad, mq_bad_ex = field_problems(mq, {'rank': r'\d+A?', 'roll': ROLL.pattern, 'comm': COMM_OK.pattern, 'score': r'\d+(\.\d+)?'})
mrows = []
for r in mq:
    n = nb.get(r['roll'])
    mrows.append({'roll': r['roll'], 'air': int(n['air']) if n and n.get('air') is not None else None,
                  'state_rank': toi(r['rank'].rstrip('A')), 'score': tof(r['score']), 'category': r['comm'], 'quota': 'Management'})
mac = air_check(mrows, nb, printed=False)
msc = score_check([{'roll': r['roll'], 'neet_score': r['score']} for r in mrows], nb)
gqrolls = {r['roll'] for r in rows}
mchecks = {
    'state_rank_source': 'printed RANK column',
    'rank_contiguity': contiguity([r['state_rank'] for r in mrows]),
    'rank_labels_with_A_suffix': sum(1 for r in mq if r['rank'].endswith('A')),
    'merit_order_breaks': inrank_order(mrows, 'score'),
    'unparsed': {'field_format_problems': mq_bad, 'examples': mq_bad_ex, **leftovers(MQ_PDF, MQ_ANCHOR)},
    'duplicate_rolls_in_list': dup_rolls(mrows),
    'air': {'source': 'not printed; filled from NBEMS 2025 master result by roll', 'filled_from_roll': sum(1 for r in mrows if r['air']),
            'rolls_found_in_nbems': mac['rolls_found_in_nbems'], 'rolls_not_found': mac['rolls_not_found'], 'not_found_rolls': mac['not_found_rolls'],
            'nbems_status_of_found': dict(collections.Counter(nb[r['roll']].get('status') or 'ok' for r in mrows if r['roll'] in nb))},
    'score_definition': 'NEET MARK column (no incentive on MQ list)',
    'neet_score_vs_nbems': msc,
    'categories': dict(collections.Counter(r['category'] for r in mrows)),
    'also_in_gq_list': len({r['roll'] for r in mrows} & gqrolls),
    'rows': len(mrows), 'pages': len(fitz.open(MQ_PDF)),
    'published_on_note': 'no date printed; Selection Committee release of 8 Nov 2025 (PDF created 2025-11-03); file is the Medical Dialogues copy',
}
with open(OUT + 'dmer_tn_mq_2025.json', 'w') as f:
    json.dump({'authority_code': 'dmer_tn', 'list_name': 'PG Management Quota Provisional Rank List', 'published_on': '2025-11-08',
               'source_file_name': os.path.basename(MQ_PDF), 'rows': mrows, 'checks': mchecks}, f, indent=1)
print('MQ', json.dumps(mchecks, indent=1, default=str))
