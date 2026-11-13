"""Mock Tests › Packages — edit the packages, see purchases + sales, give a package to a doctor (admin only)."""
import logging
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash

from db import get_db
from core.auth import login_required
from exam_engine import packages as K, store
from exam_engine.admin import _admin, _who, _deny, _close, EXAM_CODE
from exam_engine.tables import TENANT_GOOCAMPUS_IN


@login_required
def packages_admin():
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        pk = K.all_packages(conn, TENANT_GOOCAMPUS_IN, EXAM_CODE, active_only=False)
        sales = {r['package_id']: dict(r) for r in conn.execute(
            "SELECT package_id, COUNT(*) AS n, COALESCE(SUM(price_paid), 0) AS revenue, "
            "SUM(CASE WHEN source='admin_grant' THEN 1 ELSE 0 END) AS grants "
            "FROM ex_package_purchases WHERE tenant_id=? AND status='active' GROUP BY package_id",
            (TENANT_GOOCAMPUS_IN,)).fetchall()}
        q = (request.args.get('q') or '').strip()
        sql = ("SELECT pp.*, k.name AS package_name, u.name AS doctor_name, u.mobile, o.coupon_code, o.discount, "
               "o.credit, o.razorpay_payment_id FROM ex_package_purchases pp JOIN ex_packages k ON k.id = pp.package_id "
               "LEFT JOIN pg_users u ON u.id = pp.user_id LEFT JOIN ex_orders o ON o.id = pp.order_id "
               "WHERE pp.tenant_id=?")
        params = [TENANT_GOOCAMPUS_IN]
        if q:
            sql += " AND (u.name ILIKE ? OR u.mobile ILIKE ?)"
            params += ['%' + q + '%', '%' + q + '%']
        purchases = [dict(r) for r in conn.execute(sql + " ORDER BY pp.id DESC LIMIT 200", tuple(params)).fetchall()]
        for r in purchases:
            r['when'] = store.now_ist_str(r['created_at'])
            nm = (r.get('doctor_name') or '').strip()
            r['doctor'] = ('Dr. ' + nm if nm and not nm.lower().startswith('dr') else nm) or f"#{r['user_id']}"
        pending = conn.execute("SELECT COUNT(*) AS n FROM ex_orders WHERE tenant_id=? AND status='created' "
                               "AND created_at > CURRENT_TIMESTAMP - INTERVAL '2 days'", (TENANT_GOOCAMPUS_IN,)).fetchone()['n']
        totals = {'buyers': len({r['user_id'] for r in purchases if r['status'] == 'active'}),
                  'revenue': sum(float(s['revenue'] or 0) for s in sales.values()),
                  'sold': sum(int(s['n'] or 0) - int(s['grants'] or 0) for s in sales.values()),
                  'pending': pending}
        return render_template('exam_engine/packages.html', packages=pk, sales=sales, purchases=purchases,
                               totals=totals, q=q, tab='ex_packages')
    finally:
        _close(conn)


@login_required
def package_save(pkg_id):
    user = _admin()
    if not user:
        return _deny()
    f = request.form
    conn = get_db()
    try:
        p = conn.execute("SELECT * FROM ex_packages WHERE id=? AND tenant_id=?", (pkg_id, TENANT_GOOCAMPUS_IN)).fetchone()
        if not p:
            flash('Package not found.', 'error')
            return redirect(url_for('ex_packages'))
        try:
            price = round(float(f.get('price')), 2)
            full = max(0, int(f.get('full_mocks') or 0))
            vu = datetime.strptime(f.get('valid_until'), '%Y-%m-%d').date() if f.get('valid_until') else None
        except (TypeError, ValueError):
            flash('Check the price, number of mocks and the date (YYYY-MM-DD).', 'error')
            return redirect(url_for('ex_packages'))
        if price <= 0:
            flash('The price must be more than ₹0.', 'error')
            return redirect(url_for('ex_packages'))
        conn.execute("UPDATE ex_packages SET name=?, tagline=?, price=?, full_mocks=?, subject_tests=?, mini_tests=?, "
                     "valid_until=?, is_active=?, is_recommended=?, updated_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     ((f.get('name') or p['name']).strip()[:60], (f.get('tagline') or '').strip()[:160], price, full,
                      bool(f.get('subject_tests')), bool(f.get('mini_tests')), vu, 1 if f.get('is_active') else 0,
                      1 if f.get('is_recommended') else 0, _who(user), pkg_id))
        if f.get('is_recommended'):
            conn.execute("UPDATE ex_packages SET is_recommended=0 WHERE tenant_id=? AND exam_code=? AND id <> ?",
                         (TENANT_GOOCAMPUS_IN, EXAM_CODE, pkg_id))
        conn.commit()
        flash(f'Saved {p["name"]}. New buyers get these terms; existing buyers keep their access dates.', 'success')
        return redirect(url_for('ex_packages'))
    finally:
        _close(conn)


