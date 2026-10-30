"""Karnataka NEET PG 2026 Round 1 seat matrix (KEA, "PROVISIONAL SEAT MATRIX - 2026 (30/10/2026)") → standardised seat
rows, bridged to Karnataka's 2025 KEA cut-offs. Four PDFs, one body:
  medical  — "PG MEDICAL PROVISIONAL SEAT MATRIX": one block per college code (M01 …) × course code (A1 …), two lines:
             KK (Kalyana Karnataka, the 371(J) region — formerly Hyderabad-Karnataka) and RK (Rest of Karnataka).
             Each line: NON-INSERVICE (CAT1 2A 2B 3A 3B ST SCA SCB SCC SCC(20%) GM), INSERVICE (GM SCA SCB SCC SCC(20%)
             ST CAT1 2A 2B 3A 3B), PWD (same 11) and the HK-RK line total; the RK line also carries the
             PRIVATE, MANAGEMENT, NRI columns (GMP GMPH OPN NRI OTH(Q) MMH MEH MC MM MK MU MA ME) and the course's
             Total Seats (= KK total + RK total + private columns). Last page: GRAND TOTAL KK / RK lines.
  stjohns  — St. John's Medical College (M48) minority seats: RC1 RC2 RC3 + TOTAL SEATS per course, GRAND TOTAL line.
             (M48's government-quota seats are in the medical PDF; the RC seats are only here.)
  dnb_reg  — "DNB REGULAR SEAT MATRIX": in-service seats at government hospitals (Q001 …), KK / RK lines of
             GM SCA SC-B SC-C SCC(20%) ST CAT1 2A 2B 3A 3B + HK-RK + Total Seats; GRAND TOTAL lines.
  dnb_dip  — "DNB DIPLOMA SEAT MATRIX": same layout (V001 …).
Every printed number is checked: each KK / RK line's categories add to its HK-RK total, each course's Total Seats =
KK + RK + private columns (St John's: RC1 + RC2 + RC3 = TOTAL), every column adds to the GRAND TOTAL line, and the
four files' grand totals (4,724 + 94 + 44 + 30 = 4,892). Column headings are checked on every page.
Unknown college / hospital (printed name must match exactly), course or line label → SystemExit.

Quota / category mapping (2025 KEA cut-offs use quotas Government Quota, Private Quota - GMP, Private Quota - Open,
Management Quota, Private Quota - Minority, NRI Quota and KEA's allotment codes: GM / 1G / 2AG / … / SC-AG / STG for RK,
GMH / 1H / 2AH / … for KK, a 'P' prefix for PwD — PGM, P2AG, PGMH):
  NON-INSERVICE cols → quota 'Government Quota' (government AND private colleges' government seats, as 2025);
                       category as printed (CAT1, 2A, 2B, 3A, 3B, ST, SC-A, SC-B, SC-C, SC-C (20%), GM) + ' (KK)' on
                       the KK line. Bridge: 2025 'Government Quota' exactly; same KEA code (2A → 2AG, 2A (KK) → 2AH),
                       then GM / GMH; KK seats then fall back to the RK code.
  PWD cols           → quota 'Government Quota', category '<cat>-PwD' (+ ' (KK)'); bridge P<code> → PGM → non-PwD.
  INSERVICE cols     → quota 'In-service Quota', category as above. 2025 KEA has no in-service rows → never bridged
                       (new_quota_category).
  GMP / GMPH         → 'Private Quota - GMP' (GMPH → GMPH then GMP).    OPN → 'Private Quota - Open' (OPN).
  NRI                → 'NRI Quota' (NRI).                                 OTH(Q) → 'Management Quota' (2025 MNG).
  MMH MEH MC MM MK MU MA ME → 'Private Quota - Minority', category as printed (MMH / MEH fall back to MM / ME).
  St John's RC1 / RC2 / RC3 → 'Private Quota - Minority', category RC1 / RC2 / RC3 (as the 2025 St John's rows).
  DNB REGULAR        → `DNB - <course> (Post-MBBS)`, section dnb, 'DNB Quota (In-service)' (hidden by HIDE_DNB).
  DNB DIPLOMA        → `Diploma in …`, section diploma, 'Diploma Quota (In-service)' (as Gujarat / Rajasthan), EXCEPT
                       General Medicine / General Surgery: no approved 'Diploma in …' name and no NBEMS post-MBBS
                       diploma of that name → `DNB Diploma - <course>` (MCC wording), section dnb (hidden), same quota.
  Medical-college diplomas in the medical PDF (Clinical Pathology, DPH, TB & Chest) → section diploma, quota by column.
Run with /usr/bin/python3 (PyMuPDF):
    karnataka.py <medical.pdf> <stjohns.pdf> <dnb_regular.pdf> <dnb_diploma.pdf> <cutoffs2025.json> <out.json>"""
import re, sys, os, json, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

if len(sys.argv) != 7:
    raise SystemExit(__doc__)
MED, SJ, DNBR, DNBD, CUTS, OUT = sys.argv[1:7]
key = lambda s: re.sub(r'[^a-z]', '', (s or '').lower())
nows = lambda s: re.sub(r'\s+', '', clean(s))

