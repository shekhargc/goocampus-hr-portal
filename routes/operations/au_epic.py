"""
routes/operations/au_epic.py — Operations: Australia Pathway → EPIC Registration list.

Mirrors the structure of routes/operations/australia.py::ops_australia_test_bookings_list.
Shows ops_epic_registration rows where pathway='australia', joined with
plab_clients on registration_number for candidate name display.
"""

import logging
from flask import render_template, flash, request

from core.auth import admin_required
from core.users import get_user
from db import get_db


@admin_required
def ops_australia_epic_list():
    """Australia EPIC list — ops_epic_registration WHERE pathway='australia'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    epic_status_filter = (request.args.get('epic_status', '') or '').strip()
    epic_reg_filter = (request.args.get('epic_registration', '') or '').strip()
    docs_stage_filter = (request.args.get('documents_stage', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    epic_statuses = []
    epic_registrations = []
    documents_stages = []
    total = 0

    try:
        sql = '''SELECT e.id, e.registration_number, e.epic_registration,
                        e.epic_status, e.notary_camp, e.registration_date,
                        e.documents_stage, e.document_stage_status,
                        e.login_id, e.epic_id_number, e.notary_camp_login,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_epic_registration e
                   LEFT JOIN plab_clients p
                          ON e.registration_number = p.registration_number
                  WHERE e.pathway = 'australia' '''
        params = []
        if reg:
            sql += " AND e.registration_number = ? "
            params.append(reg)
        if epic_status_filter:
            sql += " AND e.epic_status = ? "
            params.append(epic_status_filter)
        if epic_reg_filter:
            sql += " AND e.epic_registration = ? "
            params.append(epic_reg_filter)
        if docs_stage_filter:
            sql += " AND e.documents_stage = ? "
            params.append(docs_stage_filter)
        if search:
            sql += """ AND (
                p.first_name LIKE ? OR p.last_name LIKE ? OR
                e.registration_number LIKE ? OR e.login_id LIKE ? OR
                e.epic_id_number LIKE ?
            ) """
            params.extend([f'%{search}%'] * 5)
        sql += " ORDER BY COALESCE(e.registration_date, '') DESC, e.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        epic_statuses = [
            r['epic_status'] for r in conn.execute(
                """SELECT DISTINCT epic_status FROM ops_epic_registration
                    WHERE pathway = 'australia' AND epic_status IS NOT NULL AND epic_status != ''
                    ORDER BY epic_status"""
            ).fetchall()
        ]
        epic_registrations = [
            r['epic_registration'] for r in conn.execute(
                """SELECT DISTINCT epic_registration FROM ops_epic_registration
                    WHERE pathway = 'australia' AND epic_registration IS NOT NULL AND epic_registration != ''
                    ORDER BY epic_registration"""
            ).fetchall()
        ]
        documents_stages = [
            r['documents_stage'] for r in conn.execute(
                """SELECT DISTINCT documents_stage FROM ops_epic_registration
                    WHERE pathway = 'australia' AND documents_stage IS NOT NULL AND documents_stage != ''
                    ORDER BY documents_stage"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_australia_epic_list: {e}")
        flash(f'Error loading Australia EPIC registrations: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_epic_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        epic_status_filter=epic_status_filter,
        epic_reg_filter=epic_reg_filter,
        docs_stage_filter=docs_stage_filter,
        client_reg=reg,
        epic_statuses=epic_statuses,
        epic_registrations=epic_registrations,
        documents_stages=documents_stages,
        pathway_name='Australia Pathway',
        active_ops_page='australia-epic',
        active_pathway='australia',
    )


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/australia/epic',
        endpoint='ops_australia_epic_list',
        view_func=ops_australia_epic_list,
        methods=['GET'],
    )
