"""GooCampus Recommended choice lists for MCC + the "New in 2026" seat picker.

Founder 2026-10-15. MCC only, two combos:
  aiq_open          — All India Quota, OPEN
  deemed_paid_open  — Deemed University paid (Self-Financed Merit / Management-Paid), OPEN
For each combo the team builds TWO lists for a doctor (both owner='team', so the doctor
sees them under "GooCampus Team Choice List", can edit, and every change is logged):
  rec_matrix:<combo>  — every 2026 seat-matrix seat in the doctor's specialities, ordered
                        by college tier (Top → Good → Average, the team-curated
                        pg_college_tiers), then speciality preference, then last year's
                        closing rank. Includes colleges/courses NEW in 2026.
  rec_cutoff:<combo>  — the classic last-year cut-off list (3 rounds, by the doctor's rank).

New-2026 picker: seat-matrix seats with no 2025 cut-off (has_cutoff=0) offered to the team
and paid doctors to add deliberately; added items carry chance='new', source='seatmatrix'.
"""
import json
import logging
from flask import request, jsonify

from db import get_db
from pg_admin.routes.api_choice import _chance, _spec_core, _generate_round, _plan_has
from pg_admin.data import choice_log as _clog

COMBOS = {
    'aiq_open': {'label': 'All India Quota · Open', 'section': 'aiq', 'seat_quota': 'All India',
                 'cut_quota': 'All India Quota', 'category': 'OPEN'},
    'deemed_paid_open': {'label': 'Deemed Paid · Open', 'section': 'deemed',
                         'seat_quota': 'Self-Financed Merit Seat',
                         'cut_quota': 'Management/Paid Seats Quota', 'category': 'OPEN'},
}
# Every list that carries team-curated tiers: the 2 recommended combos above + the extra
# MCC College Rankings lists (CIQ, NRI). (founder 2026-10-15)
TIER_LISTS = {
    'aiq_open': {'label': 'All India Quota (Government)', 'section': 'aiq', 'seat_quotas': ['All India']},
    'deemed_paid_open': {'label': 'Deemed University — Paid seats', 'section': 'deemed',
                         'seat_quotas': ['Self-Financed Merit Seat']},
    'ciq_open': {'label': 'Central Universities (DU · IP · BHU · AMU)', 'section': 'ciq',
                 'seat_quotas': ['Delhi University Quota', 'IP University Quota', 'Banaras Hindu University',
                                 'Aligarh Muslim University']},
    'nri_deemed': {'label': 'Deemed University — NRI seats', 'section': 'deemed',
                   'seat_quotas': ['Non-Resident Indian']},
}
TIERS = ('Top', 'Good', 'Average')
# Colleges with no 2025 history are never tiered — they're tagged 'New' and listed after the
# tiered ones (founder 2026-10-15: "we're not sure what it could be, just say new college").
NEW_TIER = 'New'
_TIER_IDX = {'Top': 0, 'Good': 1, 'Average': 2, NEW_TIER: 3}
_READY = False


