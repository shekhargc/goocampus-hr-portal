"""Mock Tests › Question import — the team's screens in goocampus.org (admin only for now).

  /admin/pg/mocks/import                      upload a file + list of past imports + bank totals
  /admin/pg/mocks/import/<bid>                that file's check report + its questions
  /admin/pg/mocks/q/<qid>                     review one question (side by side with its PDF page),
                                              fix it, add/crop pictures, approve / reject
  /admin/pg/mocks/template.docx               the Word template the founder fills in
Nothing reaches doctors until a question is approved here.
"""
import hashlib
import io
import json
import logging

from flask import render_template, request, redirect, url_for, flash, jsonify, Response, abort

from db import get_db
from core.auth import login_required
from core.users import get_user
from core import storage
from exam_engine import store
from exam_engine.tables import TENANT_GOOCAMPUS_IN
from exam_engine.importer import file_kind, SUPPORTED
from exam_engine.importer.checks import FLAG_TEXT, FLAG_TITLE

MAX_UPLOAD_MB = 60
EXAM_CODE = 'neet_pg'
STATUS_LABEL = {'draft': 'To review', 'approved': 'Approved', 'rejected': 'Rejected'}


def _admin():
    u = get_user()
    return dict(u) if u and u.get('is_admin') else None


def _who(u):
    return (u.get('name') or u.get('full_name') or u.get('username') or u.get('email') or f"#{u.get('id')}")


def _deny():
    flash('Admin access required', 'error')
    return redirect(url_for('dashboard'))


def _close(conn):
    try:
        conn.close()
    except Exception:
        pass


# ── import list + upload ────────────────────────────────────────────────────────────────────────────

@login_required
def imports_list():
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        batches = [dict(r) for r in conn.execute(
            "SELECT b.id, b.kind, b.filename, b.status, b.error, b.total, b.with_errors, b.uploaded_by, b.created_at, "
            "b.note, COALESCE(SUM(CASE WHEN q.status='approved' THEN 1 ELSE 0 END), 0) AS approved, "
            "COALESCE(SUM(CASE WHEN q.status='rejected' THEN 1 ELSE 0 END), 0) AS rejected "
            "FROM ex_import_batches b LEFT JOIN ex_questions q ON q.batch_id = b.id "
            "WHERE b.tenant_id=? AND b.exam_code=? GROUP BY b.id ORDER BY b.id DESC LIMIT 200",
            (TENANT_GOOCAMPUS_IN, EXAM_CODE)).fetchall()]
        for b in batches:
            b['when'] = store.now_ist_str(b['created_at'])
        bank = [dict(r) for r in conn.execute(
            "SELECT s.name, s.sort_order, "
            "COALESCE(SUM(CASE WHEN q.status='approved' THEN 1 ELSE 0 END), 0) AS approved, "
            "COALESCE(SUM(CASE WHEN q.status='draft' THEN 1 ELSE 0 END), 0) AS draft "
            "FROM ex_subjects s LEFT JOIN ex_questions q ON q.subject_id = s.id "
            "WHERE s.tenant_id=? AND s.exam_code=? GROUP BY s.id, s.name, s.sort_order ORDER BY s.sort_order",
            (TENANT_GOOCAMPUS_IN, EXAM_CODE)).fetchall()]
        unset = conn.execute("SELECT COUNT(*) AS n FROM ex_questions WHERE tenant_id=? AND exam_code=? "
                             "AND subject_id IS NULL AND status <> 'rejected'", (TENANT_GOOCAMPUS_IN, EXAM_CODE)).fetchone()['n']
        totals = {'approved': sum(b['approved'] for b in bank), 'draft': sum(b['draft'] for b in bank) + unset}
        return render_template('exam_engine/imports.html', batches=batches, bank=bank, totals=totals,
                               max_mb=MAX_UPLOAD_MB, r2=storage.is_configured())
    finally:
        _close(conn)


