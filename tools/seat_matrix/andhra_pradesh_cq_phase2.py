"""Andhra Pradesh (Dr NTRUHS) PG (Medical) Competent Authority Quota (CQ) 2026-27 PHASE-II seat matrix for ENHANCED /
NEWLY SANCTIONED seats (21 Nov 2026) -> standardised seat rows for the SEPARATE body
"Andhra Pradesh — Phase 2 — State Counselling" (authority `ntruhs`, section state, round_no 2). The Round 1 body
"Andhra Pradesh — State Counselling" is never touched.

Usage: /usr/bin/python3 andhra_pradesh_cq_phase2.py <folder with 1912-1916.pdf> <cutoffs2025.json> <round1_dump.json>
                                                    <out.json> [--accept-proposed]

Source (inbox 1910-1916): Phase-II web-options notification dt 21-11-2026 (1910) + five seat matrices: AU Non-Service
(1912), AU Service (1913), SVU Non-Service (1914), Minority Non-Service (1915), SVU Service (1916). No SWI, no Minority
Service and no NET GROUP files were published for Phase-II. The notification says the Phase-II matrix lists ONLY the
enhanced / newly permitted seats; Phase-I not-reported seats and resignation vacancies are ALSO allotted in Phase-II but
are NOT printed anywhere — so every stored seat here is an added seat (new_in_round = seats).

Layout = Round 1 (andhra_pradesh_cq.py: same 42 category columns, '<course> Total' rows, quota
'Govt Quota - <Non Service|Service>-<AU|SVU>-<Local|APUR>', categories OC-G … BC-POOL, minority MIN-G-MSM); its
read_matrix(), COLLEGES, COURSES and the cut-off bridge rules are reused. The Phase-II minority sheet has an extra (empty)
TOTAL column, so it has its own small reader.

Checks (SystemExit on any failure): SHA-256 of every PDF, page titles, headers, one course + one Total row per page and
no course twice, every course's rows = its printed Total row (column by column, inside read_matrix), every printed number
in the category columns is a parsed cell (sum of all digits on the page = 2 x seats, rows + Total row), minority college
Total row, unknown college / course codes listed up front.
Proposed (not in Round 1 maps; used only with --accept-proposed): GMCP -> Government Medical College, Paderu (new 2024
GMC, AU area, listed in the notification's Table-II; no 2025 PG cut-off), PAM -> MD - Palliative Medicine (1 seat at Homi
Bhabha Cancer Hospital, Visakhapatnam).
"""
import sys, os, json, re, hashlib, collections
import fitz
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import andhra_pradesh_cq as R1
from common import grids, clean, load_cuts, build, report

FILES = {('AU', 'NS'): '1912.pdf', ('AU', 'S'): '1913.pdf', ('SVU', 'NS'): '1914.pdf', ('SVU', 'S'): '1916.pdf',
         ('MIN', 'NS'): '1915.pdf'}
NOTIFICATION = '1910.pdf'
SHA = {'1910.pdf': 'dd4a1edef97caa10fd36e10c4a5275461e1d7b432ad583decaa5568860d21a69',
       '1912.pdf': '1724344698c6e8a2c81e8d2fdf4ec79b48ef9470f7ad44127f17cbf20bf7e7b6',
       '1913.pdf': '675fe777a14cc6a67767705bac41ec0d0c640c2ef7d9043fa0677e84d8e07dc5',
       '1914.pdf': 'c1427fc7804fc005509dacabf81e91bfa6d2a547c26f64f69c369e43ee8f89d7',
       '1915.pdf': 'cdf73cc546b0920bee6256978997c66d73def26c3fee7f1b6615370180b56ba5',
       '1916.pdf': '1a6a46b5ceb5d951372c3922b6aee383fd70a0be7c52ac6f00b0212ca1d135d0'}
