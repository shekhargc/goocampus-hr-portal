"""
routes/verification_queues.py — unified Sales / Ops verification queues.

Two role-based views, each with two tabs (New Registration | Internal Transfer),
that surface the EXISTING two completion flows into one place per role:

  Sales Team Verification  -> "Fill Details"  (things I/my-team must complete)
  Ops Team Verification    -> "Fill Details" (when I am the requester) + "Verify"

New-registration flow already exists on client_registrations:
  form_status='submitted' -> sales_completed=1 (admin_client_sales_complete)
  -> ops_status='verified' + onboarding email/notify (admin_client_ops_verify).
Internal-transfer flow already exists on internal_transfers.completion_stage:
  awaiting_sales -> awaiting_ops -> completed (routes/internal_transfers_completion).

This module ONLY reads + groups; the actual fill/verify actions stay on their
existing routes (we just link to them). Registered from app.py.
"""

import logging

from flask import render_template, request, redirect, url_for, flash, session

from core.auth import login_required
from core.users import get_user
from db import get_db


# Destination pathway -> its existing client edit-form endpoint (sales fills the
# blank service/financial fields there). Mirrors internal_transfers_completion.
PATHWAY_EDIT_ENDPOINT = {
    'plab':       'ops_plab_edit',
    'australia':  'ops_australia_client_edit_page',
    'consulting': 'ops_consulting_client_edit_page',
    'portfolio':  'ops_portfolio_client_edit_page',
    'training':   'ops_training_client_edit_page',
    'uae':        'ops_uae_client_edit_page',
}


def _can_fill(user):
    from app import has_section_permission
    return bool(session.get('is_admin') or
                (user and has_section_permission(user, 'clients', 'internal_transfers', 'add')))


def _can_verify(user):
    from app import has_section_permission
    return bool(session.get('is_admin') or
                (user and has_section_permission(user, 'clients', 'internal_transfers', 'edit')))


def _name(prefix, first, last):
    return (f"{prefix or ''} {first or ''} {last or ''}").strip() or '(no name)'


def _transfer_edit_url(pathway, client_id):
    ep = PATHWAY_EDIT_ENDPOINT.get((pathway or 'plab'))
    if not ep or not client_id:
        return None
    try:
        return url_for(ep, client_id=client_id)
    except Exception:
        return None


# ── data helpers ────────────────────────────────────────────────────────────

def _newreg_rows(conn, stage):
    """stage: 'fill' = submitted & not sales-completed; 'verify' = sales-completed
    & not ops-verified."""
    if stage == 'fill':
        where = "cr.form_status = 'submitted' AND COALESCE(cr.sales_completed,0) = 0"
        order = "cr.client_submitted_at"
    else:
        where = "COALESCE(cr.sales_completed,0) = 1 AND COALESCE(cr.ops_status,'') <> 'verified'"
        order = "cr.sales_completed_at"
    rows = conn.execute(f"""
        SELECT cr.id, cr.registration_number, cr.prefix, cr.first_name, cr.last_name,
               cr.counsellor_id, cr.counsellor_name, cr.client_submitted_at,
               cr.sales_completed_at, ps.name AS product_name
          FROM client_registrations cr
          LEFT JOIN products_services ps ON ps.id = cr.product_id
         WHERE {where}
         ORDER BY {order} DESC NULLS LAST, cr.id DESC
    """).fetchall()
    out = []
    for r in rows:
        out.append({
            'id': r['id'], 'reg': r['registration_number'] or '—',
            'name': _name(r['prefix'], r['first_name'], r['last_name']),
            'product': r['product_name'] or '',
            'counsellor_id': r['counsellor_id'], 'counsellor': r['counsellor_name'] or '',
            'when': r['client_submitted_at'] if stage == 'fill' else r['sales_completed_at'],
            'action_url': url_for('admin_client_detail', reg_id=r['id']),
        })
    return out


