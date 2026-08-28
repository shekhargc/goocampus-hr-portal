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
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
# Pathway-scoped dropdown options for the Consulting Registration edit form.
from routes.operations._form_lookups import section_client_lookups, section_client_products, transfer_for_reg


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
                try: conn.rollback()
                except Exception: pass
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
        # ── Upcoming exams list (all booked, soonest first) ──
        try:
            from datetime import date, datetime
            today = date.today().isoformat()
            rows = conn.execute(
                """SELECT t.*, p.prefix, p.first_name, p.last_name
                      FROM ops_test_bookings t
                 LEFT JOIN plab_clients p ON p.registration_number = t.registration_number
                                          AND COALESCE(p.pathway, 'plab') = 'consulting'
                     WHERE COALESCE(t.pathway, 'plab') = 'consulting'
                       AND t.exam_date >= ?
                       AND t.exam_status = 'Booked'
                  ORDER BY t.exam_date ASC LIMIT 200""",
                (today,),
            ).fetchall()
            today_d = date.today()
            ue = []
            for r in rows:
                d = dict(r)
                ed = (d.get('exam_date') or '').strip() if isinstance(d.get('exam_date'), str) else d.get('exam_date')
                days_until = None
                try:
                    if ed:
                        # exam_date is stored as an ISO 'YYYY-MM-DD' string
                        exam_d = datetime.strptime(str(ed)[:10], '%Y-%m-%d').date()
                        days_until = (exam_d - today_d).days
                        if days_until < 0:
                            days_until = 0
                except Exception:
                    days_until = None
                if days_until is None:
                    # un-parseable date -> skip so the windows stay clean
                    continue
                d['days_until'] = days_until
                ue.append(d)
            stats['upcoming_exams'] = ue
        except Exception:
            stats['upcoming_exams'] = []
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
    product_filter = (request.args.get('product', '') or '').strip()

    records = []
    total = 0
    statuses = []
    stages = []
    counsellors = []
    products = []          # product tabs (AMC / UK / USA / UAE Consulting …) + counts
    all_count = 0          # total consulting clients (for the "All" tab)

    try:
        where = ["COALESCE(pathway, 'plab') = 'consulting'"]
        params = []
        if search:
            where.append(
                "(first_name ILIKE ? OR last_name ILIKE ? "
                " OR registration_number ILIKE ? OR mobile ILIKE ? "
                " OR email ILIKE ? "
                " OR (COALESCE(prefix,'')||' '||first_name||' '||COALESCE(last_name,'')) ILIKE ?)"
            )
            params.extend([f'%{search}%'] * 6)
        if status_filter:
            where.append("account_status = ?")
            params.append(status_filter)
        if stage_filter:
            where.append("current_stage = ?")
            params.append(stage_filter)
        if counsellor_filter:
            where.append("counsellor = ?")
            params.append(counsellor_filter)
        if product_filter and product_filter.isdigit():
            where.append("product_id = ?")
            params.append(int(product_filter))
        where_sql = " AND ".join(where)

        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM plab_clients WHERE {where_sql}",
            params,
        ).fetchone()['c']

        records = [dict(r) for r in conn.execute(
            f"""SELECT *,
                    (SELECT name FROM products_services ps WHERE ps.id = plab_clients.product_id) AS product_name
                  FROM plab_clients
                 WHERE {where_sql}
                 ORDER BY NULLIF(regexp_replace(COALESCE(registration_number,''), '[^0-9]', '', 'g'), '')::bigint DESC NULLS LAST, id DESC""",
            params,
        ).fetchall()]
        if records:
            def _nrm(s): return (s or '').strip().upper()
            _keys = [_nrm(r['registration_number']) for r in records]
            _ph = ','.join(['?'] * len(_keys))
            _pmap = {pr['k']: pr for pr in conn.execute(
                f"SELECT UPPER(TRIM(registration_number)) AS k, COALESCE(SUM(total_amount_paid),0) AS tp, COALESCE(SUM(amount_paid),0) AS ap, COALESCE(SUM(gst_paid),0) AS gp FROM ops_payments WHERE UPPER(TRIM(registration_number)) IN ({_ph}) GROUP BY UPPER(TRIM(registration_number))", _keys).fetchall()}
            for r in records:
                pr = _pmap.get(_nrm(r['registration_number']))
                r['total_paid'] = float(pr['tp']) if pr else 0
                r['amount_paid'] = float(pr['ap']) if pr else 0
                r['gst_paid'] = float(pr['gp']) if pr else 0

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
        # Product tabs (AMC / UK / USA / UAE Consulting …) with per-product counts,
        # built from the products consulting clients actually have (founder 2026-08-14).
        products = [dict(r) for r in conn.execute(
            "SELECT ps.id, ps.name, COUNT(pc.id) AS cnt "
            "  FROM plab_clients pc JOIN products_services ps ON ps.id = pc.product_id "
            " WHERE COALESCE(pc.pathway,'plab') = 'consulting' "
            " GROUP BY ps.id, ps.name ORDER BY ps.name"
        ).fetchall()]
        all_count = conn.execute(
            "SELECT COUNT(*) AS c FROM plab_clients WHERE COALESCE(pathway,'plab') = 'consulting'"
        ).fetchone()['c']
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
        products=products,
        product_filter=product_filter,
        all_count=all_count,
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
    'plan_type', 'product_id', 'account_status', 'current_stage', 'switched_program',
    'counsellor', 'counsellor_email', 'counsellor_number',
    'lead_source', 'registration_date',
    # Financials
    'package_amount', 'discount_allowed', 'final_package',
    'inst1_amount', 'inst1_date', 'inst1_note',
    'inst2_amount', 'inst2_date', 'inst2_note',
    'inst3_amount', 'inst3_date', 'inst3_note',
    'inst4_amount', 'inst4_date', 'inst4_note',
    # Centralised cross-pathway referral (data layer pre-created; columns exist)
    'referral_source_pathway', 'referral_channel', 'referral_client_reg', 'referral_client_name',
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
                WHERE UPPER(TRIM(registration_number)) = UPPER(TRIM(?))""",
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
            return [dict(x) for x in conn.execute(sql, (reg,)).fetchall()]
        except Exception:
            return []

    sections = {
        'academic':             fetch('ops_academic_details', 'id DESC'),
        'epic':                 fetch('ops_epic_registration', 'id DESC'),
        'gmc':                  fetch('ops_gmc_registration', 'id DESC'),
        'amc_registration':     fetch('ops_amc_registration', 'id DESC'),
        'mentorship':           fetch('ops_mentorship', 'id DESC'),
        'training':             fetch('ops_coaching', 'id DESC'),
        'test_bookings':        fetch('ops_test_bookings', 'id DESC'),
        'online_courses':       fetch('ops_online_courses', 'id DESC'),
        'online_subscriptions': fetch('ops_online_subscriptions', 'id DESC'),
        'research':             fetch('ops_research_publication', 'id DESC'),
        'webinars':             fetch('ops_webinars_conferences', 'id DESC'),
        'call_notes':           fetch('ops_call_notes', 'created_at DESC, id DESC'),
        'payments':             fetch('ops_payments', 'id DESC'),
    }
    # Centralised referral reporting: who did THIS client refer?
    try:
        referred_clients = conn.execute(
            "SELECT registration_number, "
            "       TRIM(COALESCE(prefix,'') || ' ' || COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS name, "
            "       COALESCE(pathway, 'plab') AS pathway "
            "  FROM plab_clients WHERE referral_client_reg = ? ORDER BY name",
            (reg,)).fetchall()
    except Exception:
        referred_clients = []
    referred_count = len(referred_clients)

    from app import PLAB_DOC_TYPES
    try:
        documents = conn.execute("SELECT d.id, d.client_id, d.doc_type, d.doc_category, d.file_name, d.file_path, d.file_size, d.status, d.verified_by, d.verified_at, d.notes, d.uploaded_by, d.uploaded_at, e.name as verifier_name FROM plab_client_documents d LEFT JOIN employees e ON e.id = d.verified_by WHERE d.client_id = ? ORDER BY d.doc_category, d.uploaded_at DESC", (client['id'],)).fetchall()
    except Exception:
        documents = []
    # Package deliverables (service names + descriptions the client is owed).
    # Budgets are intentionally NOT surfaced to Ops-facing deliverables here;
    # get_package_services returns budget but the template never renders it.
    try:
        from app import get_package_services
        package_services = get_package_services(
            conn, client.get('product_id'), client.get('plan_type'))
    except Exception:
        package_services = []
    # Combined signup already created a Training record for this person, so don't
    # offer "Add to Training" again. Match the same client by email/mobile.
    try:
        has_training = conn.execute(
            "SELECT 1 FROM plab_clients WHERE COALESCE(pathway,'') = 'training' AND id <> ? "
            "AND ((COALESCE(email,'') <> '' AND LOWER(email) = LOWER(COALESCE(?, ''))) "
            "  OR (COALESCE(mobile,'') <> '' AND mobile = COALESCE(?, ''))) LIMIT 1",
            (client['id'], client.get('email'), client.get('mobile'))).fetchone() is not None
    except Exception:
        has_training = False

    # ── Onboarding sync (Standard Consulting — founder 2026-08-11) ──
    # Consulting's Onboarding tab used to read empty legacy columns → all '—'.
    # Now every row reflects REAL state:
    #   Welcome Mail    = Yes (standard on ops-verify)
    #   Service Agmt.   = Yes once a contract is uploaded (contract_path) OR the
    #                     client digitally signed it (client_agreements)
    #   Refund Policy   = the real digitally-signed record (portal clients)
    #   Welcome Call    = live status: On hold / Scheduled / Done / Pending
    # Older Zoho clients (no portal registration) assume onboarding done.
    # Consulting has NO welcome kit.
    #
    # NOTE: computed defensively in independent steps — a failure in the
    # welcome-call lookup must never blank out Agreement/Refund (that was the
    # 2026-08-11 bug: a query on a non-existent column threw and wiped the lot).
    onboarding = {'welcome_call': 'pending', 'welcome_email': True, 'agreement': False,
                  'refund_policy': True, 'wc_hold_note': ''}
    try:
        from routes.operations.australia import _yn_flag
    except Exception:
        def _yn_flag(v):
            return str(v or '').strip().lower() in (
                'yes', 'y', 'done', '1', 'true', 'completed', 'signed', 'given')
    # Agreement from the same signals the "View Contract" button uses — reliable,
    # independent of any registration lookup.
    onboarding['agreement'] = _yn_flag(client.get('service_agreement')) or bool(client.get('contract_path'))
    rn = (client.get('registration_number') or '').strip().upper()
    rowreg = None
    try:
        rowreg = conn.execute(
            "SELECT id, account_id, COALESCE(welcome_call_hold,0) AS hold, wc_hold_note, "
            "COALESCE(wc_confirmed,0) AS confirmed, COALESCE(wc_status,'') AS wc_status, "
            "wc_scheduled_date, wc_proposed_date, wc_pref_date "
            "FROM client_registrations WHERE UPPER(TRIM(registration_number)) = ? "
            "AND client_submitted_at IS NOT NULL ORDER BY id DESC LIMIT 1", (rn,)).fetchone()
    except Exception as e:
        logging.warning(f"Consulting onboarding wc lookup: {e}")
        try: conn.rollback()
        except Exception: pass
    if rowreg:
        # Portal-registered client → reflect the REAL welcome-call status.
        st = (rowreg['wc_status'] or '').strip().lower()
        if rowreg['hold']:
            onboarding['welcome_call'] = 'hold'
            onboarding['wc_hold_note'] = rowreg['wc_hold_note'] or ''
        elif rowreg['confirmed'] or st in ('confirmed', 'completed', 'done'):
            onboarding['welcome_call'] = 'yes'
        elif (rowreg['wc_scheduled_date'] or rowreg['wc_proposed_date']
              or rowreg['wc_pref_date'] or st in ('scheduled', 'proposed', 'requested')):
            onboarding['welcome_call'] = 'scheduled'
        else:
            onboarding['welcome_call'] = 'pending'
        # Agreement/Refund from the real digitally-signed records.
        try:
            if not onboarding['agreement']:
                onboarding['agreement'] = bool(conn.execute(
                    "SELECT 1 FROM client_agreements WHERE account_id = ? "
                    "AND agreement_type = 'contract' LIMIT 1", (rowreg['account_id'],)).fetchone())
            onboarding['refund_policy'] = bool(conn.execute(
                "SELECT 1 FROM client_agreements WHERE account_id = ? "
                "AND agreement_type = 'refund_policy' LIMIT 1", (rowreg['account_id'],)).fetchone())
        except Exception:
            try: conn.rollback()
            except Exception: pass
    else:
        # Legacy Zoho client (no portal registration) → assume onboarding done.
        onboarding['welcome_call'] = 'yes'
    try:
        from app import build_client_address_ctx, build_client_resume_ctx
        address_ctx = build_client_address_ctx(conn, dict(client))
        resume_ctx = build_client_resume_ctx(conn, dict(client))
    except Exception:
        address_ctx = None
        resume_ctx = None
    conn.close()

    return render_template(
        'ops_consulting_client_detail.html',
        user=user,
        client=client,
        address=address_ctx,
        resume=resume_ctx,
        onboarding=onboarding,
        has_training=has_training,
        documents=documents,
        plab_doc_types=PLAB_DOC_TYPES,
        sections=sections,
        package_services=package_services,
        referred_clients=referred_clients,
        referred_count=referred_count,
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
def ops_consulting_client_by_reg(reg):
    """Resolve a Consulting client by registration_number → detail redirect.

    Used by section drawers (Call Notes, Payments, AMC, GMC, etc.) whose
    "View Client Profile" button only knows the registration_number, not
    the numeric client_id required by /operations/consulting/clients/<id>.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM plab_clients WHERE registration_number = ? "
        "AND COALESCE(pathway, 'plab') = 'consulting' LIMIT 1",
        (reg,)
    ).fetchone()
    conn.close()
    if not row:
        flash(f'Consulting client {reg} not found.', 'error')
        return redirect(url_for('ops_consulting_clients_list'))
    return redirect(url_for('ops_consulting_client_detail', client_id=row['id']))


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
    xfer = transfer_for_reg(conn, client['registration_number']) if client else None
    # Current Sales + Operations staff, to enrich the Counsellor dropdown so an
    # ops-referred client can be assigned its ops counsellor (founder 2026-08-18).
    counsellor_emps = []
    try:
        counsellor_emps = [r['name'] for r in conn.execute(
            "SELECT name FROM employees WHERE is_active = 1 "
            " AND LOWER(COALESCE(department,'')) IN ('sales','operations') "
            " AND COALESCE(name,'') <> '' ORDER BY name").fetchall()]
    except Exception:
        pass
    conn.close()
    if not client:
        flash('Consulting client not found.', 'error')
        return redirect(url_for('ops_consulting_clients_list'))
    client = dict(client)
    if not client.get('product_id') and client.get('plan_type'):
        from app import derive_product_id_from_plan
        client['product_id'] = derive_product_id_from_plan('consulting', client.get('plan_type'))
    # Dropdown options for Plan Type, Account Status, Current Stage, Switched Program,
    # Counsellor, Lead Source — from lookup_options. Merge current staff into the
    # Counsellor list (keep the client's existing value even if it's not in either).
    lookups = section_client_lookups('consulting')
    merged = list(lookups.get('counsellors') or [])
    for nm in counsellor_emps:
        if nm not in merged:
            merged.append(nm)
    cur = (client.get('counsellor') or '').strip()
    if cur and cur not in merged:
        merged.append(cur)
    lookups['counsellors'] = sorted({m for m in merged if m}, key=str.lower)
    # Product dropdown = consulting products PLUS the client's CURRENT product even if
    # it's tagged under another pathway (e.g. "AMC Consulting"). Without this the
    # dropdown showed blank for such clients and a save could wipe the product.
    _plist = list((section_client_products('consulting') or {}).get('products') or [])
    _cpid = client.get('product_id')
    if _cpid and not any((p.get('id') == _cpid) for p in _plist):
        try:
            _pc = get_db()
            _pr = _pc.execute("SELECT id, name FROM products_services WHERE id = ?", (_cpid,)).fetchone()
            _pc.close()
            if _pr:
                _plist.append({'id': _pr['id'], 'name': _pr['name']})
                _plist.sort(key=lambda p: (p.get('name') or '').lower())
        except Exception:
            pass
    return render_template(
        'ops_consulting_client_edit_form.html',
        user=user,
        client=client,
        transfer=xfer,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-clients',
        active_pathway='consulting',
        products=_plist,
        **lookups,
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
                # product_id: empty selection -> NULL (legacy rows stay clean).
                elif col == 'product_id':
                    # Never blank an existing product on an empty submit (e.g. the edit
                    # dropdown had no matching option for a cross-pathway product). Keep it.
                    if not val:
                        continue
                    try: val = int(val)
                    except (TypeError, ValueError): continue
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
            q += " AND (c.first_name ILIKE ? OR c.last_name ILIKE ? OR c.registration_number ILIKE ? OR (COALESCE(c.prefix,'')||' '||c.first_name||' '||COALESCE(c.last_name,'')) ILIKE ?) "
            params += [f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%']
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
    # Lookup-by-registration-number helper for section drawers
    app.add_url_rule(
        '/operations/consulting/clients/by-reg/<path:reg>',
        endpoint='ops_consulting_client_by_reg',
        view_func=ops_consulting_client_by_reg,
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
