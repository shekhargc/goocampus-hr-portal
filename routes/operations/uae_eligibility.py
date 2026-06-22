"""
routes/operations/uae_eligibility.py — Operations: UAE Eligibility Letter.

Brand-new lightweight section for the UAE pathway. Surfaces rows from
ops_eligibility_letter WHERE pathway='uae', LEFT JOINed to plab_clients on
registration_number so the candidate name shows alongside each record.

Fields: Completed By (<select> lookup 'completed_by'), Eligibility Registration
Date (date), Eligibility Status (<select> lookup 'eligibility_status' →
Pending/Approved), Notes (textarea). list + add + edit + detail, all scoped to
pathway='uae'. Client picker uses /operations/api/client-search?pathway=uae.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
from app import get_lookup_options


# Columns on ops_eligibility_letter the add/edit forms may write to.
# id / registration_number / pathway / created_* are NOT editable via UI.
UAE_ELIGIBILITY_EDITABLE_COLUMNS = [
    'completed_by',
    'eligibility_registration_date',
    'eligibility_status',
    'notes',
]


def _uae_eligibility_lookups():
    """Dropdown options for the Eligibility Letter form (pathway='uae')."""
    return {
        'completed_by_options':       get_lookup_options('completed_by', pathway='uae'),
        'eligibility_status_options': get_lookup_options('eligibility_status', pathway='uae'),
    }


@admin_required
def ops_uae_eligibility_list():
    """UAE eligibility letter list — ops_eligibility_letter WHERE pathway='uae'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    status_filter = (request.args.get('status', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    statuses = []
    total = 0

    try:
        sql = '''SELECT t.id, t.registration_number, t.completed_by,
                        t.eligibility_registration_date, t.eligibility_status,
                        t.notes,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_eligibility_letter t
                   LEFT JOIN plab_clients p
                          ON t.registration_number = p.registration_number
                         AND COALESCE(p.pathway, 'plab') = 'uae'
                  WHERE COALESCE(t.pathway, 'plab') = 'uae' '''
        params = []
        if reg:
            sql += " AND t.registration_number = ? "
            params.append(reg)
        if status_filter:
            sql += " AND t.eligibility_status = ? "
            params.append(status_filter)
        if search:
            sql += """ AND (
                p.first_name ILIKE ? OR p.last_name ILIKE ? OR
                t.registration_number ILIKE ? OR t.notes ILIKE ? OR
                (COALESCE(p.prefix,'')||' '||p.first_name||' '||COALESCE(p.last_name,'')) ILIKE ?
            ) """
            params.extend([f'%{search}%'] * 5)
        sql += " ORDER BY t.eligibility_registration_date DESC NULLS LAST, t.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        statuses = [
            r['eligibility_status'] for r in conn.execute(
                """SELECT DISTINCT eligibility_status FROM ops_eligibility_letter
                    WHERE COALESCE(pathway, 'plab') = 'uae'
                      AND eligibility_status IS NOT NULL AND eligibility_status != ''
                    ORDER BY eligibility_status"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_uae_eligibility_list: {e}")
        flash(f'Error loading UAE eligibility records: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_uae_eligibility_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        status_filter=status_filter,
        client_reg=reg,
        statuses=statuses,
        pathway_name='UAE Pathway',
        active_ops_page='uae-eligibility-letter',
        active_pathway='uae',
    )


@admin_required
def ops_uae_eligibility_detail(rid):
    """Read-only detail view for a single UAE eligibility letter row."""
    user = get_user()
    conn = get_db()
    record = None
    try:
        record = conn.execute(
            """SELECT t.*, p.first_name, p.last_name, p.prefix,
                      p.mobile, p.email
                 FROM ops_eligibility_letter t
            LEFT JOIN plab_clients p
                   ON t.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'uae'
                WHERE t.id = ?
                  AND COALESCE(t.pathway, 'plab') = 'uae' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_uae_eligibility_detail: {e}")
    finally:
        conn.close()

    if not record:
        flash('UAE eligibility record not found.', 'error')
        return redirect(url_for('ops_uae_eligibility_list'))

    return render_template(
        'ops_uae_eligibility_detail.html',
        user=user,
        record=record,
        pathway_name='UAE Pathway',
        active_ops_page='uae-eligibility-letter',
        active_pathway='uae',
    )


@admin_required
def ops_uae_eligibility_edit_page(rid):
    """GET — render the edit form for a UAE eligibility letter row."""
    user = get_user()
    conn = get_db()
    record = None
    try:
        record = conn.execute(
            """SELECT t.*, p.first_name, p.last_name, p.prefix
                 FROM ops_eligibility_letter t
            LEFT JOIN plab_clients p
                   ON t.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'uae'
                WHERE t.id = ?
                  AND COALESCE(t.pathway, 'plab') = 'uae' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_uae_eligibility_edit_page: {e}")
    finally:
        conn.close()

    if not record:
        flash('UAE eligibility record not found.', 'error')
        return redirect(url_for('ops_uae_eligibility_list'))

    return render_template(
        'ops_uae_eligibility_edit.html',
        user=user,
        record=record,
        pathway_name='UAE Pathway',
        active_ops_page='uae-eligibility-letter',
        active_pathway='uae',
        **_uae_eligibility_lookups(),
    )


@admin_required
def ops_uae_eligibility_edit_save(rid):
    """POST — save edits to a UAE eligibility letter row (strict allowlist)."""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM ops_eligibility_letter "
            "WHERE id = ? AND COALESCE(pathway, 'plab') = 'uae'",
            (rid,),
        ).fetchone()
        if not existing:
            flash('UAE eligibility record not found.', 'error')
            return redirect(url_for('ops_uae_eligibility_list'))

        sets, params = [], []
        for col in UAE_ELIGIBILITY_EDITABLE_COLUMNS:
            if col in request.form:
                val = request.form.get(col, '').strip()
                sets.append(f"{col} = ?")
                params.append(val)
        if sets:
            params.append(rid)
            conn.execute(
                "UPDATE ops_eligibility_letter SET " + ', '.join(sets)
                + " WHERE id = ? AND COALESCE(pathway, 'plab') = 'uae'",
                params,
            )
            conn.commit()
            flash('Eligibility record saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_uae_eligibility_edit_save: {e}")
        flash(f'Error saving eligibility record: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_uae_eligibility_detail', rid=rid))


@admin_required
def ops_uae_eligibility_add_page():
    """GET — render the empty add form (reuses the edit template)."""
    user = get_user()
    empty_record = {col: None for col in UAE_ELIGIBILITY_EDITABLE_COLUMNS}
    empty_record['id'] = None
    empty_record['registration_number'] = ''
    empty_record['first_name'] = ''
    empty_record['last_name'] = ''
    empty_record['prefix'] = ''
    return render_template(
        'ops_uae_eligibility_edit.html',
        user=user,
        record=empty_record,
        is_new=True,
        pathway_name='UAE Pathway',
        active_ops_page='uae-eligibility-letter',
        active_pathway='uae',
        **_uae_eligibility_lookups(),
    )


@admin_required
def ops_uae_eligibility_add_save():
    """POST — insert a new UAE eligibility letter row (pathway='uae')."""
    conn = get_db()
    try:
        reg = (request.form.get('registration_number') or '').strip()
        if not reg:
            flash('Please select a candidate from the suggestions.', 'error')
            return redirect(url_for('ops_uae_eligibility_add_page'))
        client = conn.execute(
            "SELECT id FROM plab_clients "
            "WHERE registration_number = ? AND COALESCE(pathway, 'plab') = 'uae'",
            (reg,),
        ).fetchone()
        if not client:
            flash('Selected candidate is not a UAE Pathway client.', 'error')
            try: conn.rollback()
            except Exception: pass
            return redirect(url_for('ops_uae_eligibility_add_page'))

        cols = ['registration_number', 'pathway']
        vals = [reg, 'uae']
        for col in UAE_ELIGIBILITY_EDITABLE_COLUMNS:
            if col in request.form:
                cols.append(col)
                vals.append((request.form.get(col) or '').strip() or None)
        placeholders = ', '.join(['?'] * len(cols))
        cur = conn.execute(
            f"INSERT INTO ops_eligibility_letter ({', '.join(cols)}) "
            f"VALUES ({placeholders}) RETURNING id",
            vals,
        )
        new_id = cur.fetchone()['id']
        conn.commit()
        flash('Eligibility record added.', 'success')
        return redirect(url_for('ops_uae_eligibility_detail', rid=new_id))
    except Exception as e:
        logging.error(f"ops_uae_eligibility_add_save: {e}")
        flash(f'Error: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
        return redirect(url_for('ops_uae_eligibility_list'))
    finally:
        conn.close()


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/uae/eligibility-letter',
        endpoint='ops_uae_eligibility_list',
        view_func=ops_uae_eligibility_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/uae/eligibility-letter/<int:rid>',
        endpoint='ops_uae_eligibility_detail',
        view_func=ops_uae_eligibility_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/uae/eligibility-letter/add',
        endpoint='ops_uae_eligibility_add_page',
        view_func=ops_uae_eligibility_add_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/uae/eligibility-letter/add',
        endpoint='ops_uae_eligibility_add_save',
        view_func=ops_uae_eligibility_add_save,
        methods=['POST'],
    )
    app.add_url_rule(
        '/operations/uae/eligibility-letter/<int:rid>/edit',
        endpoint='ops_uae_eligibility_edit_page',
        view_func=ops_uae_eligibility_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/uae/eligibility-letter/<int:rid>/edit',
        endpoint='ops_uae_eligibility_edit_save',
        view_func=ops_uae_eligibility_edit_save,
        methods=['POST'],
    )
