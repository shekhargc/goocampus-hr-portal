"""Telangana NEET PG 2026 Phase-1 (Round 1) seat matrix — KNRUHS "MEDICAL PG DEGREE/DIPLOMA ADMISSIONS UNDER COMPETENT
AUTHORITY QUOTA FOR THE AY 2026-27", 13.11.2026, six PDFs (all with a text layer, read with `grids()`):

  minority non-service     (inbox 1691)  1 page   Deccan / Shadan / Dr. VRK Women's / Ayaan × GEN FEM GEN_PH FEM_PH
  minority service         (inbox 1692)  1 page   same layout
  non-minority non-service clinical      (1693)  24 course pages + "NET GROUP" summary page
  non-minority service clinical          (1694)  18 course pages + summary
  non-minority service non-clinical      (1695)   9 course pages + summary
  non-minority non-service non-clinical  (1696)   9 course pages + summary

Non-minority course pages: one page per course, one line per college (S.No, COLLEGE) × 37 category columns
(OC / BC A / BC B / BC C / BC D / BC E / SC 1 / SC 2 / SC 3 / ST, each _G (general) / _F (women), most with _PH_G /
_PH_F, plus BC POOL_G); a blank cell = 0. Only Competent Authority (convenor) seats — no management / NRI /
institutional seats, no AIQ (MCC's).

Stored as body "Telangana — State Counselling", authority `knruhs`, section `state`; college codes `TS-<STANDARD-NAME>`
(state_rankings.PREFIX). Quotas: non-service → State Quota, service → In-service Quota (left out of rankings);
minority colleges → State Quota (Muslim Minority) / In-service Quota (Muslim Minority). Bridge (2025 KNRUHS names,
exact): State Quota → 'Govt Quota - Non Service-Local', In-service → 'Govt Quota - Service-Local'. Categories are
stored in KNRUHS's 2025 wording (OC_G → OPEN-GEN, OC_PH_F → OPEN-FEM-PHO, BC A_G → BCA-GEN, SC 1_F → SC1-FEM,
BC POOL_G → BC-POOL; minority GEN → MIN-GEN-MSM …), category_code = the PDF column. With no same-category 2025 rank:
women's seat → the caste's GEN rank, PH → the non-PH rank, then OPEN-FEM / OPEN-GEN (BC-POOL: open to any BC
sub-group → OPEN-GEN).

Checks: titles (university, admissions line, the file's matrix title), the 37 column headings on every page, S.No
1…n on every page, every cell blank or a whole number, every number printed on a page sits in a parsed cell, every
college / course name known (stops on anything new), and each non-minority file's summary page: course × category =
the sum of that course's page (all 37 columns; a summary course with no page — MD Family Medicine — must be empty).
The two minority sheets print NO totals: every cell must hold a number (zeros are printed) and every printed number
must be read — nothing else to check them against.
Run with /usr/bin/python3 (PyMuPDF):
  telangana.py <min_ns.pdf> <min_s.pdf> <ns_clin.pdf> <s_clin.pdf> <s_nonclin.pdf> <ns_nonclin.pdf> <cutoffs2025.json> <out.json>"""
import sys, os, re, json, hashlib, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, grids, load_cuts, build, report

MIN_NS, MIN_S, NS_CLIN, S_CLIN, S_NONCLIN, NS_NONCLIN, CUTS, OUT = sys.argv[1:9]
UNIV = 'KALOJI NARAYANA RAO UNIVERSITY OF HEALTH SCIENCES, TELANGANA'
ADM = 'MEDICAL PG DEGREE/DIPLOMA ADMISSIONS UNDER COMPETENT AUTHORITY QUOTA FOR THE AY 2026-27'

