"""
import_plab_certificates.py -- run LOCALLY to bulk-import PLAB client
certificates into plab_client_documents with doc_category='certificate'.

Files go to Cloudflare R2 (object storage); only the R2 object key is
stored in plab_client_documents.file_path. This is the certificate
equivalent of bulk_import_documents.py, driven by a Zoho mapping report
instead of structured filenames.

Inputs
======
  1. Mapping report (xlsx), default:
       /Users/Santosh/Desktop/Zoho Data/UK GC/CLient's Additional Doc & Certificates Report.xlsx
     Columns:
       - 'Upload Doc / Certificate'  -> the actual filename in the folder
       - 'GC UK Registration'        -> client name with embedded reg
                                        (e.g. " Dr. Anushka Mathur -GCUKIP/25-26/009")
       - 'Doc / Certificate Name'    -> the certificate label (doc_type)
     Override with env REPORT=/path/to/report.xlsx

  2. A folder of the actual certificate files, env CERT_FOLDER (required).

Behavior (per report row)
=========================
  1. Extract reg number from 'GC UK Registration' via regex
     GC[A-Z]*/[0-9A-Za-z-]+/\\d+  ; look up client_id in plab_clients
     (pathway='plab') by registration_number (with padding-variant
     fallbacks, same as bulk_import_documents.py).
  2. Find the file in CERT_FOLDER by exact 'Upload Doc / Certificate'
     filename; fall back to a basename match if the exact path fails.
  3. Upload bytes to R2 via core.storage.upload_bytes with key
     storage.make_doc_key('plab', reg, 'Certificate', filename).
  4. INSERT plab_client_documents row:
       client_id, doc_type = 'Doc / Certificate Name' (fallback to
       filename), doc_category='certificate', file_name, file_path=r2_key,
       file_size, content_type (guessed from ext), status='uploaded',
       uploaded_by='cert_import'.
  Skipped + reported: file-not-in-folder, client-not-matched, >12MB.

Wipe (optional)
===============
  WIPE=1 deletes existing doc_category='certificate' rows (DB) and the
  matching R2 objects under plab/.../Certificate/ before importing, so
  re-runs don't duplicate. Off by default.

Run
===
  CERT_FOLDER="/path/to/certificate files" \
  DATABASE_URL=postgresql://... \
  R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... \
  R2_BUCKET_NAME=goocampus-client-docs \
  R2_ENDPOINT=https://<acct>.r2.cloudflarestorage.com \
  python3 import_plab_certificates.py

  Add WIPE=1 to clear existing certificate rows first.
  Add DRY_RUN=1 to parse + match only (no R2 upload, no DB writes).
"""

import os
import re
import sys
import time

from db import get_db


DEFAULT_REPORT = "/Users/Santosh/Desktop/Zoho Data/UK GC/CLient's Additional Doc & Certificates Report.xlsx"
MAX_FILE_SIZE_MB = 12

# Embedded reg pattern, e.g. "GCUKIP/25-26/009" inside a name string.
_REG_RE = re.compile(r'(GC[A-Z]*/[0-9A-Za-z-]+/\d+)')

# Split a reg into prefix/middle/tail for padding-variant fallback.
_REG_SPLIT_RE = re.compile(r'^(GC[A-Z]*)/([0-9A-Za-z-]+)/(\d{1,4})$')

