"""Andhra Pradesh (Dr NTRUHS) PG (Medical) COMPETENT AUTHORITY QUOTA (CQ) seat matrix 2026-27 -> standardised seat
rows for the body "Andhra Pradesh — State Counselling" (authority `ntruhs`, section state, round 1).

Usage: /usr/bin/python3 andhra_pradesh_cq.py <folder with the 18 PDFs> <cutoffs2025.json> <out.json> [--allot <allot_cells.json>]

Source: the web page https://drntr.uhsap.in/index/pgmedicalseatmatrix2026 (NOT the notification list, which is why the
news fetcher never saw it) links 18 PDFs: seat matrices for AU / SVU / SWI (state-wide institutions) / Minority, each
Non-Service and Service, the matching "NET GROUP" PDFs, and a Revised AU set (Govt Memo 2593460/C1/2024 dt 11-11-2026,
MD Radio-Diagnosis seats). The REVISED AU matrices replace the original AU ones (both are archived, inbox 1797-1814).

Layouts (cells via common.grids, blank = 0):
  AU / SVU: SNO, COLLEGE (code), AREA (AU|SVU), COURSE (code), SEAT_TYPE (L = local seats of that university area,
            APUR = unreserved), S_NS, 42 category columns (OC_G … BC_E_PH_F, SC_POOL, BC_POOL), '<course> Total' rows.
  SWI:      SNO, COLLEGE, AREA (AU|SVU = local seats of that area, APUR = unreserved), COURSE, S_NS, 42 columns.
  Minority: SNO, COLLEGE, AREA, COURSE, CATEGORY (CLDG …), SEAT_TYPE, S_NS, MINORITY; '<college> Total' rows.
NET GROUP = the same seats summed per course × category for the whole matrix (= the '<course> Total' rows) — it is a
CROSS-CHECK, not extra seats. Every course's seat-matrix total must equal its NET GROUP line, column by column.

Quota (2025 AP spellings): 'Govt Quota - <Non Service|Service>-<AU|SVU|SWI>-<Local|APUR>' — the seat's university area
and whether it is local or unreserved (in 2025 the first part was the CANDIDATE's area; the bridge accepts any candidate
area for APUR seats). Category: OC_PH_G -> OC-G-PH, BC_A_F -> BCA-F, SC1_G -> SC1-G, SC_POOL / BC_POOL kept as
SC-POOL / BC-POOL (allotted to any SC / BC sub-group by merit); minority seats MIN-G-MSM.
Colleges: codes -> 2025 cut-off names (codes cross-checked against the CQ allotment lists, which print both).
FM = MD Forensic Medicine (NET GROUP lists it under non-clinical degrees), FAM = MD Family Medicine, HA = MD Hospital
Administration (non-clinical degree). Strict: unknown code / course / column / a total that doesn't match -> SystemExit.
"""
import sys, os, json, re, collections
import fitz
sys.path.insert(0, os.path.dirname(__file__))
from common import grids, clean, load_cuts, build, report

