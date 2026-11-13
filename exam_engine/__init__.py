"""Exam engine — mock tests for NEET PG first (goocampus.in), built to be reused for NEET UG / KCET / JEE
(12thPlus) later. Founder decisions 2026-11-13: practice mocks taken anytime from a package; one free
sample mock; runs inside the portal for now (no new Render cost), kept self-contained so it can move to
its own service + database if load needs it.

  subjects.py       19 NEET PG subjects + speciality → subject mapping
  tables.py         ex_* tables (additive, tenant-aware), exam pattern as settings
  importer/         Word / typed PDF / Excel readers, the layout parser, the check report
  store.py          saving imports, images (R2), re-checks, version history
  admin.py          the team's import + review screens (/admin/pg/mocks/*)

Wire in with:  from exam_engine import register_exam_engine; register_exam_engine(app)
"""
import logging


def register_exam_engine(app):
    from exam_engine import tables, admin
    import os
    from jinja2 import ChoiceLoader, FileSystemLoader
    tpl_dir = os.path.join(os.path.dirname(__file__), 'templates')
    app.jinja_loader = ChoiceLoader([app.jinja_loader, FileSystemLoader(tpl_dir)])
    try:
        tables.ensure_exam_tables()
    except Exception as e:
        logging.error(f'exam_engine boot ensure_exam_tables: {e}')
    admin.register_routes(app)
    from exam_engine import admin_papers, doctor_api, attempts, store_api, admin_packages
    admin_papers.register_routes(app)
    store_api.register_routes(app)          # before doctor_api: /api/pg/mocks/packages/* are fixed paths
    doctor_api.register_routes(app)
    admin_packages.register_routes(app)
    attempts.start_sweeper()          # submits attempts whose time ran out while the doctor was away
