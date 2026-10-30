"""Gujarat NEET PG 2026-27 Round 1 (ACPPGMEC, 27.10.2026) → standardised seat rows, bridged to Gujarat's 2025 cut-offs.
  matrix — "Tentative Vacant Seat for Round - 01 (MD/MS/DIPLOMA/DNB)": per page two columns of course blocks
           (course code + name, then one line per college code × quota, e.g. AMED-GQ, with OP / SC / ST / SE / EWS / TOT,
           then the course's total line); section totals 1-MD/MS, 2-Diploma and Total; p17 course × quota summary,
           p18 MD / MS / Diploma × quota summary. Zeros sit on grey fills, so cells are read from word positions.
  dnb    — "In Service Reservation (10%) for NBEMS courses — post-MBBS Diploma / DNB" (a SCANNED image, no text layer):
           transcribed by hand below and pinned to the file's SHA-256, so a re-issued file stops the script.
  pwd    — optional "Vacancy PwD Round -01": the matrix lines that hold a PwD seat (PwD is horizontal, inside the
           line's TOT). Checked line by line against the matrix; it adds no seats.
Every printed number is checked: each line's categories add to its TOT, each course block's lines add to its total
line, course totals add to the section and grand totals, and the parsed seats equal both summary pages.
Run with /usr/bin/python3 (PyMuPDF):
    gujarat.py <matrix.pdf> <dnb.pdf> [<pwd.pdf>] <cutoffs2025.json> <out.json>"""
import re, sys, os, json, hashlib, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

if len(sys.argv) not in (5, 6):
    raise SystemExit(__doc__)
MATRIX, DNB = sys.argv[1:3]
PWD = sys.argv[3] if len(sys.argv) == 6 else None
CUTS, OUT = sys.argv[-2:]

COLLEGES = {  # PDF college code → standard institute name (exactly as in the 2025 Gujarat cut-offs)
    'AMED': 'B. J. Medical College, Ahmedabad',
    'BMED': 'Government Medical College, Baroda',
    'SMED': 'Government Medical College, Surat',
    'RMED': 'Pandit Deendayal Upadhyay Medical College, Rajkot',
    'JMED': 'Shri M.P. Shah Government Medical College, Jamnagar',
    'BHMED': 'Government Medical College, Bhavnagar',
    'IKDMED': 'Smt. G.R. Doshi and Smt. K.M. Mehta Institute of Kidney Diseases and Research Centre, Ahmedabad',
    'BHUMED': 'Gujarat Adani Institute of Medical Sciences, Bhuj',
    'CUMED': 'CU Shah Medical College, Surendranagar',
    'GCSMED': 'GCS Medical College and Research Center, Ahmedabad',
    'GOTMED': 'GMERS Medical College, Gotri, Vadodara',
    'KMED': 'Pramukh Swami Medical College, Karamsad',
    'NAMOMED': 'Narendra Modi Medical College, Ahmedabad',
    'NHL': 'Smt. N.H.L. Municipal Medical College, Ahmedabad',
    'SMC': 'Surat Municipal Institute of Medical Education & Research (SMIMER), Surat',
    'SOLMED': 'GMERS Medical College, Sola, Ahmedabad',
    'GMED': 'GMERS Medical College, Gandhinagar',
    'PATMED': 'GMERS Medical College, Dharpur, Patan',
    'HIMMED': 'GMERS Medical College, Himmatnagar',
    'PRMED': 'Parul Institute of Medical Sciences & Research, Vadodara',
    'MKMED': 'Dr. M.K. Shah Medical College & Research Centre, Ahmedabad',
    'JUMED': 'GMERS Medical College, Junagadh',
    'AMRMED': 'Shantabaa Medical College & General Hospital, Amreli',
    'NDMED': 'Dr. N.D. Desai Faculty of Medical Science and Research, Nadiad',
    'VISMED': 'Nootan Medical College and Research Centre, Visnagar',
    'SWAMED': 'Swaminarayan Institute of Medical Sciences & Research, Kalol, Gandhinagar',
    'KIRMED': 'Kiran Medical College, Surat',
    'ZYMED': 'Zydus Medical College and Hospital, Dahod',
    'ANAMED': 'Ananya College of Medicine & Research, Kalol, Gandhinagar',
    'VADMED': 'GMERS Medical College, Vadnagar',
    'VALMED': 'GMERS Medical College, Valsad'}
