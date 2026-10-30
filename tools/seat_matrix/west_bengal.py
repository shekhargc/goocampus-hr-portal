"""West Bengal NEET PG 2026 Round 1 seat matrix (WBMCC, "West Bengal PG Medical Counselling 2026 · Round No: 1 ·
Seat Matrix", printed 30/10/2026, 121 pages) → standardised seat rows, bridged to West Bengal's 2025 cut-offs.
Posted as body "West Bengal — State Counselling", authority_code `wbmcc`, body section `state`; rows carry
section mdms / diploma / dnb. College codes WB-<STANDARD-NAME> (common.college_code).
The pages are stored rotated 90° (landscape), so every word is turned to the page as seen before it is read.
One table: one line per institute × program × quota — SNo, Institute Name, Institute Type, Program Name, Stream,
Quota, UR, UR PwD, EWS, EWS PwD, OBC, OBC PwD, SC, SC PwD, ST, ST PwD, Total Seats. Blank cells are zero; the cell
text wraps mid-word ("MIDNAPOR E"), so names are compared with all white space removed.
The PDF prints NO totals of any kind (no per-page, per-institute, per-quota or grand total — only the 878 lines
and a header / footer on every page). Checks instead: the column headings, the page header and "Page No." on every
page, the SNo sequence 1…878 with no gap or repeat, every line's ten categories add to its Total Seats, every cell
is one whole number, no word lies outside a line, and the output rows re-add to the sum of the Total Seats column.
It stops on any unknown institute, program, quota, stream or institute type instead of guessing.

Quotas (PDF → stored quota → 2025 WBMCC cut-off quota it bridges to, matched exactly with '$'):
  Open Seat Quota          → State Quota                 → 'State Quota'
  In Service Quota         → In-service Quota            → 'State Quota-Inservice'
  Private Management Quota → Management Quota            → 'Management Quota'
  NRI Quota                → NRI Quota                   → 'NRI Quota'
  In Service DNB Quota     → DNB Quota (In-service)      (NBEMS DNB lines; WB 2025 has no DNB cut-offs → new)
                           → Diploma Quota (In-service)  (NBEMS post-MBBS diploma lines; no 2025 cut-off → new)
Categories as printed: UR / EWS / OBC / SC / ST, PwD seats "-PwD" (2025 writes them "UR-PH").
Bridge categories: X-PwD → 2025 'X-PH', then X; OBC → 2025 'OBC', then 'OBC-A', then 'OBC-B' (2025 split WB's OBC into
A / B; the PDF prints one OBC column, cutoff_category says which was used); Management Quota → 2025 'MQ';
NRI Quota → 'UR', then 'NRI'. With no category match common.build uses the 2025 UR rank (cutoff_category says so).
Sections: MD / MS / M.P.H. → mdms; DIPLOMA IN … (medical college) and (NBEMS- DIPLOMA) … → diploma ("Diploma in …");
(NBEMS) … → dnb, "DNB - <course> (Post-MBBS)" — the two "(DIRECT 6 YEARS COURSE)" programs use the MCC DNB name
"DNB - … (Direct 6 Years Course)". DNB rows are hidden from doctors by HIDE_DNB.
Institute type: the 2025 cut-off type for known colleges, else State / Central Government → Government Institute,
Private University/Institute → Private Institute.
Run with /usr/bin/python3 (PyMuPDF):  west_bengal.py <matrix.pdf> <cutoffs2025.json> <out.json>"""
import re, sys, os, json, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report

if len(sys.argv) != 4:
    raise SystemExit(__doc__)
MATRIX, CUTS, OUT = sys.argv[1:4]
nows = lambda s: re.sub(r'\s+', '', s or '').upper()

