"""Saving imports into the question bank, images in R2, re-checks after edits, version history."""
import io
import json
import logging
import re
import threading

from db import get_db
from core import storage
from exam_engine.tables import TENANT_GOOCAMPUS_IN
from exam_engine.subjects import norm_tag
from exam_engine.importer import parse_file, ImportProblem
from exam_engine.importer import checks

MAX_IMG_SIDE = 1600          # px — bigger pictures are scaled down (keeps the exam screen light)
WEB_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


# ── lookups ─────────────────────────────────────────────────────────────────────────────────────────

def subjects(conn, exam_code='neet_pg', tenant_id=TENANT_GOOCAMPUS_IN):
    return [dict(r) for r in conn.execute(
        "SELECT id, name FROM ex_subjects WHERE tenant_id=? AND exam_code=? AND is_active=1 ORDER BY sort_order, id",
        (tenant_id, exam_code)).fetchall()]


def alias_map(conn, exam_code='neet_pg', tenant_id=TENANT_GOOCAMPUS_IN):
    rows = conn.execute(
        "SELECT a.alias_key, s.name FROM ex_subject_aliases a JOIN ex_subjects s ON s.id = a.subject_id "
        "WHERE a.tenant_id=? AND a.exam_code=?", (tenant_id, exam_code)).fetchall()
    return {r['alias_key']: r['name'] for r in rows}


def pattern(conn, exam_code='neet_pg', tenant_id=TENANT_GOOCAMPUS_IN):
    r = conn.execute("SELECT config_json FROM ex_exam_patterns WHERE tenant_id=? AND exam_code=? AND is_active=1 "
                     "ORDER BY version DESC LIMIT 1", (tenant_id, exam_code)).fetchone()
    try:
        return json.loads(r['config_json']) if r else {}
    except Exception:
        return {}


def bank_fingerprints(conn, exam_code, tenant_id, exclude_batch=None, exclude_qid=None):
    sql = ("SELECT id, fingerprint FROM ex_questions WHERE tenant_id=? AND exam_code=? AND status <> 'rejected' "
           "AND fingerprint <> ''")
    params = [tenant_id, exam_code]
    if exclude_batch is not None:
        sql += " AND (batch_id IS NULL OR batch_id <> ?)"
        params.append(exclude_batch)
    if exclude_qid is not None:
        sql += " AND id <> ?"
        params.append(exclude_qid)
    out = {}
    for r in conn.execute(sql + " ORDER BY id", tuple(params)).fetchall():
        out.setdefault(r['fingerprint'], r['id'])
    return out


# ── files ───────────────────────────────────────────────────────────────────────────────────────────

def _safe(name):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', name or 'file')[:120]


def file_key_for_batch(tenant_id, batch_id, filename):
    return f'exam_engine/t{tenant_id}/imports/{batch_id}/{_safe(filename)}'


def load_batch_file(conn, batch):
    """The original uploaded bytes (R2, or the row when R2 is off)."""
    if batch.get('file_key'):
        data = storage.download_bytes(batch['file_key'])
        if data:
            return data
    r = conn.execute("SELECT file_data FROM ex_import_batches WHERE id=?", (batch['id'],)).fetchone()
    if r and r['file_data'] is not None:
        return bytes(r['file_data'])
    return None


