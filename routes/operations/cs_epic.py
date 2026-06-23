"""
routes/operations/cs_epic.py — Operations: Standard Consulting → EPIC Registration.

Mirrors the standardized Australia Registration pattern:
  - List view  (/operations/consulting/epic)
  - Detail     (/operations/consulting/epic/<id>)
  - Edit form  (/operations/consulting/epic/<id>/edit) GET + POST

Filters every query by pathway='consulting' so PLAB data never leaks in.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
# Pathway-scoped dropdown options for the Consulting EPIC Verification edit form.
from routes.operations._form_lookups import section_epic_lookups


# Allowlist of columns that the edit form is permitted to write to.
# Pathway is NEVER updated through this endpoint.
CS_EPIC_EDITABLE_COLUMNS = [
    'epic_registration',
    'epic_status',
    'notary_camp',
    'registration_date',
    'documents_stage',
    'document_stage_status',
    'notary_camp_login',
    'login_id',
    'login_pwd',
    'notary_camp_password',
    'secret_question_1', 'secret_answer_1',
    'secret_question_2', 'secret_answer_2',
    'secret_question_3', 'secret_answer_3',
    'secret_question_4', 'secret_answer_4',
    'epic_id_number',
]

# Columns that should be coerced to numeric on save.
_NUMERIC_COLS = {
    'amount', 'score', 'points', 'duration',
    'package_amount', 'discount_allowed', 'final_package',
}


@admin_required
def ops_consulting_epic_list():
    """Consulting EPIC list — ops_epic_registration WHERE pathway='consulting'."""
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
                         AND COALESCE(p.pathway, 'plab') = 'consulting'
                  WHERE COALESCE(e.pathway, 'plab') = 'consulting' '''
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
                p.first_name ILIKE ? OR p.last_name ILIKE ? OR
                e.registration_number ILIKE ? OR e.login_id ILIKE ? OR
                e.epic_id_number ILIKE ? OR
                (COALESCE(p.prefix,'')||' '||p.first_name||' '||COALESCE(p.last_name,'')) ILIKE ?
            ) """
            params.extend([f'%{search}%'] * 6)
        # Recent-first: most recently registered EPIC entries first.
        sql += " ORDER BY COALESCE(e.registration_date, '') DESC, e.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        epic_statuses = [
            r['epic_status'] for r in conn.execute(
                """SELECT DISTINCT epic_status FROM ops_epic_registration
                    WHERE COALESCE(pathway, 'plab') = 'consulting'
                      AND epic_status IS NOT NULL AND epic_status != ''
                    ORDER BY epic_status"""
            ).fetchall()
        ]
        epic_registrations = [
            r['epic_registration'] for r in conn.execute(
                """SELECT DISTINCT epic_registration FROM ops_epic_registration
                    WHERE COALESCE(pathway, 'plab') = 'consulting'
                      AND epic_registration IS NOT NULL AND epic_registration != ''
                    ORDER BY epic_registration"""
            ).fetchall()
        ]
        documents_stages = [
            r['documents_stage'] for r in conn.execute(
                """SELECT DISTINCT documents_stage FROM ops_epic_registration
                    WHERE COALESCE(pathway, 'plab') = 'consulting'
                      AND documents_stage IS NOT NULL AND documents_stage != ''
                    ORDER BY documents_stage"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_consulting_epic_list: {e}")
        flash(f'Error loading Consulting EPIC registrations: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_consulting_epic_list.html',
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
        pathway_name='Standard Consulting',
        active_ops_page='consulting-epic',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_epic_detail(rid):
    """Read-only detail page for a single Consulting EPIC registration row."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT e.*,
                      p.first_name, p.last_name, p.prefix
                 FROM ops_epic_registration e
                 LEFT JOIN plab_clients p
                        ON e.registration_number = p.registration_number
                       AND COALESCE(p.pathway, 'plab') = 'consulting'
                WHERE e.id = ?
                  AND COALESCE(e.pathway, 'plab') = 'consulting'""",
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_consulting_epic_detail: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Consulting EPIC registration not found.', 'error')
        return redirect(url_for('ops_consulting_epic_list'))

    return render_template(
        'ops_consulting_epic_detail.html',
        user=user,
        record=record,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-epic',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_epic_edit_page(rid):
    """GET — render the edit form for an Consulting EPIC registration row."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT e.*,
                      p.first_name, p.last_name, p.prefix
                 FROM ops_epic_registration e
                 LEFT JOIN plab_clients p
                        ON e.registration_number = p.registration_number
                       AND COALESCE(p.pathway, 'plab') = 'consulting'
                WHERE e.id = ?
                  AND COALESCE(e.pathway, 'plab') = 'consulting'""",
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_consulting_epic_edit_page: {e}")
        record = None
    finally:
        conn.close()

    if not record:
        flash('Consulting EPIC registration not found.', 'error')
        return redirect(url_for('ops_consulting_epic_list'))

    return render_template(
        'ops_consulting_epic_edit.html',
        user=user,
        record=record,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-epic',
        active_pathway='consulting',
        # Dropdown options sourced from lookup_options where pathway='consulting'.
        **section_epic_lookups('consulting'),
    )


@admin_required
def ops_consulting_epic_edit_save(rid):
    """POST handler: save changes to an Consulting EPIC registration row.

    Strict allowlist (CS_EPIC_EDITABLE_COLUMNS) — anything else in the form
    is silently ignored. Pathway is NEVER updated through this endpoint.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            """SELECT id FROM ops_epic_registration
                WHERE id = ?
                  AND COALESCE(pathway, 'plab') = 'consulting'""",
            (rid,),
        ).fetchone()
        if not existing:
            flash('Consulting EPIC registration not found.', 'error')
            return redirect(url_for('ops_consulting_epic_list'))

        sets = []
        params = []
        for col in CS_EPIC_EDITABLE_COLUMNS:
            if col in request.form:
                val = request.form.get(col, '').strip()
                # Numeric coercion for amount/score/points/duration columns.
                if col in _NUMERIC_COLS:
                    try:
                        val = float(val) if val else 0
                    except ValueError:
                        val = 0
                sets.append(f"{col} = ?")
                params.append(val if val != '' else None)
        if sets:
            params.append(rid)
            conn.execute(
                f"UPDATE ops_epic_registration SET {', '.join(sets)} "
                f" WHERE id = ? AND COALESCE(pathway, 'plab') = 'consulting'",
                params,
            )
            conn.commit()
            flash('EPIC registration saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_consulting_epic_edit_save: {e}")
        flash(f'Error saving EPIC registration: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_consulting_epic_detail', rid=rid))


@admin_required
def ops_consulting_epic_add_page():
    """GET — render the empty add form (reuses the edit template)."""
    user = get_user()
    empty_record = {col: None for col in CS_EPIC_EDITABLE_COLUMNS}
    empty_record['id'] = None
    empty_record['registration_number'] = ''
    empty_record['first_name'] = ''
    empty_record['last_name'] = ''
    empty_record['prefix'] = ''
    return render_template(
        'ops_consulting_epic_edit.html',
        user=user,
        record=empty_record,
        is_new=True,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-epic',
        active_pathway='consulting',
        # Dropdown options sourced from lookup_options where pathway='consulting'.
        **section_epic_lookups('consulting'),
    )


@admin_required
def ops_consulting_epic_add_save():
    """POST — insert a new Consulting EPIC registration row."""
    conn = get_db()
    try:
        reg = (request.form.get('registration_number') or '').strip()
        if not reg:
            flash('Registration number is required.', 'error')
            return redirect(url_for('ops_consulting_epic_add_page'))
        cols = ['registration_number', 'pathway']
        vals = [reg, 'consulting']
        for col in CS_EPIC_EDITABLE_COLUMNS:
            if col in request.form:
                v = (request.form.get(col) or '').strip()
                if col in _NUMERIC_COLS:
                    try:
                        v = float(v) if v else None
                    except ValueError:
                        v = None
                elif v == '':
                    v = None
                cols.append(col)
                vals.append(v)
        # Record who created this row (logged-in team member).
        if 'created_by' not in cols:
            cols.append('created_by')
            vals.append((get_user() or {}).get('id'))
        placeholders = ', '.join(['?'] * len(cols))
        cur = conn.execute(
            f"INSERT INTO ops_epic_registration ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
            vals,
        )
        new_id = cur.fetchone()['id']
        conn.commit()
        flash('EPIC registration added.', 'success')
        return redirect(url_for('ops_consulting_epic_detail', rid=new_id))
    except Exception as e:
        logging.error(f"ops_consulting_epic_add_save: {e}")
        flash(f'Error: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
        return redirect(url_for('ops_consulting_epic_list'))
    finally:
        conn.close()


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/consulting/epic',
        endpoint='ops_consulting_epic_list',
        view_func=ops_consulting_epic_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/epic/<int:rid>',
        endpoint='ops_consulting_epic_detail',
        view_func=ops_consulting_epic_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/epic/add',
        endpoint='ops_consulting_epic_add_page',
        view_func=ops_consulting_epic_add_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/epic/add',
        endpoint='ops_consulting_epic_add_save',
        view_func=ops_consulting_epic_add_save,
        methods=['POST'],
    )
    app.add_url_rule(
        '/operations/consulting/epic/<int:rid>/edit',
        endpoint='ops_consulting_epic_edit_page',
        view_func=ops_consulting_epic_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/epic/<int:rid>/edit',
        endpoint='ops_consulting_epic_edit_save',
        view_func=ops_consulting_epic_edit_save,
        methods=['POST'],
    )
