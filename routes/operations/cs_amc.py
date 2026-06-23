"""
routes/operations/cs_amc.py — Operations: Standard Consulting AMC Registration.

S-2b. New section -- AMC Registration mirrors the GMC schema but lives in
its own table ops_amc_registration. The CREATE TABLE for it lives in app.py
next to ops_amc_registration. scoped to pathway='consulting'. The underlying table
ops_amc_registration has had a pathway column since the Phase-1 foundation
migration, so consulting rows live alongside PLAB rows in the same table.

Endpoints registered:
    GET  /operations/consulting/amc
    GET  /operations/consulting/amc/add        (form)
    POST /operations/consulting/amc/add        (submit)
    GET  /operations/consulting/amc/<int:gid>/edit
    POST /operations/consulting/amc/<int:gid>/edit
    POST /operations/consulting/amc/<int:gid>/delete
"""

import logging
from datetime import datetime
from flask import (
    render_template, flash, request, redirect, url_for, session
)

from core.auth import admin_required
from core.users import get_user
from db import get_db


def _get_lookup_options(category):
    """Local copy of the global get_lookup_options helper since
    importing from app.py would cause a circular import at module
    load. Falls back to the PLAB-pathway lookups when no consulting
    options exist -- avoids forcing the user to re-seed dropdowns
    just to use the section."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT value FROM lookup_options "
            "WHERE category = ? AND COALESCE(pathway, 'plab') = 'consulting' "
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
def ops_consulting_amc_list():
    """Standard Consulting AMC list. Mirror of ops_consulting_gmc_list (new schema) filtered to
    pathway='consulting'."""
    conn = get_db()
    search = request.args.get('q', '')
    status_filter = request.args.get('status', '')
    records = []
    try:
        sql = """SELECT g.*, p.first_name, p.last_name, p.prefix
                   FROM ops_amc_registration g
              LEFT JOIN plab_clients p ON g.registration_number = p.registration_number
                  WHERE COALESCE(g.pathway, 'plab') = 'consulting' """
        params = []
        if status_filter:
            sql += " AND g.amc_setup = ? "
            params.append(status_filter)
        if search:
            sql += """ AND (p.first_name ILIKE ? OR p.last_name ILIKE ?
                        OR g.registration_number ILIKE ?
                        OR (COALESCE(p.prefix,'')||' '||p.first_name||' '||COALESCE(p.last_name,'')) ILIKE ?) """
            params.extend([f'%{search}%'] * 4)
        sql += " ORDER BY g.id DESC"
        records = conn.execute(sql, params).fetchall()
    except Exception as e:
        logging.error(f"ops_consulting_amc_list: {e}")
        records = []
    conn.close()
    return render_template(
        'ops_consulting_amc_list.html',
        records=records,
        search=search, status_filter=status_filter,
        amc_setup_statuses=_get_lookup_options('amc_setup_status'),
        active_ops_page='consulting-amc',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_amc_add():
    """Add a consulting AMC registration record."""
    conn = get_db()
    if request.method == 'POST':
        f = request.form
        try:
            conn.execute(
                """INSERT INTO ops_amc_registration (
                     registration_number, amc_reference_number, login_id, login_pwd,
                     amc_setup, registration_date,
                     pathway, created_by, updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    f.get('registration_number'), f.get('amc_reference_number'),
                    f.get('login_id'), f.get('login_pwd'), f.get('amc_setup'),
                    f.get('registration_date'),
                    'consulting', session.get('user_id', 0), datetime.now(),
                ),
            )
            conn.commit()
            flash('AMC registration record added', 'success')
        except Exception as e:
            try: conn.rollback()
            except Exception: pass
            logging.error(f"ops_consulting_amc_add: {e}")
            flash(f'Add failed: {e}', 'error')
        conn.close()
        return redirect(request.args.get('next') or url_for('ops_consulting_amc_list'))
    clients = conn.execute(
        "SELECT registration_number, prefix, first_name, last_name "
        "  FROM plab_clients "
        " WHERE COALESCE(pathway, 'plab') = 'consulting' "
        " ORDER BY first_name"
    ).fetchall()
    conn.close()
    pre_reg = request.args.get('reg', '')
    return render_template(
        'ops_consulting_amc_form.html', record=None, clients=clients,
        amc_setup_statuses=_get_lookup_options('amc_setup_status'),
        pre_reg=pre_reg, active_ops_page='consulting-amc',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_amc_edit(gid):
    """Edit a consulting AMC registration record. Restricted to
    rows where pathway='consulting' so PLAB / AMC data can't be
    mutated through this surface."""
    conn = get_db()
    record = conn.execute(
        """SELECT t.*, p.first_name, p.last_name, p.prefix,
                  p.mobile, p.email
             FROM ops_amc_registration t
        LEFT JOIN plab_clients p
               ON t.registration_number = p.registration_number
              AND COALESCE(p.pathway, 'plab') = 'consulting'
            WHERE t.id = ?
              AND COALESCE(t.pathway, 'plab') = 'consulting' """,
        (gid,),
    ).fetchone()
    if not record:
        conn.close()
        flash('Record not found', 'error')
        return redirect(url_for('ops_consulting_amc_list'))
    if request.method == 'POST':
        f = request.form
        try:
            conn.execute(
                """UPDATE ops_amc_registration SET
                     registration_number=?, amc_reference_number=?, login_id=?,
                     login_pwd=?, amc_setup=?, registration_date=?, updated_at=?
                   WHERE id = ?""",
                (
                    f.get('registration_number'), f.get('amc_reference_number'),
                    f.get('login_id'), f.get('login_pwd'), f.get('amc_setup'),
                    f.get('registration_date'), datetime.now(), gid,
                ),
            )
            conn.commit()
            flash('AMC registration record updated', 'success')
        except Exception as e:
            try: conn.rollback()
            except Exception: pass
            logging.error(f"ops_consulting_amc_edit: {e}")
            flash(f'Update failed: {e}', 'error')
        conn.close()
        return redirect(request.args.get('next') or url_for('ops_consulting_amc_list'))
    clients = conn.execute(
        "SELECT registration_number, prefix, first_name, last_name "
        "  FROM plab_clients "
        " WHERE COALESCE(pathway, 'plab') = 'consulting' "
        " ORDER BY first_name"
    ).fetchall()
    conn.close()
    return render_template(
        'ops_consulting_amc_form.html', record=record, clients=clients,
        amc_setup_statuses=_get_lookup_options('amc_setup_status'),
        pre_reg='', active_ops_page='consulting-amc',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_amc_detail(gid):
    """Read-only detail view for one Consulting AMC registration row.

    LEFT JOIN plab_clients via registration_number so we can render the
    candidate's name + contact in the header. Mirrors the PLAB-style
    detail layout (header card + two-column grid + Edit Record action).
    Pathway-scoped to consulting so PLAB / Australia rows are not
    accessible through this surface.
    """
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT g.*, p.first_name, p.last_name, p.prefix,
                      p.mobile, p.email
                 FROM ops_amc_registration g
            LEFT JOIN plab_clients p
                   ON g.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'consulting'
                WHERE g.id = ?
                  AND COALESCE(g.pathway, 'plab') = 'consulting' """,
            (gid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_consulting_amc_detail: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('AMC registration record not found.', 'error')
        return redirect(url_for('ops_consulting_amc_list'))

    return render_template(
        'ops_consulting_amc_detail.html',
        user=user,
        record=record,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-amc',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_amc_delete(gid):
    """Delete a consulting AMC registration record. Pathway gated."""
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM ops_amc_registration "
            " WHERE id = ? AND COALESCE(pathway,'plab') = 'consulting'",
            (gid,),
        )
        conn.commit()
        flash('AMC registration record deleted', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ops_consulting_amc_delete: {e}")
        flash(f'Delete failed: {e}', 'error')
    conn.close()
    return redirect(url_for('ops_consulting_amc_list'))


def register_routes(app):
    """Register Standard Consulting AMC routes."""
    app.add_url_rule(
        '/operations/consulting/amc',
        endpoint='ops_consulting_amc_list',
        view_func=ops_consulting_amc_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/amc/add',
        endpoint='ops_consulting_amc_add',
        view_func=ops_consulting_amc_add,
        methods=['GET', 'POST'],
    )
    app.add_url_rule(
        '/operations/consulting/amc/<int:gid>',
        endpoint='ops_consulting_amc_detail',
        view_func=ops_consulting_amc_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/amc/<int:gid>/edit',
        endpoint='ops_consulting_amc_edit',
        view_func=ops_consulting_amc_edit,
        methods=['GET', 'POST'],
    )
    app.add_url_rule(
        '/operations/consulting/amc/<int:gid>/delete',
        endpoint='ops_consulting_amc_delete',
        view_func=ops_consulting_amc_delete,
        methods=['POST'],
    )
