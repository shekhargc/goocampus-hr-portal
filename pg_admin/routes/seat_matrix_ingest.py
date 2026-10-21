"""Machine import of an official seat matrix (X-News-Key) — used for MCC's final 2026
matrix, which MCC publishes as 3 PDFs (All India Quota / Central Internal Quota / Deemed).

The PDFs are parsed on the team's Mac (tools/seat_matrix/), each seat is bridged to
last year's MCC cut-off (college + course + quota + category) or flagged "new in
2026", and the rows + the official PDF are posted here. A post REPLACES that one
(body, year); `supersede` marks older matrices (e.g. the provisional 'All India MCC')
as superseded — hidden from the dashboard, never deleted. (founder 2026-10-15)
"""
import base64
import logging
from flask import request, jsonify
from db import get_db

_ROW_COLS = ('sl_no', 'college_code', 'state', 'college_name', 'category', 'course_name', 'seats',
             'section', 'institute_type', 'quota', 'category_code', 'course_code', 'cutoff_institute',
             'cutoff_course', 'cutoff_quota', 'cutoff_category', 'has_cutoff', 'new_reason',
             'cr_r1', 'cr_r2', 'cr_r3', 'cr_closing', 'cutoff_fee')
_INT_COLS = {'sl_no', 'seats', 'has_cutoff', 'cr_r1', 'cr_r2', 'cr_r3', 'cr_closing'}


# What the replaced version looked like — so the site can say "what changed" from DATA, never typed
# text (founder 2026-10-21, after MCC's FINAL matrix replaced the earlier one).
_PREV_COLS = (('prev_row_count', 'INTEGER'), ('prev_college_count', 'INTEGER'), ('prev_total_seats', 'INTEGER'),
              ('prev_replaced_at', 'TIMESTAMP'), ('prev_source_file_name', "TEXT DEFAULT ''"),
              ('colleges_added', 'INTEGER'), ('colleges_removed', 'INTEGER'))


def ensure_prev_cols(conn):
    for c, t in _PREV_COLS:
        conn.execute(f"ALTER TABLE pg_seat_matrix_source ADD COLUMN IF NOT EXISTS {c} {t}")


def change_payload(r):
    """{previous, change} for a pg_seat_matrix_source row dict (None when there is no earlier version)."""
    r = r or {}
    if r.get('prev_total_seats') is None:
        return {'previous': None, 'change': None}
    prev = {'rows': r.get('prev_row_count'), 'colleges': r.get('prev_college_count'),
            'seats': r.get('prev_total_seats'), 'source_file_name': r.get('prev_source_file_name') or '',
            'replaced_at': str(r['prev_replaced_at'])[:16] if r.get('prev_replaced_at') else ''}
    cur = {'rows': r.get('row_count') or 0, 'colleges': r.get('college_count') or 0, 'seats': r.get('total_seats') or 0}
    return {'previous': prev,
            'change': {'rows': cur['rows'] - (prev['rows'] or 0), 'colleges': cur['colleges'] - (prev['colleges'] or 0),
                       'seats': cur['seats'] - (prev['seats'] or 0),
                       'colleges_added': r.get('colleges_added'), 'colleges_removed': r.get('colleges_removed')}}


def _v(r, c):
    v = r.get(c)
    if c in _INT_COLS:
        try:
            return int(v) if v not in (None, '') else None
        except (TypeError, ValueError):
            return None
    if c == 'cutoff_fee':
        try:
            return float(v) if v not in (None, '') else None
        except (TypeError, ValueError):
            return None
    return '' if v is None else str(v).strip()