QUOTAS = {'GQ': 'State Quota', 'UQ': 'Institutional Quota', 'IQ': 'In-service Quota',   # the PDF's own key line
          'MQ': 'Management Quota', 'NQ': 'NRI Quota'}
key = lambda s: re.sub(r'[^a-z]', '', (s or '').lower())
SUBJECTS = {  # PDF course name (block heading or summary page; lower-case letters only) → approved course name
    'anaesthesiology': 'MD - Anaesthesiology', 'biochemistry': 'MD - Biochemistry',
    'communitymedicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'dermatologyvenereologyleprosy': 'MD - Dermatology', 'emergencymedicine': 'MD - Emergency Medicine',
    'forensicmedicine': 'MD - Forensic Medicine', 'generalmedicine': 'MD - General Medicine',
    'immunohaematologybloodtransfusion': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'immunohaematologyblood': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'microbiology': 'MD - Microbiology', 'paediatrics': 'MD - Paediatrics', 'pathology': 'MD - Pathology',
    'pharmacology': 'MD - Pharmacology', 'physiology': 'MD - Physiology', 'psychiatry': 'MD - Psychiatry',
    'radiodiagnosis': 'MD - Radio-Diagnosis',
    'radiationoncology': 'MD - Radiotherapy / Radiation Oncology', 'radiatononcology': 'MD - Radiotherapy / Radiation Oncology',
    'tuberculosisrespiratorymedicine': 'MD - Respiratory Medicine',
    'palliativemedicine': 'MD - Palliative Medicine', 'palliatvemedicine': 'MD - Palliative Medicine',   # "ti" ligature lost
    'anatomy': 'MD/MS - Anatomy', 'generalsurgery': 'MS - General Surgery',
    'obstetricsgynaecology': 'MS - Obstetrics and Gynaecology', 'ophthalmology': 'MS - Ophthalmology',
    'orthopaedics': 'MS - Orthopaedics', 'otorhinolaryngologyent': 'MS - ENT (Otorhinolaryngology)',
    'diplomainanesthesiologyda': 'Diploma in Anaesthesiology',
    'diplomaincommunitymedicinedcm': 'Diploma in Community Medicine/Preventive and Social Medicine',
    'diplomainobstetricsgynecologydgo': 'Diploma in Obstetrics and Gynaecology',
    'diplomainobstetricsgynecology': 'Diploma in Obstetrics and Gynaecology',
    'diplomainpaediatricsdch': 'Diploma in Child Health / Paediatrics',
    'diplomainpublichealthdph': 'Diploma in Public Health',
    'diplomaintuberculosischestdiseasesdtcd': 'Diploma in Respiratory Medicine',
    'diplomaintuberculosischestdiseases': 'Diploma in Respiratory Medicine'}
CATS = ['OP', 'SC', 'ST', 'SE', 'EWS']

# ── DNB file: scanned, hand-transcribed (S.No., hospital, course, category, seats); no PwD seat is marked "YES" ──
DNB_SHA256 = '040894f9c2504a1377502c4657b36d3590f9da9e5b9099cc6239bf3da7c62277'
HOSPITALS = {  # hospital in the DNB file → standard name (2025 cut-off name where the college exists there)
    'Valsad': 'GMERS Medical College, Valsad', 'Vadnagar': 'GMERS Medical College, Vadnagar',
    'Himmatnagar': 'GMERS Medical College, Himmatnagar',
    'Navsari': 'GMERS Medical College, Navsari', 'Porbandar': 'GMERS Medical College, Porbandar',     # new (not in 2025)
    'Rajpipla': 'GMERS Medical College, Rajpipla', 'Deesa': 'General Hospital (Sub District Hospital), Deesa'}
