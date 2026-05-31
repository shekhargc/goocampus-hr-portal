"""
routes/operations/au_payments.py — Australia Pathway: Payments list.

Surfaces rows from ops_payments WHERE pathway='australia', joined to
plab_clients on registration_number so each row shows the candidate's
human name alongside the payment record.

Endpoint name: ops_australia_payments_list. Sidebar pathway switcher
links to /operations/australia/payments.
"""

import logging
from flask import render_template, flash, request

from core.auth import admin_required
from core.users import get_user
from db import get_db


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
                p.first_name LIKE ? OR p.last_name LIKE ? OR
                t.registration_number LIKE ? OR t.notes LIKE ?
            ) """
            params.extend([f'%{search}%'] * 4)
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
        pathway_name='Australia Pathway',
        active_ops_page='australia-payments',
        active_pathway='australia',
    )


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/australia/payments',
        endpoint='ops_australia_payments_list',
        view_func=ops_australia_payments_list,
        methods=['GET'],
    )
