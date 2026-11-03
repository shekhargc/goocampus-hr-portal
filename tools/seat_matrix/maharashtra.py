"""Maharashtra NEET PG 2026 provisional seat matrix (State CET Cell, dated 02/11/2026) → standardised seat rows,
bridged to Maharashtra's 2025 cut-offs. Three PDFs, merged into one body "Maharashtra — State Counselling",
authority `cetcell_mh`:
  govt     "PROVISIONAL SEAT MATRIX OF POSTGRADUATE MD/MS COURSES IN GOVT/CORPORATION/CENT.GOVT/GOVT. AIDED COLLEGES"
           page 1 = summary of all colleges, then one page per college: per subject State Seats, then SC / ST /
           VJ(DT-A) / NT-B / NT-C / NT-D / OBC / SEBC / EWS / OPEN each split GEN / INS / GEN PWD / INS PWD,
           ORPHAN (A-B, C) on the summary page only — a horizontal share already counted inside the category
           columns (Anaesthesiology: 171 categorised + 2 orphan, State Seats 171), so it is not a seat column — Total.
  private  "PROVISIONAL SEAT MATRIX OF POSTGRADUATE MD/MS COURSES IN PRIVATE/MINORITY COLLEGES": page 1 summary, one
           page per college: Total Seats, Inst., Avail. Seats, SC … OBC, Tot. Res., SEBC, OPEN, MGT, NRI, Total.
           The minority college (JIIU Jalna) prints Total Seats, Inst, Avail. Seats, Minority, MGT, NRI, Total.
  diploma  "PROVISIONAL SEAT MATRIX OF PG DIPLOMA COURSES IN GOVT/CORPORATION COLLEGES": one page (LTMC Mumbai),
           STATE QUOTA, categories split GN / INS, Tot. Res., Total.
Blank cells are zero. Some college pages print a category Total cell that differs from the sum of its subject lines
(e.g. Grant MC: OBC-GEN lines 17, Total 15) while every subject line and the page's State Seats / Total agree; the
subject lines are used and every such cell is listed in printed_total_cells_off. Hard checks: every subject line's category cells add to its State / Avail. seats and every page's
cells to its Total line (column by column); private Inst. = MGT + NRI, Total = Inst. + Avail.; the govt and private
summary pages = the sum of the college pages' subject lines, column by column (the private summary leaves out
JIIU Jalna and the two AIQ colleges). Stops on any unknown college / subject / heading.

Quotas (stored → 2025 cut-off quota it bridges to, exact): State Quota → 'State Quota'; In-service Quota (INS) →
'State Quota-Inservice'; Institutional Quota (private MGT) → 'Institutional Quota'; NRI Quota → 'NRI Quota';
Minority Quota (JIIU) → 'State Quota-Minority'; All India Quota (Vikhe Patil + NKP Salve print AIQ where the others
print MGT — those seats are filled through the All India counselling; no 2025 Maharashtra cut-off → new).
Orphan seats: a college-page cell "1 ORP AB" is 1 orphan seat, "1 + 1 ORP C" 1 seat + 1 orphan seat; orphan seats are
stored as category "<category>-Orphan" (2025: 'OBC-Orphan', 'Orphan'); their count must equal the summary's ORPHAN
A-B and C columns. Categories stored as printed (SC, ST, VJ, NT-B, NT-C, NT-D, OBC, SEBC,
EWS, OPEN; PwD seats "-PwD"); 2025 writes VJ / NT1 / NT2 / NT3, in-service "IS-" + category, PwD "-PH",
MGT 'IQ', NRI 'NRI', minority 'Minority' — cat_match bridges those spellings, else the 2025 OPEN rank.
Run with /usr/bin/python3 (PyMuPDF):
  maharashtra.py <govt.pdf> <private.pdf> <diploma.pdf> <cutoffs2025.json> <out.json>"""
import sys, os, re, json, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

if len(sys.argv) != 6:
    raise SystemExit(__doc__)
GOVT, PRIV, DIPL, CUTS, OUT = sys.argv[1:]