SUFFIX = '2026-27 (Phase-II Seat Matrix for Enhanced/Newly Sanctioned seats)'
TITLES = {('AU', 'NS'): 'PG CQ NON SERVICE AU SEAT MATRIX', ('AU', 'S'): 'PG CQ SERVICE AU SEAT MATRIX',
          ('SVU', 'NS'): 'PG CQ NON SERVICE SVU SEAT MATRIX', ('SVU', 'S'): 'PG CQ SERVICE SVU SEAT MATRIX',
          ('MIN', 'NS'): 'PG CQ NON-SERVICE MINORITY SEAT MATRIX'}
PROPOSED_COLLEGES = {'GMCP': 'Government Medical College, Paderu'}
PROPOSED_COURSES = {'PAM': ('MD - Palliative Medicine', 'mdms')}
MIN_HDR = ['SNO', 'COLLEGE', 'AREA', 'COURSE', 'CATEGORY', 'SEAT_TYPE', 'S_NS', 'MINORITY', 'TOTAL']


def title_ok(path, key):
    want = f'{TITLES[key]} {SUFFIX}'
    for p in fitz.open(path):
        got = re.sub(r'\s+', ' ', p.get_text().split('SNO')[0]).strip()
        if got != want:
            raise SystemExit(f'{os.path.basename(path)} p{p.number + 1}: title {got!r}')


def scan_codes(path, minority):
    """College / course codes used in a file + per-page course check (one course and one Total row per page)."""
    colleges, courses, totals = set(), set(), []
    for p in fitz.open(path):
        tabs = grids(p)
        if len(tabs) != 1:
            raise SystemExit(f'{os.path.basename(path)} p{p.number + 1}: {len(tabs)} tables')
        t = [[clean(x) for x in r] for r in tabs[0]]
        body = [r for r in t[1:] if r[0].isdigit()]
        colleges |= {r[1] for r in body}
        page_courses = {r[3].upper() for r in body}
        courses |= page_courses
        if not minority:
            tot = [next(x for x in r[:4] if x.endswith(' Total')) for r in t[1:] if any(x.endswith(' Total') for x in r[:4])]
            if len(page_courses) != 1 or len(tot) != 1:
                raise SystemExit(f'{os.path.basename(path)} p{p.number + 1}: courses {page_courses} totals {tot}')
            lab = tot[0][:-6].upper()
            if R1.TOTAL_ALIAS.get(lab, lab) != next(iter(page_courses)):
                raise SystemExit(f'{os.path.basename(path)} p{p.number + 1}: Total row {tot[0]} for {page_courses}')
            totals.append(lab)
    if len(totals) != len(set(totals)):
        raise SystemExit(f'{os.path.basename(path)}: a course appears on two pages {totals}')
    return colleges, courses


def printed_digits(path):
    """Sum of every number printed in the category columns (rows + Total rows) — must be 2 x the parsed seats."""
    s = 0
    for p in fitz.open(path):
        t = p.find_tables().tables[0]
        hdr = [clean(x) for x in grids(p)[0][0]]
        x_left = t.rows[0].cells[hdr.index('OC_G')][0]
        y0, y1 = t.bbox[1], t.bbox[3]
        for w in p.get_text('words'):
            cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
            if cx >= x_left and y0 <= cy <= y1 and w[4].isdigit():
                s += int(w[4])
    return s


