"""Telangana KNRUHS "PG MEDICAL DEGREE/DIPLOMA ADMISSIONS UNDER COMPETENT AUTHORITY QUOTA FOR THE AY 2026-27 —
COLLEGE WISE REVISED ALLOTMENT LIST IN FIRST PHASE OF COUNSELLING" (16.11.2026, inbox 1744, 111 pages, text layer)
-> rows for POST /api/pg/results/ingest. Authority `knruhs`. (The first Phase-1 CQ allotment was withheld on 16.11 and
replaced by this revised list.)

Layout: blocks of  "COLL :: <code>(<no>) - <college>"  /  "CRS :: <code>(<no>) - <course>"  then one line per allotted
candidate: RANK, ROLL_NO, SCORE, CANDIDATE_NAME, CAT, SX, MIN, PH, Adm Details (e.g. NS-BCB-GEN-MRC-P1).
Read ONLY Rank, Roll No, Score, CAT, MIN, PH and Adm Details (by x position from the header words). Name and gender
are never read into the output; roll numbers are used only to look up the state merit rank and are NOT stored.

- rank_ai = the printed RANK (= NEET PG AIR; checked equal to the merit list's AIR for every roll).
- rank = the state merit rank (S.No) of that roll in the loaded KNRUHS CQ final merit list (+ addenda) — required.
- quota (2025 KNRUHS names): NS -> 'Govt Quota - Non Service-Local', S -> 'Govt Quota - Service-Local'.
- allotted_category = Adm Details without the NS-/S- prefix, the -P1 phase tag and the -MRC flag, i.e. KNRUHS's 2025
  wording (OPEN-GEN, BCB-FEM, SC2-GEN, OPEN-GEN-PHO, MIN-GEN-MSM ...). MRC rows get remarks 'MRC' (KNRUHS flag).
- candidate_category = CAT (+ ' MSM' when MIN says MSM, + ' PH' when PH says PHO).
Strict: anything unexpected -> SystemExit.
Usage: /usr/bin/python3 telangana.py <allotment.pdf> <knruhs_cq_merit.json> <out.json> [--prev <phase-1 rows.json>]
(--prev = Phase 2 list: 'COLLEGE WISE ALLOTMENT LIST IN SECOND PHASE', tags -P1/-P2 → round_status)"""
import sys, os, re, json, collections
import fitz

