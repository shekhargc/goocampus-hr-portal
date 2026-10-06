"""NEET-PG counselling Seat Matrix — raw authority data (founder 2026-09-30).

Stores an announced authority seat matrix (All India MCC first) EXACTLY as the
authority published it — college/course names verbatim, NOT matched to our 2025
college master (that mapping is a later backend job, keyed on the stable college
code). Kept fully separate from pg_college_master / pg_cutoffs so there is zero
risk to the predictor data.

Two tables:
  pg_seat_matrix         — one row per (college, course) line the authority lists
  pg_seat_matrix_source  — one row per (counselling_body, academic_year): the
                           original PDF (BYTEA) + load stats, so the dashboard can
                           offer "View the official authority PDF".
"""
import logging
from db import get_db


def ensure_pg_seat_matrix():
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_seat_matrix (
            id SERIAL PRIMARY KEY,
            counselling_body TEXT NOT NULL DEFAULT 'All India MCC',
            academic_year TEXT NOT NULL DEFAULT '2026-27',
            sl_no INTEGER,
            college_code TEXT DEFAULT '',
            state TEXT DEFAULT '',
            college_name TEXT DEFAULT '',
            category TEXT DEFAULT '',
            course_name TEXT DEFAULT '',
            seats INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_seat_matrix_body_year "
                     "ON pg_seat_matrix (counselling_body, academic_year)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_seat_matrix_state ON pg_seat_matrix (state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_seat_matrix_category ON pg_seat_matrix (category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_seat_matrix_code ON pg_seat_matrix (college_code)")

        conn.execute('''CREATE TABLE IF NOT EXISTS pg_seat_matrix_source (
            id SERIAL PRIMARY KEY,
            counselling_body TEXT NOT NULL DEFAULT 'All India MCC',
            academic_year TEXT NOT NULL DEFAULT '2026-27',
            source_file_name TEXT DEFAULT '',
            pdf_name TEXT DEFAULT '',
            pdf_data BYTEA,
            pdf_content_type TEXT DEFAULT 'application/pdf',
            row_count INTEGER DEFAULT 0,
            college_count INTEGER DEFAULT 0,
            total_seats INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            uploaded_by TEXT DEFAULT '',
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_seat_matrix_source "
                     "ON pg_seat_matrix_source (counselling_body, academic_year)")
        # Explicit authority link (so a matrix ties to a counselling authority by its stable
        # code, not a fuzzy name match). (founder 2026-10-06)
        conn.execute("ALTER TABLE pg_seat_matrix ADD COLUMN IF NOT EXISTS authority_code TEXT DEFAULT ''")
        conn.execute("ALTER TABLE pg_seat_matrix_source ADD COLUMN IF NOT EXISTS authority_code TEXT DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_seat_matrix_auth ON pg_seat_matrix (authority_code)")
        # Backfill the existing All-India/MCC data to the 'mcc' authority (idempotent).
        # NB: no literal % in LIKE (psycopg2 would choke with no bound params) — use strpos.
        _mcc_where = ("WHERE COALESCE(authority_code,'')='' AND "
                      "(strpos(upper(COALESCE(counselling_body,'')),'MCC')>0 "
                      "OR strpos(upper(COALESCE(counselling_body,'')),'ALL INDIA')>0)")
        conn.execute("UPDATE pg_seat_matrix SET authority_code='mcc' " + _mcc_where)
        conn.execute("UPDATE pg_seat_matrix_source SET authority_code='mcc' " + _mcc_where)
        conn.commit()
        logging.info("pg_seat_matrix tables ensured")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_pg_seat_matrix: {e}")
    finally:
        try: conn.close()
        except Exception: pass
