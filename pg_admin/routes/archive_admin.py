"""goocampus.in Admin → Archive (founder 2026-10-22): every official PDF of every authority, by
season → authority → category, with a ZIP download of any slice and the R2 backup status.
Admin only. Read-mostly: the only writes are the backup sweep and the ZIP job record."""
import csv
import io
import json
import logging
import os
import tempfile
import threading
import zipfile
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, session, jsonify
from db import get_db
from core.auth import login_required
from core.users import get_user
from pg_admin.data import archive as A

_zip_lock = threading.Lock()


def _admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def _job_get(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS pg_archive_jobs (k TEXT PRIMARY KEY, v TEXT, "
                 "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    r = conn.execute("SELECT v FROM pg_archive_jobs WHERE k = 'zip'").fetchone()
    try:
        return json.loads(r['v']) if r and r['v'] else {}
    except Exception:
        return {}


def _job_set(conn, v):
    conn.execute("INSERT INTO pg_archive_jobs (k, v, updated_at) VALUES ('zip', ?, CURRENT_TIMESTAMP) "
                 "ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v, updated_at = CURRENT_TIMESTAMP", (json.dumps(v),))
    conn.commit()


def _filters():
    return {k: (request.values.get(k) or '').strip() for k in ('season', 'authority', 'category', 'q', 'show')}


def _rows(conn, f):
    """Documents matching the filters (no file bytes)."""
    A.ensure_cols(conn)
    from pg_admin.data.big_files import ensure_cols as bf_cols
    bf_cols(conn)
    conds, params = ["(file_data IS NOT NULL OR COALESCE(file_r2_key,'') <> '')"], []
    if f.get('authority'):
        conds.append("authority_code = ?"); params.append(f['authority'])
    if f.get('category'):
        conds.append("category = ?"); params.append(f['category'])
    if f.get('q'):
        conds.append("(title ILIKE ? OR file_name ILIKE ?)"); params += [f"%{f['q']}%"] * 2
    if f.get('show') == 'published':
        conds.append("COALESCE(is_published, TRUE) AND COALESCE(archive_only, FALSE) = FALSE")
    elif f.get('show') == 'archive_only':
        conds.append("COALESCE(archive_only, FALSE)")
    rows = [dict(r) for r in conn.execute(
        "SELECT id, authority_code, authority_name, category, title, doc_date, uploaded_at, file_name, "
        "COALESCE(is_published, TRUE) AS is_published, COALESCE(archive_only, FALSE) AS archive_only, "
        "COALESCE(source_url,'') AS source_url, COALESCE(backup_r2_key,'') AS backup_r2_key, "
        "COALESCE(file_size, octet_length(file_data)) AS size, COALESCE(file_r2_key,'') AS file_r2_key "
        "FROM pg_authority_docs WHERE " + ' AND '.join(conds) +
        " ORDER BY authority_code, category, doc_date DESC, id DESC", params).fetchall()]
    for r in rows:
        r['season'] = A.doc_season(r)
    if f.get('season'):
        rows = [r for r in rows if r['season'] == f['season']]
    return rows


@login_required
def archive_page():
    if not _admin():
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    f = _filters()
    conn = get_db()
    try:
        rows = _rows(conn, f)
        allrows = rows if not any(f.values()) else _rows(conn, {})
        seasons = sorted({r['season'] for r in allrows}, reverse=True)
        from pg_admin.authorities import AUTHORITIES, DOC_CATEGORIES
        auth_names = {a[0]: a[1] for a in AUTHORITIES}
        present = sorted({r['authority_code'] for r in allrows}, key=lambda c: (c != 'mcc', auth_names.get(c, c)))
        stats = {'files': len(rows), 'mb': round(sum(int(r['size'] or 0) for r in rows) / 1048576, 1),
                 'backed_up': sum(1 for r in rows if r['backup_r2_key']),
                 'archive_only': sum(1 for r in rows if r['archive_only'])}
        job = _job_get(conn)
    finally:
        conn.close()
    if stats['backed_up'] < stats['files']:
        A.kick_sync()                                  # catch up any missing backups in the background
    from pg_admin.authorities import category_label
    return render_template('pg_admin/archive.html', rows=rows[:1500], total=len(rows), f=f, seasons=seasons,
                           authorities=[(c, auth_names.get(c, c)) for c in present], categories=DOC_CATEGORIES,
                           category_label=category_label, stats=stats, job=job, active_section='goocampus_in')


def _build_zip(f, who):
    from core import storage
    conn = get_db()
    tmp = None
    try:
        rows = _rows(conn, f)
        _job_set(conn, {'status': 'building', 'started_at': datetime.utcnow().isoformat(), 'by': who,
                        'filters': f, 'total': len(rows), 'progress': 0})
        from pg_admin.authorities import category_label
        fd, tmp = tempfile.mkstemp(suffix='.zip'); os.close(fd)
        man = io.StringIO(); w = csv.writer(man)
        w.writerow(['Season', 'Authority', 'Category', 'Title', 'Date', 'Status', 'File in zip', 'Official link'])
        added = 0
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            for i, r in enumerate(rows, 1):
                arc = (f"{r['season']}/{A._safe(r['authority_name'] or r['authority_code'], 60)}/"
                       f"{A._safe(category_label(r['category']), 50)}/" + A.backup_key(r).rsplit('/', 1)[-1])
                try:
                    if r['file_r2_key']:
                        fd2, t2 = tempfile.mkstemp(); os.close(fd2)
                        try:
                            storage.get_client().download_file(storage.get_bucket_name(), r['file_r2_key'], t2)
                            z.write(t2, arc)
                        finally:
                            os.remove(t2)
                    else:
                        d = conn.execute("SELECT file_data FROM pg_authority_docs WHERE id = ?", (r['id'],)).fetchone()
                        z.writestr(arc, bytes(d['file_data']))
                    added += 1
                except Exception as e:
                    logging.warning("archive zip %s: %s", r['id'], e)
                    arc = f'(missing: {e})'[:120]
                w.writerow([r['season'], r['authority_name'] or r['authority_code'], category_label(r['category']),
                            r['title'], r['doc_date'] or '', 'Archive only' if r['archive_only'] else
                            ('Published' if r['is_published'] else 'Hidden'), arc, r['source_url']])
                if i % 20 == 0:
                    _job_set(conn, {**_job_get(conn), 'progress': i})
            z.writestr('_INDEX.csv', man.getvalue().encode('utf-8-sig'))
        label = '_'.join(x for x in (f.get('season'), f.get('authority'), f.get('category')) if x) or 'all'
        key = f"exports/archive/GooCampus_NEETPG_Archive_{label}_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
        storage.get_client().upload_file(tmp, storage.get_bucket_name(), key, ExtraArgs={'ContentType': 'application/zip'})
        _job_set(conn, {'status': 'ready', 'key': key, 'built_at': datetime.utcnow().isoformat(), 'by': who,
                        'filters': f, 'files': added, 'total': len(rows),
                        'mb': round(os.path.getsize(tmp) / 1048576, 1)})
    except Exception as e:
        logging.error("archive zip: %s", e)
        try:
            conn.rollback(); _job_set(conn, {**_job_get(conn), 'status': 'failed', 'error': str(e)[:300]})
        except Exception:
            pass
    finally:
        conn.close()
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
        try: _zip_lock.release()
        except RuntimeError: pass


@login_required
def archive_zip_build():
    if not _admin():
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    from core import storage
    f = _filters()
    if not storage.is_configured():
        flash('File storage is not configured.', 'error'); return redirect(url_for('pg_archive', **f))
    if not _zip_lock.acquire(blocking=False):
        flash('A zip is already being built — refresh in a minute.', 'info'); return redirect(url_for('pg_archive', **f))
    who = session.get('name') or session.get('emp_code') or 'admin'
    threading.Thread(target=_build_zip, args=(f, who), daemon=True).start()
    flash('Building the zip — this can take a few minutes for a big selection. Refresh this page to get it.', 'success')
    return redirect(url_for('pg_archive', **{k: v for k, v in f.items() if v}))


@login_required
def archive_zip_download():
    if not _admin():
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        job = _job_get(conn)
    finally:
        conn.close()
    if not job.get('key'):
        flash('No zip yet — click "Download ZIP" first.', 'error'); return redirect(url_for('pg_archive'))
    from core import storage
    url = storage.presigned_get_url(job['key'], filename_for_download=job['key'].rsplit('/', 1)[-1])
    return redirect(url, code=302) if url else redirect(url_for('pg_archive'))


@login_required
def archive_backup_now():
    if not _admin():
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    A.kick_sync()
    flash('Backing up every document to file storage in the background — refresh in a minute.', 'success')
    return redirect(url_for('pg_archive'))


def api_archive_backfill():
    """POST /api/pg/archive/backfill (X-News-Key) {file_unfiled: bool, backups: bool} — one-time catch-up:
    file every inbox PDF not yet in Documents as archive-only, then back up all documents to R2."""
    from pg_admin.routes.api_news_ingest import _ok
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    b = request.get_json(silent=True) or {}
    out = {'ok': True}
    if b.get('file_unfiled'):
        conn = get_db()
        try:
            out['filed'] = A.file_all_unfiled(conn)
        finally:
            conn.close()
    if b.get('backups'):
        threading.Thread(target=A.sync_backups, daemon=True).start()
        out['backups'] = 'started in the background'
    return jsonify(out)


def api_archive_status():
    """GET /api/pg/archive/status (X-News-Key) — counts for checks (read-only)."""
    from pg_admin.routes.api_news_ingest import _ok
    if not _ok():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        A.ensure_cols(conn)
        from pg_admin.data.big_files import ensure_cols as bf_cols
        bf_cols(conn)
        r = dict(conn.execute(
            "SELECT COUNT(*) AS docs, SUM(CASE WHEN COALESCE(backup_r2_key,'')<>'' THEN 1 ELSE 0 END) AS backed_up, "
            "SUM(CASE WHEN COALESCE(archive_only,FALSE) THEN 1 ELSE 0 END) AS archive_only "
            "FROM pg_authority_docs WHERE file_data IS NOT NULL OR COALESCE(file_r2_key,'') <> ''").fetchone())
        un = conn.execute(
            "SELECT COUNT(*) AS n FROM pg_news_inbox i WHERE i.status <> 'seen' AND (i.pdf_data IS NOT NULL OR "
            "COALESCE(i.pdf_r2_key,'') <> '') AND COALESCE(i.doc_rejected,FALSE) = FALSE AND NOT EXISTS (SELECT 1 FROM "
            "pg_authority_docs d WHERE d.auto_inbox_id = i.id)").fetchone()['n']
        links = conn.execute(
            "SELECT COUNT(*) AS n FROM pg_news_inbox i WHERE i.kind = 'link' AND i.status <> 'seen' AND "
            "COALESCE(i.url,'') <> '' AND NOT EXISTS (SELECT 1 FROM pg_authority_docs d WHERE "
            "d.auto_inbox_id = i.id AND d.auto_kind = 'snapshot')").fetchone()['n']
        return jsonify({'ok': True, **{k: int(v or 0) for k, v in r.items()}, 'inbox_pdfs_not_in_documents': int(un),
                        'web_pages_without_snapshot': int(links)})
    finally:
        conn.close()