def _transfer_rows(conn, stage):
    """stage in ('awaiting_sales','awaiting_ops')."""
    rows = conn.execute("""
        SELECT it.id, it.from_reg, it.to_reg, it.to_pathway, it.to_product,
               it.created_by, it.transfer_date, it.amount_transferred,
               pc.id AS client_id,
               TRIM(COALESCE(pc.prefix,'') || ' ' || COALESCE(pc.first_name,'') || ' ' ||
                    COALESCE(pc.last_name,'')) AS client_name
          FROM internal_transfers it
          LEFT JOIN plab_clients pc ON pc.registration_number = it.to_reg
         WHERE it.status = 'approved' AND it.to_reg IS NOT NULL
           AND COALESCE(it.completion_stage,'awaiting_sales') = ?
         ORDER BY it.id DESC
    """, (stage,)).fetchall()
    out = []
    for r in rows:
        out.append({
            'id': r['id'], 'from_reg': r['from_reg'], 'reg': r['to_reg'],
            'name': (r['client_name'] or '').strip() or '(record not found)',
            'pathway': r['to_pathway'] or 'plab', 'product': r['to_product'] or '',
            'requested_by': r['created_by'],
            'amount': float(r['amount_transferred'] or 0),
            'when': r['transfer_date'] or '',
            'action_url': _transfer_edit_url(r['to_pathway'], r['client_id']),
        })
    return out


def _emp_names(conn):
    return {e['id']: (e['name'] or '') for e in conn.execute("SELECT id, name FROM employees").fetchall()}


# ── views ───────────────────────────────────────────────────────────────────

@login_required
def verification_sales():
    """Sales Team Verification — FILL DETAILS, two tabs.
    New Reg: registrations submitted by the client, awaiting the sales section.
    Internal Transfer: transfers I requested that are awaiting the balance fill."""
    user = get_user()
    if not (_can_fill(user) or _can_verify(user)):
        flash('You do not have access to the verification queue.', 'error')
        return redirect('/')
    uid = session.get('user_id')
    conn = get_db()
    newreg = _newreg_rows(conn, 'fill')
    transfers = [t for t in _transfer_rows(conn, 'awaiting_sales')
                 if (t['requested_by'] == uid) or session.get('is_admin')]
    names = _emp_names(conn)
    conn.close()
    for t in transfers:
        t['requested_by_name'] = names.get(t['requested_by'], '')
    return render_template('verification_queue.html',
        base_template='focus_base.html', active_section='clients',
        view='sales', title='Sales Team Verification', mode='fill',
        newreg=newreg, transfers=transfers, can_verify=_can_verify(user))


@login_required
def verification_ops():
    """Ops Team Verification — two tabs, each with (optional) Fill section for
    transfers I requested + the Verify section ops acts on."""
    user = get_user()
    if not _can_verify(user):
        flash('Only ops/admin can open the ops verification queue.', 'error')
        return redirect(url_for('verification_sales') if _can_fill(user) else '/')
    uid = session.get('user_id')
    conn = get_db()
    newreg_verify = _newreg_rows(conn, 'verify')
    transfer_verify = _transfer_rows(conn, 'awaiting_ops')
    # ops can also be the requester -> their own fill tasks show here too
    transfer_fill_mine = [t for t in _transfer_rows(conn, 'awaiting_sales')
                          if (t['requested_by'] == uid) or session.get('is_admin')]
    names = _emp_names(conn)
    conn.close()
    for lst in (transfer_verify, transfer_fill_mine):
        for t in lst:
            t['requested_by_name'] = names.get(t['requested_by'], '')
    return render_template('verification_queue.html',
        base_template='focus_base.html', active_section='clients',
        view='ops', title='Ops Team Verification', mode='verify',
        newreg=newreg_verify, transfers=transfer_verify,
        transfer_fill_mine=transfer_fill_mine, can_verify=True)


def register_verification_queues(app):
    app.add_url_rule('/verifications/sales', endpoint='verification_sales',
                     view_func=verification_sales, methods=['GET'])
    app.add_url_rule('/verifications/ops', endpoint='verification_ops',
                     view_func=verification_ops, methods=['GET'])
