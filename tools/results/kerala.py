"""Kerala (CEE Kerala) PG Medical seat allotment result (provisional / final, any phase) → rows for
POST /api/pg/results/ingest. Reads the official PDF from cee.kerala.gov.in/pgm2026 → "Allotment List" (e.g.
list/allot_p1_provi.pdf, "First Phase Allotment List (Provisional)"): one table line per allotted seat —
Sl.No, ApplNo, Rank, College Name ("TVM- Govt. Medical College, Thiruvananthapuram"), Course ("GM- M D General
Medicine"), Candidate Category, Alloted Category (suffix '#' = provisionally allotted subject to the screening
committee decision, '*' = NRI provisionally allowed), Option No. No names are printed; ApplNo is dropped as read.
Ranks: the printed Rank is the NEET PG All-India rank (every one is an AIR of the loaded Kerala State Merit List and
the list runs in AIR order) → `rank_ai`. `rank` = the Kerala state merit rank, looked up by AIR in the loaded merit
list (--merit; AIR is unique there) — not printed in the allotment list.
Quota is not printed: it follows from the college (government: the GO's government group — Govt. Medical Colleges,
RCC, Malabar Cancer Centre; the rest are self-financing) and the allotted category, in 2025 CEE spellings:
  government college → Government Quota · self-financing → Private Quota · AC / MM (minority community) →
  Private Quota - Minority · NR → NRI Quota · NC / NM → NRI Quota - Minority (AC/MM/NR/NC/NM only at self-financing).
Categories as printed (2025 CEE codes: SM state merit, SC, ST, EZ, BH, MU, LA, BX, KU, EW, PD, AC, MM, NR, NC, NM;
XS ex-serviceman is new in 2026 — kept as XS, its 2025 fallback is SM). Course codes AND names must both be known.
Run with /usr/bin/python3 (PyMuPDF):
    kerala.py <allotment.pdf> <out.json> [--merit cee_kerala_state_merit.json]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
MERIT = None
if '--merit' in args:
    i = args.index('--merit'); MERIT = args[i + 1]; del args[i:i + 2]
if len(args) != 2:
    raise SystemExit(__doc__)
PDF, OUT = args
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

HEAD = [['Sl.No', 'ApplNo', 'Rank', 'College Name', 'Course', 'Candidate', 'Alloted', 'Option No.'],
        ['', '', '', '', '', 'Category', 'Category', '']]
GOVT = {'ALP', 'CMC', 'KKM', 'KLM', 'KNM', 'KTM', 'MCG', 'MLP', 'PKM', 'RCC', 'TCM', 'TVM'}   # = the GO's government group
PRIVATE = {'DMM', 'GMC', 'KDM', 'MMH', 'SIM', 'SUC', 'AAM', 'AMC', 'AZC', 'BCM', 'EMC', 'JMC', 'KCM', 'MMC', 'MZM',
           'PMC', 'SMC', 'TRM'}
key = lambda s: re.sub(r'[^a-z]', '', (s or '').lower())
COURSES = {  # (printed code, printed name as letters) → approved course name
    ('AN', 'mdanaesthesia'): 'MD - Anaesthesiology', ('AT', 'mdanatomy'): 'MD/MS - Anatomy',
    ('BI', 'mdbiochemistry'): 'MD - Biochemistry', ('CM', 'mdcommunitymedicine'): 'MD - Social & Preventive Medicine / Community Medicine',
    ('VL', 'mddermatologyvenereologyleprosy'): 'MD - Dermatology', ('EM', 'mdemergencymedicine'): 'MD - Emergency Medicine',
    ('FM', 'mdfamilymedicine'): 'MD - Family Medicine', ('FO', 'mdforensicmedicine'): 'MD - Forensic Medicine',
    ('GE', 'mdgeriatrics'): 'MD - Geriatrics', ('GM', 'mdgeneralmedicine'): 'MD - General Medicine',
    ('MI', 'mdmicrobiology'): 'MD - Microbiology', ('NM', 'mdnuclearmedicine'): 'MD - Nuclear Medicine',
    ('PD', 'mdpaediatrics'): 'MD - Paediatrics', ('PT', 'mdpathology'): 'MD - Pathology',
    ('PH', 'mdpharmacology'): 'MD - Pharmacology', ('PM', 'mdphysicalmedicineandrehabilitation'): 'MD - Physical Medicine and Rehabilitation',
    ('PY', 'mdphysiology'): 'MD - Physiology', ('PS', 'mdpsychiatry'): 'MD - Psychiatry',
    ('RD', 'mdradiodiagnosis'): 'MD - Radio-Diagnosis', ('RT', 'mdradiotherapy'): 'MD - Radiotherapy / Radiation Oncology',
    ('TB', 'mdrespiratorymedicine'): 'MD - Respiratory Medicine',
    ('TM', 'mdtransfusionmedicine'): 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    ('GS', 'msgeneralsurgery'): 'MS - General Surgery', ('OB', 'msobstetricsgynaecology'): 'MS - Obstetrics and Gynaecology',
    ('OP', 'msophthalmology'): 'MS - Ophthalmology', ('OR', 'msorthopaedics'): 'MS - Orthopaedics',
    ('ET', 'msotorhinolaryngology'): 'MS - ENT (Otorhinolaryngology)',
    ('DP', 'diplomainclinicalpathology'): 'Diploma in Pathology'}
STATE_CATS = {'SM', 'SC', 'ST', 'EZ', 'BH', 'MU', 'LA', 'BX', 'KU', 'EW', 'PD', 'XS'}
MINORITY = {'AC': 'Private Quota - Minority', 'MM': 'Private Quota - Minority', 'NR': 'NRI Quota',
            'NC': 'NRI Quota - Minority', 'NM': 'NRI Quota - Minority'}
CAND_CATS = {'General', 'SC', 'ST', 'EZ', 'BH', 'MU', 'LA', 'BX', 'KU', 'EW'}
MARK = {'#': 'Provisionally allotted subject to the screening committee decision', '*': 'NRI provisionally allowed'}

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()

doc = fitz.open(PDF)
t0 = clean(doc[0].get_text())
# the published list (after complaints) prints no '(Provisional)' / '(Final)' tag → final (CEE notification
# 'First Phase Centralised Allotment Published', 02.11.2026)
m = re.search(r'ADMISSION TO PG MEDICAL COURSES (20\d\d) (\w+) Phase Allotment List(?: \((Provisional|Final)\))?', t0)
if not m:
    raise SystemExit('title line changed')
PHASES = {'First': 1, 'Second': 2, 'Third': 3}
if m.group(2) not in PHASES:
    raise SystemExit(f'unknown phase {m.group(2)!r}')
ROUND, STATUS = PHASES[m.group(2)], (m.group(3) or 'Final').lower()
dates = collections.Counter()
lines, appl_text = [], 0
for pg in doc:
    txt = pg.get_text()
    dates.update(re.findall(r'\b(\d\d-\d\d-20\d\d)\b', txt))
    appl_text += len(re.findall(r'(?m)^\s*\d{7}\s*$', txt))   # ApplNo cells: every line must be read from a table
    for t in pg.find_tables().tables:
        for r in t.extract():
            if len(r) != 8:
                raise SystemExit(f'p{pg.number + 1}: a table line has {len(r)} columns')
            r = [clean(x) for x in r]
            if r[0].isdigit():
                if not re.fullmatch(r'\d{7}', r[1]):
                    raise SystemExit(f'p{pg.number + 1}: ApplNo has an unexpected shape')
                r[1] = ''                          # application number: never kept
                lines.append(r)
            elif r not in HEAD:
                raise SystemExit(f'p{pg.number + 1}: unexpected table line / headings changed')
sn = sorted(int(r[0]) for r in lines)
if sn != list(range(1, len(sn) + 1)):
    raise SystemExit(f'Sl.No is not 1..{len(sn)} — lines missing or read twice')
if appl_text != len(lines):
    raise SystemExit(f'{appl_text} application numbers in the page text but {len(lines)} table lines read')

state_rank = None
if MERIT:
    br = json.load(open(MERIT))
    by_air = collections.defaultdict(set)
    for x in br['rows']:
        by_air[x['air']].add(x['state_rank'])
    state_rank = {a: next(iter(s)) for a, s in by_air.items() if len(s) == 1}
    merit_name = br.get('list_name')
    del br, by_air

approved = {c['course'] for c in json.load(open(SHEET))['courses']}
rows, unknown, fill = [], collections.Counter(), collections.Counter()
for r in lines:
    sno, _, rank, college, course, ccat, acat, opt = r
    w = f'Sl.No {sno}'
    if not (rank.isdigit() and opt.isdigit()):
        raise SystemExit(f'{w}: Rank / Option No. not numbers')
    cm = re.fullmatch(r'([A-Z]{3})- ?(.+)', college)
    km = re.fullmatch(r'([A-Z]{2})- ?(.+)', course)
    am = re.fullmatch(r'([A-Z]{2})([#*]?)', acat)
    if not cm or cm.group(1) not in GOVT | PRIVATE:
        unknown['college: ' + college] += 1; continue
    if not km or (km.group(1), key(km.group(2))) not in COURSES:
        unknown['course: ' + course] += 1; continue
    if not am or (am.group(1) not in STATE_CATS and am.group(1) not in MINORITY) or ccat not in CAND_CATS:
        unknown[f'category: {acat} / {ccat}'] += 1; continue
    code, cat, mark = cm.group(1), am.group(1), am.group(2)
    govt = code in GOVT
    if cat in MINORITY:
        if govt:
            raise SystemExit(f'{w}: {cat} seat at a government college')
        quota = MINORITY[cat]
    else:
        quota = 'Government Quota' if govt else 'Private Quota'
    if cat in ('SC', 'ST', 'EZ', 'BH', 'MU', 'LA', 'BX', 'KU', 'EW') and cat != ccat:
        raise SystemExit(f'{w}: {cat} seat to a {ccat} candidate')
    std = COURSES[(km.group(1), key(km.group(2)))]
    if std not in approved:
        raise SystemExit(f'{std!r} is not in specialty_sheet.json')
    air = int(rank)
    sr = state_rank.get(air) if state_rank is not None else None
    fill['state rank from merit list' if sr else 'state rank not found'] += 1
    rows.append({'sno': int(sno), 'rank': sr, 'rank_ai': air, 'quota_raw': 'Government college' if govt else
                 'Self-financing college', 'quota': quota, 'institute_raw': college, 'course_raw': course,
                 'course': std, 'section': 'diploma' if std.startswith('Diploma') else 'mdms',
                 'allotted_category': cat, 'allotted_category_raw': acat, 'candidate_category': ccat,
                 'remarks': MARK.get(mark, '')})
del lines
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
rows.sort(key=lambda x: x['sno'])
if [x['rank_ai'] for x in rows] != sorted(x['rank_ai'] for x in rows) or len({x['rank_ai'] for x in rows}) != len(rows):
    raise SystemExit('the list is not in strictly increasing Rank (AIR) order')
if state_rank is not None:
    srs = [x['rank'] for x in rows if x['rank']]
    if srs != sorted(srs):
        raise SystemExit('state ranks looked up by AIR are not in list order')

pub = re.fullmatch(r'(\d\d)-(\d\d)-(\d{4})', dates.most_common(1)[0][0]) if dates else None
C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'lines': len(rows), 'sl_no_1_to_n': True, 'appl_nos_in_page_text': appl_text, 'pages': len(doc),
          'rank_ai_strictly_increasing': True, 'by_section': C('section'), 'by_quota': C('quota'),
          'by_allotted_category': C('allotted_category'), 'by_course': C('course'),
          'marked': {MARK[k]: sum(1 for x in rows if x['remarks'] == MARK[k]) for k in MARK},
          'colleges': len({x['institute_raw'] for x in rows}),
          'rank_ai': {'source': "printed 'Rank' column (= NEET PG AIR)", 'filled': len(rows), 'of': len(rows)},
          'rank': {'source': f'state merit rank looked up by AIR in {os.path.basename(MERIT)} ({merit_name})' if MERIT
                   else 'not filled (no --merit)', 'filled': fill.get('state rank from merit list', 0), 'of': len(rows)},
          'ai_rank': [rows[0]['rank_ai'], rows[-1]['rank_ai']]}
out = {'authority_code': 'cee_kerala', 'round': f'Round {ROUND}', 'round_order': ROUND, 'status': STATUS,
       'title': m.group(0).replace('ADMISSION TO PG MEDICAL COURSES ', 'Admission to PG Medical Courses '),
       'published_on': f'{pub.group(3)}-{pub.group(2)}-{pub.group(1)}' if pub else None,
       'source_file_name': os.path.basename(PDF),
       'notes': f'CEE Kerala {m.group(2)} Phase = Round {ROUND}. rank_ai = printed Rank (NEET PG AIR); rank = Kerala '
                'state merit rank looked up by AIR in the final State Merit List. Quota derived from college type + '
                'allotted category (not printed). XS (ex-serviceman) is new in 2026 (2025 fallback SM).',
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print('lines', len(rows), '| appl nos in page text', appl_text, '| by section', checks['by_section'])
print('by quota', checks['by_quota'])
print('by allotted category', checks['by_allotted_category'])
print('marked', checks['marked'])
print('state rank fill', checks['rank'], '| AIR range', checks['ai_rank'], '| colleges', checks['colleges'],
      '|', out['status'], out['published_on'])
