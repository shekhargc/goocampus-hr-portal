"""
routes/hr_payroll_import.py — load past months' salary statements (Excel) into DRAFT payroll (founder 2026-11-13).

Upload one or more monthly salary statements (the "Salary <Month> 26" sheet of the usual .xls) →
preview → confirm. For each month it:
  • creates the month's payroll as a DRAFT (or refreshes an existing draft; finalised/released months
    are never touched — they are only compared),
  • includes exactly the people the statement paid — ex-employees too — and leaves out the rest,
  • adds a salary entry (from that month) for anyone who has none yet (never changes an existing one),
  • copies Salary advance, Other deduction, KLWF and TDS from the statement,
  • uses the statement's paid days (LOP) and its PF / PT / ESI where they differ from the automatic figure,
  • flags every place the statement and the portal disagree (LOP vs leave records, salary entry, net pay).
The founder then reviews and finalises each month by hand.
"""

import calendar
import difflib
import io
import json
import logging
import re
from datetime import datetime, date, timedelta

from flask import render_template, request, redirect, url_for, flash, abort

from core.auth import login_required
from db import get_db
from routes import hr_payroll as P

MAX_FILE = 15 * 1024 * 1024
IMPORT_NOTE = 'From the salary statement'
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS['sept'] = 9

COLS = {  # normalised header → field
    'emlpoyeeslno': 'code', 'employeeslno': 'code', 'empcode': 'code', 'employeecode': 'code',
    'employeename': 'name', 'designation': 'designation', 'dateofjoining': 'doj',
    'wokingdays': 'wd', 'workingdays': 'wd', 'lop': 'lop', 'paiddays': 'paid',
    'basic': 'basic', 'hra': 'hra', 'conveyance': 'conveyance', 'ltc': 'ltc',
    'medicalallowance': 'medical', 'otherallowance': 'other_allowance', 'grosssalary': 'gross',
    'pt': 'pt', 'salaryadvance': 'salary_advance', 'otherdeduction': 'other_deductions', 'klwf': 'klwf',
    'pf': 'pf', 'esi': 'esi', 'tds': 'tds', 'totaldedn': 'total_deductions', 'netsalary': 'net_pay',
}
NUMS = ['wd', 'lop', 'paid', 'basic', 'hra', 'conveyance', 'ltc', 'medical', 'other_allowance', 'gross',
        'pt', 'salary_advance', 'other_deductions', 'klwf', 'pf', 'esi', 'tds', 'total_deductions', 'net_pay']


def _key(v):
    return ''.join(ch for ch in str(v or '').lower() if ch.isalnum())


def _num(v):
    try:
        if v in (None, ''):
            return 0.0
        return float(str(v).replace(',', '').strip())
    except (TypeError, ValueError):
        return 0.0


def _code(v):
    """'0006' / 6.0 / 'GC-006' → 6 (the number part), else None."""
    if v in (None, ''):
        return None
    if isinstance(v, float):
        return int(v) if v.is_integer() and v > 0 else None
    d = re.sub(r'\D', '', str(v))
    return int(d) if d else None


def _norm_name(v):
    return ' '.join(re.sub(r'[^a-z ]', ' ', str(v or '').lower()).split())


# ───────────────────────────── reading the workbook ─────────────────────────────

def _sheets(data, filename):
    """[(sheet_name, rows, to_date)] for .xls (xlrd) or .xlsx (openpyxl)."""
    if filename.lower().endswith('.xlsx'):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            out.append((ws.title, [list(r) for r in ws.iter_rows(values_only=True)],
                        lambda v: v.date() if isinstance(v, datetime) else None))
        return out
    import xlrd
    wb = xlrd.open_workbook(file_contents=data)

    def to_date(v, _m=wb.datemode):
        try:
            return xlrd.xldate_as_datetime(float(v), _m).date() if isinstance(v, float) and v > 20000 else None
        except Exception:
            return None
    return [(sh.name, [sh.row_values(r) for r in range(sh.nrows)], to_date) for sh in wb.sheets()]


