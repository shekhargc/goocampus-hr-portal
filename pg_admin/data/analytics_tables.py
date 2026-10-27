"""goocampus.in user analytics — record what registered doctors do on the dashboard
(sections used, searches, predictor runs, college opens, fee/quota/category filters) so
the admin can understand usage. Fed by POST /api/pg/track. (founder 2026-09-24)"""
import logging
from db import get_db


def ensure_analytics_tables():
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_user_events (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,                    -- pg_users.id (NULL if not logged in)
            session_id TEXT DEFAULT '',         -- anon grouping when no user
            section TEXT DEFAULT '',            -- predictor|college_db|fees|stipend|cutoff_explorer|choice_list|mentors|...
            event_type TEXT DEFAULT '',         -- section_view|search|predictor|college_open|fee_search|filter|...
            q TEXT DEFAULT '',                  -- free-text search
            college_id INTEGER,                 -- pg_college_master.id when a profile is opened
            college_name TEXT DEFAULT '',
            speciality TEXT DEFAULT '',         -- course / speciality searched
            quota TEXT DEFAULT '',
            category TEXT DEFAULT '',
            state TEXT DEFAULT '',
            authority TEXT DEFAULT '',
            fee_min NUMERIC(14,2),
            fee_max NUMERIC(14,2),
            rank INTEGER,
            detail TEXT DEFAULT '',             -- JSON, any extra fields
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        for idx, cols in [
            ('idx_pg_user_events_user', 'user_id'),
            ('idx_pg_user_events_section', 'section'),
            ('idx_pg_user_events_type', 'event_type'),
            ('idx_pg_user_events_created', 'created_at'),
        ]:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON pg_user_events ({cols})")
        _ensure_login_log(conn)
        conn.commit()
        logging.info("pg_user_events table ensured")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_analytics_tables: {e}")
    finally:
        try: conn.close()
        except Exception: pass


def _ensure_login_log(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_login_log (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        is_new INTEGER DEFAULT 0,           -- 1 = this login created the account
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_login_log_user ON pg_login_log (user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_login_log_created ON pg_login_log (created_at)")


def log_login(conn, user_id, is_new=False):
    """One row per successful OTP sign-in (no history existed before 2026-10-27: OTP rows are
    deleted and pg_users keeps only last_login_at). Never breaks the login."""
    for attempt in range(2):
        try:
            conn.execute("INSERT INTO pg_login_log (user_id, is_new) VALUES (?, ?)",
                         (user_id, 1 if is_new else 0))
            conn.commit()
            return
        except Exception as e:
            try: conn.rollback()
            except Exception: pass
            if attempt:
                logging.warning("log_login: %s", e)
                return
            try:   # table missing (boot DDL skipped on a cold start) → create it and retry once
                _ensure_login_log(conn); conn.commit()
            except Exception:
                try: conn.rollback()
                except Exception: pass
