"""Puducherry (CENTAC) PG Medical (MD/MS) round allotment list -> rows for POST /api/pg/results/ingest.

Usage: /usr/bin/python3 puducherry.py <allotment.pdf> <out.json> --gq-merit centac_gq_final.json --mq-merit centac_mq_final.json

The PDF ("ROUND 1 PROVISIONAL ALLOTMENT LIST OF PG MEDICAL COURSES - (2026 - 2027)", centacpuducherry.in) has one
section per quota x college, each starting on a new page:
    GOVERNMENT QUOTA - [ <college> ]  DATE : dd-mm-yyyy
    MANAGEMENT QUOTA - [ <college> ]
    MANAGEMENT QUOTA (TELUGU MINORITY) - [ <college> ]
and a table: SL NO, APP NO, NAME, NEET ROLL NO, NEET PERCENTILE (= NEET score), NEET ALL INDIA RANK, APPLIED
CATEGORY, ALLOTED CATEGORY, BRANCH, ROUND STATUS. SL NO restarts per section (a section may run over 2 pages).
The column x positions differ per page, so each row is read in print order, anchored on the roll number:
SL, APP NO, <name words>, ROLL, score, AIR, applied category, allotted category, <branch words>, status.
APP NO, NAME and ROLL are NEVER put in the output (the roll is used in memory only, for the merit-list check).
- rank = state merit rank = SL NO of the CENTAC FINAL merit list (GQ-ALL for Government Quota, MQ-ALL for both
  Management sections), looked up by roll; the merit list's AIR and score must equal the printed ones.
- rank_ai = printed NEET ALL INDIA RANK.
- quota (2025 CENTAC spellings): Government Quota / Management Quota / Management Quota-Telugu Minority.
- allotted_category = ALLOTED CATEGORY in the 2025 code spelling ('UGE', 'AGE', ...; a sub-category after '/'
  becomes '-FF' / '-PwD' / '-MSP' / '-ESM', as 2025 'UGE-FF'); candidate_category = APPLIED CATEGORY as printed.
- remarks = ROUND STATUS (FRESH ...).
Strict: anything unexpected -> SystemExit.
"""
import sys, os, re, json, collections, base64
import fitz

ROLL = re.compile(r'^2666\d{7}$')
APP = re.compile(r'^\d{8}$')
INT = re.compile(r'^\d+$')
SUBS = {'FF': 'FF', 'PWD': 'PwD', 'PwD': 'PwD', 'MSP': 'MSP', 'ESM': 'ESM', 'TELUGU': 'TELUGU'}
ACAT = re.compile(r'^(GEN|GENERAL|OBC|MBC|SC|ST|EBC|BCM|BT|EWS)(/(FF|PWD|PwD|MSP|ESM|TELUGU))?$')
CAT = re.compile(r'^([UA])(GE|OB|MB|SC|ST|EB|BM|BT|EW)(/(FF|PWD|PwD|MSP|ESM|TELUGU))?$')
STATUS = {'FRESH', 'UPGRADED', 'RETAINED', 'SAME', 'ALLOTTED'}
QUOTA = {'GOVERNMENT QUOTA': ('Government Quota', 'GQ'), 'MANAGEMENT QUOTA': ('Management Quota', 'MQ'),
         'MANAGEMENT QUOTA (TELUGU MINORITY)': ('Management Quota-Telugu Minority', 'MQ')}
COLLEGES = {   # printed -> name as printed (resolved by the portal name memory); listed so a new college stops the run
    'INDIRA GANDHI MEDICAL COLLEGE & RESEARCH INSTITUTE', 'PONDICHERRY INSTITUTE OF MEDICAL SCIENCE',
    'SRI MANAKULA VINAYAGAR MEDICAL COLLEGE & HOSPITAL', 'SRI VENKATESWARA MEDICAL COLLEGE HOSPITAL & RESEARCH CENTRE'}
