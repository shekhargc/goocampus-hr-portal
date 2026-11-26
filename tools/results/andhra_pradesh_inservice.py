"""Andhra Pradesh (Dr NTRUHS) PG (Medical) CQ In-service college-wise allotment list -> rows for POST /api/pg/results/ingest.

Usage: /usr/bin/python3 andhra_pradesh_inservice.py <allotment.pdf> <out.json> --merit <inservice_final_merit.pdf>

The allotment PDF ("College wise Final Allotment List of PG (Medical) Admissions, CQ Service Phase-I, 2026-27",
notice 5148/EA2/PG/2026 of 13-11-2026; the provisional list prints "Provisional") has a notice on page 1, then one
table per college: a college-name row, the header row (S.No., NEET RANK, NEET Roll No, NEET Score, Name of the
Candidate, Gender, Category, Local Area, Allotment Details, Phase) and one row per allotted candidate.
Allotment Details = '<college code> - <course code> - <seat area AU|SVU|APUR> - <seat category> - <G|F> [- MRC] --- <n>'.
Name, Gender and roll are NEVER put in the output (the roll is used in memory only, to look up the merit rank).
--merit = the "PG (Medical) CQ 2026-27 - Provisional Final Merit list of In-Service Candidates" (07.11.2026) PDF:
  Sl.No, NEET Roll No, NEET Rank, NEET Score, Name, Gender, Category, Area, Muslim Minority, PwBD (read in memory:
  Sl.No, roll, rank, score only).
- Stored as its own round 'Round 1 (In-service)' (round_order 1), so the later non-service Phase-I list (round 'Round 1')
  does not replace it (cf. Tamil Nadu 'Round 1 (PwD)').
- rank = in-service merit Sl.No (by roll; the merit list's AIR and score must equal the printed ones); rank_ai = NEET RANK.
- quota (2025 spellings): 'Govt Quota - Service-<candidate Local Area>-<Local if the seat area = the candidate's area,
  else the seat area (APUR = unreserved)>' e.g. Service-AU-Local, Service-APNL-APUR, Service-SVU-AU.
- allotted_category = '<seat category>-<G|F>' (OC-G, BCB-F, SC3-G ...; MINORITY -> MIN-G-MSM as 2025);
  allotted_category_raw = the whole Allotment Details text; candidate_category = printed Category; remarks = 'MRC'
  (meritorious reserved candidate) when printed.
- Courses by code. 'FM' is NOT mapped: both MD Forensic Medicine and MD Family Medicine exist at the colleges it is
  used for and no code legend is published, so it goes to the name-memory review queue (course_raw explains why).
Strict: anything unexpected -> SystemExit.
"""
import sys, os, re, json, collections
import fitz
PHASE = 1                 # set to 2 by main() when --prev is given (Phase-II list)
PHASES = ('Phase-1',)

ROLL = re.compile(r'^2666\d{7}$')
INT = re.compile(r'^\d+$')
HEAD = ['S.No.', 'NEET RANK', 'NEET Roll No', 'NEET Name of the Candidate Score', '', 'Gender', 'Category',
        'Local Area', 'Allotment Details', 'Phase']