def read_minority(path, sns):
    rows, printed, summed, digits = [], {}, collections.Counter(), 0
    for p in fitz.open(path):
        for t in grids(p):
            hdr = [clean(h) for h in t[0]]
            if hdr != MIN_HDR:
                raise SystemExit(f'minority header {hdr}')
            for r in t[1:]:
                r = [clean(x) for x in r]
                digits += sum(int(x) for x in r[7:9] if x.isdigit())
                if r[1].endswith(' Total'):
                    printed[r[1][:-6]] = R1.num(r[7]) or 0
                    continue
                if not r[0].isdigit():
                    continue
                n, tot = R1.num(r[7]), R1.num(r[8])
                if n is None or tot is None or (tot and tot != n):
                    raise SystemExit(f'minority row {r}')
                code, area, course, cat, st, s_ns = r[1], r[2], r[3].upper(), r[4], r[5], r[6]
                if code not in R1.COLLEGES or course not in R1.COURSES or cat != 'CLDG' or area not in ('AU', 'SVU') \
                        or st not in ('L', 'APUR') or s_ns != sns:
                    raise SystemExit(f'minority row {r}')
                summed[code] += n
                if n:
                    rows.append({'code': code, 'college': R1.COLLEGES[code], 'course_code': course,
                                 'course': R1.COURSES[course][0], 'section': R1.COURSES[course][1],
                                 'quota': f"Govt Quota - {'Non Service' if sns == 'NS' else 'Service'}-{area}-"
                                          f"{'Local' if st == 'L' else 'APUR'}",
                                 'seat_area': area if st == 'L' else 'APUR', 'category': 'MIN-G-MSM', 'seats': n,
                                 'sns': sns})
    if {k: v for k, v in summed.items() if v or k in printed} != printed:
        raise SystemExit(f'minority totals {dict(summed)} != {printed}')
    if digits != 2 * sum(printed.values()):
        raise SystemExit(f'minority printed numbers {digits} != 2 x {sum(printed.values())}')
    return rows, printed


def fam(q):   # = andhra_pradesh_cq.main(): Local seats bridge to the same Local quota; APUR to any area's APUR
    ns = 'Non Service' if 'Non Service' in q else 'Service'
    area, kind = q.rsplit('-', 2)[-2:]
    if kind == 'Local':
        return (f'Govt Quota - {ns}-{area}-Local$',)
    same = f'Govt Quota - {ns}-{area}-APUR$' if area != 'SWI' else None
    return tuple(x for x in (same, f'Govt Quota - {ns}-AU-APUR$', f'Govt Quota - {ns}-SVU-APUR$',
                             f'Govt Quota - {ns}-APNL-APUR$') if x)


def catm(x):
    return () if x['category'].endswith('-POOL') else (x['category'],)


