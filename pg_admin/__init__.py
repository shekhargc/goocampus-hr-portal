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
from pg_admin.data import college_master_tables as _college_master
from pg_admin.data import pgcp_tables as _pgcp_tables
from pg_admin.data import choice_tables as _choice_tables
from pg_admin.data import events_tables as _events_tables
from pg_admin.routes import (mentors_admin, api, predictor_admin,
                             plans_admin, users_admin, coupons_admin,
                             bookings_admin, college_master_admin, api_college,
                             pgcp_admin, api_pgcp, api_choice, choice_admin,
                             api_events, events_admin)


def register_pg_admin(app):
    # Make pg_admin/templates/ resolvable as 'pg_admin/<name>.html'
    tpl_dir = os.path.join(os.path.dirname(__file__), 'templates')
    app.jinja_loader = ChoiceLoader([app.jinja_loader, FileSystemLoader(tpl_dir)])

    # Tables self-create at boot (idempotent) — same pattern as college module.
    for fn in (_tables.ensure_pg_mentors_table, _tables.ensure_pg_auth_tables,
               _tables.ensure_pg_cutoffs_table,
               _tables.ensure_pg_colleges_table,
               _tables.ensure_pg_favorites_table,
               _tables.ensure_pg_bookings_table,
               _plans_tables.ensure_pg_plans_tables,
               _plans_tables.seed_pg_pricing_defaults,
               _plans_tables.seed_pgcp_counselling_packages,
               _plans_tables.consolidate_free_plan,
               _plans_tables.cleanup_legacy_features,
               _plans_tables.ensure_dashboard_gating_features,
               _plans_tables.set_pgcp_authority_notes,
               _college_master.ensure_college_master_tables,
               _pgcp_tables.ensure_pgcp_tables,
               _choice_tables.ensure_choice_tables,
               _events_tables.ensure_event_tables):
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

    # ── Mentor session requests (goocampus.in book form → portal) ──
    app.add_url_rule('/api/pg/bookings', 'api_pg_bookings',
                     api.api_pg_bookings, methods=['GET', 'POST'])
    # Admin: Session Requests management (true-admin gated inside)
    app.add_url_rule('/admin/pg/bookings', 'pg_bookings_admin',
                     bookings_admin.bookings_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/bookings/<int:booking_id>/update', 'pg_booking_update',
                     bookings_admin.booking_update, methods=['POST'])

    # ── College Master admin (unified Medical + DNB master; cut-off linker) ──
    app.add_url_rule('/admin/pg/college-master', 'pg_college_master_admin',
                     college_master_admin.college_master_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/college-master/upload-workbook', 'pg_college_master_upload_workbook',
                     college_master_admin.college_master_upload_workbook, methods=['POST'])
    app.add_url_rule('/admin/pg/college-master/upload-matching', 'pg_college_master_upload_matching',
                     college_master_admin.college_master_upload_matching, methods=['POST'])
    app.add_url_rule('/admin/pg/college-master/cutoff-audit', 'pg_college_master_cutoff_audit',
                     college_master_admin.college_master_cutoff_audit, methods=['GET'])
    app.add_url_rule('/admin/pg/college-master/purge-blank-cutoffs', 'pg_college_master_purge_blank',
                     college_master_admin.college_master_purge_blank, methods=['POST'])
    app.add_url_rule('/admin/pg/college-dupes', 'pg_college_dupes',
                     college_master_admin.college_dupes, methods=['GET'])
    app.add_url_rule('/admin/pg/college-dupes/merge', 'pg_college_dupes_merge',
                     college_master_admin.college_dupes_merge, methods=['POST'])
    app.add_url_rule('/admin/pg/college-database', 'pg_college_database_list',
                     college_master_admin.college_database_list, methods=['GET'])
    app.add_url_rule('/admin/pg/college-database/<int:master_id>', 'pg_college_profile',
                     college_master_admin.college_profile, methods=['GET'])
    app.add_url_rule('/admin/pg/college-database/<int:master_id>/edit', 'pg_college_edit',
                     college_master_admin.college_edit, methods=['GET'])
    app.add_url_rule('/admin/pg/college-database/<int:master_id>/save', 'pg_college_edit_save',
                     college_master_admin.college_edit_save, methods=['POST'])
    app.add_url_rule('/admin/pg/college-stipend', 'pg_college_stipend',
                     college_master_admin.college_stipend, methods=['GET'])
    app.add_url_rule('/admin/pg/college-stipend/<int:master_id>', 'pg_college_stipend_detail',
                     college_master_admin.college_stipend_detail, methods=['GET'])
    app.add_url_rule('/admin/pg/college-fees', 'pg_college_fees',
                     college_master_admin.college_fees, methods=['GET'])

    # ── Public API for goocampus.in: PG College Database + Stipend (X-PG-Key) ──
    app.add_url_rule('/api/pg/pg-colleges', 'api_pg_pg_colleges',
                     api_college.api_pg_pg_colleges, methods=['GET'])
    app.add_url_rule('/api/pg/pg-colleges/facets', 'api_pg_pg_colleges_facets',
                     api_college.api_pg_pg_colleges_facets, methods=['GET'])
    app.add_url_rule('/api/pg/pg-colleges/<int:college_id>', 'api_pg_pg_college_detail',
                     api_college.api_pg_pg_college_detail, methods=['GET'])
    app.add_url_rule('/api/pg/stipend', 'api_pg_stipend',
                     api_college.api_pg_stipend, methods=['GET'])
    app.add_url_rule('/api/pg/stipend/<int:college_id>', 'api_pg_stipend_detail',
                     api_college.api_pg_stipend_detail, methods=['GET'])
    # Fee explorer (course × college fees by quota/category)
    app.add_url_rule('/api/pg/fees', 'api_pg_fees',
                     api_college.api_pg_fees, methods=['GET'])
    app.add_url_rule('/api/pg/fees/facets', 'api_pg_fees_facets',
                     api_college.api_pg_fees_facets, methods=['GET'])
    app.add_url_rule('/api/pg/fees/<int:college_id>', 'api_pg_fees_college',
                     api_college.api_pg_fees_college, methods=['GET'])
    # Doctor's saved colleges (star), shared across College DB / Stipend / Predictor
    app.add_url_rule('/api/pg/college-favorites', 'api_pg_college_favorites',
                     api_college.api_pg_college_favorites, methods=['GET', 'POST'])
    app.add_url_rule('/api/pg/college-favorites/<int:master_id>', 'api_pg_college_favorite_delete',
                     api_college.api_pg_college_favorite_delete, methods=['DELETE'])

    # ── Indian PGCP onboarding — admin + doctor API ──
    app.add_url_rule('/admin/pg/pgcp', 'pg_pgcp_admin',
                     pgcp_admin.pgcp_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/pgcp/create', 'pg_pgcp_invite_create',
                     pgcp_admin.pgcp_invite_create, methods=['POST'])
    app.add_url_rule('/admin/pg/pgcp/client-search', 'pg_pgcp_client_search',
                     pgcp_admin.pgcp_client_search, methods=['GET'])
    app.add_url_rule('/admin/pg/pgcp/<int:invite_id>/send-email', 'pg_pgcp_send_email',
                     pgcp_admin.pgcp_send_email, methods=['POST'])
    app.add_url_rule('/admin/pg/pgcp/test-email', 'pg_pgcp_test_email',
                     pgcp_admin.pgcp_test_email, methods=['GET'])
    app.add_url_rule('/admin/pg/pgcp/<int:invite_id>', 'pg_pgcp_submission',
                     pgcp_admin.pgcp_submission, methods=['GET'])
    app.add_url_rule('/admin/pg/pgcp/<int:invite_id>/cancel', 'pg_pgcp_invite_cancel',
                     pgcp_admin.pgcp_invite_cancel, methods=['POST'])
    app.add_url_rule('/api/pg/pgcp/onboarding', 'api_pgcp_onboarding',
                     api_pgcp.api_pgcp_onboarding, methods=['GET', 'POST'])
    app.add_url_rule('/api/pg/pgcp/onboarding/submit', 'api_pgcp_submit',
                     api_pgcp.api_pgcp_submit, methods=['POST'])

    # ── Cutoff Explorer + Choice-List builder ──
    app.add_url_rule('/api/pg/cutoff-explorer', 'api_pg_cutoff_explorer',
                     api_choice.api_pg_cutoff_explorer, methods=['GET'])
    app.add_url_rule('/api/pg/cutoff-explorer/facets', 'api_pg_cutoff_facets',
                     api_choice.api_pg_cutoff_facets, methods=['GET'])
    app.add_url_rule('/api/pg/choice-entitlement', 'api_pg_choice_entitlement',
                     api_choice.api_pg_choice_entitlement, methods=['GET'])
    app.add_url_rule('/api/pg/my-states', 'api_pg_my_states',
                     api_choice.api_pg_my_states, methods=['GET', 'POST'])
    app.add_url_rule('/api/pg/choice-sets', 'api_pg_choice_sets',
                     api_choice.api_pg_choice_sets, methods=['GET', 'POST'])
    app.add_url_rule('/api/pg/choice-sets/<int:set_id>', 'api_pg_choice_set',
                     api_choice.api_pg_choice_set, methods=['GET', 'DELETE'])
    app.add_url_rule('/api/pg/choice-sets/<int:set_id>/items', 'api_pg_choice_items',
                     api_choice.api_pg_choice_items, methods=['POST'])
    app.add_url_rule('/api/pg/choice-sets/<int:set_id>/reorder', 'api_pg_choice_reorder',
                     api_choice.api_pg_choice_reorder, methods=['POST'])
    app.add_url_rule('/api/pg/choice-items/<int:item_id>', 'api_pg_choice_item_delete',
                     api_choice.api_pg_choice_item_delete, methods=['DELETE'])
    # Team-side choice-sheet editing (goocampus.org admin, on the client's behalf)
    app.add_url_rule('/admin/pg/choice-sets/<int:set_id>/cutoff-search', 'pg_choice_cutoff_search',
                     choice_admin.choice_cutoff_search, methods=['GET'])
    app.add_url_rule('/admin/pg/choice-sets/<int:set_id>/add', 'pg_choice_add',
                     choice_admin.choice_add, methods=['POST'])
    app.add_url_rule('/admin/pg/choice-sets/<int:set_id>/reorder', 'pg_choice_reorder',
                     choice_admin.choice_reorder, methods=['POST'])
    app.add_url_rule('/admin/pg/choice-items/<int:item_id>/move', 'pg_choice_move',
                     choice_admin.choice_move, methods=['POST'])
    app.add_url_rule('/admin/pg/choice-items/<int:item_id>/delete', 'pg_choice_delete',
                     choice_admin.choice_delete, methods=['POST'])
    # ── Events: public API (goocampus.in) + admin ──
    app.add_url_rule('/api/pg/events', 'api_pg_events', api_events.api_pg_events, methods=['GET'])
    app.add_url_rule('/api/pg/events/ticket/<ticket_code>', 'api_pg_event_ticket',
                     api_events.api_pg_event_ticket, methods=['GET'])
    app.add_url_rule('/api/pg/events/<slug>/register', 'api_pg_event_register',
                     api_events.api_pg_event_register, methods=['POST'])
    app.add_url_rule('/api/pg/events/<slug>', 'api_pg_event', api_events.api_pg_event, methods=['GET'])
    app.add_url_rule('/admin/pg/events', 'pg_events_admin', events_admin.events_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/events/create', 'pg_event_create', events_admin.event_create, methods=['POST'])
    app.add_url_rule('/admin/pg/events/<int:event_id>/toggle', 'pg_event_toggle',
                     events_admin.event_toggle, methods=['POST'])
    app.add_url_rule('/admin/pg/events/<int:event_id>/export', 'pg_event_export',
                     events_admin.event_export, methods=['GET'])

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
    app.add_url_rule('/admin/pg/plan-features', 'pg_plan_features',
                     plans_admin.plan_features_grid, methods=['GET'])
    app.add_url_rule('/admin/pg/plan-features/save', 'pg_plan_features_save',
                     plans_admin.plan_features_save, methods=['POST'])
    app.add_url_rule('/admin/pg/plans/compare.json', 'pg_plan_compare',
                     plans_admin.plan_compare, methods=['GET'])

    # ── Registered Doctors admin ───────────────────────────────────────────
    app.add_url_rule('/admin/pg/users', 'pg_users_admin',
                     users_admin.users_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/users/<int:user_id>', 'pg_user_detail',
                     users_admin.user_detail, methods=['GET'])
    app.add_url_rule('/admin/pg/diag/plan', 'pg_plan_diag',
                     users_admin.plan_diag, methods=['GET'])
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
    app.add_url_rule('/admin/pg/pay-test', 'pg_pay_test', api.admin_pg_pay_test, methods=['GET'])
    app.add_url_rule('/admin/pg/pay-test/verify', 'pg_pay_test_verify',
                     api.admin_pg_pay_test_verify, methods=['POST'])
    app.add_url_rule('/api/pg/checkout/verify', 'api_pg_checkout_verify',
                     api.api_pg_checkout_verify, methods=['POST'])
