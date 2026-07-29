"""Pricing, plans, entitlements, subscriptions and coupons for goocampus.in.

DESIGN NOTE — why a feature *catalogue* instead of columns  (founder 2026-07-28)
-------------------------------------------------------------------------------
The founder asked to be able to configure, per plan: "how many states they can see
in the predictor, how many PDFs they can access, how many mentor sessions are
included" — and to keep adding to that list as the product grows.

Hard-coding those as columns (`predictor_states INT`, `pdf_limit INT`, ...) means a
code change + deploy every time a new thing needs gating. So instead:

    pg_features        the CATALOGUE  — one row per gateable thing
    pg_plans           the PRODUCTS   — one row per pricing plan (incl. the Free one)
    pg_plan_features   the MATRIX     — plan x feature -> off / limited(N) / unlimited

Adding "AI college shortlist, 5 per month" later = insert one pg_features row. The
admin plan editor grows a new line by itself; no deploy, no migration.

USAGE TRACKING — distinct items, not raw hits
---------------------------------------------
"They can view 3 PDFs" must mean 3 *different* PDFs. If a doctor reopens the same
PDF tomorrow that cannot burn another slot — that would feel broken and generate
support mail. So pg_usage_items records WHICH item was consumed (pdf id, state
name, ...) and the quota check counts DISTINCT items. Re-opening something you
already unlocked is always free.

Everything is idempotent — safe to run on every boot, like the rest of the portal.
"""
import logging
from db import get_db


# ── The seeded catalogue ──────────────────────────────────────────────────────
# (code, name, description, unit, reset_period, resource_kind, sort)
#   unit          'boolean' = on/off switch      'quota' = a number
#   reset_period  'lifetime' | 'monthly' | 'daily' | 'plan_period'
#   resource_kind non-empty => quota counts DISTINCT items of this kind
_SEED_FEATURES = [
    ('predictor_access', 'College Predictor', 'Can the doctor open the predictor at all.',
     'boolean', 'lifetime', '', 10),
    ('predictor_states', 'Predictor — states visible',
     'How many different states of allotment data they can see. The free plan is '
     'normally 1, so they see the value and upgrade for the rest.',
     'quota', 'lifetime', 'state', 20),
    ('predictor_searches', 'Predictor — searches',
     'How many predictions they can run in the period.',
     'quota', 'monthly', '', 30),
    ('pdf_library', 'NEET-PG PDF library', 'Can the doctor open the PDF library at all.',
     'boolean', 'lifetime', '', 40),
    ('pdf_documents', 'PDF library — documents',
     'How many different PDFs they can open. Re-opening one they already unlocked '
     'is always free and never counts again.',
     'quota', 'lifetime', 'pdf', 50),
    ('pdf_downloads', 'PDF library — downloads',
     'How many PDFs they can download in the period (viewing is counted separately).',
     'quota', 'monthly', '', 60),
    ('mentor_directory', 'Mentor directory', 'Can they browse the mentor list and profiles.',
     'boolean', 'lifetime', '', 70),
    ('mentor_sessions', 'Mentor sessions included',
     'Sessions included in the plan at no extra cost. Set 0 on the free plan — free '
     'users can still book and pay for a mentor individually (see the next feature).',
     'quota', 'plan_period', '', 80),
    ('mentor_paid_booking', 'Book a mentor individually (pay per session)',
     'Lets the doctor book and pay for a single mentor session on their own, outside '
     'any plan. Keep this ON for the free plan — it is a revenue path, not a perk.',
     'boolean', 'lifetime', '', 90),
    ('college_shortlist', 'Saved college shortlist', 'Can they save and revisit a shortlist.',
     'boolean', 'lifetime', '', 100),
    ('counselling_call', 'Free counselling call', 'Entitles them to a call with the sales team.',
     'boolean', 'lifetime', '', 110),
    ('priority_support', 'Priority support', 'Flags them for faster response.',
     'boolean', 'lifetime', '', 120),
]


