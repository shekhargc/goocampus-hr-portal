"""
routes/operations/australia.py — Operations: AMC Pathway dashboard.

Surfaces Australia client stats from plab_clients WHERE pathway='australia'
(the storage decision locked 2026-05-31). The 228 historical Australia
clients were imported from GC_AUS_Registration_Report.xlsx by
import_australia_clients.run_import_australia_clients_once() at app boot.

The Australia Excel and the import script are committed alongside this
file so the same data shows up identically on every fresh environment.

Endpoint name preserved: ops_australia_pathway. Sidebar pathway switcher
links to /operations/australia-pathway.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
# Pathway-scoped dropdown options for the AMC Registration edit form so the
# Plan Type / Account Status / Current Stage / Counsellor / Lead Source
# <select>s render the same options PLAB uses (sourced from the AMC tab
# of Field Manager).
from routes.operations._form_lookups import section_client_lookups, section_client_products


@admin_required
def ops_australia_pathway():
    """AMC Pathway dashboard — stats from plab_clients where pathway='australia'."""
    user = get_user()
    conn = get_db()

    stats = {
        'total_clients':        0,
        'active_clients':       0,
        'on_hold_clients':      0,
        'dropped_clients':      0,
        'completed_clients':    0,
        'account_status':       {},   # {status: count}
        'current_stage':        {},   # {stage: count}
        'counsellor_breakdown': [],   # top 5 [(counsellor, count)]
        'package_total':        0.0,  # sum of final_package across active
        'recent_registrations': [],   # last 5 rows
        'this_fy_new':          0,    # signups in current Indian FY
        # Section counts shown on the dashboard tile grid.
        'section_counts':       {},   # {slug: count}
    }

    try:
        # ── Totals + status buckets ──────────────────────────────────────
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM plab_clients WHERE pathway = 'australia'"
        ).fetchone()['c']
        stats['total_clients'] = total

        # Per-status counts (single grouped query, then map keys onto buckets)
        for row in conn.execute(
            """SELECT COALESCE(NULLIF(TRIM(account_status), ''), 'Unknown') AS s,
                      COUNT(*) AS c
               FROM plab_clients WHERE pathway = 'australia'
               GROUP BY account_status"""
        ).fetchall():
            stats['account_status'][row['s']] = row['c']

        # Convenience: surface the four most common buckets at the top
        stats['active_clients']    = stats['account_status'].get('In Process', 0)
        stats['on_hold_clients']   = stats['account_status'].get('On Hold', 0)
        stats['dropped_clients']   = stats['account_status'].get('Dropped', 0)
        stats['completed_clients'] = stats['account_status'].get('Completed', 0)

        # ── Current stage breakdown (active clients only) ────────────────
        for row in conn.execute(
            """SELECT COALESCE(NULLIF(TRIM(current_stage), ''), 'Not Set') AS stg,
                      COUNT(*) AS c
               FROM plab_clients
               WHERE pathway = 'australia' AND account_status = 'In Process'
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
                   WHERE pathway = 'australia' AND account_status = 'In Process'
                   GROUP BY counsellor
                   ORDER BY c DESC
                   LIMIT 5"""
            ).fetchall()
        ]

        # ── Package value (active clients) ──────────────────────────────
        pkg_row = conn.execute(
            """SELECT COALESCE(SUM(final_package), 0) AS s
               FROM plab_clients
               WHERE pathway = 'australia' AND account_status = 'In Process'"""
        ).fetchone()
        stats['package_total'] = float(pkg_row['s'] or 0)

        # ── This-FY new registrations ───────────────────────────────────
        # Indian FY runs Apr-Mar. We could compute via SQL but the count is
        # cheap to do in Python with the registration_number prefix.
        from core.registration import indian_financial_year
        fy = indian_financial_year()
        fy_count = conn.execute(
            "SELECT COUNT(*) AS c FROM plab_clients "
            "WHERE pathway = 'australia' AND registration_number LIKE ?",
            (f'GCAUSIP/{fy}/%',),
        ).fetchone()['c']
        stats['this_fy_new'] = fy_count

        # ── Recent registrations (last 5 by id, which == reg order) ─────
        stats['recent_registrations'] = conn.execute(
            """SELECT id, registration_number, prefix, first_name, last_name,
                      mobile, email, account_status, current_stage,
                      counsellor, final_package, registration_date
               FROM plab_clients
               WHERE pathway = 'australia'
               ORDER BY id DESC
               LIMIT 5"""
        ).fetchall()

        # ── Section row counts for the dashboard tile grid ──────────────
        section_tables = {
            'test_bookings':   'ops_test_bookings',
            'academic':        'ops_academic_details',
            'epic':            'ops_epic_registration',
            'training':        'ops_coaching',
            'online_courses':  'ops_online_subscriptions',
            'payments':        'ops_payments',
            'call_notes':      'ops_call_notes',
            'research':        'ops_research_publication',
            'webinars':        'ops_webinars_conferences',
        }
        for slug, table in section_tables.items():
            try:
                stats['section_counts'][slug] = conn.execute(
                    f"SELECT COUNT(*) AS c FROM {table} WHERE pathway = 'australia'"
                ).fetchone()['c']
            except Exception:
                stats['section_counts'][slug] = 0

        # ── Detailed per-section stats (matches PLAB Pathway Dashboard) ──
        # All scoped to pathway='australia' so PLAB rows can't leak.
        from datetime import date, timedelta
        today = date.today().isoformat()
        thirty_ago = (date.today() - timedelta(days=30)).isoformat()
        AU = "pathway = 'australia'"

        def cnt(sql, *params):
            try:
                return conn.execute(sql, params).fetchone()['c']
            except Exception:
                return 0

        # Coaching / Training
        stats['coaching_total']   = cnt(f"SELECT COUNT(*) AS c FROM ops_coaching WHERE {AU}")
        stats['coaching_ongoing'] = cnt(f"SELECT COUNT(*) AS c FROM ops_coaching WHERE {AU} AND coaching_status = 'On Going'")

        # Test Bookings
        stats['test_total']       = stats['section_counts']['test_bookings']
        stats['upcoming_tests']   = cnt(f"SELECT COUNT(*) AS c FROM ops_test_bookings WHERE {AU} AND exam_date >= ? AND exam_status = 'Booked'", today)
        # AMC 1 / AMC 2 are Australia's PLAB 1 / PLAB 2 equivalents
        stats['amc1_upcoming']    = cnt(f"SELECT COUNT(*) AS c FROM ops_test_bookings WHERE {AU} AND exam_date >= ? AND exam_status = 'Booked' AND exam LIKE 'AMC 1%'", today)
        stats['amc2_upcoming']    = cnt(f"SELECT COUNT(*) AS c FROM ops_test_bookings WHERE {AU} AND exam_date >= ? AND exam_status = 'Booked' AND exam LIKE 'AMC 2%'", today)
        stats['amc_mcq_upcoming'] = cnt(f"SELECT COUNT(*) AS c FROM ops_test_bookings WHERE {AU} AND exam_date >= ? AND exam_status = 'Booked' AND exam LIKE 'AMC MCQ%'", today)
        stats['amc_clin_upcoming']= cnt(f"SELECT COUNT(*) AS c FROM ops_test_bookings WHERE {AU} AND exam_date >= ? AND exam_status = 'Booked' AND exam LIKE 'AMC Clinical%'", today)
        stats['awaiting_results'] = cnt(f"SELECT COUNT(*) AS c FROM ops_test_bookings WHERE {AU} AND exam_status = 'Attended' AND (exam_result IS NULL OR exam_result = '')")
        stats['recent_passes']    = cnt(f"SELECT COUNT(*) AS c FROM ops_test_bookings WHERE {AU} AND exam_result = 'Passed' AND exam_result_date >= ?", thirty_ago)

        # EPIC
        stats['epic_total']       = stats['section_counts']['epic']
        stats['epic_in_process']  = cnt(f"SELECT COUNT(*) AS c FROM ops_epic_registration WHERE {AU} AND epic_status = 'In Process'")
        stats['epic_completed']   = cnt(f"SELECT COUNT(*) AS c FROM ops_epic_registration WHERE {AU} AND epic_registration_status = 'Completed'")

        # Academic
        stats['academic_total']   = stats['section_counts']['academic']

        # Research
        stats['research_total']     = stats['section_counts']['research']
        stats['research_started']   = cnt(f"SELECT COUNT(*) AS c FROM ops_research_publication WHERE {AU} AND research_status = 'Started'")
        stats['research_completed'] = cnt(f"SELECT COUNT(*) AS c FROM ops_research_publication WHERE {AU} AND research_status = 'Research Completed'")
        stats['research_published'] = cnt(f"SELECT COUNT(*) AS c FROM ops_research_publication WHERE {AU} AND research_status = 'Research Published'")

        # Online Courses
        stats['oc_total']         = stats['section_counts']['online_courses']

        # Payments
        stats['payments_total']   = stats['section_counts']['payments']
        try:
            stats['payments_sum'] = float(conn.execute(
                f"SELECT COALESCE(SUM(total_amount_paid), 0) AS s FROM ops_payments WHERE {AU}"
            ).fetchone()['s'] or 0)
        except Exception:
            stats['payments_sum'] = 0.0

        # Webinars
        stats['webinars_total']   = stats['section_counts']['webinars']

        # ── Upcoming exams list (next 5 by exam_date) ──
        try:
            stats['upcoming_exams'] = conn.execute(
                f"""SELECT t.*, p.prefix, p.first_name, p.last_name
                      FROM ops_test_bookings t
                 LEFT JOIN plab_clients p ON p.registration_number = t.registration_number
                                          AND COALESCE(p.pathway, 'plab') = 'australia'
                     WHERE COALESCE(t.pathway, 'plab') = 'australia'
                       AND t.exam_date >= ?
                       AND t.exam_status = 'Booked'
                  ORDER BY t.exam_date ASC LIMIT 5""",
                (today,),
            ).fetchall()
        except Exception:
            stats['upcoming_exams'] = []

    except Exception as e:
        logging.error(f"ops_australia_pathway: {e}")
        flash(f'Error loading AMC Pathway dashboard: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_pathway_dashboard.html',
        user=user,
        pathway_name='AMC Pathway',
        stats=stats,
        active_ops_page='australia',
        active_pathway='australia',
    )


# NOTE: ops_australia_test_bookings_list was removed from this module.
# Australia Test Bookings (including the new drawer/detail/edit work
# from Phase 4 standardization) now lives entirely in
# routes/operations/au_test_bookings.py. Registration is wired in
# routes/operations/__init__.py.


@admin_required
def ops_australia_clients_list():
    """Australia Registration — list plab_clients WHERE pathway='australia'.

    This is what the Registration sidebar item links to when on Australia
    Pathway. Mirrors the PLAB client list but filtered to the Australia
    pathway and using the agent-built table template style.
    """
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    status_filter = (request.args.get('status', '') or '').strip()
    stage_filter = (request.args.get('stage', '') or '').strip()
    counsellor_filter = (request.args.get('counsellor', '') or '').strip()

    records = []
    statuses = []
    stages = []
    counsellors = []
    total = 0

    try:
        sql = '''SELECT id, registration_number, registration_date,
                        prefix, first_name, last_name, mobile, whatsapp1, email,
                        city, state, account_status, current_stage,
                        counsellor, plan_type, final_package, total_paid,
                        lead_source, dob
                   FROM plab_clients
                  WHERE pathway = 'australia' '''
        params = []
        if status_filter:
            sql += " AND account_status = ? "
            params.append(status_filter)
        if stage_filter:
            sql += " AND current_stage = ? "
            params.append(stage_filter)
        if counsellor_filter:
            sql += " AND counsellor = ? "
            params.append(counsellor_filter)
        if search:
            sql += """ AND (
                first_name ILIKE ? OR last_name ILIKE ? OR
                registration_number ILIKE ? OR mobile ILIKE ? OR email ILIKE ? OR
                (COALESCE(prefix,'')||' '||first_name||' '||COALESCE(last_name,'')) ILIKE ?
            ) """
            params.extend([f'%{search}%'] * 6)
        # Latest registrations on top (user request 2026-06-01) — mirrors PLAB.
        sql += " ORDER BY registration_date DESC NULLS LAST, id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        statuses = [
            r['account_status'] for r in conn.execute(
                """SELECT DISTINCT account_status FROM plab_clients
                    WHERE pathway = 'australia'
                      AND account_status IS NOT NULL AND account_status != ''
                    ORDER BY account_status"""
            ).fetchall()
        ]
        stages = [
            r['current_stage'] for r in conn.execute(
                """SELECT DISTINCT current_stage FROM plab_clients
                    WHERE pathway = 'australia'
                      AND current_stage IS NOT NULL AND current_stage != ''
                    ORDER BY current_stage"""
            ).fetchall()
        ]
        counsellors = [
            r['counsellor'] for r in conn.execute(
                """SELECT DISTINCT counsellor FROM plab_clients
                    WHERE pathway = 'australia'
                      AND counsellor IS NOT NULL AND counsellor != ''
                    ORDER BY counsellor"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_australia_clients_list: {e}")
        flash(f'Error loading Australia client list: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_clients_list.html',
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
        pathway_name='AMC Pathway',
        active_ops_page='australia-clients',
        active_pathway='australia',
    )


