"""Odisha (PG Medical Counselling Committee, MKCG Brahmapur) "COMMON ALLOTMENT" list of the State Quota PG Medical
counselling (Round 1: 04.11.2026) → rows for POST /api/pg/results/ingest. One PDF, three tables:
  COMMON ALLOTMENT- DIRECT CANDIDATES (MD/MS)       ┐ 8 columns: State Application No, Name of the Candidate (Dr),
  COMMON ALLOTMENT- INSERVICE CANDIDATES (MD/MS/DNB) ┘ CMR-UR, Choice No, Allotted College, Allotted Course,
                                                      Alloted Subject, Allotted Category
  SEATS LYING VACANT AFTER ROUND-1 ALLOTMENT          (Type of Seat, College, No of Seat, Course, Subject, Category)
                                                      → only counted into checks, not posted.
PERSONAL DATA: the application number and the name are never read into the output (columns 0 and 1 are blanked
the moment a line is read).

Ranks: `rank` = CMR-UR (the common merit rank, = 'Rank-UR' of the revised merit lists), `rank_ai` = NEET PG AIR
from our stored Odisha merit list of the same kind (direct → direct list, in-service incl. DNB → in-service list),
looked up by that rank. A rank printed 'A<n>' (a candidate added after rank n) is stored as n with no AIR — the
merit list's rank n is someone else.
Quota (2025 Odisha cut-off spellings): direct → Government Quota, in-service → Government Quota-Inservice, a "-MGT"
college → Management Quota / Management Quota-Inservice, DNB → DNB Quota (section dnb). Category as printed
('-PWD' → '-PwD'); candidate category is not printed.
Run with /usr/bin/python3 (PyMuPDF):
    odisha.py <allotment.pdf> <merit_direct.json> <merit_inservice.json> <out.json>
              [--seat-matrix <od seat-matrix dump.json>] [--round "Round 1"] [--round-order 1] [--status provisional]

--upgraded: the "UPGRADED ALLOTMENT WITH ROUND-1 ALLOTMENT AND ADMISSION STATUS" list (08.11.2026) → the Round 1
position AFTER upgradation, posted as the same round (it replaces the Round 1 body; the ingest keeps prev_row_count).
One 15-column table: Appl No, Name (both blanked as read), CMR-UR, Type (DIR/INS), Inst/Course/Subject/Category/Choice
for UGR-1 (upgraded round 1) and for R-1 (round 1), Status of Adm R-1 ('ADMITTED' or blank). The list holds every
candidate who has a seat after the upgradation: UGR-1 filled = the new seat (same seat re-allotted, a better seat, or
— no R-1 seat — a fresh allotment); UGR-1 blank = kept the R-1 seat (only ADMITTED candidates). Round-1 candidates not
in the list must all be R-1 choice no. 1 (notice point 1: not considered for upgradation) — they are dropped: their
seats were re-allotted (keeping them overshoots the seat matrix), i.e. they did not take admission.
Every R-1 block must equal the loaded Round 1 body row of that Type + CMR-UR; rank_ai comes from that row (same
candidate) and, for fresh allotments, from --merit-direct / --merit-inservice if given (else left empty and listed).
    odisha.py --upgraded <upgraded.pdf> <round1_body.json> <out.json> [--seat-matrix <od seat-matrix dump.json>]
              [--merit-direct <m.json>] [--merit-inservice <m.json>] [--round "Round 1"] [--round-order 1]
              [--status provisional]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
UPGRADED = '--upgraded' in args
if UPGRADED:
    args.remove('--upgraded')
opt = {'--round': 'Round 1', '--round-order': '1', '--status': 'provisional'}
for f in ('--seat-matrix', '--round', '--round-order', '--status', '--merit-direct', '--merit-inservice'):
    if f in args:
        i = args.index(f); opt[f] = args[i + 1]; del args[i:i + 2]
if UPGRADED:
    if len(args) != 3:
        raise SystemExit(__doc__)
    PDF, R1_BODY, OUT = args
else:
    if len(args) != 4 or '--merit-direct' in opt or '--merit-inservice' in opt:
        raise SystemExit(__doc__)
    PDF, M_DIRECT, M_INSERVICE, OUT = args

HEAD = ['State Application No', 'Name of the Candidate (Dr)', 'CMR-UR', 'Choice No', 'Allotted College',
        'Allotted Course', 'Alloted Subject', 'Allotted Category']
VAC_HEAD = ['Type of Seat', 'Name of College', 'No of Seat', 'Course', 'Subject', 'Category']
COLLEGES = {  # printed → (standard name = the 2026 seat matrix / 2025 cut-off name, management column?)
    'SCB MCH KATAKA': ('SCB Medical College, Cuttack', False),
    'MKCG MCH BERHAMPUR': ('Maharaja Krushna Chandra Gajapati Medical College and Hospital, Brahmapur', False),
    'VIMSAR BURLA': ('Veer Surendra Sai Institute of Medical Sciences and Research, Burla', False),
    'PGIMER BBSR': ('Postgraduate Institute of Medical Education & Research and Capital Hospital, Bhubaneswar', False),
    'AHRCC KATAKA': ('Acharya Harihar Post Graduate Institute of Cancer, Cuttack', False),
    'FM MCH BALESWAR': ('Fakir Mohan Medical College and Hospital, Balasore, Odisha', False),
    'PRM MCH BARIPADA': ('Pandit Raghunath Murmu Medical College and Hospital, Baripada, Mayurbhanj, Odisha', False),
    'BB MCH BALANGIR': ('Bhima Bhoi Medical College and Hospital, Balangir, Odisha', False),
    'HI-TECH MCH BBSR': ('Hi-Tech Medical College & Hospital, Bhubaneswar', False),
    'HI-TECH MCH RKL': ('Hi-Tech Medical College & Hospital, Rourkela', False),
    'DRIEMS KATAKA': ('DRIEMS Institute Of Health Sciences And Hospital, Tangi, Odisha', False),
    'HITECH-BBSR-MGT': ('Hi-Tech Medical College & Hospital, Bhubaneswar', True),
    'HITECH-RKL-MGT': ('Hi-Tech Medical College & Hospital, Rourkela', True),
    'DRIEMS-KATAKA-MGT': ('DRIEMS Institute Of Health Sciences And Hospital, Tangi, Odisha', True),
    'S J MCH PURI': ('Shri Jagannath Medical College and Hospital, Puri, Odisha', False),
    'SLN MCH KORAPUT': ('Saheed Laxman Nayak Medical College and Hospital, Koraput, Odisha', False)}
MDMS = {
    'ANATOMY': 'MD/MS - Anatomy', 'PHYSIOLOGY': 'MD - Physiology', 'BIOCHEMISTRY': 'MD - Biochemistry',
    'PHARMACOLOGY': 'MD - Pharmacology', 'FMT': 'MD - Forensic Medicine', 'PATHOLOGY': 'MD - Pathology',
    'MICROBIOLOGY': 'MD - Microbiology', 'COMM MEDICINE': 'MD - Social & Preventive Medicine / Community Medicine',
    'GEN MEDICINE': 'MD - General Medicine', 'PEDIATRICS': 'MD - Paediatrics', 'PSYCHIATRY': 'MD - Psychiatry',
    'RESP MEDICINE': 'MD - Respiratory Medicine', 'SKIN VD (DVL)': 'MD - Dermatology',
    'TRANSF MEDICINE': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'OBST & GYN': 'MS - Obstetrics and Gynaecology', 'GEN SURGERY': 'MS - General Surgery',
    'ORTHOPAEDICS': 'MS - Orthopaedics', 'OPHTHALMOLOGY': 'MS - Ophthalmology', 'ENT': 'MS - ENT (Otorhinolaryngology)',
    'ANESTHESIOLOGY': 'MD - Anaesthesiology', 'RADIODIAGNOSIS': 'MD - Radio-Diagnosis',
    'RADIOTHERAPY': 'MD - Radiotherapy / Radiation Oncology'}
DNB = {'GEN MEDICINE': 'DNB - General Medicine (Post-MBBS)', 'OBST & GYN': 'DNB - Obstetrics and Gynaecology (Post-MBBS)',
       'GEN SURGERY': 'DNB - General Surgery (Post-MBBS)', 'PEDIATRICS': 'DNB - Paediatrics (Post-MBBS)',
       'OPHTHALMOLOGY': 'DNB - Ophthalmology (Post-MBBS)', 'RESP MEDICINE': 'DNB - Respiratory Medicine (Post-MBBS)',
       'ANESTHESIOLOGY': 'DNB - Anaesthesiology (Post-MBBS)'}
CATS = {'UR', 'SC', 'ST', 'SEBC', 'EWS'}
SM_QUOTA = {'Government Quota': 'State Quota', 'Government Quota-Inservice': 'In-service Quota',
            'Management Quota': 'Management Quota', 'Management Quota-Inservice': 'Management Quota (In-service)',
            'DNB Quota': 'DNB Quota'}

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()


def category(s):
    s = s.replace('-PWD', '-PwD')
    base = s.split('-')[0]
    if base not in CATS or s.split('-', 1)[-1] not in (base, 'GC', 'ES', 'PwD'):
        raise SystemExit(f'unknown category {s!r}')
    return s


UG_HEAD = ['State Appl No', 'Name of Candidate (Dr)', 'CMR-UR', 'Type', 'Allotted Inst UGR-1', 'Allotted Course UGR-1',
           'Allotted Subject UGR-1', 'Allotted Category UGR-1', 'Allotted Choice UGR- 1', 'Allotted Inst R-1',
           'Allotted Course R-1', 'Allotted Subject R- 1', 'Allotted Category R-1', 'Allotted Choice R-1',
           'Status of Adm R-1']
UG_TITLE = 'UPGRADED ALLOTMENT WITH ROUND-1 ALLOTMENT AND ADMISSION STATUS'


def seat(sec, inst_raw, course_raw, subj, cat_raw):
    """Printed seat → (college, mgt, course, section, quota, category) — same rules as the Round 1 reader below."""
    if inst_raw not in COLLEGES:
        raise SystemExit(f'unknown college {inst_raw!r}')
    college, mgt = COLLEGES[inst_raw]
    if course_raw == 'MD/MS' and subj in MDMS:
        course, section = MDMS[subj], 'mdms'
    elif course_raw == 'DNB' and subj in DNB and sec == 'inservice':
        course, section = DNB[subj], 'dnb'
    else:
        raise SystemExit(f'unknown course {course_raw!r} / {subj!r} in {sec}')
    if section == 'dnb':
        quota = 'DNB Quota'
    elif mgt:
        quota = 'Management Quota' if sec == 'direct' else 'Management Quota-Inservice'
    else:
        quota = 'Government Quota' if sec == 'direct' else 'Government Quota-Inservice'
    return college, mgt, course, section, quota, category(cat_raw)


def run_upgraded():
    doc = fitz.open(PDF)
    cd = re.match(r'D:(\d{4})(\d{2})(\d{2})', doc.metadata.get('creationDate') or '')
    published = f'{cd.group(1)}-{cd.group(2)}-{cd.group(3)}' if cd else ''
    lines, pages = [], 0
    for pg in doc:
        tabs = pg.find_tables().tables
        if len(tabs) != 1:
            raise SystemExit(f'p{pg.number + 1}: {len(tabs)} tables')
        got = []
        for r in tabs[0].extract():
            c = [clean(x) for x in r]
            if len(c) != len(UG_HEAD):
                raise SystemExit(f'p{pg.number + 1}: {len(c)} columns')
            if c[0] == UG_TITLE or c[0].startswith('(1) Candidates those who have allotted their choices against '
                                                    'Choice No-1 during the Round-1 are not considered for Upgradation'):
                got.append(c[0][:3]); continue
            if c[0] == 'State Appl No':
                if c != UG_HEAD:
                    raise SystemExit(f'p{pg.number + 1}: column headings changed')
                got.append('head'); continue
            if not c[0].isdigit() or not c[1]:
                raise SystemExit(f'p{pg.number + 1}: unexpected line')
            c[0] = c[1] = ''                                   # application no + name — never kept
            lines.append(c)
        if got != ['UPG', '(1)', 'head']:
            raise SystemExit(f'p{pg.number + 1}: title / notice / heading rows changed: {got}')
        pages += 1

    r1 = json.load(open(R1_BODY))
    if r1.get('authority_code') != 'ojee' or r1.get('round') != opt['--round']:
        raise SystemExit('round 1 body is not ojee / the same round')
    R1 = {}
    for x in r1['rows']:
        k = ('inservice' if x['quota_raw'].startswith('In-service') else 'direct', x['rank'])
        if k in R1:
            raise SystemExit(f'round 1 body: {k} twice')
        R1[k] = x
    merit = {}
    for sec, f in (('direct', '--merit-direct'), ('inservice', '--merit-inservice')):
        if f in opt:
            merit[sec] = {r['state_rank']: r['air'] for r in json.load(open(opt[f]))['rows']}

    rows, kinds, ver, seen, prev = [], collections.Counter(), collections.Counter(), set(), {}
    for n, c in enumerate(lines, 1):
        sec = {'DIR': 'direct', 'INS': 'inservice'}.get(c[3])
        m = re.fullmatch(r'(A?)(\d+)', c[2])
        if not sec or not m:
            raise SystemExit(f'line {n}: type {c[3]!r} / rank {c[2]!r}')
        rank, after = int(m.group(2)), bool(m.group(1))
        k = (sec, rank)
        if k in seen:
            raise SystemExit(f'line {n}: {k} twice')
        if sec in prev and rank < prev[sec] or sec == 'direct' and 'inservice' in prev:
            raise SystemExit(f'line {n}: not in Type / CMR-UR order')
        seen.add(k); prev[sec] = rank
        ug, ro, adm = c[4:9], c[9:14], c[14]
        for blk in (ug, ro):
            if any(blk) and not all(blk) or any(blk) and not blk[4].isdigit():
                raise SystemExit(f'line {n}: half-filled seat block')
        if adm not in ('', 'ADMITTED') or adm and not any(ro):
            raise SystemExit(f'line {n}: admission status {adm!r}')
        x = R1.get(k)
        if any(ro):                                        # the R-1 block must be the loaded Round 1 row
            if not x or (x['institute_raw'], x['course_raw'], x['allotted_category_raw']) != (
                    ro[0], f'{ro[1]} {ro[2]}', ro[3]) or not x['remarks'].endswith(f'Choice no. {ro[4]}'):
                raise SystemExit(f'line {n}: R-1 block differs from the loaded Round 1 row {k}')
        elif x:
            raise SystemExit(f'line {n}: R-1 block blank but {k} has a Round 1 seat')
        if not any(ug) and not any(ro):
            raise SystemExit(f'line {n}: no seat at all')
        if not any(ug) and not adm:
            raise SystemExit(f'line {n}: kept a Round 1 seat without admission')
        r1_after = bool(x and x['remarks'].startswith('Rank printed A'))
        if not any(ug):
            kind, s = 'kept Round 1 seat (admitted)', ro
            note = 'Kept the Round 1 seat (admitted in Round 1, no upgradation).'
        elif not any(ro):
            kind, s = 'fresh allotment', ug
            note = 'Fresh allotment in the upgradation (no Round 1 seat).'
        elif ug == ro:
            kind, s = 'same seat re-allotted', ug
            note = ('Same Round 1 seat re-allotted in the upgradation (Round 1 '
                    + ('admitted' if adm else 'not admitted') + ').')
        else:
            kind, s = 'upgraded to another seat', ug
            note = (f'Upgraded from Round 1 seat {ro[0]} {ro[1]} {ro[2]} {ro[3]} (choice {ro[4]}, '
                    + ('admitted' if adm else 'not admitted') + ').')
        kinds[(sec, kind)] += 1
        college, mgt, course, section, quota, cat = seat(sec, *s[:4])
        if x and not after and not r1_after:
            ai = x['rank_ai']
            if sec in merit and merit[sec].get(rank) != ai:
                raise SystemExit(f'line {n}: Round 1 AIR differs from the merit list')
            ver['AIR from the Round 1 row' if ai else 'AIR NOT FOUND'] += 1
        elif after or r1_after:
            ai = None; ver['added after rank (no AIR)'] += 1
        elif sec in merit:
            ai = merit[sec].get(rank); ver['AIR from the merit list (fresh)' if ai else 'AIR NOT FOUND'] += 1
        else:
            ai = None; ver['fresh — AIR not looked up (no --merit file)'] += 1
        rows.append({'sno': n, 'rank': rank, 'rank_ai': ai,
                     'quota_raw': ('In-service' if sec == 'inservice' else 'Direct') + (' · Management' if mgt else ''),
                     'quota': quota, 'institute_raw': s[0], 'institute': college, 'course_raw': f'{s[1]} {s[2]}',
                     'course': course, 'section': section, 'allotted_category': cat, 'allotted_category_raw': s[3],
                     'candidate_category': '',
                     'remarks': (f'Rank printed {c[2]} (added after rank {rank}). ' if after else '')
                     + ('Round 1 list printed this rank as A' + str(rank) + ' (added after rank). ' if r1_after else '')
                     + f'{note} Choice no. {s[4]}'})
    if ver.get('AIR NOT FOUND'):
        raise SystemExit(f'AIR missing: {dict(ver)}')

    # Round 1 candidates not in the list: notice point 1 — R-1 choice no. 1, not considered for upgradation
    gone = [x for k, x in R1.items() if k not in seen]
    if any(not x['remarks'].endswith('Choice no. 1') for x in gone):
        raise SystemExit('a Round 1 candidate missing from the list was not on choice no. 1')

    def occ(rs):
        o = collections.Counter()
        for x in rs:
            o[(x['institute'], x['course'], SM_QUOTA[x['quota']], '' if 'Management' in x['quota']
               else x['allotted_category'])] += 1
        return o
    after_o, r1_o = occ(rows), occ(r1['rows'])
    net = {' | '.join(k): after_o[k] - r1_o[k] for k in set(after_o) | set(r1_o) if after_o[k] != r1_o[k]}
    smc = None
    if '--seat-matrix' in opt:
        sm, smq, cc = collections.Counter(), collections.Counter(), set()
        for x in json.load(open(opt['--seat-matrix']))['rows']:
            sm[(x['college_name'], x['course_name'], x['quota'], x['category'])] += x['seats']
            smq[(x['college_name'], x['course_name'], x['quota'])] += x['seats']
            cc.add((x['college_name'], x['course_name']))
        miss = sorted({(x['institute'], x['course']) for x in rows} - cc)
        if miss:
            raise SystemExit(f'college × course not in the seat matrix: {miss}')
        byq = collections.Counter()
        for k, v in after_o.items():
            byq[k[:3]] += v
        bad = {k: (v, smq.get(k, 0)) for k, v in byq.items() if v > smq.get(k, 0)}
        badc = {k: (v, sm.get(k, 0)) for k, v in after_o.items() if v > sm.get(k, 0)}
        gone_o = occ(gone)
        over_if_kept = {' | '.join(k): (after_o[k] + v, sm.get(k, 0)) for k, v in gone_o.items()
                        if after_o[k] + v > sm.get(k, 0)}
        if bad or badc:
            raise SystemExit(f'more allotted than seat-matrix seats: {bad} {badc}')
        smc = {'college_course_groups': len({(x['institute'], x['course']) for x in rows}),
               'college_course_quota_category_cells': len(after_o), 'all_within_matrix': True,
               'cells_over_matrix_if_the_missing_round1_candidates_kept_their_seats': over_if_kept}

    C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
    checks = {'pages': pages, 'lines': len(rows), 'by_type': dict(collections.Counter(s for s, _ in seen)),
              'by_kind': {f'{s} · {k}': v for (s, k), v in sorted(kinds.items())},
              'round1_rows': len(R1), 'round1_in_list': len(R1) - len(gone),
              'round1_not_in_list_all_choice_1': {'count': len(gone),
                                                   'by_list': dict(collections.Counter(
                                                       'direct' if x['quota_raw'].startswith('Direct') else 'inservice'
                                                       for x in gone))},
              'verification': dict(ver), 'seat_change_vs_round1': net, 'seat_matrix': smc,
              'by_quota': C('quota'), 'by_section': C('section'), 'by_institute': C('institute'),
              'by_allotted_category': C('allotted_category')}
    out = {'authority_code': 'ojee', 'round': opt['--round'], 'round_order': int(opt['--round-order']),
           'status': opt['--status'],
           'title': f'Upgraded Allotment — {opt["--round"]} (position after upgradation), State Quota PG Medical '
                    '(Direct + In-service, MD/MS/DNB), Odisha',
           'published_on': published, 'source_file_name': os.path.basename(PDF),
           'notes': ('Odisha PG Medical Counselling Committee, state quota: each candidate\'s seat after the Round 1 '
                     'upgradation (upgraded / same seat re-allotted / kept the admitted Round 1 seat / fresh '
                     'allotment — see remarks). Replaces the 04.11.2026 Round 1 list; Round 1 choice-1 candidates '
                     'not in this list did not keep their seats (re-allotted). rank = CMR-UR, rank_ai = NEET PG AIR '
                     '(from the Round 1 row of the same candidate / the revised merit list). -MGT colleges = '
                     'management seats. Application numbers and names never kept.'),
           'rows': rows, 'checks': checks}
    json.dump(out, open(OUT, 'w'), ensure_ascii=False)
    print(out['title'], '|', out['round'], out['status'], out['published_on'])
    for k, v in checks.items():
        if k not in ('by_institute', 'seat_change_vs_round1'):
            print(k, v)
    print('seat_change_vs_round1', len(net), 'cells')


if UPGRADED:
    run_upgraded()
    sys.exit()

doc = fitz.open(PDF)
cd = re.match(r'D:(\d{4})(\d{2})(\d{2})', doc.metadata.get('creationDate') or '')
published = f'{cd.group(1)}-{cd.group(2)}-{cd.group(3)}' if cd else ''
lines, vacant, sec, titles = [], collections.Counter(), None, []
for pg in doc:
    for tb in pg.find_tables().tables:
        for r in tb.extract():
            c = [clean(x) for x in r]
            if c[0].startswith('COMMON ALLOTMENT- DIRECT'):
                sec = 'direct'; titles.append(c[0]); continue
            if c[0].startswith('COMMON ALLOTMENT- INSERVICE'):
                sec = 'inservice'; titles.append(c[0]); continue
            if c[0].startswith('SEATS LYING VACANT'):
                sec = 'vacant'; titles.append(c[0]); continue
            if c[0] == 'State Application No':
                if c != HEAD:
                    raise SystemExit(f'p{pg.number + 1}: column headings changed')
                continue
            if c[0] == 'Type of Seat':
                if c[:6] != VAC_HEAD:
                    raise SystemExit(f'p{pg.number + 1}: vacancy headings changed')
                continue
            if sec == 'vacant':
                if c[0] not in ('DIRECT', 'INSERVICE') or not c[2].isdigit():
                    raise SystemExit(f'p{pg.number + 1}: unexpected vacancy line')
                vacant[f'{c[0]} {c[3]}'] += int(c[2]); continue
            if sec not in ('direct', 'inservice') or not c[0].isdigit() or len(c) != len(HEAD):
                raise SystemExit(f'p{pg.number + 1}: unexpected line in {sec}')
            c[0] = c[1] = ''                                   # application no + name — never kept
            lines.append((sec, c))
if titles != ['COMMON ALLOTMENT- DIRECT CANDIDATES (MD/MS)-2026-27', 'COMMON ALLOTMENT- INSERVICE CANDIDATES (MD/MS/DNB)-2026-27',
              'SEATS LYING VACANT AFTER ROUND-1 ALLOTMENT']:
    raise SystemExit(f'section titles changed: {titles}')

merit = {'direct': {r['state_rank']: r['air'] for r in json.load(open(M_DIRECT))['rows']},
         'inservice': {r['state_rank']: r['air'] for r in json.load(open(M_INSERVICE))['rows']}}
sm = None
if '--seat-matrix' in opt:
    sm = collections.Counter()
    for x in json.load(open(opt['--seat-matrix']))['rows']:
        sm[(x['college_name'], x['course_name'], x['quota'])] += x['seats']

rows, ver, over = [], collections.Counter(), collections.Counter()
for n, (sec, c) in enumerate(lines, 1):
    rank_raw, inst_raw, course_raw, subj, cat_raw = c[2], c[4], c[5], c[6], c[7]
    if inst_raw not in COLLEGES:
        raise SystemExit(f'unknown college {inst_raw!r}')
    college, mgt = COLLEGES[inst_raw]
    if course_raw == 'MD/MS' and subj in MDMS:
        course, section = MDMS[subj], 'mdms'
    elif course_raw == 'DNB' and subj in DNB and sec == 'inservice':
        course, section = DNB[subj], 'dnb'
    else:
        raise SystemExit(f'unknown course {course_raw!r} / {subj!r} in {sec}')
    if section == 'dnb':
        quota = 'DNB Quota'
    elif mgt:
        quota = 'Management Quota' if sec == 'direct' else 'Management Quota-Inservice'
    else:
        quota = 'Government Quota' if sec == 'direct' else 'Government Quota-Inservice'
    m = re.fullmatch(r'(A?)(\d+)', rank_raw)
    if not m:
        raise SystemExit(f'line {n}: rank {rank_raw!r}')
    rank, after = int(m.group(2)), bool(m.group(1))
    ai = None if after else merit[sec].get(rank)
    ver['AIR from the merit list' if ai else ('added after rank (no AIR)' if after else 'AIR NOT FOUND')] += 1
    if sm is not None:
        over[(college, course, SM_QUOTA[quota])] += 1
    rows.append({'sno': n, 'rank': rank, 'rank_ai': ai, 'quota_raw': ('In-service' if sec == 'inservice' else 'Direct')
                 + (' · Management' if mgt else ''), 'quota': quota, 'institute_raw': inst_raw, 'institute': college,
                 'course_raw': f'{course_raw} {subj}', 'course': course, 'section': section,
                 'allotted_category': category(cat_raw), 'allotted_category_raw': cat_raw, 'candidate_category': '',
                 'remarks': (f'Rank printed {rank_raw} (added after rank {rank}). ' if after else '')
                 + f'Choice no. {c[3]}'})
if ver.get('AIR NOT FOUND'):
    raise SystemExit(f'ranks not in the merit list: {dict(ver)}')
for sec in ('direct', 'inservice'):
    rk = [x['rank'] for x in rows if x['quota_raw'].startswith('Direct' if sec == 'direct' else 'In-service')]
    if len(rk) != len(set(rk)):
        raise SystemExit(f'{sec}: a CMR-UR rank appears twice')
if sm is not None:
    bad = {k: v for k, v in over.items() if v > sm.get(k, 0)}
    if bad:
        raise SystemExit(f'more allotted than seat-matrix seats: {bad}')

C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'allotted': len(rows), 'by_list': dict(collections.Counter(s for s, _ in lines)), 'verification': dict(ver),
          'vacant_after_round': dict(vacant), 'by_quota': C('quota'), 'by_section': C('section'),
          'by_institute': C('institute'), 'by_allotted_category': C('allotted_category'),
          'seat_matrix_checked': sm is not None}
out = {'authority_code': 'ojee', 'round': opt['--round'], 'round_order': int(opt['--round-order']),
       'status': opt['--status'],
       'title': f'Common Allotment — {opt["--round"]}, State Quota PG Medical (Direct + In-service, MD/MS/DNB), Odisha',
       'published_on': published, 'source_file_name': os.path.basename(PDF),
       'notes': ('Odisha PG Medical Counselling Committee, state quota. rank = CMR-UR (common merit rank), rank_ai = NEET '
                 'PG AIR from the revised Odisha merit list of the same kind (direct / in-service). -MGT colleges = '
                 'management seats. Application numbers and names never kept.'),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['status'], out['published_on'])
for k, v in checks.items():
    if k not in ('by_institute',):
        print(k, v)
