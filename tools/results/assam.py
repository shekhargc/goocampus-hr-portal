"""Assam (DME Assam) "Provisional Select List of Candidates for NEET PG-2026 Counseling for State Quota seats, Assam
(ROUND -1)" → rows for POST /api/pg/results/ingest. Authority `dme_assam`.

The PDF (text layer, not scanned): page 1 = the DME admission notice (date, "provisional select list"), then one table
line per candidate on the registration list in merit order: Sr.No., Reg. L Sr.No., NEET PG 2026 Roll No. + Score,
App. No., Revised State Rank, Name, Category, PWD, SHQ, NEC, and Selection Details (Code, Quota, Subject Name, College
Name) — or Code `NA` = "Choice Not available" (no seat: counted and skipped).
PERSONAL DATA: App. No. and Name are never read into the output (their x-columns are skipped); the roll number is held
in memory only, to look the ranks up, and dropped. Score is used only for the cross-check, not stored.

Ranks: `rank` = the printed Revised State Rank (`87-A` style addendum ranks → 87, the printed text in `remarks`),
checked by roll against the "Provisional Merit List of NEET-PG-2026 for Assam State Quota Seats (after inclusion of
incentive marks)" (inbox 1255, 61 pages, prints Assam State Rank + NEET-PG 2026 AI Rank). `rank_ai` = the AI Rank of
that list by roll; `--first-merit` (the 79-page provisional merit list, inbox 1151, prints AIR) re-checks the AIR,
`--inclusion` (inclusion notice 17.10.2026, inbox 1278) supplies a candidate missing from both.
NB the state merit list loaded on 2026-11-03 (read_dme_assam.py) holds state_rank = position in the FIRST list
(before incentive marks); the select list prints the revised (incentive) state ranks.

Quota / category: no 2025 Assam state-quota cut-offs exist (2025 Assam rows are MCC AIQ only), so the printed seat
quota is kept: `quota` = `State Quota` (UR, EWS, OBC/MOBC(NCL), SC, ST(P), ST(H), URPh) or `State Quota-Inservice`
(SHQ = State Health Services quota); `allotted_category` = UR / EWS / OBC/MOBC / SC / ST(P) / ST(H) / UR-PwD / SHQ,
`allotted_category_raw` = `quota_raw` = the printed quota; `candidate_category` = printed Category (+ ` PwD`).
`institute` = the college's standard name (its 2025 cut-off name; the select list uses short names, e.g. Barpeta
Medical College = Fakhruddin Ali Ahmed Medical College). Courses → approved names (specialty_sheet.json); the four
Post-MBBS diplomas → section `diploma`.
Checks (stop on failure): Sr.No 1..N, roll numbers in the text = lines, state rank never drops, code ↔ college /
subject consistent, reserved seats only to that category (UR open to all, URPh only PWD = YES, SHQ only SHQ = YES),
printed rank = merit-list rank and printed score = merit-list revised score by roll, AIR found for every allotted line.
Run with /usr/bin/python3 (PyMuPDF):
    assam.py <select_list.pdf> <merit_after_incentive.pdf> <out.json> [--first-merit <merit.pdf>]
             [--inclusion <inclusion_notice.pdf>] [--round "Round 1"] [--round-order 1] [--status provisional|final]
             [--published-on YYYY-MM-DD]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {}
for k in ('--first-merit', '--inclusion', '--round', '--round-order', '--status', '--published-on'):
    if k in args:
        i = args.index(k); opt[k] = args[i + 1]; del args[i:i + 2]
if len(args) != 3:
    raise SystemExit(__doc__)
PDF, MERIT, OUT = args
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')
ROLL = re.compile(r'2666\d{7}$')

# select-list columns by x position (points, landscape 1008 wide); App. No. and Name are never read
COLS = [('sr', 0, 50), ('regl', 50, 95), ('roll', 95, 170), ('score', 170, 224), ('app', 224, 273),
        ('srank', 273, 328), ('name', 328, 480), ('cat', 480, 550), ('pwd', 550, 577), ('shq', 577, 605),
        ('nec', 605, 632), ('code', 632, 670), ('quota', 670, 738), ('subject', 738, 868), ('college', 868, 2000)]
SKIP = {'app', 'name'}
COLLEGES = {  # code prefix → (printed name, standard name = 2025 cut-off name)
    '01': ('Assam Medical College, Dibrugarh', 'Assam Medical College, Dibrugarh'),
    '02': ('Gauhati Medical College, Guwahati', 'Gauhati Medical College and Hospital, Guwahati'),
    '03': ('Silchar Medical College, Silchar', 'Silchar Medical College, Silchar'),
    '04': ('Jorhat Medical College, Jorhat', 'Jorhat Medical College and Hospital, Jorhat'),
    '05': ('Barpeta Medical College, Barpeta', 'Fakhruddin Ali Ahmed Medical College, Barpeta, Assam'),
    '06': ('Tezpur Medical College, Tezpur', 'Tezpur Medical College & Hospital, Tezpur'),
    '07': ('Dr. B. Borooah Cancer Institute, Guwahati', 'Dr. Bhubaneswar Borooah Cancer Institute, Assam'),
    '08': ('Lakhimpur Medical College, N.Lakhimpur', 'Lakhimpur Medical College, North, Chowkham, Assam'),
    '09': ('Diphu Medical College, Diphu', 'Diphu Medical College & Hospital, Assam')}
SUBJECTS = {  # code suffix → (printed subject, approved course, section)
    '01': ('MD GENERAL MEDICINE', 'MD - General Medicine', 'mdms'),
    '02': ('MS GENERAL SURGERY', 'MS - General Surgery', 'mdms'),
    '03': ('MS ORTHOPAEDICS', 'MS - Orthopaedics', 'mdms'),
    '04': ('MS OBSTETRICS & GYNAECOLOGY', 'MS - Obstetrics and Gynaecology', 'mdms'),
    '05': ('MS OPHTHALMOLOGY', 'MS - Ophthalmology', 'mdms'),
    '06': ('MS OTORHINOLARYNGOLOGY', 'MS - ENT (Otorhinolaryngology)', 'mdms'),
    '07': ('MD PAEDIATRICS', 'MD - Paediatrics', 'mdms'),
    '08': ('MD RADIO-DIAGNOSIS', 'MD - Radio-Diagnosis', 'mdms'),
    '09': ('MD RADIO-THERAPY/RADIATION ONCOLOGY', 'MD - Radiotherapy / Radiation Oncology', 'mdms'),
    '10': ('MD ANAESTHESIOLOGY', 'MD - Anaesthesiology', 'mdms'),
    '11': ('MD COMMUNITY MEDICINE', 'MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    '12': ('MD PATHOLOGY', 'MD - Pathology', 'mdms'),
    '13': ('MD DERMATOLOGY, VENEREOLOGY & LEPROSY', 'MD - Dermatology', 'mdms'),
    '14': ('MD PSYCHIATRY', 'MD - Psychiatry', 'mdms'),
    '15': ('MD FORENSIC MEDICINE', 'MD - Forensic Medicine', 'mdms'),
    '16': ('MD BIOCHEMISTRY', 'MD - Biochemistry', 'mdms'),
    '17': ('MD PHYSIOLOGY', 'MD - Physiology', 'mdms'),
    '18': ('MD MICROBIOLOGY', 'MD - Microbiology', 'mdms'),
    '19': ('MD PHARMACOLOGY', 'MD - Pharmacology', 'mdms'),
    '20': ('MD ANATOMY', 'MD/MS - Anatomy', 'mdms'),
    '21': ('MD EMERGENCY MEDICINE', 'MD - Emergency Medicine', 'mdms'),
    '22': ('MD TUBERCULOSIS & RESPIRATORY MEDICINE', 'MD - Respiratory Medicine', 'mdms'),
    '23': ('DIPLOMA PAEDIATRICS (D.C.H.)', 'Diploma in Child Health / Paediatrics', 'diploma'),
    '24': ('DIPLOMA ANAESTHESIOLOGY (D.A.)', 'Diploma in Anaesthesiology', 'diploma'),
    '25': ('DIPLOMA OTORHINOLARYNGOLOGY (D.L.O.)', 'Diploma in ENT', 'diploma'),
    '26': ('DIPLOMA FORENSIC MEDICINE (D.F.M.)', 'Diploma in Forensic Medicine', 'diploma')}
QUOTA = {  # printed quota → (quota, allotted category, candidate Category allowed (None = any))
    'UR': ('State Quota', 'UR', None), 'EWS': ('State Quota', 'EWS', {'EWS'}),
    'OBC/MOBC(NCL)': ('State Quota', 'OBC/MOBC', {'OBC/MOBC'}), 'SC': ('State Quota', 'SC', {'SC'}),
    'ST(P)': ('State Quota', 'ST(P)', {'ST(P)'}), 'ST(H)': ('State Quota', 'ST(H)', {'ST(H)'}),
    'URPh': ('State Quota', 'UR-PwD', None), 'SHQ': ('State Quota-Inservice', 'SHQ', None)}
CAND_CAT = {'General', 'EWS', 'OBC/MOBC', 'SC', 'ST(P)', 'ST(H)'}


def words(page):
    """Page words, with the text drawn twice at (nearly) the same place kept once."""
    return list({(w[4], round(w[0] / 3), round(w[1] / 3)): w for w in page.get_text('words')}.values())


def column(x0):
    return next(n for n, a, b in COLS if a <= x0 < b)


# ── reference: merit list after incentive marks (roll → state rank, AIR, revised score) ──
def near(W, y, x0, x1, pat):
    vals = {w[4] for w in W if x0 <= w[0] < x1 and re.fullmatch(pat, w[4]) and abs((w[1] + w[3]) / 2 - y) < 3}
    return vals.pop() if len(vals) == 1 else None


merit, mbad = {}, 0
md = fitz.open(MERIT)
if 'AFTER INCLUSION OF INCENTIVE MARKS' not in re.sub(r'\s+', ' ', md[1].get_text()).upper():
    raise SystemExit('the merit file is not the "after inclusion of incentive marks" list')
for p in md:
    W = words(p)
    for w in [w for w in W if ROLL.match(w[4])]:
        y = (w[1] + w[3]) / 2
        sr, ai = near(W, y, 25, 70, r'\d+'), near(W, y, 437, 480, r'\d+')
        sc = near(W, y, 392, 437, r'\d+(\.\d+)?')
        if not sr or not ai:
            mbad += 1; continue
        v = (int(sr), int(ai), float(sc) if sc else None)       # revised score: None when not read cleanly
        if w[4] in merit and merit[w[4]] != v:
            raise SystemExit('a roll appears twice in the merit list with different values')
        merit[w[4]] = v
mranks = sorted(v[0] for v in merit.values())
if mbad or mranks != list(range(1, len(mranks) + 1)):
    raise SystemExit(f'merit list not read cleanly ({mbad} lines unread, ranks 1..{len(mranks)}: '
                     f'{mranks == list(range(1, len(mranks) + 1))})')
first = {}
if '--first-merit' in opt:          # 79-page provisional merit list (same reading as merit_lists/read_dme_assam.py)
    toks = [t for p in fitz.open(opt['--first-merit']) for t in p.get_text().split()]
    idx = [i for i, t in enumerate(toks) if ROLL.match(t)]
    for n, i in enumerate(idx):
        seg = toks[i + 1:(idx[n + 1] if n + 1 < len(idx) else len(toks))]
        g = next((k for k, t in enumerate(seg) if t in {'MALE', 'FEMALE', 'TRANSGENDER', 'OTHER', 'OTHERS'}), None)
        nums = [k for k, t in enumerate(seg[g + 1:]) if re.fullmatch(r'-?\d+', t)] if g is not None else []
        if len(nums) < 2:
            raise SystemExit(f'first merit list line {n + 1}: AIR not found')
        first[toks[i]] = int(seg[g + 1:][nums[0] + 1])
incl = {}
if '--inclusion' in opt:
    for t in fitz.open(opt['--inclusion'])[0].find_tables().tables:
        for c in t.extract()[1:]:
            roll, srank, air = (re.sub(r'\s+', '', c[k] or '') for k in (1, 5, 6))
            if ROLL.match(roll) and air.isdigit():
                incl[roll] = (srank, int(air))

# ── select list ──
doc = fitz.open(PDF)
p1 = re.sub(r'\s+', ' ', doc[0].get_text())
if 'ADMISSION NOTICE' not in p1 or 'Assam State Quota' not in p1:
    raise SystemExit('page 1 is not the DME Assam admission notice')
dm = re.search(r'Dated Guwahati the (\d{1,2})\s*(?:st|nd|rd|th)? (\w+),? (20\d\d)', p1)
MONTHS = {m: i for i, m in enumerate(('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                                      'September', 'October', 'November', 'December'), 1)}
published = opt.get('--published-on') or (f'{dm.group(3)}-{MONTHS[dm.group(2)]:02d}-{int(dm.group(1)):02d}' if dm else '')
p2 = re.sub(r'\s+', ' ', doc[1].get_text())
tm = re.search(r'((?:Provisional|Final) Select List of Candidates for NEET PG-2026 Counseling for State Quota seats, '
               r'Assam \(ROUND -?(\d+)\))', p2)
if not tm:
    raise SystemExit('page 2 title not found')
status = 'final' if tm.group(1).startswith('Final') else 'provisional'
if opt.get('--status') and opt['--status'] != status:
    raise SystemExit(f'--status {opt["--status"]} but the list says {status}')
rnd_no = int(tm.group(2))
if opt.get('--round') and opt['--round'] != f'Round {rnd_no}':
    raise SystemExit(f'--round {opt["--round"]} but the list says ROUND {rnd_no}')

lines, roll_words = [], 0
for p in doc[1:]:
    W = words(p)
    hdr = max(w[3] for w in W if w[4] in ('Code', 'Quota', 'Subject'))
    foot = min([w[1] for w in W if w[4].startswith('Important')] + [p.rect.height])
    W = [w for w in W if hdr + 1 < w[1] < foot - 2]
    roll_words += sum(1 for w in W if ROLL.match(w[4]))
    anchors = sorted([w for w in W if w[0] < 50 and w[4].isdigit()], key=lambda w: w[1])
    for i, a in enumerate(anchors):
        top, bot = a[1] - 6, (anchors[i + 1][1] - 6 if i + 1 < len(anchors) else 1e9)
        cells = collections.defaultdict(list)
        for w in W:
            if top <= w[1] < bot:
                c = column(w[0])
                if c not in SKIP:
                    cells[c].append(w)
        lines.append({k: ' '.join(x[4] for x in sorted(v, key=lambda w: (round(w[1] / 4), w[0])))
                      for k, v in cells.items()})
sr = [int(r['sr']) for r in lines]
if sr != list(range(1, len(sr) + 1)):
    raise SystemExit(f'Sr.No is not 1..{len(sr)} — lines missing or read twice')
if roll_words != len(lines):
    raise SystemExit(f'{roll_words} roll numbers in the text but {len(lines)} lines read')

approved = {c['course'] for c in json.load(open(SHEET))['courses']}
rows, unknown, ver, no_seat, prev = [], collections.Counter(), collections.Counter(), 0, 0
for r in lines:
    roll, srank_raw, cat, code = r.get('roll', ''), r.get('srank', ''), r.get('cat', ''), r.get('code', '')
    if not ROLL.match(roll) or not re.fullmatch(r'\d+(-A)?', srank_raw) or not re.fullmatch(r'\d+(\.\d+)?', r.get('score', '')):
        raise SystemExit(f'Sr.No {r["sr"]}: roll / state rank / score not as expected')
    if cat not in CAND_CAT:
        unknown['Category: ' + cat] += 1
    flags = {k: r.get(k, '') for k in ('pwd', 'shq', 'nec')}
    if any(v not in ('', 'YES') for v in flags.values()):
        unknown['PWD/SHQ/NEC: ' + str(flags)] += 1
    srank = int(srank_raw.split('-')[0])
    if srank < prev:
        raise SystemExit(f'Sr.No {r["sr"]}: state rank drops')
    prev = srank
    # reference checks (every line, allotted or not)
    m = merit.get(roll)
    if not m:
        if roll not in incl:
            ver['MISMATCH not in the merit list nor the inclusion notice'] += 1
        else:
            ver['inclusion notice line, state rank ' + ('= notice' if incl[roll][0] == srank_raw else 'MISMATCH')] += 1
    else:
        if srank_raw.isdigit():
            ver['state rank = merit list' if m[0] == srank else 'MISMATCH state rank'] += 1
        else:
            ver['n-A rank (notice) — merit list has ' + ('same n' if m[0] == srank else 'another rank')] += 1
        if m[2] is None:
            ver['score not read in merit list'] += 1
        elif not srank_raw.isdigit():     # n-A: moved + score revised by the 29.10.2026 revised-position notice
            ver['n-A rank: score revised by notice (differs from merit list)' if abs(m[2] - float(r['score'])) >= 0.005
                else 'n-A rank: score = merit list'] += 1
        else:
            ver['score = merit list revised score' if abs(m[2] - float(r['score'])) < 0.005 else 'MISMATCH score'] += 1
        if roll in first:
            ver['AIR = first merit list' if first[roll] == m[1] else 'MISMATCH AIR vs first merit list'] += 1
    if code == 'NA':
        if r.get('quota') or r.get('subject', '-') != '-' or r.get('college', '-') != '-':
            raise SystemExit(f'Sr.No {r["sr"]}: NA line with seat details')
        no_seat += 1
        continue
    cc, sc = COLLEGES.get(code[:2]), SUBJECTS.get(code[2:])
    if not re.fullmatch(r'\d{4}', code) or not cc or not sc:
        unknown['code: ' + code] += 1; continue
    if cc[0] != r.get('college') or sc[0] != r.get('subject'):
        unknown[f'code {code} ≠ printed college / subject'] += 1; continue
    if sc[1] not in approved:
        raise SystemExit(f'{sc[1]!r} is not in specialty_sheet.json')
    q = QUOTA.get(r.get('quota', ''))
    if not q:
        unknown['quota: ' + r.get('quota', '')] += 1; continue
    if (q[2] and cat not in q[2]) or (r['quota'] == 'URPh' and flags['pwd'] != 'YES') or \
            (r['quota'] == 'SHQ' and flags['shq'] != 'YES'):
        raise SystemExit(f'Sr.No {r["sr"]}: {r["quota"]} seat to a {cat} candidate {flags}')
    ai = m[1] if m else (first.get(roll) or (incl.get(roll) or (None, None))[1])
    if not ai:
        ver['no AIR'] += 1
    remarks = []
    if not srank_raw.isdigit():
        remarks.append(f'state rank printed {srank_raw}')
    if flags['shq']:
        remarks.append('SHQ candidate')
    if flags['nec']:
        remarks.append('NEC: YES')
    rows.append({'sno': int(r['sr']), 'rank': srank, 'rank_ai': ai, 'quota_raw': r['quota'], 'quota': q[0],
                 'institute_raw': cc[0], 'institute': cc[1], 'course_raw': sc[0], 'course': sc[1], 'section': sc[2],
                 'allotted_category': q[1], 'allotted_category_raw': r['quota'],
                 'candidate_category': cat + (' PwD' if flags['pwd'] else ''), 'remarks': '; '.join(remarks)})
del merit, first, incl, lines
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
if any(k.startswith('MISMATCH') for k in ver) or ver.get('no AIR'):
    raise SystemExit(f'ranks disagree with the reference files: {dict(ver)}')

C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'lines': len(sr), 'allotted': len(rows), 'no_seat_NA': no_seat, 'pages': len(doc),
          'by_section': C('section'), 'by_quota': C('quota'), 'by_quota_raw': C('quota_raw'),
          'by_allotted_category': C('allotted_category'), 'by_college': C('institute'), 'by_course': C('course'),
          'college_x_course': len({(x['institute'], x['course']) for x in rows}), 'rank_checks': dict(ver),
          'rank_ai': sum(1 for x in rows if x['rank_ai']),
          'state_rank': [min(x['rank'] for x in rows), max(x['rank'] for x in rows)],
          'ai_rank': [min(x['rank_ai'] for x in rows), max(x['rank_ai'] for x in rows)],
          'seat_matrix': 'no 2026 Assam state seat matrix loaded — not checked'}
out = {'authority_code': 'dme_assam', 'round': opt.get('--round') or f'Round {rnd_no}',
       'round_order': int(opt.get('--round-order') or rnd_no), 'status': status,
       'title': tm.group(1).replace('Counseling', 'Counselling'), 'published_on': published,
       'source_file_name': os.path.basename(PDF),
       'notes': ('DME Assam, 50% state quota seats (Government Medical Colleges + B.B.C.I.). rank = printed Revised '
                 'State Rank (n-A → n, printed text in remarks), checked against the merit list after incentive marks; '
                 'rank_ai = NEET PG AIR from that merit list by roll. quota State Quota / State Quota-Inservice (SHQ); '
                 'allotted_category = printed seat quota. "NA" (choice not available) lines not imported. No names, '
                 'roll or application numbers stored.'),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['round'], out['status'], out['published_on'])
print('lines', len(sr), '| allotted', len(rows), '| NA', no_seat, '| by section', checks['by_section'])
print('by quota', checks['by_quota'], '| by allotted category', checks['by_allotted_category'])
print('rank checks', dict(ver))
print('rank_ai', checks['rank_ai'], '/', len(rows), '| state', checks['state_rank'], '| AI', checks['ai_rank'],
      '| colleges', len(checks['by_college']), '| college x course', checks['college_x_course'])
