"""Mock Tests › Question bank, Papers, Pattern — the team's screens for step 4 (admin only for now).

  /admin/pg/mocks/bank                    browse / search the question bank; add a question by hand
  /admin/pg/mocks/papers                  list of papers (mocks) + create one
  /admin/pg/mocks/papers/<pid>            paper builder: sections, picker, auto-fill, checks, lock, publish
  /admin/pg/mocks/papers/<pid>/preview    the whole paper as doctors will see it (with answers)
  /admin/pg/mocks/pattern                 the exam pattern as editable settings (new version on save)
"""
import json
import logging

from flask import render_template, request, redirect, url_for, flash, abort

from db import get_db
from core.auth import login_required
from exam_engine import store, papers
from exam_engine.admin import _admin, _who, _deny, _close, EXAM_CODE
from exam_engine.tables import TENANT_GOOCAMPUS_IN


# ── question bank ───────────────────────────────────────────────────────────────────────────────────

@login_required
def bank():
    user = _admin()
    if not user:
        return _deny()
    a = request.args
    status = a.get('status', 'approved')
    try:
        subject_id = int(a.get('subject') or 0) or None
    except ValueError:
        subject_id = None
    text, topic = (a.get('q') or '').strip(), (a.get('topic') or '').strip()
    usage_f = a.get('used', '')
    try:
        page = max(1, int(a.get('page') or 1))
    except ValueError:
        page = 1
    per = 50
    conn = get_db()
    try:
        subj = store.subjects(conn, EXAM_CODE, TENANT_GOOCAMPUS_IN)
        where, params = ["q.tenant_id=?", "q.exam_code=?"], [TENANT_GOOCAMPUS_IN, EXAM_CODE]
        if status in ('approved', 'draft', 'rejected'):
            where.append("q.status=?")
            params.append(status)
        if subject_id:
            where.append("q.subject_id=?")
            params.append(subject_id)
        elif a.get('subject') == 'none':
            where.append("q.subject_id IS NULL")
        if text:
            where.append("(q.stem ILIKE ? OR q.options_json ILIKE ?)")
            params += ['%' + text + '%', '%' + text + '%']
        if topic:
            where.append("q.topic ILIKE ?")
            params.append('%' + topic + '%')
        if usage_f == 'unused':
            where.append("NOT EXISTS (SELECT 1 FROM ex_paper_items pi WHERE pi.question_id = q.id)")
        elif usage_f == 'used':
            where.append("EXISTS (SELECT 1 FROM ex_paper_items pi WHERE pi.question_id = q.id)")
        if a.get('img') == '1':
            where.append("EXISTS (SELECT 1 FROM ex_question_images im WHERE im.question_id = q.id AND im.role='stem')")
        w = ' AND '.join(where)
        total = conn.execute(f"SELECT COUNT(*) AS n FROM ex_questions q WHERE {w}", tuple(params)).fetchone()['n']
        rows = [dict(r) for r in conn.execute(
            f"SELECT q.id, q.stem, q.subject_id, q.topic, q.status, q.n_errors, q.answer, q.batch_id, q.source_no, "
            f"q.version, q.updated_at, "
            f"(SELECT COUNT(*) FROM ex_question_images im WHERE im.question_id = q.id AND im.role='stem') AS n_images, "
            f"(SELECT COUNT(*) FROM ex_paper_items pi WHERE pi.question_id = q.id) AS n_used "
            f"FROM ex_questions q WHERE {w} ORDER BY q.id DESC LIMIT ? OFFSET ?",
            tuple(params + [per, (page - 1) * per])).fetchall()]
        name = {s['id']: s['name'] for s in subj}
        for r in rows:
            r['subject'] = name.get(r['subject_id'], '')
        counts = {r['status']: r['n'] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM ex_questions WHERE tenant_id=? AND exam_code=? GROUP BY status",
            (TENANT_GOOCAMPUS_IN, EXAM_CODE)).fetchall()}
        return render_template('exam_engine/bank.html', rows=rows, subjects=subj, total=total, page=page, per=per,
                               counts=counts, f={'status': status, 'subject': a.get('subject', ''), 'q': text,
                                                 'topic': topic, 'used': usage_f, 'img': a.get('img', '')})
    finally:
        _close(conn)


