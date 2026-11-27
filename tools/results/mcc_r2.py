"""MCC NEET-PG seat allotment result for Round 2 and later rounds → rows for POST /api/pg/results/ingest.

From Round 2 on, MCC prints BOTH rounds on one line (13 columns):
  SNo | Rank | <prev round>: Allotted Quota, Allotted Institute, Course, Remarks |
  <this round>: Allotted Quota, Allotted Institute, Course, Allotted Category, Candidate Category, Option No., Remarks
(layout checked on MCC's 2025 Round 2 result; PG and UG use the same layout).

One output row per candidate who HOLDS a seat after this round, with round_status:
  fresh     — got a seat for the first time in this round ("Fresh Allotted in 2nd Round …")
  upgraded  — moved from the earlier-round seat ("Upgraded"); prev_* = the earlier seat
  retained  — kept the earlier-round seat: this round's Remarks "Retained" (seat reprinted), or earlier Remarks "Reported" and no new seat: "Did not opt for
              Upgradation." / "No Upgradation" / "Did not fill up fresh choices."). MCC prints no category for it —
              the portal fills allotted_category from the earlier round's row of the same rank.
Candidates with no seat after the round (not reported / surrendered and nothing new) are left out.
No names are in MCC's result; nothing but rank + seat is stored. Run with /usr/bin/python3 (PyMuPDF):
    mcc_r2.py <result.pdf> <out.json> [--cache raw.json] [--save-raw raw.json]"""
import json, re, sys, collections
import fitz

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from mcc import map_seat, clean   # noqa: E402  (same quota / course / category maps as Round 1)

NCOL = 13


def read(pdf):
    """2025 layout: 13 columns. 2026 layout (MCC Round 2, 20-11-2026): a 'Roll No' column after Rank (14 columns;
    15 on pages where a merged 'Alloted Quota' heading leaves an empty column). Roll No is dropped, never stored."""
    out = []
    for pg in fitz.open(pdf):
        for t in pg.find_tables().tables:
            for r in t.extract():
                r = [clean(x) for x in r]
                if len(r) == 15 and r[8] == '':               # empty column under the merged heading
                    r = r[:8] + r[9:]
                if len(r) == 14 and r[2].isdigit() and len(r[2]) >= 8:   # 2026: SNo, Rank, Roll No, …
                    r = r[:2] + r[3:]
                if len(r) == NCOL and r[0].isdigit():
                    out.append(r)
    return out


def blank(v):
    return v in ('', '-', '--')


def convert(raw):
    sn = sorted(int(r[0]) for r in raw)
    if sn != list(range(1, len(sn) + 1)):
        raise SystemExit(f'serial numbers are not 1..{len(sn)} — rows missing or read twice')
    rows, unknown, skipped, combos = [], collections.Counter(), collections.Counter(), collections.Counter()
    for r in raw:
        sno, rank, q1, i1, c1, rem1, q2, i2, c2, acat2, ccat, opt, rem2 = r
        if not rank.isdigit():
            unknown['rank: ' + rank] += 1; continue
        combos[(rem1 or '-', 'new seat' if not blank(q2) else 'no new seat', re.sub(r'\(.*', '', rem2).strip())] += 1
        prev = None
        if not blank(q2):                                   # a seat in this round
            # MCC reprints a kept seat in this round's columns with Remarks "Retained" (opted for upgradation, not
            # upgraded) — that is NOT a fresh allotment (2026-11-26: 6,091 MCC R2 lines were miscounted as fresh)
            low = rem2.lower()
            status = 'upgraded' if low.startswith('upgraded') else 'retained' if low.startswith('retained') else 'fresh'
            if status == 'fresh' and not low.startswith('fresh'):
                unknown['this-round remark with a seat: ' + re.sub(r'\(.*', '', rem2).strip()] += 1
                continue
            m = map_seat(q2, c2, acat2, unknown)
            if not m:
                continue
            q, std, section, cat = m
            seat = {'quota_raw': q2, 'quota': q, 'institute_raw': i2, 'course_raw': c2, 'course': std,
                    'section': section, 'allotted_category': cat, 'allotted_category_raw': acat2}
            if status == 'upgraded' and not blank(q1):
                pm = map_seat(q1, c1, '', unknown)
                if not pm:
                    continue
                prev = {'prev_quota_raw': q1, 'prev_quota': pm[0], 'prev_institute_raw': i1, 'prev_course_raw': c1,
                        'prev_course': pm[1], 'prev_remarks': rem1}
        elif rem1.lower() == 'reported' and not blank(q1):  # kept the earlier seat
            status = 'retained'
            m = map_seat(q1, c1, '', unknown)
            if not m:
                continue
            q, std, section, cat = m
            seat = {'quota_raw': q1, 'quota': q, 'institute_raw': i1, 'course_raw': c1, 'course': std,
                    'section': section, 'allotted_category': '', 'allotted_category_raw': ''}
        else:
            skipped[(rem1 or '-') + ' → ' + (rem2 or '-')] += 1
            continue
        row = {'sno': int(sno), 'rank': int(rank), **seat,
               'candidate_category': '' if blank(ccat) else ccat, 'remarks': rem2,
               'round_status': status, 'round_status_raw': rem2}
        if prev:
            row.update(prev)
        rows.append(row)
    if unknown:
        raise SystemExit(f'unknown values (add them to the maps in mcc.py): {dict(unknown)}')
    return rows, skipped, combos


def main():
    pdf, out = sys.argv[1], sys.argv[2]
    cache = sys.argv[sys.argv.index('--cache') + 1] if '--cache' in sys.argv else None
    raw = json.load(open(cache)) if cache else read(pdf)
    if not raw:
        raise SystemExit(f'no {NCOL}-column rows found — not the Round 2+ layout? (Round 1 → mcc.py)')
    if '--save-raw' in sys.argv:
        json.dump(raw, open(sys.argv[sys.argv.index('--save-raw') + 1], 'w'))
    rows, skipped, combos = convert(raw)
    json.dump({'rows': rows}, open(out, 'w'), ensure_ascii=False)
    print('lines', len(raw), '| seats held after the round', len(rows))
    print('by status', dict(collections.Counter(r['round_status'] for r in rows)))
    print('by section', dict(collections.Counter(r['section'] for r in rows)))
    print('by quota', dict(collections.Counter(r['quota'] for r in rows)))
    print('left out (no seat after the round)', dict(skipped))
    print('remark combinations (earlier remark, seat?, this-round remark):')
    for k, n in combos.most_common():
        print('  ', n, k)


if __name__ == '__main__':
    main()
