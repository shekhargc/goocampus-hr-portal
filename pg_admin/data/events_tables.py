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
        # Close registration for a past event WITHOUT hiding it (recap page + ticket
        # reprint keep working; only NEW registrations are rejected). (founder 2026-10-04)
        conn.execute("ALTER TABLE pg_events ADD COLUMN IF NOT EXISTS reg_closed INTEGER DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_event_reg_user ON pg_event_registrations (user_id)")
        # Team working-list fields per registrant — set from the Events admin while the
        # team works the attendee list (NOT filled by the registrant). (founder 2026-10-04)
        #   attendance     : '' | 'attended' | 'not_attended'
        #   session_mode   : '' | 'offline' | 'online'   (how they attended / preferred)
        #   contact_status : '' | 'not_spoken' | 'spoken' | 'completed'
        #   staff_notes    : free text by the team (separate from the registrant's own `notes`)
        conn.execute("ALTER TABLE pg_event_registrations ADD COLUMN IF NOT EXISTS attendance TEXT DEFAULT ''")
        conn.execute("ALTER TABLE pg_event_registrations ADD COLUMN IF NOT EXISTS session_mode TEXT DEFAULT ''")
        conn.execute("ALTER TABLE pg_event_registrations ADD COLUMN IF NOT EXISTS contact_status TEXT DEFAULT ''")
        conn.execute("ALTER TABLE pg_event_registrations ADD COLUMN IF NOT EXISTS staff_notes TEXT DEFAULT ''")
        # Audit: who last edited the working-list fields + when (UTC, displayed IST). So the
        # team knows which member updated a registrant's attendance/notes. (founder 2026-10-05)
        conn.execute("ALTER TABLE pg_event_registrations ADD COLUMN IF NOT EXISTS edited_by TEXT DEFAULT ''")
        conn.execute("ALTER TABLE pg_event_registrations ADD COLUMN IF NOT EXISTS edited_by_id INTEGER")
        conn.execute("ALTER TABLE pg_event_registrations ADD COLUMN IF NOT EXISTS edited_at TIMESTAMP")
        # Update history — an append-only log of team notes/updates per registrant, so the
        # client's event profile keeps a running record (who added what, when). The latest
        # note is also mirrored into pg_event_registrations.staff_notes for the list + Excel.
        # (founder 2026-10-05)
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_event_reg_updates (
            id SERIAL PRIMARY KEY,
            reg_id INTEGER NOT NULL,
            event_id INTEGER,
            note TEXT DEFAULT '',
            added_by TEXT DEFAULT '',
            added_by_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_event_reg_updates_reg ON pg_event_reg_updates (reg_id)")
        conn.commit()
        logging.info("pg_events tables ensured")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_event_tables: {e}")
    finally:
        try: conn.close()
        except Exception: pass
