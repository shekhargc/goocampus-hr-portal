"""Uttar Pradesh (DGME / upneet.gov.in, authority `dmetup`) NEET-PG seat allotment → rows for POST /api/pg/results/ingest.

UP publishes NO allotment PDF. The result is an interactive ASP.NET page:
    upneet.gov.in → Allotted Candidate List → Allotted and Vacant Seat (vaccant_result/vseat_stream.aspx)
    → "UP NEET PG Counseling For MDMS(MEDICAL)-2026" (postback ctl00$ContentPlaceHolder1$1) or "… For DNB-2026" ($4)
    → "Institute Wise Allotted Candidates Round- 1" (onallotmainCStatus.aspx) → pick an institute → Submit.
Each institute page is one table: Branch Name, Serial No., Round, Allotted under Category, Rollno, Name, Father's Name,
Rank, Allottment Date, Left Institute, Left Course.

Two steps:
    fetch  — walks every institute of both streams (sequential, ~1.5 s apart) and writes a CLEAN cache: no names,
             no father's names, no roll numbers. The roll is used in memory only, to look the candidate up in the UP
             state merit lists (the official merit PDFs, read with the same parsing as tools/merit_lists/read_dmetup.py)
             → state merit rank (SrNo), NEET AIR and merit-list category are stored with the row instead.
    build  — cache → ingest body (quota / category / course mapping + checks).

Run with /usr/bin/python3 (PyMuPDF for the merit PDFs):
    uttar_pradesh.py fetch <cache.json> --merit-mdms <merit MD/MS/Diploma R1.pdf> --merit-dnb <merit DNB R1.pdf>
    uttar_pradesh.py build <cache.json> <out.json> [--round "Round 1"] [--round-order 1] [--status provisional]
                           [--published-on YYYY-MM-DD]

Mapping (2025 UP cut-off spellings; the 2025 UP cut-offs hold NEET All-India ranks):
- rank    = UP state merit rank (merit-list SrNo of the stream's list, found by roll). The page's own "Rank" column is
            checked against it (2026 R1: MD/MS page Rank = state merit rank on every line, DNB page Rank = AIR on
            every line). DNB-stream rows (incl. Post-MBBS diplomas) carry the DNB list's rank → quota_raw starts
            'DNB list', so they can be told apart from MD/MS-list ranks.
- rank_ai = NEET AIR from the same merit-list line.
- quota   = college type + institute-code minority suffix + in-service category:
            Govt. → Government Quota (in-service category → Government Quota-Inservice);
            Private → Private Quota; Private "(… MINORITY)" institute code → Private Quota-Minority;
            Private + in-service → Private Quota-Inservice; DNB stream → DNB Quota (section dnb).
- category = the "Allotted under Category" code in 2025 spellings (see CATEGORY); the raw code is kept.
"""
import json, os, re, sys, time, html, collections
import urllib.request, urllib.parse, http.cookiejar

BASE = 'https://upneet.gov.in/vaccant_result/'
STREAMS = {'mdms': ('ctl00$ContentPlaceHolder1$1', 'UP NEET PG COUNSELING (MD/MS/DIPLOMA) -2026'),
           'dnb': ('ctl00$ContentPlaceHolder1$4', 'UP NEET PG COUNSELING (DNB) -2026')}
HEAD = ['Branch Name', 'Serial No.', 'Round', 'Allotted under Category', 'Rollno', 'Name', "Father's Name", 'Rank',
        'Allottment Date', 'Left Institute', 'Left Course']
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')
clean = lambda s: re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()


