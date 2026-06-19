"""
routes/operations/au_training.py — Operations: Consulting Training list + detail/edit.

Lists ops_coaching records imported from "All Trainings.xlsx" (stored in
the repo as All_Consulting_Trainings.xlsx) for the Standard Consulting.

The legacy DB table name is `ops_coaching` even though the Excel and the
UI both call it Training. We filter by pathway='consulting' so this view
never crosses streams with PLAB coaching rows.

A LEFT JOIN onto plab_clients on registration_number gives us the
candidate's display name (prefix + first + last).

Standardised to PLAB pattern: list (with drawer) + detail page + edit form.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
# Pathway-scoped dropdown options for the AMC Training edit form.
from routes.operations._form_lookups import section_training_lookups


# ── Editable columns on ops_coaching (pathway='consulting' scope) ────────
# Only safe-to-edit fields. id / registration_number / pathway are NOT editable.
AU_TRAINING_EDITABLE_COLUMNS = [
    'english_training', 'course_type', 'coaching_method',
    'vendor_provider', 'booked_by',
    'batch_year', 'batch_month',
    'start_date', 'end_date',
    'coaching_status',
]

# Numeric columns get coerced to float; bad data -> None.
_NUMERIC_COLUMNS = {
    'amount', 'score', 'points', 'duration',
}


@admin_required
def ops_consulting_training_list():
    """Consulting training list — ops_coaching WHERE pathway='consulting'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    course_filter = (request.args.get('course', '') or '').strip()
    method_filter = (request.args.get('method', '') or '').strip()
    status_filter = (request.args.get('status', '') or '').strip()
    vendor_filter = (request.args.get('vendor', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    courses = []
    methods = []
    statuses = []
    vendors = []
    total = 0

    try:
        sql = '''SELECT t.id, t.registration_number, t.course_type,
                        t.coaching_method, t.coaching_status,
                        t.batch_month, t.batch_year,
                        t.start_date, t.end_date,
                        t.vendor_provider, t.other_vendor,
                        t.english_training,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_coaching t
                   LEFT JOIN plab_clients p
                          ON t.registration_number = p.registration_number
                  WHERE t.pathway = 'consulting' '''
        params = []
        if reg:
            sql += " AND t.registration_number = ? "
            params.append(reg)
        if course_filter:
            sql += " AND t.course_type = ? "
            params.append(course_filter)
        if method_filter:
            sql += " AND t.coaching_method = ? "
            params.append(method_filter)
        if status_filter:
            sql += " AND t.coaching_status = ? "
            params.append(status_filter)
        if vendor_filter:
            sql += " AND t.vendor_provider = ? "
            params.append(vendor_filter)
        if search:
            sql += """ AND (
                p.first_name LIKE ? OR p.last_name LIKE ? OR
                t.vendor_provider LIKE ? OR t.english_training LIKE ? OR
                t.registration_number LIKE ?
            ) """
            params.extend([f'%{search}%'] * 5)
        # Recent-first: order by start_date DESC NULLS LAST, then id DESC.
        sql += " ORDER BY t.start_date DESC NULLS LAST, t.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        courses = [
            r['course_type'] for r in conn.execute(
                """SELECT DISTINCT course_type FROM ops_coaching
                    WHERE pathway = 'consulting' AND course_type IS NOT NULL AND course_type != ''
                    ORDER BY course_type"""
            ).fetchall()
        ]
        methods = [
            r['coaching_method'] for r in conn.execute(
                """SELECT DISTINCT coaching_method FROM ops_coaching
                    WHERE pathway = 'consulting' AND coaching_method IS NOT NULL AND coaching_method != ''
                    ORDER BY coaching_method"""
            ).fetchall()
        ]
        statuses = [
            r['coaching_status'] for r in conn.execute(
                """SELECT DISTINCT coaching_status FROM ops_coaching
                    WHERE pathway = 'consulting' AND coaching_status IS NOT NULL AND coaching_status != ''
                    ORDER BY coaching_status"""
            ).fetchall()
        ]
        vendors = [
            r['vendor_provider'] for r in conn.execute(
                """SELECT DISTINCT vendor_provider FROM ops_coaching
                    WHERE pathway = 'consulting' AND vendor_provider IS NOT NULL AND vendor_provider != ''
                    ORDER BY vendor_provider"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_consulting_training_list: {e}")
        flash(f'Error loading Consulting training: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_consulting_training_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        course_filter=course_filter,
        method_filter=method_filter,
        status_filter=status_filter,
        vendor_filter=vendor_filter,
        client_reg=reg,
        courses=courses,
        methods=methods,
        statuses=statuses,
        vendors=vendors,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-training',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_training_detail(rid):
    """Read-only detail view for one Consulting training row.

    LEFT JOIN plab_clients via registration_number so we can render the
    candidate's name in the header. Mirrors the PLAB-style client detail
    layout (header card + two-column grid + Edit button).
    """
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT t.*, p.first_name, p.last_name, p.prefix,
                      p.mobile, p.email
                 FROM ops_coaching t
            LEFT JOIN plab_clients p
                   ON t.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'consulting'
                WHERE t.id = ?
                  AND COALESCE(t.pathway, 'plab') = 'consulting' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_consulting_training_detail: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Consulting training record not found.', 'error')
        return redirect(url_for('ops_consulting_training_list'))

    return render_template(
        'ops_consulting_training_detail.html',
        user=user,
        record=record,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-training',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_training_edit_page(rid):
    """GET — render the edit form for one Consulting training row."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT t.*, p.first_name, p.last_name, p.prefix
                 FROM ops_coaching t
            LEFT JOIN plab_clients p
                   ON t.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'consulting'
                WHERE t.id = ?
                  AND COALESCE(t.pathway, 'plab') = 'consulting' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_consulting_training_edit_page: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Consulting training record not found.', 'error')
        return redirect(url_for('ops_consulting_training_list'))

    return render_template(
        'ops_consulting_training_edit.html',
        user=user,
        record=record,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-training',
        active_pathway='consulting',
        # Dropdown options sourced from lookup_options where pathway='consulting'.
        **section_training_lookups('consulting'),
    )


@admin_required
def ops_consulting_training_edit_save(rid):
    """POST — save changes to an Consulting training row.

    Strict allowlist (AU_TRAINING_EDITABLE_COLUMNS). pathway is NEVER
    updated through this endpoint. The UPDATE always includes a
    pathway clause so PLAB rows cannot be modified by mistake.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM ops_coaching WHERE id = ? AND COALESCE(pathway, 'plab') = 'consulting'",
            (rid,),
        ).fetchone()
        if not existing:
            flash('Consulting training record not found.', 'error')
            return redirect(url_for('ops_consulting_training_list'))

        sets = []
        params = []
        for col in AU_TRAINING_EDITABLE_COLUMNS:
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
                    # Empty strings get stored as NULL so they don't break
                    # downstream COALESCE() / date-parse logic.
                    val = None
                sets.append(f"{col} = ?")
                params.append(val)
        if sets:
            params.append(rid)
            conn.execute(
                f"UPDATE ops_coaching SET {', '.join(sets)} "
                f" WHERE id = ? AND COALESCE(pathway, 'plab') = 'consulting'",
                params,
            )
            conn.commit()
            flash('Training record saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_consulting_training_edit_save: {e}")
        flash(f'Error saving training record: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_consulting_training_detail', rid=rid))


@admin_required
def ops_consulting_training_add_page():
    """GET — render the empty add form (reuses the edit template)."""
    user = get_user()
    empty_record = {col: None for col in AU_TRAINING_EDITABLE_COLUMNS}
    empty_record['id'] = None
    empty_record['registration_number'] = ''
    empty_record['first_name'] = ''
    empty_record['last_name'] = ''
    empty_record['prefix'] = ''
    return render_template(
        'ops_consulting_training_edit.html',
        user=user,
        record=empty_record,
        is_new=True,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-training',
        active_pathway='consulting',
        # Dropdown options sourced from lookup_options where pathway='consulting'.
        **section_training_lookups('consulting'),
    )


@admin_required
def ops_consulting_training_add_save():
    """POST — insert a new Consulting training row, then redirect to detail."""
    conn = get_db()
    try:
        reg = (request.form.get('registration_number') or '').strip()
        if not reg:
            flash('Registration number is required.', 'error')
            return redirect(url_for('ops_consulting_training_add_page'))
        cols = ['registration_number', 'pathway']
        vals = [reg, 'consulting']
        for col in AU_TRAINING_EDITABLE_COLUMNS:
            if col in request.form:
                v = (request.form.get(col) or '').strip() or None
                if col in _NUMERIC_COLUMNS:
                    try:
                        v = float(v) if v else None
                    except ValueError:
                        v = None
                cols.append(col)
                vals.append(v)
        placeholders = ', '.join(['?'] * len(cols))
        cur = conn.execute(
            f"INSERT INTO ops_coaching ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
            vals,
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        flash('Training record added.', 'success')
        return redirect(url_for('ops_consulting_training_detail', rid=new_id))
    except Exception as e:
        logging.error(f"ops_consulting_training_add_save: {e}")
        flash(f'Error: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
        return redirect(url_for('ops_consulting_training_list'))
    finally:
        conn.close()


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/consulting/training',
        endpoint='ops_consulting_training_list',
        view_func=ops_consulting_training_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/training/<int:rid>',
        endpoint='ops_consulting_training_detail',
        view_func=ops_consulting_training_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/training/add',
        endpoint='ops_consulting_training_add_page',
        view_func=ops_consulting_training_add_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/training/add',
        endpoint='ops_consulting_training_add_save',
        view_func=ops_consulting_training_add_save,
        methods=['POST'],
    )
    app.add_url_rule(
        '/operations/consulting/training/<int:rid>/edit',
        endpoint='ops_consulting_training_edit_page',
        view_func=ops_consulting_training_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/training/<int:rid>/edit',
        endpoint='ops_consulting_training_edit_save',
        view_func=ops_consulting_training_edit_save,
        methods=['POST'],
    )
