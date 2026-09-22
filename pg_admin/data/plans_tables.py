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


# ── PGCP counselling packages (from the 2026 brochure, founder 2026-09-17) ──
# Free / Starter / Standard / Premium, shown on the same pricing page. Run-once
# (guarded by a hidden marker feature) + additive — never resurrects a package
# the founder later edits or deletes. Everything is editable in /admin/pg/plans.
_PGCP_FEATURES = [
    # code, name, description, unit, sort_order
    ('pgcp_authority',            'Counselling Authority Support', '', 'text', 200),
    ('pgcp_pre_counselling',      'Pre-counselling information', 'Rank predictor, cutoff analysis, updated fee structures', 'boolean', 201),
    ('pgcp_notifications',        'Notification & deadline reminders', 'Real-time WhatsApp updates, deadline alerts', 'boolean', 202),
    ('pgcp_admission_counselling','Admission counselling', '1-to-1 personalised counselling, process walkthroughs', 'boolean', 203),
    ('pgcp_process_eligibility',  'Process & Eligibility clauses', 'State-wise process, eligibility clauses, top colleges', 'boolean', 204),
    ('pgcp_registration',         'Registration support', 'AIQ / MCC + State Authority application', 'boolean', 205),
    ('pgcp_college_selector',     'College selector', 'Infrastructure, OPD load, stipend & department reports', 'boolean', 206),
    ('pgcp_documentation',        'Documentation support', 'Mandatory document list, templates & proof-reading', 'boolean', 207),
    ('pgcp_option_entry',         'Expert option entry support', 'Round 1, 2, mop-up strategy & priority option list', 'boolean', 208),
    ('pgcp_specialty_pref',       'Specialty preference ordering', 'Guided ordering of your specialty preferences', 'boolean', 209),
    ('pgcp_specialty_mentorship', 'Specialty-specific mentorship', 'Specialty insights, work-life advice, doctor connects', 'boolean', 210),
    ('pgcp_nri_quota',            'NRI / NRI-sponsored quota guidance', 'NRI-quota documentation, templates & expert review', 'boolean', 211),
    ('pgcp_stray_vacancy',        'Stray vacancy guidance', 'Real-time seat matrix, last-minute vacancy alerts', 'boolean', 212),
    ('pgcp_post_allotment',       'Post seat allotment guidance', 'Security deposit tracking, post-admission formalities', 'boolean', 213),
    ('pgcp_neet_specialist',      'NEET specialist until allotment', 'Dedicated NEET counsellor with unlimited sessions', 'boolean', 214),
]
_PGCP_PLANS = [
    # code, name, price, tax_note(tagline), badge, is_featured, sort_order, authority_note, included_feature_codes
    ('pgcp_free', 'Free', 0, 'No card needed', '', 0, 20, '',
        ['pgcp_pre_counselling']),
    ('pgcp_starter', 'Starter', 30000, 'incl. all taxes', '', 0, 21, 'All India / MCC + Home State only',
        ['pgcp_pre_counselling', 'pgcp_notifications', 'pgcp_process_eligibility', 'pgcp_college_selector', 'pgcp_option_entry', 'pgcp_specialty_pref']),
    ('pgcp_standard', 'Standard', 100000, '+ GST', 'Most Chosen', 1, 22, 'All India / MCC + Home State',
        ['pgcp_pre_counselling', 'pgcp_notifications', 'pgcp_admission_counselling', 'pgcp_process_eligibility', 'pgcp_registration', 'pgcp_college_selector', 'pgcp_documentation', 'pgcp_option_entry', 'pgcp_specialty_pref', 'pgcp_post_allotment']),
    ('pgcp_premium', 'Premium', 200000, '+ GST', '', 0, 23, 'All India / MCC + Home State + All Open States',
        ['pgcp_pre_counselling', 'pgcp_notifications', 'pgcp_admission_counselling', 'pgcp_process_eligibility', 'pgcp_registration', 'pgcp_college_selector', 'pgcp_documentation', 'pgcp_option_entry', 'pgcp_specialty_pref', 'pgcp_specialty_mentorship', 'pgcp_nri_quota', 'pgcp_stray_vacancy', 'pgcp_post_allotment', 'pgcp_neet_specialist']),
]