COLLEGES = {
    'ACSR': 'ACSR Government Medical College, Nellore', 'AMCV': 'Andhra Medical College, Visakhapatnam',
    'APLC': 'Apollo Institute of Medical Sciences and Research, Chittoor',
    'ASRA': 'Alluri Seetharama Raju Academy of Medical Sciences, Eluru',
    'BMCT': 'Sri Balaji Medical College Hospital and Research Institute, Renigunta, Tirupati',
    'FIMS': 'Fathima Institute of Medical Sciences, Kadapa', 'GEMS': 'Great Eastern Medical School and Hospital, Srikakulam',
    'GMCA': 'Government Medical College, Ananthapuram', 'GMCE': 'Government Medical College, Eluru',
    'GMCG': 'Guntur Medical College, Guntur', 'GMCK': 'Government Medical College, Kadapa',
    'GMCM': 'Government Medical College, Machilipatnam', 'GMCN': 'Government Medical College, Nandyal',
    'GMCO': 'Government Medical College, Ongole', 'GMCR': 'Government Medical College, Rajamahendravaram',
    'GMCS': 'Government Medical College, Srikakulam', 'GMCV': 'Government Medical College, Vizianagaram',
    'GSLR': 'GSL Medical College, Rajahmundry',
    'GVPT': 'Gayatri Vidya Parishad Institute of Health Care and Medical Technology, Visakhapatnam',
    'HCRV': 'Homi Bhabha Cancer Hospital and Research Centre, Visakhapatnam',
    'KATR': 'Katuri Medical College and Hospital, Guntur', 'KMCK': 'Kurnool Medical College, Kurnool',
    'KONA': 'Konasema Institute of Medical Sciences and Research Foundation, Amalapuram',
    'MAHA': 'Maharaja Institute of Medical Sciences, Vizianagaram', 'NARN': 'Narayana Medical College, Nellore',
    'NIMR': 'Nimra Institute of Medical Sciences, Vijayawada', 'NRIM': 'NRI Medical College, Chinnakakani',
    'NRVP': 'NRI Institute of Medical Sciences, Visakhapatnam',
    'PESK': 'P.E.S. Institute of Medical Sciences and Research, Kuppam',
    'PSIM': 'Dr. Pinnamaneni Siddhartha Institute of Medical Sciences, Gannavaram',
    'RMCK': 'Rangaraya Medical College, Kakinada', 'SMCV': 'Siddartha Medical College, Vijayawada',
    'SRMC': 'Santhiram Medical College, Nandyal', 'SVIM': 'Sri Venkateswara Institute of Medical Sciences, Tirupati (SVIMS)',
    'SVMC': 'Sri Venkateswara Medical College, Tirupati', 'VMCK': 'Viswabharathi Medical College, Kurnool'}
COURSES = {   # upper-cased seat-matrix code -> (approved course, section)
    'ANAT': ('MD/MS - Anatomy', 'mdms'), 'ANES': ('MD - Anaesthesiology', 'mdms'), 'BIO': ('MD - Biochemistry', 'mdms'),
    'DVL': ('MD - Dermatology', 'mdms'), 'EM': ('MD - Emergency Medicine', 'mdms'),
    'ENT': ('MS - ENT (Otorhinolaryngology)', 'mdms'), 'GM': ('MD - General Medicine', 'mdms'),
    'GS': ('MS - General Surgery', 'mdms'), 'MICRO': ('MD - Microbiology', 'mdms'),
    'OBG': ('MS - Obstetrics and Gynaecology', 'mdms'), 'OPTHAL': ('MS - Ophthalmology', 'mdms'),
    'ORTHO': ('MS - Orthopaedics', 'mdms'), 'PAED': ('MD - Paediatrics', 'mdms'), 'PATH': ('MD - Pathology', 'mdms'),
    'PHARM': ('MD - Pharmacology', 'mdms'), 'PHY': ('MD - Physiology', 'mdms'), 'PM': ('MD - Respiratory Medicine', 'mdms'),
    'PSY': ('MD - Psychiatry', 'mdms'), 'RD': ('MD - Radio-Diagnosis', 'mdms'),
    'RT': ('MD - Radiotherapy / Radiation Oncology', 'mdms'),
    'SPM': ('MD - Social & Preventive Medicine / Community Medicine', 'mdms'),
    'FM': ('MD - Forensic Medicine', 'mdms'), 'FAM': ('MD - Family Medicine', 'mdms'),
    'HA': ('MD - Hospital Administration', 'mdms'), 'NM': ('MD - Nuclear Medicine', 'mdms'),
    'TM': ('MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion', 'mdms'),
    'DCP': ('Diploma in Pathology', 'diploma'), 'DPH': ('Diploma in Public Health', 'diploma'),
    'DPM': ('Diploma in Psychological Medicine', 'diploma'), 'DDVL': ('Diploma in Dermatology', 'diploma'),
    'DLO': ('Diploma in ENT', 'diploma')}
TOTAL_ALIAS = {'HOSA': 'HA', 'OPTH': 'OPTHAL'}   # '<course> Total' labels printed differently from the row code
CATCOLS = ['OC_G', 'OC_F', 'OC_PH_G', 'OC_PH_F'] + [f'{s}_{x}' for s in ('SC1', 'SC2', 'SC3') for x in ('G', 'F', 'PH_G', 'PH_F')] + \
          ['SC_POOL', 'ST_G', 'ST_F', 'ST_PH_G', 'ST_PH_F'] + \
          [f'BC_{s}_{x}' for s in 'ABCDE' for x in ('G', 'F', 'PH_G', 'PH_F')] + ['BC_POOL']