def _period_from_name(text):
    """'5 Aug  26  Salary.xls' / 'Salary July 26' → '2026-08'."""
    t = str(text or '').lower()
    mo = None
    for w in re.findall(r'[a-z]+', t):
        if w in MONTHS:
            mo = MONTHS[w]
            break
    yr = re.findall(r'(?<!\d)(20\d\d|\d\d)(?!\d)', t)
    yy = None
    for y in yr:
        n = int(y)
        if n >= 2000:
            yy = n
        elif 20 <= n <= 60:
            yy = 2000 + n
    return f"{yy:04d}-{mo:02d}" if (mo and yy) else None


def _lookup_full(sheets, title_word, code, name, fields):
    """Full-month values for one person from a helper sheet (Template / Attendance)."""
    for sname, rows, _ in sheets:
        if title_word not in sname.lower():
            continue
        hdr, idx = None, {}
        for i, row in enumerate(rows[:15]):
            ks = [_key(c) for c in row]
            if 'employeename' in ks:
                hdr = i
                idx = {k: j for j, k in enumerate(ks) if k}
                break
        if hdr is None:
            continue
        ccol = next((idx[k] for k in ('emlpoyeeslno', 'employeeslno', 'employeecode') if k in idx), None)
        for row in rows[hdr + 1:]:
            if len(row) <= idx['employeename']:
                continue
            rn = _norm_name(row[idx['employeename']])
            rc = _code(row[ccol]) if ccol is not None and ccol < len(row) else None
            if (code and rc == code) or (rn and rn == _norm_name(name)):
                got = {}
                for f, keys in fields.items():
                    for k in keys:
                        if k in idx and idx[k] < len(row) and _num(row[idx[k]]) > 0:
                            got[f] = _num(row[idx[k]])
                            break
                return got
    return {}


def _nice_full(part, frac):
    """Full-month amount behind a part-month figure: the roundest number (100s, 50s, 10s) that still gives
    the statement's figure (±₹1), e.g. 25,651 at 28.5/30 days → 27,000 (not 27,001)."""
    raw = part / frac
    for step in (100, 50, 10):
        c = round(raw / step) * step
        if c > 0 and abs(round(c * frac) - part) <= 1:
            return c
    return round(raw)