@login_required
def import_upload():
    user = _admin()
    if not user:
        return _deny()
    f = request.files.get('file')
    if not f or not f.filename:
        flash('Choose a file to upload.', 'error')
        return redirect(url_for('ex_imports'))
    kind = file_kind(f.filename)
    if kind not in SUPPORTED:
        msg = {'doc': 'This is an old Word file (.doc). Open it in Word and "Save As" .docx, then upload again.',
               'xls': 'This is an old Excel file (.xls). "Save As" .xlsx, then upload again.'}.get(
            kind, 'Please upload a Word (.docx), PDF or Excel (.xlsx) file.')
        flash(msg, 'error')
        return redirect(url_for('ex_imports'))
    data = f.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        flash(f'The file is larger than {MAX_UPLOAD_MB} MB. Split it into sections and upload each.', 'error')
        return redirect(url_for('ex_imports'))
    sha1 = hashlib.sha1(data).hexdigest()
    conn = get_db()
    try:
        dup = conn.execute("SELECT id FROM ex_import_batches WHERE tenant_id=? AND exam_code=? AND file_sha1=? "
                           "AND status <> 'failed' ORDER BY id LIMIT 1", (TENANT_GOOCAMPUS_IN, EXAM_CODE, sha1)).fetchone()
        if dup:
            flash(f'This exact file was already uploaded (import #{dup["id"]}). Showing that import.', 'info')
            return redirect(url_for('ex_import_batch', bid=dup['id']))
        bid = conn.execute(
            "INSERT INTO ex_import_batches (tenant_id, exam_code, kind, filename, file_size, file_sha1, status, note, "
            "uploaded_by) VALUES (?, ?, ?, ?, ?, ?, 'parsing', ?, ?) RETURNING id",
            (TENANT_GOOCAMPUS_IN, EXAM_CODE, kind, f.filename[:250], len(data), sha1,
             (request.form.get('note') or '').strip()[:500], _who(user))).fetchone()['id']
        key = store.file_key_for_batch(TENANT_GOOCAMPUS_IN, bid, f.filename)
        if storage.is_configured() and storage.upload_bytes(key, data, f.mimetype or 'application/octet-stream'):
            conn.execute("UPDATE ex_import_batches SET file_key=? WHERE id=?", (key, bid))
        else:
            conn.execute("UPDATE ex_import_batches SET file_data=? WHERE id=?", (data, bid))
        conn.commit()
    except Exception as e:
        logging.exception('exam import upload')
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Upload failed: {e}', 'error')
        return redirect(url_for('ex_imports'))
    finally:
        _close(conn)
    store.start_processing(bid)
    return redirect(url_for('ex_import_batch', bid=bid))


# ── one import: report + questions ──────────────────────────────────────────────────────────────────

def _batch_or_404(conn, bid):
    b = conn.execute("SELECT id, tenant_id, exam_code, kind, filename, file_key, status, error, total, with_errors, "
                     "summary_json, notes_json, info_json, note, uploaded_by, created_at, parsed_at "
                     "FROM ex_import_batches WHERE id=?", (bid,)).fetchone()
    if not b:
        abort(404)
    return dict(b)


