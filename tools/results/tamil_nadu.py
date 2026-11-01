"""Tamil Nadu (DMER / Selection Committee) PG Medical allotment list → rows for POST /api/pg/results/ingest.
Reads the "Post Graduate Medical (Government Quota PWD Category) … Provisional List of Candidates allotted on …"
PDF: one line per ALLOTTED candidate — SNO, GRANK, ARNO, NAME, COMMUNITY, SERVICE, T.MARK, ALLOTTED TO
("<quota> - <course>" then the college on the next line). ARNO (application number) and NAME are never kept.
`rank` = GRANK (the Government Quota rank — what My Allotments matches a doctor's home-state rank against);
`rank_ai` is not printed: it is looked up by GRANK in the loaded TN GQ merit list (--bridge, rows with state_rank /
air / score / category). Addendum 'nA' ranks are stored there as rank n, so a GRANK can have two merit-list
lines — the one with the same COMMUNITY and T.MARK (= merit-list total marks) is taken; zero or two matches stop.
The PwD list prints no seat category: allotted_category = 'PwD' (allotted_category_raw empty), candidate_category =
COMMUNITY + ' PwD'. Quota: GQ → Government Quota (2025 TN spelling). College names are matched on the portal
through the name memory. NB the 2025 TN cut-offs hold TN merit ranks (GRANK), not All-India ranks.
Run with /usr/bin/python3 (PyMuPDF):
    tamil_nadu.py <pwd_allotment.pdf> <out.json> --bridge <dmer_tn_gq.json>
                  [--round "Round 1 (PwD)"] [--round-order 1] [--status provisional|final] [--published-on YYYY-MM-DD]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {}
for k in ('--bridge', '--round', '--round-order', '--status', '--published-on'):
    if k in args:
        i = args.index(k); opt[k] = args[i + 1]; del args[i:i + 2]
if len(args) != 2 or '--bridge' not in opt:
    raise SystemExit(__doc__)
PDF, OUT = args
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

HEAD = 'SNO GRANK ARNO NAME COMMUNITY SERVICE T.MARK ALLOTTED TO'
QUOTA = {'GQ': 'Government Quota'}
COMMUNITY = {'OC', 'BC', 'BCM', 'MBC&DNC', 'SC', 'SCA', 'ST'}     # 2025 TN Government Quota spellings
SERVICE = {'': '', 'Service': 'Service'}
COURSES = {  # printed course (white space removed) → (approved course, section) — same wording as tools/seat_matrix/tamil_nadu.py
    'M.S.Otorhinolaryngology': ('MS - ENT (Otorhinolaryngology)', 'mdms'), 'M.S.Orthopaedics': ('MS - Orthopaedics', 'mdms'),
    'M.S.Ophthalmology': ('MS - Ophthalmology', 'mdms'),
    'M.S.ObstetricsandGynaecology': ('MS - Obstetrics and Gynaecology', 'mdms'),
    'M.S.GeneralSurgery': ('MS - General Surgery', 'mdms'), 'M.D.RespiratoryMedicine': ('MD - Respiratory Medicine', 'mdms'),
    'M.D.RadioDiagnosis': ('MD - Radio-Diagnosis', 'mdms'),
    'M.D.RadiationOncology': ('MD - Radiotherapy / Radiation Oncology', 'mdms'),
    'M.D.PsychiatricMedicine': ('MD - Psychiatry', 'mdms'), 'M.D.Physiology': ('MD - Physiology', 'mdms'),
    'M.D.Pharmacology': ('MD - Pharmacology', 'mdms'), 'M.D.Pathology': ('MD - Pathology', 'mdms'),
    'M.D.Paediatrics': ('MD - Paediatrics', 'mdms'), 'M.D.Microbiology': ('MD - Microbiology', 'mdms'),
    'M.D.ImmunoHaematologyandTransfusionMedicine':
        ('MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'mdms'),
    'M.D.GeneralMedicine': ('MD - General Medicine', 'mdms'), 'M.D.ForensicMedicine': ('MD - Forensic Medicine', 'mdms'),
    'M.D.EmergencyMedicine': ('MD - Emergency Medicine', 'mdms'), 'M.D.D.V.L': ('MD - Dermatology', 'mdms'),
    'M.D.CommunityMedicine': ('MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    'M.D.Biochemistry': ('MD - Biochemistry', 'mdms'), 'M.D.Anatomy': ('MD/MS - Anatomy', 'mdms'),
    'M.D.Anaesthesiology': ('MD - Anaesthesiology', 'mdms'), 'M.D.NuclearMedicine': ('MD - Nuclear Medicine', 'mdms'),
    'M.D.Geriatrics': ('MD - Geriatrics', 'mdms'), 'M.D.FamilyMedicine': ('MD - Family Medicine', 'mdms'),
    'M.D.(P.M.R)': ('MD - Physical Medicine and Rehabilitation', 'mdms'),
    'D.A.': ('Diploma in Anaesthesiology', 'diploma'), 'D.C.H.': ('Diploma in Child Health / Paediatrics', 'diploma'),
    'D.C.P.': ('Diploma in Pathology', 'diploma'), 'D.D.V.L.': ('Diploma in Dermatology', 'diploma'),
    'D.G.O': ('Diploma in Obstetrics and Gynaecology', 'diploma'), 'D.O.': ('Diploma in Ophthalmology', 'diploma'),
    'D.ORTHO': ('Diploma in Orthopaedics', 'diploma'), 'Dip.inDiabetology': ('Diploma in Diabetology', 'diploma')}

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()


def num(s, what):
    if not re.fullmatch(r'\d+', s):
        raise SystemExit(f'{what} is not a number: {s!r}')
    return int(s)


doc = fitz.open(PDF)
top = clean(doc[0].get_text())
m_t = re.search(r'Post Graduate Medical\s*\((.*?)\)\s*Course Session\s*:?\s*(\d{4}\s*-\s*\d{4})', top)
m_d = re.search(r'(Provisional|Final) List of Candidates allotted on\s*-\s*(\d{2})\.(\d{2})\.(\d{4})', top)
if not m_t or not m_d:
    raise SystemExit('title / "List of Candidates allotted on" line not found')
status = opt.get('--status') or m_d.group(1).lower()
published = opt.get('--published-on') or f'{m_d.group(4)}-{m_d.group(3)}-{m_d.group(2)}'
title = f'Post Graduate Medical ({clean(m_t.group(1))}) {m_t.group(2)} — {m_d.group(1)} List of Candidates allotted'

lines = []
for pg in doc:
    tabs = pg.find_tables().tables
    if len(tabs) != 1:
        raise SystemExit(f'p{pg.number + 1}: {len(tabs)} tables')
    for r in tabs[0].extract():
        if len(r) != 8:
            raise SystemExit(f'p{pg.number + 1}: a table line has {len(r)} columns')
        c0 = clean(r[0])
        if c0.startswith('SNO'):
            if clean(' '.join(x or '' for x in r)) != HEAD:
                raise SystemExit(f'p{pg.number + 1}: column headings changed: {c0}')
            continue
        if not c0.isdigit():
            raise SystemExit(f'p{pg.number + 1}: a line without a serial number')
        allot = (r[7] or '').split('\n', 1)
        if len(allot) != 2:
            raise SystemExit(f'SNO {c0}: ALLOTTED TO is not "<quota> - <course>" + college')
        lines.append([c0, clean(r[1]), clean(r[4]), clean(r[5]), clean(r[6]), clean(allot[0]), clean(allot[1])])
        # r[2] ARNO and r[3] NAME are not read
sn = [int(x[0]) for x in lines]
if sn != list(range(1, len(sn) + 1)):
    raise SystemExit(f'serial numbers are not 1..{len(sn)} in order')
grank_order_breaks = [int(b[0]) for a, b in zip(lines, lines[1:]) if int(a[1]) > int(b[1])]

br = json.load(open(opt['--bridge']))
by_rank = collections.defaultdict(list)
for x in br['rows']:
    by_rank[x['state_rank']].append(x)

approved = {c['course'] for c in json.load(open(SHEET))['courses']}
rows, unknown, ai_how = [], collections.Counter(), collections.Counter()
for sno, grank, comm, serv, tmark, qc, college in lines:
    sno, grank = int(sno), num(grank, f'SNO {sno} GRANK')
    m = re.fullmatch(r'(\w+)\s*-\s*(.+)', qc)
    if not m:
        unknown['allotted to: ' + qc] += 1; continue
    q, course_raw = m.groups()
    if q not in QUOTA:
        unknown['quota: ' + q] += 1; continue
    ck = re.sub(r'\s+', '', course_raw)
    if ck not in COURSES:
        unknown['course: ' + course_raw] += 1; continue
    if comm not in COMMUNITY:
        unknown['community: ' + comm] += 1; continue
    if serv not in SERVICE:
        unknown['service: ' + serv] += 1; continue
    if not re.fullmatch(r'\d+(\.\d+)?', tmark):
        unknown['T.MARK: ' + tmark] += 1; continue
    std, sec = COURSES[ck]
    if std not in approved:
        raise SystemExit(f'{std!r} is not in specialty_sheet.json')
    cand = by_rank.get(grank, [])
    hit = [x for x in cand if x['category'] == comm and abs(float(x['score']) - float(tmark)) < 0.005]
    if len(hit) != 1:
        raise SystemExit(f'SNO {sno}: GRANK {grank} has {len(cand)} merit-list lines, {len(hit)} with the same '
                         f'community + total marks')
    ai_how['unique GRANK' if len(cand) == 1 else 'tie GRANK (nA) — community + T.MARK'] += 1
    rows.append({'sno': sno, 'rank': grank, 'rank_ai': int(hit[0]['air']), 'quota_raw': q, 'quota': QUOTA[q],
                 'institute_raw': college, 'course_raw': course_raw, 'course': std, 'section': sec,
                 'allotted_category': 'PwD', 'allotted_category_raw': '', 'candidate_category': f'{comm} PwD',
                 'remarks': SERVICE[serv]})
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
if len(rows) != len(lines):
    raise SystemExit('rows ≠ lines')

C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'lines': len(lines), 'sno_1_to_n': True, 'grank_order_breaks': grank_order_breaks, 'allotted': len(rows),
          'not_allotted_lines': 0, 'by_section': C('section'), 'by_quota': C('quota'),
          'by_candidate_category': C('candidate_category'), 'by_remarks': C('remarks'), 'by_course': C('course'),
          'colleges': len({x['institute_raw'] for x in rows}),
          'rank_ai': {'source': f'TN GQ merit list by GRANK ({os.path.basename(opt["--bridge"])}; '
                                f'community + total marks must agree)', 'filled': len(rows), 'not_filled': 0,
                      'how': dict(ai_how)},
          'state_rank': [min(x['rank'] for x in rows), max(x['rank'] for x in rows)],
          'ai_rank': [min(x['rank_ai'] for x in rows), max(x['rank_ai'] for x in rows)]}
out = {'authority_code': 'dmer_tn', 'round': opt.get('--round') or 'Round 1 (PwD)',
       'round_order': int(opt.get('--round-order') or 1), 'status': status, 'title': title, 'published_on': published,
       'source_file_name': os.path.basename(PDF),
       'notes': ('Government Quota PwD-category allotments only, kept as their own round so the main Round 1 list '
                 'does not replace them. rank = GRANK; rank_ai not printed — from the TN GQ merit list by GRANK '
                 '(community + total marks checked). Seat category not printed: allotted_category = PwD, '
                 'candidate_category = community + PwD; remarks = Service for in-service candidates.'),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['round'], out['status'], out['published_on'])
print('lines', len(lines), '| allotted', len(rows), '| GRANK order breaks', grank_order_breaks)
print('by course', checks['by_course'])
print('by candidate category', checks['by_candidate_category'], '| service', checks['by_remarks'])
print('colleges', checks['colleges'], '| rank_ai', checks['rank_ai']['how'], '| GRANK', checks['state_rank'],
      '| AI', checks['ai_rank'])
