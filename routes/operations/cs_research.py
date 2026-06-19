"""
routes/operations/au_research.py — Operations: Consulting Research & Publication.

Surfaces ops_research_publication rows WHERE pathway='consulting'. LEFT JOINs
plab_clients on registration_number so the candidate name displays even when
records came in from the bulk Excel import (import_consulting_research.py).

Also exposes detail + edit pages so the section mirrors the Registration list
pattern (drawer on the list, full detail page, edit form). Same UI as PLAB.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db
# Pathway-scoped dropdown options for the AMC Research & Publication edit form.
from routes.operations._form_lookups import section_research_lookups


# Columns on ops_research_publication that the edit form can write to.
# id / registration_number / pathway are NOT editable through the UI.
AU_RESEARCH_EDITABLE_COLUMNS = [
    'research_status',
    'research_start_date',
    'research_topic',
    'research_batch',
    'research_end_date',
    'research_provider',
    # Deliverable that cascades from the chosen Research Provider (vendor).
    'service',
    'published_journal_name',
    'author_position',
    'upload_published_copy',
]

# Coerce these to float on save (others stay as strings).
AU_RESEARCH_NUMERIC_COLUMNS = {
    'amount', 'score', 'points', 'duration',
}


@admin_required
def ops_consulting_research_list():
    """Consulting research & publication list — ops_research_publication WHERE pathway='consulting'."""
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
                  WHERE r.pathway = 'consulting' '''
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
        # Recent-first: newest research_start_date on top, NULLs at the bottom,
        # then id DESC as a tiebreaker (user request 2026-06-01).
        sql += " ORDER BY r.research_start_date DESC NULLS LAST, r.id DESC "
        records = conn.execute(sql, params).fetchall()
        total = len(records)

        statuses = [
            r['research_status'] for r in conn.execute(
                """SELECT DISTINCT research_status FROM ops_research_publication
                    WHERE pathway = 'consulting' AND research_status IS NOT NULL
                      AND research_status != ''
                    ORDER BY research_status"""
            ).fetchall()
        ]
        providers = [
            r['research_provider'] for r in conn.execute(
                """SELECT DISTINCT research_provider FROM ops_research_publication
                    WHERE pathway = 'consulting' AND research_provider IS NOT NULL
                      AND research_provider != ''
                    ORDER BY research_provider"""
            ).fetchall()
        ]
        batches = [
            r['research_batch'] for r in conn.execute(
                """SELECT DISTINCT research_batch FROM ops_research_publication
                    WHERE pathway = 'consulting' AND research_batch IS NOT NULL
                      AND research_batch != ''
                    ORDER BY research_batch"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_consulting_research_list: {e}")
        flash(f'Error loading Consulting research records: {e}', 'error')
    finally:
        conn.close()

    return render_template(
        'ops_consulting_research_list.html',
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
        pathway_name='Standard Consulting',
        active_ops_page='consulting-research',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_research_detail(rid):
    """Read-only Consulting research record detail.

    Mirrors the PLAB client detail layout: header card + Edit button on top,
    two-column grid of read-only fields below. LEFT JOIN plab_clients on
    registration_number (pathway='consulting' scope) so the candidate name
    is shown even when the research row came in from the bulk import.
    """
    user = get_user()
    conn = get_db()
    record = None
    try:
        record = conn.execute(
            """SELECT r.*,
                      p.first_name, p.last_name, p.prefix,
                      p.mobile, p.email
                 FROM ops_research_publication r
            LEFT JOIN plab_clients p
                   ON r.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'consulting'
                WHERE r.id = ?
                  AND COALESCE(r.pathway, 'plab') = 'consulting' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_consulting_research_detail: {e}")
    finally:
        conn.close()

    if not record:
        flash('Consulting research record not found.', 'error')
        return redirect(url_for('ops_consulting_research_list'))

    return render_template(
        'ops_consulting_research_detail.html',
        user=user,
        record=record,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-research',
        active_pathway='consulting',
    )


@admin_required
def ops_consulting_research_edit_page(rid):
    """GET — render the edit form for an Consulting research record."""
    user = get_user()
    conn = get_db()
    record = None
    try:
        record = conn.execute(
            """SELECT r.*,
                      p.first_name, p.last_name, p.prefix
                 FROM ops_research_publication r
            LEFT JOIN plab_clients p
                   ON r.registration_number = p.registration_number
                  AND COALESCE(p.pathway, 'plab') = 'consulting'
                WHERE r.id = ?
                  AND COALESCE(r.pathway, 'plab') = 'consulting' """,
            (rid,),
        ).fetchone()
    except Exception as e:
        logging.error(f"ops_consulting_research_edit_page: {e}")
    finally:
        conn.close()

    if not record:
        flash('Consulting research record not found.', 'error')
        return redirect(url_for('ops_consulting_research_list'))

    return render_template(
        'ops_consulting_research_edit.html',
        user=user,
        record=record,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-research',
        active_pathway='consulting',
        # Dropdown options sourced from lookup_options where pathway='consulting'.
        **section_research_lookups('consulting'),
    )


@admin_required
def ops_consulting_research_edit_save(rid):
    """POST handler: save edits to an Consulting research record.

    Strict allowlist (AU_RESEARCH_EDITABLE_COLUMNS). pathway is never
    updated. Numeric columns get float-coerced (bad input becomes 0).
    """
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM ops_research_publication "
            "WHERE id = ? AND COALESCE(pathway, 'plab') = 'consulting'",
            (rid,),
        ).fetchone()
        if not existing:
            flash('Consulting research record not found.', 'error')
            return redirect(url_for('ops_consulting_research_list'))

        # Discover which columns actually exist on this DB — guards against
        # older schemas missing optional columns (e.g. upload_published_copy).
        try:
            db_cols = {
                row['name'] for row in conn.execute(
                    "PRAGMA table_info(ops_research_publication)"
                ).fetchall()
            }
        except Exception:
            db_cols = set(AU_RESEARCH_EDITABLE_COLUMNS)

        sets, params = [], []
        for col in AU_RESEARCH_EDITABLE_COLUMNS:
            if col not in request.form:
                continue
            if db_cols and col not in db_cols:
                # Skip silently — column not present in this environment.
                continue
            val = request.form.get(col, '').strip()
            if col in AU_RESEARCH_NUMERIC_COLUMNS:
                try:
                    val = float(val) if val else 0
                except ValueError:
                    val = 0
            sets.append(f"{col} = ?")
            params.append(val)

        if sets:
            params.append(rid)
            conn.execute(
                "UPDATE ops_research_publication SET "
                + ', '.join(sets)
                + " WHERE id = ? AND COALESCE(pathway, 'plab') = 'consulting'",
                params,
            )
            conn.commit()
            flash('Research record saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_consulting_research_edit_save: {e}")
        flash(f'Error saving research record: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_consulting_research_detail', rid=rid))


@admin_required
def ops_consulting_research_add_page():
    """GET — render the empty add form (reuses the edit template)."""
    user = get_user()
    empty_record = {col: None for col in AU_RESEARCH_EDITABLE_COLUMNS}
    empty_record['id'] = None
    empty_record['registration_number'] = ''
    empty_record['first_name'] = ''
    empty_record['last_name'] = ''
    empty_record['prefix'] = ''
    return render_template(
        'ops_consulting_research_edit.html',
        user=user,
        record=empty_record,
        is_new=True,
        pathway_name='Standard Consulting',
        active_ops_page='consulting-research',
        active_pathway='consulting',
        # Dropdown options sourced from lookup_options where pathway='consulting'.
        **section_research_lookups('consulting'),
    )


@admin_required
def ops_consulting_research_add_save():
    """POST — insert a new Consulting research / publication row."""
    conn = get_db()
    try:
        reg = (request.form.get('registration_number') or '').strip()
        if not reg:
            flash('Registration number is required.', 'error')
            return redirect(url_for('ops_consulting_research_add_page'))
        # Discover live columns (older schemas may not have upload_published_copy).
        try:
            db_cols = {
                row['name'] for row in conn.execute(
                    "PRAGMA table_info(ops_research_publication)"
                ).fetchall()
            }
        except Exception:
            db_cols = set(AU_RESEARCH_EDITABLE_COLUMNS)
        cols = ['registration_number', 'pathway']
        vals = [reg, 'consulting']
        for col in AU_RESEARCH_EDITABLE_COLUMNS:
            if col not in request.form:
                continue
            if db_cols and col not in db_cols:
                continue
            v = (request.form.get(col) or '').strip() or None
            if col in AU_RESEARCH_NUMERIC_COLUMNS:
                try:
                    v = float(v) if v else None
                except ValueError:
                    v = None
            cols.append(col)
            vals.append(v)
        placeholders = ', '.join(['?'] * len(cols))
        cur = conn.execute(
            f"INSERT INTO ops_research_publication ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
            vals,
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        flash('Research record added.', 'success')
        return redirect(url_for('ops_consulting_research_detail', rid=new_id))
    except Exception as e:
        logging.error(f"ops_consulting_research_add_save: {e}")
        flash(f'Error: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
        return redirect(url_for('ops_consulting_research_list'))
    finally:
        conn.close()


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/consulting/research',
        endpoint='ops_consulting_research_list',
        view_func=ops_consulting_research_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/research/<int:rid>',
        endpoint='ops_consulting_research_detail',
        view_func=ops_consulting_research_detail,
        methods=['GET'],
    )
    # Add (GET form + POST save)
    app.add_url_rule(
        '/operations/consulting/research/add',
        endpoint='ops_consulting_research_add_page',
        view_func=ops_consulting_research_add_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/consulting/research/add',
        endpoint='ops_consulting_research_add_save',
        view_func=ops_consulting_research_add_save,
        methods=['POST'],
    )
    # Edit page (GET) — renders the form
    app.add_url_rule(
        '/operations/consulting/research/<int:rid>/edit',
        endpoint='ops_consulting_research_edit_page',
        view_func=ops_consulting_research_edit_page,
        methods=['GET'],
    )
    # Save (POST) — same URL, different method, separate endpoint
    app.add_url_rule(
        '/operations/consulting/research/<int:rid>/edit',
        endpoint='ops_consulting_research_edit_save',
        view_func=ops_consulting_research_edit_save,
        methods=['POST'],
    )
