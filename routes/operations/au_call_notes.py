"""
routes/operations/au_call_notes.py — Operations: Australia Call Notes list.

Surfaces call-note records from ops_call_notes WHERE pathway='australia'.
Imported via import_australia_call_notes.run_import_australia_call_notes_once
(4,124 rows from All_Australia_Call_Notes.xlsx).

LEFT JOINs plab_clients so the table shows candidate names alongside the
reg number stored on each note.
"""

import logging
from flask import render_template, flash, request

from core.auth import admin_required
from core.users import get_user
from db import get_db


@admin_required
def ops_australia_call_notes_list():
    """Australia call notes list — ops_call_notes WHERE pathway='australia'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    added_by_filter = (request.args.get('added_by', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    added_by_options = []
    total = 0

    try:
        sql = '''SELECT n.id, n.registration_number, n.call_date, n.call_note,
                        n.added_by, n.pathway,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_call_notes n
                   LEFT JOIN plab_clients p
                          ON n.registration_number = p.registration_number
                  WHERE n.pathway = 'australia' '''
        params = []
        if reg:
            sql += " AND n.registration_number = ? "
            params.append(reg)
        if added_by_filter:
            sql += " AND n.added_by = ? "
            params.append(added_by_filter)
        if search:
            sql += """ AND (
                p.first_name LIKE ? OR p.last_name LIKE ? OR
                n.registration_number LIKE ? OR n.call_note LIKE ?
            ) """
            params.extend([f'%{search}%'] * 4)
        sql += " ORDER BY n.call_date DESC, n.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        added_by_options = [
            r['added_by'] for r in conn.execute(
                """SELECT DISTINCT added_by FROM ops_call_notes
                    WHERE pathway = 'australia' AND added_by IS NOT NULL AND added_by != ''
                    ORDER BY added_by"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_australia_call_notes_list: {e}")
        flash(f'Error loading Australia call notes: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_call_notes_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        added_by_filter=added_by_filter,
        client_reg=reg,
        added_by_options=added_by_options,
        pathway_name='Australia Pathway',
        active_ops_page='australia-call-notes',
        active_pathway='australia',
    )


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/australia/call-notes',
        endpoint='ops_australia_call_notes_list',
        view_func=ops_australia_call_notes_list,
        methods=['GET'],
    )