COLLEGES = {  # printed (upper-cased) → 2025 cut-off name
    'GRANT GOVERNMENT MEDICAL COLLEGE, MUMBAI': 'Grant Medical College, Mumbai',
    'SETH G.S. MEDICAL COLLEGE, MUMBAI': 'Seth GS Medical College and KEM Hospital, Mumbai',
    'LOKMANYA TILAK MEDICAL COLLEGE, MUMBAI': 'Lokmanya Tilak Municipal Medical College, Sion, Mumbai',
    'T.N. MUNICIPAL MEDICAL COLLEGE, MUMBAI': 'Topiwala National Medical College, Mumbai',
    'B.J. MEDICAL COLLEGE, PUNE': 'B.J. Government Medical College, Pune',
    'V.M. GOVERNMENT MEDICAL COLLEGE, SOLAPUR': 'Dr. Vaishampayan Memorial Government Medical College, Solapur',
    'GOVERNMENT MEDICAL COLLEGE, MIRAJ': 'Government Medical College, Miraj',
    'GOVT. MEDICAL COLLEGE, NAGPUR': 'Government Medical College, Nagpur',
    'INDIRA GANDHI MEDICAL COLLEGE, NAGPUR': 'Indira Gandhi Government Medical College & Hospital, Nagpur',
    'V.N. GOVERNMENT MEDICAL COLLEGE, YEWATMAL': 'Shri Vasant Rao Naik Government Medical College, Yavatmal',
    'GOVERNMENT MEDICAL COLLEGE, AKOLA': 'Government Medical College, Akola',
    'GOVERNMENT MEDICAL COLLEGE, AURANGABAD': 'Government Medical College, Aurangabad (Sambhajinagar)',
    'GOVERNMENT MEDICAL COLLEGE, NANDED': 'Dr. Shankarrao Chavan Government Medical College, Nanded',
    'SRTR MEDICAL COLLEGE, AMBAJOGAI': 'SRTR Government Medical College, Ambajogai',
    'VILASRAO DESHMUKH GOVT. MEDICAL COLLEGE, LATUR': 'Government Medical College, Latur',
    'HBT & DR. R. N. COOPER MEDICAL COLLEGE, ANDHERI, MUMBAI':
        'H.B.T Medical College & Dr. R.N. Cooper Municipal General Hospital, Juhu, Mumbai',
    'SHREE BHAUSAHEB HIRE GOVERNMENT MEDICAL COLLEGE, DHULE': 'Sri Bhausaheb Hire Government Medical College, Dhule',
    'MAHATMA GANDHI INSTITUTE OF MEDICAL SCIENCES, WARDHA': 'Mahatma Gandhi Institute of Medical Sciences, Sevagram, Wardha',
    'TATA MEMORIAL HOSPITAL, MUMBAI': 'Tata Memorial Centre, Mumbai',
    'ALL INDIA INSTITUTE OF PHYSICAL MEDICINE & REHABILIATION, MUMBAI':
        'All India Institute of Physical Medicine and Rehabilitation, Mumbai',
    'BHABHA AUTOMIC RESEARCH CENTRE, MUMBAI': 'Bhabha Atomic Research Centre, Anushakti Nagar, Mumbai, Maharashtra',
    'PIMPRI CHINCHWAD MUNCIPAL CORPORATIONS, HAVELI, PUNE': 'Pimpri Chinchwad Municipal Corporation Post Graduate Institute, Pune',
    'RAJIV GANDHI MC, KALVA, THANE': 'Rajiv Gandhi Medical College, Thane',
    'RCSM GOVT. MEDICAL COLLEGE, KOLHAPUR': 'Rajashree Chatrapati Shahu Maharaj Government Medical College, Kolhapur',
    'GONDIA GOVT. MEDICAL COLLEGE, GONDIA': 'Government Medical College, Gondia',
    'CHANDRAPUR GOVT. MEDICAL COLLEGE, CHANDRAPUR': 'Government Medical College and Hospital, Chandrapur',
    'GOVT. MEDICAL COLLEGE, JALGAON': 'Government Medical College, Jalgaon',
    'GOVERNMENT MEDICAL COLLEGE, BARAMATI': 'Government Medical College, Baramati',
    'GOVERNMENT MEDICAL COLLEGE NANDURBAR': 'Government Medical College, Nandurbar',
    'MAHARASHTRA POST GRADUATE INSTITUTE OF MEDICAL EDUCATION & RESEARCH, NASHIK':
        'Maharashtra Post Graduate Institute of Medical Education and Research, Nashik',
    'POST GRADUATE INSTITUTE OF MEDICAL SCIENCES, (P.G.I.M.S), NERUL, NAVI MUMBAI':
        'Post Graduate Institute of Medical Sciences, (PGIMS) Navi Mumbai',
    # private / minority
    'BOMBAY HOSPITAL INSTITUTE OF MEDICAL SCIENCES, MUMBAI': 'Bombay Hospital Institute of Medical Sciences, Mumbai',
    'K.J.SOMAIYA MEDICAL COLLEGE & RESEARCH CENTRE, MUMBAI': 'KJ Somaiyya Medical College & Research Centre, Mumbai',
    'TERNA MEDICAL COLLEGE & RESEARCH CENTRE, MUMBAI': 'Terna Medical College, Navi Mumbai',
    'SANCHETI INSTUTUTE FOR ORTHOPAEDICS & REHABILITATION POST GRADUATE COLLEGE, PUNE':
        'Sancheti Institute for Orthpaedics and Rehabilitation College of Physiotherapy, Pune',
    'SMT. KASHIBAI NAVALE MEDICAL COLLEGE & GENERAL HOSPITAL, PUNE': 'Smt. Kashibai Navale Medical College and General Hospital, Pune',
    'MIMER, TALEGAON, PUNE': 'Maharashtra Institute of Medical Education & Research, Talegaon, Pune',
    'DR.VASANTRAO PAWAR MEDICAL COLLEGE HOSPITAL & RESEARCH CENTRE, NASHIK':
        'Dr. Vasantrao Pawar Med. Col. Hosp. & Research Centre, Nasik (Prev. NDMVP Samaj Medical College)',
    'SANJEEVAN MEDICAL FOUNDATION E.N.T.POSTGRADUATE TRAINING INSTITUTE, MIRAJ':
        'Sanjeevan Medical Foundation ENT Post Graduate Training Institute, Miraj',
    'POSTGRADUATE INSTITUTE OF SWASTHIYOG PRATISHTHAN, MIRAJ': 'Postgraduate Institute of Swasthiyog Pratishthan, Miraj',
    'MAHARASHTRA INSTITUTE OF MEDICAL SCIENCES & RESEARCH, LATUR': 'Maharashtra Institute of Medical Sciences & Research, Latur',
    'ANNASAHEB CHUDAMAN PATIL MEMORIAL MEDICAL COLLEGE, DHULE': 'ACPM Medical College, Dhule',
    'DR. PANJABRAO ALIAS MEDICAL COLLEGE, AMRAVATI': 'Dr. Panjabrao Alias Bhausaheb Deshmukh Memorial Medical College, Amravati',
    'DR. ULHAS PATIL MEDICAL COLLEGE, JALGAON': 'Dr. Ulhas Patil Medical College & Hospital, Jalgaon',
    'ASHWINI MEDICAL COLLEGE HOSPITAL, SOLAPUR': 'Ashwini Rural Medical College, Hospital & Research Centre, Solapur',
    'SMBT MEDICAL COLLEGE, NASHIK': 'SMBT Institute of Medical Sciences & Research Centre, Nandihills, Nashik',
    'BKL WALWALKAR MEDICAL COLLEGE, SAWARDE': 'B.K.L. Walawalkar Rural Medical College, Ratnagiri',
    'VEDANTA MC, PALGHAR': 'Vedantaa Institute of Medical Sciences, Palghar',
    'PRAKASH INSTITUTE OF MC, ISLAMPUR SANGLI': 'Prakash Institute of Medical Sciences & Research, Sangli',
    'N.S. TASGAONKAR MC, KARJAT': 'Dr. N. Y. Tasgaonkar Institute of Medical Science, Karjat',
    'RAJENDRA GODE MC AMRAVATI': 'Dr. Rajendra Gode Medical College, Amravati',
    "JIIU'S INDIAN INSTITUTE OF MEDICAL SCIENCE, JALNA": 'Indian Institute of Medical Science & Research, Jalna',
    "DR. VITTHALRAO VIKHE PATIL FOUNDATION'S MEDICAL COLLEGE, AHMEDNAGAR":
        'Dr. Vithalrao Vikhe Patil Foundations Medical College & Hospital, Ahmednagar',
    'NKP SALVE MEDICAL COLLEGE, NAGPUR':
        'N. K. P. Salve Instt. of Medical Sciences and Research Centre and Lata Mangeshkar Hospital, Nagpur'}
