"""Himachal Pradesh NEET PG 2026 Round 2 (AMRU) → the Round 2 seat list, body "Himachal Pradesh — Round 2 — State
Counselling" (authority `amru_hp`, round_no 2, list_type vacancy; the Round 1 body is never touched).

Source: "Provisional Seat Vacancy for MD/MS/DNB 2nd Round Counselling 2026" (inbox 1945, 23.11.2026, 25 pages, text
layer). Its pages 20-25 are the notice "State Quota Seat matrix for increased PG MD/MS Seats for Counselling 2026 (on
23.11.2026)", Endst. No. AMRU/(COE)-Admission-129/2026-27 PG(MD/MS)7313-7322 — the same 6 pages as inbox 1933 (checked
text-for-text when 1933 is given). The p1 note says "The increased seats in various institutions shall be added to the
respective seat vacancies", so the Round 2 list = (A) vacancies + (B) increased seats; nothing is double counted (the
vacancy list prints the increased courses' DNB lines with 0).

(A) pp 1-19: one block per college × course — Sr.No | "<Institute> - <MD/MS/DNB> <course>" | Total | HP Quota-Direct |
    HP Quota In-service | Management | NRI, with a nested Category/Seats table per quota (Direct: General ST SC EWS PH
    Single Girl child; In-service: General ST SC PH Single Girl child; Management: General ST SC PH; NRI: NRI). Cells are
    read by x position (blocks run across pages). Checks: Sr.No 1…n, every quota's categories = its printed seats, the
    four quotas = Total.
(B) pp 21-24: increased 50% State Quota MD/MS seats per college (as the Round 1 matrix: Specility | Total | GDO UR SC ST
    PWD Total | Direct UR SC ST EWS PWD Total); p25: post-MBBS DNB seats for in-service candidates (Total | GDO UR SC
    ST PWD). Checks: every line (GDO + Direct = Total), every college's Total line, grand totals.
Labels = the Round 1 body (himachal_pradesh.py): quotas 'In-service Quota (GDO)', 'State Quota (Direct)', 'Management
Quota', 'NRI Quota'; categories UR SC ST EWS PWD ('' for NRI); course names from its COURSES map. Post-MBBS DNB →
'DNB - <course> (Post-MBBS)', section dnb, 'In-service Quota (GDO)'. new_in_round = seats above the same college × course
× quota × category in the stored Round 1 body (all of (B) is new).
    /usr/bin/python3 tools/seat_matrix/himachal_pradesh_round2.py <vacancy.pdf> <round1_dump.json> <cutoffs2025.json> <out.json> [<increased.pdf>]
"""
import ast, collections, json, os, re, sys
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import clean, load_cuts, build, report

args = sys.argv[1:]
if len(args) not in (4, 5):
    raise SystemExit(__doc__)
PDF, R1DUMP, CUTS, OUT = args[:4]
INC_PDF = args[4] if len(args) == 5 else None

_src = ast.parse(open(os.path.join(os.path.dirname(__file__), 'himachal_pradesh.py')).read())
_lit = {t.id: ast.literal_eval(n.value) for n in _src.body if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name) and t.id in ('COURSES', 'IGMC', 'TANDA', 'MANDI', 'NAHAN',
                                                                   'HAMIRPUR', 'CHAMBA', 'MMMC')}
COURSES = dict(_lit['COURSES'])
IGMC, TANDA, MANDI, NAHAN, HAMIRPUR, CHAMBA, MMMC = (_lit[k] for k in ('IGMC', 'TANDA', 'MANDI', 'NAHAN', 'HAMIRPUR',
                                                                      'CHAMBA', 'MMMC'))
BLOOD = 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion'
COURSES.update({'Hematology & Blood Transfusion': BLOOD})
GDO_Q, DIR_Q, MGMT_Q, NRI_Q = 'In-service Quota (GDO)', 'State Quota (Direct)', 'Management Quota', 'NRI Quota'

INSTITUTES = [('Indira Gandhi', IGMC), ('Rajendra Prasad', TANDA), ('Lal Bahadur', MANDI), ('Yashwant Parmar', NAHAN),
              ('RadhaKrishanan', HAMIRPUR), ('Jawahar Lal Nehru', CHAMBA), ('Markandeshwar', MMMC)]
