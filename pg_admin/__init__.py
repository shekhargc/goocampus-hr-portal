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
from pg_admin.routes import mentors_admin, api


def register_pg_admin(app):
    # Make pg_admin/templates/ resolvable as 'pg_admin/<name>.html'
    tpl_dir = os.path.join(os.path.dirname(__file__), 'templates')
    app.jinja_loader = ChoiceLoader([app.jinja_loader, FileSystemLoader(tpl_dir)])

    # Tables self-create at boot (idempotent) — same pattern as college module.
    for fn in (_tables.ensure_pg_mentors_table,):
        try:
            fn()
        except Exception as e:
            logging.error(f"pg_admin boot {fn.__name__}: {e}")

    # ── Admin screens (goocampus.org staff; true-admin gated inside) ──
    app.add_url_rule('/admin/pg/mentors', 'pg_mentors_admin',
                     mentors_admin.mentors_admin, methods=['GET'])
    app.add_url_rule('/admin/pg/mentors/save', 'pg_mentor_save',
                     mentors_admin.mentor_save, methods=['POST'])
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
