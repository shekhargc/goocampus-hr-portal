"""
routes/operations/australia.py — Operations: Australia Pathway dashboard.

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


@admin_required
def ops_australia_pathway():
    """Australia Pathway dashboard — stats from plab_clients where pathway='australia'."""
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
        # Each tile shows a live count of Australia rows in the section's table.
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

    except Exception as e:
        logging.error(f"ops_australia_pathway: {e}")
        flash(f'Error loading Australia Pathway dashboard: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_pathway_dashboard.html',
        user=user,
        pathway_name='Australia Pathway',
        stats=stats,
        active_ops_page='australia',
        active_pathway='australia',
    )


@admin_required
def ops_australia_test_bookings_list():
    """Australia test bookings list — ops_test_bookings WHERE pathway='australia'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    exam_filter = (request.args.get('exam', '') or '').strip()
    status_filter = (request.args.get('status', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    exams = []
    statuses = []
    total = 0

    try:
        sql = '''SELECT t.id, t.registration_number, t.exam, t.exam_type,
                        t.booking_date, t.exam_date, t.exam_status,
                        t.exam_result, t.exam_result_date, t.score,
                        t.city_state, t.country, t.booked_by,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_test_bookings t
                   LEFT JOIN plab_clients p
                          ON t.registration_number = p.registration_number
                  WHERE t.pathway = 'australia' '''
        params = []
        if reg:
            sql += " AND t.registration_number = ? "
            params.append(reg)
        if exam_filter:
            sql += " AND t.exam = ? "
            params.append(exam_filter)
        if status_filter:
            sql += " AND t.exam_status = ? "
            params.append(status_filter)
        if search:
            sql += """ AND (
                p.first_name LIKE ? OR p.last_name LIKE ? OR
                t.test_center LIKE ? OR t.registration_number LIKE ?
            ) """
            params.extend([f'%{search}%'] * 4)
        sql += " ORDER BY COALESCE(t.exam_date, t.booking_date) DESC NULLS LAST, t.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        exams = [
            r['exam'] for r in conn.execute(
                """SELECT DISTINCT exam FROM ops_test_bookings
                    WHERE pathway = 'australia' AND exam IS NOT NULL AND exam != ''
                    ORDER BY exam"""
            ).fetchall()
        ]
        statuses = [
            r['exam_status'] for r in conn.execute(
                """SELECT DISTINCT exam_status FROM ops_test_bookings
                    WHERE pathway = 'australia' AND exam_status IS NOT NULL AND exam_status != ''
                    ORDER BY exam_status"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_australia_test_bookings_list: {e}")
        flash(f'Error loading Australia test bookings: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_test_bookings_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        exam_filter=exam_filter,
        status_filter=status_filter,
        client_reg=reg,
        exams=exams,
        statuses=statuses,
        pathway_name='Australia Pathway',
        active_ops_page='australia-test-bookings',
        active_pathway='australia',
    )


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
                first_name LIKE ? OR last_name LIKE ? OR
                registration_number LIKE ? OR mobile LIKE ? OR email LIKE ?
            ) """
            params.extend([f'%{search}%'] * 5)
        sql += " ORDER BY id DESC "
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
        pathway_name='Australia Pathway',
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
    def fetch(table, order=None):
        try:
            sql = (
                f"SELECT * FROM {table} "
                f"WHERE registration_number = ? "
                f"  AND COALESCE(pathway, 'plab') = 'australia' "
            )
            if order:
                sql += f" ORDER BY {order} "
            return conn.execute(sql, (reg,)).fetchall()
        except Exception:
            return []

    sections = {
        'test_bookings': fetch('ops_test_bookings', 'exam_date DESC NULLS LAST'),
        'academic':      fetch('ops_academic_details', 'created_at DESC'),
        'epic':          fetch('ops_epic_registration', 'created_at DESC'),
        'training':      fetch('ops_coaching', 'created_at DESC'),
        'online_courses': fetch('ops_online_subscriptions', 'created_at DESC'),
        'payments':      fetch('ops_payments', 'payment_date DESC NULLS LAST'),
        'call_notes':    fetch('ops_call_notes', 'call_date DESC NULLS LAST'),
        'research':      fetch('ops_research_publication', 'created_at DESC'),
        'webinars':      fetch('ops_webinars_conferences', 'created_at DESC'),
    }
    conn.close()

    return render_template(
        'ops_australia_client_detail.html',
        user=user,
        client=client,
        sections=sections,
        amount_paid=amount_paid,
        gst_paid=gst_paid,
        total_paid=total_paid,
        final_pkg=final_pkg,
        balance=balance,
        payment_pct=pct,
        pathway_name='Australia Pathway',
        active_ops_page='australia-clients',
        active_pathway='australia',
    )


@admin_required
def ops_australia_client_edit(client_id):
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
    app.add_url_rule(
        '/operations/australia/test-bookings',
        endpoint='ops_australia_test_bookings_list',
        view_func=ops_australia_test_bookings_list,
        methods=['GET'],
    )
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
    app.add_url_rule(
        '/operations/australia/clients/<int:client_id>/edit',
        endpoint='ops_australia_client_edit',
        view_func=ops_australia_client_edit,
        methods=['POST'],
    )