def parse_statement(data, filename):
    """Returns (dict(period_file, period_sheet, sheet, rows=[...]), error)."""
    try:
        sheets = _sheets(data, filename)
    except Exception as e:
        logging.warning(f"payroll import read {filename}: {e}")
        return None, f'{filename}: could not read this file (use the .xls / .xlsx salary statement).'
    # The statement sheet = the one whose header has Employee Name + Net Salary + PF / Salary Advance
    # (whatever the tab is called: "Salary April 26", "April 26 Salary", …). Old helper tabs like
    # "Salaries" have no PF / advance columns, so they never qualify.
    def _is_statement(rows):
        for row in rows[:20]:
            ks = {_key(c) for c in row}
            if 'employeename' in ks and 'netsalary' in ks and ({'salaryadvance', 'pf'} & ks):
                return True
        return False
    sal = [s for s in sheets if 'slip' not in s[0].lower() and _is_statement(s[1])]
    sal.sort(key=lambda s: 0 if 'salary' in s[0].lower() and s[0].lower().strip() != 'salaries' else 1)
    if not sal:
        return None, f'{filename}: no salary statement sheet found (needs Employee Name, PF and Net Salary columns).'
    sname, rows, to_date = sal[0]
    hdr, idx, sheet_date = None, {}, None
    for i, row in enumerate(rows[:20]):
        ks = [_key(c) for c in row]
        if any('salarystatement' in k for k in ks):
            for c in row:
                d = to_date(c)
                if d:
                    sheet_date = d
        if 'employeename' in ks:
            hdr = i
            for j, k in enumerate(ks):
                if k in COLS and COLS[k] not in idx:
                    idx[COLS[k]] = j
            break
    need = {'name', 'wd', 'gross', 'net_pay'}
    if hdr is None or not need.issubset(idx):
        return None, f'{filename}: could not find the statement columns (Employee Name, Working Days, Gross, Net).'
    out = []
    for i, row in enumerate(rows[hdr + 1:], start=hdr + 2):
        get = lambda f: row[idx[f]] if f in idx and idx[f] < len(row) else None
        name = ' '.join(str(get('name') or '').split())
        if not name:
            if out:
                break           # first blank row after the people = end of the table (stipends etc. below)
            continue
        if not isinstance(get('wd'), (int, float)) or _num(get('wd')) <= 0:
            continue
        r = {f: _num(get(f)) for f in NUMS}
        r.update(name=name, code=_code(get('code')), line=i, designation=str(get('designation') or '').strip())
        if 'paid' not in idx or (r['paid'] == 0 and r['gross'] > 0):
            r['paid'] = max(0.0, r['wd'] - r['lop'])
        elif abs(r['wd'] - r['lop'] - r['paid']) > 0.01 and r['paid'] > 0:
            # Days don't add up (e.g. May-2026: Working 31, LOP 0, Paid 30). The amounts are worked out on
            # Paid + LOP days, so use that as the month length.
            r['days_note'] = (f"Statement's days don't add up (Working {r['wd']:g}, LOP {r['lop']:g}, Paid {r['paid']:g}) "
                              f"— used a {r['paid'] + r['lop']:g}-day month, which matches its amounts.")
            r['wd'] = r['paid'] + r['lop']
        # Full-month values (for a new salary entry): the row itself when no LOP, else the Template /
        # Attendance sheet, else scaled back from the paid days.
        # The Template / Attendance tabs are often out of date, so a value from them is used only when it
        # explains this row (full × paid ÷ days ≈ the row, ±₹2); otherwise the row is scaled back.
        full = {}
        if r['paid'] >= r['wd'] and r['gross'] > 0:
            full = {k: r[k] for k in ('gross', 'basic', 'hra')}
        elif r['paid'] > 0:
            t = _lookup_full(sheets, 'template', r['code'], name,
                             {'gross': ['salarypermonth', 'grosssalary'], 'basic': ['basic'], 'hra': ['hra']})
            a = _lookup_full(sheets, 'attendance for', r['code'], name, {'gross': ['grosssalary']})
            frac = r['paid'] / r['wd']
            for k in ('gross', 'basic', 'hra'):
                for cand in (a.get(k), t.get(k)):
                    if cand and abs(round(cand * frac) - r[k]) <= 2:
                        full[k] = cand
                        break
                else:
                    full[k] = _nice_full(r[k], frac)
        r['full'] = {k: round(v) for k, v in full.items()}
        out.append(r)
    if not out:
        return None, f'{filename}: the salary sheet has no employee rows.'
    p_file = _period_from_name(filename)
    # The tab name ("August 26 salary") is more reliable than the date cell, which is often left from a copy.
    p_sheet = _period_from_name(sname) or (sheet_date.strftime('%Y-%m') if sheet_date else None)
    return dict(period_file=p_file, period_sheet=p_sheet, sheet=sname, rows=out), None


# ───────────────────────────── matching + plan ─────────────────────────────

def _all_employees(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM employees ORDER BY is_active DESC, name").fetchall()
            if not P._auto_excluded(dict(r))]


def _match(emps, r):
    if r.get('code'):
        hits = [e for e in emps if _code(e.get('emp_code')) == r['code']]
        if len(hits) == 1:
            return hits[0], 'code'
    n = _norm_name(r['name'])
    hits = [e for e in emps if _norm_name(e.get('name')) == n]
    if len(hits) == 1:
        return hits[0], 'name'
    scored = sorted(((difflib.SequenceMatcher(None, n, _norm_name(e.get('name'))).ratio(), e) for e in emps),
                    key=lambda x: -x[0])
    if scored and scored[0][0] >= 0.86 and (len(scored) == 1 or scored[1][0] < scored[0][0] - 0.05):
        return scored[0][1], 'similar name'
    return None, ''


def _fmt(v):
    v = float(v or 0)
    return ('%g' % v)


