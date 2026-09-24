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
        conn.commit()
        logging.info("pg_user_events table ensured")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_analytics_tables: {e}")
    finally:
        try: conn.close()
        except Exception: pass
