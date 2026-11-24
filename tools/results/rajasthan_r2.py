"""Rajasthan NEET PG Counselling Board (RUHS / SMS Medical College) — Round 2+ seat allotment result (indicative /
provisional / final) → rows for POST /api/pg/results/ingest.

The Round 2 PDF (23.11.2026) is not the Round 1 layout: 18 columns per allotted candidate —
S. No., Reg ID, NEET Roll No, Candidate Name, Gender, Domicile, Provisional Considered Category, Additional Category
(Filled), Allotted Category, R2 Allotted College (Seat Type), R2 Allotted Course, Remark, Service Status, State Merit
Rank, All India Rank, R1 Allotted College (Seat Type), R1 Allotted Course, R1 Joining Status.
Reg ID, roll, name, gender and domicile are dropped as each line is read (the domicile is held in memory only, to rule
out a State seat for a non-Rajasthan candidate when the seat type is not printed; the roll is never used).

Remark → round_status:
  'Fresh Allotment in Round 2'                              → fresh
  'Upgraded'                                                → upgraded (prev_* = the Round 1 seat)
  'Filled choice not promoted' / 'Retained R1 Seat' / 'Did not opt for upgradation' → retained (the line prints the kept Round 1 seat)
Quota / category / course spellings are the Round 1 reader's (tools/results/rajasthan.py, read from its source).

Seat type not printed: long college names are clipped in the PDF cell, so "(Seat Type)" is lost (and the name may be
cut short — completed from the Round 1 result's full name when exactly one Round 1 name starts with it). Then:
  1. retained, or the same college + course as the candidate's Round 1 seat → the Round 1 result's quota (by AI rank);
  2. upgraded inside the same college + course (a quota change) → the one other quota the candidate can hold;
  3. otherwise the one quota of that college + course in the Round 2 seat matrix that still has a free seat after
     the printed lines (State ruled out for non-Rajasthan domicile);
  4. still more than one → quota left blank, quota_raw says which quotas it can be (never guessed).
Every inference is listed in checks.seat_type_inferred / seat_type_unresolved.

    rajasthan_r2.py <allotment.pdf> <round1_rows.json> <out.json> [--matrix <round2_matrix.json>]
                    [--merit <ruhs_state_merit.json>] [--round "Round 2"] [--round-order 2]
                    [--status provisional|final] [--published-on YYYY-MM-DD]
round1_rows.json = tools/results/rajasthan.py output for the Round 1 result. --matrix = the Round 2 seat-matrix
rows ({rows:[{college_name, course_name, quota, seats}]}). --merit = the RUHS state merit list rows
(state_rank / air): every (state rank, AI rank) pair must be in it.
Run with /usr/bin/python3 (PyMuPDF)."""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {}
for k in ('--matrix', '--merit', '--round', '--round-order', '--status', '--published-on'):
    if k in args:
        i = args.index(k); opt[k] = args[i + 1]; del args[i:i + 2]
if len(args) != 3:
    raise SystemExit(__doc__)
