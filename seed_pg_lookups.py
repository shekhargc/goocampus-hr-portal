"""seed_pg_lookups.py — seed the PG (postgraduate) academic dropdowns.

Seeds lookup_options under pathway='plab' (so every pathway inherits them via the
PLAB fallback in get_lookup_options) and field_registry rows so the 5 PG fields are
editable in the Field Manager. The two specialty picklists are seeded from the
NEET-PG PDF course data (college/data/neetpg_lists.py), so the academic form offers
the SAME courses the PDF library uses — and the team can then maintain them in the
Field Manager. Idempotent: only inserts values/fields that don't already exist, so a
team edit is never overwritten on the next boot. (founder 2026-07-29)
"""
import logging


def run_seed_pg_lookups_once(get_db):
    try:
        from college.data.neetpg_lists import NEETPG_COURSES, DNB_COURSES
    except Exception as e:
        logging.error(f"seed_pg_lookups: cannot import course lists: {e}")
        NEETPG_COURSES, DNB_COURSES = [], []

    conn = get_db()
    try:
        def _seed_values(category, values):
            for i, v in enumerate(values):
                v = (v or '').strip()
                if not v:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM lookup_options WHERE category = ? AND value = ? "
                    "AND COALESCE(pathway,'plab') = 'plab'", (category, v)).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO lookup_options (category, label, value, pathway, "
                        "is_active, sort_order) VALUES (?, ?, ?, 'plab', TRUE, ?)",
                        (category, v, v, i))

        _seed_values('pg_done',   ['Yes', 'No'])
        _seed_values('pg_type',   ['NEET PG (MD/MS)', 'DNB'])
        _seed_values('pg_status', ['First Year', 'Second Year', 'Final Year', 'Completed'])
        _seed_values('pg_specialty_neetpg', NEETPG_COURSES)
        _seed_values('pg_specialty_dnb',    DNB_COURSES)

        # Field Manager rows so the PG fields appear under Academic Details.
        registry = [
            ('pg_done',      'Done PG?',              'select', 'pg_done'),
            ('pg_type',      'Which PG?',             'select', 'pg_type'),
            ('pg_specialty', 'PG Course / Specialty', 'select', 'pg_specialty_neetpg'),
            ('pg_college',   'PG College',            'text',   ''),
            ('pg_status',    'PG Status',             'select', 'pg_status'),
        ]
        for i, (fname, flabel, ftype, lcat) in enumerate(registry):
            exists = conn.execute(
                "SELECT 1 FROM field_registry WHERE section = ? AND field_name = ?",
                ('ops_academic_details', fname)).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO field_registry (section, field_name, field_label, "
                    "field_type, lookup_category, display_order, is_active) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1)",
                    ('ops_academic_details', fname, flabel, ftype, lcat, 90 + i))

        conn.commit()
        logging.info("seed_pg_lookups: PG academic dropdowns seeded")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"seed_pg_lookups: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