# ── Editable columns on plab_clients (pathway='australia' scope) ────────────
# Only columns that are safe to edit through the UI live here. id /
# registration_number / pathway are NOT editable.
AU_EDITABLE_COLUMNS = [
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


def _payment_totals_for(conn, reg_num):
    """Return (amount_paid, gst_paid, total_paid) summed from ops_payments
    for one Australia client. Pathway-scoped so PLAB payments can't leak."""
    row = conn.execute(
        """SELECT COALESCE(SUM(amount_paid), 0)        AS amt,
                  COALESCE(SUM(gst_paid), 0)           AS gst,
                  COALESCE(SUM(total_amount_paid), 0)  AS tot
             FROM ops_payments
            WHERE registration_number = ?
              AND COALESCE(pathway, 'plab') = 'australia' """,
        (reg_num,),
    ).fetchone()
    return float(row['amt'] or 0), float(row['gst'] or 0), float(row['tot'] or 0)


@admin_required
def ops_australia_client_detail(client_id):
    """Full Australia client profile — view + edit form + linked sections.

    Mirrors PLAB's /operations/plab/<id> structure: client info, payment
    breakdown, and tables of related ops_* records (test bookings, payments,
    academic, EPIC, training, etc.) all scoped to pathway='australia'.
    """
    user = get_user()
    conn = get_db()
    client = conn.execute(
        "SELECT * FROM plab_clients WHERE id = ? AND COALESCE(pathway, 'plab') = 'australia'",
        (client_id,),
    ).fetchone()
    if not client:
        conn.close()
        flash('Australia client not found.', 'error')
        return redirect(url_for('ops_australia_clients_list'))

    reg = client['registration_number']
    amount_paid, gst_paid, total_paid = _payment_totals_for(conn, reg)
    final_pkg = float(client['final_package'] or 0) or (
        float(client['package_amount'] or 0) - float(client['discount_allowed'] or 0)
    )
    balance = final_pkg - amount_paid
    pct = (amount_paid / final_pkg * 100) if final_pkg > 0 else 0

    # Related sections — only pull pathway='australia' rows for safety.
    # Each fetch returns a list of plain dicts so the section_block macro
    # in the template can iterate columns with .items().
    def fetch(table, order=None):
        try:
            sql = (
                f"SELECT * FROM {table} "
                f"WHERE registration_number = ? "
                f"  AND COALESCE(pathway, 'plab') = 'australia' "
            )
            if order:
                sql += f" ORDER BY {order} "
            return [dict(x) for x in conn.execute(sql, (reg,)).fetchall()]
        except Exception:
            return []

    sections = {
        'academic':             fetch('ops_academic_details', 'id DESC'),
        'epic':                 fetch('ops_epic_registration', 'id DESC'),
        'amc_registration':     fetch('ops_amc_registration', 'id DESC'),
        'training':             fetch('ops_coaching', 'id DESC'),
        'test_bookings':        fetch('ops_test_bookings', 'id DESC'),
        'online_courses':       fetch('ops_online_courses', 'id DESC'),
        'online_subscriptions': fetch('ops_online_subscriptions', 'id DESC'),
        'research':             fetch('ops_research_publication', 'id DESC'),
        'webinars':             fetch('ops_webinars_conferences', 'id DESC'),
        'call_notes':           fetch('ops_call_notes', 'id DESC'),
        'payments':             fetch('ops_payments', 'id DESC'),
    }

    from app import PLAB_DOC_TYPES
    try:
        documents = conn.execute("SELECT d.id, d.client_id, d.doc_type, d.doc_category, d.file_name, d.file_path, d.file_size, d.status, d.verified_by, d.verified_at, d.notes, d.uploaded_by, d.uploaded_at, e.name as verifier_name FROM plab_client_documents d LEFT JOIN employees e ON e.id = d.verified_by WHERE d.client_id = ? ORDER BY d.doc_category, d.uploaded_at DESC", (client['id'],)).fetchall()
    except Exception:
        documents = []
    conn.close()

    return render_template(
        'ops_australia_client_detail.html',
        documents=documents,
        plab_doc_types=PLAB_DOC_TYPES,
        user=user,
        client=client,
        sections=sections,
        amount_paid=amount_paid,
        gst_paid=gst_paid,
        total_paid=total_paid,
        final_pkg=final_pkg,
        balance=balance,
        payment_pct=pct,
        pathway_name='AMC Pathway',
        active_ops_page='australia-clients',
        active_pathway='australia',
    )


@admin_required
def ops_australia_client_by_reg(reg):
    """Resolve an Australia client by registration_number → detail redirect.

    Used by section drawers (Call Notes, Payments, Test Bookings, etc.)
    whose "View Client Profile" button only knows the registration_number,
    not the numeric client_id required by /operations/australia/clients/<id>.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM plab_clients WHERE registration_number = ? "
        "AND COALESCE(pathway, 'plab') = 'australia' LIMIT 1",
        (reg,)
    ).fetchone()
    conn.close()
    if not row:
        flash(f'Australia client {reg} not found.', 'error')
        return redirect(url_for('ops_australia_clients_list'))
    return redirect(url_for('ops_australia_client_detail', client_id=row['id']))


@admin_required
def ops_australia_client_edit_page(client_id):
    """GET — render the edit form for an Australia client.

    Mirrors the PLAB pattern (view page + separate edit page) so the layout
    is consistent across pathways. The view page is /operations/australia/
    clients/<id>; this edit page is .../edit (GET).
    """
    user = get_user()
    conn = get_db()
    client = conn.execute(
        "SELECT * FROM plab_clients WHERE id = ? AND COALESCE(pathway, 'plab') = 'australia'",
        (client_id,),
    ).fetchone()
    conn.close()
    if not client:
        flash('Australia client not found.', 'error')
        return redirect(url_for('ops_australia_clients_list'))
    client = dict(client)
    if not client.get('product_id') and client.get('plan_type'):
        from app import derive_product_id_from_plan
        client['product_id'] = derive_product_id_from_plan('australia', client.get('plan_type'))
    return render_template(
        'ops_australia_client_edit_form.html',
        user=user,
        client=client,
        active_ops_page='australia-clients',
        active_pathway='australia',
        # Dropdown options for Plan Type, Account Status, Current Stage,
        # Switched Program, Counsellor, Lead Source. Sourced from
        # lookup_options where pathway='australia'.
        **section_client_lookups('australia'),
        **section_client_products('australia'),
    )


@admin_required
def ops_australia_client_edit_save(client_id):
    """POST handler: save changes to an Australia client's editable fields.

    Strict allowlist (AU_EDITABLE_COLUMNS) — anything else in the form is
    silently ignored. Pathway is NEVER updated through this endpoint.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM plab_clients WHERE id = ? AND COALESCE(pathway, 'plab') = 'australia'",
            (client_id,),
        ).fetchone()
        if not existing:
            flash('Australia client not found.', 'error')
            return redirect(url_for('ops_australia_clients_list'))

        # Build SET clause from the allowlist.
        sets = []
        params = []
        for col in AU_EDITABLE_COLUMNS:
            if col in request.form:
                val = request.form.get(col, '').strip()
                # Numeric columns get coerced; bad data -> 0.
                if col in {'package_amount', 'discount_allowed', 'final_package',
                           'inst1_amount', 'inst2_amount', 'inst3_amount', 'inst4_amount'}:
                    try:
                        val = float(val) if val else 0
                    except ValueError:
                        val = 0
                # product_id: empty selection -> NULL (legacy rows stay clean).
                elif col == 'product_id':
                    val = val or None
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
        logging.error(f"ops_australia_client_edit: {e}")
        flash(f'Error saving client: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_australia_client_detail', client_id=client_id))