def build_plan(conn, imp):
    """Preview for one stored import: per row → employee, run status, salary entry, LOP check, deductions."""
    data = json.loads(imp['data'])
    period = imp['period']
    y, m = int(period[:4]), int(period[5:7])
    emps = _all_employees(conn)
    run = conn.execute("SELECT * FROM payroll_runs WHERE period = ?", (period,)).fetchone()
    run = dict(run) if run else None
    rules = P.rules_for(conn, period)
    rows, seen, issues = [], set(), 0
    for r in data['rows']:
        e, how = _match(emps, r)
        item = dict(sheet=r, emp=e, how=how, flags=[], notes=[r['days_note']] if r.get('days_note') else [])
        if not e:
            item['flags'].append('Not found in the portal — this row will be skipped.')
            issues += 1
            rows.append(item)
            continue
        if e['id'] in seen:
            item['flags'].append('Same employee appears twice in the sheet — second row skipped.')
            item['emp'] = None
            rows.append(item)
            continue
        seen.add(e['id'])
        dim, elig = P.eligible_days_for(e, y, m)
        lop_portal, _, _ = P._leave_figures(e['id'], y, m)
        days_ov = None
        if r['wd'] > 0 and abs(r['wd'] - dim) > 0.01:
            days_ov = int(round(r['wd']))
            item['notes'].append(f"Statement counts the month as {days_ov} days ({P.period_label(period)} has {dim}) "
                                 f"— the slip uses {days_ov}, like the statement.")
            dim, elig = P._month_days(dim, elig, days_ov)
        sheet_paid = r['paid']
        lop_sheet = max(0.0, elig - sheet_paid)
        item.update(eligible=elig, dim=dim, lop_portal=lop_portal, lop_use=lop_sheet, days_ov=days_ov)
        if sheet_paid > elig + 0.01:
            item['flags'].append(f"Statement paid {_fmt(sheet_paid)} days but the portal's joining / last-working-day "
                                 f"dates allow only {_fmt(elig)} — check those dates.")
            issues += 1
        elif abs(lop_portal - lop_sheet) > 0.01:
            if lop_portal == 0:
                item['notes'].append(f"No LOP in the portal's leave records — using the statement's "
                                     f"{_fmt(lop_sheet)} LOP day(s).")
            else:
                item['flags'].append(f"LOP does not match: leave records say {_fmt(lop_portal)}, the statement paid "
                                     f"{_fmt(sheet_paid)} of {_fmt(elig)} days ({_fmt(lop_sheet)} LOP). Using the statement.")
                issues += 1
        sal = P.salary_for(conn, e['id'], period)
        full_g = (r.get('full') or {}).get('gross')
        if not sal:
            if full_g:
                item['salary'] = ('add', full_g)
                item['notes'].append(f"No salary entry — will add ₹{P.inr(full_g)}/month from {P.period_label(period)}.")
            else:
                item['salary'] = ('none', 0)
                item['flags'].append('No salary entry and no full-month gross in the sheet — add the salary by hand.')
                issues += 1
        else:
            g = P.rh(sal['monthly_gross'])
            item['salary'] = ('have', g)
            frac = (r['paid'] / r['wd']) if r['wd'] else 0
            explains = frac > 0 and abs(round(g * frac) - r['gross']) <= 2
            if full_g and not explains and abs(g - full_g) > 2:
                if (sal.get('notes') or '').startswith(IMPORT_NOTE):
                    item['salary'] = ('add', full_g)
                    item['notes'].append(f"Salary changed to ₹{P.inr(full_g)} (was ₹{P.inr(g)}) — new entry from "
                                         f"{P.period_label(period)}.")
                else:
                    item['flags'].append(f"Salary entry is ₹{P.inr(g)}/month but the statement implies "
                                         f"₹{P.inr(full_g)} — not changed; fix it under Employee Salaries if needed.")
                    issues += 1
        if not int(e.get('is_active') or 0):
            item['notes'].append('Ex-employee — added to this month.')
        rows.append(item)
    on_payroll = P._payroll_employees(conn)
    left_out = [e for e in on_payroll if e['id'] not in seen and P.eligible_days_for(e, y, m)[1] > 0]
    return dict(imp=imp, data=data, period=period, run=run, rules=rules, rows=rows, left_out=left_out,
                issues=issues, conflict=(data.get('period_file') and data.get('period_sheet')
                                         and data['period_file'] != data['period_sheet']))


# ───────────────────────────── routes ─────────────────────────────

