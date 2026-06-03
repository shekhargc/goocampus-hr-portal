"""
One-time import: AMC Pathway AMC Registrations from
imports/Australia All Amc Registrations.xlsx (X-2).

The Excel has 152 candidate rows but NO embedded registration_number
(just "Dr. <name>"), so we resolve reg# by name-matching against
plab_clients WHERE pathway='australia'. Unmatched rows are logged
and skipped (admin can fix the source name or add a manual mapping
later).

Marker: au_amc_registrations_seeded = v1_initial_152

Invoked from app.py boot via
run_import_au_amc_registrations_once(get_db).
"""

import logging
import os
import re
from datetime import datetime, date


EXCEL_FILENAME = 'Australia All Amc Registrations.xlsx'
IMPORT_VERSION = 'v1_initial_152'
MARKER_KEY = 'au_amc_registrations_seeded'


# Excel column indices (0-based)
COL_NAME       = 0
COL_AMC_REF    = 1
COL_LOGIN_PWD  = 2
COL_AMC_SETUP  = 3
COL_REG_DATE   = 4
COL_ADDED_BY   = 5
COL_MODIFIED   = 6


def _ss(v):
    if v is None: return ''
    if isinstance(v, float) and v == int(v): return str(int(v))
    return str(v).strip()


def _sd(v):
    if v is None: return ''
    if isinstance(v, (datetime, date)): return v.strftime('%Y-%m-%d')
    return str(v).strip().split(' ')[0]


_PREFIX_RE = re.compile(r'^(dr|mr|mrs|ms|prof)\.?\s+', re.IGNORECASE)


def _normalize_name(name):
    """Strip 'Dr.' / 'Mr.' etc., collapse whitespace, lowercase.

    Two name strings normalize to the same key only if they refer to
    the same person, e.g.:
        'Dr.  SALONI MAHAJAN ' -> 'saloni mahajan'
        'Dr. Saloni Mahajan'   -> 'saloni mahajan'
    Punctuation and double spaces are normalised so minor formatting
    differences between the Excel and plab_clients don't break the
    match.
    """
    if not name:
        return ''
    n = _PREFIX_RE.sub('', str(name).strip())
    n = re.sub(r'\s+', ' ', n)
    return n.lower()


