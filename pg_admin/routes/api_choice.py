"""Cutoff Explorer + Choice-List builder API for goocampus.in.
X-PG-Key for the explorer (read-only); + doctor Bearer token for choice lists.
(founder 2026-09-21)
"""
import re
import logging
from flask import request, jsonify
from db import get_db
from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token
from pg_admin.data import entitlements

_PER_PAGE = 100
_NORMSQL = "btrim(regexp_replace(lower(c.institute), '[^a-z0-9]+', ' ', 'g'))"


def _page():
    try:
        return max(1, int(request.args.get('page', 1)))
    except Exception:
        return 1


def _deg_clause(dg):
    if dg == 'dnb':
        return "UPPER(COALESCE(c.degree,'')) LIKE ?", '%DNB%'
    if dg == 'mdms':
        return "UPPER(COALESCE(c.degree,'')) NOT LIKE ?", '%DNB%'
    return None, None


def _chance(rank, cr):
    if not cr or not rank:
        return 'unknown'
    if rank <= cr * 0.75:
        return 'high'
    if rank <= cr:
        return 'good'
    return 'reach'


# ── Cutoff Explorer (browse cut-offs by filter, NOT by rank) ─────────────────
def api_pg_cutoff_explorer():
    """GET /api/pg/cutoff-explorer?authority=&quota=&category=&state=&degree_group=&course=&q=&page="""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    authority = (request.args.get('authority') or '').strip()
    quota = (request.args.get('quota') or '').strip()
    category = (request.args.get('category') or '').strip()
    state = (request.args.get('state') or '').strip()
    course = (request.args.get('course') or '').strip()
    q = (request.args.get('q') or '').strip()
    dg = (request.args.get('degree_group') or '').strip()
    page = _page()
    conn = get_db()
    try:
        where, params = ["COALESCE(c.is_reference,0)=0"], []
        dgc, dgp = _deg_clause(dg)
        if dgc:
            where.append(dgc); params.append(dgp)
        if authority:
            where.append("c.authority ILIKE ?"); params.append('%' + authority + '%')
        if quota:
            where.append("LOWER(TRIM(c.quota)) = LOWER(TRIM(?))"); params.append(quota)
        if category:
            where.append("LOWER(TRIM(c.category)) = LOWER(TRIM(?))"); params.append(category)
        if state:
            where.append("c.state ILIKE ?"); params.append('%' + state + '%')
        if course:
            where.append("c.course ILIKE ?"); params.append('%' + course + '%')
        if q:
            where.append("c.institute ILIKE ?"); params.append('%' + q + '%')
        wsql = " WHERE " + " AND ".join(where)
        total = conn.execute("SELECT COUNT(*) AS n FROM pg_cutoffs c" + wsql, params).fetchone()['n']
        offset = (page - 1) * _PER_PAGE
        rows = conn.execute(
            "SELECT c.institute, c.course, c.authority, c.quota, c.category, c.degree, c.state, "
            "c.r1, c.r2, c.r3, c.r4, c.stray, c.closing_rank, MAX(a.master_id) AS pg_college_id "
            "FROM pg_cutoffs c "
            f"LEFT JOIN pg_college_alias a ON a.alias_key = {_NORMSQL}"
            + wsql +
            " GROUP BY c.institute, c.course, c.authority, c.quota, c.category, c.degree, c.state, "
            "c.r1, c.r2, c.r3, c.r4, c.stray, c.closing_rank "
            "ORDER BY c.closing_rank ASC NULLS LAST, c.institute ASC LIMIT ? OFFSET ?",
            params + [_PER_PAGE, offset]).fetchall()
        out = [dict(r) for r in rows]
    except Exception as e:
        logging.error("api_pg_cutoff_explorer: %s", e)
        conn.close()
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass
    pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
    return jsonify({'ok': True, 'rows': out, 'count': len(out), 'total': total,
                    'page': page, 'pages': pages, 'per_page': _PER_PAGE})