DNB_POST_MBBS = [  # p1 "FOR POST MBBS DNB SEATS"
    (1, 'Valsad', 'Anaesthesiology', 'ST', 1), (2, 'Navsari', 'Anaesthesiology', 'OBC', 1),
    (3, 'Porbandar', 'Obstetrics and Gynaecology', 'SC', 1), (4, 'Vadnagar', 'Orthopaedics', 'UR', 1),
    (5, 'Himmatnagar', 'Paediatrics', 'ST', 1), (6, 'Porbandar', 'Pathology', 'OBC', 1),
    (7, 'Rajpipla', 'Pathology', 'EWS', 1), (8, 'Navsari', 'Pathology', 'UR', 1)]
DNB_DIPLOMA = [  # p2 "FOR POST MBBS DIPLOMA DNB SEATS" (NBEMS post-MBBS diplomas, named like rajasthan.py's)
    (1, 'Vadnagar', 'Diploma in Anaesthesiology', 'UR', 1), (2, 'Vadnagar', 'Diploma in Obstetrics and Gynaecology', 'OBC', 1),
    (3, 'Deesa', 'Diploma in Child Health / Paediatrics', 'EWS', 1), (4, 'Himmatnagar', 'Diploma in Radio Diagnosis', 'SC', 1),
    (5, 'Porbandar', 'Diploma in Radio Diagnosis', 'UR', 1)]


def side_events(page, cols, labels=('1-MD/MS', '2-Diploma', 'Total')):
    """One page → per column-half (left, then right) the blocks in reading order:
    ('course', code, name) · ('row', sl, star, code, quota, values) · ('total', values) · ('section', label, values).
    cols = right edges of the value columns on the left half; the right half is the same grid shifted by OFF."""
    OFF = 266
    words = page.get_text('words')
    out = []
    for side in (0, 1):
        off = OFF * side
        ws = [w for w in words if ((w[0] + w[2]) / 2 >= 297) == bool(side) and 88 < (w[1] + w[3]) / 2 < 805]
        ym = lambda w: (w[1] + w[3]) / 2
        nums, anchors, heads, stars, labs, other = [], [], [], [], [], []
        for w in ws:
            t, x0, x1 = w[4], w[0] - off, w[2] - off
            col = next((i for i, c in enumerate(cols) if abs(x1 - c) <= 4), None)
            m = re.fullmatch(r'([A-Z]+)-(IQ|UQ|GQ|MQ|NQ)', t)
            if t.isdigit() and col is not None and x0 > 125:
                nums.append((ym(w), col, int(t)))
            elif m:
                anchors.append((ym(w), m.group(1), m.group(2)))
            elif re.fullmatch(r'[123]\d\d', t) and x0 < 38:
                heads.append((ym(w), t))
            elif t.isdigit() and 38 <= x0 <= 42:
                other.append((ym(w), 'sl', int(t)))
            elif t == '*':
                stars.append(ym(w))
            elif t in labels and x0 < 120:
                labs.append((ym(w), t))
            elif x0 >= 60:
                other.append((ym(w), 'name', w))
        nums.sort()
        clusters = []
        for y, c, v in nums:   # value lines: numbers within 3.5 pt of each other
            if clusters and y - clusters[-1]['y1'] <= 3.5:
                cl = clusters[-1]
            else:
                cl = {'y0': y, 'y1': y, 'vals': {}}; clusters.append(cl)
            if c in cl['vals']:
                raise SystemExit(f'p{page.number + 1}: two numbers in one cell near y={y:.0f}')
            cl['vals'][c] = v; cl['y1'] = y
        for cl in clusters:
            cl['y'] = (cl['y0'] + cl['y1']) / 2
        ev = []
        for y, code, q in anchors:
            cl = [c for c in clusters if abs(c['y'] - y) <= 5]
            if len(cl) != 1:
                raise SystemExit(f'p{page.number + 1}: {code}-{q} has {len(cl)} value lines')
            cl[0]['used'] = True
            sl = [v for yy, k, v in other if k == 'sl' and abs(yy - y) <= 5]
            if len(sl) != 1:
                raise SystemExit(f'p{page.number + 1}: {code}-{q} has no S.No.')
            ev.append((y, 'row', sl[0], any(abs(s - y) <= 5 for s in stars), code, q, cl[0]['vals']))
        for cl in clusters:
            if cl.get('used'):
                continue
            lab = [t for y, t in labs if abs(y - cl['y']) <= 6]
            ev.append((cl['y'], 'section', lab[0], cl['vals']) if lab else (cl['y'], 'total', cl['vals']))
        for y, code in heads:
            nxt = min([e[0] for e in ev if e[0] > y] + [9999])
            name = ' '.join(w[4] for yy, k, w in sorted(other, key=lambda o: (round(o[0]), o[2][0] if o[1] == 'name' else 0))
                            if k == 'name' and y - 4 <= yy < nxt - 6)
            ev.append((y, 'course', code, name))
        out += [e[1:] for e in sorted(ev, key=lambda e: e[0])]
    return out


