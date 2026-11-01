"""Tamil Nadu NEET PG 2026-27 Round 1 seat matrix (Selection Committee / DMER, "TENTATIVE VACANCY FOR PG DEGREE/DIPLOMA
COURSE 2026-2027 IN … MEDICAL COLLEGES AS ON 31-10-2026", 64 pages, text layer) → standardised seat rows, bridged to
Tamil Nadu's 2025 DMER cut-offs. Posted as body "Tamil Nadu — State Counselling", authority_code `dmer_tn`, body
section `state`; rows carry section mdms / diploma (TN prints no DNB). College codes TN-<STANDARD-NAME>
(common.college_code — the same codes the 2025-based state rankings already use, so Desk tiers carry over).
Per the Rounds rule (README) this Round 1 vacancy list IS the state's full seat matrix.

What the file covers (three tables + one breakdown, all state-counselling seats):
  pp 1-33  GOVERNMENT MEDICAL COLLEGES — the state's share only (the 50% All India Quota is MCC's), 26 colleges.
  pp 34-58 SELF FINANCING MEDICAL COLLEGES — government-quota + management-quota seats of 21 private colleges /
           hospitals, incl. Christian Medical College, Vellore (CMC 20% / CMC 50%) and ESI-PGIMSR K.K. Nagar.
  pp 59-62 PRIVATE MEDICAL COLLEGES — one private university (Sri Venkateswaraa, Chennai).
  pp 63-64 "Seat Matrix 2026: Management Quota 50% Christian Medical College, Vellore" — splits each CMC 50% cell into
           Minority Network (MNW) / Institutional Preference (IP) / Service (S) / General Merit (GM).
  Not in the file: deemed universities (MCC), All India Quota seats, DNB.
One block per speciality ("SPECIALITY: M.S. Otorhinolaryngology"); a block can run on to the next page (the heading
is repeated, SNO continues) and ends with its TOTAL line. Columns (every block, every page):
  SNO, COLLEGE, GOVERNMENT QUOTA: OPEN OC BC BCM MBC/DNC SC SCA ST, SERVICE OC … ST, CMC 20%, TOTAL,
  MANAGEMENT QUOTA: MQ, CMC 50%, MINORITY TM MM CM, NRI, TOTAL, OVER ALL TOTAL.
The pages are stored rotated 90°: words and ruling lines are turned to the page as seen, cells are read by the drawn
column / row rules. On the GOVERNMENT pages the management columns and OVER ALL TOTAL are covered by white boxes but
are still in the text layer: they must be empty there (OVER ALL TOTAL = TOTAL, checked).

Quotas (PDF column → stored quota → 2025 TN cut-off quota it bridges to, matched exactly with '$'):
  OPEN OC … ST     → Government Quota          → 'Government Quota'          category as printed (MBC/DNC → 'MBC&DNC')
  SERVICE OC … ST  → Government Quota-Service  → 'Government Quota-Service'  (in-service; left out of rankings)
  CMC 20%          → CMC 20% Quota             → 'CMC 20% Quota'             category '' (not split in 2026; bridges OC,
                                                                              then BC, MBC&DNC)
  MQ               → Management Quota          → 'Management Quota'          category 'OPEN' (2025 wording)
  CMC 50%          → CMC 50% Quota             → 'CMC 50% Quota'             split by pp 63-64: 'CMC-Minority Network',
                     'CMC-Institutional Preference', 'CMC-Service', 'CMC-General Merit' (2025 wording)
  TM / MM / CM     → Management Quota-Minority → 'Management Quota-Minority' 'Telugu Minority' / 'Malayalam Minority' /
                                                                              'Christian Minority' (the page key)
  NRI              → NRI Quota                 → 'NRI Quota'                 category 'NRI'
Government / Service seats with no same-category 2025 rank fall back to the 2025 OC rank (cutoff_category says so).
Sections: M.D. / M.S. / M.Ch. 6-year (Neuro Surgery) → mdms; D.A. / D.C.H. / D.C.P. / D.D.V.L. / D.G.O / D.O. /
D.ORTHO / Dip. in Diabetology → diploma.
Checks (SystemExit on any miss): page count + titles; column headings, group headings and column positions in every
block; footer key on self-financing / private pages; SNO 1…n per block (across pages); every line: OPEN + SERVICE +
CMC 20% = TOTAL, MQ + CMC 50% + TM + MM + CM + NRI = management TOTAL, TOTAL + management TOTAL = OVER ALL TOTAL;
every column = the block's TOTAL line; each speciality once per table; unknown college / speciality / CMC branch;
CMC 20% / 50% only at CMC; the CMC 50% cells = the pp 63-64 CMC 50% column per branch (every branch used), each
branch's MNW + IP + S + GM = CMC 50%, its Total line; output seats = sum of the printed OVER ALL TOTALs.
Run with /usr/bin/python3 (PyMuPDF):  tamil_nadu.py <vacancy.pdf> <cutoffs2025.json> <out.json>"""
import re, sys, os, json, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

