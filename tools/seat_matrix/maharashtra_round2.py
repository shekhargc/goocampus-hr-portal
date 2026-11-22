"""Maharashtra NEET PGM 2026 CAP Round 2 (State CET Cell, dated 21.11.2026) → Round 2 seat rows for a SEPARATE body
"Maharashtra — Round 2 — State Counselling" (authority `cetcell_mh`, round_no 2, list_type vacancy). The Round 1 body
("Maharashtra — State Counselling", 2,759 seats) is never touched.

Sources (both text layer):
  matrix   "Admissions to NEET(PGM) Courses, 2026-2027 (CAP Round: 2.0) Provisional Seat Matrix for CAP Round 2"
           (inbox 1904, 23 pages). One block per college ("College: 01101 GRANT GOVERNMENT MEDICAL COLLEGE MUMBAI"),
           one line per course code (4 digits + quota letter: S = state lines, I = Institutional quota, N = NRI,
           A = All India quota — Vikhe Patil + NKP Salve, as in Round 1) and a "G" (general) + optional "P" (PwD) line,
           27 '|' fields: GENERAL QUOTA SC ST VJ N1 N2 N3 OBC | Tot Res | SE EW OPN ORP ORC | INSERVICE SC ST VJ N1 N2
           N3 OBC SE EW OPEN | Min IQ NRI | Tot. (the two AIQ colleges head the IQ column "AIQ"). Blank = 0. "* * Total * *" under every college and a
           "* * Grand Total * *" line at the end (1,880 seats).
           It is the list of seats OPEN FOR ROUND 2 (Round 1 left-overs) — not the full matrix: every college prints fewer
           seats than its Round 1 matrix (e.g. Grant 81 vs 122), so list_type is 'vacancy'.
  virtual  "Virtual Vacancy for round 2 Dated 21/11/2026" (inbox 1903, 57 pages): per college Sr.No | code : subject |
           quota (OPEN, OBC, IS OPEN, PH SC, I.Q., AIQ, MINORITY, NRI …) | seats, a "Total :" per college. Footnote:
           seats presently occupied by candidates who have not filled the status-retention form and are likely to opt
           for the next round. They are NOT inside the matrix (checked: they are extra seats that may fall vacant), so
           they are counted and checked here but NOT stored as seats (pass --virtual to only print the comparison).

Stored labels = Round 1 (maharashtra.py) labels, so rounds compare line for line: quota State Quota / In-service Quota
(INSERVICE columns) / Institutional Quota (IQ on I lines) / All India Quota (IQ on A lines) / NRI Quota / Minority Quota
(JIIU Jalna); categories SC ST VJ NT-B NT-C NT-D OBC SEBC EWS OPEN, PwD line → "-PwD". Orphan seats: the ORP (Orphan A/B)
and ORC (Orphan-C) cells print the seat's category ("1VJ", "1NC" …) → "<category>-Orphan" (Round 1 spelling; here they
are separate seats, counted in Tot.). College names / courses: COLLEGES and SUBJECTS of maharashtra.py are read from
that file (ast, one source of truth); the Round-2 printed names map onto those 2025 names (CET_NAMES below), the subject
code (last two digits of the course code) onto the Round 1 course names.

Checks (hard): page heading / date / column headings; Sr. No 1…n per college; every G / P line's Tot Res = its SC…OBC
cells; every subject's cells (G + P) = its Tot.; S lines have no IQ / NRI, I / A lines only IQ, N lines only NRI;
every college's lines = its Total line (all 27 columns, orphan cells counted as numbers); every column of the college
Total lines = Grand Total and the parsed seats = 1,880; the virtual list's per-college totals and pages.
Round 1 comparison (from the stored Round 1 rows, seatmatrix-dump body=…): per college × course, seats this round vs
Round 1 — lines above Round 1 = new seats → new_in_round (spread over the line's rows, State Quota first).
Run with /usr/bin/python3 (PyMuPDF):
  maharashtra_round2.py <matrix_1904.pdf> <virtual_1903.pdf> <round1_dump.json> <cutoffs2025.json> <out.json>"""
import ast, collections, json, os, re, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report

if len(sys.argv) != 6:
    raise SystemExit(__doc__)
PDF, VPDF, R1, CUTS, OUT = sys.argv[1:6]

_src = ast.parse(open(os.path.join(os.path.dirname(__file__), 'maharashtra.py')).read())
_lit = {t.id: n.value for n in _src.body if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name) and t.id in ('COLLEGES', 'SUBJECTS')}
R1_COLLEGES = set(ast.literal_eval(_lit['COLLEGES']).values())
R1_COURSES = {ast.literal_eval(v) for v in _lit['SUBJECTS'].values}   # keys use the DERM name, values are literals

