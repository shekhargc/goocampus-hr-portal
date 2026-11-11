"""2026-27 college fees: a year-wise fee store, kept separate from the 2025 fees (founder 2026-11-11).

The 2025 fee lives on every pg_cutoffs row (pg_cutoffs.fee) and is NEVER changed. The 2026-27 fee for a seat
(authority × institute × course × quota [× category]) lives in pg_fees. Every screen that shows a fee uses ONE
rule:  the 2026-27 fee when we have a verified one, otherwise the 2025 fee, tagged "2025".

Each 2026 row was cross-checked across every stored document of the authority before loading (fee structure /
GOs before counselling, the seat matrix, and every allotment list — the latest official figure wins; see
memory feedback_fee_cross_check). It carries:
  fee_total   — the amount the authority prints = what the candidate pays at admission for the year
                (tuition + admission / university fee; hostel and other college charges are NOT included)
  tuition     — tuition per year, when the printed figure could be split (NULL = not published separately)
  other_fee / other_label — the admission / university fee inside fee_total (one-time, first year)
  note        — e.g. "SC/ST/Cat-1 may be exempt", "includes RGUHS registration fee"
  source / source_date — the document the figure was taken from
  prev_fee / prev_source — an earlier official figure, when the fee was changed (e.g. reduced in Round 1)

SQL helpers (join_sql / EFF_FEE / EFF_YEAR / DETAIL_SQL) are used by the aggregate fee queries so filtering and
sorting by fee use the 2026 figure; attach() overlays plain row lists (predictor, choice lists, seat matrix).
Everything degrades to the 2025 fee when the table is not there (cold start) — never an error.
"""
import logging
import time

FEE_YEAR = 2026
ACADEMIC_YEAR = '2026-27'

COLS = ('fee_year', 'academic_year', 'authority', 'institute', 'course', 'quota', 'category',
        'inst_key', 'course_key', 'quota_key', 'category_key',
        'fee_total', 'tuition', 'other_fee', 'other_label', 'note',
        'source', 'source_inbox_id', 'source_date', 'prev_fee', 'prev_source', 'status')

_READY = {'ok': None, 'at': 0.0}


def key(v):
    """Normalised match key: lower-case, single spaces (same as KEY_SQL)."""
    return ' '.join(str(v or '').lower().split())


def KEY_SQL(col):
    return f"LOWER(REGEXP_REPLACE(TRIM(COALESCE({col},'')), '\\s+', ' ', 'g'))"


def ensure_table(conn):
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS pg_fees ("
            " id SERIAL PRIMARY KEY, fee_year INTEGER NOT NULL, academic_year TEXT,"
            " authority TEXT NOT NULL, institute TEXT, course TEXT, quota TEXT, category TEXT DEFAULT '',"
            " inst_key TEXT NOT NULL, course_key TEXT NOT NULL, quota_key TEXT NOT NULL,"
            " category_key TEXT NOT NULL DEFAULT '',"
            " fee_total NUMERIC(14,2) NOT NULL, tuition NUMERIC(14,2), other_fee NUMERIC(14,2), other_label TEXT,"
            " note TEXT, source TEXT, source_inbox_id INTEGER, source_date TEXT,"
            " prev_fee NUMERIC(14,2), prev_source TEXT, status TEXT,"
            " loaded_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS pg_fees_seat_uq ON pg_fees "
                     "(fee_year, authority, inst_key, course_key, quota_key, category_key)")
        conn.commit()
        _READY.update(ok=True, at=time.time())
        return True
    except Exception as e:
        logging.warning("fees.ensure_table: %s", e)
        try: conn.rollback()
        except Exception: pass
        return False


def available(conn):
    """True when pg_fees exists (checked once a minute; a missing table just means 2025 fees everywhere)."""
    if _READY['ok'] and time.time() - _READY['at'] < 60:
        return True
    try:
        r = conn.execute("SELECT to_regclass('public.pg_fees') AS t").fetchone()
        ok = bool(r and r['t'])
    except Exception:
        try: conn.rollback()
        except Exception: pass
        ok = False
    _READY.update(ok=ok, at=time.time())
    return ok


