"""MCC NEET-PG 2026 FINAL DNB seat matrix ("FINAL SEATS MATRIX DNB PG COUNSELLING 2026", 503 pages) → standard
seat rows (one per institute × course × category), bridged to MCC's 2025 DNB cut-offs. JSON out only.
Run with /usr/bin/python3 (PyMuPDF):
    mcc_dnb.py <dnb_matrix.pdf> <cutoffs2025.json> <out.json>

PDF columns: Institute Type | Institute (name + address + "State-PIN(code)") | Program ("(NBEMS) X" /
"(NBEMS-DIPLOMA) X") | Quota (always "DNB Quota") | Open | Open PwD | General-EWS | General-EWS PwD | OBC |
OBC PwD | SC | SC PwD | ST | ST PwD | Total Seats; one "TOTAL SEATS" grand-total row on the last page.

MCC conventions (same as the AIQ / CIQ / Deemed bodies): college_code = MCC's 6-digit institute code,
college_name = the PDF's own institute text (code stripped), institute_type + quota = the PDF's own text,
category = the 2025 cut-off category (OPEN / EWS / OBC / SC / ST, " PwD"), category_code = the PDF column.
course_name = "DNB - <Title>" / "DNB Diploma - <Title>" — the same wording tools/results/mcc.py gives MCC's
allotment results, and it starts with "DNB" so HIDE_DNB hides it. section = 'dnb'.

Bridge: a seat links only to a 2025 MCC (All India) DNB cut-off row (course "(NBEMS…" / degree DNB /
degree_group dnb) of the SAME institute — matched by the MCC code in the cut-off name, or the exact same
name — same course, DNB quota, same category first, else the OPEN rank (cutoff_category says which).
No fuzzy college matching: anything else is new (new_reason as in common.build)."""
import collections, json, os, re, sys
import fitz
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import clean, grids, load_cuts, ALL_COURSES, approved_courses

PDF, CUTS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
HEADER = ['Institute Type', 'Institute', 'Program', 'Quota', 'Open', 'Open PwD', 'General- EWS', 'General- EWS PwD',
          'OBC', 'OBC PwD', 'SC', 'SC PwD', 'ST', 'ST PwD', 'Total Seats']
COLS = [('Open', 'OPEN'), ('Open PwD', 'OPEN PwD'), ('General-EWS', 'EWS'), ('General-EWS PwD', 'EWS PwD'),
        ('OBC', 'OBC'), ('OBC PwD', 'OBC PwD'), ('SC', 'SC'), ('SC PwD', 'SC PwD'), ('ST', 'ST'), ('ST PwD', 'ST PwD')]
TYPES = {'Diplomate of National Board (DNB) (Govt.) PG', 'Diplomate of National Board (DNB) (Pvt.) PG'}
QUOTA = 'DNB Quota'
STATES = {'Andaman and Nicobar Islands', 'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chandigarh',
          'Chhattisgarh', 'Dadra and Nagar Haveli', 'Delhi', 'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh',
          'Jammu and Kashmir', 'Jharkhand', 'Karnataka', 'Kerala', 'Ladakh', 'Madhya Pradesh', 'Maharashtra',
          'Manipur', 'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Puducherry', 'Punjab', 'Rajasthan', 'Sikkim',
          'Tamil Nadu', 'Telangana', 'Tripura', 'Uttar Pradesh', 'Uttarakhand', 'West Bengal'}
ALIAS = {'Orissa': 'Odisha', 'Pondicherry': 'Puducherry', 'Uttaranchal': 'Uttarakhand',
         'Jammu & Kashmir': 'Jammu and Kashmir'}
# Institutes whose cell prints a city (or nothing) instead of the state — the city / PIN in the PDF's own text.
STATE_BY_CODE = {
    '905591': 'Telangana',       # KIMS Hospitals, Gachibowli-500032 (Hyderabad)
    '905621': 'Telangana',       # Star Hospitals, Nanakramguda, Hyderabad-500008
    '701183': 'Telangana',       # Lotus Childrens Hospital, Kukatpally, Medchal-Malkajgiri District
    '905560': 'Delhi',           # Aarthi Scans and Labs, Block C1, Janakpuri-110058
    '905579': 'Assam',           # ESIC Medical College and Hospital, Beltola, Guwahati-781022
    '905584': 'Uttar Pradesh',   # Greenland Hospital, Gorakhpur-273013
    '905588': 'Karnataka',       # Jayadev Memorial Rashtrotthana Hospital, Bengaluru-560098
    '904275': 'Gujarat',         # GMERS Medical College and Hospital, Navsari-396445
    '905628': 'West Bengal',     # Zenith Super Specialist Hospital, Kolkata-700056
    '905578': 'Maharashtra',     # ESIC Medical College and Hospital, Andheri East, Mumbai-400093
    # Cell is only "Medica Superspecialty Hospital," — no address. Our College Database's DNB Hospitals sheet has
    # exactly this name only in Kolkata (the Ranchi one is "Bhagwan Mahavir Medica …"). REVIEW before posting.
    '701267': 'West Bengal',
}