CET_NAMES = {  # Round-2 printed "College: <code> <name>" → 2025 cut-off name (= maharashtra.py COLLEGES value)
    '01101': ('GRANT GOVERNMENT MEDICAL COLLEGE MUMBAI', 'Grant Medical College, Mumbai'),
    '01103': ('G. S. MEDICAL COLLEGE MUMBAI', 'Seth GS Medical College and KEM Hospital, Mumbai'),
    '01102': ('L. T. MEDICAL COLLEGE MUMBAI', 'Lokmanya Tilak Municipal Medical College, Sion, Mumbai'),
    '01104': ('T. N. MEDICAL COLLEGE MUMBAI', 'Topiwala National Medical College, Mumbai'),
    '01113': ('HBT & DR. R. N. COOPER MEDICAL COLLEGE JUHU, MUMBAI',
              'H.B.T Medical College & Dr. R.N. Cooper Municipal General Hospital, Juhu, Mumbai'),
    '01109': ('RAJEEV GANDHI MEDICAL COLLEGE THANE', 'Rajiv Gandhi Medical College, Thane'),
    '01110': ('B. J. GOVERNMENT MEDICAL COLLEGE PUNE', 'B.J. Government Medical College, Pune'),
    '01162': ("PCMC's PG MEDICAL INSTITUTE PIMPARI, PUNE", 'Pimpri Chinchwad Municipal Corporation Post Graduate Institute, Pune'),
    '01114': ('DR. V.M. GOVERNMENT MEDICAL COLLEGE SOLAPUR', 'Dr. Vaishampayan Memorial Government Medical College, Solapur'),
    '01115': ('GOVT. MEDICAL COLLEGE MIRAJ', 'Government Medical College, Miraj'),
    '01132': ('R.C.S.M. GOVT MEDICAL COLLEGE KOLHAPUR', 'Rajashree Chatrapati Shahu Maharaj Government Medical College, Kolhapur'),
    '01116': ('SHREE BHAUSAHEB HIRE GOVERNMENT MEDICAL COLLEGE DHULE', 'Sri Bhausaheb Hire Government Medical College, Dhule'),
    '01221': ('GOVT. MEDICAL COLLEGE NAGPUR', 'Government Medical College, Nagpur'),
    '01222': ('INDIRA GANDHI GOVERNMENT MEDICAL COLLEGE NAGPUR', 'Indira Gandhi Government Medical College & Hospital, Nagpur'),
    '01226': ('SHRI V.N. GOVT. MEDICAL COLLEGE YEOTMAL', 'Shri Vasant Rao Naik Government Medical College, Yavatmal'),
    '01234': ('GOVERNMENT MEDICAL COLLEGE AKOLA', 'Government Medical College, Akola'),
    '01327': ('GOVT. MEDICAL COLLEGE SAMBHAJINAGAR', 'Government Medical College, Aurangabad (Sambhajinagar)'),
    '01328': ('SHANKARRAO CHAVAN GOVT MEDICAL COLLEGE NANDED', 'Dr. Shankarrao Chavan Government Medical College, Nanded'),
    '01329': ('S.R.T.R. MEDICAL COLLEGE AMBAJOGAI', 'SRTR Government Medical College, Ambajogai'),
    '01333': ('VILASRAO DESHMUKH GOVT MEDICAL SCIENCE CENTRE LATUR', 'Government Medical College, Latur'),
    '01241': ('GOVT. MEDICAL COLLEGE CHANDRAPUR', 'Government Medical College and Hospital, Chandrapur'),
    '01242': ('GOVT. MEDICAL COLLEGE GONDIA', 'Government Medical College, Gondia'),
    '01199': ('MAHARASHTRA PG INSTITUTE OF MEDICAL EDU & RES NASHIK',
              'Maharashtra Post Graduate Institute of Medical Education and Research, Nashik'),
    '01261': ('MAHATAMA GANDHI INSTITUTE OF MEDICAL SCIENCES SEVAGRAM,WARDHA', 'Mahatma Gandhi Institute of Medical Sciences, Sevagram, Wardha'),
    '01135': ('T.M.H AND R.C. MUMBAI', 'Tata Memorial Centre, Mumbai'),
    '01140': ('ALL INDIA INST. OF PHY. MED. & REHEBIETATION MUMBAI', 'All India Institute of Physical Medicine and Rehabilitation, Mumbai'),
    '01143': ('BHABHA AUTOMIC RESEARCH CENTRE MUMBAI', 'Bhabha Atomic Research Centre, Anushakti Nagar, Mumbai, Maharashtra'),
    '01149': ('GOVERNMENT MEDICAL COLLEGE JALGAON', 'Government Medical College, Jalgaon'),
    '01150': ('GOVERNMENT MEDICAL COLLEGE BARAMATI', 'Government Medical College, Baramati'),
    '01198': ('PG INSTITUTE OF MEDICAL SCIENCE NEW MUMBAI', 'Post Graduate Institute of Medical Sciences, (PGIMS) Navi Mumbai'),
    '01151': ('GOVERNMENT MEDICAL COLLEGE NANDURBAR', 'Government Medical College, Nandurbar'),
    '01133': ('BOMBAY HOSPITAL MUMBAI', 'Bombay Hospital Institute of Medical Sciences, Mumbai'),
    '01134': ('SANCHETI ORTHOPEDIC RESEARCH INSTITUTE PUNE',
              'Sancheti Institute for Orthpaedics and Rehabilitation College of Physiotherapy, Pune'),
    '01119': ('SANJEEVAN MEDICAL FOUNDATION MIRAJ', 'Sanjeevan Medical Foundation ENT Post Graduate Training Institute, Miraj'),
    '01118': ('SWASTHIYOG PRATISHTAN ORTHOPEDICS INSTITUTE MIRAJ', 'Postgraduate Institute of Swasthiyog Pratishthan, Miraj'),
    '01105': ('K.J.SOMAIYA MEDICAL COLLEGE MUMBAI', 'KJ Somaiyya Medical College & Research Centre, Mumbai'),
    '01136': ('SMT.KASHIBAI NAVALE MEDICAL COLLEGE PUNE', 'Smt. Kashibai Navale Medical College and General Hospital, Pune'),
    '01112': ("MIMER'S MEDICAL COLLEGE TALEGAON PUNE", 'Maharashtra Institute of Medical Education & Research, Talegaon, Pune'),
    '01330': ('MIMSR MEDICAL COLLEGE LATUR', 'Maharashtra Institute of Medical Sciences & Research, Latur'),
    '01108': ('TERNA MEDICAL COLLEGE NEW MUMBAI', 'Terna Medical College, Navi Mumbai'),
    '01141': ("V.P.S'S MEDICAL COLLEGE NASIK",
              'Dr. Vasantrao Pawar Med. Col. Hosp. & Research Centre, Nasik (Prev. NDMVP Samaj Medical College)'),
    '01120': ('ACPM MEDICAL COLLEGE DHULE', 'ACPM Medical College, Dhule'),
    '01144': ("DR. V.V.P.F.'s MEDICAL COLLEGE AHMEDNAGAR", 'Dr. Vithalrao Vikhe Patil Foundations Medical College & Hospital, Ahmednagar'),
    '01223': ('N.K.P. SALVE MEDICAL COLLEGE NAGPUR',
              'N. K. P. Salve Instt. of Medical Sciences and Research Centre and Lata Mangeshkar Hospital, Nagpur'),
    '01225': ('DR. PANJABRAO DESHMUKH MEDICAL COLLEGE AMRAVATI', 'Dr. Panjabrao Alias Bhausaheb Deshmukh Memorial Medical College, Amravati'),
    '01142': ('DR. ULHAS PATIL MEDICAL COLLEGE JALGAON', 'Dr. Ulhas Patil Medical College & Hospital, Jalgaon'),
    '01137': ('ASHWINI RURAL MEDICAL COLLEGE SOLAPUR', 'Ashwini Rural Medical College, Hospital & Research Centre, Solapur'),
    '01139': ('B.K.L. WALAWALKAR RURAL MEDICAL COLLEGE RATNAGIRI', 'B.K.L. Walawalkar Rural Medical College, Ratnagiri'),
    '01146': ('SMBT INSTITUTE of MEDICAL SCIENCES & RESEARCH CENTRE NANDIHILLS',
              'SMBT Institute of Medical Sciences & Research Centre, Nandihills, Nashik'),
    '01345': ('INDIAN INST. of MED. SC.& RESEARCH (MUSLIM MINORITY) JALNA', 'Indian Institute of Medical Science & Research, Jalna'),
    '01147': ('VEDANTA MEDICAL COLLEGE PALGHAR', 'Vedantaa Institute of Medical Sciences, Palghar'),
    '01145': ('PRAKASH INSTITUTE of MEDICAL SCIENCES & RESEARCH ISLAMPUR,SANGLI', 'Prakash Institute of Medical Sciences & Research, Sangli'),
    '01156': ('DR. N. Y. TASGAONKAR INSTITUTE OF MEDICAL SCIENCE KARJAT', 'Dr. N. Y. Tasgaonkar Institute of Medical Science, Karjat'),
    '01248': ('DR RAJENDRA GODE MEDICAL COLLEGE AMARAVATI', 'Dr. Rajendra Gode Medical College, Amravati')}