# ── SQL pieces for queries over pg_cutoffs c ───────────────────────────────────
def join_sql(conn, alias='c'):
    """LEFT JOIN of the 2026 fee for each pg_cutoffs row ('' when the table is missing)."""
    if not available(conn):
        return ''
    a = alias
    return (f" LEFT JOIN pg_fees f26 ON f26.fee_year = {FEE_YEAR} AND f26.authority = {a}.authority"
            f" AND f26.inst_key = {KEY_SQL(a + '.institute')} AND f26.course_key = {KEY_SQL(a + '.course')}"
            f" AND f26.quota_key = {KEY_SQL(a + '.quota')}"
            f" AND (f26.category_key = '' OR f26.category_key = {KEY_SQL(a + '.category')}) ")


def eff_fee(conn, alias='c'):
    return f"COALESCE(f26.fee_total, {alias}.fee)" if available(conn) else f"{alias}.fee"


def eff_year(conn, alias='c'):
    return (f"(CASE WHEN f26.id IS NOT NULL THEN {FEE_YEAR} ELSE {alias}.year END)"
            if available(conn) else f"{alias}.year")


DETAIL = ('tuition', 'other_fee', 'other_label', 'note', 'source', 'source_date', 'prev_fee', 'prev_source')


def detail_sql(conn, agg=True):
    """Extra SELECT columns (fee_tuition, fee_other, ...) — MAX()ed for GROUP BY queries."""
    if not available(conn):
        return ''
    w = (lambda c: f"MAX(f26.{c})") if agg else (lambda c: f"f26.{c}")
    return ', ' + ', '.join(f"{w(c)} AS fee_{c}" for c in DETAIL)


def _f(v):
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def present(d, fee_field='fee', year_field='fee_year'):
    """Tidy one output row: fee as float, fee_year, fee_label ('2026-27' / '2025'), and fee_info (the breakup +
    source) for a 2026 fee. Pops the flat fee_<detail> columns."""
    flat = {c: d.pop('fee_' + c, None) for c in DETAIL}
    d[fee_field] = _f(d.get(fee_field))
    yr = d.get(year_field)
    try:
        yr = int(yr) if yr is not None else None
    except Exception:
        yr = None
    d[year_field] = yr
    if yr == FEE_YEAR and d[fee_field] is not None:
        d['fee_label'] = ACADEMIC_YEAR
        d['fee_info'] = {
            'year': ACADEMIC_YEAR, 'total': d[fee_field],
            'tuition': _f(flat['tuition']), 'other_fee': _f(flat['other_fee']),
            'other_label': flat['other_label'] or None, 'note': flat['note'] or None,
            'source': flat['source'] or None, 'source_date': flat['source_date'] or None,
            'prev_fee': _f(flat['prev_fee']), 'prev_source': flat['prev_source'] or None,
            'includes': 'Tuition + admission/university fee as printed by the authority. Hostel and other '
                        'college charges are not included.'}
    else:
        d['fee_label'] = str(yr) if (yr and d[fee_field] is not None) else None
        d['fee_info'] = None
    return d


# ── Python overlay for row lists ───────────────────────────────────────────────
def load_map(conn, authorities=None):
    """{(authority, inst_key, course_key, quota_key, category_key): row dict} for FEE_YEAR."""
    if not available(conn):
        return {}
    try:
        sql = "SELECT * FROM pg_fees WHERE fee_year = ?"
        params = [FEE_YEAR]
        auths = sorted({a for a in (authorities or []) if a})
        if authorities is not None:
            if not auths:
                return {}
            sql += " AND authority IN (" + ','.join(['?'] * len(auths)) + ")"
            params += auths
        out = {}
        for r in conn.execute(sql, params).fetchall():
            r = dict(r)
            out[(r['authority'], r['inst_key'], r['course_key'], r['quota_key'], r['category_key'] or '')] = r
        return out
    except Exception as e:
        logging.warning("fees.load_map: %s", e)
        try: conn.rollback()
        except Exception: pass
        return {}


