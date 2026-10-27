"""UK PGCP (pathway 'plab') — service price list + per-client expense tracking (Step 2 of the
service-cost plan; founder 2026-10-14). Admins only (financial).

Price list  : ops_service_prices — one ₹ price per Section + Service, optionally per Provider
              (a provider-specific price beats the service's general price). Filled by uploading
              the Unique Services Excel with the "Your price (₹)" column → preview → Apply.
Line amount : 1) an ACTUAL amount wins — the team's entered amount (ops_service_meta.amount_spent)
                 or one recorded on the service itself (mentorship amount paid, observership payment);
              2) paid by Client → ₹0 to GooCampus;
              3) paid by GooCampus → list price;
              4) paid by not set → list price, COUNTED AS GOOCAMPUS in spent (founder 2026-10-27); the lines are
                 counted as "paid by not set" so the team can still confirm them;
              5) no price → "not priced" (counted, so gaps are visible).
              Mentorship: the amount recorded on the session (no currency — mostly £60–80 typed as numbers) is
              ignored; the price list (₹10,000) applies unless the team enters an actual ₹ here (founder 2026-10-27).
Per client  : received (ex-GST, same as the refund worksheet: ops_payments) − spent = balance.
              Spent includes the Welcome kit (₹20,000, founder 2026-10-26) for every client whose kit is marked
              Given (plab_clients.welcome_kit_given — empty = Given, like AMC; the client page toggles it).
              Consulting & Operations fee (founder 2026-10-27): one fee for the client's CURRENT stage
              (STAGE_FEES defaults, editable on the Expenses page; stored in ops_service_prices under
              section 'consulting_fee'). Balance = received (ex-GST) − spent − fee.
"""
import io
import json
import logging
import re
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, send_file, session

from core.auth import admin_required
from db import get_db

PATHWAY = 'plab'


def _A():
    import app as _app          # helpers live in the app module (Services Detail / Unique Services)
    return _app


def _is_admin():
    return bool(session.get('is_admin'))


def _who():
    return session.get('name') or session.get('emp_code') or 'admin'


def _norm(s):
    return ' '.join(str(s or '').lower().split())


