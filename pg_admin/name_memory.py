"""Name memory — match ANY authority's way of writing a college / course to our standard name, and
remember it (founder 2026-10-24: "the system should know next time that this is the college").

Standard names are the ones everything else already uses: the 2025 cut-off institute names
(pg_cutoffs.institute — predictor, seat matrices, rankings) and the approved course list.

resolve(conn, kind, raw_names, authority_code) → {raw: {'std','status','how','score'}}
  1. memory: a name seen before → its stored answer (confirmed / seeded / auto).
  2. exact: the normalised name equals a standard name or a known alias (college workbook names,
     former names) — also tried on the part before each comma, because MCC writes
     "College Name, City,Full Address".
  3. fuzzy: word-weighted similarity (rare words like a city count more than "Medical College").
     A clear winner is auto-accepted (status ok, how fuzzy); anything close is put in the review
     queue with its candidates and NOT used until the team confirms it.
Every new name is written to pg_name_memory, so the next file from any authority reuses it.
seed(conn) fills the memory from what is already matched (seat matrices, college aliases).
"""
import json
import math
import re
from collections import Counter

AUTO_MIN, AUTO_GAP = 0.86, 0.12      # fuzzy auto-accept: score ≥ 0.86 and ≥ 0.12 ahead of the runner-up


def norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


_SYN = {'govt': 'government', 'med': 'medical', 'coll': 'college', 'inst': 'institute', 'univ': 'university',
        'hosp': 'hospital', 'sci': 'sciences', 'science': 'sciences', 'centre': 'center', 'pgimer': 'pgimer',
        'dr': 'dr', 'st': 'saint', 'sri': 'shri', 'shree': 'shri', 'smt': 'shrimati'}


def _tokens(s):
    return [_SYN.get(t, t) for t in norm(s).split() if t not in ('of', 'and', 'the', 'a', 'in', 'at')]


class _Index:
    """Standard names + their word weights, built once per resolve() call."""

    def __init__(self, names):
        self.names = list(dict.fromkeys(n for n in names if n))
        self.toks = {n: set(_tokens(n)) for n in self.names}
        df = Counter(t for ts in self.toks.values() for t in ts)
        n = max(1, len(self.names))
        self.w = {t: math.log(1 + n / c) for t, c in df.items()}

    def score(self, a, b_toks):
        at = set(_tokens(a))
        if not at or not b_toks:
            return 0.0
        inter = sum(self.w.get(t, 1.0) for t in at & b_toks)
        union = sum(self.w.get(t, 1.0) for t in at | b_toks)
        # containment matters more than union for "short name" vs "name + address"
        small = min(sum(self.w.get(t, 1.0) for t in at), sum(self.w.get(t, 1.0) for t in b_toks))
        return max(inter / union if union else 0, 0.92 * inter / small if small else 0)

    def best(self, raw, limit=5):
        parts = _prefixes(raw)
        sc = []
        for n in self.names:
            s = max(self.score(p, self.toks[n]) for p in parts)
            if s > 0.3:
                sc.append((round(s, 3), n))
        sc.sort(reverse=True)
        return sc[:limit]


def _prefixes(raw):
    """'A, B,C,D' → ['A', 'A, B', 'A, B,C', full] — MCC puts the address after the name."""
    bits = [b for b in re.split(r',', raw or '') if b.strip()]
    out = []
    for i in range(1, min(len(bits), 4) + 1):
        out.append(','.join(bits[:i]))
    if raw and raw not in out:
        out.append(raw)
    return out


def standard_names(conn, kind):
    if kind == 'college':
        rows = conn.execute("SELECT DISTINCT institute AS n FROM pg_cutoffs WHERE COALESCE(institute,'')<>''").fetchall()
        return [r['n'] for r in rows]
    import os
    p = os.path.join(os.path.dirname(__file__), 'data', 'specialty_sheet.json')
    names = [c['course'] for c in json.load(open(p))['courses']]
    rows = conn.execute("SELECT DISTINCT course AS n FROM pg_cutoffs WHERE COALESCE(course,'')<>''").fetchall()
    return list(dict.fromkeys(names + [r['n'] for r in rows]))


def _alias_map(conn):
    """normalised college-workbook / former / variant name → the cut-off (standard) name of the same college."""
    out = {}
    try:
        cut = {}
        for r in conn.execute("SELECT master_id, alias_name FROM pg_college_alias WHERE alias_source='cutoff' "
                              "AND COALESCE(is_active,1)=1 ORDER BY id").fetchall():
            cut.setdefault(r['master_id'], r['alias_name'])
        for r in conn.execute("SELECT master_id, alias_key FROM pg_college_alias WHERE COALESCE(is_active,1)=1").fetchall():
            if r['master_id'] in cut and r['alias_key']:
                out.setdefault(r['alias_key'], cut[r['master_id']])
    except Exception:
        try: conn.rollback()
        except Exception: pass
    return out


def _remember(conn, kind, raw, std, how, status, authority_code='', score=None, cands=None, state=''):
    conn.execute(
        "INSERT INTO pg_name_memory (kind, raw_name, raw_key, std_name, state, authority_code, how, score, status, "
        "candidates, seen_count) VALUES (?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT (kind, raw_key) DO UPDATE SET "
        "seen_count = pg_name_memory.seen_count + 1, last_seen = CURRENT_TIMESTAMP",
        [kind, raw, norm(raw), std or '', state or '', authority_code or '', how, score, status,
         json.dumps(cands or [])])


