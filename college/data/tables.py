"""College DB tables + seed/import. From app.py."""
import logging
from db import get_db
from college.utils import _make_slug

def ensure_college_tables():
    """Create colleges, college_courses, college_fee_structure tables."""
    try:
        conn = get_db()
        conn.execute('''CREATE TABLE IF NOT EXISTS colleges (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT UNIQUE,
            category TEXT NOT NULL DEFAULT 'international',
            country TEXT NOT NULL DEFAULT 'Russia',
            state_or_region TEXT DEFAULT '',
            city TEXT DEFAULT '',
            established_year INTEGER DEFAULT 0,
            university_type TEXT DEFAULT 'Government',
            medium_of_instruction TEXT DEFAULT 'English',
            nmc_approved BOOLEAN DEFAULT FALSE,
            who_approved BOOLEAN DEFAULT FALSE,
            indian_passouts TEXT DEFAULT '',
            description TEXT DEFAULT '',
            eligibility TEXT DEFAULT '',
            facilities TEXT DEFAULT '',
            ranking_info TEXT DEFAULT '',
            website_url TEXT DEFAULT '',
            logo_url TEXT DEFAULT '',
            cover_image_url TEXT DEFAULT '',
            contact_phone TEXT DEFAULT '',
            contact_email TEXT DEFAULT '',
            currency TEXT DEFAULT 'USD',
            full_package_inr_lakhs NUMERIC(10,2) DEFAULT 0,
            mess_charges TEXT DEFAULT '',
            consultancy_fee_inr NUMERIC(10,2) DEFAULT 125000,
            admin_fee TEXT DEFAULT '1500 $',
            travel_cost_inr NUMERIC(10,2) DEFAULT 75000,
            hostel_included BOOLEAN DEFAULT FALSE,
            is_featured BOOLEAN DEFAULT FALSE,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        conn.execute('''CREATE TABLE IF NOT EXISTS college_courses (
            id SERIAL PRIMARY KEY,
            college_id INTEGER NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
            course_name TEXT NOT NULL DEFAULT 'MBBS',
            degree TEXT DEFAULT 'MBBS',
            duration_years INTEGER DEFAULT 6,
            duration_includes TEXT DEFAULT 'Including Internship',
            intake_season TEXT DEFAULT 'Summer',
            seats_available INTEGER DEFAULT 0,
            description TEXT DEFAULT '',
            eligibility TEXT DEFAULT '',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        conn.execute('''CREATE TABLE IF NOT EXISTS college_fee_structure (
            id SERIAL PRIMARY KEY,
            course_id INTEGER NOT NULL REFERENCES college_courses(id) ON DELETE CASCADE,
            year_label TEXT NOT NULL,
            semester TEXT NOT NULL,
            tuition_fee NUMERIC(12,2) DEFAULT 0,
            hostel_fee NUMERIC(12,2) DEFAULT 0,
            docs_med_checkup NUMERIC(12,2) DEFAULT 0,
            visa_med_insurance NUMERIC(12,2) DEFAULT 0,
            total NUMERIC(12,2) DEFAULT 0,
            total_inr NUMERIC(12,2) DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Countries table for college portal
        conn.execute('''CREATE TABLE IF NOT EXISTS countries (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            code TEXT DEFAULT '',
            currency_code TEXT DEFAULT 'USD',
            is_active BOOLEAN DEFAULT TRUE
        )''')

        # Seed countries if empty
        cnt_count = conn.execute("SELECT COUNT(*) as c FROM countries").fetchone()['c']
        if cnt_count == 0:
            for cname, ccode, ccur in [
                ('India', 'IN', 'INR'), ('Russia', 'RU', 'RUB'),
                ('United States', 'US', 'USD'), ('United Kingdom', 'GB', 'GBP'),
                ('Germany', 'DE', 'EUR'), ('China', 'CN', 'CNY'),
                ('Ukraine', 'UA', 'UAH'), ('Kazakhstan', 'KZ', 'KZT'),
                ('Philippines', 'PH', 'PHP'), ('Bangladesh', 'BD', 'BDT'),
                ('Nepal', 'NP', 'NPR'), ('Georgia', 'GE', 'GEL'),
                ('Kyrgyzstan', 'KG', 'KGS'), ('Uzbekistan', 'UZ', 'UZS'),
                ('Armenia', 'AM', 'AMD'), ('Belarus', 'BY', 'BYN'),
                ('Egypt', 'EG', 'EGP'), ('Malaysia', 'MY', 'MYR'),
                ('Australia', 'AU', 'AUD'),
            ]:
                try:
                    conn.execute("INSERT INTO countries (name, code, currency_code) VALUES (?,?,?)",
                                 (cname, ccode, ccur))
                except Exception:
                    pass

        # Add Indian college-specific columns if missing
        for col, ctype in [
            ('university_name', 'TEXT DEFAULT \'\''),
            ('annual_intake', 'INTEGER DEFAULT 0'),
            ('counselling_authority', 'TEXT DEFAULT \'\''),
            ('opd', 'INTEGER DEFAULT 0'),
            ('ipd', 'INTEGER DEFAULT 0'),
            ('bond_penalty', 'TEXT DEFAULT \'\''),
            ('bed_count', 'INTEGER DEFAULT 0'),
            ('prospects_url', 'TEXT DEFAULT \'\''),
        ]:
            try:
                conn.execute(f"ALTER TABLE colleges ADD COLUMN {col} {ctype}")
            except Exception:
                pass  # column already exists

        # MBBS Cut-off predictor table
        conn.execute('''CREATE TABLE IF NOT EXISTS mbbs_cutoffs (
            id SERIAL PRIMARY KEY,
            year INTEGER NOT NULL,
            institute_name TEXT NOT NULL,
            quota TEXT DEFAULT '',
            category TEXT DEFAULT '',
            course TEXT DEFAULT 'MBBS',
            fees NUMERIC(12,2) DEFAULT 0,
            counselling_authority TEXT DEFAULT '',
            counselling_body TEXT DEFAULT '',
            round1_rank INTEGER,
            round2_rank INTEGER,
            round3_rank INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        conn.commit()
        conn.close()
        logging.info("College tables ensured successfully")
    except Exception as e:
        logging.error(f"ensure_college_tables: {e}")


def ensure_neetpg_doctype_column():
    """Add the doc_type column to neetpg_pdfs (base table created in app.py).

    Document type is a separate dimension from the existing `category` column
    (which means exam type: neetpg vs dnb). doc_type ∈ {cutoff,
    stipend_bond_penalty, mcc_profile}. Existing rows backfill to 'cutoff'
    via the DEFAULT. Idempotent — safe to run on every boot."""
    conn = get_db()
    try:
        conn.execute("ALTER TABLE neetpg_pdfs ADD COLUMN doc_type TEXT DEFAULT 'cutoff'")
        conn.commit()
        logging.info("neetpg_pdfs.doc_type column added")
    except Exception:
        # Column already exists (or table not yet created) — roll back and move on.
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def _auto_seed_russian_colleges():
    """Auto-seed Russian colleges from college_seed_data.py if not already present."""
    try:
        from college_seed_data import RUSSIAN_COLLEGES
    except ImportError:
        logging.info("college_seed_data.py not found, skipping Russian auto-seed")
        return

    conn = get_db()
    try:
        existing_count = conn.execute("SELECT COUNT(*) AS cnt FROM colleges WHERE country = 'Russia'").fetchone()['cnt']
        if existing_count >= len(RUSSIAN_COLLEGES):
            logging.info(f"Russian colleges already seeded ({existing_count} exist), skipping")
            conn.close()
            return

        added = 0
        for c in RUSSIAN_COLLEGES:
            slug = _make_slug(c['name'])
            ex = conn.execute("SELECT id FROM colleges WHERE slug = ?", (slug,)).fetchone()
            if ex:
                continue

            conn.execute('''INSERT INTO colleges (name, slug, category, country, city,
                established_year, university_type, medium_of_instruction, nmc_approved, who_approved,
                indian_passouts, currency, full_package_inr_lakhs,
                mess_charges, consultancy_fee_inr, admin_fee, travel_cost_inr,
                hostel_included, eligibility)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (c['name'], slug, 'international', c.get('country', 'Russia'), c.get('city', ''),
                 c.get('established_year', 0), c.get('university_type', 'Government'),
                 c.get('medium', 'English'),
                 1 if c.get('nmc_approved') else 0,
                 1 if c.get('who_approved') else 0,
                 c.get('indian_passouts', ''),
                 c.get('currency', 'RUB'),
                 c.get('full_package_inr_lakhs', 0),
                 c.get('mess_charges', ''),
                 c.get('consultancy_fee_inr', 125000),
                 c.get('admin_fee', '1500 $'),
                 c.get('travel_cost_inr', 75000),
                 1 if c.get('hostel_included') else 0,
                 c.get('eligibility', '')))

            new_college = conn.execute("SELECT id FROM colleges WHERE slug = ?", (slug,)).fetchone()
            if new_college:
                conn.execute('''INSERT INTO college_courses (college_id, course_name, degree,
                    duration_years, duration_includes, intake_season)
                    VALUES (?, 'MBBS', 'MBBS', ?, 'Including Internship', 'Summer')''',
                    (new_college['id'], c.get('duration_years', 6)))

                course = conn.execute(
                    "SELECT id FROM college_courses WHERE college_id = ? ORDER BY id DESC LIMIT 1",
                    (new_college['id'],)).fetchone()

                if course and c.get('fees'):
                    for fee in c['fees']:
                        conn.execute('''INSERT INTO college_fee_structure
                            (course_id, year_label, semester, tuition_fee, hostel_fee,
                             docs_med_checkup, visa_med_insurance, total, total_inr)
                            VALUES (?,?,?,?,?,?,?,?,?)''',
                            (course['id'], fee['year_label'], fee['semester'],
                             fee.get('tuition', 0), fee.get('hostel', 0),
                             fee.get('docs', 0), fee.get('visa', 0),
                             fee.get('total', 0), fee.get('total_inr', 0)))
            added += 1

        conn.commit()
        logging.info(f"Auto-seeded {added} Russian colleges")
    except Exception as e:
        logging.error(f"Russian auto-seed error: {e}")
    finally:
        conn.close()


def _auto_import_indian_colleges():
    """One-time import of Indian colleges from the embedded data.
       Runs at startup; skips if Indian colleges already exist."""
    conn = get_db()
    try:
        existing = conn.execute("SELECT COUNT(*) AS cnt FROM colleges WHERE category = 'indian'").fetchone()['cnt']
        if existing >= 100:
            logging.info(f"Indian colleges already imported ({existing} exist), skipping")
            conn.close()
            return
    except Exception:
        conn.close()
        return

    # Try to read the Excel file
    excel_path = os.path.join(os.path.dirname(__file__), 'indian_colleges_data.json')
    if not os.path.exists(excel_path):
        logging.info("indian_colleges_data.json not found, skipping Indian auto-import")
        conn.close()
        return

    import json
    try:
        with open(excel_path, 'r') as f:
            colleges_data = json.load(f)

        # Safe int conversion
        def safe_int(v):
            try:
                if v is None or v == '':
                    return 0
                return int(float(str(v).replace(',', '')))
            except (ValueError, TypeError):
                return 0

        # First pass: backfill states and cities
        seen_states = set()
        seen_cities = set()
        for row in colleges_data:
            state_name = str(row.get('state') or '').strip()
            city_name = str(row.get('city') or '').strip()
            if state_name and state_name not in seen_states:
                seen_states.add(state_name)
                exists_st = conn.execute("SELECT id FROM states WHERE name = ?", (state_name,)).fetchone()
                if not exists_st:
                    try:
                        conn.execute("INSERT INTO states (name, is_active) VALUES (?, TRUE)", (state_name,))
                        conn.commit()
                    except Exception:
                        conn.rollback()

            if city_name and state_name and (city_name, state_name) not in seen_cities:
                seen_cities.add((city_name, state_name))
                state_row = conn.execute("SELECT id FROM states WHERE name = ?", (state_name,)).fetchone()
                if state_row:
                    exists_city = conn.execute("SELECT id FROM cities WHERE name = ? AND state_id = ?",
                                               (city_name, state_row['id'])).fetchone()
                    if not exists_city:
                        try:
                            conn.execute("INSERT INTO cities (name, state_id, is_active) VALUES (?, ?, TRUE)",
                                         (city_name, state_row['id']))
                            conn.commit()
                        except Exception:
                            conn.rollback()

        # Second pass: insert colleges
        added = 0
        errors = 0
        for row in colleges_data:
            name = str(row.get('college_name') or '').strip()
            if not name:
                continue

            try:
                slug = _make_slug(name)
                ex = conn.execute("SELECT id FROM colleges WHERE slug = ?", (slug,)).fetchone()
                if ex:
                    continue

                state_name = str(row.get('state') or '').strip()
                city_name = str(row.get('city') or '').strip()
                college_type = str(row.get('college_type') or 'Government Institute').strip()

                conn.execute('''INSERT INTO colleges (name, slug, category, country, state_or_region, city,
                    established_year, university_type, nmc_approved, who_approved, currency,
                    medium_of_instruction, website_url,
                    university_name, annual_intake, counselling_authority, opd, ipd,
                    bond_penalty, bed_count, prospects_url)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (name, slug, 'indian', 'India', state_name, city_name,
                     safe_int(row.get('year_of_inception')),
                     college_type,
                     1, 0, 'INR', 'English',
                     str(row.get('official_website') or '').strip(),
                     str(row.get('university_name') or '').strip(),
                     safe_int(row.get('annual_intake')),
                     str(row.get('counselling_authority') or '').strip(),
                     safe_int(row.get('opd')),
                     safe_int(row.get('ipd')),
                     str(row.get('bond_penalty') or '').strip(),
                     safe_int(row.get('bed_count')),
                     str(row.get('prospects') or '').strip()))

                # Add MBBS course
                new_college = conn.execute("SELECT id FROM colleges WHERE slug = ?", (slug,)).fetchone()
                if new_college:
                    course_name = str(row.get('course') or 'MBBS').strip()
                    course_level = str(row.get('course_level') or 'UG').strip()
                    conn.execute('''INSERT INTO college_courses (college_id, course_name, degree,
                        duration_years, duration_includes, intake_season)
                        VALUES (?, ?, ?, 5, 'Including Internship', 'Summer')''',
                        (new_college['id'], course_name, course_level))

                conn.commit()
                added += 1
            except Exception as row_err:
                errors += 1
                logging.warning(f"Indian import row error ({name}): {row_err}")
                try:
                    conn.rollback()
                except Exception:
                    pass

        logging.info(f"Auto-imported {added} Indian colleges ({errors} errors)")
    except Exception as e:
        logging.error(f"Indian auto-import error: {e}")
    finally:
        conn.close()
