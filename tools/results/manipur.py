"""Manipur (DME Manipur, authority `dhs_manipur`) Round 1 State Level Medical PG Counselling 2026-27 allotment
(a SCAN, notification No. DME-5/1/2026-HEALTH, Imphal 14.11.2026) -> rows for POST /api/pg/results/ingest.

Usage: /usr/bin/python3 manipur.py <allotment.pdf | inbox:<id>> <merit_dir> <out.json>
  <merit_dir> = the nine text-layer merit PDFs (Annexure A..I, 13.11.2026, read_dhs_manipur.py's inputs).
  inbox:<id> fetches the stored PDF from staging (X-News-Key from ~/.goocampus/news_ingest.json) into memory.

The allotment prints Sl. No., Candidate Name, Candidate Category, Is PwD?, Allotted Specialty, Allotted Seat Type -
no rank, no roll. Pages 2.. are read with Apple Vision OCR (Swift helper compiled next to this file's scratch dir;
the page images are rendered IN MEMORY, nothing is written to disk). Each row is matched to ONE row of the merit list
its seat type belongs to, by normalised candidate NAME (case / spacing / punctuation / token order, Cyrillic
look-alikes from the OCR folded to Latin). Names exist only in memory: they are never printed or written; the output
holds the merit rank, the NEET-PG AIR and the seat, nothing personal.

Seat type -> merit list (ranks restart in every list, so quota_raw names the list):
  RIMS_OPEN -> A RIMS Graduate Open (RIMS Imphal)          NON_RIMS_OPEN -> B Non-RIMS Open (RIMS Imphal)
  RIMS_IN_SERVICE -> C RIMS In-service                     JNIMS_DIRECT -> D JNIMS Direct
  JNIMS_INSTITUTIONAL_PREFERENCE -> E JNIMS Inst. Pref.     JNIMS_IN_SERVICE -> F JNIMS In-service
  SAHS_DIRECT -> G SAHS State Quota Direct                 SAHS_IN_SERVICE -> H SAHS State Quota In-service
  SAHS_MGMT -> I SAHS Management Quota
Only a clear match is kept: the normalised name occurs exactly once in the mapped list (and in no other row of the
allotment), and the printed category agrees with the merit list. Anything else keeps rank / rank_ai empty.
The seat category is not printed: allotted_category = the candidate's printed category (as Goa), raw left empty.
"""
import sys, os, re, json, glob, base64, difflib, collections, subprocess, tempfile, urllib.request
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
SWIFT = r'''
import Foundation
import Vision
import PDFKit
let data = FileHandle.standardInput.readDataToEndOfFile()
guard let doc = PDFDocument(data: data) else { fatalError("bad pdf") }
let scale: CGFloat = 4
for i in 0..<doc.pageCount {
    let page = doc.page(at: i)!
    let b = page.bounds(for: .mediaBox)
    let w = Int(b.width * scale), h = Int(b.height * scale)
    let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                        space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1)); ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: ctx)
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: ctx.makeImage()!, options: [:]).perform([req])
    for o in req.results ?? [] {
        guard let c = o.topCandidates(1).first else { continue }
        let bb = o.boundingBox
        let d: [String: Any] = ["p": i + 1, "t": c.string, "x": bb.minX, "y": 1 - bb.maxY, "w": bb.width, "h": bb.height]
        print(String(data: try JSONSerialization.data(withJSONObject: d), encoding: .utf8)!)
    }
}
'''
LISTS = {   # seat type -> (annexure, merit-list title in the PDF, quota, institute)
    'RIMS_OPEN': ('A', 'RIMS GRADUATE OPEN CATEGORY', 'RIMS Open', 'RIMS'),
    'NON_RIMS_OPEN': ('B', 'NON-RIMS OPEN CATEGORY', 'Non-RIMS Open', 'RIMS'),
    'RIMS_IN_SERVICE': ('C', 'RIMS IN-SERVICE CATEGORY', 'RIMS In-service', 'RIMS'),
    'JNIMS_DIRECT': ('D', 'JNIMS DIRECT CATEGORY', 'JNIMS Direct', 'JNIMS'),
    'JNIMS_INSTITUTIONAL_PREFERENCE': ('E', 'JNIMS INSTITUTIONAL PREFERENCE CATEGORY', 'JNIMS Institutional Preference', 'JNIMS'),
    'JNIMS_IN_SERVICE': ('F', 'JNIMS IN-SERVICE CATEGORY', 'JNIMS In-service', 'JNIMS'),
    'SAHS_DIRECT': ('G', 'SAHS STATE QUOTA DIRECT CATEGORY', 'SAHS Direct', 'SAHS'),
    'SAHS_IN_SERVICE': ('H', 'SAHS STATE QUOTA IN-SERVICE CATEGORY', 'SAHS In-service', 'SAHS'),
    'SAHS_MGMT': ('I', 'SAHS MANAGEMENT QUOTA', 'SAHS Management', 'SAHS'),
}
LIST_LABEL = {'A': 'RIMS Graduate Open', 'B': 'Non-RIMS Open', 'C': 'RIMS In-service', 'D': 'JNIMS Direct',
              'E': 'JNIMS Institutional Preference', 'F': 'JNIMS In-service', 'G': 'SAHS State Quota Direct',
              'H': 'SAHS State Quota In-service', 'I': 'SAHS Management Quota'}
