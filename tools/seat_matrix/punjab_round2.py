"""Punjab (BFUHS) NEET PG 2026 ROUND 2 seats → one Round 2 body "Punjab — Round 2 — State Counselling"
(authority bfuhs, round_no 2, list_type 'vacancy') =
  (A) "Tentative vacancy position for 2nd round online counselling under NEET PG 2026" (BFUHS, PDF dated 13.11.2026,
      30 pages, one table: collegeName | courses | Branch | Category | Quota | Vacant Seats, one line per college ×
      branch × category × quota, heading row on every page, NO printed totals). Lines with 0 vacant are kept out of the
      seat rows (counted in checks); "Six months Training in Ultrasonography" (Ultrasonography_Batch1/2) is not a PG
      degree / diploma seat and is counted but not stored.
  (B) the 25 state-counselling seats of BFUHS Public Notice 03 (607, 18.11.2026) "inclusion of newly approved seats in
      various colleges in 2nd round" — parsed by punjab_added_r2.py into punjab_added_r2.json (42 seats; the 17 AIQ
      seats at GGS Faridkot / Dr B.R. Ambedkar Mohali go to MCC and are NOT stored here) → new_in_round.
      (A) predates (B) (13 Nov vs 18 Nov) and does not contain those seats, so (B) is added on top (no double counting).
There is NO Punjab Round 1 seat-matrix body (BFUHS never published one as a file — its Round 1 seats were only inside
the online counselling portal), so new_in_round marks only the 25 newly approved seats.
Names / quotas / categories follow the 2025 Punjab cut-offs and tools/results/punjab.py (college-family quotas: DMC =
Dayanand + Gian Sagar, CMC, SGRD, Adesh; CMC quota "A" kept as new). Anything unknown stops the run.
  /usr/bin/python3 tools/seat_matrix/punjab_round2.py <vacancy.pdf> <punjab_added_r2.json> <cutoffs2025.json> <out.json>
"""
import collections
import hashlib
import json
import os
import re
import sys

import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import load_cuts, build, report

VAC, ADDED, CUTS, OUT = sys.argv[1:5]
SHA_VAC = 'e264aef1f1a59bccf28f1a803234a904fc4fcf1c9f35299e46e445ab8596c842'
got = hashlib.sha256(open(VAC, 'rb').read()).hexdigest()
if SHA_VAC != 'PIN' and got != SHA_VAC:
    raise SystemExit(f'{VAC}: sha256 {got} — not the PDF this reader was written for')

HEAD = ['collegeName', 'courses', 'Branch', 'Category', 'Quota', 'Vacant Seats']

