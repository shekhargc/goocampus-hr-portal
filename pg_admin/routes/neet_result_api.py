"""NEET-PG master result + state merit-list rank bridge (founder 2026-10-30).

  pg_neet_result   — NBEMS's published result, one row per candidate: roll number, application number,
                     score (/720) and All-India rank (status ranked | absent | withheld). No names. Kept as the
                     master sheet for year-on-year score↔rank analysis and to fill the All-India rank into any
                     list that prints only roll numbers.
  pg_state_merit   — each state's merit list as rank pairs: roll number, All-India rank, state merit rank,
                     the state's score and category. No names. The bridge between a doctor's All-India rank and
                     their state rank (My Allotments, state results printed with state ranks only).

Both are written only from the Mac (X-News-Key), in parts: mode start (clears that year / list) → append … → finish.
"""
import logging
from flask import request, jsonify
from db import get_db
from pg_admin.routes.api_news_ingest import _ok

MAX_ROWS = 25000          # per call — the 2026 result is ~2.7 lakh rows, sent in parts


def _s(v):
    return str(v).strip() if v is not None else ''


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def ensure_neet_result_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_neet_result (
        id SERIAL PRIMARY KEY,
        exam_year INTEGER NOT NULL,              -- 2026 = NEET-PG 2026
        sno INTEGER,
        app_seq TEXT DEFAULT '',                 -- NBEMS application sequence number
        roll_no TEXT NOT NULL,
        score INTEGER,                           -- out of 720 (can be negative); NULL when absent / withheld
        air INTEGER,                             -- NEET-PG All-India rank
        status TEXT DEFAULT 'ranked'             -- ranked | absent | withheld
    )''')
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_neet_result ON pg_neet_result (exam_year, roll_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_neet_result_air ON pg_neet_result (exam_year, air)")
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_state_merit (
        id SERIAL PRIMARY KEY,
        authority_code TEXT NOT NULL,
        academic_year TEXT NOT NULL DEFAULT '2026-27',
        list_name TEXT NOT NULL,                 -- e.g. 'Round 1 State Merit List (Final)'
        roll_no TEXT DEFAULT '',
        air INTEGER,                             -- All-India rank (from the list, else from pg_neet_result by roll)
        state_rank INTEGER,
        score NUMERIC(8,2),                      -- the state's score (NEET score + weightage where the state adds it)
        category TEXT DEFAULT '',
        quota TEXT DEFAULT ''                    -- e.g. In-service / NRI / Management lists
    )''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_state_merit_list ON pg_state_merit (authority_code, academic_year, list_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_state_merit_air ON pg_state_merit (authority_code, air)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_state_merit_roll ON pg_state_merit (roll_no)")
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_state_merit_source (
        id SERIAL PRIMARY KEY,
        authority_code TEXT NOT NULL,
        academic_year TEXT NOT NULL DEFAULT '2026-27',
        list_name TEXT NOT NULL,
        published_on TEXT DEFAULT '',
        source_file_name TEXT DEFAULT '',
        row_count INTEGER DEFAULT 0,
        air_from_list INTEGER DEFAULT 0,         -- rows whose All-India rank the list printed
        air_from_roll INTEGER DEFAULT 0,         -- rows filled from the NBEMS result by roll number
        air_mismatch INTEGER DEFAULT 0,          -- printed AIR ≠ NBEMS AIR for the same roll (should be 0)
        notes TEXT DEFAULT '',
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_state_merit_source "
                 "ON pg_state_merit_source (authority_code, academic_year, list_name)")


def api_neet_result_ingest():
    """POST /api/pg/neet-result/ingest (X-News-Key)
    {exam_year, mode: start|append|finish, rows:[{sno, app, roll, score, air, status}]}
    start clears that exam year first; finish (rows optional) returns the stored counts."""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    d = request.get_json(silent=True) or {}
    year, mode, rows = _int(d.get('exam_year')), _s(d.get('mode')), d.get('rows') or []
    if not year or mode not in ('start', 'append', 'finish') or len(rows) > MAX_ROWS:
        return jsonify({'ok': False, 'error': 'exam_year, mode start|append|finish, <= %d rows' % MAX_ROWS}), 400
    conn = get_db()
    try:
        ensure_neet_result_tables(conn)
        if mode == 'start':
            conn.execute("DELETE FROM pg_neet_result WHERE exam_year=?", [year])
        batch = []
        for r in rows:
            roll = _s(r.get('roll'))
            if not roll:
                continue
            st = _s(r.get('status')) or ('ranked' if _int(r.get('air')) else 'absent')
            batch.append([year, _int(r.get('sno')), _s(r.get('app')), roll, _int(r.get('score')), _int(r.get('air')), st])
        if batch:
            conn.execute_batch("INSERT INTO pg_neet_result (exam_year, sno, app_seq, roll_no, score, air, status) "
                               "VALUES (?,?,?,?,?,?,?) ON CONFLICT (exam_year, roll_no) DO UPDATE SET sno=EXCLUDED.sno, "
                               "app_seq=EXCLUDED.app_seq, score=EXCLUDED.score, air=EXCLUDED.air, status=EXCLUDED.status",
                               batch, page_size=1000)
        conn.commit()
        out = {'ok': True, 'mode': mode, 'rows': len(batch)}
        if mode == 'finish':
            t = conn.execute("SELECT COUNT(*) AS n, COUNT(air) AS ranked, SUM(CASE WHEN status='absent' THEN 1 ELSE 0 END) AS absent, "
                             "SUM(CASE WHEN status='withheld' THEN 1 ELSE 0 END) AS withheld, MIN(air) AS lo, MAX(air) AS hi, "
                             "MAX(score) AS top FROM pg_neet_result WHERE exam_year=?", [year]).fetchone()
            out['stored'] = {k: (int(v) if v is not None else None) for k, v in dict(t).items()}
        return jsonify(out)
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("neet_result_ingest: %s", e)
        return jsonify({'ok': False, 'error': 'server_error', 'detail': str(e)[:300]}), 500
    finally:
        conn.close()


def api_state_merit_ingest():
    """POST /api/pg/state-merit/ingest (X-News-Key)
    {authority_code, year, list_name, published_on, source_file_name, notes, exam_year (default 2026),
     mode: start|append|finish, rows:[{roll, air, state_rank, score, category, quota}]}
    A row without an All-India rank gets it from the NBEMS result by roll number; a printed rank that disagrees
    with NBEMS is counted (air_mismatch) and the printed value is kept. start clears that one list."""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    d = request.get_json(silent=True) or {}
    auth, year, name, mode = _s(d.get('authority_code')), _s(d.get('year')) or '2026-27', _s(d.get('list_name')), _s(d.get('mode'))
    rows, exam_year = d.get('rows') or [], _int(d.get('exam_year')) or 2026
    if not auth or not name or mode not in ('start', 'append', 'finish') or len(rows) > MAX_ROWS:
        return jsonify({'ok': False, 'error': 'authority_code, list_name, mode start|append|finish required'}), 400
    conn = get_db()
    try:
        ensure_neet_result_tables(conn)
        key = [auth, year, name]
        if mode == 'start':
            conn.execute("DELETE FROM pg_state_merit WHERE authority_code=? AND academic_year=? AND list_name=?", key)
        rolls = [_s(r.get('roll')) for r in rows if _s(r.get('roll'))]
        nbems = {}
        if rolls:
            nbems = {r['roll_no']: r['air'] for r in conn.execute(
                "SELECT roll_no, air FROM pg_neet_result WHERE exam_year=? AND roll_no = ANY(?)", [exam_year, rolls]).fetchall()}
        batch, from_list, from_roll, mismatch = [], 0, 0, 0
        for r in rows:
            roll, air = _s(r.get('roll')), _int(r.get('air'))
            if air:
                from_list += 1
                if roll and nbems.get(roll) and nbems[roll] != air:
                    mismatch += 1
            elif roll and nbems.get(roll):
                air, from_roll = nbems[roll], from_roll + 1
            sc = r.get('score')
            try:
                sc = float(sc) if sc not in (None, '') else None
            except (TypeError, ValueError):
                sc = None
            batch.append(key + [roll, air, _int(r.get('state_rank')), sc, _s(r.get('category')), _s(r.get('quota'))])
        if batch:
            conn.execute_batch("INSERT INTO pg_state_merit (authority_code, academic_year, list_name, roll_no, air, state_rank, "
                               "score, category, quota) VALUES (?,?,?,?,?,?,?,?,?)", batch, page_size=1000)
        src = conn.execute("SELECT id FROM pg_state_merit_source WHERE authority_code=? AND academic_year=? AND list_name=?",
                           key).fetchone()
        if mode == 'start' or not src:
            conn.execute("DELETE FROM pg_state_merit_source WHERE authority_code=? AND academic_year=? AND list_name=?", key)
            conn.execute("INSERT INTO pg_state_merit_source (authority_code, academic_year, list_name) VALUES (?,?,?)", key)
        conn.execute("UPDATE pg_state_merit_source SET air_from_list = air_from_list + ?, air_from_roll = air_from_roll + ?, "
                     "air_mismatch = air_mismatch + ? WHERE authority_code=? AND academic_year=? AND list_name=?",
                     [from_list, from_roll, mismatch] + key)
        if mode == 'finish':
            n = conn.execute("SELECT COUNT(*) AS n FROM pg_state_merit WHERE authority_code=? AND academic_year=? AND list_name=?",
                             key).fetchone()['n']
            conn.execute("UPDATE pg_state_merit_source SET row_count=?, published_on=?, source_file_name=?, notes=?, "
                         "uploaded_at=CURRENT_TIMESTAMP WHERE authority_code=? AND academic_year=? AND list_name=?",
                         [int(n), _s(d.get('published_on')), _s(d.get('source_file_name')), _s(d.get('notes'))] + key)
        conn.commit()
        s = dict(conn.execute("SELECT row_count, air_from_list, air_from_roll, air_mismatch FROM pg_state_merit_source "
                              "WHERE authority_code=? AND academic_year=? AND list_name=?", key).fetchone())
        return jsonify({'ok': True, 'mode': mode, 'rows': len(batch), 'source': s})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("state_merit_ingest: %s", e)
        return jsonify({'ok': False, 'error': 'server_error', 'detail': str(e)[:300]}), 500
    finally:
        conn.close()


def api_neet_result_status():
    """GET /api/pg/neet-result/status (X-News-Key) — what is stored (read-only)."""
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        ensure_neet_result_tables(conn)
        res = [dict(r) for r in conn.execute(
            "SELECT exam_year, COUNT(*) AS n, COUNT(air) AS ranked, MAX(score) AS top FROM pg_neet_result "
            "GROUP BY exam_year ORDER BY exam_year").fetchall()]
        lists = [{k: (str(v) if v is not None and not isinstance(v, (int, str)) else v) for k, v in dict(r).items()}
                 for r in conn.execute("SELECT * FROM pg_state_merit_source ORDER BY authority_code, list_name").fetchall()]
        conn.commit()
        return jsonify({'ok': True, 'results': res, 'merit_lists': lists})
    finally:
        conn.close()