COLLEGES = {  # PDF college → standard name (2025 KNRUHS cut-off name where the college is in it)
    'OSMANIA MEDICAL COLLEGE': 'Osmania Medical College, Hyderabad',
    'GANDHI MEDICAL COLLEGE': 'Gandhi Medical College, Secunderabad',
    'KAKATIYA MEDICAL COLLEGE': 'Kakatiya Medical College, Warangal',
    'GMC, NIZAMABAD': 'Government Medical College, Nizamabad',
    'GMC, SIDDIPET': 'Government Medical College, Siddipet',
    'GMC, NALGONDA': 'Government Medical College, Nalgonda',
    'GMC, SURYAPET': 'Government Medical College, Suryapet', 'GMC- SURYAPET': 'Government Medical College, Suryapet',
    'GMC, MAHABUBNAGAR': 'Government Medical College, Mahabubangar',          # 2025 spelling
    'RIMS, ADILABAD': 'Rajiv Gandhi Institute of Medical Sciences, Adilabad',
    'RIMS- ADILABAD': 'Rajiv Gandhi Institute of Medical Sciences, Adilabad',
    'ESIC': 'Employees State Insurance Coporation Medical College, Sanath Nagar, Hyderabad',
    'GMC, RAMAGUNDAM': 'Government Medical College, Ramagundam',              # = SIMS (Singareni IMS)
    'GMC- RAMAGUNDAM /SIMS': 'Government Medical College, Ramagundam',
    'GMC- RAMAGUNDAM/SIMS': 'Government Medical College, Ramagundam',
    'NIMS, HYDERABAD': "Nizam's Institute of Medical Sciences, Hyderabad",
    'APOLLO INSTITUTE OF MEDICAL SCIENCES': 'Apollo Institute of Medical Sciences and Research, Hyderabad',
    'BHASKAR MEDICAL COLLEGE': 'Bhaskar Medical College, Moinabad, Ranga Reddy, Hyderabad',
    'CHALMEDA ANAND RAO INSTITUTE OF MEDICAL SCIENCES': 'Chalmeda Anand Rao Insttitute of Medical Sciences, Karimnagar',
    'CMR INSTITUTE OF MEDICAL SCIENCES': 'CMR Institute of Medical Sciences, Kandalkoya, Medchal',
    'DR. PATNAM MAHENDER REDDY INSTITUTE OF MEDICAL SCIENCES': 'Dr. Patnam Mahender Reddy Institute of Medical Sciences, Chevella',
    'KAMINENI ACADEMY OF MEDICAL SCIENCES, HYDERABAD': 'Kamineni Academy of Medical Sciences & Research Center, Hyderabad',
    'KAMINENI INSTITUTE OF MEDICAL SCIENCES, NARKETPALLY': 'Kamineni Institute of Medical Sciences, Narketpally',
    'MAHAVIR INSTITUTE OF MEDICAL SCIENCES': 'Mahavir Institute of Medical Sciences, Vikarabad',
    'MAHESHWARA MEDICAL COLLEGE': 'Maheshwara Medical College, Patancheru, Medak',
    'MAMATA ACADEMY OF MEDICAL SCIENCES, BACHUPALLY': 'Mamata Academy of Medical Sciences, Bachupally',
    'MAMATA MEDICAL COLLEGE, KHAMMAM': 'Mamata Medical College, Khammam',
    'MEDICITI INSTITUTE OF MEDICAL SCIENCES': 'Mediciti Institute of Medical Sciences, Ghanpur',
    'MNR MEDICAL COLLEGE': 'MNR Medical College & Hospital, Sangareddy',
    'PRATHIMA INSTITUTE OF MEDICAL SCIENCES': 'Prathima Institute of Medical Sciences, Karimnagar',
    'RVM INSTITUTE OF MEDICAL SCIENCES': 'R.V.M. Institute of Medical Sciences and Research Centre, Siddipet',
    'SURABHI INSTITUTE OF MEDICAL SCIENCES': 'Surabhi Institute of Medical Sciences, Siddipet',
    'SVS MEDICAL COLLEGE': 'S V S Medical College, Mahabubnagar',
    'TRR INSTITUTE OF MEDICAL SCIENCES': 'TRR Institute of Medical Sciences, Patancheru',
    'TRR INSTITUTE OF MEDICAL SCINCES': 'TRR Institute of Medical Sciences, Patancheru',     # misprint (ENT page)
    # new in 2026 (no 2025 KNRUHS cut-off) — district government medical colleges
    'GMC- JANAGOAN': 'Government Medical College, Jangaon', 'GMC- JANGOAN': 'Government Medical College, Jangaon',
    'GMC- JAYASHANKAR BHUPALPALLY': 'Government Medical College, Jayashankar Bhupalpally',
    'GMC- KAMAREDDY': 'Government Medical College, Kamareddy',
    'GMC- KARIMNAGAR': 'Government Medical College, Karimnagar', 'GMC - KARIMANAGR': 'Government Medical College, Karimnagar',
    'GMC- KHAMMAM': 'Government Medical College, Khammam',
    'GMC- MAHABUBABAD': 'Government Medical College, Mahabubabad',
    'GMC- MANCHERIAL': 'Government Medical College, Mancherial',
    'GMC- NAGARKURNOOL': 'Government Medical College, Nagarkurnool',
    'GMC- NARSAMPET': 'Government Medical College, Narsampet',
    'GMC- NIRMAL': 'Government Medical College, Nirmal',
    'GMC- RAJANNA SIRCILLA': 'Government Medical College, Rajanna Sircilla',
    'GMC- SANGAREDDY': 'Government Medical College, Sangareddy',
    'GMC- WANAPARTHY': 'Government Medical College, Wanaparthy'}
