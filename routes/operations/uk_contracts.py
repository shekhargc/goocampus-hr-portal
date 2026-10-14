"""UK PGCP (pathway 'plab') — Contracts register + bulk download (founder 2026-10-14).

/operations/plab/contracts            list of every UK client: name, registration no., status,
                                      current stage, contract on record (Yes/No) + where it is
/operations/plab/contracts/download   the same list as Excel
/operations/plab/contracts/zip/build  builds ONE zip of every contract file in the background
                                      (hundreds of files — too slow for one web request), stores it
                                      in R2 and remembers it in pg_kv
/operations/plab/contracts/zip        downloads the latest zip (15-min signed link)

A contract can live in four places (all are checked, in this order):
  1. plab_clients.contract_path                    (ops / admin upload, Zoho import)
  2. plab_client_documents — a contract document   ('Signed Contract' etc.)
  3. client_registrations.contract_path            (the client's registration)
  4. client_invitations.contract_path              (uploaded by sales at the invitation)
"Contract available" = a contract file is on record. The zip build also checks each file really
exists in storage and lists anything missing in manifest.csv. READ-ONLY on client data.
Contracts are confidential (fees + signatures) → admins only.
"""
import io
import json
import logging
import os
import re
import tempfile
import threading
import zipfile
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, send_file, session

from core.auth import admin_required
from db import get_db

KV_KEY = 'ops_contracts_zip_plab'
_CT_EXT = ('pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png')
_building = threading.Lock()


def _is_admin():
    return bool(session.get('is_admin'))


def _name(c):
    return ' '.join(f"{c.get('prefix') or ''} {c.get('first_name') or ''} {c.get('last_name') or ''}".split()) or '—'


def _r2_key(p):
    s = str(p or '').strip()
    return None if (not s or s.startswith('/') or '://' in s) else s


def _sources(conn):
    """{client_id: [source dicts]} for every UK client, plus the client rows."""
    clients = [dict(r) for r in conn.execute(
        "SELECT id, prefix, first_name, last_name, registration_number, account_status, current_stage, "
        "contract_path FROM plab_clients WHERE COALESCE(pathway,'plab') = 'plab' "
        "ORDER BY NULLIF(regexp_replace(COALESCE(registration_number,''),'[^0-9]','','g'),'')::bigint DESC NULLS LAST, id DESC"
    ).fetchall()]
    by_rn = {(c['registration_number'] or '').strip().upper(): c['id'] for c in clients if c.get('registration_number')}
    src = {c['id']: [] for c in clients}
    for c in clients:
        if _r2_key(c.get('contract_path')):
            src[c['id']].append({'kind': 'r2', 'key': c['contract_path'].strip(), 'where': 'Client profile'})
    try:
        for r in conn.execute(
                "SELECT d.id, d.client_id, d.doc_type, d.file_name, d.file_path, (d.file_data IS NOT NULL) AS has_data "
                "FROM plab_client_documents d JOIN plab_clients pc ON pc.id = d.client_id "
                "WHERE COALESCE(pc.pathway,'plab') = 'plab' AND (LOWER(COALESCE(d.doc_category,'')) = 'contract' "
                "OR LOWER(d.doc_type) LIKE '%contract%' OR LOWER(d.doc_type) LIKE '%agreement%') "
                "ORDER BY d.uploaded_at DESC NULLS LAST, d.id DESC").fetchall():
            k = _r2_key(r['file_path'])
            if k:
                src[r['client_id']].append({'kind': 'r2', 'key': k, 'where': f"Documents ({r['doc_type']})"})
            elif r['has_data']:
                src[r['client_id']].append({'kind': 'doc', 'id': r['id'], 'name': r['file_name'] or 'contract.pdf',
                                            'where': f"Documents ({r['doc_type']})"})
    except Exception as e:
        logging.warning("uk contracts docs: %s", e)
        conn.rollback()
    try:
        for r in conn.execute(
                "SELECT UPPER(TRIM(cr.registration_number)) AS rn, cr.contract_path AS rcp, ci.contract_path AS icp "
                "FROM client_registrations cr LEFT JOIN client_invitations ci ON ci.id = cr.invitation_id "
                "WHERE cr.registration_number IS NOT NULL AND (cr.contract_path IS NOT NULL OR ci.contract_path IS NOT NULL) "
                "ORDER BY cr.id DESC").fetchall():
            cid = by_rn.get(r['rn'] or '')
            if not cid:
                continue
            for col, where in (('rcp', 'Client registration'), ('icp', 'Sales invitation')):
                k = _r2_key(r[col])
                if k:
                    src[cid].append({'kind': 'r2', 'key': k, 'where': where})
    except Exception as e:
        logging.warning("uk contracts registrations: %s", e)
        conn.rollback()
    digital = set()
    try:
        for r in conn.execute(
                "SELECT DISTINCT UPPER(TRIM(cr.registration_number)) AS rn FROM client_agreements ca "
                "JOIN client_registrations cr ON cr.id = ca.registration_id WHERE ca.agreement_type = 'contract'").fetchall():
            if r['rn']:
                digital.add(r['rn'])
    except Exception:
        conn.rollback()
    for cid, lst in src.items():             # one entry per distinct file
        seen, uniq = set(), []
        for s in lst:
            k = s.get('key') or f"doc{s.get('id')}"
            if k not in seen:
                seen.add(k); uniq.append(s)
        src[cid] = uniq
    return clients, src, digital


