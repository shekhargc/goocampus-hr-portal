"""
bulk_import_documents.py -- run LOCALLY (not on Render) to bulk-import
PLAB and AMC client documents from local folders into the staging
Postgres plab_client_documents table.

Why local-only:
  Each pathway folder is ~300-800 MB. Committing 1.1GB of binary
  files to git is not viable. Instead this script reads files
  straight from the user's Downloads, connects to the staging
  Postgres via DATABASE_URL, and INSERTs the bytes into the BYTEA
  column file_data on plab_client_documents.

Usage:
    DATABASE_URL=postgresql://... python3 bulk_import_documents.py \
        --pathway plab \
        --folder "/Users/Santosh/Downloads/Plab Pathway client documents"

    DATABASE_URL=postgresql://... python3 bulk_import_documents.py \
        --pathway australia \
        --folder "/Users/Santosh/Downloads/AMC Pathway client Documents"

Behavior:
  1. Wipe all rows from plab_client_documents WHERE the linked
     plab_clients.pathway matches --pathway.
  2. Walk the folder. For each file:
     - Parse filename to extract reg# + doc type.
     - Look up plab_clients by reg# (with padding-variant fallback).
     - Read file bytes, derive content_type from extension.
     - INSERT into plab_client_documents with file_data populated.
     - For "Photograph" docs, also UPDATE plab_clients.photo_path
       to point at the doc-serve route so the profile avatar
       picks it up.
  3. Print a summary: per-doc-type insert count, unmatched files,
     etc.

Idempotent for re-runs: wipe-and-rebuild every time. Safe to run
again if files in the folder change.
"""

import argparse
import logging
import os
import re
import sys

import psycopg2
import psycopg2.extras


# ─────────────────────────────────────────────────────────────────────
#  Document-type canonicalisation
# ─────────────────────────────────────────────────────────────────────
# Map filename suffixes (with underscores) to canonical doc_type
# values matching app.py's PLAB_DOC_TYPES. Right side carries
# (canonical_name, category).
SUFFIX_TO_DOCTYPE = {
    # Personal
    'Aadhar_Copy_Optional':       ('Aadhar Copy (Optional)',     'personal'),
    'Pasport':                    ('Passport Copy (Front)',      'personal'),
    'Passport':                   ('Passport Copy (Front)',      'personal'),
    'Passport_Copy_Front':        ('Passport Copy (Front)',      'personal'),
    'Passport_Copy_Back':         ('Passport Copy (Back)',       'personal'),
    'Photograph':                 ('Photograph',                 'personal'),
    'Passport_Size_Photgraph':    ('Passport size Photograph',   'personal'),
    'Passport_Size_Photograph':   ('Passport size Photograph',   'personal'),
    # Academic
    'MBBS_Final_Certificate':            ('MBBS Final Certificate',            'academic'),
    'MBBS_Course_Completion_Certificate':('MBBS Course Completion Certificate','academic'),
    'Internship_Certificate':            ('Internship Certificate',            'academic'),
    'Internship_Certificate1':           ('Internship Certificate',            'academic'),
    'Internship_Centificate':            ('Internship Certificate',            'academic'),  # typo in source
    'State_Registration_Certificate':    ('State Registration Certificate',    'academic'),
}
# Sort suffixes by length DESC so longest match wins (e.g.
# "MBBS_Course_Completion_Certificate" should match before
# "MBBS_Final_Certificate" if any prefix collision).
_SORTED_SUFFIXES = sorted(SUFFIX_TO_DOCTYPE.keys(), key=len, reverse=True)


