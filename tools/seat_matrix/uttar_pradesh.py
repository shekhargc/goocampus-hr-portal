"""Uttar Pradesh NEET PG 2026 Round 1 seat matrix (DGME UP, upneet.gov.in "Seat Matrix For", 23/24.10.2026) →
standardised seat rows, bridged to UP's 2025 cut-offs. Two PDFs, the same layout:
  mdms — "UP NEET PG COUNSELING FOR MDMS(MEDICAL)-2026 Round-1": 35 Govt + 36 Private college blocks; MD/MS rows
         and a few medical-college diplomas (DCH, DGO, D ORTH, DA, DLO, DMRD, DVD). Category groups
         UR BC SC ST EW BS SS SG TS WE, each as total / OP / PH. Private colleges only fill UR / OP.
  dnb  — "UP NEET PG COUNSELING FOR DNB-2026": 51 Govt hospitals / colleges, POST MBBS DNB and POST MBBS DIPLOMA
         rows, groups UR BC SC ST EW only.
Every course row is checked (groups add up to the seat total, OP + PH to each group), every college block adds up
column by column to its printed Total row, and the Govt / Private / Grand Total rows to their colleges.
A diagonal red watermark is printed over the tables; its (rotated) words are dropped before the cells are read.
Run with /usr/bin/python3 (PyMuPDF):  uttar_pradesh.py <mdms.pdf> <dnb.pdf> <cutoffs2025.json> <out.json>"""
import re, sys, os, json, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report, college_code

MDMS, DNB, CUTS, OUT = sys.argv[1:5]

