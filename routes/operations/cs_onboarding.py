"""
routes/operations/cs_onboarding.py — Operations: Standard Consulting
onboarding (list / detail / update / send-welcome-email).

S-1a. Mirror of the AMC onboarding handlers (ops_au_onboarding_*) in
app.py, but filtered to pathway='consulting'. Uses the same
client_onboarding + client_welcome_kit tables -- so onboarding state
flows through the same C-G features (D timeline, E emails, F
scheduler, G slot picker) the moment a consulting client lands.

Endpoints registered:
    GET  /operations/consulting/onboarding
    GET  /operations/consulting/onboarding/<int:client_id>
    POST /operations/consulting/onboarding/<int:client_id>/update
    POST /operations/consulting/onboarding/<int:client_id>/send-welcome-email
"""

import logging
import re
from flask import render_template, flash, request, redirect, url_for, session

from core.auth import admin_required
from core.users import get_user
from db import get_db


@admin_required
def ops_consulting_onboarding_list():
    """Standard Consulting onboarding list (kanban + table).
    Filtered to pathway='consulting' on plab_clients."""
    conn = get_db()
    status_filter = request.args.get('status', '')
    search_raw = (request.args.get('search') or '').strip()
    search = search_raw.lower()
    page = int(request.args.get('page', 1) or 1)
    per_page = 50

    # Board columns (founder 2026-08-11): each client sits in the ONBOARDING
    # STAGE it is actually in — a progression, not a done/not-done checklist.
    #   Verification Pending → sales OR ops verification not yet done
    #   Email Sent           → verified + welcome email sent, call not arranged
    #   Welcome Call Pending → welcome-call stage: call scheduled but not done
    #   Welcome Call On Hold → welcome call put on hold (shows here even if the
    #                          rest of onboarding is done — must match the profile)
    #   Completed            → welcome call DONE = onboarded (NOT gated on
    #                          agreement/refund — that wrongly parked completed
    #                          clients in Email Sent)
    #   OLD Zoho-imported clients (no portal registration) → 'Completed'
    #     (they never went through the portal onboarding flow → assume done).
    STATUSES = ['Verification Pending', 'Email Sent', 'Welcome Call Pending',
                'Welcome Call On Hold', 'Completed']

    try:
        from routes.operations.australia import _yn_flag
    except Exception:
        def _yn_flag(v):
            return str(v or '').strip().lower() in (
                'yes', 'y', 'done', '1', 'true', 'completed', 'signed', 'given')

    def _norm(s):
        return (s or '').strip().upper()

    clients = [dict(r) for r in conn.execute(
        "SELECT p.id, p.registration_number, p.first_name, p.last_name, p.prefix, "
        "       p.email, p.mobile, p.plan_type, p.current_stage, p.account_status, "
        "       p.registration_date, p.welcome_mail, p.service_agreement, "
        "       p.refund_policy, p.contract_path, "
        "       o.welcome_email_sent, o.welcome_email_sent_at, o.welcome_call_date, "
        "       o.welcome_call_by, o.welcome_call_confirmed, o.welcome_kit_sent_date, "
        "       o.id AS onboarding_id "
        "  FROM plab_clients p "
        "  LEFT JOIN client_onboarding o ON o.client_id = p.id "
        " WHERE COALESCE(p.pathway, 'plab') = 'consulting'").fetchall()]

    # Portal registrations (the "new client" anchor + welcome-call status), by reg no.
    regmap = {}
    try:
        for r in conn.execute(
            "SELECT UPPER(TRIM(registration_number)) AS rn, account_id, "
            "       COALESCE(sales_completed,0) AS sales_done, COALESCE(ops_status,'') AS ops_status, "
            "       COALESCE(welcome_call_hold,0) AS hold, COALESCE(wc_confirmed,0) AS confirmed, "
            "       COALESCE(wc_status,'') AS wc_status, wc_scheduled_date, wc_proposed_date, "
            "       wc_pref_date, wc_confirmed_at "
            "  FROM client_registrations WHERE client_submitted_at IS NOT NULL "
            " ORDER BY id ASC").fetchall():
            if r['rn']:
                regmap[r['rn']] = dict(r)   # latest submitted registration wins
    except Exception as e:
        logging.warning(f"cs onboarding regmap: {e}")
        try: conn.rollback()
        except Exception: pass

    def _derive(c):
        rn = _norm(c.get('registration_number'))
        reg = regmap.get(rn)
        if not reg:
            return 'Completed'          # legacy Zoho client → assume onboarding done
        # Verification gate: sales AND ops verification done. A client whose
        # master account already has a status is by definition past verification
        # (guards against a registration row whose ops_status wasn't stamped).
        verified = ((bool(reg.get('sales_done')) and reg.get('ops_status') == 'verified')
                    or bool((c.get('account_status') or '').strip()))
        if not verified:
            return 'Verification Pending'
        st = (reg.get('wc_status') or '').strip().lower()
        # Welcome-call flow — client_registrations is the source of truth.
        # Hold shows even if the rest of onboarding is done (founder: must match
        # what the profile shows inside).
        if reg.get('hold'):
            return 'Welcome Call On Hold'
        call_done = (bool(reg.get('confirmed')) or st in ('confirmed', 'completed', 'done')
                     or bool(c.get('welcome_call_confirmed')))
        if call_done:
            return 'Completed'          # welcome call done = onboarded
        call_scheduled = (bool(reg.get('wc_scheduled_date')) or bool(reg.get('wc_proposed_date'))
                          or bool(reg.get('wc_pref_date'))
                          or st in ('scheduled', 'proposed', 'requested'))
        if call_scheduled:
            return 'Welcome Call Pending'
        # Verified, welcome email auto-sent on ops-verify, call not arranged yet.
        return 'Email Sent'

    for c in clients:
        c['onboarding_status'] = _derive(c)
        if not c.get('welcome_call_date'):
            reg = regmap.get(_norm(c.get('registration_number')))
            if reg:
                c['welcome_call_date'] = reg.get('wc_confirmed_at') or reg.get('wc_scheduled_date') or None

    def _regnum(c):
        d = re.sub(r'[^0-9]', '', c.get('registration_number') or '')
        return int(d) if d else -1
    clients.sort(key=lambda c: (_regnum(c), c.get('id') or 0), reverse=True)

    if search:
        clients = [c for c in clients if search in ' '.join([
            str(c.get('first_name') or ''), str(c.get('last_name') or ''),
            str(c.get('registration_number') or ''), str(c.get('email') or ''),
            str(c.get('prefix') or '')]).lower()]

    # Counts over the search-filtered set, before the status filter.
    kanban_counts = {st: 0 for st in STATUSES}
    for c in clients:
        kanban_counts[c['onboarding_status']] = kanban_counts.get(c['onboarding_status'], 0) + 1

    if status_filter:
        clients = [c for c in clients if c['onboarding_status'] == status_filter]

    total = len(clients)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, page), total_pages)
    kanban_clients = clients
    table_clients = clients[(page - 1) * per_page: page * per_page]
    conn.close()

    return render_template(
        'ops_consulting_onboarding.html',
        clients=table_clients, kanban_clients=kanban_clients,
        page=page, total_pages=total_pages, total=total,
        status_filter=status_filter, search=search_raw,
        kanban_counts=kanban_counts, board_statuses=STATUSES,
        active_ops_page='consulting-onboarding',
        active_pathway='consulting',
        active_section='operations',
    )