def course_std(program):
    """'(NBEMS) GENERAL MEDICINE' → 'DNB - General Medicine'; '(NBEMS-DIPLOMA) ENT' → 'DNB Diploma - Ent'
    (exactly tools/results/mcc.py's wording, so seats and allotments use one name)."""
    p = clean(program)
    if not p.startswith(('(NBEMS)', '(NBEMS-DIPLOMA)')):
        raise SystemExit(f'not a DNB program: {program!r}')
    title = p.split(')', 1)[1].strip().title().replace('Otorhinolaryngolo Gy', 'Otorhinolaryngology')
    return ('DNB Diploma - ' if p.startswith('(NBEMS-DIPLOMA)') else 'DNB - ') + title


def institute(cell):
    """→ (code, name, state) from the Institute cell."""
    m = re.search(r'\((\d{6})\)\s*$', cell or '')
    if not m:
        raise SystemExit(f'no MCC institute code in {cell!r}')
    code, body = m.group(1), cell[:m.start()]
    name = clean(body).rstrip(' ,')
    last = re.sub(r'[\s,]*[-–]?\s*\d*\s*$', '', body.split('\n')[-1]).strip(' ,')
    last = ALIAS.get(last, last)
    if code in STATE_BY_CODE:
        state = STATE_BY_CODE[code]
    elif last in STATES:
        state = last
    else:
        raise SystemExit(f'cannot read the state of {code} {name!r} (last line {last!r}) — add it to STATE_BY_CODE')
    return code, name, state


# ── read the PDF ──
doc = fitz.open(PDF)
lines, printed = [], None
for pno, page in enumerate(doc):
    tabs = page.find_tables().tables
    if len(tabs) != 1:
        raise SystemExit(f'page {pno + 1}: {len(tabs)} tables')
    ext, grd = tabs[0].extract(), grids(page)[0]
    for r, g in zip(ext, grd):
        c = [clean(x) for x in r]
        if c[0].startswith('FINAL SEATS MATRIX DNB PG COUNSELLING 2026'):
            continue
        if c[0] == 'Institute Type':
            if c != HEADER:
                raise SystemExit(f'page {pno + 1}: header changed {c}')
            continue
        nums = [clean(x) for x in g[4:15]]
        if nums != c[4:15]:          # cells on coloured fills: word positions must agree with extract()
            raise SystemExit(f'page {pno + 1}: extract {c[4:15]} vs words {nums}')
        if not all(x.isdigit() for x in nums):
            raise SystemExit(f'page {pno + 1}: non-numeric seats {c}')
        nums = [int(x) for x in nums]
        if c[0] == 'TOTAL SEATS':    # the grand-total row — never a data line
            if printed is not None or pno != len(doc) - 1:
                raise SystemExit(f'unexpected TOTAL row on page {pno + 1}')
            printed = nums
            continue
        if c[0] not in TYPES or c[3] != QUOTA:
            raise SystemExit(f'page {pno + 1}: unknown institute type / quota {c[:4]}')
        if sum(nums[:10]) != nums[10]:
            raise SystemExit(f'page {pno + 1}: categories add to {sum(nums[:10])}, row total {nums[10]}: {c[:3]}')
        code, name, state = institute(r[1])
        lines.append({'page': pno + 1, 'type': c[0], 'code': code, 'name': name, 'state': state,
                      'program': c[2], 'course': course_std(r[2]), 'nums': nums})
if printed is None:
    raise SystemExit('no TOTAL SEATS row found')

names = collections.defaultdict(set)
for x in lines:
    names[x['code']].add(x['name'])
if any(len(v) > 1 for v in names.values()):
    raise SystemExit(f'one MCC code with two names: {[(k, v) for k, v in names.items() if len(v) > 1]}')
dup = [k for k, n in collections.Counter((x['code'], x['course']) for x in lines).items() if n > 1]
if dup:
    raise SystemExit(f'institute × course printed twice: {dup[:10]}')

# ── checks vs the printed totals ──
checks = {'TOTAL SEATS': (sum(x['nums'][10] for x in lines), printed[10])}
for i, (col, _cat) in enumerate(COLS):
    checks[col] = (sum(x['nums'][i] for x in lines), printed[i])
checks[QUOTA] = (sum(x['nums'][10] for x in lines), printed[10])    # the only quota in the file
bad = {k: v for k, v in checks.items() if v[0] != v[1]}
if bad:
    raise SystemExit(f'TOTALS DO NOT MATCH THE PDF: {bad}')

