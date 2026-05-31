"""
routes/operations/au_webinars.py — Operations: Australia Pathway
Webinars & Conferences list.

Surfaces rows from ops_webinars_conferences WHERE pathway='australia',
joined to plab_clients on registration_number so we can show the
candidate name. Records are imported one-time from
All_Australia_Webinars.xlsx by
import_australia_webinars.run_import_australia_webinars_once() at app
boot.
"""

import logging
from flask import render_template, flash, request

from core.auth import admin_required
from core.users import get_user
from db import get_db


@admin_required
def ops_australia_webinars_list():
    """Australia webinars & conferences list — ops_webinars_conferences WHERE pathway='australia'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    event_type_filter = (request.args.get('event_type', '') or '').strip()
    participation_filter = (request.args.get('participation', '') or '').strip()
    event_value_filter = (request.args.get('event_value', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    event_types = []
    participations = []
    event_values = []
    total = 0

    try:
        sql = '''SELECT w.id, w.registration_number, w.event_type,
                        w.start_date, w.end_date, w.duration_days,
                        w.event_value, w.cpd_points, w.event_name,
                        w.participation_type, w.notes,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_webinars_conferences w
                   LEFT JOIN plab_clients p
                          ON w.registration_number = p.registration_number
                  WHERE w.pathway = 'australia' '''
        params = []
        if reg:
            sql += " AND w.registration_number = ? "
            params.append(reg)
        if event_type_filter:
            sql += " AND w.event_type = ? "
            params.append(event_type_filter)
        if participation_filter:
            sql += " AND w.participation_type = ? "
            params.append(participation_filter)
        if event_value_filter:
            sql += " AND w.event_value = ? "
            params.append(event_value_filter)
        if search:
            sql += """ AND (
                p.first_name LIKE ? OR p.last_name LIKE ? OR
                w.event_name LIKE ? OR w.registration_number LIKE ? OR
                w.notes LIKE ?
            ) """
            params.extend([f'%{search}%'] * 5)
        sql += " ORDER BY COALESCE(w.start_date, '') DESC, w.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        event_types = [
            r['event_type'] for r in conn.execute(
                """SELECT DISTINCT event_type FROM ops_webinars_conferences
                    WHERE pathway = 'australia' AND event_type IS NOT NULL AND event_type != ''
                    ORDER BY event_type"""
            ).fetchall()
        ]
        participations = [
            r['participation_type'] for r in conn.execute(
                """SELECT DISTINCT participation_type FROM ops_webinars_conferences
                    WHERE pathway = 'australia' AND participation_type IS NOT NULL AND participation_type != ''
                    ORDER BY participation_type"""
            ).fetchall()
        ]
        event_values = [
            r['event_value'] for r in conn.execute(
                """SELECT DISTINCT event_value FROM ops_webinars_conferences
                    WHERE pathway = 'australia' AND event_value IS NOT NULL AND event_value != ''
                    ORDER BY event_value"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_australia_webinars_list: {e}")
        flash(f'Error loading Australia webinars & conferences: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_webinars_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        event_type_filter=event_type_filter,
        participation_filter=participation_filter,
        event_value_filter=event_value_filter,
        client_reg=reg,
        event_types=event_types,
        participations=participations,
        event_values=event_values,
        pathway_name='Australia Pathway',
        active_ops_page='australia-webinars',
        active_pathway='australia',
    )


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/australia/webinars',
        endpoint='ops_australia_webinars_list',
        view_func=ops_australia_webinars_list,
        methods=['GET'],
    )