INST = {'RIMS': ('Regional Institute of Medical Sciences, Imphal', 'Regional Institute of Medical Sciences, Imphal'),
        'JNIMS': ('Jawaharlal Nehru Institute of Medical Sciences, Porompat, Imphal',
                  'Jawaharlal Nehru Institute of Medical Sciences, Porompet, Imphal'),
        'SAHS': ('Shija Academy of Health Sciences, Langol, Imphal', '')}      # SAHS: left to the name memory
SPEC = {'MD_GENERAL_MEDICINE': 'MD - General Medicine', 'MD_RADIODIAGNOSIS': 'MD - Radio-Diagnosis',
        'MD_PAEDIATRICS': 'MD - Paediatrics', 'MD_RESPIRATORY_MEDICINE': 'MD - Respiratory Medicine',
        'MS_GENERAL_SURGERY': 'MS - General Surgery', 'MS_OBST_GYNAECOLOGY': 'MS - Obstetrics and Gynaecology',
        'MS_ORTHOPAEDICS': 'MS - Orthopaedics', 'MS_OTORHINOLARYNGOLOGY': 'MS - ENT (Otorhinolaryngology)',
        'MS_OPHTHALMOLOGY': 'MS - Ophthalmology', 'MD_ANAESTHESIOLOGY': 'MD - Anaesthesiology',
        'MD_COMMUNITY_MEDICINE': 'MD - Social & Preventive Medicine / Community Medicine',
        'MD_PHYSIOLOGY': 'MD - Physiology', 'MD_DERMATOLOGY_VL': 'MD - Dermatology', 'MD_PSYCHIATRY': 'MD - Psychiatry',
        'MD_RADIATION_ONCOLOGY': 'MD - Radiotherapy / Radiation Oncology', 'MD_SPORTSMEDICINE': 'MD - Sports Medicine',
        'MD_PMR': 'MD - Physical Medicine and Rehabilitation', 'MD_PATHOLOGY': 'MD - Pathology',
        'MD_TRANSFUSION_MEDICINE': 'MD - Transfusion Medicine / Immuno-Haematology and Blood Transfusion',
        'MD_BIOCHEMISTRY': 'MD - Biochemistry', 'MD_MICROBIOLOGY': 'MD - Microbiology',
        'MD_PHARMACOLOGY': 'MD - Pharmacology', 'MD_FORENSIC_MEDICINE': 'MD - Forensic Medicine',
        'MD_ANATOMY': 'MD/MS - Anatomy', 'MD_EMERGENCY_MEDICINE': 'MD - Emergency Medicine'}
CYR = str.maketrans('АВСЕНКМОРТХУаевсорхукмнтІіЈј', 'ABCEHKMOPTXYaeBcopxykMHTIiJj')
CATS = {'GENERAL', 'OBC', 'OBC-M', 'OBC-MP', 'SC', 'ST', 'EWS'}
PWD = {'TRUE': True, 'FALSE': False, 'YES': True, 'NO': False}
SHEET = os.path.join(HERE, '..', '..', 'pg_admin', 'data', 'specialty_sheet.json')


def letters(s):
    return re.sub(r'[^A-Z]', '', s.translate(CYR).upper())


def name_key(s):
    """case / spacing / punctuation / token order insensitive; 'DR' prefix dropped."""
    t = re.sub(r'[^A-Z ]', ' ', s.translate(CYR).upper().replace('.', ' '))
    toks = [w for w in t.split() if w]
    if toks and toks[0] in ('DR', 'DR.'):
        toks = toks[1:]
    return ' '.join(sorted(toks))