@login_required
def question_new():
    """A blank draft question typed in by hand (no file)."""
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        qid = conn.execute(
            "INSERT INTO ex_questions (tenant_id, exam_code, stem, options_json, flags_json, n_errors, updated_by) "
            "VALUES (?, ?, '', ?, '[]', 1, ?) RETURNING id",
            (TENANT_GOOCAMPUS_IN, EXAM_CODE, json.dumps([[L, ''] for L in 'ABCD']), _who(user))).fetchone()['id']
        store.recheck(conn, qid)
        conn.commit()
        flash('New question created — type it in below, then approve it.', 'info')
        return redirect(url_for('ex_question', qid=qid))
    finally:
        _close(conn)


# ── papers ──────────────────────────────────────────────────────────────────────────────────────────

@login_required
def papers_list():
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM ex_paper_items i WHERE i.paper_id = p.id) AS n_items "
            "FROM ex_papers p WHERE p.tenant_id=? AND p.exam_code=? ORDER BY p.status='retired', p.sort_order, p.id",
            (TENANT_GOOCAMPUS_IN, EXAM_CODE)).fetchall()]
        subj = store.subjects(conn, EXAM_CODE, TENANT_GOOCAMPUS_IN)
        name = {s['id']: s['name'] for s in subj}
        for r in rows:
            pat = json.loads(r.get('pattern_json') or '{}')
            r['total'] = pat.get('total_questions') or 0
            r['minutes'] = pat.get('total_minutes') or 0
            r['subject'] = name.get(r.get('subject_id'), '')
            r['when'] = store.now_ist_str(r.get('updated_at'))
        approved = conn.execute("SELECT COUNT(*) AS n FROM ex_questions WHERE tenant_id=? AND exam_code=? "
                                "AND status='approved' AND n_errors=0", (TENANT_GOOCAMPUS_IN, EXAM_CODE)).fetchone()['n']
        cfg = store.pattern(conn, EXAM_CODE, TENANT_GOOCAMPUS_IN)
        return render_template('exam_engine/papers.html', rows=rows, subjects=subj, approved=approved, cfg=cfg,
                               kind_label=papers.KIND_LABEL, status_label=papers.STATUS_LABEL)
    finally:
        _close(conn)


@login_required
def paper_create():
    user = _admin()
    if not user:
        return _deny()
    kind = request.form.get('kind') if request.form.get('kind') in papers.KIND_LABEL else 'full'
    title = (request.form.get('title') or '').strip()[:200]
    try:
        subject_id = int(request.form.get('subject_id') or 0) or None
    except ValueError:
        subject_id = None
    if not title:
        flash('Give the paper a name, e.g. "Grand Test 1".', 'error')
        return redirect(url_for('ex_papers'))
    if kind == 'subject' and not subject_id:
        flash('Choose the subject for a subject test.', 'error')
        return redirect(url_for('ex_papers'))
    conn = get_db()
    try:
        cfg = store.pattern(conn, EXAM_CODE, TENANT_GOOCAMPUS_IN)
        pat = papers.pattern_for(kind, cfg)
        pid = conn.execute(
            "INSERT INTO ex_papers (tenant_id, exam_code, title, kind, subject_id, description, pattern_json, created_by, "
            "max_attempts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 3) RETURNING id",
            (TENANT_GOOCAMPUS_IN, EXAM_CODE, title, kind, subject_id if kind == 'subject' else None,
             (request.form.get('description') or '').strip()[:1000], json.dumps(pat), _who(user))).fetchone()['id']
        conn.commit()
        return redirect(url_for('ex_paper', pid=pid))
    finally:
        _close(conn)


def _paper_or_404(conn, pid):
    p = papers.load(conn, pid)
    if not p or p['tenant_id'] != TENANT_GOOCAMPUS_IN:
        abort(404)
    return p


