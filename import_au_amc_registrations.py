"""
One-time import: AMC Pathway AMC Registrations from
imports/Australia All Amc Registrations.xlsx (X-2 / X-2b).

Excel updated 2026-06-03 to a version with the GCAUSIP reg# embedded
in the candidate-name suffix:
    " Dr. SALONI  MAHAJAN  -GCAUSIP/25-26/28"

The importer extracts the reg# from the name string and matches it
against plab_clients WHERE pathway='australia'. Because the source
Excels mix 2-digit and 3-digit suffix padding (e.g. /24 vs /021),
the importer tries a few padding variants for each reg# before
giving up. A few rows whose names match a client but whose reg# is
malformed fall back to name-matching as a last resort.

Marker: au_amc_registrations_seeded = v2_reg_extract_153

Invoked from app.py boot via
run_import_au_amc_registrations_once(get_db).
"""

import logging
import os
import re
from datetime import datetime, date


EXCEL_FILENAME = 'Australia All Amc Registrations.xlsx'
IMPORT_VERSION = 'v2_reg_extract_153'
MARKER_KEY = 'au_amc_registrations_seeded'


COL_NAME       = 0
COL_AMC_REF    = 1
COL_LOGIN_PWD  = 2
COL_AMC_SETUP  = 3
COL_REG_DATE   = 4
COL_ADDED_BY   = 5
COL_MODIFIED   = 6


_REG_RE = re.compile(r'GCAUSIP/\d{1,4}(?:-\d{2,4})?/\d{1,4}', re.IGNORECASE)
_REG_SPLIT_RE = re.compile(
    r'^(GCAUSIP)/(\d{1,4}(?:-\d{2,4})?)/(\d{1,4})$', re.IGNORECASE)
_PREFIX_RE = re.compile(r'^(dr|mr|mrs|ms|prof)\.?\s+', re.IGNORECASE)


def _ss(v):
    if v is None: return ''
    if isinstance(v, float) and v == int(v): return str(int(v))
    return str(v).strip()


def _sd(v):
    if v is None: return ''
    if isinstance(v, (datetime, date)): return v.strftime('%Y-%m-%d')
    return str(v).strip().split(' ')[0]


def _extract_reg(value):
    """Extract GCAUSIP/.../... reg# from any string. Returns canonical-case
    (UPPER) form, or None."""
    if not value:
        return None
    m = _REG_RE.search(str(value))
    return m.group(0).upper() if m else None


def _reg_variants(reg):
    """Yield lookup variants of a reg# to handle padding and middle-
    format differences between the source Excel and plab_clients.

    Two kinds of inconsistency:
      a) Padding: /24 vs /024 vs /0024 vs /4
      b) Middle format: YYYY (2023) vs YY-YY (23-24)

    For GCAUSIP/25-26/24 yields:
        GCAUSIP/25-26/24, GCAUSIP/25-26/024, ...

    For GCAUSIP/2023/049 yields:
        GCAUSIP/2023/049, GCAUSIP/2023/49, ...
        AND
        GCAUSIP/23-24/049, GCAUSIP/23-24/49, ...   (YYYY -> YY-YY)
    """
    if not reg:
        return
    seen = set()
    def emit(v):
        if v and v not in seen:
            seen.add(v)
            return v
        return None

    out = emit(reg)
    if out: yield out

    m = _REG_SPLIT_RE.match(reg)
    if not m:
        return
    prefix, middle, tail = m.group(1), m.group(2), m.group(3)
    try:
        n = int(tail)
    except ValueError:
        return

    # Build the set of middle-format variants for this reg#:
    middles = [middle]
    if '-' not in middle and middle.isdigit() and len(middle) == 4:
        # YYYY -> YY-YY (calendar year -> Indian FY pair starting that
        # year). E.g. 2023 -> 23-24.
        y = int(middle)
        yy = y % 100
        yy_next = (y + 1) % 100
        middles.append(f"{yy:02d}-{yy_next:02d}")
    elif '-' in middle:
        # YY-YY -> YYYY of the starting year. E.g. 23-24 -> 2023.
        start = middle.split('-', 1)[0]
        if start.isdigit() and len(start) == 2:
            yy = int(start)
            # naive: assume 2000s
            middles.append(f"20{yy:02d}")

    # Cross-product with padding variants.
    for md in middles:
        for pad in (3, 4, 2, 1):
            v = emit(f"{prefix}/{md}/{n:0{pad}d}")
            if v: yield v


def _normalize_name(name):
    """Strip 'Dr.' / 'Mr.', strip the reg# suffix, collapse whitespace,
    lowercase. Used as the name-fallback when reg# extraction or DB
    lookup fails."""
    if not name:
        return ''
    n = str(name)
    # Strip trailing "-GCAUSIP/..." reg suffix if present.
    n = re.split(r'\s*-\s*GCAUSIP/', n, maxsplit=1)[0]
    n = _PREFIX_RE.sub('', n.strip())
    n = re.sub(r'\s+', ' ', n)
    return n.lower()


