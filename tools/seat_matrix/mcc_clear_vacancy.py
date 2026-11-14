"""MCC NEET-PG later-round seat list ("CLEAR VACANCY ROUND n (MD/MS/DNB)", "UPDATED CLEAR VACANCY ...") → raw rows.
Run with /usr/bin/python3 (PyMuPDF):
    mcc_clear_vacancy.py <list.pdf> <out.json> [<ref.json> ...]

PDF columns: StateName | InstituteType | Institute (name + address + "(6-digit MCC code)") | Quota | Branch |
Category | TotalSeats; one grand-total line at the end (only the number). Output = list of
[state, institute_type, "institute text (code)", quota, branch, category, seats, how] — the raw format the
Round 2 build step reads (empty institute_type = the grand-total line); how = where the code came from:
'cell' (printed), 'name' / 'words' (clipped in the PDF, see below — the institute text is then the clipped text).

Why this reader exists (13 Nov 2026 "UPDATED CLEAR VACANCY ROUND 2", 841 pages): the Excel→PDF export clips
long Institute cells, and the text that does overflow is drawn over the NEXT line's cell, so find_tables()
mixes two institutes (even character by character) and ~2,000 lines lose their "(code)". Fix:
  1. cells are read in the page's drawing order (MCC draws each line cell by cell), so overflow stays with
     its own line — a cell may legitimately hold a PIN in brackets before the real code: the LAST code wins;
  2. a line still without a code (its code was clipped away) is matched by its institute text against
     institutes WITH codes — this file's own lines first, then the reference files (earlier parsed lists in
     the same raw format, or built rows with college_name / college_code): the clipped text must be a prefix
     of exactly one code's text in the same state (same institute type breaks ties);
  3. last resort for reworded institutes: the distinctive (place / address) words of the clipped text must
     nearly all appear in ONE code's texts in that state and clearly beat the next one — printed "BY WORDS"
     for review.
Stops (exit 1) if any line stays without a code, or the data lines do not add up to the printed grand total."""
import collections, json, re, sys
import fitz

CODE = re.compile(r'\((\d{6})\)')
sp = lambda s: re.sub(r'\s+', ' ', s or '').strip()
norm = lambda s: re.sub(r'[^a-z0-9]', '', (s or '').lower())


STOP = {'government', 'govt', 'medical', 'college', 'hospital', 'and', 'the', 'institute', 'sciences', 'science',
        'research', 'centre', 'center', 'road', 'district', 'near', 'post', 'state', 'india', 'com', 'gmail',
        'nagar', 'of', 'for'}
HEAD = {'StateName', 'InstituteType', 'Institute', 'Quota', 'Branch', 'Category', 'TotalSeats'}


def read(pdf):
    """Cells from the page's drawing order, not from table geometry: MCC's export draws each line cell by cell
    (state, type, institute, quota, branch, category, seats), and a long institute text that overflows its
    row is still drawn inside its own cell's run — find_tables() would hand the overflow to the next line."""
    rows = []
    for p in fitz.open(pdf):
        tabs = p.find_tables().tables
        if not tabs:
            continue
        full = max(tabs[0].rows, key=lambda r: sum(1 for c in r.cells if c))
        xs = [c[0] for c in full.cells if c] + [tabs[0].bbox[2]]
        if len(xs) != 8:
            raise SystemExit(f'page {p.number + 1}: {len(xs) - 1} columns')
        col = lambda a, b: next((i for i in range(7) if xs[i] <= (a + b) / 2 < xs[i + 1]), None)
        cur = None; last = 99
        for b in p.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                t = ''.join(s['text'] for s in l['spans']).strip()
                if not t or t in HEAD or re.match(r'^Page \d+ of \d+$', t) or 'CLEAR VACANCY' in t.upper():
                    continue
                c = col(l['bbox'][0], l['bbox'][2])
                if c is None:
                    raise SystemExit(f'page {p.number + 1}: text outside the table: {t[:60]}')
                if c < last or (c == 6 and last == 6):   # a second number in the seats column = the grand total
                    cur = [''] * 7; rows.append(cur)
                cur[c] = sp(cur[c] + ' ' + t); last = c
    for r in rows:
        if not r[6].isdigit():
            raise SystemExit(f'line without a seat number: {r}')
    return rows


