"""
routes/operations/ngo.py — Operations: NGO Activities sub-area.

4 routes under /operations/ngo-activities/* — list, add, edit, delete.

Endpoint names preserved (ops_ngo_list, ops_ngo_add, ops_ngo_edit,
ops_ngo_delete) by using app.add_url_rule directly instead of
flask.Blueprint, so existing url_for(...) calls keep working unchanged.

Moved verbatim from app.py (lines 18654-18732 before extraction).
"""

import logging
from flask import request, render_template, redirect, url_for, session, flash

from core.auth import admin_required
from db import get_db


@admin_required
def ops_ngo_list():
    conn = get_db()
    search = request.args.get('q', '')
    try:
        sql = '''SELECT n.*, p.first_name, p.last_name, p.prefix
                 FROM ops_ngo_activities n
                 LEFT JOIN plab_clients p ON n.registration_number = p.registration_number
                 WHERE 1=1'''
        params = []
        if search:
            sql += """ AND (p.first_name ILIKE ? OR p.last_name ILIKE ? OR n.ngo_vendor_name ILIKE ?
                OR p.registration_number ILIKE ?
                OR (COALESCE(p.prefix,'')||' '||p.first_name||' '||COALESCE(p.last_name,'')) ILIKE ?)"""
            params.extend([f'%{search}%'] * 5)
        sql += ' ORDER BY n.created_at DESC'
        records = conn.execute(sql, params).fetchall()
    except Exception as e:
        logging.error(f"ops_ngo_list: {e}")
        records = []
    conn.close()
    return render_template('ops_ngo_list.html', records=records, search=search,
                           active_ops_page='ngo')


@admin_required
def ops_ngo_add():
    # Lazy import: get_lookup_options is still defined in app.py.
    # Calling it lazily avoids a circular import at module-load time.
    from app import get_lookup_options

    conn = get_db()
    if request.method == 'POST':
        f = request.form
        conn.execute('''INSERT INTO ops_ngo_activities (
            registration_number, ngo_vendor_name, activity_type,
            batch_name_no, activity_start_date, created_by
        ) VALUES (?,?,?,?,?,?)''', (
            f.get('registration_number'), f.get('ngo_vendor_name'), f.get('activity_type'),
            f.get('batch_name_no'), f.get('activity_start_date'), session.get('user_id', 0)
        ))
        conn.commit(); conn.close()
        flash('NGO Activity record added', 'success')
        return redirect(request.args.get('next') or url_for('ops_ngo_list'))
    conn.close()
    pre_reg = request.args.get('client', '')
    return render_template('ops_ngo_form.html', record=None,
                           ngo_vendors=get_lookup_options('ngo_vendor'),
                           activity_types=get_lookup_options('ngo_activity_type'),
                           pre_reg=pre_reg,
                           active_ops_page='ngo')


@admin_required
def ops_ngo_edit(rid):
    from app import get_lookup_options  # lazy import to avoid circular

    conn = get_db()
    record = conn.execute(
        "SELECT n.*, p.first_name, p.last_name, p.prefix FROM ops_ngo_activities n "
        "LEFT JOIN plab_clients p ON n.registration_number=p.registration_number "
        "WHERE n.id=?", (rid,)
    ).fetchone()
    if not record:
        conn.close(); flash('Record not found', 'error'); return redirect(url_for('ops_ngo_list'))
    if request.method == 'POST':
        f = request.form
        conn.execute('''UPDATE ops_ngo_activities SET
            registration_number=?, ngo_vendor_name=?, activity_type=?,
            batch_name_no=?, activity_start_date=? WHERE id=?''', (
            f.get('registration_number'), f.get('ngo_vendor_name'), f.get('activity_type'),
            f.get('batch_name_no'), f.get('activity_start_date'), rid
        ))
        conn.commit(); conn.close()
        flash('NGO Activity record updated', 'success')
        return redirect(request.args.get('next') or url_for('ops_ngo_list'))
    conn.close()
    return render_template('ops_ngo_form.html', record=record,
                           ngo_vendors=get_lookup_options('ngo_vendor'),
                           activity_types=get_lookup_options('ngo_activity_type'),
                           pre_reg='',
                           active_ops_page='ngo')


@admin_required
def ops_ngo_delete(rid):
    conn = get_db()
    conn.execute("DELETE FROM ops_ngo_activities WHERE id=?", (rid,))
    conn.commit(); conn.close()
    flash('NGO Activity record deleted', 'success')
    return redirect(request.args.get('next') or url_for('ops_ngo_list'))


def register_routes(app):
    """Register all NGO Activities routes on the Flask app.

    Uses add_url_rule (NOT Blueprint) to preserve original endpoint names,
    so url_for('ops_ngo_list') keeps working everywhere it's called.
    """
    app.add_url_rule('/operations/ngo-activities',
                     view_func=ops_ngo_list, endpoint='ops_ngo_list')
    app.add_url_rule('/operations/ngo-activities/add',
                     view_func=ops_ngo_add, endpoint='ops_ngo_add',
                     methods=['GET', 'POST'])
    app.add_url_rule('/operations/ngo-activities/<int:rid>/edit',
                     view_func=ops_ngo_edit, endpoint='ops_ngo_edit',
                     methods=['GET', 'POST'])
    app.add_url_rule('/operations/ngo-activities/<int:rid>/delete',
                     view_func=ops_ngo_delete, endpoint='ops_ngo_delete',
                     methods=['POST'])