@login_required
def paper_view(pid):
    user = _admin()
    if not user:
        return _deny()
    a = request.args
    conn = get_db()
    try:
        p = _paper_or_404(conn, pid)
        rows = papers.items(conn, p)
        secs = papers.by_section(p, rows)
        errors, notes = papers.lock_check(conn, p, rows)
        subj = store.subjects(conn, p['exam_code'], p['tenant_id'])
        cur = papers.subject_counts(rows)
        bp = p['pattern'].get('blueprint') or {}
        mix = [(s['name'], cur.get(s['name'], 0), bp.get(s['name'])) for s in subj
               if cur.get(s['name']) or bp.get(s['name'])]
        if cur.get('Not set'):
            mix.append(('Not set', cur['Not set'], None))
        used = papers.usage(conn, [r['question_id'] for r in rows], exclude_paper=p['id'])
        picker = None
        if not p['frozen'] and a.get('pick'):
            try:
                sid = int(a.get('subject') or 0) or None
            except ValueError:
                sid = None
            if p['kind'] == 'subject' and not a.get('subject'):
                sid = p.get('subject_id')
            picker = {'rows': papers.candidates(conn, p, sid, (a.get('q') or '').strip(), (a.get('topic') or '').strip(),
                                                a.get('unused') == '1', a.get('img') == '1'),
                      'f': {'subject': str(sid or ''), 'q': a.get('q', ''), 'topic': a.get('topic', ''),
                            'unused': a.get('unused', ''), 'img': a.get('img', ''), 'section': a.get('section', '')}}
        approved = conn.execute("SELECT COUNT(*) AS n FROM ex_questions WHERE tenant_id=? AND exam_code=? "
                                "AND status='approved' AND n_errors=0", (p['tenant_id'], p['exam_code'])).fetchone()['n']
        return render_template('exam_engine/paper.html', p=p, secs=secs, rows=rows, errors=errors, notes=notes,
                               mix=mix, used=used, picker=picker, subjects=subj, approved=approved,
                               attempts=papers.attempts_count(conn, p['id']),
                               kind_label=papers.KIND_LABEL, status_label=papers.STATUS_LABEL,
                               subject_name={s['id']: s['name'] for s in subj}.get(p.get('subject_id'), ''))
    finally:
        _close(conn)


def _draft_only(p, pid):
    if p['frozen']:
        flash('This paper is locked — unlock it first to change its questions.', 'error')
        return redirect(url_for('ex_paper', pid=pid))
    return None


@login_required
def paper_edit(pid):
    """Builder actions on a draft paper: add / remove / move / auto-fill / clear."""
    user = _admin()
    if not user:
        return _deny()
    f = request.form
    action = f.get('action') or (f.get('move_to') if (f.get('move_to') or '').startswith('to:') else None)
    conn = get_db()
    try:
        p = _paper_or_404(conn, pid)
        stop = _draft_only(p, pid)
        if stop:
            return stop
        back = url_for('ex_paper', pid=pid)
        if action == 'add':
            qids = [int(x) for x in f.getlist('qid') if str(x).isdigit()]
            added, skipped = papers.add_questions(conn, p, qids, f.get('section') or None)
            conn.commit()
            msg = f'Added {added} question(s).'
            if skipped:
                msg += ' Skipped ' + ', '.join(f'#{q} ({why})' for q, why in skipped[:6]) + ('…' if len(skipped) > 6 else '')
            flash(msg, 'success' if added else 'error')
            back = request.form.get('back') or back
        elif action == 'remove':
            papers.remove_item(conn, p, int(f.get('item_id') or 0))
            conn.commit()
            flash('Question removed from the paper.', 'success')
        elif action in ('up', 'down') or (action or '').startswith('to:'):
            err = papers.move_item(conn, p, int(f.get('item_id') or 0), action)
            conn.commit()
            if err:
                flash(err, 'error')
        elif action == 'autofill':
            res = papers.autofill(conn, p, any_subject=bool(f.get('any_subject')))
            conn.commit()
            msg = f"Auto-fill added {res['added']} question(s)."
            if res['filled_from_any']:
                msg += f" {res['filled_from_any']} came from other subjects."
            if res['short']:
                msg += ' Not enough approved questions in: ' + ', '.join(
                    f'{k or "no subject"} (needed {w}, found {g})' for k, (w, g) in res['short'].items()) + '.'
            flash(msg, 'success' if res['added'] and not res['short'] else 'info')
        elif action == 'clear':
            papers.clear(conn, p)
            conn.commit()
            flash('All questions removed from this paper.', 'success')
        else:
            abort(400)
        return redirect(back)
    except Exception as e:
        logging.exception('exam paper edit')
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Could not change the paper: {e}', 'error')
        return redirect(url_for('ex_paper', pid=pid))
    finally:
        _close(conn)


@login_required
def paper_settings(pid):
    user = _admin()
    if not user:
        return _deny()
    f = request.form
    conn = get_db()
    try:
        p = _paper_or_404(conn, pid)
        title = (f.get('title') or '').strip()[:200] or p['title']
        desc = (f.get('description') or '').strip()[:1000]
        free = 1 if f.get('is_free_sample') else 0
        try:
            max_attempts = max(1, min(10, int(f.get('max_attempts') or p.get('max_attempts') or 1)))
        except ValueError:
            max_attempts = p.get('max_attempts') or 1
        try:
            sort_order = int(f.get('sort_order') or 0)
        except ValueError:
            sort_order = p.get('sort_order') or 0
        if free and p['kind'] != 'full':
            flash('The free sample must be a full mock.', 'error')
            return redirect(url_for('ex_paper', pid=pid))
        if free:
            conn.execute("UPDATE ex_papers SET is_free_sample=0 WHERE tenant_id=? AND exam_code=? AND id <> ?",
                         (p['tenant_id'], p['exam_code'], pid))
        conn.execute("UPDATE ex_papers SET title=?, description=?, is_free_sample=?, sort_order=?, max_attempts=?, "
                     "updated_at=CURRENT_TIMESTAMP WHERE id=?", (title, desc, free, sort_order, max_attempts, pid))
        conn.commit()
        flash('Saved.' + (' This is now the free sample mock.' if free and not p['is_free_sample'] else ''), 'success')
        return redirect(url_for('ex_paper', pid=pid))
    finally:
        _close(conn)


