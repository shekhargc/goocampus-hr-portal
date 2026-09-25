"""Cutoff Explorer + Choice-List builder API for goocampus.in.
X-PG-Key for the explorer (read-only); + doctor Bearer token for choice lists.
(founder 2026-09-21)
"""
import re
import json
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
    # DNB rows carry the signal in the COURSE name ("(NBEMS) …") as well as (sometimes) the
    # degree code, and degree_group was mislabeled 'other' for 2025 — so match NBEMS in the
    # course too, or degree_group=dnb, so the DNB filter isn't dead. The '%DNB%' stays the
    # bound param; NBEMS is a fixed literal (escaped by the ?->%s shim). (2026-09-25)
    # '%DNB%' stays a BOUND param (safe); NBEMS uses POSITION (no literal % — the db shim
    # doesn't escape %, which errored the cut-off explorer).
    if dg == 'dnb':
        return ("(UPPER(COALESCE(c.degree,'')) LIKE ? OR POSITION('NBEMS' IN UPPER(COALESCE(c.course,''))) > 0 "
                "OR LOWER(COALESCE(c.degree_group,'')) = 'dnb')", '%DNB%')
    if dg == 'mdms':
        return ("(UPPER(COALESCE(c.degree,'')) NOT LIKE ? AND POSITION('NBEMS' IN UPPER(COALESCE(c.course,''))) = 0)", '%DNB%')
    return None, None


def _chance(rank, cr):
    """5-level banding. Reachable when the candidate's rank <= the seat's closing rank."""
    if not cr or not rank:
        return 'unknown'
    if rank <= cr * 0.5:
        return 'strong'
    if rank <= cr * 0.77:
        return 'high'
    if rank <= cr:
        return 'good'
    if rank <= cr * 1.18:
        return 'borderline'
    return 'verylow'


_DEG_PREFIX = re.compile(
    r'^\s*(MD|MS|M\.?Ch|DM|DNB|PG[- ]?Diploma(?:\s+in)?|Diploma(?:\s+in)?)\s*[-–:]?\s*', re.I)


def _spec_core(s):
    """'MD - Dermatology' -> 'Dermatology' for prefix-tolerant course matching."""
    return _DEG_PREFIX.sub('', s or '').strip()


