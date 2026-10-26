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
from pg_admin.data import choice_log as _choice_log
from pg_admin.data import events_tables as _events_tables
from pg_admin.data import analytics_tables as _analytics_tables
from pg_admin.data import seat_matrix_tables as _seat_matrix
from pg_admin.data import news_tables as _news_tables
from pg_admin.data import authority_docs_tables as _authority_docs
from pg_admin.data import specialty_groups as _specialty_groups
from pg_admin.data import results_tables as _results_tables
from pg_admin.routes import (mentors_admin, api, predictor_admin,
                             plans_admin, users_admin, coupons_admin,
                             bookings_admin, college_master_admin, api_college,
                             pgcp_admin, api_pgcp, api_choice, choice_admin,
                             api_events, events_admin, api_track, analytics_admin,
                             diag_home_state, diag_states, seat_matrix_admin, api_seat_matrix,
                             news_admin, api_news, authority_admin, api_authorities,
                             specialty_admin, news_inbox_admin, api_news_ingest,
                             calendar_admin, desk_api, seat_matrix_ingest, recommended, rankings, team_college_lists, my_payments,
                             mgmt_inquiries, archive_admin, results_api)
from pg_admin import news_scraper as _news_scraper


def register_pg_admin(app):
    from pg_admin import perf as _perf
    _perf.register(app)          # gzip + Cache-Control on public /api/pg/* GETs (2026-10-09)
    from pg_admin import site_refresh as _site_refresh
    _site_refresh.register(app)  # tell goocampus.in to rebuild pages after data changes (2026-10-21)
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
               _choice_log.ensure_choice_log_boot,
               _events_tables.ensure_event_tables,
               _analytics_tables.ensure_analytics_tables,
               _seat_matrix.ensure_pg_seat_matrix,
               _news_tables.ensure_pg_news,
               _authority_docs.ensure_pg_authority_docs,
               _specialty_groups.ensure_course_branch_table,
               _news_scraper.ensure_news_inbox_tables,
               _results_tables.ensure_results_tables):
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
    app.add_url_rule('/admin/pg/mentors/country-visibility', 'pg_mentors_country_visibility',
                     mentors_admin.mentors_country_visibility, methods=['POST'])
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

    # ── Seat Matrix admin (raw announced authority matrix; not matched to master) ──
    app.add_url_rule('/api/pg/seat-matrix/ingest', 'api_seat_matrix_ingest',
                     seat_matrix_ingest.api_seat_matrix_ingest, methods=['POST'])
    app.add_url_rule('/api/pg/seat-matrix/source', 'api_seat_matrix_source_update',
                     seat_matrix_ingest.api_seat_matrix_source_update, methods=['POST'])
    app.add_url_rule('/api/pg/seat-matrix/file-to-authority', 'api_seat_matrix_file_to_authority',
                     seat_matrix_ingest.api_seat_matrix_file_to_authority, methods=['POST'])
    # ── 2026 counselling results + name memory (founder 2026-10-24) ──
    app.add_url_rule('/api/pg/results/ingest', 'api_results_ingest', results_api.api_results_ingest, methods=['POST'])
    app.add_url_rule('/api/pg/name-memory/seed', 'api_name_memory_seed', results_api.api_name_memory_seed,
                     methods=['POST'])
    app.add_url_rule('/api/pg/results/rounds', 'api_results_rounds', results_api.api_results_rounds, methods=['GET'])
    app.add_url_rule('/api/pg/results', 'api_results', results_api.api_results, methods=['GET'])
    app.add_url_rule('/api/pg/results/facets', 'api_results_facets', results_api.api_results_facets, methods=['GET'])
    app.add_url_rule('/api/pg/results/colleges', 'api_results_colleges', results_api.api_results_colleges,
                     methods=['GET'])
    from pg_admin.routes import allotments_api as _alapi
    app.add_url_rule('/api/pg/my/allotments', 'api_pg_my_allotments', _alapi.my_allotments, methods=['GET'])
    app.add_url_rule('/api/pg/my/rank-confirm', 'api_pg_my_rank_confirm', _alapi.my_rank_confirm, methods=['POST'])
    app.add_url_rule('/api/pg/my/allotment-not-me', 'api_pg_my_allotment_not_me', _alapi.my_allotment_not_me,
                     methods=['POST'])
    app.add_url_rule('/api/pg/desk/doctors/<int:doctor_id>/allotments', 'api_pg_desk_allotments',
                     _alapi.desk_allotments, methods=['GET'])
    app.add_url_rule('/api/pg/desk/doctors/<int:doctor_id>/allotment-mark', 'api_pg_desk_allotment_mark',
                     _alapi.desk_allotment_mark, methods=['POST'])
    app.add_url_rule('/api/pg/results/rank', 'api_results_rank', results_api.api_results_rank, methods=['GET'])
    app.add_url_rule('/api/pg/results/cutoffs', 'api_results_cutoffs', results_api.api_results_cutoffs, methods=['GET'])
    app.add_url_rule('/api/pg/results/trends', 'api_results_trends', results_api.api_results_trends, methods=['GET'])
    app.add_url_rule('/api/pg/announce', 'api_announce', results_api.api_announce, methods=['POST'])
    app.add_url_rule('/api/pg/results/pdf', 'api_results_pdf', results_api.api_results_pdf, methods=['GET'])
    app.add_url_rule('/api/pg/results/leftover', 'api_results_leftover', results_api.api_results_leftover,
                     methods=['GET'])
    app.add_url_rule('/admin/pg/name-memory', 'pg_name_memory', results_api.name_memory_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/name-memory/confirm', 'pg_name_memory_confirm', results_api.name_memory_confirm,
                     methods=['POST'])
    app.add_url_rule('/admin/pg/seat-matrix', 'pg_seat_matrix_admin',
                     seat_matrix_admin.seat_matrix_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/seat-matrix/upload', 'pg_seat_matrix_upload',
                     seat_matrix_admin.seat_matrix_upload, methods=['POST'])
    app.add_url_rule('/admin/pg/seat-matrix/delete', 'pg_seat_matrix_delete',
                     seat_matrix_admin.seat_matrix_delete, methods=['POST'])
    app.add_url_rule('/admin/pg/seat-matrix/pdf', 'pg_seat_matrix_pdf_admin',
                     seat_matrix_admin.seat_matrix_pdf_admin, methods=['GET'])

    # ── Public API for goocampus.in: Seat Matrix (X-PG-Key; PDF is public) ──
    app.add_url_rule('/api/pg/seat-matrix', 'api_pg_seat_matrix',
                     api_seat_matrix.api_pg_seat_matrix, methods=['GET'])
    app.add_url_rule('/api/pg/seat-matrix/facets', 'api_pg_seat_matrix_facets',
                     api_seat_matrix.api_pg_seat_matrix_facets, methods=['GET'])
    app.add_url_rule('/api/pg/seat-matrix/pdf', 'api_pg_seat_matrix_pdf',
                     api_seat_matrix.api_pg_seat_matrix_pdf, methods=['GET'])

    # ── News & Updates admin (counselling news; admin-only) ──
    app.add_url_rule('/admin/pg/news', 'pg_news_admin',
                     news_admin.news_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/news/save', 'pg_news_save',
                     news_admin.news_save, methods=['POST'])
    app.add_url_rule('/admin/pg/news/test-email', 'pg_news_test_email',
                     news_admin.news_test_email, methods=['POST'])
    app.add_url_rule('/admin/pg/news/send-alert', 'pg_news_send_alert',
                     news_admin.news_send_alert, methods=['POST'])
    app.add_url_rule('/admin/pg/news/recipients', 'pg_news_recipients_diag',
                     news_admin.news_recipients_diag, methods=['GET'])
    app.add_url_rule('/admin/pg/news/toggle', 'pg_news_toggle',
                     news_admin.news_toggle, methods=['POST'])
    app.add_url_rule('/admin/pg/news/delete', 'pg_news_delete',
                     news_admin.news_delete, methods=['POST'])
    app.add_url_rule('/admin/pg/news/restore', 'pg_news_restore',
                     news_admin.news_restore, methods=['POST'])
    app.add_url_rule('/admin/pg/news/purge', 'pg_news_purge',
                     news_admin.news_purge, methods=['POST'])
    app.add_url_rule('/admin/pg/news/pdf', 'pg_news_pdf_admin',
                     news_admin.news_pdf_admin, methods=['GET'])
    # News Inbox — notices the scraper finds on authority sites, for review (2026-10-08)
    app.add_url_rule('/admin/pg/news-inbox', 'pg_news_inbox',
                     news_inbox_admin.news_inbox, methods=['GET'])
    app.add_url_rule('/admin/pg/news-coverage', 'pg_news_coverage',
                     news_inbox_admin.news_coverage, methods=['GET'])
    app.add_url_rule('/admin/pg/news-inbox/check', 'pg_news_inbox_check',
                     news_inbox_admin.news_inbox_check, methods=['POST'])
    app.add_url_rule('/admin/pg/news-inbox/redraft', 'pg_news_inbox_redraft',
                     news_inbox_admin.news_inbox_redraft, methods=['POST'])
    app.add_url_rule('/admin/pg/news-inbox/status', 'pg_news_inbox_status',
                     news_inbox_admin.news_inbox_status, methods=['POST'])
    # The founder's Mac pushes notices + AI drafts here (X-News-Key = env NEWS_INGEST_KEY).
    app.add_url_rule('/api/pg/news-inbox/known', 'api_news_inbox_known',
                     api_news_ingest.api_news_inbox_known, methods=['GET'])
    app.add_url_rule('/api/pg/news-inbox/ingest', 'api_news_inbox_ingest',
                     api_news_ingest.api_news_inbox_ingest, methods=['POST'])
    app.add_url_rule('/api/pg/news-inbox/status', 'api_news_inbox_status',
                     api_news_ingest.api_news_inbox_status, methods=['GET'])
    app.add_url_rule('/api/pg/news-inbox/heartbeat', 'api_news_inbox_heartbeat',
                     api_news_ingest.api_news_inbox_heartbeat, methods=['POST'])
    app.add_url_rule('/api/pg/maint/course-rename', 'api_maint_course_rename',
                     api_news_ingest.api_maint_course_rename, methods=['POST'])
    app.add_url_rule('/api/pg/news-inbox/review', 'api_news_inbox_review',
                     api_news_ingest.api_news_inbox_review, methods=['GET'])
    app.add_url_rule('/api/pg/news-inbox/hold', 'api_news_inbox_hold',
                     api_news_ingest.api_news_inbox_hold, methods=['POST'])
    app.add_url_rule('/api/pg/news-inbox/redraft-queue', 'api_news_inbox_redraft_queue',
                     api_news_ingest.api_news_inbox_redraft_queue, methods=['GET'])
    app.add_url_rule('/api/pg/news-inbox/stored-pdf', 'api_news_inbox_stored_pdf',
                     api_news_ingest.api_news_inbox_stored_pdf, methods=['GET'])
    app.add_url_rule('/api/pg/news-inbox/snapshot', 'api_news_inbox_snapshot',
                     api_news_ingest.api_news_inbox_snapshot, methods=['POST'])
    app.add_url_rule('/api/pg/news-inbox/upload-url', 'api_news_inbox_upload_url',
                     api_news_ingest.api_news_inbox_upload_url, methods=['POST'])
    app.add_url_rule('/api/pg/news-inbox/undated', 'api_news_inbox_undated',
                     api_news_ingest.api_news_inbox_undated, methods=['GET'])
    app.add_url_rule('/api/pg/news-inbox/set-date', 'api_news_inbox_set_date',
                     api_news_ingest.api_news_inbox_set_date, methods=['POST'])
    app.add_url_rule('/admin/pg/diag/news-key', 'pg_news_key_check',
                     api_news_ingest.admin_news_key_check, methods=['GET'])
    # Scraper schedule (10:00 / 13:00 / 18:30 / 23:00 IST) — same boot guard as app.py's scheduler.
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true' or os.environ.get('DATABASE_URL'):
        _news_scraper.start_scheduler()

    # ── Public API for goocampus.in: News feed (X-PG-Key; PDF is public) ──
    app.add_url_rule('/api/pg/news', 'api_pg_news',
                     api_news.api_pg_news, methods=['GET'])
    app.add_url_rule('/api/pg/calendar', 'api_pg_calendar',
                     api_news.api_pg_calendar, methods=['GET'])
    app.add_url_rule('/api/pg/counselling-status', 'api_pg_counselling_status',
                     api_news.api_pg_counselling_status, methods=['GET'])
    # Counselling Calendar admin (round-wise dates per authority; 2026-10-09)
    app.add_url_rule('/admin/pg/calendar', 'pg_calendar_admin', calendar_admin.calendar_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/calendar/save', 'pg_calendar_save', calendar_admin.calendar_save, methods=['POST'])
    app.add_url_rule('/admin/pg/calendar/remove', 'pg_calendar_remove', calendar_admin.calendar_remove, methods=['POST'])
    app.add_url_rule('/admin/pg/calendar/tidy', 'pg_calendar_tidy', calendar_admin.calendar_tidy, methods=['POST'])
    app.add_url_rule('/admin/pg/calendar/reminders', 'pg_calendar_reminders_toggle',
                     calendar_admin.calendar_reminders_toggle, methods=['POST'])
    app.add_url_rule('/admin/pg/calendar/reminders/preview', 'pg_calendar_reminders_preview',
                     calendar_admin.calendar_reminders_preview, methods=['POST'])
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true' or os.environ.get('DATABASE_URL'):
        from pg_admin import deadline_reminders as _dr
        _dr.start_scheduler()         # 8 AM IST; no-op unless switched ON + live service
    app.add_url_rule('/api/pg/news/deadlines', 'api_pg_news_deadlines',
                     api_news.api_pg_news_deadlines, methods=['GET'])
    app.add_url_rule('/api/pg/news/states', 'api_pg_news_states',
                     api_news.api_pg_news_states, methods=['GET'])
    app.add_url_rule('/api/pg/news/follows', 'api_pg_news_follows',
                     api_news.api_pg_news_follows, methods=['GET', 'POST', 'DELETE'])
    app.add_url_rule('/api/pg/news/<int:news_id>/pdf', 'api_pg_news_pdf',
                     api_news.api_pg_news_pdf, methods=['GET'])

    # ── Counselling Authorities hub (admin) + per-authority document library ──
    app.add_url_rule('/admin/pg/authorities', 'pg_authorities_admin',
                     authority_admin.authorities_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/authorities/doc/save', 'pg_authority_doc_save',
                     authority_admin.authority_doc_save, methods=['POST'])
    app.add_url_rule('/admin/pg/authorities/doc/toggle', 'pg_authority_doc_toggle',
                     authority_admin.authority_doc_toggle, methods=['POST'])
    app.add_url_rule('/admin/pg/authorities/doc/delete', 'pg_authority_doc_delete',
                     authority_admin.authority_doc_delete, methods=['POST'])
    app.add_url_rule('/admin/pg/authorities/doc/publish', 'pg_authority_doc_publish',
                     authority_admin.authority_doc_publish, methods=['POST'])
    app.add_url_rule('/admin/pg/authorities/doc/category', 'pg_authority_doc_category',
                     authority_admin.authority_doc_category, methods=['POST'])
    app.add_url_rule('/admin/pg/authorities/doc/main', 'pg_authority_doc_main',
                     authority_admin.authority_doc_main, methods=['POST'])
    app.add_url_rule('/admin/pg/authority-docs/<int:doc_id>/file', 'pg_authority_doc_file_admin',
                     authority_admin.authority_doc_file_admin, methods=['GET'])
    # ── Document Archive: every authority PDF by season → authority → category + ZIP + R2 backup ──
    app.add_url_rule('/admin/pg/archive', 'pg_archive',
                     archive_admin.archive_page, methods=['GET'])
    app.add_url_rule('/admin/pg/archive/zip', 'pg_archive_zip',
                     archive_admin.archive_zip_build, methods=['POST'])
    app.add_url_rule('/admin/pg/archive/zip/download', 'pg_archive_zip_download',
                     archive_admin.archive_zip_download, methods=['GET'])
    app.add_url_rule('/admin/pg/archive/backup', 'pg_archive_backup',
                     archive_admin.archive_backup_now, methods=['POST'])
    app.add_url_rule('/api/pg/archive/backfill', 'api_pg_archive_backfill',
                     archive_admin.api_archive_backfill, methods=['POST'])
    app.add_url_rule('/api/pg/archive/status', 'api_pg_archive_status',
                     archive_admin.api_archive_status, methods=['GET'])
    # ── Public API for goocampus.in: per-authority sections (X-PG-Key; file is public) ──
    app.add_url_rule('/api/pg/authorities', 'api_pg_authorities',
                     api_authorities.api_pg_authorities, methods=['GET'])
    app.add_url_rule('/api/pg/authority/<code>', 'api_pg_authority',
                     api_authorities.api_pg_authority, methods=['GET'])
    app.add_url_rule('/api/pg/authority-docs/<int:doc_id>/file', 'api_pg_authority_doc_file',
                     api_authorities.api_pg_authority_doc_file, methods=['GET'])

    # ── Public API for goocampus.in: PG College Database + Stipend (X-PG-Key) ──
    app.add_url_rule('/api/pg/college-lookup', 'api_pg_college_lookup',
                     api_college.api_pg_college_lookup, methods=['GET'])
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
    app.add_url_rule('/admin/pg/pgcp/backfill-profiles', 'pg_pgcp_backfill_profiles',
                     pgcp_admin.pgcp_backfill_profiles, methods=['GET', 'POST'])
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
    # Negotiated package + instalment payments per invite, and the PG payments overview
    # (team packages + online self-purchases). Admin-only (in-view gate). (2026-10-16)
    app.add_url_rule('/admin/pg/pgcp/<int:invite_id>/payments', 'pg_pgcp_payments',
                     pgcp_admin.pgcp_payments, methods=['GET', 'POST'])
    app.add_url_rule('/admin/pg/payments', 'pg_payments_admin',
                     pgcp_admin.pg_payments_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/payments/export', 'pg_payments_export',
                     pgcp_admin.pg_payments_export, methods=['GET'])
    app.add_url_rule('/api/pg/pgcp/onboarding', 'api_pgcp_onboarding',
                     api_pgcp.api_pgcp_onboarding, methods=['GET', 'POST'])
    app.add_url_rule('/api/pg/pgcp/onboarding/submit', 'api_pgcp_submit',
                     api_pgcp.api_pgcp_submit, methods=['POST'])

    # ── Cutoff Explorer + Choice-List builder ──
    app.add_url_rule('/api/pg/cutoff-explorer', 'api_pg_cutoff_explorer',
                     api_choice.api_pg_cutoff_explorer, methods=['GET'])
    app.add_url_rule('/api/pg/cutoff-explorer/facets', 'api_pg_cutoff_facets',
                     api_choice.api_pg_cutoff_facets, methods=['GET'])
    app.add_url_rule('/api/pg/cutoff-explorer/summary', 'api_pg_cutoff_summary',
                     api_choice.api_pg_cutoff_summary, methods=['GET'])
    app.add_url_rule('/api/pg/choice-entitlement', 'api_pg_choice_entitlement',
                     api_choice.api_pg_choice_entitlement, methods=['GET'])
    app.add_url_rule('/api/pg/my-states', 'api_pg_my_states',
                     api_choice.api_pg_my_states, methods=['GET', 'POST', 'DELETE'])
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
    app.add_url_rule('/admin/pg/users/<int:user_id>/choice-sets/create', 'pg_choice_create',
                     choice_admin.choice_create, methods=['POST'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/states', 'pg_choice_states',
                     choice_admin.choice_states, methods=['GET', 'POST', 'DELETE'])
    app.add_url_rule('/admin/pg/choice-facets', 'pg_choice_facets',
                     choice_admin.choice_facets, methods=['GET'])
    app.add_url_rule('/admin/pg/choice-sets/<int:set_id>/delete', 'pg_choice_delete_set',
                     choice_admin.choice_delete_set, methods=['POST'])
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
    # ── Counselling Desk (goocampus.in team login → build internal/paid doctors'
    #    choice lists, PDF + email). Token + desk_access gated in desk_api. ──
    _d = desk_api
    for rule, ep, fn, methods in (
        ('/api/pg/desk/me', 'api_pg_desk_me', _d.desk_me, ['GET']),
        ('/api/pg/desk/selftest', 'api_pg_desk_selftest', _d.desk_selftest, ['GET']),
        ('/api/pg/desk/tiers', 'api_pg_desk_tiers', recommended.desk_tiers, ['GET', 'POST']),
        ('/api/pg/desk/doctors/<int:doctor_id>/recommended', 'api_pg_desk_recommended',
         recommended.desk_recommended, ['POST']),
        ('/api/pg/desk/choice-sets/<int:set_id>/new-seats', 'api_pg_desk_new_seats',
         recommended.desk_new_seats, ['GET']),
        ('/api/pg/choice-sets/<int:set_id>/new-seats', 'api_pg_choice_new_seats',
         recommended.doctor_new_seats, ['GET']),
        ('/api/pg/tiers/ingest', 'api_pg_tiers_ingest', recommended.tiers_ingest, ['POST']),
        ('/api/pg/rankings', 'api_pg_rankings', rankings.api_rankings, ['GET']),
        ('/api/pg/my-plan-payments', 'api_pg_my_plan_payments', my_payments.api_my_payments, ['GET']),
        ('/api/pg/my-plan-payments/balance/create-order', 'api_pg_balance_create_order',
         my_payments.api_balance_create_order, ['POST']),
        ('/api/pg/my-plan-payments/balance/verify', 'api_pg_balance_verify', my_payments.api_balance_verify, ['POST']),
        ('/api/pg/rankings/pdf', 'api_pg_rankings_pdf', rankings.api_rankings_pdf, ['GET']),
        ('/api/pg/desk/rankings/email', 'api_pg_desk_rankings_email', rankings.desk_rankings_email, ['GET', 'POST']),
        ('/api/pg/desk/college-lists', 'api_pg_desk_college_lists', team_college_lists.lists_index, ['GET', 'POST']),
        ('/api/pg/desk/college-lists/<int:lid>', 'api_pg_desk_college_list', team_college_lists.list_detail,
         ['GET', 'POST', 'DELETE']),
        ('/api/pg/desk/college-lists/<int:lid>/pdf', 'api_pg_desk_college_list_pdf', team_college_lists.list_pdf,
         ['GET']),
        ('/api/pg/desk/doctors', 'api_pg_desk_doctors', _d.desk_doctors, ['GET']),
        ('/api/pg/desk/doctors/<int:doctor_id>', 'api_pg_desk_doctor', _d.desk_doctor, ['GET']),
        ('/api/pg/desk/doctors/<int:doctor_id>/states', 'api_pg_desk_states', _d.desk_states,
         ['GET', 'POST', 'DELETE']),
        ('/api/pg/desk/doctors/<int:doctor_id>/choice-sets', 'api_pg_desk_create_list',
         _d.desk_create_list, ['POST']),
        ('/api/pg/desk/facets', 'api_pg_desk_facets', _d.desk_facets, ['GET']),
        ('/api/pg/desk/doctors/<int:doctor_id>/profile', 'api_pg_desk_profile', _d.desk_profile, ['GET', 'POST']),
        ('/api/pg/desk/specialities', 'api_pg_desk_specialities', _d.desk_specialities, ['GET']),
        ('/api/pg/desk/choice-sets/<int:set_id>', 'api_pg_desk_delete_list', _d.desk_delete_list,
         ['DELETE', 'POST']),
        ('/api/pg/desk/choice-sets/<int:set_id>/search', 'api_pg_desk_search', _d.desk_search, ['GET']),
        ('/api/pg/desk/choice-sets/<int:set_id>/add', 'api_pg_desk_add', _d.desk_add, ['POST']),
        ('/api/pg/desk/choice-sets/<int:set_id>/reorder', 'api_pg_desk_reorder', _d.desk_reorder, ['POST']),
        ('/api/pg/desk/choice-sets/<int:set_id>/pdf', 'api_pg_desk_pdf', _d.desk_pdf, ['GET']),
        ('/api/pg/desk/choice-sets/<int:set_id>/email', 'api_pg_desk_email', _d.desk_email, ['POST']),
        ('/api/pg/desk/choice-items/<int:item_id>/move', 'api_pg_desk_move', _d.desk_move, ['POST']),
        ('/api/pg/desk/choice-items/<int:item_id>', 'api_pg_desk_remove', _d.desk_remove,
         ['DELETE', 'POST']),
        ('/api/pg/choice-sets/<int:set_id>/pdf', 'api_pg_choice_pdf', _d.doctor_choice_pdf, ['GET']),
        ('/api/pg/choice-sets/<int:set_id>/acknowledge', 'api_pg_choice_acknowledge',
         api_choice.api_pg_choice_acknowledge, ['POST']),
        ('/api/pg/desk/choice-sets/<int:set_id>/history', 'api_pg_desk_history', _d.desk_history, ['GET']),
    ):
        app.add_url_rule(rule, ep, fn, methods=methods)
    app.add_url_rule('/admin/pg/users/<int:user_id>/recommended', 'pg_choice_recommended',
                     recommended.admin_recommended, methods=['POST'])
    app.add_url_rule('/admin/pg/choice-sets/<int:set_id>/new-seats', 'pg_choice_new_seats',
                     recommended.admin_new_seats, methods=['GET'])
    app.add_url_rule('/admin/pg/college-rankings/pdf', 'pg_college_rankings_pdf',
                     rankings.admin_rankings_pdf, methods=['GET'])
    app.add_url_rule('/admin/pg/college-tiers', 'pg_college_tiers',
                     recommended.admin_tiers, methods=['GET', 'POST'])
    app.add_url_rule('/admin/pg/choice-sets/<int:set_id>/history', 'pg_choice_history',
                     choice_admin.choice_history, methods=['GET'])
    app.add_url_rule('/admin/pg/choice-sets/<int:set_id>/pdf', 'pg_choice_pdf',
                     choice_admin.choice_pdf, methods=['GET'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/set-desk', 'pg_user_set_desk',
                     users_admin.user_set_desk, methods=['POST'])
    # ── Events: public API (goocampus.in) + admin ──
    app.add_url_rule('/api/pg/events', 'api_pg_events', api_events.api_pg_events, methods=['GET'])
    app.add_url_rule('/api/pg/events/ticket/<ticket_code>', 'api_pg_event_ticket',
                     api_events.api_pg_event_ticket, methods=['GET'])
    app.add_url_rule('/api/pg/events/registrations', 'api_pg_event_registrations',
                     api_events.api_pg_event_registrations, methods=['GET'])
    app.add_url_rule('/api/pg/events/<slug>/register', 'api_pg_event_register',
                     api_events.api_pg_event_register, methods=['POST'])
    app.add_url_rule('/api/pg/events/<slug>', 'api_pg_event', api_events.api_pg_event, methods=['GET'])
    app.add_url_rule('/admin/pg/events', 'pg_events_admin', events_admin.events_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/events/create', 'pg_event_create', events_admin.event_create, methods=['POST'])
    app.add_url_rule('/admin/pg/events/<int:event_id>/toggle', 'pg_event_toggle',
                     events_admin.event_toggle, methods=['POST'])
    app.add_url_rule('/admin/pg/events/<int:event_id>/toggle-registration', 'pg_event_toggle_registration',
                     events_admin.event_toggle_registration, methods=['POST'])
    app.add_url_rule('/admin/pg/events/<int:event_id>/export', 'pg_event_export',
                     events_admin.event_export, methods=['GET'])
    app.add_url_rule('/admin/pg/events/registration/<int:reg_id>/update', 'pg_event_reg_update',
                     events_admin.event_reg_update, methods=['POST'])
    app.add_url_rule('/admin/pg/events/registration/<int:reg_id>/profile', 'pg_event_reg_profile',
                     events_admin.event_reg_profile, methods=['GET'])
    app.add_url_rule('/admin/pg/events/registration-update/<int:update_id>/delete', 'pg_event_reg_update_delete',
                     events_admin.event_reg_update_delete, methods=['POST'])
    # ── Usage analytics: ingest (goocampus.in) + admin dashboard ──
    app.add_url_rule('/api/pg/track', 'api_pg_track', api_track.api_pg_track, methods=['POST'])
    app.add_url_rule('/admin/pg/analytics', 'pg_analytics', analytics_admin.analytics_admin, methods=['GET'])

    # ── Predictor Data admin (cut-off dataset behind the goocampus.in predictor) ──
    app.add_url_rule('/admin/pg/predictor', 'pg_predictor_admin',
                     predictor_admin.predictor_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/specialty-groups', 'pg_specialty_groups',
                     specialty_admin.specialty_groups_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/specialty-groups/set', 'pg_specialty_groups_set',
                     specialty_admin.specialty_groups_set, methods=['POST'])
    app.add_url_rule('/admin/pg/specialty-groups/fix-cutoffs', 'pg_specialty_groups_fix_cutoffs',
                     specialty_admin.specialty_groups_fix_cutoffs, methods=['POST'])
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

    # ── Management / NRI Inquiries (goocampus.in's Management/NRI pages; NOT Sales) — 2026-10-20 ──
    app.add_url_rule('/admin/pg/mgmt-inquiries', 'pg_mgmt_inquiries',
                     mgmt_inquiries.mgmt_inquiries, methods=['GET'])
    app.add_url_rule('/admin/pg/mgmt-inquiries/<int:inq_id>/followup', 'pg_mgmt_inquiry_followup',
                     mgmt_inquiries.mgmt_inquiry_followup, methods=['POST'])
    # ── Registered Doctors admin ───────────────────────────────────────────
    app.add_url_rule('/admin/pg/users', 'pg_users_admin',
                     users_admin.users_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/users/followups', 'pg_users_followups',
                     users_admin.users_followups, methods=['GET'])
    app.add_url_rule('/admin/pg/users/visits', 'pg_users_visits',
                     users_admin.users_visits, methods=['GET'])
    app.add_url_rule('/admin/pg/users/did-not-pick-up', 'pg_users_did',
                     users_admin.users_stage, defaults={'stage': 'did-not-pick-up'}, methods=['GET'])
    app.add_url_rule('/admin/pg/users/contacted', 'pg_users_contacted',
                     users_admin.users_stage, defaults={'stage': 'contacted'}, methods=['GET'])
    app.add_url_rule('/admin/pg/users/converted', 'pg_users_converted',
                     users_admin.users_stage, defaults={'stage': 'converted'}, methods=['GET'])
    app.add_url_rule('/admin/pg/users/<int:user_id>', 'pg_user_detail',
                     users_admin.user_detail, methods=['GET'])
    app.add_url_rule('/admin/pg/diag/plan', 'pg_plan_diag',
                     users_admin.plan_diag, methods=['GET'])
    app.add_url_rule('/admin/pg/diag/home-state', 'pg_home_state_backfill',
                     diag_home_state.home_state_backfill, methods=['GET', 'POST'])
    app.add_url_rule('/admin/diag/pg-states', 'pg_states_cleanup',
                     diag_states.pg_states_cleanup, methods=['GET', 'POST'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/save', 'pg_user_save',
                     users_admin.user_save, methods=['POST'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/allotment-mark', 'pg_user_allotment_mark',
                     users_admin.user_allotment_mark, methods=['POST'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/followup', 'pg_user_followup_add',
                     users_admin.user_followup_add, methods=['POST'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/followup/<int:fu_id>/delete', 'pg_user_followup_delete',
                     users_admin.user_followup_delete, methods=['POST'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/block', 'pg_user_block',
                     users_admin.user_block, methods=['POST'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/grant-plan', 'pg_user_grant_plan',
                     users_admin.user_grant_plan, methods=['POST'])
    app.add_url_rule('/admin/pg/users/<int:user_id>/set-team', 'pg_user_set_team',
                     users_admin.user_set_team, methods=['POST'])
    app.add_url_rule('/admin/pg/users/employee-search', 'pg_employee_search',
                     users_admin.employee_search, methods=['GET'])
    app.add_url_rule('/admin/pg/users/add-employee', 'pg_add_employee',
                     users_admin.add_employee, methods=['POST'])
    app.add_url_rule('/admin/pg/diag/team-link', 'pg_team_link_check',
                     users_admin.team_link_check, methods=['GET'])
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
    app.add_url_rule('/admin/pg/diag/predictor', 'pg_predictor_diag',
                     api.admin_pg_predictor_diag, methods=['GET'])
    app.add_url_rule('/admin/pg/diag/branch-check', 'pg_branch_check',
                     api.admin_pg_branch_check, methods=['GET'])
    app.add_url_rule('/admin/pg/diag/speed', 'pg_speed_check',
                     api.admin_pg_speed_check, methods=['GET'])
    app.add_url_rule('/admin/pg/pay-test', 'pg_pay_test', api.admin_pg_pay_test, methods=['GET'])
    app.add_url_rule('/admin/pg/pay-test/verify', 'pg_pay_test_verify',
                     api.admin_pg_pay_test_verify, methods=['POST'])
    app.add_url_rule('/api/pg/checkout/verify', 'api_pg_checkout_verify',
                     api.api_pg_checkout_verify, methods=['POST'])