VAC_COURSE = {   # vacancy-list wording (after MD/MS) → approved course
    'Anatomy': 'MD/MS - Anatomy', 'Anaesthesiology': 'MD - Anaesthesiology', 'Biochemistry': 'MD - Biochemistry',
    'Community Medicine': 'MD - Social & Preventive Medicine / Community Medicine',
    'Dermatology, Venereology & Leprosy': 'MD - Dermatology', 'Forensic Medicine': 'MD - Forensic Medicine',
    'General Medicine': 'MD - General Medicine', 'General Surgery': 'MS - General Surgery',
    'Microbiology': 'MD - Microbiology', 'Obstetrics and Gynaecology': 'MS - Obstetrics and Gynaecology',
    'Ophthalmology': 'MS - Ophthalmology', 'Orthopaedics': 'MS - Orthopaedics',
    'Otorhinolaryngology': 'MS - ENT (Otorhinolaryngology)', 'Paediatrics': 'MD - Paediatrics',
    'Pathology': 'MD - Pathology', 'Pharmacology': 'MD - Pharmacology', 'Physiology': 'MD - Physiology',
    'Psychiatry': 'MD - Psychiatry', 'Pulmonary Medicine': 'MD - Respiratory Medicine',
    'Radio Diagnosis': 'MD - Radio-Diagnosis', 'Radiotherapy': 'MD - Radiotherapy / Radiation Oncology',
    'Radiation Oncology / Radiotherapy': 'MD - Radiotherapy / Radiation Oncology',
    'Hematology & Blood': BLOOD}          # printed cut short by the page break (block 85, 0 seats)
DNB_BASE = {'Anaesthesiology': 'Anaesthesiology', 'Obstetrics and Gynaecology': 'Obstetrics and Gynaecology',
            'Paediatrics': 'Paediatrics', 'General Medicine': 'General Medicine', 'General Surgery': 'General Surgery',
            'Physiology': 'Physiology',
            # increased-seat (p25) wording
            'Anesthesiology': 'Anaesthesiology', 'Obstetrics & Gynecology (OBG)': 'Obstetrics and Gynaecology',
            'Pediatrics': 'Paediatrics'}
CAT = {'General': 'UR', 'SC': 'SC', 'ST': 'ST', 'EWS': 'EWS', 'PH': 'PWD', 'Single Girl child': 'Single Girl Child',
       'NRI': ''}


def institute(name):
    hit = [c for k, c in INSTITUTES if k in name]
    if len(hit) != 1:
        raise SystemExit(f'institute not recognised: {name!r}')
    return hit[0]


doc = fitz.open(PDF)
if doc.page_count != 25:
    raise SystemExit(f'expected 25 pages, got {doc.page_count}')
p1 = clean(doc[0].get_text())
for must in ('Provisional Seat Vacancy for MD/MS/DNB 2nd Round Counselling 2026',
             'The increased seats in various institutions shall be added to the respective seat vacancies'):
    if must not in p1:
        raise SystemExit(f'p1 wording changed: {must!r} not found')

# ── (A) vacancy blocks, pp 1-19 ──
X = [('sr', 0, 82), ('name', 82, 167), ('tot', 167, 201), ('dir', 201, 241), ('ins', 241, 278), ('mq', 278, 320),
     ('nri', 320, 347), ('dcat', 347, 419), ('dseat', 419, 465), ('icat', 465, 535), ('iseat', 535, 573),
     ('mcat', 573, 614), ('mseat', 614, 661), ('ncat', 661, 694), ('nseat', 694, 740)]
PAIRS = [('dcat', 'dseat', 'dir'), ('icat', 'iseat', 'ins'), ('mcat', 'mseat', 'mq'), ('ncat', 'nseat', 'nri')]
QUOTA = {'dir': DIR_Q, 'ins': GDO_Q, 'mq': MGMT_Q, 'nri': NRI_Q}
WANT_CATS = {'dir': ['General', 'ST', 'SC', 'EWS', 'PH', 'Single Girl child'],
             'ins': ['General', 'ST', 'SC', 'PH', 'Single Girl child'], 'mq': ['General', 'ST', 'SC', 'PH'],
             'nri': ['NRI']}


