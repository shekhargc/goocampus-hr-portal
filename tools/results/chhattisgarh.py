"""Chhattisgarh (DME CG) NEET-PG (MD/MS) seat allotment result (provisional / final, any round) → rows for
POST /api/pg/results/ingest. Reads the official PDF: one table line per allotted seat — SN, Candidate Roll No,
Candidate Category, PH, Allotted institute Name, Allotted Program, Candidate Preference, Alloted Quota, Alloted
Category, Allotted Gender, Candidate Gender, All India NEET Rank, State Rank, NEET Score, Bonus Marks, Total Score,
Candidature Type. No names are printed; roll numbers are used only in memory (to check the printed ranks against the
NBEMS result / the loaded CG merit list) and dropped, candidate gender is dropped.
`rank` = printed State Rank, `rank_ai` = printed All India NEET Rank.
Quota: the 2025 CG cut-offs file their closing ranks by CANDIDATURE type (Government Quota-MBBS Passout / -Domicile /
-Non-Domicile / -Inservice), so `quota` comes from the Candidature Type column; the printed seat quota (State
Institutional / State Open Quota) is kept in `quota_raw` and the candidature type in `remarks`.
Category: Alloted Category in 2025 spelling (UR-NC → UR, UR-Female → UR-F; PH = Y adds -PwD).
Run with /usr/bin/python3 (PyMuPDF):
    chhattisgarh.py <allotment.pdf> <out.json> [--nbems neet2026.json] [--merit dme_cg_merit.json]
                    [--matrix cg_seat_matrix.json]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {}
for f in ('--nbems', '--merit', '--matrix'):
    if f in args:
        i = args.index(f); opt[f] = args[i + 1]; del args[i:i + 2]
if len(args) != 2:
    raise SystemExit(__doc__)
PDF, OUT = args
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

HEAD = ['SN', 'Candidate Roll No', 'Candidate Category', 'PH', 'Allotted institute Name', 'Allotted Program',
        'Candidate Preference', 'Alloted Quota', 'Alloted Category', 'Allotted Gender', 'Candidate Gender',
        'All India NEET Rank', 'State Rank', 'NEET Score', 'Bonus Marks',
        'Total Score (NEET Score + Bonus Marks)', 'Candidature Type']
CANDIDATURE = {  # Candidature Type → 2025 cut-off quota
    'MBBS Passout from NMC- recognised Medical College of Chhattisgarh': 'Government Quota-MBBS Passout',
    'Domicile of CG but MBBS Pass out other than NMC-recognised Medical College of Chhattisgarh': 'Government Quota-Domicile',
    'NON CG Domicile and MBBS Pass out other than NMC- recognised Medical College of Chhattisgarh': 'Government Quota-Non-Domicile',
    'Inservice Candidate from Chhattisgarh': 'Government Quota-Inservice'}
SEAT_QUOTA = {'State Institutional Quota', 'State Open Quota'}
CATEGORY = {f'{c}-{g}': (c + ('-F' if g == 'Female' else ''), 'F' if g == 'Female' else 'B')
            for c in ('UR', 'OBC', 'SC', 'ST', 'EWS') for g in ('NC', 'Female')}
CAND_CAT = {'GN', 'OBC', 'SC', 'ST', 'EWS'}
COURSES = {  # printed program → approved course name (pg_admin/data/specialty_sheet.json)
    'M.D. (ANAESTHESIOLOGY)': 'MD - Anaesthesiology', 'M.D. (ANATOMY)': 'MD/MS - Anatomy',
    'M.D. (BIOCHEMISTRY)': 'MD - Biochemistry',
    'M.D. (DERM.,VENE. and LEPROSY)/ (DERMATOLOGY)/(SKIN and VENEREAL DISEASES)/(VENEREOLO GY)': 'MD - Dermatology',
    'MD (Emergency Medicine)': 'MD - Emergency Medicine', 'M.D. (FORENSIC MEDICINE)': 'MD - Forensic Medicine',
    'M.D. (GENERAL MEDICINE)': 'MD - General Medicine', 'M.D. (MICROBIOLOGY)': 'MD - Microbiology',
    'M.D. (PAEDIATRICS)': 'MD - Paediatrics', 'M.D. (PATHOLOGY)': 'MD - Pathology',
    'M.D. (PHARMACOLOGY)': 'MD - Pharmacology', 'M.D. (PHYSIOLOGY)': 'MD - Physiology',
    'M.D. (PMR)': 'MD - Physical Medicine and Rehabilitation',
    'M.D. (PREVENTIVE and SOCIAL MEDICINE)/ COMMUNITY MEDICINE': 'MD - Social & Preventive Medicine / Community Medicine',
    'M.D. (PSYCHIATRY)': 'MD - Psychiatry', 'M.D. (RADIO- DIAGNOSIS)': 'MD - Radio-Diagnosis',
    'M.D. (Radiotherapy/ Radiation Oncology)': 'MD - Radiotherapy / Radiation Oncology',
    'M.D. (Tuberculosis and Respiratory diseases)/Pulmonary Medicine /M.D. (Respiratory Medicine)': 'MD - Respiratory Medicine',
    'M.S. (GENERAL SURGERY)': 'MS - General Surgery',
    'M.D. (Obst. and Gynae)/MS (Obstetrics and Gynaecology)': 'MS - Obstetrics and Gynaecology',
    'M.S. (OPHTHALMOLOGY)': 'MS - Ophthalmology', 'M.S. (ORTHOPAEDICS)': 'MS - Orthopaedics',
    'M.S. (E.N.T.)': 'MS - ENT (Otorhinolaryngology)'}
# printed institute → seat-matrix college name (only for the optional --matrix check; institute_raw stays as printed)
MATRIX_NAME = {
    'PT.JAWAHAR LAL NEHRU MEMORIAL MEDICAL COLLEGE, RAIPUR': 'Pt. Jawahar Lal Nehru Memorial Medical College, Raipur',
    'CHHATTISGARH INSTITUTE OF MEDICAL SCIENCES, BILASPUR': 'Chhattisgarh Institute of Medical Sciences, Bilaspur',
    'LATE BALIRAM KASHYAP SMRITI. MEDICAL COLLEGE, JAGDALPUR': 'Late Shri Baliram Kashyap Memorial Govt. Medical College, Jagdalpur',
    'LATE SHRI LAKHIRAM AGRAWAL MEMORIAL MEDICAL COLLEGE, RAIGARH': 'Late Shri Lakhi Ram Agrawal Memorial Govt. Medical College, Raigarh',
    'BHARAT RATNA LATE SHRI ATAL BIHARI VAJPAYEE MEMORIAL MEDICAL COLLEGE, RAJNANDGAON': 'Government Medical College, (Bharat Ratna Shri Atal Bihari Vajpayee Memorial Medical College), Rajnandgaon',
    'RAJMATA SMT. DEVENDRA KUMARI SINGHDEO GOVERNMENT MEDICAL COLLEGE , AMBIKAPUR': 'Rajmata Shrimati Devendra Kumari Singhdeo Government Medical College, Ambikapur',
    'Late Bisahu Das Mahant Memorial Medical College, Korba': 'Government Medical College, Korba',
    'RAIPUR INSTITUTE OF MEDICAL SCIENCES,RAIPUR': 'Raipur Institute of Medical Sciences, Raipur',
    'SHRI SHANKARACHARYA INSTITUTE OF MEDICAL SCIENCE BHILAI': 'Shri Shankaracharya Institute of Medical Sciences, Bhilai',
    'Shri Balaji Institute Of Medical Science,Raipur': 'Shri Balaji Institute of Medical Science, Raipur'}

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()
ROLL = re.compile(r'\d{11}')

doc = fitz.open(PDF)
t0 = clean(doc[0].get_text())
m = re.search(r'Chhattisgarh NEET PG \(MD/MS\) (20\d\d) Round-(\d+) (Provisional|Final) Allotment List', t0)
if not m:
    raise SystemExit('title line changed')
YEAR, ROUND, STATUS = m.group(1), int(m.group(2)), m.group(3).lower()
TITLE = m.group(0)
pdate = re.match(r"D:(\d{4})(\d\d)(\d\d)", doc.metadata.get('creationDate') or '')

lines, rolls_text = [], 0
for pg in doc:
    rolls_text += len(set(ROLL.findall(pg.get_text())))   # one roll per line: every line must be read from a table
    for t in pg.find_tables().tables:
        for r in t.extract():
            if len(r) != 17:
                raise SystemExit(f'p{pg.number + 1}: a table line has {len(r)} columns')
            r = [clean(x) for x in r]
            if r[0] == 'SN':
                if r != HEAD:
                    raise SystemExit(f'p{pg.number + 1}: column headings changed: {r}')
            elif r[0].isdigit():
                lines.append(r)
            elif r[0] != TITLE or any(r[1:]):
                raise SystemExit(f'p{pg.number + 1}: unexpected table line')
sn = sorted(int(r[0]) for r in lines)
if sn != list(range(1, len(sn) + 1)):
    raise SystemExit(f'SN is not 1..{len(sn)} — lines missing or read twice')
if rolls_text != len(lines):
    raise SystemExit(f'{rolls_text} roll numbers in the page text but {len(lines)} table lines read')

nb = mr = None
if '--nbems' in opt:
    nb = {x['roll']: x['air'] for x in json.load(open(opt['--nbems']))}
if '--merit' in opt:
    mr = {x['roll']: (x['state_rank'], x['air']) for x in json.load(open(opt['--merit']))['rows']}
ver = collections.Counter()

approved = {c['course'] for c in json.load(open(SHEET))['courses']}
rows, unknown = [], collections.Counter()
for r in lines:
    sno, roll, ccat, ph, inst, prog, _pref, squota, acat, agender, _cgender, air, srank, _s, _b, _t, ctype = r
    w = f'SN {sno}'
    if not ROLL.fullmatch(roll):
        raise SystemExit(f'{w}: roll number has an unexpected shape')
    if not (air.isdigit() and srank.isdigit()):
        raise SystemExit(f'{w}: ranks not numbers')
    air, srank = int(air), int(srank)
    # ranks checked against the NBEMS result / loaded merit list by roll number (in memory only)
    if nb is not None:
        ver['nbems ' + ('match' if nb.get(roll) == air else 'not found' if roll not in nb else 'MISMATCH')] += 1
    if mr is not None:
        ver['merit ' + ('match' if mr.get(roll) == (srank, air) else 'not found' if roll not in mr else 'MISMATCH')] += 1
    roll = None
    if squota not in SEAT_QUOTA:
        unknown['quota: ' + squota] += 1; continue
    if ctype not in CANDIDATURE:
        unknown['candidature: ' + ctype] += 1; continue
    if acat not in CATEGORY or ph not in ('N', 'Y') or ccat not in CAND_CAT:
        unknown[f'category: {acat} / PH {ph} / {ccat}'] += 1; continue
    cat, g = CATEGORY[acat]
    if agender != g:
        raise SystemExit(f'{w}: allotted category {acat} with allotted gender {agender}')
    base = cat.split('-')[0]
    if base != 'UR' and base != {'GN': 'UR'}.get(ccat, ccat):
        raise SystemExit(f'{w}: {base} seat to a {ccat} candidate')
    if prog not in COURSES:
        unknown['course: ' + prog] += 1; continue
    std = COURSES[prog]
    if std not in approved:
        raise SystemExit(f'{std!r} is not in specialty_sheet.json')
    if not inst:
        raise SystemExit(f'{w}: no institute')
    rows.append({'sno': int(sno), 'rank': srank, 'rank_ai': air, 'quota_raw': squota, 'quota': CANDIDATURE[ctype],
                 'institute_raw': inst, 'course_raw': prog, 'course': std, 'section': 'mdms',
                 'allotted_category': cat + ('-PwD' if ph == 'Y' else ''), 'allotted_category_raw': acat + (' PH' if ph == 'Y' else ''),
                 'candidate_category': ccat, 'remarks': ctype})
del lines, nb, mr
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
if any(k.endswith('MISMATCH') for k in ver):
    raise SystemExit(f'printed ranks disagree with the reference files: {dict(ver)}')

matrix = None
if '--matrix' in opt:
    mx = collections.Counter()
    for x in json.load(open(opt['--matrix']))['rows']:
        if not x['quota'].startswith('NRI'):
            mx[(x['college_name'], x['course_name'])] += x['seats']
    got = collections.Counter((MATRIX_NAME[x['institute_raw']], x['course']) for x in rows)
    over = {' | '.join(k): (n, mx.get(k, 0)) for k, n in got.items() if n > mx.get(k, 0)}
    if over:
        raise SystemExit(f'more seats allotted than the seat matrix holds (allotted, matrix): {over}')
    matrix = {'groups': len(got), 'all_within_matrix': True, 'allotted': len(rows),
              'state_seats_in_matrix': sum(mx.values())}

rows.sort(key=lambda x: x['sno'])
C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'lines': len(rows), 'sn_1_to_n': True, 'rolls_in_page_text': rolls_text, 'pages': len(doc),
          'by_section': C('section'), 'by_quota': C('quota'), 'by_quota_raw': C('quota_raw'),
          'by_allotted_category': C('allotted_category'), 'by_course': C('course'),
          'colleges': len({x['institute_raw'] for x in rows}),
          'rank_ai': {'source': "printed 'All India NEET Rank' column", 'filled': len(rows), 'of': len(rows),
                      'verified_by_roll': dict(ver)},
          'seat_matrix': matrix,
          'state_rank': [min(x['rank'] for x in rows), max(x['rank'] for x in rows)],
          'ai_rank': [min(x['rank_ai'] for x in rows), max(x['rank_ai'] for x in rows)]}
out = {'authority_code': 'dme_cg', 'round': f'Round {ROUND}', 'round_order': ROUND, 'status': STATUS, 'title': TITLE,
       'published_on': f'{pdate.group(1)}-{pdate.group(2)}-{pdate.group(3)}' if pdate else None,
       'source_file_name': os.path.basename(PDF),
       'notes': 'DME Chhattisgarh. quota = 2025 cut-off spelling from the Candidature Type column (2025 closing ranks '
                'are filed by candidature); printed seat quota in quota_raw, candidature type in remarks. rank = '
                'State Rank, rank_ai = printed All India NEET Rank. published_on = PDF creation date (no date printed).',
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print('lines', len(rows), '| roll numbers in page text', rolls_text, '| by section', checks['by_section'])
print('by quota', checks['by_quota'])
print('by quota_raw', checks['by_quota_raw'])
print('by allotted category', checks['by_allotted_category'])
print('ranks verified by roll', dict(ver), '| seat matrix', matrix)
print('colleges', checks['colleges'], '| state ranks', checks['state_rank'], '| AI ranks', checks['ai_rank'],
      '|', out['status'], out['published_on'])
