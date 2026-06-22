"""
routes/operations/au_payments.py — AMC Pathway: Payments list + detail + edit.

Surfaces rows from ops_payments WHERE pathway='australia', joined to
plab_clients on registration_number so each row shows the candidate's
human name alongside the payment record.

Endpoint name: ops_australia_payments_list. Sidebar pathway switcher
links to /operations/australia/payments.

Detail + edit routes mirror the Australia Registration pattern
(ops_australia_client_detail / _edit_page / _edit_save) so the UX is
identical across every Australia section.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
# Pathway-scoped dropdown options for the AMC Payments edit form so the
# Plan Type / Instalment / Payment Method <select>s render the same
# options PLAB uses (sourced from the AMC tab of Field Manager).
from routes.operations._form_lookups import section_payment_lookups


# ── Editable columns on ops_payments (pathway='australia' scope) ──
# id / registration_number / pathway / created_at NEVER editable via UI.
AU_PAYMENTS_EDITABLE_COLUMNS = [
    'payment_date',
    'instalment',
    'total_package',
    'total_amount_paid',
    'amount_paid',
    'gst_paid',
    'payment_method',
    'notes',
]

# Columns coerced to float on save (allowlist of "*_amount", "*_paid",
# "total_package" — the same numeric pattern PLAB uses).
AU_PAYMENTS_NUMERIC_COLUMNS = {
    'amount_paid', 'gst_paid', 'total_amount_paid', 'total_package',
}


@admin_required
def ops_australia_payments_list():
    """Australia payments list — ops_payments WHERE pathway='australia'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    instalment_filter = (request.args.get('instalment', '') or '').strip()
    method_filter = (request.args.get('method', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    instalments = []
    methods = []
    total = 0
    total_amount = 0.0

    try:
        sql = '''SELECT t.id, t.registration_number, t.payment_date,
                        t.amount_paid, t.gst_paid, t.total_amount_paid,
                        t.instalment, t.payment_method, t.total_package,
                        t.notes,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_payments t
                   LEFT JOIN plab_clients p
                          ON t.registration_number = p.registration_number
                         AND COALESCE(p.pathway, 'plab') = 'australia'
                  WHERE t.pathway = 'australia' '''
        params = []
        if reg:
            sql += " AND t.registration_number = ? "
            params.append(reg)
        if instalment_filter:
            sql += " AND t.instalment = ? "
            params.append(instalment_filter)
        if method_filter:
            sql += " AND t.payment_method = ? "
            params.append(method_filter)
        if search:
            sql += """ AND (
                p.first_name ILIKE ? OR p.last_name ILIKE ? OR
                t.registration_number ILIKE ? OR t.notes ILIKE ? OR
                (COALESCE(p.prefix,'')||' '||p.first_name||' '||COALESCE(p.last_name,'')) ILIKE ?
            ) """
            params.extend([f'%{search}%'] * 5)
        # Recent-first (user request 2026-06-01) — mirrors clients_list pattern.
        sql += " ORDER BY t.payment_date DESC NULLS LAST, t.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)
        total_amount = sum(float(r['total_amount_paid'] or 0) for r in records)

        instalments = [
            r['instalment'] for r in conn.execute(
                """SELECT DISTINCT instalment FROM ops_payments
                    WHERE pathway = 'australia' AND instalment IS NOT NULL AND instalment != ''
                    ORDER BY instalment"""
            ).fetchall()
        ]
        methods = [
            r['payment_method'] for r in conn.execute(
                """SELECT DISTINCT payment_method FROM ops_payments
                    WHERE pathway = 'australia' AND payment_method IS NOT NULL AND payment_method != ''
                    ORDER BY payment_method"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_australia_payments_list: {e}")
        flash(f'Error loading Australia payments: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_payments_list.html',
        user=user,
        records=records,
        total=total,
        total_amount=total_amount,
        search=search,
        instalment_filter=instalment_filter,
        method_filter=method_filter,
        client_reg=reg,
        instalments=instalments,
        methods=methods,
        pathway_name='AMC Pathway',
        active_ops_page='australia-payments',
        active_pathway='australia',
    )


@admin_required
def ops_australia_payments_detail(rid):
    """Read-only detail view for a single Australia payment row."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT t.*, p.first_name, p.last_name, p.prefix
                 FROM ops_payments t
            LEFT JOIN plab_clients p
                   ON t.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'australia'
                WHERE t.id = ?
                  AND COALESCE(t.pathway, 'plab') = 'australia' """,
            (rid,),
        ).fetchone()
    finally:
        conn.close()

    if not record:
        flash('Australia payment record not found.', 'error')
        return redirect(url_for('ops_australia_payments_list'))

    return render_template(
        'ops_australia_payments_detail.html',
        user=user,
        record=record,
        pathway_name='AMC Pathway',
        active_ops_page='australia-payments',
        active_pathway='australia',
    )


@admin_required
def ops_australia_payments_edit_page(rid):
    """GET — render the edit form for an Australia payment row."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT t.*, p.first_name, p.last_name, p.prefix
                 FROM ops_payments t
            LEFT JOIN plab_clients p
                   ON t.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'australia'
                WHERE t.id = ?
                  AND COALESCE(t.pathway, 'plab') = 'australia' """,
            (rid,),
        ).fetchone()
    finally:
        conn.close()

    if not record:
        flash('Australia payment record not found.', 'error')
        return redirect(url_for('ops_australia_payments_list'))

    return render_template(
        'ops_australia_payments_edit.html',
        user=user,
        record=record,
        pathway_name='AMC Pathway',
        active_ops_page='australia-payments',
        active_pathway='australia',
        # Dropdown options for Plan Type, Instalment, Payment Method.
        # Sourced from lookup_options where pathway='australia'.
        **section_payment_lookups('australia'),
    )


@admin_required
def ops_australia_payments_edit_save(rid):
    """POST — save edits to an Australia payment row.

    Strict allowlist (AU_PAYMENTS_EDITABLE_COLUMNS) — anything else in the
    form is silently ignored. Pathway and registration_number are NEVER
    updated through this endpoint.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            """SELECT id FROM ops_payments
                WHERE id = ?
                  AND COALESCE(pathway, 'plab') = 'australia' """,
            (rid,),
        ).fetchone()
        if not existing:
            flash('Australia payment record not found.', 'error')
            return redirect(url_for('ops_australia_payments_list'))

        sets = []
        params = []
        for col in AU_PAYMENTS_EDITABLE_COLUMNS:
            if col in request.form:
                val = request.form.get(col, '').strip()
                if col in AU_PAYMENTS_NUMERIC_COLUMNS:
                    try:
                        val = float(val) if val else 0
                    except ValueError:
                        val = 0
                sets.append(f"{col} = ?")
                params.append(val)
        if sets:
            params.append(rid)
            conn.execute(
                f"UPDATE ops_payments SET {', '.join(sets)} "
                f"WHERE id = ? AND COALESCE(pathway, 'plab') = 'australia'",
                params,
            )
            conn.commit()
            flash('Payment details saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_australia_payments_edit_save: {e}")
        flash(f'Error saving payment: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_australia_payments_detail', rid=rid))


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/australia/payments',
        endpoint='ops_australia_payments_list',
        view_func=ops_australia_payments_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/payments/<int:rid>',
        endpoint='ops_australia_payments_detail',
        view_func=ops_australia_payments_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/payments/<int:rid>/edit',
        endpoint='ops_australia_payments_edit_page',
        view_func=ops_australia_payments_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/payments/<int:rid>/edit',
        endpoint='ops_australia_payments_edit_save',
        view_func=ops_australia_payments_edit_save,
        methods=['POST'],
    )
