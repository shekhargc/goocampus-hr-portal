"""
routes/hr_payroll.py — HR › Payroll & Payslips (founder 2026-11-12).

What it does
  1. Salary Template (payroll_rules): the FY rules that split a monthly gross into
     Basic / HRA / Conveyance / LTC / Medical / Other and work out PF / PT / ESI.
     Rules are versioned by "effective from" month (the Oct-2026 rules are seeded).
  2. Employee salaries (employee_salary): each person's monthly gross + exceptions
     (HRA % for directors, PT exempt, no PF). Versioned by effective month (increments).
  3. Monthly payroll run (payroll_runs + payslips): pick a month → the portal takes
     LOP days from the leave records (same figure as the Monthly Report), prorates
     every component by paid days / days in month, and admin fills the monthly
     variables (TDS, KLWF, salary advance, other deductions). Draft → Finalised →
     Released. Only RELEASED slips are visible to employees.
  4. My Payslips: an employee sees ONLY their own released slips, and each slip is
     unlocked with a WhatsApp OTP (server-side, hashed, 5 min, 5 tries, one use);
     one OTP unlocks view + download of that slip for 10 minutes. Every OTP send,
     unlock, view and download is logged (payslip_access_log).

Verified: the rule engine reproduces the Oct-2026 salary statement to the rupee
for every employee (the one gap was a manual PT waiver — handled as a per-slip override).

Security
  * Payroll admin = is_admin OR Access Master hr/payroll 'edit' (checked in every route
    AND mapped in ACCESS_ROUTE_MAP).
  * Employee routes query `WHERE p.id = ? AND p.employee_id = <session user>` — a slip
    that isn't yours looks exactly like one that doesn't exist (404).
  * OTP codes never go into the (browser-readable) Flask cookie session — they are
    HMAC-hashed into payslip_otp; the unlock is a server-side row too.

Registered from app.py via register_hr_payroll(app). Tables self-create at request
time (_ensure) — cold-start safe, additive only.
"""

import calendar
import hashlib
import hmac
import io
import json
import logging
import math
import random
from datetime import datetime, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import (render_template, request, redirect, url_for, flash, session,
                   jsonify, send_file, abort, current_app)

from core.auth import login_required
from core.users import get_user
from db import get_db


OTP_TTL_SECONDS = 300          # code valid 5 minutes
OTP_MAX_TRIES = 5              # wrong attempts before the code is burnt
OTP_RESEND_GAP_SECONDS = 30    # min gap between sends
OTP_MAX_SENDS_PER_HOUR = 6
UNLOCK_SECONDS = 600           # one OTP unlocks view + download for 10 minutes

DEFAULT_COMPANY = 'GooCampus Edu Solutions Pvt Ltd.'
DEFAULT_ADDRESS = ('138/6, Ground Floor, 10th Main Road Sadashiv Nagar, 6th A Cross Road, '
                   'Behind SBI Bank, Raj Mahal Vilas Extension, Bengaluru - Karnataka 560080')

# Rule fields (name, label, kind) — kind 'pct' | 'amt' | 'text'
RULE_FIELDS = [
    ('basic_pct', 'Basic — % of monthly gross', 'pct'),
    ('basic_min', 'Basic — minimum amount (₹)', 'amt'),
    ('hra_pct', 'HRA — %', 'pct'),
    ('hra_base', 'HRA % is taken of', 'choice'),
    ('conveyance', 'Conveyance (₹ / month)', 'amt'),
    ('medical', 'Medical Allowance (₹ / month)', 'amt'),
    ('ltc', 'LTC (₹ / month)', 'amt'),
    ('pf_pct', 'PF — %', 'pct'),
    ('pf_base', 'PF % is taken of', 'choice'),
    ('pf_cap', 'PF — maximum per month (₹, 0 = no cap)', 'amt'),
    ('pt_amount', 'Professional Tax (₹ / month)', 'amt'),
    ('pt_threshold', 'PT applies when monthly gross is at least (₹)', 'amt'),
    ('esi_pct', 'ESI — employee % of gross', 'pct'),
    ('esi_threshold', 'ESI applies when monthly gross is at most (₹)', 'amt'),
    ('location', 'Location shown on slips', 'text'),
    ('company_name', 'Company name', 'text'),
    ('company_address', 'Company address', 'text'),
]
RULE_CHOICES = {
    'hra_base': [('basic', 'Basic'), ('gross', 'Monthly gross')],
    'pf_base': [('basic_other', 'Basic + Other Allowance'), ('basic', 'Basic only')],
}
SEED_RULES = dict(basic_pct=50, basic_min=18500, hra_pct=50, hra_base='basic', conveyance=1600, medical=1250,
                  ltc=0, pf_pct=12, pf_base='basic_other', pf_cap=3000, pt_amount=200, pt_threshold=25000,
                  esi_pct=0.75, esi_threshold=21000, location='Bengaluru',
                  company_name=DEFAULT_COMPANY, company_address=DEFAULT_ADDRESS)
# Apr–Sep 2026 rules (before the Oct PF change), derived from the April + June 2026 salary
# statements: Basic flat ₹15,000; HRA 20% of GROSS; PF 12% of Basic only, max ₹1,800.
# People whose Basic/HRA differed (directors, Robin, Vipin, Gopi, Jeswin S., Poornima, Harish,
# Praveen, Alfiya, Varsha) are per-person fixed amounts on Employee Salaries.
SEED_RULES_APR26 = dict(SEED_RULES, basic_pct=0, basic_min=15000, hra_pct=20, hra_base='gross',
                        pf_base='basic', pf_cap=1800)

# Login accounts that are not real staff (the founder's "Admin" login) never go on payroll.
AUTO_EXCLUDE_NAMES = {'admin'}

MANUAL_DEDUCTIONS = [('tds', 'TDS'), ('klwf', 'KLWF'), ('salary_advance', 'Salary Advance'),
                     ('other_deductions', 'Other Deductions')]

_READY = False


# ─────────────────────────────── helpers ────────────────────────────────

def _app():
    import app as _a  # lazy — avoids a circular import at module load
    return _a


