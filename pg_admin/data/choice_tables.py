"""NEET-PG Choice-List builder (founder spec, build 2026-09-21).

A candidate (Starter+) builds round-wise choice sheets for a counselling body:
pick body + rank + quota + category → we generate colleges within reach from the
cut-off data → they land in three editable sheets (Round 1 / 2 / 3), each pre-sorted
by THAT round's closing rank and tagged High/Good/Reach. Editable (reorder / add /
remove) by BOTH the client (goocampus.in) and the team (goocampus.org admin).
Colleges beyond rank reach can be added manually ("try-luck") from the Cutoff Explorer.

Plan gating (enforced in the API): Starter/Standard = MCC + home state; Premium = MCC + any state.
"""
import logging
from db import get_db


def ensure_choice_tables():
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_choice_sets (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,          -- pg_users.id (the doctor)
            label TEXT DEFAULT '',             -- e.g. "MCC All-India" / "Karnataka"
            scope TEXT DEFAULT 'mcc',          -- 'mcc' | 'state'
            authority TEXT DEFAULT '',         -- counselling body value in pg_cutoffs.authority
            degree_group TEXT DEFAULT 'mdms',  -- mdms | dnb
            state TEXT DEFAULT '',             -- for state counselling
            quota TEXT DEFAULT '',
            category TEXT DEFAULT '',
            rank INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_choice_sets_user ON pg_choice_sets (user_id)")

        conn.execute('''CREATE TABLE IF NOT EXISTS pg_choice_items (
            id SERIAL PRIMARY KEY,
            set_id INTEGER NOT NULL,
            round INTEGER NOT NULL,             -- 1 | 2 | 3
            position INTEGER DEFAULT 0,         -- order within the round sheet
            master_id INTEGER,                  -- pg_college_master.id (link to profile)
            institute TEXT DEFAULT '',          -- cut-off college name (verbatim)
            course TEXT DEFAULT '',
            quota TEXT DEFAULT '',
            category TEXT DEFAULT '',
            closing_rank INTEGER,               -- that round's historical closing rank
            chance TEXT DEFAULT '',             -- high | good | reach
            source TEXT DEFAULT 'predicted',    -- predicted | manual
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_choice_items_set ON pg_choice_items (set_id, round, position)")
        conn.commit()
        logging.info("pg_choice tables ensured")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_choice_tables: {e}")
    finally:
        try: conn.close()
        except Exception: pass
