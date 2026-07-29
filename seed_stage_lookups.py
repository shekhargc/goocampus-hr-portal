"""seed_stage_lookups.py — give every pathway its OWN Client & Pipeline dropdowns.

The Field Manager only ever showed a PLAB-only "PLAB Stages" field and no
pathway-scoped "Current Stage", so Training/Portfolio/UAE had no stage list of
their own and silently borrowed PLAB's. This seeds each pathway's Current Stage,
Account Status, Joined Stage, Plan Type and Lead Source from that pathway's OWN
existing records (the values already in use), registers a real "Current Stage"
field in settings, and retires the legacy "PLAB Stages" field from the UI.

STRICTLY ADDITIVE — it only INSERTs dropdown options and one field_registry row,
and flips the legacy field's is_active flag. It NEVER touches any client's data,
never edits an existing option, and skips anything already present. Idempotent;
safe to run on every boot and on demand. (founder 2026-07-29)
"""
import logging

# Client-level dropdowns that should be per-pathway, and the plab_clients column
# each is sourced from (the real values already recorded for that pathway).
_STAGE_CATEGORIES = [
    ('current_stage',  'current_stage'),
    ('account_status', 'account_status'),
    ('joined_stage',   'joined_stage'),
    ('plan_type',      'plan_type'),
    ('lead_source',    'lead_source'),
]
_PATHWAYS = ['plab', 'consulting', 'australia', 'training', 'portfolio', 'uae']


def _has_column(conn, table, column):
    try:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? AND column_name = ?", (table, column)).fetchall()
        return bool(rows)
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return False


def run_seed_stage_lookups_once(get_db):
    result = {'options': 0, 'registry': 0, 'retired_plab_stage': False, 'errors': []}

    # ── 1. Per-pathway option values from that pathway's own records ──
    for pathway in _PATHWAYS:
        for category, column in _STAGE_CATEGORIES:
            conn = get_db()
            try:
                if not _has_column(conn, 'plab_clients', column):
                    conn.close(); continue
                rows = conn.execute(
                    f"SELECT DISTINCT {column} AS v FROM plab_clients "
                    "WHERE COALESCE(pathway,'plab') = ? AND COALESCE(" + column + ",'') <> '' "
                    f"ORDER BY {column}", (pathway,)).fetchall()
                values = [r['v'] for r in rows if (r['v'] or '').strip()]
                # PLAB's curated stage list historically lived under 'plab_stage' —
                # carry it into current_stage so PLAB's dropdown keeps every option.
                if pathway == 'plab' and category == 'current_stage':
                    try:
                        extra = conn.execute(
                            "SELECT DISTINCT value AS v FROM lookup_options "
                            "WHERE category = 'plab_stage' AND COALESCE(pathway,'plab')='plab' "
                            "AND COALESCE(value,'') <> ''").fetchall()
                        for e in extra:
                            if e['v'] and e['v'] not in values:
                                values.append(e['v'])
                    except Exception:
                        conn.rollback()
                for i, v in enumerate(values):
                    v = (v or '').strip()
                    if not v:
                        continue
                    exists = conn.execute(
                        "SELECT 1 FROM lookup_options WHERE category = ? AND value = ? "
                        "AND COALESCE(pathway,'plab') = ?", (category, v, pathway)).fetchone()
                    if not exists:
                        conn.execute(
                            "INSERT INTO lookup_options (category, label, value, pathway, "
                            "is_active, sort_order) VALUES (?, ?, ?, ?, TRUE, ?)",
                            (category, v, v, pathway, i))
                        result['options'] += 1
                conn.commit()
            except Exception as e:
                try: conn.rollback()
                except Exception: pass
                result['errors'].append(f"{pathway}/{category}: {e}")
            finally:
                try: conn.close()
                except Exception: pass

    # ── 2. Register a real "Current Stage" field in the Field Manager ──
    conn = get_db()
    try:
        exists = conn.execute(
            "SELECT 1 FROM field_registry WHERE field_name = 'current_stage'").fetchone()
        if not exists:
            # Place it in Client & Pipeline just after Account Statuses.
            conn.execute(
                "INSERT INTO field_registry (section, field_name, field_label, field_type, "
                "lookup_category, display_order, is_active) VALUES "
                "('Client & Pipeline', 'current_stage', 'Current Stage', 'select', "
                "'current_stage', 2, TRUE)")
            result['registry'] += 1
        conn.commit()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        result['errors'].append(f"register current_stage: {e}")
    finally:
        try: conn.close()
        except Exception: pass

    # ── 3. Retire the legacy PLAB-only "PLAB Stages" field from the settings UI ──
    #      (values stay in lookup_options; only the editor is hidden, on every tab).
    conn = get_db()
    try:
        conn.execute("UPDATE field_registry SET is_active = FALSE WHERE field_name = 'plab_stage'")
        conn.commit()
        result['retired_plab_stage'] = True
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        result['errors'].append(f"retire plab_stage: {e}")
    finally:
        try: conn.close()
        except Exception: pass

    logging.info(f"seed_stage_lookups: {result}")
    return result