def api_pg_cutoff_facets():
    """GET /api/pg/cutoff-explorer/facets → distinct authorities/quotas/categories/states."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    out = {'ok': True, 'authorities': [], 'quotas': [], 'categories': [], 'states': []}
    try:
        def distinct(col):
            return [r[col] for r in conn.execute(
                f"SELECT DISTINCT {col} FROM pg_cutoffs WHERE COALESCE({col},'')<>'' "
                f"AND COALESCE(is_reference,0)=0 ORDER BY {col}").fetchall()]
        out['authorities'] = distinct('authority')
        out['quotas'] = distinct('quota')
        out['categories'] = distinct('category')
        out['states'] = distinct('state')
    except Exception as e:
        logging.error("api_pg_cutoff_facets: %s", e)
    finally:
        conn.close()
    return jsonify(out)


# ── Choice-List builder (doctor Bearer required) ─────────────────────────────
def _user(conn):
    tok = _bearer_token()
    if not tok:
        return None
    try:
        return _pg_user_by_token(conn, tok)
    except Exception:
        return None


def _plan_has(conn, user_id, feature_code):
    """True if the doctor's effective plan includes this feature (read from the
    editable Plan Features matrix, i.e. pg_plan_features value_type != 'off')."""
    try:
        plan, _sub = entitlements.effective_plan(conn, user_id)
        if not plan:
            return False
        fm = entitlements.plan_feature_map(conn, plan['id'])
        v = fm.get(feature_code)
        return bool(v and (v.get('value_type') or 'off') != 'off')
    except Exception:
        return False


def _plan_label(conn, user_id):
    try:
        plan, _sub = entitlements.effective_plan(conn, user_id)
        return (plan or {}).get('name') or 'Free'
    except Exception:
        return 'Free'


def _choice_gate(conn, uid, scope):
    """Return an error message if this doctor can't create a set of `scope`, else None.
    Reads the editable Plan Features matrix (dash_choice_list / dash_all_states)."""
    if not _plan_has(conn, uid, 'dash_choice_list'):
        return 'Upgrade to build your choice list.'
    counts = {r['scope']: r['n'] for r in conn.execute(
        "SELECT scope, COUNT(*) AS n FROM pg_choice_sets WHERE user_id = ? GROUP BY scope",
        [uid]).fetchall()}
    if scope == 'mcc' and counts.get('mcc', 0) >= 1:
        return 'You already have an MCC (All-India) choice set.'
    if scope == 'state' and not _plan_has(conn, uid, 'dash_all_states') and counts.get('state', 0) >= 1:
        return 'Your plan includes one (home) state counselling. Upgrade for more states.'
    return None


def api_pg_choice_entitlement():
    """GET /api/pg/choice-entitlement → what the doctor's plan unlocks for choice lists."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        can = _plan_has(conn, user['id'], 'dash_choice_list')
        allstates = _plan_has(conn, user['id'], 'dash_all_states')
        return jsonify({'ok': True, 'plan': _plan_label(conn, user['id']), 'can_build': can,
                        'mcc': can, 'state': ('any' if allstates else ('home' if can else False)),
                        'cutoff_explorer': _plan_has(conn, user['id'], 'dash_cutoff_explorer'),
                        'message': ('' if can else 'Upgrade to build your choice list.')})
    finally:
        conn.close()