def payroll_import():
    user, deny = P._require_manager()
    if deny:
        return deny
    if request.method == 'GET':
        return render_template('hr_payroll_import.html', user=user, plans=None, active_section='hr',
                               period_label=P.period_label, inr=P.inr)
    files = [f for f in request.files.getlist('statements') if f and f.filename]
    if not files:
        flash('Choose the salary statement file(s) first.', 'error')
        return redirect(url_for('hr_payroll_import'))
    ids, errors = [], []
    conn = get_db()
    try:
        P._ensure(conn)
        for f in files[:12]:
            data = f.read(MAX_FILE + 1)
            if len(data) > MAX_FILE:
                errors.append(f'{f.filename}: too big (max 15 MB).')
                continue
            parsed, err = parse_statement(data, f.filename)
            if err:
                errors.append(err)
                continue
            period = parsed['period_file'] or parsed['period_sheet']
            if not period:
                errors.append(f'{f.filename}: could not tell which month this is — put the month in the file name.')
                continue
            ids.append(P._insert(conn, "INSERT INTO payroll_imports (period, filename, data, created_by_name) "
                                       "VALUES (?, ?, ?, ?)",
                                 (period, f.filename[:200], json.dumps(parsed), user.get('name') or '')))
        conn.commit()
    finally:
        conn.close()
    for e in errors:
        flash(e, 'error')
    if not ids:
        return redirect(url_for('hr_payroll_import'))
    return redirect(url_for('hr_payroll_import_preview', ids=','.join(str(i) for i in ids)))


def _ids_arg(v):
    out = []
    for x in str(v or '').split(','):
        try:
            out.append(int(x))
        except ValueError:
            pass
    return out[:12]


def payroll_import_preview():
    user, deny = P._require_manager()
    if deny:
        return deny
    ids = _ids_arg(request.args.get('ids'))
    conn = get_db()
    try:
        P._ensure(conn)
        imps = [dict(r) for r in conn.execute(
            f"SELECT * FROM payroll_imports WHERE id IN ({','.join('?' * len(ids)) or 'NULL'})", ids).fetchall()]
        imps.sort(key=lambda i: i['period'])
        plans = [build_plan(conn, i) for i in imps]
    finally:
        conn.close()
    if not plans:
        flash('That import has expired — upload the files again.', 'error')
        return redirect(url_for('hr_payroll_import'))
    return render_template('hr_payroll_import.html', user=user, plans=plans, ids=','.join(str(i['id']) for i in imps),
                           active_section='hr', period_label=P.period_label, inr=P.inr, fmt=_fmt,
                           months=_month_choices())


def _month_choices():
    today = P.ist_now().date()
    d, out = date(today.year, today.month, 1), []
    for _ in range(24):
        out.append(d.strftime('%Y-%m'))
        d = (d - timedelta(days=1)).replace(day=1)
    return out


def payroll_import_month(imp_id):
    """Change which month a file is loaded into (e.g. the sheet inside says July but it's August)."""
    user, deny = P._require_manager()
    if deny:
        return deny
    period = (request.form.get('period') or '').strip()[:7]
    try:
        datetime.strptime(period, '%Y-%m')
    except ValueError:
        abort(400)
    conn = get_db()
    try:
        conn.execute("UPDATE payroll_imports SET period = ? WHERE id = ? AND applied_at IS NULL", (period, imp_id))
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for('hr_payroll_import_preview', ids=request.form.get('ids') or str(imp_id)))