COLLEGES = {  # PDF Institute Name → standard institute name (exactly as in the 2025 WBMCC cut-offs)
    'ALL INDIA INSTITUTE OF HYGIENE AND PUBLIC HEALTH': 'All India Institute of Hygiene and Public Health, Kolkata',
    'BANKURA SAMMILANI MEDICAL COLLEGE': 'Bankura Sammilani Medical College, Bankura',
    'BURDWAN MEDICAL COLLEGE': 'Burdwan Medical College, Burdwan',
    'CALCUTTA NATIONAL MEDICAL COLLEGE KOLKATA': 'Calcutta National Medical College, Kolkata',
    'CHITTARANJAN SEVA SADAN COLLEGE OF OBS. GYNAE AND CHILD HEALTH,KOLKATA': 'Chittaranjan Seva Sadan Hospital, Kolkata',
    'COLLEGE OF MEDICINE AND JNM HOSPITAL KALYANI': 'College of Medicine and JNM Hospital, Kalyani, Nadia, West Bengal',
    'COLLEGE OF MEDICINE AND SAGORE DUTTA HOSPITAL': 'College of Medicine and Sagore Dutta Hospital, Kolkata',
    'COMMAND HOSPITAL EC, ALIPORE, KOLKATA': 'Command Hospital (Eastern Command), Kolkata',
    'DIAMOND HARBOUR GOVERNMENT MEDICAL COLLEGE AND HOSPITAL':
        'Diamond Harbour Government Medical College and Hospital, South 24 Parganas, West Bengal',
    'DR. B C ROY POST GRADUATE INSTITUTE OF PAEDIATRIC SCIENCES': 'Dr. B C Roy Post Graduate Institute of Paediatric Sciences, Kolkata',
    'ESI PGIMSR AND ESIC MEDICAL COLLEGE JOKA KOLKATA': 'Employees State Insurance Corporation Medical College, Joka, Kolkata',
    'GOURI DEVI INSTITUTE OF MEDICAL SCIENCES AND HOSPITAL': 'Gouri Devi Institute of Medical Sciences and Hospital, Durgapur',
    'ICARE INSTITUTE OF MEDICAL SCIENCES AND RESEARCH HALDIA': 'ICARE Institute of Medical Sciences & Research, Haldia, Purba Midanpore',
    'INSTITUTE OF CHILD HEALTH': 'Institute of Child Health, Ballygunge, Kolkata, West Bengal',
    'INSTITUTE OF POST GRADUATE MEDICAL EDUCATION AND RESEARCH KOLKATA': 'Institute of Postgraduate Medical Education & Research, Kolkata',
    'IQ CITY MEDICAL COLLEGE, DURGAPUR': 'IQ-City Medical College, Burdwan',
    'JAGANNATH GUPTA INSTITUTE OF MEDICAL SCIENCES AND HOSPITAL':
        'Jagannath Gupta Institute of Medical Sciences and Hospital, Buita, Kolkata, West Bengal',
    'JIS SCHOOL OF MEDICAL SCIENCE & RESEARCH': 'JIS School of Medical Science & Research, Howrah',
    'KPC MEDICAL COLLEGE': 'KPC Medical College, Jadavpur, Kolkata',
    'MALDA MEDICAL COLLEGE AND HOSPITAL': 'Malda Medical College & Hospital, Malda',
    'MEDICAL COLLEGE KOLKATA': 'Government Medical College, Kolkata',    # 2025's name for Medical College, Kolkata
    'MIDNAPORE MEDICAL COLLEGE': 'Midnapore Medical College, Midnapore',
    'MURSHIDABAD MEDICAL COLLEGE AND HOSPITAL': 'Murshidabad Medical College & Hospitals, Murshidabad',
    'NIL RATAN SIRCAR MEDICAL COLLEGE': 'Nil Ratan Sircar Medical College, Kolkata',
    'NORTH BENGAL MEDICAL COLLEGE AND HOSPITAL': 'North Bengal Medical College, Darjeeling',
    'R G KAR MEDICAL COLLEGE': 'RG Kar Medical College, Kolkata',
    'RAMAKRISHNA MISSION SEVA PRATISHTHAN VIVEKANANDA INSTITUTE OF MEDICAL SCIENCES, KOLKATA':
        'Ramakrishna Mission Seva Pratishthan, Vivekananda Institute of Medical Sciences, Kolkata',
    'SCHOOL OF TROPICAL MEDICINE, KOLKATA': 'Calcutta School of Tropical Medicine, West Bengal',
    'SHRI RAMKRISHNA INSTITUTE OF MEDICAL SCIENCES & SANAKA HOSPITALS':
        'Shri Ramkrishna Institute of Medical Sciences & Sanaka Hospitals, Durgapur'}
