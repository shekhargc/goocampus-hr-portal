"""Madhya Pradesh (DME MP) NEET-PG seat allotment result (provisional / final, any round) → rows for
POST /api/pg/results/ingest. Reads two official PDFs:
  allotment       — one line per candidate (S.NO, roll no, name, state common merit rank, NEET PG AI rank, scores,
                    candidate type, 3 eligibility columns, eligible category, then the allotment: course, institute
                    type, institute, subject, subject type, allotted category/class — or NOT ALLOTTED)
  opening_closing — per institute × course × subject × allotted category × MBBS-from-MP: opening / closing AI rank
                    and state rank + ALLOTTED COUNT (used only as a check: every group must match the lines read)
Roll numbers and names are never kept. NOT ALLOTTED lines are counted and skipped. Quota comes from the allotted
category prefix (INST/ NON_INST/ IN_ NRI) + institute type, category is the rest of the allotted category; both
use the 2025 MP cut-off spellings. College names are matched on the portal through the name memory.
`rank` = State Common Merit Rank (what My Allotments matches a doctor's home-state rank against); the NEET PG
All-India rank is kept next to it as `rank_ai` (the 2025 MP cut-offs hold All-India ranks).
Run with /usr/bin/python3 (PyMuPDF):
    madhya_pradesh.py <allotment.pdf> <opening_closing.pdf> <out.json>"""
import json, os, re, sys, collections
import fitz

ALLOT, OC, OUT = sys.argv[1:4]
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

HEAD = ['S. NO', 'NEET PG 2026 ROLL NUMBER', 'CANDIDATE NAME', 'STATE COMMON MERIT RANK', 'NEET PG 2026 AI RANK',
        'NEET PG 2026 SCORE (OUT OF 720)', 'FINAL SCORE (WEIGHTAGE MARKS + NEET PG SCORE)', 'CANDIDATE TYPE',
        'ELIGIBLE FOR INSERVICE (30% quota ) SEATS', 'ELIGIBLE FOR DNB SEATS', 'MBBS PASSED FROM MP STATE',
        'ELIGIBLE CATEGORY', 'ALLOTTED COURSE', 'ALLOTTED INSTITUTE TYPE', 'ALLOTTED INSTITUTE NAME',
        'ALLOTTED SUBJECT', 'ALLOTTED SUBJECT TYPE', 'ALLOTTED CATEGORY/CLASS']
OC_HEAD = ['INSTITUTE CODE', 'INSTITUTE NAME', 'INSTITUTE TYPE', 'COURSE', 'SUBJECT', 'SUBJECTTYPE',
           'OPENING NEET PG AI RANK', 'CLOSING NEET PG AI RANK', 'OPENING STATE COMMON MERIT RANK',
           'CLOSING STATE COMMON MERIT RANK', 'OPENING NEET PG SCORE', 'CLOSING NEET PG SCORE', 'ALLOTTED CATEGORY',
           'ALLOTTED COUNT', 'MBBS FROM MP/OTHER STATE']

# allotted category/class → (quota prefix, category as spelled in the 2025 MP cut-offs). Hand-checked; anything
# else stops the run. 2025 MP categories: UR/X/OP OBC/X/OP SC/X/OP ST/X/OP EWS/X/OP OBC/PH/OP SC/PH/OP UR/NRI/OP
# IN_UR/X/OP IN_OBC/X/OP IN_SC/X/OP IN_ST/X/OP IN_EWS/X/OP IN_UR/PH/OP (UR/PH/OP is the same pattern, new in 2026).
ACAT = {}
for c in ('UR', 'OBC', 'SC', 'ST', 'EWS'):
    for h in ('X', 'PH'):
        ACAT[f'INST/{c}/{h}/OP'] = ('INST', f'{c}/{h}/OP')
        ACAT[f'NON_INST/{c}/{h}/OP'] = ('NON_INST', f'{c}/{h}/OP')
        ACAT[f'IN_{c}/{h}/OP'] = ('IN', f'IN_{c}/{h}/OP')
ACAT['INST/UR/NRI/OP'] = ('NRI', 'UR/NRI/OP')
# (institute type, quota prefix) → 2025 MP cut-off quota (2025: Institutional Quota at Govt AND Private colleges,
# Private Quota = private non-institutional, *-Inservice = 30% in-service, NRI Quota = private NRI)
QUOTA = {('Govt', 'INST'): 'Institutional Quota', ('Govt', 'IN'): 'Government Quota-Inservice',
         ('Private', 'INST'): 'Institutional Quota', ('Private', 'NON_INST'): 'Private Quota',
         ('Private', 'IN'): 'Private Quota-Inservice', ('Private', 'NRI'): 'NRI Quota'}
