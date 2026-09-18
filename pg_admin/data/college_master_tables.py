"""Unified Indian college master (founder 2026-09-18).

The canonical college list behind goocampus.in — imported from the founder's
"Medical Colleges and DNB College Database" workbook (two sheets: Medical &
Healthcare, DNB Hospitals). Everything else hangs off it by a stable id:
  pg_college_master   — one row per college (profile + fees + OPD/IPD/beds + geo)
  pg_college_course   — one row per college x course (the course catalogue)
  pg_college_alias    — every name a college is known by → its master id
                        (canonical + cut-off name + former/variant names), so a
                        search on ANY name resolves to one profile.
Cut-offs (pg_cutoffs, already uploaded, incl. stipend/bond/penalty) link in via
the alias map + the audited matching file. Additive — the live predictor is
untouched until the sections are wired.
"""
import logging
from db import get_db


def ensure_college_master_tables():
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_college_master (
            id SERIAL PRIMARY KEY,
            master_key TEXT,                    -- normalised name|state, for de-dupe/UPSERT
            kind TEXT DEFAULT 'medical',        -- 'medical' | 'dnb'
            college_name TEXT NOT NULL,         -- canonical display name
            university TEXT DEFAULT '',
            logo_url TEXT DEFAULT '',
            city TEXT DEFAULT '',
            state TEXT DEFAULT '',
            district TEXT DEFAULT '',
            country TEXT DEFAULT 'India',
            college_type TEXT DEFAULT '',
            accreditation TEXT DEFAULT '',
            college_stream TEXT DEFAULT '',
            established_year TEXT DEFAULT '',
            nearest_airport TEXT DEFAULT '',
            winter_min_temp TEXT DEFAULT '',
            summer_max_temp TEXT DEFAULT '',
            latitude TEXT DEFAULT '',
            longitude TEXT DEFAULT '',
            mess_fee_min NUMERIC(14,2),
            mess_fee_max NUMERIC(14,2),
            mess_fee_currency TEXT DEFAULT 'INR',
            hostel_fee_min NUMERIC(14,2),
            hostel_fee_max NUMERIC(14,2),
            hostel_fee_currency TEXT DEFAULT 'INR',
            opd TEXT DEFAULT '',
            ipd TEXT DEFAULT '',
            bed_count TEXT DEFAULT '',
            official_website TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_college_master ON pg_college_master (kind, master_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_college_master_state ON pg_college_master (state)")

        conn.execute('''CREATE TABLE IF NOT EXISTS pg_college_course (
            id SERIAL PRIMARY KEY,
            master_id INTEGER NOT NULL,
            course TEXT DEFAULT '',
            course_level TEXT DEFAULT '',
            course_stream TEXT DEFAULT '',
            seat_intake TEXT DEFAULT '',
            exam_type TEXT DEFAULT '',
            entrance_exams TEXT DEFAULT '',
            entrance_exam_eligibility TEXT DEFAULT '',
            academic_eligibility TEXT DEFAULT '',
            duration_total_months TEXT DEFAULT '',
            duration_years TEXT DEFAULT '',
            duration_months TEXT DEFAULT ''
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_college_course_master ON pg_college_course (master_id)")

        conn.execute('''CREATE TABLE IF NOT EXISTS pg_college_alias (
            id SERIAL PRIMARY KEY,
            master_id INTEGER NOT NULL,
            alias_name TEXT NOT NULL,
            alias_key TEXT,                     -- normalised, for lookup
            alias_source TEXT DEFAULT 'canonical', -- canonical | cutoff | former | variant
            is_active INTEGER DEFAULT 1
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_college_alias_master ON pg_college_alias (master_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_college_alias_key ON pg_college_alias (alias_key)")
        conn.commit()
        logging.info("pg_college_master tables ensured")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_college_master_tables: {e}")
    finally:
        try: conn.close()
        except Exception: pass
