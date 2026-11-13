"""Mock packages: what they unlock, prices, upgrades, coupons, granting (founder 2026-11-13).

Kept apart from the counselling plans (pg_plans / pg_subscriptions): the portal treats a doctor's newest
subscription as THE plan, and granting a counselling plan cancels other active subscriptions — so a mock
package stored there would knock out (or be knocked out by) a counselling plan. Here a doctor can hold both.

Packages (editable in admin, prices INCLUDE GST):
    Starter  ₹999   first 5 full mocks
    Standard ₹2,499 first 15 full mocks + all subject tests
    Pro      ₹3,999 first 30 full mocks + all subject tests + all mini tests
"First N full mocks" = the published full mocks in display order, the free sample not counted.
Upgrading: the doctor pays the difference — the list price of the package they already hold is credited.
Coupons: the same codes as goocampus.in, for coupons that apply to "all plans" (plan-specific coupons are
for counselling plans).
"""
from datetime import datetime, timedelta

GST_RATE = 18


def today_ist():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()


def money(v):
    return round(float(v or 0), 2)


def gst_inside(payable):
    """GST contained in a GST-inclusive amount."""
    p = money(payable)
    return round(p - p / (1 + GST_RATE / 100.0), 2)


def all_packages(conn, tenant_id, exam_code, active_only=True):
    sql = "SELECT * FROM ex_packages WHERE tenant_id=? AND exam_code=?"
    if active_only:
        sql += " AND is_active=1"
    return [dict(r) for r in conn.execute(sql + " ORDER BY sort_order, id", (tenant_id, exam_code)).fetchall()]


def owned(conn, user_id, tenant_id, exam_code):
    """The doctor's live purchases (status active, not past valid_until), with their package."""
    rows = conn.execute(
        "SELECT pp.id AS purchase_id, pp.source, pp.price_paid, pp.valid_until AS purchase_valid_until, pp.created_at, "
        "k.* FROM ex_package_purchases pp JOIN ex_packages k ON k.id = pp.package_id "
        "WHERE pp.user_id=? AND pp.status='active' AND k.tenant_id=? AND k.exam_code=? ORDER BY pp.id",
        (user_id, tenant_id, exam_code)).fetchall()
    today = today_ist()
    out = []
    for r in rows:
        r = dict(r)
        vu = r.get('purchase_valid_until')
        if vu is not None and vu < today:
            continue
        out.append(r)
    return out


def entitlement(conn, user_id, tenant_id, exam_code):
    """What the doctor's packages add up to."""
    mine = owned(conn, user_id, tenant_id, exam_code)
    return {
        'full_mocks': max([int(p['full_mocks'] or 0) for p in mine] or [0]),
        'subject_tests': any(p['subject_tests'] for p in mine),
        'mini_tests': any(p['mini_tests'] for p in mine),
        'packages': [{'code': p['code'], 'name': p['name'], 'valid_until': str(p['purchase_valid_until'] or ''),
                      'source': p['source']} for p in mine],
        'held_value': max([money(p['price']) for p in mine] or [0]),
        'held_codes': {p['code'] for p in mine},
    }


def full_mock_positions(conn, tenant_id, exam_code):
    """{paper_id: 1-based position} of published full mocks in display order (free sample not counted)."""
    rows = conn.execute("SELECT id FROM ex_papers WHERE tenant_id=? AND exam_code=? AND status='published' "
                        "AND kind='full' AND is_free_sample=0 ORDER BY sort_order, id", (tenant_id, exam_code)).fetchall()
    return {r['id']: i for i, r in enumerate(rows, 1)}


def covers(pkg_a, pkg_b):
    """True if package a already gives everything package b gives."""
    return (int(pkg_a['full_mocks'] or 0) >= int(pkg_b['full_mocks'] or 0)
            and (pkg_a['subject_tests'] or not pkg_b['subject_tests'])
            and (pkg_a['mini_tests'] or not pkg_b['mini_tests']))


def quote(conn, user_id, pkg, coupon_code=''):
    """Price for this doctor: list price − upgrade credit − coupon. → (ok, dict | error dict)."""
    ent_pk = owned(conn, user_id, pkg['tenant_id'], pkg['exam_code'])
    if any(covers(p, pkg) for p in ent_pk):
        return False, {'error': 'already_owned', 'message': 'Your current package already includes everything in this one.'}
    amount = money(pkg['price'])
    credit = min(amount, max([money(p['price']) for p in ent_pk] or [0]))
    base = round(amount - credit, 2)
    discount, coupon_id, code = 0.0, None, ''
    if (coupon_code or '').strip():
        from pg_admin.data import coupons as coupon_lib
        c = coupon_lib.find(conn, coupon_code.strip())
        if c and (c.get('applies_to') or 'all') == 'plans':
            return False, {'error': 'invalid_coupon', 'message': 'This coupon is for counselling plans, not mock packages.'}
        ok, res = coupon_lib.validate(conn, coupon_code.strip(), plan_id=None, user_id=user_id, amount=base, gst_percent=0)
        if not ok:
            return False, {'error': 'invalid_coupon', 'message': res.get('error') or 'That coupon is not valid.'}
        discount, coupon_id, code = min(base, money(res.get('discount'))), res.get('coupon_id'), res.get('code') or coupon_code
    payable = max(0.0, round(base - discount, 2))
    return True, {'package': pkg['code'], 'amount': amount, 'upgrade_credit': credit, 'discount': discount,
                  'coupon_code': code, 'coupon_id': coupon_id, 'payable': payable,
                  'gst_included': gst_inside(payable), 'gst_rate': GST_RATE,
                  'valid_until': str(pkg.get('valid_until') or '')}


def grant(conn, user_id, pkg, source, price_paid=0, order_id=None, granted_by='', notes=''):
    """Gives the doctor a package. Returns the purchase id."""
    return conn.execute(
        "INSERT INTO ex_package_purchases (tenant_id, user_id, package_id, source, price_paid, order_id, valid_until, "
        "notes, granted_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (pkg['tenant_id'], user_id, pkg['id'], source, money(price_paid), order_id, pkg.get('valid_until'),
         (notes or '')[:300], granted_by or '')).fetchone()['id']


def public_view(p, ent=None):
    """A package as the store page shows it."""
    ent = ent or {}
    held = p['code'] in (ent.get('held_codes') or set())
    return {'code': p['code'], 'name': p['name'], 'tagline': p.get('tagline') or '', 'price': money(p['price']),
            'price_note': 'incl. GST', 'full_mocks': int(p['full_mocks'] or 0),
            'subject_tests': bool(p['subject_tests']), 'mini_tests': bool(p['mini_tests']),
            'valid_until': str(p.get('valid_until') or ''), 'recommended': bool(p.get('is_recommended')),
            'owned': held}
