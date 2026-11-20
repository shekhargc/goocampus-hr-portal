"""Telangana KNRUHS "PG MEDICAL DEGREE/DIPLOMA ADMISSIONS UNDER MANAGEMENT QUOTA FOR THE AY 2026-27 — COLLEGE WISE
ALLOTMENT LIST IN FIRST PHASE OF COUNSELLING" (20.11.2026, inbox 1879, 27 pages, fixed-width text layer)
-> rows for POST /api/pg/results/ingest. Authority `knruhs`, its own round 'Round 1 (Management Quota)' (round_order 1,
like AP MQ) so it never replaces the Competent Authority 'Round 1' list (tools/results/telangana.py).

Layout (same as the CQ list): blocks of  "COLL :: <code>(<no>) - <college>"  /  "CRS :: <code>(<no>) - <course>"  /
header "RANK ROLL SCORE STUDENT_NAME LOC CAT SX MIN Adm Details", then one line per allotted candidate. Empty course
blocks print just the header. Read ONLY RANK, LOC, CAT, MIN and Adm Details, by x position from the header words; the
roll number is only used to find candidate lines (and count them), never stored. Name, gender and score are never read
into the output. A 37-character name shifts its line one character right and runs into LOC with no space; LOC is then
the last 2 characters of that word (must be OU / NL).

- rank = rank_ai = the printed RANK (MQ merit is the NEET PG All-India rank; there is no state merit number).
- Adm Details -> quota / allotted_category in the 2025 KNRUHS cut-off wording (= tools/seat_matrix/telangana_mq.py):
    MQ1-LOC-P1 -> Management Quota-(Cat-B), MQ1-Local      MQ1-UNR-P1 -> Management Quota-(Cat-B), MQ1-UR
    MQ2-UNR-P1 -> NRI Quota-(Cat-C), MQ2-UR                MQ3-UNR-P1 -> Institutional Quota-(Cat-C), MQ3-UR
    -MSM- variants (Muslim-minority colleges Deccan, Shadan, Dr. VRK Women's, Ayaan only) -> MQ1-MSM, MQ1-MSM-UR,
    MQ2-MSM-UR, MQ3-MSM-UR. Any other code -> stop.
- candidate_category = CAT (+ ' (Muslim minority)' when MIN = YES); remarks = LOC (OU / NL), as AP MQ's local area.
- institute_raw = the standard college name (same names as telangana.py and the MQ seat matrix), course_raw = printed
  course, course = approved course (telangana.py COURSES).
Strict: anything unexpected -> SystemExit.
Usage: /usr/bin/python3 telangana_mq.py <mq_allotment.pdf> <out.json>"""
import sys, os, re, json, collections
import fitz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telangana import COURSES, COLLEGES as CQ_COLLEGES, SHEET   # same course map / college names as the CQ reader

ROLL = re.compile(r'^2666\d{7}$')
HEAD = ['RANK', 'ROLL', 'SCORE', 'STUDENT_NAME', 'LOC', 'CAT', 'SX', 'MIN', 'Adm', 'Details']
CATS = {'OC', 'BC', 'OBC', 'SC', 'ST', 'EWS'}
LOCS = {'OU', 'NL'}
ADM = re.compile(r'^(MQ[123])-(LOC|UNR)(-MSM)?-P1$')
QUOTA = {'MQ1': 'Management Quota-(Cat-B)', 'MQ2': 'NRI Quota-(Cat-C)', 'MQ3': 'Institutional Quota-(Cat-C)'}
CATEGORY = {(False, 'MQ1', 'LOC'): 'MQ1-Local', (False, 'MQ1', 'UNR'): 'MQ1-UR', (False, 'MQ2', 'UNR'): 'MQ2-UR',
            (False, 'MQ3', 'UNR'): 'MQ3-UR', (True, 'MQ1', 'LOC'): 'MQ1-MSM', (True, 'MQ1', 'UNR'): 'MQ1-MSM-UR',
            (True, 'MQ2', 'UNR'): 'MQ2-MSM-UR', (True, 'MQ3', 'UNR'): 'MQ3-MSM-UR'}
