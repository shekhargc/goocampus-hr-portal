"""goocampus.in Admin module — internal screens (in goocampus.org) that manage
the goocampus.in dataset, plus the `/api/pg/*` API the Next.js user panel calls.

Self-contained, mirrors the `college/` layout: routes/, data/, templates/pg_admin/.
Wire in with:  from pg_admin import register_pg_admin; register_pg_admin(app)

Build order (see goocampus-pg/DATA_MODEL_PG.md):
  1. Mentors — pg_mentors + GET /api/pg/mentors[/:id] + admin Mentor Management  ← THIS
  2. Auth    — pg_users + OTP endpoints
  3. Bookings— pg_bookings + booking endpoints + admin Booking Management
"""
import os
import logging
from jinja2 import ChoiceLoader, FileSystemLoader
from pg_admin.data import tables as _tables
from pg_admin.data import plans_tables as _plans_tables
from pg_admin.routes import (mentors_admin, api, predictor_admin,
                             plans_admin, users_admin, coupons_admin)


def register_pg_admin(app):
    # Make pg_admin/templates/ resolvable as 'pg_admin/<name>.html'
    tpl_dir = os.path.join(os.path.dirname(__file__), 'templates')
    app.jinja_loader = ChoiceLoader([app.jinja_loader, FileSystemLoader(tpl_dir)])

    # Tables self-create at boot (idempotent) — same pattern as college module.
    for fn in (_tables.ensure_pg_mentors_table, _tables.ensure_pg_auth_tables,
               _tables.ensure_pg_cutoffs_table,
               _tables.ensure_pg_colleges_table,
               _tables.ensure_pg_favorites_table,
               _plans_tables.ensure_pg_plans_tables,
               _plans_tables.seed_pg_pricing_defaults):
        try:
            fn()
        except Exception as e:
            logging.error(f"pg_admin boot {fn.__name__}: {e}")

    # ── Admin screens (goocampus.org staff; true-admin gated inside) ──
    app.add_url_rule('/admin/pg/mentors', 'pg_mentors_admin',
                     mentors_admin.mentors_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/mentors/save', 'pg_mentor_save',
                     mentors_admin.mentor_save, methods=['POST'])
    app.add_url_rule('/admin/pg/mentors/import', 'pg_mentors_import',
                     mentors_admin.mentors_import, methods=['POST'])
    app.add_url_rule('/admin/pg/mentors/import-xlsx', 'pg_mentors_import_xlsx',
                     mentors_admin.mentors_import_xlsx, methods=['POST'])
    app.add_url_rule('/admin/pg/mentors/migrate-photos', 'pg_mentors_migrate_photos',
                     mentors_admin.mentors_migrate_photos, methods=['POST'])
    app.add_url_rule('/admin/pg/mentors/<int:mentor_id>', 'pg_mentor_detail',
                     mentors_admin.mentor_detail, methods=['GET'])
    app.add_url_rule('/admin/pg/mentors/<int:mentor_id>/toggle', 'pg_mentor_toggle',
                     mentors_admin.mentor_toggle, methods=['POST'])
    app.add_url_rule('/admin/pg/mentors/<int:mentor_id>/delete', 'pg_mentor_delete',
                     mentors_admin.mentor_delete, methods=['POST'])
    app.add_url_rule('/admin/pg/mentors/<int:mentor_id>/photo', 'pg_mentor_photo_admin',
                     mentors_admin.mentor_photo_admin, methods=['GET'])

    # ── Public API for the goocampus.in user panel (X-PG-Key guarded) ──
    app.add_url_rule('/api/pg/mentors', 'api_pg_mentors',
                     api.api_pg_mentors, methods=['GET'])
    app.add_url_rule('/api/pg/mentors/<int:mentor_id>', 'api_pg_mentor_detail',
                     api.api_pg_mentor_detail, methods=['GET'])
    # Public photo redirect (no key: it's public content; only published+active served)
    app.add_url_rule('/api/pg/mentors/<int:mentor_id>/photo', 'api_pg_mentor_photo',
                     api.api_pg_mentor_photo, methods=['GET'])

    # ── Predictor Data admin (cut-off dataset behind the goocampus.in predictor) ──
    app.add_url_rule('/admin/pg/predictor', 'pg_predictor_admin',
                     predictor_admin.predictor_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/predictor/upload', 'pg_predictor_upload',
                     predictor_admin.predictor_upload, methods=['POST'])

    # ── Predictor API for the goocampus.in site (X-PG-Key guarded) ──
    app.add_url_rule('/api/pg/predictor', 'api_pg_predictor',
                     api.api_pg_predictor, methods=['GET'])
    app.add_url_rule('/api/pg/predictor/filters', 'api_pg_predictor_filters',
                     api.api_pg_predictor_filters, methods=['GET'])
    app.add_url_rule('/api/pg/predictor/courses', 'api_pg_predictor_courses',
                     api.api_pg_predictor_courses, methods=['GET'])

    # ── College database + Favourites (X-PG-Key; favourites also need Bearer) ──
    app.add_url_rule('/api/pg/colleges', 'api_pg_colleges',
                     api.api_pg_colleges, methods=['GET'])
    app.add_url_rule('/api/pg/colleges/facets', 'api_pg_colleges_facets',
                     api.api_pg_colleges_facets, methods=['GET'])
    app.add_url_rule('/api/pg/favorites', 'api_pg_favorites',
                     api.api_pg_favorites, methods=['GET', 'POST', 'PUT'])
    app.add_url_rule('/api/pg/favorites/<int:college_id>', 'api_pg_favorite_delete',
                     api.api_pg_favorite_delete, methods=['DELETE'])

    # ── NEET-PG PDF library for the goocampus.in dashboard (same library as .org) ──
    app.add_url_rule('/api/pg/neetpg-pdfs', 'api_pg_neetpg_pdfs',
                     api.api_pg_neetpg_pdfs, methods=['GET'])
    app.add_url_rule('/api/pg/neetpg-pdfs/<int:pdf_id>/file', 'api_pg_neetpg_pdf_file',
                     api.api_pg_neetpg_pdf_file, methods=['GET'])

    # ── Doctor login for goocampus.in — WhatsApp OTP (X-PG-Key guarded) ──
    app.add_url_rule('/api/pg/otp/send', 'api_pg_otp_send',
                     api.api_pg_otp_send, methods=['POST'])
    app.add_url_rule('/api/pg/otp/verify', 'api_pg_otp_verify',
                     api.api_pg_otp_verify, methods=['POST'])
    # Doctor loads (GET) + saves (POST) their profile on goocampus.in -> the SAME
    # pg_users record the admin screen shows. Blueprint-driven so fields stay in sync.
    app.add_url_rule('/api/pg/profile', 'api_pg_profile',
                     api.api_pg_profile, methods=['GET', 'POST'])

    # ── Pricing & Plans admin ──────────────────────────────────────────────
    app.add_url_rule('/admin/pg/plans', 'pg_plans_admin',
                     plans_admin.plans_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/plans/save', 'pg_plan_save',
                     plans_admin.plan_save, methods=['POST'])
    app.add_url_rule('/admin/pg/plans/<int:plan_id>/toggle', 'pg_plan_toggle',
                     plans_admin.plan_toggle, methods=['POST'])
    app.add_url_rule('/admin/pg/plans/<int:plan_id>/delete', 'pg_plan_delete',
                     plans_admin.plan_delete, methods=['POST'])
    app.add_url_rule('/admin/pg/plans/<int:plan_id>/duplicate', 'pg_plan_duplicate',
                     plans_admin.plan_duplicate, methods=['POST'])
    app.add_url_rule('/admin/pg/plans/feature/save', 'pg_feature_save',
                     plans_admin.feature_save, methods=['POST'])
    app.add_url_rule('/admin/pg/plans/compare.json', 'pg_plan_compare',
                     plans_admin.plan_compare, methods=['GET'])

    # ── Registered Doctors admin ───────────────────────────────────────────
    app.add_url_rule('/admin/pg/users', 'pg_users_admin',
                     users_admin.users_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/users/<int:user_id>', 'pg_user_detail',
                     users_admin.user_detail, methods=['GET'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/save', 'pg_user_save',
                     users_admin.user_save, methods=['POST'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/block', 'pg_user_block',
                     users_admin.user_block, methods=['POST'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/grant-plan', 'pg_user_grant_plan',
                     users_admin.user_grant_plan, methods=['POST'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/reset-usage', 'pg_user_reset_usage',
                     users_admin.user_reset_usage, methods=['POST'])
    app.add_url_rule('/admin/pg/subscriptions/<int:sub_id>/cancel',
                     'pg_subscription_cancel', users_admin.subscription_cancel,
                     methods=['POST'])

    # ── Coupons admin ──────────────────────────────────────────────────────
    app.add_url_rule('/admin/pg/coupons', 'pg_coupons_admin',
                     coupons_admin.coupons_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/coupons/save', 'pg_coupon_save',
                     coupons_admin.coupon_save, methods=['POST'])
    app.add_url_rule('/admin/pg/coupons/<int:coupon_id>/toggle', 'pg_coupon_toggle',
                     coupons_admin.coupon_toggle, methods=['POST'])
    app.add_url_rule('/admin/pg/coupons/<int:coupon_id>/delete', 'pg_coupon_delete',
                     coupons_admin.coupon_delete, methods=['POST'])
    app.add_url_rule('/admin/pg/coupons/<int:coupon_id>/redemptions',
                     'pg_coupon_redemptions', coupons_admin.coupon_redemptions,
                     methods=['GET'])
    app.add_url_rule('/admin/pg/coupons/preview.json', 'pg_coupon_preview',
                     coupons_admin.coupon_preview, methods=['GET'])

    # ── Public pricing + entitlement + coupon API for goocampus.in ─────────
    app.add_url_rule('/api/pg/plans', 'api_pg_plans',
                     api.api_pg_plans, methods=['GET'])
    app.add_url_rule('/api/pg/entitlements', 'api_pg_entitlements',
                     api.api_pg_entitlements, methods=['GET'])
    app.add_url_rule('/api/pg/entitlements/consume', 'api_pg_entitlement_consume',
                     api.api_pg_entitlement_consume, methods=['POST'])
    app.add_url_rule('/api/pg/coupons/validate', 'api_pg_coupon_validate',
                     api.api_pg_coupon_validate, methods=['POST'])
    # Razorpay checkout: server makes the order (secret stays here) + verifies the
    # payment, starts the subscription and burns the coupon.
    app.add_url_rule('/api/pg/checkout/create-order', 'api_pg_checkout_create_order',
                     api.api_pg_checkout_create_order, methods=['POST'])
    app.add_url_rule('/api/pg/checkout/verify', 'api_pg_checkout_verify',
                     api.api_pg_checkout_verify, methods=['POST'])