# explicit standard name, taught to the name memory: the similarity match put PIMS on 'Sri Lakshmi Narayana Institute
# of Medical Sciences' (a different, deemed college) on 14.11.2026 - corrected here
INSTITUTE_STD = {'PONDICHERRY INSTITUTE OF MEDICAL SCIENCE': 'Puducherry Institute of Medical Sciences, Puducherry'}
key = lambda s: re.sub(r'[^A-Z]', '', s.upper())
COURSES = {
    'ANESTHESIOLOGY': 'MD - Anaesthesiology', 'ANAESTHESIOLOGY': 'MD - Anaesthesiology',
    'ANATOMY': 'MD/MS - Anatomy', 'BIOCHEMISTRY': 'MD - Biochemistry',
    'COMMUNITYMEDICINE': 'MD - Social & Preventive Medicine / Community Medicine',
    'DVLDERMATOLOGY': 'MD - Dermatology', 'EMERGENCYMEDICINE': 'MD - Emergency Medicine',
    'FORENSICMEDICINE': 'MD - Forensic Medicine', 'GENERALMEDICINE': 'MD - General Medicine',
    'MICROBIOLOGY': 'MD - Microbiology', 'PAEDIATRICS': 'MD - Paediatrics', 'PEDIATRICS': 'MD - Paediatrics',
    'PATHOLOGY': 'MD - Pathology', 'PHARMACOLOGY': 'MD - Pharmacology', 'PHYSIOLOGY': 'MD - Physiology',
    'PSYCHIATRY': 'MD - Psychiatry', 'RADIODIAGNOSIS': 'MD - Radio-Diagnosis',
    'TBRESPIRATORYMEDICINEPULMONARYMEDICINETBCHESTDISEASE': 'MD - Respiratory Medicine',
    'TRANSFUSIONMEDICINE': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'IMMUNOHAEMATOLOGYBLOODTRANSFUSION': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
    'GENERALSURGERY': 'MS - General Surgery', 'OBSGYN': 'MS - Obstetrics and Gynaecology',
    'OPHTHALMOLOGY': 'MS - Ophthalmology', 'ORTHOPAEDICS': 'MS - Orthopaedics', 'ORTHOPEDICS': 'MS - Orthopaedics',
    'ENTOTORHINOLARYNGOLOGY': 'MS - ENT (Otorhinolaryngology)',
}
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')


def cat_code(s):
    m = CAT.match(s)
    return m.group(1) + m.group(2) + ('-' + SUBS[m.group(4)] if m.group(4) else '')