ROLL = re.compile(r'^2666\d{7}$')
HEAD = ['RANK', 'ROLL_NO', 'SCORE', 'CANDIDATE_NAME', 'CAT', 'SX', 'MIN', 'PH', 'Adm', 'Details']
CATS = {'OC', 'BCA', 'BCB', 'BCC', 'BCD', 'BCE', 'SC1', 'SC2', 'SC3', 'ST', 'EWS'}
ADM = re.compile(r'^(NS|S)-((?:OPEN|BC[A-E]|SC[1-3]|ST|EWS|BC-POOL)-(?:GEN|FEM)(?:-PHO)?|MIN-(?:GEN|FEM)-MSM(?:-PHO)?)(-MRC)?-P([12])$')
QUOTA = {'NS': 'Govt Quota - Non Service-Local', 'S': 'Govt Quota - Service-Local'}
COLLEGES = {   # COLL code -> standard name (same names as the Telangana seat matrix, tools/seat_matrix/telangana.py)
    'AIMD': 'Arundathi Institute of Medical Sciences, Dundigal',   # first seen Phase 2 (25.11.2026), printed name
    'APLO': 'Apollo Institute of Medical Sciences and Research, Hyderabad',
    'AYAN': 'Ayaan Institute of Medical Sciences, Kanaka Mamidi',
    'BASK': 'Bhaskar Medical College, Moinabad, Ranga Reddy, Hyderabad',
    'CARK': 'Chalmeda Anand Rao Insttitute of Medical Sciences, Karimnagar',
    'CMRM': 'CMR Institute of Medical Sciences, Kandalkoya, Medchal',
    'DCMS': 'Deccan College of Medical Sciences, Hyderabad',
    'DPMR': 'Dr. Patnam Mahender Reddy Institute of Medical Sciences, Chevella',
    'ESIM': 'Employees State Insurance Coporation Medical College, Sanath Nagar, Hyderabad',
    'GAND': 'Gandhi Medical College, Secunderabad',
    'GJBP': 'Government Medical College, Jayashankar Bhupalpally', 'GJGN': 'Government Medical College, Jangaon',
    'GKHM': 'Government Medical College, Khammam', 'GKMR': 'Government Medical College, Kamareddy',
    'GKRM': 'Government Medical College, Karimnagar', 'GMCL': 'Government Medical College, Mancherial',
    'GMCM': 'Government Medical College, Mahabubangar', 'GMHB': 'Government Medical College, Mahabubabad',
    'GMNL': 'Government Medical College, Nalgonda', 'GMSR': 'Government Medical College, Suryapet',
    'GNGK': 'Government Medical College, Nagarkurnool', 'GNRM': 'Government Medical College, Nirmal',
    'GNRS': 'Government Medical College, Narsampet', 'GSGR': 'Government Medical College, Sangareddy',
    'GSRC': 'Government Medical College, Rajanna Sircilla', 'GVNZ': 'Government Medical College, Nizamabad',
    'GWNP': 'Government Medical College, Wanaparthy', 'KKTI': 'Kakatiya Medical College, Warangal',
    'KMHD': 'Kamineni Academy of Medical Sciences & Research Center, Hyderabad',
    'KMNI': 'Kamineni Institute of Medical Sciences, Narketpally',
    'MAHE': 'Maheshwara Medical College, Patancheru, Medak', 'MAMS': 'Mamata Academy of Medical Sciences, Bachupally',
    'MEDI': 'Mediciti Institute of Medical Sciences, Ghanpur', 'MHVR': 'Mahavir Institute of Medical Sciences, Vikarabad',
    'MMTA': 'Mamata Medical College, Khammam', 'MNRS': 'MNR Medical College & Hospital, Sangareddy',
    'NIMS': "Nizam's Institute of Medical Sciences, Hyderabad", 'OMCH': 'Osmania Medical College, Hyderabad',
    'PRTM': 'Prathima Institute of Medical Sciences, Karimnagar',
    'RADL': 'Rajiv Gandhi Institute of Medical Sciences, Adilabad',
    'RVMC': 'R.V.M. Institute of Medical Sciences and Research Centre, Siddipet',
    'SGMC': 'Government Medical College, Siddipet', 'SHDN': 'Shadan Institute of Medical Sciences, Peerancheru',
    'SIMS': 'Government Medical College, Ramagundam',          # Singareni IMS = GMC Ramagundam (as the seat matrix)
    'SURB': 'Surabhi Institute of Medical Sciences, Siddipet', 'SVSM': 'S V S Medical College, Mahabubnagar',
    'TRRM': 'TRR Institute of Medical Sciences, Patancheru', 'VRKW': 'Dr. VRK Womens Medical College, Aziznagar'}