def col(x):
    for n, a, b in X:
        if a <= x < b:
            return n


lines = []
for pi in range(19):
    g = collections.defaultdict(list)
    for w in doc[pi].get_text('words'):
        g[round((w[1] + w[3]) / 2 / 3)].append((w[0], col((w[0] + w[2]) / 2), w[4]))
    for k in sorted(g):
        r = collections.defaultdict(list)
        for _, c, t in sorted(g[k]):
            r[c].append(t)
        lines.append((pi + 1, {c: ' '.join(v) for c, v in r.items()}))
blocks, cats, name, open_ = [], None, [], False
for page, r in lines:
    if r.get('dcat') == 'Category' and r.get('dseat') == 'Seats':
        open_, cats, name = True, {q: [] for _, _, q in PAIRS}, []
        continue
    if not open_:
        continue
    if 'name' in r:
        name.append(r['name'])
    for c, s, q in PAIRS:
        if c in r and r[c] not in ('Category', 'Categor', 'y'):
            if not r.get(s, '').isdigit():
                raise SystemExit(f'p{page}: category {r[c]!r} has no seat number: {r}')
            cats[q].append((r[c], int(r[s])))
    if r.get('sr', '').isdigit() and r.get('tot', '').isdigit():
        tots = {q: int(r[q]) for q in ('tot', 'dir', 'ins', 'mq', 'nri')}
        blocks.append({'sr': int(r['sr']), 'name': re.sub(r'\s+', ' ', ' '.join(name)), 'tot': tots, 'cats': cats,
                       'page': page})
        open_ = False
checks = {}
if [b['sr'] for b in blocks] != list(range(1, len(blocks) + 1)):
    raise SystemExit('vacancy Sr.No not 1…n')
rows = []
for b in blocks:
    t = b['tot']
    if t['dir'] + t['ins'] + t['mq'] + t['nri'] != t['tot']:
        raise SystemExit(f'Sr {b["sr"]}: quotas {t} do not add to Total')
    for q, want in WANT_CATS.items():
        if [c for c, _ in b['cats'][q]] != want:
            raise SystemExit(f'Sr {b["sr"]} {q}: categories {b["cats"][q]}')
        if sum(n for _, n in b['cats'][q]) != t[q]:
            raise SystemExit(f'Sr {b["sr"]} {q}: categories {b["cats"][q]} ≠ {t[q]}')
    m = re.match(r'(.*) - (MD|MS|DNB) (.+)$', b['name'])
    if not m:
        raise SystemExit(f'Sr {b["sr"]}: name not "<institute> - <degree> <course>": {b["name"]!r}')
    college, degree, printed = institute(m.group(1)), m.group(2), m.group(3).strip()
    if degree == 'DNB':
        if printed not in DNB_BASE:
            raise SystemExit(f'Sr {b["sr"]}: unknown DNB course {printed!r}')
        course, section = f'DNB - {DNB_BASE[printed]} (Post-MBBS)', 'dnb'
    else:
        if printed not in VAC_COURSE:
            raise SystemExit(f'Sr {b["sr"]}: unknown course {printed!r}')
        course, section = VAC_COURSE[printed], 'mdms'
    for q, l in b['cats'].items():
        for c, n in l:
            if n:
                rows.append({'college': college, 'course': course, 'quota': QUOTA[q], 'category': CAT[c], 'seats': n,
                             'section': section, 'part': 'vacancy'})
checks['(A) vacancy blocks'] = (len(blocks), len(blocks))
checks['(A) vacancy seats = sum of block Totals'] = (sum(x['seats'] for x in rows), sum(b['tot']['tot'] for b in blocks))

# ── (B) increased seats, pp 21-25 ──
NUM = re.compile(r'^(\d+|-)$')
inc_pages = [clean(doc[i].get_text()) for i in range(19, 25)]
if INC_PDF:
    d2 = fitz.open(INC_PDF)
    other = [clean(p.get_text()) for p in d2]
    if other != inc_pages:
        raise SystemExit('increased-seat notice (1933) differs from pages 20-25 of the vacancy file')
    checks['(B) notice 1933 = vacancy file pp 20-25'] = ('same', 'same')