MINORITY = {'DCMS', 'SHDN', 'VRKW', 'AYAN'}
COLLEGES = {   # COLL code -> (printed heading, standard name = telangana.py / seat_matrix/telangana_mq.py)
    'APLO': 'APOLLO MEDICAL COLLEGE, HYDERABAD', 'AYAN': 'AYAAN INSTITUTE OF MEDICAL SCIENCES',
    'BASK': 'BHASKAR MEDICAL COLLEGE, MOINABAD',
    'CARK': 'CHALMEDA ANAND RAO INSTITUTE OF MEDICAL SCIENCES, KARIMNAGAR',
    'CMRM': 'CMR INSTITUTE OF MEDICAL SCIENCES, KANDALKOYA, MEDCHAL', 'DCMS': 'DECCAN COLLEGE OF MEDICAL SCIENCES',
    'DPMR': 'DR PATNAM MAHENDER REDDY INST OF MED SCI, CHEVELLA',
    'KMHD': 'KAMINENI ACADEMY OF MEDICAL SCI AND RESEARCH, HYD',
    'KMNI': 'KAMINENI INSTITUTE OF MEDICAL SCIENCES, NARKETPALLY', 'MAHE': 'MAHESHWARA MEDICAL COLLEGE, PATANCHERU, MEDAK',
    'MAMS': 'MAMATA ACADEMY OF MED SCI, BACHUPALLY', 'MEDI': 'MEDICITI INSTITUTE OF MEDICAL SCIENCES, GHANPUR',
    'MHVR': 'MAHAVIR INST OF MED SCI, VIKARABAD', 'MMTA': 'MAMATHA MEDICAL COLLEGE, KHAMMAM',
    'MNRS': 'MNR MEDICAL COLLEGE AND HOSPITAL, SANGAREDDY', 'NIMG': 'NEELIMA INSTITUTE OF MEDICAL SCIENCES, GHATKESAR',
    'PRTM': 'PRATHIMA INSTITUTE OF MEDICAL SCIENCES, KARIMNAGAR',
    'RVMC': 'RVM INSTITUTE OF MEDICAL SCIENCES AND RESEARCH CENTER, MEDAK',
    'SHDN': 'SHADAN INSTITUTE OF MEDICAL SCIENCES, HYD', 'SURB': 'SURABHI INST OF MED SCI, SIDDIPET',
    'SVSM': 'SRI VENKATA SAI MEDICAL COLLEGE, MAHABUBNAGAR', 'TRRM': 'TRR INSTITUTE OF MEDICAL SCIENCES, INOLE, PATANCHERU',
    'VRKW': 'DR V R K WOMENS MEDICAL COLLEGE'}