# printed college → 2025 cut-off / standard name (new 2026 hospitals get a standard name and show as new_college)
COLLEGE = {
    'Adesh Institute of Medical Sciences & Research, Bathinda': 'Adesh Institute of Medical Sciences & Research, Bhatinda',
    'Sri Guru Ram Das Institute of Medical Sciences and Research Amritsar': 'Sri Guru Ram Das Institute of Medical Sciences and Research, Sri Amritsar',
    'Dayanand Medical College and Hospital Ludhiana': 'Dayanand Medical College & Hospital, Ludhiana',
    'Government Medical College, Amritsar': 'Government Medical College, Amritsar',
    'Government Medical College, Patiala': 'Government Medical College, Patiala',
    'Christian Medical College, Ludhiana': 'Christian Medical College, Ludhiana',
    'Guru Gobind Singh Medical College Faridkot': 'Guru Govind Singh Medical College, Faridkot',
    'Gian Sagar Medical College & Hospital, Banur': 'Gian Sagar Medical College & Hospital, Patiala',
    'Dr.B.R Ambedkar State Institute of Medical Sciences S.A.S Nagar,Mohali': 'Dr. B.R. Ambedkar State Institute of Medical Sciences, Mohali',
    'SBLS CIVIL HOSPITAL, JAIL ROAD, NEAR JYOTI CHOWK, JALANDHAR': 'SBLS Civil Hospital, Jail Road, Jalandhar, Punjab',
    'JBMM DISTRICT HOSPITAL RAM BAGH PHATAK, NANDARI CINEMA CHOWK, AMRITSAR': 'JBMM District Hospital, Nandan Cinema Chowk, Amritsar, Punjab',
    'LORD MAHAVIR CIVIL HOSPITAL, OLD JAIL ROAD, LUDHIANA': 'Lord Mahavir Civil Hospital, MCH Wing Fieldganj Road, Ludhiana, Punjab',
    'MATA KAUSHALYA GOVT. HOSPITAL, NEAR COURT COMPLEX LAHORI GATE, PATIALA': 'Mata Kaushalya Government Hospital, Patiala, Punjab',
    'CIVIL HOSPITAL GURDASPUR NEAR BY PASS JEEVANWAL BABRI, GURDASPUR PUNJAB-143521': 'Civil Hospital, Gurdaspur, Punjab',
    'DISTRICT HOSPITAL FARIDKOT, CIVIL HOSPITAL FARIDKOT, PUNJAB-151203': 'District Hospital, Faridkot, Punjab',
    'Homi Bhabha Cancer Hospital,Sangrur': 'Homi Bhabha Cancer Hospital, Sangrur',
    'DISTRICT HOSPITAL, PHASE-6, SAS NAGAR, MOHALI, PUNJAB': 'District Hospital, Phase-6, SAS Nagar, Punjab',
    'SHAHEED BHAI MANI SINGH DISTRICT HOSPITAL, OPP. POLICE LINE, MANSA ROAD, BATHINDA': 'Shaheed Bhai Mani Singh District Hospital, Bathinda, Punjab',
    'Netaji Subhas National Institute of Sports, Patiala': 'Netaji Subhas National Institute of Sports, Patiala',
    'CIVIL HOSPITAL MALERKOTLA, RAILWAY ROAD, PUNJAB': 'Civil Hospital, Malerkotla, Punjab',
    'CIVIL HOSPITAL PATHANKOT, PUNJAB': 'Civil Hospital, Pathankot, Punjab',
    'CIVIL HOSPITAL, JALANDAHAR ROAD, HOSHIARPUR': 'Civil Hospital, Hoshiarpur, Punjab',
    'DISRICT HOSPITAL FAZILKA, SULLEMANI BORDER ROAD, NEAR COURT COMPLEX FAZILKA': 'District Hospital, Fazilka, Punjab',
    'DISRICT HOSPITAL TARNTARAN': 'District Hospital, Tarantaran, Sahib, Punjab',
    'DISRICT HOSPITAL, MAIN BAZAAR MOGA, PUNJAB': 'District Hospital, Main Bazaar, Moga, Punjab',
    'SDH Phagwara': 'SDH Phagwara, Chahal Naga, Gt Road, Phagwara',
    'SDH RAJPURA, RAJPURA TOWN PUNJAB': 'SDH Rajpura, Rajpura, Punjab',
    'CIVIL HOSPITAL KAPURTHALA, SULTANPUR ROAD PUNJAB': 'Civil Hospital, Kapurthala, Punjab',
    # not in the 2025 cut-offs (new 2026 DNB / diploma centres) — standard names, will show as new_college
    'CIVIL HOSPITAL ROPAR, PUNJAB': 'Civil Hospital, Ropar, Punjab',
    'Civil Hospital, Muktsar Sahib': 'Civil Hospital, Sri Muktsar Sahib, Punjab',
    'CIVIL HOSPITAL, WATER WORKS ROAD, MANSA, PUNJAB': 'Civil Hospital, Mansa, Punjab',
    'DISTRICT HOSPITAL NAWANSHAHAR VPO BARNALA KALAN, CHANDIGARH ROAD, SBS NAGAR, PUNJAB': 'District Hospital, Nawanshahr (SBS Nagar), Punjab',
    'INSTITUTE OF MENTAL HEALTH, GOVT. MENTAL HEALTH HOSPITAL, AMRITSAR': 'Institute of Mental Health, Amritsar, Punjab',
}
# added-seats notice names (punjab_added_r2.json) → standard names
ADDED_COLLEGE = {'Guru Govind Singh Medical College, Faridkot': 'Guru Govind Singh Medical College, Faridkot',
                 'Dr. B.R. Ambedkar State Institute of Medical Sciences, Mohali': 'Dr. B.R. Ambedkar State Institute of Medical Sciences, Mohali',
                 'Adesh Institute of Medical Sciences & Research, Bhatinda': 'Adesh Institute of Medical Sciences & Research, Bhatinda'}