DERM = 'MD Dermatology, Venerology & Leprosy / MD Dermatology/MD Skin & Venereal Diseases /MD Venereology'
SUBJECTS = {  # printed subject → (approved course name, section); a subject missing here may only carry 0 seats
    'MD Anesthesiology.': 'MD - Anaesthesiology', 'MS Anatomy': 'MD/MS - Anatomy', 'MD Biochemistry': 'MD - Biochemistry',
    'MD Dermatology': 'MD - Dermatology', DERM: 'MD - Dermatology',
    'MS E.N.T. (Ear, Nose, & Throat)': 'MS - ENT (Otorhinolaryngology)',
    'MD (Emergency & Critical Care)': 'MD - Emergency Medicine', 'MD Forensic Medicine': 'MD - Forensic Medicine',
    'MD General Medicine': 'MD - General Medicine', 'MS General Surgery': 'MS - General Surgery',
    'MD (Geriatric)': 'MD - Geriatrics', 'MD Microbiology': 'MD - Microbiology',
    'MD Nuclear Medicine': 'MD - Nuclear Medicine', 'Nuclear Medicine': 'MD - Nuclear Medicine',
    'MD Obstetrics & Gynecology': 'MS - Obstetrics and Gynaecology', 'MS Ophthalmology': 'MS - Ophthalmology',
    'MS Orthopedics': 'MS - Orthopaedics', 'MD Paediatrics': 'MD - Paediatrics', 'MD Pathology': 'MD - Pathology',
    'MD Pharmacalogy': 'MD - Pharmacology', 'MD Physical Medicine & Rehabilitation': 'MD - Physical Medicine and Rehabilitation',
    'MD Physiology': 'MD - Physiology',
    'MD Preventive & Social Medicine / Community Medicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'MD Preventive & Social Med / Community Med': 'MD - Social & Preventive Medicine / Community Medicine',
    'MD Psychiatry': 'MD - Psychiatry', 'MD Radio Diagnosis': 'MD - Radio-Diagnosis',
    'MD Radio Therapy': 'MD - Radiotherapy / Radiation Oncology', 'MD TB & Respiratory Disease': 'MD - Respiratory Medicine',
    'MD Transfusion Medicine': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'MD IN Transfusion Medicine': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'MD Tropical Medicine': 'MD - Tropical Medicine', 'MD Palliative Medicine': 'MD - Palliative Medicine',
    # diplomas
    'Dip. Anesthesiology': 'Diploma in Anaesthesiology', 'Dip. Bacteriology': 'Diploma in Bacteriology',
    'Dip. Child Health': 'Diploma in Child Health / Paediatrics', 'Dip. Clinical Pathology': 'Diploma in Pathology',
    'Dip. Community Medicine/Dip. Public Health': 'Diploma in Public Health', 'Dip. Dermatology': 'Diploma in Dermatology',
    'Dip. Diabetology': 'Diploma in Diabetology', 'Dip. Forensic Medicine': 'Diploma in Forensic Medicine',
    'Dip. Health Administration': 'Diploma in Health Administration',
    'Dip. Hospital Administration': 'Diploma in Hospital Administration',
    'Dip. Immunology & Blood transfusion': 'Diploma in Immuno-Haematology and Blood Transfusion',
    'Dip. Hematology & Blood transfusion': 'Diploma in Immuno-Haematology and Blood Transfusion',
    'Dip. Medical radio-diagnosis': 'Diploma in Radio Diagnosis', 'Dip. Obstetrics & Gynecology': 'Diploma in Obstetrics and Gynaecology',
    'Dip. Ophthalmology': 'Diploma in Ophthalmology', 'Dip. Orthopedics': 'Diploma in Orthopaedics',
    'Dip. Otorhinolaryngology': 'Diploma in ENT', 'Dip. Physical Med. & Rehabilitation': 'Diploma in Physical Medicine and Rehabilitation',
    'Dip. Psychological Medicine': 'Diploma in Psychological Medicine', 'Dip. Radiation Medicine': 'Diploma in Radiation Medicine',
    'Dip. Medical Radiotherapy': 'Diploma in Radiotherapy / Radiation Oncology', 'Dip. Sports Medicine': 'Diploma in Sports Medicine',
    'Dip. TB & Chest Diseases': 'Diploma in Respiratory Medicine'}
