"""Rajasthan NEET PG Counselling Board (RUHS / SMS Medical College) seat allotment result (indicative / provisional /
final, any round) → rows for POST /api/pg/results/ingest. One official PDF: a few notice pages, then one line per
ALLOTTED candidate (S. No., Reg ID, NEET Roll No, Candidate Name, Gender, Domicile, Allotted Category, Additional
Category (Filled), Allotted College (Seat Type), Allotted Course, Service Status, State Merit Rank, All India Rank).
Reg ID, roll number, name, gender and domicile are never kept (the roll number is used in memory only, to check the
printed All-India rank against the NBEMS master). Quota = seat type in brackets after the college + service status,
category = allotted category, both in the 2025 Rajasthan cut-off spellings. College names are matched on the portal
through the name memory. `rank` = State Merit Rank (what My Allotments matches a doctor's home-state rank against),
`rank_ai` = the printed All India Rank (the 2025 Rajasthan cut-offs hold All-India ranks).
Run with /usr/bin/python3 (PyMuPDF):
    rajasthan.py <allotment.pdf> <out.json> [--merit <ruhs_state_merit.json>] [--nbems <neet2026.json>]
               [--round "Round 1"] [--round-order 1] [--status provisional|final] [--published-on YYYY-MM-DD]
--merit: the loaded RUHS state merit list (rows with state_rank / air) — every (state rank, AI rank) pair must be in it.
--nbems: the NBEMS NEET-PG master (rows with roll / air) — every printed AI rank must equal the NBEMS one for the roll."""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {}
for k in ('--merit', '--nbems', '--round', '--round-order', '--status', '--published-on'):
    if k in args:
        i = args.index(k); opt[k] = args[i + 1]; del args[i:i + 2]
if len(args) != 2:
    raise SystemExit(__doc__)
PDF, OUT = args
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

HEAD = ['S. No.', 'Reg ID', 'NEET Roll No', 'Candidate Name', 'Gender', 'Domicile', 'Allotted Category',
        'Additional Category (Filled)', 'Allotted College (Seat Type)', 'Allotted Course', 'Service Status',
        'State Merit Rank', 'All India Rank']
# (seat type, service status, course kind) → 2025 Rajasthan cut-off quota. 2025: Government / State / All India /
# Management Quota × In Service / Non Service, Post-MBBS diplomas = 'Diploma Quota-In Service' (printed seat type
# 'Government'). Post-MBBS DNB (in-service, new in 2026) follows the diploma pattern. Anything else stops the run.
QUOTA = {}
for seat, q in (('Government', 'Government Quota'), ('State', 'State Quota'), ('AI', 'All India Quota'),
                ('Management', 'Management Quota')):
    QUOTA[(seat, 'Non-Service', 'mdms')] = q + '-Non Service'
    QUOTA[(seat, 'In-Service', 'mdms')] = q + '-In Service'
QUOTA[('Government', 'In-Service', 'diploma')] = 'Diploma Quota-In Service'
QUOTA[('Government', 'In-Service', 'dnb')] = 'DNB Quota-In Service'
CATEGORY = {'General': 'GEN', 'OBC NCL': 'OBC-NCL', 'MBC NCL': 'MBC-NCL', 'SC': 'SC', 'ST': 'ST', 'EWS': 'EWS'}
ADDITIONAL = {'-': '', 'STA': 'STA', 'PwBD': 'PwBD'}      # "Additional Category (Filled)" — the candidate's claim
# Lines whose college cell is printed WITHOUT the "(Seat Type)" suffix — hand-checked, keyed by S.No + college +
# course so a changed file stops instead of guessing. 2026 R1 S.No 1297: private college, non-Rajasthan domicile,
# General / Non-Service, AI rank right after the college's previous AI-seat Radio-Diagnosis allotment → AI.
SEAT_MISSING = {(1297, 'Jaipur National University Institute of Medical Sciences and Research Centre, Jaipur',
                 'MD (Radio-Diagnosis/ Radiology)'): 'AI'}