FILES = {   # (region, S/NS) -> (seat matrix file, net group file); revised AU replaces the original AU
    ('AU', 'NS'): ('revised_PG_(Medical)_CQ_2026-27_-_AU_Non-Service_Seat_Matrix_-_Revised.pdf', 'revised_AU_NET_GROUP_Non-Service_-_Revised.pdf'),
    ('AU', 'S'): ('revised_PG_(Medical)_CQ_2026-27_-_AU_Service_Seat_Matrix_-_Revised.pdf', 'revised_AU_NET_GROUP_Service_-_Revised.pdf'),
    ('SVU', 'NS'): ('PG_(Medical)_CQ_2026-27_-_SVU_Non-Service_Seat_Matrix.pdf', 'SVU_NET_GROUP_-_NON-SERVICE_-_2026-27.pdf'),
    ('SVU', 'S'): ('PG_(Medical)_CQ_2026-27_-_SVU_Service_Seat_Matrix.pdf', 'SVU_NET_GROUP_-_SERVICE_-_2026-27.pdf'),
    ('SWI', 'NS'): ('PG_(Medical)_CQ_2026-27_-_SWI_Non-Service_Seat_Matrix.pdf', 'SWI_NET_GROUP_-_NON-SERVICE_-_2026-27.pdf'),
    ('SWI', 'S'): ('PG_(Medical)_CQ_2026-27_-_SWI_Service_Seat_Matrix.pdf', 'SWI_NET_GROUP_-_SERVICE_-_2026-27.pdf'),
    ('MIN', 'NS'): ('PG_(Medical)_CQ_2026-27_-_Minority_Non-Service_Seat_Matrix.pdf', None),
    ('MIN', 'S'): ('PG_(Medical)_CQ_2026-27_-_Minority_Service_Seat_Matrix.pdf', None)}


def cat_label(col):
    if col.endswith('_POOL'):
        return col.replace('_POOL', '-POOL')
    m = re.fullmatch(r'(OC|SC[123]|ST|BC_[A-E])_(PH_)?([GF])', col)
    if not m:
        raise SystemExit(f'unknown category column {col}')
    return m.group(1).replace('_', '') + '-' + m.group(3) + ('-PH' if m.group(2) else '')


num = lambda s: int(s) if (s or '').strip().isdigit() else (0 if not (s or '').strip() else None)