def read(path, gq_merit, mq_merit):
    approved = {c['course'] for c in json.load(open(SHEET))['courses']}
    assert set(COURSES.values()) <= approved, set(COURSES.values()) - approved
    merit = {}
    for kind, fp in (('GQ', gq_merit), ('MQ', mq_merit)):
        m = json.load(open(fp))
        if m['authority_code'] != 'centac' or 'final' not in m['notes'].lower():
            raise SystemExit(f'{fp}: not a CENTAC final merit list')
        merit[kind] = {r['roll']: r for r in m['rows']}
    d = fitz.open(path)
    t0 = ' '.join(d[0].get_text().split())
    mt = re.search(r'ROUND (\d+) (PROVISIONAL|DRAFT|FINAL) ALLOTMENT LIST OF PG MEDICAL COURSES - \(2026 - 2027\)', t0)
    if not mt:
        raise SystemExit('page 1 title changed')
    if mt.group(2) == 'DRAFT':
        raise SystemExit('this is the DRAFT allotment list - not loaded')
    rnd, status = int(mt.group(1)), mt.group(2).lower()
    rows, text_rolls, sections, dates, wrapped_name = [], 0, [], collections.Counter(), 0
    checks_merit = collections.Counter()
    sec = None
    for p in d:
        txt = p.get_text()
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', txt))
        if mt.group(0) not in ' '.join(txt.split()):
            raise SystemExit(f'p{p.number + 1}: title missing')
        ws = p.get_text('words')
        lines = collections.defaultdict(list)
        for w in ws:
            lines[round(w[1])].append(w)
        title = None
        for y in sorted(lines):
            t = ' '.join(w[4] for w in sorted(lines[y], key=lambda w: w[0]))
            m = re.match(r'^(.*?) - \[ (.*?) \] DATE : (\d\d)-(\d\d)-(\d{4})$', t)
            if m:
                title = m
                break
        if not title or title.group(1) not in QUOTA or title.group(2) not in COLLEGES:
            raise SystemExit(f'p{p.number + 1}: section title not understood')
        dates[f'{title.group(5)}-{title.group(4)}-{title.group(3)}'] += 1
        k = (title.group(1), title.group(2))
        if sec is None or sec['key'] != k:
            sec = {'key': k, 'n': 0}
            sections.append(sec)
        rank_w = [w for w in ws if w[4] == 'RANK']
        if len(rank_w) != 1:
            raise SystemExit(f'p{p.number + 1}: header not found')
        hdr = ' '.join(w[4] for w in sorted(ws, key=lambda w: (round(w[1]), w[0])) if title_y(lines, title) < w[1] <= rank_w[0][1] + 1)
        for need in ('SL', 'APP', 'NAME', 'ROLL', 'PERCENTILE', 'INDIA', 'APPLIED', 'ALLOTED', 'BRANCH', 'ROUND',
                     'STATUS', 'RANK', 'CATEGORY'):
            if need not in hdr.split():
                raise SystemExit(f'p{p.number + 1}: column heading {need} missing')
        y_top = rank_w[0][1] + 4
        stop = [w[1] for w in ws if w[4] in ('***', 'NOTE') and w[1] > y_top]
        y_end = min(stop) if stop else 1e9
        body = [w for w in ws if y_top < w[1] < y_end - 1]
        anchors = sorted([w for w in body if ROLL.match(w[4])], key=lambda w: w[1])
        used = set()
        for i, a in enumerate(anchors):
            y0 = a[1] - 4                       # cells are top-aligned: wrapped Name / Branch lines sit below
            y1 = anchors[i + 1][1] - 4 if i + 1 < len(anchors) else y_end
            band = [w for w in body if y0 <= w[1] < y1]
            used.update(id(w) for w in band)
            main = sorted([w for w in band if abs(w[1] - a[1]) < 3], key=lambda w: w[0])
            other = [w for w in band if abs(w[1] - a[1]) >= 3]
            toks = [w[4] for w in main]
            where = f'p{p.number + 1} row {i + 1}'
            ri = toks.index(a[4])
            if ri < 3 or not INT.match(toks[0]) or not APP.match(toks[1]):
                raise SystemExit(f'{where}: SL / APP NO shape')
            after = main[ri + 1:]
            if len(after) < 6 or not INT.match(after[0][4]) or not INT.match(after[1][4]):
                raise SystemExit(f'{where}: score / AIR not numeric')
            acat, cat = after[2][4], after[3][4]
            if not ACAT.match(acat) or not CAT.match(cat):
                raise SystemExit(f'{where}: unknown category {acat!r} / {cat!r}')
            if after[-1][4] not in STATUS:
                raise SystemExit(f'{where}: unknown status {after[-1][4]!r}')
            br = after[4:-1]
            x_name0, x_name1 = main[1][2], a[0]
            x_br0 = after[3][2]
            for w in other:
                if w[0] >= x_br0 - 1 and w[2] <= main[-1][0] + 1:
                    br.append(w)
                elif x_name0 - 1 <= w[0] and w[2] <= x_name1 + 1:
                    wrapped_name += 1
                else:
                    raise SystemExit(f'{where}: wrapped text outside Name / Branch')
            branch = ' '.join(w[4] for w in sorted(br, key=lambda w: (round(w[1]), w[0])))
            if key(branch) not in COURSES:
                raise SystemExit(f'{where}: unknown branch {branch!r}')
            sl, score, air = int(toks[0]), int(after[0][4]), int(after[1][4])
            sec['n'] += 1
            if sl != sec['n']:
                raise SystemExit(f'{where}: SL NO {sl} != {sec["n"]} within the section')
            quota, mkind = QUOTA[title.group(1)]
            mr = merit[mkind].get(a[4])
            if mr is None:
                raise SystemExit(f'{where}: candidate not in the {mkind} final merit list')
            if mr['air'] != air or mr['score'] != score:
                raise SystemExit(f'{where}: AIR / score differ from the {mkind} merit list')
            checks_merit[f'{mkind} merit list: roll found, AIR + score agree'] += 1
            if acat.split('/')[0].replace('GENERAL', 'GEN') != mr['category'].split('/')[0].replace('GENERAL', 'GEN'):
                checks_merit[f'{mkind}: applied category differs from merit-list category'] += 1
            rows.append({'sno': len(rows) + 1, 'rank': mr['state_rank'], 'rank_ai': air,
                         'quota_raw': title.group(1), 'quota': quota, 'institute_raw': title.group(2),
                         'institute': INSTITUTE_STD.get(title.group(2), ''),
                         'course_raw': branch, 'course': COURSES[key(branch)], 'section': 'mdms',
                         'allotted_category': cat_code(cat), 'allotted_category_raw': cat,
                         'candidate_category': acat, 'remarks': after[-1][4],
                         '_sl': sl, '_score': score})
        for w in body:
            if id(w) not in used:
                raise SystemExit(f'p{p.number + 1}: stray word in data region')
    if text_rolls != len(rows):
        raise SystemExit(f'rolls in text {text_rolls} != rows {len(rows)}')
    if len(dates) != 1:
        raise SystemExit(f'section dates differ: {dict(dates)}')
    order_breaks = 0           # within a section the list should run in merit order
    by_sec = collections.defaultdict(list)
    for r in rows:
        by_sec[(r['quota_raw'], r['institute_raw'])].append(r)
    for v in by_sec.values():
        order_breaks += sum(1 for x, y in zip(v, v[1:]) if y['rank'] < x['rank'])
    for r in rows:
        del r['_sl'], r['_score']
    checks = {
        'pages': d.page_count, 'rows': len(rows), 'rolls_in_pdf_text': text_rolls, 'round': rnd, 'status': status,
        'section_date': list(dates)[0], 'sections': [f'{s["key"][0]} | {s["key"][1]}: {s["n"]}' for s in sections],
        'by_quota': dict(collections.Counter(r['quota'] for r in rows)),
        'by_college': dict(collections.Counter(r['institute_raw'] for r in rows)),
        'by_course': dict(collections.Counter(r['course'] for r in rows).most_common()),
        'by_allotted_category': dict(collections.Counter(r['allotted_category'] for r in rows).most_common()),
        'by_candidate_category': dict(collections.Counter(r['candidate_category'] for r in rows).most_common()),
        'by_status': dict(collections.Counter(r['remarks'] for r in rows)),
        'merit_checks': dict(checks_merit), 'merit_rank_order_breaks_within_section': order_breaks,
        'wrapped_name_words_skipped': wrapped_name,
        'rank': [min(r['rank'] for r in rows), max(r['rank'] for r in rows)],
        'rank_ai': [min(r['rank_ai'] for r in rows), max(r['rank_ai'] for r in rows)],
    }
    return rnd, status, list(dates)[0], rows, checks


