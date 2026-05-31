"""
routes/operations/au_online_courses.py — Operations: Australia Pathway
Online Courses & Subscriptions list view.

Surfaces ops_online_subscriptions WHERE pathway='australia' — populated
by import_australia_online_courses.run_import_australia_online_courses_once()
at app boot.
"""

import logging
from flask import render_template, flash, request

from core.auth import admin_required
from core.users import get_user
from db import get_db


@admin_required
def ops_australia_online_courses_list():
    """Australia online courses list — ops_online_subscriptions WHERE pathway='australia'."""
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
                  WHERE s.pathway = 'australia' '''
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
                p.first_name LIKE ? OR p.last_name LIKE ? OR
                s.registration_number LIKE ? OR s.online_subscription LIKE ? OR
                s.client_email LIKE ?
            ) """
            params.extend([f'%{search}%'] * 5)
        sql += " ORDER BY COALESCE(s.issued_date, '') DESC, s.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        courses = [
            r['online_subscription'] for r in conn.execute(
                """SELECT DISTINCT online_subscription FROM ops_online_subscriptions
                    WHERE pathway = 'australia' AND online_subscription IS NOT NULL
                      AND online_subscription != ''
                    ORDER BY online_subscription"""
            ).fetchall()
        ]
        activations = [
            r['activation_type'] for r in conn.execute(
                """SELECT DISTINCT activation_type FROM ops_online_subscriptions
                    WHERE pathway = 'australia' AND activation_type IS NOT NULL
                      AND activation_type != ''
                    ORDER BY activation_type"""
            ).fetchall()
        ]
        booked_bys = [
            r['booked_by'] for r in conn.execute(
                """SELECT DISTINCT booked_by FROM ops_online_subscriptions
                    WHERE pathway = 'australia' AND booked_by IS NOT NULL
                      AND booked_by != ''
                    ORDER BY booked_by"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_australia_online_courses_list: {e}")
        flash(f'Error loading Australia online courses: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_online_courses_list.html',
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
        pathway_name='Australia Pathway',
        active_ops_page='australia-online-courses',
        active_pathway='australia',
    )


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/australia/online-courses',
        endpoint='ops_australia_online_courses_list',
        view_func=ops_australia_online_courses_list,
        methods=['GET'],
    )