def seed_pgcp_counselling_packages():
    """Seed the 4 brochure counselling packages once (Free/Starter/Standard/Premium).
    Guarded by a hidden marker so it runs exactly once and never resurrects edits."""
    conn = get_db()
    try:
        if conn.execute("SELECT 1 FROM pg_features WHERE code = '_pgcp_seed_v2'").fetchone():
            return
        existing = {r['code'] for r in conn.execute("SELECT code FROM pg_features").fetchall()}
        for code, name, desc, unit, sort in _PGCP_FEATURES:
            if code in existing:
                continue
            conn.execute("INSERT INTO pg_features (code, name, description, unit, resource_kind, sort_order) "
                         "VALUES (?,?,?,?,?,?)", (code, name, desc, unit, 'counselling', sort))
        pcodes = {r['code'] for r in conn.execute("SELECT code FROM pg_plans").fetchall()}
        for code, name, price, tax_note, badge, featured, sort, authnote, incl in _PGCP_PLANS:
            if code in pcodes:
                continue
            conn.execute("INSERT INTO pg_plans (code, name, tagline, plan_kind, price, currency, "
                         "billing_period, is_featured, badge_text, cta_label, sort_order, is_active, is_public) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,1,1)",
                         (code, name, tax_note, 'counselling', price, 'INR', 'one_time',
                          featured, badge, 'Talk to a Counsellor', sort))
            pid = conn.execute("SELECT id FROM pg_plans WHERE code = ?", (code,)).fetchone()['id']
            if authnote:
                conn.execute("INSERT INTO pg_plan_features (plan_id, feature_code, value_type, note) "
                             "VALUES (?,?,'unlimited',?) ON CONFLICT DO NOTHING", (pid, 'pgcp_authority', authnote))
            for fc in incl:
                conn.execute("INSERT INTO pg_plan_features (plan_id, feature_code, value_type) "
                             "VALUES (?,?,'unlimited') ON CONFLICT DO NOTHING", (pid, fc))
        # Hide the original default 'free' plan (kept, NOT deleted — it powers free-tier
        # entitlements for logged-in doctors) so only the 4 counselling packages show.
        conn.execute("UPDATE pg_plans SET is_public = 0 WHERE code = 'free'")
        # Most-popular badge on Standard (₹1L), not Premium.
        conn.execute("UPDATE pg_plans SET is_featured = 1, badge_text = 'Most Chosen' WHERE code = 'pgcp_standard'")
        conn.execute("UPDATE pg_plans SET is_featured = 0, badge_text = '' WHERE code = 'pgcp_premium'")
        conn.execute("INSERT INTO pg_features (code, name, unit, resource_kind, is_active, sort_order) "
                     "VALUES ('_pgcp_seed_v2','(pgcp seed marker)','boolean','_meta',0,9999) ON CONFLICT DO NOTHING")
        conn.commit()
        logging.info("pg pricing: seeded PGCP counselling packages (Free/Starter/Standard/Premium)")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"seed_pgcp_counselling_packages: {e}")
    finally:
        try: conn.close()
        except Exception: pass


# Dashboard sections + gated features — every section the app has, shown on the
# Plan Features page. Names here are DEFAULTS only; the founder can rename any of
# them on that page. ALL boolean (included / not).
# sort_order 100-107 keeps these ABOVE the counselling services (200+).
_DASH_FEATURES = [
    ('dash_predictor',       'College Predictor (by rank)', 'Rank-based college prediction', 'boolean', 100),
    ('dash_cutoff_explorer', 'Cutoff Explorer (filter cut-offs)', 'Browse cut-offs by college/quota/category', 'boolean', 101),
    ('dash_college_db',      'College Database', 'Browse colleges + full profiles', 'boolean', 102),
    ('dash_stipend',         'Stipend · Bond · Penalty', 'Stipend/bond/penalty by college & speciality', 'boolean', 103),
    ('dash_favourites',      'Favourite colleges (star)', 'Save colleges across the dashboard', 'boolean', 104),
    ('dash_mentors',         'Mentors — browse & request session', 'Browse mentors, request a paid session', 'boolean', 105),
    ('dash_choice_list',     'Choice-List builder (Round 1/2/3)', 'Auto-build round-wise choice sheets, edit & export', 'boolean', 106),
    ('dash_all_states',      'Choice list — all states', 'Choice sets for any state (else home state only)', 'boolean', 107),
]
_FREE_SECTIONS = ['dash_predictor', 'dash_cutoff_explorer', 'dash_college_db',
                  'dash_stipend', 'dash_favourites', 'dash_mentors']
