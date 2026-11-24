"""Tamil Nadu (DME Selection Committee) PG Medical MAIN allotment lists of Round 2+ → ONE body for
POST /api/pg/results/ingest (round "Round 2", round_order 2). Sibling of tamil_nadu_r1.py (Round 1 layout) — the
quota / category / course / college maps are read from that file's source, so both rounds use the same spellings.

The Round 2 PDFs (24.11.2026) add an ALLOTTED FROM column (the candidate's earlier seat) and a Status column:
  GQ  SNO, GRANK, APP. NO, NAME, COMMUNITY, SERVICE, T.MARK, ALLOTTED FROM, ALLOTTED TO, CATEGORY, Status
  MQ  SNO, GRANK, APP. NO, NAME, T.MARK, ALLOTTED FROM, ALLOTTED TO, CATEGORY, STATUS
PERSONAL DATA: APP. NO and NAME (cells 2 and 3) are never read.

round_status: Status 'Retained' → retained (FROM = TO); FROM blank → fresh; FROM ≠ TO → upgraded (the seat moved —
TN prints no status for it; prev_* = the FROM seat). A seat in the FROM column can be in the OTHER list (e.g. a Round 1
GQ CMC 20% seat → a Round 2 MQ seat).

Ranks: `rank` = GRANK as printed (GQ merit rank for GQ rows, MQ merit rank for MQ / NRI rows — as in Round 1).
`rank_ai` is not printed. It is taken from the stored Round 1 result of the same list (--r1: rows of
/api/pg/results?authority=dmer_tn&round=Round 1, which carry rank + rank_ai from the TN merit lists): same list, same
GRANK (and, for a shared 'nA' GRANK, the same community). A candidate who had no Round 1 seat in that list (fresh, or
moved across lists) is looked up in --bridge files when given (merit-list rows {state_rank, air, score, category},
like tamil_nadu_r1.py's --gq-bridge / --mq-bridge); otherwise rank_ai stays empty and is counted in checks.
Every Round 1 match is checked: a retained / upgraded line's FROM seat must be that Round 1 row's seat.
Quota / category as tamil_nadu_r1.py (GQ seat category not printed → allotted_category = community).
Run with /usr/bin/python3 (PyMuPDF):
    tamil_nadu_r2.py <gq_allotment.pdf> <mq_allotment.pdf> <out.json> --r1 <tn_round1_rows.json>
                     [--gq-bridge <dmer_tn_gq.json>] [--mq-bridge <dmer_tn_mq.json>] [--seat-matrix <TN R2 matrix.json>]
                     [--round "Round 2"] [--round-order 2] [--status provisional|final] [--published-on YYYY-MM-DD]"""
import json, os, re, sys, collections
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
opt = {'--round': 'Round 2', '--round-order': '2'}
for k in ('--r1', '--gq-bridge', '--mq-bridge', '--seat-matrix', '--round', '--round-order', '--status', '--published-on'):
    if k in args:
        i = args.index(k); opt[k] = args[i + 1]; del args[i:i + 2]
if len(args) != 3 or '--r1' not in opt:
    raise SystemExit(__doc__)