@login_required
def import_batch(bid):
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        b = _batch_or_404(conn, bid)
        b['summary'] = json.loads(b.get('summary_json') or '{}')
        b['notes'] = json.loads(b.get('notes_json') or '[]')
        b['info'] = json.loads(b.get('info_json') or '{}')
        b['when'] = store.now_ist_str(b['created_at'])
        f = (request.args.get('f') or 'all').strip()
        subj = {s['id']: s['name'] for s in store.subjects(conn, b['exam_code'], b['tenant_id'])}
        rows = [dict(r) for r in conn.execute(
            "SELECT q.id, q.source_no, q.stem, q.subject_id, q.topic, q.status, q.n_errors, q.flags_json, q.answer, "
            "q.page_from, (SELECT COUNT(*) FROM ex_question_images i WHERE i.question_id = q.id) AS n_images "
            "FROM ex_questions q WHERE q.batch_id=? ORDER BY q.source_no NULLS LAST, q.id", (bid,)).fetchall()]
        counts = {'all': len(rows), 'errors': 0, 'ready': 0, 'approved': 0, 'rejected': 0}
        for r in rows:
            r['flags'] = json.loads(r.get('flags_json') or '[]')
            r['subject'] = subj.get(r['subject_id'], '')
            if r['status'] == 'approved':
                counts['approved'] += 1
            elif r['status'] == 'rejected':
                counts['rejected'] += 1
            elif r['n_errors']:
                counts['errors'] += 1
            else:
                counts['ready'] += 1

        def keep(r):
            if f == 'errors':
                return r['status'] == 'draft' and r['n_errors'] > 0
            if f == 'ready':
                return r['status'] == 'draft' and r['n_errors'] == 0
            if f in ('approved', 'rejected'):
                return r['status'] == f
            if f.startswith('flag:'):
                return any(x['code'] == f[5:] for x in r['flags'])
            return True
        shown = [r for r in rows if keep(r)]
        # subjects as they stand now (the team may have changed some since the file was read)
        live = {}
        for r in rows:
            if r['status'] != 'rejected':
                k = r['subject'] or 'Not set'
                live[k] = live.get(k, 0) + 1
        b['summary']['subjects'] = dict(sorted(live.items(), key=lambda kv: -kv[1]))
        sev = {k: v[0] for k, v in FLAG_TEXT.items()}
        sev['image_format'] = 'error'
        order = {'error': 0, 'warn': 1, 'info': 2}
        flag_rows = sorted(((code, sev.get(code, 'warn'), FLAG_TITLE.get(code, code), n)
                            for code, n in (b['summary'].get('flag_counts') or {}).items()),
                           key=lambda r: (order.get(r[1], 3), -r[3]))
        can_bulk = b['kind'] != 'pdf'
        locked = counts['approved'] + counts['rejected'] > 0
        return render_template('exam_engine/batch.html', b=b, rows=shown, counts=counts, f=f,
                               flag_rows=flag_rows, can_bulk=can_bulk, locked=locked, status_label=STATUS_LABEL)
    finally:
        _close(conn)


@login_required
def import_batch_status(bid):
    if not _admin():
        return jsonify({'error': 'admin only'}), 403
    conn = get_db()
    try:
        b = _batch_or_404(conn, bid)
        return jsonify({'status': b['status'], 'error': b['error'], 'total': b['total']})
    finally:
        _close(conn)


@login_required
def import_approve_clean(bid):
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        b = _batch_or_404(conn, bid)
        if b['kind'] == 'pdf':
            flash('PDF imports must be checked question by question against the page — bulk approve is off.', 'error')
            return redirect(url_for('ex_import_batch', bid=bid))
        ids = [r['id'] for r in conn.execute("SELECT id FROM ex_questions WHERE batch_id=? AND status='draft' "
                                             "AND n_errors=0", (bid,)).fetchall()]
        for qid in ids:
            conn.execute("UPDATE ex_questions SET status='approved', approved_by=?, approved_at=CURRENT_TIMESTAMP, "
                         "updated_at=CURRENT_TIMESTAMP WHERE id=?", (_who(user), qid))
        conn.commit()
        flash(f'Approved {len(ids)} question(s) with no problems.', 'success')
        return redirect(url_for('ex_import_batch', bid=bid))
    finally:
        _close(conn)


@login_required
def import_reparse(bid):
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        _batch_or_404(conn, bid)
        done = conn.execute("SELECT COUNT(*) AS n FROM ex_questions WHERE batch_id=? AND status <> 'draft'",
                            (bid,)).fetchone()['n']
        if done:
            flash('Some questions in this import are already approved or rejected, so it can\'t be re-read. '
                  'Upload a corrected file as a new import instead.', 'error')
            return redirect(url_for('ex_import_batch', bid=bid))
        conn.execute("UPDATE ex_import_batches SET status='parsing', error='' WHERE id=?", (bid,))
        conn.commit()
    finally:
        _close(conn)
    store.start_processing(bid)
    flash('Reading the file again…', 'info')
    return redirect(url_for('ex_import_batch', bid=bid))


