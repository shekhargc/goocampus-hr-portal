"""
routes/operations/call_notes_report.py — shared Call Notes "Reports" tab.

ONE report engine for every pathway (plab / consulting / uae / australia /
portfolio / training), added as a "Reports" tab after Notes.

Filters:  date range (from / to) + team member (added_by).
          The date is an "effective date": a valid YYYY-MM-DD call_date, else
          the date the note was saved (created_at) — because call_date is a
          free-text column that's often blank or oddly formatted.
Breakdowns: by team member, by client stage, by contact type (+ contacted
          yes/no). Plus a CSV export of the filtered notes.
"""

import csv
import io
import logging
from datetime import date, timedelta

from flask import render_template, request, Response

from core.auth import admin_required
from db import get_db

# pathway -> (label, base URL path shared with the call-notes tab bar)
_CFG = {
    'plab':       ('PLAB',       '/operations/call-notes'),
    'consulting': ('Consulting', '/operations/consulting/call-notes'),
    'uae':        ('UAE',        '/operations/uae/call-notes'),
    'australia':  ('Australia',  '/operations/australia/call-notes'),
    'portfolio':  ('Portfolio',  '/operations/portfolio/call-notes'),
    'training':   ('Training',   '/operations/training/call-notes'),
}

# Effective date: valid YYYY-MM-DD call_date, else the saved (created_at) date.
_EFF = ("CASE WHEN call_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' "
        "THEN LEFT(call_date, 10)::date ELSE created_at::date END")


def _report(pathway):
    label, base = _CFG.get(pathway, ('', ''))
    today = date.today()
    d_to = (request.args.get('to') or today.isoformat()).strip()
    d_from = (request.args.get('from') or (today - timedelta(days=30)).isoformat()).strip()
    added_by = (request.args.get('added_by') or '').strip()

    conn = get_db()
    rows, added_by_options = [], []
    try:
        added_by_options = [r['added_by'] for r in conn.execute(
            "SELECT DISTINCT added_by FROM ops_call_notes "
            "WHERE COALESCE(pathway,'plab') = ? AND added_by IS NOT NULL AND added_by <> '' "
            "ORDER BY added_by", (pathway,)).fetchall()]

        sql = (
            "SELECT n.id, n.registration_number, n.added_by, n.contacted_status, n.contact_type, "
            "       n.call_note, n.call_date, n.created_at, n.eff_date, "
            "       TRIM(COALESCE(p.prefix,'')||' '||COALESCE(p.first_name,'')||' '||COALESCE(p.last_name,'')) AS client_name, "
            "       COALESCE(NULLIF(TRIM(p.current_stage),''), NULLIF(TRIM(p.joined_stage),''), 'Unstaged') AS stage "
            "FROM (SELECT *, " + _EFF + " AS eff_date FROM ops_call_notes "
            "      WHERE COALESCE(pathway,'plab') = ?) n "
            "LEFT JOIN plab_clients p ON n.registration_number = p.registration_number "
            "WHERE n.eff_date BETWEEN ?::date AND ?::date ")
        params = [pathway, d_from, d_to]
        if added_by:
            sql += "AND n.added_by = ? "
            params.append(added_by)
        sql += "ORDER BY n.eff_date DESC, n.id DESC"
        rows = conn.execute(sql, params).fetchall()
    except Exception as e:
        logging.error(f"call_notes_report {pathway}: {e}")
    conn.close()

    total = len(rows)
    clients = len({r['registration_number'] for r in rows})
    yes = sum(1 for r in rows if (r['contacted_status'] or 'Yes') == 'Yes')
    no = sum(1 for r in rows if r['contacted_status'] == 'No')

    def _acc(key_fn):
        d = {}
        for r in rows:
            k = key_fn(r) or '—'
            e = d.setdefault(k, {'notes': 0, 'clients': set(), 'no': 0})
            e['notes'] += 1
            e['clients'].add(r['registration_number'])
            if r['contacted_status'] == 'No':
                e['no'] += 1
        out = [{'key': k, 'notes': v['notes'], 'clients': len(v['clients']), 'no': v['no']}
               for k, v in d.items()]
        out.sort(key=lambda x: x['notes'], reverse=True)
        return out

    by_member = _acc(lambda r: r['added_by'] or 'Unknown')
    by_stage = _acc(lambda r: r['stage'] or 'Unstaged')
    by_type = _acc(lambda r: r['contact_type'] or 'Call')

    if request.args.get('export') == '1':
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['Date', 'Client', 'Reg number', 'Added by', 'Contact type', 'Contacted', 'Note'])
        for r in rows:
            w.writerow([str(r['eff_date'] or ''), r['client_name'] or '', r['registration_number'] or '',
                        r['added_by'] or '', r['contact_type'] or '', r['contacted_status'] or 'Yes',
                        (r['call_note'] or '').replace('\r', ' ').replace('\n', ' ')])
        fname = f"call_notes_{pathway}_{d_from}_to_{d_to}.csv"
        return Response(buf.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename={fname}'})

    return render_template(
        'ops_call_notes_report.html',
        pathway=pathway, label=label, base=base,
        d_from=d_from, d_to=d_to, added_by=added_by, added_by_options=added_by_options,
        kpi={'total': total, 'clients': clients, 'yes': yes, 'no': no},
        by_member=by_member, by_stage=by_stage, by_type=by_type,
        active_ops_page='call-notes')


def _make_view(pathway):
    def v():
        return _report(pathway)
    v.__name__ = f'ops_{pathway}_call_notes_report'
    return admin_required(v)


def register_routes(app):
    """Attach the shared /…/call-notes/report route for every pathway."""
    specs = [
        ('plab',       '/operations/call-notes/report',            'ops_call_notes_report'),
        ('consulting', '/operations/consulting/call-notes/report', 'ops_consulting_call_notes_report'),
        ('uae',        '/operations/uae/call-notes/report',        'ops_uae_call_notes_report'),
        ('australia',  '/operations/australia/call-notes/report',  'ops_australia_call_notes_report'),
        ('portfolio',  '/operations/portfolio/call-notes/report',  'ops_portfolio_call_notes_report'),
        ('training',   '/operations/training/call-notes/report',   'ops_training_call_notes_report'),
    ]
    for pathway, path, endpoint in specs:
        app.add_url_rule(path, endpoint=endpoint, view_func=_make_view(pathway), methods=['GET'])