def run_import_au_amc_registrations_once(get_db_fn):
    """Idempotent import of the AMC pathway AMC Registrations Excel.

    1. Marker check -- bail if already at IMPORT_VERSION.
    2. Build both a reg# set AND a name -> reg# map from
       plab_clients WHERE pathway='australia' so lookups are O(1).
    3. Walk Excel rows. For each:
         a. Extract GCAUSIP reg# from the candidate-name suffix.
         b. Try the literal reg# then padding variants against the
            client set.
         c. If still no match, try name-matching as a fallback.
       Successful match -> INSERT into ops_amc_registration with
       pathway='australia'. Unmatched -> skip + log example.
    4. Wipe any existing pathway='australia' rows beforehand so
       re-imports stay clean.
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

        # Build the lookup pools from plab_clients
        reg_set = set()
        name_to_reg = {}
        try:
            for r in conn.execute(
                "SELECT registration_number, prefix, first_name, last_name "
                "  FROM plab_clients "
                " WHERE COALESCE(pathway,'plab') = 'australia' "
                "   AND registration_number IS NOT NULL "
                "   AND registration_number != ''"
            ).fetchall():
                rn = (r['registration_number'] or '').strip().upper()
                if not rn:
                    continue
                reg_set.add(rn)
                full = " ".join(filter(None, [
                    r['first_name'] or '', r['last_name'] or ''
                ]))
                key = _normalize_name(full)
                if key and key not in name_to_reg:
                    name_to_reg[key] = rn
        except Exception as e:
            logging.error(f"au_amc registrations: lookup pool: {e}")
            return {'inserted': 0, 'skipped': 0, 'errors': 1}

        logging.info(
            f"au_amc registrations import: starting {IMPORT_VERSION} "
            f"(pool: {len(reg_set)} reg#s, {len(name_to_reg)} names)")

        wb = openpyxl.load_workbook(
            excel_path, read_only=True, data_only=True)
        ws = wb.active

        # Belt-and-braces: ensure the target table exists in its own
        # transaction (S-3 fix 2 pattern).
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

        inserted = skipped = errors = recovered_via_name = matched_via_variant = 0
        unmatched_examples = []

        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not any(c not in (None, '') for c in row):
                continue
            raw_name = _ss(row[COL_NAME])
            if not raw_name:
                skipped += 1
                continue

            # 1. Try reg# extracted from the name suffix.
            extracted = _extract_reg(raw_name)
            matched_reg = None
            for variant in _reg_variants(extracted):
                if variant in reg_set:
                    matched_reg = variant
                    if variant != extracted:
                        matched_via_variant += 1
                    break

            # 2. Fallback to name-matching if reg# lookup failed.
            if not matched_reg:
                key = _normalize_name(raw_name)
                if key in name_to_reg:
                    matched_reg = name_to_reg[key]
                    recovered_via_name += 1
                    logging.info(
                        f"au_amc registrations: reg# '{extracted}' not in DB, "
                        f"recovered via name '{key}' -> {matched_reg}"
                    )

            if not matched_reg:
                if len(unmatched_examples) < 5:
                    unmatched_examples.append(raw_name[:60])
                skipped += 1
                continue

            try:
                added_by = _ss(row[COL_ADDED_BY]) if len(row) > COL_ADDED_BY else ''
                modified = _ss(row[COL_MODIFIED]) if len(row) > COL_MODIFIED else ''
                notes_bits = []
                if added_by: notes_bits.append(f"added: {added_by}")
                if modified: notes_bits.append(f"modified: {modified}")
                notes = ("Imported from Excel" if not notes_bits
                         else f"Imported from Excel ({', '.join(notes_bits)})")
                conn.execute("""
                    INSERT INTO ops_amc_registration (
                        registration_number, amc_reference_number,
                        login_pwd, amc_setup, registration_date,
                        notes, pathway
                    ) VALUES (?,?,?,?,?,?,'australia')
                """, (
                    matched_reg,
                    _ss(row[COL_AMC_REF]) if len(row) > COL_AMC_REF else '',
                    _ss(row[COL_LOGIN_PWD]) if len(row) > COL_LOGIN_PWD else '',
                    _ss(row[COL_AMC_SETUP]) if len(row) > COL_AMC_SETUP else '',
                    _sd(row[COL_REG_DATE]) if len(row) > COL_REG_DATE else '',
                    notes,
                ))
                inserted += 1
            except Exception as e:
                logging.warning(
                    f"au_amc registrations insert ({raw_name[:50]}): {e}")
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

        if unmatched_examples:
            logging.info(
                f"au_amc registrations import: {skipped} unmatched row(s) -- "
                f"examples: {'; '.join(unmatched_examples)}"
            )
        logging.info(
            f"au_amc registrations import: inserted {inserted} "
            f"({matched_via_variant} via padding variant, "
            f"{recovered_via_name} via name-fallback), "
            f"skipped {skipped}, errors {errors}"
        )
        return {'inserted': inserted, 'skipped': skipped,
                'errors': errors,
                'matched_via_variant': matched_via_variant,
                'recovered_via_name': recovered_via_name}
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