def refs(paths):
    """[(state, itype, norm_name, code)] from earlier raw lists / built rows."""
    out = []
    for p in paths:
        for r in json.load(open(p)):
            if isinstance(r, list):
                if not r[1]:
                    continue
                m = list(CODE.finditer(r[2]))
                if m and not r[2][m[-1].end():].strip():
                    out.append((sp(r[0]), sp(r[1]), norm(r[2][:m[-1].start()]), m[-1].group(1), r[2][:m[-1].start()]))
            elif r.get('college_code'):
                out.append((sp(r.get('state')), sp(r.get('institute_type')), norm(r.get('college_name')),
                            r['college_code'], r.get('college_name') or ''))
    return out


def main():
    pdf, out = sys.argv[1], sys.argv[2]
    rows = read(pdf)
    data = [r for r in rows if r[1]]
    total = [r for r in rows if not r[1]]
    stats = collections.Counter(); issues = []
    code = [None] * len(data); name = [None] * len(data); how = [''] * len(data)
    for i, r in enumerate(data):
        t = r[2]; ms = list(CODE.finditer(t))
        if ms and not t[ms[-1].end():].strip():
            code[i] = ms[-1].group(1); name[i] = sp(t[:ms[-1].start()]).rstrip(','); how[i] = 'cell'
            stats['code_in_cell'] += 1
        else:
            name[i] = t
    # name → code lookup: this file's coded lines, then the references
    own = [(sp(data[i][0]), sp(data[i][1]), norm(name[i]), code[i], name[i]) for i in range(len(data))
           if code[i] and CODE.search(data[i][2] or '')]
    pool = [own, refs(sys.argv[3:])]
    for i, r in enumerate(data):
        if code[i]:
            continue
        n = norm(name[i]); st, it = sp(r[0]), sp(r[1]); hit = None
        for src in pool:
            c = {x[3] for x in src if x[0] == st and x[2].startswith(n)}
            if len(c) > 1:
                c = {x[3] for x in src if x[0] == st and x[1] == it and x[2].startswith(n)} or c
            if len(c) == 1:
                hit = c.pop(); break
            if len(c) > 1:
                issues.append(('ambiguous name', i, name[i][:80], sorted(c))); break
        if hit:
            code[i] = hit; how[i] = 'name'; stats['code_from_name'] += 1
    # last resort — the clipped text was reworded since the reference list: same state, distinctive words
    # (place / address words) of the clipped text must nearly all appear in ONE code's texts; listed for review
    words = lambda s: {w for w in re.findall(r'[a-z0-9]{3,}', (s or '').lower()) if w not in STOP}
    vocab = collections.defaultdict(set)
    for x in pool[0] + pool[1]:
        vocab[(x[0], x[3])] |= words(x[4])
    fuzzy = {}
    for i, r in enumerate(data):
        if code[i]:
            continue
        w = words(name[i]); st = sp(r[0])
        sc = sorted(((len(w & v) / max(1, len(w)), c) for (s2, c), v in vocab.items() if s2 == st), reverse=True)
        if w and sc and sc[0][0] >= 0.75 and (len(sc) == 1 or sc[0][0] - sc[1][0] >= 0.25):
            code[i] = sc[0][1]; how[i] = 'words'; stats['code_from_words'] += 1
            fuzzy.setdefault((st, name[i][:90]), (sc[0][1], round(sc[0][0], 2), round(sc[1][0], 2) if len(sc) > 1 else None))
    for k, v in fuzzy.items():
        print('  BY WORDS', k[0], '|', k[1], '->', v)
    known = {x[3] for x in pool[1]}
    if known:   # a code never seen before could be a bracketed PIN left after a clipped code — review these
        new = collections.Counter((code[i], name[i][:90]) for i in range(len(data)) if code[i] and code[i] not in known)
        for (c, n), k in sorted(new.items()):
            print('  CODE NOT IN REFERENCES', c, '|', n, '| lines', k)
    miss = [(i, data[i][0], name[i][:90]) for i in range(len(data)) if not code[i]]
    res = []
    for i, r in enumerate(data):
        res.append([r[0], r[1], f'{name[i]} ({code[i]})' if code[i] else name[i], r[3], r[4], r[5], r[6], how[i]])
    res += total
    json.dump(res, open(out, 'w'))
    seats = sum(int(r[6]) for r in data)
    printed = [int(r[6]) for r in total]
    print(pdf.split('/')[-1], 'lines', len(data), 'seats', seats, 'printed total', printed, dict(stats),
          'institutes', len(set(code)))
    for x in issues[:20]:
        print('  ISSUE', x)
    if miss:
        print('  NO CODE', len(miss))
        for x in miss[:20]:
            print('   ', x)
    if miss or printed != [seats] or issues:
        sys.exit(1)


if __name__ == '__main__':
    main()