def subject(name):
    if key(name) not in SUBJECTS:
        raise SystemExit(f'unknown course {name!r}')
    return SUBJECTS[key(name)]


def parse_blocks(doc, pages, cols, ncat, label):
    """Walk the course blocks. Returns {(course, college code, quota): values}, the star flags, the PwD column (if any)
    and the printed section totals; checks every line, every block total and the S.No. sequence of every block."""
    lines, star, sections, pwd = {}, {}, {}, {}
    course = code_now = None
    acc, sl_next, closed = None, 1, True
    for p in pages:
        for e in side_events(doc[p], cols):
            if e[0] == 'course':
                c = subject(e[2])
                if c == course and not closed:        # the block continues on the next column / page
                    continue
                if not closed:
                    raise SystemExit(f'{label}: {course} has no total line')
                course, code_now, acc, sl_next, closed = c, e[1], [0] * (ncat + 1), 1, False
            elif e[0] == 'row':
                _, sl, st, code, q, vals = e
                if closed or sl != sl_next:
                    raise SystemExit(f'{label}: {course} line {sl} {code}-{q} out of sequence (expected {sl_next})')
                if code not in COLLEGES:
                    raise SystemExit(f'{label}: unknown college code {code!r}')
                v = [vals.get(i) for i in range(len(cols))]
                cats, tot = v[:5], v[-1]
                if None in cats or tot is None or sum(cats) != tot:
                    raise SystemExit(f'{label}: {course} {code}-{q} categories {cats} ≠ TOT {tot}')
                if (course, code, q) in lines:
                    raise SystemExit(f'{label}: {course} {code}-{q} printed twice')
                lines[(course, code, q)] = cats + [tot]
                if ncat == 6:
                    pwd[(course, code, q)] = v[5] or 0
                star.setdefault(code, set()).add(st)
                acc = [a + b for a, b in zip(acc, cats + [tot])]
                sl_next += 1
            elif e[0] == 'total':
                v = [e[1].get(i) for i in range(len(cols))]
                printed = v[:5] + [v[-1]]
                if closed or acc != printed:
                    raise SystemExit(f'{label}: {course} lines add to {acc}, block total line {printed}')
                closed = True
            else:
                v = [e[2].get(i) for i in range(len(cols))]
                sections[e[1]] = v
    if not closed:
        raise SystemExit(f'{label}: {course} has no total line')
    return lines, star, sections, pwd


rows, checks = [], {}

# ── main matrix ──
doc = fitz.open(MATRIX)
if 'Tentative Vacant Seat for Round - 01' not in clean(doc[0].get_text()):
    raise SystemExit('matrix heading changed')
block_pages = [p for p in range(len(doc)) if re.search(r'\b[A-Z]+-(IQ|UQ|GQ|MQ|NQ)\b', doc[p].get_text())]
if block_pages != list(range(16)) or len(doc) != 18:
    raise SystemExit(f'matrix page layout changed: block pages {block_pages}, {len(doc)} pages')