@admin_required
def ops_consulting_onboarding_detail(client_id):
    """Standard Consulting per-client onboarding detail.
    Routes through the same _ensure_client_onboarding helper as AMC."""
    # Import the helper lazily so we don't create a circular import
    # at module load -- the helper still lives in app.py.
    from app import _ensure_client_onboarding

    conn = get_db()
    client = conn.execute(
        "SELECT * FROM plab_clients WHERE id = ? AND COALESCE(pathway, 'plab') = 'consulting'",
        (client_id,),
    ).fetchone()
    if not client:
        conn.close()
        flash('Consulting client not found.', 'error')
        return redirect(url_for('ops_consulting_onboarding_list'))

    onb = _ensure_client_onboarding(conn, client_id, client['registration_number'])
    # Welcome kit items: read from client_welcome_kit (the unified table)
    # joined to welcome_kit_items for the canonical names.
    kit_items = conn.execute(
        """SELECT cwk.id, cwk.kit_item_id, cwk.status, cwk.sent_date,
                  cwk.notes, COALESCE(wki.item_name, cwk.item_name) AS item_name,
                  COALESCE(wki.item_type, cwk.item_type) AS item_type
             FROM client_welcome_kit cwk
        LEFT JOIN welcome_kit_items wki ON wki.id = cwk.kit_item_id
            WHERE cwk.client_id = ?
         ORDER BY wki.sort_order NULLS LAST, cwk.id""",
        (client_id,),
    ).fetchall()
    # Welcome kit template items for any not-yet-instantiated rows.
    consulting_prod = conn.execute(
        "SELECT id FROM products_services WHERE pathway = 'consulting' "
        " ORDER BY id LIMIT 1"
    ).fetchone()
    kit_template = []
    if consulting_prod:
        kit_template = conn.execute(
            "SELECT id, item_name, item_type FROM welcome_kit_items "
            " WHERE product_id = ? AND is_active = 1 "
            " ORDER BY sort_order NULLS LAST, id",
            (consulting_prod['id'],),
        ).fetchall()
    email_tpl = conn.execute(
        "SELECT * FROM email_templates WHERE template_key = 'welcome_email'"
    ).fetchone()

    # Real welcome-call status from client_registrations (the source of truth
    # that drives the board) so this page matches the board — e.g. an On Hold
    # call must read On Hold here too, not "done" from the manual table.
    wc_real = {'state': '', 'label': '', 'note': ''}
    try:
        rr = conn.execute(
            "SELECT COALESCE(welcome_call_hold,0) AS hold, wc_hold_note, "
            "       COALESCE(wc_confirmed,0) AS confirmed, COALESCE(wc_status,'') AS wc_status, "
            "       wc_scheduled_date, wc_proposed_date, wc_pref_date "
            "  FROM client_registrations "
            " WHERE UPPER(TRIM(registration_number)) = ? AND client_submitted_at IS NOT NULL "
            " ORDER BY id DESC LIMIT 1",
            ((client['registration_number'] or '').strip().upper(),)).fetchone()
        if rr:
            st = (rr['wc_status'] or '').strip().lower()
            if rr['hold']:
                wc_real = {'state': 'hold', 'label': 'On Hold', 'note': rr['wc_hold_note'] or ''}
            elif rr['confirmed'] or st in ('confirmed', 'completed', 'done'):
                wc_real = {'state': 'done', 'label': 'Done', 'note': ''}
            elif rr['wc_scheduled_date'] or rr['wc_proposed_date'] or rr['wc_pref_date'] or st in ('scheduled', 'proposed', 'requested'):
                wc_real = {'state': 'scheduled', 'label': 'Scheduled', 'note': ''}
            else:
                wc_real = {'state': 'pending', 'label': 'Pending', 'note': ''}
    except Exception:
        try: conn.rollback()
        except Exception: pass
    conn.close()

    return render_template(
        'ops_consulting_onboarding_detail.html',
        client=client, onboarding=onb, wc_real=wc_real,
        kit_items=kit_items, kit_template=kit_template,
        email_template=email_tpl,
        active_ops_page='consulting-onboarding',
        active_pathway='consulting',
        active_section='operations',
    )


