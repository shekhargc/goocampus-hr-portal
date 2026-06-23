"""
routes/operations/au_online_subscriptions.py — Operations: Standard Consulting
Online Courses & Subscriptions list view + detail + edit.

Surfaces ops_online_subscriptions WHERE pathway='consulting' — populated
by import_consulting_online_subscriptions.run_import_consulting_online_subscriptions_once()
at app boot.

Mirrors the Consulting Registration pattern: list with drawer, detail page,
edit form. Endpoints:
  - GET  /operations/consulting/online-subscriptions
  - GET  /operations/consulting/online-subscriptions/<rid>
  - GET  /operations/consulting/online-subscriptions/<rid>/edit
  - POST /operations/consulting/online-subscriptions/<rid>/edit
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
# Pathway-scoped dropdown options for the AMC Online Courses edit form.
from routes.operations._form_lookups import section_online_courses_lookups
# Cross-DB column-existence check (SQLite PRAGMA / Postgres information_schema).
from routes.operations.au_test_bookings import _existing_columns


# ── Editable columns on ops_online_subscriptions (pathway='consulting') ──
# id / registration_number / pathway are NOT editable.
# `subscription_provider` is the vendor the online_subscription (course/sub
# name) cascades from; only written when the column exists (guarded in saves).
AU_OC_EDITABLE_COLUMNS = [
    'subscription_provider',
    'online_subscription',
    'activation_type',
    'issued_date',
    'booked_by',
    'login_id',
    'password',
    'notes',
]

# Columns that need numeric coercion (none on this table, but kept for
# parity with the standard pattern).
AU_OC_NUMERIC_COLUMNS = {
    'amount', 'score', 'points', 'duration',
}

# Columns that should render as <input type="date"> on the edit form.
AU_OC_DATE_COLUMNS = {
    'issued_date',
}


@admin_required
def ops_consulting_online_subscriptions_list():
    """Consulting online courses list — ops_online_subscriptions WHERE pathway='consulting'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    course_filter = (request.args.get('course', '') or '').strip()
    activation_filter = (request.args.get('activation', '') or '').strip()
    booked_by_filter = (request.args.get('booked_by', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    courses = []
    activations = []
    booked_bys = []
    total = 0

    try:
        sql = '''SELECT s.id, s.registration_number, s.online_subscription,
                        s.issued_date, s.activation_type, s.notes,
                        s.client_email, s.login_id, s.password,
                        s.booked_by,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_online_subscriptions s
                   LEFT JOIN plab_clients p
                          ON s.registration_number = p.registration_number
                  WHERE s.pathway = 'consulting' '''
        params = []
        if reg:
            sql += " AND s.registration_number = ? "
            params.append(reg)
        if course_filter:
            sql += " AND s.online_subscription = ? "
            params.append(course_filter)
        if activation_filter:
            sql += " AND s.activation_type = ? "
            params.append(activation_filter)
        if booked_by_filter:
            sql += " AND s.booked_by = ? "
            params.append(booked_by_filter)
        if search:
            sql += """ AND (
                p.first_name ILIKE ? OR p.last_name ILIKE ? OR
                s.registration_number ILIKE ? OR s.online_subscription ILIKE ? OR
                s.client_email ILIKE ? OR
                (COALESCE(p.prefix,'')||' '||p.first_name||' '||COALESCE(p.last_name,'')) ILIKE ?
            ) """
            params.extend([f'%{search}%'] * 6)
        # Recent-first: most recently issued at the top, then by id desc.
        sql += " ORDER BY s.issued_date DESC NULLS LAST, s.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        courses = [
            r['online_subscription'] for r in conn.execute(
                """SELECT DISTINCT online_subscription FROM ops_online_subscriptions
                    WHERE pathway = 'consulting' AND online_subscription IS NOT NULL
                      AND online_subscription != ''
                    ORDER BY online_subscription"""
            ).fetchall()
        ]
        activations = [
            r['activation_type'] for r in conn.execute(
                """SELECT DISTINCT activation_type FROM ops_online_subscriptions
                    WHERE pathway = 'consulting' AND activation_type IS NOT NULL
                      AND activation_type != ''
                    ORDER BY activation_type"""
            ).fetchall()
        ]
        booked_bys = [
            r['booked_by'] for r in conn.execute(
                """SELECT DISTINCT booked_by FROM ops_online_subscriptions
                    WHERE pathway = 'consulting' AND booked_by IS NOT NULL
                      AND booked_by != ''
                    ORDER BY booked_by"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_consulting_online_subscriptions_list: {e}")
        flash(f'Error loading Consulting online courses: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_consulting_online_subscriptions_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        course_filter=course_filter,
        activation_filter=activation_filter,
        booked_by_filter=booked_by_filter,
        client_reg=reg,
        courses=courses,
        activations=activations,
        booked_bys=booked_bys,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-online-subscriptions',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_online_subscriptions_detail(rid):
    """Read-only detail page for one Consulting online course subscription.

    Joins to plab_clients on registration_number (pathway='consulting') so
    the page can show the candidate's human name alongside the subscription.
    """
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT s.*, p.first_name, p.last_name, p.prefix
                 FROM ops_online_subscriptions s
                 LEFT JOIN plab_clients p
                        ON s.registration_number = p.registration_number
                       AND COALESCE(p.pathway, 'plab') = 'consulting'
                WHERE s.id = ?
                  AND COALESCE(s.pathway, 'plab') = 'consulting' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_consulting_online_subscriptions_detail: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Online course subscription not found.', 'error')
        return redirect(url_for('ops_consulting_online_subscriptions_list'))

    return render_template(
        'ops_consulting_online_subscriptions_detail.html',
        user=user,
        record=record,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-online-subscriptions',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_online_subscriptions_edit_page(rid):
    """GET — render the edit form for one Consulting online course subscription."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT s.*, p.first_name, p.last_name, p.prefix
                 FROM ops_online_subscriptions s
                 LEFT JOIN plab_clients p
                        ON s.registration_number = p.registration_number
                       AND COALESCE(p.pathway, 'plab') = 'consulting'
                WHERE s.id = ?
                  AND COALESCE(s.pathway, 'plab') = 'consulting' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_consulting_online_subscriptions_edit_page: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Online course subscription not found.', 'error')
        return redirect(url_for('ops_consulting_online_subscriptions_list'))

    return render_template(
        'ops_consulting_online_subscriptions_edit.html',
        user=user,
        record=record,
        editable_columns=AU_OC_EDITABLE_COLUMNS,
        date_columns=AU_OC_DATE_COLUMNS,
        numeric_columns=AU_OC_NUMERIC_COLUMNS,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-online-subscriptions',
        active_pathway='consulting',
        # Dropdown options sourced from lookup_options where pathway='consulting'.
        **section_online_courses_lookups('consulting'),
    )


@admin_required
def ops_consulting_online_subscriptions_edit_save(rid):
    """POST handler: persist edits to one Consulting online course subscription.

    Strict allowlist (AU_OC_EDITABLE_COLUMNS) — anything else in the form is
    silently ignored. Pathway is NEVER updated through this endpoint.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM ops_online_subscriptions WHERE id = ? "
            "  AND COALESCE(pathway, 'plab') = 'consulting'",
            (rid,),
        ).fetchone()
        if not existing:
            flash('Online course subscription not found.', 'error')
            return redirect(url_for('ops_consulting_online_subscriptions_list'))

        # Skip any editable column not present on this DB (e.g.
        # subscription_provider on an older schema) so the UPDATE never
        # references a missing column.
        db_cols = _existing_columns(conn, 'ops_online_subscriptions')

        sets = []
        params = []
        for col in AU_OC_EDITABLE_COLUMNS:
            if col in request.form:
                if db_cols and col not in db_cols:
                    continue
                val = request.form.get(col, '').strip()
                if col in AU_OC_NUMERIC_COLUMNS:
                    try:
                        val = float(val) if val else 0
                    except ValueError:
                        val = 0
                sets.append(f"{col} = ?")
                params.append(val)
        if sets:
            params.append(rid)
            conn.execute(
                f"UPDATE ops_online_subscriptions SET {', '.join(sets)} "
                f" WHERE id = ? AND COALESCE(pathway, 'plab') = 'consulting'",
                params,
            )
            conn.commit()
            flash('Subscription details saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_consulting_online_subscriptions_edit_save: {e}")
        flash(f'Error saving subscription: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_consulting_online_subscriptions_detail', rid=rid))


@admin_required
def ops_consulting_online_subscriptions_add_page():
    """GET — render the empty add form (reuses the edit template)."""
    user = get_user()
    empty_record = {col: None for col in AU_OC_EDITABLE_COLUMNS}
    empty_record['id'] = None
    empty_record['registration_number'] = ''
    empty_record['first_name'] = ''
    empty_record['last_name'] = ''
    empty_record['prefix'] = ''
    return render_template(
        'ops_consulting_online_subscriptions_edit.html',
        user=user,
        record=empty_record,
        is_new=True,
        editable_columns=AU_OC_EDITABLE_COLUMNS,
        date_columns=AU_OC_DATE_COLUMNS,
        numeric_columns=AU_OC_NUMERIC_COLUMNS,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-online-subscriptions',
        active_pathway='consulting',
        # Dropdown options sourced from lookup_options where pathway='consulting'.
        **section_online_courses_lookups('consulting'),
    )


@admin_required
def ops_consulting_online_subscriptions_add_save():
    """POST — insert a new Consulting online course subscription row."""
    conn = get_db()
    try:
        reg = (request.form.get('registration_number') or '').strip()
        if not reg:
            flash('Registration number is required.', 'error')
            return redirect(url_for('ops_consulting_online_subscriptions_add_page'))
        db_cols = _existing_columns(conn, 'ops_online_subscriptions')
        cols = ['registration_number', 'pathway']
        vals = [reg, 'consulting']
        for col in AU_OC_EDITABLE_COLUMNS:
            if col in request.form:
                if db_cols and col not in db_cols:
                    continue
                v = (request.form.get(col) or '').strip() or None
                if col in AU_OC_NUMERIC_COLUMNS:
                    try:
                        v = float(v) if v else None
                    except ValueError:
                        v = None
                cols.append(col)
                vals.append(v)
        # Record who created this row (logged-in team member).
        if 'created_by' not in cols:
            cols.append('created_by')
            vals.append((get_user() or {}).get('id'))
        placeholders = ', '.join(['?'] * len(cols))
        cur = conn.execute(
            f"INSERT INTO ops_online_subscriptions ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
            vals,
        )
        new_id = cur.fetchone()['id']
        conn.commit()
        flash('Online course subscription added.', 'success')
        return redirect(url_for('ops_consulting_online_subscriptions_detail', rid=new_id))
    except Exception as e:
        logging.error(f"ops_consulting_online_subscriptions_add_save: {e}")
        flash(f'Error: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
        return redirect(url_for('ops_consulting_online_subscriptions_list'))
    finally:
        conn.close()


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/consulting/online-subscriptions',
        endpoint='ops_consulting_online_subscriptions_list',
        view_func=ops_consulting_online_subscriptions_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/online-subscriptions/<int:rid>',
        endpoint='ops_consulting_online_subscriptions_detail',
        view_func=ops_consulting_online_subscriptions_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/online-subscriptions/add',
        endpoint='ops_consulting_online_subscriptions_add_page',
        view_func=ops_consulting_online_subscriptions_add_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/online-subscriptions/add',
        endpoint='ops_consulting_online_subscriptions_add_save',
        view_func=ops_consulting_online_subscriptions_add_save,
        methods=['POST'],
    )
    app.add_url_rule(
        '/operations/consulting/online-subscriptions/<int:rid>/edit',
        endpoint='ops_consulting_online_subscriptions_edit_page',
        view_func=ops_consulting_online_subscriptions_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/online-subscriptions/<int:rid>/edit',
        endpoint='ops_consulting_online_subscriptions_edit_save',
        view_func=ops_consulting_online_subscriptions_edit_save,
        methods=['POST'],
    )
