"""Himachal Pradesh AMRU "Provisional Merit list of MD/MS/DNB 1st Round Counselling 2026" -> rank-bridge rows.

Usage: /usr/bin/python3 read_amru_hp.py <merit.pdf> [--out DIR]   (writes amru_hp_r1_provisional.json)

Page 1 is the covering notice (No. AMRU/(COE)-Admission-129/2026-27(MD/MS/DNB)-6994, dated 07.11.2026); pages 2..
hold one 14-column table: Sr No, Merit No, Application No, Full Name, Admission Quota, Reservation Category,
NEET ROLL No., NEET Score, All India Merit Rank, Service Incentive (Yes/No), Service Incentive %, NEET Score +
Service Incentive, Management Quota Category, NRI Sponsored.
Read ONLY: merit no., quota, reservation category, roll, NEET score, AIR, incentive, total score, mgmt category,
NRI sponsored. Application No and Full Name are never read into the output.

ONE common merit list across all quotas (merit no. 1..n, ordered by NEET score + service incentive), so it is
stored as one list with quota per row: 'HP Quota - Direct' -> 'HP Direct', 'HP Quota In- service' -> 'In-service',
'Management Quota' -> 'Management', 'NRI Quota' -> 'NRI'. state_rank = merit no.; air = printed All India Merit
Rank (not in merit order for in-service rows - the incentive lifts them); score = 'NEET Score + Service Incentive'
(the merit basis; = NEET score where no incentive). category = Reservation Category as printed.
Strict: anything unexpected -> SystemExit.
"""
import sys, os, re, json, collections
import fitz

DEFAULT_OUT = '/private/tmp/claude-501/-Users-Santosh-Desktop-Claude-Code/19945316-59b6-4770-8040-221aff24a059/scratchpad/nov8/ml/'
ROLL = re.compile(r'^2666\d{7}$')
INT = re.compile(r'^\d+$')
QUOTA = {'HP Quota - Direct': 'HP Direct', 'HP Quota In- service': 'In-service', 'Management Quota': 'Management',
         'NRI Quota': 'NRI'}
