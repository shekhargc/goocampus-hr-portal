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
from flask import render_template, flash

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
