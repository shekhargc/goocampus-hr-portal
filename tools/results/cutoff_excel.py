"""Team cut-off Excel from an allotment result (founder 2026-11-17): closing ranks per
college × course × quota × allotted category, from the JSON a results reader writes (mcc.py / mcc_r2.py / state readers).

    cutoff_excel.py <rows.json> <out.xlsx> --title "MCC NEET-PG 2026 Round 2" [--prev <earlier_round_rows.json>]

Sheets
  Read me          — source, rules, counts
  MD-MS & Diploma  — closing ranks (non-DNB)
  DNB              — closing ranks (DNB quota), hospital names exactly as published
  (founder 2026-11-17: no All-allotments sheet; every sheet starts with a S.No column)

Rules
  * Closing rank = highest (worst) rank allotted in THIS round for that college/course/quota/category;
    opening rank = lowest. From Round 2 on, only FRESH + UPGRADED seats count — a candidate who simply
    kept the earlier seat (retained) did not compete in this round (same rule as the portal/website).
  * 'Seats held after round' also counts retained seats.
  * Retained rows print no category in MCC's PDF; with --prev the category is copied from the earlier
    round's row of the same rank and seat.
No candidate names are read, stored or written."""
import json, sys, collections
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

args = sys.argv[1:]
SRC, OUT = args[0], args[1]
TITLE = args[args.index('--title') + 1] if '--title' in args else 'Allotment result'
PREV = args[args.index('--prev') + 1] if '--prev' in args else None

rows = json.load(open(SRC))['rows']
if PREV:
    prev = {r['rank']: r for r in json.load(open(PREV))['rows']}
    for r in rows:
        if r.get('round_status') == 'retained' and not r.get('allotted_category'):
            p = prev.get(r['rank'])
            if p and p.get('institute_raw') == r.get('institute_raw') and p.get('course') == r.get('course'):
                r['allotted_category'] = p.get('allotted_category', '')

later_round = any(r.get('round_status') for r in rows)
competes = lambda r: r.get('round_status') in (None, '', 'fresh', 'upgraded')

groups = collections.defaultdict(lambda: {'ranks': [], 'held': 0, 'fresh': 0, 'upgraded': 0, 'retained': 0})
for r in rows:
    k = (r['section'] == 'dnb', r['institute_raw'], r['course'], r['quota'], r.get('allotted_category') or '(not printed)')
    g = groups[k]
    g['held'] += 1
    st = r.get('round_status') or ''
    if st in g:
        g[st] += 1
    if competes(r):
        g['ranks'].append(r['rank'])

short = lambda n: (n or '').split(',')[0].strip()   # MCC prints "Name, City,Address" — name = before the first comma

HEAD_FILL = PatternFill('solid', fgColor='1E3A8A')
HEAD_FONT = Font(bold=True, color='FFFFFF')


def sheet(ws, header, data, widths):
    ws.append(header)
    for c in ws[1]:
        c.fill, c.font, c.alignment = HEAD_FILL, HEAD_FONT, Alignment(wrap_text=True, vertical='center')
    for d in data:
        ws.append(d)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions


wb = Workbook()
readme = wb.active
readme.title = 'Read me'
n_comp = sum(1 for r in rows if competes(r))
status_counts = collections.Counter(r.get('round_status') or 'allotted' for r in rows)
lines = [
    [TITLE + ' — closing ranks'],
    [],
    ['Source', 'Official allotment result PDF (converted by GooCampus). Verify any seat in the official PDF.'],
    ['Seats in the list', len(rows)],
    ['Counted for closing ranks', n_comp],
    ['By status', ', '.join(f'{k}: {v}' for k, v in sorted(status_counts.items()))],
    ['Closing rank', 'Highest (worst) rank allotted in this round for that college + course + quota + category.'],
    ['Opening rank', 'Lowest (best) rank allotted in this round for that combination.'],
]
if later_round:
    lines += [['Round 2+ rule', 'Only FRESH and UPGRADED seats set the closing rank. Candidates who kept their '
                                'earlier seat (retained) did not compete in this round; they are counted in '
                                '"Seats held after round".']]
lines += [['Names', 'No candidate names are in this file.']]
for l in lines:
    readme.append(l)
readme['A1'].font = Font(bold=True, size=14, color='1E3A8A')
readme.column_dimensions['A'].width = 26
readme.column_dimensions['B'].width = 110

hdr = ['S.No', 'College / Institute', 'Course', 'Quota', 'Allotted category', 'Opening rank', 'Closing rank',
       'Seats allotted this round']
if later_round:
    hdr += ['Fresh', 'Upgraded', 'Retained (kept earlier seat)', 'Seats held after round']
hdr += ['Full name + address as published']
wid = [7, 55, 42, 30, 18, 13, 13, 14] + ([9, 11, 16, 14] if later_round else []) + [90]
for dnb, name in ((False, 'MD-MS & Diploma'), (True, 'DNB')):
    data = []
    for k in sorted((k for k in groups if k[0] == dnb), key=lambda k: (k[1], k[2], k[3], k[4])):
        g = groups[k]
        rk = g['ranks']
        line = [short(k[1]), k[2], k[3], k[4], min(rk) if rk else None, max(rk) if rk else None, len(rk)]
        if later_round:
            line += [g['fresh'], g['upgraded'], g['retained'], g['held']]
        data.append([len(data) + 1] + line + [k[1]])
    sheet(wb.create_sheet(name), hdr, data, wid)

wb.save(OUT)
print(f'{OUT}: {len(rows)} seats, {sum(1 for k in groups if not k[0])} MD/MS+Diploma lines, '
      f'{sum(1 for k in groups if k[0])} DNB lines')
