"""Andhra Pradesh (Dr NTRUHS) PG (Medical) CQ NON-SERVICE college-wise allotment list -> rows for POST /api/pg/results/ingest.

Usage: /usr/bin/python3 andhra_pradesh_nonservice.py <allotment.pdf> <out.json> --merit <nonservice_final_merit.pdf>

Same layout as the in-service list (andhra_pradesh_inservice.py, whose course table / detail pattern are reused):
notice on page 1, then one table per college (college row, header, one row per allotted candidate).
"College wise Final Allotment List of PG (Medical) Admissions, CQ Non-Service Phase-I, 2026-27" (notice
5148/EA2/PG/2026 of 15-11-2026). Stored as round 'Round 1' (round_order 1); 'Round 1 (In-service)' is a separate round.
--merit = "PG (Medical) CQ 2026-27 - Provisional Final Merit list of Non-Service Candidates" (07.11.2026), read with
tools/merit_lists/read_ntruhs_ap_cq_table.py (roll used in memory only).
- rank = non-service merit Sl.No (by roll; AIR and score must equal the printed ones); rank_ai = NEET RANK.
- quota (2025 spellings): 'Govt Quota - Non Service-<candidate area>-<Local | seat area>'.
- allotted_category = '<seat category>-<G|F>[-PH]' (MINORITY -> MIN-G-MSM); remarks 'MRC' when printed.
Name, gender and roll are NEVER put in the output. Strict: anything unexpected -> SystemExit.
"""
import sys, os, re, json, collections
import fitz
PHASE = 1                 # set to 2 by main() when --prev is given (Phase-II list)
PHASES = ('Phase-1',)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'merit_lists'))
import andhra_pradesh_inservice as ins
import read_ntruhs_ap_cq_table as meritreader

