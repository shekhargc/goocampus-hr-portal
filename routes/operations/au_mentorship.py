"""
routes/operations/au_mentorship.py — Operations: AMC Pathway Mentorship.

Mirror of the Standard Consulting Mentorship handlers (cs_mentorship.py)
scoped to pathway='australia'. The underlying ops_mentorship table is
shared across pathways via the `pathway` column.

Endpoints registered:
    GET  /operations/australia/mentorship
    GET  /operations/australia/mentorship/add        (form)
    POST /operations/australia/mentorship/add        (submit)
    GET  /operations/australia/mentorship/<int:rid>
    GET  /operations/australia/mentorship/<int:rid>/edit
    POST /operations/australia/mentorship/<int:rid>/edit
    POST /operations/australia/mentorship/<int:rid>/delete
"""

import logging
from flask import render_template, flash, request, redirect, url_for, session

from core.auth import admin_required
from core.users import get_user
from db import get_db
from routes.operations._form_lookups import vendor_names_for, get_lookup_options
from routes.operations.au_test_bookings import _existing_columns


# New optional columns surfaced on the Mentorship form. These may not exist
# on the DB yet, so every write is guarded by _existing_columns and skipped
# silently until the column is added (no migrations here).
AU_MENTORSHIP_EXTRA_COLUMNS = ['service', 'fee_currency', 'service_description']


def _mentorship_extra_save(conn, rid):
    """Persist the new optional Mentorship columns for row `rid`, guarded."""
    db_cols = _existing_columns(conn, 'ops_mentorship')
    sets, params = [], []
    for col in AU_MENTORSHIP_EXTRA_COLUMNS:
        if col not in request.form:
            continue
        if db_cols and col not in db_cols:
            continue
        val = (request.form.get(col) or '').strip() or None
        sets.append(f"{col} = ?")
        params.append(val)
    if sets:
        params.append(rid)
        conn.execute(
            "UPDATE ops_mentorship SET " + ', '.join(sets)
            + " WHERE id = ? AND COALESCE(pathway,'plab') = 'australia'",
            params,
        )


def _mentorship_lookups():
    """Dropdown options for the Mentorship vendor-first cascade (AMC Pathway)."""
    return {
        'program_providers':  vendor_names_for('Mentorship', 'australia',
                                               fallback_lookup='program_provider'),
        'mentorship_services': get_lookup_options('mentorship_service', pathway='australia'),
    }


def _get_lookup_options(category):
    """Per-pathway lookup options with fallback to PLAB."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT value FROM lookup_options "
            "WHERE category = ? AND COALESCE(pathway, 'plab') = 'australia' "
            "  AND is_active = TRUE "
            "ORDER BY sort_order, id",
            (category,),
        ).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT value FROM lookup_options "
                "WHERE category = ? AND COALESCE(pathway, 'plab') = 'plab' "
                "  AND is_active = TRUE "
                "ORDER BY sort_order, id",
                (category,),
            ).fetchall()
        return [r['value'] for r in rows]
    except Exception as e:
        logging.warning(f"_get_lookup_options({category}): {e}")
        return []
    finally:
        try: conn.close()
        except Exception: pass


@admin_required
def ops_australia_mentorship_list():
    """AMC Pathway mentorship session list."""
    conn = get_db()
    search = request.args.get('q', '')
    records = []
    try:
        sql = """SELECT m.*, p.first_name, p.last_name, p.prefix
                   FROM ops_mentorship m
              LEFT JOIN plab_clients p ON m.registration_number = p.registration_number
                  WHERE COALESCE(m.pathway, 'plab') = 'australia' """
        params = []
        if search:
            sql += """ AND (p.first_name ILIKE ? OR p.last_name ILIKE ?
                        OR m.program_provider ILIKE ?
                        OR p.registration_number ILIKE ?
                        OR (COALESCE(p.prefix,'')||' '||p.first_name||' '||COALESCE(p.last_name,'')) ILIKE ?) """
            params.extend([f'%{search}%'] * 5)
        sql += " ORDER BY m.id DESC"
        records = conn.execute(sql, params).fetchall()
    except Exception as e:
        logging.error(f"ops_australia_mentorship_list: {e}")
        records = []
    conn.close()
    return render_template(
        'ops_australia_mentorship_list.html',
        records=records, search=search,
        active_ops_page='australia-mentorship',
        active_pathway='australia',
    )


@admin_required
def ops_australia_mentorship_add():
    conn = get_db()
    if request.method == 'POST':
        f = request.form
        try:
            cur = conn.execute(
                """INSERT INTO ops_mentorship (
                     registration_number, session_date, start_time, end_time,
                     duration_minutes, amount_paid, payment_status,
                     candidate_attendance, additional_notes, session_confirmation,
                     program_provider, mentor_attendance, mobile_number,
                     candidate_email, pathway, created_by
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (
                    f.get('registration_number'), f.get('session_date'),
                    f.get('start_time'), f.get('end_time'),
                    f.get('duration_minutes'),
                    f.get('amount_paid') or 0, f.get('payment_status'),
                    f.get('candidate_attendance'), f.get('additional_notes'),
                    f.get('session_confirmation'), f.get('program_provider'),
                    f.get('mentor_attendance'), f.get('mobile_number'),
                    f.get('candidate_email'),
                    'australia', session.get('user_id', 0),
                ),
            )
            new_id = cur.fetchone()['id']
            _mentorship_extra_save(conn, new_id)
            conn.commit()
            flash('Mentorship session added', 'success')
        except Exception as e:
            try: conn.rollback()
            except Exception: pass
            logging.error(f"ops_australia_mentorship_add: {e}")
            flash(f'Add failed: {e}', 'error')
        conn.close()
        return redirect(request.args.get('next') or url_for('ops_australia_mentorship_list'))
    conn.close()
    pre_reg = request.args.get('client', '')
    return render_template(
        'ops_australia_mentorship_form.html', record=None,
        payment_statuses=_get_lookup_options('mentorship_payment_status'),
        attendance_options=_get_lookup_options('mentorship_attendance'),
        confirmation_options=_get_lookup_options('mentorship_confirmation'),
        pre_reg=pre_reg,
        active_ops_page='australia-mentorship',
        active_pathway='australia',
        **_mentorship_lookups(),
    )