COLLEGES = {  # KEA college code → (name exactly as printed, standard institute name = the 2025 KEA cut-off name)
    'M01': ('Bangalore Medical College and Research Institute, Bangalore', 'Bangalore Medical College and Research Institute, Bangalore'),
    'M02': ('Mysore Medical College and Research Instt. (Prev.name Government Medical College), Mysore', 'Mysore Medical College and Research Institute, Mysore'),
    'M03': ('Karnataka Medical College and Research Institute, Hubballi, Karnataka', 'Karnataka Institute of Medical Sciences, Hubballi'),
    'M04': ('Vijaynagar Institute of Medical Sciences, Bellary', 'Vijayanagar Institute of Medical Sciences, Ballari'),
    'M05': ('Mandya Institute of Medical Sciences, Mandya', 'Mandya Institute of Medical Sciences, Mandya'),
    'M06': ('Belagavi Institute of Medical Sciences, Belagavi', 'Belagavi Institute of Medical Sciences, Belagavi'),
    'M07': ('Hassan Institute of Medical Sciences, Hassan', 'Hassan Institute of Medical Sciences, Hassan'),
    'M08': ('Shimoga Institute of Medical Sciences, Shimoga', 'Shimoga Institute of Medical Sciences, Shimoga'),
    'M09': ('Raichur Institute of Medical Sciences, Raichur', 'Raichur Institute of Medical Sciences, Raichur'),
    'M10': ('Bidar Institute of Medical Sciences, Bidar', 'Bidar Institute of Medical Sciences, Bidar'),
    'M11': ('Kidwai Memorial Institute of Oncology, Bangalore', 'Kidwai Memorial Institute of Oncology, Bangalore'),
    'M12': ('Indira Gandhi Institute of Child Health, Bangalore', 'Indira Gandhi Institute of Child Health, Bangalore'),
    'M13': ('Employees State Insurance Corporation Medical College, Gulbarga', 'Employees State Insurance Corporation Medical College, Gulbarga'),
    'M14': ('JJM Medical College, Davangere', 'JJM Medical College, Davangere'),
    'M15': ('M S Ramaiah Medical College, Bangalore', 'M.S. Ramaiah Medical College, Bangalore'),
    'M16': ('Kempegowda Institute of Medical Sciences, Bangalore', 'Kempegowda Institute of Medical Sciences, Bangalore'),
    'M17': ('Mahadevappa Rampure Medical College, Kalaburagi, Gulbarga', 'Mahadevappa Rampure Medical College, Gulbarga'),
    'M18': ('Adichunchanagiri Institute of Medical Sciences, Bellur', 'Adichunchanagiri Institute of Medical Sciences, Bellur, Mandya'),
    'M19': ('K V G Medical College, Sullia', 'KVG Medical College and Hospital, Sullia'),
    'M20': ('Dr BR Ambedkar Medical College, Bangalore', 'Dr. BR Ambedkar Medical College, Bangalore'),
    'M21': ('S S Institute of Medical Sciences& Research Centre, Davangere', 'S S Institute of Medical Sciences & Research Centre, Davangere'),
    'M22': ('S. Nijalingappa Medical College & HSK Hospital & Research Centre, Bagalkot', 'S. Nijalingappa Medical College & HSK Hospital & Research Centre, Bagalkot'),
    'M23': ('Basaveswara Medical College and Hospital, Chitradurga', 'Basaveswara Medical College and Hospital, Chitradurga'),
    'M24': ('Al-Ameen Medical College, Bijapur', 'Al-Ameen Medical College, Bijapur'),
    'M25': ('Father Mullers Medical College, Mangalore', 'Father Mullers Institue of Medical Education and Research, Mangalore'),
    'M26': ('Vydehi Institute Of Medical Sciences & Research Centre, Bangalore', 'Vydehi Institute of Medical Sciences & Research Centre, Bangalore'),
    'M27': ('SDM College of Medical Sciences & Hospital, Sattur, Dharwad', 'SDM College of Medical Sciences and Hospital, Dharwad'),
    'M28': ('MVJ Medical College and Research Hospital, Bangalore', 'MVJ Medical College and Research Hospital, Bangalore'),
    'M30': ('Navodaya Medical College, Raichur', 'Navodaya Medical College, Raichur'),
    'M31': ('A J Institute of Medical Sciences & Research Centre, Mangalore', 'A.J. Institute of Medical Sciences and Research Centre, Mangalore'),
    'M32': ('Kasturba Medical College, Mangalore', 'Kasturba Medical College, Mangalore'),
    'M33': ('Kasturba Medical College, Manipal', 'Kasturba Medical College, Manipal'),
    'M34': ('Sanjay Gandhi Institute of Trauma and Orthopaedics, Bangalore', 'Sanjay Gandhi Institute of Trauma and Orthopaedics, Bangalore'),
    'M35': ('JSS Medical College, Mysore', 'JSS Medical College, Mysore'),
    'M36': ('K S Hegde Medical Academy, Mangalore', 'K S Hegde Medical Academy, Mangalore'),
    'M37': ('Yenepoya Medical College, Mangalore', 'Yenepoya Medical College, Mangalore'),
    'M38': ('Employees State Insurance Corporation Medical College, Bangalore', 'Employees State Insurance Corporation Medical College, Bangalore'),
    'M39': ('Khaja Bandanawaz University - Faculty of Medical Sciences, Gulbarga', 'Khaja Bandanawaz University Faculty of Medical Sciences, Gulbarga'),
    'M40': ('Shri B M Patil Medical College, Hospital & Research Centre, Vijayapura (Bijapur', 'Shri B M Patil Medical College, Hospital & Research Centre, Vijayapura (Bijapur)'),
    'M43': ('Sapthagiri Institute of Medical Sciences & Research Centre, Bangalore', 'Sapthagiri Institute of Medical Sciences & Research Centre, Bangalore'),
    'M46': ('BGS Global Institute of Medical Sciences, Bangalore', 'BGS Global Institute of Medical Sciences, Bangalore'),
    'M47': ('Srinivas Institute of Medical Research Centre, Srinivasnagar, Mangalore', 'Srinivas Institute of Medical Sciences and Research Centre, Mangalore'),
    'M48': ('St. Johns Medical College, Bangalore', 'St. Johns Medical College, Bangalore'),
    'M49': ('Dharwad Institute of Mental Health and Neuro Sciences, Dharwad', 'Dharwad Institute of Mental Health and Neurosciences (DIMHANS), Dharwad'),
    'M50': ('K.H. Patil Institute of Medical Sciences (previously Gadag Institute of Medical Sciences, Mallasamudra, Mulgund Road, Gadag)', 'Gadag Institute of Medical Sciences, Gadag'),
    'M51': ('SDS Tuberculosis Research Centre and Rajiv Gandhi Institute of Chest Diseases, Bangalore', 'SDS Tuberculosis Research Centre and Rajiv Gandhi Institute of Chest Diseases, Bangalore'),
    'M52': ('Akash Institute of Medical Sciences & Research Centre, Devanhalli, Bangalore, Karnataka', 'Akash Institute of Medical Sciences and Research Centre, Bangalore'),
    'M53': ('The Oxford Medical College, Hospital & Research Centre, Bangalore', 'The Oxford Medical College, Hospital & Research Centre, Bangalore'),
    'M54': ('Shridevi Institute of Medical Sciences & Research Hospital, Tumkur', 'Shridevi Institute of Medical Sciences & Research Hospital, Tumkur'),
    'M55': ('Gulbarga Institute of Medical Sciences, Gulbarga', 'Gulbarga Institute of Medical Sciences, Gulbarga'),
    'M57': ('Koppal Institute of Medical Sciences, Koppal', 'Koppal Institute of Medical Sciences, Koppal'),
    'M58': ('Kanachur Institute of Medical Sciences, Mangalore', 'Kanachur Institute of Medical Sciences, Mangalore'),
    'M59': ('Subbaiah Institute of Medical Sciences, Shimoga, Karnataka', 'Subbaiah Institute of Medical Sciences, Shimoga'),
    'M60': ('Karwar Institute of Medical Sciences, Karwar', 'Karwar Institute of Medical Sciences, Karwar'),
    'M61': ('Kodagu Institute of Medical Sciences, Kodagu', 'Kodagu Institute of Medical Sciences, Kodagu'),
    'M62': ('Chamrajanagar Institute of Medical Sciences, Karnataka', 'Chamarajanagar Institute of Medical Sciences, Chamarajanagar'),
    'M63': ('East Point College of Medical Sciences & Research Centre, Bangalore', 'East Point College of Medical Sciences & Research Centre, Bangalore'),
    'M64': ('Shri Atal Bihari Vajpayee Medical College & Research Institute', 'Shri Atal Bihari Vajpayee Medical College and Research Institute, Bangalore'),
    'M65': ('Dr. Chandramma Dayananda Sagar Instt. of Medical Education & Research, Harohalli, Hubli', 'Dr. Chandramma Dayananda Sagar Institute of Medical Education & Research, Harohalli'),
    'M66': ('Chikkamagaluru Institute of Medical Sciences, Chikkamagaluru', 'Chikkamagaluru Institute of Medical Sciences, Chikkamagaluru'),  # new (not in 2025)
    'M67': ('Nandi Medical College and Research Institute Chikkaballapura (Chikkaballapura Institute of Medical Sciences Chikkaballapura )', 'Chikkaballapura Institute of Medical Sciences, Chikkaballapura'),
    'M68': ('Haveri Institute of Medical Sciences, Haveri', 'Haveri Institute of Medical Sciences, Haveri'),
    'M69': ('Siddaganga Medical College and Research Institute, Tumakuru', 'Siddaganga Medical College and Research Institute, Tumakuru'),
    'M70': ('Sri Chamundeshwari Medical College Hospital & Research Institute', 'Sri Chamundeshwari Medical College Hospital & Research Institute, Channapatna'),
    'M71': ('Sri Madhusudan Sai Institute of Medical Sciences & Research, Chikballapur', 'Sri Madhusudan Sai Institute of Medical Sciences and Research, Chikkaballapura')}
