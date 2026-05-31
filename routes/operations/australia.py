"""
routes/operations/australia.py — Operations: Australia Pathway sub-area.

Replaces the placeholder /operations/australia-pathway route from app.py.

Australia Pathway uses the v2 client management architecture (the same flow
used by all new pathways under Operations):
  - clients live in `client_registrations` filtered by product_id
  - the registration / form / sales / ops verification flow is shared
  - per-pathway customisation lives in `client_form_configs` (per product)

This dashboard surfaces Australia-specific stats by filtering
`client_registrations` to products whose name matches 'Australia' (case
insensitive) — so as soon as the admin adds an "Australia Pathway" product
via /products UI, those clients start showing up here automatically.

Endpoint name preserved: ops_australia_pathway (matches existing url_for
calls and sidebar links — no app.py call-site changes needed).
"""

import logging
from flask import render_template, flash

from core.auth import admin_required
from core.users import get_user
from db import get_db


def _australia_product_ids(conn):
    """Return product ids whose name includes 'Australia' (case-insensitive).

    Returns [] if no such product exists yet (e.g. admin hasn't added the
    'Australia Pathway' product through the UI yet). The dashboard renders
    zeros in that case.
    """
    rows = conn.execute(
        "SELECT id FROM products_services WHERE LOWER(name) LIKE ?",
        ('%australia%',),
    ).fetchall()
    return [r['id'] for r in rows]


@admin_required
def ops_australia_pathway():
    """Australia Pathway dashboard — v2 client stats filtered to Australia products."""
    user = get_user()
    conn = get_db()

    # Default empty state — keeps the page renderable if the products table
    # or v2 tables aren't fully set up on this environment.
    stats = {
        'total_clients': 0,
        'product_configured': False,
        'product_names': [],
        'form_status': {},     # {status: count}  draft / submitted
        'ops_status': {},      # {status: count}  pending / verified / etc
        'onboarding_status': {},  # {status: count} pending / confirmed
        'recent_submissions': [],
        'pending_ops_verifications': [],
        'invitations_total': 0,
        'invitations_pending': 0,
    }

    try:
        prod_ids = _australia_product_ids(conn)
        product_rows = conn.execute(
            "SELECT id, name FROM products_services WHERE LOWER(name) LIKE ?",
            ('%australia%',),
        ).fetchall()
        stats['product_configured'] = bool(prod_ids)
        stats['product_names'] = [r['name'] for r in product_rows]

        if prod_ids:
            placeholders = ','.join(['?'] * len(prod_ids))

            # ── Totals ──
            stats['total_clients'] = conn.execute(
                f"SELECT COUNT(*) AS c FROM client_registrations WHERE product_id IN ({placeholders})",
                prod_ids,
            ).fetchone()['c']

            # ── Form status breakdown (draft / submitted) ──
            for row in conn.execute(
                f"""SELECT COALESCE(form_status, 'unknown') AS s, COUNT(*) AS c
                    FROM client_registrations WHERE product_id IN ({placeholders})
                    GROUP BY form_status""",
                prod_ids,
            ).fetchall():
                stats['form_status'][row['s']] = row['c']

            # ── Ops status breakdown ──
            for row in conn.execute(
                f"""SELECT COALESCE(ops_status, 'pending') AS s, COUNT(*) AS c
                    FROM client_registrations WHERE product_id IN ({placeholders})
                    GROUP BY ops_status""",
                prod_ids,
            ).fetchall():
                stats['ops_status'][row['s']] = row['c']

            # ── Onboarding status breakdown ──
            for row in conn.execute(
                f"""SELECT COALESCE(onboarding_status, 'pending') AS s, COUNT(*) AS c
                    FROM client_registrations WHERE product_id IN ({placeholders})
                    GROUP BY onboarding_status""",
                prod_ids,
            ).fetchall():
                stats['onboarding_status'][row['s']] = row['c']

            # ── Recent submissions (last 5) ──
            stats['recent_submissions'] = conn.execute(
                f"""SELECT id, registration_number, prefix, first_name, last_name,
                           form_status, ops_status, onboarding_status,
                           client_submitted_at, created_at
                    FROM client_registrations
                    WHERE product_id IN ({placeholders})
                    ORDER BY COALESCE(client_submitted_at, created_at) DESC
                    LIMIT 5""",
                prod_ids,
            ).fetchall()

            # ── Pending ops verifications (submitted but not verified) ──
            stats['pending_ops_verifications'] = conn.execute(
                f"""SELECT id, registration_number, prefix, first_name, last_name,
                           client_submitted_at, sales_completed, sales_completed_at
                    FROM client_registrations
                    WHERE product_id IN ({placeholders})
                      AND form_status = 'submitted'
                      AND (ops_status IS NULL OR ops_status = 'pending')
                    ORDER BY client_submitted_at ASC
                    LIMIT 10""",
                prod_ids,
            ).fetchall()

            # ── Invitations stats ──
            stats['invitations_total'] = conn.execute(
                f"SELECT COUNT(*) AS c FROM client_invitations WHERE product_id IN ({placeholders})",
                prod_ids,
            ).fetchone()['c']
            stats['invitations_pending'] = conn.execute(
                f"""SELECT COUNT(*) AS c FROM client_invitations
                    WHERE product_id IN ({placeholders}) AND status = 'pending'""",
                prod_ids,
            ).fetchone()['c']

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