def prepare_image(data, ext):
    """→ (bytes, ext, content_type, width, height, problem). Scales big pictures down; converts
    BMP/TIFF to PNG; EMF/WMF (Word clip-art formats) can't be shown in a browser → problem."""
    ext = (ext or '').lower().replace('jpeg', 'jpg')
    if ext in ('emf', 'wmf', 'svg'):
        return data, ext, 'image/' + ext, None, None, f'The picture is in {ext.upper()} format, which browsers ' \
                                                      'can\'t show — paste it as a PNG/JPG picture instead.'
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.load()
        w, h = im.size
        needs_convert = ext not in WEB_EXT
        if max(w, h) > MAX_IMG_SIDE or needs_convert:
            if max(w, h) > MAX_IMG_SIDE:
                im.thumbnail((MAX_IMG_SIDE, MAX_IMG_SIDE))
            buf = io.BytesIO()
            if ext == 'jpg' and im.mode in ('RGB', 'L'):
                im.save(buf, 'JPEG', quality=88, optimize=True)
                out_ext = 'jpg'
            else:
                if im.mode not in ('RGB', 'RGBA', 'L', 'P'):
                    im = im.convert('RGBA')
                im.save(buf, 'PNG', optimize=True)
                out_ext = 'png'
            data, ext = buf.getvalue(), out_ext
            w, h = im.size
        ctype = {'jpg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp'}.get(ext, 'image/png')
        return data, ext, ctype, w, h, None
    except Exception as e:
        return data, ext, 'application/octet-stream', None, None, f'The picture could not be opened ({e.__class__.__name__}).'