def ocr(pdf):
    cache = os.path.join(tempfile.gettempdir(), 'gc_manipur_ocr')
    os.makedirs(cache, exist_ok=True)
    exe = os.path.join(cache, 'ocrpdf')
    if not os.path.exists(exe):
        src = os.path.join(cache, 'ocrpdf.swift')
        open(src, 'w').write(SWIFT)
        subprocess.run(['swiftc', '-O', src, '-o', exe], check=True, capture_output=True)
    out = subprocess.run([exe], input=pdf, capture_output=True, check=True).stdout.decode()
    return [json.loads(l) for l in out.splitlines()]


def best(s, canon, cut):
    """canonical key whose letters are closest to s (ratio >= cut and a clear margin), else None."""
    sc = sorted(((difflib.SequenceMatcher(None, s, letters(k)).ratio(), k) for k in canon), reverse=True)
    if sc and sc[0][0] >= cut and (len(sc) == 1 or sc[0][0] - sc[1][0] >= 0.08):
        return sc[0][1]
    return None


def read_allotment(pdf):
    L = ocr(pdf)
    p1 = ' '.join(l['t'] for l in L if l['p'] == 1)
    if 'Round 1 of State Level Medical' not in p1 or 'Provisional Allotment' not in p1 or 'DME-5/1/2026-HEALTH' not in p1:
        raise SystemExit('notice page changed')
    rows, stats = [], collections.Counter()
    for p in sorted({l['p'] for l in L if l['p'] > 1}):
        ls = [dict(l, t=l['t'].translate(CYR), cy=l['y'] + l['h'] / 2) for l in L if l['p'] == p]
        if not any('LIST OF ALLOTTED CANDIDATES IN ROUND 1' in l['t'] for l in ls):
            raise SystemExit(f'p{p}: annexure title missing')
        hdr = [l for l in ls if re.search(r'Candidate|Allotted|Category|PWD|Type', l['t'], re.I) and l['y'] < 0.16]
        hy = max(l['y'] + l['h'] for l in hdr if not re.search(r'_', l['t']))
        xname = min(l['x'] for l in hdr if 'Candidate Name' in l['t'])
        xcat = min([l['x'] for l in hdr if l['t'].strip() in ('Candidate', 'Category')] or [9])
        body = [l for l in ls if l['cy'] > hy and l['y'] < 0.93 and not l['t'].startswith('Page')]
        seats, rest = [], []
        for l in body:
            k = best(letters(l['t']), LISTS, 0.85) if l['x'] > 0.45 and len(letters(l['t'])) >= 7 else None
            (seats if k else rest).append(dict(l, seat=k) if k else l)
        seats.sort(key=lambda l: l['cy'])
        if not seats:
            raise SystemExit(f'p{p}: no seat types')
        pitch = min([b['cy'] - a['cy'] for a, b in zip(seats, seats[1:])] or [0.023])
        if pitch < 0.012:
            raise SystemExit(f'p{p}: two seat types on one line')
        grp = [{'seat': s['seat'], 'cy': s['cy'], 'items': []} for s in seats]
        for l in rest:
            g = min(grp, key=lambda g: abs(g['cy'] - l['cy']))
            if abs(g['cy'] - l['cy']) > 0.6 * max(pitch, 0.02):
                stats['stray_lines'] += 1
                continue
            g['items'].append(l)
        for g in grp:
            ser, cat, pwd, spec, name = [], [], [], [], []
            for l in sorted(g['items'], key=lambda l: (l['y'], l['x'])):
                t = l['t'].strip()
                if re.match(r'^\d{1,3}\.?$', t) and l['x'] < xname:
                    ser.append(int(t.rstrip('.')))
                elif t.upper() in PWD and l['x'] > 0.38:
                    pwd.append(PWD[t.upper()])
                elif t.upper() in CATS and l['x'] > 0.3:
                    cat.append(t.upper())
                elif l['x'] > 0.45 and letters(t)[:2] in ('MD', 'MS', 'IM') and best(letters(t).lstrip('I'), SPEC, 0.85):
                    spec.append(best(letters(t).lstrip('I'), SPEC, 0.85))
                elif l['x'] < xcat - 0.02:
                    name.append(t)
                else:
                    stats['unclassified_lines'] += 1
                    g['bad'] = True
            if len(spec) != 1 or len(cat) > 1 or len(pwd) > 1 or len(ser) > 1 or not name:
                g['bad'] = True
            rows.append({'page': p, 'seat': g['seat'], 'ser': ser[0] if ser else None, 'cat': cat[0] if cat else '',
                         'pwd': pwd[0] if pwd else None, 'spec': spec[0] if len(spec) == 1 else None,
                         'name': ' '.join(name), 'bad': bool(g.get('bad'))})
    # serial numbers: one run 1..n per seat type (a list may go over a page); OCR'd serials must agree
    seq, last, mism = collections.Counter(), None, 0
    for r in rows:
        if r['seat'] != last and seq[r['seat']]:
            raise SystemExit(f"seat type {r['seat']} printed in two places")
        last = r['seat']
        seq[r['seat']] += 1
        if r['ser'] is not None and r['ser'] != seq[r['seat']]:
            mism += 1
        r['sl'] = seq[r['seat']]
    stats['serial_ocr_disagree'] = mism
    stats['serial_ocr_read'] = sum(1 for r in rows if r['ser'] is not None)
    return rows, stats