COURSES = {   # CRS code -> (printed name, approved course, section)
    'FAM': ('MD(FAMILY MEDICINE)', 'MD - Family Medicine', 'mdms'),   # first seen Phase 2 (25.11.2026)
    'GM': ('MD(GENERAL MEDICINE)', 'MD - General Medicine', 'mdms'), 'PAED': ('MD(PAEDIATRICS)', 'MD - Paediatrics', 'mdms'),
    'ANES': ('MD(ANAESTHESIA)', 'MD - Anaesthesiology', 'mdms'), 'PM': ('MD(RESPIRATORY_MEDICINE)', 'MD - Respiratory Medicine', 'mdms'),
    'DVL': ('MD(DVL)', 'MD - Dermatology', 'mdms'), 'RD': ('MD(RADIODIAGNOSIS)', 'MD - Radio-Diagnosis', 'mdms'),
    'PSY': ('MD(PSYCHIATRY)', 'MD - Psychiatry', 'mdms'),
    'RT': ('MD(RADIATION ONCOLOGY)', 'MD - Radiotherapy / Radiation Oncology', 'mdms'),
    'HA': ('MD(HOSPITAL ADMINISTRATION)', 'MD - Hospital Administration', 'mdms'),
    'TM': ('MD(IMMUNO HAEMATOLOGY AND BLOOD TRANSFUSION MEDICINE)',
           'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'mdms'),
    'EM': ('MD(EMERGENCY MEDICINE)', 'MD - Emergency Medicine', 'mdms'), 'GERIA': ('MD (GERIATRICS)', 'MD - Geriatrics', 'mdms'),
    'PALIAT': ('MD (PALLIATIVE MEDICINE)', 'MD - Palliative Medicine', 'mdms'),
    'NM': ('MD(NUCLEAR_MEDICINE)', 'MD - Nuclear Medicine', 'mdms'),
    'PMR': ('MD(PHYSICAL MEDICINE REHABILITATION)', 'MD - Physical Medicine and Rehabilitation', 'mdms'),
    'TRAMA': ('MS (TRAUMATOLOGY AND SURGERY)', 'MS - Traumatology and Surgery', 'mdms'),
    'GS': ('MS(GENERAL SURGERY)', 'MS - General Surgery', 'mdms'), 'ORTHO': ('MS(ORTHOPAEDICS)', 'MS - Orthopaedics', 'mdms'),
    'OPTHAL': ('MS(OPTHALMOLOGY)', 'MS - Ophthalmology', 'mdms'),
    'ENT': ('MS(OTO-RHINO-LARYNGOLOGY)', 'MS - ENT (Otorhinolaryngology)', 'mdms'),
    'OBG': ('MS(OBSTETRICS AND GYNAECOLOGY)', 'MS - Obstetrics and Gynaecology', 'mdms'),
    'ANATO': ('MD(ANATOMY)', 'MD/MS - Anatomy', 'mdms'), 'PHYSI': ('MD(PHYSIOLOGY)', 'MD - Physiology', 'mdms'),
    'BIO': ('MD(BIOCHEMISTRY)', 'MD - Biochemistry', 'mdms'), 'PATH': ('MD(PATHOLOGY)', 'MD - Pathology', 'mdms'),
    'MICRO': ('MD(MICROBIOLOGY)', 'MD - Microbiology', 'mdms'), 'PHARMA': ('MD(PHARMACOLOGY)', 'MD - Pharmacology', 'mdms'),
    'FM': ('MD(FORENSIC MEDICINE)', 'MD - Forensic Medicine', 'mdms'),
    'SPM': ('MD(COMMUNITY MEDICINE)', 'MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    'DTCD': ('DTCD', 'Diploma in Respiratory Medicine', 'diploma'), 'DO': ('DO', 'Diploma in Ophthalmology', 'diploma'),
    'DPH': ('DPH', 'Diploma in Public Health', 'diploma'), 'DMRD': ('DMRD', 'Diploma in Radio Diagnosis', 'diploma')}
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')


def main():
    args = sys.argv[1:]
    PREV = None
    if '--prev' in args:          # Phase 2: the loaded Phase-1 rows ({"rows": [...]}) → round_status
        i = args.index('--prev'); PREV = args[i + 1]; del args[i:i + 2]
    if len(args) != 3:
        raise SystemExit(__doc__)
    pdf, merit_path, out = args
    PHASE = 2 if PREV else 1
    approved = {c['course'] for c in json.load(open(SHEET))['courses']}
    assert {v[1] for v in COURSES.values()} <= approved
    merit = {r['roll']: r for r in json.load(open(merit_path))['rows']}
    d = fitz.open(pdf)
    t0 = ' '.join(d[0].get_text().split())
    for need in ('KALOJI NARAYANA RAO UNIVERSITY OF HEALTH SCIENCES', 'COMPETENT AUTHORITY QUOTA FOR THE AY 2026-27',
                 'COLLEGE WISE REVISED ALLOTMENT LIST IN FIRST PHASE OF COUNSELLING' if PHASE == 1 else
                 'COLLEGE WISE ALLOTMENT LIST IN SECOND PHASE OF COUNSELLING'):
        if need not in t0:
            raise SystemExit('title changed: missing ' + need)
    last = ' '.join(d[-1].get_text().split())
    md = re.search(r'Date:\s*(\d{2})-(\d{2})-(\d{4})', last)
    if not md:
        raise SystemExit('date not found')
    rows, coll, crs, hx = [], None, None, None
    text_rolls = 0
    stat = collections.Counter()
    for p in d:
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        lines = collections.defaultdict(list)
        for w in p.get_text('words'):
            lines[round(w[3])].append(w)
        for y in sorted(lines):
            ws = sorted(lines[y], key=lambda w: w[0])
            txt = ' '.join(w[4] for w in ws)
            m = re.match(r'^COLL :: ([A-Z]+)\s*\(\d+\) - (.+)$', txt)
            if m:
                if m.group(1) not in COLLEGES:
                    raise SystemExit(f'p{p.number + 1}: unknown college {txt!r}')
                coll = m.group(1); crs = None
                continue
            m = re.match(r'^CRS :: ([A-Z]+)\s*\(\d+\) - (.+)$', txt)
            if m:
                if m.group(1) not in COURSES or ' '.join(m.group(2).split()) != COURSES[m.group(1)][0]:
                    raise SystemExit(f'p{p.number + 1}: unknown course {txt!r}')
                crs = m.group(1)
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
            sc = pick(hx['SCORE'] - 4, hx['CANDIDATE_NAME'] - 4)
            cat = pick(hx['CAT'] - 2, hx['SX'] - 2)
            mino = pick(hx['MIN'] - 2, hx['PH'] - 2)
            ph = pick(hx['PH'] - 2, hx['Adm'] - 2)
            adm = pick(hx['Adm'] - 2, 9999)
            if not (len(rk) == 1 and rk[0].isdigit() and len(sc) == 1 and re.match(r'^-?\d+$', sc[0])
                    and cat in ([c] for c in CATS) and mino in ([], ['MSM']) and ph in ([], ['PHO']) and len(adm) == 1):
                raise SystemExit(f'p{p.number + 1}: row shape (rank {rk})')
            ma = ADM.match(adm[0])
            if ma and int(ma.group(4)) > PHASE:
                ma = None
            if not ma:
                raise SystemExit(f'p{p.number + 1}: unknown Adm Details {adm[0]!r}')
            mr = merit.get(roll[0][4])
            if mr is None:
                raise SystemExit(f'p{p.number + 1}: roll of AIR {rk[0]} not in the merit list')
            if mr['air'] != int(rk[0]):
                raise SystemExit(f'p{p.number + 1}: AIR {rk[0]} != merit list AIR')
            if mr.get('score') is not None and mr['score'] != int(sc[0]):
                stat['score_differs_from_merit'] += 1
            if mr['category'] != cat[0]:
                stat['category_differs_from_merit'] += 1
            name, course, section = COURSES[crs]
            rows.append({'sno': len(rows) + 1, 'rank': mr['state_rank'], 'rank_ai': int(rk[0]),
                         'quota_raw': adm[0], 'quota': QUOTA[ma.group(1)],
                         'institute_raw': COLLEGES[coll], 'course_raw': name, 'course': course, 'section': section,
                         'allotted_category': ma.group(2), 'allotted_category_raw': adm[0],
                         'candidate_category': cat[0] + (' MSM' if mino else '') + (' PH' if ph else ''),
                         'remarks': 'MRC' if ma.group(3) else '', '_phase': int(ma.group(4))})
    link = collections.Counter()
    if PHASE == 2:      # Adm Details tag -P1 = seat from Phase 1 (retained), -P2 = allotted in Phase 2
        prev = {int(p['rank_ai']): p for p in json.load(open(PREV))['rows']}
        for r in rows:
            p = prev.get(r['rank_ai'])
            same = bool(p) and (p['institute_raw'], p['course'], p['quota']) == (r['institute_raw'], r['course'], r['quota'])
            if r['_phase'] == 1:
                if not same:
                    raise SystemExit(f"AIR {r['rank_ai']}: tagged P1 but not the loaded Phase-1 seat")
                r['round_status'] = 'retained'
            elif p and not same:
                r['round_status'] = 'upgraded'
                r.update(prev_quota_raw=p['quota_raw'], prev_quota=p['quota'], prev_institute_raw=p['institute_raw'],
                         prev_course_raw=p['course_raw'], prev_course=p['course'])
            else:
                r['round_status'] = 'fresh'
                if p:
                    link['P2 tag but same seat as Phase 1'] += 1
            r['round_status_raw'] = f"P{r['_phase']}"
            link[r['round_status']] += 1
    for r in rows:
        r.pop('_phase', None)
    if len(rows) != text_rolls:
        raise SystemExit(f'rows {len(rows)} != rolls in text {text_rolls}')
    if len({(r['rank_ai']) for r in rows}) != len(rows):
        raise SystemExit('duplicate AIR')
    checks = {'pages': d.page_count, 'rows': len(rows), 'rolls_in_text': text_rolls,
              'date': f'{md.group(3)}-{md.group(2)}-{md.group(1)}',
              'colleges': len({r['institute_raw'] for r in rows}), 'courses': len({r['course'] for r in rows}),
              'by_quota': dict(collections.Counter(r['quota'] for r in rows)),
              'by_section': dict(collections.Counter(r['section'] for r in rows)),
              'by_category': dict(collections.Counter(r['allotted_category'] for r in rows).most_common()),
              'mrc_rows': sum(1 for r in rows if r['remarks'] == 'MRC'),
              'air_equals_merit_air': len(rows), **dict(stat), 'link_to_phase_1': dict(link),
              'rank': [min(r['rank'] for r in rows), max(r['rank'] for r in rows)],
              'rank_ai': [min(r['rank_ai'] for r in rows), max(r['rank_ai'] for r in rows)]}
    if PHASE == 2:
        body = {'authority_code': 'knruhs', 'round': 'Round 2', 'round_order': 2, 'status': 'final',
                'title': 'KNRUHS Telangana PG Medical 2026 — Competent Authority Quota, Phase 2 College-wise Allotment List',
                'published_on': checks['date'], 'source_file_name': os.path.basename(pdf),
                'notes': ('KNRUHS CQ (convenor) Phase-2 college-wise allotment list. KNRUHS prints neither "provisional" nor '
                          '"final" (Phase 1 stored as final, same here). Adm Details -P1 = seat kept from Phase 1 (retained, '
                          'checked = loaded Phase-1 seat), -P2 = allotted in Phase 2 (upgraded if the candidate held a Phase-1 '
                          'seat, else fresh). rank = state merit rank (CQ final merit list + all addenda incl. 25.11), '
                          'rank_ai = printed NEET PG rank. No names, gender or roll numbers stored.'),
                'rows': rows, 'checks': checks}
        json.dump(body, open(out, 'w'), indent=1, ensure_ascii=False)
        print(out); print(json.dumps(checks, indent=1, ensure_ascii=False))
        return
    body = {'authority_code': 'knruhs', 'round': 'Round 1', 'round_order': 1, 'status': 'final',
            'title': 'KNRUHS Telangana PG Medical 2026 — Competent Authority Quota, Phase 1 College-wise Revised Allotment List',
            'published_on': checks['date'], 'source_file_name': os.path.basename(pdf),
            'notes': ('KNRUHS CQ (convenor) Phase-1 college-wise REVISED allotment list, 16.11.2026 (the first Phase-1 '
                      'allotment was withheld; report by 4 PM 19.11.2026). KNRUHS prints neither "provisional" nor "final". '
                      'rank = state merit rank (S.No of the CQ final merit list 13.11 + addenda), rank_ai = printed NEET PG '
                      'rank (AIR). quota NS/S = non-service / service; category = Adm Details in KNRUHS 2025 wording; '
                      'remarks MRC = KNRUHS MRC flag. No names, gender or roll numbers stored.'),
            'rows': rows, 'checks': checks}
    json.dump(body, open(out, 'w'), indent=1, ensure_ascii=False)
    print(out); print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