@login_required
def package_grant():
    """Give a package to a doctor at no charge (e.g. a scholarship or a team decision)."""
    user = _admin()
    if not user:
        return _deny()
    f = request.form
    mobile = ''.join(ch for ch in (f.get('mobile') or '') if ch.isdigit())[-10:]
    conn = get_db()
    try:
        p = conn.execute("SELECT * FROM ex_packages WHERE id=? AND tenant_id=?",
                         (int(f.get('package_id') or 0), TENANT_GOOCAMPUS_IN)).fetchone()
        if not p or len(mobile) != 10:
            flash('Enter the doctor\'s 10-digit mobile number and choose a package.', 'error')
            return redirect(url_for('ex_packages'))
        u = conn.execute("SELECT id, name FROM pg_users WHERE RIGHT(regexp_replace(COALESCE(mobile,''), '[^0-9]', '', 'g'), 10) = ? "
                         "ORDER BY id LIMIT 1", (mobile,)).fetchone()
        if not u:
            flash(f'No goocampus.in account with mobile {mobile}. Ask the doctor to log in on goocampus.in once first.', 'error')
            return redirect(url_for('ex_packages'))
        note = (f.get('note') or '').strip()
        if not note:
            flash('Add a short reason (e.g. "scholarship", "refund replacement").', 'error')
            return redirect(url_for('ex_packages'))
        K.grant(conn, u['id'], dict(p), 'admin_grant', 0, None, _who(user), note)
        conn.commit()
        flash(f'Gave {p["name"]} to {u["name"] or mobile}.', 'success')
        return redirect(url_for('ex_packages'))
    finally:
        _close(conn)


@login_required
def purchase_cancel(purchase_id):
    """Turns a package off for a doctor (e.g. after a refund). Their past attempts and results stay."""
    user = _admin()
    if not user:
        return _deny()
    conn = get_db()
    try:
        r = conn.execute("UPDATE ex_package_purchases SET status='cancelled', cancelled_at=CURRENT_TIMESTAMP, "
                         "notes = COALESCE(notes,'') || ? WHERE id=? AND status='active' RETURNING id",
                         (f" · cancelled by {_who(user)}: {(request.form.get('reason') or '').strip()[:200]}",
                          purchase_id)).fetchone()
        conn.commit()
        flash('Package turned off for this doctor.' if r else 'Already cancelled.', 'success' if r else 'info')
        return redirect(url_for('ex_packages'))
    finally:
        _close(conn)


def register_routes(app):
    r = app.add_url_rule
    r('/admin/pg/mocks/packages', 'ex_packages', packages_admin, methods=['GET'])
    r('/admin/pg/mocks/packages/<int:pkg_id>/save', 'ex_package_save', package_save, methods=['POST'])
    r('/admin/pg/mocks/packages/grant', 'ex_package_grant', package_grant, methods=['POST'])
    r('/admin/pg/mocks/packages/purchase/<int:purchase_id>/cancel', 'ex_purchase_cancel', purchase_cancel,
      methods=['POST'])
