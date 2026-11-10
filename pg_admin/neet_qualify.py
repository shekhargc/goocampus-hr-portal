"""NEET-PG qualification from the official result sheet (founder 2026-11-09/10).

Qualified = score 262 or above. Many doctors entered only their All-India rank, so the
cut-off is also expressed as a RANK: the worst AIR in the NBEMS master result
(pg_neet_result) that scored 262+. A doctor with no score but a rank at or better than
that rank is qualified ("by rank"); a worse rank is not qualified.

Also looks up the official score for a rank (score_for_ranks) — used by the
"Check scores vs result" admin tool (routes/diag_neet_scores.py).
"""
import time
import logging

NEET_YEAR = 2026
QUALIFY_SCORE = 262

_cache = {'at': 0.0, 'rank': None}


def cutoff_rank(conn):
    """Worst All-India rank with score >= 262 in the NEET-PG result (cached 1 h); None if not loaded."""
    if time.time() - _cache['at'] < 3600 and _cache['rank']:
        return _cache['rank']
    try:
        r = conn.execute("SELECT MAX(air) AS r FROM pg_neet_result WHERE exam_year = ? AND score >= ? "
                         "AND air IS NOT NULL", (NEET_YEAR, QUALIFY_SCORE)).fetchone()
        rank = int(r['r']) if r and r['r'] else None
    except Exception as e:
        logging.error("neet_qualify.cutoff_rank: %s", e)
        try: conn.rollback()
        except Exception: pass
        rank = None
    _cache.update(at=time.time(), rank=rank)
    return rank


def qual_sql(conn, ualias='u'):
    """{'yes'|'no'|'unknown': SQL condition}. A doctor's own score decides; with no score, the rank vs the cut-off rank."""
    s, k = f"COALESCE({ualias}.neet_pg_score,0)", f"COALESCE({ualias}.neet_pg_rank,0)"
    cut = cutoff_rank(conn)
    if not cut:                                   # result not loaded → score only
        return {'yes': f"{s} >= {QUALIFY_SCORE}", 'no': f"({s} > 0 AND {s} < {QUALIFY_SCORE})",
                'unknown': f"{s} <= 0"}
    return {'yes': f"({s} >= {QUALIFY_SCORE} OR ({s} <= 0 AND {k} > 0 AND {k} <= {cut}))",
            'no': f"(({s} > 0 AND {s} < {QUALIFY_SCORE}) OR ({s} <= 0 AND {k} > {cut}))",
            'unknown': f"({s} <= 0 AND {k} <= 0)"}


def status(score, rank, cut):
    """'yes' | 'no' | 'yes_rank' | 'no_rank' | '' for one doctor (list column)."""
    if score and score > 0:
        return 'yes' if score >= QUALIFY_SCORE else 'no'
    if rank and rank > 0 and cut:
        return 'yes_rank' if rank <= cut else 'no_rank'
    return ''


def score_for_ranks(conn, ranks):
    """{air: (min_score, max_score, rows)} from the result sheet for the given ranks."""
    ranks = sorted({int(r) for r in ranks if r and int(r) > 0})
    if not ranks:
        return {}
    out = {}
    for r in conn.execute("SELECT air, MIN(score) AS lo, MAX(score) AS hi, COUNT(*) AS n FROM pg_neet_result "
                          "WHERE exam_year = ? AND air = ANY(?) GROUP BY air", (NEET_YEAR, ranks)).fetchall():
        out[int(r['air'])] = (r['lo'], r['hi'], int(r['n']))
    return out


def ranks_for_scores(conn, scores):
    """{score: (best_air, worst_air)} — the rank band that a score falls in."""
    scores = sorted({int(s) for s in scores if s is not None})
    if not scores:
        return {}
    return {int(r['score']): (r['lo'], r['hi']) for r in conn.execute(
        "SELECT score, MIN(air) AS lo, MAX(air) AS hi FROM pg_neet_result WHERE exam_year = ? AND score = ANY(?) "
        "AND air IS NOT NULL GROUP BY score", (NEET_YEAR, scores)).fetchall()}
