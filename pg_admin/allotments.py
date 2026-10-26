"""A doctor's own seat allotments, matched from the published counselling results by rank (founder 2026-10-24).

  MCC (All India)        → pg_users.neet_pg_rank   = pg_results.rank
  a state's counselling  → pg_users.home_state_rank = pg_results.rank, for the doctor's home state only
                           (state lists use the state merit rank, not the All-India rank)

Nothing is copied: allotments are read live from pg_results, so a corrected rank or a final list that replaces a
provisional one shows straight away. A profile rank can be wrong or old, so every match is labelled "matched by
rank" and can be marked:
  confirmed — the team checked it (Counselling Desk / admin)
  not_me    — the doctor or the team says it isn't theirs (hidden from the doctor, flagged for the team)
Rank / score changes made through this flow are logged in pg_profile_edit_log (the same log the Desk uses). A doctor may confirm their rank, score
and home-state rank once and correct them ONE more time from the dashboard; after that only the team can change
them (internal doctors: the Counselling Desk, with the scorecard as proof).
"""
import logging

SELF_CORRECTIONS = 1


def ensure(conn):
    try:
        for col, typ in (('home_state_rank', 'INTEGER'), ('rank_confirmed_at', 'TIMESTAMP'),
                         ('rank_self_edits', 'INTEGER DEFAULT 0'), ('rank_prompt_closed_at', 'TIMESTAMP'),
                         ('correction_prompt_closed_at', 'TIMESTAMP')):
            if not conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name='pg_users' "
                                "AND column_name=?", [col]).fetchone():
                conn.execute(f"ALTER TABLE pg_users ADD COLUMN IF NOT EXISTS {col} {typ}")
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_allotment_marks (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            authority_code TEXT NOT NULL,
            academic_year TEXT NOT NULL DEFAULT '2026-27',
            round TEXT NOT NULL,
            verdict TEXT NOT NULL,              -- confirmed | not_me
            rank_used INTEGER,
            marked_by TEXT DEFAULT '',
            via TEXT DEFAULT '',                -- doctor | desk | admin
            note TEXT DEFAULT '',
            marked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_allotment_marks "
                     "ON pg_allotment_marks (user_id, authority_code, academic_year, round)")
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_profile_edit_log (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, field TEXT NOT NULL, old_value TEXT DEFAULT '',
            new_value TEXT DEFAULT '', changed_by TEXT DEFAULT '', source TEXT DEFAULT 'desk',
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("allotments.ensure: %s", e)


def _authorities():
    """code → (name, state label) for every counselling authority."""
    from pg_admin.authorities import AUTHORITIES
    return {a[0]: (a[1], a[2]) for a in AUTHORITIES}


def _state_key(s):
    return ' '.join((s or '').lower().replace('&', 'and').split())


def _rounds(conn):
    """Published result rounds: [(authority_code, year, round, round_order, status, published_on, uploaded_at)]."""
    return [dict(r) for r in conn.execute(
        "SELECT authority_code, academic_year, round, round_order, status, published_on, uploaded_at "
        "FROM pg_results_source WHERE COALESCE(is_hidden,0)=0 ORDER BY uploaded_at").fetchall()]


def _row(r, auths, mark=None):
    sec = r.get('section') or 'mdms'
    name = auths.get(r['authority_code'], (r['authority_code'], ''))[0]
    college = r['institute_raw'] if sec == 'dnb' else (r['institute'] or r['institute_raw'])
    out = {'authority_code': r['authority_code'], 'authority_name': name, 'round': r['round'],
           'round_order': r['round_order'], 'status': r['status'], 'published_on': r['published_on'] or '',
           'program': 'dnb' if sec == 'dnb' else 'mdms', 'rank': r['rank'],
           'rank_type': 'All India rank' if r['authority_code'] == 'mcc' else 'State rank',
           'college': college, 'college_short': (college or '').split(',')[0].strip(),
           'state': r.get('state') or '', 'college_type': r.get('college_type') or '',
           'course': r['course'] or r['course_raw'], 'quota': r['quota'] or r['quota_raw'],
           'allotted_category': r['allotted_category'], 'candidate_category': r['candidate_category'],
           'verdict': (mark or {}).get('verdict') or '', 'marked_by': (mark or {}).get('marked_by') or '',
           'marked_via': (mark or {}).get('via') or ''}
    out['label'] = f"{_short_auth(r['authority_code'], name)} {_short_round(r['round'])} · {out['course']}"
    return out


def _short_auth(code, name):
    return 'MCC' if code == 'mcc' else (name or code)


def _short_round(rnd):
    return (rnd or '').replace('Round ', 'R')


def for_users(conn, users, include_not_me=True):
    """{user_id: [allotment, …] newest round first} for a list of pg_users dicts (id, neet_pg_rank, state,
    home_state_rank). One query per published authority — fast for a whole page of doctors."""
    out = {u['id']: [] for u in users}
    if not users:
        return out
    auths = _authorities()
    rounds = _rounds(conn)
    if not rounds:
        return out
    codes = {r['authority_code'] for r in rounds}
    marks = {}
    ids = [u['id'] for u in users]
    for m in conn.execute("SELECT user_id, authority_code, academic_year, round, verdict, marked_by, via "
                          "FROM pg_allotment_marks WHERE user_id = ANY(?)", [ids]).fetchall():
        marks[(m['user_id'], m['authority_code'], m['academic_year'], m['round'])] = dict(m)
    src = {(r['authority_code'], r['academic_year'], r['round']): r for r in rounds}
    for code in codes:
        if code == 'mcc':
            by_rank = {}
            for u in users:
                try:
                    rk = int(u.get('neet_pg_rank') or 0)
                except (TypeError, ValueError):
                    rk = 0
                if rk > 0:
                    by_rank.setdefault(rk, []).append(u['id'])
        else:
            st = _state_key(auths.get(code, ('', ''))[1])
            by_rank = {}
            for u in users:
                try:
                    rk = int(u.get('home_state_rank') or 0)
                except (TypeError, ValueError):
                    rk = 0
                if rk > 0 and st and _state_key(u.get('state')) == st:
                    by_rank.setdefault(rk, []).append(u['id'])
        if not by_rank:
            continue
        for r in conn.execute(
                "SELECT authority_code, academic_year, round, rank, section, institute, institute_raw, state, "
                "college_type, course, course_raw, quota, quota_raw, allotted_category, candidate_category "
                "FROM pg_results WHERE authority_code = ? AND rank = ANY(?)", [code, list(by_rank)]).fetchall():
            r = dict(r)
            s = src.get((r['authority_code'], r['academic_year'], r['round']))
            if not s:
                continue
            r.update(round_order=s['round_order'], status=s['status'], published_on=s['published_on'])
            for uid in by_rank.get(r['rank'], []):
                mk = marks.get((uid, r['authority_code'], r['academic_year'], r['round']))
                if mk and mk['verdict'] == 'not_me' and not include_not_me:
                    continue
                out[uid].append(_row(r, auths, mk))
    for uid in out:
        out[uid].sort(key=lambda a: (a['authority_code'] != 'mcc', -int(a['round_order'] or 0)))
    return out


def latest(allots):
    """The allotment to show in a list column: the newest round, MCC first; ignores 'not me'."""
    live = [a for a in allots if a['verdict'] != 'not_me']
    if not live:
        return None
    return sorted(live, key=lambda a: (-int(a['round_order'] or 0), a['authority_code'] != 'mcc'))[0]


def grouped(allots):
    """Doctor dashboard shape: {mdms: [{authority_code, authority_name, rounds:[…]}], dnb: [...]}."""
    out = {'mdms': [], 'dnb': []}
    for prog in ('mdms', 'dnb'):
        by = {}
        for a in allots:
            if a['program'] != prog:
                continue
            g = by.setdefault(a['authority_code'], {'authority_code': a['authority_code'],
                                                     'authority_name': a['authority_name'], 'rounds': []})
            g['rounds'].append(a)
        for g in by.values():
            g['rounds'].sort(key=lambda a: int(a['round_order'] or 0))
            prev = None
            for a in g['rounds']:          # what changed since the previous round
                if prev is None:
                    a['change'] = ''
                elif (prev['college'], prev['course']) == (a['college'], a['course']):
                    a['change'] = 'Same seat as ' + prev['round']
                else:
                    a['change'] = 'Changed from ' + prev['round']
                prev = a
        out[prog] = sorted(by.values(), key=lambda g: (g['authority_code'] != 'mcc', g['authority_name']))
    return out


def mark(conn, user_id, authority_code, year, rnd, verdict, by, via, rank_used=None, note=''):
    if verdict not in ('confirmed', 'not_me', ''):
        raise ValueError('bad verdict')
    if not verdict:
        conn.execute("DELETE FROM pg_allotment_marks WHERE user_id=? AND authority_code=? AND academic_year=? "
                     "AND round=?", [user_id, authority_code, year, rnd])
        return
    conn.execute(
        "INSERT INTO pg_allotment_marks (user_id, authority_code, academic_year, round, verdict, rank_used, "
        "marked_by, via, note) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT (user_id, authority_code, academic_year, round) "
        "DO UPDATE SET verdict=EXCLUDED.verdict, rank_used=EXCLUDED.rank_used, marked_by=EXCLUDED.marked_by, "
        "via=EXCLUDED.via, note=EXCLUDED.note, marked_at=CURRENT_TIMESTAMP",
        [user_id, authority_code, year, rnd, verdict, rank_used, by or '', via, note or ''])


RANK_FIELDS = ('neet_pg_rank', 'neet_pg_score', 'home_state_rank')


def parse_rank_value(field, v):
    """'1,234' / 1234 / '512.0' → int; blank → None. A NEET-PG score can be 0 or negative; ranks must be > 0.
    Raises ValueError with a doctor-readable message."""
    if v is None or str(v).strip() == '':
        return None
    try:
        n = int(round(float(str(v).replace(',', '').strip())))
    except (TypeError, ValueError):
        raise ValueError({'neet_pg_score': 'Score must be a number.'}.get(field, 'Rank must be a whole number.'))
    if field != 'neet_pg_score' and n <= 0:
        raise ValueError('Rank must be above 0.')
    return n


def set_ranks(conn, user_id, values, by, via, note=''):
    """Write rank / score / home-state rank, logging each change. Returns the changed field names."""
    cur = conn.execute("SELECT neet_pg_rank, neet_pg_score, home_state_rank FROM pg_users WHERE id=?",
                       [user_id]).fetchone()
    if not cur:
        return []
    changed = []
    for f in RANK_FIELDS:
        v = parse_rank_value(f, values.get(f)) if f in values else None
        if v is None:
            continue                       # left blank = keep what is there (never wipes a rank)
        if cur[f] != v:
            conn.execute(f"UPDATE pg_users SET {f}=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", [v, user_id])
            conn.execute("INSERT INTO pg_profile_edit_log (user_id, field, old_value, new_value, changed_by, source) "
                         "VALUES (?,?,?,?,?,?)",
                         [user_id, f, '' if cur[f] is None else str(cur[f]), '' if v is None else str(v), by or '',
                          (via + (' — ' + note if note else ''))[:200]])
            changed.append(f)
    return changed


def rank_state(conn, user_id):
    """What the doctor may do: confirm (first time), correct (once), or nothing (ask the team)."""
    u = conn.execute("SELECT neet_pg_rank, neet_pg_score, home_state_rank, state, rank_confirmed_at, "
                     "COALESCE(rank_self_edits,0) AS edits, rank_prompt_closed_at, correction_prompt_closed_at "
                     "FROM pg_users WHERE id=?", [user_id]).fetchone()
    if not u:
        return None
    u = dict(u)
    confirmed = u['rank_confirmed_at'] is not None
    left = 0 if not confirmed else max(0, SELF_CORRECTIONS - int(u['edits'] or 0))
    not_me = conn.execute("SELECT 1 FROM pg_allotment_marks WHERE user_id=? AND verdict='not_me' AND via='doctor' "
                          "LIMIT 1", [user_id]).fetchone() is not None
    # Ask ONCE (founder 2026-10-26): the confirm pop-up shows until the doctor confirms OR closes it once; the
    # correction pop-up after "This isn't me" shows once. Both can still be done any time from My Allotments.
    return {'neet_pg_rank': u['neet_pg_rank'], 'neet_pg_score': u['neet_pg_score'],
            'home_state': u['state'] or '', 'home_state_rank': u['home_state_rank'],
            'rank_confirmed': confirmed,
            'rank_confirmed_at': str(u['rank_confirmed_at'])[:16] if confirmed else '',
            'needs_confirm': not confirmed,
            'show_confirm_prompt': (not confirmed) and u['rank_prompt_closed_at'] is None,
            'show_correction_prompt': bool(confirmed and left > 0 and not_me and u['correction_prompt_closed_at'] is None),
            'corrections_left': left}


def summary(conn):
    """Per published round: doctors with the needed rank, how many got a seat (MD/MS vs DNB), by doctor type."""
    from pg_admin.routes.users_admin import _category_case
    users = [dict(r) for r in conn.execute(
        f"SELECT u.id, u.neet_pg_rank, u.home_state_rank, u.state, ({_category_case('u')}) AS cat "
        f"FROM pg_users u").fetchall()]
    allots = for_users(conn, users, include_not_me=False)
    auths = _authorities()
    rows = []
    for rd in _rounds(conn):
        code = rd['authority_code']
        if code == 'mcc':
            pool = [u for u in users if (u['neet_pg_rank'] or 0) > 0]
        else:
            st = _state_key(auths.get(code, ('', ''))[1])
            pool = [u for u in users if (u['home_state_rank'] or 0) > 0 and _state_key(u['state']) == st]
        cats = {c: {'with_rank': 0, 'mdms': 0, 'dnb': 0} for c in ('internal', 'paid', 'free', 'team')}
        for u in pool:
            c = cats.setdefault(u['cat'], {'with_rank': 0, 'mdms': 0, 'dnb': 0})
            c['with_rank'] += 1
            hit = [a for a in allots.get(u['id'], [])
                   if a['authority_code'] == code and a['round'] == rd['round']]
            if hit:
                c[hit[0]['program']] += 1
        tot = {k: sum(c[k] for c in cats.values()) for k in ('with_rank', 'mdms', 'dnb')}
        rows.append({'authority_code': code, 'authority_name': auths.get(code, (code, ''))[0], 'round': rd['round'],
                     'status': rd['status'], 'by_type': cats, 'total': tot})
    return rows