HOSPITALS = {  # DNB files: hospital code → (name as printed, standard name); Q… = DNB Regular, V… = DNB Diploma
    'Q001': ('General hospital 4th T Block, (beside RGUHS) Jayanagar, Bengaluru, Karnataka', 'General Hospital, Jayanagar, Bengaluru, Karnataka'),
    'Q002': ('KC General hospital #89 5th cross Malleshwaram, Bengaluru, Karnataka- 560003', 'K.C. General Hospital, Malleshwaram, Bengaluru, Karnataka'),
    'Q003': ('Sir CV Raman general hospital,80 feet road, Indiranagar, Bengaluru, Karnataka 560038', 'Sir C.V. Raman General Hospital, Indiranagar, Bengaluru, Karnataka'),
    'Q005': ('District hospital, sector no-11, Navanagar Bagalkot,Karnataka-587103', 'District Hospital, Bagalkot, Karnataka'),
    'Q006': ('District Hospital near sangam circle, Dr Rajkumar road, Ballari, Karnataka', 'District Hospital, Ballari, Karnataka'),
    'Q010': ('Taluk general hospital Kadur NH 206 Kadu, Chikkamagalur district, Karnataka', 'Taluk General Hospital, Kadur, Chikkamagaluru, Karnataka'),
    'Q012': ('District hospital killa road, Dharwad, Karnataka', 'District Hospital, Dharwad, Karnataka'),
    'Q013': ('General hospital Arakalagud road, Dr BR Ambedkarcircle, Holenarsipura taluka, Hassan District, Karnataka- 573211', 'General Hospital, Holenarasipura, Hassan, Karnataka'),
    'Q015': ('SNR District hospital Kolar, Karnataka -563101', 'SNR District Hospital, Kolar, Karnataka'),
    'Q016': ('Sub division hospital,opp town police station, Gangavathi, Karnataka- 583227', 'Sub-Divisional Hospital, Gangavathi, Karnataka'),
    'Q020': ('General hospital Shikaripura, near Ib circle Doddapete main road, Karnataka-577427', 'General Hospital, Shikaripura, Karnataka'),
    'Q021': ('Sub division hospital Sagara, JC Road, Sagara, Shivamogga dist Karnataka', 'Sub-Divisional Hospital, Sagara, Shivamogga, Karnataka'),
    'Q022': ('District hospital BH Road, Tumkakuru', 'District Hospital, Tumakuru, Karnataka'),
    'Q023': ('General hospital Pavagada,Tumakuru district,Karnataka', 'General Hospital, Pavagada, Tumakuru, Karnataka'),
    'Q025': ('District hospital next to sainik school second gate Athani road, Vijaypura, Karnataka-586103', 'District Hospital, Vijayapura, Karnataka'),
    'Q026': ('General hospital and MCH, Falls road Gokak, Belgaum dist, Karnataka- 591307', 'General Hospital and MCH, Gokak, Belagavi, Karnataka'),
    'Q027': ('General hospital, Tiptur, Karnataka-572201', 'General Hospital, Tiptur, Karnataka'),
    'Q028': ('Shri Jayachamrajendra general hospital, BH Road, Arasikere, Hassan district, Karnataka-573103', 'Shri Jayachamarajendra General Hospital, Arasikere, Hassan, Karnataka'),
    'Q030': ('District hospital and Epidemiological diseases hospital, Mysuru,KRS Road,Metagalli,Mysuru, Karnataka-570016', 'District Hospital and Epidemic Diseases Hospital, Mysuru, Karnataka'),
    'Q032': ('Government General Hospital and 60 Bed Mother and Child Hospital, Hosapete, Vijayanagra District Karnataka, Karnataka-583201', 'Government General Hospital and MCH, Hosapete, Karnataka'),
    'V001': ('General hospital 4th T Block, (beside RGUHS) Jayanagar, Bengaluru, Karnataka', 'General Hospital, Jayanagar, Bengaluru, Karnataka'),
    'V002': ('KC General hospital #89 5th cross Malleshwaram, Bengaluru, Karnataka- 560003', 'K.C. General Hospital, Malleshwaram, Bengaluru, Karnataka'),
    'V005': ('District hospital, sector no-11, Navanagar Bagalkot,Karnataka-587103', 'District Hospital, Bagalkot, Karnataka'),
    'V006': ('District Hospital near sangam circle, Dr Rajkumar road, Ballari, Karnataka', 'District Hospital, Ballari, Karnataka'),
    'V009': ('Chikkamagaluru Insitute of Medical Sciences, Tegur Village, Chikkamgaluru, Karntaka-577133', 'Chikkamagaluru Institute of Medical Sciences, Chikkamagaluru'),  # = M66
    'V012': ('District hospital killa road, Dharwad, Karnataka', 'District Hospital, Dharwad, Karnataka'),
    'V015': ('SNR District hospital Kolar, Karnataka -563101', 'SNR District Hospital, Kolar, Karnataka'),
    'V022': ('District hospital BH Road, Tumkakuru', 'District Hospital, Tumakuru, Karnataka'),
    'V025': ('District hospital next to sainik school second gate Athani road, Vijaypura, Karnataka-586103', 'District Hospital, Vijayapura, Karnataka')}