if 'State Quota Seat matrix for increased PG MD/MS Seats for Counselling 2026' not in re.sub(r'\s+', ' ', inc_pages[0]):
    raise SystemExit('p20 is not the increased-seat notice')
INC_HEAD = {21: IGMC, 22: TANDA, 23: MANDI, 24: HAMIRPUR}
INC_WANT = {IGMC: 41, TANDA: 23, MANDI: 15, HAMIRPUR: 13}
inc = []


def toks(page):
    return [w[4] for w in sorted(doc[page - 1].get_text('words'), key=lambda w: (w[5], w[6], w[7]))]


for page, college in INC_HEAD.items():
    t = toks(page)
    head = ' '.join(t[:40])
    if college.split(',')[0].replace('Dr. ', '').split()[0] not in head:
        raise SystemExit(f'p{page}: heading is not {college}: {head[:120]!r}')
    i = t.index('Direct', t.index('Direct') + 1) + 1          # end of the column headings ("Total Direct")
    name, acc, total = [], [0] * 12, None
    while i < len(t):
        if NUM.match(t[i]):
            v = t[i:i + 12]
            if len(v) != 12 or not all(NUM.match(x) for x in v):
                raise SystemExit(f'p{page}: short line after {name}: {v}')
            n = [0 if x == '-' else int(x) for x in v]
            label = re.sub(r'-\s+', '-', ' '.join(name)).strip()
            if label in ('', 'Total'):
                total = n
                break
            if sum(n[1:5]) != n[5] or sum(n[6:11]) != n[11] or n[5] + n[11] != n[0]:
                raise SystemExit(f'p{page} {label}: line does not add up {n}')
            if label not in COURSES:
                raise SystemExit(f'p{page}: unknown speciality {label!r}')
            acc = [a + b for a, b in zip(acc, n)]
            for c, k in zip(('UR', 'SC', 'ST', 'PWD'), n[1:5]):
                if k:
                    inc.append({'college': college, 'course': COURSES[label], 'quota': GDO_Q, 'category': c,
                                'seats': k, 'section': 'mdms', 'part': 'increased'})
            for c, k in zip(('UR', 'SC', 'ST', 'EWS', 'PWD'), n[6:11]):
                if k:
                    inc.append({'college': college, 'course': COURSES[label], 'quota': DIR_Q, 'category': c,
                                'seats': k, 'section': 'mdms', 'part': 'increased'})
            name, i = [], i + 12
        else:
            name.append(t[i]); i += 1
    if total is None:
        raise SystemExit(f'p{page}: no Total line')
    checks[f'(B) p{page} {college[:30]} Total line'] = (acc, total)
    checks[f'(B) p{page} {college[:30]} seats'] = (acc[0], INC_WANT[college])

# p25 post-MBBS DNB (in-service): college heading, 'Specility Name Total Seats GDO UR SC ST PWD', lines of 5
t = toks(25)
DNB_HEAD = [('Rajendra Prasad', TANDA, 1), ('Lal Bahadur', MANDI, 10), ('Parmar', NAHAN, 1), ('Radhakrishnan', HAMIRPUR, 10)]
starts = []
for key, college, want in DNB_HEAD:
    j = next((k for k in range(len(t)) if key.split()[0] in t[k] and (len(key.split()) == 1 or t[k + 1] == key.split()[1])), None)
    if j is None:
        raise SystemExit(f'p25: heading {key!r} not found')
    starts.append((j, college, want))
