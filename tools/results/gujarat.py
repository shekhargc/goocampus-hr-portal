"""Gujarat (ACPPGMEC) NEET-PG seat allotment result (provisional / final, any round) → rows for
POST /api/pg/results/ingest. Reads three official PDFs of the same round:
  meritwise      — "Provisional Meritwise Allotment List": one line per allotted seat (SR, student name, MERITNO,
                   Cat + Cat Merit, Score, ADM Cat, Adm Seat Type, AIQ Rank, User ID, Adm Type Merit, Adm Round,
                   College code, Branch). The main source.
  institutewise  — "Provisional Institute Wise Allotment List": the same allotments grouped under
                   "<no> <college code> <college name>" + branch headings (adds the printed college NAME and the
                   candidate's pass college, which is dropped). Check: every line must be the same seat as in the
                   meritwise list (college × branch × quota × category × merit × AIQ rank), so every
                   institute × course × quota × category count agrees.
  last_merit     — "Last Merit": per branch × college (code, code-MQ, code-NQ) the closing merit per quota block
                   (Government / Institutional / Inservice) × OPEN EWS SC ST SE. Check: the highest merit we read for
                   every group equals the printed one, and no group is printed that we have no seat for.
Names, user IDs, gender flag and pass college are never kept. `rank` = state merit number (MERITNO; half numbers
like 256.5 = inserted later, stored as the floor like the merit-list bridge), `rank_ai` = the printed AIQ Rank
(NEET PG All-India rank). Quota / category use the 2025 Gujarat cut-off spellings: GQ → Government Quota,
UQ → Institutional Quota, IQ → Government Quota-Inservice, MQ → Management Quota, NQ → NRI Quota;
categories OP SE EW SC ST (+ -PH), MQ, NRI. institute_raw = the college name printed in the institute-wise list for
the college code (the meritwise list prints only the code); the portal's name memory resolves it.
Run with /usr/bin/python3 (PyMuPDF):
    gujarat.py <meritwise.pdf> <institutewise.pdf> <last_merit.pdf> <out.json> [--bridge <merit_bridge.json>]
--bridge: the loaded Gujarat merit list (rows with state_rank / air) — checks every (merit, AIQ rank) pair is in it."""
import json, os, re, sys, collections
import fitz

args = [a for a in sys.argv[1:]]
BRIDGE = None
if '--bridge' in args:
    i = args.index('--bridge'); BRIDGE = args[i + 1]; del args[i:i + 2]
if len(args) != 4:
    raise SystemExit(__doc__)
MERIT, INST, LAST, OUT = args
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

QUOTA = {'GQ': 'Government Quota', 'UQ': 'Institutional Quota', 'IQ': 'Government Quota-Inservice',
         'MQ': 'Management Quota', 'NQ': 'NRI Quota'}
key = lambda s: re.sub(r'[^a-z]', '', (s or '').lower())
SUBJECTS = {  # printed branch (lower-case letters only) → approved course name (same map as tools/seat_matrix/gujarat.py)
    'anaesthesiology': 'MD - Anaesthesiology', 'biochemistry': 'MD - Biochemistry',
    'communitymedicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'dermatologyvenereologyleprosy': 'MD - Dermatology', 'emergencymedicine': 'MD - Emergency Medicine',
    'forensicmedicine': 'MD - Forensic Medicine', 'generalmedicine': 'MD - General Medicine',
    'immunohaematologybloodtransfusion': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'microbiology': 'MD - Microbiology', 'paediatrics': 'MD - Paediatrics', 'pathology': 'MD - Pathology',
    'pharmacology': 'MD - Pharmacology', 'physiology': 'MD - Physiology', 'psychiatry': 'MD - Psychiatry',
    'radiodiagnosis': 'MD - Radio-Diagnosis', 'radiationoncology': 'MD - Radiotherapy / Radiation Oncology',
    'tuberculosisrespiratorymedicine': 'MD - Respiratory Medicine', 'palliativemedicine': 'MD - Palliative Medicine',
    'anatomy': 'MD/MS - Anatomy', 'generalsurgery': 'MS - General Surgery',
    'obstetricsgynaecology': 'MS - Obstetrics and Gynaecology', 'ophthalmology': 'MS - Ophthalmology',
    'orthopaedics': 'MS - Orthopaedics', 'otorhinolaryngologyent': 'MS - ENT (Otorhinolaryngology)',
    'diplomainanesthesiologyda': 'Diploma in Anaesthesiology',
    'diplomaincommunitymedicinedcm': 'Diploma in Community Medicine/Preventive and Social Medicine',
    'diplomainobstetricsgynecologydgo': 'Diploma in Obstetrics and Gynaecology',
    'diplomainpaediatricsdch': 'Diploma in Child Health / Paediatrics',
    'diplomainpublichealthdph': 'Diploma in Public Health',
    'diplomaintuberculosischestdiseasesdtcd': 'Diploma in Respiratory Medicine'}