@admin_required
def ops_consulting_onboarding_update(client_id):
    """Save handler for the consulting onboarding detail form."""
    from app import _ensure_client_onboarding, _maybe_fire_stage_transitions

    user = get_user()
    conn = get_db()
    client = conn.execute(
        "SELECT * FROM plab_clients WHERE id = ? AND COALESCE(pathway, 'plab') = 'consulting'",
        (client_id,),
    ).fetchone()
    if not client:
        conn.close()
        flash('Consulting client not found.', 'error')
        return redirect(url_for('ops_consulting_onboarding_list'))
    onb = _ensure_client_onboarding(conn, client_id, client['registration_number'])
    _e3_old_state = dict(onb) if onb else {}
    f = request.form
    conn.execute(
        """UPDATE client_onboarding SET
              welcome_call_date = ?, welcome_call_by = ?,
              welcome_call_confirmed = ?, welcome_call_notes = ?,
              welcome_kit_method = ?, welcome_kit_sent_date = ?,
              updated_at = CURRENT_TIMESTAMP
            WHERE id = ?""",
        (
            f.get('welcome_call_date', ''), f.get('welcome_call_by', ''),
            1 if f.get('welcome_call_confirmed') else 0,
            f.get('welcome_call_notes', ''),
            f.get('welcome_kit_method', ''), f.get('welcome_kit_sent_date', ''),
            onb['id'],
        ),
    )

    # Per-item kit checklist -- stored in client_welcome_kit per S-1a
    # (same shape as PLAB / AMC).
    consulting_prod = conn.execute(
        "SELECT id FROM products_services WHERE pathway = 'consulting' "
        " ORDER BY id LIMIT 1"
    ).fetchone()
    if consulting_prod:
        items = conn.execute(
            "SELECT id, item_name, item_type FROM welcome_kit_items "
            " WHERE product_id = ? AND is_active = 1",
            (consulting_prod['id'],),
        ).fetchall()
        for it in items:
            included = bool(f.get(f"kit_included_{it['id']}"))
            sent_date = (f.get(f"kit_sent_date_{it['id']}") or '').strip()
            notes = (f.get(f"kit_notes_{it['id']}") or '').strip()
            row = conn.execute(
                "SELECT id FROM client_welcome_kit "
                " WHERE client_id = ? AND kit_item_id = ?",
                (client_id, it['id']),
            ).fetchone()
            if included or sent_date:
                if row:
                    conn.execute(
                        "UPDATE client_welcome_kit SET "
                        " status = 'done', sent_date = ?, notes = ?, "
                        " completed_by = ?, "
                        " completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP) "
                        " WHERE id = ?",
                        (sent_date, notes, user['id'] if user else None, row['id']),
                    )
                else:
                    try:
                        conn.execute(
                            "INSERT INTO client_welcome_kit "
                            "(client_id, kit_item_id, item_name, item_type, "
                            " status, sent_date, notes, completed_by, completed_at) "
                            "VALUES (?, ?, ?, ?, 'done', ?, ?, ?, CURRENT_TIMESTAMP)",
                            (client_id, it['id'], it['item_name'], it['item_type'],
                             sent_date, notes, user['id'] if user else None),
                        )
                    except Exception as e:
                        logging.warning(f"consulting onb update insert cwk: {e}")
                        try: conn.rollback()
                        except Exception: pass
            elif row:
                conn.execute(
                    "UPDATE client_welcome_kit SET "
                    " status = 'pending', sent_date = NULL, "
                    " completed_by = NULL, completed_at = NULL, notes = ? "
                    " WHERE id = ?",
                    (notes, row['id']),
                )

    # Re-compute simple onboarding status from filled-ness of key items.
    fresh = dict(conn.execute(
        "SELECT * FROM client_onboarding WHERE id = ?", (onb['id'],)
    ).fetchone())
    status = 'Pending'
    if fresh.get('welcome_email_sent'):
        status = 'Email Sent'
    if fresh.get('welcome_call_confirmed'):
        status = 'Call Done'
    if fresh.get('welcome_kit_sent_date') or fresh.get('welcome_kit_method'):
        status = 'Kit Dispatched'
    if (fresh.get('welcome_kit_sent_date') and fresh.get('welcome_call_confirmed')
            and fresh.get('welcome_email_sent')):
        status = 'Completed'
    conn.execute(
        "UPDATE client_onboarding SET onboarding_status = ? WHERE id = ?",
        (status, onb['id']),
    )
    _e3_new_state = dict(conn.execute(
        "SELECT * FROM client_onboarding WHERE id = ?", (onb['id'],)
    ).fetchone() or {})
    conn.commit()
    _maybe_fire_stage_transitions(conn, client_id, _e3_old_state, _e3_new_state)
    conn.close()
    flash('Consulting onboarding updated.', 'success')
    return redirect(url_for('ops_consulting_onboarding_detail', client_id=client_id))