def ensure_rec_tables(conn, force=False):
    global _READY
    if _READY and not force:
        return
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_college_tiers (
            id SERIAL PRIMARY KEY,
            list_key TEXT NOT NULL,            -- aiq_open | deemed_paid_open
            college_code TEXT NOT NULL,        -- MCC 6-digit institute code
            college_name TEXT DEFAULT '',
            tier TEXT DEFAULT 'Average',       -- Top | Good | Average
            basis_rank INTEGER,                -- 2025 median clinical closing rank (draft basis)
            updated_by TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_college_tiers ON pg_college_tiers (list_key, college_code)")
        conn.execute("ALTER TABLE pg_choice_sets ADD COLUMN IF NOT EXISTS list_kind TEXT DEFAULT ''")
        conn.commit()
        _READY = True
    except Exception as e:
        logging.warning("ensure_rec_tables: %s", e)
        try: conn.rollback()
        except Exception: pass


def _s(v):
    return (str(v).strip() if v is not None else '')


def _short_name(name):
    """'Govt Medical College, Satna, Near Kendriya Vidyalaya…' → 'Govt Medical College, Satna'."""
    segs = [x.strip() for x in (name or '').split(',') if x.strip() and x.strip().upper() not in ('NA', 'N A', 'N.A.', '-')]
    if not segs:
        return ''
    out = segs[0]
    if len(segs) > 1 and len(segs[1]) <= 40 and not any(ch.isdigit() for ch in segs[1]):
        out += ', ' + segs[1]
    return out


def _bodies(conn, section=None):
    q = ("SELECT counselling_body, section FROM pg_seat_matrix_source WHERE COALESCE(superseded,0)=0 "
         "AND COALESCE(authority_code,'')='mcc' AND COALESCE(section,'') NOT IN ('', 'nmc_initial')")
    p = []
    if section:
        q += " AND section=?"; p.append(section)
    return [r['counselling_body'] for r in conn.execute(q, p).fetchall()]


def _tiers(conn, combo):
    return {r['college_code']: r['tier'] for r in conn.execute(
        "SELECT college_code, tier FROM pg_college_tiers WHERE list_key=?", [combo]).fetchall()}


# ── Tiers (team-curated Top / Good / Average) ────────────────────────────────
def tiers_payload(conn, combo):
    c = TIER_LISTS[combo]
    bodies = _bodies(conn, c['section'])
    if not bodies:
        return []
    ph = ','.join(['?'] * len(bodies))
    qph = ','.join(['?'] * len(c['seat_quotas']))
    newc = _new_codes(conn, combo)
    rows = conn.execute(
        f"SELECT college_code, MAX(college_name) AS name, MAX(state) AS state, MAX(institute_type) AS itype, "
        f"SUM(seats) AS seats, MAX(CASE WHEN has_cutoff=1 THEN 1 ELSE 0 END) AS has_history "
        f"FROM pg_seat_matrix WHERE counselling_body IN ({ph}) AND quota IN ({qph}) "
        f"GROUP BY college_code", bodies + list(c['seat_quotas'])).fetchall()
    tiers = {r['college_code']: dict(r) for r in conn.execute(
        "SELECT college_code, tier, basis_rank, updated_by, updated_at FROM pg_college_tiers "
        "WHERE list_key=?", [combo]).fetchall()}
    # NRI seats behave oddly (small pool, scattered ranks) — a deemed college's NRI tier FOLLOWS its
    # Deemed Paid tier (same college). Only colleges absent from Deemed Paid keep their own NRI tier.
    followed = {}
    if combo == 'nri_deemed':
        followed = {r['college_code']: dict(r) for r in conn.execute(
            "SELECT college_code, tier, basis_rank, updated_by, updated_at FROM pg_college_tiers "
            "WHERE list_key='deemed_paid_open'").fetchall()}
    out = []
    for r in rows:
        t = followed.get(r['college_code']) or tiers.get(r['college_code']) or {}
        new = r['college_code'] in newc
        out.append({'college_code': r['college_code'], 'college': _short_name(r['name']), 'state': r['state'],
                    'institute_type': r['itype'] or '',
                    'seats': int(r['seats'] or 0), 'new_college': new,
                    'editable': (not new) and r['college_code'] not in followed,
                    'follows': 'deemed_paid_open' if r['college_code'] in followed else '',
                    'tier': NEW_TIER if new else (t.get('tier') or 'Average'), 'basis_rank': t.get('basis_rank'),
                    'updated_by': t.get('updated_by') or '',
                    'updated_at': str(t['updated_at'])[:16] if t.get('updated_at') else ''})
    out.sort(key=lambda x: (_TIER_IDX.get(x['tier'], 2), x['basis_rank'] or 10**9, x['college']))
    return out


def _new_codes(conn, combo):
    """MCC codes of colleges with no 2025 cut-off history at all for this combo's section."""
    c = TIER_LISTS[combo]
    bodies = _bodies(conn, c['section'])
    if not bodies:
        return set()
    ph = ','.join(['?'] * len(bodies))
    return {r['college_code'] for r in conn.execute(
        f"SELECT college_code FROM pg_seat_matrix WHERE counselling_body IN ({ph}) "
        f"GROUP BY college_code HAVING MAX(CASE WHEN COALESCE(cutoff_institute,'')<>'' THEN 1 ELSE 0 END)=0",
        bodies).fetchall()}


def set_tier(conn, combo, code, tier, who, name='', basis=None):
    if combo not in TIER_LISTS or tier not in TIERS or not code:
        return False
    if code in _new_codes(conn, combo):      # new colleges stay 'New' — never tiered
        return False
    if combo == 'nri_deemed' and conn.execute(
            "SELECT 1 FROM pg_college_tiers WHERE list_key='deemed_paid_open' AND college_code=?", [code]).fetchone():
        return False                         # NRI follows the college's Deemed Paid tier — edit it there
    row = conn.execute("SELECT id FROM pg_college_tiers WHERE list_key=? AND college_code=?",
                       [combo, code]).fetchone()
    if row:
        conn.execute("UPDATE pg_college_tiers SET tier=?, updated_by=?, updated_at=CURRENT_TIMESTAMP "
                     + (", college_name=?" if name else "") + (", basis_rank=?" if basis is not None else "")
                     + " WHERE id=?",
                     [tier, who] + ([name] if name else []) + ([basis] if basis is not None else []) + [row['id']])
    else:
        conn.execute("INSERT INTO pg_college_tiers (list_key, college_code, college_name, tier, basis_rank, "
                     "updated_by) VALUES (?,?,?,?,?,?)", [combo, code, name, tier, basis, who])
    return True


# ── Build the two recommended lists for a doctor ─────────────────────────────
def _upsert_set(conn, user_id, kind, label, rank, specialties, qcs):
    ex = conn.execute("SELECT id FROM pg_choice_sets WHERE user_id=? AND COALESCE(list_kind,'')=? "
                      "AND COALESCE(owner,'client')='team' ORDER BY id LIMIT 1", [user_id, kind]).fetchone()
    if ex:
        sid = ex['id']
        conn.execute("UPDATE pg_choice_sets SET label=?, rank=?, specialties=?, quota_categories=?, "
                     "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     [label, rank, json.dumps(specialties), json.dumps(qcs), sid])
        conn.execute("DELETE FROM pg_choice_items WHERE set_id=?", [sid])
        return sid, True
    sid = conn.execute(
        "INSERT INTO pg_choice_sets (user_id, label, scope, authority, degree_group, state, quota, category, rank, "
        "specialties, quota_categories, owner, list_kind) VALUES (?,?,'mcc','MCC','mdms','',?,?,?,?,?,'team',?) "
        "RETURNING id", [user_id, label, qcs[0]['quota'], 'OPEN', rank, json.dumps(specialties),
                         json.dumps(qcs), kind]).fetchone()['id']
    return sid, False


def _r1(r):
    """Last year's Round-1 closing rank for the seat (Round 2 / final as fallbacks)."""
    for k in ('cr_r1', 'cr_r2', 'cr_closing'):
        if r.get(k):
            return r[k]
    return None


def _matrix_items(conn, combo, specialties, rank, order='rank'):
    """Every 2026 seat in the doctor's specialities for this combo — nothing filtered by rank.
    order='rank'       → one combined list by last year's Round-1 closing rank (seat that went first, first)
    order='speciality' → grouped by the doctor's speciality order, each group by Round-1 rank
    Seats new in 2026 (no previous cut-off) go last (per group when grouped), tagged 'new'."""
    c = COMBOS[combo]
    bodies = _bodies(conn, c['section'])
    if not bodies:
        return []
    ph = ','.join(['?'] * len(bodies))
    where = [f"s.counselling_body IN ({ph})", "s.quota=?", "s.category=?"]
    params = bodies + [c['seat_quota'], c['category']]
    if specialties:
        ors = []
        for sp in specialties:
            ors.append("(LOWER(TRIM(s.cutoff_course))=LOWER(TRIM(?)) OR s.cutoff_course ILIKE ?)")
            params.extend([sp, '%' + _spec_core(sp) + '%'])
        where.append("(" + " OR ".join(ors) + ")")
    rows = [dict(r) for r in conn.execute(
        "SELECT s.college_code, s.college_name, s.cutoff_institute, s.cutoff_course, s.course_name, "
        "s.cutoff_quota, s.category, s.cr_r1, s.cr_r2, s.cr_closing, s.cutoff_fee, s.has_cutoff, s.seats "
        "FROM pg_seat_matrix s WHERE " + " AND ".join(where), params).fetchall()]
    cores = [(_spec_core(sp).lower(), i) for i, sp in enumerate(specialties or [])]

    def spec_idx(course):
        cl = (course or '').lower()
        for core, i in cores:
            if core and core in cl:
                return i
        return len(cores)
    for r in rows:
        r['r1'] = _r1(r) if r['has_cutoff'] else None
        r['is_new'] = not r['r1']
        r['spec'] = spec_idx(r['cutoff_course'] or r['course_name'])
    big = 10 ** 9
    if order == 'speciality':
        rows.sort(key=lambda r: (r['spec'], r['is_new'], r['r1'] or big, r['college_name']))
    else:
        rows.sort(key=lambda r: (r['is_new'], r['r1'] or big, r['spec'], r['college_name']))
    return rows


def build_recommended(conn, user_id, combo, specialties, rank, actor, order='rank'):
    """(Re)build the GooCampus Recommended Round-1 list rec_matrix:<combo> for this doctor.
    (The older rank-filtered 'rec_cutoff' list is no longer built — founder 2026-10-15.)"""
    from pg_admin.routes.choice_admin import _self_heal, _stamp_team
    _self_heal(conn)
    ensure_rec_tables(conn)
    c = COMBOS[combo]
    order = 'speciality' if order == 'speciality' else 'rank'
    qcs = [{'quota': c['cut_quota'], 'categories': [c['category']]}]
    kind = 'rec_matrix:' + combo
    how = 'grouped by speciality' if order == 'speciality' else "in last year's Round 1 cut-off order"
    sid, rebuilt = _upsert_set(conn, user_id, kind,
                               f"GooCampus Recommended — {c['label']} — Round 1 ({how})",
                               rank, specialties, qcs)
    items = []
    for pos, r in enumerate(_matrix_items(conn, combo, specialties, rank, order), start=1):
        items.append([sid, 1, pos, None, r['cutoff_institute'] or _short_name(r['college_name']),
                      r['cutoff_course'] or r['course_name'], c['cut_quota'], r['category'],
                      r['r1'], 'new' if r['is_new'] else _chance(rank, r['r1']),
                      float(r['cutoff_fee']) if r['cutoff_fee'] is not None else None, 'INR',
                      'seatmatrix', 'team', actor])
    if items:
        conn.execute_batch(
            "INSERT INTO pg_choice_items (set_id, round, position, master_id, institute, course, quota, "
            "category, closing_rank, chance, fee, currency, source, added_by, added_by_name) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", items, page_size=500)
    _stamp_team(conn, sid, actor)
    _clog.log(conn, sid, 'rebuild' if rebuilt else 'build', 'team', actor, user_id=user_id,
              detail={'kind': kind, 'order': order, 'colleges': len(items), 'rank': rank,
                      'specialties': specialties})
    n_new = sum(1 for it in items if it[9] == 'new')
    return {'matrix': {'set_id': sid, 'items': len(items), 'new': n_new, 'order': order}}


# ── "New in 2026" seats for a choice list ─────────────────────────────────────
def new_seats(conn, set_id, args):
    s = conn.execute("SELECT * FROM pg_choice_sets WHERE id=?", [set_id]).fetchone()
    if not s:
        return None
    s = dict(s)
    if (s.get('scope') or '') != 'mcc':
        return {'rows': [], 'note': 'New-2026 seats are available for MCC lists only.'}
    bodies = _bodies(conn)
    if not bodies:
        return {'rows': []}
    ph = ','.join(['?'] * len(bodies))
    where = [f"counselling_body IN ({ph})", "has_cutoff=0"]
    params = list(bodies)
    quota, cat, q = _s(args.get('quota')), _s(args.get('category')), _s(args.get('q'))
    if quota:
        where.append("cutoff_quota=?"); params.append(quota)
    if cat:
        where.append("category=?"); params.append(cat)
    if not quota and not cat:
        try:
            qcs = json.loads(s.get('quota_categories') or '[]')
        except Exception:
            qcs = []
        ors = []
        for pair in qcs:
            qv = _s(pair.get('quota')); cats = [x for x in (pair.get('categories') or []) if _s(x)]
            if qv and cats:
                ors.append("(cutoff_quota=? AND category IN (" + ','.join(['?'] * len(cats)) + "))")
                params.append(qv); params.extend(cats)
        if ors:
            where.append("(" + " OR ".join(ors) + ")")
    # Hide seats already in the list (this round if ?round= is given, else any round).
    if _s(args.get('include_added')) not in ('1', 'true'):
        try:
            rnd = int(args.get('round')) if args.get('round') else None
        except (TypeError, ValueError):
            rnd = None
        have = conn.execute("SELECT LOWER(TRIM(institute)) AS i, LOWER(TRIM(course)) AS c FROM pg_choice_items "
                            "WHERE set_id = ?" + (" AND round = ?" if rnd else ""),
                            [set_id] + ([rnd] if rnd else [])).fetchall()
        added = {(r['i'], r['c']) for r in have}
    else:
        added = set()
    if q:
        from pg_admin.routes.api import smart_name_clause
        fn, pn = smart_name_clause("college_name", q)
        fc, pc = smart_name_clause("course_name", q)
        where.append(f"({fn} OR {fc})"); params.extend(pn + pc)
    try:
        limit = max(1, min(int(args.get('limit') or 100), 500))
    except (TypeError, ValueError):
        limit = 100
    try:
        offset = max(0, int(args.get('offset') or 0))
    except (TypeError, ValueError):
        offset = 0
    rows = conn.execute(
        "SELECT college_code, college_name, state, course_name, cutoff_course, cutoff_institute, cutoff_quota, "
        "category, seats, new_reason, section FROM pg_seat_matrix WHERE " + " AND ".join(where) +
        f" ORDER BY state, college_name, course_name LIMIT {limit} OFFSET {offset}", params).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        inst = r['cutoff_institute'] or _short_name(r['college_name'])
        if (inst.strip().lower(), (r['cutoff_course'] or r['course_name']).strip().lower()) in added:
            continue
        out.append({'institute': r['cutoff_institute'] or _short_name(r['college_name']),
                    'course': r['cutoff_course'] or r['course_name'], 'quota': r['cutoff_quota'],
                    'category': r['category'], 'state': r['state'], 'seats': r['seats'],
                    'college_code': r['college_code'], 'new_reason': r['new_reason'],
                    'section': r['section'], 'is_new': True})
    return {'rows': out, 'limit': limit, 'offset': offset, 'more': len(out) == limit}


# ── Routes ───────────────────────────────────────────────────────────────────
def _combo_or_400(combo, lists=None):
    if combo not in (lists or COMBOS):
        return jsonify({'ok': False, 'error': 'unknown list', 'allowed': list(lists or COMBOS)}), 400
    return None


def _build_from_request(user_id, actor):
    body = request.get_json(silent=True) or {}
    combo = _s(body.get('combo'))
    err = _combo_or_400(combo)
    if err:
        return err
    sp = body.get('specialties') or []
    if isinstance(sp, str):
        sp = [x.strip() for x in sp.split(',') if x.strip()]
    try:
        rank = int(body.get('rank'))
    except (TypeError, ValueError):
        rank = None
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM pg_users WHERE id=?", [user_id]).fetchone():
            return jsonify({'ok': False, 'error': 'doctor_not_found'}), 404
        if not _plan_has(conn, user_id, 'dash_choice_list'):
            return jsonify({'ok': False, 'error': 'not_entitled',
                            'message': 'Recommended MCC lists are for Internal and paid doctors.'}), 403
        res = build_recommended(conn, user_id, combo, [x for x in sp if _s(x)], rank, actor,
                                order=_s(body.get('order')) or 'rank')
        conn.commit()
        return jsonify({'ok': True, 'combo': combo, **res})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("build_recommended: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def _tiers_get(combo):
    err = _combo_or_400(combo, TIER_LISTS)
    if err:
        return err
    conn = get_db()
    try:
        ensure_rec_tables(conn)
        rows = tiers_payload(conn, combo)
        return jsonify({'ok': True, 'combo': combo, 'label': TIER_LISTS[combo]['label'], 'tiers': list(TIERS),
                        'lists': [{'key': k, 'label': v['label']} for k, v in TIER_LISTS.items()],
                        'colleges': rows})
    finally:
        conn.close()


def _tiers_post(actor):
    body = request.get_json(silent=True) or {}
    combo = _s(body.get('combo'))
    err = _combo_or_400(combo, TIER_LISTS)
    if err:
        return err
    changes = body.get('changes') or ([{'code': body.get('code'), 'tier': body.get('tier')}]
                                      if body.get('code') else [])
    conn = get_db()
    try:
        ensure_rec_tables(conn)
        n = 0
        for ch in changes:
            if set_tier(conn, combo, _s(ch.get('code')), _s(ch.get('tier')), actor):
                n += 1
        conn.commit()
        return jsonify({'ok': True, 'updated': n})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("tiers_post: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def _new_seats_get(set_id):
    conn = get_db()
    try:
        res = new_seats(conn, set_id, request.args)
        if res is None:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        return jsonify({'ok': True, **res})
    except Exception as e:
        logging.error("new_seats: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# Desk (goocampus.in team login)
def desk_tiers():
    from pg_admin.routes.desk_api import _guard, _actor_name
    m, _, err = _guard()
    if err:
        return err
    if request.method == 'POST':
        return _tiers_post(_actor_name(m))
    return _tiers_get(_s(request.args.get('combo')) or 'aiq_open')


def desk_recommended(doctor_id):
    from pg_admin.routes.desk_api import _guard, _actor_name
    m, _, err = _guard(doctor_id=doctor_id)
    return err or _build_from_request(doctor_id, _actor_name(m))


def desk_new_seats(set_id):
    from pg_admin.routes.desk_api import _guard
    m, _, err = _guard(set_id=set_id)
    return err or _new_seats_get(set_id)


# Admin (goocampus.org)
def _admin_user():
    from core.users import get_user
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def admin_recommended(user_id):
    u = _admin_user()
    if not u:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    return _build_from_request(user_id, (u.get('name') or u.get('username') or 'GooCampus team').strip())


def admin_new_seats(set_id):
    if not _admin_user():
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    return _new_seats_get(set_id)


def admin_tiers():
    u = _admin_user()
    if not u:
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    if request.method == 'POST':
        return _tiers_post((u.get('name') or 'admin').strip())
    return _tiers_get(_s(request.args.get('combo')) or 'aiq_open')


# Doctor's own picker (paid / internal)
def doctor_new_seats(set_id):
    from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        tok = _bearer_token()
        u = _pg_user_by_token(conn, tok) if tok else None
        if not u:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        if not conn.execute("SELECT 1 FROM pg_choice_sets WHERE id=? AND user_id=?", [set_id, u['id']]).fetchone():
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        if not _plan_has(conn, u['id'], 'dash_choice_list'):
            return jsonify({'ok': False, 'error': 'not_entitled',
                            'message': 'New 2026 seats are part of the paid plans.'}), 403
    finally:
        conn.close()
    return _new_seats_get(set_id)


# Bulk tier import (Mac, X-News-Key) — seeds the draft and applies the founder's reviewed Excel
def tiers_ingest():
    from pg_admin.routes.api_news_ingest import _ok
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    body = request.get_json(silent=True) or {}
    combo = _s(body.get('combo'))
    err = _combo_or_400(combo, TIER_LISTS)
    if err:
        return err
    only_new = bool(body.get('only_missing'))
    # replace_drafts: overwrite rows still holding a machine draft, never a team member's edit
    replace_drafts = bool(body.get('replace_drafts'))
    conn = get_db()
    try:
        ensure_rec_tables(conn)
        have = set(_tiers(conn, combo)) if only_new else set()
        if replace_drafts:
            have = {r['college_code'] for r in conn.execute(
                "SELECT college_code FROM pg_college_tiers WHERE list_key=? AND COALESCE(updated_by,'') NOT ILIKE ? "
                "AND COALESCE(updated_by,'') <> 'import'", [combo, 'Draft%']).fetchall()}
        n = 0
        for r in body.get('rows') or []:
            code = _s(r.get('code'))
            if not code or code in have:
                continue
            if set_tier(conn, combo, code, _s(r.get('tier')), _s(body.get('who')) or 'import',
                        name=_s(r.get('college')), basis=r.get('basis_rank')):
                n += 1
        conn.commit()
        return jsonify({'ok': True, 'combo': combo, 'updated': n})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("tiers_ingest: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