def api_seat_matrix_ingest():
    """POST /api/pg/seat-matrix/ingest  (X-News-Key)
    {body, year, section, authority_code, sort_order, source_file_name, pdf_name, pdf_b64,
     rows:[{...}], supersede:[body,...], notes}"""
    from pg_admin.routes.api_news_ingest import _ok
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    d = request.get_json(silent=True) or {}
    body = (d.get('body') or '').strip()
    year = (d.get('year') or '2026-27').strip()
    rows = d.get('rows') or []
    if not body or not rows:
        return jsonify({'ok': False, 'error': 'body and rows required'}), 400
    pdf = None
    if d.get('pdf_b64'):
        try:
            pdf = base64.b64decode(d['pdf_b64'])
        except Exception:
            return jsonify({'ok': False, 'error': 'bad pdf_b64'}), 400
    from pg_admin.data.seat_matrix_tables import ensure_pg_seat_matrix
    ensure_pg_seat_matrix()
    auth = (d.get('authority_code') or 'mcc').strip()
    conn = get_db()
    try:
        ensure_prev_cols(conn)
        # the version being replaced (for "what changed")
        old = conn.execute("SELECT COUNT(*) AS n, COUNT(DISTINCT college_code) AS c, COALESCE(SUM(seats),0) AS s "
                           "FROM pg_seat_matrix WHERE counselling_body=? AND academic_year=?", [body, year]).fetchone()
        old_codes = {r['college_code'] for r in conn.execute(
            "SELECT DISTINCT college_code FROM pg_seat_matrix WHERE counselling_body=? AND academic_year=?",
            [body, year]).fetchall()}
        old_src = conn.execute("SELECT source_file_name FROM pg_seat_matrix_source WHERE counselling_body=? "
                               "AND academic_year=?", [body, year]).fetchone()
        conn.execute("DELETE FROM pg_seat_matrix WHERE counselling_body=? AND academic_year=?", [body, year])
        cols = ('counselling_body', 'academic_year', 'authority_code') + _ROW_COLS
        ph = ','.join(['?'] * len(cols))
        sql = f"INSERT INTO pg_seat_matrix ({','.join(cols)}) VALUES ({ph})"
        for r in rows:
            conn.execute(sql, [body, year, auth] + [_v(r, c) for c in _ROW_COLS])
        colleges = len({(r.get('college_code') or '', r.get('college_name') or '') for r in rows})
        seats = sum(int(r.get('seats') or 0) for r in rows)
        src = conn.execute("SELECT id FROM pg_seat_matrix_source WHERE counselling_body=? AND academic_year=?",
                           [body, year]).fetchone()
        vals = [d.get('source_file_name') or '', d.get('pdf_name') or '', len(rows), colleges, seats,
                d.get('notes') or '', 'Mac import', auth, d.get('section') or '', int(d.get('sort_order') or 0)]
        if src:
            conn.execute("UPDATE pg_seat_matrix_source SET source_file_name=?, pdf_name=?, row_count=?, "
                         "college_count=?, total_seats=?, notes=?, uploaded_by=?, authority_code=?, section=?, "
                         "sort_order=?, superseded=0, uploaded_at=CURRENT_TIMESTAMP WHERE id=?", vals + [src['id']])
            sid = src['id']
        else:
            sid = conn.execute("INSERT INTO pg_seat_matrix_source (source_file_name, pdf_name, row_count, "
                               "college_count, total_seats, notes, uploaded_by, authority_code, section, sort_order, "
                               "counselling_body, academic_year) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                               vals + [body, year]).fetchone()['id']
        if pdf:
            conn.execute("UPDATE pg_seat_matrix_source SET pdf_data=?, pdf_content_type='application/pdf' "
                         "WHERE id=?", [pdf, sid])
        new_codes = {(r.get('college_code') or '') for r in rows}
        if old and int(old['n'] or 0) and (int(old['n']) != len(rows) or int(old['s'] or 0) != seats
                                           or old_codes != new_codes):
            # a real revision → remember what it replaced (a re-import of the same file keeps the
            # earlier "what changed")
            conn.execute("UPDATE pg_seat_matrix_source SET prev_row_count=?, prev_college_count=?, prev_total_seats=?, "
                         "prev_replaced_at=CURRENT_TIMESTAMP, prev_source_file_name=?, colleges_added=?, "
                         "colleges_removed=? WHERE id=?",
                         [int(old['n']), int(old['c'] or 0), int(old['s'] or 0),
                          (old_src['source_file_name'] if old_src else '') or '',
                          len(new_codes - old_codes), len(old_codes - new_codes), sid])
        sup = []
        for b in d.get('supersede') or []:
            b = (b or '').strip()
            if b and b != body:
                conn.execute("UPDATE pg_seat_matrix_source SET superseded=1 WHERE counselling_body=? "
                             "AND academic_year=?", [b, year])
                sup.append(b)
        conn.commit()
        return jsonify({'ok': True, 'body': body, 'rows': len(rows), 'colleges': colleges,
                        'seats': seats, 'superseded': sup, 'pdf': bool(pdf)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_seat_matrix_ingest: %s", e)
        return jsonify({'ok': False, 'error': 'server_error', 'detail': str(e)[:300]}), 500
    finally:
        conn.close()


def api_seat_matrix_source_update():
    """POST /api/pg/seat-matrix/source (X-News-Key) {body, year, superseded?, section?, sort_order?, notes?}
    — change how an already-loaded matrix is listed (e.g. bring back the initial NMC matrix as
    its own card next to the official MCC sections). Rows are never touched. (founder 2026-10-15)"""
    from pg_admin.routes.api_news_ingest import _ok
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    d = request.get_json(silent=True) or {}
    body = (d.get('body') or '').strip()
    year = (d.get('year') or '2026-27').strip()
    sets, vals = [], []
    if 'superseded' in d:
        sets.append("superseded=?"); vals.append(1 if d.get('superseded') else 0)
    if 'section' in d:
        sets.append("section=?"); vals.append((d.get('section') or '').strip())
    if 'sort_order' in d:
        sets.append("sort_order=?"); vals.append(int(d.get('sort_order') or 0))
    if 'notes' in d:
        sets.append("notes=?"); vals.append((d.get('notes') or '').strip())
    prev = d.get('previous') if isinstance(d.get('previous'), dict) else None
    if prev:      # record what an already-replaced version looked like (one-time backfill)
        for k, col in (('rows', 'prev_row_count'), ('colleges', 'prev_college_count'), ('seats', 'prev_total_seats'),
                       ('colleges_added', 'colleges_added'), ('colleges_removed', 'colleges_removed')):
            if k in prev:
                sets.append(f"{col}=?"); vals.append(int(prev[k]) if prev[k] is not None else None)
        if 'source_file_name' in prev:
            sets.append("prev_source_file_name=?"); vals.append(str(prev['source_file_name'] or '')[:300])
        if prev.get('replaced_at'):
            sets.append("prev_replaced_at=?"); vals.append(str(prev['replaced_at'])[:19])
    if not body or not sets:
        return jsonify({'ok': False, 'error': 'body and at least one field required'}), 400
    conn = get_db()
    try:
        ensure_prev_cols(conn)
        conn.execute(f"UPDATE pg_seat_matrix_source SET {', '.join(sets)} WHERE counselling_body=? "
                     "AND academic_year=?", vals + [body, year])
        conn.commit()
        row = conn.execute("SELECT counselling_body, COALESCE(superseded,0) AS superseded, "
                           "COALESCE(section,'') AS section, COALESCE(sort_order,0) AS sort_order "
                           "FROM pg_seat_matrix_source WHERE counselling_body=? AND academic_year=?",
                           [body, year]).fetchone()
        return jsonify({'ok': bool(row), 'source': dict(row) if row else None})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_seat_matrix_source_update: %s", e)
        return jsonify({'ok': False, 'error': 'server_error', 'detail': str(e)[:200]}), 500
    finally:
        conn.close()


def api_seat_matrix_file_to_authority():
    """POST /api/pg/seat-matrix/file-to-authority (X-News-Key)
    {items:[{body, title}], authority_code:'mcc', year?} — copy each loaded matrix's OFFICIAL PDF into that
    authority's Documents → Seat Matrix, HIDDEN and waiting for the founder's Publish (same box as the
    auto-filed notices). Exact-same files are skipped (sha256). (founder 2026-10-15)"""
    from pg_admin.routes.api_news_ingest import _ok
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    from pg_admin.data.auto_docs import find_same_file, sha256
    from pg_admin.authorities import get_authority
    d = request.get_json(silent=True) or {}
    code = (d.get('authority_code') or 'mcc').strip()
    year = (d.get('year') or '2026-27').strip()
    auth = get_authority(code) or {}
    conn = get_db()
    out = []
    try:
        for it in d.get('items') or []:
            body = (it.get('body') or '').strip()
            title = (it.get('title') or body).strip()[:300]
            src = conn.execute("SELECT pdf_name, pdf_data FROM pg_seat_matrix_source WHERE counselling_body=? "
                               "AND academic_year=?", [body, year]).fetchone()
            if not src or not src['pdf_data']:
                out.append({'body': body, 'result': 'no_pdf'}); continue
            data = bytes(src['pdf_data'])
            if find_same_file(conn, code, data):
                out.append({'body': body, 'result': 'duplicate'}); continue
            conn.execute(
                "INSERT INTO pg_authority_docs (authority_code, authority_name, category, title, doc_date, note, "
                "file_name, file_data, file_content_type, is_published, uploaded_by, file_sha256, review_pending, "
                "auto_kind) VALUES (?,?,?,?,?,?,?,?,'application/pdf',FALSE,'Seat matrix import',?,TRUE,'pdf')",
                [code, auth.get('name', ''), 'seat_matrix', title, '', '', (src['pdf_name'] or 'seat-matrix.pdf')[:200],
                 data, sha256(data)])
            out.append({'body': body, 'result': 'filed', 'title': title})
        conn.commit()
        return jsonify({'ok': True, 'results': out})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("seat matrix → authority docs: %s", e)
        return jsonify({'ok': False, 'error': 'server_error', 'detail': str(e)[:200]}), 500
    finally:
        conn.close()