CATS = {'OC', 'BCA', 'BCB', 'BCC', 'BCD', 'BCE', 'SC1', 'SC2', 'SC3', 'ST', 'EWS'}
SEAT_CATS = CATS | {'MINORITY'}
AREAS = {'AU', 'SVU', 'APNL'}
SEAT_AREAS = {'AU', 'SVU', 'APUR'}
FM_RAW = 'FM (NTRUHS course code - Forensic Medicine or Family Medicine, not stated)'
COURSES = {
    'ANAT': 'MD/MS - Anatomy', 'ANES': 'MD - Anaesthesiology', 'BIO': 'MD - Biochemistry', 'DVL': 'MD - Dermatology',
    'EM': 'MD - Emergency Medicine', 'ENT': 'MS - ENT (Otorhinolaryngology)', 'GM': 'MD - General Medicine',
    'GS': 'MS - General Surgery', 'MICRO': 'MD - Microbiology', 'OBG': 'MS - Obstetrics and Gynaecology',
    'OPTHAL': 'MS - Ophthalmology', 'ORTHO': 'MS - Orthopaedics', 'PAED': 'MD - Paediatrics', 'PATH': 'MD - Pathology',
    'PHARM': 'MD - Pharmacology', 'PHY': 'MD - Physiology', 'PM': 'MD - Respiratory Medicine',   # Pulmonary Medicine
    'PSY': 'MD - Psychiatry', 'RD': 'MD - Radio-Diagnosis', 'RT': 'MD - Radiotherapy / Radiation Oncology',
    'SPM': 'MD - Social & Preventive Medicine / Community Medicine', 'FM': None,
}
COURSE_RAW = {'ANAT': 'MD/MS Anatomy', 'ANES': 'MD Anaesthesiology', 'BIO': 'MD Biochemistry', 'DVL': 'MD DVL',
              'EM': 'MD Emergency Medicine', 'ENT': 'MS ENT', 'GM': 'MD General Medicine', 'GS': 'MS General Surgery',
              'MICRO': 'MD Microbiology', 'OBG': 'MS OBG', 'OPTHAL': 'MS Ophthalmology', 'ORTHO': 'MS Orthopaedics',
              'PAED': 'MD Paediatrics', 'PATH': 'MD Pathology', 'PHARM': 'MD Pharmacology', 'PHY': 'MD Physiology',
              'PM': 'MD Pulmonary Medicine', 'PSY': 'MD Psychiatry', 'RD': 'MD Radio-Diagnosis',
              'RT': 'MD Radiotherapy', 'SPM': 'MD SPM / Community Medicine', 'FM': FM_RAW}
DETAIL = re.compile(r'^([A-Z]{3,5}) - ([A-Z]{2,6}) - ([A-Z]{2,4}) - ([A-Z0-9]{2,8}) - ([GF])( - MRC)? --- (\d+)$')
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')


def read_merit(path):
    d = fitz.open(path)
    t0 = ' '.join(d[0].get_text().split()).upper()
    if 'IN-SERVICE' not in t0 and 'IN SERVICE' not in t0:
        raise SystemExit('merit: not the in-service list')
    out, text_rolls = {}, 0
    for p in d:
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        for t in p.find_tables().tables:
            for r in t.extract():
                c = [' '.join((x or '').split()) for x in r]
                if len(c) != 10 or not ROLL.match(c[1]):
                    continue
                if not (INT.match(c[0]) and INT.match(c[2]) and INT.match(c[3])):
                    raise SystemExit(f'merit p{p.number + 1}: Sl.No / rank / score shape')
                out[c[1]] = {'sl': int(c[0]), 'air': int(c[2]), 'score': int(c[3])}
    sl = sorted(v['sl'] for v in out.values())
    if len(out) != text_rolls or sl != list(range(1, len(sl) + 1)):
        raise SystemExit('merit: rows / Sl.No do not add up')
    return out