def _money(v):
    """'₹ 1,500/-' / 1500 / '1500.00' → 1500.0 ; '' / 'NA' / text → None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = re.sub(r'[₹,\s]|/-$|rs\.?|inr', '', str(v), flags=re.I)
    try:
        return float(t) if t not in ('', '-') else None
    except ValueError:
        return None


def _ensure(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS ops_service_prices (
        id SERIAL PRIMARY KEY, pathway TEXT NOT NULL DEFAULT 'plab', section_key TEXT NOT NULL,
        service_key TEXT NOT NULL, provider_key TEXT NOT NULL DEFAULT '',
        service_label TEXT DEFAULT '', provider_label TEXT DEFAULT '', price NUMERIC(14,2) NOT NULL,
        updated_by TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_ops_service_prices "
                 "ON ops_service_prices (pathway, section_key, service_key, provider_key)")
    conn.execute('''CREATE TABLE IF NOT EXISTS ops_service_prices_log (
        id SERIAL PRIMARY KEY, pathway TEXT, section_key TEXT, service_key TEXT, provider_key TEXT,
        old_price NUMERIC(14,2), new_price NUMERIC(14,2), changed_by TEXT DEFAULT '', source TEXT DEFAULT '',
        changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS ops_price_uploads (
        id SERIAL PRIMARY KEY, pathway TEXT, file_name TEXT DEFAULT '', data TEXT,
        uploaded_by TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, applied_at TIMESTAMP)''')
    conn.execute("ALTER TABLE ops_service_meta ADD COLUMN IF NOT EXISTS amount_spent NUMERIC(14,2)")
    conn.commit()
    try:                                  # usually already there (AMC added it); never let it block a page
        if not conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'plab_clients' "
                            "AND column_name = 'welcome_kit_given'").fetchone():
            conn.execute("ALTER TABLE plab_clients ADD COLUMN IF NOT EXISTS welcome_kit_given INTEGER DEFAULT 1")
        conn.commit()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.warning("uk_expenses: welcome_kit_given column: %s", e)


KIT_DEFAULT = 20000.0       # founder 2026-10-26
_KIT_KEY = ('welcome_kit', 'welcome kit', '')


STAGE_FEES = [('English Stage', 200000.0), ('PLAB 1 Stage', 300000.0), ('PLAB 2 Stage', 500000.0),
              ('Job Stage', 500000.0)]           # founder 2026-10-27 — fee for the client's current stage only
_FEE_SECTION = 'consulting_fee'
_EXTRA_LABELS = {_FEE_SECTION: 'Consulting & Operations fee', 'welcome_kit': 'Welcome kit'}


def _stage_fees(conn):
    """[(stage label, fee)] — saved values win over the defaults."""
    saved = {r['service_key']: float(r['price']) for r in conn.execute(
        "SELECT service_key, price FROM ops_service_prices WHERE pathway = ? AND section_key = ?",
        (PATHWAY, _FEE_SECTION)).fetchall()}
    return [(st, saved.get(_norm(st), d)) for st, d in STAGE_FEES]


def _fee_for(fees, stage):
    st = _norm(stage)
    for label, fee in fees:
        if _norm(label) == st:
            return fee
    return 0.0


def _kit_given(v):
    """plab_clients.welcome_kit_given: empty / anything but 0 = Given (same rule as AMC)."""
    return (v is None) or (str(v).strip() not in ('0', '0.0', 'False', 'false'))


def _kit_price(conn):
    r = conn.execute("SELECT price FROM ops_service_prices WHERE pathway = ? AND section_key = ? AND service_key = ? "
                     "AND provider_key = ?", (PATHWAY,) + _KIT_KEY).fetchone()
    return float(r['price']) if r else KIT_DEFAULT


def _kit_map(conn):
    """client id → welcome kit given?"""
    return {r['id']: _kit_given(r['k']) for r in conn.execute(
        "SELECT id, welcome_kit_given AS k FROM plab_clients WHERE COALESCE(pathway,'plab') = 'plab'").fetchall()}


def _prices(conn):
    out = {}
    for r in conn.execute("SELECT section_key, service_key, provider_key, price, service_label, provider_label, "
                          "updated_by, updated_at FROM ops_service_prices WHERE pathway = ?", (PATHWAY,)).fetchall():
        out[(r['section_key'], r['service_key'], r['provider_key'])] = dict(r)
    return out


def _actuals(conn):
    """{(source_table, record_id): amount} entered by the team."""
    out = {}
    for r in conn.execute("SELECT source_table, record_id, amount_spent FROM ops_service_meta "
                          "WHERE amount_spent IS NOT NULL").fetchall():
        out[(r['source_table'], r['record_id'])] = float(r['amount_spent'])
    return out


def _price_line(row, prices, actuals):
    """→ (amount, basis): basis actual | price | estimate | client | unpriced."""
    a = actuals.get((row['source_table'], row['record_id']))
    if a is None and row.get('section_key') not in _IGNORE_RECORDED:
        rec = _money(row.get('amount'))
        a = rec if rec else None
    if a is not None:
        return a, 'actual'
    if row.get('paid_by') == 'Client':
        return 0.0, 'client'
    sec, svc, prov = row['section_key'], _norm(row.get('service')), _norm(row.get('provider'))
    p = prices.get((sec, svc, prov)) or prices.get((sec, svc, ''))
    if p is None:
        return 0.0, 'unpriced'
    return float(p['price']), ('price' if row.get('paid_by') == 'GooCampus' else 'estimate')


_IGNORE_RECORDED = {'mentorship'}     # recorded amounts there have no currency (mostly £) — use the price list


_BASIS_LABEL = {'actual': 'Actual amount', 'price': 'Price list',
                'estimate': 'Price list (paid by not set → counted as GooCampus)',
                'client': 'Paid by client (₹0)', 'unpriced': 'Not priced yet'}


def _client_totals(conn, statuses):
    """Per-client totals for the expenses page / Excel (only clients in the chosen statuses)."""
    A = _A()
    rows, all_statuses, stages = A._plab_services_detail_data(conn, statuses=statuses)
    prices, actuals = _prices(conn), _actuals(conn)
    per = {}
    for r in rows:
        amt, basis = _price_line(r, prices, actuals)
        c = per.setdefault(r['client_id'], {
            'client_id': r['client_id'], 'name': r['name'], 'registration_number': r['registration_number'],
            'status': r['account_status'], 'stage': r['current_stage'], 'lines': 0,
            'spent': 0.0, 'estimate': 0.0, 'to_confirm': 0, 'unpriced': 0, 'client_paid': 0})
        c['lines'] += 1
        if basis in ('actual', 'price', 'estimate'):     # paid by not set counts as GooCampus (founder)
            c['spent'] += amt
        if basis == 'estimate':
            c['estimate'] += amt
            c['to_confirm'] += 1
        elif basis == 'unpriced':
            c['unpriced'] += 1
        else:
            c['client_paid'] += 1
    # clients with no service lines still belong in the list
    for cl in A._plab_filtered_clients(conn, statuses=statuses):
        if cl['id'] not in per:
            per[cl['id']] = {'client_id': cl['id'], 'registration_number': cl.get('registration_number') or '',
                             'name': ' '.join(f"{cl.get('prefix') or ''} {cl.get('first_name') or ''} "
                                              f"{cl.get('last_name') or ''}".split()) or '—',
                             'status': cl.get('account_status') or '', 'stage': cl.get('current_stage') or '',
                             'lines': 0, 'spent': 0.0, 'estimate': 0.0, 'to_confirm': 0, 'unpriced': 0,
                             'client_paid': 0}
    out = []
    kit_price, kits, fees = _kit_price(conn), _kit_map(conn), _stage_fees(conn)
    for c in per.values():
        c['received'] = A._refund_paid_ex_gst(conn, c['registration_number']) if c['registration_number'] else 0.0
        c['kit'] = kit_price if kits.get(c['client_id'], True) else 0.0
        c['services_spent'] = c['spent']
        c['spent'] += c['kit']
        c['fee'] = _fee_for(fees, c['stage'])
        c['balance'] = c['received'] - c['spent'] - c['fee']
        out.append(c)
    out.sort(key=lambda c: c['name'].lower())
    return out, all_statuses, stages


def _deny():
    flash('Expenses are visible to admins only.', 'error')
    return redirect(url_for('ops_main_dashboard'))


# ── pages ────────────────────────────────────────────────────────────────────
@admin_required
def expenses_page():
    if not _is_admin():
        return _deny()
    A = _A()
    f = A._svc_filters(request.args)
    conn = get_db()
    try:
        _ensure(conn)
        clients, statuses, stages = _client_totals(conn, f['statuses'])
        n_prices = conn.execute("SELECT COUNT(*) AS n FROM ops_service_prices WHERE pathway = ?", (PATHWAY,)).fetchone()['n']
        fees = _stage_fees(conn)
    finally:
        conn.close()
    q = _norm(request.args.get('q'))
    if q:
        clients = [c for c in clients if q in _norm(f"{c['name']} {c['registration_number']}")]
    tot = {k: sum(c[k] for c in clients) for k in ('received', 'spent', 'kit', 'fee', 'estimate', 'to_confirm',
                                                    'balance', 'unpriced', 'lines')}
    return render_template('ops_plab_expenses.html', clients=clients, tot=tot, n_prices=n_prices, fees=fees,
                           statuses_all=sorted(set(statuses) | set(A._SVC_DEFAULT_STATUSES)), picked=f['statuses'],
                           status_qs=A._svc_status_qs(f['statuses']), q=request.args.get('q') or '',
                           active_ops_page='plab-expenses')


@admin_required
def expenses_download():
    if not _is_admin():
        return _deny()
    from openpyxl import Workbook
    A = _A()
    f = A._svc_filters(request.args)
    conn = get_db()
    try:
        _ensure(conn)
        clients, _s, _g = _client_totals(conn, f['statuses'])
    finally:
        conn.close()
    headers = ['Client Name', 'Registration Number', 'Status', 'Current Stage', 'Received (ex-GST ₹)',
               'Services spent (₹)', 'Welcome kit (₹)', 'Total spent (₹)', 'Consulting & Operations fee (₹)',
               'Balance (₹)',
               'Of which "paid by" not set (₹)', 'Service lines', 'Lines "paid by" not set', 'Lines not priced',
               'Lines paid by client']
    wb = Workbook(write_only=True)
    ws = A._svc_xl_sheet(wb, 'UK expenses', headers, [28, 22, 14, 22, 16, 16, 14, 16, 18, 14, 20, 10, 14, 12, 12])
    for c in clients:
        ws.append([A._svc_xl_value(c['name']), c['registration_number'], c['status'], c['stage'],
                   round(c['received'], 2), round(c['services_spent'], 2), round(c['kit'], 2), round(c['spent'], 2),
                   round(c['fee'], 2), round(c['balance'], 2), round(c['estimate'], 2), c['lines'], c['to_confirm'], c['unpriced'],
                   c['client_paid']])
    A._svc_xl_filter(ws, len(headers), len(clients))
    return A._svc_xl_send(wb, 'UK_PGCP_Client_Expenses')


@admin_required
def expense_client(client_id):
    """One client's service lines with the amount used and why; the actual ₹ can be corrected."""
    if not _is_admin():
        return _deny()
    A = _A()
    conn = get_db()
    try:
        _ensure(conn)
        cl = conn.execute("SELECT * FROM plab_clients WHERE id = ? AND COALESCE(pathway,'plab') = 'plab'",
                          (client_id,)).fetchone()
        if not cl:
            flash('Client not found.', 'error')
            return redirect(url_for('ops_plab_expenses'))
        cl = dict(cl)
        rows, _s, _g = A._plab_services_detail_data(conn, search=cl.get('registration_number') or '', statuses=[])
        rows = [r for r in rows if r['client_id'] == client_id]
        prices, actuals = _prices(conn), _actuals(conn)
        for r in rows:
            r['amt'], r['basis'] = _price_line(r, prices, actuals)
            r['basis_label'] = _BASIS_LABEL[r['basis']]
            r['team_amount'] = actuals.get((r['source_table'], r['record_id']))
        received = A._refund_paid_ex_gst(conn, cl.get('registration_number') or '')
        kit_price = _kit_price(conn)
        fee = _fee_for(_stage_fees(conn), cl.get('current_stage'))
    finally:
        conn.close()
    kit_given = _kit_given(cl.get('welcome_kit_given'))
    kit = kit_price if kit_given else 0.0
    spent = sum(r['amt'] for r in rows if r['basis'] in ('actual', 'price', 'estimate')) + kit
    est = sum(r['amt'] for r in rows if r['basis'] == 'estimate')
    name = ' '.join(f"{cl.get('prefix') or ''} {cl.get('first_name') or ''} {cl.get('last_name') or ''}".split())
    return render_template('ops_plab_expense_client.html', cl=cl, name=name, rows=rows, received=received,
                           spent=spent, estimate=est, balance=received - spent - fee, fee=fee,
                           stage=cl.get('current_stage') or '', kit=kit, kit_given=kit_given,
                           kit_price=kit_price, to_confirm=sum(1 for r in rows if r['basis'] == 'estimate'),
                           unpriced=sum(1 for r in rows if r['basis'] == 'unpriced'),
                           active_ops_page='plab-expenses')


