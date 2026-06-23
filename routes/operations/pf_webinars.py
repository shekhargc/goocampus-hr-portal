"""
routes/operations/pf_webinars.py — Operations: Portfolio Pathway
Webinars & Conferences list + detail + edit.

Surfaces rows from ops_webinars_conferences WHERE pathway='portfolio',
joined to plab_clients on registration_number so we can show the
candidate name. Records are imported one-time from
All_Portfolio_Webinars.xlsx by
import_consulting_webinars.run_import_consulting_webinars_once() at app
boot.

Standardised to the PLAB / Portfolio Training pattern: list (with
drawer) + detail page + edit form. The "webinar_conference_name" field
in the UI maps to the DB column `event_name`.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
# Pathway-scoped dropdown options for the AMC Webinars & Conferences edit form.
from routes.operations._form_lookups import section_webinars_lookups
# Cross-DB column-existence check (SQLite PRAGMA / Postgres information_schema).
from routes.operations.au_test_bookings import _existing_columns


# ── Editable columns on ops_webinars_conferences (pathway='portfolio') ─
# Only safe-to-edit fields. id / registration_number / pathway never
# editable. The UI calls `event_name` "Webinar / Conference Name".
# `provider` is the vendor the event_type cascades from; it is only written
# when the column actually exists on this DB (guarded in the save handlers).
AU_WEBINARS_EDITABLE_COLUMNS = [
    'provider',
    'event_type', 'participation_type', 'event_value', 'event_status',
    'start_date', 'end_date', 'duration_days',
    'event_name', 'cpd_points', 'notes',
]

# Numeric columns get coerced to float; bad data -> None.
_NUMERIC_COLUMNS = {
    'amount', 'score', 'points', 'duration',
    'cpd_points', 'duration_days',
}


@admin_required
def ops_portfolio_webinars_list():
    """Portfolio webinars & conferences list — ops_webinars_conferences WHERE pathway='portfolio'."""
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
                  WHERE w.pathway = 'portfolio' '''
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
                p.first_name ILIKE ? OR p.last_name ILIKE ? OR
                w.event_name ILIKE ? OR w.registration_number ILIKE ? OR
                w.notes ILIKE ? OR
                (COALESCE(p.prefix,'')||' '||p.first_name||' '||COALESCE(p.last_name,'')) ILIKE ?
            ) """
            params.extend([f'%{search}%'] * 6)
        # Recent-first: order by start_date DESC NULLS LAST, then id DESC.
        sql += " ORDER BY w.start_date DESC NULLS LAST, w.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        event_types = [
            r['event_type'] for r in conn.execute(
                """SELECT DISTINCT event_type FROM ops_webinars_conferences
                    WHERE pathway = 'portfolio' AND event_type IS NOT NULL AND event_type != ''
                    ORDER BY event_type"""
            ).fetchall()
        ]
        participations = [
            r['participation_type'] for r in conn.execute(
                """SELECT DISTINCT participation_type FROM ops_webinars_conferences
                    WHERE pathway = 'portfolio' AND participation_type IS NOT NULL AND participation_type != ''
                    ORDER BY participation_type"""
            ).fetchall()
        ]
        event_values = [
            r['event_value'] for r in conn.execute(
                """SELECT DISTINCT event_value FROM ops_webinars_conferences
                    WHERE pathway = 'portfolio' AND event_value IS NOT NULL AND event_value != ''
                    ORDER BY event_value"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_portfolio_webinars_list: {e}")
        flash(f'Error loading Portfolio webinars & conferences: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_portfolio_webinars_list.html',
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
        pathway_name='Portfolio Pathway',
        active_ops_page='portfolio-webinars',
        active_pathway='portfolio',
    )


@admin_required
def ops_portfolio_webinars_detail(rid):
    """Read-only detail view for one Portfolio webinar/conference row.

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
                  AND COALESCE(p.pathway, 'plab') = 'portfolio'
                WHERE w.id = ?
                  AND COALESCE(w.pathway, 'plab') = 'portfolio' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_portfolio_webinars_detail: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Portfolio webinar/conference record not found.', 'error')
        return redirect(url_for('ops_portfolio_webinars_list'))

    return render_template(
        'ops_portfolio_webinars_detail.html',
        user=user,
        record=record,
        pathway_name='Portfolio Pathway',
        active_ops_page='portfolio-webinars',
        active_pathway='portfolio',
    )


@admin_required
def ops_portfolio_webinars_edit_page(rid):
    """GET — render the edit form for one Portfolio webinar/conference row."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT w.*, p.first_name, p.last_name, p.prefix
                 FROM ops_webinars_conferences w
            LEFT JOIN plab_clients p
                   ON w.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'portfolio'
                WHERE w.id = ?
                  AND COALESCE(w.pathway, 'plab') = 'portfolio' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_portfolio_webinars_edit_page: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Portfolio webinar/conference record not found.', 'error')
        return redirect(url_for('ops_portfolio_webinars_list'))

    return render_template(
        'ops_portfolio_webinars_edit.html',
        user=user,
        record=record,
        pathway_name='Portfolio Pathway',
        active_ops_page='portfolio-webinars',
        active_pathway='portfolio',
        # Dropdown options sourced from lookup_options where pathway='portfolio'.
        **section_webinars_lookups('portfolio'),
    )


@admin_required
def ops_portfolio_webinars_edit_save(rid):
    """POST — save changes to an Portfolio webinar/conference row.

    Strict allowlist (AU_WEBINARS_EDITABLE_COLUMNS). pathway is NEVER
    updated through this endpoint. The UPDATE always includes a
    pathway clause so PLAB rows cannot be modified by mistake.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM ops_webinars_conferences WHERE id = ? AND COALESCE(pathway, 'plab') = 'portfolio'",
            (rid,),
        ).fetchone()
        if not existing:
            flash('Portfolio webinar/conference record not found.', 'error')
            return redirect(url_for('ops_portfolio_webinars_list'))

        # Skip any editable column not present on this DB (e.g. provider on
        # an older schema) so the UPDATE never references a missing column.
        db_cols = _existing_columns(conn, 'ops_webinars_conferences')

        sets = []
        params = []
        for col in AU_WEBINARS_EDITABLE_COLUMNS:
            if col in request.form:
                if db_cols and col not in db_cols:
                    continue
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
                f" WHERE id = ? AND COALESCE(pathway, 'plab') = 'portfolio'",
                params,
            )
            conn.commit()
            flash('Webinar / conference record saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_portfolio_webinars_edit_save: {e}")
        flash(f'Error saving webinar / conference record: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_portfolio_webinars_detail', rid=rid))


