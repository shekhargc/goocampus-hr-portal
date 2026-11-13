"""Doctor-facing exam APIs — called by goocampus.in (server-side, with X-PG-Key + the doctor's Bearer token),
exactly like the rest of /api/pg/*. The exam screen itself lives on goocampus.in; this is its engine.

  GET  /api/pg/mocks                              papers the doctor can see + access + their attempts
  POST /api/pg/mocks/<pid>/start                  start (or resume the open) attempt → state
  GET  /api/pg/mocks/attempts/<aid>               state: clock, sections, current section's questions
  POST /api/pg/mocks/attempts/<aid>/save          autosave a batch of answers (+ malpractice flags)
  POST /api/pg/mocks/attempts/<aid>/next-section  finish the section early (only if the pattern allows)
  POST /api/pg/mocks/attempts/<aid>/submit        final save + submit → state with the score
  GET  /api/pg/mocks/img/<iid>?t=…                a question picture (signed link; no key needed)
Full contract for the website session: docs/sections/mock-tests-api.md
"""
import logging

from flask import request, jsonify, Response, abort, current_app, redirect

from db import get_db
from core import storage
from exam_engine import attempts as A, papers as P, access, results as R
from exam_engine.tables import TENANT_GOOCAMPUS_IN

EXAM_CODE = 'neet_pg'
IMG_TTL = 6 * 3600


def _err(code, message, status):
    return jsonify({'ok': False, 'error': code, 'message': message}), status


def _doctor(conn):
    """(pg_users row, None) or (None, error response). Same handshake as every /api/pg/* doctor call."""
    from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token
    if not _authorized():
        return None, _err('unauthorized', 'Missing or wrong X-PG-Key.', 401)
    token = _bearer_token()
    if not token:
        return None, _err('no_token', 'Please log in.', 401)
    row = _pg_user_by_token(conn, token)
    if not row:
        return None, _err('invalid_token', 'Your login has expired — please log in again.', 401)
    return dict(row), None


def _signer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.secret_key, salt='ex-question-image')


def _image_url_maker(aid):
    def make(iid, row):
        if row and row.get('file_key') and storage.is_configured():
            url = storage.presigned_get_url(row['file_key'], ttl_seconds=IMG_TTL)
            if url:
                return url
        tok = _signer().dumps({'i': iid, 'a': aid})
        return request.url_root.rstrip('/') + f'/api/pg/mocks/img/{iid}?t={tok}'
    return make


def _own_attempt(conn, aid, user):
    a = A.load(conn, aid)
    if not a or a['user_id'] != user['id']:
        return None, None, _err('not_found', 'Attempt not found.', 404)
    p = P.load(conn, a['paper_id'])
    if not p:
        return None, None, _err('not_found', 'Paper not found.', 404)
    return a, p, None


def _close(conn):
    try:
        conn.close()
    except Exception:
        pass


def _body():
    return request.get_json(silent=True) or {}


# ── list ────────────────────────────────────────────────────────────────────────────────────────────

def api_mocks_list():
    conn = get_db()
    try:
        user, err = _doctor(conn)
        if err:
            return err
        subj = {r['id']: r['name'] for r in conn.execute(
            "SELECT id, name FROM ex_subjects WHERE tenant_id=? AND exam_code=?", (TENANT_GOOCAMPUS_IN, EXAM_CODE)).fetchall()}
        papers = [P.load(conn, r['id']) for r in conn.execute(
            "SELECT id FROM ex_papers WHERE tenant_id=? AND exam_code=? AND status='published' "
            "ORDER BY is_free_sample DESC, sort_order, id", (TENANT_GOOCAMPUS_IN, EXAM_CODE)).fetchall()]
        mine = {}
        for r in conn.execute("SELECT id, paper_id, status, score, max_score, submitted_at, started_at, deadline_at, is_ranked "
                              "FROM ex_attempts WHERE user_id=? ORDER BY id", (user['id'],)).fetchall():
            mine.setdefault(r['paper_id'], []).append(dict(r))
        ctx = access.context(conn, user, TENANT_GOOCAMPUS_IN, EXAM_CODE)
        out = []
        for p in papers:
            ok, via, reason = access.can_take(conn, user, p, ctx)
            atts = mine.get(p['id'], [])
            open_a = next((x for x in atts if x['status'] == 'in_progress'), None)
            done = [x for x in atts if x['status'] == 'submitted']
            last = done[-1] if done else None
            ranked = next((x for x in done if x['is_ranked']), None)
            pat = p['pattern']
            out.append({
                'id': p['id'], 'title': p['title'], 'kind': p['kind'], 'kind_label': P.KIND_LABEL.get(p['kind']),
                'subject': subj.get(p.get('subject_id'), ''), 'description': p.get('description') or '',
                'is_free_sample': bool(p.get('is_free_sample')),
                'total_questions': pat.get('total_questions'), 'total_minutes': pat.get('total_minutes'),
                'max_marks': pat.get('max_marks'), 'sections': len(pat.get('sections') or []),
                'access': {'allowed': ok, 'via': via, 'reason': reason},
                'attempts': {'used': len(atts), 'allowed': int(p.get('max_attempts') or 1),
                             'open_attempt_id': open_a['id'] if open_a else None,
                             'last': ({'attempt_id': last['id'], 'score': last['score'], 'max_score': last['max_score'],
                                       'ranked': bool(last['is_ranked']), 'submitted_at': A._iso(last['submitted_at'])}
                                      if last else None),
                             'ranked': ({'attempt_id': ranked['id'], 'score': ranked['score']} if ranked else None),
                             'next_is_practice': bool(done) and not open_a},
            })
        ent = ctx['ent']
        return jsonify({'ok': True, 'mocks': out,
                        'my_package': {'full_mocks': ent['full_mocks'], 'subject_tests': ent['subject_tests'],
                                       'mini_tests': ent['mini_tests'], 'packages': ent['packages']}})
    finally:
        _close(conn)