def save_image(conn, question_id, data, ext, role='stem', source='upload', page=0, user='',
               tenant_id=TENANT_GOOCAMPUS_IN):
    """Stores one picture for a question; returns (image_id, problem)."""
    data, ext, ctype, w, h, problem = prepare_image(data, ext)
    nxt = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM ex_question_images WHERE question_id=? "
                       "AND role=?", (question_id, role)).fetchone()['n']
    r = conn.execute("INSERT INTO ex_question_images (tenant_id, question_id, role, sort_order, content_type, ext, "
                     "width, height, source, page, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                     (tenant_id, question_id, role, nxt, ctype, ext, w, h, source, page or 0, user)).fetchone()
    iid = r['id']
    key = f'exam_engine/t{tenant_id}/q/{question_id}/{iid}.{ext}'
    if storage.is_configured() and storage.upload_bytes(key, data, ctype):
        conn.execute("UPDATE ex_question_images SET file_key=? WHERE id=?", (key, iid))
    else:
        conn.execute("UPDATE ex_question_images SET data=? WHERE id=?", (bytes(data), iid))
    return iid, problem


def delete_image(conn, image_id):
    r = conn.execute("SELECT id, question_id, file_key FROM ex_question_images WHERE id=?", (image_id,)).fetchone()
    if not r:
        return None
    conn.execute("DELETE FROM ex_question_images WHERE id=?", (image_id,))
    if r['file_key']:
        try:
            storage.delete_object(r['file_key'])
        except Exception:
            pass
    return r['question_id']


def images_for(conn, question_id):
    return [dict(r) for r in conn.execute(
        "SELECT id, role, sort_order, ext, width, height, source, page FROM ex_question_images "
        "WHERE question_id=? ORDER BY role DESC, sort_order, id", (question_id,)).fetchall()]


# ── importing a file ────────────────────────────────────────────────────────────────────────────────

def start_processing(batch_id):
    """Parse in the background so the upload returns at once (a 180-question PDF takes a few seconds)."""
    t = threading.Thread(target=process_batch, args=(batch_id,), name=f'ex-import-{batch_id}', daemon=True)
    t.start()
    return t


def process_batch(batch_id):
    conn = get_db()
    try:
        b = conn.execute("SELECT * FROM ex_import_batches WHERE id=?", (batch_id,)).fetchone()
        if not b:
            return
        b = dict(b)
        tenant_id, exam_code = b['tenant_id'], b['exam_code']
        data = load_batch_file(conn, b)
        if not data:
            raise ImportProblem('The uploaded file could not be found in storage — please upload it again.')
        cfg = pattern(conn, exam_code, tenant_id)
        n_opt = int(cfg.get('options_per_question') or 4)
        parsed = parse_file(b['filename'], data, n_options=n_opt)
        subj_rows = subjects(conn, exam_code, tenant_id)
        subj_id = {s['name']: s['id'] for s in subj_rows}
        qs = parsed['questions']
        summary = checks.check_batch(qs, alias_map(conn, exam_code, tenant_id), [s['name'] for s in subj_rows],
                                     bank_fingerprints(conn, exam_code, tenant_id, exclude_batch=batch_id), n_opt)

        # a re-run replaces this batch's drafts (never touches approved questions)
        conn.execute("DELETE FROM ex_question_images WHERE question_id IN (SELECT id FROM ex_questions "
                     "WHERE batch_id=? AND status='draft')", (batch_id,))
        conn.execute("DELETE FROM ex_questions WHERE batch_id=? AND status='draft'", (batch_id,))
        image_problems = 0
        for q in qs:
            flags = list(q['flags'])
            row = conn.execute(
                "INSERT INTO ex_questions (tenant_id, exam_code, batch_id, source_no, source_ref, page_from, page_to, "
                "stem, image_desc, options_json, answer, sections_json, subject_id, topic, tags_raw, lead_tag, "
                "flags_json, n_errors, fingerprint, updated_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (tenant_id, exam_code, batch_id, q.get('no'), q.get('source_ref', ''),
                 (q.get('pages') or [0, 0])[0], (q.get('pages') or [0, 0])[1],
                 q.get('stem') or '', q.get('image_desc') or '', json.dumps(q.get('options') or []),
                 q.get('answer') or '', json.dumps(q.get('sections') or []), subj_id.get(q.get('subject')),
                 q.get('topic') or '', ' / '.join(q.get('tags') or ([q['subject_raw']] if q.get('subject_raw') else [])),
                 q.get('lead_tag') or '', json.dumps(flags), 0, q.get('fingerprint') or '', b.get('uploaded_by') or '')
            ).fetchone()
            qid = row['id']
            for img in q.get('images') or []:
                _, problem = save_image(conn, qid, img['data'], img.get('ext'), img.get('role', 'stem'),
                                        img.get('source', b['kind']), img.get('page') or 0, b.get('uploaded_by') or '',
                                        tenant_id)
                if problem:
                    flags.append({'code': 'image_format', 'severity': 'error', 'message': problem})
                    image_problems += 1
            n_err = sum(1 for f in flags if f['severity'] == 'error')
            conn.execute("UPDATE ex_questions SET flags_json=?, n_errors=? WHERE id=?", (json.dumps(flags), n_err, qid))
        if image_problems:
            summary['flag_counts']['image_format'] = image_problems
        n_err_total = conn.execute("SELECT COUNT(*) AS n FROM ex_questions WHERE batch_id=? AND n_errors > 0",
                                   (batch_id,)).fetchone()['n']
        summary['with_errors'] = n_err_total
        summary['ready'] = summary['total'] - n_err_total
        info = {k: v for k, v in (parsed.get('info') or {}).items() if isinstance(v, (int, float, str, bool))}
        conn.execute("UPDATE ex_import_batches SET status='ready', error='', total=?, with_errors=?, summary_json=?, "
                     "notes_json=?, info_json=?, parsed_at=CURRENT_TIMESTAMP WHERE id=?",
                     (len(qs), n_err_total, json.dumps(summary), json.dumps(parsed.get('notes') or []),
                      json.dumps(info), batch_id))
        conn.commit()
    except ImportProblem as e:
        _fail(conn, batch_id, str(e))
    except Exception as e:
        logging.exception(f'exam import {batch_id}')
        _fail(conn, batch_id, f'Something went wrong while reading the file ({e.__class__.__name__}: {e}).')
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _fail(conn, batch_id, message):
    try:
        conn.rollback()
        conn.execute("UPDATE ex_import_batches SET status='failed', error=? WHERE id=?", (message[:2000], batch_id))
        conn.commit()
    except Exception:
        logging.exception('exam import: could not record failure')


# ── one question: re-check, history ─────────────────────────────────────────────────────────────────

def load_question(conn, qid):
    r = conn.execute("SELECT * FROM ex_questions WHERE id=?", (qid,)).fetchone()
    if not r:
        return None
    q = dict(r)
    q['options'] = [tuple(o) for o in json.loads(q.get('options_json') or '[]')]
    q['sections'] = [tuple(s) for s in json.loads(q.get('sections_json') or '[]')]
    q['flags'] = json.loads(q.get('flags_json') or '[]')
    return q