def rh(x):
    """Round half-up to the rupee (Excel ROUND, not Python's banker's rounding)."""
    return int(Decimal(str(float(x or 0))).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _f(v, default=0.0):
    try:
        if v is None or v == '':
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _num(v):
    """Decimal/float → int when whole, else a trimmed float (display only)."""
    x = _f(v)
    return int(x) if x == int(x) else round(x, 3)


def ist_now():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


def inr(v):
    """72800 → '72,800' (Indian grouping, whole rupees)."""
    n = rh(v)
    neg, s = n < 0, str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ','.join(parts) + ',' + tail
    return ('-' if neg else '') + s


_ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven',
         'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def _w100(n):
    return _ONES[n] if n < 20 else _TENS[n // 10] + (' ' + _ONES[n % 10] if n % 10 else '')


def _w1000(n):
    h, r = divmod(n, 100)
    return ((_ONES[h] + ' Hundred' + (' ' if r else '')) if h else '') + (_w100(r) if r else '')


def rupees_in_words(amount):
    """45000 → 'Forty Five Thousand Rupees Only' (lakh/crore system, like the slips)."""
    n = rh(amount)
    if n <= 0:
        return 'Zero Rupees Only'
    out = []
    for div, name in ((10 ** 7, 'Crore'), (10 ** 5, 'Lakh'), (1000, 'Thousand')):
        q, n = divmod(n, div)
        if q:
            out.append((rupees_in_words(q).replace(' Rupees Only', '') if q >= 1000 else _w1000(q)) + ' ' + name)
    if n:
        out.append(_w1000(n))
    return ' '.join(out) + ' Rupees Only'


def period_label(period):
    try:
        y, m = int(period[:4]), int(period[5:7])
        return f"{calendar.month_name[m]} {y}"
    except Exception:
        return period or ''


def fy_label(period):
    y, m = int(period[:4]), int(period[5:7])
    s = y if m >= 4 else y - 1
    return f"FY {s}-{str(s + 1)[-2:]}"


def _parse_date(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()[:10]
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _pk(conn):
    return 'SERIAL PRIMARY KEY' if getattr(conn, 'is_postgres', False) else 'INTEGER PRIMARY KEY AUTOINCREMENT'


def _insert(conn, sql, params):
    """INSERT … and return the new id on both Postgres and SQLite."""
    if getattr(conn, 'is_postgres', False):
        return conn.execute(sql + ' RETURNING id', params).fetchone()['id']
    cur = conn.execute(sql, params)
    return cur.lastrowid


def _ensure(conn):
    """Create payroll tables (request-time, idempotent, additive only)."""
    global _READY
    if _READY:
        return
    pk = _pk(conn)
    ddl = [
        f'''CREATE TABLE IF NOT EXISTS payroll_rules (
            id {pk},
            effective_from TEXT NOT NULL,
            basic_pct NUMERIC(8,3), basic_min NUMERIC(12,2), hra_pct NUMERIC(8,3),
            conveyance NUMERIC(12,2), medical NUMERIC(12,2), ltc NUMERIC(12,2),
            pf_pct NUMERIC(8,3), pf_cap NUMERIC(12,2),
            pt_amount NUMERIC(12,2), pt_threshold NUMERIC(12,2),
            esi_pct NUMERIC(8,3), esi_threshold NUMERIC(12,2),
            location TEXT, company_name TEXT, company_address TEXT, notes TEXT,
            updated_by_name TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        f'''CREATE TABLE IF NOT EXISTS employee_salary (
            id {pk},
            employee_id INTEGER NOT NULL,
            effective_from TEXT NOT NULL,
            monthly_gross NUMERIC(12,2) NOT NULL,
            hra_pct NUMERIC(8,3),
            pt_exempt INTEGER DEFAULT 0,
            pf_exempt INTEGER DEFAULT 0,
            notes TEXT,
            updated_by_name TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        f'''CREATE TABLE IF NOT EXISTS payroll_runs (
            id {pk},
            period TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'draft',
            rules_id INTEGER,
            created_by_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finalised_by_name TEXT, finalised_at TIMESTAMP,
            released_by_name TEXT, released_at TIMESTAMP)''',
        f'''CREATE TABLE IF NOT EXISTS payslips (
            id {pk},
            run_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            period TEXT NOT NULL,
            emp_name TEXT, emp_code TEXT, designation TEXT, location TEXT,
            bank_account TEXT, pf_account TEXT, joining_date TEXT,
            days_in_month NUMERIC(6,2), eligible_days NUMERIC(6,2), lop_days NUMERIC(6,2),
            paid_days NUMERIC(6,2), full_gross NUMERIC(12,2),
            basic NUMERIC(12,2), hra NUMERIC(12,2), conveyance NUMERIC(12,2), ltc NUMERIC(12,2),
            medical NUMERIC(12,2), other_allowance NUMERIC(12,2), gross NUMERIC(12,2),
            pf NUMERIC(12,2), pt NUMERIC(12,2), esi NUMERIC(12,2), tds NUMERIC(12,2),
            klwf NUMERIC(12,2), salary_advance NUMERIC(12,2), other_deductions NUMERIC(12,2),
            total_deductions NUMERIC(12,2), net_pay NUMERIC(12,2),
            leave_taken NUMERIC(6,2), leave_balance NUMERIC(6,2),
            overrides TEXT, notes TEXT,
            updated_by_name TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (run_id, employee_id))''',
        f'''CREATE TABLE IF NOT EXISTS payslip_otp (
            id {pk},
            employee_id INTEGER NOT NULL,
            payslip_id INTEGER NOT NULL,
            code_hash TEXT NOT NULL,
            tries INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0,
            unlocked_until TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        '''CREATE TABLE IF NOT EXISTS payroll_exclusions (
            employee_id INTEGER PRIMARY KEY,
            excluded_by_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
        f'''CREATE TABLE IF NOT EXISTS payslip_access_log (
            id {pk},
            payslip_id INTEGER, employee_id INTEGER, actor_id INTEGER, actor_name TEXT,
            action TEXT, ip TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''',
    ]
    try:
        for q in ddl:
            conn.execute(q)
        conn.commit()
        for table, col, typ in (('payroll_rules', 'hra_base', 'TEXT'), ('payroll_rules', 'pf_base', 'TEXT'),
                                ('employee_salary', 'basic_amount', 'NUMERIC(12,2)'),
                                ('employee_salary', 'hra_amount', 'NUMERIC(12,2)'),
                                ('employee_salary', 'monthly_tds', 'NUMERIC(12,2)')):
            _add_col(conn, table, col, typ)
        # Seed the Oct-2026 rules once (derived from the Oct-2026 salary statement).
        has = conn.execute("SELECT 1 FROM payroll_rules LIMIT 1").fetchone()
        if not has:
            cols = ['effective_from'] + list(SEED_RULES.keys()) + ['notes', 'updated_by_name']
            vals = ['2026-10'] + list(SEED_RULES.values()) + [
                'Seeded from the Oct-2026 salary statement (Basic 50% of gross, min ₹18,500; '
                'PF 12% of Basic + Other, max ₹3,000).', 'System']
            conn.execute(f"INSERT INTO payroll_rules ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
            conn.commit()
        # Seed the Apr–Sep 2026 (old PF) rules once — only if no version before Oct exists yet.
        older = conn.execute("SELECT 1 FROM payroll_rules WHERE effective_from < '2026-10' LIMIT 1").fetchone()
        if not older:
            cols = ['effective_from'] + list(SEED_RULES_APR26.keys()) + ['notes', 'updated_by_name']
            vals = ['2026-04'] + list(SEED_RULES_APR26.values()) + [
                'Apr–Sep 2026 rules from the April + June 2026 salary statements (Basic ₹15,000; HRA 20% of gross; '
                'PF 12% of Basic, max ₹1,800). Different Basic/HRA = fixed amounts on Employee Salaries.', 'System']
            conn.execute(f"INSERT INTO payroll_rules ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
            conn.commit()
        _READY = True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"hr_payroll _ensure: {e}")


def _me():
    """Logged-in employee as a plain dict (get_user() may return a DB row object)."""
    u = get_user()
    return dict(u) if u else None


def _add_col(conn, table, col, typ):
    """Additive column (Postgres: IF NOT EXISTS; SQLite: ignore 'duplicate column')."""
    try:
        if getattr(conn, 'is_postgres', False):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}")
        else:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _can_manage(user):
    if not user:
        return False
    if user.get('is_admin'):
        return True
    try:
        return _app().has_section_permission(user, 'hr', 'payroll', 'edit')
    except Exception:
        return False


def _require_manager():
    """Returns (user, None) or (None, redirect-response)."""
    user = _me()
    if not _can_manage(user):
        flash('Payroll is restricted. Ask an admin for access.', 'error')
        return None, redirect(url_for('dashboard'))
    return user, None


def _log(conn, payslip_id, employee_id, user, action):
    try:
        conn.execute("INSERT INTO payslip_access_log (payslip_id, employee_id, actor_id, actor_name, action, ip) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (payslip_id, employee_id, (user or {}).get('id'), (user or {}).get('name') or '',
                      action, (request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:120]))
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"payslip log: {e}")


# ─────────────────────────── rules / salary lookup ──────────────────────────

def rules_for(conn, period):
    r = conn.execute("SELECT * FROM payroll_rules WHERE effective_from <= ? "
                     "ORDER BY effective_from DESC, id DESC LIMIT 1", (period,)).fetchone()
    return dict(r) if r else None


def salary_for(conn, employee_id, period):
    r = conn.execute("SELECT * FROM employee_salary WHERE employee_id = ? AND effective_from <= ? "
                     "ORDER BY effective_from DESC, id DESC LIMIT 1", (employee_id, period)).fetchone()
    return dict(r) if r else None


# ──────────────────────────────── calculation ───────────────────────────────

def _set(v):
    return v is not None and str(v).strip() != ''


def split_gross(rules, gross, sal=None):
    """Full-month split of a monthly gross into components (before LOP).
    `sal` (the employee_salary row) may carry per-person exceptions: a fixed Basic
    (basic_amount), a fixed HRA (hra_amount) or a different HRA % (hra_pct)."""
    sal = sal or {}
    G = rh(gross)
    if _set(sal.get('basic_amount')):
        basic = min(G, rh(sal.get('basic_amount')))
    else:
        basic = min(G, max(rh(G * _f(rules.get('basic_pct')) / 100), rh(rules.get('basic_min'))))
    rem = G - basic
    if _set(sal.get('hra_amount')):
        hra = min(rh(sal.get('hra_amount')), rem)
    else:
        hp = _f(sal.get('hra_pct')) if _set(sal.get('hra_pct')) else _f(rules.get('hra_pct'))
        base = G if (rules.get('hra_base') or 'basic') == 'gross' else basic
        hra = min(rh(base * hp / 100), rem)
    rem -= hra
    conv = min(rh(rules.get('conveyance')), rem); rem -= conv
    ltc = min(rh(rules.get('ltc')), rem); rem -= ltc
    med = min(rh(rules.get('medical')), rem); rem -= med
    return dict(basic=basic, hra=hra, conveyance=conv, ltc=ltc, medical=med, other_allowance=rem)


def compute_slip(rules, salary, days_in_month, eligible_days, lop_days, manual=None, overrides=None):
    """Compute one month's payslip figures.

    Every component is prorated by paid_days / days_in_month and rounded half-up.
    PF = pf_pct of (Basic + Other Allowance), capped. PT = flat amount when the FULL
    monthly gross >= threshold. ESI = esi_pct of earned gross when full gross <= threshold.
    `manual` = TDS / KLWF / salary advance / other deductions (entered by admin).
    `overrides` = admin-set values that replace the auto ones: lop_days, pt, esi, pf.
    """
    manual = manual or {}
    overrides = overrides or {}
    if 'lop_days' in overrides:
        lop_days = _f(overrides['lop_days'])
    G = rh(salary.get('monthly_gross'))
    full = split_gross(rules, G, salary)
    paid = max(0.0, _f(eligible_days) - _f(lop_days))
    factor = (paid / float(days_in_month)) if days_in_month else 0.0
    out = {k: rh(v * factor) for k, v in full.items()}
    out['gross'] = sum(out[k] for k in ('basic', 'hra', 'conveyance', 'ltc', 'medical', 'other_allowance'))

    pf = 0
    if not int(salary.get('pf_exempt') or 0) and out['gross'] > 0:
        pf_wage = out['basic'] if (rules.get('pf_base') or 'basic_other') == 'basic' else out['basic'] + out['other_allowance']
        pf = rh(pf_wage * _f(rules.get('pf_pct')) / 100)
        cap = rh(rules.get('pf_cap'))
        if cap > 0:
            pf = min(pf, cap)
    pt = 0
    if not int(salary.get('pt_exempt') or 0) and out['gross'] > 0 and G >= rh(rules.get('pt_threshold')):
        pt = rh(rules.get('pt_amount'))
    esi = 0
    if 0 < G <= rh(rules.get('esi_threshold')) and out['gross'] > 0:
        esi = int(math.ceil(out['gross'] * _f(rules.get('esi_pct')) / 100))
    if 'pt' in overrides:
        pt = rh(overrides['pt'])
    if 'esi' in overrides:
        esi = rh(overrides['esi'])
    if 'pf' in overrides:
        pf = rh(overrides['pf'])

    out.update(pf=pf, pt=pt, esi=esi)
    for k, _ in MANUAL_DEDUCTIONS:
        out[k] = rh(manual.get(k))
    out['total_deductions'] = sum(out[k] for k in ('pf', 'pt', 'esi', 'tds', 'klwf', 'salary_advance', 'other_deductions'))
    out['net_pay'] = out['gross'] - out['total_deductions']
    out.update(full_gross=G, days_in_month=days_in_month, eligible_days=_f(eligible_days),
               lop_days=_f(lop_days), paid_days=paid)
    return out


def eligible_days_for(emp, year, month):
    """Calendar days in the month the person was employed (joining / last working day)."""
    dim = calendar.monthrange(year, month)[1]
    first, last = date(year, month, 1), date(year, month, dim)
    start, end = first, last
    j = _parse_date(emp.get('joining_date'))
    if j:
        if j > last:
            return dim, 0
        if j > first:
            start = j
    lwd = _parse_date(emp.get('last_working_day'))
    if lwd and not int(emp.get('is_active') or 0):
        if lwd < first:
            return dim, 0
        if lwd < last:
            end = lwd
    return dim, max(0, (end - start).days + 1)


def _leave_figures(employee_id, year, month):
    """(auto LOP days, leave taken this month, FY leave balance) from the leave system —
    the same numbers the Monthly Report uses. Failures fall back to zeros."""
    a = _app()
    lop = taken = bal = 0.0
    try:
        f = a.leave_month_figures(employee_id, year, month)
        lop, taken = _f(f.get('deduction')), _f(f.get('days_taken'))
    except Exception as e:
        logging.warning(f"payroll leave_month_figures {employee_id}: {e}")
    try:
        fy = year if month >= 4 else year - 1
        bal = _f(a.leave_type_balances(employee_id, fy).get('total_balance'))
    except Exception as e:
        logging.warning(f"payroll leave_type_balances {employee_id}: {e}")
    return lop, taken, bal


SLIP_NUM_COLS = ['days_in_month', 'eligible_days', 'lop_days', 'paid_days', 'full_gross', 'basic', 'hra',
                 'conveyance', 'ltc', 'medical', 'other_allowance', 'gross', 'pf', 'pt', 'esi', 'tds',
                 'klwf', 'salary_advance', 'other_deductions', 'total_deductions', 'net_pay']


def _build_or_refresh_slip(conn, run, emp, rules, salary, user, existing=None):
    """Compute + upsert one employee's slip in a DRAFT run, keeping admin-entered values."""
    y, m = int(run['period'][:4]), int(run['period'][5:7])
    dim, elig = eligible_days_for(emp, y, m)
    lop, taken, bal = _leave_figures(emp['id'], y, m)
    manual = {k: (existing or {}).get(k) for k, _ in MANUAL_DEDUCTIONS}
    overrides = {}
    if existing and existing.get('overrides'):
        try:
            overrides = json.loads(existing['overrides']) or {}
        except Exception:
            overrides = {}
    # TDS (founder 2026-11-12): only the directors have a regular TDS — their "Monthly TDS" on the
    # salary entry repeats for every month that entry covers (e.g. Apr–Sep). Anyone else's TDS is a
    # one-off typed on that month's slip, and is NOT copied to the next month.
    if not overrides.get('tds_set') and _set(salary.get('monthly_tds')):
        manual['tds'] = salary.get('monthly_tds')
    c = compute_slip(rules, salary, dim, elig, lop, manual, overrides)
    ident = dict(emp_name=emp.get('name') or '', emp_code=emp.get('emp_code') or '',
                 designation=emp.get('designation') or '', location=rules.get('location') or 'Bengaluru',
                 bank_account=emp.get('bank_account_number') or '', pf_account=emp.get('pf_number') or '',
                 joining_date=str(emp.get('joining_date') or '')[:10])
    data = dict(ident, **{k: c[k] for k in SLIP_NUM_COLS})
    data.update(leave_taken=taken, leave_balance=bal, overrides=json.dumps(overrides),
                updated_by_name=(user or {}).get('name') or '')
    if existing:
        sets = ', '.join(f"{k} = ?" for k in data) + ', updated_at = CURRENT_TIMESTAMP'
        conn.execute(f"UPDATE payslips SET {sets} WHERE id = ?", list(data.values()) + [existing['id']])
    else:
        data.update(run_id=run['id'], employee_id=emp['id'], period=run['period'])
        conn.execute(f"INSERT INTO payslips ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
                     list(data.values()))


def _excluded_ids(conn):
    try:
        return {r['employee_id'] for r in conn.execute("SELECT employee_id FROM payroll_exclusions").fetchall()}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return set()


def _auto_excluded(emp):
    return (str(emp.get('name') or '').strip().lower() in AUTO_EXCLUDE_NAMES
            or str(emp.get('emp_code') or '').strip().lower() in AUTO_EXCLUDE_NAMES)


def _payroll_employees(conn, include_excluded=False):
    """Active employees (the people on the dashboard) — interns/stipends aren't employees.
    The admin login account and anyone marked "Not on payroll" are left out."""
    rows = [dict(r) for r in conn.execute("SELECT * FROM employees WHERE is_active = 1 ORDER BY name").fetchall()]
    ex = _excluded_ids(conn)
    for r in rows:
        r['payroll_excluded'] = r['id'] in ex or _auto_excluded(r)
        r['payroll_auto_excluded'] = _auto_excluded(r)
    return rows if include_excluded else [r for r in rows if not r['payroll_excluded']]


def _refresh_run(conn, run, user):
    """(Re)compute every eligible employee's slip in a draft run. Returns missing-salary list."""
    rules = rules_for(conn, run['period'])
    if not rules:
        return None
    existing = {r['employee_id']: dict(r) for r in conn.execute(
        "SELECT * FROM payslips WHERE run_id = ?", (run['id'],)).fetchall()}
    missing = []
    y, m = int(run['period'][:4]), int(run['period'][5:7])
    for emp in _payroll_employees(conn, include_excluded=True):
        if emp['payroll_excluded'] and emp['id'] in existing:
            conn.execute("DELETE FROM payslips WHERE id = ?", (existing[emp['id']]['id'],))
    for emp in _payroll_employees(conn):
        sal = salary_for(conn, emp['id'], run['period'])
        if not sal:
            missing.append(emp)
            continue
        if eligible_days_for(emp, y, m)[1] <= 0 and emp['id'] not in existing:
            continue  # joined after this month
        _build_or_refresh_slip(conn, run, emp, rules, sal, user, existing.get(emp['id']))
    conn.commit()
    return missing


def _missing_salary(conn, period):
    out = []
    for emp in _payroll_employees(conn):
        if not salary_for(conn, emp['id'], period):
            out.append(emp)
    return out


# ───────────────────────────── admin: runs ──────────────────────────────

def payroll_home():
    user, deny = _require_manager()
    if deny:
        return deny
    conn = get_db()
    try:
        _ensure(conn)
        runs = [dict(r) for r in conn.execute(
            "SELECT r.*, (SELECT COUNT(*) FROM payslips p WHERE p.run_id = r.id) AS n, "
            "(SELECT SUM(net_pay) FROM payslips p WHERE p.run_id = r.id) AS net "
            "FROM payroll_runs r ORDER BY r.period DESC").fetchall()]
        rules = rules_for(conn, ist_now().strftime('%Y-%m'))
        n_sal = conn.execute("SELECT COUNT(DISTINCT employee_id) AS c FROM employee_salary").fetchone()['c']
    finally:
        conn.close()
    today = ist_now().date()
    prev = (today.replace(day=1) - timedelta(days=1))
    months = []
    d = date(today.year, today.month, 1)
    for _ in range(14):
        months.append(d.strftime('%Y-%m'))
        d = (d - timedelta(days=1)).replace(day=1)
    return render_template('hr_payroll.html', user=user, runs=runs, rules=rules, n_sal=n_sal,
                           default_period=prev.strftime('%Y-%m'), months=months,
                           period_label=period_label, inr=inr, active_section='hr')


def payroll_start():
    user, deny = _require_manager()
    if deny:
        return deny
    period = (request.form.get('period') or '').strip()[:7]
    try:
        datetime.strptime(period, '%Y-%m')
    except ValueError:
        flash('Pick a valid month.', 'error')
        return redirect(url_for('hr_payroll'))
    conn = get_db()
    try:
        _ensure(conn)
        ex = conn.execute("SELECT id FROM payroll_runs WHERE period = ?", (period,)).fetchone()
        if ex:
            return redirect(url_for('hr_payroll_run', run_id=ex['id']))
        rules = rules_for(conn, period)
        if not rules:
            flash(f'No salary template covers {period_label(period)}. Add one under Salary Template first.', 'error')
            return redirect(url_for('hr_payroll'))
        run_id = _insert(conn, "INSERT INTO payroll_runs (period, status, rules_id, created_by_name) VALUES (?, 'draft', ?, ?)",
                         (period, rules['id'], user.get('name') or ''))
        conn.commit()
        run = dict(conn.execute("SELECT * FROM payroll_runs WHERE id = ?", (run_id,)).fetchone())
        _refresh_run(conn, run, user)
    finally:
        conn.close()
    flash(f'Payroll for {period_label(period)} calculated. Check LOP and add TDS / advances, then Finalise.', 'success')
    return redirect(url_for('hr_payroll_run', run_id=run_id))


def payroll_run(run_id):
    user, deny = _require_manager()
    if deny:
        return deny
    conn = get_db()
    try:
        _ensure(conn)
        run = conn.execute("SELECT * FROM payroll_runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            abort(404)
        run = dict(run)
        slips = [dict(r) for r in conn.execute(
            "SELECT * FROM payslips WHERE run_id = ? ORDER BY emp_name", (run_id,)).fetchall()]
        missing = _missing_salary(conn, run['period']) if run['status'] == 'draft' else []
        rules = rules_for(conn, run['period'])
        views = {r['payslip_id']: r['c'] for r in conn.execute(
            "SELECT payslip_id, COUNT(*) AS c FROM payslip_access_log WHERE action IN ('view','download') "
            "AND payslip_id IN (SELECT id FROM payslips WHERE run_id = ?) GROUP BY payslip_id", (run_id,)).fetchall()}
    finally:
        conn.close()
    for s in slips:
        try:
            s['ov'] = json.loads(s.get('overrides') or '{}') or {}
        except Exception:
            s['ov'] = {}
        s['views'] = views.get(s['id'], 0)
    tot_keys = ['gross', 'pf', 'pt', 'esi', 'tds', 'klwf', 'salary_advance', 'other_deductions',
                'total_deductions', 'net_pay', 'lop_days']
    totals = {k: sum(_f(s.get(k)) for s in slips) for k in tot_keys}
    return render_template('hr_payroll_run.html', user=user, run=run, slips=slips, totals=totals,
                           missing=missing, rules=rules, period_label=period_label, fy_label=fy_label,
                           inr=inr, manual_fields=MANUAL_DEDUCTIONS, active_section='hr')


def payroll_recalc(run_id):
    user, deny = _require_manager()
    if deny:
        return deny
    conn = get_db()
    try:
        _ensure(conn)
        run = conn.execute("SELECT * FROM payroll_runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            abort(404)
        if run['status'] != 'draft':
            flash('Only a draft payroll can be recalculated. Re-open it first.', 'error')
            return redirect(url_for('hr_payroll_run', run_id=run_id))
        _refresh_run(conn, dict(run), user)
    finally:
        conn.close()
    flash('Recalculated from the latest salaries and leave records. Your TDS / advances / overrides were kept.', 'success')
    return redirect(url_for('hr_payroll_run', run_id=run_id))


def payroll_slip_save(slip_id):
    """Save the drawer: LOP / PT / ESI / PF overrides + manual deductions + notes."""
    user, deny = _require_manager()
    if deny:
        return deny
    conn = get_db()
    try:
        _ensure(conn)
        slip = conn.execute("SELECT * FROM payslips WHERE id = ?", (slip_id,)).fetchone()
        if not slip:
            abort(404)
        slip = dict(slip)
        run = dict(conn.execute("SELECT * FROM payroll_runs WHERE id = ?", (slip['run_id'],)).fetchone())
        if run['status'] != 'draft':
            flash('This payroll is finalised. Re-open it to make changes.', 'error')
            return redirect(url_for('hr_payroll_run', run_id=run['id']))
        try:
            ov = json.loads(slip.get('overrides') or '{}') or {}
        except Exception:
            ov = {}
        for k in ('lop_days', 'pt', 'esi', 'pf'):
            if request.form.get(f'auto_{k}'):
                ov.pop(k, None)               # back to the automatic value
            elif (request.form.get(k) or '').strip() != '':
                ov[k] = _f(request.form.get(k))
        manual = {k: _f(request.form.get(k)) for k, _ in MANUAL_DEDUCTIONS}
        if abs(manual['tds'] - _f(slip.get('tds'))) > 0.005:
            ov['tds_set'] = True          # keep this month's TDS even if the salary entry's TDS changes
        conn.execute("UPDATE payslips SET overrides = ?, notes = ?, tds = ?, klwf = ?, salary_advance = ?, "
                     "other_deductions = ? WHERE id = ?",
                     (json.dumps(ov), (request.form.get('notes') or '').strip()[:500],
                      manual['tds'], manual['klwf'], manual['salary_advance'], manual['other_deductions'], slip_id))
        conn.commit()
        emp = conn.execute("SELECT * FROM employees WHERE id = ?", (slip['employee_id'],)).fetchone()
        sal = salary_for(conn, slip['employee_id'], run['period'])
        rules = rules_for(conn, run['period'])
        if emp and sal and rules:
            fresh = dict(conn.execute("SELECT * FROM payslips WHERE id = ?", (slip_id,)).fetchone())
            _build_or_refresh_slip(conn, run, dict(emp), rules, sal, user, fresh)
            conn.commit()
    finally:
        conn.close()
    flash(f"Saved {slip.get('emp_name')}.", 'success')
    return redirect(url_for('hr_payroll_run', run_id=run['id']) + f"#slip-{slip_id}")


def payroll_status(run_id):
    user, deny = _require_manager()
    if deny:
        return deny
    action = request.form.get('action')
    conn = get_db()
    try:
        _ensure(conn)
        run = conn.execute("SELECT * FROM payroll_runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            abort(404)
        st, who, label = run['status'], user.get('name') or '', period_label(run['period'])
        if action == 'finalise' and st == 'draft':
            conn.execute("UPDATE payroll_runs SET status = 'finalised', finalised_by_name = ?, "
                         "finalised_at = CURRENT_TIMESTAMP WHERE id = ?", (who, run_id))
            msg = f'{label} finalised — figures are locked. Release when ready for employees to see.'
        elif action == 'release' and st == 'finalised':
            conn.execute("UPDATE payroll_runs SET status = 'released', released_by_name = ?, "
                         "released_at = CURRENT_TIMESTAMP WHERE id = ?", (who, run_id))
            msg = f'{label} payslips released. Employees can now open them (with WhatsApp OTP).'
        elif action == 'reopen' and st in ('finalised', 'released'):
            conn.execute("UPDATE payroll_runs SET status = 'draft' WHERE id = ?", (run_id,))
            msg = f'{label} re-opened as draft — employees can no longer see these slips until you release again.'
        elif action == 'delete' and st == 'draft':
            conn.execute("DELETE FROM payslips WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM payroll_runs WHERE id = ?", (run_id,))
            conn.commit()
            flash(f'Draft payroll for {label} deleted.', 'success')
            return redirect(url_for('hr_payroll'))
        else:
            flash('That action is not allowed in the current status.', 'error')
            return redirect(url_for('hr_payroll_run', run_id=run_id))
        conn.commit()
    finally:
        conn.close()
    flash(msg, 'success')
    return redirect(url_for('hr_payroll_run', run_id=run_id))


def payroll_export(run_id):
    """Salary statement for the month as Excel — same column order as the founder's sheet."""
    user, deny = _require_manager()
    if deny:
        return deny
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    conn = get_db()
    try:
        _ensure(conn)
        run = conn.execute("SELECT * FROM payroll_runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            abort(404)
        slips = [dict(r) for r in conn.execute(
            "SELECT * FROM payslips WHERE run_id = ? ORDER BY emp_name", (run_id,)).fetchall()]
    finally:
        conn.close()
    wb = Workbook()
    ws = wb.active
    ws.title = f"Salary {period_label(run['period'])}"[:31]
    ws.append([f"Salary Statement for the month of : {period_label(run['period'])}  ({run['status'].title()})"])
    ws['A1'].font = Font(bold=True, size=12)
    head = ['Sl No.', 'Employee Code', 'Employee Name', 'Designation', 'Date of Joining', 'Working Days', 'LOP',
            'Paid Days', 'Basic', 'HRA', 'Conveyance', 'LTC', 'Medical Allowance', 'Other Allowance',
            'Gross Salary', 'PT', 'Salary Advance', 'Other Deduction', 'KLWF', 'PF', 'ESI', 'TDS',
            'Total Dedn', 'Net Salary', 'Bank A/c No.', 'PF A/c No.', 'Notes']
    ws.append([])
    ws.append(head)
    for c in ws[3]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='1E3A8A')
        c.alignment = Alignment(wrap_text=True, vertical='center')
    num = ['basic', 'hra', 'conveyance', 'ltc', 'medical', 'other_allowance', 'gross', 'pt', 'salary_advance',
           'other_deductions', 'klwf', 'pf', 'esi', 'tds', 'total_deductions', 'net_pay']
    for i, s in enumerate(slips, 1):
        ws.append([i, s['emp_code'], s['emp_name'], s['designation'], s['joining_date'],
                   _f(s['eligible_days']), _f(s['lop_days']), _f(s['paid_days'])]
                  + [rh(s[k]) for k in num] + [s['bank_account'], s['pf_account'], s.get('notes') or ''])
    ws.append([])
    ws.append(['', '', 'TOTAL', '', '', '', sum(_f(s['lop_days']) for s in slips), '']
              + [sum(rh(s[k]) for s in slips) for k in num])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    from openpyxl.utils import get_column_letter
    for i, w in enumerate([6, 12, 26, 30, 13] + [10] * 19 + [16, 16, 30], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"Salary-Statement-{run['period']}.xlsx",
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def payroll_slip_view(slip_id):
    """Admin preview of any slip (no OTP — payroll managers already see the whole run)."""
    user, deny = _require_manager()
    if deny:
        return deny
    conn = get_db()
    try:
        _ensure(conn)
        slip = conn.execute("SELECT * FROM payslips WHERE id = ?", (slip_id,)).fetchone()
        if not slip:
            abort(404)
        slip = dict(slip)
        run = dict(conn.execute("SELECT * FROM payroll_runs WHERE id = ?", (slip['run_id'],)).fetchone())
        rules = rules_for(conn, slip['period']) or {}
    finally:
        conn.close()
    return render_template('payslip_view.html', user=user, slip=slip, run=run, rules=rules, inr=inr,
                           words=rupees_in_words(slip['net_pay']), period_label=period_label,
                           admin_view=True, unlocked=True, active_section='hr')


# ─────────────────────────── admin: template + salaries ───────────────────────────

def payroll_template():
    user, deny = _require_manager()
    if deny:
        return deny
    conn = get_db()
    try:
        _ensure(conn)
        if request.method == 'POST':
            eff = (request.form.get('effective_from') or '').strip()[:7]
            try:
                datetime.strptime(eff, '%Y-%m')
            except ValueError:
                flash('Pick the month these rules start from.', 'error')
                return redirect(url_for('hr_payroll_template'))
            vals = {}
            for k, _, kind in RULE_FIELDS:
                v = (request.form.get(k) or '').strip()
                if kind == 'choice':
                    allowed = [c for c, _ in RULE_CHOICES[k]]
                    v = v if v in allowed else allowed[0]
                vals[k] = v if kind in ('text', 'choice') else _f(v)
            mode = request.form.get('mode')
            if mode == 'edit' and request.form.get('rules_id'):
                rid = int(request.form.get('rules_id'))
                # Never rewrite rules that a finalised/released payroll already used.
                locked = conn.execute("SELECT 1 FROM payroll_runs WHERE rules_id = ? AND status <> 'draft' LIMIT 1",
                                      (rid,)).fetchone()
                if locked:
                    flash('These rules were used by a finalised payroll — save them as a NEW version '
                          'starting from a later month instead.', 'error')
                    return redirect(url_for('hr_payroll_template'))
                sets = ', '.join(f"{k} = ?" for k in vals)
                conn.execute(f"UPDATE payroll_rules SET effective_from = ?, {sets}, notes = ?, updated_by_name = ?, "
                             f"updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                             [eff] + list(vals.values()) + [(request.form.get('notes') or '').strip(),
                                                            user.get('name') or '', rid])
                flash('Salary template updated.', 'success')
            else:
                cols = ['effective_from'] + list(vals) + ['notes', 'updated_by_name']
                conn.execute(f"INSERT INTO payroll_rules ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             [eff] + list(vals.values()) + [(request.form.get('notes') or '').strip(),
                                                            user.get('name') or ''])
                flash(f'New rules saved — they apply from {period_label(eff)} onwards.', 'success')
            conn.commit()
            return redirect(url_for('hr_payroll_template'))
        versions = [dict(r) for r in conn.execute(
            "SELECT * FROM payroll_rules ORDER BY effective_from DESC, id DESC").fetchall()]
        used = {r['rules_id'] for r in conn.execute(
            "SELECT DISTINCT rules_id FROM payroll_runs WHERE status <> 'draft'").fetchall()}
    finally:
        conn.close()
    for v in versions:  # 50.000 → 50, 0.750 → 0.75 for display
        for k, _, kind in RULE_FIELDS:
            if kind not in ('text', 'choice') and v.get(k) is not None:
                v[k] = _num(v[k])
    # Worked example so the founder can sanity-check the rules at a glance.
    example = None
    if versions:
        ex_gross = 47000
        sp = split_gross(versions[0], ex_gross)
        example = dict(gross=ex_gross, **sp,
                       pf=compute_slip(versions[0], {'monthly_gross': ex_gross}, 30, 30, 0)['pf'])
    return render_template('hr_payroll_template.html', user=user, versions=versions, used=used,
                           fields=RULE_FIELDS, choices=RULE_CHOICES, example=example, inr=inr, period_label=period_label,
                           active_section='hr')


def payroll_salaries():
    user, deny = _require_manager()
    if deny:
        return deny
    conn = get_db()
    try:
        _ensure(conn)
        period = ist_now().strftime('%Y-%m')
        rules = rules_for(conn, period) or rules_for(conn, '9999-12')
        emps = _payroll_employees(conn, include_excluded=True)
        hist = {}
        for r in conn.execute("SELECT * FROM employee_salary ORDER BY effective_from DESC, id DESC").fetchall():
            hist.setdefault(r['employee_id'], []).append(dict(r))
    finally:
        conn.close()
    rows = []
    for e in emps:
        h = hist.get(e['id'], [])
        cur = next((x for x in h if x['effective_from'] <= period), h[-1] if h else None)
        split = split_gross(rules, cur['monthly_gross'], cur) if (cur and rules) else None
        rows.append(dict(emp=e, cur=cur, hist=h, split=split))
    rows_on = [r for r in rows if not r['emp']['payroll_excluded']]
    rows_off = [r for r in rows if r['emp']['payroll_excluded']]
    return render_template('hr_payroll_salaries.html', user=user, rows=rows_on, rows_off=rows_off, rules=rules, inr=inr,
                           period_label=period_label, this_month=period, active_section='hr')


def payroll_salary_save():
    user, deny = _require_manager()
    if deny:
        return deny
    try:
        emp_id = int(request.form.get('employee_id'))
    except (TypeError, ValueError):
        flash('Pick an employee.', 'error')
        return redirect(url_for('hr_payroll_salaries'))
    eff = (request.form.get('effective_from') or '').strip()[:7]
    gross = _f(request.form.get('monthly_gross'), -1)
    try:
        datetime.strptime(eff, '%Y-%m')
    except ValueError:
        flash('Pick the month this salary starts from.', 'error')
        return redirect(url_for('hr_payroll_salaries'))
    if gross <= 0:
        flash('Enter the monthly gross salary.', 'error')
        return redirect(url_for('hr_payroll_salaries'))
    def _opt(name):
        v = (request.form.get(name) or '').strip()
        return _f(v) if v != '' else None
    hra = _opt('hra_pct')
    basic_amt, hra_amt, tds_amt = _opt('basic_amount'), _opt('hra_amount'), _opt('monthly_tds')
    conn = get_db()
    try:
        _ensure(conn)
        emp = conn.execute("SELECT name FROM employees WHERE id = ?", (emp_id,)).fetchone()
        if not emp:
            abort(404)
        same = conn.execute("SELECT id FROM employee_salary WHERE employee_id = ? AND effective_from = ?",
                            (emp_id, eff)).fetchone()
        vals = (gross, hra, basic_amt, hra_amt, tds_amt, 1 if request.form.get('pt_exempt') else 0,
                1 if request.form.get('pf_exempt') else 0,
                (request.form.get('notes') or '').strip()[:300], user.get('name') or '')
        if same:
            conn.execute("UPDATE employee_salary SET monthly_gross = ?, hra_pct = ?, basic_amount = ?, hra_amount = ?, "
                         "monthly_tds = ?, pt_exempt = ?, pf_exempt = ?, notes = ?, updated_by_name = ?, "
                         "updated_at = CURRENT_TIMESTAMP WHERE id = ?", vals + (same['id'],))
        else:
            conn.execute("INSERT INTO employee_salary (monthly_gross, hra_pct, basic_amount, hra_amount, monthly_tds, "
                         "pt_exempt, pf_exempt, notes, updated_by_name, employee_id, effective_from) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", vals + (emp_id, eff))
        conn.commit()
    finally:
        conn.close()
    flash(f"Salary saved for {emp['name']} — ₹{inr(gross)} / month from {period_label(eff)}.", 'success')
    return redirect(url_for('hr_payroll_salaries') + f"#emp-{emp_id}")


def payroll_exclude():
    """Mark an employee login as Not on payroll (or put them back)."""
    user, deny = _require_manager()
    if deny:
        return deny
    try:
        emp_id = int(request.form.get('employee_id'))
    except (TypeError, ValueError):
        abort(400)
    conn = get_db()
    try:
        _ensure(conn)
        emp = conn.execute("SELECT name FROM employees WHERE id = ?", (emp_id,)).fetchone()
        if not emp:
            abort(404)
        if request.form.get('action') == 'include':
            conn.execute("DELETE FROM payroll_exclusions WHERE employee_id = ?", (emp_id,))
            msg = f"{emp['name']} is back on payroll."
        else:
            if not conn.execute("SELECT 1 FROM payroll_exclusions WHERE employee_id = ?", (emp_id,)).fetchone():
                conn.execute("INSERT INTO payroll_exclusions (employee_id, excluded_by_name) VALUES (?, ?)",
                             (emp_id, user.get('name') or ''))
            msg = f"{emp['name']} is marked Not on payroll — no salary slip will be made for this login."
        conn.commit()
    finally:
        conn.close()
    flash(msg, 'success')
    return redirect(url_for('hr_payroll_salaries'))


def payroll_salary_delete(sal_id):
    user, deny = _require_manager()
    if deny:
        return deny
    conn = get_db()
    try:
        _ensure(conn)
        conn.execute("DELETE FROM employee_salary WHERE id = ?", (sal_id,))
        conn.commit()
    finally:
        conn.close()
    flash('Salary entry removed (payslips already calculated keep their figures).', 'success')
    return redirect(url_for('hr_payroll_salaries'))


# ─────────────────────────── employee: My Payslips ───────────────────────────

def _own_released_slip(conn, slip_id, user):
    """The slip ONLY if it belongs to the logged-in employee and its run is released."""
    r = conn.execute("SELECT p.* FROM payslips p JOIN payroll_runs r ON r.id = p.run_id "
                     "WHERE p.id = ? AND p.employee_id = ? AND r.status = 'released'",
                     (slip_id, user['id'])).fetchone()
    return dict(r) if r else None


def _otp_hash(code, emp_id, slip_id):
    key = (current_app.secret_key or 'payslip').encode() if isinstance(current_app.secret_key, str) \
        else (current_app.secret_key or b'payslip')
    return hmac.new(key, f"{emp_id}:{slip_id}:{code}".encode(), hashlib.sha256).hexdigest()


def _now_utc():
    return datetime.utcnow()


def _as_dt(v):
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v)[:26])
    except Exception:
        return None


def _is_unlocked(conn, emp_id, slip_id):
    r = conn.execute("SELECT unlocked_until FROM payslip_otp WHERE employee_id = ? AND payslip_id = ? "
                     "AND used = 1 AND unlocked_until IS NOT NULL ORDER BY id DESC LIMIT 1",
                     (emp_id, slip_id)).fetchone()
    until = _as_dt(r['unlocked_until']) if r else None
    return bool(until and until > _now_utc()), until


def my_payslips():
    user = _me()
    if not user:
        return redirect(url_for('login'))
    conn = get_db()
    try:
        _ensure(conn)
        slips = [dict(r) for r in conn.execute(
            "SELECT p.id, p.period FROM payslips p JOIN payroll_runs r ON r.id = p.run_id "
            "WHERE p.employee_id = ? AND r.status = 'released' ORDER BY p.period DESC", (user['id'],)).fetchall()]
    finally:
        conn.close()
    return render_template('my_payslips.html', user=user, slips=slips, period_label=period_label,
                           fy_label=fy_label, active_section='hr')


def my_payslip_view(slip_id):
    user = _me()
    if not user:
        return redirect(url_for('login'))
    conn = get_db()
    try:
        _ensure(conn)
        slip = _own_released_slip(conn, slip_id, user)
        if not slip:
            abort(404)
        unlocked, until = _is_unlocked(conn, user['id'], slip_id)
        rules = rules_for(conn, slip['period']) or {}
        if unlocked:
            _log(conn, slip_id, user['id'], user, 'view')
        masked = None
        try:
            a = _app()
            emp = conn.execute("SELECT * FROM employees WHERE id = ?", (user['id'],)).fetchone()
            num = a._employee_otp_number(dict(emp)) if emp else None
            masked = a._mask_mobile(num) if num else None
        except Exception:
            pass
    finally:
        conn.close()
    secs_left = int((until - _now_utc()).total_seconds()) if (unlocked and until) else 0
    if not unlocked:
        # Never send figures to the browser while locked.
        slip = {'id': slip['id'], 'period': slip['period'], 'emp_name': slip['emp_name']}
    return render_template('payslip_view.html', user=user, slip=slip, rules=rules, inr=inr,
                           words=rupees_in_words(slip.get('net_pay')) if unlocked else '',
                           period_label=period_label, admin_view=False, unlocked=unlocked,
                           secs_left=secs_left, masked=masked, active_section='hr')


def my_payslip_send_otp(slip_id):
    user = _me()
    if not user:
        return jsonify({'error': 'Please log in again.'}), 401
    conn = get_db()
    try:
        _ensure(conn)
        slip = _own_released_slip(conn, slip_id, user)
        if not slip:
            return jsonify({'error': 'Payslip not found.'}), 404
        now = _now_utc()
        recent = [dict(r) for r in conn.execute(
            "SELECT created_at FROM payslip_otp WHERE employee_id = ? ORDER BY id DESC LIMIT 10",
            (user['id'],)).fetchall()]
        times = [t for t in (_as_dt(r['created_at']) for r in recent) if t]
        if times and (now - times[0]).total_seconds() < OTP_RESEND_GAP_SECONDS:
            return jsonify({'error': 'Please wait a few seconds before asking for another code.'}), 429
        if sum(1 for t in times if (now - t).total_seconds() < 3600) >= OTP_MAX_SENDS_PER_HOUR:
            return jsonify({'error': 'Too many codes requested. Please try again in an hour.'}), 429
        a = _app()
        emp = conn.execute("SELECT * FROM employees WHERE id = ? AND is_active = 1", (user['id'],)).fetchone()
        num = a._employee_otp_number(dict(emp)) if emp else None
        if not num:
            return jsonify({'error': 'No WhatsApp number is on file for you. Please contact HR.'}), 400
        code = f"{random.SystemRandom().randint(0, 999999):06d}"
        # Burn any earlier unused code for this slip; store only a keyed hash.
        conn.execute("UPDATE payslip_otp SET used = 2 WHERE employee_id = ? AND payslip_id = ? AND used = 0",
                     (user['id'], slip_id))
        conn.execute("INSERT INTO payslip_otp (employee_id, payslip_id, code_hash, created_at) VALUES (?, ?, ?, ?)",
                     (user['id'], slip_id, _otp_hash(code, user['id'], slip_id), now))
        conn.commit()
        ok, err = a._send_otp_fast([('whatsapp', lambda: a._send_whatsapp_otp(num, code))])
        _log(conn, slip_id, user['id'], user, 'otp_sent' if ok else 'otp_send_failed')
    finally:
        conn.close()
    if not ok:
        return jsonify({'error': err or 'Could not send the code. Please try again.'}), 500
    return jsonify({'success': True, 'message': f'Code sent on WhatsApp to {a._mask_mobile(num)}.'})


def my_payslip_verify_otp(slip_id):
    user = _me()
    if not user:
        return jsonify({'error': 'Please log in again.'}), 401
    code = ''.join(ch for ch in str((request.get_json(silent=True) or {}).get('otp') or request.form.get('otp') or '')
                   if ch.isdigit())
    conn = get_db()
    try:
        _ensure(conn)
        slip = _own_released_slip(conn, slip_id, user)
        if not slip:
            return jsonify({'error': 'Payslip not found.'}), 404
        row = conn.execute("SELECT * FROM payslip_otp WHERE employee_id = ? AND payslip_id = ? AND used = 0 "
                           "ORDER BY id DESC LIMIT 1", (user['id'], slip_id)).fetchone()
        if not row:
            return jsonify({'error': 'Please request a code first.'}), 400
        row = dict(row)
        made = _as_dt(row['created_at'])
        if not made or (_now_utc() - made).total_seconds() > OTP_TTL_SECONDS:
            conn.execute("UPDATE payslip_otp SET used = 2 WHERE id = ?", (row['id'],)); conn.commit()
            return jsonify({'error': 'That code has expired. Please request a new one.'}), 400
        if int(row['tries'] or 0) >= OTP_MAX_TRIES:
            conn.execute("UPDATE payslip_otp SET used = 2 WHERE id = ?", (row['id'],)); conn.commit()
            return jsonify({'error': 'Too many wrong attempts. Please request a new code.'}), 400
        if not code or not hmac.compare_digest(_otp_hash(code, user['id'], slip_id), row['code_hash']):
            tries = int(row['tries'] or 0) + 1
            conn.execute("UPDATE payslip_otp SET tries = ?, used = ? WHERE id = ?",
                         (tries, 2 if tries >= OTP_MAX_TRIES else 0, row['id']))
            conn.commit()
            _log(conn, slip_id, user['id'], user, 'otp_wrong')
            left = OTP_MAX_TRIES - tries
            return jsonify({'error': f'Wrong code. {left} attempt{"s" if left != 1 else ""} left.' if left > 0
                            else 'Too many wrong attempts. Please request a new code.'}), 400
        conn.execute("UPDATE payslip_otp SET used = 1, unlocked_until = ? WHERE id = ?",
                     (_now_utc() + timedelta(seconds=UNLOCK_SECONDS), row['id']))
        conn.commit()
        _log(conn, slip_id, user['id'], user, 'unlocked')
    finally:
        conn.close()
    return jsonify({'success': True})


def my_payslip_downloaded(slip_id):
    """Logged by the page when the employee saves the PDF (only while unlocked)."""
    user = _me()
    if not user:
        return jsonify({'error': 'login'}), 401
    conn = get_db()
    try:
        _ensure(conn)
        slip = _own_released_slip(conn, slip_id, user)
        if not slip or not _is_unlocked(conn, user['id'], slip_id)[0]:
            return jsonify({'error': 'locked'}), 403
        _log(conn, slip_id, user['id'], user, 'download')
    finally:
        conn.close()
    return jsonify({'success': True})


def payroll_access_log(run_id):
    """Who opened / downloaded which slip in a run (payroll managers)."""
    user, deny = _require_manager()
    if deny:
        return deny
    conn = get_db()
    try:
        _ensure(conn)
        run = conn.execute("SELECT * FROM payroll_runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            abort(404)
        rows = [dict(r) for r in conn.execute(
            "SELECT l.*, p.emp_name FROM payslip_access_log l JOIN payslips p ON p.id = l.payslip_id "
            "WHERE p.run_id = ? ORDER BY l.id DESC LIMIT 500", (run_id,)).fetchall()]
    finally:
        conn.close()
    for r in rows:
        t = _as_dt(r['created_at'])
        r['ist'] = (t + timedelta(hours=5, minutes=30)).strftime('%d %b %Y, %I:%M %p') if t else ''
    return render_template('hr_payroll_log.html', user=user, run=dict(run), rows=rows,
                           period_label=period_label, active_section='hr')


# ──────────────────────────────── register ────────────────────────────────

def register_hr_payroll(app):
    lr = login_required
    rules = [
        ('/hr/payroll', 'hr_payroll', payroll_home, ['GET']),
        ('/hr/payroll/start', 'hr_payroll_start', payroll_start, ['POST']),
        ('/hr/payroll/run/<int:run_id>', 'hr_payroll_run', payroll_run, ['GET']),
        ('/hr/payroll/run/<int:run_id>/recalc', 'hr_payroll_recalc', payroll_recalc, ['POST']),
        ('/hr/payroll/run/<int:run_id>/status', 'hr_payroll_status', payroll_status, ['POST']),
        ('/hr/payroll/run/<int:run_id>/export', 'hr_payroll_export', payroll_export, ['GET']),
        ('/hr/payroll/run/<int:run_id>/log', 'hr_payroll_access_log', payroll_access_log, ['GET']),
        ('/hr/payroll/slip/<int:slip_id>', 'hr_payroll_slip_view', payroll_slip_view, ['GET']),
        ('/hr/payroll/slip/<int:slip_id>/save', 'hr_payroll_slip_save', payroll_slip_save, ['POST']),
        ('/hr/payroll/template', 'hr_payroll_template', payroll_template, ['GET', 'POST']),
        ('/hr/payroll/salaries', 'hr_payroll_salaries', payroll_salaries, ['GET']),
        ('/hr/payroll/salaries/save', 'hr_payroll_salary_save', payroll_salary_save, ['POST']),
        ('/hr/payroll/salaries/<int:sal_id>/delete', 'hr_payroll_salary_delete', payroll_salary_delete, ['POST']),
        ('/hr/payroll/salaries/exclude', 'hr_payroll_exclude', payroll_exclude, ['POST']),
        ('/my-payslips', 'my_payslips', my_payslips, ['GET']),
        ('/my-payslips/<int:slip_id>', 'my_payslip_view', my_payslip_view, ['GET']),
        ('/my-payslips/<int:slip_id>/send-otp', 'my_payslip_send_otp', my_payslip_send_otp, ['POST']),
        ('/my-payslips/<int:slip_id>/verify-otp', 'my_payslip_verify_otp', my_payslip_verify_otp, ['POST']),
        ('/my-payslips/<int:slip_id>/downloaded', 'my_payslip_downloaded', my_payslip_downloaded, ['POST']),
    ]
    for path, endpoint, fn, methods in rules:
        app.add_url_rule(path, endpoint=endpoint, view_func=lr(fn), methods=methods)
