"""
routes/internal_transfers_completion.py — Internal Transfer, Phase 2.

The completion hand-off that runs AFTER an admin approves a transfer. Approval
(_execute_internal_transfer in app.py) creates a new pathway record in
'Pending Verification' with blank service/financial fields and stamps the
transfer row completion_stage='awaiting_sales'. This module drives the queue
that moves it the rest of the way:

    awaiting_sales  -> sales fills the balance/pathway fields (on the existing
                       per-pathway edit form) and submits for verification
    awaiting_ops    -> ops reviews and verifies -> record goes 'In Process' (live)
    completed       -> done; record is live

One shared, pathway-agnostic set of routes keyed by transfer id, so a single
queue + three actions serve all six pathways (PLAB / Australia / Consulting /
Portfolio / UAE / Training).

Registered from app.py via register_internal_transfer_completion(app) (plain
add_url_rule, matching routes/operations/, so endpoint names stay stable).
"""

import logging

from flask import render_template, request, redirect, url_for, flash, session

from core.auth import login_required
from core.users import get_user
from db import get_db


# Destination pathway -> the edit-form endpoint where sales fills the blank
# service/financial fields. All take client_id. PLAB still lives in app.py.
PATHWAY_EDIT_ENDPOINT = {
    'plab':       'ops_plab_edit',
    'australia':  'ops_australia_client_edit_page',
    'consulting': 'ops_consulting_client_edit_page',
    'portfolio':  'ops_portfolio_client_edit_page',
    'training':   'ops_training_client_edit_page',
    'uae':        'ops_uae_client_edit_page',
}


def _can_fill(user):
    """Sales step: raise/fill a transfer. Admin, or Clients > Internal
    Transfers > Add (same grant that lets them REQUEST one in phase 1)."""
    from app import has_section_permission
    return bool(session.get('is_admin') or
                (user and has_section_permission(user, 'clients', 'internal_transfers', 'add')))


def _can_verify(user):
    """Ops step: verify a filled transfer and take it live. Admin, or
    Clients > Internal Transfers > Edit (the same grant that approves)."""
    from app import has_section_permission
    return bool(session.get('is_admin') or
                (user and has_section_permission(user, 'clients', 'internal_transfers', 'edit')))


def _edit_url_for(pathway, client_id):
    """Edit-form URL for a transferred client, or None if unresolvable."""
    ep = PATHWAY_EDIT_ENDPOINT.get((pathway or 'plab'))
    if not ep or not client_id:
        return None
    try:
        return url_for(ep, client_id=client_id)
    except Exception:
        return None


@login_required
def internal_transfer_completion_queue():
    """The 'internal transfer view': approved transfers grouped by hand-off
    stage, plus the requester's own tracking list."""
    user = get_user()
    if not (_can_fill(user) or _can_verify(user)):
        flash('You do not have access to the internal-transfer queue.', 'error')
        return redirect(url_for('operations_dashboard') if _has_endpoint('operations_dashboard') else '/')

    uid = session.get('user_id')
    conn = get_db()
    rows = conn.execute("""
        SELECT it.id, it.from_reg, it.to_reg, it.to_pathway, it.to_product, it.created_by,
               it.completion_stage, it.amount_transferred, it.transfer_date,
               it.sales_submitted_at, it.ops_verified_at,
               pc.id AS client_id, pc.account_status,
               TRIM(COALESCE(pc.prefix,'') || ' ' || COALESCE(pc.first_name,'') || ' ' ||
                    COALESCE(pc.last_name,'')) AS client_name
          FROM internal_transfers it
          LEFT JOIN plab_clients pc ON pc.registration_number = it.to_reg
         WHERE it.status = 'approved' AND it.to_reg IS NOT NULL
         ORDER BY it.id DESC
    """).fetchall()
    # requester display names
    who = {r['id']: (r['name'] or '')
           for r in conn.execute("SELECT id, name FROM employees").fetchall()}
    conn.close()

    awaiting_sales, awaiting_ops, completed, mine = [], [], [], []
    for r in rows:
        stage = r['completion_stage'] or 'awaiting_sales'
        item = {
            'id': r['id'], 'from_reg': r['from_reg'], 'to_reg': r['to_reg'],
            'pathway': r['to_pathway'] or 'plab', 'product': r['to_product'] or '',
            'client_name': r['client_name'] or '(record not found)',
            'account_status': r['account_status'] or '',
            'amount_transferred': float(r['amount_transferred'] or 0),
            'transfer_date': r['transfer_date'] or '',
            'stage': stage,
            'requested_by': who.get(r['created_by'], ''),
            'edit_url': _edit_url_for(r['to_pathway'], r['client_id']),
            'sales_submitted_at': r['sales_submitted_at'],
            'ops_verified_at': r['ops_verified_at'],
        }
        if stage == 'awaiting_sales':
            awaiting_sales.append(item)
        elif stage == 'awaiting_ops':
            awaiting_ops.append(item)
        elif stage == 'completed':
            completed.append(item)
        if r['created_by'] == uid:
            mine.append(item)

    return render_template('internal_transfer_completion.html',
        base_template='focus_base.html', active_section='clients',
        awaiting_sales=awaiting_sales, awaiting_ops=awaiting_ops,
        completed=completed, mine=mine,
        can_fill=_can_fill(user), can_verify=_can_verify(user))