COURSES = {  # medical / St John's PDF: (course code, printed name in lower-case letters) → approved course name
    ('A1', 'mdanatomy'): 'MD/MS - Anatomy', ('A2', 'mdphysiology'): 'MD - Physiology', ('A3', 'mdbiochemistry'): 'MD - Biochemistry',
    ('B1', 'mdpharmacology'): 'MD - Pharmacology', ('B2', 'mdpathology'): 'MD - Pathology', ('B3', 'mdmicrobiology'): 'MD - Microbiology',
    ('B4', 'mdcommunitymedicine'): 'MD - Social & Preventive Medicine / Community Medicine',
    ('B5', 'mdforensicmedicine'): 'MD - Forensic Medicine', ('C1', 'mddermatology'): 'MD - Dermatology',
    ('C2', 'mdradiotherapy'): 'MD - Radiotherapy / Radiation Oncology', ('C3', 'mdpaediatrics'): 'MD - Paediatrics',
    ('C4', 'mdgeneralmedicine'): 'MD - General Medicine', ('C5', 'mdradiodiagnosis'): 'MD - Radio-Diagnosis',
    ('C6', 'mdpsychiatry'): 'MD - Psychiatry', ('C7', 'mdrespiratorymedicine'): 'MD - Respiratory Medicine',
    ('C8', 'mdhospitaladministration'): 'MD - Hospital Administration', ('C9', 'mdemergencymedicine'): 'MD - Emergency Medicine',
    ('D0', 'mdfamilymedicine'): 'MD - Family Medicine', ('D1', 'msopthalamology'): 'MS - Ophthalmology',
    ('D2', 'msent'): 'MS - ENT (Otorhinolaryngology)', ('D3', 'msorthopedics'): 'MS - Orthopaedics',
    ('D4', 'mdanaesthesia'): 'MD - Anaesthesiology', ('D5', 'msgeneralsurgery'): 'MS - General Surgery',
    ('D6', 'msobstetricsandgynecology'): 'MS - Obstetrics and Gynaecology',
    ('D7', 'mdimmunohaematologybloodtransfusion'): 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    ('D8', 'physicalmedicineandrehabilitation'): 'MD - Physical Medicine and Rehabilitation',
    ('DA', 'mdsportsmedicine'): 'MD - Sports Medicine', ('H1', 'mdgeritrics'): 'MD - Geriatrics',
    ('E1', 'diplomainclinicalpathology'): 'Diploma in Pathology', ('E4', 'diplomainpublichealthdph'): 'Diploma in Public Health',
    ('F4', 'diplomaintuberculosischestdiseases'): 'Diploma in Respiratory Medicine'}