def read(path, merit):
    approved = {c['course'] for c in json.load(open(SHEET))['courses']}
    assert {v for v in COURSES.values() if v} <= approved
    d = fitz.open(path)
    t1 = ' '.join(d[1].get_text().split())
    m = re.search(r'College wise (Final|Provisional) Allotment List of PG \(Medical\) Admissions, CQ Service Phase-' + ('I' if PHASE == 1 else 'II') + ', 2026-27', t1)
    if not m:
        raise SystemExit('page 2 title changed')
    status = m.group(1).lower()
    t0 = ' '.join(d[0].get_text().split())
    md = re.search(r'Date:\s*(\d{2})-(\d{2})-(\d{4})', t0)
    rows, text_rolls, college, code_of = [], 0, None, {}
    for p in d:
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        if p.number == 0:
            continue                      # page 1 = the notice (the provisional list's notice has a small table)
        for t in p.find_tables().tables:
            for r in t.extract():
                c = [' '.join((x or '').split()) for x in r]
                if len(c) == 10 and re.fullmatch(r'-\s*Phase-[12]', c[9]):   # a wrapped '-' of the details cell
                    c[9] = c[9].lstrip('- ')
                if len(c) == 10:     # '---' before the seat no. can wrap as '-- -', '- --' (Phase-II PDFs)
                    c[8] = re.sub(r'(?<=[A-Z]) [- ]*-[- ]* (\d+)$', r' --- \1', c[8])
                if len(c) != 10:
                    raise SystemExit(f'p{p.number + 1}: table with {len(c)} columns')
                if c[0] and not any(c[1:]):
                    college = c[0]
                    continue
                if c == HEAD:
                    continue
                where = f'p{p.number + 1} sno {c[0] if INT.match(c[0]) else "?"}'
                if not (INT.match(c[0]) and INT.match(c[1]) and ROLL.match(c[2]) and INT.match(c[3])):
                    raise SystemExit(f'{where}: unexpected row shape')
                if c[5] not in ('M', 'F', 'T') or c[6] not in CATS or c[7] not in AREAS or c[9] not in PHASES:
                    raise SystemExit(f'{where}: gender / category / area / phase value')
                dm = DETAIL.match(c[8])
                if not dm:
                    raise SystemExit(f'{where}: allotment details shape [{c[8]}]')
                ccode, course, seat_area, seat_cat, gf, mrc, _n = dm.groups()
                if college is None or code_of.setdefault(ccode, college) != college:
                    raise SystemExit(f'{where}: college code {ccode} does not match its college heading')
                if course not in COURSES or seat_area not in SEAT_AREAS or seat_cat not in SEAT_CATS:
                    raise SystemExit(f'{where}: unknown course / seat area / seat category')
                mr = merit.get(c[2])
                if mr is None or mr['air'] != int(c[1]) or mr['score'] != int(c[3]):
                    raise SystemExit(f'{where}: not in the in-service merit list with the same AIR / score')
                cand = c[7]
                quota = f"Govt Quota - Service-{cand}-{'Local' if seat_area == cand else seat_area}"
                cat = 'MIN-G-MSM' if seat_cat == 'MINORITY' else f'{seat_cat}-{gf}'
                if seat_cat == 'MINORITY' and gf != 'G':
                    raise SystemExit(f'{where}: minority seat not G')
                rows.append({'sno': len(rows) + 1, 'rank': mr['sl'], 'rank_ai': int(c[1]), 'quota_raw': seat_area,
                             'quota': quota, 'institute_raw': college, 'course_raw': COURSE_RAW[course],
                             'course': COURSES[course] or '', 'section': 'mdms', 'allotted_category': cat,
                             'allotted_category_raw': c[8], 'candidate_category': c[6], 'remarks': 'MRC' if mrc else '', '_phase': c[9],
                             '_sno': int(c[0]), '_college': college})
    if text_rolls != len(rows):
        raise SystemExit(f'rolls in text {text_rolls} != rows {len(rows)}')
    by_col = collections.defaultdict(list)
    for r in rows:
        by_col[r['_college']].append(r['_sno'])
    bad = [k for k, v in by_col.items() if v != list(range(1, len(v) + 1))]
    if bad:
        raise SystemExit(f'S.No not 1..n within {len(bad)} colleges')
    for r in rows:
        del r['_sno'], r['_college']
    checks = {
        'pages': d.page_count, 'rows': len(rows), 'rolls_in_pdf_text': text_rolls, 'status': status,
        'notice_date': f'{md.group(3)}-{md.group(2)}-{md.group(1)}' if md else '', 'colleges': len(by_col),
        'college_codes': {k: v for k, v in sorted(code_of.items())},
        'by_quota': dict(collections.Counter(r['quota'] for r in rows).most_common()),
        'by_allotted_category': dict(collections.Counter(r['allotted_category'] for r in rows).most_common()),
        'by_course': dict(collections.Counter(r['course'] or r['course_raw'] for r in rows).most_common()),
        'mrc': sum(1 for r in rows if r['remarks'] == 'MRC'),
        'merit_rank_found_and_air_score_agree': len(rows),
        'rank': [min(r['rank'] for r in rows), max(r['rank'] for r in rows)],
        'rank_ai': [min(r['rank_ai'] for r in rows), max(r['rank_ai'] for r in rows)],
    }
    return status, checks['notice_date'], rows, checks


