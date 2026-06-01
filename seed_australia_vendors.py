"""
seed_australia_vendors.py — auto-populate vendors_providers + vendor_service_map
for the Australia Pathway from the data we already imported.

The user pointed out that the historical Excel imports already contain every
vendor / provider / course / subscription name we need. Rather than asking
them for a separate vendor Excel, we extract those distinct names from the
existing ops_* tables (scoped to pathway='australia') and insert them into
the shared centralised tables with country='Australia Pathway'.

What it does, in order:

1. ops_coaching.vendor_provider + english_training (Australia rows)
     -> vendors_providers (category='Training Programs', country='Australia
        Pathway')
     -> vendor_service_map (one row per distinct training program the vendor
        offers, so the PLAB-style cascade works: pick vendor -> training
        dropdown filters to that vendor's services)

2. ops_online_subscriptions.online_subscription (Australia rows)
     -> vendors_providers (category='Online Subscriptions', country='Australia
        Pathway') — the subscription name doubles as the vendor here
     -> vendor_service_map links the subscription back to itself as a service

3. ops_research_publication.research_provider (Australia rows)
     -> vendors_providers (category='Research & Publications', country=
        'Australia Pathway')

Idempotent via _import_markers marker key 'au_vendors_seed'. Bump
IMPORT_VERSION to force a re-run. Runs on app boot AFTER the Phase 2/3
imports so the source rows exist.
"""

import logging


IMPORT_VERSION = 'au_vendors_v1'
AU_COUNTRY = 'Australia Pathway'


def _vendor_id_or_rowid(row):
    """Return id from row, falling back to rowid for SQLite dev DBs where
    SERIAL doesn't auto-increment. Postgres always populates id."""
    if row is None:
        return None
    rid = row['id'] if 'id' in row.keys() else None
    if rid is not None:
        return rid
    try:
        return row['rowid']
    except Exception:
        return None


def _ensure_vendor(conn, name, category):
    """Return (vendor_id, created) — insert if missing, otherwise return existing id.

    Vendors are uniquely identified by (name, country, category). We use
    country='Australia Pathway' for everything here. Falls back to rowid on
    SQLite where SERIAL columns may not auto-populate.
    """
    row = conn.execute(
        "SELECT rowid, id FROM vendors_providers "
        "WHERE name = ? AND country = ? AND category = ?",
        (name, AU_COUNTRY, category),
    ).fetchone()
    if row:
        return _vendor_id_or_rowid(row), False
    # Pick next sort_order for this category
    max_so = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS m "
        "FROM vendors_providers WHERE country = ? AND category = ?",
        (AU_COUNTRY, category),
    ).fetchone()['m']
    conn.execute(
        "INSERT INTO vendors_providers (name, country, category, is_active, sort_order) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, AU_COUNTRY, category, 1, max_so + 1),
    )
    new_row = conn.execute(
        "SELECT rowid, id FROM vendors_providers "
        "WHERE name = ? AND country = ? AND category = ? "
        "ORDER BY rowid DESC LIMIT 1",
        (name, AU_COUNTRY, category),
    ).fetchone()
    return _vendor_id_or_rowid(new_row), True


def _ensure_service(conn, vendor_id, service_name):
    """Link a service to a vendor (idempotent)."""
    if not vendor_id or not service_name:
        return False
    existing = conn.execute(
        "SELECT id FROM vendor_service_map WHERE vendor_id = ? AND service_name = ?",
        (vendor_id, service_name),
    ).fetchone()
    if existing:
        return False
    conn.execute(
        "INSERT INTO vendor_service_map (vendor_id, service_name) VALUES (?, ?)",
        (vendor_id, service_name),
    )
    return True