@admin_required
def ops_consulting_onboarding_send_welcome_email(client_id):
    """Mirror of ops_au_onboarding_send_welcome_email for the
    consulting pathway. Routes through the E-2 stage-email helper."""
    from app import (
        _ensure_client_onboarding,
        _stage_email_context_from_client,
        _send_stage_email,
    )

    conn = get_db()
    client = conn.execute(
        "SELECT * FROM plab_clients WHERE id = ? AND COALESCE(pathway,'plab')='consulting'",
        (client_id,),
    ).fetchone()
    if not client:
        conn.close()
        flash('Consulting client not found.', 'error')
        return redirect(url_for('ops_consulting_onboarding_list'))
    if not client['email']:
        conn.close()
        flash('Client has no email address.', 'error')
        return redirect(url_for('ops_consulting_onboarding_detail', client_id=client_id))
    onb = _ensure_client_onboarding(conn, client_id, client['registration_number'])

    context = _stage_email_context_from_client(dict(client))
    context['product_name'] = 'GooCampus Standard Consulting'
    result = _send_stage_email(conn, 'welcome_email', client_id, context)

    if result['status'] == 'sent':
        conn.execute(
            """UPDATE client_onboarding SET
                 welcome_email_sent = 1,
                 welcome_email_sent_at = CURRENT_TIMESTAMP,
                 welcome_email_sent_by = ?,
                 onboarding_status = CASE
                   WHEN onboarding_status = 'Pending' THEN 'Email Sent'
                   ELSE onboarding_status END,
                 updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (session.get('user_id'), onb['id']),
        )
        conn.commit()
        flash(f'Welcome email sent to {", ".join(result["recipients"])}', 'success')
    elif result['status'] == 'disabled':
        flash('Welcome email template is disabled. Enable it in Email Templates to send.', 'error')
    elif result['status'] == 'no_template':
        flash('Welcome email template not found.', 'error')
    elif result['status'] == 'no_recipients':
        flash('No recipients selected on the welcome email template.', 'error')
    elif result['status'] == 'send_failed':
        flash('Failed to send email. Check Resend API key.', 'error')
    else:
        flash(f'Error sending email: {result.get("error","unknown")}', 'error')
    conn.close()
    return redirect(url_for('ops_consulting_onboarding_detail', client_id=client_id))


def register_routes(app):
    """Register Standard Consulting onboarding routes."""
    app.add_url_rule(
        '/operations/consulting/onboarding',
        endpoint='ops_consulting_onboarding_list',
        view_func=ops_consulting_onboarding_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/onboarding/<int:client_id>',
        endpoint='ops_consulting_onboarding_detail',
        view_func=ops_consulting_onboarding_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/onboarding/<int:client_id>/update',
        endpoint='ops_consulting_onboarding_update',
        view_func=ops_consulting_onboarding_update,
        methods=['POST'],
    )
    app.add_url_rule(
        '/operations/consulting/onboarding/<int:client_id>/send-welcome-email',
        endpoint='ops_consulting_onboarding_send_welcome_email',
        view_func=ops_consulting_onboarding_send_welcome_email,
        methods=['POST'],
    )