@login_required
def paper_status(pid):
    user = _admin()
    if not user:
        return _deny()
    action = request.form.get('action')
    conn = get_db()
    try:
        p = _paper_or_404(conn, pid)
        if action == 'lock':
            if p['status'] != 'draft':
                flash('This paper is already locked.', 'info')
                return redirect(url_for('ex_paper', pid=pid))
            problems = papers.lock(conn, p, _who(user))
            if problems:
                conn.rollback()
                flash('Can\'t lock yet: ' + ' '.join(problems), 'error')
                return redirect(url_for('ex_paper', pid=pid))
            msg = 'Locked. Every question is now frozen into this paper — later edits in the bank won\'t change it.'
        elif action == 'unlock':
            err = papers.unlock(conn, p, _who(user))
            if err:
                flash(err, 'error')
                return redirect(url_for('ex_paper', pid=pid))
            msg = 'Unlocked — it\'s a draft again, using the latest version of each question.'
        elif action == 'delete':
            if p['status'] != 'draft' or papers.attempts_count(conn, pid):
                flash('Only a draft paper that nobody has taken can be deleted.', 'error')
                return redirect(url_for('ex_paper', pid=pid))
            conn.execute("DELETE FROM ex_paper_items WHERE paper_id=?", (pid,))
            conn.execute("DELETE FROM ex_papers WHERE id=?", (pid,))
            conn.commit()
            flash(f'Paper “{p["title"]}” deleted. Its questions stay in the bank.', 'success')
            return redirect(url_for('ex_papers'))
        else:
            err = papers.set_status(conn, p, action, _who(user))
            if err:
                flash(err, 'error')
                return redirect(url_for('ex_paper', pid=pid))
            msg = {'publish': 'Published — it will be available to doctors once the exam screen goes live.',
                   'unpublish': 'Unpublished — back to locked.', 'retire': 'Retired — hidden from doctors.',
                   'restore': 'Restored to locked.'}.get(action, 'Done.')
        conn.commit()
        flash(msg, 'success')
        return redirect(url_for('ex_paper', pid=pid))
    finally:
        _close(conn)


@login_required
def paper_preview(pid):
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        p = _paper_or_404(conn, pid)
        rows = papers.items(conn, p)
        for r in rows:
            if r['images'] is None:
                r['images'] = store.images_for(conn, r['question_id'])
        return render_template('exam_engine/paper_preview.html', p=p, secs=papers.by_section(p, rows),
                               show_answers=request.args.get('answers', '1') == '1')
    finally:
        _close(conn)


# ── exam pattern settings ───────────────────────────────────────────────────────────────────────────

@login_required
def pattern_view():
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        cfg = store.pattern(conn, EXAM_CODE, TENANT_GOOCAMPUS_IN)
        hist = [dict(r) for r in conn.execute(
            "SELECT version, name, is_active, updated_by, updated_at, created_at FROM ex_exam_patterns "
            "WHERE tenant_id=? AND exam_code=? ORDER BY version DESC", (TENANT_GOOCAMPUS_IN, EXAM_CODE)).fetchall()]
        for h in hist:
            h['when'] = store.now_ist_str(h.get('updated_at') or h.get('created_at'))
        subj = store.subjects(conn, EXAM_CODE, TENANT_GOOCAMPUS_IN)
        return render_template('exam_engine/pattern.html', cfg=cfg, hist=hist, subjects=subj)
    finally:
        _close(conn)


