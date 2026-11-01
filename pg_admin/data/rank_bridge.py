"""All-India rank + state rank for every 2025 cut-off (founder 2026-11-01).

Most states' 2025 cut-offs already hold NEET All-India ranks. Tamil Nadu's hold TN STATE merit ranks — so a
doctor's All-India rank was being compared with TN state ranks (predictor, comparisons). Using TN's 2025-26 rank
lists (pg_state_merit, academic year 2025-26: state rank → roll → AIR from the NBEMS 2025 result) every TN
cut-off gets its All-India equivalent.

ADDITIVE ONLY — the original r1..r4 / stray / closing_rank are never changed. New columns on pg_cutoffs:
  r1_ai, r2_ai, r3_ai, r4_ai, stray_ai, closing_ai  — the All-India rank (same as the original for AIR states;
                                                       converted for state-rank states; NULL when it can't be)
  rank_basis — 'air' (original is All-India) | 'state' (original is a state rank; *_ai converted where possible)
Display rule: All-India rank first, the state rank underneath; a state rank alone is always labelled as one.
"""
import logging

RANK_COLS = ('r1', 'r2', 'r3', 'r4', 'stray', 'closing_rank')
AI_COL = {'r1': 'r1_ai', 'r2': 'r2_ai', 'r3': 'r3_ai', 'r4': 'r4_ai', 'stray': 'stray_ai', 'closing_rank': 'closing_ai'}

# pg_cutoffs.authority (2025) whose ranks are STATE ranks → the 2025 merit lists that convert them
STATE_RANK_CUTOFFS = {
    'Tamil Nadu': {
        'authority_code': 'dmer_tn', 'academic_year': '2025-26', 'label': 'TN rank',
        'lists': {'gq': 'PG Government Quota Provisional Rank List', 'mq': 'PG Management Quota Provisional Rank List'},
    },
}


def _tn_list(quota):
    q = (quota or '').lower()
    return 'mq' if ('management' in q or 'nri' in q or 'cmc 50' in q) else 'gq'


LIST_FOR = {'Tamil Nadu': _tn_list}


_READY = False
# SQL: the All-India value of a rank column — the *_ai column once filled; before the first fill (rank_basis
# NULL) the original, which is All-India for every state except the state-rank ones (still unconverted then)
def ai_sql(col, alias=''):
    a = (alias + '.') if alias else ''
    return (f"(CASE WHEN {a}rank_basis IS NULL THEN {a}{col} ELSE {a}{AI_COL[col]} END)")


SELECT_AI = ', '.join(f"{c}" for c in AI_COL.values()) + ', rank_basis'


def ensure_cols(conn):
    """Once per process (they're cheap no-ops after the first time, but not free)."""
    global _READY
    if _READY:
        return
    try:
        for c in AI_COL.values():
            conn.execute(f"ALTER TABLE pg_cutoffs ADD COLUMN IF NOT EXISTS {c} INTEGER")
        conn.execute("ALTER TABLE pg_cutoffs ADD COLUMN IF NOT EXISTS rank_basis TEXT")
        conn.commit()
        _READY = True
    except Exception as e:
        logging.warning("rank_bridge ensure_cols: %s", e)
        try: conn.rollback()
        except Exception: pass


def state_rank_maps(conn, authority):
    """{list_key: {state_rank: air}} for a state-rank authority (empty if its merit lists aren't loaded)."""
    cfg = STATE_RANK_CUTOFFS.get(authority)
    if not cfg:
        return {}
    out = {}
    for key, name in cfg['lists'].items():
        out[key] = {r['state_rank']: r['air'] for r in conn.execute(
            "SELECT state_rank, air FROM pg_state_merit WHERE authority_code=? AND academic_year=? AND list_name=? "
            "AND state_rank IS NOT NULL AND air IS NOT NULL", [cfg['authority_code'], cfg['academic_year'], name]).fetchall()}
    return out


