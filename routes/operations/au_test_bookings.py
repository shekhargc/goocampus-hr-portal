"""
routes/operations/au_test_bookings.py — Operations: Australia Test Bookings.

Standardizes the Australia Test Bookings section to match the Australia
Registration list pattern:
  - List view with recent-first ordering + right-side drawer on row click
  - Full-page read-only detail (PLAB-style)
  - Full-page edit form (PLAB-style)

All routes are pathway-scoped: ``COALESCE(pathway, 'plab') = 'australia'``,
so PLAB rows can never leak into the Australia UI.

Endpoint names (stable so existing url_for() call sites keep working):
  ops_australia_test_bookings_list         GET /operations/australia/test-bookings
  ops_australia_test_bookings_detail       GET /operations/australia/test-bookings/<rid>
  ops_australia_test_bookings_edit_page    GET /operations/australia/test-bookings/<rid>/edit
  ops_australia_test_bookings_edit_save   POST /operations/australia/test-bookings/<rid>/edit
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
# Pathway-scoped dropdown options for the AMC Test Bookings edit form.
from routes.operations._form_lookups import section_test_bookings_lookups


# ── Editable columns on ops_test_bookings (Australia scope) ─────────────────
# Per task spec — one input per field in the edit form. The SAVE handler
# filters this list against the actual DB schema before issuing UPDATE so
# columns that don't exist (e.g. login_id/password on the live PLAB schema)
# are silently dropped instead of raising.
AU_TB_EDITABLE_COLUMNS = [
    'exam', 'booking_date', 'exam_date', 'exam_method', 'exam_type',
    'country', 'login_id', 'password', 'city_state',
    'exam_status', 'exam_result', 'exam_result_date', 'score',
    'revaluation_applied', 'reval_applied_date', 'reval_result', 'reval_score',
]

# Numeric coercion targets (per task spec). Strings get coerced to float
# before being passed to UPDATE; bad input → 0.
AU_TB_NUMERIC_COLUMNS = {'score', 'reval_score', 'amount', 'points', 'duration'}


def _existing_columns(conn, table):
    """Return the set of columns that actually exist on the given table.

    Works on both SQLite (PRAGMA) and PostgreSQL (information_schema), since
    the same code runs against either backend in this project.
    """
    cols = set()
    # Try PostgreSQL first
    try:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            (table,),
        ).fetchall()
        cols = {r[0] if not isinstance(r, dict) else r['column_name'] for r in rows}
        if cols:
            return cols
    except Exception:
        pass
    # Fall back to SQLite PRAGMA
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        cols = {r['name'] for r in rows}
    except Exception:
        pass
    return cols


# ────────────────────────────────────────────────────────────────────────────
# LIST
# ────────────────────────────────────────────────────────────────────────────
@admin_required
def ops_australia_test_bookings_list():
    """Australia test bookings list — ops_test_bookings WHERE pathway='australia'.

    Ordering: most recent exam_date first (NULLs last), then id DESC so the
    newest rows surface at the top, matching the Registration list pattern.
    """
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    exam_filter = (request.args.get('exam', '') or '').strip()
    status_filter = (request.args.get('status', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()
    view_filter = (request.args.get('view', '') or '').strip()  # '' | 'upcoming' | 'awaiting'

    records = []
    exams = []
    statuses = []
    total = 0

    try:
        sql = '''SELECT t.id, t.registration_number, t.exam, t.exam_type,
                        t.booking_date, t.exam_date, t.exam_status,
                        t.exam_result, t.exam_result_date, t.score,
                        t.city_state, t.country, t.booked_by,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_test_bookings t
                   LEFT JOIN plab_clients p
                          ON t.registration_number = p.registration_number
                         AND COALESCE(p.pathway, 'plab') = 'australia'
                  WHERE COALESCE(t.pathway, 'plab') = 'australia' '''
        params = []
        if reg:
            sql += " AND t.registration_number = ? "
            params.append(reg)
        if exam_filter:
            sql += " AND t.exam = ? "
            params.append(exam_filter)
        if status_filter:
            sql += " AND t.exam_status = ? "
            params.append(status_filter)
        if view_filter in ('upcoming', 'awaiting'):
            from datetime import date as _date
            _today = _date.today().isoformat()
            if view_filter == 'upcoming':
                # Booked exams whose date is still ahead.
                sql += " AND t.exam_status = 'Booked' AND t.exam_date >= ? "
                params.append(_today)
            else:
                # Awaiting results: no result yet, and either Attended OR a Booked
                # exam whose date has passed (derived — status is not mutated).
                sql += (" AND (t.exam_result IS NULL OR t.exam_result = '') "
                        " AND (t.exam_status = 'Attended' "
                        "      OR (t.exam_status = 'Booked' AND t.exam_date < ?)) ")
                params.append(_today)
        if search:
            sql += """ AND (
                p.first_name ILIKE ? OR p.last_name ILIKE ? OR
                t.test_center ILIKE ? OR t.registration_number ILIKE ? OR
                (COALESCE(p.prefix,'')||' '||p.first_name||' '||COALESCE(p.last_name,'')) ILIKE ?
            ) """
            params.extend([f'%{search}%'] * 5)
        # Recent-first: most-recent exam_date first (NULLs last), then id DESC.
        sql += " ORDER BY t.exam_date DESC NULLS LAST, t.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        exams = [
            r['exam'] for r in conn.execute(
                """SELECT DISTINCT exam FROM ops_test_bookings
                    WHERE COALESCE(pathway, 'plab') = 'australia'
                      AND exam IS NOT NULL AND exam != ''
                    ORDER BY exam"""
            ).fetchall()
        ]
        statuses = [
            r['exam_status'] for r in conn.execute(
                """SELECT DISTINCT exam_status FROM ops_test_bookings
                    WHERE COALESCE(pathway, 'plab') = 'australia'
                      AND exam_status IS NOT NULL AND exam_status != ''
                    ORDER BY exam_status"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_australia_test_bookings_list: {e}")
        flash(f'Error loading Australia test bookings: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_test_bookings_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        exam_filter=exam_filter,
        status_filter=status_filter,
        view_filter=view_filter,
        client_reg=reg,
        exams=exams,
        statuses=statuses,
        pathway_name='AMC Pathway',
        active_ops_page='australia-test-bookings',
        active_pathway='australia',
    )