# ── Cutoff Explorer (browse cut-offs by filter, NOT by rank) ─────────────────
def api_pg_cutoff_explorer():
    """GET /api/pg/cutoff-explorer?authority=&quota=&category=&state=&degree_group=&course=&q=&page="""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    authority = (request.args.get('authority') or '').strip()
    quota = (request.args.get('quota') or '').strip()
    category = (request.args.get('category') or '').strip()
    state = (request.args.get('state') or '').strip()
    college_type = (request.args.get('college_type') or '').strip()
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
        if college_type:
            where.append("c.institute_type ILIKE ?"); params.append('%' + college_type + '%')
        if course:
            where.append("c.course ILIKE ?"); params.append('%' + course + '%')
        if q:
            where.append("c.institute ILIKE ?"); params.append('%' + q + '%')
        wsql = " WHERE " + " AND ".join(where)
        total = conn.execute("SELECT COUNT(*) AS n FROM pg_cutoffs c" + wsql, params).fetchone()['n']
        offset = (page - 1) * _PER_PAGE
        rows = conn.execute(
            "SELECT c.institute, c.course, c.authority, c.quota, c.category, c.degree, c.state, "
            "c.institute_type, "
            "c.r1, c.r2, c.r3, c.r4, c.stray, c.closing_rank, MAX(a.master_id) AS pg_college_id "
            "FROM pg_cutoffs c "
            f"LEFT JOIN pg_college_alias a ON a.alias_key = {_NORMSQL}"
            + wsql +
            " GROUP BY c.institute, c.course, c.authority, c.quota, c.category, c.degree, c.state, "
            "c.institute_type, "
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
    out = {'ok': True, 'authorities': [], 'quotas': [], 'categories': [], 'states': [],
           'college_types': []}
    try:
        def distinct(col):
            return [r[col] for r in conn.execute(
                f"SELECT DISTINCT {col} FROM pg_cutoffs WHERE COALESCE({col},'')<>'' "
                f"AND COALESCE(is_reference,0)=0 ORDER BY {col}").fetchall()]
        out['authorities'] = distinct('authority')
        out['quotas'] = distinct('quota')
        out['categories'] = distinct('category')
        out['states'] = distinct('state')
        out['college_types'] = distinct('institute_type')
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
    """True if the doctor's effective plan includes this feature. Reads the editable
    Plan Features matrix (pg_plan_features); if the matrix has NO entry for this
    feature (e.g. the one-time seed didn't run), falls back to a sensible default by
    plan tier so a paid plan still unlocks the right things."""
    try:
        plan, _sub = entitlements.effective_plan(conn, user_id)
        if not plan:
            return False
        fm = entitlements.plan_feature_map(conn, plan['id'])
        v = fm.get(feature_code)
        if v is not None:                       # explicit matrix value wins (on OR off)
            return (v.get('value_type') or 'off') != 'off'
        # no explicit mapping → default by plan tier
        code = (plan.get('code') or '').lower()
        paid = any(t in code for t in ('starter', 'standard', 'premium'))
        premium = 'premium' in code
        if feature_code == 'dash_all_states':
            return premium
        if feature_code == 'dash_choice_list':
            return paid
        if feature_code == 'dash_cutoff_explorer':
            return True
        return False
    except Exception:
        return False


def _plan_label(conn, user_id):
    try:
        plan, _sub = entitlements.effective_plan(conn, user_id)
        return (plan or {}).get('name') or 'Free'
    except Exception:
        return 'Free'


def _choice_gate(conn, uid, scope, state=''):
    """Return an error message if this doctor can't create this set, else None.
    FREE tier: ONE home-state list only — self-build (predictor + manual), no auto-generate,
    no All-India/MCC, and the GooCampus team can't edit it.
    PAID (dash_choice_list): MCC + any LOCKED state (home / plan-allowed other), auto-built."""
    paid = _plan_has(conn, uid, 'dash_choice_list')
    counts = {r['scope']: r['n'] for r in conn.execute(
        "SELECT scope, COUNT(*) AS n FROM pg_choice_sets WHERE user_id = ? GROUP BY scope",
        [uid]).fetchall()}
    states = _doctor_states(conn, uid)
    home = next((s['state'] for s in states if s['role'] == 'home'), None)
    locked = {s['state'].strip().lower() for s in states}
    if scope == 'mcc':
        if not paid:
            return 'The All-India / MCC choice list is a paid feature. On the Free plan you can build a choice list for your home state.'
        if counts.get('mcc', 0) >= 1:
            return 'You already have an MCC (All-India) choice set.'
        return None
    if scope == 'state':
        if not state or state.strip().lower() not in locked:
            return 'Set this state as your home/other state before building its choice list.'
        if not paid:
            if not home or state.strip().lower() != home.strip().lower():
                return 'On the Free plan you can build a choice list for your home state only.'
            if counts.get('state', 0) >= 1:
                return 'You already have your home-state choice list. Upgrade to add more states or the All-India list.'
        return None
    return None


def _entitlement_ctx(conn, uid):
    """The doctor's current choice-list entitlement, cached for out-of-plan checks."""
    _home_ok, max_other = _state_limits(conn, uid)
    home = next((s['state'] for s in _doctor_states(conn, uid) if s['role'] == 'home'), None)
    return {'paid': _plan_has(conn, uid, 'dash_choice_list'),
            'max_other': max_other, 'home_l': (home or '').strip().lower()}


def _set_out_of_plan(conn, uid, s, ctx=None):
    """Is this set outside what the doctor's CURRENT plan covers? (downgrade lock — the set
    is kept but becomes view-only; never deleted). MCC needs paid; a non-home state needs an
    allowed 'other' slot; home-state + in-limit sets stay in-plan."""
    ctx = ctx or _entitlement_ctx(conn, uid)
    scope = (s.get('scope') or '').strip().lower()
    st = (s.get('state') or '').strip().lower()
    if scope == 'mcc':
        return not ctx['paid']
    if scope == 'state':
        if st and st == ctx['home_l']:
            return False
        if ctx['max_other'] is None:       # premium: any state
            return False
        if ctx['max_other'] == 0:          # free / starter: home only
            return True
        # standard etc.: the earliest N non-home state sets stay in-plan, the rest lock
        others = [r['id'] for r in conn.execute(
            "SELECT id FROM pg_choice_sets WHERE user_id = ? AND LOWER(scope) = 'state' "
            "AND LOWER(COALESCE(state,'')) <> ? ORDER BY id", [uid, ctx['home_l']]).fetchall()]
        try:
            rank = others.index(s['id'])
        except ValueError:
            rank = len(others)
        return rank >= ctx['max_other']
    return False


def api_pg_choice_entitlement():
    """GET /api/pg/choice-entitlement → what the doctor's plan unlocks for choice lists."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        paid = _plan_has(conn, user['id'], 'dash_choice_list')
        home_ok, max_other = _state_limits(conn, user['id'])
        states = _doctor_states(conn, user['id'])
        home = next((s['state'] for s in states if s['role'] == 'home'), None)
        return jsonify({'ok': True, 'plan': _plan_label(conn, user['id']),
                        'tier': ('paid' if paid else 'free'),
                        'can_build': True,               # everyone can build at least a home-state list
                        'manual_build': True,            # everyone can add colleges manually (predictor/cut-off)
                        'auto_generate': paid,           # FREE self-builds (predictor + manual); no auto-build
                        'auto_build': paid,              # alias for the website: false=manual-only (Free), true=auto (Starter+)
                        'team_editable': paid,           # FREE list is theirs — team is view-only
                        'mcc': paid,
                        'home_only': (not paid),
                        'state': ('any' if max_other is None else 'home'),
                        'home_state': home,
                        'locked_states': [s['state'] for s in states],
                        'allowed_other_states': ('any' if max_other is None else max_other),
                        'cutoff_explorer': _plan_has(conn, user['id'], 'dash_cutoff_explorer'),
                        'message': ('' if paid else 'Free plan: build a home-state choice list yourself (add from the predictor or manually). Upgrade for auto-build, more states and GooCampus team support.')})
    finally:
        conn.close()


_ROUND_CAP = 200   # max colleges auto-seeded per round sheet


def _generate_round(conn, set_id, rnd, authority, dg, specialties, quota_cats, rank):
    """Fill one round sheet from the cut-offs, honouring specialties[] + quota_categories[].
    Reach is filtered IN SQL (HAVING) so the cap keeps reachable colleges, not the most
    competitive unreachable ones. Ordered by specialty preference, then closing rank."""
    col = {1: 'r1', 2: 'r2', 3: 'r3'}[rnd]
    where, params = [f"c.{col} IS NOT NULL", "COALESCE(c.is_reference,0)=0"], []
    dgc, dgp = _deg_clause(dg)
    if dgc:
        where.append(dgc); params.append(dgp)
    if authority:
        where.append("c.authority ILIKE ?"); params.append('%' + authority + '%')
    # specialties[] → OR of (exact course OR contains the core keyword)
    if specialties:
        ors = []
        for sp in specialties:
            ors.append("(LOWER(TRIM(c.course)) = LOWER(TRIM(?)) OR c.course ILIKE ?)")
            params.extend([sp, '%' + _spec_core(sp) + '%'])
        where.append("(" + " OR ".join(ors) + ")")
    # quota_categories[] → OR of (quota match AND category IN (...))
    if quota_cats:
        qors = []
        for pair in quota_cats:
            qv = (pair.get('quota') or '').strip()
            cats = [c for c in (pair.get('categories') or []) if (c or '').strip()]
            if not qv or not cats:
                continue
            ph = ','.join(['LOWER(TRIM(?))'] * len(cats))
            qors.append(f"(LOWER(TRIM(c.quota)) = LOWER(TRIM(?)) AND LOWER(TRIM(c.category)) IN ({ph}))")
            params.append(qv); params.extend(cats)
        if qors:
            where.append("(" + " OR ".join(qors) + ")")
    # reach floor IN SQL: keep seats the candidate can plausibly enter (down to a try-luck stretch)
    having = ""
    if rank:
        having = f" HAVING MIN(c.{col}) >= ?"
        floor_val = int(rank * 0.7)
    rows = conn.execute(
        f"SELECT c.institute, c.course, c.quota, c.category, MIN(c.{col}) AS cr, "
        "MAX(a.master_id) AS master_id, MAX(c.fee) AS fee "
        "FROM pg_cutoffs c "
        f"LEFT JOIN pg_college_alias a ON a.alias_key = {_NORMSQL} "
        "WHERE " + " AND ".join(where) +
        " GROUP BY c.institute, c.course, c.quota, c.category" + having,
        params + ([floor_val] if rank else [])).fetchall()
    # specialty preference index for ordering
    cores = [(_spec_core(sp).lower(), i) for i, sp in enumerate(specialties or [])]

    def _spec_idx(course):
        cl = (course or '').lower()
        for core, i in cores:
            if core and core in cl:
                return i
        return len(cores)
    ordered = sorted([dict(r) for r in rows],
                     key=lambda r: (_spec_idx(r['course']), r['cr'] if r['cr'] is not None else 10**9))
    items = []
    for pos, r in enumerate(ordered[:_ROUND_CAP], start=1):
        items.append([set_id, rnd, pos, r['master_id'], r['institute'], r['course'],
                      r['quota'], r['category'], r['cr'], _chance(rank, r['cr']),
                      r['fee'], 'INR', 'predicted'])
    if items:
        conn.execute_batch(
            "INSERT INTO pg_choice_items (set_id, round, position, master_id, institute, course, "
            "quota, category, closing_rank, chance, fee, currency, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", items, page_size=500)


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
            # Downgrade lock: mark sets the CURRENT plan no longer covers as view-only.
            ctx = _entitlement_ctx(conn, uid)
            for s in sets:
                s['out_of_plan'] = _set_out_of_plan(conn, uid, s, ctx)
            return jsonify({'ok': True, 'sets': sets})
        body = request.get_json(silent=True) or {}
        scope = (body.get('scope') or 'mcc').strip()
        gate = _choice_gate(conn, uid, scope, (body.get('state') or '').strip())
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
        specialties = [s for s in (body.get('specialties') or []) if (s or '').strip()]
        quota_cats = body.get('quota_categories') or []
        if not quota_cats and quota:                       # legacy fallback → one pair
            quota_cats = [{'quota': quota, 'categories': [category] if category else []}]
        sid = conn.execute(
            "INSERT INTO pg_choice_sets (user_id, label, scope, authority, degree_group, state, "
            "quota, category, rank, specialties, quota_categories) VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
            [uid, (body.get('label') or '').strip(), scope, authority, dg,
             (body.get('state') or '').strip(), quota, category, rank,
             json.dumps(specialties), json.dumps(quota_cats)]).fetchone()['id']
        # PAID tiers auto-build the round sheets — UNLESS the client asked for a manual
        # (empty) set via body auto:false. FREE is always manual (add from predictor /
        # manually), so its rounds stay empty regardless.
        if (body.get('auto') is not False) and _plan_has(conn, uid, 'dash_choice_list'):
            for rnd in (1, 2, 3):
                _generate_round(conn, sid, rnd, authority, dg, specialties, quota_cats, rank)
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
        sset = dict(s)
        for k, default in (('specialties', []), ('quota_categories', [])):
            try:
                sset[k] = json.loads(sset.get(k) or '[]')
            except Exception:
                sset[k] = default
        return jsonify({'ok': True, 'set': sset, 'rounds': rounds})
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
        s = conn.execute("SELECT id, rank, scope, state FROM pg_choice_sets WHERE id = ? AND user_id = ?",
                         [set_id, user['id']]).fetchone()
        if not s:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        if _set_out_of_plan(conn, user['id'], dict(s)):
            return jsonify({'ok': False, 'error': 'not_entitled',
                            'message': 'This choice list is view-only on your current plan. Upgrade to edit it.'}), 403
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
        # Find the owning set (must be the doctor's) and block edits on a view-only set.
        srow = conn.execute(
            "SELECT s.id, s.scope, s.state FROM pg_choice_sets s "
            "JOIN pg_choice_items i ON i.set_id = s.id "
            "WHERE i.id = ? AND s.user_id = ?", [item_id, user['id']]).fetchone()
        if not srow:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        if _set_out_of_plan(conn, user['id'], dict(srow)):
            return jsonify({'ok': False, 'error': 'not_entitled',
                            'message': 'This choice list is view-only on your current plan. Upgrade to edit it.'}), 403
        conn.execute("DELETE FROM pg_choice_items WHERE id = ? AND set_id = ?",
                     [item_id, srow['id']])
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
        s = conn.execute("SELECT id, scope, state FROM pg_choice_sets WHERE id=? AND user_id=?",
                         [set_id, user['id']]).fetchone()
        if not s:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        if _set_out_of_plan(conn, user['id'], dict(s)):
            return jsonify({'ok': False, 'error': 'not_entitled',
                            'message': 'This choice list is view-only on your current plan. Upgrade to edit it.'}), 403
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


# ── Doctor's locked states (home + plan-allowed extras) ──────────────────────
def _state_limits(conn, uid):
    """home_ok = may set a HOME state (everyone, incl. Free — for the home-state list).
    max_other = extra states beyond home: None (unlimited) | 1 | 0, from dash_all_states /
    dash_extra_state (paid tiers only)."""
    home_ok = True
    if _plan_has(conn, uid, 'dash_all_states'):
        max_other = None
    elif _plan_has(conn, uid, 'dash_extra_state'):
        max_other = 1
    else:
        max_other = 0
    return home_ok, max_other


def _doctor_states(conn, uid):
    return [dict(r) for r in conn.execute(
        "SELECT state, role, locked FROM pg_doctor_states WHERE user_id = ? ORDER BY "
        "CASE role WHEN 'home' THEN 0 ELSE 1 END, id", [uid]).fetchall()]


def api_pg_my_states():
    """/api/pg/my-states  (X-PG-Key + doctor Bearer)
       GET → { states:[{state,role,locked}], home, allowed_other, can_add_other }
       POST { state, role:'home'|'other' } → set + lock (home once; 'other' up to plan limit)."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        uid = user['id']
        home_ok, max_other = _state_limits(conn, uid)

        def _payload():
            states = _doctor_states(conn, uid)
            home = next((s['state'] for s in states if s['role'] == 'home'), None)
            others = [s for s in states if s['role'] == 'other']
            can_add_other = home_ok and (max_other is None or len(others) < max_other)
            return {'ok': True, 'states': states, 'home': home,
                    'allowed_other': ('any' if max_other is None else max_other),
                    'can_add_other': can_add_other, 'can_set_home': home_ok and not home}

        if request.method == 'GET':
            return jsonify(_payload())

        body = request.get_json(silent=True) or {}
        state = (body.get('state') or '').strip()
        role = (body.get('role') or 'other').strip()
        if not state:
            return jsonify({'ok': False, 'error': 'state required'}), 400
        if not home_ok:
            return jsonify({'ok': False, 'error': 'not_entitled',
                            'message': 'Upgrade to set your counselling states.'}), 403
        existing = _doctor_states(conn, uid)
        if role == 'home':
            if any(s['role'] == 'home' for s in existing):
                return jsonify({'ok': False, 'error': 'home_locked',
                                'message': 'Home state is already set and locked.'}), 409
        else:
            others = [s for s in existing if s['role'] == 'other']
            if max_other is not None and len(others) >= max_other:
                msg = ('Your plan does not include extra states.' if max_other == 0
                       else 'You have used your extra-state allowance. Upgrade for more.')
                return jsonify({'ok': False, 'error': 'limit', 'message': msg}), 403
        if any(s['state'].strip().lower() == state.lower() for s in existing):
            return jsonify({'ok': True, 'already': True})   # idempotent
        conn.execute("INSERT INTO pg_doctor_states (user_id, state, role, locked) VALUES (?,?,?,1)",
                     [uid, state, 'home' if role == 'home' else 'other'])
        conn.commit()
        return jsonify(_payload())
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_my_states: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