# ── 2025 MCC DNB cut-offs ──
approved_courses()                                   # DNB names are exempt from the approved list (common.build)
mcc = load_cuts(CUTS, 'MCC (All India)')
is_dnb = lambda c: ('NBEMS' in (c['course'] or '').upper() or (c['course'] or '').upper().startswith('DNB')
                    or 'DNB' in (c['degree'] or '').upper() or (c['degree_group'] or '').lower() == 'dnb')
dcuts = [c for c in mcc if is_dnb(c)]
norm = lambda s: re.sub(r'[^A-Z0-9]+', '', (s or '').upper())


def cut_course(c):
    s = clean(c['course'])
    return course_std(s) if s.startswith('(NBEMS') else s


cut_by_code, cut_by_name = {}, {}
for c in dcuts:
    m = re.search(r'\((\d{6})\)\s*$', c['institute'] or '')
    if m:
        cut_by_code[m.group(1)] = c['institute']
    cut_by_name.setdefault(norm(re.sub(r'\(\d{6}\)\s*$', '', c['institute'] or '')), c['institute'])
by = collections.defaultdict(list)
for c in dcuts:
    by[(c['institute'], cut_course(c))].append(c)
ALL_COURSES.update(cut_course(c) for c in dcuts)

rows = []
for x in lines:
    inst = cut_by_code.get(x['code']) or cut_by_name.get(norm(x['name'])) or ''
    for i, (col, cat) in enumerate(COLS):
        n = x['nums'][i]
        if not n:
            continue
        cand = [c for c in by.get((inst, x['course']), []) if (c['quota'] or '').startswith('DNB')] if inst else []
        same = [c for c in cand if c['category'] == cat]
        pick = (sorted(same or [c for c in cand if c['category'] == 'OPEN'],
                       key=lambda c: -(c['closing_rank'] or 0))[:1] or [None])[0]
        rows.append({
            'sl_no': len(rows) + 1, 'college_code': x['code'], 'state': x['state'], 'college_name': x['name'],
            'category': cat, 'course_name': x['course'], 'seats': n, 'section': 'dnb', 'institute_type': x['type'],
            'quota': QUOTA, 'category_code': col, 'course_code': '',
            'cutoff_institute': inst, 'cutoff_course': x['course'] if pick or x['course'] in ALL_COURSES else '',
            'cutoff_quota': pick['quota'] if pick else '', 'cutoff_category': pick['category'] if pick else '',
            'has_cutoff': 1 if pick else 0,
            'new_reason': '' if pick else ('new_college' if not inst else
                                           ('new_course' if not by.get((inst, x['course'])) else 'new_quota_category')),
            'cr_r1': pick['r1'] if pick else None, 'cr_r2': pick['r2'] if pick else None,
            'cr_r3': pick['r3'] if pick else None, 'cr_closing': pick['closing_rank'] if pick else None,
            'cutoff_fee': pick['fee'] if pick else None})

# the output must still add up to the PDF
checks['rows (seats)'] = (sum(r['seats'] for r in rows), printed[10])
for i, (col, cat) in enumerate(COLS):
    checks['rows ' + cat] = (sum(r['seats'] for r in rows if r['category'] == cat), printed[i])
bad = {k: v for k, v in checks.items() if v[0] != v[1]}
if bad:
    raise SystemExit(f'OUTPUT DOES NOT ADD UP TO THE PDF: {bad}')
checks['pdf_course_lines'] = len(lines)
checks['institutes'] = len(names)
checks['cutoff_2025_mcc_rows'] = len(mcc)
checks['cutoff_2025_mcc_dnb_rows'] = len(dcuts)

json.dump({'rows': rows, 'checks': checks}, open(OUT, 'w'), ensure_ascii=False, indent=0)
print('checks (parsed, printed):', {k: v for k, v in checks.items() if isinstance(v, tuple)})
print('pdf lines', len(lines), '| rows', len(rows), '| seats', sum(r['seats'] for r in rows), '| institutes', len(names))
print('by institute type', {t: sum(r['seats'] for r in rows if r['institute_type'] == t) for t in sorted(TYPES)})
print('by category', {c: sum(r['seats'] for r in rows if r['category'] == c) for _, c in COLS})
print('by course type', {k: sum(r['seats'] for r in rows if r['course_name'].startswith(k))
                         for k in ('DNB - ', 'DNB Diploma - ')})
print('2025 MCC cut-off rows', len(mcc), '| of them DNB', len(dcuts))
print('linked to a 2025 cut-off:', sum(r['seats'] for r in rows if r['has_cutoff']), 'seats /',
      sum(1 for r in rows if r['has_cutoff']), 'rows | new rows:',
      dict(collections.Counter(r['new_reason'] for r in rows if not r['has_cutoff'])))
if not dcuts:
    print('WARNING: the cut-off file has NO 2025 MCC DNB rows — every seat is flagged new_college.')