# ────────────────────────────────────────────────────────────────────────────
# DETAIL (read-only)
# ────────────────────────────────────────────────────────────────────────────
@admin_required
def ops_australia_test_bookings_detail(rid):
    """Full Australia test booking profile — read-only PLAB-style layout."""
    user = get_user()
    conn = get_db()
    record = conn.execute(
        """SELECT t.*, p.prefix, p.first_name, p.last_name
             FROM ops_test_bookings t
        LEFT JOIN plab_clients p
               ON t.registration_number = p.registration_number
              AND COALESCE(p.pathway, 'plab') = 'australia'
            WHERE t.id = ?
              AND COALESCE(t.pathway, 'plab') = 'australia' """,
        (rid,),
    ).fetchone()
    conn.close()
    if not record:
        flash('Australia test booking not found.', 'error')
        return redirect(url_for('ops_australia_test_bookings_list'))
    return render_template(
        'ops_australia_test_bookings_detail.html',
        user=user,
        record=record,
        pathway_name='AMC Pathway',
        active_ops_page='australia-test-bookings',
        active_pathway='australia',
    )


# ────────────────────────────────────────────────────────────────────────────
# EDIT (GET)
# ────────────────────────────────────────────────────────────────────────────
@admin_required
def ops_australia_test_bookings_edit_page(rid):
    """GET — render the edit form for one Australia test booking."""
    user = get_user()
    conn = get_db()
    record = conn.execute(
        """SELECT t.*, p.prefix, p.first_name, p.last_name
             FROM ops_test_bookings t
        LEFT JOIN plab_clients p
               ON t.registration_number = p.registration_number
              AND COALESCE(p.pathway, 'plab') = 'australia'
            WHERE t.id = ?
              AND COALESCE(t.pathway, 'plab') = 'australia' """,
        (rid,),
    ).fetchone()
    conn.close()
    if not record:
        flash('Australia test booking not found.', 'error')
        return redirect(url_for('ops_australia_test_bookings_list'))
    return render_template(
        'ops_australia_test_bookings_edit.html',
        user=user,
        record=record,
        pathway_name='AMC Pathway',
        active_ops_page='australia-test-bookings',
        active_pathway='australia',
        # Dropdown options sourced from lookup_options where pathway='australia'.
        **section_test_bookings_lookups('australia'),
    )