def lookup(fmap, authority, institute, course, quota, category=''):
    if not fmap:
        return None
    k = (authority, key(institute), key(course), key(quota))
    return fmap.get(k + (key(category),)) or fmap.get(k + ('',))


def attach(conn, rows, authority=None, inst='institute', course='course', quota='quota', category='category',
           fee_field='fee', year_field='fee_year', base_year=2025, fmap=None):
    """Overlay the 2026 fee on each row dict in place (rows keep their 2025 fee when there is none).
    authority: a fixed authority name, or None to read row['authority']."""
    if not rows:
        return rows
    if fmap is None:
        auths = {authority} if authority else {r.get('authority') for r in rows}
        fmap = load_map(conn, auths)
    for r in rows:
        f = lookup(fmap, authority or r.get('authority'), r.get(inst), r.get(course), r.get(quota),
                   r.get(category) or '')
        if f:
            r[fee_field] = f['fee_total']
            r[year_field] = FEE_YEAR
            for c in DETAIL:
                r['fee_' + c] = f.get(c)
        elif r.get(year_field) is None:
            r[year_field] = base_year if r.get(fee_field) is not None else None
        present(r, fee_field, year_field)
    return rows


def seat_matrix_authority(body):
    """pg_seat_matrix.counselling_body → the pg_cutoffs authority whose fees apply."""
    b = (body or '').strip()
    if '— State Counselling' in b or '- State Counselling' in b:
        return b.split('—')[0].split(' - ')[0].strip()
    if b.upper().startswith('MCC'):
        return 'MCC (All India)'
    return b


# ── Loading (admin / ingest tool) ──────────────────────────────────────────────
def load_rows(conn, authority, rows, loaded_by, replace=True, fee_year=FEE_YEAR):
    """Replace (default) the authority's FEE_YEAR fee rows with `rows` (list of dicts with COLS fields).
    Returns the number written. Only the new year's rows are touched — never pg_cutoffs."""
    ensure_table(conn)
    if replace:
        conn.execute("DELETE FROM pg_fees WHERE fee_year = ? AND authority = ?", [fee_year, authority])
    items, seen = [], set()
    for r in rows:
        if r.get('fee_total') in (None, '') or float(r['fee_total']) <= 1:
            continue
        k = (key(r.get('institute')), key(r.get('course')), key(r.get('quota')), key(r.get('category')))
        if not all(k[:3]) or k in seen:
            continue
        seen.add(k)
        items.append([fee_year, r.get('academic_year') or ACADEMIC_YEAR, authority,
                      r.get('institute'), r.get('course'), r.get('quota'), r.get('category') or '',
                      k[0], k[1], k[2], k[3],
                      r['fee_total'], r.get('tuition'), r.get('other_fee'), r.get('other_label'), r.get('note'),
                      r.get('source'), r.get('source_inbox_id'), r.get('source_date'),
                      r.get('prev_fee'), r.get('prev_source'), r.get('status'), loaded_by])
    if items:
        conn.execute_batch(
            "INSERT INTO pg_fees (" + ', '.join(COLS) + ", loaded_by) VALUES ("
            + ','.join(['?'] * (len(COLS) + 1)) + ")", items, page_size=500)
    conn.commit()
    _READY.update(ok=True, at=time.time())
    return len(items)


def summary(conn):
    if not available(conn):
        return []
    try:
        return [dict(r) for r in conn.execute(
            "SELECT authority, fee_year, COUNT(*) AS seats, COUNT(tuition) AS with_tuition, "
            "COUNT(prev_fee) AS changed, MIN(created_at) AS loaded_at, MAX(loaded_by) AS loaded_by "
            "FROM pg_fees GROUP BY authority, fee_year ORDER BY authority").fetchall()]
    except Exception as e:
        logging.warning("fees.summary: %s", e)
        try: conn.rollback()
        except Exception: pass
        return []
