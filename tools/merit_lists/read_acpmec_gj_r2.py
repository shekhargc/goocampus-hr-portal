"""Gujarat ACPPGMEC "Provisional Merit list for M.D/M.S/Diploma Courses For the year 2026-27" — ROUND 2 lists of
17.11.2026 (inbox 1757 GENERAL, 1758 SC, 1759 ST, 1760 SEBC, 1761 EWS, 1762 SC CATEGORY IN SERVICE) -> rank-bridge rows.
(The Round 1 reader module sm4_gj.py is no longer on disk; this reader is self-contained.)

Columns printed: User ID, Roll No, GEN MERIT, CAT MERIT, [Uni. MERIT, Uni.Cat MERIT | in-service column], All India
Overall Rank, Score, NAME, Pass Institute Name, Remark. Read ONLY Roll No, GEN MERIT, CAT MERIT, Uni.Cat MERIT,
All India Overall Rank and Score (by x position from each page's header words; rows anchored on the 2666xxxxxxx roll,
whose other cells sit up to ~3 pt above/below). Name, institute, user ID and remarks are never read.

GENERAL list -> one row per candidate: state_rank = floor(GEN MERIT) (half merits like 256.50 = inserted rows, as in
Round 1), air = All India Overall Rank, score, category = SE->SEBC / EW->EWS / SC / ST from CAT MERIT (else Uni.Cat
MERIT, else OPEN), quota ''. The four category lists are NOT stored separately (every candidate is in the general
list); they are used to check: every roll in a category list is in the general list with that category.
SC IN-SERVICE list -> its own rows (quota 'In-service', category SC).
Usage: /usr/bin/python3 read_acpmec_gj_r2.py <general.pdf> <sc.pdf> <st.pdf> <sebc.pdf> <ews.pdf> <sc_inservice.pdf> <out_dir>"""
import sys, os, re, json, math, collections
import fitz

ROLL = re.compile(r'^2666\d{7}$')
NUM = re.compile(r'^\d+(\.\d+)?$')
CATP = {'SE': 'SEBC', 'EW': 'EWS', 'SC': 'SC', 'ST': 'ST'}
TITLE = 'Provisional Merit list for M.D/M.S/Diploma Courses For the year 2026-27'


def read(path, want_title):
    d = fitz.open(path)
    t0 = ' '.join(d[0].get_text().split())
    if 'ACPPGMEC' not in t0 or TITLE not in t0 or want_title not in t0:
        raise SystemExit(f'{os.path.basename(path)}: title changed')
    recs, text_rolls = [], 0
    for p in d:
        ws = p.get_text('words')
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        roll_h = [w for w in ws if w[4] == 'Roll']
        if len(roll_h) != 1:
            raise SystemExit(f'{os.path.basename(path)} p{p.number + 1}: header row not found')
        hdr = {w[4]: w for w in ws if w[4] in ('Roll', 'GEN', 'CAT', 'All', 'Score', 'NAME', 'Uni.Cat')
               and abs(w[3] - roll_h[0][3]) < 3}                  # header words on the 'Roll' line only
        for k in ('Roll', 'GEN', 'CAT', 'All', 'Score', 'NAME'):
            if k not in hdr:
                raise SystemExit(f'{os.path.basename(path)} p{p.number + 1}: header {k} missing')
        x = {k: v[0] for k, v in hdr.items()}
        hy = hdr['Roll'][3]
        for a in sorted([w for w in ws if ROLL.match(w[4]) and w[1] > hy], key=lambda w: w[1]):
            cy = (a[1] + a[3]) / 2
            band = [w for w in ws if abs((w[1] + w[3]) / 2 - cy) <= 4.5 and w is not a]
            pick = lambda lo, hi: [w[4] for w in band if lo <= w[0] < hi]
            gen = pick(x['GEN'] - 14, x['CAT'] - 10)
            cat = pick(x['CAT'] - 10, (x['Uni.Cat'] - 50) if 'Uni.Cat' in x else x['CAT'] + 44)
            ucat = pick(x['Uni.Cat'] - 6, x['All'] - 12) if 'Uni.Cat' in x else []
            air = pick(x['All'] - 12, x['Score'] - 6)
            sc = pick(x['Score'] - 6, x['NAME'] - 6)
            if not (len(gen) == 1 and NUM.match(gen[0]) and len(air) == 1 and NUM.match(air[0]) and len(sc) == 1
                    and re.match(r'^-?\d+(\.\d+)?$', sc[0]) and len(cat) <= 1 and len(ucat) <= 1):
                raise SystemExit(f'{os.path.basename(path)} p{p.number + 1}: row shape near GEN {gen} AIR {air}')
            cc = [c[:2] for c in cat + ucat if re.match(r'^(SE|EW|SC|ST)-', c)]
            recs.append({'roll': a[4], 'gen': float(gen[0]), 'air': float(air[0]), 'score': float(sc[0]),
                         'cat': cat[0] if cat else '', 'catp': cc[0] if cc else ''})
    if len(recs) != text_rolls:
        raise SystemExit(f'{os.path.basename(path)}: rows {len(recs)} != rolls in text {text_rolls}')
    if len({r['roll'] for r in recs}) != len(recs):
        raise SystemExit(f'{os.path.basename(path)}: duplicate roll')
    return d, recs