if len(sys.argv) != 4:
    raise SystemExit(__doc__)
PDF, CUTS, OUT = sys.argv[1:4]
nows = lambda s: re.sub(r'\s+', '', s or '').upper()

COLLEGES = {  # printed college name → standard institute name (exactly as in the 2025 TN DMER cut-offs)
    # GOVERNMENT MEDICAL COLLEGES
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
    'CUDDALORE MEDICAL COLLEGE, ANNAMALAINAGAR':        # Rajah Muthiah MC, Annamalai Nagar (taken over by Govt as GMC Cuddalore)
        'Rajah Muthiah Medical College, Government Medical College and Hospital, Cuddalore',
    'GOVERNMENT MEDICAL COLLEGE & ESIC HOSPITAL, COIMBATORE': 'Government Medical College and ESIC Hospital, Coimbatore',
    'GOVERNMENT MEDICAL COLLEGE, OMANDURAR': 'Government Medical College, Omandurar',
    'GOVERNMENT MEDICAL COLLEGE, PUDUKOTTAI': 'Government Medical College, Pudukkottai',
    'GOVERNMENT SIVAGANGAI MEDICAL COLLEGE, SIVAGANGA': 'Government Sivgangai Medical College, Sivagangai',
    'GOVT. THIRUVALLUR MEDICAL COLLEGE HOSPITAL,': 'Government Medical College, Thiruvallur',
    'TAMIL NADU. DR. MGR MEDICAL UNIVERSITY': 'Tamil Nadu Dr. M.G.R. Medical University',
    'THENI GOVERNMENT MEDICAL COLLEGE,THENI': 'Government Theni Medical College, Theni',
    'THIRUVARUR GOVT. MEDICAL COLLEGE, THIRUVARUR': 'Government Thiruvarur Medical College, Thiruvarur',
    # SELF FINANCING MEDICAL COLLEGES
    'ANNAPOORNA MEDICAL COLLEGE & HOSPITAL, SALEM': 'Annapoorna Medical College & Hospital, Salem',
    'ARAVIND EYE HOSPITAL, MADURAI': 'Aravind Eye Hospital, Madurai, Tamil Nadu',
    'ARUNAI MEDICAL COLLEGE, TIRUVANNAMALAI': 'Arunai Medical College & Hospital, Tiruvannamalai',
    'CANCER INSTITUTE, ADAYAR': 'Cancer Institute, Adayar',
    'CHRISTIAN MEDICAL COLLEGE, VELLORE': 'Christian Medical College, Vellore',
    'ESI-PGIMSR,ESI HOSPITAL,K.K NAGAR,CHENNAI':          # ESIC Medical College & PGIMSR, K.K. Nagar (2025: same courses)
        'Employees State Insurance Coporation Medical College, Chennai',
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
    # PRIVATE MEDICAL COLLEGES
    'SRI VENKATESWARAA MEDICAL COLLEGE HOSPITAL AND RESEARCH INSTITUTE, CHENNAI (PRIVATE UNIVERSITY)':
        'Sri Venkateswaraa Medical College Hospital and Research Institute, Chennai'}
NEW_COLLEGES = {}   # printed name → new standard name, for colleges not in the 2025 TN cut-offs (none in this file)
TABLES = {  # page title (2nd line) → table; institute type used only for a college not in the 2025 cut-offs
    'GOVERNMENT MEDICAL COLLEGES AS ON 31-10-2026': ('govt', 'Government Institute'),
    'SELF FINANCING MEDICAL COLLEGES AS ON 31-10-2026': ('self', 'Private Institute'),
    'PRIVATE MEDICAL COLLEGES AS ON 31-10-2026': ('private', 'State Private University')}