def _kv_get(conn):
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS pg_kv (key TEXT PRIMARY KEY, value TEXT DEFAULT '', "
                     "updated_by TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        r = conn.execute("SELECT value FROM pg_kv WHERE key = ?", (KV_KEY,)).fetchone()
        return json.loads(r['value']) if r and r['value'] else {}
    except Exception:
        conn.rollback()
        return {}


def _kv_set(conn, data, who=''):
    conn.execute("CREATE TABLE IF NOT EXISTS pg_kv (key TEXT PRIMARY KEY, value TEXT DEFAULT '', "
                 "updated_by TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("INSERT INTO pg_kv (key, value, updated_by, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                 "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, "
                 "updated_at = CURRENT_TIMESTAMP", (KV_KEY, json.dumps(data), who))
    conn.commit()


def _rows(conn):
    clients, src, digital = _sources(conn)
    job = _kv_get(conn)
    verified = job.get('verified') or {}
    rows = []
    for c in clients:
        rn = (c.get('registration_number') or '').strip()
        s = src.get(c['id'], [])
        rows.append({
            'id': c['id'], 'name': _name(c), 'registration_number': rn or '—',
            'status': c.get('account_status') or '', 'stage': c.get('current_stage') or '',
            'has_contract': bool(s), 'where': ', '.join(dict.fromkeys(x['where'] for x in s)),
            'digital': rn.upper() in digital,
            'verified': verified.get(str(c['id'])),       # True/False after a zip build, else None
        })
    return rows, job


@admin_required
def contracts_page():
    if not _is_admin():
        flash('Contracts are visible to admins only.', 'error')
        return redirect(url_for('ops_main_dashboard'))
    conn = get_db()
    try:
        rows, job = _rows(conn)
    finally:
        conn.close()
    f_status, f_stage, f_has = (request.args.get('status') or '').strip(), (request.args.get('stage') or '').strip(), \
        (request.args.get('has') or '').strip()
    statuses = sorted({r['status'] for r in rows if r['status']})
    stages = sorted({r['stage'] for r in rows if r['stage']})
    shown = [r for r in rows if (not f_status or r['status'] == f_status) and (not f_stage or r['stage'] == f_stage)
             and (not f_has or (f_has == 'yes') == r['has_contract'])]
    return render_template('ops_plab_contracts.html', rows=shown, total=len(rows),
                           with_contract=sum(1 for r in rows if r['has_contract']), job=job,
                           statuses=statuses, stages=stages, f_status=f_status, f_stage=f_stage, f_has=f_has,
                           active_ops_page='plab-contracts')


@admin_required
def contracts_download():
    """Excel: Client Name + Registration Number first (house rule), then status, stage, contract."""
    if not _is_admin():
        flash('Contracts are visible to admins only.', 'error')
        return redirect(url_for('ops_main_dashboard'))
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    conn = get_db()
    try:
        rows, job = _rows(conn)
    finally:
        conn.close()
    xs = lambda v: ILLEGAL_CHARACTERS_RE.sub('', v) if isinstance(v, str) else v
    wb = Workbook(); ws = wb.active; ws.title = 'UK PGCP Contracts'
    hdr = ['Client Name', 'Registration Number', 'Status', 'Current Stage', 'Contract Available',
           'Contract Location', 'Digitally Agreed in Portal', 'File Checked in Storage']
    ws.append(hdr)
    for r in rows:
        chk = '' if r['verified'] is None else ('Yes' if r['verified'] else 'MISSING')
        ws.append([xs(r['name']), xs(r['registration_number']), xs(r['status']), xs(r['stage']),
                   'Yes' if r['has_contract'] else 'No', xs(r['where']), 'Yes' if r['digital'] else 'No', chk])
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF'); cell.fill = PatternFill('solid', fgColor='0F1B33')
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    ws.freeze_panes = 'C2'; ws.auto_filter.ref = ws.dimensions
    for i, w in enumerate([28, 22, 14, 22, 12, 34, 14, 14], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    out = io.BytesIO(); wb.save(out); out.seek(0)
    return send_file(out, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=f"UK_PGCP_Contracts_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")


def _safe(s):
    return re.sub(r'[\\/:*?"<>|]+', '_', s or '').strip()[:90] or 'client'


def _build_zip(who):
    """Background: fetch every contract file, zip it on disk, upload the zip to R2, remember it."""
    from core import storage
    conn = get_db()
    tmp = None
    try:
        clients, src, _d = _sources(conn)
        _kv_set(conn, {**_kv_get(conn), 'status': 'building', 'started_at': datetime.utcnow().isoformat(),
                       'by': who, 'progress': 0, 'total': len(clients)}, who)
        fd, tmp = tempfile.mkstemp(suffix='.zip'); os.close(fd)
        verified, missing, added = {}, [], 0
        manifest = io.StringIO()
        manifest.write('Client Name,Registration Number,Status,Current Stage,Contract Available,File in zip,Location,Note\n')
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            for i, c in enumerate(clients, 1):
                rn = (c.get('registration_number') or '').strip()
                got, note, where = None, '', ''
                for s in src.get(c['id'], []):
                    try:
                        if s['kind'] == 'doc':
                            r = conn.execute("SELECT file_data FROM plab_client_documents WHERE id = ?", (s['id'],)).fetchone()
                            data = bytes(r['file_data']) if r and r['file_data'] else None
                            ext = s['name'].rsplit('.', 1)[-1].lower() if '.' in s['name'] else 'pdf'
                        else:
                            data = storage.download_bytes(s['key'])
                            if data is None:            # stale key (e.g. Zoho import) → look in the client's Contract folder
                                folder = s['key'].rsplit('/', 1)[0] + '/' if '/' in s['key'] else ''
                                alts = (storage.list_objects(folder, max_keys=20) if folder else []) or \
                                       storage.list_objects(f"plab/{storage._safe_segment(rn)}/Contract/", max_keys=20)
                                data = storage.download_bytes(alts[0]) if alts else None
                            ext = s['key'].rsplit('.', 1)[-1].lower() if '.' in s['key'] else 'pdf'
                        if data:
                            got, where = (data, ext if ext in _CT_EXT else 'pdf'), s['where']
                            break
                    except Exception as e:
                        note = str(e)[:80]
                if src.get(c['id']):
                    verified[str(c['id'])] = bool(got)
                fname = ''
                if got:
                    fname = f"{_safe(rn)} - {_safe(_name(c))}.{got[1]}"
                    z.writestr(fname, got[0]); added += 1
                elif src.get(c['id']):
                    note = note or 'on record but the file was not found in storage'
                    missing.append(rn or str(c['id']))
                row = [_name(c), rn, c.get('account_status') or '', c.get('current_stage') or '',
                       'Yes' if src.get(c['id']) else 'No', fname, where, note]
                manifest.write(','.join('"' + str(x).replace('"', "'") + '"' for x in row) + '\n')
                if i % 25 == 0:
                    _kv_set(conn, {**_kv_get(conn), 'progress': i}, who)
            z.writestr('_LIST_all_UK_PGCP_clients.csv', manifest.getvalue().encode('utf-8-sig'))
        key = f"exports/contracts/UK_PGCP_Contracts_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
        storage.get_client().upload_file(tmp, storage.get_bucket_name(), key,
                                          ExtraArgs={'ContentType': 'application/zip'})
        _kv_set(conn, {'status': 'ready', 'key': key, 'built_at': datetime.utcnow().isoformat(), 'by': who,
                       'files': added, 'missing': missing, 'total': len(clients), 'verified': verified}, who)
    except Exception as e:
        logging.error("uk contracts zip: %s", e)
        try:
            conn.rollback()
            _kv_set(conn, {**_kv_get(conn), 'status': 'failed', 'error': str(e)[:300]}, who)
        except Exception:
            pass
    finally:
        conn.close()
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
        try: _building.release()
        except RuntimeError: pass


@admin_required
def contracts_zip_build():
    if not _is_admin():
        flash('Contracts are visible to admins only.', 'error')
        return redirect(url_for('ops_main_dashboard'))
    from core import storage
    if not storage.is_configured():
        flash('File storage is not configured.', 'error')
        return redirect(url_for('ops_plab_contracts'))
    conn = get_db()
    try:
        job = _kv_get(conn)
    finally:
        conn.close()
    if job.get('status') == 'building':                  # another server worker may be building it
        try:
            age = (datetime.utcnow() - datetime.fromisoformat(job.get('started_at'))).total_seconds()
        except Exception:
            age = 99999
        if age < 20 * 60:
            flash('A zip is already being built — refresh in a minute.', 'info')
            return redirect(url_for('ops_plab_contracts'))
    if not _building.acquire(blocking=False):
        flash('A zip is already being built — refresh in a minute.', 'info')
        return redirect(url_for('ops_plab_contracts'))
    who = session.get('name') or session.get('emp_code') or 'admin'
    threading.Thread(target=_build_zip, args=(who,), daemon=True).start()
    flash('Building the zip of all UK contracts — this takes a few minutes. Refresh this page to see when it is ready.', 'success')
    return redirect(url_for('ops_plab_contracts'))


@admin_required
def contracts_zip():
    if not _is_admin():
        flash('Contracts are visible to admins only.', 'error')
        return redirect(url_for('ops_main_dashboard'))
    conn = get_db()
    try:
        job = _kv_get(conn)
    finally:
        conn.close()
    if job.get('status') != 'ready' and not job.get('key'):
        flash('No zip yet — click "Build zip of all contracts" first.', 'error')
        return redirect(url_for('ops_plab_contracts'))
    from core import storage
    url = storage.presigned_get_url(job['key'], filename_for_download=job['key'].rsplit('/', 1)[-1])
    if not url:
        flash('Could not prepare the download — try again.', 'error')
        return redirect(url_for('ops_plab_contracts'))
    return redirect(url, code=302)


def register_routes(app):
    app.add_url_rule('/operations/plab/contracts', 'ops_plab_contracts', contracts_page, methods=['GET'])
    app.add_url_rule('/operations/plab/contracts/download', 'ops_plab_contracts_download', contracts_download, methods=['GET'])
    app.add_url_rule('/operations/plab/contracts/zip/build', 'ops_plab_contracts_zip_build', contracts_zip_build, methods=['POST'])
    app.add_url_rule('/operations/plab/contracts/zip', 'ops_plab_contracts_zip', contracts_zip, methods=['GET'])
