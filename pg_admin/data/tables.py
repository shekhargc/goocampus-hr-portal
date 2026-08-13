"""pg_admin DB tables. Postgres-first DDL (production is Postgres; local SQLite is
lenient about the extra type names). Idempotent — runs on every boot.

pg_mentors is the expert/senior doctor an aspirant browses + books on goocampus.in.
Straight from goocampus-pg/DATA_MODEL_PG.md §2 (itself from the old `doctorSchema`).
Prefixed `pg_` so it never clashes with existing portal tables (plab_clients etc.).
"""
import logging
from db import get_db


def ensure_pg_mentors_table():
    """Create pg_mentors + its filter indexes. Safe to run repeatedly."""
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_mentors (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            specialization TEXT NOT NULL,
            qualification TEXT NOT NULL,
            designation TEXT DEFAULT '',
            experience_years INTEGER,
            specialties JSONB DEFAULT '[]',
            languages JSONB DEFAULT '[]',
            bio TEXT DEFAULT '',
            photo_url TEXT DEFAULT '',
            medical_council_number TEXT DEFAULT '',
            medical_council_state TEXT DEFAULT '',
            hospital_name TEXT DEFAULT '',
            hospital_address TEXT DEFAULT '',
            counselling_fee NUMERIC(10,2) DEFAULT 0,
            consultation_fee NUMERIC(10,2) DEFAULT 0,
            service_type TEXT DEFAULT 'counselling',
            availability JSONB DEFAULT '{}',
            is_available BOOLEAN DEFAULT FALSE,
            rating NUMERIC(2,1) DEFAULT 0,
            total_reviews INTEGER DEFAULT 0,
            is_published BOOLEAN DEFAULT FALSE,
            is_verified BOOLEAN DEFAULT FALSE,
            is_active BOOLEAN DEFAULT TRUE,
            admin_notes TEXT DEFAULT '',
            created_by INTEGER,
            updated_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            -- Type split: 'specialist' (senior expert) vs 'peer_to_peer' (junior/peer mentor).
            mentor_type TEXT DEFAULT 'specialist',
            -- Richer profile fields scraped from the live site (goocampusworld.com).
            experience_range TEXT DEFAULT '',
            total_mentees TEXT DEFAULT '',
            mentorship_hours TEXT DEFAULT '',
            awards TEXT DEFAULT '',
            certifications TEXT DEFAULT '',
            reviews_count INTEGER DEFAULT 0,
            -- Provenance (for idempotent import + image migration).
            source TEXT DEFAULT '',
            external_id TEXT DEFAULT '',
            source_photo_url TEXT DEFAULT '',
            profile_source_url TEXT DEFAULT ''
        )''')
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"ensure_pg_mentors_table create: {e}")

    # ── Idempotent ALTERs so a pre-existing table (from the first commit) gains the
    #    new columns without a manual migration. Each guarded independently. ──
    for col, ddl in [
        ('mentor_type', "TEXT DEFAULT 'specialist'"),
        # Pathway country the mentor advises on (UK/Australia/USA/…). Blank
        # until set — only ~40 of 160 are inferable from their topic, so the
        # rest are filled in by the team. (founder 2026-07-28)
        ('country', "TEXT DEFAULT ''"),
        ('experience_range', "TEXT DEFAULT ''"),
        ('total_mentees', "TEXT DEFAULT ''"),
        ('mentorship_hours', "TEXT DEFAULT ''"),
        ('awards', "TEXT DEFAULT ''"),
        ('certifications', "TEXT DEFAULT ''"),
        ('reviews_count', "INTEGER DEFAULT 0"),
        ('source', "TEXT DEFAULT ''"),
        ('external_id', "TEXT DEFAULT ''"),
        ('source_photo_url', "TEXT DEFAULT ''"),
        ('profile_source_url', "TEXT DEFAULT ''"),
        # ── Full mentor profile from the founder's mentors_list.xlsx (2026-08-13).
        #    Granular fields kept verbatim so nothing is lost; the display columns
        #    above (name/bio/mentor_type/…) are populated from these at import.
        ('gender', "TEXT DEFAULT ''"),
        ('timezone', "TEXT DEFAULT ''"),
        ('pricing_currency', "TEXT DEFAULT ''"),
        ('discount', "TEXT DEFAULT ''"),
        ('current_state', "TEXT DEFAULT ''"),
        ('current_city', "TEXT DEFAULT ''"),
        ('location_origin', "TEXT DEFAULT ''"),
        ('special_interest', "TEXT DEFAULT ''"),
        ('hobbies', "TEXT DEFAULT ''"),
        ('completion_yr', "TEXT DEFAULT ''"),
        ('profession_job_title', "TEXT DEFAULT ''"),
        ('profession_company', "TEXT DEFAULT ''"),
        ('profession_location', "TEXT DEFAULT ''"),
        ('profession_total_exp', "TEXT DEFAULT ''"),
        ('profession_curr_work_exp', "TEXT DEFAULT ''"),
        ('profession_previous_work_exp', "TEXT DEFAULT ''"),
        ('pre_work_exp', "TEXT DEFAULT ''"),
        ('edu_qualification', "TEXT DEFAULT ''"),
        ('edu_pg_speciality', "TEXT DEFAULT ''"),
        ('edu_mbbs_college', "TEXT DEFAULT ''"),
        ('edu_mbbs_year', "TEXT DEFAULT ''"),
        ('edu_pg_college', "TEXT DEFAULT ''"),
        ('edu_pg_year', "TEXT DEFAULT ''"),
        ('topics_list', "TEXT DEFAULT ''"),
        ('intro_video', "TEXT DEFAULT ''"),
        ('added_on', "TEXT DEFAULT ''"),
        ('updated_src', "TEXT DEFAULT ''"),
    ]:
        try:
            conn.execute(f"ALTER TABLE pg_mentors ADD COLUMN {col} {ddl}")
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    try:
        # Filter/sort indexes + a unique key on (source, external_id) so the seed
        # importer can upsert idempotently (one row per old-site mentor).
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_mentors_pub "
                     "ON pg_mentors (is_published, is_active)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_mentors_type "
                     "ON pg_mentors (mentor_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_mentors_rating "
                     "ON pg_mentors (rating)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_mentors_source "
                     "ON pg_mentors (source, external_id) "
                     "WHERE source <> '' AND external_id <> ''")
        conn.commit()
        logging.info("pg_mentors table ensured successfully")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"ensure_pg_mentors_table index: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def ensure_pg_auth_tables():
    """pg_users (goocampus.in aspirant who logs in via WhatsApp OTP; first login =
    signup) + pg_otps (DB-stored one-time codes — send + verify are stateless
    service-to-service API calls, so the code can't live in a Flask session).
    Idempotent. (founder 2026-07-24)"""
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_users (
            id SERIAL PRIMARY KEY,
            mobile TEXT UNIQUE NOT NULL,
            name TEXT DEFAULT '',
            email TEXT DEFAULT '',
            neet_pg_year TEXT DEFAULT '',
            neet_pg_rank INTEGER,
            target_speciality TEXT DEFAULT '',
            photo_url TEXT DEFAULT '',
            session_token TEXT,
            token_expires_at TIMESTAMP,
            last_login_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_users_token ON pg_users (session_token)")
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_otps (
            id SERIAL PRIMARY KEY,
            mobile TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            expires_at TIMESTAMP,
            attempts INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_otps_mobile ON pg_otps (mobile)")
        conn.commit()
        logging.info("pg_users + pg_otps tables ensured successfully")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"ensure_pg_auth_tables: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def ensure_pg_cutoffs_table():
    """NEET-PG closing-rank dataset that powers the goocampus.in College Predictor.

    The site used to read a 10 MB JSON from its own repo — but that file is
    .gitignored, so it never reached the deployed site and the predictor silently
    fell back to a 168 KB sample ("Preview mode"). Per the settled architecture
    (goocampus.org IS the backend for goocampus.in) the data now lives here and is
    served over /api/pg/predictor, so next year's cut-offs are an admin upload
    instead of a code deploy. (founder 2026-07-24)

    closing_rank is DERIVED at import (the worst/last-round closing rank) so the
    predictor's "within reach" filter is a single indexed comparison.
    """
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_cutoffs (
            id SERIAL PRIMARY KEY,
            year INTEGER NOT NULL,
            institute TEXT DEFAULT '',
            authority TEXT DEFAULT '',
            quota TEXT DEFAULT '',
            category TEXT DEFAULT '',
            degree TEXT DEFAULT '',
            course TEXT DEFAULT '',
            state TEXT DEFAULT '',
            fee NUMERIC(14,2),
            stipend NUMERIC(14,2),
            bond_years NUMERIC(6,2),
            penalty NUMERIC(14,2),
            r1 INTEGER, r2 INTEGER, r3 INTEGER, r4 INTEGER, stray INTEGER,
            closing_rank INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Extra columns for the college database (founder 2026-08-11): the master
        # file also carries institution type, seat/course type and beds, and we
        # derive coarse scope tags so the site can filter by predictor + tab.
        #   institute_type  — verbatim from the Excel (Government Institute / Deemed / …)
        #   authority_type  — 'allindia' (MCC) | 'state'  (which counselling)
        #   degree_group    — 'mdms' (MD/MS) | 'dnb' (DNB/DNB-Diploma) | 'other'
        #   seat_type/course_type/beds — extra detail carried through
        #   college_id      — FK into pg_colleges (backfilled after each import)
        #   is_reference    — 1 for stipend/bond-only rows (no cut-off) → excluded
        for col, ddl in [
            ('institute_type', 'TEXT'), ('authority_type', 'TEXT'),
            ('degree_group', 'TEXT'), ('seat_type', 'TEXT'),
            ('course_type', 'TEXT'), ('beds', 'INTEGER'),
            ('college_id', 'INTEGER'), ('is_reference', 'INTEGER DEFAULT 0'),
            # Year-wise stipend + full counselling body name (founder 2026-08-12).
            # `stipend` holds Year 1; these add Years 2 & 3 and the verbose body.
            ('stipend_yr2', 'NUMERIC(14,2)'), ('stipend_yr3', 'NUMERIC(14,2)'),
            ('counselling_body', 'TEXT'),
        ]:
            try:
                conn.execute(f"ALTER TABLE pg_cutoffs ADD COLUMN IF NOT EXISTS {col} {ddl}")
            except Exception:
                conn.rollback()
        # The predictor filters on year + closing_rank, then narrows by
        # authority / category / state / course keyword.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_cutoffs_rank "
                     "ON pg_cutoffs (year, closing_rank)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_cutoffs_auth "
                     "ON pg_cutoffs (authority)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_cutoffs_cat "
                     "ON pg_cutoffs (category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_cutoffs_state "
                     "ON pg_cutoffs (state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_cutoffs_college "
                     "ON pg_cutoffs (college_id)")
        conn.commit()
        logging.info("pg_cutoffs table ensured successfully")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"ensure_pg_cutoffs_table: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def ensure_pg_colleges_table():
    """College master for the NEET-PG/DNB database (founder 2026-08-11).

    One row per distinct (college, counselling scope). The `college_id` is the
    STABLE backbone — cut-offs reference it, favourites store it, the site's
    4th "Favourite colleges" predictor tab matches on it. It must survive a data
    re-upload, so the importer UPSERTs by `name_key` + `authority_type` and never
    reissues an id for a college it has seen before.
    """
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_colleges (
            college_id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            name_key TEXT NOT NULL,            -- normalised name, for stable identity
            institution_type TEXT DEFAULT '',  -- verbatim from the Excel
            authority_type TEXT DEFAULT '',    -- 'allindia' | 'state'
            state TEXT DEFAULT '',
            city TEXT DEFAULT '',
            degree_groups TEXT DEFAULT '[]',   -- JSON array e.g. ["mdms","dnb"]
            beds INTEGER,
            year INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Identity = normalised name + counselling scope + state. A college that
        # sits under BOTH MCC and a state yields two rows (one per scope) — the
        # site was told to expect a scalar authority_type (see API_CONTRACT.md).
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_colleges_identity "
                     "ON pg_colleges (name_key, authority_type, state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_colleges_type "
                     "ON pg_colleges (institution_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_colleges_state "
                     "ON pg_colleges (state)")
        conn.commit()
        logging.info("pg_colleges table ensured successfully")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_pg_colleges_table: {e}")
    finally:
        try: conn.close()
        except Exception: pass


def ensure_pg_favorites_table():
    """Per-doctor college shortlist (founder 2026-08-11). Scoped to a pg_users
    id (the goocampus.in doctor account). Surfaced in the Sales/CRM view as a
    2026-27 counselling call opener."""
    conn = get_db()
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_favorites (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            college_id INTEGER NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_favorites "
                     "ON pg_favorites (user_id, college_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_favorites_user "
                     "ON pg_favorites (user_id)")
        conn.commit()
        logging.info("pg_favorites table ensured successfully")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_pg_favorites_table: {e}")
    finally:
        try: conn.close()
        except Exception: pass