# ── start / resume ──────────────────────────────────────────────────────────────────────────────────

def api_mock_start(pid):
    conn = get_db()
    try:
        user, err = _doctor(conn)
        if err:
            return err
        p = P.load(conn, pid)
        if not p or p['tenant_id'] != TENANT_GOOCAMPUS_IN or p['status'] != 'published':
            return _err('not_found', 'This mock is not available.', 404)
        aid = A.open_attempt(conn, user['id'], pid)
        if aid:
            a = A.load(conn, aid)
            A.log_event(conn, aid, 'resumed', (request.headers.get('User-Agent') or '')[:200])
        else:
            ok, via, reason = access.can_take(conn, user, p)
            if not ok:
                return _err(reason or 'no_access', access.MESSAGES.get(reason, 'You don\'t have access to this mock.'), 403)
            if A.attempts_used(conn, user['id'], pid) >= int(p.get('max_attempts') or 1):
                return _err('no_attempts_left', 'You have already taken this mock.', 409)
            try:
                aid = A.create(conn, p, user['id'], via, (_body().get('client_info') or
                                                          request.headers.get('User-Agent') or ''))
            except Exception as e:
                conn.rollback()
                aid = A.open_attempt(conn, user['id'], pid)      # a double click started it already
                if not aid:
                    logging.exception('mock start')
                    return _err('start_failed', f'Could not start the mock ({e.__class__.__name__}).', 500)
            a = A.load(conn, aid)
        A.advance(conn, a, p)
        st = A.state(conn, a, p, _image_url_maker(a['id']))
        conn.commit()
        return jsonify({'ok': True, **st})
    finally:
        _close(conn)


# ── during the exam ─────────────────────────────────────────────────────────────────────────────────

def api_attempt_state(aid):
    conn = get_db()
    try:
        user, err = _doctor(conn)
        if err:
            return err
        a, p, err = _own_attempt(conn, aid, user)
        if err:
            return err
        A.advance(conn, a, p)
        st = A.state(conn, a, p, _image_url_maker(aid))
        conn.commit()
        return jsonify({'ok': True, **st})
    finally:
        _close(conn)


def api_attempt_save(aid):
    conn = get_db()
    try:
        user, err = _doctor(conn)
        if err:
            return err
        a, p, err = _own_attempt(conn, aid, user)
        if err:
            return err
        b = _body()
        before = (a['status'], a['cur_section'])
        res = A.save(conn, a, p, b.get('responses') or [], b.get('events') or [])
        sec_left, total_left = A.remaining(a)
        conn.commit()
        return jsonify({'ok': True, 'status': a['status'], 'saved': res['saved'], 'rejected': res['rejected'],
                        'cur_section': a['cur_section'], 'section_code': a['sections'][a['cur_section']]['code'],
                        'section_changed': (a['status'], a['cur_section']) != before,
                        'section_remaining_seconds': sec_left, 'total_remaining_seconds': total_left,
                        'server_time': A._iso(A.utcnow())})
    except Exception as e:
        logging.exception('mock save')
        try:
            conn.rollback()
        except Exception:
            pass
        return _err('save_failed', f'Could not save ({e.__class__.__name__}) — your answers are kept on this device; '
                                   'they will be sent again.', 500)
    finally:
        _close(conn)