CATS = {'SC': 'SC', 'ST': 'ST', 'VJ(DT-A)': 'VJ', 'VJ DT-A': 'VJ', 'VJ DT- A': 'VJ', 'VJ-DT-A': 'VJ', 'NT-B': 'NT-B', 'NT-C': 'NT-C',
        'NT-D': 'NT-D', 'OBC': 'OBC', 'SEBC': 'SEBC', 'EWS': 'EWS', 'OPEN': 'OPEN'}
SUB = {'GEN': ('State Quota', ''), 'GN': ('State Quota', ''), 'INS': ('In-service Quota', ''),
       'GEN PWD': ('State Quota', '-PwD'), 'INS PWD': ('In-service Quota', '-PwD')}
AGG = {'State Seats', 'STATE QUOTA', 'Total Seats', 'Inst', 'Inst.', 'Avail. Seats', 'Tot. Res.', 'Total', 'TOTAL'}
TITLES = {GOVT: 'PROVISIONAL SEAT MATRIX OF POSTGRADUATE MD/MS COURSES IN GOVT/CORPORATION/CENT.GOVT/GOVT. AIDED COLLEGES',
          PRIV: 'PROVISIONAL SEAT MATRIX OF POSTGRADUATE MD/MS COURSES IN PRIVATE/MINORITY COLLEGES',
          DIPL: 'PROVISIONAL SEAT MATRIX OF PG DIPLOMA COURSES IN GOVT/CORPORATION COLLEGES'}
