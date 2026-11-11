"""2026-27 fee store — import + read-only check (X-News-Key, the same key as the news-ingest tools).

POST /api/pg/fees/import {authority, fee_year?, replace?, rows:[{institute, course, quota, category?, fee_total,
     tuition?, other_fee?, other_label?, note?, source?, source_inbox_id?, source_date?, prev_fee?, prev_source?,
     status?}]}
     → replaces that authority's fee rows for the year with the verified rows (only pg_fees — never pg_cutoffs).
     Rows come from the per-authority cross-check sheet the founder approved (founder 2026-11-11: fees must be
     correct and taken from the right documents).
GET  /api/pg/fees/store?authority=&q=&n=  → summary + a few stored rows (read-only check).
"""
import hmac
import logging
import os
from flask import request, jsonify
from db import get_db
from pg_admin.data import fees as F


def _ok():
    want = (os.environ.get('NEWS_INGEST_KEY') or '').strip()
    got = (request.headers.get('X-News-Key') or '').strip()
    return bool(want) and hmac.compare_digest(want, got)


def api_fees_import():
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    b = request.get_json(silent=True) or {}
    authority = (b.get('authority') or '').strip()
    rows = b.get('rows') or []
    if not authority or not isinstance(rows, list) or not rows:
        return jsonify({'ok': False, 'error': 'authority and rows are required'}), 400
    try:
        fee_year = int(b.get('fee_year') or F.FEE_YEAR)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'bad fee_year'}), 400
    conn = get_db()
    try:
        known = conn.execute("SELECT COUNT(*) AS n FROM pg_cutoffs WHERE authority = ?", [authority]).fetchone()['n']
        if not known:
            return jsonify({'ok': False, 'error': f'unknown authority {authority!r} (not in pg_cutoffs)'}), 400
        n = F.load_rows(conn, authority, rows, (b.get('loaded_by') or 'fee import')[:80],
                        replace=b.get('replace', True) is not False, fee_year=fee_year)
        return jsonify({'ok': True, 'authority': authority, 'fee_year': fee_year, 'written': n,
                        'summary': F.summary(conn)})
    except Exception as e:
        logging.error("api_fees_import: %s", e)
        try: conn.rollback()
        except Exception: pass
        return jsonify({'ok': False, 'error': str(e)[:300]}), 500
    finally:
        conn.close()


def api_fees_store():
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    authority = (request.args.get('authority') or '').strip()
    q = (request.args.get('q') or '').strip().lower()
    try:
        n = min(200, max(1, int(request.args.get('n') or 20)))
    except ValueError:
        n = 20
    conn = get_db()
    try:
        out = {'ok': True, 'available': F.available(conn), 'summary': F.summary(conn), 'rows': []}
        if authority and out['available']:
            sql = ("SELECT institute, course, quota, category, fee_total, tuition, other_fee, other_label, note, "
                   "source, source_date, prev_fee, prev_source, status FROM pg_fees WHERE fee_year = ? AND authority = ?")
            params = [F.FEE_YEAR, authority]
            if q:
                sql += " AND (inst_key LIKE ? OR course_key LIKE ?)"
                params += ['%' + q + '%', '%' + q + '%']
            rows = conn.execute(sql + " ORDER BY inst_key, course_key, quota_key LIMIT ?", params + [n]).fetchall()
            out['rows'] = [{k: (float(v) if hasattr(v, 'as_integer_ratio') or type(v).__name__ == 'Decimal' else v)
                            for k, v in dict(r).items()} for r in rows]
        resp = jsonify(out)
        resp.headers['Cache-Control'] = 'no-store'
        return resp
    finally:
        conn.close()