def title_y(lines, m):
    for y in sorted(lines):
        if ' '.join(w[4] for w in sorted(lines[y], key=lambda w: w[0])) == m.group(0):
            return y
    return 0


def main():
    a = sys.argv[1:]
    opt = {}
    for k in ('--gq-merit', '--mq-merit'):
        if k not in a:
            raise SystemExit(__doc__)
        i = a.index(k); opt[k] = a[i + 1]; del a[i:i + 2]
    if len(a) != 2:
        raise SystemExit(__doc__)
    pdf, out = a
    rnd, status, date, rows, checks = read(pdf, opt['--gq-merit'], opt['--mq-merit'])
    body = {'authority_code': 'centac', 'round': f'Round {rnd}', 'round_order': rnd, 'status': status,
            'title': f'Round {rnd} {status.title()} Allotment List of PG Medical Courses (M.D./M.S.) 2026-2027 - CENTAC Puducherry',
            'published_on': date, 'source_file_name': os.path.basename(pdf),
            'notes': ('CENTAC Puducherry PG Medical (MD/MS). Government Quota (IGMCRI + 3 private colleges), Management '
                      'Quota and Management Quota (Telugu Minority, SVMCH). rank = SL NO in the CENTAC final merit list '
                      '(12-11-2026) of that quota (GQ-ALL / MQ-ALL), rank_ai = printed NEET AIR. allotted_category = '
                      'printed allotted category code (UGE/AGE ...), candidate_category = applied category. remarks = '
                      'round status. No names, roll or application numbers stored.'),
            'rows': rows, 'checks': checks}
    with open(out, 'w') as f:
        json.dump(body, f, indent=1, ensure_ascii=False)
    print(out)
    print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