DNB_REG = {  # DNB Regular: (code, name) → course (section dnb)
    ('G2', 'anaesthesiology'): 'DNB - Anaesthesiology (Post-MBBS)', ('G6', 'paediatrics'): 'DNB - Paediatrics (Post-MBBS)',
    ('F0', 'familymedicine'): 'DNB - Family Medicine (Post-MBBS)', ('F7', 'ent'): 'DNB - ENT (Post-MBBS)',
    ('G3', 'opthalmology'): 'DNB - Ophthalmology (Post-MBBS)', ('G1', 'obstricgynaecology'): 'DNB - Obstetrics and Gynaecology (Post-MBBS)',
    ('F3', 'radiology'): 'DNB - Radio-Diagnosis (Post-MBBS)'}
DNB_DIP = {  # DNB Diploma: (code, name) → (course, section)
    ('C3', 'paediatrics'): ('Diploma in Child Health / Paediatrics', 'diploma'), ('D1', 'opthalmology'): ('Diploma in Ophthalmology', 'diploma'),
    ('D3', 'orthopaedics'): ('Diploma in Orthopaedics', 'diploma'), ('D4', 'anaesthesiology'): ('Diploma in Anaesthesiology', 'diploma'),
    ('D6', 'obstetricsgynaecology'): ('Diploma in Obstetrics and Gynaecology', 'diploma'),
    ('C4', 'generalmedicine'): ('DNB Diploma - General Medicine', 'dnb'),     # no approved / NBEMS "Diploma in General Medicine"
    ('D5', 'generalsurgery'): ('DNB Diploma - General Surgery', 'dnb')}       # nor "Diploma in General Surgery" → hidden
COURSE_TYPE = {'government': ('Government Institute',), 'privateunaided': ('Private Institute',),
               'deemedprivateuniversity': ('Deemed', 'State Private University')}

CAT = {'CAT1': 'CAT1', 'CAT 1': 'CAT1', '2A': '2A', '2B': '2B', '3A': '3A', '3B': '3B', 'ST': 'ST', 'GM': 'GM',
       'SCA': 'SC-A', 'SC-B': 'SC-B', 'SCB': 'SC-B', 'SC-C': 'SC-C', 'SCC': 'SC-C', 'SCC(20%)': 'SC-C (20%)'}
G1 = ['CAT1', '2A', '2B', '3A', '3B', 'ST', 'SCA', 'SCB', 'SCC', 'SCC(20%)', 'GM']                 # non-inservice
G2 = ['GM', 'SCA', 'SCB', 'SCC', 'SCC(20%)', 'ST', 'CAT1', '2A', '2B', '3A', '3B']                 # inservice / PwD
PRIV = ['GMP', 'GMPH', 'OPN', 'NRI', 'OTH(Q)', 'MMH', 'MEH', 'MC', 'MM', 'MK', 'MU', 'MA', 'ME']
PRIV_QUOTA = {'GMP': 'Private Quota - GMP', 'GMPH': 'Private Quota - GMP', 'OPN': 'Private Quota - Open', 'NRI': 'NRI Quota',
              'OTH(Q)': 'Management Quota'}                                    # the rest: Private Quota - Minority
LEAD = ['SrNo', 'CLGCODE', 'COLLEGENAME', 'CRSCD', 'COURSENAME', 'COURSETYPE', 'SEATTYPE']
MED_HEAD = LEAD + G1 + G2 + G2 + ['HK-RK'] + PRIV + ['TotalSeats']
DNB_HEAD = LEAD + ['GM', 'SCA', 'SC-B', 'SC-C', 'SCC(20%)', 'ST', 'CAT1', '2A', '2B', '3A', '3B', 'HK-RK', 'TotalSeats']


def val(s, label):
    s = clean(s)
    if not s.isdigit():
        raise SystemExit(f'{label}: not a number: {s!r}')
    return int(s)


def page_table(page, head, groups, label):
    """The page's one table as rows of len(head) cells. Pages where the footer cell splits a column (an extra
    column with no heading) are folded back; the heading row and the group row are checked."""
    g = grids(page)
    if len(g) != 1:
        raise SystemExit(f'{label}: {len(g)} tables on the page')
    g = g[0]
    hi = next((i for i, r in enumerate(g) if clean(r[0]) == 'Sr No'), None)
    if hi is None:
        raise SystemExit(f'{label}: no heading row')
    hrow = g[hi]

    def fold(r):
        out = []
        for j, x in enumerate(r):
            if hrow[j] is None and j:
                if clean(x):
                    if clean(out[-1]):
                        raise SystemExit(f'{label}: two numbers in one split cell {r}')
                    out[-1] = x
            else:
                out.append(x)
        return out
    got = [nows(x) for x in fold(hrow)]
    if got != head:
        raise SystemExit(f'{label}: column headings changed: {got}')
    if not hi:          # some pages' detected table starts at the column headings (no group row) — headings checked
        return [fold(r) for r in g[hi + 1:]]
    top = fold(g[hi - 1])
    for j, t in groups.items():
        if len(top) <= j or clean(top[j]) != t:
            raise SystemExit(f'{label}: group heading {t!r} not over column {j}: {top}')
    return [fold(r) for r in g[hi + 1:]]