# ───────────────────────────── fetch ─────────────────────────────
class Site:
    def __init__(self, delay=1.5):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.delay, self.n = delay, 0

    def _open(self, url, data=None):
        time.sleep(self.delay)
        self.n += 1
        hdr = {'User-Agent': 'Mozilla/5.0 (Macintosh) results-reader'}
        if data is not None:
            hdr['Referer'] = url
            data = urllib.parse.urlencode(data).encode()
        for attempt in range(3):
            try:
                r = self.op.open(urllib.request.Request(url, data=data, headers=hdr), timeout=120)
                return r.geturl(), r.read().decode('utf-8', 'replace')
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(10)

    @staticmethod
    def hidden(t):
        d = {}
        for m in re.finditer(r'<input[^>]*type="hidden"[^>]*>', t):
            n = re.search(r'name="([^"]*)"', m.group(0)); v = re.search(r'value="([^"]*)"', m.group(0))
            if n:
                d[html.unescape(n.group(1))] = html.unescape(v.group(1)) if v else ''
        return d

    def get(self, url):
        return self._open(url)

    def post(self, url, page, target='', extra=None):
        d = self.hidden(page); d['__EVENTTARGET'] = target; d['__EVENTARGUMENT'] = ''
        d.update(extra or {})
        return self._open(url, d)


def institutes(page):
    sel = re.search(r'(?is)<select name="ctl00\$ContentPlaceHolder1\$DDL_Institute".*?</select>', page)
    if not sel:
        raise SystemExit('institute dropdown not found')
    return [(v, clean(n)) for v, n in re.findall(r'<option value="([^"]*)">([^<]*)</option>', sel.group(0))
            if v.isdigit()]


def table_lines(page):
    """Data lines of the allotment table as cell lists. Cells are split on '<td' (the Round cell is not closed)."""
    tabs = [t for t in re.findall(r'(?is)<table[^>]*>.*?</table>', page) if 'Allotted under Category' in t]
    if len(tabs) != 1:
        return None, 0
    trs = re.findall(r'(?is)<tr[^>]*>(.*?)</tr>', tabs[0])
    heads = [clean(x) for x in re.findall(r'(?is)<th[^>]*>(.*?)</th>', tabs[0])]
    heads = [h for h in heads if h and h != 'Candidate Details']
    if heads != HEAD:
        raise SystemExit(f'column headings changed: {heads}')
    out = []
    for tr in trs:
        if '<td' not in tr.lower():
            continue
        cells = [clean(c) for c in re.split(r'(?i)<td[^>]*>', tr)[1:]]
        out.append(cells)
    return out, len(trs)


