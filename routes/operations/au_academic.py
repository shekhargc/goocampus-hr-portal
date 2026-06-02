"""
routes/operations/au_academic.py — Operations: Australia Academic Details.

Surfaces ops_academic_details WHERE pathway='australia', LEFT JOINed against
plab_clients on registration_number so the candidate name shows even though
ops_academic_details itself doesn't store the name.

Mirrors the Australia Registration pattern (clients_list / client_detail /
client_edit_form): list with click-to-open drawer + dedicated detail page +
dedicated edit page. Keeps endpoint names stable so url_for() call sites
elsewhere don't need to change.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db


# ── Editable columns on ops_academic_details (pathway='australia' scope) ────
# Only columns safe to edit through the UI. id / registration_number /
# pathway / created_at / created_by are NOT editable.
AU_ACADEMIC_EDITABLE_COLUMNS = [
    'img_fmg', 'img_medical_college', 'fmg_medical_college', 'country',
    'mbbs_status', 'mbbs_start_date', 'mbbs_end_date',
    'speciality_interest_1', 'speciality_interest_2',
    'internship_status', 'internship_hospital', 'internship_location',
    'internship_hospital_2', 'internship_location_2',
    'internship_start_date', 'internship_end_date',
    'internship_gap', 'gap_in_months', 'gap_reason',
    'working_status', 'working_hospital_name',
    'additional_info',
]

# Columns that should be coerced to float (storage is TEXT but UI uses
# type=number; we round-trip through float to drop any junk values).
AU_ACADEMIC_NUMERIC_COLUMNS = set()


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
        # Recent-first ordering (created_at desc with id as tiebreaker).
        sql += " ORDER BY a.created_at DESC NULLS LAST, a.id DESC "
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
        pathway_name='AMC Pathway',
        active_ops_page='australia-academic',
        active_pathway='australia',
    )


@admin_required
def ops_australia_academic_detail(rid):
    """Read-only detail view for one Australia academic-details row.

    LEFT JOIN plab_clients so we can show candidate name even though
    ops_academic_details itself doesn't carry it. Pathway-scoped so PLAB
    rows can never load here.
    """
    user = get_user()
    conn = get_db()
    record = conn.execute(
        """SELECT a.*, p.first_name, p.last_name, p.prefix
             FROM ops_academic_details a
             LEFT JOIN plab_clients p
                    ON a.registration_number = p.registration_number
                   AND COALESCE(p.pathway, 'plab') = 'australia'
            WHERE a.id = ?
              AND COALESCE(a.pathway, 'plab') = 'australia' """,
        (rid,),
    ).fetchone()
    conn.close()
    if not record:
        flash('Australia academic record not found.', 'error')
        return redirect(url_for('ops_australia_academic_list'))
    return render_template(
        'ops_australia_academic_detail.html',
        user=user,
        record=record,
        pathway_name='AMC Pathway',
        active_ops_page='australia-academic',
        active_pathway='australia',
    )


@admin_required
def ops_australia_academic_edit_page(rid):
    """GET — render the edit form for one Australia academic-details row."""
    user = get_user()
    conn = get_db()
    record = conn.execute(
        """SELECT a.*, p.first_name, p.last_name, p.prefix
             FROM ops_academic_details a
             LEFT JOIN plab_clients p
                    ON a.registration_number = p.registration_number
                   AND COALESCE(p.pathway, 'plab') = 'australia'
            WHERE a.id = ?
              AND COALESCE(a.pathway, 'plab') = 'australia' """,
        (rid,),
    ).fetchone()
    conn.close()
    if not record:
        flash('Australia academic record not found.', 'error')
        return redirect(url_for('ops_australia_academic_list'))
    return render_template(
        'ops_australia_academic_edit.html',
        user=user,
        record=record,
        pathway_name='AMC Pathway',
        active_ops_page='australia-academic',
        active_pathway='australia',
    )


@admin_required
def ops_australia_academic_edit_save(rid):
    """POST handler: save changes to one Australia academic-details row.

    Strict allowlist (AU_ACADEMIC_EDITABLE_COLUMNS) — anything else in the
    form is silently ignored. Pathway is NEVER updated through this endpoint.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            """SELECT id FROM ops_academic_details
                WHERE id = ? AND COALESCE(pathway, 'plab') = 'australia' """,
            (rid,),
        ).fetchone()
        if not existing:
            flash('Australia academic record not found.', 'error')
            return redirect(url_for('ops_australia_academic_list'))

        sets = []
        params = []
        for col in AU_ACADEMIC_EDITABLE_COLUMNS:
            if col in request.form:
                val = request.form.get(col, '').strip()
                if col in AU_ACADEMIC_NUMERIC_COLUMNS:
                    try:
                        val = float(val) if val else 0
                    except ValueError:
                        val = 0
                sets.append(f"{col} = ?")
                params.append(val)
        if sets:
            params.append(rid)
            conn.execute(
                f"""UPDATE ops_academic_details
                       SET {', '.join(sets)}
                     WHERE id = ?
                       AND COALESCE(pathway, 'plab') = 'australia' """,
                params,
            )
            conn.commit()
            flash('Academic details saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_australia_academic_edit_save: {e}")
        flash(f'Error saving academic details: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_australia_academic_detail', rid=rid))


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/australia/academic-details',
        endpoint='ops_australia_academic_list',
        view_func=ops_australia_academic_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/academic-details/<int:rid>',
        endpoint='ops_australia_academic_detail',
        view_func=ops_australia_academic_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/academic-details/<int:rid>/edit',
        endpoint='ops_australia_academic_edit_page',
        view_func=ops_australia_academic_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/academic-details/<int:rid>/edit',
        endpoint='ops_australia_academic_edit_save',
        view_func=ops_australia_academic_edit_save,
        methods=['POST'],
    )