lines, star, sections, _ = parse_blocks(doc, block_pages, [153, 178, 202, 226, 254, 285], 5, 'matrix')
# the '*' marks exactly the government colleges (no MQ / NQ lines); a college is either always or never starred
for code, s in star.items():
    if len(s) != 1:
        raise SystemExit(f'{code} is starred on some lines only')
is_md = lambda c: c.startswith('MD')          # MD/MS - Anatomy counts under MD on the summary page
is_dip = lambda c: c.startswith('Diploma')
grp = lambda c: 'DIPLOMA' if is_dip(c) else ('MD' if is_md(c) else 'MS')
col_sum = lambda pick: [sum(v[i] for k, v in lines.items() if pick(k[0])) for i in range(6)]
want_sec = {'1-MD/MS': col_sum(lambda c: not is_dip(c)), '2-Diploma': col_sum(is_dip), 'Total': col_sum(lambda c: True)}
if sorted(sections) != sorted(want_sec):
    raise SystemExit(f'section total lines found: {sorted(sections)}')
for lab, got in want_sec.items():
    printed = sections[lab]
    for i, cat in enumerate(CATS + ['TOT']):
        checks[f'matrix {lab} {cat}'] = (got[i], printed[i])

# summary pages: course × quota (p17) and MD / MS / Diploma × quota (p18)
QORDER = ['IQ', 'UQ', 'GQ', 'MQ', 'NQ']
by_cq = collections.Counter()
for (c, code, q), v in lines.items():
    by_cq[(c, q)] += v[-1]
for p, keyfn, lab in ((16, subject, 'course'), (17, lambda s: s, 'type')):
    g = grids(doc[p])[0]
    if [clean(x) for x in g[0][2:8]] != QORDER + ['Total']:
        raise SystemExit(f'summary p{p + 1} headings changed: {g[0]}')
    seen = set()
    for r in g[1:]:
        name, vals = clean(r[1]), [int(clean(x)) for x in r[2:8]]
        if sum(vals[:5]) != vals[5]:
            raise SystemExit(f'summary p{p + 1}: {name} quotas {vals[:5]} ≠ total {vals[5]}')
        if name == 'Total':
            got = [sum(v for (c, q), v in by_cq.items() if q == qq) for qq in QORDER]
            for qq, a, b in zip(QORDER + ['Total'], got + [sum(got)], vals):
                checks[f'summary p{p + 1} Total {qq}'] = (a, b)
            continue
        k = keyfn(name)
        seen.add(k)
        pick = (lambda c: c == k) if lab == 'course' else (lambda c: grp(c) == k)
        got = [sum(v for (c, q), v in by_cq.items() if q == qq and pick(c)) for qq in QORDER]
        if got + [sum(got)] != vals:
            raise SystemExit(f'summary p{p + 1}: {name} parsed {got + [sum(got)]}, printed {vals}')
        if lab == 'type':
            checks[f'summary p18 {name}'] = (sum(got), vals[5])
    every = {c for c, q in by_cq} if lab == 'course' else {grp(c) for c, q in by_cq}
    if seen != every:
        raise SystemExit(f'summary p{p + 1} rows {sorted(seen)} ≠ parsed {sorted(every)}')
    if lab == 'course':
        checks['course blocks (each checked against its total line) = summary p17 rows'] = (len(every), len(seen))
for (c, code, q), v in lines.items():
    for cat, n in zip(CATS, v[:5]):
        if n:
            rows.append({'college': COLLEGES[code], 'course': c, 'quota': QUOTAS[q], 'seats': n,
                         'section': 'diploma' if is_dip(c) else 'mdms', 'category': cat})
checks['matrix seats'] = (sum(x['seats'] for x in rows), want_sec['Total'][-1])