def read_matrix(path, region, sns):
    """-> (rows, per-course totals {course_code: [42]})"""
    d = fitz.open(path)
    rows, printed, summed = [], {}, collections.defaultdict(lambda: [0] * len(CATCOLS))
    for p in d:
        for t in grids(p):
            hdr = [clean(h) for h in t[0]]
            if hdr[:2] != ['SNO', 'COLLEGE']:
                raise SystemExit(f'{os.path.basename(path)} p{p.number + 1}: header {hdr[:6]}')
            has_type = 'SEAT_TYPE' in hdr
            cols = [{'SC_POOL_G': 'SC_POOL'}.get(c, c) for c in hdr[hdr.index('S_NS') + 1:]]   # SWI Service spelling
            if cols != CATCOLS:
                raise SystemExit(f'{os.path.basename(path)} p{p.number + 1}: category columns changed')
            base = hdr.index('S_NS') + 1
            for r in t[1:]:
                r = [clean(x) for x in r]
                tot = next((x for x in r[:4] if x.endswith(' Total')), None)
                if tot:
                    vals = [num(x) for x in r[base:]]
                    if None in vals:
                        raise SystemExit(f'{path}: bad total row {r}')
                    lab = tot[:-6].upper()
                    printed[TOTAL_ALIAS.get(lab, lab)] = vals
                    continue
                if not r[0].isdigit():
                    continue
                code, area, course = r[1], r[2], r[3].upper()
                s_ns = r[hdr.index('S_NS')]
                if code not in COLLEGES or course not in COURSES or s_ns != sns:
                    raise SystemExit(f'{os.path.basename(path)}: unknown college / course / S_NS {code} {course} {s_ns}')
                if has_type:
                    st = r[hdr.index('SEAT_TYPE')]
                    if area != region or st not in ('L', 'APUR'):
                        raise SystemExit(f'{os.path.basename(path)}: area / seat type {area} {st}')
                    q_area, local = region, st == 'L'
                else:                                   # SWI: AREA = seat area
                    if area not in ('AU', 'SVU', 'APUR'):
                        raise SystemExit(f'{os.path.basename(path)}: SWI area {area}')
                    q_area, local = ('SWI', False) if area == 'APUR' else (area, True)
                vals = [num(x) for x in r[base:]]
                if None in vals:
                    raise SystemExit(f'{os.path.basename(path)}: non-number cell in row {r[:6]}')
                for i, v in enumerate(vals):
                    summed[course][i] += v
                    if v:
                        rows.append({'code': code, 'college': COLLEGES[code], 'course_code': course,
                                     'course': COURSES[course][0], 'section': COURSES[course][1],
                                     'quota': f"Govt Quota - {'Non Service' if sns == 'NS' else 'Service'}-{q_area}-"
                                              f"{'Local' if local else 'APUR'}",
                                     'seat_area': area if (local or not has_type) else 'APUR',
                                     'category': cat_label(CATCOLS[i]), 'seats': v, 'sns': sns})
    bad = {k: (summed.get(k), v) for k, v in printed.items() if summed.get(k, [0] * len(CATCOLS)) != v}
    if bad:
        raise SystemExit(f'{os.path.basename(path)}: course totals differ {list(bad)[:5]}')
    missing = set(summed) - set(printed)
    if missing:
        raise SystemExit(f'{os.path.basename(path)}: no Total row for {sorted(missing)}')
    return rows, dict(summed)


def read_minority(path, sns):
    d = fitz.open(path)
    rows, printed, summed = [], {}, collections.Counter()
    for p in d:
        for t in grids(p):
            hdr = [clean(h) for h in t[0]]
            if hdr != ['SNO', 'COLLEGE', 'AREA', 'COURSE', 'CATEGORY', 'SEAT_TYPE', 'S_NS', 'MINORITY']:
                raise SystemExit(f'minority header {hdr}')
            for r in t[1:]:
                r = [clean(x) for x in r]
                if r[1].endswith(' Total'):
                    printed[r[1][:-6]] = num(r[7]) or 0; continue
                if not r[0].isdigit():
                    continue
                n = num(r[7])
                if n is None:
                    raise SystemExit(f'minority row count {r}')
                code, area, course, st, s_ns = r[1], r[2], r[3].upper(), r[5], r[6]
                if code not in COLLEGES or course not in COURSES or st not in ('L', 'APUR') or s_ns != sns:
                    raise SystemExit(f'minority row {r}')
                summed[code] += n
                if not n:
                    continue
                rows.append({'code': code, 'college': COLLEGES[code], 'course_code': course, 'course': COURSES[course][0],
                             'section': COURSES[course][1],
                             'quota': f"Govt Quota - {'Non Service' if sns == 'NS' else 'Service'}-{area}-"
                                      f"{'Local' if st == 'L' else 'APUR'}",
                             'seat_area': area if st == 'L' else 'APUR', 'category': 'MIN-G-MSM', 'seats': n, 'sns': sns})
    if {k: v for k, v in summed.items() if v or k in printed} != printed:
        raise SystemExit(f'minority totals {dict(summed)} != {printed}')
    return rows


def read_net(path):
    """NET GROUP: per course code -> [42] (course lines only)."""
    out = {}
    for p in fitz.open(path):
        for t in grids(p):
            rows = [[clean(x) for x in r] for r in t]
            start = next((i for i, r in enumerate(rows) if r[:2] == ['Sub', 'S / NS']), None)   # a title row may come first
            if start is None:
                continue
            for r in rows[start + 1:]:
                code = TOTAL_ALIAS.get((r[0] or '').upper(), (r[0] or '').upper())
                if code in COURSES and r[1] in ('S', 'NS'):
                    vals = [num(x) for x in r[2:2 + len(CATCOLS)]]
                    if None not in vals and len(vals) == len(CATCOLS):
                        out[code] = vals
    return out