QUOTA_RAW = {'INST': 'INST', 'NON_INST': 'NON_INST', 'IN': 'IN_', 'NRI': 'INST NRI'}
# (allotted course, subject) → (approved course name, section). MD/MS names are checked against the specialty sheet;
# Post-MBBS DNB / Diploma use the MP seat-matrix names (tools/seat_matrix/madhya_pradesh.py).
COURSES = {
    ('MD', 'ANAESTHESIOLOGY'): 'MD - Anaesthesiology', ('MD', 'BIOCHEMISTRY'): 'MD - Biochemistry',
    ('MD', 'COMMUNITY MEDICINE'): 'MD - Social & Preventive Medicine / Community Medicine',
    ('MD', 'DERMATOLOGY VENEREOLOGY AND LEPROSY'): 'MD - Dermatology',
    ('MD', 'EMERGENCY MEDICINE'): 'MD - Emergency Medicine',
    ('MD', 'FORENSIC MEDICINE AND TOXICOLOGY'): 'MD - Forensic Medicine',
    ('MD', 'GENERAL MEDICINE'): 'MD - General Medicine',
    ('MD', 'IMMUNO HAEMATOLOGY AND BLOOD TRANSFUSION'): 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    ('MD', 'MICROBIOLOGY'): 'MD - Microbiology', ('MD', 'PAEDIATRICS'): 'MD - Paediatrics',
    ('MD', 'PATHOLOGY'): 'MD - Pathology', ('MD', 'PHARMACOLOGY'): 'MD - Pharmacology',
    ('MD', 'PHYSIOLOGY'): 'MD - Physiology', ('MD', 'PSYCHIATRY'): 'MD - Psychiatry',
    ('MD', 'RADIATION ONCOLOGY'): 'MD - Radiotherapy / Radiation Oncology',
    ('MD', 'RADIODIAGNOSIS'): 'MD - Radio-Diagnosis', ('MD', 'RESPIRATORY MEDICINE'): 'MD - Respiratory Medicine',
    ('MD', 'ANATOMY'): 'MD/MS - Anatomy', ('MS', 'ANATOMY'): 'MD/MS - Anatomy',
    ('MS', 'GENERAL SURGERY'): 'MS - General Surgery',
    ('MS', 'OBSTETRICS AND GYNAECOLOGY'): 'MS - Obstetrics and Gynaecology',
    ('MS', 'OPHTHALMOLOGY'): 'MS - Ophthalmology', ('MS', 'ORTHOPAEDICS'): 'MS - Orthopaedics',
    ('MS', 'OTORHINOLARYNGOLOGY (ENT)'): 'MS - ENT (Otorhinolaryngology)',
    ('POST MBBS PG DIP', 'Paediatrics'): 'Diploma in Child Health / Paediatrics',
    ('POST MBBS PG DIP', 'OBGY'): 'Diploma in Obstetrics and Gynaecology',
    ('POST MBBS PG DIP', 'Anesthesiology'): 'Diploma in Anaesthesiology',
    ('POST MBBS PG DIP', 'Opthalmology'): 'Diploma in Ophthalmology',
    ('POST MBBS PG DIP', 'Family Medicine'): 'Diploma in Family Medicine',
    ('POST MBBS PG DIP', 'ENT'): 'Diploma in ENT',
    ('POST MBBS DNB', 'Paediatrics'): 'DNB - Paediatrics (Post-MBBS)',
    ('POST MBBS DNB', 'General Medicine'): 'DNB - General Medicine (Post-MBBS)'}
SECTION = {'MD': 'mdms', 'MS': 'mdms', 'POST MBBS PG DIP': 'diploma', 'POST MBBS DNB': 'dnb'}

clean = lambda s: re.sub(r'\s+', ' ', (s or '').replace('\n', ' ')).strip()


def num(s, what):
    if not re.fullmatch(r'\d+', s):
        raise SystemExit(f'{what} is not a number: {s!r}')
    return int(s)


def tables(pdf, head, width):
    """Data lines of every table of the given width; the column headings must be exactly as expected."""
    out = []
    for pg in fitz.open(pdf):
        for t in pg.find_tables().tables:
            for r in t.extract():
                if len(r) != width:
                    raise SystemExit(f'{os.path.basename(pdf)} p{pg.number + 1}: a table line has {len(r)} columns')
                r = [clean(x) for x in r]
                if r[0] == head[0]:
                    if r != head:
                        raise SystemExit(f'{os.path.basename(pdf)} p{pg.number + 1}: column headings changed: {r}')
                elif r[0].isdigit():
                    out.append(r)
    return out


# ── allotment list ──
lines = []
for r in tables(ALLOT, HEAD, 18):
    r[1] = r[2] = ''                       # roll number + name: never kept
    lines.append(r)
sn = sorted(int(r[0]) for r in lines)
if sn != list(range(1, len(sn) + 1)):
    raise SystemExit(f'serial numbers are not 1..{len(sn)} — lines missing or read twice')

