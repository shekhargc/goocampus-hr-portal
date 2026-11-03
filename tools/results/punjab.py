"""Punjab (BFUHS) PG Medical provisional selection list (NEET PG 2026, any round) → rows for POST /api/pg/results/ingest.
The PDF is one table, 10 columns per allotted candidate: M No, Regn No., NEET PG Rollno, NAME, Category, University
from where passed MBBS, Allotted College, Allotted Branch, Allotted Quota, Allotted Category. No title or date is
printed (published_on = the PDF creation date). PERSONAL DATA: Regn No, name and university are never read into the
output; the roll number is held in memory only, to look the ranks up, and dropped.

Ranks: `rank` = M No (the BFUHS state merit number; checked against the loaded Round 1 merit list — the roll there must
carry the same merit number), `rank_ai` = NEET PG All India Rank from that merit list by roll (NBEMS 2026 by roll as a
fallback). NRI lines print no M No: `rank` is empty and the NRI merit-list position goes in `remarks`.

Quota: the 2025 Punjab cut-offs file private colleges under college-specific quotas, so the printed quota is mapped per
college family (DMC = Dayanand + Gian Sagar, as in 2025; CMC; SGRD; Adesh). CMC's "A" quota and SGRD's ultrasonography
"Sikh Minority Management Seats" have no 2025 equivalent and are kept as new quotas (no comparison) — never guessed.
Printed quota → `quota_raw`. Category: 2025 spellings (General Category → General, Backward Classes → BC, Scheduled
Caste → SC, EWS (IP) → EWS-IP, Christian → Minority; IP and NRI unchanged); candidate category → `candidate_category`.
Courses: MD/MS → approved names (checked against specialty_sheet.json); Post-MBBS DNB → `DNB - … (Post-MBBS)`, section
dnb; Post-MBBS diplomas, DCH / DA / Sports Medicine diploma and the Ultrasonography certificate batches → section diploma.
Run with /usr/bin/python3 (PyMuPDF):
    punjab.py <selection.pdf> <out.json> --merit bfuhs_r1_main.json [--nri bfuhs_r1_nri.json] [--nbems neet2026.json]
              [--round 1] [--status provisional|final]"""
import json, os, re, sys, collections
import fitz

args = sys.argv[1:]
opt = {'--round': '1', '--status': 'provisional'}
for f in ('--merit', '--nri', '--nbems', '--round', '--status'):
    if f in args:
        i = args.index(f); opt[f] = args[i + 1]; del args[i:i + 2]
if len(args) != 2 or '--merit' not in opt:
    raise SystemExit(__doc__)
PDF, OUT = args
ROUND, STATUS = int(opt['--round']), opt['--status']
if STATUS not in ('provisional', 'final'):
    raise SystemExit('--status must be provisional or final')
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')

HEAD = ['M No', 'Regn No.', 'NEET PG Rollno', 'NAME', 'Category', 'University from where passed MBBS',
        'Allotted College', 'Allotted Branch', 'Allotted Quota', 'Allotted Category']
CATEGORY = {'IP': 'IP', 'General Category': 'General', 'Backward Classes': 'BC', 'Scheduled Caste': 'SC',
            'EWS (IP)': 'EWS-IP', 'Christian': 'Minority', 'NRI': 'NRI',
            'Persons with Disability': 'PWD'}                    # revised R1 list (03.11.2026); 2025 spelling PWD
CAND_CAT = {'General', 'BC', 'EWS', 'SC', 'PWD'}


def family(college):
    c = college.lower()
    for key, fam in (('dayanand', 'DMC'), ('gian sagar', 'DMC'), ('christian medical', 'CMC'),
                     ('guru ram das', 'SGRD'), ('adesh', 'Adesh')):
        if key in c:
            return fam
    return ''


QUOTA = {  # (college family, printed quota) → 2025 cut-off quota
    ('', 'Government Quota'): 'Government Quota', ('', 'State Quota (50%)'): 'Government Quota',
    ('DMC', 'Government Quota'): 'DMC Government Quota', ('DMC', 'Government Quota (IP)'): 'DMC Government Quota',
    ('DMC', 'Management Quota'): 'DMC Management Quota',          # NRI category → DMC NRI Quota (below)
    ('CMC', 'Minority Quota'): 'CMC Minority Quota', ('CMC', 'NRI Quota'): 'CMC NRI Quota',
    ('CMC', 'A'): 'CMC Quota A',                                   # new in 2026 — no 2025 equivalent
    ('CMC', 'B'): 'CMC Quota B', ('CMC', 'C'): 'CMC Quota C',      # revised R1 list (03.11.2026) — also new
    ('SGRD', 'General Quota as per Punjab Govt. Notification'): 'SGRD General Quota',
    ('SGRD', 'Sikh Minority Seats'): 'SGRD Sikh Minority Quota',
    ('SGRD', 'Sikh Minority Management Seats'): 'SGRD Sikh Minority Management Quota',   # new (ultrasonography)
    ('Adesh', 'General Merit (50%)'): 'Adesh General Merit Quota',
    ('Adesh', 'Open Merit (All India Basis)'): 'Adesh Open Merit Quota (All India basis)'}