COURSES = {  # printed course → approved course name (pg_admin/data/specialty_sheet.json)
    'MD (Anaesthesiology)': 'MD - Anaesthesiology', 'MD (Anatomy)': 'MD/MS - Anatomy', 'MS (Anatomy)': 'MD/MS - Anatomy',
    'MD (Biochemistry)': 'MD - Biochemistry', 'MD (Emergency Medicine)': 'MD - Emergency Medicine',
    'MD (Family Medicine)': 'MD - Family Medicine', 'MD (Forensic Medicine)': 'MD - Forensic Medicine',
    'MD (General Medicine)': 'MD - General Medicine', 'MD (Geriatrics/Geriatric Medicine)': 'MD - Geriatrics',
    'MD (Hospital Administration)': 'MD - Hospital Administration',
    'MD (Immunohaematology & Blood Transfusion/ Transfusion Medicine)': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'MD (Laboratory Medicine)': 'MD - Laboratory Medicine',
    'MD (Microbiology)': 'MD - Microbiology', 'MD (Nuclear Medicine)': 'MD - Nuclear Medicine',
    'MD (Paediatrics)': 'MD - Paediatrics', 'MD (Palliative Medicine)': 'MD - Palliative Medicine',
    'MD (Pathology)': 'MD - Pathology', 'MD (Pharmacology)': 'MD - Pharmacology',
    'MD (Physical Med. & Rehabilitation)': 'MD - Physical Medicine and Rehabilitation',
    'MD (Physiology)': 'MD - Physiology',
    'MD (Preventive & Social Medicine (PSM)/ Community Medicine)': 'MD - Social & Preventive Medicine / Community Medicine',
    'MD (Psychiatry)': 'MD - Psychiatry', 'MD (Radio-Diagnosis/ Radiology)': 'MD - Radio-Diagnosis',
    'MD (Radiotherapy/ Radiation Oncology)': 'MD - Radiotherapy / Radiation Oncology',
    'MD (Respiratory Medicine/T.B. & Chest/Tuberculosis & Respiratory Diseases)': 'MD - Respiratory Medicine',
    'MD (Skin & V.D / Dermatology Ven. & Leprosy)': 'MD - Dermatology', 'MD (Tropical Medicine)': 'MD - Tropical Medicine',
    'MS (E.N.T./ Otorhinolaryngology)': 'MS - ENT (Otorhinolaryngology)', 'MS (General Surgery)': 'MS - General Surgery',
    'MS (Obstetrics & Gynaecology)': 'MS - Obstetrics and Gynaecology', 'MS (Ophthalmology)': 'MS - Ophthalmology',
    'MS (Orthopaedics)': 'MS - Orthopaedics', 'MS (Traumatology and Surgery)': 'MS - Traumatology and Surgery',
    # Post-MBBS (NBEMS) diplomas at district hospitals — the 2025 Rajasthan cut-off / seat-matrix names
    'Post MBBS Diploma (Anaesthesia)': 'Diploma in Anaesthesiology',
    'Post MBBS Diploma (Paediatrics)': 'Diploma in Child Health / Paediatrics', 'Post MBBS Diploma (ENT)': 'Diploma in ENT',
    'Post MBBS Diploma (Family Medicine)': 'Diploma in Family Medicine',
    'Post MBBS Diploma (Obs & Gyne)': 'Diploma in Obstetrics and Gynaecology',
    'Post MBBS Diploma (Ophthalmology)': 'Diploma in Ophthalmology',
    'Post MBBS Diploma (Radio Diagnosis)': 'Diploma in Radio Diagnosis',
    'Post MBBS Diploma (TB & Chest)': 'Diploma in Respiratory Medicine',
    # Post-MBBS DNB — the seat-matrix names (tools/seat_matrix/rajasthan.py)
    'Post MBBS DNB (Emergency Medicine)': 'DNB - Emergency Medicine (Post-MBBS)',
    'Post MBBS DNB (Family Medicine)': 'DNB - Family Medicine (Post-MBBS)'}


def section(course):
    if course.startswith(('MD (', 'MS (')):
        return 'mdms'
    if course.startswith('Post MBBS Diploma ('):
        return 'diploma'
    if course.startswith('Post MBBS DNB ('):
        return 'dnb'
    return None


clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()


def num(s, what):
    if not re.fullmatch(r'\d+', s):
        raise SystemExit(f'{what} is not a number: {s!r}')
    return int(s)