GQ_PDF, MQ_PDF, OUT = args
SHEET = os.path.join(HERE, '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

_src = open(os.path.join(HERE, 'tamil_nadu_r1.py')).read()
_ns = {}
exec(_src[_src.index('HEAD = {'):_src.index('\nclean = lambda')], _ns)
TITLE, COMMUNITY, CMC, GQ_CAT, MQ_CAT, COLLEGES, COURSES = (
    _ns[k] for k in ('TITLE', 'COMMUNITY', 'CMC', 'GQ_CAT', 'MQ_CAT', 'COLLEGES', 'COURSES'))
HEAD = {'GQ': 'SNO GRANK APP. NO NAME COMMUNITY SERVICE T.MARK ALLOTTED FROM ALLOTTED TO CATEGORY Status',
        'MQ': 'SNO GRANK APP. NO NAME T.MARK ALLOTTED FROM ALLOTTED TO CATEGORY STATUS'}
# Round 2 adds 11 new Government medical colleges and 2 private universities (TN Round 2 seat matrix of 21.11.2026
# names = 'Tamil Nadu — Round 2 — State Counselling' body) and one course
COLLEGES = dict(COLLEGES, **{
    'GOVT. TIRUPPUR MEDICAL COLLEGE HOSPITAL, TIRUPPUR.': 'Government Medical College, Tiruppur',
    'GOVT. DINDIGUL MEDICAL COLLEGE HOSPITAL, DINDIGUL': 'Government Medical College, Dindigul',
    'GOVERNMENT MEDICAL COLLEGE, KARUR': 'Government Medical College, Karur',
    'GOVT. NAGAPATTINAM MEDICAL COLLEGE HOSPITAL,': 'Government Medical College, Nagapattinam',
    'GOVT. NAMAKKAL MEDICAL COLLEGE HOSPITAL, NAMAKKAL.': 'Government Medical College, Namakkal',
    'GOVT. RAMANATHAPURAM MEDICAL COLLEGE HOSPITAL,': 'Government Medical College, Ramanathapuram',
    'GOVT. KRISHNAGIRI MEDICAL COLLEGE HOSPITAL,': 'Government Medical College, Krishnagiri',
    'GOVT. MEDICAL COLLEGE HOSPITAL, VIRUDHUNAGAR.': 'Government Medical College, Virudhunagar',
    'GOVT. THE NILGIRIS MEDICAL COLLEGE HOSPITAL, THE NILGIRIS': 'Government Medical College, Nilgiris',
    'GOVT.ARIYALUR MEDICAL COLLEGE HOSPITAL, ARIYALUR.': 'Government Medical College, Ariyalur',
    'GOVT.KALLAKURUCHI MEDICAL COLLEGE HOSPITAL,': 'Government Medical College, Kallakurichi',
    'TAKSHASHILA MEDICAL COLLEGE, ONGUR, TINDIVANAM, VILLUPURAM (PRIVATE UNIVERSITY)': 'Takshashila Medical College',
    'KANYAKUMARI MEDICAL MISSION RESEARCH CENTER, KANYAKUMARI (PRIVATE UNIVERSITY)':
        'Kanyakumari Medical Mission Research Center, Kanyakumari'})
COURSES = dict(COURSES, **{'M.D.SportsMedicine': ('MD - Sports Medicine', 'mdms')})

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()
approved = {c['course'] for c in json.load(open(SHEET))['courses']}
for std, _ in COURSES.values():
    if std not in approved:
        raise SystemExit(f'{std!r} is not in specialty_sheet.json')


def seat(cell):
    """'GQ - <course>\\n<college>' / 'MQ - …' / 'NRI Category<course>\\n…' → (prefix, course_raw, college_raw) or None.
    A long course name wraps onto the next line(s): the split is the one line break where the course part is a known
    course (and, when one exists, the rest a known college)."""
    if not clean(cell):
        return None
    ls = [clean(x) for x in (cell or '').split('\n') if clean(x)]
    m = re.fullmatch(r'(GQ|MQ)\s*-\s*(.+)', ls[0]) or re.fullmatch(r'(NRI) Category\s*(.+)', ls[0])
    if not m or len(ls) < 2:
        raise SystemExit(f'seat cell is not "<quota> - <course>" + college: {clean(cell)!r}')
    pre, first = m.group(1), m.group(2)
    splits = [(' '.join([first] + ls[1:k]), ' '.join(ls[k:])) for k in range(1, len(ls))]
    ok = [s for s in splits if re.sub(r'\s+', '', s[0]) in COURSES]
    best = [s for s in ok if s[1] in COLLEGES] or ok or splits[:1]
    if len(best) != 1 and len({b for b in best}) != 1:
        raise SystemExit(f'seat cell split is ambiguous: {clean(cell)!r}')
    return pre, best[0][0], best[0][1]


def read_list(path, kind):
    doc = fitz.open(path)
    top = clean(' '.join(w[4] for w in doc[0].get_text('words') if w[1] < 55))
    m_t = re.search(r'Post Graduate Medical\s*\(\s*(.*?)\s*\)\s*Course Session\s*:?\s*(\d{4}\s*-\s*\d{4})', top)
    m_d = re.search(r'(Provisional|Final) List of Candidates allotted on\s*-\s*(\d{2})\.(\d{2})\.(\d{4})', top)
    if not m_t or not m_d or m_t.group(1) != TITLE[kind]:
        raise SystemExit(f'{kind}: title / "List of Candidates allotted on" line not found or not {TITLE[kind]}')
    ncol = len(HEAD[kind].split(' ')) - 3      # 'APP. NO', 'ALLOTTED FROM', 'ALLOTTED TO' are two words each
    lines = []
    for pg in doc:
        tabs = pg.find_tables().tables
        if len(tabs) != 1:
            raise SystemExit(f'{kind} p{pg.number + 1}: {len(tabs)} tables')
        foot = clean(' '.join(w[4] for w in pg.get_text('words') if w[1] > 560))
        if foot != f'Page-{pg.number + 1} of {len(doc)}':
            raise SystemExit(f'{kind} p{pg.number + 1}: footer {foot!r}')
        for r in tabs[0].extract():
            if len(r) != ncol:
                raise SystemExit(f'{kind} p{pg.number + 1}: a table line has {len(r)} columns')
            c0 = clean(r[0])
            if c0.startswith('SNO'):
                if clean(' '.join(x or '' for x in r)) != HEAD[kind]:
                    raise SystemExit(f'{kind} p{pg.number + 1}: column headings changed')
                continue
            if not c0.isdigit():
                raise SystemExit(f'{kind} p{pg.number + 1}: a line without a serial number')
            if kind == 'GQ':
                comm, serv, tmark, fr, to = clean(r[4]), clean(r[5]), clean(r[6]), r[7], r[8]
            else:
                comm, serv, tmark, fr, to = '', '', clean(r[4]), r[5], r[6]
            lines.append({'sno': int(c0), 'grank': clean(r[1]), 'comm': comm, 'serv': serv, 'tmark': tmark,
                          'from': seat(fr), 'to': seat(to), 'cat': clean(r[-2]), 'status': clean(r[-1])})
    sn = [x['sno'] for x in lines]
    if sn != list(range(1, len(sn) + 1)):
        raise SystemExit(f'{kind}: serial numbers are not 1..{len(sn)} in order')
    return m_t, m_d, lines


def merit(path):
    by = collections.defaultdict(list)
    if path:
        for x in json.load(open(path))['rows']:
            by[x['state_rank']].append(x)
    return by


# Round 1 result rows → {list: {grank: [row, …]}}; list = 'GQ' (quota_raw GQ) or 'MQ' (MQ / NRI)
R1 = collections.defaultdict(lambda: collections.defaultdict(list))
for x in json.load(open(opt['--r1']))['rows']:
    if x.get('rank') is None or x.get('rank_ai') is None:
        continue
    R1['GQ' if x['quota_raw'] == 'GQ' else 'MQ'][int(x['rank'])].append(x)
BRIDGE = {'GQ': merit(opt.get('--gq-bridge')), 'MQ': merit(opt.get('--mq-bridge'))}

rows, unknown, ai_how, seat_check = [], collections.Counter(), collections.Counter(), collections.Counter()
no_ai, heads = [], {}
for kind, path in (('GQ', GQ_PDF), ('MQ', MQ_PDF)):
    m_t, m_d, lines = read_list(path, kind)
    heads[kind] = (m_t, m_d, len(lines))
    for x in lines:
        sno, g = x['sno'], x['grank']
        mg = re.fullmatch(r'(\d+)(A?)', g)
        if not mg:
            unknown[f'{kind} GRANK: {g}'] += 1; continue
        grank, addendum = int(mg.group(1)), bool(mg.group(2))
        if not re.fullmatch(r'\d+(\.\d+)?', x['tmark']):
            unknown[f'{kind} T.MARK: ' + x['tmark']] += 1; continue
        if not x['to']:
            unknown[f'{kind} SNO {sno}: no ALLOTTED TO'] += 1; continue
        bad = False
        for side in ('from', 'to'):
            s = x[side]
            if not s:
                continue
            if re.sub(r'\s+', '', s[1]) not in COURSES:
                unknown['course: ' + s[1]] += 1; bad = True
            if s[2] not in COLLEGES:
                unknown['college: ' + s[2]] += 1; bad = True
        if bad:
            continue
        q_raw, course_raw, college_raw = x['to']
        inst = COLLEGES[college_raw]
        course, sec = COURSES[re.sub(r'\s+', '', course_raw)]
        remarks = []
        if kind == 'GQ':
            if q_raw != 'GQ':
                unknown[f'GQ list seat prefix {q_raw}'] += 1; continue
            if x['comm'] not in COMMUNITY:
                unknown['community: ' + x['comm']] += 1; continue
            if x['serv'] not in ('', 'Service'):
                unknown['service: ' + x['serv']] += 1; continue
            if x['cat'] not in GQ_CAT:
                unknown['GQ category: ' + x['cat']] += 1; continue
            quota = GQ_CAT[x['cat']] or ('Government Quota-Service' if x['serv'] else 'Government Quota')
            if x['cat'] == 'CMC 20%' and inst != CMC:
                raise SystemExit(f'GQ SNO {sno}: CMC 20% outside CMC')
            acat = cand = x['comm']
            if x['serv']:
                remarks.append('Service')
        else:
            if x['cat'] not in MQ_CAT:
                unknown['MQ category: ' + x['cat']] += 1; continue
            quota, acat, prefix, cmc_only = MQ_CAT[x['cat']]
            if prefix != q_raw:
                raise SystemExit(f'MQ SNO {sno}: category {x["cat"]!r} printed with prefix {q_raw!r}')
            if cmc_only != (inst == CMC):
                raise SystemExit(f'MQ SNO {sno}: category {x["cat"]!r} at {inst}')
            cand = ''
        st_raw = x['status']
        if st_raw not in ('', 'Retained'):
            unknown[f'{kind} status: {st_raw}'] += 1; continue
        fr = x['from']
        if st_raw == 'Retained':
            if fr != x['to']:
                raise SystemExit(f'{kind} SNO {sno}: Retained but FROM ≠ TO')
            rstat = 'retained'
        elif not fr:
            rstat = 'fresh'
        elif fr == x['to']:
            rstat = 'retained'; remarks.append('same seat, status blank')
        else:
            rstat = 'upgraded'
        # rank_ai: Round 1 row of the same list + GRANK
        rank_ai, r1 = None, None
        if grank == 0:
            remarks.append('GRANK printed 0'); ai_how[f'{kind} GRANK 0 — not filled'] += 1
        else:
            c = R1[kind].get(grank, [])
            if len(c) > 1 and kind == 'GQ':
                c = [r for r in c if r.get('candidate_category') == x['comm']]
            if len(c) > 1 and fr:
                c = [r for r in c if r['institute'] == COLLEGES[fr[2]] and r['course'] == COURSES[re.sub(r'\s+', '', fr[1])][0]]
            if len(c) == 1:
                r1 = c[0]; rank_ai = int(r1['rank_ai']); ai_how[f'{kind} from Round 1 result (same list + GRANK)'] += 1
                if fr:
                    same = (r1['institute'] == COLLEGES[fr[2]] and r1['course'] == COURSES[re.sub(r'\s+', '', fr[1])][0])
                    seat_check['FROM seat = Round 1 seat' if same else 'FROM seat ≠ Round 1 seat'] += 1
                    if not same:
                        raise SystemExit(f'{kind} SNO {sno}: GRANK {g} Round 1 seat differs from FROM')
                else:
                    seat_check['fresh but GRANK held a Round 1 seat in this list'] += 1
            elif len(c) > 1:
                raise SystemExit(f'{kind} SNO {sno}: GRANK {g} matches {len(c)} Round 1 rows')
            else:
                b = BRIDGE[kind].get(grank, [])
                hit = [m for m in b if abs(float(m['score']) - float(x['tmark'])) < 0.005
                       and (kind == 'MQ' or m['category'] == x['comm'])]
                if len(hit) == 1:
                    rank_ai = int(hit[0]['air']); ai_how[f'{kind} from merit-list bridge'] += 1
                    if kind == 'MQ':
                        cand = hit[0]['category']
                else:
                    ai_how[f'{kind} not filled ({rstat}{", FROM in other list" if fr and (fr[0] == "GQ") != (kind == "GQ") else ""})'] += 1
                    no_ai.append({'list': kind, 'sno': sno, 'grank': g, 'round_status': rstat})
        if kind == 'MQ' and not cand and r1:
            cand = r1.get('candidate_category') or ''
        if addendum:
            remarks.append(f'GRANK {g}')
        row = {'sno': sno, 'rank': grank or None, 'rank_ai': rank_ai, 'quota_raw': q_raw, 'quota': quota,
               'institute_raw': college_raw, 'institute': inst, 'course_raw': course_raw, 'course': course,
               'section': sec, 'allotted_category': acat, 'allotted_category_raw': x['cat'],
               'candidate_category': cand, 'remarks': ', '.join(remarks),
               'round_status': rstat, 'round_status_raw': st_raw}
        if fr:
            pq, pc, pcol = fr
            pquota = r1['quota'] if r1 else {'GQ': 'Government Quota', 'MQ': 'Management Quota', 'NRI': 'NRI Quota'}[pq]
            row.update({'prev_quota_raw': pq, 'prev_quota': pquota, 'prev_institute_raw': pcol,
                        'prev_course_raw': pc, 'prev_course': COURSES[re.sub(r'\s+', '', pc)][0],
                        'prev_remarks': 'Round 1 seat (ALLOTTED FROM)'})
        rows.append(row)
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
n_lines = heads['GQ'][2] + heads['MQ'][2]
if len(rows) != n_lines:
    raise SystemExit('rows ≠ lines')
dates = {(h[1].group(1), h[1].group(2), h[1].group(3), h[1].group(4), h[0].group(2)) for h in heads.values()}
if len(dates) != 1:
    raise SystemExit(f'the two lists differ in status / date / session: {dates}')
st, dd, mm, yy, session = dates.pop()
status = opt.get('--status') or st.lower()
published = opt.get('--published-on') or f'{yy}-{mm}-{dd}'

C = lambda f, rr=rows: dict(collections.Counter(x[f] for x in rr).most_common())
checks = {'lines': {'GQ': heads['GQ'][2], 'MQ': heads['MQ'][2], 'total': n_lines}, 'sno_1_to_n_per_list': True,
          'by_round_status': C('round_status'), 'from_seat_vs_round1': dict(seat_check),
          'by_section': C('section'), 'by_quota': C('quota'), 'by_remarks': C('remarks'),
          'colleges': len({x['institute'] for x in rows}),
          'rank_ai': {'filled': sum(1 for x in rows if x['rank_ai'] is not None),
                      'not_filled': sum(1 for x in rows if x['rank_ai'] is None), 'how': dict(ai_how)},
          'rank_ai_missing': no_ai}
if '--seat-matrix' in opt:
    sm = collections.Counter()
    for s in json.load(open(opt['--seat-matrix']))['rows']:
        sm[(s['college_name'], s['course_name'])] += s['seats']
    # the Round 2 matrix lists the seats open in Round 2 → compare the seats newly taken (fresh + upgraded) only
    got = collections.Counter((x['institute'], x['course']) for x in rows if x['round_status'] != 'retained')
    over = {f'{c} · {co}': f'{n} taken / {sm[(c, co)]} open' for (c, co), n in got.items() if n > sm[(c, co)]}
    checks['seat_matrix'] = {'matrix_seats': sum(sm.values()), 'taken_in_round': sum(got.values()), 'groups': len(got),
                             'groups_not_in_matrix': sum(1 for k in got if k not in sm), 'over_matrix': over}
out = {'authority_code': 'dmer_tn', 'round': opt['--round'], 'round_order': int(opt['--round-order']),
       'status': status,
       'title': f'Post Graduate Medical (Government Quota + Management Quota) Course Session {session} — '
                f'{st} List of Candidates allotted on {dd}.{mm}.{yy}',
       'published_on': published,
       'source_file_name': f'GQ: {os.path.basename(GQ_PDF)} + MQ: {os.path.basename(MQ_PDF)}',
       'notes': ('Tamil Nadu Selection Committee Round 2 main lists: Government Quota (incl. CMC 20%) + Management '
                 'Quota (incl. NRI, minority, CMC 50%) in one round. rank = GRANK of each list (GQ merit rank for GQ '
                 'rows, MQ merit rank for MQ/NRI rows); rank_ai from the Round 1 result of the same list by GRANK '
                 '(or the TN merit list). round_status from ALLOTTED FROM / Status: Retained = kept, blank FROM = '
                 'fresh, different FROM = upgraded (prev_* = the FROM seat). GQ seat category not printed: '
                 'allotted_category = candidate community.'),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['round'], out['round_order'], out['status'], out['published_on'])
for k in ('lines', 'by_round_status', 'from_seat_vs_round1', 'by_quota', 'colleges', 'rank_ai', 'seat_matrix'):
    print(k, checks.get(k))