COLLEGES = {  # MD/MS PDF college header (name part) → standard institute name (exact 2025 cut-off name)
    'AUTONOMOUS MEDICAL COLLEGE, AYODHYA': 'Autonomous State Medical College, Ayodhya',
    'AUTONOMOUS MEDICAL COLLEGE, BAHRAICH': 'Maharaja Suhel Dev Autonomous State Medical College & Mahrishi Balark Hospitals, Bahraich',
    'AUTONOMOUS MEDICAL COLLEGE, BASTI': 'Maharshi Vashishtha Autonomous State Medical College, Basti',
    'AUTONOMOUS MEDICAL COLLEGE, DEORIA': 'Maharshi Devraha Baba Autonomous State Medical College, Deoria',
    'AUTONOMOUS MEDICAL COLLEGE, ETAH': 'Autonomous State Medical College, Etah',
    'AUTONOMOUS MEDICAL COLLEGE, FATEHPUR': 'Autonomous State Medical College Society, Fatehpur',
    'AUTONOMOUS MEDICAL COLLEGE, FIROZABAD': 'Autonomous State Medical College Society, Firozabad',
    'AUTONOMOUS MEDICAL COLLEGE, GHAZIPUR': 'Maharshi Vishwamitra Autonomous State Medical College, Ghazipur, Uttar Pradesh',
    'AUTONOMOUS MEDICAL COLLEGE, HARDOI': 'Autonomous State Medical College, Hardoi, Uttar Pradesh',
    'AUTONOMOUS MEDICAL COLLEGE, JAUNPUR': 'Uma Nath Singh Autonomous State Medical College Society, Jaunpur',
    'AUTONOMOUS MEDICAL COLLEGE, MIRZAPUR': 'Maa Vindhyavasini Autonomous State Medical College, Visundarpur, Mirzapur, Uttar Pradesh',
    'AUTONOMOUS MEDICAL COLLEGE, PRATAPGARH': 'Autonomous State Medical College, Pratapgarh',
    'AUTONOMOUS MEDICAL COLLEGE, SHAHJAHANPUR': 'Autonomous State Medical College, Shahjahanpur',
    'AUTONOMOUS MEDICAL COLLEGE, SIDDHARTHNAGAR': 'Autonomous State Medical College, Siddharthnagar',
    'BABA RAGHAV DAS MEDICAL COLLEGE, GORAKHPUR': 'Baba Raghav Das Medical College, Gorakhpur',
    'DR. RAM MANOHAR LOHIA INSTITUTE OF MEDICAL SCIENCES, LUCKNOW': 'Dr. Ram Manohar Lohia Institute of Medical Sciences, Lucknow',
    'GANESH SHANKAR VIDYARTHI MEMORIAL MEDICAL COLLEGE, KANPUR': 'GSVM Medical College, Kanpur',
    'GOVERNMENT INSTITUTE OF MEDICAL SCIENCES, GREATER NOIDA': 'Government Institute of Medical Sciences, Greater Noida',
    'GOVERNMENT MEDICAL COLLEGE, AMBEDKAR NAGAR': 'Mahamaya Rajkiya Allopathic Medical College, Ambedkarnagar',
    'GOVERNMENT MEDICAL COLLEGE, AZAMGARH': 'Government Medical College & Super Facility Hospital, Azamgarh',
    'GOVERNMENT MEDICAL COLLEGE, BADAUN': 'Government Medical College, Badaun',
    'GOVERNMENT MEDICAL COLLEGE, BANDA': 'Rani Durgavati Medical College, Banda',
    'GOVERNMENT MEDICAL COLLEGE, JALAUN': 'Rajkiya Medical College, Jalaun',
    'GOVERNMENT MEDICAL COLLEGE, KANNAUJ': 'Government Medical College, Kannauj, Uttar Pradesh',
    'GOVERNMENT MEDICAL COLLEGE, SAHARANPUR': 'Shaikh-UL-Hind Maulana Mahmood Hasan Medical College, Saharanpur',
    'INSTITUTE OF MENTAL HEALTH & HOSPITAL, AGRA': 'Institute of Mental Health and Hospital, Agra',
    'KING GEORGES MEDICAL UNIVESITY, LUCKNOW': 'King George Medical University, Lucknow',
    'LALA LAJPAT RAI MEMORIAL MEDICAL COLLEGE, MEERUT': 'Lala Lajpat Rai Memorial Medical College, Meerut',
    'MAHARANI LAXMI BAI MEDICAL COLLEGE, JHANSI': 'Maharani Laxmi Bai Medical College, Jhansi',
    'MOTI LAL NEHRU MEDICAL COLLEGE, PRAYAGRAJ': 'Moti Lal Nehru Medical College, Allahabad',
    'POST GRADUATE INSTITUTE OF CHILD HEALTH, NOIDA': 'Post Graduate Institute of Child Health, Sector 30, Noida, Uttar Pradesh',
    'REGIONAL INSTITUTE OF OPHTHALMOLOGY, SITAPUR': 'Regional Institute of Ophthalmology, Sitapur',
    'SANJAY GANDHI POSTGRADUATE INSTITUTE OF MEDICAL SCIENCE, LUCKNOW': 'Sanjay Gandhi Postgarduate Institute of Medical Sciences, Lucknow',
    'SAROJINI NAIDU MEDICAL COLLGE, AGRA': 'Sarojini Naidu Medical College, Agra',
    'UTTAR PRADESH UNIVERSITY OF MEDICAL SCIENCES, SAIFAI, ETAWAH': 'Uttar Pradesh University of Medical Sciences, Saifai, Etawah, Uttar Pradesh',
    'CAREER INSTITUTE OF MEDICAL SCIENCES, LKO': 'Career Institute of Medical Sciences & Hospital, Lucknow',
    'CAREER INSTITUTE OF MEDICAL SCIENCES, LKO (MUSLIM MINORITY)': 'Career Institute of Medical Sciences & Hospital, Lucknow',
    'ERA MEDICAL COLLEGE LUCKNOW': 'Era Lucknow Medical College, Lucknow',
    'ERA MEDICAL COLLEGE LUCKNOW (MUSLIM MINORITY)': 'Era Lucknow Medical College, Lucknow',
    'F.H. MEDICAL COLLEGE & HOSPITAL, AGRA': 'F.H. Medical College & Hospital, Etamdapur, Agra',
    'F.H. MEDICAL COLLEGE & HOSPITAL, AGRA (MUSLIM MINORITY)': 'F.H. Medical College & Hospital, Etamdapur, Agra',
    'G.S. MEDICAL COLLEGE, HAPUR': 'G.S. Medical College & Hospital, Hapur',
    'HERITAGE MEDICAL COLLEGE, VARANASI': 'Heritage Institute of Medical Sciences, Varanasi',
    'HIND MEDICAL COLLEGE BARABANKI': 'Hind Institute of Medical Sciences, Barabanki',
    'HIND MEDICAL COLLEGE, SITAPUR': 'Hind Institute of Medical Sciences, Sitapur',
    'INTEGRAL INSTITUTE OF MEDICAL SCIENCES, LUCKNOW': 'Integral Institute of Medical Sciences & Research, Lucknow',
    'INTEGRAL INSTITUTE OF MEDICAL SCIENCES, LUCKNOW (MUSLIM MINORITY)': 'Integral Institute of Medical Sciences & Research, Lucknow',
    'K.D. MEDICAL COLLEGE, MATHURA': 'K.D. Medical College Hospital & Research Centre, Mathura',
    'K.M. MEDICAL COLLEGE, MATHURA': 'Krishna Mohan Medical College & Hospital, Mathura',
    'MAYO INSTITUTE OF MEDICAL SCIENCE, BARABANKI': 'Mayo Institute of Medical Sciences, Barabanki',
    'MUZAFFAR NAGAR MEDICAL COLLEGE MUZAFFAR NAGAR': 'Muzaffarnagar Medical College, Muzaffarnagar',
    'NARAINA MEICAL COLLEGE & RESEARCH CENTRE, KANPUR': 'Naraina Medical College & Research Centre (NMCRC), Kanpur, Uttar Pradesh',
    'NATIONAL CAPITAL MEDICAL COLLEGE, MEERUT': 'National Capital Region Institute of Medical Sciences, Meerut',
    'NOIDA INTERNATIONAL INSTITUTE OF MEDICAL SCIENCES, GREATER NOIDA': 'Noida International Institute of Medical Science, Gautam Budha Nagar',
    'PRASAD MEDICAL COLLEGE, LUCKNOW': 'Prasad Institute of Medical Sciences, Lucknow',
    'RAJSHREE MEDICAL RESEARCH INSTITUTE BAREILLY': 'Rajshree Medical Research Institute, Bareilly',
    'RAMA MEDICAL COLLEGE HOSPITAL & RESEARCH CENTRE, HAPUR': 'Rama Medical College & Hospital, Hapur, Ghaziabad',
    'RAMA MEDICAL COLLEGE KANPUR': 'Rama Medical College & Hospital, Kanpur',
    'ROHILKHAND MEDICAL COLLEGE, BAREILLY': 'Rohilkhand Medical College & Hospital, Bareilly',
    'SARASWATI INSTITUTE OF MEDICAL SCIENCES HAPUR': 'Saraswati Institute of Medical Sciences, Hapur',
    'SARASWATI MEDICAL COLLEGE, UNNAO': 'Saraswati Medical College, Unnao',
    'SCHOOL OF MEDICAL SCIENCES & RESEARCH, SHARDA UNIVERSITY G. NOIDA': 'School of Medical Sciences & Research, Greater Noida',
    'SHRI RAM MURTI MEDICAL SCIENCES BARILLY': 'Shri Ram Murti Smarak Institute of Medical Sciences, Bareilly',
    'SKS HOSPITAL MEDICAL COLLEGE & RESEARCH CENTER, MATHURA': 'SKS Hospital Medical College & Research Centre, Mathura',
    'SUBHARATI MEDICAL COLLEGE, MEERUT': 'Subharti Medical College, Meerut',
    'T.S. MISHRA MEDICAL COLLEGE & HOSPITAL, LUCKNOW': 'T S Misra Medical College & Hospital, Amusi, Lucknow',
    'TEERTHANKER MAHAVEER UNIVERSITY, MORADABAD': 'Teerthanker Mahaveer Medical College & Research Center, Moradabad',
    'TEERTHANKER MAHAVEER UNIVERSITY, MORADABAD (JAIN MINORITY)': 'Teerthanker Mahaveer Medical College & Research Center, Moradabad',
    'UNITED MEDICAL COLLEGE, PRAYAGRAJ': 'United Institute of Medical Science, Prayagraj',
    'VARUNARJUN MEDICAL COLLEGE, SHAHAJANPUR': 'Varun Arjun Medical College, Shahjahanpur',
    'VENKATESHWARA MEDICAL COLLEGE, AMROHA': 'Venkateshwara Institute of Medical Sciences, Gajraula'}
