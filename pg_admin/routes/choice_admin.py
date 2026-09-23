"""Team-side choice-sheet editing (goocampus.org admin, on the client's behalf).

The doctor builds/edits their round-wise choice lists on goocampus.in. From the
admin doctor profile (/admin/pg/users/<id>) the GooCampus team can edit the SAME
sheets — add a college, move it up/down, or remove it — for any doctor. Every team
edit is attributed (pg_choice_items.added_by='team' + added_by_name, and the set is
stamped team_edited_at/by) so the client's dashboard can show the change came from us.

Reuses the cut-off data + chance banding from api_choice so team-added colleges carry
the same closing rank / chance / master link as auto-generated ones. (founder 2026-09-23)
"""
import logging
from flask import request, jsonify, redirect, url_for, flash
from db import get_db
from core.users import get_user
from core.auth import login_required
from pg_admin.routes.api_choice import _chance, _NORMSQL, _deg_clause, _spec_core


def _admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def _admin_name(u):
    return (u.get('name') or u.get('username') or 'GooCampus team').strip()


def _s(v):
    return (str(v).strip() if v is not None else '')


def _self_heal(conn):
    """Cold-start guard: make sure the attribution columns exist before we touch them."""
    try:
        conn.execute("ALTER TABLE pg_choice_items ADD COLUMN IF NOT EXISTS added_by TEXT DEFAULT 'client'")
        conn.execute("ALTER TABLE pg_choice_items ADD COLUMN IF NOT EXISTS added_by_name TEXT DEFAULT ''")
        conn.execute("ALTER TABLE pg_choice_sets ADD COLUMN IF NOT EXISTS team_edited_at TIMESTAMP")
        conn.execute("ALTER TABLE pg_choice_sets ADD COLUMN IF NOT EXISTS team_edited_by TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass


def _stamp_team(conn, set_id, admin_name):
    conn.execute("UPDATE pg_choice_sets SET team_edited_at = CURRENT_TIMESTAMP, team_edited_by = ?, "
                 "updated_at = CURRENT_TIMESTAMP WHERE id = ?", [admin_name, set_id])


def _round_items(conn, set_id, rnd):
    """The current round sheet as plain dicts (for the JS to re-render)."""
    return [dict(r) for r in conn.execute(
        "SELECT id, round, position, master_id, institute, course, quota, category, "
        "closing_rank, chance, fee, currency, source, added_by, added_by_name "
        "FROM pg_choice_items WHERE set_id = ? AND round = ? ORDER BY position, id",
        [set_id, rnd]).fetchall()]


def _set_owner(conn, set_id):
    r = conn.execute("SELECT id, user_id, rank, degree_group, authority FROM pg_choice_sets WHERE id = ?",
                     [set_id]).fetchone()
    return dict(r) if r else None


# ── Search cut-offs for the "add college" picker ─────────────────────────────
@login_required
def choice_cutoff_search(set_id):
    """GET /admin/pg/choice-sets/<set_id>/cutoff-search?round=&q=
    Candidate colleges from the cut-offs for THIS set's degree group, with the chosen
    round's closing rank + master link + chance vs the doctor's rank."""
    if not _admin():
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    conn = get_db()
    try:
        s = _set_owner(conn, set_id)
        if not s:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        try:
            rnd = int(request.args.get('round') or 1)
            assert rnd in (1, 2, 3)
        except Exception:
            rnd = 1
        col = {1: 'r1', 2: 'r2', 3: 'r3'}[rnd]
        q = _s(request.args.get('q'))
        where = [f"c.{col} IS NOT NULL", "COALESCE(c.is_reference,0)=0"]
        params = []
        dgc, dgp = _deg_clause(s.get('degree_group') or 'mdms')
        if dgc:
            where.append(dgc); params.append(dgp)
        if s.get('authority'):
            where.append("c.authority ILIKE ?"); params.append('%' + s['authority'] + '%')
        if q:
            where.append("(c.institute ILIKE ? OR c.course ILIKE ?)")
            params.extend(['%' + q + '%', '%' + q + '%'])
        rows = conn.execute(
            f"SELECT c.institute, c.course, c.quota, c.category, MIN(c.{col}) AS cr, "
            "MAX(a.master_id) AS master_id, MAX(c.fee) AS fee "
            "FROM pg_cutoffs c "
            f"LEFT JOIN pg_college_alias a ON a.alias_key = {_NORMSQL} "
            "WHERE " + " AND ".join(where) +
            " GROUP BY c.institute, c.course, c.quota, c.category "
            f"ORDER BY MIN(c.{col}) ASC NULLS LAST, c.institute ASC LIMIT 40",
            params).fetchall()
        rank = s.get('rank')
        out = []
        for r in rows:
            r = dict(r)
            r['chance'] = _chance(rank, r['cr'])
            out.append(r)
        return jsonify({'ok': True, 'rows': out})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("choice_cutoff_search: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── Add a college to a round (team) ──────────────────────────────────────────
@login_required
def choice_add(set_id):
    """POST /admin/pg/choice-sets/<set_id>/add
    {round, institute, course, quota, category, master_id, closing_rank}"""
    u = _admin()
    if not u:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    conn = get_db()
    try:
        _self_heal(conn)
        s = _set_owner(conn, set_id)
        if not s:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        body = request.get_json(silent=True) or {}
        try:
            rnd = int(body.get('round')); assert rnd in (1, 2, 3)
        except Exception:
            return jsonify({'ok': False, 'error': 'round 1|2|3 required'}), 400
        institute = _s(body.get('institute'))
        if not institute:
            return jsonify({'ok': False, 'error': 'institute required'}), 400
        cr = body.get('closing_rank')
        try: cr = int(cr) if cr not in (None, '') else None
        except (TypeError, ValueError): cr = None
        master_id = body.get('master_id') or None
        nextpos = conn.execute("SELECT COALESCE(MAX(position),0)+1 AS p FROM pg_choice_items "
                               "WHERE set_id=? AND round=?", [set_id, rnd]).fetchone()['p']
        conn.execute(
            "INSERT INTO pg_choice_items (set_id, round, position, master_id, institute, course, "
            "quota, category, closing_rank, chance, source, added_by, added_by_name) "
            "VALUES (?,?,?,?,?,?,?,?,?,?, 'manual', 'team', ?)",
            [set_id, rnd, nextpos, master_id, institute, _s(body.get('course')),
             _s(body.get('quota')), _s(body.get('category')), cr, _chance(s.get('rank'), cr),
             _admin_name(u)])
        _stamp_team(conn, set_id, _admin_name(u))
        conn.commit()
        return jsonify({'ok': True, 'round': rnd, 'items': _round_items(conn, set_id, rnd)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("choice_add: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── Move a college up/down within its round (team) ───────────────────────────
@login_required
def choice_move(item_id):
    """POST /admin/pg/choice-items/<item_id>/move  {dir:'up'|'down'} — swap with neighbour."""
    u = _admin()
    if not u:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    conn = get_db()
    try:
        _self_heal(conn)
        it = conn.execute("SELECT id, set_id, round, position FROM pg_choice_items WHERE id = ?",
                          [item_id]).fetchone()
        if not it:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        it = dict(it)
        direction = _s((request.get_json(silent=True) or {}).get('dir')) or 'up'
        # normalise positions 1..n first (guards against gaps/dupes), then swap.
        ordered = conn.execute("SELECT id FROM pg_choice_items WHERE set_id=? AND round=? "
                               "ORDER BY position, id", [it['set_id'], it['round']]).fetchall()
        ids = [r['id'] for r in ordered]
        idx = ids.index(item_id)
        swap = idx - 1 if direction == 'up' else idx + 1
        if 0 <= swap < len(ids):
            ids[idx], ids[swap] = ids[swap], ids[idx]
        for pos, iid in enumerate(ids, start=1):
            conn.execute("UPDATE pg_choice_items SET position=? WHERE id=?", [pos, iid])
        _stamp_team(conn, it['set_id'], _admin_name(u))
        conn.commit()
        return jsonify({'ok': True, 'round': it['round'], 'items': _round_items(conn, it['set_id'], it['round'])})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("choice_move: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── Reorder a whole round (team, drag order) ─────────────────────────────────
@login_required
def choice_reorder(set_id):
    """POST /admin/pg/choice-sets/<set_id>/reorder  {round, ordered_item_ids:[...]}"""
    u = _admin()
    if not u:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    conn = get_db()
    try:
        _self_heal(conn)
        if not _set_owner(conn, set_id):
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        body = request.get_json(silent=True) or {}
        try:
            rnd = int(body.get('round')); assert rnd in (1, 2, 3)
        except Exception:
            return jsonify({'ok': False, 'error': 'round 1|2|3 required'}), 400
        for pos, iid in enumerate(body.get('ordered_item_ids') or [], start=1):
            conn.execute("UPDATE pg_choice_items SET position=? WHERE id=? AND set_id=? AND round=?",
                         [pos, iid, set_id, rnd])
        _stamp_team(conn, set_id, _admin_name(u))
        conn.commit()
        return jsonify({'ok': True, 'round': rnd, 'items': _round_items(conn, set_id, rnd)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("choice_reorder: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── Remove a college (team) ──────────────────────────────────────────────────
@login_required
def choice_delete(item_id):
    """POST /admin/pg/choice-items/<item_id>/delete — remove one college from a round."""
    u = _admin()
    if not u:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    conn = get_db()
    try:
        _self_heal(conn)
        it = conn.execute("SELECT id, set_id, round FROM pg_choice_items WHERE id = ?",
                          [item_id]).fetchone()
        if not it:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        it = dict(it)
        conn.execute("DELETE FROM pg_choice_items WHERE id = ?", [item_id])
        # re-pack positions so the round stays 1..n
        ordered = conn.execute("SELECT id FROM pg_choice_items WHERE set_id=? AND round=? "
                               "ORDER BY position, id", [it['set_id'], it['round']]).fetchall()
        for pos, r in enumerate(ordered, start=1):
            conn.execute("UPDATE pg_choice_items SET position=? WHERE id=?", [pos, r['id']])
        _stamp_team(conn, it['set_id'], _admin_name(u))
        conn.commit()
        return jsonify({'ok': True, 'round': it['round'], 'items': _round_items(conn, it['set_id'], it['round'])})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("choice_delete: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
