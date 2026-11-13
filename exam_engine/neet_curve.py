"""Predicted NEET PG All-India rank from a mock score — using the real NBEMS result.

The portal holds NBEMS's published result (pg_neet_result: score /720 + All-India rank, ~2.7 lakh rows per
year, loaded by the results team). A mock score is put on the same /720 scale and looked up:
    predicted AIR = 1 + number of real candidates who scored MORE than that.
The range is the rank at ±8 marks (two questions either way). This assumes the mock is about as hard as
the real paper — it is a guide, and the result page says so.

This is the exam engine's only read of a portal table; if the engine moves to its own service, this module
becomes an API call (or a copy of the curve).
"""
import bisect
import logging
import time

_CACHE = {'at': 0, 'curve': None}
TTL = 6 * 3600
RANGE_MARKS = 8


def _load(conn):
    try:
        r = conn.execute("SELECT to_regclass('pg_neet_result') AS t").fetchone()
        if not r or not r['t']:
            return None
        yr = conn.execute("SELECT MAX(exam_year) AS y FROM pg_neet_result WHERE air IS NOT NULL AND score IS NOT NULL").fetchone()
        year = yr['y'] if yr else None
        if not year:
            return None
        rows = conn.execute("SELECT score, COUNT(*) AS n FROM pg_neet_result WHERE exam_year=? AND air IS NOT NULL "
                            "AND score IS NOT NULL GROUP BY score ORDER BY score DESC", (year,)).fetchall()
    except Exception as e:
        logging.warning(f'neet curve unavailable: {e}')
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    scores, above, total = [], [], 0
    for r in rows:                       # descending score: `above` = candidates with a higher score
        scores.append(int(r['score']))
        above.append(total)
        total += int(r['n'])
    return {'year': int(year), 'scores_desc': scores, 'above': above, 'total': total} if total else None


def curve(conn):
    if _CACHE['curve'] is None or time.time() - _CACHE['at'] > TTL:
        _CACHE['curve'] = _load(conn)
        _CACHE['at'] = time.time()
    return _CACHE['curve']


def air_for(c, score_720):
    """1 + candidates who scored strictly more than score_720."""
    asc = list(reversed(c['scores_desc']))             # ascending
    i = bisect.bisect_right(asc, score_720)              # first index with score > score_720
    n_higher_groups = len(asc) - i
    if n_higher_groups <= 0:
        return 1
    # candidates above = cumulative count up to the lowest score that is still > score_720
    idx_desc = n_higher_groups - 1                       # position (in descending list) of that lowest higher score
    return c['above'][idx_desc] + _group_size(c, idx_desc) + 1


def _group_size(c, idx_desc):
    nxt = c['above'][idx_desc + 1] if idx_desc + 1 < len(c['above']) else c['total']
    return nxt - c['above'][idx_desc]


def predict(conn, score, max_score):
    """→ {'air', 'air_best', 'air_worst', 'score_720', 'year', 'candidates'} or None."""
    if not max_score:
        return None
    c = curve(conn)
    if not c:
        return None
    s = round(score * 720 / max_score)
    return {'air': air_for(c, s), 'air_best': air_for(c, s + RANGE_MARKS), 'air_worst': air_for(c, s - RANGE_MARKS),
            'score_720': s, 'year': c['year'], 'candidates': c['total']}