STD = {k: CQ_COLLEGES[k] for k in COLLEGES if k in CQ_COLLEGES}
STD['NIMG'] = 'Neelima Institute of Medical Sciences, Medchal'       # MQ seat matrix code NEELIMA (not in the CQ list)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    pdf, out = sys.argv[1:3]
    approved = {c['course'] for c in json.load(open(SHEET))['courses']}
    assert {v[1] for v in COURSES.values()} <= approved
    assert set(STD) == set(COLLEGES)
    d = fitz.open(pdf)
    t0 = ' '.join(d[0].get_text().split())
    for need in ('KALOJI NARAYANA RAO UNIVERSITY OF HEALTH SCIENCES',
                 'PG MEDICAL DEGREE/DIPLOMA ADMISSIONS UNDER MANAGEMENT QUOTA FOR THE AY 2026-27',
                 'COLLEGE WISE ALLOTMENT LIST IN FIRST PHASE OF COUNSELLING'):
        if need not in t0:
            raise SystemExit('title changed: missing ' + need)
    md = re.search(r'Date:\s*(\d{2})-(\d{2})-(\d{4})', ' '.join(d[-1].get_text().split()))
    if not md:
        raise SystemExit('date not found')
    rows, coll, crs, hx = [], None, None, None
    text_rolls, name_into_loc, blocks = 0, 0, []
    for p in d:
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        lines = collections.defaultdict(list)
        for w in p.get_text('words'):
            lines[round(w[3])].append(w)
        for y in sorted(lines):
            ws = sorted(lines[y], key=lambda w: w[0])
            txt = ' '.join(w[4] for w in ws)
            if txt.startswith('COLL ::'):
                m = re.match(r'^COLL :: ([A-Z]+)\s*\(\d+\) - (.+)$', txt)
                if not m or m.group(1) not in COLLEGES or m.group(2) != COLLEGES[m.group(1)]:
                    raise SystemExit(f'p{p.number + 1}: unknown college {txt!r}')
                coll = m.group(1); crs = None
                continue
            if txt.startswith('CRS ::'):
                m = re.match(r'^CRS :: ([A-Z]+)\s*\(\d+\) - (.+)$', txt)
                if not m or m.group(1) not in COURSES or ' '.join(m.group(2).split()) != COURSES[m.group(1)][0]:
                    raise SystemExit(f'p{p.number + 1}: unknown course {txt!r}')
                crs = m.group(1); blocks.append((coll, crs))
                continue
            if txt.startswith('RANK '):
                if [w[4] for w in ws] != HEAD:
                    raise SystemExit(f'p{p.number + 1}: header changed')
                hx = {w[4]: w[0] for w in ws}
                continue
            roll = [w for w in ws if ROLL.match(w[4])]
            if not roll:
                continue
            if len(roll) != 1 or coll is None or crs is None or hx is None:
                raise SystemExit(f'p{p.number + 1}: row outside a college/course block')
            pick = lambda lo, hi: [w[4] for w in ws if lo <= w[0] < hi]
            rk = pick(0, roll[0][0] - 1)
            sc = pick(hx['SCORE'] - 4, hx['STUDENT_NAME'] - 4)
            loc = pick(hx['LOC'] - 2, hx['CAT'] - 2)
            if not loc:          # a 37-character name pushes the line one character right and joins LOC with no
                span = [w for w in ws if w[0] < hx['LOC'] - 2 < w[2]]     # space: LOC = last 2 chars of that word
                if len(span) != 1 or span[0][2] > hx['CAT'] - 2:
                    raise SystemExit(f'p{p.number + 1}: LOC column empty')
                loc = [span[0][4][-2:]]
                name_into_loc += 1
            cat = pick(hx['CAT'] - 2, hx['SX'] - 2)
            sx = pick(hx['SX'] - 2, hx['MIN'] - 2)
            mino = pick(hx['MIN'] - 2, hx['Adm'] - 2)
            adm = pick(hx['Adm'] - 2, 9999)
            where = f'p{p.number + 1} rank {rk}'
            if not (len(rk) == 1 and rk[0].isdigit() and len(sc) == 1 and re.match(r'^-?\d+$', sc[0])
                    and len(loc) == 1 and loc[0] in LOCS and cat in ([c] for c in CATS) and sx in (['M'], ['F'], ['T'])
                    and mino in ([], ['YES']) and len(adm) == 1):
                raise SystemExit(f'{where}: row shape [loc {loc} cat {cat} min {mino} adm {adm}]')
            ma = ADM.match(adm[0])
            if not ma:
                raise SystemExit(f'{where}: unknown Adm Details {adm[0]!r}')
            mq, area, msm = ma.group(1), ma.group(2), bool(ma.group(3))
            if (mq, area) == ('MQ2', 'LOC') or (mq, area) == ('MQ3', 'LOC'):
                raise SystemExit(f'{where}: unknown Adm Details {adm[0]!r}')
            if msm != (coll in MINORITY):
                raise SystemExit(f'{where}: {adm[0]} at {coll} (MSM seats only at Muslim-minority colleges)')
            if msm and not mino:
                raise SystemExit(f'{where}: MSM seat to a candidate without MIN = YES')
            name, course, section = COURSES[crs]
            rows.append({'sno': len(rows) + 1, 'rank': int(rk[0]), 'rank_ai': int(rk[0]),
                         'quota_raw': adm[0], 'quota': QUOTA[mq],
                         'institute_raw': STD[coll], 'course_raw': name, 'course': course, 'section': section,
                         'allotted_category': CATEGORY[(msm, mq, area)], 'allotted_category_raw': adm[0],
                         'candidate_category': cat[0] + (' (Muslim minority)' if mino else ''),
                         'remarks': loc[0], '_block': len(blocks)})
    if len(rows) != text_rolls:
        raise SystemExit(f'rows {len(rows)} != rolls in text {text_rolls}')
    if len({r['rank_ai'] for r in rows}) != len(rows):
        raise SystemExit('duplicate NEET rank')
    if len(set(blocks)) != len(blocks):
        raise SystemExit('a college x course block is printed twice')
    by_block = collections.defaultdict(list)
    for r in rows:
        by_block[r['_block']].append(r['rank'])
    unsorted = sum(1 for v in by_block.values() if v != sorted(v))
    if unsorted:
        raise SystemExit(f'{unsorted} college x course blocks not in NEET-rank order')
    for r in rows:
        del r['_block']
    cc = collections.defaultdict(collections.Counter)
    for r in rows:
        cc[r['institute_raw']][f"{r['course']} | {r['allotted_category']}"] += 1
    checks = {'pages': d.page_count, 'rows': len(rows), 'rolls_in_text': text_rolls,
              'date': f'{md.group(3)}-{md.group(2)}-{md.group(1)}',
              'course_blocks_printed': len(blocks), 'course_blocks_with_rows': len(by_block),
              'name_ran_into_loc_column': name_into_loc,
              'colleges': len({r['institute_raw'] for r in rows}), 'courses': len({r['course'] for r in rows}),
              'by_college': dict(collections.Counter(r['institute_raw'] for r in rows).most_common()),
              'by_course': dict(collections.Counter(r['course'] for r in rows).most_common()),
              'by_quota': dict(collections.Counter(r['quota'] for r in rows).most_common()),
              'by_allotted_category': dict(collections.Counter(r['allotted_category'] for r in rows).most_common()),
              'by_adm_details': dict(collections.Counter(r['allotted_category_raw'] for r in rows).most_common()),
              'by_candidate_category': dict(collections.Counter(r['candidate_category'] for r in rows).most_common()),
              'by_loc': dict(collections.Counter(r['remarks'] for r in rows).most_common()),
              'by_section': dict(collections.Counter(r['section'] for r in rows)),
              'rank_ai': [min(r['rank_ai'] for r in rows), max(r['rank_ai'] for r in rows)],
              'college_course_category': {k: dict(sorted(v.items())) for k, v in sorted(cc.items())}}
    body = {'authority_code': 'knruhs', 'round': 'Round 1 (Management Quota)', 'round_order': 1, 'status': 'final',
            'title': 'KNRUHS Telangana PG Medical 2026 — Management Quota, Phase 1 College-wise Allotment List',
            'published_on': checks['date'], 'source_file_name': os.path.basename(pdf),
            'notes': ('KNRUHS Management Quota Phase-1 college-wise allotment list, 20.11.2026 (report by 4 PM 26.11.2026). '
                      'KNRUHS prints neither "provisional" nor "final". Its own round, separate from the CQ Round 1. '
                      'rank = rank_ai = printed NEET PG rank (AIR). quota / allotted_category in the 2025 KNRUHS wording '
                      '(MQ1 = Management Quota-(Cat-B) Local / UR, MQ2 = NRI Quota-(Cat-C), MQ3 = Institutional '
                      'Quota-(Cat-C); MSM = Muslim-minority colleges); candidate_category = caste category (+ Muslim '
                      'minority); remarks = local area (OU / NL). No names, gender, scores or roll numbers stored.'),
            'rows': rows, 'checks': checks}
    json.dump(body, open(out, 'w'), indent=1, ensure_ascii=False)
    print(out)
    print(json.dumps({k: v for k, v in checks.items() if k != 'college_course_category'}, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