starts.sort()
dnb_total = 0
for idx, (j, college, want) in enumerate(starts):
    end = starts[idx + 1][0] if idx + 1 < len(starts) else len(t)
    seg = t[j:end]
    k = seg.index('PWD') + 1
    name, acc, total = [], [0] * 5, None
    while k < len(seg):
        if NUM.match(seg[k]) and len(name) and not (seg[k].isdigit() and name[-1] in ('Dr', 'Dr.')):
            v = seg[k:k + 5]
            if len(v) != 5 or not all(NUM.match(x) for x in v):
                break
            n = [0 if x == '-' else int(x) for x in v]
            label = ' '.join(name).strip()
            if label == 'Total':
                total = n
                break
            if sum(n[1:]) != n[0]:
                raise SystemExit(f'p25 {college} {label}: line does not add up {n}')
            if label not in DNB_BASE:
                raise SystemExit(f'p25: unknown DNB speciality {label!r}')
            acc = [a + b for a, b in zip(acc, n)]
            for c, s in zip(('UR', 'SC', 'ST', 'PWD'), n[1:]):
                if s:
                    inc.append({'college': college, 'course': f'DNB - {DNB_BASE[label]} (Post-MBBS)', 'quota': GDO_Q,
                                'category': c, 'seats': s, 'section': 'dnb', 'part': 'increased'})
            name, k = [], k + 5
        else:
            name.append(seg[k]); k += 1
    if total is not None:
        checks[f'(B) p25 DNB {college[:30]} Total line'] = (acc, total)
    checks[f'(B) p25 DNB {college[:30]} seats'] = (acc[0], want)
    dnb_total += acc[0]
checks['(B) increased MD/MS seats'] = (sum(x['seats'] for x in inc if x['section'] == 'mdms'), 92)
checks['(B) post-MBBS DNB seats'] = (dnb_total, 22)

# ── new_in_round vs the stored Round 1 body ──
r1 = collections.Counter()
for x in json.load(open(R1DUMP))['rows']:
    r1[(x['college_name'], x['course_name'], x['quota'], x['category'] or '')] += int(x['seats'])
allrows = rows + inc
merged = collections.OrderedDict()
for x in allrows:
    key = (x['college'], x['course'], x['quota'], x['category'], x['section'])
    if key in merged:
        merged[key]['seats'] += x['seats']; merged[key]['inc'] += x['seats'] if x['part'] == 'increased' else 0
    else:
        merged[key] = dict(x, inc=x['seats'] if x['part'] == 'increased' else 0)
vac_over_r1 = []
final = []
for key, x in merged.items():
    base = r1[key[:4]]
    vac = x['seats'] - x['inc']
    if vac > base:
        vac_over_r1.append((key[0][:25], key[1], key[2], key[3], vac, base))
    x['new_in_round'] = x['inc'] + max(0, vac - base)
    final.append(x)
checks['vacancy lines above Round 1 seats (listed below)'] = (len(vac_over_r1), len(vac_over_r1))

cuts = load_cuts(CUTS, 'Himachal Pradesh')
fam = {GDO_Q: ('State Quota-Inservice$',), DIR_Q: ('State Quota$',), MGMT_Q: ('Management Quota$',),
       NRI_Q: ('NRI Quota$',)}
CB = {'UR': ('GEN',), 'PWD': ('GEN-PH',), '': ('NRI',)}
out = build([{k: v for k, v in x.items() if k not in ('part', 'inc', 'new_in_round')} for x in final], cuts,
            'Himachal Pradesh', 'HP', lambda q: fam[q], lambda x: CB.get(x['category'], (x['category'],)))
if len(out) != len(final):
    raise SystemExit('build() changed the row count')
for o, x in zip(out, final):
    if (o['college_name'], o['course_name'], o['quota'], o['seats']) != (x['college'], x['course'], x['quota'], x['seats']):
        raise SystemExit('build() reordered rows')
    o['new_in_round'] = x['new_in_round']
json.dump({'rows': out, 'checks': checks, 'vacancy_over_round1': vac_over_r1}, open(OUT, 'w'), ensure_ascii=False,
          indent=0)
report(out, checks)
print('vacancy seats', sum(x['seats'] - x['inc'] for x in final), '| increased', sum(x['inc'] for x in final),
      '| new_in_round', sum(x['new_in_round'] for x in final))
print('by quota', dict(collections.Counter({q: sum(o['seats'] for o in out if o['quota'] == q) for q in
                                            sorted({o['quota'] for o in out})})))
print('by section', {s: sum(o['seats'] for o in out if o['section'] == s) for s in sorted({o['section'] for o in out})})
for name in (IGMC, TANDA, MANDI, NAHAN, HAMIRPUR, CHAMBA, MMMC):
    print(f'   {name}: {sum(r["seats"] for r in out if r["college_name"] == name)}')
if vac_over_r1:
    print('vacancy lines above the Round 1 seats:', vac_over_r1)