def fill_cutoffs(conn, year=2025):
    """Fill the *_ai columns + rank_basis for one cut-off year (idempotent; originals untouched)."""
    ensure_cols(conn)
    sets = ', '.join(f"{AI_COL[c]} = {c}" for c in RANK_COLS)
    states = list(STATE_RANK_CUTOFFS)
    ph = ','.join(['?'] * len(states))
    conn.execute(f"UPDATE pg_cutoffs SET {sets}, rank_basis = 'air' WHERE year = ? "
                 f"AND COALESCE(authority,'') NOT IN ({ph})", [year] + states)
    stats = {'air_rows': conn.execute(f"SELECT COUNT(*) AS n FROM pg_cutoffs WHERE year = ? AND rank_basis = 'air'",
                                      [year]).fetchone()['n']}
    for auth in states:
        maps = state_rank_maps(conn, auth)
        if not any(maps.values()):
            stats[auth] = 'merit lists not loaded — left as state ranks'
            conn.execute("UPDATE pg_cutoffs SET rank_basis = 'state' WHERE year = ? AND authority = ?", [year, auth])
            continue
        pick = LIST_FOR[auth]
        rows = conn.execute(f"SELECT id, quota, {', '.join(RANK_COLS)} FROM pg_cutoffs WHERE year = ? AND authority = ?",
                            [year, auth]).fetchall()
        done = miss = 0
        batch = []
        for r in rows:
            m = maps.get(pick(r['quota'])) or {}
            vals = []
            for c in RANK_COLS:
                v = r[c]
                a = m.get(v) if v else None
                if v:
                    done += 1 if a else 0
                    miss += 0 if a else 1
                vals.append(a)
            batch.append(vals + [r['id']])
        sets_ai = ', '.join(f"{AI_COL[c]} = ?" for c in RANK_COLS)
        for b in batch:
            conn.execute(f"UPDATE pg_cutoffs SET {sets_ai}, rank_basis = 'state' WHERE id = ?", b)
        stats[auth] = {'rows': len(rows), 'ranks_converted': done, 'ranks_not_found': miss}
    conn.commit()
    return stats


def state_label(authority):
    return (STATE_RANK_CUTOFFS.get(authority) or {}).get('label') or 'State rank'


def present(d):
    """Shape one cut-off row for the website (in place): r1..closing_rank become the ALL-INDIA rank (None when a
    state-rank seat couldn't be converted); the state rank goes to <col>_state; rank_basis + state_rank_label say
    what is shown. Rows without the *_ai columns (not filled yet) pass through unchanged."""
    basis = d.get('rank_basis')
    if basis not in ('air', 'state'):          # not filled yet → as before, minus the empty helper columns
        for c in AI_COL.values():
            d.pop(c, None)
        d.pop('rank_basis', None)
        return d
    if basis == 'state':
        for c in RANK_COLS:
            d[c + '_state'] = d.get(c)
            d[c] = d.get(AI_COL[c])
        d['state_rank_label'] = state_label(d.get('authority'))
        d['rank_basis'] = 'air+state' if any(d.get(c) for c in RANK_COLS) else 'state'
    for c in AI_COL.values():
        d.pop(c, None)
    return d


SEAT_CR = ('cr_r1', 'cr_r2', 'cr_r3', 'cr_closing')


def present_seat_rows(conn, body, rows):
    """Seat-matrix rows (in place): their 2025 cr_* values were copied from the state's cut-offs, so for a
    state-rank authority they are STATE ranks → cr_* become All-India (None if not convertible), the state rank
    goes to <col>_state; rank_basis per row. Needs the row's cutoff_quota to pick the list (GQ / MQ)."""
    auth = (body or '').split(' —')[0].strip()
    if auth not in STATE_RANK_CUTOFFS:
        return rows
    maps, pick = state_rank_maps(conn, auth), LIST_FOR[auth]
    if not any(maps.values()):
        return rows
    for r in rows:
        if not any(r.get(c) for c in SEAT_CR):
            continue
        m = maps.get(pick(r.get('cutoff_quota') or r.get('quota'))) or {}
        for c in SEAT_CR:
            v = r.get(c)
            r[c + '_state'] = v
            r[c] = m.get(v) if v else None
        r['state_rank_label'] = state_label(auth)
        r['rank_basis'] = 'air+state' if any(r.get(c) for c in SEAT_CR) else 'state'
    return rows