# ────────────────────────────────────────────────────────────────────────────
# EDIT (POST — save)
# ────────────────────────────────────────────────────────────────────────────
@admin_required
def ops_australia_test_bookings_edit_save(rid):
    """POST handler: save edits to a single Australia test booking.

    Strict allowlist (AU_TB_EDITABLE_COLUMNS); columns the live schema
    doesn't expose are silently dropped instead of crashing the UPDATE.
    Pathway is NEVER updated through this endpoint.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            """SELECT id FROM ops_test_bookings
                WHERE id = ?
                  AND COALESCE(pathway, 'plab') = 'australia' """,
            (rid,),
        ).fetchone()
        if not existing:
            flash('Australia test booking not found.', 'error')
            return redirect(url_for('ops_australia_test_bookings_list'))

        # Filter the spec's allowlist down to columns the live table actually has,
        # so the UPDATE never references a non-existent column.
        live_cols = _existing_columns(conn, 'ops_test_bookings')
        effective = [c for c in AU_TB_EDITABLE_COLUMNS if (not live_cols) or c in live_cols]

        sets = []
        params = []
        for col in effective:
            if col in request.form:
                val = request.form.get(col, '').strip()
                # Numeric coercion (per task spec)
                if col in AU_TB_NUMERIC_COLUMNS:
                    try:
                        val = float(val) if val else 0
                    except ValueError:
                        val = 0
                # Empty date strings → NULL to avoid invalid-date errors on PG
                elif col.endswith('_date') and val == '':
                    val = None
                sets.append(f"{col} = ?")
                params.append(val)

        if sets:
            params.append(rid)
            conn.execute(
                f"""UPDATE ops_test_bookings
                       SET {', '.join(sets)}
                     WHERE id = ?
                       AND COALESCE(pathway, 'plab') = 'australia' """,
                params,
            )
            conn.commit()
            flash('Test booking saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_australia_test_bookings_edit_save: {e}")
        flash(f'Error saving test booking: {e}', 'error')
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

    return redirect(url_for('ops_australia_test_bookings_detail', rid=rid))


# ────────────────────────────────────────────────────────────────────────────
# ADD (GET — form)
# ────────────────────────────────────────────────────────────────────────────
@admin_required
def ops_australia_test_bookings_add_page():
    """GET — render the empty add form (reuses the edit template)."""
    user = get_user()
    empty_record = {col: None for col in AU_TB_EDITABLE_COLUMNS}
    empty_record['id'] = None
    empty_record['registration_number'] = ''
    empty_record['first_name'] = ''
    empty_record['last_name'] = ''
    empty_record['prefix'] = ''
    return render_template(
        'ops_australia_test_bookings_edit.html',
        user=user,
        record=empty_record,
        is_new=True,
        pathway_name='AMC Pathway',
        active_ops_page='australia-test-bookings',
        active_pathway='australia',
        # Dropdown options sourced from lookup_options where pathway='australia'.
        **section_test_bookings_lookups('australia'),
    )


# ────────────────────────────────────────────────────────────────────────────
# ADD (POST — insert)
# ────────────────────────────────────────────────────────────────────────────
@admin_required
def ops_australia_test_bookings_add_save():
    """POST — insert a new Australia test booking row."""
    conn = get_db()
    try:
        reg = (request.form.get('registration_number') or '').strip()
        if not reg:
            flash('Registration number is required.', 'error')
            return redirect(url_for('ops_australia_test_bookings_add_page'))
        live_cols = _existing_columns(conn, 'ops_test_bookings')
        effective = [c for c in AU_TB_EDITABLE_COLUMNS if (not live_cols) or c in live_cols]
        cols = ['registration_number', 'pathway']
        vals = [reg, 'australia']
        for col in effective:
            if col in request.form:
                v = (request.form.get(col) or '').strip()
                if col in AU_TB_NUMERIC_COLUMNS:
                    try:
                        v = float(v) if v else None
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
            f"INSERT INTO ops_test_bookings ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
            vals,
        )
        new_id = cur.fetchone()['id']
        conn.commit()
        flash('Test booking added.', 'success')
        return redirect(url_for('ops_australia_test_bookings_detail', rid=new_id))
    except Exception as e:
        logging.error(f"ops_australia_test_bookings_add_save: {e}")
        flash(f'Error: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
        return redirect(url_for('ops_australia_test_bookings_list'))
    finally:
        conn.close()


# ────────────────────────────────────────────────────────────────────────────
# REGISTRATION
# ────────────────────────────────────────────────────────────────────────────
def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app.

    NOTE: The list endpoint name (`ops_australia_test_bookings_list`) is
    also registered by routes/operations/australia.py against the same URL.
    When this module is wired up via routes/operations/__init__.py, replace
    the entry there so this is the single source of truth — Flask will
    reject duplicate endpoint registrations otherwise.
    """
    app.add_url_rule(
        '/operations/australia/test-bookings',
        endpoint='ops_australia_test_bookings_list',
        view_func=ops_australia_test_bookings_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/test-bookings/<int:rid>',
        endpoint='ops_australia_test_bookings_detail',
        view_func=ops_australia_test_bookings_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/test-bookings/add',
        endpoint='ops_australia_test_bookings_add_page',
        view_func=ops_australia_test_bookings_add_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/test-bookings/add',
        endpoint='ops_australia_test_bookings_add_save',
        view_func=ops_australia_test_bookings_add_save,
        methods=['POST'],
    )
    app.add_url_rule(
        '/operations/australia/test-bookings/<int:rid>/edit',
        endpoint='ops_australia_test_bookings_edit_page',
        view_func=ops_australia_test_bookings_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/test-bookings/<int:rid>/edit',
        endpoint='ops_australia_test_bookings_edit_save',
        view_func=ops_australia_test_bookings_edit_save,
        methods=['POST'],
    )