@admin_required
def expense_amount_save():
    """Set / clear the ACTUAL amount spent on one service line (wins over the price list)."""
    if not _is_admin():
        return _deny()
    A = _A()
    table, cid = (request.form.get('source_table') or '').strip(), int(request.form.get('client_id') or 0)
    allowed = {t for _k, _l, ts in A.PLAB_SERVICE_COLUMNS for t in (ts or [])} | {'plab_client_documents'}
    try:
        rid = int(request.form.get('record_id') or 0)
    except ValueError:
        rid = 0
    raw = (request.form.get('amount') or '').strip()
    amt = _money(raw) if raw else None
    if table not in allowed or not rid or (raw and amt is None):
        flash('Could not save — check the amount.', 'error')
        return redirect(url_for('ops_plab_expense_client', client_id=cid))
    conn = get_db()
    try:
        A._ensure_service_meta(conn)
        _ensure(conn)
        old = conn.execute("SELECT amount_spent FROM ops_service_meta WHERE source_table = ? AND record_id = ?",
                           (table, rid)).fetchone()
        conn.execute("INSERT INTO ops_service_meta (source_table, record_id, amount_spent, updated_by, updated_at) "
                     "VALUES (?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT (source_table, record_id) DO UPDATE SET "
                     "amount_spent = EXCLUDED.amount_spent, updated_by = EXCLUDED.updated_by, "
                     "updated_at = CURRENT_TIMESTAMP", (table, rid, amt, _who()))
        conn.execute("INSERT INTO ops_service_meta_log (source_table, record_id, field, old_value, new_value, changed_by) "
                     "VALUES (?,?,?,?,?,?)", (table, rid, 'amount_spent',
                                              '' if not old or old['amount_spent'] is None else str(old['amount_spent']),
                                              '' if amt is None else str(amt), _who()))
        conn.commit()
        flash('Actual amount saved.' if amt is not None else 'Actual amount cleared — the price list applies again.', 'success')
    except Exception as e:
        conn.rollback(); logging.error("expense_amount_save: %s", e)
        flash('Could not save.', 'error')
    finally:
        conn.close()
    return redirect(url_for('ops_plab_expense_client', client_id=cid))


