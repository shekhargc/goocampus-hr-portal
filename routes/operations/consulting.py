"""
routes/operations/consulting.py — Operations: Standard Consulting pathway.

Foundation shell (S-0). Surfaces basic stats and a single clients list
for the Standard Consulting pathway, which houses four products in
products_services:
    * AMC Consulting
    * UAE Consulting
    * USA Consulting
    * UK Consulting

Data model
----------
Clients live in `plab_clients` with pathway='consulting' (same storage
decision made for AMC -- see Phase 2.2). Products live in
products_services with pathway='consulting'. The product a client signed
up for is captured at invitation time in client_invitations.product_id
and carried through to client_registrations.product_id, then to
plab_clients.product_id (added by the S-0 boot migration).

URL space
---------
    GET /operations/consulting               -> dashboard
    GET /operations/consulting/clients       -> clients list

Endpoint names
--------------
    ops_consulting_pathway        (dashboard view)
    ops_consulting_clients_list   (clients list)
"""

import logging
from flask import render_template, flash, request

from core.auth import admin_required
from core.users import get_user
from db import get_db


@admin_required
def ops_consulting_pathway():
    """Standard Consulting dashboard -- mirrors the Australia dashboard
    layout but stripped to what makes sense for a brand-new pathway
    (no test bookings / EPIC / research / etc. tables to count yet)."""
    user = get_user()
    conn = get_db()

    stats = {
        'total_clients':        0,
        'active_clients':       0,
        'on_hold_clients':      0,
        'dropped_clients':      0,
        'completed_clients':    0,
        'account_status':       {},
        'current_stage':        {},
        'counsellor_breakdown': [],
        'package_total':        0.0,
        'recent_registrations': [],
        'this_fy_new':          0,
        # Per-product split -- the user-visible "what consulting type"
        # each client signed up for.
        'product_split':        [],   # [(product_name, count), ...]
    }

    try:
        # ── Totals + status buckets ──────────────────────────────────────
        stats['total_clients'] = conn.execute(
            "SELECT COUNT(*) AS c FROM plab_clients WHERE pathway = 'consulting'"
        ).fetchone()['c']

        for row in conn.execute(
            """SELECT COALESCE(NULLIF(TRIM(account_status), ''), 'Unknown') AS s,
                      COUNT(*) AS c
               FROM plab_clients WHERE pathway = 'consulting'
               GROUP BY account_status"""
        ).fetchall():
            stats['account_status'][row['s']] = row['c']

        stats['active_clients']    = stats['account_status'].get('In Process', 0)
        stats['on_hold_clients']   = stats['account_status'].get('On Hold', 0)
        stats['dropped_clients']   = stats['account_status'].get('Dropped', 0)
        stats['completed_clients'] = stats['account_status'].get('Completed', 0)

        # ── Current stage breakdown (active only) ───────────────────────
        for row in conn.execute(
            """SELECT COALESCE(NULLIF(TRIM(current_stage), ''), 'Not Set') AS stg,
                      COUNT(*) AS c
               FROM plab_clients
               WHERE pathway = 'consulting' AND account_status = 'In Process'
               GROUP BY current_stage
               ORDER BY c DESC"""
        ).fetchall():
            stats['current_stage'][row['stg']] = row['c']

        # ── Counsellor distribution (top 5) ─────────────────────────────
        stats['counsellor_breakdown'] = [
            (r['counsellor'] or 'Unassigned', r['c'])
            for r in conn.execute(
                """SELECT COALESCE(NULLIF(TRIM(counsellor), ''), 'Unassigned') AS counsellor,
                          COUNT(*) AS c
                   FROM plab_clients
                   WHERE pathway = 'consulting' AND account_status = 'In Process'
                   GROUP BY counsellor
                   ORDER BY c DESC
                   LIMIT 5"""
            ).fetchall()
        ]

        # ── Package value (active clients) ──────────────────────────────
        pkg = conn.execute(
            """SELECT COALESCE(SUM(final_package), 0) AS s
               FROM plab_clients
               WHERE pathway = 'consulting' AND account_status = 'In Process'"""
        ).fetchone()
        stats['package_total'] = float(pkg['s'] or 0)

        # ── Per-product split -- joins plab_clients to products_services
        # via product_id (added by S-0 boot migration). Falls back to
        # 'Unspecified' when product_id is null. ─────────────────────────
        try:
            stats['product_split'] = [
                (r['product_name'], r['c'])
                for r in conn.execute(
                    """SELECT COALESCE(ps.name, 'Unspecified') AS product_name,
                              COUNT(*) AS c
                       FROM plab_clients pc
                       LEFT JOIN products_services ps ON ps.id = pc.product_id
                       WHERE pc.pathway = 'consulting'
                       GROUP BY ps.name
                       ORDER BY c DESC"""
                ).fetchall()
            ]
        except Exception:
            # product_id column may not exist on a fresh DB before the
            # boot migration runs -- handled silently.
            stats['product_split'] = []

        # ── This-FY new registrations (reg-number prefix GCCSS/<FY>/) ──
        from core.registration import indian_financial_year
        fy = indian_financial_year()
        stats['this_fy_new'] = conn.execute(
            "SELECT COUNT(*) AS c FROM plab_clients "
            "WHERE pathway = 'consulting' AND registration_number LIKE ?",
            (f'GCCSS/{fy}/%',),
        ).fetchone()['c']

        # ── X-4b: AMC-style section card counts (most are 0 for
        # consulting -- those sections show 0 in the section grid). ──
        CS = "COALESCE(pathway, 'plab') = 'consulting'"
        def cnt(sql, *params):
            try:
                return conn.execute(sql, params).fetchone()['c']
            except Exception:
                return 0
        # Sections consulting HAS data for:
        stats['academic_total']     = cnt(f"SELECT COUNT(*) AS c FROM ops_academic_details WHERE {CS}")
        stats['payments_total']     = cnt(f"SELECT COUNT(*) AS c FROM ops_payments WHERE {CS}")
        try:
            stats['payments_sum']   = float(conn.execute(
                f"SELECT COALESCE(SUM(total_amount_paid), 0) AS s FROM ops_payments WHERE {CS}"
            ).fetchone()['s'] or 0)
        except Exception:
            stats['payments_sum']   = 0.0
        stats['epic_total']         = cnt(f"SELECT COUNT(*) AS c FROM ops_epic_registration WHERE {CS}")
        stats['epic_in_process']    = cnt(f"SELECT COUNT(*) AS c FROM ops_epic_registration WHERE {CS} AND epic_status = 'In Process'")
        stats['epic_completed']     = cnt(f"SELECT COUNT(*) AS c FROM ops_epic_registration WHERE {CS} AND epic_status = 'Completed'")
        # Sections that AMC has but consulting doesn't -- 0 stub so the
        # template loops don't error out.
        for k in ('coaching_total', 'coaching_ongoing',
                  'test_total', 'upcoming_tests',
                  'amc_mcq_upcoming', 'amc_clin_upcoming',
                  'amc1_upcoming', 'amc2_upcoming',
                  'awaiting_results', 'recent_passes',
                  'research_total', 'research_started',
                  'research_completed', 'research_published',
                  'oc_total', 'webinars_total'):
            stats[k] = 0
        stats['upcoming_exams']     = []
        stats['section_counts']     = {
            'academic': stats['academic_total'],
            'payments': stats['payments_total'],
            'epic':     stats['epic_total'],
        }

        # ── Recent registrations (last 5) ───────────────────────────────
        try:
            stats['recent_registrations'] = conn.execute(
                """SELECT pc.id, pc.registration_number, pc.prefix,
                          pc.first_name, pc.last_name, pc.mobile, pc.email,
                          pc.account_status, pc.current_stage, pc.counsellor,
                          pc.final_package, pc.registration_date,
                          ps.name AS product_name
                   FROM plab_clients pc
                   LEFT JOIN products_services ps ON ps.id = pc.product_id
                   WHERE pc.pathway = 'consulting'
                   ORDER BY pc.id DESC
                   LIMIT 5"""
            ).fetchall()
        except Exception:
            stats['recent_registrations'] = conn.execute(
                """SELECT id, registration_number, prefix, first_name,
                          last_name, mobile, email, account_status,
                          current_stage, counsellor, final_package,
                          registration_date
                   FROM plab_clients
                   WHERE pathway = 'consulting'
                   ORDER BY id DESC
                   LIMIT 5"""
            ).fetchall()

    except Exception as e:
        logging.error(f"ops_consulting_pathway: {e}")
        flash(f'Error loading Standard Consulting dashboard: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_consulting_pathway_dashboard.html',
        user=user,
        pathway_name='Standard Consulting',
        stats=stats,
        active_ops_page='consulting',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_clients_list():
    """Standard Consulting clients list -- matches the AMC list template
    (right-side drawer + standard fonts). Data shape mirrors the AMC
    handler so the cloned template renders cleanly: provides search /
    status / stage / counsellor filter pools plus the records list."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or request.args.get('search', '') or '').strip()
    status_filter = (request.args.get('status', '') or '').strip()
    stage_filter = (request.args.get('stage', '') or '').strip()
    counsellor_filter = (request.args.get('counsellor', '') or '').strip()

    records = []
    total = 0
    statuses = []
    stages = []
    counsellors = []

    try:
        where = ["COALESCE(pathway, 'plab') = 'consulting'"]
        params = []
        if search:
            where.append(
                "(first_name ILIKE ? OR last_name ILIKE ? "
                " OR registration_number ILIKE ? OR mobile ILIKE ? "
                " OR email ILIKE ?)"
            )
            params.extend([f'%{search}%'] * 5)
        if status_filter:
            where.append("account_status = ?")
            params.append(status_filter)
        if stage_filter:
            where.append("current_stage = ?")
            params.append(stage_filter)
        if counsellor_filter:
            where.append("counsellor = ?")
            params.append(counsellor_filter)
        where_sql = " AND ".join(where)

        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM plab_clients WHERE {where_sql}",
            params,
        ).fetchone()['c']

        records = conn.execute(
            f"""SELECT id, registration_number, prefix, first_name, last_name,
                       mobile, email, account_status, current_stage, counsellor,
                       package_amount, discount_allowed, final_package,
                       registration_date, dob, city, state, plan_type,
                       father_name, father_phone, mother_name, mother_phone,
                       parents_email, counsellor_email, counsellor_number,
                       lead_source
                 FROM plab_clients
                 WHERE {where_sql}
                 ORDER BY id DESC""",
            params,
        ).fetchall()

        # Filter dropdown pools
        statuses = [
            r['account_status'] for r in conn.execute(
                """SELECT DISTINCT account_status FROM plab_clients
                    WHERE COALESCE(pathway,'plab') = 'consulting'
                      AND account_status IS NOT NULL AND account_status != ''
                    ORDER BY account_status"""
            ).fetchall()
        ]
        stages = [
            r['current_stage'] for r in conn.execute(
                """SELECT DISTINCT current_stage FROM plab_clients
                    WHERE COALESCE(pathway,'plab') = 'consulting'
                      AND current_stage IS NOT NULL AND current_stage != ''
                    ORDER BY current_stage"""
            ).fetchall()
        ]
        counsellors = [
            r['counsellor'] for r in conn.execute(
                """SELECT DISTINCT counsellor FROM plab_clients
                    WHERE COALESCE(pathway,'plab') = 'consulting'
                      AND counsellor IS NOT NULL AND counsellor != ''
                    ORDER BY counsellor"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_consulting_clients_list: {e}")
        flash(f'Error loading clients list: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_consulting_clients.html',
        user=user,
        records=records,
        total=total,
        search=search,
        status_filter=status_filter,
        stage_filter=stage_filter,
        counsellor_filter=counsellor_filter,
        statuses=statuses,
        stages=stages,
        counsellors=counsellors,
        active_ops_page='consulting-clients',
        active_pathway='consulting',
    )