def run_import_au_amc_registrations_once(get_db_fn):
    """Idempotent import of the AMC pathway AMC Registrations Excel.

    1. Marker check -- bail if already at IMPORT_VERSION.
    2. Build name -> reg# map from plab_clients WHERE pathway='australia'.
    3. Walk Excel rows, normalize the candidate name, look up reg#.
    4. INSERT into ops_amc_registration (pathway='australia') -- skip
       rows whose name doesn't match any australia client.
    5. Set marker.
    """
    excel_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'imports', EXCEL_FILENAME,
    )
    if not os.path.exists(excel_path):
        logging.info("au_amc registrations import: no Excel found, skipping")
        return {'inserted': 0, 'skipped': 0, 'errors': 0}

    conn = None
    try:
        import openpyxl
        conn = get_db_fn()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS _import_markers "
                "(key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
        marker = conn.execute(
            "SELECT value FROM _import_markers WHERE key = ?",
            (MARKER_KEY,),
        ).fetchone()
        if marker and marker['value'] == IMPORT_VERSION:
            logging.info(
                f"au_amc registrations import: already at {IMPORT_VERSION}, skipping")
            return {'inserted': 0, 'skipped': 0, 'errors': 0}

        # Build name -> reg# map from australia clients
        name_to_reg = {}
        try:
            for r in conn.execute(
                "SELECT registration_number, prefix, first_name, last_name "
                "  FROM plab_clients "
                " WHERE COALESCE(pathway,'plab') = 'australia' "
                "   AND registration_number IS NOT NULL "
                "   AND registration_number != ''"
            ).fetchall():
                full = " ".join(filter(None, [
                    r['first_name'] or '', r['last_name'] or ''
                ]))
                key = _normalize_name(full)
                if key and key not in name_to_reg:
                    name_to_reg[key] = r['registration_number']
        except Exception as e:
            logging.error(f"au_amc registrations: name map fetch: {e}")
            return {'inserted': 0, 'skipped': 0, 'errors': 1}

        logging.info(
            f"au_amc registrations import: starting {IMPORT_VERSION} "
            f"(mapping pool = {len(name_to_reg)} australia clients)")

        wb = openpyxl.load_workbook(
            excel_path, read_only=True, data_only=True)
        ws = wb.active

        # Pre-fix the ops_amc_registration table -- mirror the same
        # standalone-CREATE trick from S-3 fix 2 so this importer works
        # even if the main ensure_ops_tables block was aborted earlier
        # in boot. Idempotent.
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ops_amc_registration (
                    id SERIAL PRIMARY KEY,
                    registration_number TEXT REFERENCES plab_clients(registration_number),
                    amc_reference_number TEXT,
                    login_pwd TEXT,
                    secret_question TEXT,
                    secret_answer TEXT,
                    amc_setup TEXT,
                    registration_date TEXT,
                    english_exam TEXT,
                    exam_date TEXT,
                    english_result_expiry_date TEXT,
                    license TEXT,
                    license_received_date TEXT,
                    candidate_email TEXT,
                    mobile_number TEXT,
                    notes TEXT,
                    pathway TEXT,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """)
            conn.commit()
        except Exception as e:
            logging.warning(f"au_amc registrations: table ensure: {e}")
            try: conn.rollback()
            except Exception: pass

        # Wipe any existing pathway='australia' rows so re-runs don't
        # double-write (mirrors S-3 fix 3b pattern).
        try:
            conn.execute(
                "DELETE FROM ops_amc_registration "
                " WHERE COALESCE(pathway,'plab') = 'australia'"
            )
            conn.commit()
        except Exception as e:
            logging.warning(f"au_amc registrations: pre-import wipe: {e}")
            try: conn.rollback()
            except Exception: pass

        inserted = skipped = errors = 0
        unmatched_names = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not any(c not in (None, '') for c in row):
                continue
            raw_name = _ss(row[COL_NAME])
            if not raw_name:
                skipped += 1
                continue
            key = _normalize_name(raw_name)
            reg = name_to_reg.get(key)
            if not reg:
                unmatched_names.append(raw_name)
                skipped += 1
                continue
            try:
                conn.execute("""
                    INSERT INTO ops_amc_registration (
                        registration_number, amc_reference_number,
                        login_pwd, amc_setup, registration_date,
                        notes, pathway
                    ) VALUES (?,?,?,?,?,?,'australia')
                """, (
                    reg,
                    _ss(row[COL_AMC_REF]) if len(row) > COL_AMC_REF else '',
                    _ss(row[COL_LOGIN_PWD]) if len(row) > COL_LOGIN_PWD else '',
                    _ss(row[COL_AMC_SETUP]) if len(row) > COL_AMC_SETUP else '',
                    _sd(row[COL_REG_DATE]) if len(row) > COL_REG_DATE else '',
                    # Stash the added/modified user metadata in the
                    # free-text notes column so we don't lose history.
                    "Imported from Excel ({}{})".format(
                        f"added: {_ss(row[COL_ADDED_BY])}" if len(row) > COL_ADDED_BY else '',
                        f", modified: {_ss(row[COL_MODIFIED])}" if len(row) > COL_MODIFIED and _ss(row[COL_MODIFIED]) else '',
                    ).strip(' (,)') or 'Imported from Excel',
                ))
                inserted += 1
            except Exception as e:
                logging.warning(f"au_amc registrations insert ({raw_name[:50]}): {e}")
                try: conn.rollback()
                except Exception: pass
                errors += 1

        conn.commit()

        # Mark done
        try:
            conn.execute(
                "INSERT INTO _import_markers (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (MARKER_KEY, IMPORT_VERSION),
            )
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
            try:
                conn.execute("DELETE FROM _import_markers WHERE key = ?", (MARKER_KEY,))
                conn.execute(
                    "INSERT INTO _import_markers (key, value) VALUES (?, ?)",
                    (MARKER_KEY, IMPORT_VERSION),
                )
                conn.commit()
            except Exception as e:
                logging.warning(f"au_amc registrations: marker write: {e}")

        if unmatched_names:
            # Log up to 5 example unmatched names so admin can see
            # which ones need manual attention.
            samples = "; ".join(unmatched_names[:5])
            logging.info(
                f"au_amc registrations import: {len(unmatched_names)} "
                f"name(s) did not match any australia client. "
                f"Examples: {samples}"
            )
        logging.info(
            f"au_amc registrations import: inserted {inserted}, "
            f"skipped {skipped} (no name match), errors {errors}"
        )
        return {'inserted': inserted, 'skipped': skipped, 'errors': errors}
    except Exception as e:
        logging.error(f"run_import_au_amc_registrations_once: {e}")
        try:
            if conn: conn.rollback()
        except Exception: pass
        return {'inserted': 0, 'skipped': 0, 'errors': 1}
    finally:
        try:
            if conn: conn.close()
        except Exception: pass