def link_phase2(rows, prev_path):
    """Phase-II list: the Phase column says where the seat came from. Phase-1 = kept from Phase-I (must equal the loaded
    Phase-I seat → retained); Phase-2 = allotted in Phase-II → upgraded when the candidate held a Phase-I seat
    (prev_* filled), else fresh. Returns a count dict for checks."""
    prev = {int(p['rank_ai']): p for p in json.load(open(prev_path))['rows']}
    link = collections.Counter()
    for r in rows:
        p = prev.get(r['rank_ai'])
        same = bool(p) and (p['institute_raw'], p['course_raw'], p['quota']) == (r['institute_raw'], r['course_raw'], r['quota'])
        if r['_phase'] == 'Phase-1':
            r['round_status'] = 'retained'
            link['retained' + ('' if same else ' — NOT the loaded Phase-I seat' if p else ' — no Phase-I row loaded')] += 1
        elif p and not same:
            r['round_status'] = 'upgraded'
            r.update(prev_quota_raw=p['quota_raw'], prev_quota=p['quota'], prev_institute_raw=p['institute_raw'],
                     prev_course_raw=p['course_raw'], prev_course=p['course'])
            link['upgraded'] += 1
        else:
            r['round_status'] = 'fresh'
            link['fresh' + (' (same seat as Phase-I, re-allotted)' if p else '')] += 1
        r['round_status_raw'] = r['_phase']
    return dict(link)


def main():
    a = sys.argv[1:]
    if '--merit' not in a:
        raise SystemExit(__doc__)
    i = a.index('--merit'); merit_pdf = a[i + 1]; del a[i:i + 2]
    global PHASE, PHASES
    prev_path = None
    if '--prev' in a:     # Phase-II list: link to the loaded Phase-I rows
        i = a.index('--prev'); prev_path = a[i + 1]; del a[i:i + 2]
        PHASE, PHASES = 2, ('Phase-1', 'Phase-2')
    if len(a) != 2:
        raise SystemExit(__doc__)
    pdf, out = a
    status, date, rows, checks = read(pdf, read_merit(merit_pdf))
    if PHASE == 2:
        checks['link_to_phase_1'] = link_phase2(rows, prev_path)
    for r in rows:
        r.pop('_phase', None)
    body = {'authority_code': 'ntruhs', 'round': 'Round 1 (In-service)'.replace('Round 1', f'Round {PHASE}'), 'round_order': PHASE, 'status': status,
            'title': f'PG (Medical) CQ 2026-27 - In-service Phase-' + ('I' if PHASE == 1 else 'II') + f' College wise {status.title()} Allotment List',
            'published_on': date, 'source_file_name': os.path.basename(pdf),
            'notes': ('Dr NTRUHS Competent Authority Quota, IN-SERVICE candidates, Phase-I (= Round 1), college-wise list. '
                      'Own round so the non-service Phase-I list does not replace it. rank = Sl.No in the CQ in-service '
                      'provisional final merit list (07.11.2026), rank_ai = printed NEET AIR. quota = Govt Quota - '
                      'Service-<candidate area>-<Local / seat area> (2025 spelling); allotted_category = seat category + '
                      'G/F; remarks MRC = meritorious reserved candidate. Course code FM (Forensic or Family Medicine) left '
                      'for review. No names, roll numbers or gender stored.'),
            'rows': rows, 'checks': checks}
    with open(out, 'w') as f:
        json.dump(body, f, indent=1, ensure_ascii=False)
    print(out)
    print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