# ── X-4a: per-client detail + edit + delete (PLAB/AMC parity) ──────────
CS_EDITABLE_COLUMNS = [
    # Personal
    'prefix', 'first_name', 'last_name', 'mobile', 'whatsapp1', 'whatsapp2',
    'email', 'dob', 'city', 'state',
    'instagram', 'facebook', 'linkedin',
    'father_name', 'father_phone', 'mother_name', 'mother_phone', 'parents_email',
    # Service
    'plan_type', 'account_status', 'current_stage', 'switched_program',
    'counsellor', 'counsellor_email', 'counsellor_number',
    'lead_source', 'registration_date',
    # Financials
    'package_amount', 'discount_allowed', 'final_package',
    'inst1_amount', 'inst1_date', 'inst1_note',
    'inst2_amount', 'inst2_date', 'inst2_note',
    'inst3_amount', 'inst3_date', 'inst3_note',
    'inst4_amount', 'inst4_date', 'inst4_note',
]
# Numeric fields get coerced to float on save.
CS_NUMERIC_COLUMNS = {
    'package_amount', 'discount_allowed', 'final_package',
    'inst1_amount', 'inst2_amount', 'inst3_amount', 'inst4_amount',
}


def _cs_payment_totals_for(conn, reg_num):
    """Sum (amount_paid, gst_paid, total_paid) for ONE consulting client
    from ops_payments. Pathway-scoped so PLAB / AMC payments can't
    leak."""
    try:
        row = conn.execute(
            """SELECT COALESCE(SUM(amount_paid), 0)        AS amt,
                      COALESCE(SUM(gst_paid), 0)           AS gst,
                      COALESCE(SUM(total_amount_paid), 0)  AS tot
                 FROM ops_payments
                WHERE registration_number = ?
                  AND COALESCE(pathway, 'plab') = 'consulting'""",
            (reg_num,),
        ).fetchone()
        return (float(row['amt'] or 0),
                float(row['gst'] or 0),
                float(row['tot'] or 0))
    except Exception:
        return 0.0, 0.0, 0.0