def _load_transfer(conn, tid):
    return conn.execute("SELECT * FROM internal_transfers WHERE id = ?", (tid,)).fetchone()


def _safe_next(default_endpoint='internal_transfer_completion_queue'):
    nxt = (request.form.get('next') or '').strip()
    if nxt.startswith('/'):
        return nxt
    return url_for(default_endpoint)


@login_required
def internal_transfer_submit_for_ops(tid):
    """Sales action: the blank fields are filled, hand off to ops."""
    user = get_user()
    if not _can_fill(user):
        flash('You do not have permission to submit transfers for verification.', 'error')
        return redirect(url_for('internal_transfer_completion_queue'))
    conn = get_db()
    try:
        t = _load_transfer(conn, tid)
        if not t or t['status'] != 'approved':
            conn.close()
            flash('That transfer is not ready for submission.', 'error')
            return redirect(url_for('internal_transfer_completion_queue'))
        stage = t['completion_stage'] or 'awaiting_sales'
        if stage != 'awaiting_sales':
            conn.close()
            flash('That transfer has already been submitted.', 'info')
            return redirect(_safe_next())
        # Guard: the destination record must actually have its balance/pathway
        # fields filled before ops is asked to verify.
        pc = conn.execute("SELECT id, product_id, final_package, package_amount FROM plab_clients WHERE registration_number = ? LIMIT 1",
                          (t['to_reg'],)).fetchone()
        if not pc:
            conn.close()
            flash('The transferred client record could not be found.', 'error')
            return redirect(url_for('internal_transfer_completion_queue'))
        has_product = pc['product_id'] is not None
        has_amount = float(pc['final_package'] or 0) > 0 or float(pc['package_amount'] or 0) > 0
        if not (has_product and has_amount):
            conn.close()
            flash('Please fill the Product and Package/Final amount on the client before submitting for verification.', 'error')
            return redirect(_safe_next())
        conn.execute("""UPDATE internal_transfers
            SET completion_stage = 'awaiting_ops', sales_submitted_by = ?, sales_submitted_at = CURRENT_TIMESTAMP
            WHERE id = ?""", (session.get('user_id'), tid))
        # Notify admins (who verify/approve) that a transfer is ready to verify.
        from app import create_notification
        for a in conn.execute("SELECT id FROM employees WHERE is_admin = 1 AND is_active = 1", []).fetchall():
            create_notification(conn, a['id'], 'Internal transfer ready to verify',
                f'{t["to_reg"]} ({t["to_product"] or ""}) — sales completed the details. Needs ops verification to go live.',
                'info', url_for('internal_transfer_completion_queue'))
        conn.commit()
        conn.close()
        flash('Submitted for ops verification. The client goes live once verified.', 'success')
    except Exception as e:
        logging.error(f"internal_transfer_submit_for_ops: {e}")
        try: conn.rollback()
        except Exception: pass
        try: conn.close()
        except Exception: pass
        flash(f'Could not submit: {e}', 'error')
    return redirect(_safe_next())


