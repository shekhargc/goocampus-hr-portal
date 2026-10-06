"""Per-authority document library for the NEET-PG counselling sections (founder 2026-10-06).

Each row is one uploaded document (registration doc, annexure/format, fee structure,
seat-matrix PDF, or other notification) attached to a counselling authority. The file
bytes live in Postgres (BYTEA) — same pattern as pg_seat_matrix_source — because Render
has no persistent disk. Served to the goocampus.in dashboard, grouped by category, and
only for authorities that actually have content.
"""

import logging

from db import get_db


def ensure_pg_authority_docs(conn=None):
    """Create the authority-documents table (Render cold-start safe). Call with no args at
    boot (opens its own connection) or with the request's conn as a per-request guard."""
    own = conn is None
    if own:
        conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_authority_docs (
            id SERIAL PRIMARY KEY,
            authority_code TEXT NOT NULL DEFAULT '',
            authority_name TEXT DEFAULT '',
            category TEXT NOT NULL DEFAULT 'other',
            title TEXT DEFAULT '',
            doc_date TEXT DEFAULT '',
            note TEXT DEFAULT '',
            file_name TEXT DEFAULT '',
            file_data BYTEA,
            file_content_type TEXT DEFAULT 'application/pdf',
            is_published BOOLEAN DEFAULT TRUE,
            sort_order INTEGER DEFAULT 0,
            uploaded_by TEXT DEFAULT '',
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_authority_docs_code ON pg_authority_docs (authority_code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_authority_docs_cat ON pg_authority_docs (authority_code, category)")
        conn.commit()
        logging.info("pg_authority_docs table ensured")
    except Exception as e:
        logging.error("ensure_pg_authority_docs: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        if own:
            try: conn.close()
            except Exception: pass