@admin_required
def ops_portfolio_webinars_add_page():
    """GET — render the empty add form (reuses the edit template)."""
    user = get_user()
    empty_record = {col: None for col in AU_WEBINARS_EDITABLE_COLUMNS}
    empty_record['id'] = None
    empty_record['registration_number'] = ''
    empty_record['first_name'] = ''
    empty_record['last_name'] = ''
    empty_record['prefix'] = ''
    return render_template(
        'ops_portfolio_webinars_edit.html',
        user=user,
        record=empty_record,
        is_new=True,
        pathway_name='Portfolio Pathway',
        active_ops_page='portfolio-webinars',
        active_pathway='portfolio',
        # Dropdown options sourced from lookup_options where pathway='portfolio'.
        **section_webinars_lookups('portfolio'),
    )


@admin_required
def ops_portfolio_webinars_add_save():
    """POST — insert a new Portfolio webinar / conference row."""
    conn = get_db()
    try:
        reg = (request.form.get('registration_number') or '').strip()
        if not reg:
            flash('Registration number is required.', 'error')
            return redirect(url_for('ops_portfolio_webinars_add_page'))
        db_cols = _existing_columns(conn, 'ops_webinars_conferences')
        cols = ['registration_number', 'pathway']
        vals = [reg, 'portfolio']
        for col in AU_WEBINARS_EDITABLE_COLUMNS:
            if col in request.form:
                if db_cols and col not in db_cols:
                    continue
                v = (request.form.get(col) or '').strip()
                if col in _NUMERIC_COLUMNS:
                    if not v:
                        v = None
                    else:
                        try:
                            v = float(v)
                        except ValueError:
                            v = None
                elif v == '':
                    v = None
                cols.append(col)
                vals.append(v)
        # Record who created this row (logged-in team member).
        if 'created_by' not in cols:
            cols.append('created_by')
            vals.append((get_user() or {}).get('id'))
        placeholders = ', '.join(['?'] * len(cols))
        cur = conn.execute(
            f"INSERT INTO ops_webinars_conferences ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
            vals,
        )
        new_id = cur.fetchone()['id']
        conn.commit()
        flash('Webinar / conference record added.', 'success')
        return redirect(url_for('ops_portfolio_webinars_detail', rid=new_id))
    except Exception as e:
        logging.error(f"ops_portfolio_webinars_add_save: {e}")
        flash(f'Error: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
        return redirect(url_for('ops_portfolio_webinars_list'))
    finally:
        conn.close()


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/portfolio/webinars',
        endpoint='ops_portfolio_webinars_list',
        view_func=ops_portfolio_webinars_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/portfolio/webinars/<int:rid>',
        endpoint='ops_portfolio_webinars_detail',
        view_func=ops_portfolio_webinars_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/portfolio/webinars/add',
        endpoint='ops_portfolio_webinars_add_page',
        view_func=ops_portfolio_webinars_add_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/portfolio/webinars/add',
        endpoint='ops_portfolio_webinars_add_save',
        view_func=ops_portfolio_webinars_add_save,
        methods=['POST'],
    )
    app.add_url_rule(
        '/operations/portfolio/webinars/<int:rid>/edit',
        endpoint='ops_portfolio_webinars_edit_page',
        view_func=ops_portfolio_webinars_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/portfolio/webinars/<int:rid>/edit',
        endpoint='ops_portfolio_webinars_edit_save',
        view_func=ops_portfolio_webinars_edit_save,
        methods=['POST'],
    )