def read_merit(merit_dir):
    by = {}
    for f in sorted(glob.glob(os.path.join(merit_dir, '*.pdf'))):
        d = fitz.open(f)
        t0 = ' '.join(d[0].get_text().split())
        m = re.search(r'MERIT LIST OF CANDIDATES APPLYING FOR (.+?) ANNEXURE-([A-I])\b', t0)
        if not m:
            continue
        ann = m.group(2)
        if not any(v[0] == ann and v[1] == m.group(1) for v in LISTS.values()):
            raise SystemExit(f'{os.path.basename(f)}: title not understood')
        recs = []
        for p in d:
            for t in p.find_tables().tables:
                for r in t.extract():
                    c = [' '.join((x or '').split()) for x in r]
                    if len(c) < 5 or not re.match(r'^2666\d{7}$', c[1]):
                        continue
                    if len(c) == 5:
                        cat, pwd = '', False
                    else:
                        cat = c[3] + ('' if c[4] == '-' else '/' + c[4])
                        pwd = c[5] in ('YES', 'TRUE')
                    recs.append({'rank': int(c[0]), 'air': int(c[-1]), 'name': c[2], 'cat': cat, 'pwd': pwd})
        if [r['rank'] for r in recs] != list(range(1, len(recs) + 1)):
            raise SystemExit(f'{ann}: ranks not 1..n')
        by[ann] = recs
    if sorted(by) != list('ABCDEFGHI'):
        raise SystemExit(f'merit lists found: {sorted(by)}')
    return by


def cat_agrees(allot_cat, merit_cat):
    if not allot_cat or not merit_cat:
        return True                      # not printed (blank cell / management list)
    main, _, sub = merit_cat.partition('/')
    return allot_cat in (main, sub)


