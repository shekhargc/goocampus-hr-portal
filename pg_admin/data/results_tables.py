"""NEET-PG 2026 counselling RESULTS (seat allotments) + the name memory (founder 2026-10-24).

  pg_name_memory        — every way an authority has written a college / course name, tied to our
                          standard name (the cut-off institute / approved course name everything else
                          uses). Keyed by NAME, not by college-master id, so it survives a college-
                          workbook re-import. Learned once, reused for every later file from any
                          authority; unsure matches wait in a review queue until the team confirms.
  pg_results            — one row per allotted seat, as the authority published it (rank, quota,
                          institute, course, allotted / candidate category, remarks) + our standard
                          names next to the raw ones.
  pg_results_source     — one row per (authority, year, round): status provisional / final, the
                          official PDF, counts, and what a final list replaced.
Rounds are kept separately; a final list replaces the provisional list of the SAME round only.
"""
import logging
from db import get_db


def ensure_results_tables():
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_name_memory (
            id SERIAL PRIMARY KEY,
            kind TEXT NOT NULL DEFAULT 'college',     -- college | course
            raw_name TEXT NOT NULL,                   -- exactly as an authority printed it
            raw_key TEXT NOT NULL,                    -- normalised (lower, a-z0-9 words)
            std_name TEXT DEFAULT '',                 -- our standard name ('' = not matched yet)
            state TEXT DEFAULT '',                    -- state of the matched college (helps review)
            authority_code TEXT DEFAULT '',           -- where it was first seen
            how TEXT DEFAULT '',                      -- seed_matrix | seed_alias | exact | fuzzy | confirmed
            score NUMERIC(5,3),                       -- fuzzy similarity when auto-matched
            status TEXT DEFAULT 'ok',                 -- ok | review | unmatched
            candidates TEXT DEFAULT '',               -- JSON list of [score, std_name] for the review screen
            seen_count INTEGER DEFAULT 0,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            confirmed_by TEXT DEFAULT '',
            confirmed_at TIMESTAMP
        )''')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_name_memory ON pg_name_memory (kind, raw_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_name_memory_std ON pg_name_memory (kind, std_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_name_memory_status ON pg_name_memory (status)")

        conn.execute('''CREATE TABLE IF NOT EXISTS pg_results (
            id SERIAL PRIMARY KEY,
            authority_code TEXT NOT NULL,
            academic_year TEXT NOT NULL DEFAULT '2026-27',
            round TEXT NOT NULL,                      -- 'Round 1', 'Round 2', 'Mop-up', 'Stray' …
            sno INTEGER,
            rank INTEGER,
            quota_raw TEXT DEFAULT '',
            quota TEXT DEFAULT '',                    -- standard quota (as in the cut-offs)
            institute_raw TEXT DEFAULT '',
            institute TEXT DEFAULT '',                -- standard name ('' = not matched yet)
            state TEXT DEFAULT '',
            college_type TEXT DEFAULT '',             -- Government / Private / Deemed / Central …
            course_raw TEXT DEFAULT '',
            course TEXT DEFAULT '',                   -- approved course name
            section TEXT DEFAULT 'mdms',              -- mdms | diploma | dnb
            allotted_category TEXT DEFAULT '',        -- standard (OPEN, OBC, SC, ST, EWS, + ' PwD')
            allotted_category_raw TEXT DEFAULT '',
            candidate_category TEXT DEFAULT '',
            remarks TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_results_round ON pg_results (authority_code, academic_year, round)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_results_rank ON pg_results (rank)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_results_inst ON pg_results (institute, course)")

        conn.execute('''CREATE TABLE IF NOT EXISTS pg_results_source (
            id SERIAL PRIMARY KEY,
            authority_code TEXT NOT NULL,
            academic_year TEXT NOT NULL DEFAULT '2026-27',
            round TEXT NOT NULL,
            round_order INTEGER DEFAULT 1,            -- 1, 2, 3 … for sorting / "previous round"
            status TEXT DEFAULT 'provisional',        -- provisional | final
            title TEXT DEFAULT '',
            published_on TEXT DEFAULT '',             -- date on the official file (YYYY-MM-DD)
            source_file_name TEXT DEFAULT '',
            pdf_name TEXT DEFAULT '',
            pdf_data BYTEA,
            row_count INTEGER DEFAULT 0,
            matched_rows INTEGER DEFAULT 0,           -- rows whose college + course resolved to standard names
            notes TEXT DEFAULT '',
            is_hidden INTEGER DEFAULT 0,
            prev_status TEXT DEFAULT '',              -- what the last re-import replaced
            prev_row_count INTEGER,
            prev_replaced_at TIMESTAMP,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_results_source "
                     "ON pg_results_source (authority_code, academic_year, round)")
        conn.commit()
        logging.info("pg_results + pg_name_memory tables ensured")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_results_tables: {e}")
    finally:
        try: conn.close()
        except Exception: pass