CATEGORY = {'IP': 'IP', 'General Category': 'General', 'Backward Classes': 'BC', 'Scheduled Caste': 'SC',
            'EWS (IP)': 'EWS-IP', 'Christian': 'Minority', 'NRI': 'NRI', 'PWD (IP)': 'PWD-IP',
            'Persons with Disability': 'PWD'}


def family(college):
    c = college.lower()
    for key, fam in (('dayanand', 'DMC'), ('gian sagar', 'DMC'), ('christian medical', 'CMC'),
                     ('guru ram das', 'SGRD'), ('adesh', 'Adesh')):
        if key in c:
            return fam
    return ''


QUOTA = {  # (college family, printed quota) → 2025 cut-off quota (same map as tools/results/punjab.py)
    ('', 'Government Quota'): 'Government Quota', ('', 'State Quota (50%)'): 'Government Quota',
    ('DMC', 'Government Quota'): 'DMC Government Quota', ('DMC', 'Government Quota (IP)'): 'DMC Government Quota',
    ('DMC', 'Management Quota'): 'DMC Management Quota',
    ('CMC', 'Minority Quota'): 'CMC Minority Quota', ('CMC', 'NRI Quota'): 'CMC NRI Quota',
    ('CMC', 'A'): 'CMC Quota A', ('CMC', 'B'): 'CMC Quota B', ('CMC', 'C'): 'CMC Quota C',
    ('SGRD', 'General Quota as per Punjab Govt. Notification'): 'SGRD General Quota',
    ('SGRD', 'Sikh Minority Seats'): 'SGRD Sikh Minority Quota',
    ('SGRD', 'Sikh Minority Management Seats'): 'SGRD Sikh Minority Management Quota',
    ('Adesh', 'General Merit (50%)'): 'Adesh General Merit Quota',
    ('Adesh', 'Open Merit (All India Basis)'): 'Adesh Open Merit Quota (All India basis)'}