def read_kkrk(path, head, groups, codes, title, label):
    """KK / RK line pairs → list of courses {college, course code, name, type, kk, rk, kk_tot, rk_tot, priv, total};
    plus the GRAND TOTAL KK / RK lines. n = category columns per line; private columns only in the medical file."""
    doc = fitz.open(path)
    if title not in clean(doc[0].get_text()):
        raise SystemExit(f'{label}: title {title!r} not found')
    n = head.index('HK-RK') - len(LEAD)
    npriv = len(head) - len(LEAD) - n - 2
    courses, grand, cur, pending, sr_seen = [], {}, None, None, []
    for pno, page in enumerate(doc, 1):
        for r in page_table(page, head, groups, f'{label} p{pno}'):
            lab = clean(r[6])
            if lab not in ('KK', 'RK'):
                if any(clean(x) for x in r[7:]) and 'NOTE' not in ' '.join(clean(x) for x in r):
                    raise SystemExit(f'{label} p{pno}: unexpected line {r}')
                continue
            is_grand = clean(r[0]) == 'GRAND TOTAL'
            if clean(r[1]):
                code = clean(r[1])
                if code not in codes:
                    raise SystemExit(f'{label} p{pno}: unknown college / hospital code {code!r} ({clean(r[2])!r})')
                if clean(r[2]) != codes[code][0]:
                    raise SystemExit(f'{label} p{pno}: {code} printed name changed: {clean(r[2])!r}')
                if cur != code:
                    sr_seen.append((val(r[0], label), code))
                cur = code
            cats = [val(x, f'{label} p{pno} {cur} {lab}') for x in r[7:7 + n]]
            tot = val(r[7 + n], f'{label} p{pno} {cur} {lab} total')
            if sum(cats) != tot:
                raise SystemExit(f'{label} p{pno}: {cur} {clean(r[3])} {lab} categories add to {sum(cats)}, HK-RK {tot}')
            tail = r[8 + n:]
            if lab == 'KK':
                if pending:
                    raise SystemExit(f'{label} p{pno}: {pending["college"]} {pending["code"]} has no RK line')
                if any(clean(x) for x in tail):
                    raise SystemExit(f'{label} p{pno}: {cur} KK line has private / total cells {tail}')
                if is_grand:
                    grand['KK'] = cats + [tot]
                    pending = {'grand': True}
                    continue
                if not clean(r[3]):
                    raise SystemExit(f'{label} p{pno}: {cur} KK line without a course')
                pending = {'college': cur, 'code': clean(r[3]), 'name': clean(r[4]), 'type': key(r[5]),
                           'kk': cats, 'kk_tot': tot}
            else:
                if not pending or clean(r[3]):
                    raise SystemExit(f'{label} p{pno}: RK line without its KK line {r[:7]}')
                priv = [val(x, f'{label} p{pno} {cur} private') for x in tail[:npriv]]
                total = val(tail[npriv], f'{label} p{pno} {cur} Total Seats')
                if pending.get('grand'):
                    grand['RK'] = cats + [tot] + priv + [total]
                    if total != grand['KK'][-1] + tot + sum(priv):
                        raise SystemExit(f'{label}: GRAND TOTAL {total} ≠ KK + RK + private')
                else:
                    if pending['college'] != cur:
                        raise SystemExit(f'{label} p{pno}: course {pending["code"]} KK / RK lines in different colleges')
                    if total != pending['kk_tot'] + tot + sum(priv):
                        raise SystemExit(f'{label} p{pno}: {cur} {pending["code"]} Total Seats {total} ≠ KK {pending["kk_tot"]} '
                                         f'+ RK {tot} + private {sum(priv)}')
                    courses.append(dict(pending, rk=cats, rk_tot=tot, priv=priv, total=total))
                pending = None
    if pending or sorted(grand) != ['KK', 'RK']:
        raise SystemExit(f'{label}: GRAND TOTAL lines missing')
    srs = [s for s, _ in sr_seen]
    if srs != list(range(1, len(srs) + 1)) or len({c for _, c in sr_seen}) != len(sr_seen):
        raise SystemExit(f'{label}: college Sr No sequence broken: {sr_seen}')
    # every column = its GRAND TOTAL cell
    kk_sum = [sum(c['kk'][i] for c in courses) for i in range(n)] + [sum(c['kk_tot'] for c in courses)]
    rk_sum = ([sum(c['rk'][i] for c in courses) for i in range(n)] + [sum(c['rk_tot'] for c in courses)]
              + [sum(c['priv'][i] for c in courses) for i in range(npriv)] + [sum(c['total'] for c in courses)])
    names = head[len(LEAD):]
    for lab, got, printed, cols in (('KK', kk_sum, grand['KK'], names[:n + 1]), ('RK', rk_sum, grand['RK'], names)):
        for i, (a, b) in enumerate(zip(got, printed)):
            if a != b:
                raise SystemExit(f'{label}: column {lab} #{i} {cols[i]} adds to {a}, GRAND TOTAL {b}')
    return courses, grand, len(sr_seen)


rows, checks, institute_type = [], {}, {}


def kk_cat(c, kk, pwd=False):
    return CAT[c] + ('-PwD' if pwd else '') + (' (KK)' if kk else '')


# ── medical ──
med, mg, n_med = read_kkrk(MED, MED_HEAD, {6: 'NON- INSERVICE SEATS', 18: 'INSERVICE SEATS', 29: 'PWD SEATS',
                                           41: 'PRIVATE, MANEGEMANET,NRI'},
                           COLLEGES, 'PG MEDICAL PROVISIONAL SEAT MATRIX - 2026', 'medical')
