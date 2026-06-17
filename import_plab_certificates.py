"""
import_plab_certificates.py -- run LOCALLY to bulk-import PLAB client
certificates into plab_client_documents with doc_category='certificate'.

Files go to Cloudflare R2 (object storage); only the R2 object key is
stored in plab_client_documents.file_path.

Driven by cert_manifest.json
============================
The certificate files were pulled directly from Zoho Creator's
"CLient's Additional Doc & Certificates Report" via the logged-in browser
(2026-06-17). Each file is saved in the folder named by its Zoho RECORD ID:
    <record_id>.<ext>     e.g. 104951000003371027.pdf
and cert_manifest.json maps every record to its client + label:
    [{ "id": "...", "fname": "Adhar.pdf", "reg": "GCUKIP/2022/004",
       "label": "AAdhar" }, ...]

We use the manifest (NOT the Zoho xlsx) because Zoho's exported xlsx stores
the internal epoch-prefixed filename, while the downloaded files use the
record id; the manifest is the authoritative join.

Behavior (per manifest record)
==============================
  1. reg -> client_id in plab_clients (pathway='plab') by
     registration_number, with padding/year-format variant fallbacks.
  2. Locate the file in CERT_FOLDER as <id>.* (any extension).
  3. Upload bytes to R2 via core.storage.upload_bytes with key
     storage.make_doc_key('plab', reg, 'Certificate', <original fname>).
  4. INSERT plab_client_documents row:
       client_id, doc_type = label (fallback: original fname),
       doc_category='certificate', file_name = original fname,
       file_path = r2_key, file_size, content_type, status='uploaded',
       uploaded_by='cert_import'.
  Skipped + reported: file-not-in-folder, client-not-matched, >25MB.

Wipe (optional)
===============
  WIPE=1 deletes existing doc_category='certificate' rows created by THIS
  importer (uploaded_by='cert_import') and their R2 objects before
  importing, so re-runs don't duplicate. Manual portal cert uploads
  (uploaded_by != 'cert_import') survive. Off by default.

Run
===
  CERT_FOLDER="/Users/Santosh/Desktop/Zoho Data/UK GC/Certificates" \
  DATABASE_URL=postgresql://... \
  R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... \
  R2_BUCKET_NAME=goocampus-client-docs \
  R2_ENDPOINT=https://<acct>.r2.cloudflarestorage.com \
  python3 import_plab_certificates.py

  Add DRY_RUN=1 to parse + match only (no R2 upload, no DB writes).
  Add WIPE=1 to clear prior cert_import rows first.
  Override manifest path with MANIFEST=/path/to/cert_manifest.json
"""

import os
import re
import sys
import json
import time

from db import get_db


MAX_FILE_SIZE_MB = 25

_REG_RE = re.compile(r'(GC[A-Z]*/[0-9A-Za-z-]+/\d+)')
_REG_SPLIT_RE = re.compile(r'^(GC[A-Z]*)/([0-9A-Za-z-]+)/(\d{1,4})$')