def main():
    folder, cuts_path, out_path = sys.argv[1:4]
    rows, checks = [], {'files': {}, 'net_group': {}}
    for (region, sns), (sm, ng) in FILES.items():
        if region == 'MIN':
            r = read_minority(os.path.join(folder, sm), sns)
            checks['files'][f'{region}-{sns}'] = {'rows': len(r), 'seats': sum(x['seats'] for x in r)}
        else:
            r, totals = read_matrix(os.path.join(folder, sm), region, sns)
            net = read_net(os.path.join(folder, ng))
            zero = [0] * len(CATCOLS)                   # an all-zero NET GROUP line = the course has no seats there
            diff = sorted(k for k in set(net) | set(totals) if (net.get(k) or zero) != (totals.get(k) or zero))
            if diff:
                raise SystemExit(f'{region}-{sns}: seat matrix vs NET GROUP differ for {diff}')
            checks['net_group'][f'{region}-{sns}'] = f'{len(net)} courses equal'
            checks['files'][f'{region}-{sns}'] = {'rows': len(r), 'seats': sum(x['seats'] for x in r)}
        rows += r
    # merge identical (college, course, quota, category) lines (none expected, but keep it safe)
    merged = collections.OrderedDict()
    for x in rows:
        k = (x['college'], x['course'], x['quota'], x['category'])
        if k in merged:
            merged[k]['seats'] += x['seats']
        else:
            merged[k] = dict(x)
    rows = list(merged.values())
    cuts = load_cuts(cuts_path, 'Andhra Pradesh')

    def fam(q):
        ns = 'Non Service' if 'Non Service' in q else 'Service'
        area, kind = q.rsplit('-', 2)[-2:]
        if kind == 'Local':
            return (f'Govt Quota - {ns}-{area}-Local$',)
        same = f'Govt Quota - {ns}-{area}-APUR$' if area != 'SWI' else None
        return tuple(x for x in (same, f'Govt Quota - {ns}-AU-APUR$', f'Govt Quota - {ns}-SVU-APUR$',
                                 f'Govt Quota - {ns}-APNL-APUR$') if x)

    def catm(x):
        c = x['category']
        if c.endswith('-POOL'):
            return ()
        return (c,)
    out = build(rows, cuts, 'Andhra Pradesh', 'AP', fam, catm)
    if '--allot' in sys.argv:                       # allotted CQ Round 1 seats must fit the matrix
        cells = json.load(open(sys.argv[sys.argv.index('--allot') + 1]))
        cap = collections.Counter()
        pool = collections.Counter()
        for x in rows:
            k = (x['code'], x['course_code'], x['seat_area'], x['sns'])
            if x['category'] in ('SC-POOL', 'BC-POOL'):
                pool[k + (x['category'][:2],)] += x['seats']
            else:
                cap[k + (x['category'],)] += x['seats']
        over = []
        for code, course, area, cat, sns, n in cells:
            k = (code, course, area, sns, cat)
            room = cap.get(k, 0)
            if n > room:
                grp = 'SC' if cat.startswith('SC') else ('BC' if cat.startswith('BC') else None)
                extra = pool.get((code, course, area, sns, grp), 0) if grp else 0
                if n > room + extra:
                    over.append({'cell': k, 'allotted': n, 'matrix': room, 'pool': extra})
        checks['allotment_fit'] = {'allotted': sum(c[5] for c in cells), 'cells': len(cells), 'over_matrix': len(over),
                                   'examples': over[:15]}
    checks['by_quota'] = dict(collections.Counter())
    for x in out:
        checks['by_quota'][x['quota']] = checks['by_quota'].get(x['quota'], 0) + x['seats']
    checks['seats'] = sum(x['seats'] for x in out)
    checks['colleges'] = len({x['college_name'] for x in out})
    report(out, {})                                  # totals were checked above (course / college Total rows + NET GROUP)
    json.dump({'rows': out, 'checks': checks}, open(out_path, 'w'), indent=1)
    print(json.dumps({k: v for k, v in checks.items() if k != 'by_quota'}, indent=1)[:3000])
    print('seats', checks['seats'], 'rows', len(out), 'colleges', checks['colleges'])


if __name__ == '__main__':
    main()