TITLE1 = 'TENTATIVE VACANCY FOR PG DEGREE/DIPLOMA COURSE 2026-2027 IN'
SPECIALITIES = {  # printed speciality (white space removed) → (course, section)
    'M.S.Otorhinolaryngology': ('MS - ENT (Otorhinolaryngology)', 'mdms'),
    'M.S.Orthopaedics': ('MS - Orthopaedics', 'mdms'),
    'M.S.Ophthalmology': ('MS - Ophthalmology', 'mdms'),
    'M.S.ObstetricsandGynaecology': ('MS - Obstetrics and Gynaecology', 'mdms'),
    'M.S.GeneralSurgery': ('MS - General Surgery', 'mdms'),
    'M.D.RespiratoryMedicine': ('MD - Respiratory Medicine', 'mdms'),
    'M.D.RadioDiagnosis': ('MD - Radio-Diagnosis', 'mdms'),
    'M.D.RadiationOncology': ('MD - Radiotherapy / Radiation Oncology', 'mdms'),
    'M.D.PsychiatricMedicine': ('MD - Psychiatry', 'mdms'),
    'M.D.Physiology': ('MD - Physiology', 'mdms'),
    'M.D.Pharmacology': ('MD - Pharmacology', 'mdms'),
    'M.D.Pathology': ('MD - Pathology', 'mdms'),
    'M.D.Paediatrics': ('MD - Paediatrics', 'mdms'),
    'M.D.Microbiology': ('MD - Microbiology', 'mdms'),
    'M.D.ImmunoHaematologyandTransfusionMedicine':
        ('MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'mdms'),
    'M.D.GeneralMedicine': ('MD - General Medicine', 'mdms'),
    'M.D.ForensicMedicine': ('MD - Forensic Medicine', 'mdms'),
    'M.D.EmergencyMedicine': ('MD - Emergency Medicine', 'mdms'),
    'M.D.D.V.L': ('MD - Dermatology', 'mdms'),
    'M.D.CommunityMedicine': ('MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    'M.D.Biochemistry': ('MD - Biochemistry', 'mdms'),
    'M.D.Anatomy': ('MD/MS - Anatomy', 'mdms'),
    'M.D.Anaesthesiology': ('MD - Anaesthesiology', 'mdms'),
    'M.D.NuclearMedicine': ('MD - Nuclear Medicine', 'mdms'),
    'M.D.Geriatrics': ('MD - Geriatrics', 'mdms'),
    'M.D.FamilyMedicine': ('MD - Family Medicine', 'mdms'),
    'M.D.(P.M.R)': ('MD - Physical Medicine and Rehabilitation', 'mdms'),
    'M.Ch.,6Year(NeuroSurgery)': ('MCh - Neuro Surgery', 'mdms'),           # 6-year post-MBBS M.Ch (2025 'MCh - Neuro Surgery')
    'D.A.': ('Diploma in Anaesthesiology', 'diploma'),
    'D.C.H.': ('Diploma in Child Health / Paediatrics', 'diploma'),
    'D.C.P.': ('Diploma in Pathology', 'diploma'),
    'D.D.V.L.': ('Diploma in Dermatology', 'diploma'),
    'D.G.O': ('Diploma in Obstetrics and Gynaecology', 'diploma'),
    'D.O.': ('Diploma in Ophthalmology', 'diploma'),
    'D.ORTHO': ('Diploma in Orthopaedics', 'diploma'),
    'Dip.inDiabetology': ('Diploma in Diabetology', 'diploma')}
CMC_BRANCHES = {  # pp 63-64 (degree, branch name, white space removed) → course
    ('M.D', 'Anaesthesiology'): 'MD - Anaesthesiology', ('M.D', 'Anatomy'): 'MD/MS - Anatomy',
    ('M.D', 'Biochemistry'): 'MD - Biochemistry', ('M.D', 'D.V.L.'): 'MD - Dermatology',
    ('M.D', 'GeneralMedicine'): 'MD - General Medicine', ('M.D', 'Microbiology'): 'MD - Microbiology',
    ('M.D', 'Paediatrics'): 'MD - Paediatrics', ('M.D', 'Pathology'): 'MD - Pathology',
    ('M.D', 'Pharmacology'): 'MD - Pharmacology', ('M.D', 'Physiology'): 'MD - Physiology',
    ('M.D', 'PsychiatricMedicine'): 'MD - Psychiatry', ('M.D', 'RadioDiagnosis'): 'MD - Radio-Diagnosis',
    ('M.D', 'RadiationOncology'): 'MD - Radiotherapy / Radiation Oncology',
    ('M.D', 'CommunityMedicine'): 'MD - Social & Preventive Medicine / Community Medicine',
    ('M.D', 'RespiratoryMedicine'): 'MD - Respiratory Medicine', ('M.D', 'Geriatrics'): 'MD - Geriatrics',
    ('M.D', 'ImmunoHaema.&Trans.Med.'): 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    ('M.D', 'P.M.R.'): 'MD - Physical Medicine and Rehabilitation', ('M.D', 'EmergencyMedicine'): 'MD - Emergency Medicine',
    ('M.D', 'FamilyMedicine'): 'MD - Family Medicine', ('M.D', 'NuclearMedicine'): 'MD - Nuclear Medicine',
    ('M.S', 'GeneralSurgery'): 'MS - General Surgery', ('M.S', 'ObstetricsandGynaecology'): 'MS - Obstetrics and Gynaecology',
    ('M.S', 'Ophthalmology'): 'MS - Ophthalmology', ('M.S', 'Otorhinolaryngology'): 'MS - ENT (Otorhinolaryngology)',
    ('M.S', 'Orthopaedics'): 'MS - Orthopaedics', ('M.Ch', 'NeuroSurgery'): 'MCh - Neuro Surgery',
    ('DIP', 'D.C.P.'): 'Diploma in Pathology'}
CMC = 'Christian Medical College, Vellore'
CMC_TITLE = 'Seat Matrix 2026: Management Quota 50% Christian Medical College, Vellore'
CMC_HEAD = ['S.NO', 'Branch Name', None, 'CMC 50%', 'Minority Network (MNW)', 'Institutional Preference (IP)', 'Service (S)',
            'General Merit (GM)']
CMC_CATS = ['CMC-Minority Network', 'CMC-Institutional Preference', 'CMC-Service', 'CMC-General Merit']

# column rules on the turned page (x of each drawn vertical rule; the thick rules are filled bars, their middle is used)
RULES = [24.5, 47.0, 269.3, 292.6, 318.5, 346.1, 372.5, 403.3, 432.5, 463.5, 498.5, 528.2, 555.2, 588.5, 618.5, 648.5,
         674.8, 715.2, 757.2, 786.5, 816.5, 836.4, 858.5, 881.9, 905.9, 940.8, 981.6]
HEAD = ['SNO', 'COLLEGE', 'OC', 'BC', 'BCM', 'MBC DNC', 'SC', 'SCA', 'ST', 'OC', 'BC', 'BCM', 'MBC DNC', 'SC', 'SCA', 'ST',
        'CMC 20%', 'TOTAL', 'MQ', 'CMC 50%', 'TM', 'MM', 'CM', 'NRI', 'TOTAL', 'TOTAL']
GROUPS = 'GOVERNMENT QUOTA MANAGEMENT QUOTA OVER OPEN SERVICE MINORITY ALL'
GROUP_COLS = {'GOVERNMENT': (2, 17), 'MANAGEMENT': (18, 24), 'QUOTA': (2, 24), 'OPEN': (2, 8), 'SERVICE': (9, 15), 'MINORITY': (20, 22),
              'OVER': (25, 25), 'ALL': (25, 25)}
FOOTER = 'CM - Christian Minority, MM - Malayalam Minority, TM - Telugu Minority'
CATS = ['OC', 'BC', 'BCM', 'MBC&DNC', 'SC', 'SCA', 'ST']
OPEN_C, SERV_C, CMC20, GTOT, MQ, CMC50, TM, MM, CM, NRI, MTOT, ALLTOT = range(2, 9), range(9, 16), 16, 17, 18, 19, 20, 21, 22, 23, 24, 25
MINORITY = {TM: 'Telugu Minority', MM: 'Malayalam Minority', CM: 'Christian Minority'}
COLNAME = ['SNO', 'COLLEGE'] + ['OPEN ' + c for c in CATS] + ['SERVICE ' + c for c in CATS] + \
          ['CMC 20%', 'TOTAL', 'MQ', 'CMC 50%', 'TM', 'MM', 'CM', 'NRI', 'MANAGEMENT TOTAL', 'OVER ALL TOTAL']

for m in (COLLEGES, NEW_COLLEGES):
    if len({nows(k) for k in m}) != len(m):
        raise SystemExit('two mapping keys are the same without spaces')
NAMES = {nows(k): v for k, v in list(COLLEGES.items()) + list(NEW_COLLEGES.items())}


def col(x):
    """Column index of a word centre, -1 outside the table."""
    if x < RULES[0] or x >= RULES[-1]:
        return -1
    return max(i for i, s in enumerate(RULES[:-1]) if x >= s)


def page_blocks(page):
    """One matrix page → (table, [block]); block = {speciality, y, lines: [{col: text}], where}."""
    where = f'p{page.number + 1}'
    if page.rotation != 90:
        raise SystemExit(f'{where}: page rotation {page.rotation}, expected 90')
    rot = page.rotation_matrix
    ws = []
    for w in page.get_text('words'):
        r = fitz.Rect(w[:4]) * rot
        ws.append((round(r.y0, 1), r.x0, r.x1, w[4]))
    ws.sort()
    rules = []                       # horizontal rules that cross the SNO column (row borders)
    for dr in page.get_drawings():
        for it in dr['items']:
            if it[0] == 're':
                r = it[1] * rot
                if r.height < 3 and r.x0 <= RULES[0] + 1.5 and r.x1 >= RULES[1] - 1:
                    rules.append((r.y0 + r.y1) / 2)
    rules.sort()
    title = [' '.join(t for y, x0, x1, t in ws if abs(y - yy) < 1) for yy in sorted({y for y, *_ in ws if y < 40})]
    if len(title) != 2 or clean(title[0]) != TITLE1 or clean(title[1]) not in TABLES:
        raise SystemExit(f'{where}: page title changed: {title}')
    table = TABLES[clean(title[1])][0]
    specs = [w for w in ws if w[3] == 'SPECIALITY:']
    if not specs or specs[0][0] > 50:
        raise SystemExit(f'{where}: no SPECIALITY heading under the title')
    used = {i for i, w in enumerate(ws) if w[0] < 40}
    blocks = []
    for bi, sp in enumerate(specs):
        sy = sp[0]
        end = specs[bi + 1][0] - 1 if bi + 1 < len(specs) else page.rect.height
        sline = [(i, w) for i, w in enumerate(ws) if abs(w[0] - sy) < 1]
        used |= {i for i, w in sline}
        spec = ''.join(w[3] for i, w in sorted(sline, key=lambda t: t[1][1]) if w[3] != 'SPECIALITY:')
        sno = [w for w in ws if w[3] == 'SNO' and sy < w[0] < end]
        if len(sno) != 1 or col((sno[0][1] + sno[0][2]) / 2) != 0:
            raise SystemExit(f'{where} {spec}: SNO heading not found once')
        hy = sno[0][0]
        # group headings (GOVERNMENT QUOTA … OVER ALL) and column headings
        grp = [(i, w) for i, w in enumerate(ws) if sy + 1 < w[0] < hy - 7]
        heads = [(i, w) for i, w in enumerate(ws) if hy - 7 <= w[0] <= hy + 7]
        used |= {i for i, w in grp + heads}
        gtext = ' '.join(w[3] for i, w in sorted(grp, key=lambda t: (t[1][0], t[1][1])))
        if gtext != GROUPS:
            raise SystemExit(f'{where} {spec}: group headings changed: {gtext!r}')
        for i, w in grp:
            lo, hi = GROUP_COLS[w[3]]
            c = col((w[1] + w[2]) / 2)
            if not lo <= c <= hi:
                raise SystemExit(f'{where} {spec}: group heading {w[3]!r} over column {c}')
        cells = collections.defaultdict(list)
        for i, w in heads:
            cells[col((w[1] + w[2]) / 2)].append(w)
        got = [' '.join(w[3] for w in sorted(cells[c], key=lambda w: (w[0], w[1]))) for c in range(len(HEAD))]
        if got != HEAD or set(cells) != set(range(len(HEAD))):
            raise SystemExit(f'{where} {spec}: column headings changed: {got}')
        # table lines between the row rules under the headings
        L = []
        for y in (y for y in rules if hy + 6 < y < end):
            if not L or y - L[-1] > 3:
                L.append(y)
        if len(L) < 2:
            raise SystemExit(f'{where} {spec}: no table lines')
        lines = []
        for a, b in zip(L, L[1:]):
            cells = collections.defaultdict(list)
            for i, w in enumerate(ws):
                if a <= w[0] + 1 < b:
                    c = col((w[1] + w[2]) / 2)
                    if c < 0:
                        raise SystemExit(f'{where} {spec}: word {w[3]!r} outside the table columns')
                    cells[c].append(w)
                    used.add(i)
            if cells:
                lines.append({c: ' '.join(w[3] for w in sorted(v)) for c, v in cells.items()})
            else:
                raise SystemExit(f'{where} {spec}: empty table line')
        blocks.append({'speciality': spec, 'lines': lines, 'where': f'{where} {spec}', 'bottom': L[-1]})
    rest = [w for i, w in enumerate(ws) if i not in used]
    foot = clean(' '.join(w[3] for w in rest))
    if foot not in (FOOTER, '') or any(w[0] < blocks[-1]['bottom'] for w in rest) or (table != 'govt' and foot != FOOTER):
        raise SystemExit(f'{where}: text outside the tables: {foot!r}')
    return table, blocks


def num(s, where):
    s = clean(s)
    if s and not s.isdigit():
        raise SystemExit(f'{where}: not one whole number: {s!r}')
    return int(s) if s else 0


doc = fitz.open(PDF)
if len(doc) != 64:
    raise SystemExit(f'{len(doc)} pages, expected 64 (re-issued file? check it and update the expectations)')

# ── pp 63-64: CMC Vellore 50% management quota split ──
cmc, cmc_sno, cmc_total = {}, 0, None
for pno in (63, 64):
    page = doc[pno - 1]
    if page.rotation != 0 or CMC_TITLE not in clean(page.get_text()):
        raise SystemExit(f'p{pno}: CMC 50% page title / orientation changed')
    g = grids(page)
    if len(g) != 1 or [clean(x) if x is not None else None for x in g[0][0]] != CMC_HEAD:
        raise SystemExit(f'p{pno}: CMC 50% column headings changed: {g[0][0] if g else g}')
    for r in g[0][1:]:
        if clean(r[0]) == 'Total':
            cmc_total = [num(x, f'p{pno} CMC Total') for x in r[3:8]]
            continue
        if num(r[0], f'p{pno} CMC S.NO') != cmc_sno + 1:
            raise SystemExit(f'p{pno}: CMC S.NO {r[0]!r} after {cmc_sno}')
        cmc_sno += 1
        k = (clean(r[1]), re.sub(r'\s+', '', r[2] or ''))
        if k not in CMC_BRANCHES:
            raise SystemExit(f'p{pno}: unknown CMC branch {r[1:3]}')
        v = [num(x, f'p{pno} CMC {k}') for x in r[3:8]]
        if sum(v[1:]) != v[0]:
            raise SystemExit(f'p{pno}: CMC {k}: MNW + IP + S + GM {v[1:]} ≠ CMC 50% {v[0]}')
        course = CMC_BRANCHES[k]
        if course in cmc:
            raise SystemExit(f'p{pno}: CMC branch {course} printed twice')
        cmc[course] = v
if cmc_total is None:
    raise SystemExit('CMC 50% table: no Total line')
if len(cmc) != len(CMC_BRANCHES):
    raise SystemExit(f'CMC 50% table: branches missing: {sorted(set(CMC_BRANCHES.values()) - set(cmc))}')

# ── pp 1-62: the three vacancy tables ──
rows, checks = [], {}
blocks = collections.OrderedDict()   # (table, speciality) → {lines, total, where}
open_block, last_table = None, None
for page in doc.pages(0, 62):
    table, bl = page_blocks(page)
    if last_table and table != last_table and open_block:
        raise SystemExit(f'p{page.number + 1}: {open_block} has no TOTAL line before the {table} table')
    last_table = table
    for b in bl:
        k = (table, b['speciality'])
        if open_block:
            if k != open_block or b is not bl[0]:
                raise SystemExit(f'{b["where"]}: {open_block[1]} block has no TOTAL line')
        elif k in blocks:
            raise SystemExit(f'{b["where"]}: speciality printed twice in the {table} table')
        else:
            blocks[k] = {'lines': [], 'total': None, 'where': b['where']}
        blk = blocks[k]
        for ln in b['lines']:
            if blk['total'] is not None:
                raise SystemExit(f'{b["where"]}: line after the TOTAL line: {ln}')
            if clean(ln.get(1)) == 'TOTAL' and 0 not in ln:
                blk['total'] = ln
            else:
                blk['lines'].append((ln, b['where']))
        open_block = None if blk['total'] is not None else k
if open_block:
    raise SystemExit(f'{open_block}: no TOTAL line at the end')

cmc_seen = {}
n_lines, printed_all, table_seats = 0, 0, collections.Counter()
college_table = {}
col_sum = collections.defaultdict(lambda: [0] * 26)
col_printed = collections.defaultdict(lambda: [0] * 26)
for (table, spec), blk in blocks.items():
    if nows(spec) not in {nows(s) for s in SPECIALITIES}:
        raise SystemExit(f'{blk["where"]}: unknown speciality {spec!r}')
    course, section = SPECIALITIES[next(s for s in SPECIALITIES if nows(s) == nows(spec))]
    sums, seen = [0] * 26, set()
    for i, (ln, where) in enumerate(blk['lines'], 1):
        if clean(ln.get(0)) != str(i):
            raise SystemExit(f'{where}: SNO {ln.get(0)!r}, expected {i} (sequence broken)')
        inst = clean(ln.get(1))
        if nows(inst) not in NAMES:
            raise SystemExit(f'{where}: unknown college {inst!r}')
        college = NAMES[nows(inst)]
        if college_table.setdefault(college, table) != table:
            raise SystemExit(f'{where}: {college} in two tables ({college_table[college]}, {table})')
        if college in seen:
            raise SystemExit(f'{where}: {college} printed twice in {spec}')
        seen.add(college)
        v = [0, 0] + [num(ln.get(c), f'{where} SNO {i} {COLNAME[c]}') for c in range(2, 26)]
        lab = f'{where} SNO {i} {college}'
        if sum(v[c] for c in list(OPEN_C) + list(SERV_C)) + v[CMC20] != v[GTOT]:
            raise SystemExit(f'{lab}: OPEN + SERVICE + CMC 20% ≠ TOTAL {v[GTOT]}')
        if sum(v[MQ:MTOT]) != v[MTOT]:
            raise SystemExit(f'{lab}: MQ … NRI ≠ management TOTAL {v[MTOT]}')
        if v[GTOT] + v[MTOT] != v[ALLTOT] or v[ALLTOT] < 1:
            raise SystemExit(f'{lab}: TOTAL {v[GTOT]} + management {v[MTOT]} ≠ OVER ALL TOTAL {v[ALLTOT]}')
        if table == 'govt' and any(v[MQ:MTOT + 1]):
            raise SystemExit(f'{lab}: management seats on a government page (hidden columns)')
        if college != CMC and (v[CMC20] or v[CMC50]):
            raise SystemExit(f'{lab}: CMC 20% / 50% seats outside CMC')
        for c in range(2, 26):
            sums[c] += v[c]
        n_lines += 1
        base = {'college': college, 'course': course, 'section': section, 'table': table}
        for c, cat in zip(OPEN_C, CATS):
            if v[c]:
                rows.append(dict(base, quota='Government Quota', category=cat, seats=v[c]))
        for c, cat in zip(SERV_C, CATS):
            if v[c]:
                rows.append(dict(base, quota='Government Quota-Service', category=cat, seats=v[c]))
        if v[CMC20]:
            rows.append(dict(base, quota='CMC 20% Quota', category='', seats=v[CMC20]))
        if v[MQ]:
            rows.append(dict(base, quota='Management Quota', category='OPEN', seats=v[MQ]))
        if v[CMC50]:
            if course not in cmc or cmc[course][0] != v[CMC50]:
                raise SystemExit(f'{lab}: CMC 50% {v[CMC50]} ≠ the pp 63-64 CMC 50% for {course}: {cmc.get(course)}')
            if course in cmc_seen:
                raise SystemExit(f'{lab}: CMC 50% for {course} printed twice')
            cmc_seen[course] = v[CMC50]
            for cat, n in zip(CMC_CATS, cmc[course][1:]):
                if n:
                    rows.append(dict(base, quota='CMC 50% Quota', category=cat, seats=n))
        for c, cat in MINORITY.items():
            if v[c]:
                rows.append(dict(base, quota='Management Quota-Minority', category=cat, seats=v[c]))
        if v[NRI]:
            rows.append(dict(base, quota='NRI Quota', category='NRI', seats=v[NRI]))
    tot = blk['total']
    pv = [0, 0] + [num(tot.get(c), f'{blk["where"]} TOTAL {COLNAME[c]}') for c in range(2, 26)]
    for c in range(2, 26):
        if sums[c] != pv[c]:
            raise SystemExit(f'{blk["where"]}: column {COLNAME[c]} adds to {sums[c]}, TOTAL line {pv[c]}')
        col_sum[table][c] += sums[c]
        col_printed[table][c] += pv[c]
    checks[f'{table} {spec} OVER ALL TOTAL'] = (sums[ALLTOT], pv[ALLTOT])
    printed_all += pv[ALLTOT]
    table_seats[table] += pv[ALLTOT]
for table in ('govt', 'self', 'private'):
    for c in range(2, 26):
        checks[f'{table} column {COLNAME[c]} = sum of the speciality TOTAL lines'] = (col_sum[table][c], col_printed[table][c])
if set(cmc_seen) != set(cmc):
    raise SystemExit(f'CMC 50% branches with no CMC 50% cell in the matrix: {sorted(set(cmc) - set(cmc_seen))}')
checks['CMC 50% cells in the matrix = pp 63-64 CMC 50% Total'] = (sum(cmc_seen.values()), cmc_total[0])
for i, lab in enumerate(['CMC 50%', 'MNW', 'IP', 'S', 'GM']):
    checks[f'pp 63-64 CMC {lab} column = its Total line'] = (sum(v[i] for v in cmc.values()), cmc_total[i])
checks['lines whose columns add to TOTAL / management TOTAL / OVER ALL TOTAL'] = (n_lines, n_lines)
checks['seat rows = sum of the printed OVER ALL TOTAL lines (grand total)'] = (sum(x['seats'] for x in rows), printed_all)
used = set(college_table)
unused = sorted(set(NAMES.values()) - used)
if unused:
    raise SystemExit(f'mapping table has colleges the PDF no longer lists: {unused}')

cuts = load_cuts(CUTS, 'Tamil Nadu')
known = {c['institute'] for c in cuts}
missing = sorted(set(COLLEGES.values()) - known)
if missing:
    raise SystemExit(f'college map points at names not in the 2025 TN cut-offs: {missing}')
clash = sorted(set(NEW_COLLEGES.values()) & known)
if clash:
    raise SystemExit(f'NEW_COLLEGES names that are in the 2025 cut-offs (move them to COLLEGES): {clash}')
TYPE = {t: it for t, it in TABLES.values()}
for x in rows:
    if x['college'] not in known:
        x['institute_type'] = TYPE[x.pop('table')]
    else:
        x.pop('table')

FAMILY = {'Government Quota': ('Government Quota$',), 'Government Quota-Service': ('Government Quota-Service$',),
          'CMC 20% Quota': ('CMC 20% Quota$',), 'CMC 50% Quota': ('CMC 50% Quota$',),
          'Management Quota': ('Management Quota$',), 'Management Quota-Minority': ('Management Quota-Minority$',),
          'NRI Quota': ('NRI Quota$',)}


def cat_match(x):
    q, cat = x['quota'], x['category']
    if q in ('Government Quota', 'Government Quota-Service'):
        return (cat, 'OC') if cat != 'OC' else ('OC',)
    if q == 'CMC 20% Quota':
        return ('OC', 'BC', 'MBC&DNC')
    if q == 'CMC 50% Quota':
        return tuple(dict.fromkeys((cat, 'CMC-General Merit', 'CMC-General')))
    return (cat,)


out = build(rows, cuts, 'Tamil Nadu', 'TN', lambda q: FAMILY[q], cat_match)
codes = collections.defaultdict(set)
for r in out:
    codes[r['college_code']].add(r['college_name'])
if any(len(v) > 1 for v in codes.values()):
    raise SystemExit(f'two colleges share a college code: {[v for v in codes.values() if len(v) > 1]}')
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
print('by table', dict(table_seats), '| colleges', len(used), f'({len(used & known)} in 2025, {len(used - known)} new)')
print('2025 TN colleges not in this file:', sorted(known - used))
