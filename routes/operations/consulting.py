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

        # ── This-FY new registrations (reg-number prefix GCCONS/<FY>/) ──
        from core.registration import indian_financial_year
        fy = indian_financial_year()
        stats['this_fy_new'] = conn.execute(
            "SELECT COUNT(*) AS c FROM plab_clients "
            "WHERE pathway = 'consulting' AND registration_number LIKE ?",
            (f'GCCONS/{fy}/%',),
        ).fetchone()['c']

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
    """Standard Consulting clients list -- single shared list across all
    4 products, with a Product column and product filter dropdown."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('search') or '').strip()
    product_filter = (request.args.get('product') or '').strip()
    status_filter = (request.args.get('status') or '').strip()
    page = max(1, int(request.args.get('page', 1) or 1))
    per_page = 50

    where = ["pc.pathway = 'consulting'"]
    params = []
    if search:
        where.append(
            "(pc.first_name ILIKE ? OR pc.last_name ILIKE ? "
            " OR pc.registration_number ILIKE ? OR pc.email ILIKE ?)"
        )
        params.extend([f'%{search}%'] * 4)
    if product_filter:
        where.append("ps.name = ?")
        params.append(product_filter)
    if status_filter:
        where.append("pc.account_status = ?")
        params.append(status_filter)
    where_sql = " AND ".join(where)

    products = []
    statuses = []
    clients = []
    total = 0

    try:
        try:
            total = conn.execute(
                f"""SELECT COUNT(*) AS c
                    FROM plab_clients pc
                    LEFT JOIN products_services ps ON ps.id = pc.product_id
                    WHERE {where_sql}""",
                params,
            ).fetchone()['c']
        except Exception:
            # product_id missing -- fall back to a simpler query.
            where2 = [w for w in where if 'ps.name' not in w]
            where2_sql = " AND ".join(where2) or "pc.pathway = 'consulting'"
            total = conn.execute(
                f"SELECT COUNT(*) AS c FROM plab_clients pc WHERE {where2_sql}",
                [p for w, p in zip(where, params) if 'ps.name' not in w],
            ).fetchone()['c']

        try:
            clients = conn.execute(
                f"""SELECT pc.id, pc.registration_number, pc.prefix,
                          pc.first_name, pc.last_name, pc.mobile, pc.email,
                          pc.account_status, pc.current_stage, pc.counsellor,
                          pc.final_package, pc.registration_date,
                          ps.name AS product_name
                    FROM plab_clients pc
                    LEFT JOIN products_services ps ON ps.id = pc.product_id
                    WHERE {where_sql}
                    ORDER BY pc.id DESC
                    LIMIT {per_page} OFFSET {(page - 1) * per_page}""",
                params,
            ).fetchall()
        except Exception:
            clients = []

        # Filter dropdowns
        try:
            products = [
                r['name'] for r in conn.execute(
                    "SELECT name FROM products_services "
                    "WHERE COALESCE(pathway, '') = 'consulting' "
                    "  AND COALESCE(status, 'active') = 'active' "
                    "ORDER BY name"
                ).fetchall()
            ]
        except Exception:
            products = []
        try:
            statuses = [
                r['s'] for r in conn.execute(
                    "SELECT DISTINCT COALESCE(NULLIF(TRIM(account_status),''),'Unknown') AS s "
                    " FROM plab_clients WHERE pathway = 'consulting' "
                    "ORDER BY s"
                ).fetchall()
            ]
        except Exception:
            statuses = []
    except Exception as e:
        logging.error(f"ops_consulting_clients_list: {e}")
        flash(f'Error loading clients list: {e}', 'error')
    finally:
        conn.close()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        'ops_consulting_clients.html',
        user=user,
        clients=clients,
        products=products,
        statuses=statuses,
        search=search,
        product_filter=product_filter,
        status_filter=status_filter,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        active_ops_page='consulting-clients',
        active_pathway='consulting',
    )


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