def fetch(cache, merit_pdfs):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'merit_lists'))
    from merit_common import table_rows, num
    merit = {}
    for stream, path in merit_pdfs.items():   # roll → (SrNo, AIR, category) — in memory only
        pages, trs, _ = table_rows(path)
        m, ncols = {}, None
        for _pn, r in trs:
            if not r or not r[0].isdigit():
                continue
            ncols = ncols or len(r)
            if len(r) != ncols:
                continue
            sno, roll, _nm, _fa, cat, sub, _marks, air = r[:8]
            m[roll] = (int(sno), num(air), cat if sub in ('', 'OP') else f'{cat}-{sub}')
        merit[stream] = m
        print(f'merit {stream}: {len(m)} lines ({os.path.basename(path)})')
    site = Site()
    out = {'fetched_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'source': BASE + 'vseat_stream.aspx',
           'merit_files': {k: os.path.basename(v) for k, v in merit_pdfs.items()},
           'merit_sizes': {k: len(v) for k, v in merit.items()}, 'streams': {}}
    for stream, (target, label) in STREAMS.items():
        _, start = site.get(BASE + 'vseat_stream.aspx')
        url, dpage = site.post(BASE + 'vseat_stream.aspx', start, target)
        if label not in dpage:
            raise SystemExit(f'{stream}: stream page does not say {label!r}')
        links = re.findall(r"<a href='([^']+)'>\s*([^<]*Round[^<]*)</a>", dpage)
        _, lpage = site.get(BASE + 'onallotmainCStatus.aspx')
        if label not in lpage:
            raise SystemExit(f'{stream}: list page does not say {label!r}')
        insts = institutes(lpage)
        st = {'label': label, 'round_links': [clean(x[1]) for x in links], 'institutes': len(insts), 'lines': [],
              'per_institute': {}, 'empty_institutes': []}
        for code, name in insts:
            _, ipage = site.post(BASE + 'onallotmainCStatus.aspx', lpage, '',
                                 {'ctl00$ContentPlaceHolder1$DDL_Institute': code, 'ctl00$ContentPlaceHolder1$Submit': 'Submit'})
            shown = re.search(r'\((\d{3})\)\s*[^<]*', ipage[ipage.find('List of Allotted Candidates'):] or '')
            lines, ntr = table_lines(ipage)
            if lines is None:
                st['empty_institutes'].append(code); st['per_institute'][code] = 0
                continue
            if not shown or shown.group(1) != code:
                raise SystemExit(f'{stream} {code}: page shows another institute')
            for c in lines:
                if len(c) < 11:
                    raise SystemExit(f'{stream} {code}: a line has {len(c)} cells')
                branch, serial, rnd, cat, roll, _nm, _fa, rank, date, left_i, left_c = c[:11]
                ml = merit[stream].get(roll) or merit['mdms' if stream == 'dnb' else 'dnb'].get(roll)
                other = roll not in merit[stream] and ml is not None
                st['lines'].append({'inst_code': code, 'inst': name, 'branch': branch, 'serial': serial, 'round': rnd,
                                    'category': cat, 'page_rank': rank, 'date': date, 'left_institute': left_i,
                                    'left_course': left_c, 'roll_ok': bool(re.fullmatch(r'2666\d{7}', roll)),
                                    'merit_state_rank': ml[0] if ml else None, 'merit_air': ml[1] if ml else None,
                                    'merit_category': ml[2] if ml else None,
                                    'merit_list': (('dnb' if stream == 'mdms' else 'mdms') if other else stream) if ml else None})
                del roll, _nm, _fa                   # personal data never leaves this loop
            st['per_institute'][code] = len(lines)
            print(f'{stream} {code}: {len(lines)}', flush=True)
        out['streams'][stream] = st
    out['requests'] = site.n
    json.dump(out, open(cache, 'w'), indent=1)
    print('wrote', cache, {k: len(v['lines']) for k, v in out['streams'].items()}, 'requests', site.n)


# ───────────────────────────── build ─────────────────────────────
# "Allotted under Category" → (2025 UP cut-off category, in-service?, seat-matrix category). PH = PwD seats.
# BS / SS / SG are UP's in-service groups — in 2025 they only occur under 'Government Quota-Inservice'.
CATEGORY = {'UROP': ('UR', False, 'UR'), 'BCOP': ('BC', False, 'OBC'), 'SCOP': ('SC', False, 'SC'),
            'EWOP': ('EWS', False, 'EWS'), 'STOP': ('ST', False, 'ST'),
            'URPH': ('UR-PH', False, 'UR-PwD'), 'BCPH': ('BC-PH', False, 'OBC-PwD'), 'SCPH': ('SC-PH', False, 'SC-PwD'),
            'EWPH': ('EWS-PH', False, 'EWS-PwD'), 'STPH': ('ST-PH', False, 'ST-PwD'),
            'BSOP': ('BS', True, 'BS'), 'SSOP': ('SS', True, 'SS'), 'SGOP': ('SG', True, 'SG')}
# merit-list category a reserved seat needs (OB / OE / OS / OT = the list's other groups; they only sit on UR seats)
NEEDS = {'BC': {'BC', 'BC-PH'}, 'SC': {'SC', 'SC-PH'}, 'EWS': {'EW', 'EW-PH'}, 'ST': {'ST', 'ST-PH'},
         'UR-PH': {'UR-PH'}, 'BC-PH': {'BC-PH'}, 'SC-PH': {'SC-PH'}, 'EWS-PH': {'EW-PH'}, 'ST-PH': {'ST-PH'}}
SP2025 = {'quota': {'Government Quota', 'Government Quota-Inservice', 'Private Quota', 'Private Quota-Minority',
                    'Private Quota-Inservice'},
          'category': {'UR', 'BC', 'SC', 'EWS', 'ST', 'UR-PH', 'BC-PH', 'SC-PH', 'EWS-PH', 'BS', 'SS', 'SG'}}