MDMS = {
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
        return 'USG', 'usg'
    return None, None


# ── (A) the tentative vacancy list ─────────────────────────────────────────
doc = fitz.open(VAC)
lines, unknown, heads = [], collections.Counter(), 0
checks = collections.Counter()
for pg in doc:
    for tb in pg.find_tables().tables:
        for r in tb.extract():
            c = [clean(v) for v in r]
            if len(c) != 6:
                raise SystemExit(f'expected 6 columns, got {len(c)}: {c}')
            if c[0] == 'collegeName':
                if c != HEAD:
                    raise SystemExit(f'column headings changed: {c}')
                heads += 1
                continue
            if not c[5].isdigit():
                raise SystemExit(f'vacant seats not a number: {c}')
            lines.append(c)
if heads != len(doc):
    raise SystemExit(f'expected one heading row per page: {heads} headings, {len(doc)} pages')

rows = []
for college_raw, prog, branch, cat_raw, quota_raw, vac in lines:
    n = int(vac)
    checks['lines'] += 1
    checks['printed_vacant_total'] += n
    course, section = course_of(branch)
    if not course:
        unknown['branch: ' + branch] += 1; continue
    if section == 'usg':
        checks['ultrasonography_training_seats_not_stored'] += n; continue
    college = COLLEGE.get(college_raw)
    if not college:
        unknown['college: ' + college_raw] += 1; continue
    fam = family(college)
    q = QUOTA.get((fam, quota_raw))
    if fam == 'DMC' and quota_raw == 'Management Quota' and cat_raw == 'NRI':
        q = 'DMC NRI Quota'
    if not q:
        unknown[f'quota: {fam or "-"} | {quota_raw}'] += 1; continue
    if cat_raw not in CATEGORY:
        unknown['category: ' + cat_raw] += 1; continue
    if n == 0:
        checks['zero_lines_not_stored'] += 1; continue
    rows.append({'college': college, 'course': course, 'section': section, 'quota': q, 'quota_raw': quota_raw,
                 'category': CATEGORY[cat_raw], 'seats': n, 'new_in_round': 0})
if unknown:
    raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
stored_vac = sum(x['seats'] for x in rows)
if stored_vac + checks['ultrasonography_training_seats_not_stored'] != checks['printed_vacant_total']:
    raise SystemExit('vacant seats lost while parsing')

# ── (B) newly approved seats (state-counselling part only) ─────────────────
added = json.load(open(ADDED))
add_rows = []
for a in added['rows']:
    college = ADDED_COLLEGE.get(a['college'])
    if not college:
        raise SystemExit(f"added-seat college not mapped: {a['college']}")
    if 'state_split' in a:                     # government colleges: the 50 % state quota part
        for k, v in a['state_split'].items():
            if v:
                add_rows.append({'college': college, 'course': a['course'], 'quota': 'Government Quota',
                                 'quota_raw': 'Government Quota (newly approved)', 'category': {'IP': 'IP', 'SC': 'SC', 'BC': 'BC'}[k],
                                 'seats': v})
        if sum(a['state_split'].values()) != a['state_quota']:
            raise SystemExit(f'state split ≠ state quota: {a}')
    else:                                       # Adesh (private): general merit (50 %) + open merit (All India basis)
        for part, quota, cmap in (('general_merit', 'Adesh General Merit Quota',
                                   {'IP': 'IP', 'SC': 'SC', 'BC': 'BC', 'PWD(IP)': 'PWD-IP'}),
                                  ('open_merit_all_india', 'Adesh Open Merit Quota (All India basis)',
                                   {'Open': 'General', 'SC': 'SC', 'BC': 'BC', 'PWD': 'PWD'})):
            p = a[part]
            if sum(v for k, v in p.items() if k != 'total') != p['total']:
                raise SystemExit(f'{part} parts ≠ total: {a}')
            for k, v in p.items():
                if k != 'total' and v:
                    add_rows.append({'college': college, 'course': a['course'], 'quota': quota,
                                     'quota_raw': quota + ' (newly approved)', 'category': cmap[k], 'seats': v})
added_state = sum(x['seats'] for x in add_rows)
if added_state != added.get('punjab_counselling_part', 25):
    raise SystemExit(f"added state-counselling seats {added_state} ≠ {added.get('punjab_counselling_part')}")
for x in add_rows:
    x.update(section='mdms', new_in_round=x['seats'])

# merge (same college × course × quota × category): seats = vacant + added, new_in_round = the added part
agg = {}
for x in rows + add_rows:
    k = (x['college'], x['course'], x['quota'], x['category'])
    if k in agg:
        agg[k]['seats'] += x['seats']; agg[k]['new_in_round'] += x['new_in_round']
    else:
        agg[k] = dict(x)
merged = list(agg.values())

cuts = load_cuts(CUTS, 'Punjab')
FAM = lambda q: (q + '$',)


def cat_match(x):
    return {'PWD-IP': ('PWD-IP', 'PWD'), 'PWD': ('PWD', 'PWD-IP')}.get(x['category'], (x['category'],))


out = build(merged, cuts, 'Punjab', 'PB', FAM, cat_match)
for o, x in zip(out, merged):
    o['new_in_round'] = x['new_in_round']
report(out, {'stored seats = vacant + added': (sum(r['seats'] for r in out), stored_vac + added_state)})
print('vacant seats stored:', stored_vac, '| newly approved (state part):', added_state,
      '| zero lines skipped:', checks['zero_lines_not_stored'],
      '| ultrasonography training seats not stored:', checks['ultrasonography_training_seats_not_stored'],
      '| printed vacant total (all lines):', checks['printed_vacant_total'])
print('by section', {s: sum(r['seats'] for r in out if r['section'] == s) for s in ('mdms', 'diploma', 'dnb')})
json.dump({'rows': out, 'checks': {**checks, 'pages': len(doc), 'heading_rows': heads, 'vacant_stored': stored_vac,
                                   'added_state_part': added_state, 'sha256_vacancy_pdf': got}},
          open(OUT, 'w'), ensure_ascii=False, indent=1)