@admin_required
def ops_consulting_client_detail(client_id):
    """Full consulting client profile -- view + linked-section panels.

    Mirror of ops_australia_client_detail scoped to pathway='consulting'.
    Only fetches sections that consulting actually uses (academic,
    call_notes, EPIC, payments, AMC registration, mentorship); skips
    AMC-specific training/test_bookings/research/webinars/online_courses.
    """
    user = get_user()
    conn = get_db()
    client = conn.execute(
        "SELECT * FROM plab_clients "
        " WHERE id = ? AND COALESCE(pathway, 'plab') = 'consulting'",
        (client_id,),
    ).fetchone()
    if not client:
        conn.close()
        flash('Consulting client not found.', 'error')
        return redirect(url_for('ops_consulting_clients_list'))

    reg = client['registration_number']
    amount_paid, gst_paid, total_paid = _cs_payment_totals_for(conn, reg)
    final_pkg = float(client['final_package'] or 0) or (
        float(client['package_amount'] or 0) - float(client['discount_allowed'] or 0)
    )
    balance = final_pkg - amount_paid
    pct = (amount_paid / final_pkg * 100) if final_pkg > 0 else 0

    def fetch(table, order=None):
        try:
            sql = (
                f"SELECT * FROM {table} "
                f"WHERE registration_number = ? "
                f"  AND COALESCE(pathway, 'plab') = 'consulting' "
            )
            if order:
                sql += f" ORDER BY {order} "
            return conn.execute(sql, (reg,)).fetchall()
        except Exception:
            return []

    sections = {
        'academic':   fetch('ops_academic_details', 'created_at DESC'),
        'call_notes': fetch('ops_call_notes', 'call_date DESC NULLS LAST'),
        'epic':       fetch('ops_epic_registration', 'created_at DESC'),
        'payments':   fetch('ops_payments', 'payment_date DESC NULLS LAST'),
        # Consulting-specific sections that AMC pathway doesn't have:
        'amc_registration': fetch('ops_amc_registration', 'created_at DESC'),
        'mentorship':       fetch('ops_mentorship', 'created_at DESC'),
        # AMC-only sections stubbed to empty so the template loops still work.
        'test_bookings':    [],
        'training':         [],
        'online_courses':   [],
        'research':         [],
        'webinars':         [],
    }
    conn.close()

    return render_template(
        'ops_consulting_client_detail.html',
        user=user,
        client=client,
        sections=sections,
        amount_paid=amount_paid,
        gst_paid=gst_paid,
        total_paid=total_paid,
        final_pkg=final_pkg,
        balance=balance,
        payment_pct=pct,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-clients',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_client_edit_page(client_id):
    """GET -- render the edit form for a consulting client."""
    user = get_user()
    conn = get_db()
    client = conn.execute(
        "SELECT * FROM plab_clients "
        " WHERE id = ? AND COALESCE(pathway, 'plab') = 'consulting'",
        (client_id,),
    ).fetchone()
    conn.close()
    if not client:
        flash('Consulting client not found.', 'error')
        return redirect(url_for('ops_consulting_clients_list'))
    return render_template(
        'ops_consulting_client_edit_form.html',
        user=user,
        client=client,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-clients',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_client_edit_save(client_id):
    """POST -- save edits to a consulting client's editable fields."""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM plab_clients "
            " WHERE id = ? AND COALESCE(pathway,'plab') = 'consulting'",
            (client_id,),
        ).fetchone()
        if not existing:
            flash('Consulting client not found.', 'error')
            return redirect(url_for('ops_consulting_clients_list'))
        sets = []
        params = []
        for col in CS_EDITABLE_COLUMNS:
            if col in request.form:
                val = request.form.get(col, '').strip()
                if col in CS_NUMERIC_COLUMNS:
                    try: val = float(val) if val else 0
                    except ValueError: val = 0
                sets.append(f"{col} = ?")
                params.append(val)
        if sets:
            params.append(client_id)
            conn.execute(
                f"UPDATE plab_clients SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
            flash('Client details saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_consulting_client_edit_save: {e}")
        flash(f'Error saving client: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    return redirect(url_for('ops_consulting_client_detail', client_id=client_id))


@admin_required
def ops_consulting_documents_list():
    """Y-2: Documents overview for consulting clients. Clone of
    ops_documents_list scoped to pathway='consulting'. The shared
    plab_client_documents table holds rows for every pathway --
    we just JOIN through plab_clients and filter on pathway."""
    user = get_user()
    conn = get_db()
    search = (request.args.get('search') or '').strip()
    status_filter = (request.args.get('status') or '')
    page = max(1, int(request.args.get('page', 1) or 1))
    per_page = 50

    # Same PLAB-doc required list used by ops_documents_list -- the
    # consulting checklist is identical until product-specific doc
    # types are added (future work).
    try:
        from app import PLAB_ALL_REQUIRED_DOCS as REQUIRED_DOCS
    except Exception:
        REQUIRED_DOCS = []
    total_required = len(REQUIRED_DOCS)

    all_clients = []
    try:
        q = """SELECT c.id, c.registration_number, c.first_name, c.last_name, c.prefix,
                      c.account_status, c.current_stage, c.created_at,
                      COUNT(d.id) as doc_count,
                      SUM(CASE WHEN d.status = 'verified' THEN 1 ELSE 0 END) as verified_count
                 FROM plab_clients c
            LEFT JOIN plab_client_documents d ON d.client_id = c.id
                WHERE COALESCE(c.pathway, 'plab') = 'consulting' """
        params = []
        if search:
            q += " AND (c.first_name ILIKE ? OR c.last_name ILIKE ? OR c.registration_number ILIKE ?) "
            params += [f'%{search}%', f'%{search}%', f'%{search}%']
        q += """ GROUP BY c.id, c.registration_number, c.first_name, c.last_name, c.prefix,
                          c.account_status, c.current_stage, c.created_at
                 ORDER BY c.created_at DESC NULLS LAST, c.id DESC"""
        rows = conn.execute(q, params).fetchall()
        for r in rows:
            rd = dict(r)
            rd['total_required'] = total_required
            rd['name'] = f"{r['prefix'] or ''} {r['first_name'] or ''} {r['last_name'] or ''}".strip()
            if status_filter == 'complete' and rd['doc_count'] < total_required:
                continue
            if status_filter == 'incomplete' and rd['doc_count'] >= total_required:
                continue
            if status_filter == 'none' and rd['doc_count'] > 0:
                continue
            all_clients.append(rd)
    except Exception as e:
        logging.error(f"ops_consulting_documents_list: {e}")
        all_clients = []
    finally:
        conn.close()

    # Stats before pagination — template needs total_clients,
    # total_documents, complete_count (matches the PLAB documents
    # template contract — fixes 500 'total_clients undefined').
    total_clients = len(all_clients)
    complete_count = sum(1 for c in all_clients if c.get('doc_count', 0) >= total_required)
    total_documents = sum(c.get('doc_count', 0) for c in all_clients)
    total_pages = max(1, (total_clients + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    page_clients = all_clients[start:start + per_page]

    return render_template(
        'ops_consulting_documents_list.html',
        user=user,
        clients=page_clients,
        total_clients=total_clients,
        complete_count=complete_count,
        total_documents=total_documents,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        search=search,
        status_filter=status_filter,
        total_required=total_required,
        start_index=start if page_clients else 0,
        active_ops_page='consulting-documents',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_client_delete(client_id):
    """Hard-delete a consulting client (pathway-gated)."""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM plab_clients "
            " WHERE id = ? AND COALESCE(pathway,'plab') = 'consulting'",
            (client_id,),
        ).fetchone()
        if not existing:
            flash('Consulting client not found.', 'error')
            return redirect(url_for('ops_consulting_clients_list'))
        conn.execute("DELETE FROM plab_clients WHERE id = ?", (client_id,))
        conn.commit()
        flash('Client deleted', 'success')
    except Exception as e:
        logging.error(f"ops_consulting_client_delete: {e}")
        flash(f'Error: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    return redirect(url_for('ops_consulting_clients_list'))


def register_routes(app):
    """Register Standard Consulting routes with the Flask app."""
    app.add_url_rule(
        '/operations/consulting',
        endpoint='ops_consulting_pathway',
        view_func=ops_consulting_pathway,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/clients',
        endpoint='ops_consulting_clients_list',
        view_func=ops_consulting_clients_list,
        methods=['GET'],
    )
    # X-4a: per-client detail + edit + delete
    app.add_url_rule(
        '/operations/consulting/clients/<int:client_id>',
        endpoint='ops_consulting_client_detail',
        view_func=ops_consulting_client_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/clients/<int:client_id>/edit',
        endpoint='ops_consulting_client_edit_page',
        view_func=ops_consulting_client_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/clients/<int:client_id>/edit',
        endpoint='ops_consulting_client_edit_save',
        view_func=ops_consulting_client_edit_save,
        methods=['POST'],
    )
    app.add_url_rule(
        '/operations/consulting/clients/<int:client_id>/delete',
        endpoint='ops_consulting_client_delete',
        view_func=ops_consulting_client_delete,
        methods=['POST'],
    )
    # Y-2: documents list
    app.add_url_rule(
        '/operations/consulting/documents',
        endpoint='ops_consulting_documents_list',
        view_func=ops_consulting_documents_list,
        methods=['GET'],
    )