PDF, R1, OUT = args
HERE = os.path.dirname(os.path.abspath(__file__))
SHEET = os.path.join(HERE, '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

# ── maps from the Round 1 reader (QUOTA, CATEGORY, ADDITIONAL, COURSES) ──
_src = open(os.path.join(HERE, 'rajasthan.py')).read()
_ns = {}
exec(_src[_src.index('QUOTA = {}'):_src.index('\ndef section')], _ns)
QUOTA, CATEGORY, ADDITIONAL, COURSES = _ns['QUOTA'], _ns['CATEGORY'], _ns['ADDITIONAL'], _ns['COURSES']

HEAD = ['S. No.', 'Reg ID', 'NEET Roll No', 'Candidate Name', 'Gender', 'Domicile', 'Provisional Considered Category',
        'Additional Category (Filled)', 'Allotted Category', 'R2 Allotted College (Seat Type)', 'R2 Allotted Course',
        'Remark', 'Service Status', 'State Merit Rank', 'All India Rank', 'R1 Allotted College (Seat Type)',
        'R1 Allotted Course', 'R1 Joining Status']
REMARK = {'Fresh Allotment in Round 2': 'fresh', 'Upgraded': 'upgraded',
          'Filled choice not promoted': 'retained', 'Did not opt for upgradation': 'retained',
          'Retained R1 Seat': 'retained'}   # provisional 24.11 list's wording for "Filled choice not promoted"
JOIN = {'', 'Joined', 'Not Reported', 'Resigned'}
SEAT_NAME = {'Government': 'Government Quota', 'State': 'State Quota', 'AI': 'All India Quota',
             'Management': 'Management Quota'}
NAME_SEAT = {v: k for k, v in SEAT_NAME.items()}


def section(course):
    if course.startswith(('MD (', 'MS (')):
        return 'mdms'
    if course.startswith('Post MBBS Diploma ('):
        return 'diploma'
    if course.startswith('Post MBBS DNB ('):
        return 'dnb'
    return None


clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()
key = lambda s: re.sub(r'[^a-z]', '', s.lower())


def num(s, what):
    if not re.fullmatch(r'\d+', s):
        raise SystemExit(f'{what} is not a number: {s!r}')
    return int(s)


def split_seat(cell):
    m = re.fullmatch(r'(.*\S)\s*\((Government|State|AI|Management)\)', cell)
    return (m.group(1), m.group(2)) if m else (cell, None)


doc = fitz.open(PDF)
notice = clean(' '.join(doc[i].get_text() for i in range(min(5, len(doc)))))
m_date = re.search(r'Dated:\s*(\d{2})\.(\d{2})\.(\d{4})', notice)
m_title = re.search(r'((?:INDICATIVE|PROVISIONAL|FINAL)[A-Z &]*ROUND\s*(\d+)\s*SEAT ALLOTMENT RESULT)', notice)
if not m_title:
    raise SystemExit('no "… ROUND n SEAT ALLOTMENT RESULT" title on the notice pages')
rnd_no = int(m_title.group(2))
if rnd_no < 2:
    raise SystemExit('this reader is for Round 2+; use rajasthan.py for Round 1')
status = opt.get('--status') or ('final' if m_title.group(1).startswith('FINAL') else 'provisional')
published = opt.get('--published-on') or (f'{m_date.group(3)}-{m_date.group(2)}-{m_date.group(1)}' if m_date else '')

lines, domicile, per_page = [], {}, collections.Counter()
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
            domicile[int(r[0])] = r[5] == 'Rajasthan'      # in memory only, never written
            r[1] = r[2] = r[3] = r[4] = r[5] = ''          # Reg ID, roll, name, gender, domicile
            lines.append(r)
            per_page[pg.number + 1] += 1
sn = sorted(int(r[0]) for r in lines)
if sn != list(range(1, len(sn) + 1)):
    raise SystemExit(f'serial numbers are not 1..{len(sn)} — lines missing or read twice')

r1 = json.load(open(R1))
r1_by_air = collections.defaultdict(list)
for x in r1['rows']:
    r1_by_air[x['rank_ai']].append(x)
r1_names = sorted({x['institute_raw'] for x in r1['rows']})


def full_name(inst):
    """A clipped college name → the one Round 1 name it is the start of (else unchanged)."""
    if inst in r1_names:
        return inst
    hits = [n for n in r1_names if n.startswith(inst.rstrip(', '))]
    return hits[0] if len(hits) == 1 else inst


def full_course(c):
    """A clipped course cell → the one known printed course it is the start of (else unchanged)."""
    if not c or c in COURSES:
        return c
    hits = [k for k in COURSES if k.startswith(c)]
    return hits[0] if len(hits) == 1 else c


approved = {c['course'] for c in json.load(open(SHEET))['courses']}
unknown = collections.Counter()
parsed = []
for r in lines:
    (sno, _, _, _, _, _, pcat, addl, acat, college, course, remark, service, smr, air, r1college, r1course,
     r1join) = r
    sno = int(sno)
    course, r1course = full_course(course), full_course(r1course)
    inst, seat = split_seat(college)
    inst = full_name(inst)
    sec = section(course)
    if course not in COURSES or not sec:
        unknown['course: ' + course] += 1; continue
    if remark not in REMARK:
        unknown['remark: ' + remark] += 1; continue
    if r1join not in JOIN:
        unknown['R1 joining status: ' + r1join] += 1; continue
    if acat not in CATEGORY:
        unknown['category: ' + acat] += 1; continue
    if addl not in ADDITIONAL:
        unknown['additional category: ' + addl] += 1; continue
    if service not in ('In-Service', 'Non-Service'):
        unknown['service: ' + service] += 1; continue
    p_inst, p_seat = split_seat(r1college)
    p_inst = full_name(p_inst) if p_inst else ''
    if r1course and r1course not in COURSES:
        unknown['R1 course: ' + r1course] += 1; continue
    std = COURSES[course]
    if sec != 'dnb' and std not in approved:
        raise SystemExit(f'{std!r} is not in specialty_sheet.json')
    parsed.append(dict(sno=sno, inst=inst, seat=seat, course=course, std=std, sec=sec, rs=REMARK[remark],
                       remark=remark, service=service, rank=num(smr, f'S.No {sno} state rank'),
                       air=num(air, f'S.No {sno} AI rank'), acat=acat, addl=addl, p_inst=p_inst, p_seat=p_seat,
                       p_course=r1course, r1join=r1join))
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')

# ── Round 1 row of the same candidate (by AI rank + printed Round 1 seat) ──
link = collections.Counter()
r1_conflicts = []
for x in parsed:
    x['r1'] = None
    if not x['p_course']:
        continue
    cands = [p for p in r1_by_air.get(x['air'], []) if p['course_raw'] == x['p_course']
             and key(p['institute_raw']) == key(x['p_inst'])]
    if len(cands) == 1:
        x['r1'] = cands[0]; link['found'] += 1
    else:
        link['not_found'] += 1
        if x['rs'] != 'fresh':
            raise SystemExit(f'S.No {x["sno"]}: Round 1 seat not found in {R1} (AI rank {x["air"]})')
    if x['r1'] and x['p_seat'] and NAME_SEAT.get(x['r1']['quota'].split('-')[0]) not in (None, x['p_seat']):
        if not x['r1']['quota'].startswith(('Diploma', 'DNB')):
            # the 24.11 provisional list prints one such line (R1 "Management" vs the Round 1 result's All India
            # seat): the Round 1 RESULT wins as prev_*; listed in checks.r1_seat_type_conflicts, not fatal
            r1_conflicts.append({'sno': x['sno'], 'printed_r1_seat': x['p_seat'], 'round_1_result_quota': x['r1']['quota']})
    if x['rs'] == 'retained' and (x['inst'], x['course']) != (x['p_inst'], x['p_course']):
        raise SystemExit(f'S.No {x["sno"]}: retained but the Round 2 seat ≠ the Round 1 seat')

# ── seat type where it is not printed ──
cap, used = collections.Counter(), collections.Counter()
if '--matrix' in opt:
    for m in json.load(open(opt['--matrix']))['rows']:
        cap[(key(m['college_name'])[:18], m['course_name'], m['quota'])] += m['seats']
for x in parsed:
    if x['seat'] and x['rs'] != 'retained':
        used[(key(x['inst'])[:18], x['std'], SEAT_NAME[x['seat']])] += 1
inferred, unresolved = [], []
QUOTAS = ('State Quota', 'All India Quota', 'Management Quota', 'Government Quota')
pending = []                                  # (line, k, options) still to settle
for x in parsed:                              # pass 1: Round 1 seat, or only one quota possible at all
    x['quota_note'] = ''
    if x['seat']:
        continue
    k = (key(x['inst'])[:18], x['std'])
    same = x['r1'] and (x['inst'], x['course']) == (x['p_inst'], x['p_course'])
    r1seat = NAME_SEAT.get(x['r1']['quota'].split('-')[0]) if x['r1'] else None
    if (x['rs'] == 'retained' or (same and x['rs'] == 'fresh')) and r1seat:
        x['seat'], how = r1seat, 'Round 1 result (same seat)'
    else:
        opts = [q for q in QUOTAS if cap[k + (q,)]]
        if not domicile[x['sno']]:
            opts = [q for q in opts if q != 'State Quota']
        how = 'the only Round 2 matrix quota of this college + course the candidate can hold'
        if same and x['rs'] == 'upgraded' and r1seat:
            opts = [q for q in opts if q != SEAT_NAME[r1seat]]
            how = 'upgraded inside the same college + course: the other quota the candidate can hold'
        if len(opts) != 1:
            pending.append((x, k, opts)); continue
        x['seat'] = NAME_SEAT[opts[0]]
    if x['rs'] != 'retained':
        used[k + (SEAT_NAME[x['seat']],)] += 1
    inferred.append({'sno': x['sno'], 'college': x['inst'], 'course': x['std'], 'seat_type': x['seat'], 'how': how})
# pass 2: one quota still has free seats — only when there are enough of them for every pending line of that group
group = collections.Counter(k for _, k, _ in pending)
for x, k, opts in pending:
    free = [q for q in opts if cap[k + (q,)] > used[k + (q,)]]
    if len(free) == 1 and cap[k + (free[0],)] - used[k + (free[0],)] >= group[k]:
        x['seat'] = NAME_SEAT[free[0]]
        inferred.append({'sno': x['sno'], 'college': x['inst'], 'course': x['std'], 'seat_type': x['seat'],
                         'how': 'the only Round 2 matrix quota with free seats for every unprinted line'})
    else:
        x['quota_note'] = ' or '.join(opts) or 'unknown'
        unresolved.append({'sno': x['sno'], 'college': x['inst'], 'course': x['std'], 'could_be': opts})
del domicile

inf_snos = {i['sno'] for i in inferred}
rows = []
for x in parsed:
    seat, sec = x['seat'], x['sec']
    if seat:
        if (seat, x['service'], sec) not in QUOTA:
            raise SystemExit(f'S.No {x["sno"]}: quota {seat} + {x["service"]} + {sec} not in the map')
        quota = QUOTA[(seat, x['service'], sec)]
        qraw = f'{seat} ({x["service"]})' + (' [seat type not printed; inferred]' if x['sno'] in inf_snos else '')
    else:
        quota, qraw = '', f'(seat type not printed: {x["quota_note"]}) ({x["service"]})'
    raw_status = x['remark'] + (f' (Round 1: {x["r1join"]})' if x['r1join'] and x['rs'] == 'fresh' else '')
    row = {'sno': x['sno'], 'rank': x['rank'], 'rank_ai': x['air'], 'quota_raw': qraw, 'quota': quota,
           'institute_raw': x['inst'], 'course_raw': x['course'], 'course': x['std'], 'section': sec,
           'allotted_category': CATEGORY[x['acat']], 'allotted_category_raw': x['acat'],
           'candidate_category': ADDITIONAL[x['addl']], 'remarks': x['service'],
           'round_status': x['rs'], 'round_status_raw': raw_status}
    if x['rs'] == 'upgraded' and x['r1']:
        p = x['r1']
        row.update({'prev_quota_raw': p['quota_raw'], 'prev_quota': p['quota'], 'prev_institute_raw': p['institute_raw'],
                    'prev_course_raw': p['course_raw'], 'prev_course': p['course'], 'prev_remarks': 'Round 1 seat'})
    rows.append(row)

SP2025 = {'quota': ['All India Quota-In Service', 'All India Quota-Non Service', 'Diploma Quota-In Service',
                    'Government Quota-In Service', 'Government Quota-Non Service', 'Government Quota-Sr. Demonstrator',
                    'Management Quota-In Service', 'Management Quota-Non Service', 'State Quota-In Service',
                    'State Quota-Non Service'],
          'category': ['EWS', 'GEN', 'MBC-NCL', 'OBC-NCL', 'SC', 'ST']}
not_2025 = {'quota': sorted({x['quota'] for x in rows if x['quota']} - set(SP2025['quota'])),
            'allotted_category': sorted({x['allotted_category'] for x in rows} - set(SP2025['category']))}

rank_checks = {'rank_ai_source': 'printed All India Rank column', 'printed': len(rows)}
if '--merit' in opt:
    by_sr = collections.defaultdict(set)
    for x in json.load(open(opt['--merit']))['rows']:
        by_sr[x['state_rank']].add(x['air'])
    miss = [x['sno'] for x in rows if x['rank'] not in by_sr]
    diff = [x['sno'] for x in rows if x['rank'] in by_sr and x['rank_ai'] not in by_sr[x['rank']]]
    rank_checks['state_merit_list'] = {'file': os.path.basename(opt['--merit']), 'state_rank_found': len(rows) - len(miss),
                                       'state_rank_not_found_snos': miss, 'ai_rank_differs_snos': diff}

matrix_check = {}
if '--matrix' in opt:
    got = collections.Counter((key(x['institute_raw'])[:18], x['course'], x['quota'].split('-')[0])
                              for x in rows if x['round_status'] != 'retained' and x['quota'])
    over = {f'{k[0]} | {k[1]} | {k[2]}': (n, cap[k]) for k, n in got.items() if n > cap[k]}
    matrix_check = {'note': 'informational — Round 2 also fills seats vacated during the round',
                    'fresh_upgraded_rows': sum(got.values()), 'matrix_seats': sum(cap.values()),
                    'groups_over_matrix': len(over), 'over_matrix_examples': dict(list(over.items())[:15])}

rows.sort(key=lambda x: x['sno'])
C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'lines': len(lines), 'sno_1_to_n': True, 'lines_per_page': dict(per_page), 'allotted': len(rows),
          'by_round_status': C('round_status'), 'by_round_status_raw': C('round_status_raw'),
          'link_to_round_1': dict(link), 'by_section': C('section'), 'by_quota': C('quota'),
          'by_allotted_category': C('allotted_category'), 'by_candidate_category': C('candidate_category'),
          'by_course': C('course'), 'seat_type_inferred': inferred, 'seat_type_unresolved': unresolved,
          'not_in_2025_spellings': not_2025, 'colleges': len({x['institute_raw'] for x in rows}),
          'state_rank': [min(x['rank'] for x in rows), max(x['rank'] for x in rows)],
          'ai_rank': [min(x['rank_ai'] for x in rows), max(x['rank_ai'] for x in rows)], 'rank_ai': rank_checks,
          'matrix': matrix_check, 'r1_seat_type_conflicts': r1_conflicts}