MDMS = {  # printed branch after "MD/MS_" (spaces removed, lower case) → approved course name
    'radio-diagnosis': 'MD - Radio-Diagnosis', 'generalmedicine': 'MD - General Medicine',
    'dermatologyvenerology&leprosy': 'MD - Dermatology', 'paediatrics': 'MD - Paediatrics',
    'psychiatry': 'MD - Psychiatry', 'obst.&gynae': 'MS - Obstetrics and Gynaecology',
    'opthalmology': 'MS - Ophthalmology', 'generalsurgery': 'MS - General Surgery',
    'tuberculosis&respiratorymedicine': 'MD - Respiratory Medicine', 'orthopaedics': 'MS - Orthopaedics',
    'anaesthesia': 'MD - Anaesthesiology', 'ent': 'MS - ENT (Otorhinolaryngology)',
    'otorhinolaryngology(ent)': 'MS - ENT (Otorhinolaryngology)',
    'radiotherapy': 'MD - Radiotherapy / Radiation Oncology', 'radiationoncology': 'MD - Radiotherapy / Radiation Oncology',
    'emergencymedicine': 'MD - Emergency Medicine', 'pathology': 'MD - Pathology', 'familymedicine': 'MD - Family Medicine',
    'immunohaematology&bloodtransfusion': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'preventive&socialmedicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'communitymedicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'forensicmedicine': 'MD - Forensic Medicine', 'microbiology': 'MD - Microbiology', 'biochemistry': 'MD - Biochemistry',
    'pharmacology': 'MD - Pharmacology', 'physiology': 'MD - Physiology', 'anatomy': 'MD/MS - Anatomy'}
MDMS_DIPLOMA = {'dch': 'Diploma in Child Health / Paediatrics', 'da': 'Diploma in Anaesthesiology',
                'postgraduationdiplomainsportsmedicine': 'Diploma in Sports Medicine'}
DNB = {'generalmedicine': 'General Medicine', 'psychiatry': 'Psychiatry', 'obst.&gynae': 'Obstetrics and Gynaecology',
       'orthopaedics': 'Orthopaedics', 'respiratorymedicine': 'Respiratory Medicine', 'paediatrics': 'Paediatrics',
       'ent': 'ENT (Otorhinolaryngology)', 'anaesthesia': 'Anaesthesiology', 'generalsurgery': 'General Surgery',
       'opthalmology': 'Ophthalmology', 'familymedicine': 'Family Medicine'}
DIPLOMA = {'tuberculosisandchestdisease': 'Diploma in Respiratory Medicine',
           'paediatrics': 'Diploma in Child Health / Paediatrics', 'anaesthesiology': 'Diploma in Anaesthesiology',
           'obst.&gynae': 'Diploma in Obstetrics and Gynaecology', 'radio-diagnosis': 'Diploma in Radio Diagnosis'}


