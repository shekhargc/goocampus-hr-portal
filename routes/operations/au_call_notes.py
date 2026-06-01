"""
routes/operations/au_call_notes.py — Operations: Australia Call Notes list.

Surfaces call-note records from ops_call_notes WHERE pathway='australia'.
Imported via import_australia_call_notes.run_import_australia_call_notes_once
(4,124 rows from All_Australia_Call_Notes.xlsx).

LEFT JOINs plab_clients so the table shows candidate names alongside the
reg number stored on each note.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db


# ── Editable columns on ops_call_notes (pathway='australia' scope) ──────────
# Only safe-to-edit columns live here. id / registration_number / pathway are
# never editable through the UI.
AU_CALL_NOTES_EDITABLE_COLUMNS = [
    'call_date',
    'call_note',
    'added_by',
    'contact_type',
    'contacted_status',
]

# Numeric coercion list — any of these that exist on the table get coerced to
# float on save. ops_call_notes has none today but we keep the pattern so the
# template matches the other Australia sections.
AU_CALL_NOTES_NUMERIC_COLUMNS = {
    'amount', 'score', 'points', 'duration',
}


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
                        n.added_by, n.contact_type, n.contacted_status, n.pathway,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_call_notes n
                   LEFT JOIN plab_clients p
                          ON n.registration_number = p.registration_number
                         AND COALESCE(p.pathway, 'plab') = 'australia'
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
        sql += " ORDER BY n.call_date DESC NULLS LAST, n.id DESC "
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


@admin_required
def ops_australia_call_notes_detail(rid):
    """Full Australia call note view — read-only detail card.

    LEFT JOINs plab_clients via registration_number (pathway='australia') so
    the page can show the candidate's name alongside the note metadata.
    """
    user = get_user()
    conn = get_db()
    record = conn.execute(
        """SELECT n.*, p.first_name, p.last_name, p.prefix
             FROM ops_call_notes n
             LEFT JOIN plab_clients p
                    ON n.registration_number = p.registration_number
                   AND COALESCE(p.pathway, 'plab') = 'australia'
            WHERE n.id = ?
              AND COALESCE(n.pathway, 'plab') = 'australia' """,
        (rid,),
    ).fetchone()
    conn.close()
    if not record:
        flash('Australia call note not found.', 'error')
        return redirect(url_for('ops_australia_call_notes_list'))
    return render_template(
        'ops_australia_call_notes_detail.html',
        user=user,
        record=record,
        pathway_name='Australia Pathway',
        active_ops_page='australia-call-notes',
        active_pathway='australia',
    )


@admin_required
def ops_australia_call_notes_edit_page(rid):
    """GET — render the edit form for an Australia call note."""
    user = get_user()
    conn = get_db()
    record = conn.execute(
        """SELECT * FROM ops_call_notes
            WHERE id = ?
              AND COALESCE(pathway, 'plab') = 'australia' """,
        (rid,),
    ).fetchone()
    conn.close()
    if not record:
        flash('Australia call note not found.', 'error')
        return redirect(url_for('ops_australia_call_notes_list'))
    return render_template(
        'ops_australia_call_notes_edit.html',
        user=user,
        record=record,
        pathway_name='Australia Pathway',
        active_ops_page='australia-call-notes',
        active_pathway='australia',
    )


@admin_required
def ops_australia_call_notes_edit_save(rid):
    """POST handler: save changes to an Australia call note's editable fields.

    Strict allowlist (AU_CALL_NOTES_EDITABLE_COLUMNS). Pathway is NEVER
    updated through this endpoint.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            """SELECT id FROM ops_call_notes
                WHERE id = ?
                  AND COALESCE(pathway, 'plab') = 'australia' """,
            (rid,),
        ).fetchone()
        if not existing:
            flash('Australia call note not found.', 'error')
            return redirect(url_for('ops_australia_call_notes_list'))

        sets = []
        params = []
        for col in AU_CALL_NOTES_EDITABLE_COLUMNS:
            if col in request.form:
                val = request.form.get(col, '').strip()
                if col in AU_CALL_NOTES_NUMERIC_COLUMNS:
                    try:
                        val = float(val) if val else 0
                    except ValueError:
                        val = 0
                sets.append(f"{col} = ?")
                params.append(val)
        if sets:
            params.append(rid)
            conn.execute(
                f"UPDATE ops_call_notes SET {', '.join(sets)} "
                f" WHERE id = ? AND COALESCE(pathway, 'plab') = 'australia'",
                params,
            )
            conn.commit()
            flash('Call note saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_australia_call_notes_edit_save: {e}")
        flash(f'Error saving call note: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_australia_call_notes_detail', rid=rid))


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/australia/call-notes',
        endpoint='ops_australia_call_notes_list',
        view_func=ops_australia_call_notes_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/call-notes/<int:rid>',
        endpoint='ops_australia_call_notes_detail',
        view_func=ops_australia_call_notes_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/call-notes/<int:rid>/edit',
        endpoint='ops_australia_call_notes_edit_page',
        view_func=ops_australia_call_notes_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/call-notes/<int:rid>/edit',
        endpoint='ops_australia_call_notes_edit_save',
        view_func=ops_australia_call_notes_edit_save,
        methods=['POST'],
    )
