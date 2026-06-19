"""
routes/operations/pf_payments.py — UAE Pathway: Payments list + detail + edit.

Surfaces rows from ops_payments WHERE pathway='uae', joined to
plab_clients on registration_number so each row shows the candidate's
human name alongside the payment record.

Endpoint name: ops_uae_payments_list. Sidebar pathway switcher
links to /operations/uae/payments.

Detail + edit routes mirror the uae Registration pattern
(ops_uae_clients_list / _edit_page / _edit_save) so the UX is
identical across every uae section.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
# Pathway-scoped dropdown options for the UAE Payments edit form
# (Plan Type / Instalment / Payment Method <select>s).
from routes.operations._form_lookups import section_payment_lookups


# ── Editable columns on ops_payments (pathway='uae' scope) ──
# id / registration_number / pathway / created_at NEVER editable via UI.
PF_PAYMENTS_EDITABLE_COLUMNS = [
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
PF_PAYMENTS_NUMERIC_COLUMNS = {
    'amount_paid', 'gst_paid', 'total_amount_paid', 'total_package',
}


@admin_required
def ops_uae_payments_list():
    """UAE payments list — ops_payments WHERE pathway='uae'."""
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
                         AND COALESCE(p.pathway, 'plab') = 'uae'
                  WHERE t.pathway = 'uae' '''
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
                p.first_name LIKE ? OR p.last_name LIKE ? OR
                t.registration_number LIKE ? OR t.notes LIKE ?
            ) """
            params.extend([f'%{search}%'] * 4)
        # Recent-first (user request 2026-06-01) — mirrors clients_list pattern.
        sql += " ORDER BY t.payment_date DESC NULLS LAST, t.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)
        total_amount = sum(float(r['total_amount_paid'] or 0) for r in records)

        instalments = [
            r['instalment'] for r in conn.execute(
                """SELECT DISTINCT instalment FROM ops_payments
                    WHERE pathway = 'uae' AND instalment IS NOT NULL AND instalment != ''
                    ORDER BY instalment"""
            ).fetchall()
        ]
        methods = [
            r['payment_method'] for r in conn.execute(
                """SELECT DISTINCT payment_method FROM ops_payments
                    WHERE pathway = 'uae' AND payment_method IS NOT NULL AND payment_method != ''
                    ORDER BY payment_method"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_uae_payments_list: {e}")
        flash(f'Error loading UAE payments: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_uae_payments_list.html',
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
        pathway_name='UAE Pathway',
        active_ops_page='uae-payments',
        active_pathway='uae',
    )


@admin_required
def ops_uae_payments_detail(rid):
    """Read-only detail view for a single UAE payment row."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT t.*, p.first_name, p.last_name, p.prefix
                 FROM ops_payments t
            LEFT JOIN plab_clients p
                   ON t.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'uae'
                WHERE t.id = ?
                  AND COALESCE(t.pathway, 'plab') = 'uae' """,
            (rid,),
        ).fetchone()
    finally:
        conn.close()

    if not record:
        flash('UAE payment record not found.', 'error')
        return redirect(url_for('ops_uae_payments_list'))

    return render_template(
        'ops_uae_payments_detail.html',
        user=user,
        record=record,
        pathway_name='UAE Pathway',
        active_ops_page='uae-payments',
        active_pathway='uae',
    )


@admin_required
def ops_uae_payments_edit_page(rid):
    """GET — render the edit form for an UAE payment row."""
    user = get_user()
    conn = get_db()
    try:
        record = conn.execute(
            """SELECT t.*, p.first_name, p.last_name, p.prefix
                 FROM ops_payments t
            LEFT JOIN plab_clients p
                   ON t.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'uae'
                WHERE t.id = ?
                  AND COALESCE(t.pathway, 'plab') = 'uae' """,
            (rid,),
        ).fetchone()
    finally:
        conn.close()

    if not record:
        flash('UAE payment record not found.', 'error')
        return redirect(url_for('ops_uae_payments_list'))

    return render_template(
        'ops_uae_payments_edit.html',
        user=user,
        record=record,
        pathway_name='UAE Pathway',
        active_ops_page='uae-payments',
        active_pathway='uae',
        # Dropdown options sourced from lookup_options where pathway='uae'.
        **section_payment_lookups('uae'),
    )


@admin_required
def ops_uae_payments_edit_save(rid):
    """POST — save edits to an UAE payment row.

    Strict allowlist (PF_PAYMENTS_EDITABLE_COLUMNS) — anything else in the
    form is silently ignored. Pathway and registration_number are NEVER
    updated through this endpoint.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            """SELECT id FROM ops_payments
                WHERE id = ?
                  AND COALESCE(pathway, 'plab') = 'uae' """,
            (rid,),
        ).fetchone()
        if not existing:
            flash('UAE payment record not found.', 'error')
            return redirect(url_for('ops_uae_payments_list'))

        sets = []
        params = []
        for col in PF_PAYMENTS_EDITABLE_COLUMNS:
            if col in request.form:
                val = request.form.get(col, '').strip()
                if col in PF_PAYMENTS_NUMERIC_COLUMNS:
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
                f"WHERE id = ? AND COALESCE(pathway, 'plab') = 'uae'",
                params,
            )
            conn.commit()
            flash('Payment details saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_uae_payments_edit_save: {e}")
        flash(f'Error saving payment: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_uae_payments_detail', rid=rid))


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/uae/payments',
        endpoint='ops_uae_payments_list',
        view_func=ops_uae_payments_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/uae/payments/<int:rid>',
        endpoint='ops_uae_payments_detail',
        view_func=ops_uae_payments_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/uae/payments/<int:rid>/edit',
        endpoint='ops_uae_payments_edit_page',
        view_func=ops_uae_payments_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/uae/payments/<int:rid>/edit',
        endpoint='ops_uae_payments_edit_save',
        view_func=ops_uae_payments_edit_save,
        methods=['POST'],
    )