@admin_required
def ops_australia_client_delete(client_id):
    """Z-1: hard-delete an Australia client. Mirror of
    ops_plab_delete with a pathway='australia' safety check so PLAB
    rows can't be deleted through this surface even if someone
    crafts the URL by hand.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM plab_clients "
            " WHERE id = ? AND COALESCE(pathway,'plab') = 'australia'",
            (client_id,),
        ).fetchone()
        if not existing:
            flash('Australia client not found.', 'error')
            return redirect(url_for('ops_australia_clients_list'))
        conn.execute("DELETE FROM plab_clients WHERE id = ?", (client_id,))
        conn.commit()
        flash('Client deleted', 'success')
    except Exception as e:
        logging.error(f"ops_australia_client_delete: {e}")
        flash(f'Error: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    return redirect(url_for('ops_australia_clients_list'))


@admin_required
def ops_australia_documents_list():
    """Documents overview for Australia (AMC) clients.

    Same shape as ops_documents_list (PLAB) and
    ops_consulting_documents_list — JOIN plab_clients +
    plab_client_documents filtered to pathway='australia'. After Y-4
    each row's file_path is an R2 object key, but this list only
    counts docs per client; no R2 calls happen here.
    """
    user = get_user()
    conn = get_db()
    search = (request.args.get('search') or '').strip()
    status_filter = (request.args.get('status') or '')
    page = max(1, int(request.args.get('page', 1) or 1))
    per_page = 50

    # Use the same PLAB checklist for now -- AMC-specific required
    # docs can be carved out later via lookup_options.
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
                WHERE COALESCE(c.pathway, 'plab') = 'australia' """
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
        logging.error(f"ops_australia_documents_list: {e}")
        all_clients = []
    finally:
        conn.close()

    total_clients = len(all_clients)
    complete_count = sum(1 for c in all_clients if c.get('doc_count', 0) >= total_required)
    total_documents = sum(c.get('doc_count', 0) for c in all_clients)
    total_pages = max(1, (total_clients + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    page_clients = all_clients[start:start + per_page]

    return render_template(
        'ops_australia_documents_list.html',
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
        active_ops_page='australia-documents',
        active_pathway='australia',
    )


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app.

    Uses app.add_url_rule to preserve endpoint names — keeps existing
    url_for('ops_australia_pathway') call sites working unchanged.
    """
    app.add_url_rule(
        '/operations/australia-pathway',
        endpoint='ops_australia_pathway',
        view_func=ops_australia_pathway,
        methods=['GET'],
    )
    # Australia Test Bookings registration moved to routes/operations/au_test_bookings.py.
    app.add_url_rule(
        '/operations/australia/clients',
        endpoint='ops_australia_clients_list',
        view_func=ops_australia_clients_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/australia/clients/<int:client_id>',
        endpoint='ops_australia_client_detail',
        view_func=ops_australia_client_detail,
        methods=['GET'],
    )
    # Lookup-by-registration-number helper for section drawers
    app.add_url_rule(
        '/operations/australia/clients/by-reg/<path:reg>',
        endpoint='ops_australia_client_by_reg',
        view_func=ops_australia_client_by_reg,
        methods=['GET'],
    )
    # Edit page (GET) — renders the form
    app.add_url_rule(
        '/operations/australia/clients/<int:client_id>/edit',
        endpoint='ops_australia_client_edit_page',
        view_func=ops_australia_client_edit_page,
        methods=['GET'],
    )
    # Save (POST) — same URL, different method, separate endpoint
    app.add_url_rule(
        '/operations/australia/clients/<int:client_id>/edit',
        endpoint='ops_australia_client_edit_save',
        view_func=ops_australia_client_edit_save,
        methods=['POST'],
    )
    # Z-1: Delete handler (POST)
    app.add_url_rule(
        '/operations/australia/clients/<int:client_id>/delete',
        endpoint='ops_australia_client_delete',
        view_func=ops_australia_client_delete,
        methods=['POST'],
    )
    # Y-5: Documents list (clone of ops_consulting_documents_list,
    # scoped to pathway='australia')
    app.add_url_rule(
        '/operations/australia/documents',
        endpoint='ops_australia_documents_list',
        view_func=ops_australia_documents_list,
        methods=['GET'],
    )