types = collections.defaultdict(set)
for c in med:
    k = (c['code'], key(c['name']))
    if k not in COURSES:
        raise SystemExit(f'medical: unknown course {c["code"]} {c["name"]!r}')
    course, college = COURSES[k], COLLEGES[c['college']][1]
    if c['type'] not in COURSE_TYPE:
        raise SystemExit(f'medical: unknown course type {c["type"]!r}')
    types[college].add(c['type'])
    sec = 'diploma' if course.startswith('Diploma') else 'mdms'
    for kk, vals in ((True, c['kk']), (False, c['rk'])):
        for i, v in enumerate(vals):
            if not v:
                continue
            grp, ci = divmod(i, 11)
            lab = (G1 if grp == 0 else G2)[ci]
            quota = 'In-service Quota' if grp == 1 else 'Government Quota'
            rows.append({'college': college, 'course': course, 'quota': quota, 'seats': v, 'section': sec,
                         'category': kk_cat(lab, kk, grp == 2)})
    for lab, v in zip(PRIV, c['priv']):
        if v:
            rows.append({'college': college, 'course': course, 'quota': PRIV_QUOTA.get(lab, 'Private Quota - Minority'),
                         'seats': v, 'section': sec, 'category': lab})
for college, ts in types.items():
    if len(ts) != 1:
        raise SystemExit(f'medical: {college} printed with course types {ts}')
    institute_type[college] = COURSE_TYPE[ts.pop()]
med_total = mg['RK'][-1]
checks['medical seats'] = (sum(x['seats'] for x in rows), med_total)
checks['medical colleges (Sr No 1..n)'] = (len({c['college'] for c in med}), n_med)
nm = len(MED_HEAD) - len(LEAD)
for i, lab in enumerate((['NI ' + x for x in G1] + ['IS ' + x for x in G2] + ['PWD ' + x for x in G2] + ['HK-RK'])):
    checks[f'medical GRAND TOTAL KK {lab}'] = (sum(c['kk'][i] if i < 33 else c['kk_tot'] for c in med), mg['KK'][i])
    checks[f'medical GRAND TOTAL RK {lab}'] = (sum(c['rk'][i] if i < 33 else c['rk_tot'] for c in med), mg['RK'][i])
for i, lab in enumerate(PRIV):
    checks[f'medical GRAND TOTAL {lab}'] = (sum(c['priv'][i] for c in med), mg['RK'][34 + i])

# ── St John's (RC1 / RC2 / RC3) ──
doc = fitz.open(SJ)
if len(doc) != 1 or 'PG MEDICAL PROVISIONAL SEAT MATRIX - 2026' not in clean(doc[0].get_text()):
    raise SystemExit('stjohns: layout / title changed')
g = grids(doc[0])
if len(g) != 1 or [nows(x) for x in g[0][0]] != ['SrNo', 'CLGCODE', 'CLGNAME', 'CRSCODE', 'CRSNAME', 'COURSETYPE',
                                                  'RC1', 'RC2', 'RC3', 'TOTALSEATS']:
    raise SystemExit(f'stjohns: column headings changed: {g[0][0] if g else g}')
sj, sj_grand, college = collections.Counter(), None, None
for r in g[0][1:]:
    if clean(r[0]) == 'GRAND TOTAL':
        sj_grand = [val(x, 'stjohns grand') for x in r[6:10]]
        continue
    if clean(r[1]):
        if clean(r[1]) != 'M48' or clean(r[2]) != COLLEGES['M48'][0]:
            raise SystemExit(f'stjohns: unexpected college {r[1:3]}')
        college = COLLEGES['M48'][1]
    k = (clean(r[3]), key(r[4]))
    if k not in COURSES:
        raise SystemExit(f'stjohns: unknown course {r[3:5]}')
    v = [val(x, f'stjohns {k}') for x in r[6:10]]
    if sum(v[:3]) != v[3]:
        raise SystemExit(f'stjohns: {k} RC1-3 {v[:3]} ≠ total {v[3]}')
    for lab, n in zip(('RC1', 'RC2', 'RC3'), v[:3]):
        if n:
            rows.append({'college': college, 'course': COURSES[k], 'quota': 'Private Quota - Minority', 'seats': n,
                         'section': 'mdms', 'category': lab})
    for lab, n in zip(('RC1', 'RC2', 'RC3', 'TOTAL'), v):
        sj[lab] += n
if sj_grand is None:
    raise SystemExit('stjohns: no GRAND TOTAL line')
for lab, b in zip(('RC1', 'RC2', 'RC3', 'TOTAL'), sj_grand):
    checks[f'stjohns GRAND TOTAL {lab}'] = (sj[lab], b)

