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
import logging

from flask import request, jsonify, g, Response

from db import get_db
from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token
from pg_admin.routes import choice_admin
from pg_admin.routes.api_choice import live_fees, _plan_has, _plan_label, _state_limits, _doctor_states

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
        conn.execute("ALTER TABLE pg_choice_sets ADD COLUMN IF NOT EXISTS last_emailed_at TIMESTAMP")
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
    conn = get_db()
    try:
        d = dict(conn.execute(
            "SELECT id, name, mobile, email, state, city, college, neet_pg_year, neet_pg_score, "
            "neet_pg_rank, target_speciality, photo_url, created_at FROM pg_users WHERE id = ?",
            [doctor_id]).fetchone())
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
            for k in ('created_at', 'updated_at', 'team_edited_at', 'last_emailed_at'):
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
                  "You can also see and download it any time from your dashboard on "
                  "<a href='https://goocampus.in' style='color:#EA6C1E;'>goocampus.in</a>. "
                  "Please check the official seat matrix before you lock your choices.</p>"
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
    return jsonify(out)
