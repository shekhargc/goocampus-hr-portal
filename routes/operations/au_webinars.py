"""
routes/operations/au_webinars.py — Operations: AMC Pathway
Webinars & Conferences list + detail + edit.

Surfaces rows from ops_webinars_conferences WHERE pathway='australia',
joined to plab_clients on registration_number so we can show the
candidate name. Records are imported one-time from
All_Australia_Webinars.xlsx by
import_australia_webinars.run_import_australia_webinars_once() at app
boot.

Standardised to the PLAB / Australia Training pattern: list (with
drawer) + detail page + edit form. The "webinar_conference_name" field
in the UI maps to the DB column `event_name`.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db


# ── Editable columns on ops_webinars_conferences (pathway='australia') ─
# Only safe-to-edit fields. id / registration_number / pathway never
# editable. The UI calls `event_name` "Webinar / Conference Name".
AU_WEBINARS_EDITABLE_COLUMNS = [
    'event_type', 'participation_type', 'event_value',
    'start_date', 'end_date', 'duration_days',
    'event_name', 'cpd_points', 'notes',
]

# Numeric columns get coerced to float; bad data -> None.
_NUMERIC_COLUMNS = {
    'amount', 'score', 'points', 'duration',
    'cpd_points', 'duration_days',
}


@admin_required
def ops_australia_webinars_list():
    """Australia webinars & conferences list — ops_webinars_conferences WHERE pathway='australia'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    event_type_filter = (request.args.get('event_type', '') or '').strip()
    participation_filter = (request.args.get('participation', '') or '').strip()
    event_value_filter = (request.args.get('event_value', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    event_types = []
    participations = []
    event_values = []
    total = 0

    try:
        sql = '''SELECT w.id, w.registration_number, w.event_type,
                        w.start_date, w.end_date, w.duration_days,
                        w.event_value, w.cpd_points, w.event_name,
                        w.participation_type, w.notes,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_webinars_conferences w
                   LEFT JOIN plab_clients p
                          ON w.registration_number = p.registration_number
                  WHERE w.pathway = 'australia' '''
        params = []
        if reg:
            sql += " AND w.registration_number = ? "
            params.append(reg)
        if event_type_filter:
            sql += " AND w.event_type = ? "
            params.append(event_type_filter)
        if participation_filter:
            sql += " AND w.participation_type = ? "
            params.append(participation_filter)
        if event_value_filter:
            sql += " AND w.event_value = ? "
            params.append(event_value_filter)
        if search:
            sql += """ AND (
                p.first_name LIKE ? OR p.last_name LIKE ? OR
                w.event_name LIKE ? OR w.registration_number LIKE ? OR
                w.notes LIKE ?
            ) """
            params.extend([f'%{search}%'] * 5)
        # Recent-first: order by start_date DESC NULLS LAST, then id DESC.
        sql += " ORDER BY w.start_date DESC NULLS LAST, w.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        event_types = [
            r['event_type'] for r in conn.execute(
                """SELECT DISTINCT event_type FROM ops_webinars_conferences
                    WHERE pathway = 'australia' AND event_type IS NOT NULL AND event_type != ''
                    ORDER BY event_type"""
            ).fetchall()
        ]
        participations = [
            r['participation_type'] for r in conn.execute(
                """SELECT DISTINCT participation_type FROM ops_webinars_conferences
                    WHERE pathway = 'australia' AND participation_type IS NOT NULL AND participation_type != ''
                    ORDER BY participation_type"""
            ).fetchall()
        ]
        event_values = [
            r['event_value'] for r in conn.execute(
                """SELECT DISTINCT event_value FROM ops_webinars_conferences
                    WHERE pathway = 'australia' AND event_value IS NOT NULL AND event_value != ''
                    ORDER BY event_value"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_australia_webinars_list: {e}")
        flash(f'Error loading Australia webinars & conferences: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_webinars_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        event_type_filter=event_type_filter,
        participation_filter=participation_filter,
        event_value_filter=event_value_filter,
        client_reg=reg,
        event_types=event_types,
        participations=participations,
        event_values=event_values,
        pathway_name='AMC Pathway',
        active_ops_page='australia-webinars',
        active_pathway='australia',
    )


@admin_required
def ops_australia_webinars_detail(rid):
    """Read-only detail view for one Australia webinar/conference row.

    LEFT JOIN plab_clients via registration_number so we can render the
    candidate's name in the header. Mirrors the PLAB-style detail layout
    (header card + two-column grid + Edit button).
    """
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT w.*, p.first_name, p.last_name, p.prefix,
                      p.mobile, p.email
                 FROM ops_webinars_conferences w
            LEFT JOIN plab_clients p
                   ON w.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'australia'
                WHERE w.id = ?
                  AND COALESCE(w.pathway, 'plab') = 'australia' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_australia_webinars_detail: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Australia webinar/conference record not found.', 'error')
        return redirect(url_for('ops_australia_webinars_list'))

    return render_template(
        'ops_australia_webinars_detail.html',
        user=user,
        record=record,
        pathway_name='AMC Pathway',
        active_ops_page='australia-webinars',
        active_pathway='australia',
    )


@admin_required
def ops_australia_webinars_edit_page(rid):
    """GET — render the edit form for one Australia webinar/conference row."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT w.*, p.first_name, p.last_name, p.prefix
                 FROM ops_webinars_conferences w
            LEFT JOIN plab_clients p
                   ON w.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'australia'
                WHERE w.id = ?
                  AND COALESCE(w.pathway, 'plab') = 'australia' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_australia_webinars_edit_page: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Australia webinar/conference record not found.', 'error')
        return redirect(url_for('ops_australia_webinars_list'))

    return render_template(
        'ops_australia_webinars_edit.html',
        user=user,
        record=record,
        pathway_name='AMC Pathway',
        active_ops_page='australia-webinars',
        active_pathway='australia',
    )


@admin_required
def ops_australia_webinars_edit_save(rid):
    """POST — save changes to an Australia webinar/conference row.

    Strict allowlist (AU_WEBINARS_EDITABLE_COLUMNS). pathway is NEVER
    updated through this endpoint. The UPDATE always includes a
    pathway clause so PLAB rows cannot be modified by mistake.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM ops_webinars_conferences WHERE id = ? AND COALESCE(pathway, 'plab') = 'australia'",
            (rid,),
        ).fetchone()
        if not existing:
            flash('Australia webinar/conference record not found.', 'error')
            return redirect(url_for('ops_australia_webinars_list'))

        sets = []
        params = []
        for col in AU_WEBINARS_EDITABLE_COLUMNS:
            if col in request.form:
                val = request.form.get(col, '').strip()
                # Numeric columns get coerced to float; empty -> None.
                if col in _NUMERIC_COLUMNS:
                    if not val:
                        val = None
                    else:
                        try:
                            val = float(val)
                        except ValueError:
                            val = None
                elif val == '':
                    # Empty strings get stored as NULL so they don't
                    # break downstream COALESCE() / date-parse logic.
                    val = None
                sets.append(f"{col} = ?")
                params.append(val)
        if sets:
            params.append(rid)
            conn.execute(
                f"UPDATE ops_webinars_conferences SET {', '.join(sets)} "
                f" WHERE id = ? AND COALESCE(pathway, 'plab') = 'australia'",
                params,
            )
            conn.commit()
            flash('Webinar / conference record saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_australia_webinars_edit_save: {e}")
        flash(f'Error saving webinar / conference record: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_australia_webinars_detail', rid=rid))


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/australia/webinars',
        endpoint='ops_australia_webinars_list',
        view_func=ops_australia_webinars_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/webinars/<int:rid>',
        endpoint='ops_australia_webinars_detail',
        view_func=ops_australia_webinars_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/webinars/<int:rid>/edit',
        endpoint='ops_australia_webinars_edit_page',
        view_func=ops_australia_webinars_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/webinars/<int:rid>/edit',
        endpoint='ops_australia_webinars_edit_save',
        view_func=ops_australia_webinars_edit_save,
        methods=['POST'],
    )