_ALL_PLANS = ['pgcp_free', 'pgcp_starter', 'pgcp_standard', 'pgcp_premium']
# feature_code -> plan codes included by default
_DASH_DEFAULTS = {c: list(_ALL_PLANS) for c in _FREE_SECTIONS}
_DASH_DEFAULTS['dash_choice_list'] = ['pgcp_starter', 'pgcp_standard', 'pgcp_premium']
_DASH_DEFAULTS['dash_all_states'] = ['pgcp_premium']


def ensure_dashboard_gating_features():
    """Keep the dashboard features present + their default plan mapping. Runs every
    boot but is purely additive (ON CONFLICT DO NOTHING) — it fills gaps for any new
    feature and NEVER overwrites the founder's edits on the Plan Features page."""
    conn = get_db()
    try:
        for code, name, desc, unit, sort in _DASH_FEATURES:
            conn.execute("INSERT INTO pg_features (code, name, description, unit, resource_kind, sort_order) "
                         "VALUES (?,?,?,?, 'dashboard', ?) ON CONFLICT (code) DO NOTHING",
                         (code, name, desc, unit, sort))
            # keep grouping + order current for pre-existing rows (never touch name → founder can rename)
            conn.execute("UPDATE pg_features SET resource_kind='dashboard', sort_order=? WHERE code=?",
                         (sort, code))
        for fc, plan_codes in _DASH_DEFAULTS.items():
            for pc in plan_codes:
                row = conn.execute("SELECT id FROM pg_plans WHERE code = ?", (pc,)).fetchone()
                if row:
                    conn.execute("INSERT INTO pg_plan_features (plan_id, feature_code, value_type) "
                                 "VALUES (?,?, 'unlimited') ON CONFLICT DO NOTHING", (row['id'], fc))
        conn.commit()
        logging.info("pg pricing: ensured dashboard features")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"ensure_dashboard_gating_features: {e}")
    finally:
        try: conn.close()
        except Exception: pass


def consolidate_free_plan():
    """One Free plan, not two. Promote the real Free package (pgcp_free) to be the
    free-tier ANCHOR (plan_kind='free') and retire the old standalone 'free' plan
    (kept in the DB, just inactive + hidden + no longer the anchor). Idempotent."""
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM pg_plans WHERE code = 'pgcp_free'").fetchone():
            return
        conn.execute("UPDATE pg_plans SET plan_kind = 'free' WHERE code = 'pgcp_free'")
        conn.execute("UPDATE pg_plans SET plan_kind = 'retired', is_active = 0, is_public = 0 "
                     "WHERE code = 'free'")
        conn.commit()
        logging.info("pg pricing: consolidated to a single free plan (pgcp_free)")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"consolidate_free_plan: {e}")
    finally:
        try: conn.close()
        except Exception: pass


# Pre-PGCP generic features, superseded by the dashboard features + counselling
# services. Retired so the plan cards show one clean list. (founder 2026-09-22)
_LEGACY_FEATURE_CODES = [
    'predictor_access', 'predictor_states', 'predictor_searches',
    'pdf_library', 'pdf_documents', 'pdf_downloads',
    'mentor_directory', 'mentor_sessions', 'mentor_paid_booking',
    'college_shortlist', 'counselling_call', 'priority_support',
]


def cleanup_legacy_features():
    """Deactivate the old generic feature catalogue (kept in DB, just hidden) so the
    plan matrix shows only the built dashboard features + counselling services. Idempotent."""
    conn = get_db()
    try:
        ph = ','.join(['?'] * len(_LEGACY_FEATURE_CODES))
        conn.execute(f"UPDATE pg_features SET is_active = 0 WHERE code IN ({ph})",
                     _LEGACY_FEATURE_CODES)
        conn.commit()
        logging.info("pg pricing: retired legacy generic features")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error(f"cleanup_legacy_features: {e}")
    finally:
        try: conn.close()
        except Exception: pass