@login_required
def internal_transfer_verify(tid):
    """Ops action: verify a submitted transfer and take the record live."""
    user = get_user()
    if not _can_verify(user):
        flash('Only ops/admin can verify internal transfers.', 'error')
        return redirect(url_for('internal_transfer_completion_queue'))
    conn = get_db()
    try:
        t = _load_transfer(conn, tid)
        if not t or t['status'] != 'approved' or (t['completion_stage'] or '') != 'awaiting_ops':
            conn.close()
            flash('That transfer is not awaiting verification.', 'error')
            return redirect(url_for('internal_transfer_completion_queue'))
        conn.execute("UPDATE plab_clients SET account_status = 'In Process', updated_at = CURRENT_TIMESTAMP WHERE registration_number = ?",
                     (t['to_reg'],))
        conn.execute("""UPDATE internal_transfers
            SET completion_stage = 'completed', ops_verified_by = ?, ops_verified_at = CURRENT_TIMESTAMP
            WHERE id = ?""", (session.get('user_id'), tid))
        from app import create_notification
        if t['created_by']:
            create_notification(conn, t['created_by'], 'Internal transfer verified & live',
                f'{t["to_reg"]} ({t["to_product"] or ""}) was verified by ops and is now live (In Process).',
                'success', url_for('internal_transfer_completion_queue'))
        conn.commit()
        conn.close()
        flash(f'Verified: {t["to_reg"]} is now live (In Process).', 'success')
    except Exception as e:
        logging.error(f"internal_transfer_verify: {e}")
        try: conn.rollback()
        except Exception: pass
        try: conn.close()
        except Exception: pass
        flash(f'Verification failed: {e}', 'error')
    return redirect(_safe_next())


@login_required
def internal_transfer_return_to_sales(tid):
    """Ops action: send a submitted transfer back to sales with a note."""
    user = get_user()
    if not _can_verify(user):
        flash('Only ops/admin can return internal transfers.', 'error')
        return redirect(url_for('internal_transfer_completion_queue'))
    note = (request.form.get('note') or '').strip()
    conn = get_db()
    try:
        t = _load_transfer(conn, tid)
        if not t or t['status'] != 'approved' or (t['completion_stage'] or '') != 'awaiting_ops':
            conn.close()
            flash('That transfer is not awaiting verification.', 'error')
            return redirect(url_for('internal_transfer_completion_queue'))
        conn.execute("UPDATE internal_transfers SET completion_stage = 'awaiting_sales' WHERE id = ?", (tid,))
        from app import create_notification
        if t['created_by']:
            msg = f'{t["to_reg"]} ({t["to_product"] or ""}) was returned by ops for changes.'
            if note:
                msg += f' Note: {note}'
            create_notification(conn, t['created_by'], 'Internal transfer returned for changes',
                msg, 'warning', url_for('internal_transfer_completion_queue'))
        conn.commit()
        conn.close()
        flash('Returned to sales for changes.', 'success')
    except Exception as e:
        logging.error(f"internal_transfer_return_to_sales: {e}")
        try: conn.rollback()
        except Exception: pass
        try: conn.close()
        except Exception: pass
        flash(f'Could not return transfer: {e}', 'error')
    return redirect(url_for('internal_transfer_completion_queue'))


def _has_endpoint(name):
    from flask import current_app
    return name in current_app.view_functions


def register_internal_transfer_completion(app):
    app.add_url_rule('/internal-transfers/completion',
                     endpoint='internal_transfer_completion_queue',
                     view_func=internal_transfer_completion_queue, methods=['GET'])
    app.add_url_rule('/internal-transfers/<int:tid>/submit-for-ops',
                     endpoint='internal_transfer_submit_for_ops',
                     view_func=internal_transfer_submit_for_ops, methods=['POST'])
    app.add_url_rule('/internal-transfers/<int:tid>/verify',
                     endpoint='internal_transfer_verify',
                     view_func=internal_transfer_verify, methods=['POST'])
    app.add_url_rule('/internal-transfers/<int:tid>/return-to-sales',
                     endpoint='internal_transfer_return_to_sales',
                     view_func=internal_transfer_return_to_sales, methods=['POST'])
