"""
routes/operations/uae_self_assessment.py — Operations: UAE Self Assessment.

Brand-new lightweight section for the UAE pathway. Surfaces rows from
ops_self_assessment WHERE pathway='uae', LEFT JOINed to plab_clients on
registration_number so the candidate name shows alongside each record.

Fields: Completed By (<select> lookup 'completed_by'), Date Completed (date),
Report Doc (text), Notes (textarea). list + add + edit + detail, all scoped
to pathway='uae'. Client picker uses /operations/api/client-search?pathway=uae.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
from app import get_lookup_options


# Columns on ops_self_assessment the add/edit forms may write to.
# id / registration_number / pathway / created_* are NOT editable via UI.
UAE_SELF_ASSESSMENT_EDITABLE_COLUMNS = [
    'completed_by',
    'date_completed',
    'report_doc',
    'notes',
]


def _uae_self_assessment_lookups():
    """Dropdown options for the Self Assessment form (pathway='uae')."""
    return {
        'completed_by_options': get_lookup_options('completed_by', pathway='uae'),
    }


@admin_required
def ops_uae_self_assessment_list():
    """UAE self assessment list — ops_self_assessment WHERE pathway='uae'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    completed_by_filter = (request.args.get('completed_by', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    completed_by_options = []
    total = 0

    try:
        sql = '''SELECT t.id, t.registration_number, t.completed_by,
                        t.date_completed, t.report_doc, t.notes,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_self_assessment t
                   LEFT JOIN plab_clients p
                          ON t.registration_number = p.registration_number
                         AND COALESCE(p.pathway, 'plab') = 'uae'
                  WHERE COALESCE(t.pathway, 'plab') = 'uae' '''
        params = []
        if reg:
            sql += " AND t.registration_number = ? "
            params.append(reg)
        if completed_by_filter:
            sql += " AND t.completed_by = ? "
            params.append(completed_by_filter)
        if search:
            sql += """ AND (
                p.first_name LIKE ? OR p.last_name LIKE ? OR
                t.registration_number LIKE ? OR t.notes LIKE ?
            ) """
            params.extend([f'%{search}%'] * 4)
        sql += " ORDER BY t.date_completed DESC NULLS LAST, t.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        completed_by_options = [
            r['completed_by'] for r in conn.execute(
                """SELECT DISTINCT completed_by FROM ops_self_assessment
                    WHERE COALESCE(pathway, 'plab') = 'uae'
                      AND completed_by IS NOT NULL AND completed_by != ''
                    ORDER BY completed_by"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_uae_self_assessment_list: {e}")
        flash(f'Error loading UAE self assessment records: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_uae_self_assessment_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        completed_by_filter=completed_by_filter,
        client_reg=reg,
        completed_by_options=completed_by_options,
        pathway_name='UAE Pathway',
        active_ops_page='uae-self-assessment',
        active_pathway='uae',
    )


@admin_required
def ops_uae_self_assessment_detail(rid):
    """Read-only detail view for a single UAE self assessment row."""
    user = get_user()
    conn = get_db()
    record = None
    try:
        record = conn.execute(
            """SELECT t.*, p.first_name, p.last_name, p.prefix,
                      p.mobile, p.email
                 FROM ops_self_assessment t
            LEFT JOIN plab_clients p
                   ON t.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'uae'
                WHERE t.id = ?
                  AND COALESCE(t.pathway, 'plab') = 'uae' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_uae_self_assessment_detail: {e}")
    finally:
        conn.close()

    if not record:
        flash('UAE self assessment record not found.', 'error')
        return redirect(url_for('ops_uae_self_assessment_list'))

    return render_template(
        'ops_uae_self_assessment_detail.html',
        user=user,
        record=record,
        pathway_name='UAE Pathway',
        active_ops_page='uae-self-assessment',
        active_pathway='uae',
    )


@admin_required
def ops_uae_self_assessment_edit_page(rid):
    """GET — render the edit form for a UAE self assessment row."""
    user = get_user()
    conn = get_db()
    record = None
    try:
        record = conn.execute(
            """SELECT t.*, p.first_name, p.last_name, p.prefix
                 FROM ops_self_assessment t
            LEFT JOIN plab_clients p
                   ON t.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'uae'
                WHERE t.id = ?
                  AND COALESCE(t.pathway, 'plab') = 'uae' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_uae_self_assessment_edit_page: {e}")
    finally:
        conn.close()

    if not record:
        flash('UAE self assessment record not found.', 'error')
        return redirect(url_for('ops_uae_self_assessment_list'))

    return render_template(
        'ops_uae_self_assessment_edit.html',
        user=user,
        record=record,
        pathway_name='UAE Pathway',
        active_ops_page='uae-self-assessment',
        active_pathway='uae',
        **_uae_self_assessment_lookups(),
    )


@admin_required
def ops_uae_self_assessment_edit_save(rid):
    """POST — save edits to a UAE self assessment row (strict allowlist)."""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM ops_self_assessment "
            "WHERE id = ? AND COALESCE(pathway, 'plab') = 'uae'",
            (rid,),
        ).fetchone()
        if not existing:
            flash('UAE self assessment record not found.', 'error')
            return redirect(url_for('ops_uae_self_assessment_list'))

        sets, params = [], []
        for col in UAE_SELF_ASSESSMENT_EDITABLE_COLUMNS:
            if col in request.form:
                val = request.form.get(col, '').strip()
                sets.append(f"{col} = ?")
                params.append(val)
        if sets:
            params.append(rid)
            conn.execute(
                "UPDATE ops_self_assessment SET " + ', '.join(sets)
                + " WHERE id = ? AND COALESCE(pathway, 'plab') = 'uae'",
                params,
            )
            conn.commit()
            flash('Self assessment record saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_uae_self_assessment_edit_save: {e}")
        flash(f'Error saving self assessment record: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_uae_self_assessment_detail', rid=rid))


@admin_required
def ops_uae_self_assessment_add_page():
    """GET — render the empty add form (reuses the edit template)."""
    user = get_user()
    empty_record = {col: None for col in UAE_SELF_ASSESSMENT_EDITABLE_COLUMNS}
    empty_record['id'] = None
    empty_record['registration_number'] = ''
    empty_record['first_name'] = ''
    empty_record['last_name'] = ''
    empty_record['prefix'] = ''
    return render_template(
        'ops_uae_self_assessment_edit.html',
        user=user,
        record=empty_record,
        is_new=True,
        pathway_name='UAE Pathway',
        active_ops_page='uae-self-assessment',
        active_pathway='uae',
        **_uae_self_assessment_lookups(),
    )


@admin_required
def ops_uae_self_assessment_add_save():
    """POST — insert a new UAE self assessment row (pathway='uae')."""
    conn = get_db()
    try:
        reg = (request.form.get('registration_number') or '').strip()
        if not reg:
            flash('Please select a candidate from the suggestions.', 'error')
            return redirect(url_for('ops_uae_self_assessment_add_page'))
        client = conn.execute(
            "SELECT id FROM plab_clients "
            "WHERE registration_number = ? AND COALESCE(pathway, 'plab') = 'uae'",
            (reg,),
        ).fetchone()
        if not client:
            flash('Selected candidate is not a UAE Pathway client.', 'error')
            try: conn.rollback()
            except Exception: pass
            return redirect(url_for('ops_uae_self_assessment_add_page'))

        cols = ['registration_number', 'pathway']
        vals = [reg, 'uae']
        for col in UAE_SELF_ASSESSMENT_EDITABLE_COLUMNS:
            if col in request.form:
                cols.append(col)
                vals.append((request.form.get(col) or '').strip() or None)
        placeholders = ', '.join(['?'] * len(cols))
        cur = conn.execute(
            f"INSERT INTO ops_self_assessment ({', '.join(cols)}) "
            f"VALUES ({placeholders}) RETURNING id",
            vals,
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        flash('Self assessment record added.', 'success')
        return redirect(url_for('ops_uae_self_assessment_detail', rid=new_id))
    except Exception as e:
        logging.error(f"ops_uae_self_assessment_add_save: {e}")
        flash(f'Error: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
        return redirect(url_for('ops_uae_self_assessment_list'))
    finally:
        conn.close()


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/uae/self-assessment',
        endpoint='ops_uae_self_assessment_list',
        view_func=ops_uae_self_assessment_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/uae/self-assessment/<int:rid>',
        endpoint='ops_uae_self_assessment_detail',
        view_func=ops_uae_self_assessment_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/uae/self-assessment/add',
        endpoint='ops_uae_self_assessment_add_page',
        view_func=ops_uae_self_assessment_add_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/uae/self-assessment/add',
        endpoint='ops_uae_self_assessment_add_save',
        view_func=ops_uae_self_assessment_add_save,
        methods=['POST'],
    )
    app.add_url_rule(
        '/operations/uae/self-assessment/<int:rid>/edit',
        endpoint='ops_uae_self_assessment_edit_page',
        view_func=ops_uae_self_assessment_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/uae/self-assessment/<int:rid>/edit',
        endpoint='ops_uae_self_assessment_edit_save',
        view_func=ops_uae_self_assessment_edit_save,
        methods=['POST'],
    )