title = m_title.group(1).title()
out = {'authority_code': 'ruhs', 'round': opt.get('--round') or f'Round {rnd_no}',
       'round_order': int(opt.get('--round-order') or rnd_no), 'status': status,
       'title': f'Rajasthan NEET PG Counselling 2026 — {title}', 'published_on': published,
       'source_file_name': os.path.basename(PDF),
       'notes': ('One line per allotted candidate. round_status from the Remark column (fresh / upgraded / retained = '
                 '"Filled choice not promoted" or "Did not opt for upgradation", which keep the Round 1 seat). '
                 'rank = State Merit Rank, rank_ai = printed All India Rank. quota = seat type + service status '
                 '(2025 spellings). Clipped college cells lose "(Seat Type)": '
                 f'{len(inferred)} inferred (see checks.seat_type_inferred), {len(unresolved)} left blank '
                 '(checks.seat_type_unresolved).'),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['round'], out['status'], out['published_on'])
print('lines', len(lines), '| allotted', len(rows), '| pages', min(per_page), '-', max(per_page))
for k in ('by_round_status', 'by_round_status_raw', 'link_to_round_1', 'by_section', 'by_quota',
          'by_allotted_category', 'by_candidate_category', 'not_in_2025_spellings', 'colleges', 'state_rank', 'ai_rank'):
    print(k, checks[k])
print('seat type inferred', len(inferred))
for i in inferred:
    print('  ', i)
print('seat type unresolved', unresolved)
print('rank_ai', json.dumps({k: ({kk: (vv if not isinstance(vv, list) else f'{len(vv)} snos {vv[:10]}') for kk, vv in v.items()}
                                 if isinstance(v, dict) else v) for k, v in rank_checks.items()}))
print('matrix', json.dumps(matrix_check))
