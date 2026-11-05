"""Tamil Nadu (DME Selection Committee) PG Medical MAIN allotment lists of a round → ONE body for
POST /api/pg/results/ingest (round "Round 1", round_order 1). Sibling of tamil_nadu.py, which reads the separate
Government Quota PwD list (round "Round 1 (PwD)", left untouched — the PwD candidates are not in these two lists).
The ingest replaces a whole (authority, year, round), so the GQ and MQ lists go in ONE body; `quota` tells them apart.

Two PDFs, both "Post Graduate Medical(<quota>) Course Session :2026 - 2027 Provisional List of Candidates allotted on
- dd.mm.yyyy", one table per page:
  GQ  SNO, GRANK, APP. NO, NAME, COMMUNITY, SERVICE, T.MARK, ALLOTTED TO ("GQ - <course>" + college), CATEGORY
  MQ  SNO, GRANK, APP. NO, NAME, T.MARK, ALLOTTED TO ("MQ - <course>" / "NRI Category<course>" + college), CATEGORY
PERSONAL DATA: APP. NO and NAME are never read (cells 2 and 3 are skipped).

Ranks: `rank` = GRANK as printed in each list (GQ list = TN Government Quota merit rank, MQ list = TN Management
Quota merit rank — the rank each list allots by; the 2025 TN cut-offs hold the same two kinds of rank). An 'nA'
GRANK (candidate added after rank n by an addendum) is stored as n, the printed text goes in `remarks`.
`rank_ai` is not printed: looked up by GRANK in the loaded merit list of the same quota (--gq-bridge / --mq-bridge,
rows with state_rank / air / score / category). GQ: the merit line with the same COMMUNITY and T.MARK (= merit-list
total marks incl. service incentive) must be the only one. MQ (no community printed): the line with the same T.MARK;
a rank shared with an addendum line is settled by MQ_TIES. MQ_NO_RANK lists lines whose GRANK is printed '0' —
stored with no rank / rank_ai. Anything else unmatched stops the run.
Quota / category (2025 TN cut-off spellings):
  GQ, CATEGORY ''        → 'Government Quota' (SERVICE blank) / 'Government Quota-Service' (SERVICE = Service);
  GQ, CATEGORY 'CMC 20%' → 'CMC 20% Quota' (Christian Medical College only);
  allotted_category = COMMUNITY (OC BC BCM MBC&DNC SC SCA ST — the seat's own category is not printed; the 2025 TN
  cut-offs are filed by the candidate's community too), allotted_category_raw = printed CATEGORY.
  MQ 'Management Quota' → 'Management Quota' / 'OPEN'; 'NRI' ("NRI Category" prefix) → 'NRI Quota' / 'NRI';
  'Telugu Minority' / 'Malayalam Minority' / 'Christian Minority' → 'Management Quota-Minority' / as printed;
  CMC only: 'CMC General' / 'CMC Service' / 'Minority Network' / 'Inst. Preference' → 'CMC 50% Quota' /
  'CMC-General Merit' / 'CMC-Service' / 'CMC-Minority Network' / 'CMC-Institutional Preference'.
candidate_category = COMMUNITY (GQ, printed) / the merit list's community (MQ, not printed). remarks: 'Service'
(GQ in-service), 'GRANK <n>A', 'GRANK printed 0'.
Courses → approved names (same table as tools/seat_matrix/tamil_nadu.py; M.Ch 6-year Neuro Surgery → mdms, diplomas
→ diploma; TN prints no DNB). Colleges → the 2026 TN seat-matrix names (`institute`, same table as the seat matrix).
Checks (SystemExit): titles / dates / headings; SNO 1..N per list; GRANK ascending per list (GRANK 0 lines excepted);
every quota / category / course / college / community known; CMC categories only at CMC and the others never there;
--seat-matrix: per college × course, GQ blank-SERVICE ≤ Government Quota seats, all GQ ≤ Government Quota +
Government Quota-Service seats, CMC 20% ≤ CMC 20% seats, and each MQ quota × category ≤ its seats.
Run with /usr/bin/python3 (PyMuPDF):
    tamil_nadu_r1.py <gq_allotment.pdf> <mq_allotment.pdf> <out.json> --gq-bridge <dmer_tn_gq.json>
                     --mq-bridge <dmer_tn_mq.json> [--seat-matrix <TN seat-matrix dump.json>]
                     [--round "Round 1"] [--round-order 1] [--status provisional|final] [--published-on YYYY-MM-DD]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {'--round': 'Round 1', '--round-order': '1'}
for k in ('--gq-bridge', '--mq-bridge', '--seat-matrix', '--round', '--round-order', '--status', '--published-on'):
    if k in args:
        i = args.index(k); opt[k] = args[i + 1]; del args[i:i + 2]
if len(args) != 3 or '--gq-bridge' not in opt or '--mq-bridge' not in opt:
    raise SystemExit(__doc__)
GQ_PDF, MQ_PDF, OUT = args
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

HEAD = {'GQ': 'SNO GRANK APP. NO NAME COMMUNITY SERVICE T.MARK ALLOTTED TO CATEGORY',
        'MQ': 'SNO GRANK APP. NO NAME T.MARK ALLOTTED TO CATEGORY'}
TITLE = {'GQ': 'Government Quota', 'MQ': 'Management Quota'}
COMMUNITY = {'OC', 'BC', 'BCM', 'MBC&DNC', 'SC', 'SCA', 'ST'}     # 2025 TN spellings
CMC = 'Christian Medical College, Vellore'
GQ_CAT = {'': None, 'CMC 20%': 'CMC 20% Quota'}                  # printed CATEGORY → quota (None = by SERVICE)
MQ_CAT = {  # printed CATEGORY → (quota, allotted_category, printed prefix, CMC only?)
    'Management Quota': ('Management Quota', 'OPEN', 'MQ', False),
    'NRI': ('NRI Quota', 'NRI', 'NRI', False),
    'Telugu Minority': ('Management Quota-Minority', 'Telugu Minority', 'MQ', False),
    'Malayalam Minority': ('Management Quota-Minority', 'Malayalam Minority', 'MQ', False),
    'Christian Minority': ('Management Quota-Minority', 'Christian Minority', 'MQ', False),
    'CMC General': ('CMC 50% Quota', 'CMC-General Merit', 'MQ', True),
    'CMC Service': ('CMC 50% Quota', 'CMC-Service', 'MQ', True),
    'Minority Network': ('CMC 50% Quota', 'CMC-Minority Network', 'MQ', True),
    'Inst. Preference': ('CMC 50% Quota', 'CMC-Institutional Preference', 'MQ', True)}
# MQ merit list: rank 898 is shared by the original line (MBC&DNC, AIR 45025) and '898A' (OC, AIR 45038) added by
# the MQ addendum (1558.pdf); same score 413. A plain printed '898' is the original line.
MQ_TIES = {898: 45025}
MQ_NO_RANK = {199}   # MQ SNO printed with GRANK '0' (T.MARK 413, NRI, between GRANK 898 and 902) — not guessed
COLLEGES = {  # printed → 2026 TN seat-matrix / 2025 cut-off name (same table as tools/seat_matrix/tamil_nadu.py)
    'MADRAS MEDICAL COLLEGE, CHENNAI': 'Madras Medical College, Chennai',
    'STANLEY MEDICAL COLLEGE, CHENNAI': 'Stanley Medical College, Chennai',
    'KILPAUK MEDICAL COLLEGE, CHENNAI': 'Government Kilpauk Medical College, Chennai',
    'MADURAI MEDICAL COLLEGE, MADURAI': 'Madurai Medical College, Madurai',
    'THANJAVUR MEDICAL COLLEGE,THANJAVUR': 'Thanjavur Medical College, Thanjavur',
    'CHENGALPATTU MEDICAL COLLEGE, CHENGALPATTU': 'Chengalpattu Medical College, Chengalpattu',
    'TIRUNELVELI MEDICAL COLLEGE,TIRUNELVELI': 'Government Medical College, Tirunelveli',
    'COIMBATORE MEDICAL COLLEGE, COIMBATORE': 'Coimbatore Medical College, Coimbatore',
    'MOHAN KUMARAMANGALAM MEDICAL COLLEGE, SALEM': 'Government Mohan Kumaramangalam Medical College, Salem',
    'K A P VISWANATHAN GOVERNMENT MEDICAL COLLEGE, TRICHY': 'K.A.P. Viswanatham Government Medical College, Tiruchirapalli',
    'THOOTHUKUDI MEDICAL COLLEGE, THOOTHUKUDI': 'Thoothukudi Medical College, Thoothukudi',
    'KANYAKUMARI GOVERNMENT MEDICAL COLLEGE, ASARIPALLAM': 'Kanyakumari Government Medical College, Asaripallam',
    'GOVERNMENT VELLORE MEDICAL COLLEGE, VELLORE': 'Government Vellore Medical College, Vellore',
    'GOVERNMENT DHARMAPURI MEDICAL COLLEGE, DHARMAPURI': 'Government Dharmapuri Medical College, Dharmapuri',
    'GOVERNMENT VILLUPURAM MEDICAL COLLEGE, VILLUPURAM': 'Government Villupuram Medical College, Villupuram',
    'GOVERNMENT THIRUVANNAMALAI MEDICAL COLLEGE, THIRUVANNAMALAI': 'Government Thiruvannamalai Medical College, Thiruvannamalai',
    'GOVERNMENT ERODE MEDICAL COLLEGE & HOSPITAL, PERUNDURAI': 'Government Erode Medical College & Hospital, Perundurai',
    'CUDDALORE MEDICAL COLLEGE, ANNAMALAINAGAR':
        'Rajah Muthiah Medical College, Government Medical College and Hospital, Cuddalore',
    'GOVERNMENT MEDICAL COLLEGE & ESIC HOSPITAL, COIMBATORE': 'Government Medical College and ESIC Hospital, Coimbatore',
    'GOVERNMENT MEDICAL COLLEGE, OMANDURAR': 'Government Medical College, Omandurar',
    'GOVERNMENT MEDICAL COLLEGE, PUDUKOTTAI': 'Government Medical College, Pudukkottai',
    'GOVERNMENT SIVAGANGAI MEDICAL COLLEGE, SIVAGANGA': 'Government Sivgangai Medical College, Sivagangai',
    'GOVT. THIRUVALLUR MEDICAL COLLEGE HOSPITAL,': 'Government Medical College, Thiruvallur',
    'TAMIL NADU. DR. MGR MEDICAL UNIVERSITY': 'Tamil Nadu Dr. M.G.R. Medical University',
    'THENI GOVERNMENT MEDICAL COLLEGE,THENI': 'Government Theni Medical College, Theni',
    'THIRUVARUR GOVT. MEDICAL COLLEGE, THIRUVARUR': 'Government Thiruvarur Medical College, Thiruvarur',
    'ANNAPOORNA MEDICAL COLLEGE & HOSPITAL, SALEM': 'Annapoorna Medical College & Hospital, Salem',
    'ARAVIND EYE HOSPITAL, MADURAI': 'Aravind Eye Hospital, Madurai, Tamil Nadu',
    'ARUNAI MEDICAL COLLEGE, TIRUVANNAMALAI': 'Arunai Medical College & Hospital, Tiruvannamalai',
    'CANCER INSTITUTE, ADAYAR': 'Cancer Institute, Adayar',
    'CHRISTIAN MEDICAL COLLEGE, VELLORE': CMC,
    'ESI-PGIMSR,ESI HOSPITAL,K.K NAGAR,CHENNAI': 'Employees State Insurance Coporation Medical College, Chennai',
    'INDIRA MEDICAL COLLEGE & HOSPITALS, THIRUVALLUR': 'Indira Medical College & Hospitals, Thiruvallur',
    'JOSEPH EYE HOSPITAL, TRICHY': 'Joseph Eye Hospital, Trichy',
    'KARPAGAM FACULTY OF MEDICAL SCIENCES & RESEARCH, COIMBATORE': 'Karpagam Faculty of Medical Sciences & Research, Coimbatore',
    'KMCH INSTITUTE OF HEALTH SCIENCES AND RESEARCH, COIMBATORE': 'KMCH Institute of Health Sciences and Research, Coimbatore',
    'MADHA MEDICAL COLLEGE AND HOSPITAL, THANDALAM, CHENNAI': 'Madha Medical College and Hospital, Thandalam, Chennai',
    'MELMARUVATHUR ADIPARASAKTHI INSTT. MEDICAL SCIENCES AND RESEARCH':
        'Melmaruvathur Adiparasakthi Institute Medical Sciences and Research, Melmaruvathur',
    'PSG INSTITUTE OF MEDICAL SCIENCES, COIMBATORE': 'PSG Institute of Medical Sciences, Coimbatore',
    'PSP MEDICAL COLLEGE HOSPITAL AND RESEARCH INSTITUTE, KANCHEEPURAM': 'PSP Medical College Hospital and Research Institute, Kancheepuram',
    'SANKARA NETHRALAYA, CHENNAI': 'Sankara Nethralaya, Chennai',
    'SREE MOOKAMBIKA INSTITUTE OF MEDICAL SCIENCES, KANYAKUMARI': 'Sree Mookambigai Institute of Medical Sciences, Kannyakumari',
    'SRI MUTHUKUMARAN MEDICAL COLLEGE,CHENNAI': 'Sri Muthukumaran Medical College and Hospital, Chennai',
    'SWAMY VIVEKANANDHA MEDICAL COLLEGE HOSPITAL AND RESEARCH INSTITUTE': 'Swamy Vivekanandha Medical College Hospital & Research Institute',
    'TAGORE MEDICAL COLLEGE AND HOSPITAL, CHENNAI': 'Tagore Medical College and Hospital, Chennai',
    'TRICHY SRM MEDICAL COLLEGE HOSPITAL & RESEARCH CENTRE, TRICHY': 'Trichy SRM Medical College Hospital & Research Centre, Trichy',
    'VELAMMAL MEDICAL COLLEGE HOSPITAL AND RESEARCH INSTITUTE, MADURAI': 'Velammal Medical College Hospital and Research Institute, Madurai',
    'SRI VENKATESWARAA MEDICAL COLLEGE HOSPITAL AND RESEARCH INSTITUTE, CHENNAI (PRIVATE UNIVERSITY)':
        'Sri Venkateswaraa Medical College Hospital and Research Institute, Chennai'}
COURSES = {  # printed course (white space removed) → (approved course, section)
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
    'M.Ch.,6Year(NeuroSurgery)': ('MCh - Neuro Surgery', 'mdms'),
    'D.A.': ('Diploma in Anaesthesiology', 'diploma'), 'D.C.H.': ('Diploma in Child Health / Paediatrics', 'diploma'),
    'D.C.P.': ('Diploma in Pathology', 'diploma'), 'D.D.V.L.': ('Diploma in Dermatology', 'diploma'),
    'D.G.O': ('Diploma in Obstetrics and Gynaecology', 'diploma'), 'D.O.': ('Diploma in Ophthalmology', 'diploma'),
    'D.ORTHO': ('Diploma in Orthopaedics', 'diploma'), 'Dip.inDiabetology': ('Diploma in Diabetology', 'diploma')}

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()
approved = {c['course'] for c in json.load(open(SHEET))['courses']}
for std, _ in COURSES.values():
    if std not in approved:
        raise SystemExit(f'{std!r} is not in specialty_sheet.json')


def read_list(path, kind):
    """→ (title, status, published, lines). APP. NO and NAME (cells 2, 3) are never read."""
    doc = fitz.open(path)
    top = clean(' '.join(w[4] for w in doc[0].get_text('words') if w[1] < 55))
    m_t = re.search(r'Post Graduate Medical\s*\(\s*(.*?)\s*\)\s*Course Session\s*:?\s*(\d{4}\s*-\s*\d{4})', top)
    m_d = re.search(r'(Provisional|Final) List of Candidates allotted on\s*-\s*(\d{2})\.(\d{2})\.(\d{4})', top)
    if not m_t or not m_d or m_t.group(1) != TITLE[kind]:
        raise SystemExit(f'{kind}: title / "List of Candidates allotted on" line not found or not {TITLE[kind]}')
    ncol = len(HEAD[kind].split(' ')) - 2          # 'APP. NO' and 'ALLOTTED TO' are two words each
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
            allot = (r[-2] or '').split('\n', 1)
            if len(allot) != 2:
                raise SystemExit(f'{kind} SNO {c0}: ALLOTTED TO is not "<quota> - <course>" + college')
            if kind == 'GQ':
                comm, serv, tmark = clean(r[4]), clean(r[5]), clean(r[6])
            else:
                comm, serv, tmark = '', '', clean(r[4])
            lines.append({'sno': int(c0), 'grank': clean(r[1]), 'comm': comm, 'serv': serv, 'tmark': tmark,
                          'qc': clean(allot[0]), 'college': clean(allot[1]), 'cat': clean(r[-1])})
    sn = [x['sno'] for x in lines]
    if sn != list(range(1, len(sn) + 1)):
        raise SystemExit(f'{kind}: serial numbers are not 1..{len(sn)} in order')
    return m_t, m_d, lines


def merit(path):
    by = collections.defaultdict(list)
    for x in json.load(open(path))['rows']:
        by[x['state_rank']].append(x)
    return by


GQB, MQB = merit(opt['--gq-bridge']), merit(opt['--mq-bridge'])
rows, unknown, ai_how, order_breaks = [], collections.Counter(), collections.Counter(), {}
heads = {}
for kind, path in (('GQ', GQ_PDF), ('MQ', MQ_PDF)):
    m_t, m_d, lines = read_list(path, kind)
    heads[kind] = (m_t, m_d, len(lines))
    prev = 0
    breaks = []
    for x in lines:
        sno, g = x['sno'], x['grank']
        mg = re.fullmatch(r'(\d+)(A?)', g)
        if not mg:
            unknown[f'{kind} GRANK: {g}'] += 1; continue
        grank, addendum = int(mg.group(1)), bool(mg.group(2))
        if not re.fullmatch(r'\d+(\.\d+)?', x['tmark']):
            unknown[f'{kind} T.MARK: ' + x['tmark']] += 1; continue
        if kind == 'GQ':
            mq = re.fullmatch(r'GQ\s*-\s*(.+)', x['qc'])
            q_raw, course_raw = 'GQ', (mq.group(1) if mq else '')
        else:
            mq = re.fullmatch(r'MQ\s*-\s*(.+)', x['qc']) or re.fullmatch(r'NRI Category\s*(.+)', x['qc'])
            q_raw = 'MQ' if x['qc'].startswith('MQ') else 'NRI'
            course_raw = mq.group(1) if mq else ''
        if not mq:
            unknown[f'{kind} allotted to: ' + x['qc']] += 1; continue
        ck = re.sub(r'\s+', '', course_raw)
        if ck not in COURSES:
            unknown['course: ' + course_raw] += 1; continue
        if x['college'] not in COLLEGES:
            unknown['college: ' + x['college']] += 1; continue
        inst = COLLEGES[x['college']]
        course, sec = COURSES[ck]
        remarks = []
        if kind == 'GQ':
            if x['comm'] not in COMMUNITY:
                unknown['community: ' + x['comm']] += 1; continue
            if x['serv'] not in ('', 'Service'):
                unknown['service: ' + x['serv']] += 1; continue
            if x['cat'] not in GQ_CAT:
                unknown['GQ category: ' + x['cat']] += 1; continue
            quota = GQ_CAT[x['cat']] or ('Government Quota-Service' if x['serv'] else 'Government Quota')
            if (x['cat'] == 'CMC 20%') != (inst == CMC and x['cat'] == 'CMC 20%'):
                raise SystemExit(f'GQ SNO {sno}: CMC 20% outside CMC')
            acat, cand = x['comm'], x['comm']
            if x['serv']:
                remarks.append('Service')
            cands = GQB.get(grank, [])
            hit = [m for m in cands if m['category'] == x['comm'] and abs(float(m['score']) - float(x['tmark'])) < 0.005]
            if len(hit) != 1:
                raise SystemExit(f'GQ SNO {sno}: GRANK {g} has {len(cands)} merit-list lines, {len(hit)} with the same '
                                 f'community + total marks')
            ai_how['GQ ' + ('unique GRANK' if len(cands) == 1 else 'shared GRANK (nA) — community + T.MARK')] += 1
            rank, rank_ai = grank, int(hit[0]['air'])
        else:
            if x['cat'] not in MQ_CAT:
                unknown['MQ category: ' + x['cat']] += 1; continue
            quota, acat, prefix, cmc_only = MQ_CAT[x['cat']]
            if prefix != q_raw:
                raise SystemExit(f'MQ SNO {sno}: category {x["cat"]!r} printed with prefix {q_raw!r}')
            if cmc_only != (inst == CMC):
                raise SystemExit(f'MQ SNO {sno}: category {x["cat"]!r} at {inst}')
            if grank == 0:
                if sno not in MQ_NO_RANK:
                    raise SystemExit(f'MQ SNO {sno}: GRANK printed 0')
                rank, rank_ai, cand = None, None, ''
                remarks.append('GRANK printed 0')
                ai_how['MQ GRANK printed 0 — not filled'] += 1
            else:
                cands = MQB.get(grank, [])
                hit = [m for m in cands if abs(float(m['score']) - float(x['tmark'])) < 0.005]
                if len(hit) > 1 and grank in MQ_TIES and not addendum:
                    hit = [m for m in hit if int(m['air']) == MQ_TIES[grank]]
                    ai_how['MQ shared GRANK — MQ_TIES (original line, not the addendum)'] += 1
                elif len(hit) == 1:
                    ai_how['MQ unique GRANK — T.MARK agrees'] += 1
                if len(hit) != 1:
                    raise SystemExit(f'MQ SNO {sno}: GRANK {g} has {len(cands)} merit-list lines, {len(hit)} with the '
                                     f'same total marks')
                rank, rank_ai, cand = grank, int(hit[0]['air']), hit[0]['category']
        if addendum:
            remarks.append(f'GRANK {g}')
        if rank is not None:
            if rank < prev:
                breaks.append(sno)
            prev = rank
        rows.append({'sno': sno, 'rank': rank, 'rank_ai': rank_ai, 'quota_raw': q_raw, 'quota': quota,
                     'institute_raw': x['college'], 'institute': inst, 'course_raw': course_raw, 'course': course,
                     'section': sec, 'allotted_category': acat, 'allotted_category_raw': x['cat'],
                     'candidate_category': cand, 'remarks': ', '.join(remarks)})
    order_breaks[kind] = breaks
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
if any(order_breaks.values()):
    raise SystemExit(f'GRANK not ascending at SNO {order_breaks}')
n_lines = heads['GQ'][2] + heads['MQ'][2]
if len(rows) != n_lines:
    raise SystemExit('rows ≠ lines')
dates = {(h[1].group(1), h[1].group(2), h[1].group(3), h[1].group(4), h[0].group(2)) for h in heads.values()}
if len(dates) != 1:
    raise SystemExit(f'the two lists differ in status / date / session: {dates}')
st, dd, mm, yy, session = dates.pop()
status = opt.get('--status') or st.lower()
published = opt.get('--published-on') or f'{yy}-{mm}-{dd}'

checks = {'lines': {'GQ': heads['GQ'][2], 'MQ': heads['MQ'][2], 'total': n_lines}, 'sno_1_to_n_per_list': True,
          'grank_ascending_per_list': True}
if '--seat-matrix' in opt:
    sm = collections.Counter()
    for s in json.load(open(opt['--seat-matrix']))['rows']:
        sm[(s['college_name'], s['course_name'], s['quota'], s['category'])] += s['seats']
    smq = collections.Counter()
    for (c, co, q, cat), n in sm.items():
        smq[(c, co, q)] += n
    got = collections.defaultdict(collections.Counter)
    for r in rows:
        k = (r['institute'], r['course'])
        if r['quota'] == 'Government Quota':
            got[k]['gq_open'] += 1; got[k]['gq_all'] += 1
        elif r['quota'] == 'Government Quota-Service':
            got[k]['gq_all'] += 1
        elif r['quota'] == 'CMC 20% Quota':
            got[k]['cmc20'] += 1
        elif r['quota'] == 'Management Quota-Minority' or r['quota'] == 'CMC 50% Quota':
            got[k][(r['quota'], r['allotted_category'])] += 1
        else:
            got[k][(r['quota'],)] += 1
    bad, groups = {}, 0
    for (c, co), cnt in got.items():
        groups += 1
        cap = {'gq_open': smq[(c, co, 'Government Quota')],
               'gq_all': smq[(c, co, 'Government Quota')] + smq[(c, co, 'Government Quota-Service')],
               'cmc20': smq[(c, co, 'CMC 20% Quota')]}
        for key, n in cnt.items():
            if isinstance(key, tuple):
                lim = smq[(c, co, key[0])] if len(key) == 1 else sm[(c, co, key[0], key[1])]
            else:
                lim = cap[key]
            if n > lim:
                bad[f'{c} · {co} · {key}'] = f'{n} allotted / {lim} seats'
    if bad:
        raise SystemExit(f'more allotted than seat-matrix seats: {bad}')
    cc = {(r['institute'], r['course']) for r in rows}
    checks['seat_matrix'] = (f'{len(cc)} college × course groups, all within the matrix ({sum(sm.values())} seats): '
                             f'GQ open ≤ Government Quota, GQ all ≤ Government Quota + Service, CMC 20%, each MQ '
                             f'quota × category')

C = lambda f, rr=rows: dict(collections.Counter(x[f] for x in rr).most_common())
for kind in ('GQ', 'MQ'):
    rr = [x for x in rows if (x['quota_raw'] == 'GQ') == (kind == 'GQ')]
    rk = [x['rank'] for x in rr if x['rank'] is not None]
    ai = [x['rank_ai'] for x in rr if x['rank_ai'] is not None]
    checks[kind] = {'rows': len(rr), 'by_quota': C('quota', rr), 'by_allotted_category': C('allotted_category', rr),
                    'by_section': C('section', rr), 'grank': [min(rk), max(rk)], 'air': [min(ai), max(ai)],
                    'rank_ai_filled': len(ai), 'rank_ai_missing': len(rr) - len(ai)}
checks.update({'by_section': C('section'), 'by_quota': C('quota'), 'by_remarks': C('remarks'),
               'colleges': len({x['institute'] for x in rows}),
               'rank_ai': {'source': f'TN merit lists by GRANK ({os.path.basename(opt["--gq-bridge"])}, '
                                     f'{os.path.basename(opt["--mq-bridge"])})',
                           'filled': sum(1 for x in rows if x['rank_ai'] is not None),
                           'not_filled': sum(1 for x in rows if x['rank_ai'] is None), 'how': dict(ai_how)}})
out = {'authority_code': 'dmer_tn', 'round': opt['--round'], 'round_order': int(opt['--round-order']),
       'status': status,
       'title': f'Post Graduate Medical (Government Quota + Management Quota) Course Session {session} — '
                f'{st} List of Candidates allotted',
       'published_on': published,
       'source_file_name': f'GQ: {os.path.basename(GQ_PDF)} + MQ: {os.path.basename(MQ_PDF)}',
       'notes': ('Tamil Nadu Selection Committee main lists: Government Quota (incl. CMC 20%) + Management Quota '
                 '(incl. NRI, minority, CMC 50%) in one round; the GQ PwD list is its own round "Round 1 (PwD)". '
                 'rank = GRANK of each list (GQ merit rank for GQ rows, MQ merit rank for MQ/NRI rows); rank_ai not '
                 'printed — from the TN GQ / MQ merit lists by GRANK. GQ seat category not printed: '
                 'allotted_category = candidate community (2025 TN convention); in-service GQ candidates → '
                 'Government Quota-Service. sno = the serial number of each list (GQ and MQ both start at 1).'),
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print(out['title'], '|', out['round'], out['round_order'], out['status'], out['published_on'])
for k in ('lines', 'by_section', 'by_quota', 'colleges', 'rank_ai', 'seat_matrix'):
    print(k, checks.get(k))
for kind in ('GQ', 'MQ'):
    print(kind, checks[kind])