EXT_TO_MIME = {
    '.jpg':  'image/jpeg', '.jpeg': 'image/jpeg', '.png':  'image/png',
    '.gif':  'image/gif',  '.webp': 'image/webp',
    '.pdf':  'application/pdf',
    '.doc':  'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}


# ─────────────────────────────────────────────────────────────────────
#  Filename parsers per pathway
# ─────────────────────────────────────────────────────────────────────
# PLAB:  GCUKIP-YY-YY-NNN_<DOC_TYPE>[ (n)].<ext>
_PLAB_RE = re.compile(
    r'^(GCUKIP)-(\d{1,4}(?:-\d{2,4})?)-(\d{1,4})_(.+?)(?:\s\(\d+\))?\.([a-zA-Z]+)$'
)

# AMC:  GC_Australia_Client_Docs_<REG_WITH_UNDERSCORES>_<NAME>_<DOC_TYPE>__<orig_name>.<ext>
# Reg uses underscores: GCAUSIP_2023_011 or GCAUSIP_24-25_007
_AMC_RE = re.compile(
    r'^GC_Australia_Client_Docs_GCAUSIP_(\d{2,4}(?:-\d{2,4})?)_(\d{1,4})_(.+?)__(.+)\.([a-zA-Z]+)$'
)


def _parse_plab_filename(fname):
    """Return (reg_number, doc_type_canonical, doc_category, ext) or None."""
    m = _PLAB_RE.match(fname)
    if not m:
        return None
    middle, tail, doc_suffix, ext = m.group(2), m.group(3), m.group(4), m.group(5)
    reg = f"GCUKIP/{middle}/{tail}"
    canonical = _match_doc_type(doc_suffix)
    if not canonical:
        return None
    return reg, canonical[0], canonical[1], ext.lower()


def _parse_amc_filename(fname):
    """Return (reg_number, doc_type_canonical, doc_category, ext) or None."""
    m = _AMC_RE.match(fname)
    if not m:
        return None
    middle, tail, name_and_type, _orig, ext = (
        m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))
    reg = f"GCAUSIP/{middle}/{tail}"
    # name_and_type contains "<NAME>_<DOC_TYPE>". Match the doc type
    # as a SUFFIX (longest match wins).
    canonical = _match_doc_type_in_suffix(name_and_type)
    if not canonical:
        return None
    return reg, canonical[0], canonical[1], ext.lower()


def _match_doc_type(suffix):
    """Look up an EXACT doc-type suffix (e.g. 'Aadhar_Copy_Optional')."""
    return SUFFIX_TO_DOCTYPE.get(suffix)


def _match_doc_type_in_suffix(name_and_type):
    """For AMC filenames, find which doc-type-suffix is at the end of
    name_and_type. Returns the canonical (name, category) or None."""
    for sfx in _SORTED_SUFFIXES:
        if name_and_type.endswith('_' + sfx) or name_and_type == sfx:
            return SUFFIX_TO_DOCTYPE[sfx]
    return None


# ─────────────────────────────────────────────────────────────────────
#  Reg# lookup against plab_clients (with padding-variant fallback)
# ─────────────────────────────────────────────────────────────────────
_REG_SPLIT_RE = re.compile(r'^(GCUKIP|GCAUSIP)/(\d{1,4}(?:-\d{2,4})?)/(\d{1,4})$')


def _reg_variants(reg):
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
    seen = {reg}
    for md in middles:
        for pad in (3, 4, 2, 1):
            v = f"{prefix}/{md}/{n:0{pad}d}"
            if v not in seen:
                seen.add(v)
                yield v


def lookup_client_id(conn, reg):
    cur = conn.cursor()
    for variant in _reg_variants(reg):
        cur.execute(
            "SELECT id FROM plab_clients WHERE UPPER(registration_number) = UPPER(%s) LIMIT 1",
            (variant,))
        row = cur.fetchone()
        if row:
            cur.close()
            return row[0], variant
    cur.close()
    return None, None


# ─────────────────────────────────────────────────────────────────────
#  Main import
# ─────────────────────────────────────────────────────────────────────
MAX_FILE_SIZE_MB = 12   # Skip files larger than this; logged.


