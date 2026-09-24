"""goocampus.in Events — in-person sessions with their own "Reserve your seat"
registration (SEPARATE from the counsellor-callback client flow). Each registration
gets a unique printable ticket code. (founder 2026-09-24)
"""
import logging
from db import get_db


def ensure_event_tables():
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_events (
            id SERIAL PRIMARY KEY,
            slug TEXT UNIQUE,
            title TEXT DEFAULT '',
            venue TEXT DEFAULT '',
            city TEXT DEFAULT '',
            state TEXT DEFAULT '',
            event_date TEXT DEFAULT '',        -- YYYY-MM-DD (display only)
            event_time TEXT DEFAULT '',
            description TEXT DEFAULT '',
            ticket_prefix TEXT DEFAULT 'GCE',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_event_registrations (
            id SERIAL PRIMARY KEY,
            event_id INTEGER NOT NULL,
            ticket_code TEXT,                  -- unique printable id, e.g. GCE-00042
            name TEXT DEFAULT '',
            email TEXT DEFAULT '',
            mobile TEXT DEFAULT '',
            rank INTEGER,                      -- optional
            score INTEGER,                     -- optional
            domicile_state TEXT DEFAULT '',
            college TEXT DEFAULT '',
            target_speciality TEXT DEFAULT '',
            city TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            extra TEXT DEFAULT '',             -- JSON, any additional fields
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pg_event_ticket ON pg_event_registrations (ticket_code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_event_reg_event ON pg_event_registrations (event_id)")
        # Link a registration to the logged-in doctor (their "my tickets" list) + a
        # per-event "Powered by" line for the ticket. (founder 2026-09-25)
        conn.execute("ALTER TABLE pg_event_registrations ADD COLUMN IF NOT EXISTS user_id INTEGER")
        conn.execute("ALTER TABLE pg_events ADD COLUMN IF NOT EXISTS powered_by TEXT DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_event_reg_user ON pg_event_registrations (user_id)")
        conn.commit()
        logging.info("pg_events tables ensured")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_event_tables: {e}")
    finally:
        try: conn.close()
        except Exception: pass