EXT_TO_MIME = {
    '.jpg':  'image/jpeg', '.jpeg': 'image/jpeg', '.png':  'image/png',
    '.gif':  'image/gif',  '.webp': 'image/webp',
    '.pdf':  'application/pdf',
    '.doc':  'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}


def extract_reg(text):
    if not text:
        return None
    m = _REG_RE.search(str(text))
    return m.group(1) if m else None


def _reg_variants(reg):
    """Yield reg plus padding / year-format variants so a reg like
    GCUKIP/2023/057 also matches GCUKIP/23-24/057 etc."""
    seen = set()

    def emit(v):
        if v not in seen:
            seen.add(v)
            return True
        return False

    if emit(reg):
        yield reg
    m = _REG_SPLIT_RE.match(reg)
    if not m:
        return
    prefix, middle, tail = m.group(1), m.group(2), m.group(3)
    try:
        n = int(tail)
    except ValueError:
        return
    middles = [middle]
    if '-' not in middle and middle.isdigit() and len(middle) == 4:
        y = int(middle); yy = y % 100; yyn = (y + 1) % 100
        middles.append(f"{yy:02d}-{yyn:02d}")
    elif '-' in middle:
        start = middle.split('-', 1)[0]
        if start.isdigit() and len(start) == 2:
            middles.append(f"20{int(start):02d}")
    for md in middles:
        for pad in (3, 4, 2, 1):
            v = f"{prefix}/{md}/{n:0{pad}d}"
            if emit(v):
                yield v


def build_reg_lookup(conn):
    """Map normalized registration_number -> client_id (pathway='plab')."""
    rows = conn.execute(
        "SELECT id, registration_number FROM plab_clients "
        "WHERE COALESCE(pathway,'plab')='plab' AND registration_number IS NOT NULL"
    ).fetchall()
    lookup = {}
    for r in rows:
        reg = (r['registration_number'] or '').strip().upper()
        if reg:
            lookup.setdefault(reg, r['id'])
    return lookup


def lookup_client_id(lookup, reg):
    if not reg:
        return None
    for variant in _reg_variants(reg):
        cid = lookup.get(variant.strip().upper())
        if cid:
            return cid
    return None


def build_file_index(folder):
    """Map basename -> full path for fallback matching."""
    index = {}
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.startswith('.'):
                continue
            index.setdefault(f, os.path.join(root, f))
    return index


def find_file(folder, file_index, fname):
    """Exact path under folder first; then basename match anywhere."""
    if not fname:
        return None
    direct = os.path.join(folder, fname)
    if os.path.isfile(direct):
        return direct
    base = os.path.basename(str(fname).strip())
    return file_index.get(base)


def main():
    report = os.environ.get('REPORT', DEFAULT_REPORT)
    folder = os.environ.get('CERT_FOLDER')
    dry_run = os.environ.get('DRY_RUN') in ('1', 'true', 'True')
    wipe = os.environ.get('WIPE') in ('1', 'true', 'True')

    if not os.path.isfile(report):
        print(f"ERROR: report not found: {report}", file=sys.stderr)
        sys.exit(1)
    if not folder:
        print("ERROR: CERT_FOLDER env var required (folder of certificate files).", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(folder):
        print(f"ERROR: CERT_FOLDER not found: {folder}", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get('DATABASE_URL') and not dry_run:
        print("ERROR: DATABASE_URL env var required (or set DRY_RUN=1).", file=sys.stderr)
        sys.exit(1)

    import openpyxl
    wb = openpyxl.load_workbook(report, read_only=True, data_only=True)
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else '' for h in next(it)]
    hidx = {h: i for i, h in enumerate(headers)}

    col_file = hidx.get('Upload Doc / Certificate')
    col_reg = hidx.get('GC UK Registration')
    col_name = hidx.get('Doc / Certificate Name')
    if col_file is None or col_reg is None:
        print(f"ERROR: required columns missing. Found headers: {headers}", file=sys.stderr)
        sys.exit(1)

    rows = []
    for r in it:
        if not any(v not in (None, '') for v in r):
            continue
        def g(i):
            return r[i] if (i is not None and i < len(r)) else None
        fname = (str(g(col_file)).strip() if g(col_file) is not None else '')
        reg_raw = g(col_reg)
        label = (str(g(col_name)).strip() if g(col_name) is not None else '')
        if not fname:
            continue
        rows.append((fname, reg_raw, label))
    wb.close()
    print(f"Report rows with a filename: {len(rows)}")

    file_index = build_file_index(folder)
    print(f"Files found in CERT_FOLDER: {len(file_index)}")

    # Storage + DB
    from core import storage
    if not dry_run and not storage.is_configured():
        print("ERROR: R2 not configured (R2_* env vars). Set them or use DRY_RUN=1.", file=sys.stderr)
        sys.exit(1)

    conn = None
    reg_lookup = {}
    if not dry_run:
        conn = get_db()
        reg_lookup = build_reg_lookup(conn)
        print(f"PLAB clients indexed by reg: {len(reg_lookup)}")

        if wipe:
            # SAFE wipe: only touch rows this importer created
            # (uploaded_by='cert_import'). Manual cert uploads from the
            # portal UI (uploaded_by='ops_team') survive. Delete each
            # row's R2 object first, then the DB rows.
            try:
                prior = conn.execute(
                    "SELECT id, file_path FROM plab_client_documents "
                    "WHERE doc_category = 'certificate' AND uploaded_by = 'cert_import'"
                ).fetchall()
                print(f"Wiping {len(prior)} prior cert_import rows (+ their R2 objects)")
                for row in prior:
                    fp = row['file_path']
                    if fp and not str(fp).startswith('db://') and '://' not in str(fp):
                        try:
                            storage.delete_object(str(fp))
                        except Exception as e:
                            print(f"  R2 delete skipped {fp}: {e}")
                conn.execute(
                    "DELETE FROM plab_client_documents "
                    "WHERE doc_category = 'certificate' AND uploaded_by = 'cert_import'"
                )
                conn.commit()
                print("Wiped prior cert_import certificate rows from DB")
            except Exception as e:
                conn.rollback()
                print(f"  Wipe failed: {e}")

    summary = {
        'rows': len(rows), 'uploaded': 0,
        'file_missing': [], 'unmatched_reg': [], 'skipped_big': [],
        'errors': 0,
    }

    for i, (fname, reg_raw, label) in enumerate(rows, 1):
        try:
            reg = extract_reg(reg_raw)
            fpath = find_file(folder, file_index, fname)
            if not fpath:
                if len(summary['file_missing']) < 20:
                    summary['file_missing'].append(fname)
                continue

            client_id = None
            if not dry_run:
                client_id = lookup_client_id(reg_lookup, reg)
                if not client_id:
                    if len(summary['unmatched_reg']) < 20:
                        summary['unmatched_reg'].append(reg or str(reg_raw))
                    continue
            else:
                # dry-run: still note unmatched-looking regs (no DB)
                if not reg:
                    if len(summary['unmatched_reg']) < 20:
                        summary['unmatched_reg'].append(str(reg_raw))

            try:
                size = os.path.getsize(fpath)
            except Exception:
                size = 0
            if size > MAX_FILE_SIZE_MB * 1024 * 1024:
                summary['skipped_big'].append((fname, size))
                continue

            doc_type = label or os.path.basename(fpath)
            ext = os.path.splitext(fpath)[1].lower()
            content_type = EXT_TO_MIME.get(ext, 'application/octet-stream')
            leaf = os.path.basename(fpath)

            if dry_run:
                summary['uploaded'] += 1
                continue

            with open(fpath, 'rb') as fh:
                data = fh.read()

            r2_key = storage.make_doc_key('plab', reg or f'client_{client_id}', 'Certificate', leaf)
            if not storage.upload_bytes(r2_key, data, content_type):
                print(f"  R2 upload failed: {leaf}")
                summary['errors'] += 1
                continue

            # Insert with up to 3 reconnect attempts.
            inserted = False
            for attempt in range(3):
                try:
                    conn.execute(
                        "INSERT INTO plab_client_documents "
                        "  (client_id, doc_type, doc_category, file_name, file_path, "
                        "   file_size, content_type, status, uploaded_by) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'uploaded', 'cert_import')",
                        (client_id, doc_type, 'certificate', leaf, r2_key,
                         len(data), content_type),
                    )
                    conn.commit()
                    inserted = True
                    break
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    if attempt < 2:
                        print(f"  insert retry {attempt+1} for {leaf}: {e}")
                        time.sleep(2 ** attempt)
                        try:
                            conn.close()
                        except Exception:
                            pass
                        conn = get_db()
                    else:
                        print(f"  insert failed {leaf}: {e}")
                        storage.delete_object(r2_key)
                        summary['errors'] += 1
            if inserted:
                summary['uploaded'] += 1
        except Exception as e:
            print(f"  row {i} error ({fname}): {e}")
            summary['errors'] += 1

        if i % 25 == 0 or i == len(rows):
            print(f"  progress: {i}/{len(rows)} (uploaded={summary['uploaded']}, "
                  f"missing={len(summary['file_missing'])}, "
                  f"unmatched={len(summary['unmatched_reg'])}, errors={summary['errors']})")

    if conn:
        try:
            conn.close()
        except Exception:
            pass

    print()
    print("=== Certificate Import Summary ===")
    print(f"  Mode:                      {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"  Report rows:               {summary['rows']}")
    print(f"  Uploaded / inserted:       {summary['uploaded']}")
    print(f"  File not found in folder:  {len(summary['file_missing'])}  {summary['file_missing'][:5]}")
    print(f"  Client not matched:        {len(summary['unmatched_reg'])}  {summary['unmatched_reg'][:5]}")
    print(f"  Skipped (>12 MB):          {len(summary['skipped_big'])}  {[f for f,_ in summary['skipped_big'][:5]]}")
    print(f"  Errors:                    {summary['errors']}")


if __name__ == '__main__':
    main()
