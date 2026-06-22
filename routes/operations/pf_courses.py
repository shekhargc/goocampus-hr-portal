"""
routes/operations/pf_courses.py — Operations: Portfolio Pathway
Online Courses list + detail + edit.

Surfaces rows from ops_online_courses WHERE pathway='portfolio', joined
to plab_clients on registration_number so we can show the candidate name.
Data is entered manually (no import). This is a DISTINCT section from
Online Subscriptions (which uses the ops_online_subscriptions table).

Modeled on the PLAB Online Courses handlers (ops_courses_* in app.py),
standardised to the AMC / Portfolio pattern: list (with drawer) + detail
page + edit form + add form. Fields mirror the PLAB course form:
  courses_name, course_type, start_date, end_date, validity_months,
  course_provider, certification_body, subject_name, course_status,
  booked_by, notes (plus contact fields client_email / mobile_number /
  candidate_email).

Endpoints registered:
  - GET  /operations/portfolio/courses
  - GET  /operations/portfolio/courses/<rid>
  - GET  /operations/portfolio/courses/add        (form)
  - POST /operations/portfolio/courses/add        (submit)
  - GET  /operations/portfolio/courses/<rid>/edit
  - POST /operations/portfolio/courses/<rid>/edit
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
from app import get_lookup_options
# Centralised vendor list for the Online Subscriptions category (vendor-first
# cascade) + cross-DB column-existence guard.
from routes.operations._form_lookups import section_online_courses_lookups
from routes.operations.au_test_bookings import _existing_columns


# ── Editable columns on ops_online_courses (pathway='portfolio') ───────
# id / registration_number / pathway are NOT editable through the UI.
# This section uses ops_online_courses (course_provider / courses_name) — the
# vendor-first cascade runs on those existing columns; there is no
# subscription_provider/online_subscription column here.
CS_OC_EDITABLE_COLUMNS = [
    'courses_name', 'course_type', 'start_date', 'end_date',
    'validity_months', 'course_provider', 'certification_body',
    'subject_name', 'course_status', 'booked_by', 'notes',
    'client_email', 'mobile_number', 'candidate_email',
]

# Numeric columns get coerced to float; bad data -> None.
CS_OC_NUMERIC_COLUMNS = {
    'validity_months', 'amount', 'score', 'points', 'duration',
}


def _course_lookups():
    """Dropdown options for the Online Courses edit/add form.

    Mirrors the PLAB course form dropdowns (ops_courses_form.html) but
    scoped to pathway='portfolio' so the Portfolio Field Manager owns
    the option lists. Falls back to PLAB seed when not yet configured.
    """
    lk = {
        'course_names':         get_lookup_options('course_name',        pathway='portfolio'),
        'course_types':         get_lookup_options('course_type',        pathway='portfolio'),
        'course_statuses':      get_lookup_options('course_status',      pathway='portfolio'),
        'booked_by_options':    get_lookup_options('course_booked_by',   pathway='portfolio'),
        'course_providers':     get_lookup_options('course_provider',    pathway='portfolio'),
        'certification_bodies': get_lookup_options('certification_body', pathway='portfolio'),
    }
    # Centralised vendor list + deliverable list for the vendor-first cascade
    # (Online Subscriptions category). subscription_vendors drives the
    # Provider <select>; subscription_types is the full deliverable list the
    # cascade narrows from.
    sub = section_online_courses_lookups('portfolio')
    lk['subscription_vendors'] = sub.get('subscription_vendors', [])
    lk['subscription_types'] = sub.get('subscription_types', [])
    return lk


@admin_required
def ops_portfolio_courses_list():
    """Portfolio online courses list — ops_online_courses WHERE pathway='portfolio'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    course_filter = (request.args.get('course', '') or '').strip()
    status_filter = (request.args.get('status', '') or '').strip()
    provider_filter = (request.args.get('provider', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    courses = []
    statuses = []
    providers = []
    total = 0

    try:
        sql = '''SELECT c.id, c.registration_number, c.courses_name,
                        c.course_type, c.start_date, c.end_date,
                        c.validity_months, c.course_provider,
                        c.certification_body, c.subject_name,
                        c.course_status, c.booked_by, c.notes,
                        c.client_email, c.mobile_number, c.candidate_email,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_online_courses c
                   LEFT JOIN plab_clients p
                          ON c.registration_number = p.registration_number
                  WHERE c.pathway = 'portfolio' '''
        params = []
        if reg:
            sql += " AND c.registration_number = ? "
            params.append(reg)
        if course_filter:
            sql += " AND c.courses_name = ? "
            params.append(course_filter)
        if status_filter:
            sql += " AND c.course_status = ? "
            params.append(status_filter)
        if provider_filter:
            sql += " AND c.course_provider = ? "
            params.append(provider_filter)
        if search:
            sql += """ AND (
                p.first_name ILIKE ? OR p.last_name ILIKE ? OR
                c.courses_name ILIKE ? OR c.registration_number ILIKE ? OR
                c.course_provider ILIKE ? OR
                (COALESCE(p.prefix,'')||' '||p.first_name||' '||COALESCE(p.last_name,'')) ILIKE ?
            ) """
            params.extend([f'%{search}%'] * 6)
        # Recent-first: most recently started at the top, then by id desc.
        sql += " ORDER BY c.start_date DESC NULLS LAST, c.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        courses = [
            r['courses_name'] for r in conn.execute(
                """SELECT DISTINCT courses_name FROM ops_online_courses
                    WHERE pathway = 'portfolio' AND courses_name IS NOT NULL
                      AND courses_name != ''
                    ORDER BY courses_name"""
            ).fetchall()
        ]
        statuses = [
            r['course_status'] for r in conn.execute(
                """SELECT DISTINCT course_status FROM ops_online_courses
                    WHERE pathway = 'portfolio' AND course_status IS NOT NULL
                      AND course_status != ''
                    ORDER BY course_status"""
            ).fetchall()
        ]
        providers = [
            r['course_provider'] for r in conn.execute(
                """SELECT DISTINCT course_provider FROM ops_online_courses
                    WHERE pathway = 'portfolio' AND course_provider IS NOT NULL
                      AND course_provider != ''
                    ORDER BY course_provider"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_portfolio_courses_list: {e}")
        flash(f'Error loading Portfolio online courses: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_portfolio_courses_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        course_filter=course_filter,
        status_filter=status_filter,
        provider_filter=provider_filter,
        client_reg=reg,
        courses=courses,
        statuses=statuses,
        providers=providers,
        pathway_name='Portfolio Pathway',
        active_ops_page='portfolio-courses',
        active_pathway='portfolio',
    )


@admin_required
def ops_portfolio_courses_detail(rid):
    """Read-only detail page for one Portfolio online course row."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT c.*, p.first_name, p.last_name, p.prefix,
                      p.mobile, p.email
                 FROM ops_online_courses c
            LEFT JOIN plab_clients p
                   ON c.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'portfolio'
                WHERE c.id = ?
                  AND COALESCE(c.pathway, 'plab') = 'portfolio' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_portfolio_courses_detail: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Online course record not found.', 'error')
        return redirect(url_for('ops_portfolio_courses_list'))

    return render_template(
        'ops_portfolio_courses_detail.html',
        user=user,
        record=record,
        pathway_name='Portfolio Pathway',
        active_ops_page='portfolio-courses',
        active_pathway='portfolio',
    )


@admin_required
def ops_portfolio_courses_edit_page(rid):
    """GET — render the edit form for one Portfolio online course row."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT c.*, p.first_name, p.last_name, p.prefix
                 FROM ops_online_courses c
            LEFT JOIN plab_clients p
                   ON c.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'portfolio'
                WHERE c.id = ?
                  AND COALESCE(c.pathway, 'plab') = 'portfolio' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_portfolio_courses_edit_page: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Online course record not found.', 'error')
        return redirect(url_for('ops_portfolio_courses_list'))

    return render_template(
        'ops_portfolio_courses_edit.html',
        user=user,
        record=record,
        pathway_name='Portfolio Pathway',
        active_ops_page='portfolio-courses',
        active_pathway='portfolio',
        **_course_lookups(),
    )


@admin_required
def ops_portfolio_courses_edit_save(rid):
    """POST — save changes to a Portfolio online course row.

    Strict allowlist (CS_OC_EDITABLE_COLUMNS). pathway is NEVER updated.
    The UPDATE always includes a pathway clause so rows from other
    pathways cannot be modified by mistake.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM ops_online_courses "
            "WHERE id = ? AND COALESCE(pathway, 'plab') = 'portfolio'",
            (rid,),
        ).fetchone()
        if not existing:
            flash('Online course record not found.', 'error')
            return redirect(url_for('ops_portfolio_courses_list'))

        # Skip any editable column not present on this DB (e.g.
        # subscription_provider / online_subscription on this schema) so the
        # UPDATE never references a missing column.
        db_cols = _existing_columns(conn, 'ops_online_courses')

        sets = []
        params = []
        for col in CS_OC_EDITABLE_COLUMNS:
            if col in request.form:
                if db_cols and col not in db_cols:
                    continue
                val = request.form.get(col, '').strip()
                if col in CS_OC_NUMERIC_COLUMNS:
                    if not val:
                        val = None
                    else:
                        try:
                            val = float(val)
                        except ValueError:
                            val = None
                elif val == '':
                    val = None
                sets.append(f"{col} = ?")
                params.append(val)
        if sets:
            params.append(rid)
            conn.execute(
                f"UPDATE ops_online_courses SET {', '.join(sets)} "
                f" WHERE id = ? AND COALESCE(pathway, 'plab') = 'portfolio'",
                params,
            )
            conn.commit()
            flash('Online course record saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_portfolio_courses_edit_save: {e}")
        flash(f'Error saving online course record: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_portfolio_courses_detail', rid=rid))


@admin_required
def ops_portfolio_courses_add_page():
    """GET — render the empty add form (reuses the edit template)."""
    user = get_user()
    empty_record = {col: None for col in CS_OC_EDITABLE_COLUMNS}
    empty_record['id'] = None
    empty_record['registration_number'] = ''
    empty_record['first_name'] = ''
    empty_record['last_name'] = ''
    empty_record['prefix'] = ''
    return render_template(
        'ops_portfolio_courses_edit.html',
        user=user,
        record=empty_record,
        is_new=True,
        pathway_name='Portfolio Pathway',
        active_ops_page='portfolio-courses',
        active_pathway='portfolio',
        **_course_lookups(),
    )


@admin_required
def ops_portfolio_courses_add_save():
    """POST — insert a new Portfolio online course row, then redirect to detail."""
    conn = get_db()
    try:
        reg = (request.form.get('registration_number') or '').strip()
        if not reg:
            flash('Registration number is required.', 'error')
            return redirect(url_for('ops_portfolio_courses_add_page'))
        db_cols = _existing_columns(conn, 'ops_online_courses')
        cols = ['registration_number', 'pathway']
        vals = [reg, 'portfolio']
        for col in CS_OC_EDITABLE_COLUMNS:
            if col in request.form:
                if db_cols and col not in db_cols:
                    continue
                v = (request.form.get(col) or '').strip() or None
                if col in CS_OC_NUMERIC_COLUMNS:
                    try:
                        v = float(v) if v else None
                    except ValueError:
                        v = None
                cols.append(col)
                vals.append(v)
        placeholders = ', '.join(['?'] * len(cols))
        cur = conn.execute(
            f"INSERT INTO ops_online_courses ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
            vals,
        )
        new_id = cur.fetchone()['id']
        conn.commit()
        flash('Online course record added.', 'success')
        return redirect(url_for('ops_portfolio_courses_detail', rid=new_id))
    except Exception as e:
        logging.error(f"ops_portfolio_courses_add_save: {e}")
        flash(f'Error: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
        return redirect(url_for('ops_portfolio_courses_list'))
    finally:
        conn.close()


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/portfolio/courses',
        endpoint='ops_portfolio_courses_list',
        view_func=ops_portfolio_courses_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/portfolio/courses/<int:rid>',
        endpoint='ops_portfolio_courses_detail',
        view_func=ops_portfolio_courses_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/portfolio/courses/add',
        endpoint='ops_portfolio_courses_add_page',
        view_func=ops_portfolio_courses_add_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/portfolio/courses/add',
        endpoint='ops_portfolio_courses_add_save',
        view_func=ops_portfolio_courses_add_save,
        methods=['POST'],
    )
    app.add_url_rule(
        '/operations/portfolio/courses/<int:rid>/edit',
        endpoint='ops_portfolio_courses_edit_page',
        view_func=ops_portfolio_courses_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/portfolio/courses/<int:rid>/edit',
        endpoint='ops_portfolio_courses_edit_save',
        view_func=ops_portfolio_courses_edit_save,
        methods=['POST'],
    )