def _apply_one(conn, imp, user):
    """Load one month. Returns a result dict for the summary page."""
    plan = build_plan(conn, imp)
    period, label = plan['period'], P.period_label(plan['period'])
    res = dict(period=period, label=label, filename=imp['filename'], rows=[], status='', run_id=None)
    rules = plan['rules']
    if not rules:
        res['status'] = f'Skipped — no salary template covers {label}.'
        return res
    run = plan['run']
    if run and run['status'] != 'draft':
        res.update(status=f'Not changed — {label} is already {run["status"]}. Re-open it first to reload.',
                   run_id=run['id'])
        return res
    who = user.get('name') or ''
    if not run:
        rid = P._insert(conn, "INSERT INTO payroll_runs (period, status, rules_id, created_by_name) "
                              "VALUES (?, 'draft', ?, ?)", (period, rules['id'], who))
        conn.commit()
        run = dict(conn.execute("SELECT * FROM payroll_runs WHERE id = ?", (rid,)).fetchone())
    res['run_id'] = run['id']
    matched = [it for it in plan['rows'] if it['emp']]
    # 1. salary entries for people without one (never changes an existing, hand-made entry)
    for it in matched:
        kind, g = it.get('salary') or ('have', 0)
        if kind != 'add':
            continue
        full = it['sheet'].get('full') or {}
        sal_tmp = {'monthly_gross': g, 'hra_pct': None, 'basic_amount': None, 'hra_amount': None}
        auto = P.split_gross(rules, g, sal_tmp)
        basic_amt = full.get('basic') if full.get('basic') and abs(full['basic'] - auto['basic']) > 1 else None
        if basic_amt:
            sal_tmp['basic_amount'] = basic_amt
            auto = P.split_gross(rules, g, sal_tmp)
        hra_amt = full.get('hra') if full.get('hra') and abs(full['hra'] - auto['hra']) > 1 else None
        conn.execute("INSERT INTO employee_salary (employee_id, effective_from, monthly_gross, basic_amount, hra_amount, "
                     "pt_exempt, pf_exempt, notes, updated_by_name) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)",
                     (it['emp']['id'], period, g, basic_amt, hra_amt,
                      f"{IMPORT_NOTE} ({label}, {imp['filename']})"[:300], who))
    # 2. who is in this month
    conn.execute("DELETE FROM payroll_run_people WHERE run_id = ?", (run['id'],))
    ids = {it['emp']['id'] for it in matched}
    for eid in ids:
        conn.execute("INSERT INTO payroll_run_people (run_id, employee_id, mode) VALUES (?, ?, 'add')", (run['id'], eid))
    for e in P._payroll_employees(conn):
        if e['id'] not in ids:
            conn.execute("INSERT INTO payroll_run_people (run_id, employee_id, mode) VALUES (?, ?, 'skip')",
                         (run['id'], e['id']))
    conn.commit()
    # 3. compute, then put the statement's LOP + deductions on each slip
    P._refresh_run(conn, run, user)
    for it in matched:
        s, eid = it['sheet'], it['emp']['id']
        slip = conn.execute("SELECT * FROM payslips WHERE run_id = ? AND employee_id = ?", (run['id'], eid)).fetchone()
        row = dict(name=it['emp']['name'], flags=list(it['flags']), notes=list(it['notes']),
                   sheet_net=P.rh(s['net_pay']), sheet_gross=P.rh(s['gross']))
        if not slip:
            row['flags'].append('No slip made (no salary entry).')
            res['rows'].append(row)
            continue
        slip = dict(slip)
        try:
            ov = json.loads(slip.get('overrides') or '{}') or {}
        except Exception:
            ov = {}
        for k in ('lop_days', 'pt', 'esi', 'pf', 'days_in_month'):
            ov.pop(k, None)
        if it.get('days_ov'):
            ov['days_in_month'] = it['days_ov']
        if abs(_num(it.get('lop_portal')) - _num(it.get('lop_use'))) > 0.001:
            ov['lop_days'] = it['lop_use']
        ov['tds_set'] = True
        ov['from_statement'] = imp['filename']
        conn.execute("UPDATE payslips SET overrides = ?, tds = ?, klwf = ?, salary_advance = ?, other_deductions = ? "
                     "WHERE id = ?", (json.dumps(ov), s['tds'], s['klwf'], s['salary_advance'], s['other_deductions'],
                                      slip['id']))
        _rebuild(conn, run, eid, user)
        slip = dict(conn.execute("SELECT * FROM payslips WHERE id = ?", (slip['id'],)).fetchone())
        changed = False
        for k in ('pf', 'pt', 'esi'):
            if P.rh(slip[k]) != P.rh(s[k]):
                ov[k] = P.rh(s[k])
                changed = True
        if changed:
            conn.execute("UPDATE payslips SET overrides = ? WHERE id = ?", (json.dumps(ov), slip['id']))
            _rebuild(conn, run, eid, user)
            slip = dict(conn.execute("SELECT * FROM payslips WHERE id = ?", (slip['id'],)).fetchone())
        row.update(net=P.rh(slip['net_pay']), gross=P.rh(slip['gross']), lop=slip['lop_days'], paid=slip['paid_days'])
        if P.rh(slip['gross']) != row['sheet_gross']:
            row['flags'].append(f"Earned gross differs: statement ₹{P.inr(row['sheet_gross'])}, portal "
                                f"₹{P.inr(slip['gross'])} — check the salary entry's Basic / HRA.")
        if P.rh(slip['net_pay']) != row['sheet_net']:
            row['flags'].append(f"Net pay differs: statement ₹{P.inr(row['sheet_net'])}, portal ₹{P.inr(slip['net_pay'])}.")
        res['rows'].append(row)
    for it in plan['rows']:
        if not it['emp']:
            res['rows'].append(dict(name=it['sheet']['name'], flags=it['flags'], notes=[], sheet_net=P.rh(it['sheet']['net_pay'])))
    conn.commit()
    res['left_out'] = [e['name'] for e in plan['left_out']]
    n_ok = sum(1 for r in res['rows'] if not r['flags'])
    res['status'] = f'Loaded as draft — {n_ok} of {len(res["rows"])} match the statement exactly.'
    return res