MINORITY = {'DECCAN': 'Deccan College of Medical Sciences, Hyderabad',
            'SHADHAN': 'Shadan Institute of Medical Sciences, Peerancheru',
            'DR. VRK WOMENS': 'Dr. VRK Womens Medical College, Aziznagar',
            'AYAAN': 'Ayaan Institute of Medical Sciences, Kanaka Mamidi'}

C = {  # course key (see ckey) → (approved course name, section)
    'GENERALMEDICINE': ('MD - General Medicine', 'mdms'), 'PAEDIATRICS': ('MD - Paediatrics', 'mdms'),
    'ANAESTHESIA': ('MD - Anaesthesiology', 'mdms'), 'RESPIRATORYMEDICINE': ('MD - Respiratory Medicine', 'mdms'),
    'DVL': ('MD - Dermatology', 'mdms'), 'RADIODIAGNOSIS': ('MD - Radio-Diagnosis', 'mdms'),
    'PSYCHIATRY': ('MD - Psychiatry', 'mdms'), 'RADIOTHERAPY': ('MD - Radiotherapy / Radiation Oncology', 'mdms'),
    'HOSPITALADMINISTRATION': ('MD - Hospital Administration', 'mdms'),
    'TRANSFUSIONMEDICINE': ('MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'mdms'),
    'EMERGENCYMEDICINE': ('MD - Emergency Medicine', 'mdms'), 'GERIATRICMEDICINE': ('MD - Geriatrics', 'mdms'),
    'PALLIATIVEMEDICINE': ('MD - Palliative Medicine', 'mdms'), 'NUCLEARMEDICINE': ('MD - Nuclear Medicine', 'mdms'),
    'PHYSICALMEDICINEREHABILITATION': ('MD - Physical Medicine and Rehabilitation', 'mdms'),
    'TRAUMATOLOGYSURGERY': ('MS - Traumatology and Surgery', 'mdms'), 'FAMILYMEDICINE': ('MD - Family Medicine', 'mdms'),
    'GENERALSURGERY': ('MS - General Surgery', 'mdms'), 'ORTHOPAEDICS': ('MS - Orthopaedics', 'mdms'),
    'OPHTHALMOLOGY': ('MS - Ophthalmology', 'mdms'), 'ENT': ('MS - ENT (Otorhinolaryngology)', 'mdms'),
    'OBG': ('MS - Obstetrics and Gynaecology', 'mdms'),
    'DO': ('Diploma in Ophthalmology', 'diploma'),
    'DTCD': ('Diploma in Respiratory Medicine', 'diploma'),          # Tuberculosis & Chest Diseases (2025 KNRUHS name)
    'DMRD': ('Diploma in Radio Diagnosis', 'diploma'), 'DPH': ('Diploma in Public Health', 'diploma'),
    'ANATOMY': ('MD/MS - Anatomy', 'mdms'), 'PHYSIOLOGY': ('MD - Physiology', 'mdms'),
    'BIOCHEMISTRY': ('MD - Biochemistry', 'mdms'), 'PATHOLOGY': ('MD - Pathology', 'mdms'),
    'MICROBIOLOGY': ('MD - Microbiology', 'mdms'), 'PHARMACOLOGY': ('MD - Pharmacology', 'mdms'),
    'FORENSICMEDICINE': ('MD - Forensic Medicine', 'mdms'),
    'COMMUNITYMEDICINE': ('MD - Social & Preventive Medicine / Community Medicine', 'mdms')}
MIN_COURSES = {
    'MD (Gen.Med)': 'GENERALMEDICINE', 'MD (Paed)': 'PAEDIATRICS', 'MD (Anes)': 'ANAESTHESIA',
    'MD (T.B.)': 'RESPIRATORYMEDICINE', 'MD DVL': 'DVL', 'MD (R.D.)': 'RADIODIAGNOSIS', 'MD (Psy.)': 'PSYCHIATRY',
    'MD(RT) *': 'RADIOTHERAPY', 'MD (Emer.Med)': 'EMERGENCYMEDICINE', 'MD(Transfusion Medicine)': 'TRANSFUSIONMEDICINE',
    'MD (Hos.Adm)': 'HOSPITALADMINISTRATION', 'MD (Physical Medicine Rehabilitation)': 'PHYSICALMEDICINEREHABILITATION',
    'MD (Geriatric Medicine)': 'GERIATRICMEDICINE', 'MS (Gen.Surg)': 'GENERALSURGERY', 'MS (Ortho.)': 'ORTHOPAEDICS',
    'MS (Opthal)': 'OPHTHALMOLOGY', 'MS (ENT)': 'ENT', 'MS (OB&G)': 'OBG',
    'MD (Anatomy)': 'ANATOMY', 'MD (Physio.)': 'PHYSIOLOGY', 'MD (Biochem.)': 'BIOCHEMISTRY', 'MD (Path)': 'PATHOLOGY',
    'MD (Micro)': 'MICROBIOLOGY', 'MD (Micro.Bio)': 'MICROBIOLOGY', 'MD (Pharma)': 'PHARMACOLOGY',
    'MD (FM)': 'FORENSICMEDICINE', 'MD (SPM)': 'COMMUNITYMEDICINE'}

HEAD = ['OC_G', 'OC_F', 'OC_PH_G', 'OC_PH_F', 'BC A_G', 'BC A_F', 'BC A_PH_G', 'BC A_PH_F', 'BC B_G', 'BC B_F',
        'BC B_PH_G', 'BC B_PH_F', 'BC C_G', 'BC C_F', 'BC D_G', 'BC D_F', 'BC D_PH_G', 'BC D_PH_F', 'BC E_G', 'BC E_F',
        'BC E_PH_G', 'BC E_PH_F', 'BC POOL_G', 'SC 1_G', 'SC 1_F', 'SC 2_G', 'SC 2_F', 'SC 2_PH_G', 'SC 2_PH_F',
        'SC 3_G', 'SC 3_F', 'SC 3_PH_G', 'SC 3_PH_F', 'ST_G', 'ST_F', 'ST_PH_G', 'ST_PH_F']
MIN_HEAD = ['GEN', 'FEM', 'GEN_PH', 'FEM_PH']


def cat_of(code):
    """PDF column → 2025 KNRUHS-style category: OC_PH_F → OPEN-FEM-PHO, BC A_G → BCA-GEN, BC POOL_G → BC-POOL."""
    if code == 'BC POOL_G':
        return 'BC-POOL'
    m = re.fullmatch(r'(OC|BC [A-E]|SC [1-3]|ST)(_PH)?_([GF])', code)
    base = 'OPEN' if m.group(1) == 'OC' else m.group(1).replace(' ', '')
    return f"{base}-{'GEN' if m.group(3) == 'G' else 'FEM'}{'-PHO' if m.group(2) else ''}"


def min_cat(code):
    return {'GEN': 'MIN-GEN-MSM', 'FEM': 'MIN-FEM-MSM', 'GEN_PH': 'MIN-GEN-MSM-PHO', 'FEM_PH': 'MIN-FEM-MSM-PHO'}[code]


def ckey(s):
    s = clean(s).upper()
    s = re.sub(r'\(\s*(NON-?\s*)?SERVICE\s*\)', '', s)
    s = s.replace('DIPLOMA IN PUBLIC HEALTH (DPH)', 'DPH').replace('MICRO BIOLOGY', 'MICROBIOLOGY')
    s = re.sub(r'^(MD|MS)\s+', '', s.strip())
    return re.sub(r'[^A-Z0-9]', '', s).replace('MEDICINEANDREHABILITATION', 'MEDICINEREHABILITATION')


def course(s):
    k = ckey(s)
    if k not in C:
        raise SystemExit(f'unknown course {s!r}')
    return k


def val(s, where):
    s = clean(s)
    if s == '':
        return 0
    if not s.isdigit():
        raise SystemExit(f'not a number {s!r} at {where}')
    return int(s)


def numbers_read(page, table):
    """every number printed on the page must be one parsed cell (nothing outside the grid, nothing dropped)."""
    printed = collections.Counter(w[4] for w in page.get_text('words') if w[4].isdigit())
    cells = collections.Counter()
    for r in table:
        for c in r:
            for tok in clean(c).split():
                if tok.isdigit():
                    cells[tok] += 1
    for k in ('2026', '27'):          # "AY 2026-27" in the title
        cells.pop(k, None); printed.pop(k, None)
    return printed == cells


rows, checks, files = [], {}, {}


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def main_file(path, title, quota, label):
    """a non-minority file: course pages + the NET GROUP summary page."""
    doc = fitz.open(path)
    files[label] = sha(path)
    per = collections.defaultdict(collections.Counter)      # course key → column → seats
    for pn in range(len(doc) - 1):
        ts = grids(doc[pn])
        if len(ts) != 1:
            raise SystemExit(f'{label} p{pn + 1}: {len(ts)} tables')
        t = ts[0]
        tl = [clean(r[0]) for r in t[1:5]]
        if tl[0] != UNIV or tl[1] != ADM or tl[2].replace('- ', '-') not in (title, title.replace('DEGREE', 'DIPLOMA')):
            raise SystemExit(f'{label} p{pn + 1}: titles changed {tl}')
        k = course(tl[3])
        if k in per:
            raise SystemExit(f'{label}: course {k} on two pages')
        h = [clean(x) for x in t[5]]
        if h != ['S.NO', 'COLLEGE'] + HEAD:
            raise SystemExit(f'{label} p{pn + 1}: column headings changed {h}')
        if not numbers_read(doc[pn], t):
            raise SystemExit(f'{label} p{pn + 1}: a printed number is outside the parsed cells')
        cname, csec = C[k]
        sl = 0
        per[k]  # course page present (even if all blank)
        for r in t[6:]:
            if not any(clean(x) for x in r if x is not None):
                continue
            sl += 1
            m = re.fullmatch(r'(\d+) (.+)', clean(r[0]))
            if r[1] is None and m:      # last line of a page whose S.No / COLLEGE rule is not drawn: one merged cell
                r = [m.group(1), m.group(2)] + r[2:]
            if clean(r[0]) != str(sl):
                raise SystemExit(f'{label} p{pn + 1}: S.No out of sequence {r[:2]}')
            nm = clean(r[1])
            if nm not in COLLEGES:
                raise SystemExit(f'{label}: unknown college {nm!r}')
            for code, cell in zip(HEAD, r[2:]):
                n = val(cell, f'{label} p{pn + 1} {nm} {code}')
                per[k][code] += n
                if n:
                    rows.append({'college': COLLEGES[nm], 'course': cname, 'quota': quota, 'seats': n, 'section': csec,
                                 'category': cat_of(code), 'category_code': code.replace(' ', '')})
    # summary page
    t = grids(doc[-1])
    if len(t) != 1:
        raise SystemExit(f'{label} summary: {len(t)} tables')
    t = t[0]
    if not numbers_read(doc[-1], t):
        raise SystemExit(f'{label} summary: a printed number is outside the parsed cells')
    if [clean(x) for x in t[5]] != ['S.NO', 'COLLEGE'] + HEAD:
        raise SystemExit(f'{label} summary: column headings changed')
    seen = set()
    for r in t[6:]:
        if not clean(r[0]).isdigit():
            continue
        k = course(r[1])
        seen.add(k)
        got = [val(c, f'{label} summary {k}') for c in r[2:]]
        if k not in per:
            if any(got):
                raise SystemExit(f'{label} summary: {k} has seats but no course page')
            continue
        for code, n in zip(HEAD, got):
            checks[f'{label} | {C[k][0]} | {code}'] = (per[k][code], n)
    for k in per:
        if k not in seen:
            raise SystemExit(f'{label}: course {k} missing from the summary page')
    tot = sum(sum(v.values()) for v in per.values())
    print(f'{label}: {len(per)} courses, {tot} seats')
    return tot


def minority_file(path, title, quota, label):
    doc = fitz.open(path)
    files[label] = sha(path)
    if len(doc) != 1:
        raise SystemExit(f'{label}: {len(doc)} pages')
    t = grids(doc[0])[0]
    tl = [clean(r[0]) for r in t[1:4]]
    if tl != [UNIV, ADM, title]:
        raise SystemExit(f'{label}: titles changed {tl}')
    if not numbers_read(doc[0], t):
        raise SystemExit(f'{label}: a printed number is outside the parsed cells')
    cols, tot, sl_prev, heads = None, 0, 0, 0
    for r in t[4:]:
        c0 = clean(r[0])
        if c0 == 'S.NO':
            names = [clean(x) for x in r[2:]]
            cols = [names[i] for i in range(0, 16, 4)]
            if cols != list(MINORITY) or any(names[i] for i in range(16) if i % 4):
                raise SystemExit(f'{label}: college headings changed {names}')
            heads += 1
            continue
        if r[0] is None and r[1] is None:
            if [clean(x) for x in r[2:]] != MIN_HEAD * 4:
                raise SystemExit(f'{label}: category headings changed {r}')
            continue
        if c0 in ('CLINICAL GROUP: DEGREE', 'NON-CLINICAL GROUP: DEGREE', ''):
            continue
        if not c0.isdigit() or int(c0) <= sl_prev:
            raise SystemExit(f'{label}: S.No out of order {r[:2]}')
        sl_prev = int(c0)
        nm = clean(r[1])
        if nm not in MIN_COURSES:
            raise SystemExit(f'{label}: unknown course {nm!r}')
        cname, csec = C[MIN_COURSES[nm]]
        for i, cell in enumerate(r[2:]):
            if not clean(cell).isdigit():
                raise SystemExit(f'{label}: empty / non-number cell {cell!r} on {nm}')
            n = int(clean(cell))
            tot += n
            if n:
                code = MIN_HEAD[i % 4]
                rows.append({'college': MINORITY[cols[i // 4]], 'course': cname, 'quota': quota, 'seats': n,
                             'section': csec, 'category': min_cat(code), 'category_code': code})
    if heads != 2:
        raise SystemExit(f'{label}: expected 2 table blocks, got {heads}')
    print(f'{label}: {tot} seats (no printed totals)')
    return tot


totals = {
    'minority non-service': minority_file(MIN_NS, 'MINORITY - NON-SERVICE IN CLINICAL AND NON-CLINICAL SPECIALITIES',
                                          'State Quota (Muslim Minority)', 'minority non-service'),
    'minority service': minority_file(MIN_S, 'MINORITY - SERVICE IN CLINICAL AND NON-CLINICAL SPECIALITIES',
                                      'In-service Quota (Muslim Minority)', 'minority service'),
    'non-service clinical': main_file(NS_CLIN, 'NON-SERVICE CLINICAL DEGREE SEAT MATRIX', 'State Quota', 'non-service clinical'),
    'service clinical': main_file(S_CLIN, 'SERVICE CLINICAL DEGREE SEAT MATRIX', 'In-service Quota', 'service clinical'),
    'service non-clinical': main_file(S_NONCLIN, 'SERVICE NON-CLINICAL DEGREE SEAT MATRIX', 'In-service Quota', 'service non-clinical'),
    'non-service non-clinical': main_file(NS_NONCLIN, 'NON-SERVICE NON-CLINICAL DEGREE SEAT MATRIX', 'State Quota',
                                          'non-service non-clinical')}

FAMILY = {'State Quota': ('Govt Quota - Non Service-Local$',), 'In-service Quota': ('Govt Quota - Service-Local$',),
          'State Quota (Muslim Minority)': ('Govt Quota - Non Service-Local$',),
          'In-service Quota (Muslim Minority)': ('Govt Quota - Service-Local$',)}


def cat_match(x):
    c = x['category']
    if c == 'BC-POOL':
        return ('OPEN-GEN',)
    if c.startswith('MIN-'):
        return tuple(dict.fromkeys((c, c.replace('-PHO', ''), c.replace('FEM', 'GEN').replace('-PHO', ''))))
    base, sex = c.split('-')[0], c.split('-')[1]
    return tuple(dict.fromkeys((c, f'{base}-{sex}', f'{base}-GEN', f'OPEN-{sex}', 'OPEN-GEN')))


cuts = load_cuts(CUTS, 'Telangana')
out = build(rows, cuts, 'Telangana', 'TS', lambda q: FAMILY[q], cat_match)
for o, x in zip(out, rows):
    o['category_code'] = x['category_code']
json.dump({'rows': out, 'checks': checks, 'files_sha256': files, 'file_totals': totals}, open(OUT, 'w'),
          ensure_ascii=False, indent=0)
report(out, checks)
print('file totals', totals, '=', sum(totals.values()))
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
print('bridged with a different category:', sum(r['seats'] for r in out if r['has_cutoff'] and r['cutoff_category'] != r['category']))