def resolve(conn, kind, raw_names, authority_code='', learn=True):
    raw_names = [r for r in dict.fromkeys(raw_names) if r and r.strip()]
    keys = {r: norm(r) for r in raw_names}
    mem = {}
    if raw_names:
        for r in conn.execute("SELECT raw_key, std_name, status, how, score FROM pg_name_memory WHERE kind=? "
                              "AND raw_key = ANY(?)", [kind, list(set(keys.values()))]).fetchall():
            mem[r['raw_key']] = r
    out, todo = {}, []
    for raw in raw_names:
        m = mem.get(keys[raw])
        if m:
            out[raw] = {'std': m['std_name'] if m['status'] == 'ok' else '', 'status': m['status'],
                        'how': m['how'], 'score': float(m['score']) if m['score'] is not None else None}
            if learn:
                conn.execute("UPDATE pg_name_memory SET seen_count=seen_count+1, last_seen=CURRENT_TIMESTAMP "
                             "WHERE kind=? AND raw_key=?", [kind, keys[raw]])
        else:
            todo.append(raw)
    if not todo:
        return out
    std = standard_names(conn, kind)
    by_key = {norm(n): n for n in std}
    alias = _alias_map(conn) if kind == 'college' else {}
    idx = _Index(std)
    for raw in todo:
        hit = None
        for p in _prefixes(raw):
            k = norm(p)
            hit = by_key.get(k) or alias.get(k)
            if hit:
                break
        if hit:
            res = {'std': hit, 'status': 'ok', 'how': 'exact', 'score': 1.0}
            cands = []
        else:
            cands = idx.best(raw)
            top = cands[0][0] if cands else 0
            gap = top - (cands[1][0] if len(cands) > 1 else 0)
            if cands and top >= AUTO_MIN and gap >= AUTO_GAP:
                res = {'std': cands[0][1], 'status': 'ok', 'how': 'fuzzy', 'score': top}
            else:
                res = {'std': '', 'status': 'review' if cands else 'unmatched', 'how': 'fuzzy', 'score': top or None}
        out[raw] = res
        if learn:
            _remember(conn, kind, raw, res['std'], res['how'], res['status'], authority_code, res['score'], cands)
    return out


def teach(conn, kind, raw, std, authority_code=''):
    """An importer that already knows the standard name (e.g. a checked course map) tells the memory.
    Never overrides a team-confirmed answer."""
    conn.execute(
        "INSERT INTO pg_name_memory (kind, raw_name, raw_key, std_name, authority_code, how, status, seen_count) "
        "VALUES (?,?,?,?,?,'importer','ok',0) ON CONFLICT (kind, raw_key) DO UPDATE SET std_name=EXCLUDED.std_name, "
        "status='ok', how='importer' WHERE pg_name_memory.how <> 'confirmed'",
        [kind, raw, norm(raw), std, authority_code or ''])


def confirm(conn, kind, raw_key, std_name, who):
    """Team decision from the review screen — becomes permanent memory ('' = not a college we list)."""
    conn.execute("UPDATE pg_name_memory SET std_name=?, status=?, how='confirmed', confirmed_by=?, "
                 "confirmed_at=CURRENT_TIMESTAMP WHERE kind=? AND raw_key=?",
                 [std_name or '', 'ok' if std_name else 'unmatched', who or '', kind, raw_key])


def seed(conn):
    """Fill the memory from names we have ALREADY matched (never overwrites anything stored):
    seat-matrix lines (authority name → cut-off name), and the college workbook's aliases."""
    n = Counter()
    for r in conn.execute(
            "SELECT DISTINCT college_name, cutoff_institute, authority_code, state FROM pg_seat_matrix "
            "WHERE COALESCE(cutoff_institute,'')<>'' AND COALESCE(college_name,'')<>''").fetchall():
        conn.execute("INSERT INTO pg_name_memory (kind, raw_name, raw_key, std_name, state, authority_code, how, status) "
                     "VALUES ('college',?,?,?,?,?,'seed_matrix','ok') ON CONFLICT (kind, raw_key) DO NOTHING",
                     [r['college_name'], norm(r['college_name']), r['cutoff_institute'], r['state'] or '',
                      r['authority_code'] or ''])
        n['college_matrix'] += 1
    for r in conn.execute(
            "SELECT DISTINCT course_name, cutoff_course, authority_code FROM pg_seat_matrix "
            "WHERE COALESCE(cutoff_course,'')<>'' AND COALESCE(course_name,'')<>''").fetchall():
        conn.execute("INSERT INTO pg_name_memory (kind, raw_name, raw_key, std_name, authority_code, how, status) "
                     "VALUES ('course',?,?,?,?,'seed_matrix','ok') ON CONFLICT (kind, raw_key) DO NOTHING",
                     [r['course_name'], norm(r['course_name']), r['cutoff_course'], r['authority_code'] or ''])
        n['course_matrix'] += 1
    names = {}
    for r in conn.execute("SELECT a.alias_name, a.alias_key, a.master_id FROM pg_college_alias a "
                          "WHERE COALESCE(a.is_active,1)=1").fetchall():
        names.setdefault(r['alias_key'], r['alias_name'])
    amap = _alias_map(conn)
    for k, stdn in amap.items():
        if k and k in names:
            conn.execute("INSERT INTO pg_name_memory (kind, raw_name, raw_key, std_name, how, status) "
                         "VALUES ('college',?,?,?,'seed_alias','ok') ON CONFLICT (kind, raw_key) DO NOTHING",
                         [names[k], k, stdn])
            n['college_alias'] += 1
    return dict(n)