def run_seed_australia_vendors_once(get_db_fn):
    """Populate vendors_providers + vendor_service_map for Australia.

    Returns a stats dict for logging / inspection.
    """
    conn = get_db_fn()
    try:
        # Marker table
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS _import_markers (key TEXT PRIMARY KEY, value TEXT)")
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
        marker = conn.execute(
            "SELECT value FROM _import_markers WHERE key = 'au_vendors_seed'"
        ).fetchone()
        if marker and marker['value'] == IMPORT_VERSION:
            logging.info(f"AU vendors seed: already at {IMPORT_VERSION}, skipping")
            return {'training': 0, 'online_subs': 0, 'research': 0, 'services_added': 0}

        logging.info(f"AU vendors seed: starting {IMPORT_VERSION}...")
        stats = {
            'training_vendors_added':       0,
            'online_subs_vendors_added':    0,
            'research_vendors_added':       0,
            'services_added':               0,
        }

        # ── 1. Training vendors (ops_coaching.vendor_provider) ──────────
        try:
            rows = conn.execute(
                "SELECT DISTINCT TRIM(vendor_provider) AS vendor, "
                "                TRIM(COALESCE(english_training, '')) AS service "
                "FROM ops_coaching "
                "WHERE COALESCE(pathway, 'plab') = 'australia' "
                "  AND vendor_provider IS NOT NULL "
                "  AND TRIM(vendor_provider) != ''"
            ).fetchall()
        except Exception as e:
            logging.warning(f"AU vendors: training extract failed: {e}")
            rows = []

        for row in rows:
            vendor_name = row['vendor']
            service = row['service']
            vid, created = _ensure_vendor(conn, vendor_name, 'Training Programs')
            if created:
                stats['training_vendors_added'] += 1
            if service and _ensure_service(conn, vid, service):
                stats['services_added'] += 1
        conn.commit()

        # ── 2. Online Subscriptions vendors ─────────────────────────────
        # The subscription name IS the vendor here (e.g., 'MplusX', 'eMedici').
        try:
            rows = conn.execute(
                "SELECT DISTINCT TRIM(online_subscription) AS sub "
                "FROM ops_online_subscriptions "
                "WHERE COALESCE(pathway, 'plab') = 'australia' "
                "  AND online_subscription IS NOT NULL "
                "  AND TRIM(online_subscription) != ''"
            ).fetchall()
        except Exception as e:
            logging.warning(f"AU vendors: online subs extract failed: {e}")
            rows = []

        for row in rows:
            sub_name = row['sub']
            vid, created = _ensure_vendor(conn, sub_name, 'Online Subscriptions')
            if created:
                stats['online_subs_vendors_added'] += 1
            # A subscription provider's "service" is itself (so cascade dropdowns
            # showing "subscription_type" can be populated for Australia).
            if _ensure_service(conn, vid, sub_name):
                stats['services_added'] += 1
        conn.commit()

        # ── 3. Research providers (ops_research_publication.research_provider) ──
        try:
            rows = conn.execute(
                "SELECT DISTINCT TRIM(research_provider) AS rp "
                "FROM ops_research_publication "
                "WHERE COALESCE(pathway, 'plab') = 'australia' "
                "  AND research_provider IS NOT NULL "
                "  AND TRIM(research_provider) != ''"
            ).fetchall()
        except Exception as e:
            logging.warning(f"AU vendors: research extract failed: {e}")
            rows = []

        for row in rows:
            rp_name = row['rp']
            vid, created = _ensure_vendor(conn, rp_name, 'Research & Publications')
            if created:
                stats['research_vendors_added'] += 1
            if _ensure_service(conn, vid, rp_name):
                stats['services_added'] += 1
        conn.commit()

        # Marker write — both ON CONFLICT and fallback paths.
        try:
            conn.execute(
                "INSERT INTO _import_markers (key, value) VALUES ('au_vendors_seed', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (IMPORT_VERSION,),
            )
            conn.commit()
        except Exception:
            try:
                conn.execute("DELETE FROM _import_markers WHERE key = 'au_vendors_seed'")
                conn.execute(
                    "INSERT INTO _import_markers (key, value) VALUES ('au_vendors_seed', ?)",
                    (IMPORT_VERSION,),
                )
                conn.commit()
            except Exception as e:
                logging.warning(f"AU vendors seed: marker write failed: {e}")

        total_vendors = (stats['training_vendors_added']
                       + stats['online_subs_vendors_added']
                       + stats['research_vendors_added'])
        logging.info(
            f"AU vendors seed {IMPORT_VERSION}: "
            f"{total_vendors} vendors added "
            f"(training={stats['training_vendors_added']}, "
            f"online_subs={stats['online_subs_vendors_added']}, "
            f"research={stats['research_vendors_added']}), "
            f"{stats['services_added']} services linked"
        )
        return stats
    finally:
        try:
            conn.close()
        except Exception:
            pass
