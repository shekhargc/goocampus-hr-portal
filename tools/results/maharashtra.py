"""Maharashtra (State CET Cell) "PROVISIONAL SELECTION LIST FOR NEET(PG)-CET 2026", Admissions to MD/MS/DIPLOMA Courses
2026-2027 (Round 1.0, printed 05/11/2026) → rows for POST /api/pg/results/ingest. Authority `cetcell_mh`.
A fixed-width (Courier) list, one 141-character line per candidate of the state merit list, in merit order:
  SrNo [I/IB] SML  FormNo  Name  Cat.  Code (CCSSq) : Subject  College  City  Quota  remark
or "Choice Not Available" in place of Code … Quota (no seat — counted and skipped).
PERSONAL DATA: FormNo (application no.) and Name are never read — the line is sliced around them (cols 17-51).

Ranks: `rank` = SML (State Merit List number of the common merit list), `rank_ai` = NEET PG AIR looked up by SML in
our stored "Final Provisional" common state merit list (cetcell_mh_common_provisional.json). The candidate Cat. cell
is checked against that merit list's category for the same SML (a wrong bridge would show as many category
mismatches; up to 3 are tolerated and listed — R1 2026: SML 2103 printed SEBC here, OPEN in the merit list);
in-service candidates (`I` / `IB` after SrNo) should carry an AIR that is in the in-service merit list (soft: up to 3
misses are listed in checks — R1 2026 has one, SML 5611, marked I but not on the 02.11 in-service list).
Code = college (2 digits) + subject (2 digits) + seat type: S state, I institutional (private MGT), A AIQ seat of Vikhe
Patil / NKP Salve (printed quota 'I.Q.', remark 'AIQ'), N NRI.
Quota / category (2025 Maharashtra cut-off spellings):
  S + OPEN/OBC/SC/ST/SEBC/EWS/VJA/NTB/NTC/NTD  → State Quota, category (VJA→VJ, NTB→NT1, NTC→NT2, NTD→NT3)
  S + 'PH X'                                  → State Quota, 'X-PH'
  S + 'EMX' (earmarked seat, remark (EMR))    → State Quota, X (earmarking receiver noted in remarks)
  S + ORPHAN / 'ORPHAN-C O' (OrphanC-OBC)     → State Quota, 'Orphan' / 'OBC-Orphan'
  S + 'IS X'                                  → State Quota-Inservice, 'IS-X'
  S + MINORITY (IIMSR Jalna)                  → State Quota-Minority, 'Minority'
  I or A + 'I.Q.'                             → Institutional Quota, 'IQ' (2025 files Vikhe Patil / NKP Salve's share
                                                as Institutional Quota; the 2026 seat matrix calls it All India Quota)
  N + NRI                                     → NRI Quota, 'NRI'
Checks (stop on failure): 86 pages 'Pg : - n -', header Round 1.0 + printed date, SrNo 1..N, SML strictly ascending,
form numbers in the page text = lines read, every code's college/subject agrees with the printed names, quota agrees
with the seat type, every SML in the merit list, candidate category = merit-list category, in-service AIRs in the
in-service list; --seat-matrix: allotted ≤ seats per college × course × seat-matrix quota (category-level overs are
listed, soft — earmarking / PH / orphan seats move between category cells). LTMC's diploma seats are compared
all quotas together: the list fills the matrix's INS diploma cells with state-pool candidates of the same category.
Run with /usr/bin/python3 (PyMuPDF):
    maharashtra.py <selection.pdf> <cetcell_mh_common_provisional.json> <cetcell_mh_inservice_provisional.json> <out.json>
                   [--seat-matrix <MH seat-matrix dump.json>] [--round "Round 1"] [--round-order 1] [--status provisional]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {'--round': 'Round 1', '--round-order': '1', '--status': 'provisional'}
for f in ('--seat-matrix', '--round', '--round-order', '--status'):
    if f in args:
        i = args.index(f); opt[f] = args[i + 1]; del args[i:i + 2]
if len(args) != 4:
    raise SystemExit(__doc__)
PDF, M_COMMON, M_INSERVICE, OUT = args
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

COLLEGES = {  # code → (printed college, printed city, 2026 seat-matrix / 2025 cut-off name)
    '01': ('GMC', 'MUMBAI', 'Grant Medical College, Mumbai'),
    '02': ('GSMC', 'MUMBAI', 'Seth GS Medical College and KEM Hospital, Mumbai'),
    '03': ('LTMC', 'MUMBAI', 'Lokmanya Tilak Municipal Medical College, Sion, Mumbai'),
    '04': ('TNMC', 'MUMBAI', 'Topiwala National Medical College, Mumbai'),
    '05': ('HBT & COOP', 'JUHU, MUMB', 'H.B.T Medical College & Dr. R.N. Cooper Municipal General Hospital, Juhu, Mumbai'),
    '06': ('Rajeev Gan', 'THANE', 'Rajiv Gandhi Medical College, Thane'),
    '07': ('BJMC', 'PUNE', 'B.J. Government Medical College, Pune'),
    '08': ('PCMC PGM I', 'PIMPARI, P', 'Pimpri Chinchwad Municipal Corporation Post Graduate Institute, Pune'),
    '09': ('VMMC', 'SOLAPUR', 'Dr. Vaishampayan Memorial Government Medical College, Solapur'),
    '10': ('GMC', 'MIRAJ', 'Government Medical College, Miraj'),
    '11': ('GMC', 'KOLHAPUR', 'Rajashree Chatrapati Shahu Maharaj Government Medical College, Kolhapur'),
    '12': ('B Hire', 'DHULE', 'Sri Bhausaheb Hire Government Medical College, Dhule'),
    '13': ('GMC', 'NAGPUR', 'Government Medical College, Nagpur'),
    '14': ('IGMC', 'NAGPUR', 'Indira Gandhi Government Medical College & Hospital, Nagpur'),
    '15': ('VNMC', 'YEOTMAL', 'Shri Vasant Rao Naik Government Medical College, Yavatmal'),
    '16': ('GMC', 'AKOLA', 'Government Medical College, Akola'),
    '17': ('GMC', 'SAMBHAJINA', 'Government Medical College, Aurangabad (Sambhajinagar)'),
    '18': ('GMC', 'NANDED', 'Dr. Shankarrao Chavan Government Medical College, Nanded'),
    '19': ('SRTR', 'AMBAJOGAI', 'SRTR Government Medical College, Ambajogai'),
    '20': ('GMC', 'LATUR', 'Government Medical College, Latur'),
    '21': ('CGMC', 'CHANDRAPUR', 'Government Medical College and Hospital, Chandrapur'),
    '22': ('GGMC', 'GONDIA', 'Government Medical College, Gondia'),
    '23': ('MPGIMER', 'NASHIK', 'Maharashtra Post Graduate Institute of Medical Education and Research, Nashik'),
    '24': ('MGIMS', 'SEVAGRAM,W', 'Mahatma Gandhi Institute of Medical Sciences, Sevagram, Wardha'),
    '25': ('TATA', 'MUMBAI', 'Tata Memorial Centre, Mumbai'),
    '26': ('AIIPMR', 'MUMBAI', 'All India Institute of Physical Medicine and Rehabilitation, Mumbai'),
    '28': ('BARC', 'MUMBAI', 'Bhabha Atomic Research Centre, Anushakti Nagar, Mumbai, Maharashtra'),
    '29': ('BHMS', 'MUMBAI', 'Bombay Hospital Institute of Medical Sciences, Mumbai'),
    '30': ('SANCHETI', 'PUNE', 'Sancheti Institute for Orthpaedics and Rehabilitation College of Physiotherapy, Pune'),
    '31': ('SANJEEVAN', 'MIRAJ', 'Sanjeevan Medical Foundation ENT Post Graduate Training Institute, Miraj'),
    '32': ('SWASTHIYOG', 'MIRAJ', 'Postgraduate Institute of Swasthiyog Pratishthan, Miraj'),
    '33': ('KJMC', 'MUMBAI', 'KJ Somaiyya Medical College & Research Centre, Mumbai'),
    '34': ('SKN', 'PUNE', 'Smt. Kashibai Navale Medical College and General Hospital, Pune'),
    '35': ('MIMER', 'TALEGAON P', 'Maharashtra Institute of Medical Education & Research, Talegaon, Pune'),
    '36': ('MIMSR', 'LATUR', 'Maharashtra Institute of Medical Sciences & Research, Latur'),
    '37': ('TERNA', 'NEW MUMBAI', 'Terna Medical College, Navi Mumbai'),
    '38': ('VPS', 'NASIK', 'Dr. Vasantrao Pawar Med. Col. Hosp. & Research Centre, Nasik (Prev. NDMVP Samaj Medical College)'),
    '39': ('ACPM', 'DHULE', 'ACPM Medical College, Dhule'),
    '40': ('VVPF', 'AHMEDNAGAR', 'Dr. Vithalrao Vikhe Patil Foundations Medical College & Hospital, Ahmednagar'),
    '41': ('NKP Salve', 'NAGPUR',
           'N. K. P. Salve Instt. of Medical Sciences and Research Centre and Lata Mangeshkar Hospital, Nagpur'),
    '42': ('PDMC', 'AMRAVATI', 'Dr. Panjabrao Alias Bhausaheb Deshmukh Memorial Medical College, Amravati'),
    '43': ('UPMC', 'JALGAON', 'Dr. Ulhas Patil Medical College & Hospital, Jalgaon'),
    '44': ('ASHWINI ME', 'SOLAPUR', 'Ashwini Rural Medical College, Hospital & Research Centre, Solapur'),
    '45': ('BK WALAWAL', 'RATNAGIRI', 'B.K.L. Walawalkar Rural Medical College, Ratnagiri'),
    '46': ('SMBT', 'NANDIHILLS', 'SMBT Institute of Medical Sciences & Research Centre, Nandihills, Nashik'),
    '47': ('IIMSR', 'JALNA', 'Indian Institute of Medical Science & Research, Jalna'),
    '48': ('VEDANTA MC', 'PALGHAR', 'Vedantaa Institute of Medical Sciences, Palghar'),
    '49': ('GMC', 'JALGAON', 'Government Medical College, Jalgaon'),
    '50': ('GMC', 'BARAMATI', 'Government Medical College, Baramati'),
    '51': ('PGIMS', 'NEW MUMBAI', 'Post Graduate Institute of Medical Sciences, (PGIMS) Navi Mumbai'),
    '52': ('PIMS', 'ISLAMPUR,S', 'Prakash Institute of Medical Sciences & Research, Sangli'),
    '53': ('GMC', 'NANDURBAR', 'Government Medical College, Nandurbar'),
    '54': ('DNY TASGAO', 'KARJAT', 'Dr. N. Y. Tasgaonkar Institute of Medical Science, Karjat'),
    '55': ('DR R GODE', 'AMARAVATI', 'Dr. Rajendra Gode Medical College, Amravati')}
SUBJECTS = {  # code → (printed subject, approved course name, section)
    '01': ('MEDICINE', 'MD - General Medicine', 'mdms'), '02': ('SKIN & VD', 'MD - Dermatology', 'mdms'),
    '03': ('CHEST & TB', 'MD - Respiratory Medicine', 'mdms'), '04': ('PSYCHIATRY', 'MD - Psychiatry', 'mdms'),
    '05': ('PAEDIATRIC', 'MD - Paediatrics', 'mdms'), '06': ('SURGERY', 'MS - General Surgery', 'mdms'),
    '07': ('ORTHOPEDICS', 'MS - Orthopaedics', 'mdms'), '08': ('E.N.T.', 'MS - ENT (Otorhinolaryngology)', 'mdms'),
    '09': ('OPTHALMOLOGY', 'MS - Ophthalmology', 'mdms'), '10': ('RADIOLOGY', 'MD - Radio-Diagnosis', 'mdms'),
    '11': ('ANAESTHESIA', 'MD - Anaesthesiology', 'mdms'), '12': ('OBGY', 'MS - Obstetrics and Gynaecology', 'mdms'),
    '13': ('RADIOTHERAPY', 'MD - Radiotherapy / Radiation Oncology', 'mdms'),
    '14': ('ANATOMY', 'MD/MS - Anatomy', 'mdms'), '15': ('PHYSIOLOGY', 'MD - Physiology', 'mdms'),
    '16': ('PHARMACOLOGY', 'MD - Pharmacology', 'mdms'), '17': ('MICROBIOLOGY', 'MD - Microbiology', 'mdms'),
    '18': ('P.S.M.', 'MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    '19': ('FORENSIC MEDICINE', 'MD - Forensic Medicine', 'mdms'), '20': ('PATHOLOGY', 'MD - Pathology', 'mdms'),
    '21': ('BIOCHEMISTRY', 'MD - Biochemistry', 'mdms'),
    '22': ('IMMUNOLOGY HAEMATOLO', 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'mdms'),
    '23': ('PHYSICAL MEDICINE &', 'MD - Physical Medicine and Rehabilitation', 'mdms'),
    '24': ('PALLIATIVE MEDICINE', 'MD - Palliative Medicine', 'mdms'),
    '25': ('NUCLEAR MEDICINE', 'MD - Nuclear Medicine', 'mdms'),
    '26': ('EMERGENCY & CRITICAL', 'MD - Emergency Medicine', 'mdms'), '27': ('GERIATRIC', 'MD - Geriatrics', 'mdms'),
    '29': ('D.P.M.', 'Diploma in Psychological Medicine', 'diploma'),
    '30': ('D.C.H.', 'Diploma in Child Health / Paediatrics', 'diploma'),
    '31': ('D.M.R.D.', 'Diploma in Radio Diagnosis', 'diploma'), '33': ('D.A.', 'Diploma in Anaesthesiology', 'diploma'),
    '34': ('D.G.O.', 'Diploma in Obstetrics and Gynaecology', 'diploma'), '39': ('D.O.R.L.', 'Diploma in ENT', 'diploma')}
CAT = {'OPEN': 'OPEN', 'OBC': 'OBC', 'SC': 'SC', 'ST': 'ST', 'SEBC': 'SEBC', 'EWS': 'EWS', 'VJA': 'VJ', 'NTB': 'NT1',
       'NTC': 'NT2', 'NTD': 'NT3'}
MERIT_CAT = {'OPEN': 'OPEN', 'OBC': 'OBC', 'SC': 'SC', 'ST': 'ST', 'SEBC': 'SEBC', 'EWS': 'EWS', 'DT-VJ(A)': 'VJA',
             'NT(B)': 'NTB', 'NT(C)': 'NTC', 'NT(D)': 'NTD'}
CAND_TAGS = {'PWD': 'PwD', 'MIN': 'Minority', 'ORC': 'Orphan-C', 'ORA': 'Orphan-A', 'NRI': 'NRI'}
SM_QUOTA = {'State Quota': 'State Quota', 'State Quota-Inservice': 'In-service Quota',
            'State Quota-Minority': 'Minority Quota', 'NRI Quota': 'NRI Quota'}
FORM = re.compile(r'(?<!\d)26\d{7}(?!\d)')


def quota_cat(sfx, q, rem):
    """(quota, allotted category, note) from the seat type letter, the printed quota and the remark."""
    if sfx in ('I', 'A'):
        if q != 'I.Q.' or rem != ('AIQ' if sfx == 'A' else ''):
            raise SystemExit(f'seat type {sfx} with quota {q!r} / remark {rem!r}')
        return 'Institutional Quota', 'IQ', 'AIQ seat (seat-matrix All India Quota), allotted as I.Q.' if sfx == 'A' else ''
    if sfx == 'N':
        if q != 'NRI' or rem != 'NRI':
            raise SystemExit(f'NRI seat with quota {q!r} / remark {rem!r}')
        return 'NRI Quota', 'NRI', ''
    if sfx != 'S':
        raise SystemExit(f'unknown seat type {sfx!r}')
    if q in CAT and rem in ('', '(EMD)'):
        return 'State Quota', CAT[q], 'Earmarking donor (EMD)' if rem else ''
    m = re.fullmatch(r'PH (\w+)', q)
    if m and m.group(1) in CAT and rem in ('PH', f'PH-{m.group(1)}'):
        return 'State Quota', CAT[m.group(1)] + '-PH', ''
    m = re.fullmatch(r'EM(\w+)', q)
    if m and m.group(1) in CAT and m.group(1) != 'OPEN' and rem == '(EMR)':
        return 'State Quota', CAT[m.group(1)], 'Earmarked seat — earmarking receiver (EMR)'
    m = re.fullmatch(r'IS (\w+)', q)
    if m and m.group(1) in CAT and rem in ('', '(EMD)'):
        return 'State Quota-Inservice', 'IS-' + CAT[m.group(1)], 'Earmarking donor (EMD)' if rem else ''
    if q == 'ORPHAN' and rem == 'Orphan':
        return 'State Quota', 'Orphan', ''
    if q == 'ORPHAN-C O' and rem == 'OrphanC-OBC':
        return 'State Quota', 'OBC-Orphan', 'Orphan-C seat'
    if q == 'MINORITY' and rem == '(Minority)':
        return 'State Quota-Minority', 'Minority', ''
    raise SystemExit(f'unknown quota {q!r} / remark {rem!r}')


def cand_cat(s):
    """printed Cat. cell → (merit-list base category code, candidate_category text)."""
    toks = s.split()
    base = toks[0] if toks and toks[0] in CAT else 'OPEN'
    tags = toks[1:] if toks and toks[0] in CAT else toks
    if any(t not in CAND_TAGS for t in tags):
        raise SystemExit(f'unknown candidate category {s!r}')
    return base, ' '.join([CAT[base]] + [CAND_TAGS[t] for t in tags])


approved = {c['course'] for c in json.load(open(SHEET))['courses']}
for _, std, _ in SUBJECTS.values():
    if std not in approved:
        raise SystemExit(f'{std!r} is not in specialty_sheet.json')

doc = fitz.open(PDF)
lines, forms_in_text, printed = [], 0, set()
for pg in doc:
    text = pg.get_text()
    if f'Pg : - {pg.number + 1} -' not in text or 'Admissions to MD/MS/DIPLOMA Courses, 2026-2027 (Round: 1.0)' not in text \
            or 'PROVISIONAL SELECTION LIST FOR NEET(PG)-CET 2026' not in text:
        raise SystemExit(f'p{pg.number + 1}: page header changed')
    printed.update(re.findall(r'Printed On:(\d{2})/(\d{2})/(\d{4})', text))
    forms_in_text += len(FORM.findall(text))
    for b in pg.get_text('rawdict')['blocks']:
        for ln in b.get('lines', []):
            for s in ln['spans']:
                t = ''.join(c['c'] for c in s['chars'])
                if re.fullmatch(r'26\d{7}', t[17:26]):
                    if len(t) != 141 or t[26:29] != '   ' or t[51] != ' ':
                        raise SystemExit(f'p{pg.number + 1}: line layout changed')
                    lines.append((pg.number + 1, t[:17] + ' ' * 35 + t[52:]))   # form no + name never kept
if len(printed) != 1:
    raise SystemExit(f'printed-on dates: {printed}')
dd, mm, yy = printed.pop()
published = f'{yy}-{mm}-{dd}'
if forms_in_text != len(lines):
    raise SystemExit(f'{forms_in_text} form numbers in the text, {len(lines)} lines read')

merit = {r['state_rank']: r for r in json.load(open(M_COMMON))['rows']}
ins_air = {r['air'] for r in json.load(open(M_INSERVICE))['rows']}
sm = sm_cat = None
if '--seat-matrix' in opt:
    sm, sm_cat = collections.Counter(), collections.Counter()
    for x in json.load(open(opt['--seat-matrix']))['rows']:
        # LTMC diplomas: the matrix splits them GN / INS, but the list fills the INS cells from the state pool
        # (same category, quota printed as a state category) — so diploma seats are compared all quotas together
        q = 'State Quota' if x['section'] == 'diploma' else x['quota']
        sm[(x['college_name'], x['course_name'], q)] += x['seats']
        sm_cat[(x['college_name'], x['course_name'], q, x['category'])] += x['seats']

rows, no_choice, ver, cat_off = [], collections.Counter(), collections.Counter(), []
ins_check, ins_missing = collections.Counter(), []
prev_sml = 0
for n, (page, t) in enumerate(lines, 1):
    srno, mark, sml_s = t[0:4].strip(), t[4:6].strip(), t[6:11].strip()
    if srno != str(n):
        raise SystemExit(f'p{page}: SrNo {srno!r}, expected {n}')
    if mark not in ('', 'I', 'IB') or not re.fullmatch(r'-?\d+', sml_s) or (mark and not sml_s.startswith('-')) \
            or (not mark and sml_s.startswith('-')) or t[11:17].strip():
        raise SystemExit(f'p{page} SrNo {n}: SML cell {t[4:17]!r}')
    sml = int(sml_s.lstrip('-'))
    if sml <= prev_sml:
        raise SystemExit(f'p{page} SrNo {n}: SML not ascending')
    prev_sml = sml
    base, cand = cand_cat(t[52:66].strip())
    m = merit.get(sml)
    if not m:
        raise SystemExit(f'SML {sml} not in the merit list')
    if MERIT_CAT[m['category']] != base:
        cat_off.append(sml)
    if mark:
        ins_check['in the in-service merit list' if m['air'] in ins_air else 'NOT in the in-service merit list'] += 1
        if m['air'] not in ins_air:
            ins_missing.append(sml)
    rest = t[66:]
    if rest.strip() == 'Choice Not Available':
        no_choice['in-service' if mark else 'all'] += 1
        continue
    code, sep = t[66:71], t[71:74]
    subj_p, coll_p, city_p, q, rem = t[74:95].strip(), t[95:106].strip(), t[106:117].strip(), t[117:128].strip(), \
        t[128:].strip()
    if not re.fullmatch(r'\d{4}[SIAN]', code) or sep != ' : ':
        raise SystemExit(f'p{page} SrNo {n}: code {code!r}')
    cc, sc, sfx = code[:2], code[2:4], code[4]
    if cc not in COLLEGES or COLLEGES[cc][:2] != (coll_p, city_p):
        raise SystemExit(f'p{page} SrNo {n}: college code {cc} / {coll_p!r} {city_p!r}')
    if sc not in SUBJECTS or SUBJECTS[sc][0] != subj_p:
        raise SystemExit(f'p{page} SrNo {n}: subject code {sc} / {subj_p!r}')
    college = COLLEGES[cc][2]
    _, course, section = SUBJECTS[sc]
    quota, cat, note = quota_cat(sfx, q, rem)
    if quota == 'State Quota-Inservice' and not mark:
        raise SystemExit(f'SrNo {n}: in-service seat to a candidate not marked in-service')
    if quota == 'State Quota-Minority' and 'Minority' not in cand:
        raise SystemExit(f'SrNo {n}: minority seat to a non-minority candidate')
    if cat.endswith('-PH') and 'PwD' not in cand:
        raise SystemExit(f'SrNo {n}: PH seat to a candidate without PwD')
    if quota == 'NRI Quota' and 'NRI' not in cand:
        raise SystemExit(f'SrNo {n}: NRI seat to a non-NRI candidate')
    ver['AIR from the merit list'] += 1
    remarks = '; '.join(x for x in (
        {'I': 'In-service candidate with incentive marks (I)', 'IB': 'In-service candidate without incentive marks (IB)'}
        .get(mark, ''), note, f'Code {code}') if x)
    rows.append({'sno': n, 'rank': sml, 'rank_ai': m['air'],
                 'quota_raw': q + (' (AIQ)' if sfx == 'A' else ''), 'quota': quota,
                 'institute_raw': f'{coll_p}, {city_p}', 'institute': college,
                 'course_raw': subj_p, 'course': course, 'section': section,
                 'allotted_category': cat, 'allotted_category_raw': q, 'candidate_category': cand, 'remarks': remarks})
if len(cat_off) > 3:
    raise SystemExit(f'{len(cat_off)} lines whose Cat. differs from the merit-list category, e.g. SML {cat_off[:10]}')

checks = {'lines': len(lines), 'allotted': len(rows), 'choice_not_available': sum(no_choice.values()),
          'choice_not_available_inservice': no_choice.get('in-service', 0), 'srno_1_to_n': True,
          'sml_ascending': True, 'sml_range': [rows[0]['rank'], rows[-1]['rank']] if rows else None,
          'form_numbers_in_text': forms_in_text, 'candidate_category_matches_merit_list': len(lines) - len(cat_off),
          'candidate_category_differs_sml': cat_off,
          'rank_ai': dict(ver), 'inservice_candidates': sum(1 for _, t in lines if t[4:6].strip()),
          'inservice_vs_inservice_merit_list': dict(ins_check), 'inservice_not_in_list_sml': ins_missing}
if len(ins_missing) > 3:
    raise SystemExit(f'in-service candidates not in the in-service merit list: SML {ins_missing}')
if sm is not None:
    got, got_cat = collections.Counter(), collections.Counter()
    for x in rows:
        smq = 'All India Quota' if x['quota_raw'] == 'I.Q. (AIQ)' else SM_QUOTA.get(x['quota'], x['quota'])
        got[(x['institute'], x['course'], smq)] += 1
        c = x['allotted_category'].replace('IS-', '').replace('-PH', '-PwD')
        c = {'NT1': 'NT-B', 'NT2': 'NT-C', 'NT3': 'NT-D', 'IQ': '', 'NRI': '', 'Minority': '', 'Orphan': 'OPEN-Orphan'}.get(c, c)
        c = c.replace('NT1-', 'NT-B-').replace('NT2-', 'NT-C-').replace('NT3-', 'NT-D-')
        got_cat[(x['institute'], x['course'], smq, c)] += 1
    missing = {' · '.join(k): v for k, v in got.items() if sm.get(k, 0) == 0}
    over = {' · '.join(k): f'{v} allotted / {sm[k]} seats' for k, v in got.items() if 0 < sm.get(k, 0) < v}
    if missing or over:
        raise SystemExit(f'not in the seat matrix: {missing}\nmore allotted than seats: {over}')
    groups = {(k[0], k[1]) for k in got}
    checks['seat_matrix'] = (f'{len(groups)} college × course groups ({len(got)} with quota) all in the matrix, '
                             f'allotted ≤ seats ({sum(sm.values())} seats)')
    checks['seat_matrix_category_over'] = {' · '.join(k): f'{v} allotted / {sm_cat.get(k, 0)} seats'
                                           for k, v in got_cat.items() if v > sm_cat.get(k, 0)}

C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks.update({'by_quota': C('quota'), 'by_section': C('section'), 'by_allotted_category': C('allotted_category'),
               'by_institute': C('institute')})
out = {'authority_code': 'cetcell_mh', 'round': opt['--round'], 'round_order': int(opt['--round-order']),
       'status': opt['--status'],
       'title': f'Provisional Selection List — {opt["--round"]}, State Quota PG Medical (MD/MS/Diploma), Maharashtra',
       'published_on': published, 'source_file_name': os.path.basename(PDF),
       'notes': ('State CET Cell Maharashtra, NEET(PG)-CET 2026 Round 1.0 provisional selection list. rank = SML (state '
                 'merit list no.), rank_ai = NEET PG AIR from the final provisional common state merit list by SML. '
                 'I.Q. = Institutional Quota (incl. the Vikhe Patil / NKP Salve seats the seat matrix calls AIQ); IS = '
                 'State Quota-Inservice; EM<cat> = earmarked seat of that category; PH = PwD seat. "Choice Not '
                 'Available" lines (no seat) are skipped. Form numbers and names never kept.'),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['status'], out['published_on'])
for k, v in checks.items():
    if k != 'by_institute':
        print(k, v)