HOSPITALS = {  # DNB / Post-MBBS Diploma PDF header → 2025 cut-off name where the college is there, else a new standard name
    'AUTONOMOUS STATE MEDICAL COLLEGE, ETAH': 'Autonomous State Medical College, Etah',
    'AUTONOMOUS STATE MEDICAL COLLEGE, HARDOI': 'Autonomous State Medical College, Hardoi, Uttar Pradesh',
    'RAJA PRATAP BAHADUR HOSPITAL ALLIED WITH DR SONELAL PATEL AUTONOMOUS STATE MEDICAL COLLEGE, PRATAPGARH':
        'Autonomous State Medical College, Pratapgarh',
    'AUTONOMOUS STATE MEDICAL COLLEGE & ALLIED PANDIT RAM PRASAD BISMIL MEMORIAL HOSPITAL, SHAHJAHANPUR':
        'Autonomous State Medical College, Shahjahanpur',
    'BALRAMPUR HOSPITAL, GOLAGANJ, LUCKNOW': 'Balrampur Hospital, Golaganj, Lucknow',
    'DR. SHYAMA PRASAD MUKHARJEE (CIVIL) HOSPITAL, HAZRATGANJ, LUCKNOW': 'Dr. Shyama Prasad Mukharjee (Civil) Hospital, Hazratganj, Lucknow',
    'GIMS, GREATER NOIDA, GAUTAM BUDDHA NAGAR': 'Government Institute of Medical Sciences, Greater Noida',
    'GOVERNMENT MEDICAL COLLEGE & SUPER SPCIALITY HOSPITAL, CHAKRAPANPUR, AZAMGARH':
        'Government Medical College & Super Facility Hospital, Azamgarh',
    'GOVERNMENT MEDICAL COLLEGE, GUNERA, WAZIDPUR, BADAUN': 'Government Medical College, Badaun',
    'RANI DURGAVATI MEDICAL COLLEGE (GOVERNMENT ALLOPATHIC MEDICAL COLLEGE), BANDA': 'Rani Durgavati Medical College, Banda',
    'MAHARAJA SUHEL DEV MEDICAL COLLEGE & MAHRISHI BALARK HOSPITAL, BAHRAICH':
        'Maharaja Suhel Dev Autonomous State Medical College & Mahrishi Balark Hospitals, Bahraich',
    'MAHARSHI VASHISHTHA AUTONOMOUS STATE MEDICAL COLLEGE & OPEC HOSPITAL, BASTI': 'Maharshi Vashishtha Autonomous State Medical College, Basti',
    'MRA MEDICAL COLLEGE, AMBEDKAR NAGAR': 'Mahamaya Rajkiya Allopathic Medical College, Ambedkarnagar',
    'P.L. SHARMA DISTRICT HOSPITAL, AHMAD ROAD, NEAR GHANTAGHAR, MEERUT': 'P.L. Sharma District Hospital, Meerut',
    'SHRI SHIV PRASAD GUPTA DIVISIONAL DISTRICT HOSPITAL, KABIRCHAURA VARANASI':
        'Shri Shiv Prasad Gupta Divisional District Hospital, Kabirchaura, Varanasi',
    'TEJ BAHADUR SAPRU HOSPITAL, STANLEY ROAD, ALLAHABAD': 'Tej Bahadur Sapru Hospital, Allahabad',
    'URSALA HORSMAN MEMORIAL HOSPITAL, BADA CHUARAHA, CIVIL LINES, KANPUR': 'Ursala Horsman Memorial Hospital, Kanpur',
    'VEERANGNA AWANTI BAI WOMEN HOSPITAL, GOLAGANJ, QUAISERBAGH, LUCKNOW': 'Veerangna Awanti Bai Women Hospital, Lucknow',
    'DISTRICT COMBINED HOSPITAL, SECTOR 23, SANJAY NAGAR, GHAZIABAD': 'District Combined Hospital, Sanjay Nagar, Ghaziabad',
    'DISTRICT COMBINED HOSPITAL, SECTOR 39, NOIDA, GAUTAM BUDDH NAGAR': 'District Combined Hospital, Sector 39, Noida',
    'DISTRICT COMBINED HOSPITAL, VRINDAVAN, MATHURA': 'District Combined Hospital, Vrindavan, Mathura',
    'DISTRICT MALE HOSPITAL, KOTWALI ROAD, BASTI': 'District Male Hospital, Basti',
    'DISTRICT MALE HOSPITAL, SAI KA TAKIYA, AGRA': 'District Male Hospital, Agra',
    'DISTRICT WOMEN HOSPITAL, NAKA SATRIKH, BARABANKI': 'District Women Hospital, Barabanki',
    'DISTRICT WOMEN HOSPITAL, REKABGANJ, AYODHYA': 'District Women Hospital, Ayodhya',
    'DIVISIONAL DISTRICT HOSPITAL, DDU MARG, BALRAMPUR, HARRA KI CHUNGI, SADAR, AZAMGARH': 'Divisional District Hospital, Azamgarh',
    'LAL BAHADUR SHASTRI HOSPITAL, RAMNAGAR, VARANASI': 'Lal Bahadur Shastri Hospital, Ramnagar, Varanasi',
    'LOK BANDHU RAJ NARAYAN COMBINED HOSPITAL, LDA COLONY, KANPUR ROAD, LUCKNOW': 'Lok Bandhu Raj Narayan Combined Hospital, Lucknow',
    'NETAJI SUBHASH CHANDRA BOSE DISTRICT HOSPITAL, GORAKHPUR': 'Netaji Subhash Chandra Bose District Hospital, Gorakhpur',
    'PANDIT DEEN DAYAL UPADHYAY DIVISIONAL DISTRICT HOSPITAL, MORADABAD': 'Pandit Deen Dayal Upadhyay Divisional District Hospital, Moradabad',
    'RANA BENI MADHAV SINGH DISTRICT HOSPITAL, NIRALANAGAR, KACHAHARI ROAD, RAIBARELI': 'Rana Beni Madhav Singh District Hospital, Raibareli',
    'SRI RAM HOSPITAL NEAR AYODHYA JUNCTION, AYODHYA': 'Sri Ram Hospital, Ayodhya',
    'SWAMI KALYAN DEV DISTRICT HOSPITAL, LADDHAWALA, MUZAFFARNAGAR': 'Swami Kalyan Dev District Hospital, Muzaffarnagar',
    'AUTONOMOUS STATE MEDICAL COLLEGE, AYODHYA': 'Autonomous State Medical College, Ayodhya',
    'AUTONOMOUS STATE MEDICAL COLLEGE (ASMC) PILIBHIT': 'Autonomous State Medical College, Pilibhit',
    'AUTONOMOUS STATE MEDICAL COLLEGE, TILOI, AMETHI': 'Autonomous State Medical College, Tiloi, Amethi',
    'COMBINED DISTRICT HOSPITAL, GT ROAD, KANNAUJ': 'Combined District Hospital, Kannauj',
    'DISTRICT COMBINED HOSPITAL, PHARENDA ROAD MUKHYALAY MAHARAJGANJ': 'District Combined Hospital, Maharajganj',
    'DISTRICT HOSPITAL, MALE BUDAUN, KUTCHERY ROAD BUDAUN': 'District Hospital (Male), Budaun',
    'DISTRICT WOMEN HOSPITAL JAUNPUR, SAHABUDDINPUR, BHANDARI STATION ROAD, JAUNPUR': 'District Women Hospital, Jaunpur',
    'GOVERNMENT TB HOSPITAL, TELIYARGANJ PRAYAGRAJ': 'Government TB Hospital, Teliyarganj, Prayagraj',
    'KALYAN SINGH GOVERNMENT MEDICAL COLLEGE, CHANDPUR ROAD, NEAR TEHSIL SADAR,BULANDSHAHR': 'Kalyan Singh Government Medical College, Bulandshahr',
    'MANAYAWAR KANSHI RAM DISTRCIT COMBINED HOSPITAL AND TRAUMA CENTRE, RAMADEVI KANPUR NAGAR':
        'Manayawar Kanshi Ram District Combined Hospital and Trauma Centre, Kanpur',
    'PANDIT DEEN DAYAL UPADHYAY GOVERNMENT HOSPITAL, PANDEYPUR, VARANASI': 'Pandit Deen Dayal Upadhyay Government Hospital, Pandeypur, Varanasi',
    'MAHARSHI VISHWAMITRA AUTONOMOUS STATE MEDICAL COLLEGE, RTI MAIDAN, GHAZIPUR':
        'Maharshi Vishwamitra Autonomous State Medical College, Ghazipur, Uttar Pradesh',
    'AUTONOMOUS STATE MEDICAL COLLEGE AND HOSPITAL,CHICHAULI,DIBIYAPUR ROAD,AURAIYA': 'Autonomous State Medical College, Auraiya',
    'MAHATMA VIDUR AUTONOMOUS STATE MEDICAL COLLEGE, VILL MADHUSUDANPUR DEVIDAS, POST KIRATPUR, TEH NAJIBABAD , DISTT BIJNOR':
        'Mahatma Vidur Autonomous State Medical College, Bijnor',
    'RAM SAGAR MISHRA COMBINED HOSPITAL, SADHAMAU BKT LUCKNOW': 'Ram Sagar Mishra Combined Hospital, Sadhamau, Lucknow',
    'MENTAL HOSPITAL BAREILLY, ANAND ASHRAM ROAD, SHYAMGANJ, BAREILLY, UTTAR PRADESH': 'Mental Hospital, Bareilly',
    'RANI LAXMI BAI COMBINED HOSPITAL LUYCKNOW, A BLOCK RAJAJIPURAM LUCKNOW': 'Rani Laxmi Bai Combined Hospital, Rajajipuram, Lucknow',
    'DISTRICT WOMEN HOSPITAL, BAJORIA ROAD, SAHARANPUR': 'District Women Hospital, Saharanpur'}