NEW_COLLEGES = {  # not in the 2025 WBMCC cut-offs: new standard name (place from the NBEMS / MCC DNB address list)
    'ASANSOL DISTRICT HOSPITAL': 'Asansol District Hospital, Asansol',
    'BALURGHAT DH AND SSH': 'Balurghat District Hospital and Super Speciality Hospital, Balurghat',
    'BARASAT GOVERNMENT MEDICAL COLLEGE AND HOSPITAL': 'Barasat Government Medical College and Hospital, Barasat',
    'BISHNUPUR DISTRICT HOSPITAL': 'Bishnupur District Hospital, Bankura',
    'BOLPUR SUB DIVISION HOSPITAL': 'Bolpur Sub Division Hospital, Birbhum',
    'CHANDAN NAGAR SUB DIVISION HOSPITAL': 'Chandannagar Sub Division Hospital, Hooghly',
    'DEBEN MAHATO SADAR HOSPITAL, PURULIA': 'Deben Mahato Sadar Hospital, Purulia',
    'DINHATA SUB DIVISIONAL HOSPITAL': 'Dinhata Sub Divisional Hospital, Cooch Behar',
    'DISTRICT HOSPITAL DARJEELING': 'District Hospital, Darjeeling',
    'DISTRICT HOSPITAL HOWRAH': 'District Hospital, Howrah',
    'DISTRICT HOSPITAL NADIA': 'District Hospital, Krishnagar, Nadia',
    'DOMKAL SUB DIVISIONAL AND SUPER SPECIALITY HOSPITAL': 'Domkal Sub Divisional and Super Speciality Hospital, Murshidabad',
    'DURGAPUR SUB DIVISIONAL HOSPITAL': 'Durgapur Sub Divisional Hospital, Durgapur',
    'HABRA STATE GENERAL HOSPITAL': 'Habra State General Hospital, North 24 Parganas',
    'HALDIA SUB DIVISIONAL HOSPITAL': 'Haldia Sub Divisional Hospital, Purba Medinipur',
    'IMAMBARA DISTRICT HOSPITAL': 'Imambara District Hospital, Hooghly',
    'INFECTIOUS DISEASES AND BELIAGHATA GENERAL HOSPITAL': 'Infectious Diseases and Beliaghata General Hospital, Kolkata',
    'ISLAMPUR SUB DIVISIONAL HOSPITAL': 'Islampur Sub Divisional Hospital, Uttar Dinajpur',
    'JANGIPUR S. D. HOSPITAL': 'Jangipur Sub Divisional Hospital, Murshidabad',
    'Jalpaiguri Government Medical College and Hospital (Formerly DISTRICT HOSPITAL) JALPAIGURI':
        'Jalpaiguri Government Medical College and Hospital, Jalpaiguri',
    'KALNA SD AND SS HOSPITAL': 'Kalna Sub Divisional and Super Speciality Hospital, Purba Bardhaman',
    'KATWA SUB DIVISIONAL HOSPITAL': 'Katwa Sub Divisional Hospital, Purba Bardhaman',
    'KHARAGPUR SUB DIVISIONAL HOSPITAL': 'Kharagpur Sub Divisional Hospital, Paschim Medinipur',
    'KHATRA SUB DIVISIONAL HOSPITAL': 'Khatra Sub Divisional Hospital, Bankura',
    'LALBAGH SUB DIVISION HOSPITAL': 'Lalbagh Sub Division Hospital, Murshidabad',
    'M R BANGUR HOSPITAL': 'M R Bangur Hospital, Kolkata',
    'MAHARAJA JITENDRA NARAYAN MEDICAL COLLEGE AND HOSPITAL': 'Maharaja Jitendra Narayan Medical College and Hospital, Cooch Behar',
    'MAL SUPER SPECIALITY HOSPITAL': 'Mal Super Speciality Hospital, Jalpaiguri',
    'PRAFULLA CHANDRA SEN GOVT. MEDICAL COLLEGE AND HOSPITAL': 'Prafulla Chandra Sen Government Medical College and Hospital, Arambagh',
    'RAIGANJ GOVERNMENT MEDICAL COLLEGE AND HOSPITAL': 'Raiganj Government Medical College and Hospital, Raiganj',
    'RAMPURHAT GOVT. MEDICAL COLLEGE AND HOSPITAL': 'Rampurhat Government Medical College and Hospital, Rampurhat',
    'RANAGHAT SUB DIVISIONAL HOSPITAL': 'Ranaghat Sub Divisional Hospital, Nadia',
    'SILIGURI DISTRICT HOSPITAL': 'Siliguri District Hospital, Siliguri',
    'SURI SADAR HOSPITAL': 'Suri Sadar Hospital, Birbhum',
    'TAMRALIPTO GOVERNMENT MEDICAL COLLEGE': 'Tamralipto Government Medical College, Tamluk',
    'UTTARPARA STATE GENERAL HOSPITAL': 'Uttarpara State General Hospital, Hooghly',
    'WALSH S.D.H., SERAMPORE': 'Walsh Sub Divisional Hospital, Serampore'}