def main():
    a = sys.argv[1:]
    close = set()          # founder-approved close-spelling matches, e.g. --close A:10,A:16 (annexure:Sl)
    if '--close' in a:
        i = a.index('--close')
        close = {(x.split(':')[0], int(x.split(':')[1])) for x in a[i + 1].split(',') if x}
        del a[i:i + 2]
    if len(a) != 3:
        raise SystemExit(__doc__)
    src, merit_dir, out = a
    if src.startswith('inbox:'):
        key = json.load(open(os.path.expanduser('~/.goocampus/news_ingest.json')))['key']
        pdf = urllib.request.urlopen(urllib.request.Request(
            'https://goocampus-hr-portal-staging.onrender.com/api/pg/news-inbox/stored-pdf?id=' + src[6:],
            headers={'X-News-Key': key, 'User-Agent': 'gc'}), timeout=300).read()
        pdf_name = f'Manipur-PG-2026-R1-Allotment-inbox{src[6:]}.pdf'
    else:
        pdf = open(src, 'rb').read()
        pdf_name = os.path.basename(src)
    approved = {c['course'] for c in json.load(open(SHEET))['courses']}
    if not set(SPEC.values()) <= approved:
        raise SystemExit('course not in specialty sheet')
    rows, stats = read_allotment(pdf)
    merit = read_merit(merit_dir)
    keys = {ann: collections.Counter(name_key(r['name']) for r in recs) for ann, recs in merit.items()}
    allot_keys = collections.Counter(name_key(r['name']) for r in rows)
    res = collections.Counter()
    per_list = collections.defaultdict(list)
    out_rows = []
    used = set()
    for i, r in enumerate(rows):
        ann, _, quota, inst = LISTS[r['seat']]
        k = name_key(r['name'])
        hit = None
        if r['bad'] or not k:
            why = 'unmatched_ocr_row'
        elif keys[ann][k] > 1 or allot_keys[k] > 1:
            why = 'ambiguous_same_name'
        elif keys[ann][k] == 0 and (ann, r['sl']) in close:
            kl = k.replace(' ', '')
            sc = sorted(((difflib.SequenceMatcher(None, kl, name_key(m['name']).replace(' ', '')).ratio(), m['rank'])
                         for m in merit[ann]), reverse=True)
            hit = next(m for m in merit[ann] if m['rank'] == sc[0][1])
            if (sc[0][0] < 0.85 or sc[0][0] - sc[1][0] < 0.2 or not cat_agrees(r['cat'], hit['cat'])
                    or (ann, hit['rank']) in used):
                raise SystemExit(f"approved close match {ann} Sl {r['sl']} no longer clear")
            why = 'matched_close_spelling'
            used.add((ann, hit['rank']))
            close.discard((ann, r['sl']))
        elif keys[ann][k] == 0:
            why = 'unmatched_no_name' if not any(keys[o][k] for o in keys) else 'unmatched_in_other_list_only'
        else:
            hit = next(m for m in merit[ann] if name_key(m['name']) == k)
            if not cat_agrees(r['cat'], hit['cat']):
                why, hit = 'unmatched_category_disagrees', None
            elif (ann, hit['rank']) in used:
                why, hit = 'ambiguous_merit_row_twice', None
            else:
                why = 'matched'
                used.add((ann, hit['rank']))
        res[why] += 1
        if hit:
            per_list[ann].append((r['sl'], hit['rank']))
        cat = r['cat'] or (hit['cat'].split('/')[-1] if hit and hit['cat'] else '')
        pw = r['pwd'] if r['pwd'] is not None else (hit['pwd'] if hit else False)
        acat = (cat + ' PwD' if pw else cat) if cat else ''
        iraw, istd = INST[inst]
        out_rows.append({
            'sno': i + 1, 'rank': hit['rank'] if hit else None, 'rank_ai': hit['air'] if hit else None,
            'quota_raw': f"{r['seat']} (merit list Annexure {ann})", 'quota': quota,
            'institute_raw': iraw, 'institute': istd, 'course_raw': r['spec'] or '', 'course': SPEC.get(r['spec'], ''),
            'section': 'mdms', 'allotted_category': acat, 'allotted_category_raw': '',
            'candidate_category': acat,
            'remarks': f"Merit list: Annexure {ann} - {LIST_LABEL[ann]}; Sl. {r['sl']} of {r['seat']}"
                       + ('' if hit else '; rank not matched')
                       + ('; rank matched on a close spelling' if why == 'matched_close_spelling' else '')})
    if close:
        raise SystemExit(f'approved close matches not found: {sorted(close)}')
    order = {}
    for ann, pr in sorted(per_list.items()):
        rk = [b for _, b in sorted(pr)]
        inc = sum(1 for x, y in zip(rk, rk[1:]) if y > x)
        order[ann] = {'matched': len(rk), 'increasing_pairs': f'{inc}/{max(len(rk) - 1, 0)}',
                      'ranks': rk}
    del rows, merit, keys, allot_keys          # names leave memory here
    checks = {'rows': len(out_rows), 'ocr': dict(stats), 'match': dict(res),
              'by_seat_type': dict(collections.Counter(r['quota_raw'] for r in out_rows)),
              'by_course': dict(collections.Counter(r['course'] or '?' for r in out_rows).most_common()),
              'by_category': dict(collections.Counter(r['allotted_category'] or '?' for r in out_rows).most_common()),
              'merit_order': order,
              'rank_ai_filled': sum(1 for r in out_rows if r['rank_ai'])}
    body = {'authority_code': 'dhs_manipur', 'round': 'Round 1', 'round_order': 1, 'status': 'provisional',
            'title': 'Manipur PG Medical Counselling 2026 — Provisional Allotment, Round 1',
            'published_on': '2026-11-14', 'source_file_name': pdf_name, 'pdf_name': pdf_name,
            'pdf_b64': base64.b64encode(pdf).decode(),
            'notes': ('DME Manipur Round 1 State Level Medical PG Counselling 2026-27, list of allotted candidates '
                      '(notification DME-5/1/2026-HEALTH, Imphal 14.11.2026; candidates download the Provisional '
                      'Allotment letter and Freeze/Float/Reject). The scan prints no rank or roll: each row was matched '
                      'by candidate name to the Round 1 merit list (Annexure A-I, 13.11.2026) of its seat type - rank = '
                      'State Merit Rank WITHIN that list (ranks restart per list; quota_raw names the list), rank_ai = '
                      'NEET-PG AIR from that list. Rows without a clear unique match keep no rank; a few rows whose '
                      'OCR spelling differs slightly were matched on a close spelling after review (see remarks). Seat category is not '
                      'printed: category = the candidate category. No names or roll numbers stored.'),
            'rows': out_rows, 'checks': checks}
    json.dump(body, open(out, 'w'), indent=1, ensure_ascii=False)
    print(out)
    print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