@login_required
def import_discard(bid):
    """Removes an import that has nothing approved/rejected yet (e.g. the wrong file was uploaded)."""
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        b = _batch_or_404(conn, bid)
        done = conn.execute("SELECT COUNT(*) AS n FROM ex_questions WHERE batch_id=? AND status <> 'draft'",
                            (bid,)).fetchone()['n']
        if done:
            flash('This import has approved or rejected questions, so it can\'t be discarded.', 'error')
            return redirect(url_for('ex_import_batch', bid=bid))
        keys = [r['file_key'] for r in conn.execute(
            "SELECT i.file_key FROM ex_question_images i JOIN ex_questions q ON q.id = i.question_id "
            "WHERE q.batch_id=? AND i.file_key <> ''", (bid,)).fetchall()]
        conn.execute("DELETE FROM ex_question_images WHERE question_id IN (SELECT id FROM ex_questions WHERE batch_id=?)", (bid,))
        conn.execute("DELETE FROM ex_questions WHERE batch_id=?", (bid,))
        conn.execute("DELETE FROM ex_import_batches WHERE id=?", (bid,))
        conn.commit()
        for k in keys + ([b['file_key']] if b.get('file_key') else []):
            try:
                storage.delete_object(k)
            except Exception:
                pass
        flash(f'Import #{bid} ({b["filename"]}) was discarded.', 'success')
        return redirect(url_for('ex_imports'))
    finally:
        _close(conn)


@login_required
def import_page_png(bid, page):
    """A PDF page as a picture, for the side-by-side check (cached in R2 after the first view)."""
    if not _admin():
        abort(403)
    conn = get_db()
    try:
        b = _batch_or_404(conn, bid)
        if b['kind'] != 'pdf':
            abort(404)
        key = f'exam_engine/t{b["tenant_id"]}/imports/{bid}/pages/{int(page)}.png'
        if storage.is_configured() and storage.object_size(key):
            url = storage.presigned_get_url(key)
            if url:
                return redirect(url)
        data = store.load_batch_file(conn, b)
    finally:
        _close(conn)
    if not data:
        abort(404)
    from exam_engine.importer.pdf_reader import render_page_png
    png = render_page_png(data, int(page))
    if not png:
        abort(404)
    if storage.is_configured():
        storage.upload_bytes(key, png, 'image/png')
    return Response(png, mimetype='image/png', headers={'Cache-Control': 'private, max-age=3600'})


# ── one question ────────────────────────────────────────────────────────────────────────────────────

def _neighbours(conn, q):
    rows = conn.execute("SELECT id, status, n_errors FROM ex_questions WHERE batch_id=? "
                        "ORDER BY source_no NULLS LAST, id", (q['batch_id'],)).fetchall()
    ids = [r['id'] for r in rows]
    i = ids.index(q['id']) if q['id'] in ids else -1
    prev_id = ids[i - 1] if i > 0 else None
    next_id = ids[i + 1] if 0 <= i < len(ids) - 1 else None
    next_todo = None
    for r in rows[i + 1:] + rows[:max(i, 0)]:
        if r['status'] == 'draft' and r['id'] != q['id']:
            next_todo = r['id']
            break
    return prev_id, next_id, next_todo, i + 1, len(ids)


@login_required
def question_view(qid):
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        q = store.load_question(conn, qid)
        if not q:
            abort(404)
        b = _batch_or_404(conn, q['batch_id']) if q.get('batch_id') else None
        subj = store.subjects(conn, q['exam_code'], q['tenant_id'])
        imgs = store.images_for(conn, qid)
        prev_id, next_id, next_todo, pos, total = _neighbours(conn, q) if b else (None, None, None, 1, 1)
        versions = [dict(r) for r in conn.execute(
            "SELECT version, changed_by, changed_at, note FROM ex_question_versions WHERE question_id=? "
            "ORDER BY id DESC LIMIT 20", (qid,)).fetchall()]
        for v in versions:
            v['when'] = store.now_ist_str(v['changed_at'])
        pages = []
        if b and b['kind'] == 'pdf' and q.get('page_from'):
            pages = list(range(int(q['page_from']), int(q.get('page_to') or q['page_from']) + 1))[:4]
        subject_flag = any(f['code'] in ('subject_unmapped', 'subject_guessed') for f in q['flags'])
        from exam_engine import papers as _papers
        used_in = _papers.usage(conn, [qid]).get(qid, [])
        return render_template('exam_engine/question.html', q=q, b=b, subjects=subj, imgs=imgs,
                               prev_id=prev_id, next_id=next_id, next_todo=next_todo, pos=pos, total=total,
                               versions=versions, pages=pages, subject_flag=subject_flag, used_in=used_in,
                               status_label=STATUS_LABEL,
                               subject_name={s['id']: s['name'] for s in subj}.get(q.get('subject_id'), ''))
    finally:
        _close(conn)