PROGRAMS = {  # PDF Program Name → (course name, section)
    'M.D. (ANAESTHESIOLOGY) (ASTH)': ('MD - Anaesthesiology', 'mdms'),
    'M.D. (BIOCHEMISTRY) (BIOC)': ('MD - Biochemistry', 'mdms'),
    'M.D. (DERM.,VENE. AND LEPROSY)/(DERMATOLOGY)/(SKIN AND VENEREAL DISEASES)/(VENEREOLOGY) (DV-L)': ('MD - Dermatology', 'mdms'),
    'M.D. (EMERGENCY AND CRITICAL CARE)/M.D. (EMERGENCY MEDICINE) (E-CC)': ('MD - Emergency Medicine', 'mdms'),
    'M.D. (FORENSIC MEDICINE) (FMED)': ('MD - Forensic Medicine', 'mdms'),
    'M.D. (GENERAL MEDICINE) (GMED)': ('MD - General Medicine', 'mdms'),
    'M.D. GERIATRICS (GERA)': ('MD - Geriatrics', 'mdms'),
    'M.D. (MICROBIOLOGY) (MICR)': ('MD - Microbiology', 'mdms'),
    'M.D. (OBST. AND GYNAE)/MS (OBSTETRICS AND GYNAECOLOGY) (OBGY)': ('MS - Obstetrics and Gynaecology', 'mdms'),
    'M.D. (PAEDIATRICS) (PAED)': ('MD - Paediatrics', 'mdms'),
    'M.D. (PATHOLOGY) (PATH)': ('MD - Pathology', 'mdms'),
    'M.D. (PHARMACOLOGY) (PHAR)': ('MD - Pharmacology', 'mdms'),
    'M.D. (PHYSICAL MED. AND REHABILITATION) (PM-R)': ('MD - Physical Medicine and Rehabilitation', 'mdms'),
    'M.D. (PHYSIOLOGY) (PHYS)': ('MD - Physiology', 'mdms'),
    'M.D. (PREVENTIVE AND SOCIAL MEDICINE)/COMMUNITY MEDICINE (P-SM)': ('MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    'M.D. (PSYCHIATRY) (PSYY)': ('MD - Psychiatry', 'mdms'),
    'M.D. (RADIO-DIAGNOSIS) (RADD)': ('MD - Radio-Diagnosis', 'mdms'),
    'M.D. (RADIOTHERAPY/RADIATION ONCOLOGY) (RADT)': ('MD - Radiotherapy / Radiation Oncology', 'mdms'),
    'M.D. IN TRANSFUSION MEDICINE/IMMUNO-HAEMATOLOGY AND BLOOD TRANSFUSION (T-FM)':
        ('MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'mdms'),
    'M.D. (TROPICAL MEDICINE) (TMED)': ('MD - Tropical Medicine', 'mdms'),
    'M.D. (TUBERCULOSIS AND RESPIRATORY DISEASES)/PULMONARY MEDICINE/M.D. (RESPIRATORY MEDICINE) (TBRD)':
        ('MD - Respiratory Medicine', 'mdms'),
    'M.P.H. (EPIDEMIOLOGY) (DMPH)': ('MPH - Epidemiology', 'mdms'),
    'M.S. (E.N.T.) (EN-T)': ('MS - ENT (Otorhinolaryngology)', 'mdms'),
    'M.S. (GENERAL SURGERY) (GSUR)': ('MS - General Surgery', 'mdms'),
    'M.S. (OPHTHALMOLOGY) (OPTH)': ('MS - Ophthalmology', 'mdms'),
    'M.S. (ORTHOPAEDICS) (ORTH)': ('MS - Orthopaedics', 'mdms'),
    'MD/MS (ANATOMY) (ANAT)': ('MD/MS - Anatomy', 'mdms'),
    # medical-college diplomas
    'DIP.IN GYNAE. AND OBST. (D-GO)': ('Diploma in Obstetrics and Gynaecology', 'diploma'),
    'DIPLOMA IN ANAESTHESIOLOGY (D-AN)': ('Diploma in Anaesthesiology', 'diploma'),
    'DIPLOMA IN CHILD HEALTH/PAEDIATRICS (D-CH)': ('Diploma in Child Health / Paediatrics', 'diploma'),
    'DIPLOMA IN CLINICAL PATHOLOGY (D-CP)': ('Diploma in Pathology', 'diploma'),
    'DIPLOMA IN OPHTHALMOLOGY/DOMS (D-OP)': ('Diploma in Ophthalmology', 'diploma'),
    'DIPLOMA IN ORTHOPAEDICS (DORT)': ('Diploma in Orthopaedics', 'diploma'),
    'DIPLOMA IN OTO-RHINO-LARYNGOLOGY (D-LO)': ('Diploma in ENT', 'diploma'),
    # NBEMS post-MBBS diplomas (named like gujarat.py / rajasthan.py)
    '(NBEMS-DIPLOMA) ANAESTHESIOLOGY (NBDA)': ('Diploma in Anaesthesiology', 'diploma'),
    '(NBEMS-DIPLOMA) OBSTETRICS AND GYNAECOLOGY (NDGO)': ('Diploma in Obstetrics and Gynaecology', 'diploma'),
    '(NBEMS-DIPLOMA) OPHTHALMOLOGY (NBDO)': ('Diploma in Ophthalmology', 'diploma'),
    '(NBEMS-DIPLOMA) OTORHINOLARYNGOLOGY (E.N.T.) (NDLO)': ('Diploma in ENT', 'diploma'),
    '(NBEMS-DIPLOMA) PAEDIATRICS (NDCH)': ('Diploma in Child Health / Paediatrics', 'diploma'),
    '(NBEMS-DIPLOMA) RADIO-DIAGNOSIS (NDMR)': ('Diploma in Radio Diagnosis', 'diploma'),
    '(NBEMS-DIPLOMA) TUBERCULOSIS AND CHEST DISEASES (NDTC)': ('Diploma in Respiratory Medicine', 'diploma'),
    # NBEMS DNB (post-MBBS broad specialities; the direct 6-year programs keep MCC DNB's name)
    '(NBEMS) ANAESTHESIOLOGY (DANS)': ('DNB - Anaesthesiology (Post-MBBS)', 'dnb'),
    '(NBEMS) GENERAL MEDICINE (DMED)': ('DNB - General Medicine (Post-MBBS)', 'dnb'),
    '(NBEMS) GENERAL SURGERY (DSUR)': ('DNB - General Surgery (Post-MBBS)', 'dnb'),
    '(NBEMS) MICROBIOLOGY (DMIC)': ('DNB - Microbiology (Post-MBBS)', 'dnb'),
    '(NBEMS) OBSTETRICS AND GYNAECOLOGY (DOBG)': ('DNB - Obstetrics and Gynaecology (Post-MBBS)', 'dnb'),
    '(NBEMS) OPHTHALMOLOGY (DOPH)': ('DNB - Ophthalmology (Post-MBBS)', 'dnb'),
    '(NBEMS) ORTHOPAEDICS (NDORT)': ('DNB - Orthopaedics (Post-MBBS)', 'dnb'),    # printed "(NBEMS)"; code looks like a diploma's
    '(NBEMS) PAEDIATRICS (DPED)': ('DNB - Paediatrics (Post-MBBS)', 'dnb'),
    '(NBEMS) CARDIO VASCULAR AND THORACIC SURGERY (DIRECT 6 YEARS COURSE) (DCTVS)':
        ('DNB - Cardio Vascular And Thoracic Surgery (Direct 6 Years Course)', 'dnb'),
    '(NBEMS) PAEDIATRIC SURGERY (DIRECT 6 YEARS COURSE) (DPEDS)': ('DNB - Paediatric Surgery (Direct 6 Years Course)', 'dnb')}
QUOTAS = {'Open Seat Quota': 'State Quota', 'In Service Quota': 'In-service Quota',
          'Private Management Quota': 'Management Quota', 'NRI Quota': 'NRI Quota',
          'In Service DNB Quota': None}      # → DNB Quota (In-service) / Diploma Quota (In-service), by program
TYPES = {'State Government': 'Government Institute', 'Central Government': 'Government Institute',
         'Private University/Institute': 'Private Institute'}
HEAD = ['SNo', 'Institute Name', 'Institute Type', 'Program Name', 'Stream', 'Quota', 'UR', 'UR PwD', 'EWS', 'EWS PwD',
        'OBC', 'OBC PwD', 'SC', 'SC PwD', 'ST', 'ST PwD', 'Total Seats']
CATS = ['UR', 'UR-PwD', 'EWS', 'EWS-PwD', 'OBC', 'OBC-PwD', 'SC', 'SC-PwD', 'ST', 'ST-PwD']
TOP = 'West Bengal Medical Counselling Committee West Bengal PG Medical Counselling 2026 Round No: 1 Seat Matrix'
COLS = [12, 60.3, 108.7, 157.1, 205.4, 253.8, 302.1, 350.5, 398.8, 447.2, 495.5, 543.9, 592.2, 640.6, 688.9, 737.3, 785.7]
#        left edge of each column on the turned page (headings, text and numbers all start there — checked per page)
BODY = (88, 560)    # table lines lie between the column headings and the "Printed On … Page No." footer

for m in (COLLEGES, NEW_COLLEGES, PROGRAMS):
    if len({nows(k) for k in m}) != len(m):
        raise SystemExit('two mapping keys are the same without spaces')
NAMES = {nows(k): v for k, v in list(COLLEGES.items()) + list(NEW_COLLEGES.items())}
PROGS = {nows(k): v for k, v in PROGRAMS.items()}


def page_lines(page):
    """One page → list of table lines, each {col index: cell text} (cell words in reading order)."""
    if page.rotation != 90:
        raise SystemExit(f'p{page.number + 1}: page rotation {page.rotation}, expected 90')
    rot = page.rotation_matrix
    ws = []
    for w in page.get_text('words'):
        r = fitz.Rect(w[:4]) * rot
        ws.append((round(r.y0, 1), r.x0, w[4]))
    ws.sort()
    top = ' '.join(t for y, x, t in sorted(ws, key=lambda w: (w[0], w[1])) if y < 70)
    bottom = ' '.join(t for y, x, t in ws if y >= BODY[1])
    if top != TOP:
        raise SystemExit(f'p{page.number + 1}: page heading changed: {top!r}')
    m = re.fullmatch(r'Printed On \d\d/\d\d/\d{4} \d\d:\d\d Page No\. (\d+)', bottom)
    if not m or int(m.group(1)) != page.number + 1:
        raise SystemExit(f'p{page.number + 1}: footer changed: {bottom!r}')
    starts = COLS
    col = lambda x: max([i for i, s in enumerate(starts) if x >= s - 1.5] or [-1])
    labels = collections.defaultdict(list)
    for y, x, t in (w for w in ws if 70 <= w[0] < BODY[0]):   # heading words, each column's first word at its start
        labels[col(x)].append((y, x, t))
    names = [' '.join(t for y, x, t in sorted(labels[i])) for i in range(len(HEAD))]
    if names != HEAD or set(labels) != set(range(len(HEAD))) or \
            any(abs(min(x for y, x, t in labels[i]) - starts[i]) > 0.5 for i in range(len(HEAD))):
        raise SystemExit(f'p{page.number + 1}: column headings changed: {names}')
    body = [w for w in ws if BODY[0] <= w[0] < BODY[1]]
    if any(col(x) < 0 for y, x, t in body):
        raise SystemExit(f'p{page.number + 1}: a word left of the SNo column')
    anchors = [w for w in body if col(w[1]) == 0]
    if not anchors or anchors[0] != min(body):
        raise SystemExit(f'p{page.number + 1}: the first table word is not an SNo')
    lines = []
    for i, a in enumerate(anchors):
        nxt = anchors[i + 1][0] if i + 1 < len(anchors) else BODY[1]
        cells = collections.defaultdict(list)
        for y, x, t in body:
            if a[0] <= y < nxt:
                c = col(x)
                if c >= 6 and abs(x - starts[c]) > 1.5:
                    raise SystemExit(f'p{page.number + 1} SNo {a[2]}: number {t!r} not aligned to a column')
                cells[c].append((y, x, t))
        lines.append({c: ' '.join(t for y, x, t in sorted(v)) for c, v in cells.items()})
    return lines


doc = fitz.open(MATRIX)
if len(doc) != 121:
    raise SystemExit(f'{len(doc)} pages, expected 121 (re-issued file? check it and update the expectations)')
rows, checks, printed_total, sno = [], {}, 0, 0
seen = set()
for page in doc:
    for ln in page_lines(page):
        s = ln.get(0, '')
        if not s.isdigit() or int(s) != sno + 1:
            raise SystemExit(f'p{page.number + 1}: SNo {s!r} after {sno} (sequence broken)')
        sno = int(s)
        where = f'p{page.number + 1} SNo {sno}'
        inst, itype, prog, stream, quota = (clean(ln.get(c, '')) for c in range(1, 6))
        if nows(inst) not in NAMES:
            raise SystemExit(f'{where}: unknown institute {inst!r}')
        if nows(prog) not in PROGS:
            raise SystemExit(f'{where}: unknown program {prog!r}')
        itype = next((t for t in TYPES if nows(t) == nows(itype)), itype)   # wraps mid-word too
        if itype not in TYPES:
            raise SystemExit(f'{where}: unknown institute type {itype!r}')
        if nows(stream) != 'PGMEDICAL':
            raise SystemExit(f'{where}: unknown stream {stream!r}')
        quota = next((t for t in QUOTAS if nows(t) == nows(quota)), quota)
        if quota not in QUOTAS:
            raise SystemExit(f'{where}: unknown quota {quota!r}')
        vals = []
        for c in range(6, 17):
            v = ln.get(c, '')
            if v and not v.isdigit():
                raise SystemExit(f'{where}: column {HEAD[c]} is not one whole number: {v!r}')
            vals.append(int(v) if v else 0)
        cats, total = vals[:10], vals[10]
        if total < 1 or sum(cats) != total:
            raise SystemExit(f'{where}: categories {cats} add to {sum(cats)}, Total Seats {total}')
        course, section = PROGS[nows(prog)]
        nbems = nows(prog).startswith('(NBEMS')
        if (quota == 'In Service DNB Quota') != nbems:
            raise SystemExit(f'{where}: quota {quota!r} with program {prog!r}')
        q = QUOTAS[quota] or ('DNB Quota (In-service)' if section == 'dnb' else 'Diploma Quota (In-service)')
        if q in ('Management Quota', 'NRI Quota') and cats[0] != total:
            raise SystemExit(f'{where}: {q} seats outside UR')
        college = NAMES[nows(inst)]
        k = (college, course, q)
        if k in seen:
            raise SystemExit(f'{where}: {k} printed twice')
        seen.add(k)
        printed_total += total
        for cat, n in zip(CATS, cats):
            if n:
                rows.append({'college': college, 'course': course, 'quota': q, 'seats': n, 'section': section,
                             'category': cat, 'pdf_type': TYPES[itype]})
checks['SNo 1…N continuous (lines parsed, last SNo)'] = (len(seen), sno)
checks['lines whose categories add to their Total Seats'] = (len(seen), sno)
checks['seat rows re-added = sum of the Total Seats column'] = (sum(x['seats'] for x in rows), printed_total)
checks['pages read (Page No. 1…N each checked)'] = (len(doc), 121)
used = {x['college'] for x in rows}
unused = sorted(set(NAMES.values()) - used)
if unused:
    raise SystemExit(f'mapping table has institutes the PDF no longer lists: {unused}')

cuts = load_cuts(CUTS, 'West Bengal')
known = {c['institute'] for c in cuts}
missing = sorted(set(COLLEGES.values()) - known)
if missing:
    raise SystemExit(f'college map points at names not in the 2025 WB cut-offs: {missing}')
clash = sorted(set(NEW_COLLEGES.values()) & known)
if clash:
    raise SystemExit(f'NEW_COLLEGES names that are in the 2025 cut-offs (move them to COLLEGES): {clash}')
for x in rows:
    if x['college'] not in known:
        x['institute_type'] = x['pdf_type']

FAMILY = {'State Quota': ('State Quota$',), 'In-service Quota': ('State Quota-Inservice$',),
          'Management Quota': ('Management Quota$',), 'NRI Quota': ('NRI Quota$',),
          'DNB Quota (In-service)': ('DNB',), 'Diploma Quota (In-service)': ('Diploma Quota',)}


def cat_match(x):
    if x['quota'] == 'Management Quota':
        return ('MQ',)
    if x['quota'] == 'NRI Quota':
        return ('UR', 'NRI')
    base = x['category'].split('-')[0]
    same = ('OBC', 'OBC-A', 'OBC-B') if base == 'OBC' else (base,)
    return (base + '-PH',) + same if x['category'].endswith('-PwD') else same


out = build(rows, cuts, 'West Bengal', 'WB', lambda q: FAMILY[q], cat_match)
codes = collections.defaultdict(set)
for r in out:
    codes[r['college_code']].add(r['college_name'])
if any(len(v) > 1 for v in codes.values()):
    raise SystemExit(f'two colleges share a college code: {[v for v in codes.values() if len(v) > 1]}')
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
print('lines', sno, '| institutes', len(used), f'({len(used & known)} in 2025, {len(used - known)} new)')
