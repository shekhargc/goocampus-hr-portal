"""Doctor-facing and Counselling-Desk APIs for a doctor's own seat allotments + rank confirmation
(founder 2026-10-26). Logic lives in pg_admin/allotments.py.

Doctor (X-PG-Key + the doctor's token):
  GET  /api/pg/my/allotments            → rank status + allotments grouped MD/MS | DNB → authority → rounds
  POST /api/pg/my/rank-confirm          {neet_pg_rank, neet_pg_score, home_state_rank} — first time: confirm
                                        (values may be corrected here); afterwards ONE more correction; then
                                        "contact the team"
  POST /api/pg/my/allotment-not-me      {authority, round, year?} — hide a wrongly matched allotment
Counselling Desk (internal + paid doctors):
  GET  /api/pg/desk/doctors/<id>/allotments           → every match incl. 'not me', rank status, rank log
  POST /api/pg/desk/doctors/<id>/allotment-mark       {authority, round, year?, verdict: confirmed|not_me|''}
  (rank / score / home-state rank are edited through the existing /api/pg/desk/doctors/<id>/profile — logged)
"""
import logging
from flask import request, jsonify
from db import get_db
from pg_admin import allotments as AL

YEAR = '2026-27'


def _s(v):
    return str(v).strip() if v is not None else ''


def _doctor(conn):
    from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token
    if not _authorized():
        return None, (jsonify({'ok': False, 'error': 'unauthorized'}), 401)
    tok = _bearer_token()
    u = _pg_user_by_token(conn, tok) if tok else None
    if not u:
        return None, (jsonify({'ok': False, 'error': 'invalid_token'}), 401)
    return dict(u), None


