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
        # Official source link for the item (e.g. the authority's page), shown + clickable
        # on the dashboard alongside the PDF. (founder 2026-10-05)
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS source_url TEXT DEFAULT ''")
        # SEO news + deadlines (2026-10-08): category, one-line summary, key dates (JSON
        # {field: {date, time}} — only dates the notice actually states).
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS category TEXT DEFAULT ''")
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS summary TEXT DEFAULT ''")
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS key_dates TEXT DEFAULT ''")

        # Per-doctor "followed states" for the news feed (beyond All-India + home state).
        # Saved to the doctor's profile so the admin can see their subscriptions.
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_news_follows (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            state TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_news_follows ON pg_news_follows (user_id, state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_news_follows_user ON pg_news_follows (user_id)")
        conn.commit()
        logging.info("pg_news tables ensured")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_pg_news: {e}")
    finally:
        try: conn.close()
        except Exception: pass