def _connect(db_url):
    """Return an autocommit connection with keepalive tuning. Lives in
    its own function so the import loop can call it on reconnect."""
    conn = psycopg2.connect(
        db_url,
        sslmode='require',
        connect_timeout=30,
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
    )
    conn.autocommit = True
    return conn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pathway', required=True, choices=['plab', 'australia'])
    ap.add_argument('--folder', required=True, help='Local folder with the document files.')
    ap.add_argument('--dry-run', action='store_true', help='Parse only -- do not write to DB.')
    ap.add_argument('--no-wipe', action='store_true', help='Skip the pre-import wipe step.')
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    db_url = os.environ.get('DATABASE_URL')
    if not db_url and not args.dry_run:
        print('ERROR: DATABASE_URL env var required (or use --dry-run).', file=sys.stderr)
        sys.exit(1)

    parser = _parse_plab_filename if args.pathway == 'plab' else _parse_amc_filename

    folder = args.folder
    if not os.path.isdir(folder):
        print(f'ERROR: folder not found: {folder}', file=sys.stderr)
        sys.exit(1)
    files = sorted(os.listdir(folder))
    logging.info(f"Scanning {len(files)} entries in {folder}")

    conn = None
    if not args.dry_run:
        conn = _connect(db_url)

    # 1. Wipe existing rows for this pathway
    if conn and not args.no_wipe:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM plab_client_documents "
            "WHERE client_id IN ("
            "  SELECT id FROM plab_clients WHERE COALESCE(pathway,'plab') = %s)",
            (args.pathway,))
        wiped = cur.rowcount
        cur.close()
        logging.info(f"Wiped {wiped} existing {args.pathway} document rows")

    summary = {
        'parsed': 0, 'unparsed_filenames': [],
        'inserted': 0, 'photo_updated': 0,
        'unmatched_reg': [], 'errors': 0,
        'skipped_too_big': [],
        'doc_type_counts': {},
    }

    files_to_process = [f for f in files
                        if os.path.isfile(os.path.join(folder, f))
                        and not f.startswith('.')
                        and not f.endswith('.xlsx')]
    total_to_process = len(files_to_process)

    for i, fname in enumerate(files_to_process, 1):
        parsed = parser(fname)
        if not parsed:
            if len(summary['unparsed_filenames']) < 10:
                summary['unparsed_filenames'].append(fname)
            continue
        reg, doc_type, doc_category, ext = parsed
        summary['parsed'] += 1
        summary['doc_type_counts'][doc_type] = summary['doc_type_counts'].get(doc_type, 0) + 1

        if args.dry_run:
            continue

        fpath = os.path.join(folder, fname)
        try:
            size = os.path.getsize(fpath)
        except Exception:
            size = 0
        if size > MAX_FILE_SIZE_MB * 1024 * 1024:
            logging.info(f"  [{i}/{total_to_process}] SKIP {fname} ({size/1024/1024:.1f} MB > {MAX_FILE_SIZE_MB} MB)")
            summary['skipped_too_big'].append((fname, size))
            continue

        try:
            with open(fpath, 'rb') as f:
                data = f.read()
        except Exception as e:
            logging.warning(f"  read failed {fname}: {e}")
            summary['errors'] += 1
            continue

        # Insert with up to 3 reconnect attempts on connection errors.
        for attempt in range(3):
            try:
                client_id, _ = lookup_client_id(conn, reg)
                if not client_id:
                    if len(summary['unmatched_reg']) < 10:
                        summary['unmatched_reg'].append(reg)
                    break  # not retriable
                content_type = EXT_TO_MIME.get('.' + ext.lower(), 'application/octet-stream')
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO plab_client_documents
                           (client_id, doc_type, doc_category, file_name, file_path,
                            file_size, file_data, content_type, status, uploaded_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'uploaded', 'bulk_import_2026_06_03')
                       RETURNING id""",
                    (client_id, doc_type, doc_category, fname, f"{args.pathway}/{fname}",
                     len(data), psycopg2.Binary(data), content_type))
                doc_id = cur.fetchone()[0]
                summary['inserted'] += 1
                if doc_type == 'Photograph':
                    cur.execute(
                        "UPDATE plab_clients SET photo_path = %s WHERE id = %s",
                        (f"/operations/plab/doc/{doc_id}/file", client_id))
                    summary['photo_updated'] += 1
                cur.close()
                break  # success
            except (psycopg2.InterfaceError, psycopg2.OperationalError) as e:
                logging.warning(f"  conn error on {fname} attempt {attempt+1}: {e}")
                try: conn.close()
                except Exception: pass
                if attempt < 2:
                    import time as _t; _t.sleep(2 ** attempt)
                    try:
                        conn = _connect(db_url)
                        logging.info("  reconnected.")
                    except Exception as ce:
                        logging.error(f"  reconnect failed: {ce}")
                else:
                    summary['errors'] += 1
            except Exception as e:
                logging.warning(f"  insert failed {fname}: {e}")
                summary['errors'] += 1
                break

        if i % 25 == 0 or i == total_to_process:
            logging.info(
                f"  progress: {i}/{total_to_process} "
                f"(inserted={summary['inserted']}, "
                f"errors={summary['errors']}, "
                f"skipped_big={len(summary['skipped_too_big'])})")

    if conn:
        try: conn.close()
        except Exception: pass

    # ── Summary ──
    print()
    print(f"=== Bulk Import Summary ({args.pathway}) ===")
    print(f"  Files scanned:              {len(files)}")
    print(f"  Parsed successfully:        {summary['parsed']}")
    print(f"  Unparsed filename samples:  {summary['unparsed_filenames']}")
    print(f"  Inserted into DB:           {summary['inserted']}")
    print(f"  Photo path updates:         {summary['photo_updated']}")
    print(f"  Unmatched reg# (no client): {len(summary['unmatched_reg'])} ({summary['unmatched_reg'][:5]})")
    print(f"  Insert errors:              {summary['errors']}")
    print(f"  Doc type breakdown:")
    for k, v in sorted(summary['doc_type_counts'].items(), key=lambda x: -x[1]):
        print(f"    {v:4d}  {k}")


if __name__ == '__main__':
    main()