def my_allotments():
    conn = get_db()
    try:
        AL.ensure(conn)
        u, err = _doctor(conn)
        if err:
            return err
        allots = AL.for_users(conn, [u], include_not_me=False).get(u['id'], [])
        st = AL.rank_state(conn, u['id'])
        return jsonify({'ok': True, 'rank': st, 'allotments': AL.grouped(allots), 'count': len(allots),
                        'note': 'Matched by your rank: MCC uses your All-India rank, state counselling your '
                                'home-state merit rank. Always confirm on the official result.'})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("my_allotments: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def my_rank_confirm():
    conn = get_db()
    try:
        AL.ensure(conn)
        u, err = _doctor(conn)
        if err:
            return err
        d = request.get_json(silent=True) or {}
        vals = {k: d.get(k) for k in AL.RANK_FIELDS if k in d}
        st = AL.rank_state(conn, u['id'])
        cur = {k: st.get(k) for k in AL.RANK_FIELDS}
        new = {}
        for k, v in vals.items():
            n = AL.parse_rank_value(k, v)          # ValueError → 400 with a readable message
            if n is not None:
                new[k] = n                         # blank = keep what is there
        differs = any(new[k] != cur.get(k) for k in new)
        who = (u.get('name') or u.get('mobile') or 'doctor').strip()
        if not st['rank_confirmed']:
            if not (new.get('neet_pg_rank') or cur.get('neet_pg_rank')):
                return jsonify({'ok': False, 'error': 'bad_value', 'message': 'Please enter your All-India rank.'}), 400
            AL.set_ranks(conn, u['id'], vals, who, 'goocampus.in (rank confirmation)')
            conn.execute("UPDATE pg_users SET rank_confirmed_at = CURRENT_TIMESTAMP, "
                         "rank_prompt_closed_at = COALESCE(rank_prompt_closed_at, CURRENT_TIMESTAMP) WHERE id = ?",
                         [u['id']])
        elif differs:
            if st['corrections_left'] <= 0:
                return jsonify({'ok': False, 'error': 'correction_used',
                                'message': 'You have already corrected your rank once. Please contact the '
                                           'GooCampus team with your scorecard to change it again.'}), 403
            AL.set_ranks(conn, u['id'], vals, who, 'goocampus.in (one-time correction)')
            conn.execute("UPDATE pg_users SET rank_self_edits = COALESCE(rank_self_edits,0) + 1, "
                         "correction_prompt_closed_at = COALESCE(correction_prompt_closed_at, CURRENT_TIMESTAMP) "
                         "WHERE id = ?", [u['id']])
        conn.commit()
        st = AL.rank_state(conn, u['id'])
        return jsonify({'ok': True, 'rank': st,
                        'allotments': AL.grouped(AL.for_users(conn, [dict(conn.execute(
                            "SELECT id, neet_pg_rank, home_state_rank, state FROM pg_users WHERE id=?",
                            [u['id']]).fetchone())], include_not_me=False).get(u['id'], []))})
    except ValueError as e:
        try: conn.rollback()
        except Exception: pass
        return jsonify({'ok': False, 'error': 'bad_value', 'message': str(e)}), 400
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("my_rank_confirm: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def my_allotment_not_me():
    conn = get_db()
    try:
        AL.ensure(conn)
        u, err = _doctor(conn)
        if err:
            return err
        d = request.get_json(silent=True) or {}
        auth, rnd = _s(d.get('authority')), _s(d.get('round'))
        if not auth or not rnd:
            return jsonify({'ok': False, 'error': 'authority and round required'}), 400
        rank = u.get('neet_pg_rank') if auth == 'mcc' else u.get('home_state_rank')
        AL.mark(conn, u['id'], auth, _s(d.get('year')) or YEAR, rnd, 'not_me',
                (u.get('name') or u.get('mobile') or 'doctor'), 'doctor', rank_used=rank)
        conn.commit()
        return jsonify({'ok': True, 'rank': AL.rank_state(conn, u['id']),
                        'message': 'Hidden. If your rank on your profile is wrong, correct it so we can show '
                                   'your real allotment.'})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("my_allotment_not_me: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def my_rank_prompt():
    """POST /api/pg/my/rank-prompt {prompt: 'confirm'|'correction'} — the doctor closed that pop-up ("Later" /
    ✕): never show it automatically again (founder 2026-10-26: ask once). They can still confirm / correct from
    My Allotments."""
    conn = get_db()
    try:
        AL.ensure(conn)
        u, err = _doctor(conn)
        if err:
            return err
        which = _s((request.get_json(silent=True) or {}).get('prompt')) or 'confirm'
        col = 'correction_prompt_closed_at' if which == 'correction' else 'rank_prompt_closed_at'
        conn.execute(f"UPDATE pg_users SET {col} = COALESCE({col}, CURRENT_TIMESTAMP) WHERE id = ?", [u['id']])
        conn.commit()
        return jsonify({'ok': True, 'rank': AL.rank_state(conn, u['id'])})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("my_rank_prompt: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── Counselling Desk ──────────────────────────────────────────────────────────
def desk_allotments(doctor_id):
    from pg_admin.routes.desk_api import _guard
    m, _, err = _guard(doctor_id=doctor_id)
    if err:
        return err
    conn = get_db()
    try:
        AL.ensure(conn)
        u = conn.execute("SELECT id, neet_pg_rank, home_state_rank, state FROM pg_users WHERE id=?",
                         [doctor_id]).fetchone()
        allots = AL.for_users(conn, [dict(u)], include_not_me=True).get(doctor_id, []) if u else []
        log = [dict(r) for r in conn.execute(
            "SELECT field, old_value, new_value, changed_by, source, changed_at FROM pg_profile_edit_log "
            "WHERE user_id = ? AND field IN ('neet_pg_rank','neet_pg_score','home_state_rank') ORDER BY id DESC "
            "LIMIT 50", [doctor_id]).fetchall()]
        for r in log:
            r['changed_at'] = str(r['changed_at'])[:16] if r.get('changed_at') else ''
        return jsonify({'ok': True, 'rank': AL.rank_state(conn, doctor_id), 'allotments': allots,
                        'grouped': AL.grouped([a for a in allots if a['verdict'] != 'not_me']),
                        'latest': AL.latest(allots), 'rank_log': log})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("desk_allotments: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def desk_allotment_mark(doctor_id):
    from pg_admin.routes.desk_api import _guard, _actor_name
    m, _, err = _guard(doctor_id=doctor_id)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    auth, rnd, verdict = _s(d.get('authority')), _s(d.get('round')), _s(d.get('verdict'))
    if not auth or not rnd or verdict not in ('confirmed', 'not_me', ''):
        return jsonify({'ok': False, 'error': 'authority, round and verdict (confirmed|not_me|"") required'}), 400
    conn = get_db()
    try:
        AL.ensure(conn)
        u = conn.execute("SELECT neet_pg_rank, home_state_rank FROM pg_users WHERE id=?", [doctor_id]).fetchone()
        rank = (u['neet_pg_rank'] if auth == 'mcc' else u['home_state_rank']) if u else None
        AL.mark(conn, doctor_id, auth, _s(d.get('year')) or YEAR, rnd, verdict, _actor_name(m), 'desk',
                rank_used=rank, note=_s(d.get('note'))[:300])
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("desk_allotment_mark: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
