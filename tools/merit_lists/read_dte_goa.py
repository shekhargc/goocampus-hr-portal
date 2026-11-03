"""Goa (DTE) "PG DEGREE ADMISSION 2026 - PROVISIONAL MERIT LIST" (Goa Medical College) -> rank-bridge rows.
Usage: /usr/bin/python3 read_dte_goa.py <merit.pdf> <out.json>
One 7-column table: MERIT NO., REG NO., NAME OF THE CANDIDATE, CATEGORY 1, CATEGORY 2, NEET PG RANK, REMARKS.
Reads ONLY merit no., the two categories and the NEET PG rank — REG NO., NAME and REMARKS are never read into the
output. No roll number is printed, so air = the printed NEET PG rank (checked to exist in the NBEMS 2026 result).
state_rank = merit no.; category = CATEGORY 2 (OBC / ST / EWS / SC / OBC-O / PwD), else CATEGORY 1 (GEN).
The 29.10.2026 list: 161 rows, merit 1..161; merit 157-161 follow 156 out of AIR order (Goa lists them last —
their remarks name pending certificates) — stored as printed."""
import sys, re, json, collections
import fitz

if len(sys.argv) != 3:
    raise SystemExit(__doc__)
PDF, OUT = sys.argv[1:]
HEAD = ['MERIT NO.', 'REG NO.', 'NAME OF THE CANDIDATE (as per MBBS Degree Certificate)', 'CATEGORY 1', 'CATEGORY 2',
        'NEET PG RANK', 'REMARKS']
NBEMS = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/neet_result/neet2026.json'

doc = fitz.open(PDF)
cd = re.match(r'D:(\d{4})(\d{2})(\d{2})', doc.metadata.get('creationDate') or '')
rows = []
for pg in doc:
    for tb in pg.find_tables().tables:
        for r in tb.extract():
            c = [' '.join((x or '').split()) for x in r]
            if len(c) != 7 or not re.fullmatch(r'\d+', c[0]):
                if len(c) == 7 and c[0].startswith('MERIT') and c != HEAD:
                    raise SystemExit(f'p{pg.number + 1}: column headings changed')
                continue                                   # headings / blank filler lines / the abbreviations key
            if not re.fullmatch(r'\d+', c[5]):
                raise SystemExit(f'merit {c[0]}: NEET PG rank not a number')
            rows.append({'roll': '', 'air': int(c[5]), 'state_rank': int(c[0]), 'score': None,
                         'category': c[4] if c[4] not in ('', '-') else c[3], 'quota': ''})
sr = [r['state_rank'] for r in rows]
if sr != list(range(1, len(sr) + 1)):
    raise SystemExit('merit numbers are not 1..n in order')
airs = {x['air'] for x in json.load(open(NBEMS)) if x.get('air')}
missing = [r['state_rank'] for r in rows if r['air'] not in airs]
if missing:
    raise SystemExit(f'NEET PG rank not in the NBEMS result at merit {missing[:10]}')
a = [r['air'] for r in rows]
checks = {'rows': len(rows), 'merit_1_to_n': True, 'air_in_nbems': len(rows),
          'air_order_breaks_at_merit': [rows[i + 1]['state_rank'] for i in range(len(a) - 1) if a[i + 1] < a[i]],
          'category': dict(collections.Counter(r['category'] for r in rows).most_common())}
obj = {'authority_code': 'dte_goa', 'list_name': 'PG Degree Admission 2026 Provisional Merit List',
       'published_on': f'{cd.group(1)}-{cd.group(2)}-{cd.group(3)}' if cd else '', 'rows': rows, 'checks': checks}
json.dump(obj, open(OUT, 'w'))
print(json.dumps(checks))