@login_required
def question_save(qid):
    user = _admin()
    if not user:
        return _deny()
    who = _who(user)
    conn = get_db()
    try:
        q = store.load_question(conn, qid)
        if not q:
            abort(404)
        form = request.form
        letters = [L for L, _ in q['options']] or list('ABCD')
        for L in 'ABCD':
            if L not in letters and (form.get('opt_' + L) or '').strip():
                letters.append(L)
        letters = sorted(set(letters))
        options = [(L, (form.get('opt_' + L) or '').strip()) for L in letters if ('opt_' + L) in form]
        options = [(L, t) for L, t in options if t] if len([1 for _, t in options if t]) >= 2 else options
        sections = []
        i = 0
        while f'sec_label_{i}' in form:
            label = (form.get(f'sec_label_{i}') or '').strip() or 'Explanation'
            text = (form.get(f'sec_text_{i}') or '').strip()
            if text:
                sections.append((label, text))
            i += 1
        new_text = (form.get('sec_text_new') or '').strip()
        if new_text:
            sections.append(((form.get('sec_label_new') or '').strip() or 'Explanation', new_text))
        try:
            subject_id = int(form.get('subject_id') or 0) or None
        except ValueError:
            subject_id = None
        answer = (form.get('answer') or '').strip().upper()[:1]
        new = {'stem': (form.get('stem') or '').strip(), 'image_desc': (form.get('image_desc') or '').strip(),
               'options_json': json.dumps(options), 'answer': answer, 'sections_json': json.dumps(sections),
               'subject_id': subject_id, 'topic': (form.get('topic') or '').strip()[:200]}
        changed = any(str(q.get(k) or '') != str(v or '') for k, v in new.items())
        if not changed:
            flash('No changes to save.', 'info')
            return redirect(url_for('ex_question', qid=qid))
        store.snapshot(conn, q, who, 'edited')
        back_to_draft = q['status'] == 'approved'
        conn.execute("UPDATE ex_questions SET stem=?, image_desc=?, options_json=?, answer=?, sections_json=?, "
                     "subject_id=?, topic=?, version=version+1, updated_by=?, updated_at=CURRENT_TIMESTAMP"
                     + (", status='draft', approved_by='', approved_at=NULL" if back_to_draft else "") +
                     " WHERE id=?",
                     (new['stem'], new['image_desc'], new['options_json'], new['answer'], new['sections_json'],
                      new['subject_id'], new['topic'], who, qid))
        store.recheck(conn, qid)
        extra = ''
        if subject_id and subject_id != q.get('subject_id') and form.get('remember_alias') and q.get('lead_tag'):
            if store.remember_alias(conn, q, subject_id, who):
                n = store.apply_alias_to_batch(conn, q['batch_id'], q['lead_tag'], subject_id, who) if q.get('batch_id') else 0
                extra = f' “{q["lead_tag"]}” will be filed under this subject from now on' + \
                        (f' ({n} more question(s) in this file updated).' if n else '.')
        conn.commit()
        flash('Saved.' + (' It was approved before, so it needs approving again.' if back_to_draft else '') + extra,
              'success')
        return redirect(url_for('ex_question', qid=qid))
    except Exception as e:
        logging.exception('exam question save')
        try:
            conn.rollback()
        except Exception:
            pass
        flash(f'Could not save: {e}', 'error')
        return redirect(url_for('ex_question', qid=qid))
    finally:
        _close(conn)