# NBEMS post-MBBS DNB seats are printed as "<Branch> (DNB)": kept as published, section dnb
DNB_RE = re.compile(r'(.+?)\s*\(DNB\)$')
CATS = ('OP', 'SE', 'EW', 'SC', 'ST')

clean = lambda s: re.sub(r'\s+', ' ', (s or '')).strip()


TRUNCATED = collections.Counter()


def course_of(branch, allow_prefix=False):
    m = DNB_RE.fullmatch(branch)
    if m:
        return 'DNB - ' + clean(m.group(1)), 'dnb'
    hit = [k for k in SUBJECTS if k.startswith(key(branch))]
    if key(branch) not in SUBJECTS and allow_prefix and len(hit) == 1 and len(key(branch)) >= 12:
        TRUNCATED[branch] += 1                 # heading cut at the line end (institute-wise list only)
        branch = hit[0]
    if key(branch) not in SUBJECTS:
        raise SystemExit(f'unknown branch {branch!r} — add it to SUBJECTS')
    std = SUBJECTS[key(branch)]
    return std, 'diploma' if std.startswith('Diploma') else 'mdms'


def page_spans(page, y0min=93, y0max=568):
    """Text spans (each printed cell is its own span) inside the data area: (y0, x0, x1, text)."""
    out = []
    for b in page.get_text('rawdict')['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                t = clean(''.join(c['c'] for c in s['chars']))
                if t and y0min <= s['bbox'][1] <= y0max:
                    out.append((s['bbox'][1], s['bbox'][0], s['bbox'][2], t))
    return out


def colof(cols, xm):
    c = None
    for n, x in cols:
        if xm >= x:
            c = n
    return c


def cells(sp, cols, top, bot):
    c = collections.defaultdict(list)
    for y, x0, x1, t in sp:
        if top <= y < bot:
            c[colof(cols, (x0 + x1) / 2)].append((round(y), x0, t))
    return {k: ' '.join(t for _, _, t in sorted(v)) for k, v in c.items()}


def merit_no(s, where):
    if not re.fullmatch(r'\d+(\.\d+)?', s or ''):
        raise SystemExit(f'{where}: merit {s!r} is not a number')
    return float(s)


def air(s, where):
    m = re.fullmatch(r'(\d+)\.0', s or '')
    if not m:
        raise SystemExit(f'{where}: AIQ rank {s!r} is not N.0')
    return int(m.group(1))


CATGRP = re.compile(r'(OP|SE|EW|ST|SC)\s*(\d+(?:\.\d+)?)?')
ADMSEAT = re.compile(r'(OP|SE|EW|ST|SC|MQ|NRI)(PH)?\s*(GQ|UQ|IQ|MQ|NQ)')


def head_check(doc, title, label):
    t = clean(doc[0].get_text())
    if title not in t:
        raise SystemExit(f'{label}: heading {title!r} not found')
    return t


# ── 1. meritwise list ──
MCOLS = [('sr', 0), ('flag', 40), ('name', 53), ('merit', 230), ('cat', 266), ('catmerit', 287), ('score', 313),
         ('admcat', 343), ('seat', 370), ('aiq', 410), ('uid', 466), ('tmerit', 505), ('round', 558),
         ('college', 590), ('branch', 637)]
md = fitz.open(MERIT)
mt = head_check(md, 'Meritwise Allotment List', 'meritwise')
m = re.search(r'(Provisional|Final)\s+Meritwise Allotment List\s*-\s*Round\s*-\s*(\d+)', mt)
if not m:
    raise SystemExit('meritwise: title line changed')
STATUS, ROUND = m.group(1).lower(), int(m.group(2))
lines, footer_dates = [], collections.Counter()
for pg in md:
    ft = clean(pg.get_text())
    footer_dates.update(re.findall(r'\b(\d\d-\d\d-20\d\d)\b', ft))
    hdr = clean(pg.get_text(clip=fitz.Rect(0, 60, 841, 93)))
    if 'MERITNO' not in hdr or 'AIQ' not in hdr:
        raise SystemExit(f'meritwise p{pg.number + 1}: column headings changed')
    sp = page_spans(pg)
    anchors = sorted(y for y, x0, x1, t in sp if (x0 + x1) / 2 < 40 and t.isdigit())
    stray = [t for y, x0, x1, t in sp if (x0 + x1) / 2 < 40 and not t.isdigit()]
    if stray:
        raise SystemExit(f'meritwise p{pg.number + 1}: {len(stray)} non-numeric cells in the SR column')
    for i, a in enumerate(anchors):
        c = cells(sp, MCOLS, a - 5, anchors[i + 1] - 5 if i + 1 < len(anchors) else 569)
        uid = c.pop('uid', '')                                           # user ID: checked for shape, never kept
        if c.get('tmerit', '').startswith('NService-'):
            c['tmerit'] = 'I' + c['tmerit']         # 'INService-n' is wider than its cell: the leading I is clipped
        if not re.fullmatch(r'\d{5}', uid):
            raise SystemExit(f'meritwise p{pg.number + 1}: User ID cell has an unexpected shape')
        c.pop('name', None); c.pop('flag', None)                          # name, gender flag: never kept
        c['_page'] = pg.number + 1
        lines.append(c)
sn = sorted(int(x['sr']) for x in lines)
if sn != list(range(1, len(sn) + 1)):
    raise SystemExit(f'meritwise: SR is not 1..{len(sn)} — lines missing or read twice')

approved = {c['course'] for c in json.load(open(SHEET))['courses']}
rows = []
for x in lines:
    w = f"meritwise SR {x['sr']} (p{x['_page']})"
    extra = set(x) - {'sr', 'merit', 'cat', 'catmerit', 'score', 'admcat', 'seat', 'aiq', 'tmerit', 'round', 'college',
                      'branch', '_page'}
    if extra:
        raise SystemExit(f'{w}: text in unexpected columns {extra}')
    cg = CATGRP.fullmatch(clean(x.get('cat', '') + ' ' + x.get('catmerit', '')))
    asg = ADMSEAT.fullmatch(clean(x.get('admcat', '') + ' ' + x.get('seat', '')))
    if not cg or (cg.group(1) == 'OP') != (cg.group(2) is None):
        raise SystemExit(f'{w}: Cat / Cat Merit not readable')
    if not asg:
        raise SystemExit(f'{w}: ADM Cat / Seat Type not readable')
    if x.get('round') != f'{ROUND:02d}' or not re.fullmatch(r'\d+', x.get('score', '')):
        raise SystemExit(f'{w}: Adm Round / Score not readable')
    if not re.fullmatch(r'[A-Z]+', x.get('college', '')) or not x.get('branch'):
        raise SystemExit(f'{w}: college code / branch not readable')
    tm = x.get('tmerit', '')
    if tm and not re.fullmatch(r'[A-Za-z]+-\d+(\.\d+)?', tm):
        raise SystemExit(f'{w}: Adm Type Merit {tm!r} not readable')
    acat, ph, seat = asg.groups()
    ccat = cg.group(1)
    if (seat == 'MQ') != (acat == 'MQ') or (seat == 'NQ') != (acat == 'NRI') or (ph and seat != 'GQ' and seat != 'UQ'):
        raise SystemExit(f'{w}: allotted category {acat}{ph or ""} with seat type {seat}')
    if acat in ('SE', 'EW', 'SC', 'ST') and acat != ccat:
        raise SystemExit(f'{w}: reserved {acat} seat to a {ccat} candidate')
    std, section = course_of(x['branch'])
    if section != 'dnb' and std not in approved:
        raise SystemExit(f'{std!r} is not in specialty_sheet.json')
    mer = merit_no(x['merit'], w)
    rows.append({'sno': int(x['sr']), 'rank': int(mer), 'rank_ai': air(x['aiq'], w), 'quota_raw': seat,
                 'quota': QUOTA[seat], 'institute_raw': None, 'course_raw': x['branch'], 'course': std,
                 'section': section, 'allotted_category': acat + ('-PH' if ph else ''),
                 'allotted_category_raw': acat + (ph or ''), 'candidate_category': ccat,
                 'remarks': '; '.join(([f'merit {x["merit"]}'] if mer != int(mer) else []) +
                                      ([f'Adm Type Merit {tm}'] if tm else [])),
                 '_code': x['college'], '_merit': mer, '_catmerit': float(cg.group(2)) if cg.group(2) else None,
                 '_tmerit': tm})

# ── 2. institute-wise list ──
ICOLS = [('sr', 0), ('flag', 40), ('name', 53), ('merit', 235), ('cat', 272), ('score', 325), ('admcat', 360),
         ('seat', 398), ('aiq', 445), ('tmerit', 497), ('round', 570), ('pass', 598)]
idoc = fitz.open(INST)
head_check(idoc, 'Institute Wise Allotment List', 'institutewise')
names, ilines = {}, []
college = branch = None
for pg in idoc:
    sp = page_spans(pg)
    ev = []
    # heading lines start at the left margin and have nothing in the Seat Type column; data lines are anchored on SR
    for y in sorted({y for y, x0, x1, t in sp if x0 < 20 or (x0 + x1) / 2 < 40}):
        ln = sorted([s for s in sp if abs(s[0] - y) < 2], key=lambda s: s[1])
        seat_cell = any(398 <= s[1] and s[2] < 445 for s in sp if abs(s[0] - y) < 3.5)
        if seat_cell:
            if not ln[0][3].isdigit():
                raise SystemExit(f'institutewise p{pg.number + 1}: SR not a number')
            ev.append((y, 'row', None))
        else:
            ev.append((y, 'head', ln))
    ev.sort(key=lambda e: e[0])
    for i, (y, kind, ln) in enumerate(ev):
        if kind == 'head':
            if re.fullmatch(r'\d{3}', ln[0][3]):
                if len(ln) < 3 or not re.fullmatch(r'[A-Z]+', ln[1][3]):
                    raise SystemExit(f'institutewise p{pg.number + 1}: college heading not readable '
                                     f'{[(round(q[1]), re.sub("[A-Za-z]", "a", q[3])) for q in ln]}')
                code, nm = ln[1][3], clean(' '.join(s[3] for s in ln[2:]))
                if names.setdefault(code, nm) != nm:
                    raise SystemExit(f'institutewise: {code} printed with two names')
                college = code
            else:
                branch = clean(' '.join(s[3] for s in ln))
            continue
        c = cells(sp, ICOLS, y - 5, ev[i + 1][0] - 5 if i + 1 < len(ev) else 569)
        for k in ('name', 'flag', 'pass'):          # name, gender flag, pass college: never kept
            c.pop(k, None)
        w = f'institutewise p{pg.number + 1} {college} {branch} SR {c.get("sr")}'
        if set(c) - {'sr', 'merit', 'cat', 'score', 'admcat', 'seat', 'aiq', 'tmerit', 'round'}:
            raise SystemExit(f'{w}: text in unexpected columns')
        cg = CATGRP.fullmatch(c.get('cat', ''))
        asg = ADMSEAT.fullmatch(clean(c.get('admcat', '') + ' ' + c.get('seat', '')))
        if not (college and branch and cg and asg):
            raise SystemExit(f'{w}: line not readable')
        ilines.append((college, course_of(branch, True)[0], asg.group(3), asg.group(1) + (asg.group(2) or ''),
                       merit_no(c.get('merit'), w), air(c.get('aiq'), w), cg.group(1), c.get('tmerit', '')))

theirs = collections.Counter(ilines)
# clipped college codes in the meritwise list (e.g. NAMOME = NAMOMED: the cell is too narrow) → the unique code
# of the institute-wise list that starts with it
codes = {}
for r in rows:
    c = r['_code']
    if c not in codes:
        hit = [k for k in names if k == c] or [k for k in names if k.startswith(c)]
        if len(hit) != 1:
            raise SystemExit(f'college code {c!r} matches {hit} in the institute-wise list')
        codes[c] = hit[0]
for r in rows:
    r['_code'] = codes[r['_code']]
    r['institute_raw'] = names[r['_code']]
mine = collections.Counter((r['_code'], r['course'], r['quota_raw'], r['allotted_category_raw'], r['_merit'],
                            r['rank_ai'], r['candidate_category'], r['_tmerit']) for r in rows)
diff_a, diff_b = mine - theirs, theirs - mine
grp = lambda cnt: collections.Counter({k[:4]: 0 for k in cnt}) + collections.Counter(
    [k[:4] for k, n in cnt.items() for _ in range(n)])
gm, gt = grp(mine), grp(theirs)
group_mism = [(' | '.join(k), gm.get(k, 0), gt.get(k, 0)) for k in set(gm) | set(gt) if gm.get(k, 0) != gt.get(k, 0)]
if diff_a or diff_b:
    for a in diff_a:
        print('  differs (field, meritwise, institute-wise):', [(i, a[i], b[i]) for b in diff_b if b[:4] == a[:4] for i in range(4, 8) if a[i] != b[i]][:3])
if diff_a or diff_b or len(ilines) != len(rows):
    raise SystemExit(f'institute-wise check failed: {sum(diff_a.values())} meritwise lines not in it, '
                     f'{sum(diff_b.values())} of its lines not in the meritwise list; group mismatches {group_mism[:20]}')
inst_check = {'lines': len(ilines), 'lines_matched_seat_for_seat': len(rows), 'groups': len(gm),
              'group_count_mismatches': group_mism, 'colleges': len(names), 'clipped_codes': {k: v for k, v in codes.items() if k != v}}

# ── 3. last merit (closing merit per college × branch × quota × category) ──
ldoc = fitz.open(LAST)
head_check(ldoc, 'Last Merit - Round', 'last merit')
BLOCKS = {'GQ': [(234, 'OP'), (278, 'EW'), (318, 'SC'), (358, 'ST'), (399, 'SE')],
          'UQ': [(444, 'OP'), (482, 'EW'), (510, 'SC'), (547, 'ST'), (584, 'SE')],
          'IQ': [(648, 'OP'), (684, 'EW'), (720, 'SC'), (756, 'ST'), (792, 'SE')]}
XCOL = [(x, q, c) for q, v in BLOCKS.items() for x, c in v]
CODE_RE = re.compile(r'[A-Z]+(-MQ|-NQ)?')
last, pwd_zero, lbranch, lcode = {}, 0, None, None
for pg in ldoc:
    hdr = clean(pg.get_text(clip=fitz.Rect(0, 75, 841, 112)))
    if hdr.split()[:6] != ['Government', 'Seats', 'Institutional', 'Seats', 'Inservice', 'Seats']:
        raise SystemExit(f'last merit p{pg.number + 1}: headings changed: {hdr}')
    ws = [w for w in pg.get_text('words') if 112 < w[1] < 558]          # footer line (Page n of N, note) at y≈563
    used = {w for w in ws if (70 <= w[0] < 85 and w[4] == '*')}         # '*' = government college
    ev = [(w[1], 'code', w[4]) for w in ws if 85 <= w[0] < 95 and CODE_RE.fullmatch(w[4])]
    ev += [(w[1], 'pwd', None) for w in ws if 80 <= w[0] < 88 and w[4] == 'PWD']
    ev += [(y, 'head', clean(' '.join(w[4] for w in sorted(ws, key=lambda w: w[0]) if abs(w[1] - y) < 2)))
           for y in sorted({w[1] for w in ws if 70 <= w[0] < 85 and re.search('[a-z]', w[4])})]
    used |= {w for w in ws if (85 <= w[0] < 95 and CODE_RE.fullmatch(w[4])) or (80 <= w[0] < 88 and w[4] == 'PWD')}
    prev = None
    for y, kind, v in sorted(ev):
        if kind == 'head':
            lbranch = clean(lbranch + ' ' + v) if prev == 'head' else v      # long branch names wrap onto 2 lines
            prev = kind
            used |= {w for w in ws if abs(w[1] - y) < 2}
            continue
        prev = kind
        std = course_of(lbranch)[0]
        if kind == 'code':
            lcode, q = (v.split('-') + [None])[:2]
            band = lambda w: -9 <= w[1] - y <= -3        # a college's values sit ~6 pt above its code
        else:
            q = 'PWD'
            band = lambda w: abs(w[1] - y) < 2           # "PWD" line under the college: GQ PwD closing merit, 0.0 = none
        for w in ws:
            if not band(w) or w[0] < 190 or w in used:
                continue
            if not re.fullmatch(r'\d+(\.\d+)?', w[4]):
                raise SystemExit(f'last merit p{pg.number + 1}: {w[4]!r} in a value cell')
            hit = [(qq, cc) for x, qq, cc in XCOL if abs(w[2] - x) <= 6]
            if len(hit) != 1:
                raise SystemExit(f'last merit p{pg.number + 1}: value at x={w[2]:.0f} is in no column')
            qq, cc = hit[0]
            used.add(w)
            if q in ('MQ', 'NQ'):      # code-MQ / code-NQ lines: one value, in the first column
                if (qq, cc) != ('GQ', 'OP'):
                    raise SystemExit(f'last merit p{pg.number + 1}: {v} value outside the first column')
                qq, cc = q, ('MQ' if q == 'MQ' else 'NRI')
            elif q == 'PWD':
                if qq != 'GQ':
                    raise SystemExit(f'last merit p{pg.number + 1}: PWD value outside the Government block')
                if float(w[4]) == 0:
                    pwd_zero += 1
                    continue
                cc += 'PH'
            k = (lcode, std, qq, cc)
            if k in last:
                raise SystemExit(f'last merit: {k} printed twice')
            last[k] = float(w[4])
    left = [w for w in ws if w not in used]
    if left:
        raise SystemExit(f'last merit p{pg.number + 1}: {len(left)} words not read: {[(round(w[0]), round(w[1]), w[4]) for w in left][:30]}')

# which merit each block prints (found by matching every group): Government OPEN = general MERITNO, Government
# EWS/SC/ST/SE = Cat Merit, Institutional / Inservice / NRI = the number in Adm Type Merit (university / in-service /
# NRI merit), Management = general MERITNO, PWD line = PwD merit (not printed in the allotment lists: checked for
# presence and order only). 99999 = seat conversion (no seat to check).
num = lambda t: float(t.split('-', 1)[1]) if t else None


def block_merit(r):
    q, c = r['quota_raw'], r['allotted_category_raw']
    if q == 'GQ':
        return r['_merit'] if c == 'OP' else r['_catmerit']
    if q == 'MQ':
        return r['_merit']
    return num(r['_tmerit'])


groups = collections.defaultdict(list)
for r in rows:
    groups[(r['_code'], r['course'], r['quota_raw'], r['allotted_category_raw'])].append(r)
lm_mism, lm_unprinted, lm_ok, lm_ph = [], [], 0, []
for k in sorted(set(groups) | set(last)):
    if k not in groups:
        if last[k] != 99999:
            lm_mism.append({'group': ' | '.join(k), 'printed': last[k], 'parsed': None})
        continue
    if k not in last:
        lm_unprinted.append({'group': ' | '.join(k), 'seats': len(groups[k])})
        continue
    if k[3].endswith('PH'):
        lm_ph.append((max(r['_merit'] for r in groups[k]), last[k], k)); lm_ok += 1
        continue
    vals = [block_merit(r) for r in groups[k]]
    if None in vals or max(vals) != last[k]:
        lm_mism.append({'group': ' | '.join(k), 'printed': last[k], 'parsed': None if None in vals else max(vals)})
    else:
        lm_ok += 1
lm_ph.sort()
if [p for _, p, _ in lm_ph] != sorted(p for _, p, _ in lm_ph):
    raise SystemExit('last merit: PwD merits are not in general-merit order')
if lm_mism:
    raise SystemExit(f'last merit check failed: {lm_mism[:20]}')
if sum(x['seats'] for x in lm_unprinted) > 20:
    raise SystemExit(f'last merit: {len(lm_unprinted)} groups not printed — layout changed? {lm_unprinted[:10]}')
last_check = {'groups_printed': len(last), 'groups_matched': lm_ok, 'pwd_lines_zero_values': pwd_zero,
              'pwd_groups': len(lm_ph), 'groups_with_seats_not_printed': lm_unprinted, 'mismatches': lm_mism,
              'rule': 'Government OPEN + Management = MERITNO; Government EWS/SC/ST/SE = Cat Merit; Institutional / '
                      'Inservice / NRI = Adm Type Merit number; PWD line = PwD merit (order-checked only)'}

# ── 4. optional: every (merit, AIQ rank) pair is in the loaded merit list ──
bridge_check = None
if BRIDGE:
    br = json.load(open(BRIDGE))
    pairs = {(x['state_rank'], x['air']) for x in br['rows']}
    by_rank = collections.defaultdict(set)
    for x in br['rows']:
        by_rank[x['state_rank']].add(x['air'])
    miss = [r['sno'] for r in rows if (r['rank'], r['rank_ai']) not in pairs]
    bridge_check = {'file': os.path.basename(BRIDGE), 'list': br.get('list_name'), 'pairs_found': len(rows) - len(miss),
                    'pairs_missing_sno': miss[:50], 'n_missing': len(miss)}
    del br, pairs, by_rank

for r in rows:
    for k in [k for k in r if k.startswith('_')]:
        del r[k]
rows.sort(key=lambda x: x['sno'])
dates = [d for d, _ in footer_dates.most_common()]
C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'lines': len(rows), 'sr_1_to_n': True, 'pages': len(md), 'by_section': C('section'), 'by_quota': C('quota'),
          'by_quota_raw': C('quota_raw'), 'by_allotted_category': C('allotted_category'), 'by_course': C('course'),
          'colleges': len({x['institute_raw'] for x in rows}),
          'institutewise': inst_check, 'truncated_branch_headings_institutewise': dict(TRUNCATED),
          'last_merit': last_check, 'merit_list_bridge': bridge_check,
          'rank_ai': {'source': "printed 'AIQ Rank' column (N.0)", 'filled': sum(1 for x in rows if x['rank_ai']),
                      'of': len(rows)},
          'half_merit_rows': sum(1 for x in rows if x['remarks'].startswith('merit ')),
          'state_rank': [min(x['rank'] for x in rows), max(x['rank'] for x in rows)],
          'ai_rank': [min(x['rank_ai'] for x in rows), max(x['rank_ai'] for x in rows)]}