TYPES = {GOVT: 'Government Institute', PRIV: 'Private Institute', DIPL: 'Government Institute'}


ORP = re.compile(r'^(?:(\d+)\s*\+\s*)?(\d+)\s*ORP\s*(AB|C)$')


def cell(s):
    """(seats, orphan seats) of one cell: '3', '' = 0, '1 ORP AB' = 1 orphan seat, '1 + 1 ORP C' = 1 + 1 orphan."""
    s = clean(s)
    if s == '':
        return 0, 0
    if s.isdigit():
        return int(s), 0
    m = ORP.match(s)
    if not m:
        raise SystemExit(f'not a number: {s!r}')
    return int(m.group(1) or 0) + int(m.group(2)), int(m.group(2))


n = lambda s: cell(s)[0]


def labels(h1, h2):
    """column index → (group, sub) from the two heading lines (a group heading spans its sub-columns)."""
    out, grp = {}, None
    for i in range(2, len(h1)):
        if h1[i]:
            grp = clean(h1[i])
        sub = clean(h2[i]) if i < len(h2) and h2[i] else ''
        out[i] = (grp, sub)
    return out


def cell_key(lab):
    """(group, sub) → (quota, category) of one seat column, or None for an aggregate column."""
    grp, sub = lab
    if grp in AGG and not sub:
        return None
    if grp == 'ORPHAN' and sub in ('A-B', 'C'):          # summary page only: orphan seats are a horizontal
        return None                                      # share already inside the category columns
    if grp in CATS and sub in SUB:
        q, pwd = SUB[sub]
        return (q, CATS[grp] + pwd)
    if grp in CATS and not sub:                          # private: one column per category = State Quota
        return ('State Quota', CATS[grp])
    if grp == 'MGT' and not sub:
        return ('Institutional Quota', '')
    if grp == 'AIQ' and not sub:                         # Vikhe Patil, NKP Salve: the institute share is AIQ
        return ('All India Quota', '')
    if grp == 'NRI' and not sub:
        return ('NRI Quota', '')
    if grp == 'Minority' and not sub:
        return ('Minority Quota', '')
    raise SystemExit(f'unknown column heading {lab}')