@admin_required
def ops_australia_mentorship_edit(rid):
    conn = get_db()
    record = conn.execute(
        """SELECT t.*, p.first_name, p.last_name, p.prefix,
                  p.mobile, p.email
             FROM ops_mentorship t
        LEFT JOIN plab_clients p
               ON t.registration_number = p.registration_number
              AND COALESCE(p.pathway, 'plab') = 'australia'
            WHERE t.id = ?
              AND COALESCE(t.pathway, 'plab') = 'australia' """,
        (rid,),
    ).fetchone()
    if not record:
        conn.close()
        flash('Record not found', 'error')
        return redirect(url_for('ops_australia_mentorship_list'))
    if request.method == 'POST':
        f = request.form
        try:
            conn.execute(
                """UPDATE ops_mentorship SET
                     registration_number=?, session_date=?,
                     start_time=?, end_time=?, duration_minutes=?,
                     amount_paid=?, payment_status=?,
                     candidate_attendance=?, additional_notes=?,
                     session_confirmation=?, program_provider=?,
                     mentor_attendance=?, mobile_number=?,
                     candidate_email=?
                   WHERE id = ?""",
                (
                    f.get('registration_number'), f.get('session_date'),
                    f.get('start_time'), f.get('end_time'),
                    f.get('duration_minutes'),
                    f.get('amount_paid') or 0, f.get('payment_status'),
                    f.get('candidate_attendance'), f.get('additional_notes'),
                    f.get('session_confirmation'), f.get('program_provider'),
                    f.get('mentor_attendance'), f.get('mobile_number'),
                    f.get('candidate_email'), rid,
                ),
            )
            _mentorship_extra_save(conn, rid)
            conn.commit()
            flash('Mentorship session updated', 'success')
        except Exception as e:
            try: conn.rollback()
            except Exception: pass
            logging.error(f"ops_australia_mentorship_edit: {e}")
            flash(f'Update failed: {e}', 'error')
        conn.close()
        return redirect(request.args.get('next') or url_for('ops_australia_mentorship_list'))
    conn.close()
    return render_template(
        'ops_australia_mentorship_form.html', record=record,
        payment_statuses=_get_lookup_options('mentorship_payment_status'),
        attendance_options=_get_lookup_options('mentorship_attendance'),
        confirmation_options=_get_lookup_options('mentorship_confirmation'),
        pre_reg='',
        active_ops_page='australia-mentorship',
        active_pathway='australia',
        **_mentorship_lookups(),
    )


@admin_required
def ops_australia_mentorship_detail(rid):
    """Read-only detail view for one AMC Pathway mentorship session row."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT m.*, p.first_name, p.last_name, p.prefix,
                      p.mobile, p.email
                 FROM ops_mentorship m
            LEFT JOIN plab_clients p
                   ON m.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'australia'
                WHERE m.id = ?
                  AND COALESCE(m.pathway, 'plab') = 'australia' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_australia_mentorship_detail: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Mentorship session not found.', 'error')
        return redirect(url_for('ops_australia_mentorship_list'))

    return render_template(
        'ops_australia_mentorship_detail.html',
        user=user,
        record=record,
        pathway_name='AMC Pathway',
        active_ops_page='australia-mentorship',
        active_pathway='australia',
    )


@admin_required
def ops_australia_mentorship_delete(rid):
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM ops_mentorship "
            " WHERE id = ? AND COALESCE(pathway,'plab') = 'australia'",
            (rid,),
        )
        conn.commit()
        flash('Mentorship session deleted', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ops_australia_mentorship_delete: {e}")
        flash(f'Delete failed: {e}', 'error')
    conn.close()
    return redirect(request.args.get('next') or url_for('ops_australia_mentorship_list'))


def register_routes(app):
    app.add_url_rule(
        '/operations/australia/mentorship',
        endpoint='ops_australia_mentorship_list',
        view_func=ops_australia_mentorship_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/mentorship/add',
        endpoint='ops_australia_mentorship_add',
        view_func=ops_australia_mentorship_add,
        methods=['GET', 'POST'],
    )
    app.add_url_rule(
        '/operations/australia/mentorship/<int:rid>',
        endpoint='ops_australia_mentorship_detail',
        view_func=ops_australia_mentorship_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/mentorship/<int:rid>/edit',
        endpoint='ops_australia_mentorship_edit',
        view_func=ops_australia_mentorship_edit,
        methods=['GET', 'POST'],
    )
    app.add_url_rule(
        '/operations/australia/mentorship/<int:rid>/delete',
        endpoint='ops_australia_mentorship_delete',
        view_func=ops_australia_mentorship_delete,
        methods=['POST'],
    )
