"""Indian PGCP — negotiated "package" + instalment payments for team invites.
(founder 2026-10-16, phase 1 = team side)

A PAYING client invited by the team gets a negotiated package:
    list price (the plan's price) − discount (flat ₹ or a coupon)
    GST treatment:  'plus'      → final = (price − discount) × (1 + gst%/100)   (gst defaults to 18)
                    'inclusive' → final =  price − discount   (GST already inside)
    final package amount — auto-computed, but the team may overwrite it with the
    negotiated figure.
Payments are then recorded in instalments (pg_pgcp_payments). balance = final − Σ payments.
Status: due (nothing paid) → part_paid → paid (balance ≤ 0). A part-paid client gets
FULL plan access (auto_grant_internal_premium treats part_paid like paid).

LEGACY invites (created before this, gst_mode = '' and final_amount NULL) are read with
the old rule — final = invited_amount − discount, paid = paid_amount when
payment_status = 'paid' — and are NEVER written to just by viewing them. Only when the
team edits the package / records a payment on one is it "adopted" (snapshotted into the
new columns; an old offline paid_amount becomes an opening payment row).

Online self-purchase (website checkout) is untouched: plan price (+ its own gst) −
coupon, full payment only.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

DEFAULT_GST = Decimal('18')
PAY_MODES = [('bank', 'Bank transfer'), ('upi', 'UPI'), ('online', 'Online (Razorpay)'),
             ('cash', 'Cash'), ('other', 'Other')]
PAY_MODE_LABELS = dict(PAY_MODES)
STATUS_LABELS = {'due': 'Due', 'part_paid': 'Part-paid', 'paid': 'Paid'}

# Single source for the schema — run at boot (pgcp_tables.ensure_pgcp_tables) AND at
# request time (ensure_schema) because a Render cold start can skip boot DDL.
SCHEMA_DDL = [
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS payment_status TEXT DEFAULT 'due'",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS paid_online INTEGER DEFAULT 0",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS payment_ref TEXT DEFAULT ''",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS paid_amount NUMERIC(14,2)",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS list_price NUMERIC(14,2)",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS gst_mode TEXT DEFAULT ''",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS gst_percent NUMERIC(5,2)",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS discount_mode TEXT DEFAULT ''",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS coupon_code TEXT DEFAULT ''",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS final_amount NUMERIC(14,2)",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS balance_due_date TEXT DEFAULT ''",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS balance_due_note TEXT DEFAULT ''",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS balance_requested INTEGER DEFAULT 0",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS package_updated_by TEXT DEFAULT ''",
    "ALTER TABLE pg_pgcp_invitations ADD COLUMN IF NOT EXISTS package_updated_at TIMESTAMP",
    '''CREATE TABLE IF NOT EXISTS pg_pgcp_payments (
        id SERIAL PRIMARY KEY,
        invitation_id INTEGER NOT NULL,
        amount NUMERIC(14,2) NOT NULL DEFAULT 0,
        paid_on TEXT DEFAULT '',            -- YYYY-MM-DD (IST calendar date)
        mode TEXT DEFAULT '',               -- online | bank | upi | cash | other
        ref TEXT DEFAULT '',
        note TEXT DEFAULT '',
        recorded_by TEXT DEFAULT '',
        razorpay_order_id TEXT DEFAULT '',
        razorpay_payment_id TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''',
    "CREATE INDEX IF NOT EXISTS idx_pgcp_pay_inv ON pg_pgcp_payments (invitation_id)",
    '''CREATE TABLE IF NOT EXISTS pg_pgcp_payment_log (
        id SERIAL PRIMARY KEY,
        invitation_id INTEGER NOT NULL,
        action TEXT DEFAULT '',             -- created | package_edit | payment_add | payment_delete | ...
        detail TEXT DEFAULT '',
        done_by TEXT DEFAULT '',
        done_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''',
    "CREATE INDEX IF NOT EXISTS idx_pgcp_paylog_inv ON pg_pgcp_payment_log (invitation_id)",
    # A coupon used on a team invite has no doctor yet → note which invite it went to.
    "ALTER TABLE pg_coupon_redemptions ADD COLUMN IF NOT EXISTS invitation_id INTEGER",
    "ALTER TABLE pg_coupon_redemptions ADD COLUMN IF NOT EXISTS note TEXT DEFAULT ''",
]

_SCHEMA_OK = False


def ensure_schema(conn, force=False):
    """Request-time guard (idempotent; runs once per process once it succeeds)."""
    global _SCHEMA_OK
    if _SCHEMA_OK and not force:
        return
    ok = True
    for ddl in SCHEMA_DDL:
        try:
            conn.execute(ddl)
        except Exception as e:
            ok = False
            try: conn.rollback()
            except Exception: pass
            logging.error("pgcp_package.ensure_schema: %s", e)
    try:
        conn.commit()
    except Exception:
        pass
    _SCHEMA_OK = ok


# ── money ────────────────────────────────────────────────────────────────────
def D(v, default=None):
    """Decimal(2dp) from anything ('1,999', 1999.0, Decimal, None)."""
    if v is None:
        return default
    s = str(v).replace(',', '').replace('₹', '').strip()
    if s == '':
        return default
    try:
        return Decimal(s).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        return default


def _q(x):
    return x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def compute_package(list_price, discount_amount=0, gst_mode='plus', gst_percent=None,
                    override_final=None):
    """Pure package maths. Returns floats:
        {list_price, discount, gst_mode, gst_percent, taxable, gst, computed_final,
         final, overridden}
    'plus'      : taxable = price − discount; gst = taxable × pct; final = taxable + gst
    'inclusive' : final = price − discount; GST is inside: taxable = final ÷ (1+pct), gst = final − taxable
    override_final (the team's negotiated figure) replaces final; taxable/gst are then
    re-derived from it (GST inside the agreed number) so the breakdown still adds up."""
    price = D(list_price, Decimal('0')) or Decimal('0')
    if price < 0:
        price = Decimal('0')
    disc = D(discount_amount, Decimal('0')) or Decimal('0')
    disc = max(Decimal('0'), min(disc, price))
    mode = 'inclusive' if (gst_mode or '').strip().lower() == 'inclusive' else 'plus'
    pct = D(gst_percent)
    if pct is None:
        pct = DEFAULT_GST
    pct = max(Decimal('0'), min(pct, Decimal('100')))
    rate = pct / Decimal('100')
    base = price - disc
    if mode == 'plus':
        taxable = base
        gst = _q(taxable * rate)
        computed = taxable + gst
    else:
        computed = base
        taxable = _q(computed / (Decimal('1') + rate)) if rate else computed
        gst = computed - taxable
    final = computed
    overridden = False
    ov = D(override_final)
    if ov is not None and ov >= 0 and abs(ov - computed) >= Decimal('0.01'):
        overridden = True
        final = ov
        taxable = _q(final / (Decimal('1') + rate)) if rate else final
        gst = final - taxable
    return {'list_price': float(price), 'discount': float(disc), 'gst_mode': mode,
            'gst_percent': float(pct), 'taxable': float(taxable), 'gst': float(gst),
            'computed_final': float(computed), 'final': float(final),
            'overridden': overridden}


def status_for(final, paid):
    """due (nothing paid) → part_paid → paid (balance ≤ 0)."""
    paid = paid or Decimal('0')
    if paid <= 0:
        return 'due'
    if final is None:
        return 'part_paid'
    return 'paid' if (final - paid) <= 0 else 'part_paid'


# ── reads ────────────────────────────────────────────────────────────────────
def is_legacy(inv):
    return inv.get('final_amount') is None and not (inv.get('gst_mode') or '').strip()


def list_payments(conn, invite_id):
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM pg_pgcp_payments WHERE invitation_id = ? ORDER BY paid_on, id",
            [invite_id]).fetchall()]
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("pgcp_package.list_payments: %s", e)
        return []


def payments_by_invite(conn):
    """{invitation_id: [payments...]} — one query for list screens."""
    out = {}
    try:
        for r in conn.execute("SELECT * FROM pg_pgcp_payments ORDER BY paid_on, id").fetchall():
            r = dict(r)
            out.setdefault(r['invitation_id'], []).append(r)
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("pgcp_package.payments_by_invite: %s", e)
    return out


def summary(conn, inv, payments=None):
    """Read-only money picture of one invite (never writes):
        {final, paid, balance, status, status_label, payments[], legacy, last_paid_on}
    Pass `payments` (from payments_by_invite) to avoid a query per row."""
    inv = dict(inv or {})
    pays = payments if payments is not None else list_payments(conn, inv.get('id'))
    pay_sum = sum((D(p.get('amount'), Decimal('0')) for p in pays), Decimal('0'))
    legacy = is_legacy(inv)
    if legacy:
        inv_amt = D(inv.get('invited_amount'))
        final = (inv_amt - (D(inv.get('discount'), Decimal('0')) or Decimal('0'))) if inv_amt is not None else None
        base_paid = Decimal('0')
        if (inv.get('payment_status') or 'due') == 'paid':
            base_paid = D(inv.get('paid_amount'), Decimal('0')) or Decimal('0')
        paid = base_paid + pay_sum
        if (inv.get('payment_status') or 'due') == 'paid' and not pays:
            status = 'paid'    # old rows: trust the stored flag exactly as before
        else:
            status = status_for(final, paid)
    else:
        final = D(inv.get('final_amount'))
        paid = pay_sum
        status = status_for(final, paid)
    balance = (final - paid) if final is not None else None
    last = ''
    for p in pays:
        if (p.get('paid_on') or '') > last:
            last = p.get('paid_on') or ''
    return {
        'final': float(final) if final is not None else None,
        'paid': float(paid),
        'balance': float(balance) if balance is not None else None,
        'status': status,
        'status_label': STATUS_LABELS.get(status, status),
        'payments': pays,
        'legacy': legacy,
        'last_paid_on': last,
    }


# ── writes (only for invites the team is actively editing) ───────────────────
def log(conn, invite_id, action, detail, by):
    try:
        conn.execute("INSERT INTO pg_pgcp_payment_log (invitation_id, action, detail, done_by) "
                     "VALUES (?,?,?,?)", [invite_id, action, detail or '', by or ''])
    except Exception as e:
        logging.error("pgcp_package.log: %s", e)
        raise


def add_payment(conn, invite_id, amount, paid_on, mode, ref, note, by,
                razorpay_order_id='', razorpay_payment_id=''):
    amt = D(amount)
    if amt is None or amt <= 0:
        raise ValueError('Payment amount must be more than 0')
    mode = mode if mode in PAY_MODE_LABELS else 'other'
    pid = conn.execute(
        "INSERT INTO pg_pgcp_payments (invitation_id, amount, paid_on, mode, ref, note, "
        "recorded_by, razorpay_order_id, razorpay_payment_id) VALUES (?,?,?,?,?,?,?,?,?) "
        "RETURNING id",
        [invite_id, float(amt), (paid_on or '').strip(), mode, (ref or '').strip(),
         (note or '').strip(), by or '', razorpay_order_id or '', razorpay_payment_id or '']
    ).fetchone()['id']
    log(conn, invite_id, 'payment_add',
        f"₹{amt:,.2f} on {paid_on or '—'} via {PAY_MODE_LABELS.get(mode, mode)}"
        + (f" · ref {ref}" if ref else '') + (f" · {note}" if note else ''), by)
    return pid


def adopt_legacy(conn, inv, by):
    """First team edit on a legacy invite: snapshot the old figures into the package
    columns (final = invited − discount, GST treated as inside) and turn an old offline
    paid_amount into an opening payment row, so nothing is double-counted afterwards.
    No-op for non-legacy invites. Caller commits."""
    if not is_legacy(inv):
        return inv
    inv_amt = D(inv.get('invited_amount'))
    disc = D(inv.get('discount'), Decimal('0')) or Decimal('0')
    final = (inv_amt - disc) if inv_amt is not None else None
    conn.execute(
        "UPDATE pg_pgcp_invitations SET list_price = COALESCE(list_price, ?), gst_mode = 'inclusive', "
        "gst_percent = COALESCE(gst_percent, ?), discount_mode = CASE WHEN COALESCE(discount_mode,'') = '' "
        "THEN 'flat' ELSE discount_mode END, final_amount = ? WHERE id = ?",
        [float(inv_amt) if inv_amt is not None else None, float(DEFAULT_GST),
         float(final) if final is not None else None, inv['id']])
    opening = ''
    if (inv.get('payment_status') or 'due') == 'paid':
        pa = D(inv.get('paid_amount'))
        if pa is not None and pa > 0:
            conn.execute(
                "INSERT INTO pg_pgcp_payments (invitation_id, amount, paid_on, mode, ref, note, "
                "recorded_by, razorpay_payment_id) VALUES (?,?,?,?,?,?,?,?)",
                [inv['id'], float(pa), str(inv.get('created_at') or '')[:10],
                 'online' if inv.get('paid_online') else 'other', inv.get('payment_ref') or '',
                 'Opening balance — paid before instalment tracking', by or '',
                 (inv.get('payment_ref') or '') if inv.get('paid_online') else ''])
            opening = f"; opening payment ₹{pa:,.2f} carried over"
    log(conn, inv['id'], 'adopt_legacy',
        f"Old invite moved to package tracking: final ₹{final:,.2f}" if final is not None
        else "Old invite moved to package tracking (no amount on file)", by)
    if opening:
        log(conn, inv['id'], 'adopt_legacy', opening.lstrip('; '), by)
    row = conn.execute("SELECT * FROM pg_pgcp_invitations WHERE id = ?", [inv['id']]).fetchone()
    return dict(row) if row else inv


def refresh_status(conn, invite_id):
    """Recompute from final_amount + payments; store payment_status (due|part_paid|paid)
    and keep paid_amount = total paid (so every existing reader stays correct).
    Call ONLY on invites the team edits / records payments for. Caller commits."""
    row = conn.execute("SELECT * FROM pg_pgcp_invitations WHERE id = ?", [invite_id]).fetchone()
    if not row:
        return None
    inv = dict(row)
    pays = list_payments(conn, invite_id)
    paid = sum((D(p.get('amount'), Decimal('0')) for p in pays), Decimal('0'))
    final = D(inv.get('final_amount'))
    st = status_for(final, paid)
    last_ref = ''
    for p in pays:
        if (p.get('ref') or p.get('razorpay_payment_id')):
            last_ref = p.get('razorpay_payment_id') or p.get('ref')
    conn.execute(
        "UPDATE pg_pgcp_invitations SET payment_status = ?, paid_amount = ?, "
        "payment_ref = CASE WHEN ? <> '' THEN ? ELSE COALESCE(payment_ref,'') END WHERE id = ?",
        [st, float(paid) if pays else None, last_ref, last_ref, invite_id])
    return st


def redeem_coupon_for_invite(conn, coupon, invite_id, plan_id, order_amount, discount, by):
    """Burn one coupon use for a team invite (no doctor yet → user_id NULL, note the
    invite). Guards the per-coupon TOTAL limit atomically. Returns True/False.
    Caller commits (or rolls back on False)."""
    row = conn.execute(
        "UPDATE pg_coupons SET used_count = COALESCE(used_count,0) + 1 WHERE id = ? "
        "AND (usage_limit_total IS NULL OR COALESCE(used_count,0) < usage_limit_total) RETURNING id",
        [coupon['coupon_id']]).fetchone()
    if not row:
        return False
    conn.execute(
        "INSERT INTO pg_coupon_redemptions (coupon_id, coupon_code, user_id, plan_id, "
        "order_amount, discount_amount, invitation_id, note) VALUES (?,?,?,?,?,?,?,?)",
        [coupon['coupon_id'], coupon.get('code') or '', None, plan_id,
         float(D(order_amount, Decimal('0'))), float(D(discount, Decimal('0'))), invite_id,
         f"PGCP team invite #{invite_id} (by {by or 'team'})"])
    return True