def _generate_round(conn, set_id, rnd, authority, dg, quota, category, rank):
    """Fill one round sheet from the cut-offs (that round's closing rank)."""
    col = {1: 'r1', 2: 'r2', 3: 'r3'}[rnd]
    where, params = [f"c.{col} IS NOT NULL", "COALESCE(c.is_reference,0)=0"], []
    dgc, dgp = _deg_clause(dg)
    if dgc:
        where.append(dgc); params.append(dgp)
    if authority:
        where.append("c.authority ILIKE ?"); params.append('%' + authority + '%')
    if quota:
        where.append("LOWER(TRIM(c.quota)) = LOWER(TRIM(?))"); params.append(quota)
    if category:
        where.append("LOWER(TRIM(c.category)) = LOWER(TRIM(?))"); params.append(category)
    rows = conn.execute(
        f"SELECT c.institute, c.course, c.quota, c.category, MIN(c.{col}) AS cr, "
        "MAX(a.master_id) AS master_id "
        "FROM pg_cutoffs c "
        f"LEFT JOIN pg_college_alias a ON a.alias_key = {_NORMSQL} "
        "WHERE " + " AND ".join(where) +
        " GROUP BY c.institute, c.course, c.quota, c.category "
        f"ORDER BY MIN(c.{col}) ASC LIMIT 400", params).fetchall()
    items, pos = [], 0
    for r in rows:
        cr = r['cr']
        if rank and cr and rank > cr * 1.15:     # too far out of reach → leave for manual add
            continue
        pos += 1
        items.append([set_id, rnd, pos, r['master_id'], r['institute'], r['course'],
                      r['quota'], r['category'], cr, _chance(rank, cr), 'predicted'])
    if items:
        conn.execute_batch(
            "INSERT INTO pg_choice_items (set_id, round, position, master_id, institute, course, "
            "quota, category, closing_rank, chance, source) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            items, page_size=500)


def api_pg_choice_sets():
    """GET → the doctor's choice sets;  POST {label,scope,authority,degree_group,state,quota,category,rank}
    → create + auto-generate the 3 round sheets."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        uid = user['id']
        if request.method == 'GET':
            sets = [dict(r) for r in conn.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM pg_choice_items i WHERE i.set_id=s.id) AS n_items "
                "FROM pg_choice_sets s WHERE s.user_id = ? ORDER BY s.id DESC", [uid]).fetchall()]
            return jsonify({'ok': True, 'sets': sets})
        body = request.get_json(silent=True) or {}
        scope = (body.get('scope') or 'mcc').strip()
        gate = _choice_gate(conn, uid, scope)
        if gate:
            return jsonify({'ok': False, 'error': 'not_entitled', 'message': gate}), 403
        try:
            rank = int(body.get('rank'))
        except (TypeError, ValueError):
            rank = None
        authority = (body.get('authority') or '').strip()
        dg = (body.get('degree_group') or 'mdms').strip()
        quota = (body.get('quota') or '').strip()
        category = (body.get('category') or '').strip()
        sid = conn.execute(
            "INSERT INTO pg_choice_sets (user_id, label, scope, authority, degree_group, state, "
            "quota, category, rank) VALUES (?,?,?,?,?,?,?,?,?) RETURNING id",
            [uid, (body.get('label') or '').strip(), scope,
             authority, dg, (body.get('state') or '').strip(), quota, category, rank]).fetchone()['id']
        for rnd in (1, 2, 3):
            _generate_round(conn, sid, rnd, authority, dg, quota, category, rank)
        conn.commit()
        return jsonify({'ok': True, 'set_id': sid})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_choice_sets: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pg_choice_set(set_id):
    """GET → set + its 3 round sheets;  DELETE → remove the whole set."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        s = conn.execute("SELECT * FROM pg_choice_sets WHERE id = ? AND user_id = ?",
                         [set_id, user['id']]).fetchone()
        if not s:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        if request.method == 'DELETE':
            conn.execute("DELETE FROM pg_choice_items WHERE set_id = ?", [set_id])
            conn.execute("DELETE FROM pg_choice_sets WHERE id = ?", [set_id])
            conn.commit()
            return jsonify({'ok': True, 'deleted': True})
        items = [dict(r) for r in conn.execute(
            "SELECT * FROM pg_choice_items WHERE set_id = ? ORDER BY round, position, id",
            [set_id]).fetchall()]
        rounds = {1: [], 2: [], 3: []}
        for it in items:
            rounds.setdefault(it['round'], []).append(it)
        return jsonify({'ok': True, 'set': dict(s), 'rounds': rounds})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_choice_set: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pg_choice_items(set_id):
    """POST {round, institute, course, quota, category, master_id, closing_rank} → manual add."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        s = conn.execute("SELECT rank FROM pg_choice_sets WHERE id = ? AND user_id = ?",
                         [set_id, user['id']]).fetchone()
        if not s:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        body = request.get_json(silent=True) or {}
        try:
            rnd = int(body.get('round'))
            assert rnd in (1, 2, 3)
        except Exception:
            return jsonify({'ok': False, 'error': 'round 1|2|3 required'}), 400
        cr = body.get('closing_rank')
        try: cr = int(cr) if cr not in (None, '') else None
        except (TypeError, ValueError): cr = None
        nextpos = (conn.execute("SELECT COALESCE(MAX(position),0)+1 AS p FROM pg_choice_items "
                                "WHERE set_id=? AND round=?", [set_id, rnd]).fetchone()['p'])
        conn.execute(
            "INSERT INTO pg_choice_items (set_id, round, position, master_id, institute, course, "
            "quota, category, closing_rank, chance, source) VALUES (?,?,?,?,?,?,?,?,?,?, 'manual')",
            [set_id, rnd, nextpos, body.get('master_id'), (body.get('institute') or '').strip(),
             (body.get('course') or '').strip(), (body.get('quota') or '').strip(),
             (body.get('category') or '').strip(), cr, _chance(s['rank'], cr)])
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_choice_items: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pg_choice_item_delete(item_id):
    """DELETE /api/pg/choice-items/<item_id> (must belong to the doctor's set)."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        conn.execute(
            "DELETE FROM pg_choice_items WHERE id = ? AND set_id IN "
            "(SELECT id FROM pg_choice_sets WHERE user_id = ?)", [item_id, user['id']])
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_choice_item_delete: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pg_choice_reorder(set_id):
    """POST {round, ordered_item_ids:[...]} → set positions for a round sheet."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        if not conn.execute("SELECT 1 FROM pg_choice_sets WHERE id=? AND user_id=?",
                            [set_id, user['id']]).fetchone():
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        body = request.get_json(silent=True) or {}
        ids = body.get('ordered_item_ids') or []
        pos = 0
        for iid in ids:
            pos += 1
            conn.execute("UPDATE pg_choice_items SET position = ? WHERE id = ? AND set_id = ?",
                         [pos, iid, set_id])
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_choice_reorder: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
