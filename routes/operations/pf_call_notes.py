"""
routes/operations/pf_call_notes.py — Operations: Portfolio Call Notes list.

Surfaces call-note records from ops_call_notes WHERE pathway='portfolio'.

LEFT JOINs plab_clients so the table shows candidate names alongside the
reg number stored on each note.
"""

import logging
from flask import render_template, flash, request, redirect, url_for

from core.auth import admin_required
from core.users import get_user
from db import get_db


# ── Editable columns on ops_call_notes (pathway='portfolio' scope) ──────────
# Only safe-to-edit columns live here. id / registration_number / pathway are
# never editable through the UI.
PF_CALL_NOTES_EDITABLE_COLUMNS = [
    'call_date',
    'call_note',
    'added_by',
    'contact_type',
    'contacted_status',
]

# Numeric coercion list — any of these that exist on the table get coerced to
# float on save. ops_call_notes has none today but we keep the pattern so the
# template matches the other Portfolio sections.
PF_CALL_NOTES_NUMERIC_COLUMNS = {
    'amount', 'score', 'points', 'duration',
}


# Stage-based follow-up intervals for Portfolio clients (mirrors PLAB's
# STAGE_FOLLOWUP_DAYS pattern). User can adjust these per Portfolio stage
# semantics via Settings later — for now they match PLAB's defaults so the
# urgency math is consistent across pathways.
PF_STAGE_FOLLOWUP_DAYS = {
    # Common stages — adjust here when Portfolio's stage taxonomy is finalised.
    'English Stage':       7,
    'Discovery Stage':     15,
    'Engagement Stage':    15,
    'AHPRA Stage':         30,
    'Job Stage':           30,
}
PF_STAGE_FOLLOWUP_DEFAULT = 15


def _pf_stage_interval(stage):
    return PF_STAGE_FOLLOWUP_DAYS.get(stage or '', PF_STAGE_FOLLOWUP_DEFAULT)