# the private summary page covers 20 colleges: not the minority college (JIIU) nor the two AIQ colleges
NOT_IN_SUMMARY = {'Indian Institute of Medical Science & Research, Jalna',
                  'Dr. Vithalrao Vikhe Patil Foundations Medical College & Hospital, Ahmednagar',
                  'N. K. P. Salve Instt. of Medical Sciences and Research Centre and Lata Mangeshkar Hospital, Nagpur'}


def norm(k):
    g = {'Inst.': 'Inst', 'TOTAL': 'Total', 'VJ DT- A': 'VJ DT-A', 'AIQ': 'MGT'}.get(k[0], k[0])
    return (g, k[1])


rows, checks = [], {}
checks_orphan = collections.Counter()
printed_off = []   # (pdf, page, college, column, subject lines add to, printed Total line)
page_totals = {GOVT: collections.Counter(), PRIV: collections.Counter()}
summaries = {}
for path in (GOVT, PRIV, DIPL):
    doc = fitz.open(path)
    text0 = clean(doc[0].get_text())
    if TITLES[path] not in text0 and path != PRIV:
        raise SystemExit(f'{os.path.basename(path)}: title changed')
    for pg in doc:
        for t in grids(pg):
            head = clean(t[0][0] or '')
            # find the subject heading line
            hi = next(i for i, r in enumerate(t) if clean(r[0] or '') in ('No.', 'No'))
            h1, h2 = t[hi], t[hi + 1]
            two = not clean(h2[0] or '') and not clean(h2[1] or '') and any(clean(c or '') for c in h2[2:])
            labs = labels(h1, h2 if two else [None] * len(h1))
            body = t[hi + (2 if two else 1):]
            summary = pg.number == 0 and path != DIPL
            college = None
            if not summary:
                college = COLLEGES.get(head.upper())
                if not college:
                    raise SystemExit(f'{os.path.basename(path)} p{pg.number + 1}: unknown college {head!r}')
            col_sum = collections.Counter()
            total_line = None
            for r in body:
                c0 = clean(r[0] or '')
                if c0.startswith('Total'):
                    total_line = r; continue
                if not c0.isdigit():
                    raise SystemExit(f'p{pg.number + 1}: unexpected line {r[:3]}')
                subj = clean(r[1])
                cells = {i: n(r[i]) for i in labs if i < len(r)}
                for i, v in cells.items():
                    col_sum[labs[i]] += v
                seat = {i: v for i, v in cells.items() if cell_key(labs[i]) and v}
                agg = {labs[i][0]: v for i, v in cells.items() if not cell_key(labs[i])}
                total = agg.get('Total', agg.get('TOTAL', 0))
                if path == PRIV:
                    inst = agg.get('Inst', agg.get('Inst.', 0))
                    mgt_nri = sum(v for i, v in cells.items() if cell_key(labs[i]) and cell_key(labs[i])[0] in ('Institutional Quota', 'All India Quota', 'NRI Quota'))
                    state = sum(v for i, v in cells.items() if cell_key(labs[i]) and cell_key(labs[i])[0] in ('State Quota', 'Minority Quota'))
                    if inst != mgt_nri or agg.get('Avail. Seats', 0) != state or total != inst + state:
                        raise SystemExit(f'p{pg.number + 1} {subj}: Inst {inst} ≠ MGT+NRI {mgt_nri} or Avail '
                                         f'{agg.get("Avail. Seats")} ≠ {state} or Total {total}')
                else:
                    st = agg.get('State Seats', agg.get('STATE QUOTA', 0))
                    if sum(seat.values()) != st or total != st:
                        raise SystemExit(f'p{pg.number + 1} {subj}: categories add to {sum(seat.values())}, State Seats {st}, Total {total}')
                if summary or not seat:
                    continue
                if subj not in SUBJECTS:
                    raise SystemExit(f'p{pg.number + 1}: subject {subj!r} has seats but no course name')
                course = SUBJECTS[subj]
                section = 'diploma' if course.startswith('Diploma') else 'mdms'
                merged = collections.Counter()
                for i, v in seat.items():
                    q, cat = cell_key(labs[i])
                    orp = cell(r[i])[1]
                    if orp:
                        merged[(q, cat + '-Orphan')] += orp
                        checks_orphan[ORP.match(clean(r[i])).group(3)] += orp
                    if v - orp:
                        merged[(q, cat)] += v - orp
                for (q, cat), v in merged.items():
                    rows.append({'college': college, 'course': course, 'quota': q, 'category': cat, 'seats': v,
                                 'section': section, 'institute_type': TYPES[path]})
            if total_line is None:
                raise SystemExit(f'p{pg.number + 1}: no Total line')
            tl = {labs[i]: n(total_line[i]) for i in labs if i < len(total_line)}
            bad = {k: (col_sum[k], v) for k, v in tl.items() if col_sum[k] != v}
            hard = {k: v for k, v in bad.items() if k[0] in AGG and not k[1]}
            if hard:
                raise SystemExit(f'{os.path.basename(path)} p{pg.number + 1}: seat totals ≠ Total line {hard}')
            for k, v in bad.items():      # the PDF's own category total cell is off; the subject lines add up
                printed_off.append((os.path.basename(path), pg.number + 1, head[:40], ' '.join(k).strip(), *v))
            if summary:
                summaries[path] = tl
            elif path in page_totals and college not in NOT_IN_SUMMARY:
                for k, v in col_sum.items():                  # the subject lines (the printed Total cells can be off)
                    page_totals[path][norm(k)] += v
            checks[f'{os.path.basename(path)} p{pg.number + 1} {college or "summary"} | Total'] = (
                sum(x['seats'] for x in rows if x['college'] == college and TYPES[path] == x['institute_type']
                    and (x['section'] == 'diploma') == (path == DIPL)) if college else tl.get(('Total', '')) or tl.get(('TOTAL', '')),
                tl.get(('Total', ''), tl.get(('TOTAL', ''))))