approved = {c['course'] for c in json.load(open(SHEET))['courses']}
rows, unknown, not_allotted = [], collections.Counter(), 0
for r in lines:
    sno, _, _, smr, air, score, final, ctype, _, _, mp, ecat, course, itype, inst, subj, stype, acat = r
    smr, air = num(smr, f'S.NO {sno} state rank'), num(air, f'S.NO {sno} AI rank')
    if course == 'NOT ALLOTTED':
        if {itype, inst, subj, stype, acat} != {'NOT ALLOTTED'}:
            raise SystemExit(f'S.NO {sno}: NOT ALLOTTED course but allotment columns filled')
        not_allotted += 1
        continue
    if acat not in ACAT:
        unknown['category: ' + acat] += 1; continue
    pre, cat = ACAT[acat]
    if (itype, pre) not in QUOTA:
        unknown[f'quota: {itype} + {pre}'] += 1; continue
    if (course, subj) not in COURSES or course not in SECTION:
        unknown[f'course: {course} / {subj}'] += 1; continue
    std, section = COURSES[(course, subj)], SECTION[course]
    if section != 'dnb' and std not in approved:
        raise SystemExit(f'{std!r} is not in specialty_sheet.json')
    if section == 'mdms' and not (std.startswith(course + ' - ') or std.startswith('MD/MS - ')):
        raise SystemExit(f'S.NO {sno}: {course} {subj} mapped to {std}')
    if not inst:
        raise SystemExit(f'S.NO {sno}: no institute')
    rows.append({'sno': int(sno), 'rank': smr, 'rank_ai': air, 'quota_raw': f'{QUOTA_RAW[pre]} ({itype})',
                 'quota': QUOTA[(itype, pre)], 'institute_raw': inst, 'course_raw': f'{course} {subj}',
                 'course': std, 'section': section, 'allotted_category': cat, 'allotted_category_raw': acat,
                 # eligible category without the trailing gender letter (…/M, …/F)
                 'candidate_category': re.sub(r'/[MF]$', '', ecat), 'remarks': ctype,
                 '_k': (inst, course, subj, acat, mp), '_type': (itype, stype)})
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
if len(rows) + not_allotted != len(lines):
    raise SystemExit('allotted + not allotted ≠ lines')

# ── cross-check against the official opening / closing list ──
got = collections.defaultdict(list)
for x in rows:
    got[x['_k']].append(x)
oc, mism = {}, []
for r in tables(OC, OC_HEAD, 15):
    code, inst, itype, course, subj, stype, oai, cai, osr, csr, _, _, acat, n, mp = r
    k = (inst, course, subj, acat, mp)
    if k in oc:
        raise SystemExit(f'opening/closing repeats {k}')
    oc[k] = (num(n, 'ALLOTTED COUNT'), num(oai, 'opening AI'), num(cai, 'closing AI'), num(osr, 'opening state'),
             num(csr, 'closing state'), itype, stype)
for k in set(oc) | set(got):
    g = got.get(k, [])
    mine = (len(g), min((x['rank_ai'] for x in g), default=None), max((x['rank_ai'] for x in g), default=None),
            min((x['rank'] for x in g), default=None), max((x['rank'] for x in g), default=None),
            g[0]['_type'][0] if g else None, g[0]['_type'][1] if g else None)
    if oc.get(k) != mine:
        mism.append({'group': ' | '.join(k), 'official': oc.get(k), 'parsed': mine})
oc_total = sum(v[0] for v in oc.values())
if mism or oc_total != len(rows):
    raise SystemExit(f'opening/closing check failed (official total {oc_total}, parsed {len(rows)}): {mism[:20]}')
for x in rows:
    del x['_k'], x['_type']

rows.sort(key=lambda x: x['sno'])
C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
checks = {'lines': len(lines), 'sno_1_to_n': True, 'allotted': len(rows), 'not_allotted': not_allotted,
          'by_section': C('section'), 'by_quota': C('quota'), 'by_allotted_category': C('allotted_category'),
          'by_quota_raw': C('quota_raw'), 'by_course': C('course'),
          'opening_closing': {'groups': len(oc), 'groups_matched': len(oc) - len(mism),
                              'allotted_count_total': oc_total, 'mismatches': mism},
          'colleges': len({x['institute_raw'] for x in rows}),
          'state_rank': [min(x['rank'] for x in rows), max(x['rank'] for x in rows)],
          'ai_rank': [min(x['rank_ai'] for x in rows), max(x['rank_ai'] for x in rows)]}
json.dump({'rows': rows, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False)
print('lines', len(lines), '| allotted', len(rows), '| not allotted', not_allotted)
print('by section', checks['by_section'])
print('by quota', checks['by_quota'])
print('by allotted category', checks['by_allotted_category'])
print(f'opening/closing: {len(oc)} groups all match, ALLOTTED COUNT total {oc_total}')
print('colleges', checks['colleges'], '| state ranks', checks['state_rank'], '| AI ranks', checks['ai_rank'])