def recheck(conn, qid):
    """Re-runs the checks on a question after the team edits it; returns the new flags."""
    q = load_question(conn, qid)
    if not q:
        return []
    imgs = images_for(conn, qid)
    cq = {'stem': q['stem'], 'options': q['options'], 'answer': q['answer'], 'ticks': [],
          'sections': q['sections'], 'image_desc': q['image_desc'],
          'images': [{'role': i['role']} for i in imgs], 'cleaned': []}
    flags = checks.check_question(cq)
    if not q.get('subject_id'):
        flags.append(checks.flag('subject_unmapped', raw='“%s”' % (q.get('lead_tag') or 'none given')))
    fp = checks.fingerprint(q['stem'], [t for _, t in q['options']])
    if q['stem'].strip():
        bank = bank_fingerprints(conn, q['exam_code'], q['tenant_id'], exclude_qid=qid)
        if fp in bank:
            other = conn.execute("SELECT batch_id, source_no FROM ex_questions WHERE id=?", (bank[fp],)).fetchone()
            if other and other['batch_id'] == q['batch_id'] and other['source_no'] is not None:
                flags.append(checks.flag('dup_in_file', other=other['source_no']))
            else:
                flags.append(checks.flag('dup_in_bank', other=bank[fp]))
    for i in imgs:
        if i['ext'] in ('emf', 'wmf', 'svg'):
            flags.append({'code': 'image_format', 'severity': 'error',
                          'message': f'A picture is in {i["ext"].upper()} format, which browsers can\'t show — replace it with a PNG/JPG.'})
    n_err = sum(1 for f in flags if f['severity'] == 'error')
    conn.execute("UPDATE ex_questions SET flags_json=?, n_errors=?, fingerprint=? WHERE id=?",
                 (json.dumps(flags), n_err, fp, qid))
    return flags


SNAP_FIELDS = ('stem', 'image_desc', 'options_json', 'answer', 'sections_json', 'subject_id', 'topic', 'status')


def snapshot(conn, q, user, note=''):
    """Keeps the current version before it changes."""
    snap = {k: q.get(k) for k in SNAP_FIELDS}
    conn.execute("INSERT INTO ex_question_versions (question_id, version, snapshot_json, changed_by, note) "
                 "VALUES (?, ?, ?, ?, ?)", (q['id'], q.get('version') or 1, json.dumps(snap, default=str), user, note))


def remember_alias(conn, q, subject_id, user):
    """The team chose a subject for a tag we didn't know — remember it for every later file."""
    key = norm_tag(q.get('lead_tag') or '')
    if not key or not subject_id:
        return False
    conn.execute("INSERT INTO ex_subject_aliases (tenant_id, exam_code, alias_key, subject_id, source, created_by) "
                 "VALUES (?, ?, ?, ?, 'team', ?) ON CONFLICT (tenant_id, exam_code, alias_key) DO NOTHING",
                 (q['tenant_id'], q['exam_code'], key, subject_id, user))
    return True


def apply_alias_to_batch(conn, batch_id, lead_tag, subject_id, user):
    """Other questions in the same file with the same unknown first tag get the same subject."""
    ids = [r['id'] for r in conn.execute(
        "SELECT id FROM ex_questions WHERE batch_id=? AND lead_tag=? AND status='draft' "
        "AND (subject_id IS NULL OR flags_json LIKE ?)", (batch_id, lead_tag, '%subject_guessed%')).fetchall()]
    for qid in ids:
        conn.execute("UPDATE ex_questions SET subject_id=?, updated_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (subject_id, user, qid))
        recheck(conn, qid)
    return len(ids)


def now_ist_str(dt):
    if not dt:
        return ''
    try:
        from datetime import timedelta
        return (dt + timedelta(hours=5, minutes=30)).strftime('%d %b %Y, %I:%M %p')
    except Exception:
        return str(dt)