def clean(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def course_of(raw):
    k = re.sub(r'\s+', '', raw).lower()
    if k.startswith('md/ms_'):
        b = k[6:]
        if b in MDMS:
            return MDMS[b], 'mdms'
        if b in MDMS_DIPLOMA:
            return MDMS_DIPLOMA[b], 'diploma'
    elif k.startswith('post_mbbs_dnb_') and k[14:] in DNB:
        return f'DNB - {DNB[k[14:]]} (Post-MBBS)', 'dnb'
    elif k.startswith('post_mbbs_diploma_') and k[18:] in DIPLOMA:
        return DIPLOMA[k[18:]], 'diploma'
    elif k in ('ultrasonography_batch1', 'ultrasonography_batch2'):
        return 'Ultrasonography-Batch' + k[-1], 'diploma'
    return None, None


approved = {c['course'] for c in json.load(open(SHEET))['courses']}
merit = {str(x['roll']): x for x in json.load(open(opt['--merit']))['rows']}
nri = {str(x['roll']): x for x in json.load(open(opt['--nri']))['rows']} if '--nri' in opt else {}
nbems = {}
if '--nbems' in opt:
    nbems = {str(x['roll']): x.get('air') for x in json.load(open(opt['--nbems']))}

doc = fitz.open(PDF)
rows, unknown, ver = [], collections.Counter(), collections.Counter()
heads = 0
for pg in doc:
    for tb in pg.find_tables().tables:
        for r in tb.extract():
            c = [clean(v) for v in r]
            if len(c) != 10:
                raise SystemExit(f'expected 10 columns, got {len(c)}')
            if c[0] == 'M No' or c[0].startswith('M No'):
                if c[:4] != HEAD[:4] and not c[0].startswith('M No Regn'):
                    raise SystemExit(f'column headings changed: {c}')
                heads += 1
                continue
            mno, roll, ccat, college, branch, quota_raw, acat_raw = c[0], re.sub(r'\D', '', c[2]), c[4], c[6], c[7], c[8], c[9]
            # c[1] Regn No, c[3] NAME, c[5] University — never read into the output
            if mno and not mno.isdigit():
                raise SystemExit(f'unexpected M No {mno!r}')
            course, section = course_of(branch)
            if not course:
                unknown['branch: ' + branch] += 1; continue
            if section == 'mdms' and course not in approved:
                unknown['not an approved course: ' + course] += 1
            fam = family(college)
            q = QUOTA.get((fam, quota_raw))
            if fam == 'DMC' and quota_raw == 'Management Quota' and acat_raw == 'NRI':
                q = 'DMC NRI Quota'
            if not q:
                unknown[f'quota: {fam or "-"} | {quota_raw}'] += 1; continue
            if acat_raw not in CATEGORY:
                unknown['allotted category: ' + acat_raw] += 1; continue
            if ccat not in CAND_CAT:
                unknown['candidate category: ' + ccat] += 1
            m, nri_no = merit.get(roll), ''
            if mno:
                rank = int(mno)
                if not m:
                    ver['MISMATCH roll not in merit list'] += 1
                elif int(m['state_rank']) != rank:
                    ver['MISMATCH merit number differs'] += 1
                else:
                    ver['merit number matches merit list'] += 1
                ai = m.get('air') if m else None
            else:
                n = nri.get(roll)
                rank = None          # the NRI list's own position is not a state merit rank → kept in remarks
                nri_no = f"NRI merit no. {n['state_rank']}" if n and n.get('state_rank') else 'NRI (no merit number)'
                ver['NRI line (no M No)'] += 1
                ai = (n or {}).get('air') or (m or {}).get('air')
            if roll in nbems and nbems[roll]:
                if ai and int(ai) != int(nbems[roll]):
                    ver['MISMATCH AIR vs NBEMS'] += 1
                else:
                    ver['AIR matches NBEMS by roll'] += 1
                ai = ai or nbems[roll]
            if not ai:
                ver['no AIR found'] += 1
            rows.append({'sno': len(rows) + 1, 'rank': rank, 'rank_ai': int(ai) if ai else None,
                         'quota_raw': quota_raw, 'quota': q, 'institute_raw': college, 'course_raw': branch,
                         'course': course, 'section': section, 'allotted_category': CATEGORY[acat_raw],
                         'allotted_category_raw': acat_raw, 'candidate_category': ccat, 'remarks': nri_no})
del merit, nri, nbems
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
if any(k.startswith('MISMATCH') for k in ver):
    raise SystemExit(f'ranks disagree with the reference files: {dict(ver)}')
if heads != len(doc):
    raise SystemExit(f'expected one heading row per page: {heads} headings, {len(doc)} pages')

meta = doc.metadata.get('creationDate') or ''
pdate = re.match(r'D:(20\d\d)(\d\d)(\d\d)', meta)
C = lambda f: dict(collections.Counter(x[f] for x in rows).most_common())
ranked = [x['rank'] for x in rows if x['rank']]
checks = {'lines': len(rows), 'pages': len(doc), 'heading_rows': heads, 'by_section': C('section'),
          'by_quota': C('quota'), 'by_quota_raw': C('quota_raw'), 'by_allotted_category': C('allotted_category'),
          'by_course': C('course'), 'colleges': len({x['institute_raw'] for x in rows}),
          'rank_checks': dict(ver), 'merit_numbers_unique': len(ranked) == len(set(ranked)),
          'state_rank': [min(ranked), max(ranked)],
          'ai_rank': [min(x['rank_ai'] for x in rows if x['rank_ai']), max(x['rank_ai'] for x in rows if x['rank_ai'])]}
if not checks['merit_numbers_unique']:
    raise SystemExit('a merit number appears twice')
out = {'authority_code': 'bfuhs', 'round': f'Round {ROUND}', 'round_order': ROUND, 'status': STATUS,
       'title': f'Punjab (BFUHS) PG Medical 2026 — {STATUS.title()} Selection List, Round {ROUND}',
       'published_on': f'{pdate.group(1)}-{pdate.group(2)}-{pdate.group(3)}' if pdate else None,
       'source_file_name': os.path.basename(PDF),
       'notes': 'BFUHS Faridkot. rank = M No (state merit number, checked against the Round 1 merit list); rank_ai = '
                'NEET PG AIR by roll from the merit list / NBEMS 2026. Private-college quotas mapped to the 2025 '
                'college-specific spellings (DMC / CMC / SGRD / Adesh); CMC quota "A" kept as new. No names stored.',
       'rows': rows, 'checks': checks}
json.dump(out, open(OUT, 'w'), ensure_ascii=False)
print('lines', len(rows), '| pages', len(doc), '| by section', checks['by_section'])
print('by quota', checks['by_quota'])
print('by allotted category', checks['by_allotted_category'])
print('rank checks', dict(ver), '| colleges', checks['colleges'], '| state ranks', checks['state_rank'],
      '| AI ranks', checks['ai_rank'], '|', out['status'], out['published_on'])
