"""College module — Portal + Medical Predictor + NEET-PG PDFs + partner pages.
Self-contained: routes/, data/, templates/college/, static/college/.
Wire in with:  from college import register_college; register_college(app)
"""
import os, logging
from jinja2 import ChoiceLoader, FileSystemLoader
from college.data import tables as _tables
from college.routes import portal, predictor, neetpg, partner


def register_college(app):
    tpl_dir = os.path.join(os.path.dirname(__file__), 'templates')
    app.jinja_loader = ChoiceLoader([app.jinja_loader, FileSystemLoader(tpl_dir)])
    for fn in (_tables.ensure_college_tables, _tables.ensure_neetpg_doctype_column,
               _tables.ensure_neetpg_quota_column,
               _tables.rename_neetpg_state_all_india_mcc,
               _tables._auto_seed_russian_colleges,
               _tables._auto_import_indian_colleges):
        try:
            fn()
        except Exception as e:
            logging.error(f"college boot {fn.__name__}: {e}")
    app.add_url_rule('/colleges', 'colleges_list', portal.colleges_list, methods=['GET'])
    app.add_url_rule('/colleges/<slug>', 'college_profile', portal.college_profile, methods=['GET'])
    app.add_url_rule('/colleges/admin/add', 'college_add', portal.college_add, methods=['GET', 'POST'])
    app.add_url_rule('/colleges/admin/edit/<int:college_id>', 'college_edit', portal.college_edit, methods=['GET', 'POST'])
    app.add_url_rule('/colleges/admin/delete/<int:college_id>', 'college_delete', portal.college_delete, methods=['POST'])
    app.add_url_rule('/colleges/admin/<int:college_id>/course/add', 'college_course_add', portal.college_course_add, methods=['POST'])
    app.add_url_rule('/colleges/admin/course/<int:course_id>/fee/add', 'college_fee_add', portal.college_fee_add, methods=['POST'])
    app.add_url_rule('/colleges/admin/fee/delete/<int:fee_id>', 'college_fee_delete', portal.college_fee_delete, methods=['POST'])
    app.add_url_rule('/colleges/admin/seed', 'college_seed', portal.college_seed, methods=['POST'])
    app.add_url_rule('/colleges/admin/debug-import', 'college_debug_import', portal.college_debug_import, methods=['GET'])
    app.add_url_rule('/colleges/admin/import-all', 'college_import_all', portal.college_import_all, methods=['GET'])
    app.add_url_rule('/medical-predictor', 'medical_predictor', predictor.medical_predictor, methods=['GET'])
    app.add_url_rule('/api/predictor/import', 'predictor_import', predictor.predictor_import, methods=['POST'])
    app.add_url_rule('/api/predictor/filters', 'predictor_filters', predictor.predictor_filters, methods=['GET'])
    app.add_url_rule('/api/predictor/search', 'predictor_search', predictor.predictor_search, methods=['GET'])
    app.add_url_rule('/neet-pg-2025', 'neetpg_landing', neetpg.neetpg_landing, methods=['GET'])
    app.add_url_rule('/neet-pg-2025/capture-lead', 'neetpg_capture_lead', neetpg.neetpg_capture_lead, methods=['POST'])
    app.add_url_rule('/neet-pg-2025/check-phone', 'neetpg_check_phone', neetpg.neetpg_check_phone, methods=['POST'])
    app.add_url_rule('/neet-pg-2025/send-otp', 'neetpg_send_otp', neetpg.neetpg_send_otp, methods=['POST'])
    app.add_url_rule('/neet-pg-2025/verify-otp', 'neetpg_verify_otp', neetpg.neetpg_verify_otp, methods=['POST'])
    app.add_url_rule('/neet-pg-2025/logout', 'neetpg_logout', neetpg.neetpg_logout, methods=['POST'])
    app.add_url_rule('/neet-pg-2025/request', 'neetpg_submit_request', neetpg.neetpg_submit_request, methods=['POST'])
    app.add_url_rule('/neet-pg-2025/check-notifications', 'neetpg_check_notifications', neetpg.neetpg_check_notifications, methods=['POST'])
    app.add_url_rule('/admin/neetpg-requests/<int:req_id>/complete', 'neetpg_complete_request', neetpg.neetpg_complete_request, methods=['POST'])
    app.add_url_rule('/neet-pg-2025/download/<int:pdf_id>', 'neetpg_download', neetpg.neetpg_download, methods=['GET'])
    app.add_url_rule('/neet-pg-2025/view/<int:pdf_id>', 'neetpg_view', neetpg.neetpg_view, methods=['GET'])
    app.add_url_rule('/admin/neetpg-pdfs', 'neetpg_admin', neetpg.neetpg_admin, methods=['GET'])
    app.add_url_rule('/admin/neetpg-pdfs/upload', 'neetpg_upload', neetpg.neetpg_upload, methods=['POST'])
    app.add_url_rule('/admin/neetpg-pdfs/<int:pdf_id>/toggle', 'neetpg_toggle', neetpg.neetpg_toggle, methods=['POST'])
    app.add_url_rule('/admin/neetpg-pdfs/<int:pdf_id>/publish', 'neetpg_publish', neetpg.neetpg_publish, methods=['POST'])
    app.add_url_rule('/admin/neetpg-pdfs/<int:pdf_id>/toggle-schedule', 'neetpg_toggle_schedule', neetpg.neetpg_toggle_schedule, methods=['POST'])
    app.add_url_rule('/admin/neetpg-pdfs/<int:pdf_id>/wa-blast', 'neetpg_wa_blast', neetpg.neetpg_wa_blast, methods=['POST'])
    app.add_url_rule('/admin/neetpg-pdfs/<int:pdf_id>', 'neetpg_delete', neetpg.neetpg_delete, methods=['DELETE'])
    app.add_url_rule('/admin/neetpg-leads/<int:lead_id>', 'neetpg_delete_lead', neetpg.neetpg_delete_lead, methods=['DELETE'])
    app.add_url_rule('/admin/neetpg-requests/<int:req_id>', 'neetpg_delete_request', neetpg.neetpg_delete_request, methods=['DELETE'])
    app.add_url_rule('/admin/neetpg-leads/export', 'neetpg_export_leads', neetpg.neetpg_export_leads, methods=['GET'])
    app.add_url_rule('/admin/neetpg-pdfs/quota-backfill', 'neetpg_quota_backfill', neetpg.neetpg_quota_backfill, methods=['GET', 'POST'])
    app.add_url_rule('/admin/neetpg-pdfs/bulk-upload', 'neetpg_bulk_upload', neetpg.neetpg_bulk_upload, methods=['POST'])
    app.add_url_rule('/admin/neetpg-pdfs/bulk-delete', 'neetpg_bulk_delete', neetpg.neetpg_bulk_delete, methods=['GET', 'POST'])
    app.add_url_rule('/admin/neetpg-pdfs/find-missing', 'neetpg_find_missing', neetpg.neetpg_find_missing, methods=['POST'])
    app.add_url_rule('/admin/neetpg-pdfs/all', 'neetpg_all_uploads', neetpg.neetpg_all_uploads, methods=['GET'])
    app.add_url_rule('/partner/colleges', 'partner_colleges', partner.partner_colleges, methods=['GET'])
    app.add_url_rule('/partner/colleges/<slug>', 'partner_college_profile', partner.partner_college_profile, methods=['GET'])
    app.add_url_rule('/partner/medical-predictor', 'partner_medical_predictor', partner.partner_medical_predictor, methods=['GET'])