# orphan seats (marked "ORP AB" / "ORP C" in the college pages) = the summary page's ORPHAN A-B / C columns
for kind, lab in (('AB', 'A-B'), ('C', 'C')):
    checks[f'orphan seats ORP {kind} (summary ORPHAN {lab})'] = (checks_orphan[kind], summaries[GOVT].get(('ORPHAN', lab), 0))
# summary pages = sum of the college pages (labels that exist on both)
for path, sm in summaries.items():
    for k, v in sm.items():
        if norm(k) in page_totals[path] or k[0] in ('Total', 'TOTAL'):
            checks[f'{os.path.basename(path)} summary {k[0]} {k[1]}'.strip()] = (page_totals[path].get(norm(k), 0), v)
        elif v and k[0] != 'ORPHAN':                     # ORPHAN: checked against the ORP marks above
            checks[f'{os.path.basename(path)} summary {k[0]} {k[1]} (not on college pages)'] = (0, v)

FAMILY = {'State Quota': ('State Quota$',), 'In-service Quota': ('State Quota-Inservice$',),
          'Institutional Quota': ('Institutional Quota$',), 'NRI Quota': ('NRI Quota$',),
          'Minority Quota': ('State Quota-Minority$',), 'All India Quota': ('All India Quota$',)}
CAT25 = {'VJ': 'VJ', 'NT-B': 'NT1', 'NT-C': 'NT2', 'NT-D': 'NT3', 'SEBC': 'SEBC'}


def cat_match(x):
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
json.dump({'rows': out, 'checks': checks, 'printed_total_cells_off': printed_off}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('printed category-total cells that differ from their subject lines (lines used):', len(printed_off))
for x in printed_off: print('  ', x)
print('by quota', dict(collections.Counter(r['quota'] for r in out for _ in range(r['seats']))))
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma')})