# ── DNB Regular / DNB Diploma (in-service) ──
DNB_CATS = ['GM', 'SCA', 'SC-B', 'SC-C', 'SCC(20%)', 'ST', 'CAT1', '2A', '2B', '3A', '3B']
dnb_totals = {}
for path, title, cmap, label in ((DNBR, 'DNB REGULAR SEAT MATRIX - 2026', DNB_REG, 'dnb_regular'),
                                 (DNBD, 'DNB DIPLOMA SEAT MATRIX - 2026', DNB_DIP, 'dnb_diploma')):
    courses, gr, n_h = read_kkrk(path, DNB_HEAD, {7: 'INSERVICE SEATS', 18: 'TOTAL'},
                                 {k: v for k, v in HOSPITALS.items() if k[0] == ('Q' if label == 'dnb_regular' else 'V')},
                                 title, label)
    before = sum(x['seats'] for x in rows)
    for c in courses:
        k = (c['code'], key(c['name']))
        if k not in cmap:
            raise SystemExit(f'{label}: unknown course {c["code"]} {c["name"]!r}')
        if c['type'] != 'government':
            raise SystemExit(f'{label}: course type {c["type"]!r}')
        course, sec = (cmap[k], 'dnb') if label == 'dnb_regular' else cmap[k]
        hosp = HOSPITALS[c['college']][1]
        institute_type.setdefault(hosp, ('Government Institute',))
        for kk, vals in ((True, c['kk']), (False, c['rk'])):
            for lab, v in zip(DNB_CATS, vals):
                if v:
                    rows.append({'college': hosp, 'course': course, 'seats': v, 'section': sec,
                                 'quota': 'DNB Quota (In-service)' if label == 'dnb_regular' else 'Diploma Quota (In-service)',
                                 'category': kk_cat(lab, kk)})
    dnb_totals[label] = gr['RK'][-1]
    checks[f'{label} seats'] = (sum(x['seats'] for x in rows) - before, gr['RK'][-1])
    checks[f'{label} hospitals (Sr No 1..n)'] = (len({c['college'] for c in courses}), n_h)
    for i, lab in enumerate(DNB_CATS + ['HK-RK']):
        checks[f'{label} GRAND TOTAL KK {lab}'] = (sum(c['kk'][i] if i < 11 else c['kk_tot'] for c in courses), gr['KK'][i])
        checks[f'{label} GRAND TOTAL RK {lab}'] = (sum(c['rk'][i] if i < 11 else c['rk_tot'] for c in courses), gr['RK'][i])

checks['all four files (= sum of the four printed grand totals)'] = (
    sum(x['seats'] for x in rows), med_total + sj_grand[3] + dnb_totals['dnb_regular'] + dnb_totals['dnb_diploma'])

# merge rows that repeat (same college × course × quota × category) — none expected
agg = collections.OrderedDict()
for x in rows:
    k = (x['college'], x['course'], x['quota'], x['category'])
    if k in agg:
        agg[k]['seats'] += x['seats']
    else:
        agg[k] = dict(x)
rows = list(agg.values())

FAMILY = {'Government Quota': ('Government Quota$',), 'In-service Quota': (),        # no 2025 KEA in-service rows
          'Private Quota - GMP': ('Private Quota - GMP$',), 'Private Quota - Open': ('Private Quota - Open$',),
          'NRI Quota': ('NRI Quota$',), 'Management Quota': ('Management Quota$',),
          'Private Quota - Minority': ('Private Quota - Minority$',),
          'DNB Quota (In-service)': ('DNB',), 'Diploma Quota (In-service)': ('Diploma Quota',)}
ROOT = {'GM': 'GM', 'CAT1': '1', '2A': '2A', '2B': '2B', '3A': '3A', '3B': '3B', 'ST': 'ST',
        'SC-A': 'SC-A', 'SC-B': 'SC-B', 'SC-C': 'SC-C', 'SC-C (20%)': 'SC-C'}


def kea(root, kk, pwd):
    """KEA 2025 allotment code: GM / GMH, else root + G (RK) / H (KK); 'P' prefix for PwD (PGM, P2AG, PGMH)."""
    c = ('GMH' if kk else 'GM') if root == 'GM' else root + ('H' if kk else 'G')
    return ('P' if pwd else '') + c


def cat_match(x):
    cat = x['category']
    if x['quota'] == 'Private Quota - GMP':
        return ('GMPH', 'GMP') if cat == 'GMPH' else ('GMP',)
    if x['quota'] == 'Management Quota':
        return ('MNG',)
    if x['quota'] in ('Private Quota - Open', 'NRI Quota', 'Private Quota - Minority'):
        return {'MMH': ('MMH', 'MM'), 'MEH': ('MEH', 'ME')}.get(cat, (cat,))
    m = re.fullmatch(r'(.+?)(-PwD)?( \(KK\))?', cat)
    root, pwd, kk = ROOT[m.group(1)], bool(m.group(2)), bool(m.group(3))
    seq = []
    for p in ((True, False) if pwd else (False,)):
        seq += [kea(root, kk, p), kea('GM', kk, p)] + ([kea(root, False, p), kea('GM', False, p)] if kk else [])
    return tuple(dict.fromkeys(seq))


cuts = load_cuts(CUTS, 'Karnataka')
known = {c['institute'] for c in cuts}
missing = sorted({v[1] for k, v in COLLEGES.items() if k != 'M66'} - known)
if missing:
    raise SystemExit(f'college map points at names not in the 2025 cut-offs: {missing}')
cut_type = {c['institute']: c['institute_type'] for c in cuts}
for name, allowed in sorted(institute_type.items()):
    if name in cut_type and cut_type[name] not in allowed:
        print(f'   NOTE: {name}: PDF course type {allowed}, 2025 cut-off institute_type {cut_type[name]!r} (cut-off type kept)')
for x in rows:
    if x['college'] not in cut_type:
        x['institute_type'] = institute_type[x['college']][0]
out = build(rows, cuts, 'Karnataka', 'KA', lambda q: FAMILY[q], cat_match)
CODE_FIX = {  # the shared 40-character cut gives the two ESIC colleges the same code, so they get a hand-made one
    'Employees State Insurance Corporation Medical College, Bangalore': 'KA-ESIC-MEDICAL-COLLEGE-BANGALORE',
    'Employees State Insurance Corporation Medical College, Gulbarga': 'KA-ESIC-MEDICAL-COLLEGE-GULBARGA'}
codes = collections.defaultdict(set)
for r in out:
    r['college_code'] = CODE_FIX.get(r['college_name'], r['college_code'])
    codes[r['college_code']].add(r['college_name'])
if any(len(v) > 1 for v in codes.values()):
    raise SystemExit(f'two colleges share a college code: {[v for v in codes.values() if len(v) > 1]}')
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
print('by file', {'medical': med_total, 'stjohns': sj_grand[3], **dnb_totals})