doc = fitz.open(PDF)
# ── title / date / round from the notice ──
notice = clean(' '.join(doc[i].get_text() for i in range(min(5, len(doc)))))
m_date = re.search(r'Dated:\s*(\d{2})\.(\d{2})\.(\d{4})', notice)
m_title = re.search(r'((?:INDICATIVE|PROVISIONAL|FINAL)[A-Z &]*ROUND\s*(\d+)\s*SEAT ALLOTMENT RESULT)', notice)
if not m_title:
    raise SystemExit('no "… ROUND n SEAT ALLOTMENT RESULT" title on the notice pages')
rnd_no = int(m_title.group(2))
status = opt.get('--status') or ('final' if m_title.group(1).startswith('FINAL') else 'provisional')
published = opt.get('--published-on') or (f'{m_date.group(3)}-{m_date.group(2)}-{m_date.group(1)}' if m_date else '')

# ── allotment lines; personal columns dropped as each line is read ──
lines, rolls, per_page = [], {}, collections.Counter()
for pg in doc:
    for t in pg.find_tables().tables:
        for r in t.extract():
            if len(r) != len(HEAD):
                raise SystemExit(f'p{pg.number + 1}: a table line has {len(r)} columns')
            r = [clean(x) for x in r]
            if r[0] == HEAD[0]:
                if r != HEAD:
                    raise SystemExit(f'p{pg.number + 1}: column headings changed: {r}')
                continue
            if not r[0].isdigit():
                raise SystemExit(f'p{pg.number + 1}: a line without a serial number')
            rolls[int(r[0])] = r[2]                     # in memory only (AI-rank check), never written
            r[1] = r[2] = r[3] = r[4] = r[5] = ''       # Reg ID, roll, name, gender, domicile
            lines.append(r)
            per_page[pg.number + 1] += 1
sn = sorted(int(r[0]) for r in lines)
if sn != list(range(1, len(sn) + 1)):
    raise SystemExit(f'serial numbers are not 1..{len(sn)} — lines missing or read twice')

approved = {c['course'] for c in json.load(open(SHEET))['courses']}
rows, unknown, inferred = [], collections.Counter(), []
for r in lines:
    sno, _, _, _, _, _, acat, addl, college, course, service, smr, air = r
    sno = int(sno)
    m = re.fullmatch(r'(.*\S)\s*\((Government|State|AI|Management)\)', college)
    if m:
        inst, seat = m.groups()
    elif (sno, college, course) in SEAT_MISSING:
        inst, seat = college, SEAT_MISSING[(sno, college, course)]
        inferred.append({'sno': sno, 'seat_type': seat})
    else:
        unknown[f'seat type not printed: S.No {sno}'] += 1; continue
    sec = section(course)
    if course not in COURSES or not sec:
        unknown['course: ' + course] += 1; continue
    if (seat, service, sec) not in QUOTA:
        unknown[f'quota: {seat} + {service} + {sec}'] += 1; continue
    if acat not in CATEGORY:
        unknown['category: ' + acat] += 1; continue
    if addl not in ADDITIONAL:
        unknown['additional category: ' + addl] += 1; continue
    std = COURSES[course]
    if sec != 'dnb' and std not in approved:
        raise SystemExit(f'{std!r} is not in specialty_sheet.json')
    if sec == 'mdms' and not (std.startswith(course[:2] + ' - ') or std.startswith('MD/MS - ')):
        raise SystemExit(f'S.No {sno}: {course} mapped to {std}')
    rows.append({'sno': sno, 'rank': num(smr, f'S.No {sno} state rank'), 'rank_ai': num(air, f'S.No {sno} AI rank'),
                 'quota_raw': f'{seat} ({service})' if m else f'(seat type not printed; {seat} inferred) ({service})',
                 'quota': QUOTA[(seat, service, sec)], 'institute_raw': inst, 'course_raw': course, 'course': std,
                 'section': sec, 'allotted_category': CATEGORY[acat], 'allotted_category_raw': acat,
                 'candidate_category': ADDITIONAL[addl], 'remarks': service})
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
if len(rows) != len(lines):
    raise SystemExit('rows ≠ lines')

# ── 2025 spellings: every quota / category must exist in the 2025 Rajasthan cut-offs (new: DNB quota) ──
SP2025 = {'quota': ['All India Quota-In Service', 'All India Quota-Non Service', 'Diploma Quota-In Service',
                    'Government Quota-In Service', 'Government Quota-Non Service', 'Government Quota-Sr. Demonstrator',
                    'Management Quota-In Service', 'Management Quota-Non Service', 'State Quota-In Service',
                    'State Quota-Non Service'],
          'category': ['EWS', 'GEN', 'MBC-NCL', 'OBC-NCL', 'SC', 'ST']}
