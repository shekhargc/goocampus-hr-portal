"""
seed_australia_lookups.py — auto-populate lookup_options for pathway='australia'.

After Phase 2 imports landed 5,500+ records of historical Australia data into
the ops_* tables, the user expected Settings -> Australia Pathway tab to
already show populated dropdowns. This script seeds those dropdowns from
the actual imported data — every distinct value in the relevant column
becomes a selectable option, scoped to pathway='australia'.

Categories mirror the PLAB SEED_DATA names so the same Field Manager UI
(driven by field_registry rows) renders cleanly for both pathways. PLAB
sees its values, Australia sees Australia values — strict per-pathway
isolation enforced by the pathway column added in Phase 1.

Idempotent via _import_markers marker key 'au_lookups_seed'. Bump
IMPORT_VERSION to force a re-seed (e.g. after adding a new mapping).
Runs on app boot AFTER the Australia ops_* imports so the source data
is in place. Empty categories (no rows yet in source) are silently
skipped so this works on fresh staging environments too.
"""

import logging


IMPORT_VERSION = 'au_lookups_v1'


# Each entry: (lookup_options.category, source_table, source_column).
# When the data uses a different column than PLAB does, we still map to
# the PLAB category name so the same Field Manager UI works for both.
# Source rows are always filtered to pathway='australia'.
LOOKUP_SOURCES = [
    # ── Test Bookings ──
    ('exam_name',          'ops_test_bookings',         'exam'),
    ('exam_status',        'ops_test_bookings',         'exam_status'),
    ('exam_result',        'ops_test_bookings',         'exam_result'),
    ('exam_method',        'ops_test_bookings',         'exam_type'),
    ('exam_booked_by',     'ops_test_bookings',         'booked_by'),
    ('exam_country',       'ops_test_bookings',         'country'),

    # ── Coaching / Training ──
    ('coaching_status',        'ops_coaching', 'coaching_status'),
    ('coaching_method',        'ops_coaching', 'coaching_method'),
    ('coaching_course_type',   'ops_coaching', 'course_type'),
    ('training_program',       'ops_coaching', 'english_training'),

    # ── Online Subscriptions / Courses ──
    ('subscription_type',      'ops_online_subscriptions', 'online_subscription'),
    ('activation_type',        'ops_online_subscriptions', 'activation_type'),
    ('subscription_booked_by', 'ops_online_subscriptions', 'booked_by'),

    # ── Payments ──
    ('payment_method', 'ops_payments', 'payment_method'),
    ('instalment',     'ops_payments', 'instalment'),

    # ── EPIC ──
    ('epic_reg_status',    'ops_epic_registration', 'epic_registration_status'),
    ('epic_status',        'ops_epic_registration', 'epic_status'),
    ('doc_stage',          'ops_epic_registration', 'documents_stage'),
    ('notary_camp_status', 'ops_epic_registration', 'notary_cam'),

    # ── Webinars & Conferences ──
    ('event_type',         'ops_webinars_conferences', 'event_type'),
    ('event_value',        'ops_webinars_conferences', 'event_value'),
    ('participation_type', 'ops_webinars_conferences', 'participation_type'),

    # ── Research & Publication ──
    ('research_status',    'ops_research_publication', 'research_status'),
    ('research_provider',  'ops_research_publication', 'research_provider'),
    ('author_position',    'ops_research_publication', 'author_position'),

    # ── Academic Details ──
    ('img_fmg',            'ops_academic_details', 'img_fmg'),
    ('mbbs_status',        'ops_academic_details', 'mbbs_status'),
    ('internship_status',  'ops_academic_details', 'internship_status'),
    ('working_status',     'ops_academic_details', 'working_status'),

    # ── Client-level (account/stage) ──
    ('account_status',     'plab_clients', 'account_status'),
    ('current_stage',      'plab_clients', 'current_stage'),
    ('plan_type',          'plab_clients', 'plan_type'),
    ('counsellor',         'plab_clients', 'counsellor'),
    ('lead_source',        'plab_clients', 'lead_source'),
]


