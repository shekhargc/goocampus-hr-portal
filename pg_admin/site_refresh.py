"""Tell goocampus.in to rebuild its cached pages the moment the portal changes the data behind them
(founder 2026-10-21: the public seat-matrix page kept showing the previous totals for up to an hour
after the MCC FINAL import).

One after-request hook: when a data-changing endpoint below succeeds, the portal POSTs the page tags
to the website's refresh link in a background thread (5 s timeout) — never slows or breaks a save.

Env (both set by the founder in Render):
  SITE_REVALIDATE_URL  e.g. https://goocampus.in/api/revalidate
  SITE_REVALIDATE_KEY  same secret as the website's REVALIDATE_KEY
Missing env → silently does nothing.
"""
import logging
import os
import threading

# endpoint → tags the website should refresh. 'authority' adds authority:<code> when the request
# names one (form/JSON authority_code).
_ENDPOINT_TAGS = {
    # seat matrix (+ rankings, which are built on it)
    'api_seat_matrix_ingest': ['seat-matrix', 'rankings', 'authority'],
    'api_seat_matrix_source_update': ['seat-matrix', 'rankings', 'authority'],
    'api_seat_matrix_file_to_authority': ['seat-matrix', 'authority'],
    'pg_seat_matrix_upload': ['seat-matrix', 'rankings', 'authority'],
    'pg_seat_matrix_delete': ['seat-matrix', 'rankings', 'authority'],
    # cut-offs / course names / college data
    'pg_predictor_upload': ['cutoffs', 'rankings', 'colleges'],
    'pg_specialty_groups_fix_cutoffs': ['cutoffs'],
    'api_maint_course_rename': ['cutoffs', 'seat-matrix', 'colleges'],
    'pg_college_master_upload_workbook': ['colleges', 'cutoffs'],
    'pg_college_master_upload_matching': ['colleges', 'cutoffs'],
    'pg_college_master_purge_blank': ['colleges', 'cutoffs'],
    # news + counselling calendar
    'pg_news_save': ['news', 'calendar', 'authority'],
    'pg_news_toggle': ['news'],
    'pg_news_delete': ['news'],
    'pg_news_restore': ['news'],
    'pg_news_purge': ['news'],
    'api_news_inbox_ingest': ['calendar'],
    'pg_calendar_save': ['calendar', 'news', 'authority'],
    'pg_calendar_remove': ['calendar', 'news', 'authority'],
    'pg_calendar_tidy': ['calendar', 'news', 'authority'],
    # authority documents
    'pg_authority_doc_save': ['authority'],
    'pg_authority_doc_toggle': ['authority'],
    'pg_authority_doc_delete': ['authority'],
    'pg_authority_doc_publish': ['authority'],
    'pg_authority_doc_category': ['authority'],
    'pg_authority_doc_main': ['authority'],
    # college tiers → MCC College Rankings
    'pg_college_tiers': ['rankings'],
    'api_pg_desk_tiers': ['rankings'],
    'api_pg_tiers_ingest': ['rankings'],
}


def _post(url, key, payload):
    try:
        import requests
        r = requests.post(url, json=payload, headers={'X-Revalidate-Key': key}, timeout=5)
        if r.status_code >= 400:
            logging.warning("site refresh %s → %s %s", payload.get('tags'), r.status_code, r.text[:160])
    except Exception as e:
        logging.warning("site refresh failed: %s", e)


def refresh(tags, paths=None):
    """Fire-and-forget: ask goocampus.in to rebuild pages carrying these tags."""
    url = (os.environ.get('SITE_REVALIDATE_URL') or '').strip()
    key = (os.environ.get('SITE_REVALIDATE_KEY') or '').strip()
    tags = sorted({t for t in (tags or []) if t})
    if not (url and key and (tags or paths)):
        return False
    threading.Thread(target=_post, args=(url, key, {'tags': tags, 'paths': list(paths or [])}),
                     daemon=True).start()
    return True


def _authority_code():
    from flask import request
    code = (request.form.get('authority_code') or request.form.get('authority') or '').strip().lower()
    if not code:
        d = request.get_json(silent=True) if request.is_json else None
        if isinstance(d, dict):
            code = str(d.get('authority_code') or '').strip().lower()
    return code


def register(app):
    @app.after_request
    def _site_refresh_hook(response):
        try:
            from flask import request
            if request.method != 'POST':
                return response
            tags = _ENDPOINT_TAGS.get(request.endpoint or '')
            if not tags or response.status_code >= 400:
                return response
            # admin forms answer with a redirect either way — only a signed-in user's save counts
            # (API endpoints reject bad keys with 401, so their status is enough)
            if not request.path.startswith('/api/'):
                from flask import session
                if not session.get('user_id'):
                    return response
            out = [t for t in tags if t != 'authority']
            if 'authority' in tags:
                code = _authority_code()
                out.append(f'authority:{code}' if code else 'authority')
            refresh(out)
        except Exception as e:
            logging.warning("site refresh hook: %s", e)
        return response