def main():
    if len(sys.argv) != 8:
        raise SystemExit(__doc__)
    gen_pdf, sc_pdf, st_pdf, se_pdf, ew_pdf, scis_pdf, out_dir = sys.argv[1:8]
    d, recs = read(gen_pdf, 'GENERAL MERIT LIST')
    by_roll = {r['roll']: r for r in recs}
    rows, frac, airfrac = [], 0, 0
    for r in recs:
        if r['gen'] != int(r['gen']):
            frac += 1
        if r['air'] != int(r['air']):
            airfrac += 1
        rows.append({'roll': r['roll'], 'air': int(r['air']), 'state_rank': int(math.floor(r['gen'])), 'score': r['score'],
                     'category': CATP.get(r['catp'], 'OPEN'), 'quota': ''})
    gens = [r['gen'] for r in recs]
    checks = {'general': {'file': os.path.basename(gen_pdf), 'pages': d.page_count, 'rows': len(rows),
                          'gen_merit_ascending_in_print_order': all(b >= a for a, b in zip(gens, gens[1:])),
                          'half_merit_rows': frac, 'air_not_integer': airfrac,
                          'by_category': dict(collections.Counter(r['category'] for r in rows))}}
    for path, title, cat in ((sc_pdf, 'SC MERIT LIST', 'SC'), (st_pdf, 'ST MERIT LIST', 'ST'),
                             (se_pdf, 'SEBC MERIT LIST', 'SEBC'), (ew_pdf, 'EWS MERIT LIST', 'EWS')):
        _, cr = read(path, title)
        missing = sum(1 for r in cr if r['roll'] not in by_roll)
        wrong = sum(1 for r in cr if r['roll'] in by_roll and CATP.get(by_roll[r['roll']]['catp']) != cat)
        same_air = sum(1 for r in cr if r['roll'] in by_roll and by_roll[r['roll']]['air'] == r['air'])
        checks[cat] = {'file': os.path.basename(path), 'rows': len(cr), 'not_in_general': missing,
                       'general_category_differs': wrong, 'air_same_as_general': same_air,
                       'general_rows_with_this_category': sum(1 for r in rows if r['category'] == cat)}
        if missing or wrong:
            raise SystemExit(f'{cat} list disagrees with the general list: {checks[cat]}')
    _, isr = read(scis_pdf, 'SC CATEGORY IN SERVICE MERIT LIST')
    is_rows = [{'roll': r['roll'], 'air': int(r['air']), 'state_rank': int(math.floor(r['gen'])), 'score': r['score'],
                'category': 'SC', 'quota': 'In-service'} for r in isr]
    checks['sc_in_service'] = {'file': os.path.basename(scis_pdf), 'rows': len(is_rows),
                               'in_general_list': sum(1 for r in isr if r['roll'] in by_roll)}
    common = {'authority_code': 'acpmec', 'published_on': '2026-11-17'}
    gen_obj = dict(common, list_name='Round 2 Provisional General Merit List', source_file_name=os.path.basename(gen_pdf),
                   notes=('ACPPGMEC Gujarat MD/MS/Diploma 2026-27 Round 2 provisional GENERAL merit list (17.11.2026). '
                          'state_rank = GEN MERIT (half merits = inserted rows, stored as floor); air = All India Overall '
                          'Rank; category from CAT MERIT (SC/ST/SEBC/EWS lists checked: every roll present with the same '
                          'category). The Round 1 general list stays loaded under its own name.'),
                   row_count=len(rows), checks=checks, rows=rows)
    is_obj = dict(common, list_name='Round 2 Provisional SC In-Service Merit List', source_file_name=os.path.basename(scis_pdf),
                  notes='ACPPGMEC Gujarat Round 2 provisional SC CATEGORY IN SERVICE merit list (17.11.2026). '
                        'state_rank = GEN MERIT; quota In-service.',
                  row_count=len(is_rows), checks=checks['sc_in_service'], rows=is_rows)
    for name, obj in (('acpmec_r2_general.json', gen_obj), ('acpmec_r2_sc_inservice.json', is_obj)):
        json.dump(obj, open(os.path.join(out_dir, name), 'w'), indent=1)
    print(json.dumps(checks, indent=1))


if __name__ == '__main__':
    main()
