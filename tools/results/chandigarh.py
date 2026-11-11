"""Chandigarh GMCH-32 "LIST OF SELECTED CANDIDATES IN FIRST COUNSELLING (MDMS COURSE - 2026)" (dated 09.11.2026,
https://gmch.gov.in/sites/default/files/documents/Result_2.pdf) -> rows for POST /api/pg/results/ingest.

The PDF is a SCAN (garbage text layer), 71 lines, one college (GMCH Sector 32). Typed by hand from the page images
(2026-11-11): Sr No, Category, Rank (= NEET PG All-India rank — runs 299..154,939 in Sr No order) and Course only.
Application IDs and names are NEVER typed. The file is SHA-pinned so a re-upload (revised list) stops this script.
Quota / category / course use the 2025 Chandigarh cut-off spellings (State Quota-IP Pool; GEN / SC; OBC_NCL -> OBC).
Usage: python3 chandigarh.py <Result_2.pdf> <out.json> [--status final]
"""
import sys, json, hashlib

SHA = 'ca9849a47909a3b746352db2050ca5c90bfc631314253198730b03cfd0ceac5b'  # Result_2.pdf as of 09.11.2026
G, S, O = 'General', 'SC', 'OBC_NCL'
C = {'GM': 'MD - General Medicine', 'RD': 'MD - Radio-Diagnosis', 'OG': 'MS - Obstetrics and Gynaecology',
     'PE': 'MD - Paediatrics', 'PS': 'MD - Psychiatry', 'OP': 'MS - Ophthalmology', 'EN': 'MS - ENT (Otorhinolaryngology)',
     'GS': 'MS - General Surgery', 'OR': 'MS - Orthopaedics', 'AN': 'MD - Anaesthesiology',
     'RT': 'MD - Radiotherapy / Radiation Oncology', 'DE': 'MD - Dermatology', 'PH': 'MD - Pharmacology',
     'TM': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
     'CM': 'MD - Social & Preventive Medicine / Community Medicine', 'PA': 'MD - Pathology', 'PY': 'MD - Physiology',
     'MI': 'MD - Microbiology', 'FM': 'MD - Forensic Medicine', 'BI': 'MD - Biochemistry'}
RAW = {'GM': 'General Medicine', 'RD': 'Radiodiagnosis', 'OG': 'Obstt. & Gynae', 'PE': 'Paediatrics', 'PS': 'Psychiatry',
       'OP': 'Ophthalmology', 'EN': 'OtoRhinoLaryngology', 'GS': 'General Surgery', 'OR': 'Orthopaedics',
       'AN': 'Anaesthesiology', 'RT': 'Radiotherapy', 'DE': 'Dermatology', 'PH': 'Pharmacology',
       'TM': 'Transfusion Medicine', 'CM': 'Community Medicine', 'PA': 'Pathology', 'PY': 'Physiology',
       'MI': 'Microbiology', 'FM': 'Forensic Medicine', 'BI': 'Biochemistry'}
# (sno, category as printed, rank, course key)
L = [(1,G,299,'GM'),(2,G,529,'RD'),(3,G,593,'RD'),(4,G,626,'RD'),(5,G,830,'GM'),(6,G,837,'RD'),(7,G,1272,'GM'),
     (8,G,1410,'RD'),(9,G,1599,'GM'),(10,G,1845,'OG'),(11,G,2086,'PE'),(12,G,2130,'OG'),(13,G,2231,'OG'),
     (14,G,2280,'PS'),(15,G,2386,'PE'),(16,G,2641,'OP'),(17,G,2938,'PE'),(18,G,2979,'PE'),(19,G,2985,'PE'),
     (20,G,3253,'EN'),(21,G,3273,'PS'),(22,G,3702,'GS'),(23,G,5257,'PS'),(24,G,6434,'GS'),(25,G,6497,'OR'),
     (26,G,6569,'OR'),(27,S,6913,'OG'),(28,G,7306,'OR'),(29,G,7403,'OR'),(30,G,7578,'GS'),(31,G,8199,'GS'),
     (32,G,9296,'PS'),(33,G,9365,'EN'),(34,G,9908,'AN'),(35,G,10777,'GS'),(36,G,11292,'AN'),(37,G,11935,'AN'),
     (38,G,12219,'RT'),(39,G,12521,'AN'),(40,G,13678,'AN'),(41,G,14049,'RT'),(42,S,14099,'DE'),(43,G,14259,'AN'),
     (44,G,15144,'AN'),(45,O,16252,'DE'),(46,G,17089,'AN'),(47,G,17810,'PH'),(48,G,19375,'AN'),(49,G,23477,'TM'),
     (50,S,26182,'GM'),(51,G,31867,'CM'),(52,G,32592,'PA'),(53,S,32978,'AN'),(54,G,36731,'CM'),(55,G,38079,'PA'),
     (56,G,38538,'PA'),(57,S,41129,'OP'),(58,G,42967,'TM'),(59,G,44443,'PY'),(60,G,47818,'CM'),(61,S,48170,'GS'),
     (62,G,49765,'TM'),(63,G,54499,'MI'),(64,G,57646,'PH'),(65,S,69913,'CM'),(66,G,89815,'FM'),(67,G,105116,'MI'),
     (68,S,107020,'MI'),(69,S,123547,'FM'),(70,G,140706,'BI'),(71,S,154939,'BI')]
CAT = {G: 'GEN', S: 'SC', O: 'OBC'}

args = sys.argv[1:]
status = 'final'
if '--status' in args:
    i = args.index('--status'); status = args[i + 1]; del args[i:i + 2]
pdf, out = args
h = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
if SHA and h != SHA:
    raise SystemExit(f'PDF changed (sha {h[:12]}) — a revised list: re-type it')
assert [x[0] for x in L] == list(range(1, 72)), 'Sr No must run 1..71'
assert all(L[i][2] < L[i + 1][2] for i in range(len(L) - 1)), 'rank must rise with Sr No'
inst_raw = 'Govt. Medical College & Hospital, Sector 32, Chandigarh'
rows = [{'sno': n, 'rank': r, 'rank_ai': r, 'quota_raw': 'State Quota (GMCH-32 first counselling)',
         'quota': 'State Quota-IP Pool', 'institute_raw': inst_raw,
         'institute': 'Government Medical College and Hospital, Chandigarh',
         'course_raw': RAW[c], 'course': C[c], 'section': 'mdms', 'allotted_category': CAT[cat],
         'allotted_category_raw': cat, 'candidate_category': '', 'remarks': ''} for n, cat, r, c in L]
d = {'authority_code': 'gmch_chd', 'round': 'Round 1', 'round_order': 1, 'status': status,
     'title': 'List of Selected Candidates in First Counselling (MD/MS 2026), GMCH Sector 32, Chandigarh',
     'published_on': '2026-11-09', 'source_file_name': 'GMCH-32 Result_2.pdf (selected candidates, first counselling MDMS 2026)',
     'pdf_name': 'GMCH32-PG-2026-Round1-Selected.pdf',
     'notes': 'Scanned list typed by hand (Sr No, category, rank, course only — no names / application IDs). '
              'rank = NEET PG All-India rank as printed. One college (GMCH-32).',
     'rows': rows}
json.dump(d, open(out, 'w'))
print('rows', len(rows), 'sha', h[:16], {k: sum(1 for x in L if x[1] == k) for k in (G, S, O)})