@login_required
def pattern_save():
    """Saves a NEW pattern version (existing papers keep the pattern they were made with)."""
    user = _admin()
    if not user:
        return _deny()
    f = request.form

    def num(key, default, lo=0, hi=100000):
        try:
            v = int(float(f.get(key)))
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, v))

    conn = get_db()
    try:
        cfg = store.pattern(conn, EXAM_CODE, TENANT_GOOCAMPUS_IN)
        n_sec = num('n_sections', len(cfg.get('sections') or []) or 5, 1, 10)
        sections = []
        for i in range(n_sec):
            code = 'ABCDEFGHIJ'[i]
            sections.append({'code': code, 'name': f'Section {code}', 'questions': num(f'sec_q_{i}', 36, 1, 500),
                             'minutes': num(f'sec_m_{i}', 42, 1, 600)})
        new = dict(cfg)
        new['name'] = (f.get('name') or cfg.get('name') or 'NEET PG').strip()[:100]
        new['sections'] = sections
        new['total_questions'] = sum(s['questions'] for s in sections)
        new['total_minutes'] = sum(s['minutes'] for s in sections)
        new['marking'] = {'correct': num('mark_correct', 4, 0, 100), 'wrong': -num('mark_wrong', 1, 0, 100),
                          'unattempted': 0}
        new['max_marks'] = new['total_questions'] * new['marking']['correct']
        new['options_per_question'] = num('options', 4, 2, 6)
        new['section_lock'] = bool(f.get('section_lock'))
        new['section_runs_full_time'] = bool(f.get('section_runs_full_time'))
        new['shuffle_questions'] = bool(f.get('shuffle_questions'))
        new['shuffle_options'] = bool(f.get('shuffle_options'))
        new['subject_test'] = {'questions': num('st_q', 60, 1, 500), 'minutes': num('st_m', 70, 1, 600)}
        new['mini_test'] = {'questions': num('mt_q', 30, 1, 500), 'minutes': num('mt_m', 35, 1, 600)}
        bp = {}
        for s in store.subjects(conn, EXAM_CODE, TENANT_GOOCAMPUS_IN):
            v = num(f'bp_{s["id"]}', 0, 0, 500)
            if v:
                bp[s['name']] = v
        new['blueprint'] = bp
        new['source'] = (f.get('source') or cfg.get('source') or '').strip()[:300]
        if json.dumps(new, sort_keys=True) == json.dumps(cfg, sort_keys=True):
            flash('No changes to save.', 'info')
            return redirect(url_for('ex_pattern'))
        ver = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS v FROM ex_exam_patterns WHERE tenant_id=? "
                           "AND exam_code=?", (TENANT_GOOCAMPUS_IN, EXAM_CODE)).fetchone()['v']
        conn.execute("UPDATE ex_exam_patterns SET is_active=0 WHERE tenant_id=? AND exam_code=?",
                     (TENANT_GOOCAMPUS_IN, EXAM_CODE))
        conn.execute("INSERT INTO ex_exam_patterns (tenant_id, exam_code, version, name, config_json, is_active, "
                     "updated_by) VALUES (?, ?, ?, ?, ?, 1, ?)",
                     (TENANT_GOOCAMPUS_IN, EXAM_CODE, ver, new['name'], json.dumps(new), _who(user)))
        conn.commit()
        warn = '' if sum(bp.values()) == new['total_questions'] else \
            f' Note: the subject mix adds up to {sum(bp.values())}, not {new["total_questions"]} — auto-fill scales it.'
        flash(f'Saved as pattern version {ver}. New papers use it; existing papers keep theirs.' + warn, 'success')
        return redirect(url_for('ex_pattern'))
    finally:
        _close(conn)


def register_routes(app):
    r = app.add_url_rule
    r('/admin/pg/mocks/bank', 'ex_bank', bank, methods=['GET'])
    r('/admin/pg/mocks/q/new', 'ex_question_new', question_new, methods=['POST'])
    r('/admin/pg/mocks/papers', 'ex_papers', papers_list, methods=['GET'])
    r('/admin/pg/mocks/papers', 'ex_paper_create', paper_create, methods=['POST'])
    r('/admin/pg/mocks/papers/<int:pid>', 'ex_paper', paper_view, methods=['GET'])
    r('/admin/pg/mocks/papers/<int:pid>/edit', 'ex_paper_edit', paper_edit, methods=['POST'])
    r('/admin/pg/mocks/papers/<int:pid>/settings', 'ex_paper_settings', paper_settings, methods=['POST'])
    r('/admin/pg/mocks/papers/<int:pid>/status', 'ex_paper_status', paper_status, methods=['POST'])
    r('/admin/pg/mocks/papers/<int:pid>/preview', 'ex_paper_preview', paper_preview, methods=['GET'])
    r('/admin/pg/mocks/pattern', 'ex_pattern', pattern_view, methods=['GET'])
    r('/admin/pg/mocks/pattern', 'ex_pattern_save', pattern_save, methods=['POST'])