def api_attempt_next_section(aid):
    conn = get_db()
    try:
        user, err = _doctor(conn)
        if err:
            return err
        a, p, err = _own_attempt(conn, aid, user)
        if err:
            return err
        b = _body()
        if b.get('responses'):
            A.save(conn, a, p, b['responses'], b.get('events') or [])
        msg = A.end_section_early(conn, a, p)
        if msg:
            conn.commit()
            return _err('not_allowed', msg, 409)
        st = A.state(conn, a, p, _image_url_maker(aid))
        conn.commit()
        return jsonify({'ok': True, **st})
    finally:
        _close(conn)


def api_attempt_submit(aid):
    conn = get_db()
    try:
        user, err = _doctor(conn)
        if err:
            return err
        a, p, err = _own_attempt(conn, aid, user)
        if err:
            return err
        b = _body()
        if b.get('responses') or b.get('events'):
            A.save(conn, a, p, b.get('responses') or [], b.get('events') or [])
        A.advance(conn, a, p)
        if a['status'] == 'in_progress':
            A.finalize(conn, a, p, 'doctor')
        st = A.state(conn, a, p, _image_url_maker(aid))
        conn.commit()
        return jsonify({'ok': True, **st})
    finally:
        _close(conn)


def api_attempt_result(aid):
    conn = get_db()
    try:
        user, err = _doctor(conn)
        if err:
            return err
        a, p, err = _own_attempt(conn, aid, user)
        if err:
            return err
        A.advance(conn, a, p)
        conn.commit()
        if a['status'] != 'submitted':
            return _err('not_submitted', 'The result is ready once the mock is submitted.', 409)
        return jsonify({'ok': True, **R.result(conn, a, p)})
    finally:
        _close(conn)


def api_attempt_solutions(aid):
    conn = get_db()
    try:
        user, err = _doctor(conn)
        if err:
            return err
        a, p, err = _own_attempt(conn, aid, user)
        if err:
            return err
        A.advance(conn, a, p)
        conn.commit()
        if a['status'] != 'submitted':
            return _err('not_submitted', 'Solutions open once the mock is submitted.', 409)
        sec = (request.args.get('section') or '').strip().upper() or None
        return jsonify({'ok': True, 'attempt_id': aid, 'section': sec,
                        'questions': R.solutions(conn, a, p, _image_url_maker(aid), sec)})
    finally:
        _close(conn)


def api_question_image(iid):
    """Signed picture link handed out inside an attempt's state (used when the picture isn't in R2)."""
    from itsdangerous import BadSignature, SignatureExpired
    try:
        data = _signer().loads(request.args.get('t') or '', max_age=IMG_TTL)
    except (BadSignature, SignatureExpired):
        abort(403)
    if data.get('i') != iid:
        abort(403)
    conn = get_db()
    try:
        r = conn.execute("SELECT file_key, data, content_type FROM ex_question_images WHERE id=?", (iid,)).fetchone()
        if not r:
            abort(404)
        if r['file_key'] and storage.is_configured():
            url = storage.presigned_get_url(r['file_key'], ttl_seconds=IMG_TTL)
            if url:
                return redirect(url)
        if r['data'] is None:
            abort(404)
        return Response(bytes(r['data']), mimetype=r['content_type'] or 'image/png',
                        headers={'Cache-Control': 'private, max-age=21600'})
    finally:
        _close(conn)


def register_routes(app):
    r = app.add_url_rule
    r('/api/pg/mocks', 'api_ex_mocks', api_mocks_list, methods=['GET'])
    r('/api/pg/mocks/<int:pid>/start', 'api_ex_mock_start', api_mock_start, methods=['POST'])
    r('/api/pg/mocks/attempts/<int:aid>', 'api_ex_attempt', api_attempt_state, methods=['GET'])
    r('/api/pg/mocks/attempts/<int:aid>/save', 'api_ex_attempt_save', api_attempt_save, methods=['POST'])
    r('/api/pg/mocks/attempts/<int:aid>/next-section', 'api_ex_attempt_next', api_attempt_next_section, methods=['POST'])
    r('/api/pg/mocks/attempts/<int:aid>/submit', 'api_ex_attempt_submit', api_attempt_submit, methods=['POST'])
    r('/api/pg/mocks/attempts/<int:aid>/result', 'api_ex_attempt_result', api_attempt_result, methods=['GET'])
    r('/api/pg/mocks/attempts/<int:aid>/solutions', 'api_ex_attempt_solutions', api_attempt_solutions, methods=['GET'])
    r('/api/pg/mocks/img/<int:iid>', 'api_ex_question_image', api_question_image, methods=['GET'])
