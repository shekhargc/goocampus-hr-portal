"""NEET-PG counselling News & Updates (founder 2026-09-30).

A simple newsroom: the team posts an update tagged to a counselling body
(All India MCC, a state authority, INI-CET, NBE/DNB, etc.), with a heading and
either pasted text or an attached PDF. The goocampus.in dashboard shows a doctor
the news for All India (always) + their home state by default, and they can pull
in other states.

Scope model: each item is either 'all_india' (shown to everyone) or 'state'
(shown when that state is followed). `body_label` is the human authority name.
PDF is stored as BYTEA (like the seat-matrix source) — no R2 dependency.
"""
import logging
from db import get_db


def ensure_pg_news():
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_news (
            id SERIAL PRIMARY KEY,
            scope TEXT NOT NULL DEFAULT 'all_india',   -- 'all_india' | 'state'
            state TEXT DEFAULT '',                       -- set when scope='state'
            body_label TEXT NOT NULL DEFAULT 'All India MCC',
            heading TEXT NOT NULL DEFAULT '',
            body_text TEXT DEFAULT '',
            pdf_name TEXT DEFAULT '',
            pdf_data BYTEA,
            pdf_content_type TEXT DEFAULT 'application/pdf',
            is_published BOOLEAN DEFAULT TRUE,
            published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_news_scope ON pg_news (scope)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_news_state ON pg_news (state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_news_pub ON pg_news (is_published, published_at)")
        conn.commit()
        logging.info("pg_news table ensured")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_pg_news: {e}")
    finally:
        try: conn.close()
        except Exception: pass