def ensure_pg_plans_tables():
    """Create/patch every pricing table. Idempotent; called at boot."""
    conn = get_db()
    try:
        # ── The catalogue of gateable things ──────────────────────────────────
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_features (
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            unit TEXT DEFAULT 'quota',
            reset_period TEXT DEFAULT 'lifetime',
            resource_kind TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 100,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # ── The plans themselves ──────────────────────────────────────────────
        # compare_at_price drives the struck-through "was" price; badge_* drive the
        # Bestseller / Most Popular ribbon the founder asked for.
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_plans (
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            tagline TEXT DEFAULT '',
            description TEXT DEFAULT '',
            plan_kind TEXT DEFAULT 'paid',
            price NUMERIC(12,2) DEFAULT 0,
            compare_at_price NUMERIC(12,2),
            currency TEXT DEFAULT 'INR',
            billing_period TEXT DEFAULT 'one_time',
            duration_days INTEGER,
            badge_text TEXT DEFAULT '',
            badge_color TEXT DEFAULT '#F57C1F',
            accent_color TEXT DEFAULT '#2952A3',
            is_featured INTEGER DEFAULT 0,
            highlights TEXT DEFAULT '[]',
            cta_label TEXT DEFAULT '',
            seats_limit INTEGER,
            razorpay_plan_id TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            is_public INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 100,
            created_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # ── plan x feature ────────────────────────────────────────────────────
        # value_type: 'off' | 'limited' (limit_value) | 'unlimited'
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_plan_features (
            id SERIAL PRIMARY KEY,
            plan_id INTEGER NOT NULL,
            feature_code TEXT NOT NULL,
            value_type TEXT DEFAULT 'off',
            limit_value INTEGER,
            note TEXT DEFAULT '',
            UNIQUE (plan_id, feature_code)
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_plan_features_plan "
                     "ON pg_plan_features (plan_id)")

        # ── who is on what ────────────────────────────────────────────────────
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_subscriptions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            status TEXT DEFAULT 'active',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            price_paid NUMERIC(12,2) DEFAULT 0,
            discount_amount NUMERIC(12,2) DEFAULT 0,
            coupon_code TEXT DEFAULT '',
            payment_ref TEXT DEFAULT '',
            source TEXT DEFAULT 'admin_grant',
            notes TEXT DEFAULT '',
            granted_by TEXT DEFAULT '',
            cancelled_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_subs_user "
                     "ON pg_subscriptions (user_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_subs_plan "
                     "ON pg_subscriptions (plan_id)")

        # ── usage: one row per DISTINCT thing consumed ────────────────────────
        # period_key is 'lifetime' or 'YYYY-MM' / 'YYYY-MM-DD' so a monthly quota
        # resets by simply looking at a different key — no cron, nothing to expire.
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_usage_items (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            feature_code TEXT NOT NULL,
            period_key TEXT DEFAULT 'lifetime',
            item_key TEXT DEFAULT '',
            hits INTEGER DEFAULT 1,
            first_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, feature_code, period_key, item_key)
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_usage_lookup "
                     "ON pg_usage_items (user_id, feature_code, period_key)")

        # ── coupons ───────────────────────────────────────────────────────────
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_coupons (
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            discount_type TEXT DEFAULT 'percent',
            discount_value NUMERIC(12,2) DEFAULT 0,
            max_discount_amount NUMERIC(12,2),
            min_order_amount NUMERIC(12,2) DEFAULT 0,
            valid_from TIMESTAMP,
            valid_until TIMESTAMP,
            usage_limit_total INTEGER,
            usage_limit_per_user INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            applies_to TEXT DEFAULT 'all',
            first_time_only INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_coupon_plans (
            id SERIAL PRIMARY KEY,
            coupon_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            UNIQUE (coupon_id, plan_id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_coupon_redemptions (
            id SERIAL PRIMARY KEY,
            coupon_id INTEGER NOT NULL,
            coupon_code TEXT DEFAULT '',
            user_id INTEGER,
            subscription_id INTEGER,
            plan_id INTEGER,
            order_amount NUMERIC(12,2) DEFAULT 0,
            discount_amount NUMERIC(12,2) DEFAULT 0,
            redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_coupon_redeem "
                     "ON pg_coupon_redemptions (coupon_id, user_id)")

        # ── admin-side columns on the existing doctor record ──────────────────
        # pg_users was created by the OTP work; these are the fields the admin
        # screen needs. Added one-by-one so an existing column can't abort the lot.
        for col, ddl in [
            ('is_blocked', 'INTEGER DEFAULT 0'),
            ('admin_notes', "TEXT DEFAULT ''"),
            ('city', "TEXT DEFAULT ''"),
            ('state', "TEXT DEFAULT ''"),
            ('college', "TEXT DEFAULT ''"),
            ('source', "TEXT DEFAULT ''"),
            ('tags', "TEXT DEFAULT ''"),
            ('updated_by', "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE pg_users ADD COLUMN IF NOT EXISTS {col} {ddl}")
            except Exception:
                conn.rollback()

        conn.commit()
        logging.info("pg pricing tables ensured successfully")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"ensure_pg_plans_tables: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def seed_pg_pricing_defaults():
    """Seed the feature catalogue, and a starter Free plan the first time only.

    ADDITIVE: an existing feature row is never overwritten — the founder may have
    renamed or reworded it, and a boot must not undo that. Only genuinely new codes
    are inserted. Likewise the Free plan is created only if NO plan exists at all,
    so a boot can never resurrect or alter a plan that was edited or removed.
    """
    conn = get_db()
    try:
        existing = {r['code'] for r in
                    conn.execute("SELECT code FROM pg_features").fetchall()}
        added = 0
        for code, name, desc, unit, period, kind, sort in _SEED_FEATURES:
            if code in existing:
                continue
            conn.execute(
                "INSERT INTO pg_features (code, name, description, unit, "
                "reset_period, resource_kind, sort_order) VALUES (?,?,?,?,?,?,?)",
                (code, name, desc, unit, period, kind, sort))
            added += 1

        row = conn.execute("SELECT COUNT(*) AS n FROM pg_plans").fetchone()
        if (row['n'] if row else 0) == 0:
            conn.execute(
                "INSERT INTO pg_plans (code, name, tagline, description, plan_kind, "
                "price, billing_period, is_featured, cta_label, highlights, sort_order) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ('free', 'Free', 'Start exploring, no card needed',
                 'Everything a doctor needs to see how GooCampus works.',
                 'free', 0, 'lifetime', 0, 'Start free',
                 '["1 state of allotment data", "A few sample cut-off PDFs", '
                 '"Book a mentor session any time (pay per session)"]', 10))
            plan_id = conn.execute("SELECT id FROM pg_plans WHERE code = ?",
                                   ('free',)).fetchone()['id']
            # Sensible free-tier starting point — every value is editable in the admin.
            free_defaults = {
                'predictor_access': ('limited', None),
                'predictor_states': ('limited', 1),
                'predictor_searches': ('limited', 10),
                'pdf_library': ('limited', None),
                'pdf_documents': ('limited', 3),
                'pdf_downloads': ('limited', 3),
                'mentor_directory': ('limited', None),
                'mentor_sessions': ('limited', 0),
                'mentor_paid_booking': ('limited', None),   # ON: free users can still pay per session
                'counselling_call': ('limited', None),
            }
            for code, (vtype, limit) in free_defaults.items():
                conn.execute(
                    "INSERT INTO pg_plan_features (plan_id, feature_code, value_type, "
                    "limit_value) VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                    (plan_id, code, vtype, limit))
            logging.info("pg pricing: seeded starter Free plan")

        conn.commit()
        if added:
            logging.info(f"pg pricing: seeded {added} new feature(s)")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logging.error(f"seed_pg_pricing_defaults: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