pub = re.fullmatch(r'(\d\d)-(\d\d)-(\d{4})', dates[0]) if dates else None
out = {'authority_code': 'acpmec', 'round': f'Round {ROUND}', 'round_order': ROUND, 'status': STATUS,
       'title': f'{STATUS.title()} Meritwise Allotment List - Round - {ROUND:02d} (MD / MS / DIPLOMA / DNB)',
       'published_on': f'{pub.group(3)}-{pub.group(2)}-{pub.group(1)}' if pub else None,
       'source_file_name': os.path.basename(MERIT),
       'notes': 'ACPPGMEC Gujarat. institute_raw = college name printed in the institute-wise list for the college '
                'code. rank = MERITNO (half numbers stored as floor, exact number in remarks); rank_ai = printed AIQ '
                'Rank. Cross-checked seat for seat against the institute-wise list and group by group against Last '
                'Merit. DNB seats kept as published (section dnb).',
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print('lines', len(rows), '| by section', checks['by_section'])
print('by quota', checks['by_quota'])
print('by allotted category', checks['by_allotted_category'])
print(f"institute-wise: {len(ilines)} lines, all matched seat for seat; {len(gm)} groups, 0 count mismatches")
print(f"last merit: {lm_ok}/{len(last)} printed groups match; {len(lm_unprinted)} groups with seats not printed "
      f"({sum(x['seats'] for x in lm_unprinted)} seats); PwD lines {len(lm_ph)}")
if bridge_check:
    print(f"merit-list bridge: {bridge_check['pairs_found']}/{len(rows)} (merit, AIQ rank) pairs found")
print('colleges', checks['colleges'], '| state ranks', checks['state_rank'], '| AI ranks', checks['ai_rank'],
      '| published', out['published_on'], out['status'])