def _rebuild(conn, run, eid, user):
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (eid,)).fetchone()
    sal = P.salary_for(conn, eid, run['period'])
    rules = P.rules_for(conn, run['period'])
    fresh = conn.execute("SELECT * FROM payslips WHERE run_id = ? AND employee_id = ?", (run['id'], eid)).fetchone()
    if emp and sal and rules and fresh:
        P._build_or_refresh_slip(conn, run, dict(emp), rules, sal, user, dict(fresh))
        conn.commit()


def payroll_import_apply():
    user, deny = P._require_manager()
    if deny:
        return deny
    chosen = []
    for v in request.form.getlist('imp_id'):
        try:
            chosen.append(int(v))
        except ValueError:
            pass
    if not chosen:
        flash('Tick at least one month to load.', 'error')
        return redirect(url_for('hr_payroll_import_preview', ids=request.form.get('ids') or ''))
    conn = get_db()
    results = []
    try:
        P._ensure(conn)
        imps = [dict(r) for r in conn.execute(
            f"SELECT * FROM payroll_imports WHERE id IN ({','.join('?' * len(chosen))}) AND applied_at IS NULL",
            chosen).fetchall()]
        periods = [i['period'] for i in imps]
        dup = {p for p in periods if periods.count(p) > 1}
        for imp in sorted(imps, key=lambda i: (i['period'], i['id'])):
            if imp['period'] in dup:
                results.append(dict(label=P.period_label(imp['period']), filename=imp['filename'], rows=[],
                                    status='Skipped — two files are set to the same month. Fix the month and retry.'))
                continue
            try:
                res = _apply_one(conn, imp, user)
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logging.error(f"payroll import apply {imp['id']}: {e}")
                res = dict(label=P.period_label(imp['period']), filename=imp['filename'], rows=[],
                           status='Could not load this month — nothing more was changed for it. Please tell support.')
            results.append(res)
            conn.execute("UPDATE payroll_imports SET applied_at = CURRENT_TIMESTAMP, applied_by_name = ?, result = ? "
                         "WHERE id = ?", (user.get('name') or '', json.dumps(res, default=str), imp['id']))
            conn.commit()
    finally:
        conn.close()
    return render_template('hr_payroll_import_result.html', user=user, results=results, active_section='hr',
                           inr=P.inr, fmt=_fmt)


def register_hr_payroll_import(app):
    lr = login_required
    for path, endpoint, fn, methods in (
        ('/hr/payroll/import', 'hr_payroll_import', payroll_import, ['GET', 'POST']),
        ('/hr/payroll/import/preview', 'hr_payroll_import_preview', payroll_import_preview, ['GET']),
        ('/hr/payroll/import/<int:imp_id>/month', 'hr_payroll_import_month', payroll_import_month, ['POST']),
        ('/hr/payroll/import/apply', 'hr_payroll_import_apply', payroll_import_apply, ['POST']),
    ):
        app.add_url_rule(path, endpoint=endpoint, view_func=lr(fn), methods=methods)
