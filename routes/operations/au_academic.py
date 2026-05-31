"""
routes/operations/au_academic.py — Operations: Australia Academic Details list.

Surfaces ops_academic_details WHERE pathway='australia', LEFT JOINed against
plab_clients on registration_number so the candidate name shows even though
ops_academic_details itself doesn't store the name.

Endpoint name: ops_australia_academic_list (kept stable so url_for()
call sites stay simple).
"""

import logging
from flask import render_template, flash, request

from core.auth import admin_required
from core.users import get_user
from db import get_db


@admin_required
def ops_australia_academic_list():
    """Australia academic details list — ops_academic_details WHERE pathway='australia'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    img_fmg_filter = (request.args.get('img_fmg', '') or '').strip()
    mbbs_status_filter = (request.args.get('mbbs_status', '') or '').strip()
    working_status_filter = (request.args.get('working_status', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    img_fmgs = []
    mbbs_statuses = []
    working_statuses = []
    total = 0

    try:
        sql = '''SELECT a.id, a.registration_number, a.img_fmg,
                        a.img_medical_college, a.fmg_medical_college,
                        a.country, a.mbbs_status, a.mbbs_end_date,
                        a.speciality_interest_1, a.speciality_interest_2,
                        a.internship_status, a.internship_hospital,
                        a.internship_location, a.working_status,
                        a.working_hospital_name,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_academic_details a
                   LEFT JOIN plab_clients p
                          ON a.registration_number = p.registration_number
                  WHERE a.pathway = 'australia' '''
        params = []
        if reg:
            sql += " AND a.registration_number = ? "
            params.append(reg)
        if img_fmg_filter:
            sql += " AND a.img_fmg = ? "
            params.append(img_fmg_filter)
        if mbbs_status_filter:
            sql += " AND a.mbbs_status = ? "
            params.append(mbbs_status_filter)
        if working_status_filter:
            sql += " AND a.working_status = ? "
            params.append(working_status_filter)
        if search:
            sql += """ AND (
                p.first_name LIKE ? OR p.last_name LIKE ? OR
                a.registration_number LIKE ? OR
                a.img_medical_college LIKE ? OR a.fmg_medical_college LIKE ?
            ) """
            params.extend([f'%{search}%'] * 5)
        sql += " ORDER BY a.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        img_fmgs = [
            r['img_fmg'] for r in conn.execute(
                """SELECT DISTINCT img_fmg FROM ops_academic_details
                    WHERE pathway = 'australia' AND img_fmg IS NOT NULL AND img_fmg != ''
                    ORDER BY img_fmg"""
            ).fetchall()
        ]
        mbbs_statuses = [
            r['mbbs_status'] for r in conn.execute(
                """SELECT DISTINCT mbbs_status FROM ops_academic_details
                    WHERE pathway = 'australia' AND mbbs_status IS NOT NULL AND mbbs_status != ''
                    ORDER BY mbbs_status"""
            ).fetchall()
        ]
        working_statuses = [
            r['working_status'] for r in conn.execute(
                """SELECT DISTINCT working_status FROM ops_academic_details
                    WHERE pathway = 'australia' AND working_status IS NOT NULL AND working_status != ''
                    ORDER BY working_status"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_australia_academic_list: {e}")
        flash(f'Error loading Australia academic details: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_academic_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        img_fmg_filter=img_fmg_filter,
        mbbs_status_filter=mbbs_status_filter,
        working_status_filter=working_status_filter,
        client_reg=reg,
        img_fmgs=img_fmgs,
        mbbs_statuses=mbbs_statuses,
        working_statuses=working_statuses,
        pathway_name='Australia Pathway',
        active_ops_page='australia-academic',
        active_pathway='australia',
    )


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/australia/academic-details',
        endpoint='ops_australia_academic_list',
        view_func=ops_australia_academic_list,
        methods=['GET'],
    )
