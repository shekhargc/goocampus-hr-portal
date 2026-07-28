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
