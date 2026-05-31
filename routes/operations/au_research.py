"""
routes/operations/au_research.py — Operations: Australia Research & Publication list.

Surfaces ops_research_publication rows WHERE pathway='australia'. LEFT JOINs
plab_clients on registration_number so the candidate name displays even when
records came in from the bulk Excel import (import_australia_research.py).
"""

import logging
from flask import render_template, flash, request

from core.auth import admin_required
from core.users import get_user
from db import get_db


@admin_required
def ops_australia_research_list():
    """Australia research & publication list — ops_research_publication WHERE pathway='australia'."""
    user = get_user()
    conn = get_db()

    search = (request.args.get('q', '') or '').strip()
    status_filter = (request.args.get('status', '') or '').strip()
    provider_filter = (request.args.get('provider', '') or '').strip()
    batch_filter = (request.args.get('batch', '') or '').strip()
    reg = (request.args.get('client', '') or '').strip()

    records = []
    statuses = []
    providers = []
    batches = []
    total = 0

    try:
        sql = '''SELECT r.id, r.registration_number, r.research_status,
                        r.research_topic, r.research_start_date,
                        r.research_end_date, r.research_provider,
                        r.research_batch, r.published_journal_name,
                        r.author_position, r.published_copy,
                        p.first_name, p.last_name, p.prefix
                   FROM ops_research_publication r
                   LEFT JOIN plab_clients p
                          ON r.registration_number = p.registration_number
                  WHERE r.pathway = 'australia' '''
        params = []
        if reg:
            sql += " AND r.registration_number = ? "
            params.append(reg)
        if status_filter:
            sql += " AND r.research_status = ? "
            params.append(status_filter)
        if provider_filter:
            sql += " AND r.research_provider = ? "
            params.append(provider_filter)
        if batch_filter:
            sql += " AND r.research_batch = ? "
            params.append(batch_filter)
        if search:
            sql += """ AND (
                p.first_name LIKE ? OR p.last_name LIKE ? OR
                r.research_topic LIKE ? OR r.registration_number LIKE ? OR
                r.published_journal_name LIKE ?
            ) """
            params.extend([f'%{search}%'] * 5)
        sql += " ORDER BY COALESCE(r.research_start_date, '') DESC NULLS LAST, r.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        statuses = [
            r['research_status'] for r in conn.execute(
                """SELECT DISTINCT research_status FROM ops_research_publication
                    WHERE pathway = 'australia' AND research_status IS NOT NULL
                      AND research_status != ''
                    ORDER BY research_status"""
            ).fetchall()
        ]
        providers = [
            r['research_provider'] for r in conn.execute(
                """SELECT DISTINCT research_provider FROM ops_research_publication
                    WHERE pathway = 'australia' AND research_provider IS NOT NULL
                      AND research_provider != ''
                    ORDER BY research_provider"""
            ).fetchall()
        ]
        batches = [
            r['research_batch'] for r in conn.execute(
                """SELECT DISTINCT research_batch FROM ops_research_publication
                    WHERE pathway = 'australia' AND research_batch IS NOT NULL
                      AND research_batch != ''
                    ORDER BY research_batch"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_australia_research_list: {e}")
        flash(f'Error loading Australia research records: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_australia_research_list.html',
        user=user,
        records=records,
        total=total,
        search=search,
        status_filter=status_filter,
        provider_filter=provider_filter,
        batch_filter=batch_filter,
        client_reg=reg,
        statuses=statuses,
        providers=providers,
        batches=batches,
        pathway_name='Australia Pathway',
        active_ops_page='australia-research',
        active_pathway='australia',
    )


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/australia/research',
        endpoint='ops_australia_research_list',
        view_func=ops_australia_research_list,
        methods=['GET'],
    )