# ── price list ───────────────────────────────────────────────────────────────
@admin_required
def prices_page():
    if not _is_admin():
        return _deny()
    A = _A()
    conn = get_db()
    try:
        _ensure(conn)
        prices = sorted(_prices(conn).values(),
                        key=lambda p: (p['section_key'], p['service_key'], p['provider_key']))
    finally:
        conn.close()
    labels = {k: l for k, l, _t in A.PLAB_SERVICE_COLUMNS} | _EXTRA_LABELS
    for p in prices:
        p['section'] = labels.get(p['section_key'], p['section_key'])
    return render_template('ops_plab_service_prices.html', prices=prices, preview=None,
                           active_ops_page='plab-expenses')


def _parse_upload(fileobj):
    """The Unique Services Excel → [{section_key, section, service, provider, price, by_service}] + problems."""
    import openpyxl
    A = _A()
    sec_by_label = {_norm(l): k for k, l, _t in A.PLAB_SERVICE_COLUMNS}
    wb = openpyxl.load_workbook(fileobj, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    hdr, idx = None, {}
    for r in rows:                                    # find the header row
        cells = [_norm(x) for x in r]
        if 'section' in cells and 'service' in cells:
            hdr = cells
            break
    if not hdr:
        raise ValueError('Could not find the Section / Service header — upload the Unique Services Excel.')
    for name, test in (('section', lambda h: h == 'section'), ('service', lambda h: h == 'service'),
                       ('provider', lambda h: h.startswith('provider')), ('price', lambda h: 'price' in h)):
        idx[name] = next((i for i, h in enumerate(hdr) if test(h)), None)
    if idx['price'] is None:
        raise ValueError('No "Your price (₹)" column found.')
    items, problems = [], []
    for n, r in enumerate(rows, start=2):
        g = lambda k: (r[idx[k]] if idx[k] is not None and idx[k] < len(r) else None)
        raw_price = g('price')
        if raw_price in (None, ''):
            continue
        price = _money(raw_price)
        sec_l, svc, prov = str(g('section') or '').strip(), str(g('service') or '').strip(), str(g('provider') or '').strip()
        if price is None:
            problems.append(f"Row {n}: price “{raw_price}” is not a number — skipped ({svc})")
            continue
        sk = sec_by_label.get(_norm(sec_l))
        if not sk:
            problems.append(f"Row {n}: unknown section “{sec_l}” — skipped")
            continue
        by_service = bool(re.search(r'\(\+\d+ others?\)\s*$', prov)) or not prov
        prov_clean = '' if by_service else prov
        items.append({'section_key': sk, 'section': sec_l, 'service': svc, 'provider': prov_clean,
                      'service_key': _norm(svc), 'provider_key': _norm(prov_clean), 'price': price})
    return items, problems


@admin_required
def prices_upload():
    """Upload → PREVIEW (nothing saved until Apply)."""
    if not _is_admin():
        return _deny()
    f = request.files.get('file')
    if not f or not f.filename.lower().endswith(('.xlsx', '.xlsm')):
        flash('Choose the Unique Services Excel (.xlsx) with your prices filled in.', 'error')
        return redirect(url_for('ops_plab_service_prices'))
    try:
        items, problems = _parse_upload(io.BytesIO(f.read()))
    except Exception as e:
        flash(f'Could not read the file: {e}', 'error')
        return redirect(url_for('ops_plab_service_prices'))
    conn = get_db()
    try:
        _ensure(conn)
        current = _prices(conn)
        # how many delivered lines each priced row will cover (so you see it matters) — informational only:
        # a problem here must never block the upload
        A = _A()
        cover = {}
        try:
            lines, _s, _g = A._plab_services_detail_data(conn)
            for r in lines:
                k = (r['section_key'], _norm(r.get('service')))
                cover.setdefault(k + (_norm(r.get('provider')),), 0)
                cover[k + (_norm(r.get('provider')),)] += 1
                cover[k + ('',)] = cover.get(k + ('',), 0) + 1
        except Exception as e:
            try: conn.rollback()
            except Exception: pass
            logging.exception("prices_upload: line count skipped: %s", e)
        new = changed = same = 0
        for it in items:
            cur = current.get((it['section_key'], it['service_key'], it['provider_key']))
            it['old'] = float(cur['price']) if cur else None
            it['change'] = 'new' if cur is None else ('same' if abs(float(cur['price']) - it['price']) < 0.005 else 'changed')
            it['lines'] = cover.get((it['section_key'], it['service_key'], it['provider_key']), 0)
            new += it['change'] == 'new'; changed += it['change'] == 'changed'; same += it['change'] == 'same'
        up = conn.execute("INSERT INTO ops_price_uploads (pathway, file_name, data, uploaded_by) VALUES (?,?,?,?) "
                          "RETURNING id", (PATHWAY, f.filename[:200], json.dumps(items), _who())).fetchone()['id']
        conn.commit()
        prices = sorted(current.values(), key=lambda p: (p['section_key'], p['service_key'], p['provider_key']))
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.exception("prices_upload: %s", e)
        flash(f'Could not prepare the preview — {type(e).__name__}: {str(e)[:300]}', 'error')
        return redirect(url_for('ops_plab_service_prices'))
    finally:
        conn.close()
    labels = {k: l for k, l, _t in _A().PLAB_SERVICE_COLUMNS} | _EXTRA_LABELS
    for p in prices:
        p['section'] = labels.get(p['section_key'], p['section_key'])
    return _render_preview(prices, {'id': up, 'items': items, 'problems': problems, 'new': new,
                                    'changed': changed, 'same': same, 'file': f.filename,
                                    'unmatched': sum(1 for i in items if not i['lines'])})


def _render_preview(prices, preview):
    try:
        return render_template('ops_plab_service_prices.html', prices=prices, preview=preview,
                               active_ops_page='plab-expenses')
    except Exception as e:
        logging.exception("prices preview render: %s", e)
        flash(f'Upload #{preview.get("id")} was read ({len(preview.get("items") or [])} prices) but the preview page '
              f'failed — {type(e).__name__}: {str(e)[:300]}', 'error')
        return redirect(url_for('ops_plab_service_prices'))


@admin_required
def prices_apply(upload_id):
    if not _is_admin():
        return _deny()
    conn = get_db()
    try:
        _ensure(conn)
        up = conn.execute("SELECT data, applied_at FROM ops_price_uploads WHERE id = ? AND pathway = ?",
                          (upload_id, PATHWAY)).fetchone()
        if not up or up['applied_at']:
            flash('That upload was already applied (or not found) — upload the file again.', 'error')
            return redirect(url_for('ops_plab_service_prices'))
        items = json.loads(up['data'] or '[]')
        current = _prices(conn)
        n = 0
        for it in items:
            key = (it['section_key'], it['service_key'], it['provider_key'])
            cur = current.get(key)
            if cur and abs(float(cur['price']) - it['price']) < 0.005:
                continue
            conn.execute("INSERT INTO ops_service_prices (pathway, section_key, service_key, provider_key, service_label, "
                         "provider_label, price, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP) "
                         "ON CONFLICT (pathway, section_key, service_key, provider_key) DO UPDATE SET "
                         "price = EXCLUDED.price, service_label = EXCLUDED.service_label, "
                         "provider_label = EXCLUDED.provider_label, updated_by = EXCLUDED.updated_by, "
                         "updated_at = CURRENT_TIMESTAMP",
                         (PATHWAY, *key, it['service'], it['provider'], it['price'], _who()))
            conn.execute("INSERT INTO ops_service_prices_log (pathway, section_key, service_key, provider_key, old_price, "
                         "new_price, changed_by, source) VALUES (?,?,?,?,?,?,?,?)",
                         (PATHWAY, *key, float(cur['price']) if cur else None, it['price'], _who(), f'upload #{upload_id}'))
            n += 1
        conn.execute("UPDATE ops_price_uploads SET applied_at = CURRENT_TIMESTAMP WHERE id = ?", (upload_id,))
        conn.commit()
        flash(f'Price list updated — {n} price(s) saved. Client expenses now use them.', 'success')
    except Exception as e:
        conn.rollback(); logging.error("prices_apply: %s", e)
        flash('Could not apply the prices.', 'error')
    finally:
        conn.close()
    return redirect(url_for('ops_plab_service_prices'))


def current_price_lookup(conn):
    """For the Unique Services Excel: (section_key, service_key, provider_key) → price (pre-fills the column)."""
    try:
        _ensure(conn)
        return {k: float(v['price']) for k, v in _prices(conn).items()}
    except Exception:
        conn.rollback()
        return {}


@admin_required
def stage_fees_save():
    """Save the Consulting & Operations fee per stage (Expenses page form; logged like a price change)."""
    if not _is_admin():
        return _deny()
    conn = get_db()
    try:
        _ensure(conn)
        cur = dict(_stage_fees(conn))
        n = 0
        for i, (label, _d) in enumerate(STAGE_FEES):
            raw = (request.form.get(f'fee_{i}') or '').strip()
            amt = _money(raw)
            if amt is None or abs(amt - cur[label]) < 0.005:
                continue
            key = (PATHWAY, _FEE_SECTION, _norm(label), '')
            conn.execute("INSERT INTO ops_service_prices (pathway, section_key, service_key, provider_key, service_label, "
                         "provider_label, price, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP) "
                         "ON CONFLICT (pathway, section_key, service_key, provider_key) DO UPDATE SET "
                         "price = EXCLUDED.price, updated_by = EXCLUDED.updated_by, updated_at = CURRENT_TIMESTAMP",
                         key + (label, '', amt, _who()))
            conn.execute("INSERT INTO ops_service_prices_log (pathway, section_key, service_key, provider_key, old_price, "
                         "new_price, changed_by, source) VALUES (?,?,?,?,?,?,?,?)",
                         key + (cur[label], amt, _who(), 'stage fee form'))
            n += 1
        conn.commit()
        flash(f'Consulting & Operations fee updated for {n} stage(s).' if n else 'No fee changed.', 'success')
    except Exception as e:
        conn.rollback(); logging.error("stage_fees_save: %s", e)
        flash('Could not save the fees.', 'error')
    finally:
        conn.close()
    return redirect(url_for('ops_plab_expenses'))


@admin_required
def expense_kit_toggle(client_id):
    """Mark this client's Welcome kit as Given / Not given (counts ₹20,000 in spent when Given)."""
    if not _is_admin():
        return _deny()
    given = 1 if request.form.get('given') == '1' else 0
    conn = get_db()
    try:
        _ensure(conn)
        conn.execute("UPDATE plab_clients SET welcome_kit_given = ? WHERE id = ? AND COALESCE(pathway,'plab') = 'plab'",
                     (given, client_id))
        conn.commit()
        logging.info("UK expenses: welcome kit %s for client %s by %s", 'given' if given else 'not given', client_id, _who())
        flash('Welcome kit marked ' + ('Given' if given else 'Not given') + '.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("expense_kit_toggle: %s", e)
        flash('Could not save — please try again.', 'error')
    finally:
        conn.close()
    return redirect(url_for('ops_plab_expense_client', client_id=client_id))


def register_routes(app):
    app.add_url_rule('/operations/plab/expenses', 'ops_plab_expenses', expenses_page, methods=['GET'])
    app.add_url_rule('/operations/plab/expenses/download', 'ops_plab_expenses_download', expenses_download, methods=['GET'])
    app.add_url_rule('/operations/plab/expenses/<int:client_id>', 'ops_plab_expense_client', expense_client, methods=['GET'])
    app.add_url_rule('/operations/plab/expenses/amount', 'ops_plab_expense_amount', expense_amount_save, methods=['POST'])
    app.add_url_rule('/operations/plab/expenses/stage-fees', 'ops_plab_stage_fees', stage_fees_save, methods=['POST'])
    app.add_url_rule('/operations/plab/expenses/<int:client_id>/kit', 'ops_plab_expense_kit', expense_kit_toggle,
                     methods=['POST'])
    app.add_url_rule('/operations/plab/service-prices', 'ops_plab_service_prices', prices_page, methods=['GET'])
    app.add_url_rule('/operations/plab/service-prices/upload', 'ops_plab_service_prices_upload', prices_upload, methods=['POST'])
    app.add_url_rule('/operations/plab/service-prices/apply/<int:upload_id>', 'ops_plab_service_prices_apply',
                     prices_apply, methods=['POST'])
