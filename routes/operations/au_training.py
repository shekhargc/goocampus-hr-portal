"""
routes/operations/au_training.py — Operations: Australia Training list.

Lists ops_coaching records imported from "All Trainings.xlsx" (stored in
the repo as All_Australia_Trainings.xlsx) for the Australia Pathway.

The legacy DB table name is `ops_coaching` even though the Excel and the
UI both call it Training. We filter by pathway='australia' so this view
never crosses streams with PLAB coaching rows.

A LEFT JOIN onto plab_clients on registration_number gives us the
candidate's display name (prefix + first + last).
"""

import logging
from flask import render_template, flash, request

from core.auth import admin_required
from core.users import get_user
from db import get_db


@admin_required
def ops_australia_training_list():
    """Australia training list — ops_coaching WHERE pathway='australia'."""
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
                  WHERE t.pathway = 'australia' '''
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
        sql += " ORDER BY COALESCE(t.start_date, t.end_date) DESC NULLS LAST, t.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        courses = [
            r['course_type'] for r in conn.execute(
                """SELECT DISTINCT course_type FROM ops_coaching
                    WHERE pathway = 'australia' AND course_type IS NOT NULL AND course_type != ''
                    ORDER BY course_type"""
            ).fetchall()
        ]
        methods = [
            r['coaching_method'] for r in conn.execute(
                """SELECT DISTINCT coaching_method FROM ops_coaching
                    WHERE pathway = 'australia' AND coaching_method IS NOT NULL AND coaching_method != ''
                    ORDER BY coaching_method"""
            ).fetchall()
        ]
        statuses = [
            r['coaching_status'] for r in conn.execute(
                """SELECT DISTINCT coaching_status FROM ops_coaching
                    WHERE pathway = 'australia' AND coaching_status IS NOT NULL AND coaching_status != ''
                    ORDER BY coaching_status"""
            ).fetchall()
        ]
        vendors = [
            r['vendor_provider'] for r in conn.execute(
                """SELECT DISTINCT vendor_provider FROM ops_coaching
                    WHERE pathway = 'australia' AND vendor_provider IS NOT NULL AND vendor_provider != ''
                    ORDER BY vendor_provider"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_australia_training_list: {e}")
        flash(f'Error loading Australia training: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_training_list.html',
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
        pathway_name='Australia Pathway',
        active_ops_page='australia-training',
        active_pathway='australia',
    )


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/australia/training',
        endpoint='ops_australia_training_list',
        view_func=ops_australia_training_list,
        methods=['GET'],
    )
