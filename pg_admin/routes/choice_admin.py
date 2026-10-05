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
from pg_admin.routes.api_choice import (_chance, _NORMSQL, _deg_clause, _spec_core,
                                        _plan_has, _choice_gate, _generate_round,
                                        _state_limits, _doctor_states)


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


# Free-tier clients own their home-state list — the GooCampus team is VIEW-ONLY on it
# (founder 2026-09-24). Only paid (dash_choice_list) clients' lists can be team-edited.
_FREE_LIST_MSG = ('This client is on the Free plan — their home-state choice list is '
                  'self-service and cannot be edited by the team (view only).')


@login_required
def choice_create(user_id):
    """Team creates a NEW choice list for a doctor, per counselling body (MCC or a
    state), from the doctor's profile — mirrors the doctor-side POST /api/pg/choice-sets
    but on the client's behalf, respecting the DOCTOR's plan entitlement + stamping the
    team member. Optionally auto-builds the 3 rounds (paid), else an empty list the team
    fills. (founder 2026-10-01)"""
    import json as _json
    u = _admin()
    if not u:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    body = request.get_json(silent=True) or request.form
    scope = _s(body.get('scope')) or 'mcc'
    state = _s(body.get('state'))
    dg = _s(body.get('degree_group')) or 'mdms'
    authority = _s(body.get('authority'))
    try:
        rank = int(body.get('rank'))
    except (TypeError, ValueError):
        rank = None
    sp = body.get('specialties')
    if isinstance(sp, str):
        specialties = [x.strip() for x in sp.split(',') if x.strip()]
    else:
        specialties = [x for x in (sp or []) if _s(x)]
    quota = _s(body.get('quota'))
    category = _s(body.get('category'))
    qcs = body.get('quota_categories') or []
    if not qcs and quota:
        qcs = [{'quota': quota, 'categories': [category] if category else []}]
    auto = str(body.get('auto', '1')).lower() not in ('0', 'false', 'no', 'off')

    conn = get_db()
    try:
        _self_heal(conn)
        if not conn.execute("SELECT 1 FROM pg_users WHERE id = ?", [user_id]).fetchone():
            return jsonify({'ok': False, 'error': 'doctor_not_found'}), 404
        # ONE list per counselling body. If this body already has a set, REBUILD it in
        # place (update its params + regenerate the rounds) — never create a duplicate.
        # Only check the plan entitlement when starting a NEW body's list.
        existing = conn.execute(
            "SELECT id FROM pg_choice_sets WHERE user_id = ? AND scope = ? "
            "AND LOWER(COALESCE(state,'')) = LOWER(?) ORDER BY id LIMIT 1",
            [user_id, scope, state or '']).fetchone()
        if existing:
            sid = existing['id']
            conn.execute(
                "UPDATE pg_choice_sets SET label=?, authority=?, degree_group=?, quota=?, "
                "category=?, rank=?, specialties=?, quota_categories=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                [_s(body.get('label')), authority, dg, quota, category, rank,
                 _json.dumps(specialties), _json.dumps(qcs), sid])
            conn.execute("DELETE FROM pg_choice_items WHERE set_id = ?", [sid])
        else:
            gate = _choice_gate(conn, user_id, scope, state)
            if gate:
                return jsonify({'ok': False, 'error': 'not_entitled', 'message': gate}), 403
            sid = conn.execute(
                "INSERT INTO pg_choice_sets (user_id, label, scope, authority, degree_group, state, "
                "quota, category, rank, specialties, quota_categories) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "RETURNING id",
                [user_id, _s(body.get('label')), scope, authority, dg, state, quota, category, rank,
                 _json.dumps(specialties), _json.dumps(qcs)]).fetchone()['id']
        if auto and _plan_has(conn, user_id, 'dash_choice_list'):
            for rnd in (1, 2, 3):
                _generate_round(conn, sid, rnd, authority, dg, specialties, qcs, rank)
        _stamp_team(conn, sid, _admin_name(u))
        conn.commit()
        return jsonify({'ok': True, 'set_id': sid, 'rebuilt': bool(existing)})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("choice_create: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


@login_required
def choice_states(user_id):
    """Team manages a doctor's counselling states from their profile (home stays
    fixed; 'other' states capped by the DOCTOR's plan). Mirrors /api/pg/my-states.
    GET → payload; POST {state} → add 'other'; DELETE {state} → remove a non-home.
    Adding a state here reflects on the doctor's own dashboard too (same table).
    (founder 2026-10-02)"""
    u = _admin()
    if not u:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM pg_users WHERE id = ?", [user_id]).fetchone():
            return jsonify({'ok': False, 'error': 'doctor_not_found'}), 404
        home_ok, max_other = _state_limits(conn, user_id)

        def _payload():
            states = _doctor_states(conn, user_id)
            home = next((s['state'] for s in states if s['role'] == 'home'), None)
            others = [s for s in states if s['role'] == 'other']
            return {'ok': True, 'states': states, 'home': home,
                    'allowed_other': ('any' if max_other is None else max_other),
                    'can_add_other': home_ok and (max_other is None or len(others) < max_other)}

        if request.method == 'GET':
            return jsonify(_payload())

        state = _s((request.get_json(silent=True) or {}).get('state')
                   or request.form.get('state') or request.args.get('state'))
        if not state:
            return jsonify({'ok': False, 'error': 'state_required'}), 400

        if request.method == 'DELETE':
            row = conn.execute("SELECT id, role FROM pg_doctor_states WHERE user_id=? "
                               "AND LOWER(state)=LOWER(?) ORDER BY id LIMIT 1",
                               [user_id, state]).fetchone()
            if row and (row['role'] or '') == 'home':
                return jsonify({'ok': False, 'error': 'home_fixed',
                                'message': 'The home / domicile state is fixed and cannot be removed.'}), 403
            if row:
                conn.execute("DELETE FROM pg_doctor_states WHERE id=?", [row['id']])
                conn.commit()
            return jsonify(_payload())

        # POST → add an 'other' state, capped by the doctor's plan.
        existing = _doctor_states(conn, user_id)
        others = [s for s in existing if s['role'] == 'other']
        if max_other is not None and len(others) >= max_other:
            msg = ('This doctor’s plan does not include extra states.' if max_other == 0
                   else 'This doctor has used their extra-state allowance (plan limit).')
            return jsonify({'ok': False, 'error': 'limit', 'message': msg}), 403
        if any(s['state'].strip().lower() == state.lower() for s in existing):
            return jsonify({'ok': True, 'already': True, **_payload()})
        conn.execute("INSERT INTO pg_doctor_states (user_id, state, role, locked) VALUES (?,?,'other',0)",
                     [user_id, state])
        conn.commit()
        return jsonify(_payload())
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("choice_states: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


@login_required
def choice_facets():
    """Distinct quota + category options for a counselling body (MCC or a state),
    from pg_cutoffs, so the team's build form only offers valid combos.
    GET ?scope=mcc|state&state=&degree_group=mdms|dnb (founder 2026-10-02)"""
    if not _admin():
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    scope = _s(request.args.get('scope')) or 'mcc'
    state = _s(request.args.get('state'))
    dg = _s(request.args.get('degree_group')) or 'mdms'
    where = ["COALESCE(c.is_reference,0)=0"]
    params = []
    dgc, dgp = _deg_clause(dg)
    if dgc:
        where.append(dgc); params.append(dgp)
    if scope == 'state' and state:
        where.append("c.state ILIKE ?"); params.append('%' + state + '%')
    else:  # MCC / All-India
        where.append("(c.authority ILIKE ? OR c.authority ILIKE ? OR c.authority ILIKE ?)")
        params.extend(['%MCC%', '%All India%', '%AIQ%'])
    wsql = " WHERE " + " AND ".join(where)
    conn = get_db()
    try:
        quotas = [r['quota'] for r in conn.execute(
            f"SELECT DISTINCT c.quota AS quota FROM pg_cutoffs c{wsql} "
            "AND COALESCE(c.quota,'')<>'' ORDER BY c.quota", params).fetchall()]
        cats = [r['category'] for r in conn.execute(
            f"SELECT DISTINCT c.category AS category FROM pg_cutoffs c{wsql} "
            "AND COALESCE(c.category,'')<>'' ORDER BY c.category", params).fetchall()]
        # categories available per quota (so category can follow the chosen quota)
        by_quota = {}
        for r in conn.execute(
                f"SELECT DISTINCT c.quota AS quota, c.category AS category FROM pg_cutoffs c{wsql} "
                "AND COALESCE(c.quota,'')<>'' AND COALESCE(c.category,'')<>'' "
                "ORDER BY c.quota, c.category", params).fetchall():
            by_quota.setdefault(r['quota'], []).append(r['category'])
        return jsonify({'ok': True, 'quotas': quotas, 'categories': cats,
                        'categories_by_quota': by_quota})
    except Exception as e:
        logging.error("choice_facets: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


@login_required
def choice_delete_set(set_id):
    """Team deletes a whole choice list (and its colleges) for a doctor — e.g. to
    remove a stray/duplicate list. (founder 2026-10-02)"""
    if not _admin():
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM pg_choice_sets WHERE id = ?", [set_id]).fetchone():
            return jsonify({'ok': True, 'deleted': True})   # already gone — idempotent
        conn.execute("DELETE FROM pg_choice_items WHERE set_id = ?", [set_id])
        conn.execute("DELETE FROM pg_choice_sets WHERE id = ?", [set_id])
        conn.commit()
        return jsonify({'ok': True, 'deleted': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("choice_delete_set: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def _team_can_edit(conn, user_id):
    return _plan_has(conn, user_id, 'dash_choice_list')


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
            from pg_admin.routes.api import smart_name_clause
            fi, pi = smart_name_clause("c.institute", q)
            fc, pc = smart_name_clause("c.course", q)
            where.append(f"({fi} OR {fc})"); params.extend(pi + pc)
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
        if not _team_can_edit(conn, s['user_id']):
            return jsonify({'ok': False, 'error': 'free_tier', 'message': _FREE_LIST_MSG}), 403
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
        _o = _set_owner(conn, it['set_id'])
        if _o and not _team_can_edit(conn, _o['user_id']):
            return jsonify({'ok': False, 'error': 'free_tier', 'message': _FREE_LIST_MSG}), 403
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
        _o = _set_owner(conn, set_id)
        if not _o:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        if not _team_can_edit(conn, _o['user_id']):
            return jsonify({'ok': False, 'error': 'free_tier', 'message': _FREE_LIST_MSG}), 403
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
        _o = _set_owner(conn, it['set_id'])
        if _o and not _team_can_edit(conn, _o['user_id']):
            return jsonify({'ok': False, 'error': 'free_tier', 'message': _FREE_LIST_MSG}), 403
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