# ── PwD vacancy list: must be a subset of the matrix (same line, same numbers) ──
if PWD:
    pd = fitz.open(PWD)
    if len(pd) != 1 or 'Vacancy Pwd Round -01' not in clean(pd[0].get_text()):
        raise SystemExit('PwD list layout changed')
    plines, _, psec, pcount = parse_blocks(pd, [0], [153, 178, 202, 226, 247, 268, 292], 6, 'pwd')
    for k, v in plines.items():
        if lines.get(k) != v:
            raise SystemExit(f'PwD line {k} {v} is not the matrix line {lines.get(k)} — PwD seats would be extra')
        if pcount[k] < 1 or pcount[k] > v[-1]:
            raise SystemExit(f'PwD line {k}: {pcount[k]} PwD of {v[-1]}')
    psum = [sum(v[i] for v in plines.values()) for i in range(6)]
    for lab in ('1-MD/MS', 'Total'):
        pr = [psec[lab][i] for i in (0, 1, 2, 3, 4, 6)]
        checks[f'pwd {lab} TOT'] = (psum[-1], pr[-1])
        if psum != pr:
            raise SystemExit(f'PwD {lab}: lines add to {psum}, printed {pr}')
    checks['pwd PwD seats'] = (sum(pcount.values()), psec['Total'][5])
    checks['pwd lines found in matrix'] = (sum(1 for k in plines if k in lines), len(plines))

# ── DNB file (scanned) ──
if hashlib.sha256(open(DNB, 'rb').read()).hexdigest() != DNB_SHA256:
    raise SystemExit('the DNB PDF is not the file transcribed below — re-read it and update DNB_POST_MBBS / DNB_DIPLOMA')
dd = fitz.open(DNB)
if len(dd) != 2 or any(clean(pg.get_text()) for pg in dd):
    raise SystemExit('the DNB PDF now has a text layer / other pages — parse it instead of the transcription')
for table, sec in ((DNB_POST_MBBS, 'dnb'), (DNB_DIPLOMA, 'diploma')):
    if [t[0] for t in table] != list(range(1, len(table) + 1)):
        raise SystemExit('DNB S.No. sequence broken')
    for _, h, course, cat, n in table:
        rows.append({'college': HOSPITALS[h], 'quota': 'DNB Quota (In-service)' if sec == 'dnb' else 'Diploma Quota (In-service)',
                     'course': f'DNB - {course} (Post-MBBS)' if sec == 'dnb' else course,
                     'seats': n, 'section': sec, 'category': cat,
                     # the 2025 cut-offs file every GMERS college as 'Private Institute' — keep new ones the same
                     'institute_type': 'Private Institute' if HOSPITALS[h].startswith('GMERS') else 'Government Institute'})
checks['dnb Post-MBBS DNB S.No.'] = (len(DNB_POST_MBBS), 8)          # last S.No. printed on p1
checks['dnb Post-MBBS Diploma S.No.'] = (len(DNB_DIPLOMA), 5)        # last S.No. printed on p2

FAMILY = {'State Quota': ('Government Quota$',), 'Institutional Quota': ('Institutional Quota',),
          'In-service Quota': ('Government Quota-Inservice',), 'Management Quota': ('Management Quota',),
          'NRI Quota': ('NRI Quota',), 'DNB Quota (In-service)': ('DNB',), 'Diploma Quota (In-service)': ('Diploma Quota',)}


def cat_match(x):
    if x['quota'] == 'Management Quota':
        return ('MQ',)
    if x['quota'] == 'NRI Quota':
        return ('NRI',)
    return ({'EWS': 'EW', 'OBC': 'SE', 'UR': 'OP'}.get(x['category'], x['category']),)


cuts = load_cuts(CUTS, 'Gujarat')
known = {c['institute'] for c in cuts}
missing = sorted(set(COLLEGES.values()) - known)
if missing:
    raise SystemExit(f'college map points at names not in the 2025 cut-offs: {missing}')
out = build(rows, cuts, 'Gujarat', 'GJ', lambda q: FAMILY[q], cat_match)
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