def _pf_categorise(days_since, stage):
    """Mirror PLAB's categorise_by_stage. Urgency bands:
       never / critical / overdue / attention / ok / recent."""
    interval = _pf_stage_interval(stage)
    if days_since is None:
        return 'never'
    if days_since >= interval * 2:
        return 'critical'
    if days_since >= int(interval * 1.5):
        return 'overdue'
    if days_since >= interval:
        return 'attention'
    if days_since >= max(1, interval // 2):
        return 'ok'
    return 'recent'


@admin_required
def ops_portfolio_call_notes_list():
    """Portfolio call notes list — Notes tab.

    Mirrors PLAB pattern: when no filters/tab are present in the query
    string, redirect to the Tracker tab (the more useful default for ops).
    Returns the same render shape PLAB does (records + tracker_data both
    passed) so the unified template can switch on active_tab.
    """
    # Default to tracker view when no explicit tab/filters provided.
    if (not request.args.get('tab')
            and not request.args.get('reg')
            and not request.args.get('client_name')
            and not request.args.get('added_by')
            and not request.args.get('note_search')
            and not request.args.get('q')
            and not request.args.get('client')
            and not request.args.get('page')):
        return redirect(url_for('ops_portfolio_call_notes_tracker'))

    user = get_user()
    conn = get_db()

    # Accept both legacy (q/client) and PLAB (note_search/reg) parameter names.
    reg = (request.args.get('reg') or request.args.get('client') or '').strip()
    client_name = (request.args.get('client_name') or '').strip()
    added_by_filter = (request.args.get('added_by') or '').strip()
    note_search = (request.args.get('note_search') or request.args.get('q') or '').strip()

    page = max(1, request.args.get('page', 1, type=int))
    per_page = 50
    offset = (page - 1) * per_page

    records = []
    added_by_options = []
    total_count = 0

    try:
        sql_base = '''SELECT n.id, n.registration_number, n.call_date, n.call_note,
                             n.added_by, n.contact_type, n.contacted_status, n.pathway,
                             p.first_name, p.last_name, p.prefix
                        FROM ops_call_notes n
                        LEFT JOIN plab_clients p
                               ON n.registration_number = p.registration_number
                              AND COALESCE(p.pathway, 'plab') = 'portfolio'
                       WHERE COALESCE(n.pathway, 'plab') = 'portfolio' '''
        params = []
        if reg:
            sql_base += " AND n.registration_number ILIKE ? "
            params.append(f'%{reg}%')
        if client_name:
            sql_base += """ AND (p.first_name ILIKE ? OR p.last_name ILIKE ?
                OR (p.first_name || ' ' || p.last_name) ILIKE ?
                OR n.registration_number ILIKE ?
                OR (COALESCE(p.prefix,'')||' '||p.first_name||' '||COALESCE(p.last_name,'')) ILIKE ?) """
            params.extend([f'%{client_name}%'] * 5)
        if added_by_filter:
            sql_base += " AND n.added_by = ? "
            params.append(added_by_filter)
        if note_search:
            sql_base += " AND n.call_note ILIKE ? "
            params.append(f'%{note_search}%')

        # Count
        count_sql = "SELECT COUNT(*) AS c FROM (" + sql_base + ") AS sub"
        try:
            total_count = conn.execute(count_sql, params).fetchone()['c']
        except Exception:
            total_count = 0

        records_sql = sql_base + " ORDER BY n.call_date DESC NULLS LAST, n.id DESC LIMIT ? OFFSET ? "
        records = conn.execute(records_sql, params + [per_page, offset]).fetchall()

        added_by_options = [
            r['added_by'] for r in conn.execute(
                """SELECT DISTINCT added_by FROM ops_call_notes
                    WHERE COALESCE(pathway, 'plab') = 'portfolio'
                      AND added_by IS NOT NULL AND added_by != ''
                    ORDER BY added_by"""
            ).fetchall()
        ]
    except Exception as e:
        logging.error(f"ops_portfolio_call_notes_list: {e}")
        flash(f'Error loading Portfolio call notes: {e}', 'error')
    finally:
        try: conn.close()
        except Exception: pass

    total_pages = max(0, (total_count + per_page - 1) // per_page) if total_count else 0
    has_filters = bool(reg or client_name or added_by_filter or note_search)

    return render_template(
        'ops_portfolio_call_notes_list.html',
        user=user,
        # Notes tab data
        records=records,
        added_by_options=added_by_options,
        has_filters=has_filters,
        reg=reg,
        client_name=client_name,
        added_by_filter=added_by_filter,
        note_search=note_search,
        page=page,
        per_page=per_page,
        total_count=total_count,
        total_pages=total_pages,
        # Tracker tab data (empty here — the tracker route fills these)
        tracker_data=[],
        summary={'never': 0, 'critical': 0, 'overdue': 0, 'attention': 0, 'ok': 0, 'recent': 0, 'total': 0},
        gap_filter='',
        search_q='',
        stage_filter='',
        stage_counts={},
        stage_intervals=PF_STAGE_FOLLOWUP_DAYS,
        # Shared
        pathway_name='Portfolio Pathway',
        active_tab='notes',
        active_ops_page='portfolio-call-notes',
        active_pathway='portfolio',
    )


@admin_required
def ops_portfolio_call_notes_tracker():
    """Portfolio Follow-up Tracker — mirrors PLAB ops_call_notes_tracker.

    Aggregates per-client last contact date + counts, categorises by
    stage-specific follow-up interval, returns the same shape PLAB does so
    the unified template can render the tracker view.
    """
    from datetime import date, datetime
    conn = get_db()
    search_q = (request.args.get('q') or '').strip()
    gap_filter = (request.args.get('gap') or '').strip()
    stage_filter = (request.args.get('stage') or '').strip()

    tracker_data = []
    summary = {'never': 0, 'critical': 0, 'overdue': 0, 'attention': 0, 'ok': 0, 'recent': 0, 'total': 0}
    stage_counts = {}

    try:
        sql = '''
            SELECT p.registration_number, p.prefix, p.first_name, p.last_name,
                   p.current_stage, p.mobile, p.account_status,
                   MAX(CASE WHEN COALESCE(n.contacted_status, 'Yes') = 'Yes' THEN n.call_date END) AS last_call_date,
                   COUNT(n.id) AS note_count,
                   COUNT(CASE WHEN COALESCE(n.contacted_status, 'Yes') = 'Yes' THEN 1 END) AS contacted_count,
                   COUNT(CASE WHEN n.contacted_status = 'No' THEN 1 END) AS not_contacted_count,
                   MAX(CASE WHEN COALESCE(n.contacted_status, 'Yes') = 'Yes' THEN n.contact_type END) AS last_contact_type
              FROM plab_clients p
         LEFT JOIN ops_call_notes n
                ON p.registration_number = n.registration_number
               AND COALESCE(n.pathway, 'plab') = 'portfolio'
             WHERE COALESCE(p.pathway, 'plab') = 'portfolio'
               AND p.account_status = 'In Process'
        '''
        params = []
        if stage_filter:
            sql += " AND p.current_stage = ? "
            params.append(stage_filter)
        if search_q:
            sql += """ AND (p.first_name ILIKE ? OR p.last_name ILIKE ?
                OR p.registration_number ILIKE ?
                OR (COALESCE(p.prefix,'') || ' ' || p.first_name || ' ' || COALESCE(p.last_name,'')) ILIKE ?) """
            params.extend([f'%{search_q}%'] * 4)
        sql += '''
            GROUP BY p.registration_number, p.prefix, p.first_name, p.last_name,
                     p.current_stage, p.mobile, p.account_status
            ORDER BY last_call_date ASC NULLS FIRST
        '''
        rows = conn.execute(sql, params).fetchall()

        today = date.today()
        category_counts = {'never': 0, 'critical': 0, 'overdue': 0, 'attention': 0, 'ok': 0, 'recent': 0}
        for row in rows:
            last_call_date = row['last_call_date']
            contacted_count = row['contacted_count'] or 0
            stage = row['current_stage'] or ''
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

            days_since = None
            if not last_call_date or contacted_count == 0:
                category = 'never'
            else:
                try:
                    if isinstance(last_call_date, str):
                        last_call = datetime.strptime(last_call_date, '%Y-%m-%d').date()
                    else:
                        last_call = last_call_date if isinstance(last_call_date, date) else last_call_date.date()
                except Exception:
                    last_call = None
                if last_call:
                    days_since = (today - last_call).days
                    category = _pf_categorise(days_since, stage)
                else:
                    category = 'never'
            category_counts[category] += 1

            name_parts = [row['prefix'] or '', row['first_name'] or '', row['last_name'] or '']
            client_name = ' '.join(p for p in name_parts if p).strip()
            interval = _pf_stage_interval(stage)
            tracker_data.append({
                'registration_number': row['registration_number'],
                'name': client_name,
                'stage': stage,
                'mobile': row['mobile'],
                'last_call_date': last_call_date,
                'note_count': row['note_count'],
                'contacted_count': contacted_count,
                'not_contacted_count': row['not_contacted_count'] or 0,
                'last_contact_type': row['last_contact_type'] or '',
                'days_since': days_since,
                'category': category,
                'followup_interval': interval,
                'days_overdue': max(0, (days_since or 0) - interval) if days_since is not None else None,
            })

        if gap_filter:
            tracker_data = [d for d in tracker_data if d['category'] == gap_filter]

        summary = {
            'never': category_counts['never'],
            'critical': category_counts['critical'],
            'overdue': category_counts['overdue'],
            'attention': category_counts['attention'],
            'ok': category_counts['ok'],
            'recent': category_counts['recent'],
            'total': len(tracker_data) if gap_filter else sum(category_counts.values()),
        }
    except Exception as e:
        logging.error(f"ops_portfolio_call_notes_tracker: {e}")
    finally:
        try: conn.close()
        except Exception: pass

    return render_template(
        'ops_portfolio_call_notes_list.html',
        tracker_data=tracker_data, summary=summary,
        gap_filter=gap_filter, search_q=search_q, stage_filter=stage_filter,
        stage_counts=stage_counts, stage_intervals=PF_STAGE_FOLLOWUP_DAYS,
        records=[], added_by_options=[], has_filters=False,
        reg='', client_name='', added_by_filter='', note_search='',
        page=1, per_page=50, total_count=0, total_pages=0,
        pathway_name='Portfolio Pathway',
        active_tab='tracker',
        active_ops_page='portfolio-call-notes',
        active_pathway='portfolio',
    )


@admin_required
def ops_portfolio_call_notes_not_contacted():
    """Portfolio Not Contacted Tracker — mirrors PLAB ops_call_notes_not_contacted.

    Lists Portfolio clients with at least one contacted_status='No' note,
    bucketed by stage-based urgency just like the tracker view.
    """
    from datetime import date, datetime
    conn = get_db()
    search_q = (request.args.get('q') or '').strip()
    gap_filter = (request.args.get('gap') or '').strip()
    stage_filter = (request.args.get('stage') or '').strip()

    tracker_data = []
    summary = {'never': 0, 'critical': 0, 'overdue': 0, 'attention': 0, 'ok': 0, 'recent': 0, 'total': 0}
    stage_counts = {}

    try:
        sql = '''
            SELECT p.registration_number, p.prefix, p.first_name, p.last_name,
                   p.current_stage, p.mobile, p.account_status,
                   MAX(CASE WHEN COALESCE(n.contacted_status, 'Yes') = 'Yes' THEN n.call_date END) AS last_contact_date,
                   MAX(CASE WHEN n.contacted_status = 'No' THEN n.call_date END) AS last_attempt_date,
                   COUNT(n.id) AS note_count,
                   COUNT(CASE WHEN n.contacted_status = 'No' THEN 1 END) AS not_contacted_count,
                   COUNT(CASE WHEN COALESCE(n.contacted_status, 'Yes') = 'Yes' THEN 1 END) AS contacted_count
              FROM plab_clients p
              INNER JOIN ops_call_notes n
                      ON p.registration_number = n.registration_number
                     AND COALESCE(n.pathway, 'plab') = 'portfolio'
             WHERE COALESCE(p.pathway, 'plab') = 'portfolio'
               AND p.account_status = 'In Process'
               AND EXISTS (SELECT 1 FROM ops_call_notes n2
                            WHERE n2.registration_number = p.registration_number
                              AND COALESCE(n2.pathway, 'plab') = 'portfolio'
                              AND n2.contacted_status = 'No')
        '''
        params = []
        if stage_filter:
            sql += " AND p.current_stage = ? "
            params.append(stage_filter)
        if search_q:
            sql += """ AND (p.first_name ILIKE ? OR p.last_name ILIKE ?
                OR p.registration_number ILIKE ?
                OR (COALESCE(p.prefix,'') || ' ' || p.first_name || ' ' || COALESCE(p.last_name,'')) ILIKE ?) """
            params.extend([f'%{search_q}%'] * 4)
        sql += '''
            GROUP BY p.registration_number, p.prefix, p.first_name, p.last_name,
                     p.current_stage, p.mobile, p.account_status
            ORDER BY last_contact_date ASC NULLS FIRST
        '''
        rows = conn.execute(sql, params).fetchall()

        today = date.today()
        category_counts = {'never': 0, 'critical': 0, 'overdue': 0, 'attention': 0, 'ok': 0, 'recent': 0}
        for row in rows:
            last_contact_date = row['last_contact_date']
            contacted_count = row['contacted_count'] or 0
            stage = row['current_stage'] or ''
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

            days_since = None
            if not last_contact_date or contacted_count == 0:
                category = 'never'
            else:
                try:
                    if isinstance(last_contact_date, str):
                        last_c = datetime.strptime(last_contact_date, '%Y-%m-%d').date()
                    else:
                        last_c = last_contact_date if isinstance(last_contact_date, date) else last_contact_date.date()
                except Exception:
                    last_c = None
                if last_c:
                    days_since = (today - last_c).days
                    category = _pf_categorise(days_since, stage)
                else:
                    category = 'never'
            category_counts[category] += 1

            name_parts = [row['prefix'] or '', row['first_name'] or '', row['last_name'] or '']
            client_name = ' '.join(p for p in name_parts if p).strip()
            interval = _pf_stage_interval(stage)
            tracker_data.append({
                'registration_number': row['registration_number'],
                'name': client_name,
                'stage': stage,
                'mobile': row['mobile'],
                'last_call_date': last_contact_date,
                'last_attempt_date': row['last_attempt_date'],
                'note_count': row['note_count'],
                'not_contacted_count': row['not_contacted_count'] or 0,
                'contacted_count': contacted_count,
                'last_contact_type': '',
                'days_since': days_since,
                'category': category,
                'followup_interval': interval,
                'days_overdue': max(0, (days_since or 0) - interval) if days_since is not None else None,
            })

        if gap_filter:
            tracker_data = [d for d in tracker_data if d['category'] == gap_filter]

        summary = {
            'never': category_counts['never'],
            'critical': category_counts['critical'],
            'overdue': category_counts['overdue'],
            'attention': category_counts['attention'],
            'ok': category_counts['ok'],
            'recent': category_counts['recent'],
            'total': len(tracker_data) if gap_filter else sum(category_counts.values()),
        }
    except Exception as e:
        logging.error(f"ops_portfolio_call_notes_not_contacted: {e}")
    finally:
        try: conn.close()
        except Exception: pass

    return render_template(
        'ops_portfolio_call_notes_list.html',
        tracker_data=tracker_data, summary=summary,
        gap_filter=gap_filter, search_q=search_q, stage_filter=stage_filter,
        stage_counts=stage_counts, stage_intervals=PF_STAGE_FOLLOWUP_DAYS,
        records=[], added_by_options=[], has_filters=False,
        reg='', client_name='', added_by_filter='', note_search='',
        page=1, per_page=50, total_count=0, total_pages=0,
        pathway_name='Portfolio Pathway',
        active_tab='not_contacted',
        active_ops_page='portfolio-call-notes',
        active_pathway='portfolio',
    )


@admin_required
def ops_portfolio_call_notes_detail(rid):
    """Full Portfolio call note view — read-only detail card.

    LEFT JOINs plab_clients via registration_number (pathway='portfolio') so
    the page can show the candidate's name alongside the note metadata.
    """
    user = get_user()
    conn = get_db()
    record = conn.execute(
        """SELECT n.*, p.first_name, p.last_name, p.prefix
             FROM ops_call_notes n
             LEFT JOIN plab_clients p
                    ON n.registration_number = p.registration_number
                   AND COALESCE(p.pathway, 'plab') = 'portfolio'
            WHERE n.id = ?
              AND COALESCE(n.pathway, 'plab') = 'portfolio' """,
        (rid,),
    ).fetchone()
    conn.close()
    if not record:
        flash('Portfolio call note not found.', 'error')
        return redirect(url_for('ops_portfolio_call_notes_list'))
    return render_template(
        'ops_portfolio_call_notes_detail.html',
        user=user,
        record=record,
        pathway_name='Portfolio Pathway',
        active_ops_page='portfolio-call-notes',
        active_pathway='portfolio',
    )


@admin_required
def ops_portfolio_call_notes_edit_page(rid):
    """GET — render the edit form for an Portfolio call note."""
    user = get_user()
    conn = get_db()
    record = conn.execute(
        """SELECT n.*, p.first_name, p.last_name, p.prefix
             FROM ops_call_notes n
        LEFT JOIN plab_clients p
               ON n.registration_number = p.registration_number
              AND COALESCE(p.pathway, 'plab') = 'portfolio'
            WHERE n.id = ?
              AND COALESCE(n.pathway, 'plab') = 'portfolio' """,
        (rid,),
    ).fetchone()
    conn.close()
    if not record:
        flash('Portfolio call note not found.', 'error')
        return redirect(url_for('ops_portfolio_call_notes_list'))
    return render_template(
        'ops_portfolio_call_notes_edit.html',
        user=user,
        record=record,
        pathway_name='Portfolio Pathway',
        active_ops_page='portfolio-call-notes',
        active_pathway='portfolio',
    )


@admin_required
def ops_portfolio_call_notes_edit_save(rid):
    """POST handler: save changes to an Portfolio call note's editable fields.

    Strict allowlist (PF_CALL_NOTES_EDITABLE_COLUMNS). Pathway is NEVER
    updated through this endpoint.
    """
    conn = get_db()
    try:
        existing = conn.execute(
            """SELECT id FROM ops_call_notes
                WHERE id = ?
                  AND COALESCE(pathway, 'plab') = 'portfolio' """,
            (rid,),
        ).fetchone()
        if not existing:
            flash('Portfolio call note not found.', 'error')
            return redirect(url_for('ops_portfolio_call_notes_list'))

        sets = []
        params = []
        for col in PF_CALL_NOTES_EDITABLE_COLUMNS:
            if col in request.form:
                val = request.form.get(col, '').strip()
                if col in PF_CALL_NOTES_NUMERIC_COLUMNS:
                    try:
                        val = float(val) if val else 0
                    except ValueError:
                        val = 0
                sets.append(f"{col} = ?")
                params.append(val)
        if sets:
            params.append(rid)
            conn.execute(
                f"UPDATE ops_call_notes SET {', '.join(sets)} "
                f" WHERE id = ? AND COALESCE(pathway, 'plab') = 'portfolio'",
                params,
            )
            conn.commit()
            flash('Call note saved.', 'success')
        else:
            flash('No changes to save.', 'info')
    except Exception as e:
        logging.error(f"ops_portfolio_call_notes_edit_save: {e}")
        flash(f'Error saving call note: {e}', 'error')
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()

    return redirect(url_for('ops_portfolio_call_notes_detail', rid=rid))


# ── ADD form (mirrors PLAB's /operations/call-notes/add) ────────────────
@admin_required
def ops_portfolio_call_notes_add():
    """GET/POST: Create a new Portfolio call note.

    Mirrors the PLAB call notes form structure: Client autocomplete (scoped
    to pathway='portfolio'), Contacted Yes/No, Contact Type
    (Call/WhatsApp/Email — hidden when Contacted=No), Date (defaults today),
    Added By, Note. New row written with pathway='portfolio'.
    """
    user = get_user()
    if request.method == 'POST':
        registration_number = (request.form.get('registration_number') or '').strip()
        call_date           = (request.form.get('call_date') or '').strip()
        call_note           = (request.form.get('call_note') or '').strip()
        contacted_status    = (request.form.get('contacted_status') or 'Yes').strip()
        contact_type        = (request.form.get('contact_type') or 'Call').strip()
        added_by            = (request.form.get('added_by') or '').strip()

        if not registration_number:
            flash('Please select a client from the suggestions.', 'error')
            return redirect(url_for('ops_portfolio_call_notes_add'))
        if not call_date:
            flash('Date is required.', 'error')
            return redirect(url_for('ops_portfolio_call_notes_add'))
        if not call_note:
            flash('Note is required.', 'error')
            return redirect(url_for('ops_portfolio_call_notes_add'))
        if contacted_status == 'No':
            contact_type = ''  # PLAB JS hides the field — match server-side

        conn = get_db()
        try:
            client = conn.execute(
                "SELECT id FROM plab_clients "
                "WHERE registration_number = ? AND COALESCE(pathway, 'plab') = 'portfolio'",
                (registration_number,),
            ).fetchone()
            if not client:
                flash('Selected client is not an Portfolio Pathway client.', 'error')
                try: conn.rollback()
                except Exception: pass
                return redirect(url_for('ops_portfolio_call_notes_add'))

            conn.execute(
                "INSERT INTO ops_call_notes "
                "(registration_number, call_date, call_note, contacted_status, "
                " contact_type, added_by, created_by, pathway) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'portfolio')",
                (registration_number, call_date, call_note, contacted_status,
                 contact_type, added_by, (user.get('id') if user else None)),
            )
            conn.commit()
            flash('Call note added.', 'success')
        except Exception as e:
            logging.error(f"ops_portfolio_call_notes_add: {e}")
            try: conn.rollback()
            except Exception: pass
            flash(f'Error adding call note: {e}', 'error')
            return redirect(url_for('ops_portfolio_call_notes_add'))
        finally:
            try: conn.close()
            except Exception: pass

        return redirect(url_for('ops_portfolio_call_notes_list'))

    pre_reg = (request.args.get('reg') or '').strip()
    pre_client = None
    if pre_reg:
        conn = get_db()
        try:
            pre_client = conn.execute(
                "SELECT prefix, first_name, last_name FROM plab_clients "
                "WHERE registration_number = ? AND COALESCE(pathway, 'plab') = 'portfolio'",
                (pre_reg,),
            ).fetchone()
        finally:
            try: conn.close()
            except Exception: pass
        if pre_client is None:
            pre_reg = ''

    return render_template(
        'ops_portfolio_call_notes_add.html',
        user=user,
        pre_reg=pre_reg,
        pre_client=pre_client,
        pathway_name='Portfolio Pathway',
        active_ops_page='portfolio-call-notes',
        active_pathway='portfolio',
    )


def register_routes(app):
    """Attach this sub-area's URL rules to the Flask app."""
    app.add_url_rule(
        '/operations/portfolio/call-notes',
        endpoint='ops_portfolio_call_notes_list',
        view_func=ops_portfolio_call_notes_list,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/portfolio/call-notes/<int:rid>',
        endpoint='ops_portfolio_call_notes_detail',
        view_func=ops_portfolio_call_notes_detail,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/portfolio/call-notes/<int:rid>/edit',
        endpoint='ops_portfolio_call_notes_edit_page',
        view_func=ops_portfolio_call_notes_edit_page,
        methods=['GET'],
    )
    app.add_url_rule(
        '/operations/portfolio/call-notes/<int:rid>/edit',
        endpoint='ops_portfolio_call_notes_edit_save',
        view_func=ops_portfolio_call_notes_edit_save,
        methods=['POST'],
    )
    # Add form — mirrors PLAB /operations/call-notes/add structure.
    app.add_url_rule(
        '/operations/portfolio/call-notes/add',
        endpoint='ops_portfolio_call_notes_add',
        view_func=ops_portfolio_call_notes_add,
        methods=['GET', 'POST'],
    )
    # Follow-up Tracker tab — categorises Portfolio "In Process" clients by
    # contact urgency, just like PLAB /operations/call-notes/tracker.
    app.add_url_rule(
        '/operations/portfolio/call-notes/tracker',
        endpoint='ops_portfolio_call_notes_tracker',
        view_func=ops_portfolio_call_notes_tracker,
        methods=['GET'],
    )
    # Not Contacted tab — Portfolio clients with contacted_status='No' notes.
    app.add_url_rule(
        '/operations/portfolio/call-notes/not-contacted',
        endpoint='ops_portfolio_call_notes_not_contacted',
        view_func=ops_portfolio_call_notes_not_contacted,
        methods=['GET'],
    )