def _table_has_column(conn, table, column):
    """Defensive: skip mappings whose target column doesn't exist on this DB."""
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if cols:
            return column in cols
        # Postgres path — PRAGMA returns nothing
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? AND column_name = ?",
            (table, column),
        ).fetchall()
        return bool(rows)
    except Exception:
        return False


def run_seed_australia_lookups_once(get_db_fn):
    """Seed lookup_options for pathway='australia' from imported ops_* data.

    Returns a dict with stats: per-category insert/update counts and a
    'skipped_categories' list for missing tables/columns.
    """
    conn = get_db_fn()
    try:
        # Marker table reused.
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS _import_markers (key TEXT PRIMARY KEY, value TEXT)")
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        marker = conn.execute(
            "SELECT value FROM _import_markers WHERE key = 'au_lookups_seed'"
        ).fetchone()
        if marker and marker['value'] == IMPORT_VERSION:
            logging.info(f"Australia lookups seed: already at {IMPORT_VERSION}, skipping")
            return {'per_category': {}, 'skipped_categories': []}

        logging.info(f"Australia lookups seed: starting {IMPORT_VERSION}...")
        stats = {'per_category': {}, 'skipped_categories': []}

        for category, table, column in LOOKUP_SOURCES:
            if not _table_has_column(conn, table, column):
                stats['skipped_categories'].append((category, table, column, 'missing column'))
                continue

            # Pull distinct values from rows scoped to pathway='australia'.
            try:
                rows = conn.execute(
                    f"SELECT DISTINCT TRIM({column}) AS v FROM {table} "
                    f"WHERE pathway = 'australia' "
                    f"  AND {column} IS NOT NULL AND TRIM({column}) != '' "
                    f"ORDER BY v",
                ).fetchall()
            except Exception as e:
                stats['skipped_categories'].append((category, table, column, str(e)))
                continue

            distinct_values = [r['v'] for r in rows if r['v']]
            if not distinct_values:
                stats['per_category'][category] = 0
                continue

            inserted = 0
            updated = 0
            # Highest existing sort_order for this (category, australia) so we
            # append new values rather than collide.
            try:
                max_order = conn.execute(
                    "SELECT MAX(sort_order) AS m FROM lookup_options "
                    "WHERE category = ? AND COALESCE(pathway, 'plab') = 'australia'",
                    (category,),
                ).fetchone()['m'] or 0
            except Exception:
                max_order = 0

            for value in distinct_values:
                try:
                    existing = conn.execute(
                        "SELECT id FROM lookup_options "
                        "WHERE category = ? AND value = ? AND COALESCE(pathway, 'plab') = 'australia'",
                        (category, value),
                    ).fetchone()
                    if existing:
                        # Already there — leave it alone (admin may have edited it).
                        updated += 1
                        continue
                    max_order += 1
                    conn.execute(
                        "INSERT INTO lookup_options (category, label, value, sort_order, is_active, pathway) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (category, value, value, max_order, 1, 'australia'),
                    )
                    inserted += 1
                except Exception as e:
                    logging.warning(f"AU lookup seed row failed ({category} / {value!r}): {e}")
            conn.commit()
            stats['per_category'][category] = inserted

        # Write the marker so subsequent boots are no-ops.
        try:
            conn.execute(
                "INSERT INTO _import_markers (key, value) VALUES ('au_lookups_seed', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (IMPORT_VERSION,),
            )
            conn.commit()
        except Exception:
            try:
                conn.execute("DELETE FROM _import_markers WHERE key = 'au_lookups_seed'")
                conn.execute(
                    "INSERT INTO _import_markers (key, value) VALUES ('au_lookups_seed', ?)",
                    (IMPORT_VERSION,),
                )
                conn.commit()
            except Exception as e:
                logging.warning(f"AU lookup seed: could not write marker: {e}")

        total = sum(stats['per_category'].values())
        skipped = len(stats['skipped_categories'])
        logging.info(
            f"Australia lookups seed {IMPORT_VERSION} complete — "
            f"{total} options across {len(stats['per_category'])} categories, "
            f"{skipped} categories skipped"
        )
        return stats
    finally:
        try:
            conn.close()
        except Exception:
            pass
