"""Counselling Desk — goocampus.in team view for building doctors' choice lists.

A GooCampus team member (e.g. Ashwini) logs into goocampus.in with her own team
account. If the founder has switched on "Counselling Desk" for that account
(pg_users.desk_access = 1, team members only), the site shows her a Desk with:

  * Internal doctors + Paid customers (two lists) — basic profile: rank, score,
    home state, target speciality, choice lists so far
  * a doctor's choice lists per counselling body (MCC / a state): build (auto 3
    rounds), add any college of that authority filtered by quota + category,
    move / remove, delete a list
  * Download PDF / Email PDF to the doctor (from info@goocampus.in)

Everything is written to the doctor's OWN pg_choice_sets/items, so it shows on the
doctor's dashboard straight away (stamped "by the GooCampus team").

Auth: the X-PG-Key server handshake + the team member's Bearer session token (the
same pattern as every /api/pg/* doctor call). Free doctors and other team accounts
are never reachable from the Desk. The list/edit work reuses the admin choice views
in choice_admin (g.desk_actor tells them who is acting). (founder 2026-10-15)
"""
import base64
import json
import logging

from flask import request, jsonify, g, Response

from db import get_db
from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token
from pg_admin.routes import choice_admin
from pg_admin.routes.api_choice import live_fees, _plan_has, _plan_label, _state_limits, _doctor_states
from pg_admin.data import choice_log as _clog

DESK_TYPES = ('internal', 'paid')
_TYPE_LABEL = {'internal': 'Internal', 'paid': 'Paid'}


def _s(v):
    return (str(v).strip() if v is not None else '')


_COLS_READY = False