@login_required
def question_status(qid):
    user = _admin()
    if not user:
        return _deny()
    action = request.form.get('action')
    conn = get_db()
    try:
        q = store.load_question(conn, qid)
        if not q:
            abort(404)
        b = _batch_or_404(conn, q['batch_id']) if q.get('batch_id') else None
        go_next = None
        if action == 'approve':
            flags = store.recheck(conn, qid)
            if any(f['severity'] == 'error' for f in flags):
                conn.commit()
                flash('This question still has problems (in red) — fix them before approving.', 'error')
                return redirect(url_for('ex_question', qid=qid))
            if b and b['kind'] == 'pdf' and not request.form.get('checked_page'):
                flash('Tick “I checked it against the PDF page” before approving.', 'error')
                return redirect(url_for('ex_question', qid=qid))
            conn.execute("UPDATE ex_questions SET status='approved', reject_reason='', approved_by=?, "
                         "approved_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?", (_who(user), qid))
            msg = 'Approved.'
        elif action == 'reject':
            reason = (request.form.get('reason') or '').strip()[:500]
            conn.execute("UPDATE ex_questions SET status='rejected', reject_reason=?, approved_by='', approved_at=NULL, "
                         "updated_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (reason, _who(user), qid))
            msg = 'Rejected — it won\'t be used in any mock.'
        elif action == 'reopen':
            conn.execute("UPDATE ex_questions SET status='draft', approved_by='', approved_at=NULL, "
                         "updated_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (_who(user), qid))
            store.recheck(conn, qid)
            msg = 'Back to “to review”.'
        else:
            abort(400)
        conn.commit()
        if action in ('approve', 'reject') and b:
            _, _, go_next, _, _ = _neighbours(conn, q)
        flash(msg, 'success')
        return redirect(url_for('ex_question', qid=go_next) if go_next else url_for('ex_question', qid=qid))
    finally:
        _close(conn)


@login_required
def question_image_upload(qid):
    user = _admin()
    if not user:
        return _deny()
    f = request.files.get('image')
    role = 'explanation' if request.form.get('role') == 'explanation' else 'stem'
    if not f or not f.filename:
        flash('Choose a picture to upload.', 'error')
        return redirect(url_for('ex_question', qid=qid))
    data = f.read()
    if len(data) > 15 * 1024 * 1024:
        flash('That picture is over 15 MB — please use a smaller one.', 'error')
        return redirect(url_for('ex_question', qid=qid))
    ext = (f.filename.rsplit('.', 1)[-1] if '.' in f.filename else 'png').lower()
    conn = get_db()
    try:
        if not store.load_question(conn, qid):
            abort(404)
        _, problem = store.save_image(conn, qid, data, ext, role, 'upload', 0, _who(user))
        store.recheck(conn, qid)
        conn.commit()
        flash(problem or 'Picture added.', 'error' if problem else 'success')
        return redirect(url_for('ex_question', qid=qid))
    finally:
        _close(conn)


@login_required
def question_crop(qid):
    """Cut a picture / diagram out of the PDF page shown next to the question."""
    user = _admin()
    if not user:
        return jsonify({'ok': False, 'error': 'admin only'}), 403
    try:
        page = int(request.form.get('page') or 0)
        box = [float(request.form.get(k)) for k in ('x0', 'y0', 'x1', 'y1')]
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Select an area on the page first.'}), 400
    role = 'explanation' if request.form.get('role') == 'explanation' else 'stem'
    conn = get_db()
    try:
        q = store.load_question(conn, qid)
        if not q or not q.get('batch_id'):
            abort(404)
        b = _batch_or_404(conn, q['batch_id'])
        if b['kind'] != 'pdf':
            return jsonify({'ok': False, 'error': 'Cropping works only for PDF imports.'}), 400
        data = store.load_batch_file(conn, b)
        from exam_engine.importer.pdf_reader import crop_region
        png = crop_region(data, page, box) if data else None
        if not png:
            return jsonify({'ok': False, 'error': 'That area is too small — drag a bigger box.'}), 400
        iid, problem = store.save_image(conn, qid, png, 'png', role, 'crop', page, _who(user))
        store.recheck(conn, qid)
        conn.commit()
        return jsonify({'ok': True, 'image_id': iid})
    finally:
        _close(conn)


@login_required
def image_delete(iid):
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        r = conn.execute("SELECT question_id FROM ex_question_images WHERE id=?", (iid,)).fetchone()
        if not r:
            abort(404)
        from exam_engine import papers as _papers
        if _papers.image_in_frozen_paper(conn, iid, r['question_id']):
            flash('This picture is shown in a locked or published paper, so it can\'t be removed. '
                  'Unlock that paper first, or add a new picture instead.', 'error')
            return redirect(url_for('ex_question', qid=r['question_id']))
        qid = store.delete_image(conn, iid)
        if not qid:
            abort(404)
        store.recheck(conn, qid)
        conn.commit()
        flash('Picture removed.', 'success')
        return redirect(url_for('ex_question', qid=qid))
    finally:
        _close(conn)


@login_required
def image_serve(iid):
    if not _admin():
        abort(403)
    conn = get_db()
    try:
        r = conn.execute("SELECT file_key, data, content_type FROM ex_question_images WHERE id=?", (iid,)).fetchone()
        if not r:
            abort(404)
        if r['file_key']:
            url = storage.presigned_get_url(r['file_key'])
            if url:
                return redirect(url)
        if r['data'] is not None:
            return Response(bytes(r['data']), mimetype=r['content_type'] or 'image/png',
                            headers={'Cache-Control': 'private, max-age=3600'})
        abort(404)
    finally:
        _close(conn)


@login_required
def word_template():
    """The fixed Word template: instructions + two worked examples (one with a picture)."""
    if not _admin():
        return _deny()
    from exam_engine.template_docx import build_template
    return Response(build_template(), mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    headers={'Content-Disposition': 'attachment; filename="GooCampus_NEET_PG_question_template.docx"'})


def register_routes(app):
    r = app.add_url_rule
    r('/admin/pg/mocks/import', 'ex_imports', imports_list, methods=['GET'])
    r('/admin/pg/mocks/import', 'ex_import_upload', import_upload, methods=['POST'])
    r('/admin/pg/mocks/import/<int:bid>', 'ex_import_batch', import_batch, methods=['GET'])
    r('/admin/pg/mocks/import/<int:bid>/status', 'ex_import_batch_status', import_batch_status, methods=['GET'])
    r('/admin/pg/mocks/import/<int:bid>/approve-clean', 'ex_import_approve_clean', import_approve_clean, methods=['POST'])
    r('/admin/pg/mocks/import/<int:bid>/reparse', 'ex_import_reparse', import_reparse, methods=['POST'])
    r('/admin/pg/mocks/import/<int:bid>/discard', 'ex_import_discard', import_discard, methods=['POST'])
    r('/admin/pg/mocks/import/<int:bid>/page/<int:page>.png', 'ex_import_page', import_page_png, methods=['GET'])
    r('/admin/pg/mocks/q/<int:qid>', 'ex_question', question_view, methods=['GET'])
    r('/admin/pg/mocks/q/<int:qid>/save', 'ex_question_save', question_save, methods=['POST'])
    r('/admin/pg/mocks/q/<int:qid>/status', 'ex_question_status', question_status, methods=['POST'])
    r('/admin/pg/mocks/q/<int:qid>/image', 'ex_question_image', question_image_upload, methods=['POST'])
    r('/admin/pg/mocks/q/<int:qid>/crop', 'ex_question_crop', question_crop, methods=['POST'])
    r('/admin/pg/mocks/img/<int:iid>', 'ex_image', image_serve, methods=['GET'])
    r('/admin/pg/mocks/img/<int:iid>/delete', 'ex_image_delete', image_delete, methods=['POST'])
    r('/admin/pg/mocks/template.docx', 'ex_word_template', word_template, methods=['GET'])
