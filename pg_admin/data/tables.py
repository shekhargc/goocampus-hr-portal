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
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Indexes for the public list's filter/sort (published+active, specialization, rating).
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_mentors_pub "
                     "ON pg_mentors (is_published, is_active)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_mentors_spec "
                     "ON pg_mentors (specialization)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_mentors_rating "
                     "ON pg_mentors (rating)")
        conn.commit()
        logging.info("pg_mentors table ensured successfully")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"ensure_pg_mentors_table: {e}")
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