def seat_matrix_maps():
    """COLLEGES / HOSPITALS / COURSES of tools/seat_matrix/uttar_pradesh.py (read as literals, the module runs on import)."""
    import ast
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'seat_matrix', 'uttar_pradesh.py')).read()
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and \
                node.targets[0].id in ('COLLEGES', 'HOSPITALS', 'COURSES', 'MINORITY'):
            out[node.targets[0].id] = ast.literal_eval(node.value)
    return out


def build(cache, out_path, opt):
    d = json.load(open(cache))
    sm = seat_matrix_maps()
    courses = {raw: (std, sec) for raw, std, sec in sm['COURSES'].values()}
    approved = {c['course'] for c in json.load(open(SHEET))['courses']}
    rows, unknown, cat_bad, rank_page = [], collections.Counter(), [], collections.Counter()
    sno = 0
    for stream in ('mdms', 'dnb'):
        for x in d['streams'][stream]['lines']:
            m = re.fullmatch(r'\((\d{3})\)\s*(.*?)\s*\[(Govt\.|Private)\]\s*Co-Education', x['inst'])
            if not m or m.group(1) != x['inst_code']:
                unknown['institute text: ' + x['inst']] += 1; continue
            raw, kind = re.sub(r'\s+', ' ', m.group(2)), m.group(3)
            names = sm['COLLEGES'] if stream == 'mdms' else sm['HOSPITALS']
            if raw not in names:
                unknown[f'{stream} institute not in the seat-matrix map: {raw}'] += 1; continue
            if x['branch'] not in courses:
                unknown['course: ' + x['branch']] += 1; continue
            std, sec = courses[x['branch']]
            if (stream == 'dnb') != (sec in ('dnb',) or x['branch'].endswith('(POST MBBS DIPLOMA)')):
                unknown[f'{stream} course in the wrong stream: {x["branch"]}'] += 1; continue
            if x['category'] not in CATEGORY:
                unknown['category: ' + x['category']] += 1; continue
            if x['round'] != 'Round1':
                unknown['round: ' + x['round']] += 1; continue
            if x['merit_state_rank'] is None or x['merit_list'] != stream:
                unknown[f'{stream}: roll not on the {stream} merit list'] += 1; continue
            cat, inservice, _ = CATEGORY[x['category']]
            minority = next((k for k in sm['MINORITY'] if raw.endswith(k)), None)
            if sec == 'dnb':
                quota = 'DNB Quota'
            elif kind == 'Govt.':
                quota = 'Government Quota-Inservice' if inservice else 'Government Quota'
            elif minority:
                quota = 'Private Quota-Minority'
            else:
                quota = 'Private Quota-Inservice' if inservice else 'Private Quota'
            if cat in NEEDS and x['merit_category'] not in NEEDS[cat]:
                cat_bad.append({'stream': stream, 'inst': x['inst_code'], 'seat': x['category'], 'merit': x['merit_category']})
            pr = int(x['page_rank'])
            rank_page['state_rank' if pr == x['merit_state_rank'] else 'air' if pr == x['merit_air'] else 'neither'] += 1
            if sec != 'dnb' and std not in approved:
                raise SystemExit(f'{std!r} is not in specialty_sheet.json')
            sno += 1
            rows.append({'sno': sno, 'rank': x['merit_state_rank'], 'rank_ai': x['merit_air'],
                         'quota_raw': f'{kind} ' + (minority or '') + (' in-service' if inservice else ''),
                         'quota': quota, 'institute_raw': raw, 'institute': '' if sec == 'dnb' else names[raw],
                         'course_raw': x['branch'], 'course': std, 'section': sec,
                         'allotted_category': cat, 'allotted_category_raw': x['category'],
                         'candidate_category': x['merit_category'],
                         'remarks': f"{x['inst_code']}/{x['serial']}; allotted {x['date']}"
                                    + (f"; left {x['left_institute']} {x['left_course']}" if x['left_institute'] not in ('-', '') else '')})
            rows[-1]['quota_raw'] = rows[-1]['quota_raw'].strip()
            if stream == 'dnb':   # rank = position on the separate DNB merit list (96 lines), not the MD/MS list
                rows[-1]['quota_raw'] = 'DNB list ' + rows[-1]['quota_raw']
                rows[-1]['remarks'] += '; rank = UP DNB merit list rank'
    if unknown:
        raise SystemExit(f'unknown values (add them to the maps): {dict(unknown)}')
    if cat_bad:
        raise SystemExit(f'reserved seats to another category: {cat_bad[:20]}')
    total = sum(len(s['lines']) for s in d['streams'].values())
    if len(rows) != total:
        raise SystemExit('rows ≠ lines')
    not_2025 = {'quota': sorted({r['quota'] for r in rows if r['section'] != 'dnb'} - SP2025['quota']),
                'category': sorted({r['allotted_category'] for r in rows} - SP2025['category'])}
    C = lambda f, rs=rows: dict(collections.Counter(r[f] for r in rs).most_common())
    dates = sorted({x['date'] for s in d['streams'].values() for x in s['lines']})
    pub = opt.get('--published-on') or ('-'.join(reversed(dates[0].split('/'))) if len(dates) == 1 else '')
    checks = {'lines': total, 'per_stream': {k: len(v['lines']) for k, v in d['streams'].items()},
              'institutes_walked': {k: v['institutes'] for k, v in d['streams'].items()},
              'serial_1_to_n_per_institute': True, 'allotment_dates': dates,
              'page_rank_is': {'mdms': 'UP state merit rank (SrNo of the MD/MS/Diploma merit list)',
                               'dnb': 'NEET AIR'}, 'page_rank_matches': dict(rank_page),
              'rank_ai_from_merit_list': sum(1 for r in rows if r['rank_ai']),
              'reserved_seats_to_matching_category': True,
              'quota': C('quota'), 'category': C('allotted_category'), 'section': C('section'),
              'colleges': len({r['institute_raw'] for r in rows}), 'not_in_2025_spellings': not_2025,
              'fetched_at': d['fetched_at'], 'merit_files': d['merit_files']}
    rnd = opt.get('--round') or 'Round 1'
    body = {'authority_code': 'dmetup', 'year': '2026-27', 'round': rnd, 'round_order': int(opt.get('--round-order') or 1),
            'status': opt.get('--status') or 'final',
            'title': f'UP NEET PG 2026 {rnd} — Institute Wise Allotted Candidates (MD/MS/Diploma + DNB / Post-MBBS Diploma)',
            'published_on': pub, 'source_file_name': d['source'],
            'notes': ('No PDF published: read from upneet.gov.in "Allotted Candidate List → Allotted and Vacant Seat → '
                      'Institute Wise Allotted Candidates Round- 1" (MDMS and DNB streams, every institute), fetched '
                      f"{d['fetched_at']}. Names / roll numbers not kept. rank = UP state merit rank, rank_ai = NEET AIR "
                      '(both from the UP Round 1 state merit lists by roll). UP prints no provisional/final label.'),
            'rows': rows, 'checks': checks}
    json.dump(body, open(out_path, 'w'), indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in checks.items()}, indent=1, ensure_ascii=False))
    print('wrote', out_path, len(rows), 'rows')


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ('fetch', 'build'):
        raise SystemExit(__doc__)
    opt = {}
    for k in ('--merit-mdms', '--merit-dnb', '--round', '--round-order', '--status', '--published-on'):
        if k in args:
            i = args.index(k); opt[k] = args[i + 1]; del args[i:i + 2]
    if args[0] == 'fetch':
        if len(args) != 2 or '--merit-mdms' not in opt or '--merit-dnb' not in opt:
            raise SystemExit(__doc__)
        return fetch(args[1], {'mdms': opt['--merit-mdms'], 'dnb': opt['--merit-dnb']})
    if len(args) != 3:
        raise SystemExit(__doc__)
    build(args[1], args[2], opt)


if __name__ == '__main__':
    main()