COURSES = {  # PDF course code → (the PDF's own wording, approved course name, section) — the wording is checked
    'ANS': ('MD ANAESTHESIA', 'MD - Anaesthesiology', 'mdms'), 'ANT': ('MS ANATOMY', 'MD/MS - Anatomy', 'mdms'),
    'MBI': ('MD BIOCHEMISTRY', 'MD - Biochemistry', 'mdms'),
    'SPM': ('MD COMMUNITY MEDICINE', 'MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    'SKI': ('MD DERMATOLOGY', 'MD - Dermatology', 'mdms'), 'EGM': ('MD EMERGENCY MEDICINE', 'MD - Emergency Medicine', 'mdms'),
    'MDM': ('MD FORENSIC MEDICINE', 'MD - Forensic Medicine', 'mdms'), 'MDI': ('MD GENERAL MEDICINE', 'MD - General Medicine', 'mdms'),
    'MHA': ('MD HOSPITAL ADMINISTRATION', 'MD - Hospital Administration', 'mdms'),
    'IBT': ('MD IMMUNOHAEMATOLOGY & BLOOD TRANSFUISION', 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'mdms'),
    'LMN': ('MD LAB MEDICINE', 'MD - Laboratory Medicine', 'mdms'), 'MIC': ('MD MICROBIOLOGY', 'MD - Microbiology', 'mdms'),
    'MNM': ('MD NUCLEAR MEDICINE', 'MD - Nuclear Medicine', 'mdms'), 'PAE': ('MD PAEDIATRICS', 'MD - Paediatrics', 'mdms'),
    'PAH': ('MD PATHOLOGY', 'MD - Pathology', 'mdms'), 'PHA': ('MD PHARMACOLOGY', 'MD - Pharmacology', 'mdms'),
    'PMR': ('MD PHYSICAL MEDICINE AND REHABILITATION', 'MD - Physical Medicine and Rehabilitation', 'mdms'),
    'PHY': ('MD PHYSIOLOGY', 'MD - Physiology', 'mdms'), 'PSY': ('MD PSYCHIATRY', 'MD - Psychiatry', 'mdms'),
    'MRO': ('MD RADIATION ONCOLOGY', 'MD - Radiotherapy / Radiation Oncology', 'mdms'),
    'RDI': ('MD RADIODIAGNOSIS', 'MD - Radio-Diagnosis', 'mdms'), 'TBC': ('MD RESPIRATORY MEDICINE', 'MD - Respiratory Medicine', 'mdms'),
    'SPO': ('MD SPORTS MEDICINE', 'MD - Sports Medicine', 'mdms'),
    'MTS': ('MD TRAUMATOLOGY & SURGERY', 'MS - Traumatology and Surgery', 'mdms'),   # printed "MD"; the approved name is MS
    'ENT': ('MS ENT', 'MS - ENT (Otorhinolaryngology)', 'mdms'), 'SRG': ('MS GENERAL SURGERY', 'MS - General Surgery', 'mdms'),
    'GYN': ('MS OBSTETRICS & GYNAECOLOGY', 'MS - Obstetrics and Gynaecology', 'mdms'),
    'OPH': ('MS OPHTHALMOLOGY', 'MS - Ophthalmology', 'mdms'), 'ORT': ('MS ORTHOPAEDICS', 'MS - Orthopaedics', 'mdms'),
    # medical-college diplomas (in the MD/MS PDF)
    'DCH': ('DCH', 'Diploma in Child Health / Paediatrics', 'diploma'), 'DGO': ('DGO', 'Diploma in Obstetrics and Gynaecology', 'diploma'),
    'DOR': ('D ORTH', 'Diploma in Orthopaedics', 'diploma'), 'DDA': ('DA', 'Diploma in Anaesthesiology', 'diploma'),
    'DLO': ('DLO', 'Diploma in ENT', 'diploma'), 'DMR': ('DMRD', 'Diploma in Radio Diagnosis', 'diploma'),
    'DVD': ('DVD', 'Diploma in Dermatology', 'diploma'),
    # DNB PDF: Post-MBBS Diploma
    'ANED': ('ANESTHESIOLOGY (POST MBBS DIPLOMA)', 'Diploma in Anaesthesiology', 'diploma'),
    'OBSD': ('OBS & GYNAE (POST MBBS DIPLOMA)', 'Diploma in Obstetrics and Gynaecology', 'diploma'),
    'OPHD': ('OPHTHALMOLOGY (POST MBBS DIPLOMA)', 'Diploma in Ophthalmology', 'diploma'),
    'ENTD': ('OTORHINOLARYNGOLOGY (ENT) (POST MBBS DIPLOMA)', 'Diploma in ENT', 'diploma'),
    'PAED': ('PEDIATRICS (POST MBBS DIPLOMA)', 'Diploma in Child Health / Paediatrics', 'diploma'),
    'RDID': ('RADIODIAGNOSIS (POST MBBS DIPLOMA)', 'Diploma in Radio Diagnosis', 'diploma'),
    'TBCD': ('RESPIRATORY MEDICINE (TB & CHEST) (POST MBBS DIPLOMA)', 'Diploma in Respiratory Medicine', 'diploma'),
    # DNB PDF: Post-MBBS DNB ("DNB - … (Post-MBBS)" as in madhya_pradesh.py / rajasthan.py; hidden by the DNB filter)
    'ANES': ('ANESTHESIOLOGY (POST MBBS DNB)', 'DNB - Anaesthesiology (Post-MBBS)', 'dnb'),
    'EGMP': ('EMERGENCY MEDICINE (POST MBBS DNB)', 'DNB - Emergency Medicine (Post-MBBS)', 'dnb'),
    'FAMP': ('FAMILY MEDICINE (POST MBBS DNB)', 'DNB - Family Medicine (Post-MBBS)', 'dnb'),
    'GMDP': ('GENERAL MEDICINE (POST MBBS DNB)', 'DNB - General Medicine (Post-MBBS)', 'dnb'),
    'GSRP': ('GENERAL SURGERY (POST MBBS DNB)', 'DNB - General Surgery (Post-MBBS)', 'dnb'),
    'OBSP': ('OBS & GYNAE (POST MBBS DNB)', 'DNB - Obstetrics and Gynaecology (Post-MBBS)', 'dnb'),
    'OTHP': ('ORTHOPEDICS (POST MBBS DNB)', 'DNB - Orthopaedics (Post-MBBS)', 'dnb'),
    'PAHP': ('PATHOLOGY (POST MBBS DNB)', 'DNB - Pathology (Post-MBBS)', 'dnb'),
    'PAEP': ('PEDIATRICS (POST MBBS DNB)', 'DNB - Paediatrics (Post-MBBS)', 'dnb'),
    'PSYP': ('PSYCHIATRY (POST MBBS DNB)', 'DNB - Psychiatry (Post-MBBS)', 'dnb'),
    'RMCP': ('RESPIRATORY MEDICINE (TB & CHEST) (POST MBBS DNB)', 'DNB - Respiratory Medicine (Post-MBBS)', 'dnb'),
    'SKIP': ('SKIN (POST MBBS DNB)', 'DNB - Dermatology (Post-MBBS)', 'dnb')}
CAT_NAME = {'UR': 'UR', 'BC': 'OBC', 'SC': 'SC', 'ST': 'ST', 'EW': 'EWS',      # PDF group → category ("-PwD" = PH seats);
            'BS': 'BS', 'SS': 'SS', 'SG': 'SG', 'TS': 'TS', 'WE': 'WE'}        # BS/SS/SG/TS/WE kept as UP prints them
MINORITY = {'(MUSLIM MINORITY)': 'Private Quota (Muslim Minority)', '(JAIN MINORITY)': 'Private Quota (Jain Minority)'}
HEADER = re.compile(r'^(\d+)\.\s+(.+?),?\s*\((\d{3})\)\s*\[(Govt\.|Private)\]\s*\(Co-Education\)$')


def words_flat(page):
    """The page's words without the diagonal watermark (its line runs at 45°, the table text is horizontal)."""
    tp = page.get_textpage()
    rotated = {(b['number'], li) for b in page.get_text('dict', textpage=tp)['blocks']
               for li, l in enumerate(b.get('lines', [])) if abs(l['dir'][1]) > 1e-3}
    return [w for w in page.get_text('words', textpage=tp) if (w[5], w[6]) not in rotated]


def grids(page):
    """Like common.grids, but read from the watermark-free words."""
    words = words_flat(page)

    def text(b):
        if b is None:
            return None
        x0, y0, x1, y1 = b
        return ' '.join(w[4] for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1)
    return [[[text(c) for c in r.cells] for r in t.rows] for t in page.find_tables().tables]


def val(s, where):
    s = clean(s)
    if not s.isdigit():
        raise SystemExit(f'{where}: not a number: {s!r}')
    return int(s)


def parse(path, groups, names, label, title):
    """One seat-matrix PDF → list of college blocks {name, code, kind, courses:[(code, raw, [values])], total:[...]}
    plus the printed summary rows {'Total (Govt)': [...], 'Total (Private)': [...], 'Grand Total': [...]}."""
    head = ['Course Name & Code', 'UPNEET PG Seat'] + [h for g in groups for h in (g, g + ' OP', g + ' PH')] + ['Status']
    width = 1 + 3 * len(groups)
    doc = fitz.open(path)
    first = clean(doc[0].get_text())
    if title not in first or 'Round-1' not in first:
        raise SystemExit(f'{label}: page 1 heading changed')
    colleges, summary, cur = [], {}, None
    for p in range(len(doc)):
        for g in grids(doc[p]):
            for r in g:
                if len(r) != len(head):
                    raise SystemExit(f'{label} p{p + 1}: table has {len(r)} columns, expected {len(head)}')
                cells = [clean(x) for x in r]
                a = cells[0]
                if not any(cells) or a.startswith(('Seat Matrix For', 'Director General Medical Education')):
                    continue
                if a == 'Course Name & Code':
                    if cells != head:
                        raise SystemExit(f'{label} p{p + 1}: column headings changed: {cells}')
                    continue
                m = HEADER.match(a)
                if m:
                    if any(cells[1:]):
                        raise SystemExit(f'{label} p{p + 1}: college header row has extra cells: {cells}')
                    if cur and cur['total'] is None:
                        raise SystemExit(f'{label}: {cur["raw"]} has no Total row')
                    if int(m.group(1)) != len(colleges) + 1:
                        raise SystemExit(f'{label}: college number {m.group(1)} out of order')
                    if m.group(2) not in names:
                        raise SystemExit(f'{label}: unknown college {m.group(2)!r}')
                    cur = {'raw': m.group(2), 'code': m.group(3), 'kind': m.group(4), 'courses': [], 'total': None}
                    colleges.append(cur)
                    continue
                if a in ('Total', 'Total (Govt)', 'Total (Private)', 'Grand Total'):
                    vals = [val(x, f'{label} {a}') for x in cells[1:width + 1]]
                    if cells[-1]:
                        raise SystemExit(f'{label}: {a} row has a status {cells[-1]!r}')
                    if a == 'Total':
                        if cur is None or cur['total'] is not None:
                            raise SystemExit(f'{label} p{p + 1}: stray Total row')
                        cur['total'] = vals
                    else:
                        summary[a] = vals
                    continue
                m = re.match(r'^(.+?)\s*\[(\w+)\s*\]$', a)
                if not m or cur is None or cur['total'] is not None:
                    raise SystemExit(f'{label} p{p + 1}: unexpected row {cells}')
                raw, code = m.group(1).upper(), m.group(2)
                if code not in COURSES or COURSES[code][0] != raw:
                    raise SystemExit(f'{label}: unknown course {a!r}')
                if not cells[-1].startswith('Approved'):
                    raise SystemExit(f'{label}: {cur["raw"]} {a}: status {cells[-1]!r}')
                vals = [val(x, f'{label} {cur["raw"]} {a}') for x in cells[1:width + 1]]
                if any(c == code for c, _, _ in cur['courses']):
                    raise SystemExit(f'{label}: {cur["raw"]} lists {a} twice')
                cur['courses'].append((code, a, vals))
    if cur and cur['total'] is None:
        raise SystemExit(f'{label}: {cur["raw"]} has no Total row')
    return colleges, summary


def check_and_rows(colleges, summary, groups, names, label, checks):
    """Row / college / summary checks; returns seat rows (one per course × category, PH seats as '-PwD')."""
    cols = ['Seat'] + [h for g in groups for h in (g, g + ' OP', g + ' PH')]
    rows, sums = [], {'Govt.': [0] * len(cols), 'Private': [0] * len(cols)}
    for c in colleges:
        college = names[c['raw']]
        quota = 'State Quota' if c['kind'] == 'Govt.' else next(
            (q for k, q in MINORITY.items() if c['raw'].endswith(k)), 'Private Quota')
        acc = [0] * len(cols)
        for code, raw, v in c['courses']:
            where = f'{label}: {c["raw"]} {raw}'
            for gi, grp in enumerate(groups):
                t, op, ph = v[1 + 3 * gi:4 + 3 * gi]
                if op + ph != t:
                    raise SystemExit(f'{where}: {grp} OP {op} + PH {ph} ≠ {t}')
            if sum(v[1 + 3 * gi] for gi in range(len(groups))) != v[0]:
                raise SystemExit(f'{where}: categories add to {sum(v[1 + 3 * gi] for gi in range(len(groups)))}, seats {v[0]}')
            if c['kind'] == 'Private' and v[2] != v[0]:
                raise SystemExit(f'{where}: private college with seats outside UR / OP')
            acc = [x + y for x, y in zip(acc, v)]
            for gi, grp in enumerate(groups):
                for n, suffix in ((v[2 + 3 * gi], ''), (v[3 + 3 * gi], '-PwD')):
                    if n:
                        rows.append({'college': college, 'course': COURSES[code][1], 'quota': quota, 'seats': n,
                                     'section': COURSES[code][2], 'category': CAT_NAME[grp] + suffix, 'kind': c['kind']})
        if acc != c['total']:
            bad = {cols[i]: (a, b) for i, (a, b) in enumerate(zip(acc, c['total'])) if a != b}
            raise SystemExit(f'{label}: {c["raw"]} courses do not add up to its Total row: {bad}')
        sums[c['kind']] = [x + y for x, y in zip(sums[c['kind']], acc)]
    checks[f'{label} college Total rows matched'] = (len(colleges), len(colleges))
    want = {'Total (Govt)': sums['Govt.'], 'Total (Private)': sums['Private'],
            'Grand Total': [x + y for x, y in zip(sums['Govt.'], sums['Private'])]}
    for name, got in want.items():
        if name not in summary:
            raise SystemExit(f'{label}: no {name} row')
        for i, col in enumerate(cols):
            if col == 'Seat' or got[i] or summary[name][i]:
                checks[f'{label} {name} {col}'] = (got[i], summary[name][i])
    return rows


checks = {}
MD_GROUPS = ['UR', 'BC', 'SC', 'ST', 'EW', 'BS', 'SS', 'SG', 'TS', 'WE']
DNB_GROUPS = ['UR', 'BC', 'SC', 'ST', 'EW']
md_colleges, md_sum = parse(MDMS, MD_GROUPS, COLLEGES, 'mdms', 'UP NEET PG COUNSELING FOR MDMS(MEDICAL)-2026')
dnb_colleges, dnb_sum = parse(DNB, DNB_GROUPS, HOSPITALS, 'dnb', 'UP NEET PG COUNSELING FOR DNB-2026')
md_rows = check_and_rows(md_colleges, md_sum, MD_GROUPS, COLLEGES, 'mdms', checks)
dnb_rows = check_and_rows(dnb_colleges, dnb_sum, DNB_GROUPS, HOSPITALS, 'dnb', checks)
if set(COLLEGES) - {c['raw'] for c in md_colleges} or set(HOSPITALS) - {c['raw'] for c in dnb_colleges}:
    raise SystemExit('mapping table has colleges the PDFs no longer list: '
                     f'{sorted(set(COLLEGES) - {c["raw"] for c in md_colleges}) + sorted(set(HOSPITALS) - {c["raw"] for c in dnb_colleges})}')

cuts = load_cuts(CUTS, 'Uttar Pradesh')
known = {c['institute'] for c in cuts}
for raw, name in COLLEGES.items():   # every MD/MS college is a 2025 college (the DNB list also has new hospitals)
    if name not in known:
        raise SystemExit(f'MD/MS college {raw!r} → {name!r} is not a 2025 UP cut-off institute')
CODE_FIX = {  # the shared 40-character cut gives these two the same code, so they get a hand-made one
    'Autonomous State Medical College Society, Fatehpur': 'UP-AUTONOMOUS-STATE-MEDICAL-COLLEGE-SOCIETY-FATEHPUR',
    'Autonomous State Medical College Society, Firozabad': 'UP-AUTONOMOUS-STATE-MEDICAL-COLLEGE-SOCIETY-FIROZABAD'}
code_of = lambda name: CODE_FIX.get(name) or college_code('UP', name)
codes = collections.defaultdict(set)
for name in set(COLLEGES.values()) | set(HOSPITALS.values()):
    codes[code_of(name)].add(name)
if any(len(v) > 1 for v in codes.values()):
    raise SystemExit(f'two colleges share a college code: {[v for v in codes.values() if len(v) > 1]}')
for x in md_rows + dnb_rows:   # institute_type from the cut-off where known, else from the PDF header
    if x['college'] not in known:
        x['institute_type'] = 'Government Institute' if x['kind'] == 'Govt.' else 'Private Institute'
cut_type = {c['institute']: c['institute_type'] for c in cuts}
for name in sorted({x['college'] for x in md_rows + dnb_rows if x['college'] in known}):
    hdr = {x['kind'] for x in md_rows + dnb_rows if x['college'] == name}
    if ('Govt.' in hdr) != (cut_type[name] == 'Government Institute'):
        print(f'   NOTE: {name}: PDF header {sorted(hdr)}, 2025 cut-off institute_type {cut_type[name]!r} (cut-off type kept)')
keys = collections.Counter((x['college'], x['course'], x['quota'], x['category']) for x in md_rows + dnb_rows)
if any(n > 1 for n in keys.values()):
    raise SystemExit(f'the same college × course × quota × category comes twice: {[k for k, n in keys.items() if n > 1]}')

# common.build matches quota families by prefix, and UP's names nest ("Government Quota" is a prefix of
# "Government Quota-Inservice", "Private Quota" of "Private Quota-Minority"), so every 2025 quota gets a '|' end
# mark for the bridge and families name whole quotas; the mark is taken off cutoff_quota afterwards.
FAMILY = {'State Quota': ('Government Quota|',), 'Private Quota': ('Private Quota|',),
          'Private Quota (Muslim Minority)': ('Private Quota-Minority|',),
          'Private Quota (Jain Minority)': ('Private Quota-Minority|',)}
# BS / SS / SG / TS / WE: in UP's 2025 cut-offs these codes only occur under "Government Quota-Inservice"
# (the medical-college diplomas), so those seats bridge to the in-service ranks; every other govt seat bridges to
# "Government Quota" only (never falls back to an in-service rank).
INSERVICE_CODES = ('BS', 'SS', 'SG', 'TS', 'WE')
INSERVICE_FAMILY = {'State Quota': ('Government Quota-Inservice|',)}
PDF_CAT = {'OBC': 'BC'}   # our name → UP's 2025 code (EWS, UR, SC, ST, BS, SS, SG … are the same)


def cat_match(x):
    base = x['category'].split('-')[0]
    code = PDF_CAT.get(base, base)
    return (f'{code}-PH', code) if x['category'].endswith('PwD') else (code,)


rows = md_rows + dnb_rows
special = [i for i, x in enumerate(rows) if x['category'].split('-')[0] in INSERVICE_CODES]
plain = sorted(set(range(len(rows))) - set(special))
marked = [dict(c, quota=c['quota'] + '|') for c in cuts]
out = [None] * len(rows)
for idx, fam in ((plain, FAMILY), (special, INSERVICE_FAMILY)):
    for i, r in zip(idx, build([rows[i] for i in idx], marked, 'Uttar Pradesh', 'UP', lambda q: fam[q], cat_match)):
        r['cutoff_quota'] = r['cutoff_quota'].rstrip('|')
        out[i] = r
for i, r in enumerate(out, 1):
    r['sl_no'], r['college_code'] = i, code_of(r['college_name'])
json.dump({'rows': out, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
report(out, checks)
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
n_md = len(md_rows)
for lab, part in (('mdms pdf', out[:n_md]), ('dnb pdf', out[n_md:])):
    print(f'{lab}: rows {len(part)} seats {sum(r["seats"] for r in part)} colleges {len({r["college_name"] for r in part})}',
          '| linked', sum(r['seats'] for r in part if r['has_cutoff']),
          '| new', dict(collections.Counter(r['new_reason'] for r in part if not r['has_cutoff'])))