SUBJ = {  # subject code (last two digits of the course code) → (printed abbreviation, Round 1 course name)
    '01': ('MEDICINE', 'MD - General Medicine'), '02': ('SKIN & VD', 'MD - Dermatology'),
    '03': ('CHEST & TB', 'MD - Respiratory Medicine'), '04': ('PSYCHIATRY', 'MD - Psychiatry'),
    '05': ('PAEDIATRIC', 'MD - Paediatrics'), '06': ('SURGERY', 'MS - General Surgery'), '07': ('ORTHO', 'MS - Orthopaedics'),
    '08': ('E.N.T.', 'MS - ENT (Otorhinolaryngology)'), '09': ('OPTHAL', 'MS - Ophthalmology'),
    '10': ('RADIOLOGY', 'MD - Radio-Diagnosis'), '11': ('ANAESTHESIA', 'MD - Anaesthesiology'),
    '12': ('OBGY', 'MS - Obstetrics and Gynaecology'), '13': ('RADIO-TH.', 'MD - Radiotherapy / Radiation Oncology'),
    '14': ('ANATOMY', 'MD/MS - Anatomy'), '15': ('PHYSIOLOGY', 'MD - Physiology'), '16': ('PHARMA', 'MD - Pharmacology'),
    '17': ('MICRO', 'MD - Microbiology'),
    '18': ('P.S.M.', 'MD - Social & Preventive Medicine / Community Medicine'),
    '19': ('FOR.MEDICINE', 'MD - Forensic Medicine'), '20': ('PATHO', 'MD - Pathology'), '21': ('BIOCHEM', 'MD - Biochemistry'),
    '22': ('IH & TM', 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion'),
    '23': ('PHY MED & RH', 'MD - Physical Medicine and Rehabilitation'), '24': ('PALLIAT MED', 'MD - Palliative Medicine'),
    '25': ('NUCLEAR MED', 'MD - Nuclear Medicine'), '26': ('EMG & CRI-CA', 'MD - Emergency Medicine'),
    '27': ('GERIATRIC', 'MD - Geriatrics'),
    # PG diplomas (LTMC Mumbai only, as in Round 1)
    '28': ('D.V.D.', 'Diploma in Dermatology'), '29': ('D.P.M.', 'Diploma in Psychological Medicine'),
    '30': ('D.C.H.', 'Diploma in Child Health / Paediatrics'), '31': ('D.M.R.D.', 'Diploma in Radio Diagnosis'),
    '33': ('D.A.', 'Diploma in Anaesthesiology'), '34': ('D.G.O.', 'Diploma in Obstetrics and Gynaecology'),
    '35': ('D.P.H.', 'Diploma in Public Health'), '39': ('D.O.R.L.', 'Diploma in ENT'),
    '40': ('D.OPTHAL.', 'Diploma in Ophthalmology')}
VSUBJ = {  # virtual-vacancy list spells the subject out
    'SKIN AND VD': '02', 'CHEST AND TB': '03', 'ORTHOPEDICS': '07', 'OPTHALMOLOGY': '09', 'RADIOTHERAPY': '13',
    'PHARMACOLOGY': '16', 'MICROBIOLOGY': '17', 'FORENSIC MEDICINE': '19', 'PATHOLOGY': '20', 'BIOCHEMISTRY': '21',
    'IMMUNOLOGY HAEMATOLOGY AND TRANS.MED.': '22', 'PHYSICAL MEDICINE AND REHABILITION': '23', 'PALLIATIVE MEDICINE': '24',
    'NUCLEAR MEDICINE': '25', 'EMERGENCY AND CRITICAL CARE': '26'}
CATS = ['SC', 'ST', 'VJ', 'NT-B', 'NT-C', 'NT-D', 'OBC']          # fields 0-6 (general), 13-19 (in-service)
FIELDS = ([('State Quota', c) for c in CATS] + [None] +            # 7 = Tot Res (aggregate)
          [('State Quota', 'SEBC'), ('State Quota', 'EWS'), ('State Quota', 'OPEN'), ('ORP', ''), ('ORC', '')] +
          [('In-service Quota', c) for c in CATS + ['SEBC', 'EWS', 'OPEN']] +
          [('Minority Quota', ''), ('IQ', ''), ('NRI Quota', ''), None])   # 26 = Tot.
ORPTAG = {'SC': 'SC', 'ST': 'ST', 'VJ': 'VJ', 'NB': 'NT-B', 'NC': 'NT-C', 'ND': 'NT-D', 'OB': 'OBC', 'SE': 'SEBC',
          'EW': 'EWS', 'OP': 'OPEN'}
HEAD1 = 'Sr  Code  Subject              <---GENERAL QUOTA-->  Tot|   |   |   |     |    |<---------INSERVICE QUOTA------------>|Min|IQ |NRI|Tot.'
HEAD2 = 'No                            SC| ST|VJ|N1|N2|N3|OBC|Res| SE| EW|OPN|ORP  | ORC|     SC|ST|VJ|N1|N2|N3|OBC|SE|EW|OPEN |   |   |   |'
GRAND = 1880


def cell(s):
    """(seats, orphan category or None) of one field: '' = 0, '3', '1VJ' (orphan seat of category VJ)."""
    s = s.strip()
    if s == '':
        return 0, None
    if s.isdigit():
        return int(s), None
    m = re.fullmatch(r'(\d+)([A-Z]{2})', s)
    if not m or m.group(2) not in ORPTAG:
        raise SystemExit(f'not a number / orphan tag: {s!r}')
    return int(m.group(1)), ORPTAG[m.group(2)]


def fields(line):
    f = line[29:].split('|')
    if len(f) != 27:
        raise SystemExit(f'{len(f)} fields, expected 27: {line!r}')
    return [cell(x) for x in f]


# ---------------- matrix (1904) ----------------
bad = sorted(v for k, (p, v) in CET_NAMES.items() if v not in R1_COLLEGES)
if bad:
    raise SystemExit(f'CET_NAMES values not in maharashtra.py COLLEGES: {bad}')
bad = sorted(c for _, c in SUBJ.values() if c not in R1_COURSES)
if bad:
    raise SystemExit(f'SUBJ courses not in maharashtra.py SUBJECTS: {bad}')

doc = fitz.open(PDF)
checks, rows = {}, []
lines = []
for pg in doc:
    t = pg.get_text().split('\n')
    head = clean(' '.join(t[:6]))
    for want in ('Admissions to NEET(PGM) Courses, 2026-2027 (CAP Round: 2.0)', 'Provisional Seat Matrix for CAP Round 2',
                 'Date:21.11.2026', f'Pg:{pg.number + 1}'):
        if want not in head:
            raise SystemExit(f'p{pg.number + 1}: heading {want!r} missing')
    lines += [(pg.number + 1, l) for l in t]

colleges = collections.OrderedDict()   # code → {'name', 'subjects': [...], 'total': fields}
cur, subj, grand, sr = None, None, None, 0
unknown = []
for pno, l in lines:
    s = l.strip()
    if s.startswith('College:'):
        m = re.fullmatch(r'College: (\d{5}) (.+)', s)
        code, name = m.group(1), clean(m.group(2))
        if code not in CET_NAMES or CET_NAMES[code][0] != name:
            unknown.append(f'college {code} {name!r}'); cur = None; continue
        if code in colleges:
            raise SystemExit(f'p{pno}: college {code} printed twice')
        cur = colleges[code] = {'name': CET_NAMES[code][1], 'subjects': [], 'total': None, 'page': pno}
        sr = 0
        continue
    if s.startswith('Sr  Code'):
        if s.rstrip() not in (HEAD1, HEAD1.replace('|IQ |', '|AIQ|')): raise SystemExit(f'p{pno}: heading 1 changed {s!r}')
        if cur is not None:      # Vikhe Patil + NKP Salve head the IQ column "AIQ" (their A lines)
            cur['aiq_head'] = '|AIQ|' in s
        continue
    if s.startswith('No  ') and 'SC|' in s:
        if s.rstrip() != HEAD2: raise SystemExit(f'p{pno}: heading 2 changed {s!r}')
        continue
    m = re.match(r'^ *(\d+) (\d{2})(\d{2})([SINA]) (.{18})([GP])', l)
    if m:
        if cur is None:
            continue
        sr += 1
        if int(m.group(1)) != sr:
            raise SystemExit(f'p{pno}: Sr. No {m.group(1)} after {sr - 1}')
        sc = m.group(3)
        if sc not in SUBJ or SUBJ[sc][0] != m.group(5).strip():
            unknown.append(f'subject {sc} {m.group(5).strip()!r} ({cur["name"]})'); subj = None; continue
        if m.group(6) != 'G':
            raise SystemExit(f'p{pno}: subject line not G: {l!r}')
        subj = {'code': m.group(2) + sc + m.group(4), 'sub': sc, 'kind': m.group(4), 'G': fields(l), 'P': None}
        cur['subjects'].append(subj)
        continue
    if re.match(r'^ {28}P', l):
        if subj is None or subj['P'] is not None:
            raise SystemExit(f'p{pno}: P line without a subject: {l!r}')
        subj['P'] = fields(l); continue
    if '* * Total * *' in l:
        f = l.split('* * Total * *')[1].split('|')
        if len(f) != 27: raise SystemExit(f'p{pno}: Total line has {len(f)} fields')
        cur['total'] = [cell(x)[0] for x in f]; subj = None; continue
    if '* * Grand Total * *' in l:
        f = l.split('* * Grand Total * *')[1].split('|')
        if len(f) != 27: raise SystemExit(f'p{pno}: Grand Total line has {len(f)} fields')
        grand = [cell(x)[0] for x in f]; continue
    if (not s or set(s) <= set('=-') or s.startswith(('####', 'GOVERNMENT OF MAHARASHTRA', 'State Common Entrance',
                                                       'Admissions to NEET', 'Provisional Seat Matrix', 'Legends:',
                                                       'ORP:Orphan')) or s.startswith('SC  ST VJ')):
        continue
    raise SystemExit(f'p{pno}: unexpected line {l!r}')
if unknown:
    raise SystemExit('UNKNOWN names (add a mapping, never guess):\n  ' + '\n  '.join(unknown))
if grand is None:
    raise SystemExit('no Grand Total line')

colsum = [0] * 27
orphan_kinds = collections.Counter()
for code, c in colleges.items():
    if c['total'] is None:
        raise SystemExit(f'{c["name"]}: no Total line')
    kinds = {sj['kind'] for sj in c['subjects']}
    if c.get('aiq_head') != ('A' in kinds) or ('A' in kinds and 'I' in kinds):
        raise SystemExit(f'{c["name"]}: column heading AIQ={c.get("aiq_head")} but line kinds {sorted(kinds)}')
    csum = [0] * 27
    for sj in c['subjects']:
        lines_ = [('G', sj['G'])] + ([('P', sj['P'])] if sj['P'] else [])
        tot = sj['G'][26][0]
        if sj['P'] and sj['P'][26][0]:
            raise SystemExit(f'{c["name"]} {sj["code"]}: Tot. printed on the P line')
        seats_line = 0
        for gp, f in lines_:
            if sum(f[i][0] for i in range(7)) != f[7][0]:
                raise SystemExit(f'{c["name"]} {sj["code"]} {gp}: SC..OBC {sum(f[i][0] for i in range(7))} ≠ Tot Res {f[7][0]}')
            for i in range(27):
                csum[i] += f[i][0]
            for i, key in enumerate(FIELDS):
                v, tag = f[i]
                if key is None or not v:
                    continue
                q, cat = key
                seats_line += v
                if q == 'IQ':
                    if sj['kind'] not in 'IA':
                        raise SystemExit(f'{c["name"]} {sj["code"]}: IQ seats on a {sj["kind"]} line')
                    q = 'Institutional Quota' if sj['kind'] == 'I' else 'All India Quota'
                elif q == 'NRI Quota':
                    if sj['kind'] != 'N':
                        raise SystemExit(f'{c["name"]} {sj["code"]}: NRI seats on a {sj["kind"]} line')
                elif sj['kind'] != 'S':
                    raise SystemExit(f'{c["name"]} {sj["code"]}: {q} seats on a {sj["kind"]} line')
                if q in ('ORP', 'ORC'):
                    if not tag or gp == 'P':
                        raise SystemExit(f'{c["name"]} {sj["code"]}: orphan cell without category / on PwD line')
                    orphan_kinds[q] += v
                    q, cat = 'State Quota', tag + '-Orphan'
                elif tag:
                    raise SystemExit(f'{c["name"]} {sj["code"]}: category tag outside ORP / ORC')
                elif gp == 'P':
                    if q not in ('State Quota', 'In-service Quota'):
                        raise SystemExit(f'{c["name"]} {sj["code"]}: PwD seat in {q}')
                    cat += '-PwD'
                course = SUBJ[sj['sub']][1]
                rows.append({'college': c['name'], 'course': course, 'quota': q, 'category': cat, 'seats': v,
                             'section': 'diploma' if course.startswith('Diploma') else 'mdms', 'cet_code': sj['code']})
        if seats_line != tot:
            raise SystemExit(f'{c["name"]} {sj["code"]}: cells add to {seats_line}, Tot. {tot}')
    off = {i: (csum[i], c['total'][i]) for i in range(27) if csum[i] != c['total'][i]}
    checks[f'{c["name"]} | Total line, all 27 columns'] = (len(off), 0)
    if off:
        print('   column differences', c['name'], off)
    checks[f'{c["name"]} | Tot.'] = (sum(r['seats'] for r in rows if r['college'] == c['name']), c['total'][26])
    for i in range(27):
        colsum[i] += c['total'][i]
checks['Grand Total line = sum of college Total lines (27 columns, differing columns)'] = (
    sum(1 for i in range(27) if colsum[i] != grand[i]), 0)
checks['Grand Total seats'] = (sum(r['seats'] for r in rows), grand[26])
checks['Grand Total = 1,880 (printed)'] = (grand[26], GRAND)
checks['orphan A/B seats (ORP column)'] = (orphan_kinds['ORP'], grand[11])
checks['orphan C seats (ORC column)'] = (orphan_kinds['ORC'], grand[12])
checks['colleges'] = (len(colleges), 54)

# merge identical college × course × quota × category (a course printed once per quota letter)
merged = collections.OrderedDict()
for r in rows:
    k = (r['college'], r['course'], r['quota'], r['category'])
    if k in merged:
        merged[k]['seats'] += r['seats']
    else:
        merged[k] = dict(r)
rows = list(merged.values())

# ---------------- virtual vacancy (1903) — counted, checked, not stored ----------------
VQ = {'OPEN': ('State Quota', 'OPEN'), 'OBC': ('State Quota', 'OBC'), 'SC': ('State Quota', 'SC'), 'ST': ('State Quota', 'ST'),
      'SEBC': ('State Quota', 'SEBC'), 'EWS': ('State Quota', 'EWS'), 'VJA': ('State Quota', 'VJ'), 'NTB': ('State Quota', 'NT-B'),
      'NTC': ('State Quota', 'NT-C'), 'NTD': ('State Quota', 'NT-D'), 'I.Q.': ('Institutional Quota', ''),
      'AIQ': ('All India Quota', ''), 'MINORITY': ('Minority Quota', ''), 'NRI': ('NRI Quota', '')}


def vquota(s):
    if s in VQ:
        return VQ[s]
    m = re.fullmatch(r'(IS|PH) (\w+)', s)
    if m and m.group(2) in VQ and VQ[m.group(2)][0] == 'State Quota':
        q, c = VQ[m.group(2)]
        return ('In-service Quota', c) if m.group(1) == 'IS' else (q, c + '-PwD')
    raise SystemExit(f'virtual vacancy: unknown quota {s!r}')


by_prefix = {}
for code, c in colleges.items():
    for sj in c['subjects']:
        by_prefix.setdefault(sj['code'][:2], c['name'])
vdoc = fitz.open(VPDF)
vtok = []
for pg in vdoc:
    t = [x.strip() for x in pg.get_text().split('\n')]
    if f'Page {pg.number + 1} of {len(vdoc)}' not in t or 'Virtual Vacancy for round 2 Dated 21/11/2026' not in t:
        raise SystemExit(f'virtual p{pg.number + 1}: footer changed')
    vtok += [x for x in t if x and x not in ('Sr.No.', 'Code : Subject Name', 'Quota', 'Total Seats', 'NEET(PGM)',
                                              f'Page {pg.number + 1} of {len(vdoc)}', 'Admissions to Health Science Courses 2026-27',
                                              'Virtual Vacancy for round 2 Dated 21/11/2026')
             and not x.startswith(('Note: Virtual vacancies', 'Retention form likely'))]
virtual, vcol, i, vsr, vsum = [], None, 0, 0, 0
while i < len(vtok):
    x = vtok[i]
    m = re.fullmatch(r'(\d{2}) : (.+)', x)
    if m:
        name = m.group(2)
        while i + 1 < len(vtok) and not vtok[i + 1].isdigit() and vtok[i + 1] != 'Total :':   # wrapped college name
            i += 1; name = clean(name + ' ' + vtok[i])
        m = (None, None, name)
        if m[2] != vcol:          # the college header is repeated on a continuation page
            if vcol is not None and f'virtual | {vcol} | Total' not in checks:
                raise SystemExit(f'virtual: {vcol} has no Total line')
            vcol, vsr, vsum = m[2], 0, 0
        i += 1; continue
    if x == 'Total :':
        checks[f'virtual | {vcol} | Total'] = (vsum, int(vtok[i + 1])); i += 2; continue
    if x.isdigit() and int(x) == vsr + 1:
        cs = re.fullmatch(r'(\d{2})(\d{2})([SINA]) : (.+)', vtok[i + 1])
        if not cs: raise SystemExit(f'virtual: bad line {vtok[i:i + 4]}')
        sub = VSUBJ.get(cs.group(4), cs.group(4))
        sub = next((k for k, v in SUBJ.items() if v[0] == cs.group(4)), sub) if sub == cs.group(4) else sub
        if sub not in SUBJ: raise SystemExit(f'virtual: unknown subject {cs.group(4)!r}')
        if cs.group(2) != sub: raise SystemExit(f'virtual: subject code {cs.group(2)} ≠ {cs.group(4)}')
        q, cat = vquota(vtok[i + 2])
        n_ = int(vtok[i + 3])
        college = by_prefix.get(cs.group(1))
        if not college: raise SystemExit(f'virtual: college prefix {cs.group(1)} not in the matrix ({vcol})')
        virtual.append({'college': college, 'course': SUBJ[sub][1], 'quota': q, 'category': cat, 'seats': n_,
                        'printed_college': vcol})
        vsr += 1; vsum += n_; i += 4; continue
    raise SystemExit(f'virtual: unexpected token {x!r} near {vtok[i - 3:i + 3]}')
vtotal = sum(v['seats'] for v in virtual)
in_matrix = sum(v['seats'] for v in virtual
                if merged.get((v['college'], v['course'], v['quota'], v['category']), {}).get('seats'))

# ---------------- Round 1 comparison ----------------
r1 = json.load(open(R1))['rows']
r1_cc = collections.Counter()
inst_type = {}
for r in r1:
    r1_cc[(r['college_name'], r['course_name'])] += r['seats']
    inst_type[r['college_name']] = r['institute_type']
r2_cc = collections.Counter()
for r in rows:
    r2_cc[(r['college'], r['course'])] += r['seats']
    r['institute_type'] = inst_type.get(r['college'], 'Government Institute')
new_colleges = sorted({r['college'] for r in rows} - set(inst_type))
above = {k: (v, r1_cc.get(k, 0)) for k, v in r2_cc.items() if v > r1_cc.get(k, 0)}
v_cc = collections.Counter()
for v in virtual:
    v_cc[(v['college'], v['course'])] += v['seats']
over_with_virtual = {k: (r2_cc.get(k, 0), v, r1_cc.get(k, 0)) for k, v in v_cc.items() if r2_cc.get(k, 0) + v > r1_cc.get(k, 0)}

FAMILY = {'State Quota': ('State Quota$',), 'In-service Quota': ('State Quota-Inservice$',),
          'Institutional Quota': ('Institutional Quota$',), 'NRI Quota': ('NRI Quota$',),
          'Minority Quota': ('State Quota-Minority$',), 'All India Quota': ('All India Quota$',)}
CAT25 = {'VJ': 'VJ', 'NT-B': 'NT1', 'NT-C': 'NT2', 'NT-D': 'NT3', 'SEBC': 'SEBC'}


def cat_match(x):   # same as maharashtra.py
    if x['quota'] == 'Institutional Quota':
        return ('IQ',)
    if x['quota'] == 'NRI Quota':
        return ('NRI',)
    if x['quota'] == 'Minority Quota':
        return ('Minority',)
    if x['category'].endswith('-Orphan'):
        b = CAT25.get(x['category'][:-7], x['category'][:-7])
        return (f'{b}-Orphan', f'{b}-ORPHAN', 'Orphan', b)
    pwd = x['category'].endswith('-PwD')
    base = CAT25.get(x['category'].replace('-PwD', ''), x['category'].replace('-PwD', ''))
    if x['quota'] == 'In-service Quota':
        return (f'IS-{base}-PH', 'IS-PH', f'IS-{base}', 'IS-OPEN') if pwd else (f'IS-{base}', 'IS-OPEN')
    return (f'{base}-PH', base) if pwd else (base,)


cuts = load_cuts(CUTS, 'Maharashtra')
out = build(rows, cuts, 'Maharashtra', 'MH', lambda q: FAMILY[q], cat_match)
r1_codes = {r['college_code'] for r in r1}
checks['college codes = Round 1 codes (codes not in Round 1)'] = (len({r['college_code'] for r in out} - r1_codes), 0)
# new_in_round: college × course seats above Round 1, given first to the quota × category lines that grew
r1_line = collections.Counter()
for r in r1:
    r1_line[(r['college_name'], r['course_name'], r['quota'], r['category'])] += r['seats']
for r in out:
    r['new_in_round'] = 0
for (col, crs), (n2, n1) in above.items():
    extra = n2 - n1
    mine = [r for r in out if r['college_name'] == col and r['course_name'] == crs]
    grow = lambda r: max(0, r['seats'] - r1_line.get((col, crs, r['quota'], r['category']), 0))
    for r in sorted(mine, key=lambda r: (-grow(r), r['quota'] != 'State Quota', -r['seats'])):
        take = min(extra, grow(r) or r['seats'] - r['new_in_round']); r['new_in_round'] += take; extra -= take
        if not extra: break
    if extra:
        raise SystemExit(f'new_in_round: {extra} seats of {col} | {crs} not placed')

json.dump({'rows': out, 'checks': checks,
           'virtual_vacancies': {'seats': virtual and vtotal, 'lines': len(virtual), 'colleges': len({v['college'] for v in virtual}),
                                 'by_quota': dict(collections.Counter(v['quota'] for v in virtual for _ in range(v['seats']))),
                                 'seats_on_a_matrix_line_with_seats': in_matrix,
                                 'college_course_over_round1_if_added': {f'{k[0]} | {k[1]}': v for k, v in over_with_virtual.items()},
                                 'rows': virtual},
           'round1_compare': {'round1_seats': sum(r1_cc.values()), 'round2_seats': sum(r2_cc.values()),
                              'college_course_above_round1': {f'{k[0]} | {k[1]}': v for k, v in above.items()},
                              'courses_not_in_round1': [f'{k[0]} | {k[1]}' for k in r2_cc if k not in r1_cc],
                              'new_colleges': new_colleges,
                              'per_college': {c: (sum(v for k, v in r2_cc.items() if k[0] == c),
                                                  sum(v for k, v in r1_cc.items() if k[0] == c))
                                              for c in sorted({k[0] for k in r1_cc} | {k[0] for k in r2_cc})}}},
          open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma')})
print('orphan seats', dict(orphan_kinds), '| new_in_round', sum(r['new_in_round'] for r in out))
print('Round 1', sum(r1_cc.values()), '→ Round 2', sum(r2_cc.values()), '| college × course above Round 1:', len(above),
      sum(a - b for a, b in above.values()), 'seats')
for k, v in sorted(above.items()):
    print('   above R1', k, v)
print('   courses not in Round 1:', [k for k in r2_cc if k not in r1_cc], '| new colleges:', new_colleges)
for r in out:
    if r['new_in_round']:
        print('   new_in_round', r['new_in_round'], '|', r['college_name'], '|', r['course_name'], '|', r['quota'], r['category'])
print('virtual vacancies (not stored):', vtotal, 'seats,', len(virtual), 'lines,', len({v["college"] for v in virtual}),
      'colleges | on a matrix line that already has seats:', in_matrix)
print('   virtual by quota', dict(collections.Counter(v['quota'] for v in virtual for _ in range(v['seats']))))
print('   college × course where R2 + virtual > R1:', len(over_with_virtual))
for k, v in sorted(over_with_virtual.items())[:30]:
    print('     ', k, '(R2, virtual, R1) =', v)
