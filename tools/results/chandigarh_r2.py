"""Chandigarh GMCH-32 "LIST OF SELECTED CANDIDATES IN SECOND COUNSELLING (MDMS COURSE - 2026)" (23.11.2026, inbox 1937)
-> rows for POST /api/pg/results/ingest. Unlike Round 1 (a scan typed by hand) this PDF has a text layer.

Text order per line: Application ID (18 digits), Student Name (may wrap to 2 lines), Category, Rank, Course, Sr No. Names and application IDs are
read only to skip them — NEVER stored or printed. rank = NEET PG All-India rank as printed. One college (GMCH-32).
Course / category / quota spellings follow chandigarh.py (Round 1).
Usage: python3 chandigarh_r2.py <pdf> <out.json> [--status final]
"""
import sys, json, re, hashlib, ast, os
import fitz

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chandigarh.py')).read()
tree = ast.parse(src)
V = {}
for n in tree.body:
    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ('C', 'RAW'):
        V[n.targets[0].id] = ast.literal_eval(n.value)
BY_RAW = {v.lower(): k for k, v in V['RAW'].items()}
BY_RAW.update({'radio diagnosis': 'RD', 'radio-diagnosis': 'RD', 'obstetrics & gynaecology': 'OG', 'ent': 'EN'})
CAT = {'general': 'GEN', 'sc': 'SC', 'obc': 'OBC', 'obc_ncl': 'OBC', 'obc-ncl': 'OBC'}

args = sys.argv[1:]
status = 'final'
if '--status' in args:
    i = args.index('--status'); status = args[i + 1]; del args[i:i + 2]
pdf, out = args
h = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
L = [l.strip() for p in fitz.open(pdf) for l in p.get_text().split('\n') if l.strip()]
rows, bad = [], []
i = 0
while i < len(L):
    if re.fullmatch(r'\d{18}', L[i]):
        j = i + 2                      # the name can wrap onto 2+ lines: skip to the category word
        while j < len(L) and L[j].lower() not in CAT and j < i + 6:
            j += 1
        cat, rank, course, sno = L[j], L[j + 1], L[j + 2], L[j + 3]
        assert rank.isdigit() and sno.isdigit(), f'line shape at Sr No near {len(rows)+1}'
        k = BY_RAW.get(course.lower())
        if not k or cat.lower() not in CAT:
            bad.append((sno, cat, course))
        else:
            rows.append({'sno': int(sno), 'rank': int(rank), 'rank_ai': int(rank),
                         'quota_raw': 'State Quota (GMCH-32 second counselling)', 'quota': 'State Quota-IP Pool',
                         'institute_raw': 'Govt. Medical College & Hospital, Sector 32, Chandigarh',
                         'institute': 'Government Medical College and Hospital, Chandigarh',
                         'course_raw': course, 'course': V['C'][k], 'section': 'mdms',
                         'allotted_category': CAT[cat.lower()], 'allotted_category_raw': cat,
                         'candidate_category': '', 'remarks': ''})
        i = j + 4
    else:
        i += 1
if bad:
    raise SystemExit(f'unknown course/category: {bad}')
assert [r['sno'] for r in rows] == list(range(1, len(rows) + 1)), 'Sr No must run 1..n'
d = {'authority_code': 'gmch_chd', 'round': 'Round 2', 'round_order': 2, 'status': status,
     'title': 'List of Selected Candidates in Second Counselling (MD/MS 2026), GMCH Sector 32, Chandigarh',
     'published_on': '2026-11-23', 'source_file_name': 'GMCH-32 selected candidates, second counselling MDMS 2026 (inbox 1937)',
     'pdf_name': 'GMCH32-PG-2026-Round2-Selected.pdf',
     'notes': 'Read from the text layer (Sr No, category, rank, course only — no names / application IDs). '
              'rank = NEET PG All-India rank as printed. One college (GMCH-32).',
     'rows': rows}
json.dump(d, open(out, 'w'))
from collections import Counter
print('rows', len(rows), 'sha', h[:16], dict(Counter(r['allotted_category'] for r in rows)),
      'rank', rows[0]['rank'], '..', rows[-1]['rank'])
print(dict(Counter(r['course'].split(' - ')[1] for r in rows)))
