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
    """Returns a small result dict so callers (e.g. the admin trigger) can report
    what happened. Commits the dropdown values FIRST and independently, so a later
    field_registry hiccup can never roll back the dropdowns (the bug that left every
    list empty when this ran at cold-start boot)."""
    result = {'values': 0, 'registry': 0, 'errors': []}
    try:
        from college.data.neetpg_lists import NEETPG_COURSES, DNB_COURSES
    except Exception as e:
        result['errors'].append(f"course list import: {e}")
        NEETPG_COURSES, DNB_COURSES = [], []

    # ── 1. Dropdown values (each category committed on its own) ──
    for category, values in [
        ('pg_done',   ['Yes', 'No']),
        ('pg_type',   ['NEET PG (MD/MS)', 'DNB']),
        ('pg_status', ['First Year', 'Second Year', 'Final Year', 'Completed']),
        ('pg_specialty_neetpg', NEETPG_COURSES),
        ('pg_specialty_dnb',    DNB_COURSES),
    ]:
        conn = get_db()
        try:
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
                    result['values'] += 1
            conn.commit()
        except Exception as e:
            try: conn.rollback()
            except Exception: pass
            result['errors'].append(f"{category}: {e}")
        finally:
            try: conn.close()
            except Exception: pass

    # ── 2. Field Manager rows (separate transaction) ──
    registry = [
        ('pg_done',      'Done PG?',              'select', 'pg_done'),
        ('pg_type',      'Which PG?',             'select', 'pg_type'),
        ('pg_specialty', 'PG Course / Specialty', 'select', 'pg_specialty_neetpg'),
        ('pg_college',   'PG College',            'text',   ''),
        ('pg_status',    'PG Status',             'select', 'pg_status'),
    ]
    conn = get_db()
    try:
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
                result['registry'] += 1
        conn.commit()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        result['errors'].append(f"field_registry: {e}")
    finally:
        try: conn.close()
        except Exception: pass

    logging.info(f"seed_pg_lookups: {result}")
    return result