HA_RAW = 'HA (NTRUHS course code - MD or Diploma Hospital Administration, both offered at these colleges, not stated)'
EXTRA = {   # codes not in the in-service list; Diploma codes start with D (section 'diploma')
    'NM': ('MD - Nuclear Medicine', 'MD Nuclear Medicine', 'mdms'),
    'PAM': ('MD - Palliative Medicine', 'MD Palliative Medicine', 'mdms'),   # first seen Phase-II (25.11.2026)
    'FAM': ('MD - Family Medicine', 'MD Family Medicine', 'mdms'),           # first seen Phase-II (25.11.2026)
    'TM': ('MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'MD Transfusion Medicine (SVIMS)', 'mdms'),
    'HA': ('', HA_RAW, 'mdms'),
    'DPM': ('Diploma in Psychological Medicine', 'DPM', 'diploma'),
    'DCP': ('Diploma in Pathology', 'DCP (Diploma in Clinical Pathology)', 'diploma'),
    'DPH': ('Diploma in Public Health', 'DPH', 'diploma'),
    'DDVL': ('Diploma in Dermatology', 'DDVL', 'diploma'),
    'DLO': ('Diploma in ENT', 'DLO', 'diploma'),
}
COURSES = {k: (v, ins.COURSE_RAW[k], 'mdms') for k, v in ins.COURSES.items()}
COURSES['FM'] = ('', ins.FM_RAW, 'mdms')
COURSES.update(EXTRA)
DETAIL = re.compile(r'^([A-Z]{3,6}) - ([A-Z]{2,6}) - ([A-Z]{2,4}) - ([A-Z0-9]{2,8})( - PH)? - ([GF])( - MRC)? (?:---|-- -|- --) (\d+)$')   # PH printed before G/F; one cell wraps '---' as '-- -'


def read_merit(path):
    d = fitz.open(path)
    t0 = ' '.join(d[0].get_text().split()).upper()
    if 'NON-SERVICE' not in t0 and 'NON SERVICE' not in t0:
        raise SystemExit('merit: not the non-service list')
    _d, kind, stage, recs = meritreader.read(path)
    if kind != 'nonservice' or stage != 'provisional_final':
        raise SystemExit(f'merit: {kind} {stage}')
    return {r['roll']: {'sl': r['sl'], 'air': r['air'], 'score': r['score']} for r in recs}


def read(path, merit):
    approved = {c['course'] for c in json.load(open(ins.SHEET))['courses']}
    assert {v[0] for v in COURSES.values() if v[0]} <= approved
    d = fitz.open(path)
    t1 = ' '.join(d[1].get_text().split())
    m = re.search(r'College wise (Final|Provisional) Allotment List of PG \(Medical\) Admissions, CQ Non[- ]Service Phase-' + ('I' if PHASE == 1 else 'II') + ', 2026-27', t1, re.I)
    if not m:
        raise SystemExit('page 2 title changed')
    status = m.group(1).lower()
    md = re.search(r'Date:\s*(\d{2})-(\d{2})-(\d{4})', ' '.join(d[0].get_text().split()))
    rows, text_rolls, college, code_of, unk = [], 0, None, {}, collections.Counter()
    for p in d:
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        if p.number == 0:
            continue
        for t in p.find_tables().tables:
            for r in t.extract():
                c = [' '.join((x or '').split()) for x in r]
                if len(c) == 10 and re.fullmatch(r'-\s*Phase-[12]', c[9]):   # a wrapped '-' of the details cell
                    c[9] = c[9].lstrip('- ')
                if len(c) == 10:     # '---' before the seat no. can wrap as '-- -', '- --', '- - -' (Phase-II PDFs)
                    c[8] = re.sub(r'(?<=[A-Z]) [- ]*-[- ]* (\d+)$', r' --- \1', c[8])
                if len(c) != 10:
                    raise SystemExit(f'p{p.number + 1}: table with {len(c)} columns')
                if c[0] and not any(c[1:]):
                    college = c[0]; continue
                if c[0] in ('Sl.No.', 'S.No.'):
                    continue
                where = f'p{p.number + 1} sno {c[0] if ins.INT.match(c[0]) else "?"}'
                if not (ins.INT.match(c[0]) and ins.INT.match(c[1]) and ins.ROLL.match(c[2]) and ins.INT.match(c[3])):
                    raise SystemExit(f'{where}: unexpected row shape')
                if c[5] not in ('M', 'F', 'T') or c[6] not in ins.CATS or c[7] not in ins.AREAS or c[9] not in PHASES:
                    raise SystemExit(f'{where}: gender / category / area / phase value [{c[6]}|{c[7]}|{c[9]}]')
                dm = DETAIL.match(c[8])
                if not dm:
                    raise SystemExit(f'{where}: allotment details shape [{c[8]}]')
                ccode, course, seat_area, seat_cat, ph, gf, mrc, _n = dm.groups()
                if college is None or code_of.setdefault(ccode, college) != college:
                    raise SystemExit(f'{where}: college code {ccode} does not match its college heading')
                if course not in COURSES or seat_area not in ins.SEAT_AREAS or seat_cat not in ins.SEAT_CATS:
                    unk[(course, seat_area, seat_cat)] += 1; continue
                mr = merit.get(c[2])
                if mr is None or mr['air'] != int(c[1]) or mr['score'] != int(c[3]):
                    raise SystemExit(f'{where}: not in the non-service merit list with the same AIR / score')
                cand = c[7]
                quota = f"Govt Quota - Non Service-{cand}-{'Local' if seat_area == cand else seat_area}"
                if seat_cat == 'MINORITY':
                    if gf != 'G' or ph:
                        raise SystemExit(f'{where}: minority seat not G')
                    cat = 'MIN-G-MSM'
                else:
                    cat = f'{seat_cat}-{gf}' + ('-PH' if ph else '')
                rows.append({'sno': len(rows) + 1, 'rank': mr['sl'], 'rank_ai': int(c[1]), 'quota_raw': seat_area,
                             'quota': quota, 'institute_raw': college, 'course_raw': COURSES[course][1],
                             'course': COURSES[course][0], 'section': COURSES[course][2], 'allotted_category': cat,
                             'allotted_category_raw': c[8], 'candidate_category': c[6], 'remarks': 'MRC' if mrc else '', '_phase': c[9],
                             '_sno': int(c[0]), '_college': college})
    if unk:
        raise SystemExit(f'unknown course / seat area / seat category: {dict(unk)}')
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
    pdf, out = a
    status, date, rows, checks = read(pdf, read_merit(merit_pdf))
    if PHASE == 2:
        checks['link_to_phase_1'] = link_phase2(rows, prev_path)
    for r in rows:
        r.pop('_phase', None)
    body = {'authority_code': 'ntruhs', 'round': 'Round 1'.replace('Round 1', f'Round {PHASE}'), 'round_order': PHASE, 'status': status,
            'title': f'PG (Medical) CQ 2026-27 - Non-service Phase-' + ('I' if PHASE == 1 else 'II') + f' College wise {status.title()} Allotment List',
            'published_on': date, 'source_file_name': os.path.basename(pdf),
            'notes': ('Dr NTRUHS Competent Authority Quota, NON-SERVICE candidates, Phase-I (= Round 1), college-wise list. '
                      'In-service Phase-I is its own round (Round 1 (In-service)). rank = Sl.No in the CQ non-service '
                      'provisional final merit list (07.11.2026), rank_ai = printed NEET AIR. quota = Govt Quota - Non '
                      'Service-<candidate area>-<Local / seat area> (2025 spelling); allotted_category = seat category + G/F '
                      '(+PH); remarks MRC = meritorious reserved candidate. Course codes FM (Forensic or Family Medicine), HA (MD or Diploma '
                      'Hospital Administration) left for review. No names, roll numbers or gender stored.'),
            'rows': rows, 'checks': checks}
    json.dump(body, open(out, 'w'), indent=1, ensure_ascii=False)
    print(out); print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