EXT_TO_MIME = {
    '.jpg':  'image/jpeg', '.jpeg': 'image/jpeg', '.png':  'image/png',
    '.gif':  'image/gif',  '.webp': 'image/webp',
    '.pdf':  'application/pdf',
    '.doc':  'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.eml':  'message/rfc822',
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


def build_id_index(folder):
    """Map record-id (filename without extension) -> full path."""
    index = {}
    for f in os.listdir(folder):
        if f.startswith('.') or f == 'cert_manifest.json':
            continue
        full = os.path.join(folder, f)
        if not os.path.isfile(full):
            continue
        stem = os.path.splitext(f)[0]
        index.setdefault(stem, full)
    return index


def main():
    folder = os.environ.get('CERT_FOLDER')
    dry_run = os.environ.get('DRY_RUN') in ('1', 'true', 'True')
    wipe = os.environ.get('WIPE') in ('1', 'true', 'True')

    if not folder:
        print("ERROR: CERT_FOLDER env var required (folder of certificate files).", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(folder):
        print(f"ERROR: CERT_FOLDER not found: {folder}", file=sys.stderr)
        sys.exit(1)

    manifest_path = os.environ.get('MANIFEST', os.path.join(folder, 'cert_manifest.json'))
    if not os.path.isfile(manifest_path):
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get('DATABASE_URL') and not dry_run:
        print("ERROR: DATABASE_URL env var required (or set DRY_RUN=1).", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path, encoding='utf-8') as fh:
        records = json.load(fh)
    print(f"Manifest records: {len(records)}")

    id_index = build_id_index(folder)
    print(f"Files found in CERT_FOLDER: {len(id_index)}")

    from core import storage
    if not dry_run and not storage.is_configured():
        print("ERROR: R2 not configured (R2_* env vars). Set them or use DRY_RUN=1.", file=sys.stderr)
        sys.exit(1)

    conn = None
    reg_lookup = {}
    # Connect whenever a DB is configured -- even in DRY_RUN -- so we can
    # validate client matching before committing to the real upload.
    if os.environ.get('DATABASE_URL'):
        conn = get_db()
        reg_lookup = build_reg_lookup(conn)
        print(f"PLAB clients indexed by reg: {len(reg_lookup)}")

        if wipe and not dry_run:
            try:
                prior = conn.execute(
                    "SELECT id, file_path FROM plab_client_documents "
                    "WHERE doc_category = 'certificate' AND uploaded_by = 'cert_import'"
                ).fetchall()
                print(f"Wiping {len(prior)} prior cert_import rows (+ their R2 objects)")
                for row in prior:
                    fp = row['file_path']
                    if fp and '://' not in str(fp):
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
        'records': len(records), 'uploaded': 0,
        'file_missing': [], 'unmatched_reg': [], 'skipped_big': [],
        'errors': 0,
    }

    for i, rec in enumerate(records, 1):
        rid = str(rec.get('id') or '').strip()
        fname = (rec.get('fname') or '').strip() or f'{rid}.bin'
        reg = extract_reg(rec.get('reg'))
        label = (rec.get('label') or '').strip()
        try:
            fpath = id_index.get(rid)
            if not fpath:
                if len(summary['file_missing']) < 20:
                    summary['file_missing'].append(rid)
                continue

            # Match client whenever we have a reg_lookup (both modes).
            client_id = lookup_client_id(reg_lookup, reg) if reg_lookup else None
            if reg_lookup and not client_id:
                if len(summary['unmatched_reg']) < 40:
                    summary['unmatched_reg'].append(reg or str(rec.get('reg')))
                continue

            try:
                size = os.path.getsize(fpath)
            except Exception:
                size = 0
            if size > MAX_FILE_SIZE_MB * 1024 * 1024:
                summary['skipped_big'].append((fname, size))
                continue

            doc_type = label or fname
            # Use the original Zoho filename for display/key; the on-disk
            # name is the record id, which we don't want to surface.
            ext = os.path.splitext(fname)[1].lower() or os.path.splitext(fpath)[1].lower()
            content_type = EXT_TO_MIME.get(ext, 'application/octet-stream')

            if dry_run:
                summary['uploaded'] += 1
                continue

            with open(fpath, 'rb') as fh:
                data = fh.read()

            r2_key = storage.make_doc_key('plab', reg or f'client_{client_id}', 'Certificate', fname)
            if not storage.upload_bytes(r2_key, data, content_type):
                print(f"  R2 upload failed: {fname}")
                summary['errors'] += 1
                continue

            inserted = False
            for attempt in range(3):
                try:
                    conn.execute(
                        "INSERT INTO plab_client_documents "
                        "  (client_id, doc_type, doc_category, file_name, file_path, "
                        "   file_size, content_type, status, uploaded_by) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'uploaded', 'cert_import')",
                        (client_id, doc_type, 'certificate', fname, r2_key,
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
                        print(f"  insert retry {attempt+1} for {fname}: {e}")
                        time.sleep(2 ** attempt)
                        try:
                            conn.close()
                        except Exception:
                            pass
                        conn = get_db()
                    else:
                        print(f"  insert failed {fname}: {e}")
                        storage.delete_object(r2_key)
                        summary['errors'] += 1
            if inserted:
                summary['uploaded'] += 1
        except Exception as e:
            print(f"  record {i} error ({rid}): {e}")
            summary['errors'] += 1

        if i % 25 == 0 or i == len(records):
            print(f"  progress: {i}/{len(records)} (uploaded={summary['uploaded']}, "
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
    print(f"  Manifest records:          {summary['records']}")
    print(f"  Uploaded / inserted:       {summary['uploaded']}")
    print(f"  File not found in folder:  {len(summary['file_missing'])}  {summary['file_missing'][:5]}")
    print(f"  Client not matched:        {len(summary['unmatched_reg'])}  {summary['unmatched_reg'][:5]}")
    print(f"  Skipped (>{MAX_FILE_SIZE_MB} MB):          {len(summary['skipped_big'])}  {[f for f,_ in summary['skipped_big'][:5]]}")
    print(f"  Errors:                    {summary['errors']}")


if __name__ == '__main__':
    main()