def main():
    folder, cuts_path, r1_path, out_path = sys.argv[1:5]
    checks = {'sha256': {}, 'files': {}}
    for f, h in SHA.items():
        got = hashlib.sha256(open(os.path.join(folder, f), 'rb').read()).hexdigest()
        if got != h:
            raise SystemExit(f'{f}: SHA-256 {got} (expected {h}) — a different file, re-check it')
        checks['sha256'][f] = 'ok'
    # 1. names: every college / course code must be known (Round 1 maps) or a listed proposal
    used_c, used_k = set(), set()
    for key, f in FILES.items():
        title_ok(os.path.join(folder, f), key)
        c, k = scan_codes(os.path.join(folder, f), key[0] == 'MIN')
        used_c |= c
        used_k |= k
    unknown_c = sorted(used_c - set(R1.COLLEGES))
    unknown_k = sorted(used_k - set(R1.COURSES))
    stray = [x for x in unknown_c if x not in PROPOSED_COLLEGES] + [x for x in unknown_k if x not in PROPOSED_COURSES]
    if stray:
        raise SystemExit(f'UNKNOWN codes with no proposal: {stray}')
    if unknown_c or unknown_k:
        print('codes not in andhra_pradesh_cq.py (proposed mapping):',
              {**{c: PROPOSED_COLLEGES[c] for c in unknown_c}, **{k: PROPOSED_COURSES[k][0] for k in unknown_k}})
        if '--accept-proposed' not in sys.argv:
            raise SystemExit('stopped: confirm the proposed names, then re-run with --accept-proposed')
        R1.COLLEGES.update({c: PROPOSED_COLLEGES[c] for c in unknown_c})
        R1.COURSES.update({k: PROPOSED_COURSES[k] for k in unknown_k})
    checks['proposed_used'] = {'colleges': unknown_c, 'courses': unknown_k}
    # 2. parse (course Total rows asserted inside R1.read_matrix) + every printed number accounted for
    rows = []
    for (region, sns), f in FILES.items():
        path = os.path.join(folder, f)
        if region == 'MIN':
            r, printed = read_minority(path, sns)
            checks['files'][f'{region}-{sns}'] = {'file': f, 'rows': len(r), 'seats': sum(x['seats'] for x in r),
                                                  'college_totals': printed}
        else:
            r, totals = R1.read_matrix(path, region, sns)
            seats = sum(x['seats'] for x in r)
            dig = printed_digits(path)
            if dig != 2 * seats:
                raise SystemExit(f'{f}: printed numbers {dig} != 2 x parsed seats {seats}')
            checks['files'][f'{region}-{sns}'] = {
                'file': f, 'rows': len(r), 'seats': seats, 'printed_numbers': f'{dig} = 2 x {seats}',
                'course_totals': {k: sum(v) for k, v in totals.items() if sum(v)}}
        rows += r
    merged = collections.OrderedDict()
    for x in rows:
        k = (x['college'], x['course'], x['quota'], x['category'])
        if k in merged:
            merged[k]['seats'] += x['seats']
        else:
            merged[k] = dict(x)
    rows = list(merged.values())
    out = build(rows, load_cuts(cuts_path, 'Andhra Pradesh'), 'Andhra Pradesh', 'AP', fam, catm)
    for x in out:
        x['new_in_round'] = x['seats']      # the Phase-II matrix lists only enhanced / newly sanctioned seats
    # 3. against the stored Round 1 body (staging seatmatrix-dump)
    r1 = json.load(open(r1_path))
    r1 = r1['rows'] if isinstance(r1, dict) else r1
    r1_cc, r1_line = collections.Counter(), collections.Counter()
    for x in r1:
        r1_cc[(x['college_name'], x['course_name'])] += x['seats']
        r1_line[(x['college_name'], x['course_name'], x['quota'], x['category'])] += x['seats']
    r1_codes = {x['college_name']: x['college_code'] for x in r1}
    code_drift = sorted(n for n in {x['college_name'] for x in out} if n in r1_codes and
                        r1_codes[n] != next(y['college_code'] for y in out if y['college_name'] == n))
    if code_drift:
        raise SystemExit(f'college codes differ from the Round 1 body: {code_drift}')
    p2_cc = collections.Counter()
    for x in out:
        p2_cc[(x['college_name'], x['course_name'])] += x['seats']
    cmp_lines = [{'college': c, 'course': k, 'round1': r1_cc.get((c, k), 0), 'phase2_added': n,
                  'after': r1_cc.get((c, k), 0) + n} for (c, k), n in sorted(p2_cc.items())]
    r1_colleges = {x['college_name'] for x in r1}
    checks['round1'] = {
        'round1_body': {'rows': len(r1), 'seats': sum(x['seats'] for x in r1), 'colleges': len(r1_colleges)},
        'new_colleges': sorted({x['college_name'] for x in out} - r1_colleges),
        'new_college_course': [l for l in cmp_lines if not l['round1'] and l['college'] in r1_colleges],
        'lines_on_existing_quota_category': sum(1 for x in out if r1_line.get((x['college_name'], x['course_name'],
                                                                                  x['quota'], x['category']))),
        'college_course_lines': len(cmp_lines)}
    checks['by_quota'] = dict(sorted(collections.Counter(
        {q: sum(x['seats'] for x in out if x['quota'] == q) for q in {x['quota'] for x in out}}).items()))
    checks['by_college'] = dict(sorted(collections.Counter(
        {c: sum(x['seats'] for x in out if x['college_name'] == c) for c in {x['college_name'] for x in out}}).items()))
    checks['seats'] = sum(x['seats'] for x in out)
    checks['colleges'] = len({x['college_name'] for x in out})
    checks['new_in_round'] = sum(x['new_in_round'] for x in out)
    report(out, {'seats = file totals': (checks['seats'], sum(v['seats'] for v in checks['files'].values()))})
    json.dump({'rows': out, 'checks': checks, 'round1_compare': cmp_lines}, open(out_path, 'w'), indent=1)
    print(json.dumps({k: v for k, v in checks.items() if k not in ('by_college',)}, indent=1, ensure_ascii=False)[:6000])


if __name__ == '__main__':
    main()