RCATS = {'General', 'SC', 'ST', 'EWS', 'OBC', 'Single Girl child', 'Physically Handicapped', 'NRI'}
MCATS = {'General', 'SC', 'ST', 'OBC', 'Physically Handicapped', 'Physically Handicappe d', 'NRI', ''}
HEAD_KEYS = ['Sr', 'Merit', 'Applicat', 'Full', 'Admission', 'Reservation', 'ROLL', 'Score', 'Rank', 'Incentiv',
             'Incenti', 'Score', 'Manageme', 'NRI']


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = sys.argv[1]
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else DEFAULT_OUT
    d = fitz.open(path)
    notice = ' '.join(d[0].get_text().split())
    for need in ('Atal Medical & Research University', 'Provisional Merit list of MD/MS/DNB 1st round', 'NEET PG 2026'):
        if need not in notice:
            raise SystemExit('covering notice changed: missing ' + need)
    m = re.search(r'Dated:\s*(\d{2})\.(\d{2})\.(\d{4})', notice)
    published = f'{m.group(3)}-{m.group(2)}-{m.group(1)}' if m else ''
    t2 = ' '.join(d[1].get_text().split())
    if 'Provisional Merit list of MD/MS/DNB 1st Round Counselling 2026' not in t2 or 'Released Date : 07-Nov-2026' not in t2:
        raise SystemExit('page 2 title changed')
    recs, text_rolls, head_seen, zero_word = [], 0, False, 0
    for p in d:
        text_rolls += len(re.findall(r'(?<!\d)2666\d{7}(?!\d)', p.get_text()))
        if p.number == 0:
            continue
        for tb in p.find_tables().tables:
            for r in tb.extract():
                c = [' '.join((x or '').split()) for x in r]
                if len(c) != 14:
                    raise SystemExit(f'p{p.number + 1}: table with {len(c)} columns')
                if not INT.match(c[0]):
                    if c[0].startswith('Sr'):
                        if not all(k in c[i] for i, k in enumerate(HEAD_KEYS)):
                            raise SystemExit(f'p{p.number + 1}: column headings changed')
                        head_seen = True
                    elif any(c[1:]) or not (c[0] == '' or 'Atal Medical' in c[0] or 'Provisional Merit' in c[0]
                                            or 'Released Date' in c[0]):
                        raise SystemExit(f'p{p.number + 1}: unexpected non-data row')
                    continue
                where = f'p{p.number + 1} sr {c[0]}'
                if c[1] != c[0]:
                    raise SystemExit(f'{where}: Sr No != Merit No')
                if c[4] not in QUOTA:
                    raise SystemExit(f'{where}: unknown quota')
                if c[5] not in RCATS or c[12] not in MCATS:
                    raise SystemExit(f'{where}: unknown category')
                if not ROLL.match(c[6]) or not INT.match(c[7]) or not INT.match(c[8]):
                    raise SystemExit(f'{where}: roll / NEET score / AIR not numeric')
                if c[9] not in ('Yes', 'No') or c[13] not in ('Yes', 'No'):
                    raise SystemExit(f'{where}: Yes/No column shape')
                inc = c[10].rstrip('%')
                if inc.lower() in ('zero', 'nil'):   # printed as words on a few Yes rows
                    inc, zero_word = '0', zero_word + 1
                if c[9] == 'No' and inc:
                    raise SystemExit(f'{where}: incentive % without Service Incentive = Yes')
                try:
                    incv = float(inc) if inc else 0.0
                    total = float(c[11])
                except ValueError:
                    raise SystemExit(f'{where}: incentive / total not numeric')
                recs.append({'sr': int(c[0]), 'quota': QUOTA[c[4]], 'cat': c[5], 'roll': c[6], 'neet': int(c[7]),
                             'air': int(c[8]), 'inc_yes': c[9] == 'Yes', 'inc': incv, 'total': total,
                             'mcat': c[12].replace('Handicappe d', 'Handicapped'), 'nri_sp': c[13] == 'Yes'})
    if not head_seen:
        raise SystemExit('column headings not found')
    sr = [r['sr'] for r in recs]
    if sr != list(range(1, len(sr) + 1)):
        raise SystemExit('merit no. is not 1..n in print order')
    if text_rolls != len(recs):
        raise SystemExit(f'rolls in text {text_rolls} != rows {len(recs)}')
    dup = [k for k, v in collections.Counter(r['roll'] for r in recs).items() if v > 1]
    if dup:
        raise SystemExit(f'{len(dup)} duplicate rolls')
    formula_bad = [r['sr'] for r in recs if abs(r['total'] - r['neet'] * (1 + r['inc'] / 100)) > 0.01]
    total_breaks = [recs[i + 1]['sr'] for i in range(len(recs) - 1) if recs[i + 1]['total'] > recs[i]['total']]
    if total_breaks:
        raise SystemExit(f'total score not non-increasing at merit {total_breaks[:10]}')
    rows = [{'roll': r['roll'], 'air': r['air'], 'state_rank': r['sr'], 'score': r['total'], 'category': r['cat'],
             'quota': r['quota']} for r in recs]
    no_inc = [r for r in recs if not r['inc_yes']]
    air_breaks_no_inc = sum(1 for a, b in zip(no_inc, no_inc[1:]) if b['air'] < a['air'])
    checks = {
        'page_count': d.page_count, 'row_count': len(rows), 'rolls_in_pdf_text': text_rolls,
        'printed_total': 'none printed; last merit no. = row count', 'state_rank_1_to_n': True,
        'state_rank_source': "printed 'Merit No' (= Sr No on every row)",
        'air_source': "printed 'All India Merit Rank'", 'air_printed': len(rows), 'air_blank': 0,
        'air_min': min(r['air'] for r in rows), 'air_max': max(r['air'] for r in rows),
        'air_order_breaks_all_rows': sum(1 for a, b in zip(rows, rows[1:]) if b['air'] < a['air']),
        'air_order_breaks_among_rows_without_incentive': air_breaks_no_inc,
        'score_definition': "'NEET Score + Service Incentive' as printed (merit basis); non-increasing along merit no.",
        'score_formula_neet_x_1_plus_incentive_pct_mismatch': formula_bad[:20],
        'service_incentive_yes': sum(1 for r in recs if r['inc_yes']),
        'incentive_pct_printed_as_zero_or_nil_word': zero_word,
        'categories': dict(collections.Counter(r['category'] for r in rows).most_common()),
        'quotas': dict(collections.Counter(r['quota'] for r in rows).most_common()),
        'management_quota_category': dict(collections.Counter(r['mcat'] for r in recs).most_common()),
        'nri_sponsored_yes': sum(1 for r in recs if r['nri_sp']),
        'nbems_check': 'not done locally (NBEMS file not on this Mac) - the ingest counts air_mismatch by roll',
    }
    notes = ("AMRU HP MD/MS/DNB 1st round provisional merit list (notice 129/2026-27-6994, 07.11.2026). One common "
             "merit list for all quotas; quota per row (HP Direct / In-service / Management / NRI). state_rank = merit "
             "no.; score = NEET score + service incentive; AIR printed for every row. Discrepancies till 11 AM 08.11.2026.")
    obj = {'authority_code': 'amru_hp', 'list_name': 'MD/MS/DNB 1st Round Provisional Merit List',
           'published_on': published, 'source_file_name': os.path.basename(path), 'notes': notes,
           'row_count': len(rows), 'checks': checks, 'rows': rows}
    fp = os.path.join(out, 'amru_hp_r1_provisional.json')
    with open(fp, 'w') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    print(fp)
    print(json.dumps(checks, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