not_2025 = {f: sorted({x[f] for x in rows} - set(SP2025[k])) for f, k in (('quota', 'quota'), ('allotted_category', 'category'))}

# ── AI-rank checks (optional inputs) ──
rank_checks = {'rank_ai_source': 'printed All India Rank column', 'printed': len(rows)}
if '--merit' in opt:
    mr = json.load(open(opt['--merit']))
    by_sr = collections.defaultdict(set)
    for x in mr['rows']:
        by_sr[x['state_rank']].add(x['air'])
    miss = [x['sno'] for x in rows if x['rank'] not in by_sr]
    diff = [x['sno'] for x in rows if x['rank'] in by_sr and x['rank_ai'] not in by_sr[x['rank']]]
    rank_checks['state_merit_list'] = {'file': os.path.basename(opt['--merit']), 'state_rank_found': len(rows) - len(miss),
                                       'state_rank_not_found_snos': miss, 'ai_rank_differs_snos': diff}
if '--nbems' in opt:
    nb = {str(x['roll']).strip(): x['air'] for x in json.load(open(opt['--nbems']))}
    miss = [x['sno'] for x in rows if rolls[x['sno']] not in nb]
    diff = [x['sno'] for x in rows if rolls[x['sno']] in nb and nb[rolls[x['sno']]] != x['rank_ai']]
    rank_checks['nbems_by_roll'] = {'roll_found': len(rows) - len(miss), 'roll_not_found_snos': miss,
                                    'ai_rank_differs_snos': diff}
rolls.clear()

rows.sort(key=lambda x: x['sno'])
C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'lines': len(lines), 'sno_1_to_n': True, 'lines_per_page': dict(per_page), 'allotted': len(rows),
          'not_allotted_lines': 0, 'by_section': C('section'), 'by_quota': C('quota'), 'by_quota_raw': C('quota_raw'),
          'by_allotted_category': C('allotted_category'), 'by_candidate_category': C('candidate_category'),
          'by_course': C('course'), 'seat_type_inferred': inferred, 'not_in_2025_spellings': not_2025,
          'colleges': len({x['institute_raw'] for x in rows}),
          'state_rank': [min(x['rank'] for x in rows), max(x['rank'] for x in rows)],
          'ai_rank': [min(x['rank_ai'] for x in rows), max(x['rank_ai'] for x in rows)], 'rank_ai': rank_checks}
title = m_title.group(1).title()
out = {'authority_code': 'ruhs', 'round': opt.get('--round') or f'Round {rnd_no}',
       'round_order': int(opt.get('--round-order') or rnd_no), 'status': status,
       'title': f'Rajasthan NEET PG Counselling 2026 — {title}', 'published_on': published,
       'source_file_name': os.path.basename(PDF),
       'notes': ('One line per allotted candidate (no not-allotted lines are printed). rank = State Merit Rank, '
                 'rank_ai = printed All India Rank. quota = seat type + service status (2025 spellings); '
                 'candidate_category = "Additional Category (Filled)" (STA / PwBD) — the candidate\'s claim, not the '
                 'seat category.' + (f' Seat type not printed for S.No {", ".join(str(i["sno"]) for i in inferred)}'
                                    f' — inferred (see checks.seat_type_inferred).' if inferred else '')),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['round'], out['status'], out['published_on'])
print('lines', len(lines), '| allotted', len(rows), '| pages', min(per_page), '-', max(per_page))
print('by section', checks['by_section'])
print('by quota', checks['by_quota'])
print('by allotted category', checks['by_allotted_category'], '| candidate (additional)', checks['by_candidate_category'])
print('seat type inferred', inferred, '| not in 2025 spellings', not_2025)
print('colleges', checks['colleges'], '| state ranks', checks['state_rank'], '| AI ranks', checks['ai_rank'])
print('rank_ai', json.dumps({k: ({kk: (vv if not isinstance(vv, list) else f'{len(vv)} snos {vv[:10]}') for kk, vv in v.items()}
                                 if isinstance(v, dict) else v) for k, v in rank_checks.items()}))