def ensure_desk_columns(conn, force=False):
    """Cold-start safe: the desk flag + emailed stamps + the email log. Runs the DDL once
    per process (desk/me is called on every dashboard page) — force=True re-runs it."""
    global _COLS_READY
    if _COLS_READY and not force:
        return
    try:
        conn.execute("ALTER TABLE pg_users ADD COLUMN IF NOT EXISTS desk_access INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE pg_users ADD COLUMN IF NOT EXISTS is_team_member INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE pg_choice_sets ADD COLUMN IF NOT EXISTS owner TEXT DEFAULT 'client'")
        conn.execute("ALTER TABLE pg_choice_sets ADD COLUMN IF NOT EXISTS list_kind TEXT DEFAULT ''")
        # Ordered speciality preferences recorded by the team (any length; default 3 in the UI)
        conn.execute("ALTER TABLE pg_users ADD COLUMN IF NOT EXISTS speciality_prefs TEXT DEFAULT '[]'")
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_profile_edit_log (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,          -- the doctor
            field TEXT NOT NULL,
            old_value TEXT DEFAULT '',
            new_value TEXT DEFAULT '',
            changed_by TEXT DEFAULT '',
            source TEXT DEFAULT 'desk',
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_profile_edit_log_user ON pg_profile_edit_log (user_id, id)")
        conn.execute("ALTER TABLE pg_choice_sets ADD COLUMN IF NOT EXISTS last_emailed_at TIMESTAMP")
        _clog.ensure_choice_log(conn, force=True)
        conn.execute("ALTER TABLE pg_choice_sets ADD COLUMN IF NOT EXISTS last_emailed_by TEXT DEFAULT ''")
        conn.execute("ALTER TABLE pg_choice_sets ADD COLUMN IF NOT EXISTS last_emailed_to TEXT DEFAULT ''")
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_choice_email_log (
            id SERIAL PRIMARY KEY,
            set_id INTEGER NOT NULL,
            user_id INTEGER,                 -- the doctor
            sent_to TEXT DEFAULT '',
            sent_by TEXT DEFAULT '',
            ok INTEGER DEFAULT 0,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()
        _COLS_READY = True
    except Exception as e:
        logging.warning("ensure_desk_columns: %s", e)
        try: conn.rollback()
        except Exception: pass


def _type_sql(alias='u'):
    from pg_admin.routes.users_admin import _category_case
    return _category_case(alias)


def _doctor_type(conn, uid):
    r = conn.execute(f"SELECT {_type_sql('u')} AS t FROM pg_users u WHERE u.id = ?", [uid]).fetchone()
    return r['t'] if r else None


def _desk_member(conn):
    """The calling team member if she has desk access, else None."""
    tok = _bearer_token()
    if not tok:
        return None
    u = _pg_user_by_token(conn, tok)
    if not u:
        return None
    u = dict(u)
    if int(u.get('is_team_member') or 0) != 1 or int(u.get('desk_access') or 0) != 1:
        return None
    return u


def _guard(doctor_id=None, set_id=None, item_id=None):
    """Common gate. Returns (member, doctor_id, error_response)."""
    if not _authorized():
        return None, None, (jsonify({'ok': False, 'error': 'unauthorized'}), 401)
    conn = get_db()
    try:
        ensure_desk_columns(conn)
        m = _desk_member(conn)
        if not m:
            return None, None, (jsonify({'ok': False, 'error': 'no_desk_access',
                                         'message': 'Your account does not have Counselling Desk access.'}), 403)
        if item_id is not None:
            r = conn.execute("SELECT set_id FROM pg_choice_items WHERE id = ?", [item_id]).fetchone()
            if not r:
                return m, None, (jsonify({'ok': False, 'error': 'not_found'}), 404)
            set_id = r['set_id']
        if set_id is not None:
            r = conn.execute("SELECT user_id FROM pg_choice_sets WHERE id = ?", [set_id]).fetchone()
            if not r:
                return m, None, (jsonify({'ok': False, 'error': 'not_found'}), 404)
            doctor_id = r['user_id']
        if doctor_id is not None:
            t = _doctor_type(conn, doctor_id)
            if t not in DESK_TYPES:
                return m, None, (jsonify({'ok': False, 'error': 'out_of_scope',
                                          'message': 'The Desk covers Internal and Paid doctors only.'}), 403)
        return m, doctor_id, None
    finally:
        conn.close()


def _actor_name(m):
    return (m.get('name') or 'GooCampus team').strip()


def _as_desk(m, view, *args):
    """Run an admin choice view as this desk member (same logic, same attribution)."""
    g.desk_actor = {'name': _actor_name(m), 'is_admin': True, 'desk': True}
    return view.__wrapped__(*args)


# ── Who am I ────────────────────────────────────────────────────────────────
def desk_me():
    """GET /api/pg/desk/me → {ok, desk:true|false, name} — the site shows the Desk tab
    only when desk is true."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        ensure_desk_columns(conn)
        m = _desk_member(conn)
        return jsonify({'ok': True, 'desk': bool(m), 'name': _actor_name(m) if m else ''})
    finally:
        conn.close()


# ── Doctor lists ─────────────────────────────────────────────────────────────
def desk_doctors():
    """GET /api/pg/desk/doctors?type=internal|paid&q=&page=&per_page=
    → {ok, type, counts:{internal,paid}, total, page, doctors:[...]}"""
    m, _, err = _guard()
    if err:
        return err
    dtype = _s(request.args.get('type')) or 'internal'
    if dtype not in DESK_TYPES:
        dtype = 'internal'
    q = _s(request.args.get('q'))
    try:
        page = max(1, int(request.args.get('page') or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per = max(1, min(int(request.args.get('per_page') or 50), 200))
    except (TypeError, ValueError):
        per = 50
    conn = get_db()
    try:
        base = (f"SELECT u.id, u.name, u.mobile, u.email, u.state, u.city, u.college, "
                f"u.neet_pg_year, u.neet_pg_score, u.neet_pg_rank, u.target_speciality, u.created_at, "
                f"{_type_sql('u')} AS doc_type FROM pg_users u WHERE COALESCE(u.is_blocked,0) = 0")
        counts = {r['doc_type']: r['n'] for r in conn.execute(
            f"SELECT doc_type, COUNT(*) AS n FROM ({base}) x GROUP BY doc_type").fetchall()}
        where, params = ["x.doc_type = ?"], [dtype]
        if q:
            digits = ''.join(ch for ch in q if ch.isdigit())
            cond = "(x.name ILIKE ? OR x.email ILIKE ?"
            params += ['%' + q + '%', '%' + q + '%']
            if len(digits) >= 4:
                cond += " OR regexp_replace(COALESCE(x.mobile,''),'[^0-9]','','g') LIKE ?"
                params.append('%' + digits + '%')
            where.append(cond + ")")
        wsql = " AND ".join(where)
        total = conn.execute(f"SELECT COUNT(*) AS n FROM ({base}) x WHERE {wsql}", params).fetchone()['n']
        rows = [dict(r) for r in conn.execute(
            f"SELECT x.*, "
            "(SELECT COUNT(*) FROM pg_choice_sets s WHERE s.user_id = x.id) AS n_lists, "
            "(SELECT MAX(s.team_edited_at) FROM pg_choice_sets s WHERE s.user_id = x.id) AS last_team_edit, "
            "(SELECT MAX(s.last_emailed_at) FROM pg_choice_sets s WHERE s.user_id = x.id) AS last_emailed "
            f"FROM ({base}) x WHERE {wsql} "
            "ORDER BY x.neet_pg_rank ASC NULLS LAST, x.name ASC "
            f"LIMIT {per} OFFSET {(page - 1) * per}", params).fetchall()]
        for r in rows:
            r['type_label'] = _TYPE_LABEL.get(r.get('doc_type'), '')
            for k in ('created_at', 'last_team_edit', 'last_emailed'):
                r[k] = str(r[k])[:16] if r.get(k) else ''
        return jsonify({'ok': True, 'type': dtype,
                        'counts': {t: counts.get(t, 0) for t in DESK_TYPES},
                        'total': total, 'page': page, 'per_page': per, 'doctors': rows})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("desk_doctors: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def desk_doctor(doctor_id):
    """GET /api/pg/desk/doctors/<id> → profile basics + plan + counselling states +
    every choice list with its 3 rounds (live fees)."""
    m, _, err = _guard(doctor_id=doctor_id)
    if err:
        return err
    import json as _json
    json = _json
    conn = get_db()
    try:
        d = dict(conn.execute(
            "SELECT id, name, mobile, email, state, city, college, neet_pg_year, neet_pg_score, "
            "neet_pg_rank, target_speciality, photo_url, created_at, "
            "COALESCE(speciality_prefs,'[]') AS speciality_prefs FROM pg_users WHERE id = ?",
            [doctor_id]).fetchone())
        try:
            d['speciality_prefs'] = json.loads(d.get('speciality_prefs') or '[]')
        except Exception:
            d['speciality_prefs'] = []
        d['speciality_prefs_source'] = 'profile' if d['speciality_prefs'] else ''
        # Not set by the team yet → use the doctor's OWN choices from their onboarding form (up to 3),
        # mapped to our course names. Read-only: nothing is written to the doctor's record.
        if not d['speciality_prefs']:
            try:
                onb = conn.execute("SELECT specialities FROM pg_pgcp_onboarding WHERE user_id = ? "
                                   "ORDER BY id DESC LIMIT 1", [doctor_id]).fetchone()
                raw = json.loads((onb or {}).get('specialities') or '[]') if onb else []
            except Exception:
                try: conn.rollback()
                except Exception: pass
                raw = []
            if not raw and d.get('target_speciality'):
                raw = [x.strip() for x in str(d['target_speciality']).split(',') if x.strip()]
            if raw:
                d['onboarding_specialities'] = raw
                d['speciality_prefs'] = _map_specialities(conn, raw)
                d['speciality_prefs_source'] = 'onboarding'
        d['created_at'] = str(d['created_at'])[:16] if d.get('created_at') else ''
        d['doc_type'] = _doctor_type(conn, doctor_id)
        d['type_label'] = _TYPE_LABEL.get(d['doc_type'], '')
        d['plan'] = _plan_label(conn, doctor_id)
        d['can_auto_build'] = _plan_has(conn, doctor_id, 'dash_choice_list')
        states = _doctor_states(conn, doctor_id)
        home_ok, max_other = _state_limits(conn, doctor_id)
        others = [s for s in states if s['role'] == 'other']
        sets = [dict(r) for r in conn.execute(
            "SELECT * FROM pg_choice_sets WHERE user_id = ? ORDER BY id", [doctor_id]).fetchall()]
        items = [dict(r) for r in conn.execute(
            "SELECT i.* FROM pg_choice_items i JOIN pg_choice_sets s ON s.id = i.set_id "
            "WHERE s.user_id = ? ORDER BY i.set_id, i.round, i.position, i.id", [doctor_id]).fetchall()]
        live_fees(conn, items)
        by = {s['id']: s for s in sets}
        for s in sets:
            for k in ('specialties', 'quota_categories'):
                try:
                    s[k] = _json.loads(s.get(k) or '[]')
                except Exception:
                    s[k] = []
            s['needs_ack'] = _clog.ack_state(s)
            for k in ('created_at', 'updated_at', 'team_edited_at', 'last_emailed_at',
                      'client_ack_at', 'client_edited_at'):
                s[k] = str(s[k])[:16] if s.get(k) else ''
            s['rounds'] = {'1': [], '2': [], '3': []}
        for it in items:
            s = by.get(it['set_id'])
            if s is None:
                continue
            it['added_at'] = str(it['added_at'])[:16] if it.get('added_at') else ''
            s['rounds'].setdefault(str(it['round']), []).append(it)
        return jsonify({'ok': True, 'doctor': d, 'states': states,
                        'home': next((s['state'] for s in states if s['role'] == 'home'), None),
                        'allowed_other': ('any' if max_other is None else max_other),
                        'can_add_other': home_ok and (max_other is None or len(others) < max_other),
                        'lists': sets})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("desk_doctor: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── Choice-list work (same logic as the goocampus.org admin panel) ───────────
def desk_states(doctor_id):
    """GET / POST {state} / DELETE {state} — the doctor's counselling states."""
    m, _, err = _guard(doctor_id=doctor_id)
    return err or _as_desk(m, choice_admin.choice_states, doctor_id)


def desk_create_list(doctor_id):
    """POST {scope:'mcc'|'state', state, authority, degree_group, rank, specialties[],
    quota_categories:[{quota,categories[]}], label, auto} → build (or rebuild) the list."""
    m, _, err = _guard(doctor_id=doctor_id)
    return err or _as_desk(m, choice_admin.choice_create, doctor_id)


def desk_facets():
    """GET ?scope=&state=&degree_group= → quotas + categories (by quota) for the build form."""
    m, _, err = _guard()
    return err or _as_desk(m, choice_admin.choice_facets)


def desk_search(set_id):
    """GET ?round=1|2|3&q=&quota=&category=&limit=&offset= → colleges of this list's
    authority with that round's closing rank + chance vs the doctor's rank."""
    m, _, err = _guard(set_id=set_id)
    return err or _as_desk(m, choice_admin.choice_cutoff_search, set_id)


def desk_add(set_id):
    """POST {round, institute, course, quota, category, master_id, closing_rank}."""
    m, _, err = _guard(set_id=set_id)
    return err or _as_desk(m, choice_admin.choice_add, set_id)


def desk_reorder(set_id):
    """POST {round, ordered_item_ids:[...]}."""
    m, _, err = _guard(set_id=set_id)
    return err or _as_desk(m, choice_admin.choice_reorder, set_id)


def desk_delete_list(set_id):
    """DELETE (or POST) → remove the whole list."""
    m, _, err = _guard(set_id=set_id)
    return err or _as_desk(m, choice_admin.choice_delete_set, set_id)


def desk_move(item_id):
    """POST {dir:'up'|'down'}."""
    m, _, err = _guard(item_id=item_id)
    return err or _as_desk(m, choice_admin.choice_move, item_id)


def desk_remove(item_id):
    """DELETE (or POST) → remove one college from its round."""
    m, _, err = _guard(item_id=item_id)
    return err or _as_desk(m, choice_admin.choice_delete, item_id)


def desk_history(set_id):
    """GET → every change to this list, newest first: who (team member or the doctor),
    what (build/add/move/reorder/remove/email/acknowledge), which college + round, when (UTC)."""
    m, _, err = _guard(set_id=set_id)
    if err:
        return err
    conn = get_db()
    try:
        return jsonify({'ok': True, 'history': _clog.history(conn, set_id)})
    except Exception as e:
        logging.error("desk_history: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── PDF + email ──────────────────────────────────────────────────────────────
def _pdf_response(pdf, fname):
    return Response(pdf, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{fname}"'})


def desk_pdf(set_id):
    """GET → the GooCampus-branded PDF of this list."""
    m, _, err = _guard(set_id=set_id)
    if err:
        return err
    from pg_admin.choice_pdf import build_pdf
    conn = get_db()
    try:
        pdf, fname = build_pdf(conn, set_id, prepared_by=_actor_name(m))
        if not pdf:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        return _pdf_response(pdf, fname)
    except Exception as e:
        logging.error("desk_pdf: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def desk_email(set_id):
    """POST {to?:email (default = the doctor's email), note?:text, cc_me?:bool}
    → emails the PDF to the doctor from info@goocampus.in and logs it."""
    m, doctor_id, err = _guard(set_id=set_id)
    if err:
        return err
    import re
    from email_utils import send_email, render_branded_email
    from pg_admin.choice_pdf import build_pdf, load_set, set_title
    body = request.get_json(silent=True) or {}
    conn = get_db()
    try:
        s, d, _rounds = load_set(conn, set_id)
        to = _s(body.get('to')) or _s(d.get('email'))
        if not to or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', to):
            return jsonify({'ok': False, 'error': 'no_email',
                            'message': 'This doctor has no valid email — enter one to send to.'}), 400
        pdf, fname = build_pdf(conn, set_id, prepared_by=_actor_name(m))
        name = (d.get('name') or '').strip()
        dr = name if name.lower().startswith('dr') else ('Dr. ' + name if name else 'Doctor')
        note = _s(body.get('note'))
        from html import escape
        inner = (f"<p style='margin:0 0 14px;font-size:15px;color:#0F1B33;'>Dear {escape(dr)},</p>"
                 f"<p style='margin:0 0 14px;font-size:14px;color:#374151;line-height:1.6;'>"
                 f"Please find attached your NEET-PG choice list for <b>{escape(set_title(s))}</b>, "
                 f"prepared by your GooCampus counsellor {escape(_actor_name(m))}.</p>")
        if note:
            inner += (f"<p style='margin:0 0 14px;font-size:14px;color:#374151;line-height:1.6;"
                      f"white-space:pre-wrap;'>{escape(note)}</p>")
        inner += ("<p style='margin:0 0 14px;font-size:14px;color:#374151;line-height:1.6;'>"
                  "Please open it on your dashboard at "
                  "<a href='https://goocampus.in/dashboard/team-choice-list' style='color:#EA6C1E;font-weight:bold;'>goocampus.in</a> (GooCampus Team Choice List), "
                  "review it and confirm. You can edit it there too.</p>"
                  "<p style='margin:0 0 16px;font-size:12px;color:#6b7280;line-height:1.55;"
                  "border-left:3px solid #fdba74;padding:6px 10px;background:#fff7ed;'>"
                  + escape(_clog.DISCLAIMER) + "</p>"
                  "<p style='margin:0;font-size:14px;color:#374151;'>Warm regards,<br>Team GooCampus</p>")
        html = render_branded_email('Your NEET-PG choice list', inner,
                                    preheader=f'Your choice list for {set_title(s)} is attached')
        cc = []
        if body.get('cc_me') and _s(m.get('email')):
            cc = [_s(m.get('email'))]
        ok = send_email([to], f'Your NEET-PG choice list — {set_title(s)}', html,
                        from_address='GooCampus <info@goocampus.in>', cc_list=cc or None,
                        attachments=[{'filename': fname,
                                      'content': base64.b64encode(pdf).decode('ascii')}])
        conn.execute("INSERT INTO pg_choice_email_log (set_id, user_id, sent_to, sent_by, ok) "
                     "VALUES (?,?,?,?,?)", [set_id, doctor_id, to, _actor_name(m), 1 if ok else 0])
        if ok:
            _clog.log(conn, set_id, 'email', 'team', _actor_name(m), user_id=doctor_id, detail={'to': to})
            conn.execute("UPDATE pg_choice_sets SET last_emailed_at = CURRENT_TIMESTAMP, "
                         "last_emailed_by = ?, last_emailed_to = ? WHERE id = ?",
                         [_actor_name(m), to, set_id])
        conn.commit()
        if not ok:
            return jsonify({'ok': False, 'error': 'send_failed',
                            'message': 'The email could not be sent — please try again.'}), 502
        return jsonify({'ok': True, 'sent_to': to})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("desk_email: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── The doctor's own Download PDF ────────────────────────────────────────────
def doctor_choice_pdf(set_id):
    """GET /api/pg/choice-sets/<id>/pdf — the doctor downloads their OWN list as a PDF.
    Internal + paid doctors (the choice-list plan feature); Free gets a 403 message."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    from pg_admin.choice_pdf import build_pdf
    conn = get_db()
    try:
        tok = _bearer_token()
        u = _pg_user_by_token(conn, tok) if tok else None
        if not u:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        s = conn.execute("SELECT id, team_edited_by FROM pg_choice_sets WHERE id = ? AND user_id = ?",
                         [set_id, u['id']]).fetchone()
        if not s:
            return jsonify({'ok': False, 'error': 'not_found'}), 404
        if not _plan_has(conn, u['id'], 'dash_choice_list'):
            return jsonify({'ok': False, 'error': 'not_entitled',
                            'message': 'Downloading your choice list as a PDF is part of the paid plans.'}), 403
        pdf, fname = build_pdf(conn, set_id, prepared_by=(s.get('team_edited_by') or ''))
        return _pdf_response(pdf, fname)
    except Exception as e:
        logging.error("doctor_choice_pdf: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


# ── Read-only self-test (X-News-Key) ─────────────────────────────────────────
def desk_selftest():
    """GET /api/pg/desk/selftest (X-News-Key) — proves the Desk SQL + PDF work on the
    real Postgres without any login: returns COUNTS and sizes only, no doctor data."""
    from pg_admin.routes.api_news_ingest import _ok
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    from flask import current_app
    out = {'ok': True}
    conn = get_db()
    try:
        ensure_desk_columns(conn)
        base = (f"SELECT u.id, {_type_sql('u')} AS doc_type FROM pg_users u "
                "WHERE COALESCE(u.is_blocked,0) = 0")
        out['counts'] = {r['doc_type']: r['n'] for r in conn.execute(
            f"SELECT doc_type, COUNT(*) AS n FROM ({base}) x GROUP BY doc_type").fetchall()}
        out['desk_members'] = conn.execute(
            "SELECT COUNT(*) AS n FROM pg_users WHERE COALESCE(is_team_member,0)=1 "
            "AND COALESCE(desk_access,0)=1").fetchone()['n']
        r = conn.execute(
            f"SELECT s.id FROM pg_choice_sets s JOIN ({base}) x ON x.id = s.user_id "
            "WHERE x.doc_type IN ('internal','paid') AND EXISTS "
            "(SELECT 1 FROM pg_choice_items i WHERE i.set_id = s.id) ORDER BY s.id DESC LIMIT 1").fetchone()
        sid = r['id'] if r else None
        out['sample_set'] = bool(sid)
        # Internal/paid doctors whose plan does NOT include the choice-list feature
        # (the Desk could not auto-build MCC / extra states for them).
        missing = {'internal': 0, 'paid': 0}
        for row in conn.execute(f"SELECT id, doc_type FROM ({base}) x "
                                "WHERE doc_type IN ('internal','paid')").fetchall():
            if not _plan_has(conn, row['id'], 'dash_choice_list'):
                missing[row['doc_type']] += 1
        out['without_choice_feature'] = missing
    finally:
        conn.close()
    if sid:
        from pg_admin.choice_pdf import build_pdf
        conn = get_db()
        try:
            pdf, _fn = build_pdf(conn, sid, prepared_by='Self-test')
            out['pdf_bytes'] = len(pdf or b'')
        except Exception as e:
            out['pdf_error'] = str(e)[:200]
        finally:
            conn.close()
        try:
            with current_app.test_request_context(
                    f'/x?round=1&limit=500', method='GET'):
                g.desk_actor = {'name': 'Self-test', 'is_admin': True, 'desk': True}
                resp = choice_admin.choice_cutoff_search.__wrapped__(sid)
                body = resp.get_json() if hasattr(resp, 'get_json') else resp[0].get_json()
                out['search_rows_round1'] = len(body.get('rows') or []) if body else None
                out['search_ok'] = bool(body and body.get('ok'))
        except Exception as e:
            out['search_error'] = str(e)[:200]
    try:
        with current_app.test_request_context('/x?scope=mcc&degree_group=mdms', method='GET'):
            g.desk_actor = {'name': 'Self-test', 'is_admin': True, 'desk': True}
            resp = choice_admin.choice_facets.__wrapped__()
            body = resp.get_json()
            out['facets_quotas'] = len(body.get('quotas') or [])
    except Exception as e:
        out['facets_error'] = str(e)[:200]
    # Speciality grouping (clinical / non-clinical) — counts only.
    try:
        from pg_admin.data import specialty_groups as sg
        conn = get_db()
        try:
            cs = [r['course'] for r in conn.execute(
                "SELECT DISTINCT course FROM pg_cutoffs WHERE COALESCE(is_reference,0)=0 AND COALESCE(course,'')<>''").fetchall()]
            ctx = sg.context(conn)
            grp = [sg.group_source(c, ctx)[0] for c in cs]
            out['specialities'] = {'clinical': sum(1 for x in grp if x == 'clinical'),
                                   'non_clinical': sum(1 for x in grp if x != 'clinical')}
            out['profile_log_table'] = bool(conn.execute(
                "SELECT to_regclass('pg_profile_edit_log') AS t").fetchone()['t'])
        finally:
            conn.close()
    except Exception as e:
        out['spec_error'] = str(e)[:200]
    # Onboarding speciality names → our course names (read-only mapping check).
    try:
        conn = get_db()
        try:
            out['spec_map'] = _map_specialities(conn, ['Radiology', 'General Medicine', 'Dermatology',
                                                       'Orthopaedics', 'Paediatrics', 'OBG'])
            raw = [r['s'] for r in conn.execute(
                "SELECT specialities AS s FROM pg_pgcp_onboarding WHERE COALESCE(specialities,'[]') <> '[]' "
                "ORDER BY id DESC LIMIT 40").fetchall()]
            names = sorted({x for t in raw for x in (json.loads(t) if t else [])})
            out['onboarding_spec_names'] = names[:40]
        finally:
            conn.close()
    except Exception as e:
        out['spec_map_error'] = str(e)[:200]
    # MCC authority header summary (official sections combined, NMC excluded).
    try:
        from pg_admin.routes.api_authorities import _seat_matrix_for
        from pg_admin.authorities import get_authority
        conn = get_db()
        try:
            sm = _seat_matrix_for(conn, get_authority('mcc'))
            out['mcc_header'] = {k: sm.get(k) for k in ('total_seats', 'college_count', 'counselling_body')} if sm else None
        finally:
            conn.close()
    except Exception as e:
        out['mcc_header_error'] = str(e)[:200]
    # Recommended MCC lists — read-only dry run (counts + first 3 tiers), no writes.
    try:
        from pg_admin.routes import recommended as _rec
        conn = get_db()
        try:
            _rec.ensure_rec_tables(conn)
            for combo in _rec.COMBOS:
                items = _rec._matrix_items(conn, combo, ['MD - Radio-diagnosis', 'MD - General Medicine'], 5000)
                out['rec_' + combo] = {'items': len(items), 'new': sum(1 for i in items if not i['has_cutoff']),
                                       'first': [i['tier'] for i in items[:3]],
                                       'tiers_set': len(_rec._tiers(conn, combo))}
        finally:
            conn.close()
    except Exception as e:
        out['rec_error'] = str(e)[:200]
    return jsonify(out)



def _map_specialities(conn, names):
    """Doctor-typed speciality names ('Radiology', 'General Medicine') → our MD/MS course names
    ('MD - Radio-diagnosis'). Exact match first, then the course whose core matches; unmatched
    names are kept as typed so nothing the doctor chose is lost."""
    from pg_admin.routes.api_choice import _spec_core
    try:
        courses = [r['course'] for r in conn.execute(
            "SELECT DISTINCT course FROM pg_cutoffs WHERE COALESCE(is_reference,0)=0 AND COALESCE(course,'')<>'' "
            "AND UPPER(LEFT(course, 2)) IN ('MD', 'MS')").fetchall()]
    except Exception:
        try: conn.rollback()
        except Exception: pass
        courses = []
    norm = lambda x: ''.join(ch for ch in (x or '').lower().replace('&', ' and ') if ch.isalnum())
    # Common short / everyday names → a word that appears in our course name
    alias = {'radiology': 'radio', 'radiodiagnosis': 'radio', 'obg': 'obstetrics', 'obgy': 'obstetrics',
             'og': 'obstetrics', 'gynaecology': 'obstetrics', 'gynecology': 'obstetrics', 'ent': 'ent',
             'ortho': 'orthopaedics', 'orthopedics': 'orthopaedics', 'peds': 'paediatrics',
             'pediatrics': 'paediatrics', 'medicine': 'generalmedicine', 'surgery': 'generalsurgery',
             'anesthesia': 'anaesthesiology', 'anaesthesia': 'anaesthesiology', 'derma': 'dermatology',
             'psych': 'psychiatry', 'pulmonology': 'respiratory', 'chestmedicine': 'respiratory',
             'tbchest': 'respiratory', 'ophthal': 'ophthalmology', 'eye': 'ophthalmology',
             'communitymedicine': 'community', 'psm': 'community', 'forensic': 'forensic', 'fmt': 'forensic',
             'emergency': 'emergency', 'radiotherapy': 'radiation', 'familymedicine': 'family'}
    flat = []
    for n in names:                     # a doctor may type several in one box: "Surgery, Psychiatry, ..."
        flat.extend([x.strip() for x in str(n or '').split(',') if x.strip()])
    out = []
    for n in flat:
        n = _s(n)
        if not n:
            continue
        key = alias.get(norm(n))
        if key:
            cands = [c for c in courses if key in norm(c)]
            if cands:
                v = sorted(cands, key=len)[0]
                if v not in out:
                    out.append(v)
                continue
        hit = next((c for c in courses if norm(c) == norm(n) or norm(_spec_core(c)) == norm(n)), None)
        if not hit:
            core = norm(_spec_core(n))[:8]
            cands = [c for c in courses if core and core in norm(c)]
            hit = sorted(cands, key=len)[0] if cands else None
        v = hit or n
        if v not in out:
            out.append(v)
    return out


# ── Team edits a doctor's profile (internal / paid only) ─────────────────────
_EDITABLE = ('name', 'email', 'neet_pg_year', 'neet_pg_rank', 'neet_pg_score', 'target_speciality',
             'college', 'city', 'state')
_INTS = {'neet_pg_rank', 'neet_pg_score'}


def desk_profile(doctor_id):
    """POST /api/pg/desk/doctors/<id>/profile  {name?, email?, neet_pg_year?, neet_pg_rank?,
    neet_pg_score?, target_speciality?, college?, city?, state?, speciality_prefs?:[ordered courses]}
    Only the keys sent are changed (blank never wipes). The mobile is never editable (login id).
    'state' is the Home/Domicile state — must be a canonical state; it also updates the doctor's
    counselling home state. Every change is logged (pg_profile_edit_log). GET → the change log."""
    import json as _json
    m, _, err = _guard(doctor_id=doctor_id)
    if err:
        return err
    conn = get_db()
    try:
        if request.method == 'GET':
            rows = [dict(r) for r in conn.execute(
                "SELECT field, old_value, new_value, changed_by, source, changed_at FROM pg_profile_edit_log "
                "WHERE user_id = ? ORDER BY id DESC LIMIT 200", [doctor_id]).fetchall()]
            for r in rows:
                r['changed_at'] = str(r['changed_at'])[:19] if r.get('changed_at') else ''
            return jsonify({'ok': True, 'log': rows})
        body = request.get_json(silent=True) or {}
        cur = dict(conn.execute("SELECT * FROM pg_users WHERE id = ?", [doctor_id]).fetchone())
        who = _actor_name(m)
        changes = {}
        for k in _EDITABLE:
            if k not in body:
                continue
            v = body.get(k)
            if k in _INTS:
                try:
                    v = int(float(v)) if v not in (None, '') else None
                except (TypeError, ValueError):
                    return jsonify({'ok': False, 'error': 'bad_value', 'field': k}), 400
                if v is None:
                    continue
            else:
                v = _s(v)
                if not v:
                    continue
            if k == 'state':
                from pg_admin.routes.users_admin import _canonical_states
                canon = {x.lower(): x for x in _canonical_states()}
                if v.lower() not in canon:
                    return jsonify({'ok': False, 'error': 'bad_state', 'message': 'Pick a state from the list.'}), 400
                v = canon[v.lower()]
            if (cur.get(k) if cur.get(k) is not None else '') != v:
                changes[k] = v
        prefs = None
        if 'speciality_prefs' in body:
            prefs = [_s(x) for x in (body.get('speciality_prefs') or []) if _s(x)]
            seen = set(); prefs = [x for x in prefs if not (x.lower() in seen or seen.add(x.lower()))]
        if not changes and prefs is None:
            return jsonify({'ok': True, 'changed': []})
        if changes:
            sets = ', '.join(f"{k} = ?" for k in changes)
            conn.execute(f"UPDATE pg_users SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         list(changes.values()) + [doctor_id])
            for k, v in changes.items():
                conn.execute("INSERT INTO pg_profile_edit_log (user_id, field, old_value, new_value, changed_by) "
                             "VALUES (?,?,?,?,?)", [doctor_id, k, '' if cur.get(k) is None else str(cur.get(k)),
                                                     str(v), who])
            if 'state' in changes:       # keep the counselling home state in step (same as the admin edit)
                home = conn.execute("SELECT id FROM pg_doctor_states WHERE user_id = ? AND role = 'home'",
                                    [doctor_id]).fetchone()
                if home:
                    conn.execute("UPDATE pg_doctor_states SET state = ? WHERE id = ?", [changes['state'], home['id']])
                else:
                    conn.execute("INSERT INTO pg_doctor_states (user_id, state, role, locked) VALUES (?,?,'home',1)",
                                 [doctor_id, changes['state']])
        if prefs is not None:
            old = cur.get('speciality_prefs') or '[]'
            new = _json.dumps(prefs)
            if old != new:
                conn.execute("UPDATE pg_users SET speciality_prefs = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                             [new, doctor_id])
                conn.execute("INSERT INTO pg_profile_edit_log (user_id, field, old_value, new_value, changed_by) "
                             "VALUES (?,?,?,?,?)", [doctor_id, 'speciality_prefs', old, new, who])
                changes['speciality_prefs'] = prefs
        conn.commit()
        return jsonify({'ok': True, 'changed': list(changes.keys())})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("desk_profile: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def desk_specialities():
    """GET /api/pg/desk/specialities?degree_group=mdms&authority=
    → {clinical:[course...], non_clinical:[course...]} — every course in the cut-off data, grouped
    the same way doctors see it (para/pre-clinical fold into non-clinical)."""
    m, _, err = _guard()
    if err:
        return err
    from pg_admin.data import specialty_groups as sg
    from pg_admin.routes.api_choice import _deg_clause
    dg = _s(request.args.get('degree_group')) or 'mdms'
    auth = _s(request.args.get('authority'))
    conn = get_db()
    try:
        where, params = ["COALESCE(c.is_reference,0)=0"], []
        dgc, dgp = _deg_clause(dg)
        if dgc:
            where.append(dgc); params.append(dgp)
        if auth:
            where.append("c.authority ILIKE ?"); params.append('%' + auth + '%')
        courses = [r['course'] for r in conn.execute(
            "SELECT DISTINCT c.course AS course FROM pg_cutoffs c WHERE " + " AND ".join(where) +
            " AND COALESCE(c.course,'')<>'' ORDER BY c.course", params).fetchall()]
        ctx = sg.context(conn)
        out = {'clinical': [], 'non_clinical': []}
        for c in courses:
            g, _src = sg.group_source(c, ctx)
            out['clinical' if g == 'clinical' else 'non_clinical'].append(c)
        return jsonify({'ok': True, **out})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("desk_specialities: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()
