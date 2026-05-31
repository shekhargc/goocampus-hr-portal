"""
routes/operations/ — Operations section split into per-sub-area Python modules.

This is the big reorganization of the refactor. The Operations section has
130 routes spread across ~20 sub-areas (PLAB, onboarding, GMC, EPIC,
coaching, vendors, etc.). Each sub-area gets its own file so multiple
agents can work on different sub-areas in parallel without touching the
same Python module.

Why NOT Flask Blueprints:
We use app.add_url_rule(...) instead of Blueprints so that endpoint names
stay identical (ops_ngo_list, ops_plab_list, etc.). app.py has ~110
existing url_for('ops_*') call sites — using Blueprints would rename
endpoints to 'operations_ngo.ops_ngo_list' and break every one of those
calls. Plain add_url_rule preserves names with zero call-site changes.

To add a new sub-area (e.g. Australia Pathway, which will mirror PLAB ~75%):
1. Create routes/operations/<name>.py
2. Define route functions decorated with @login_required / @admin_required
3. Define a register_routes(app) function that calls app.add_url_rule(...)
4. Add the import + register_routes(app) call to register_operations_modules() below

To register all sub-area modules with the Flask app, app.py calls:
    from routes.operations import register_operations_modules
    register_operations_modules(app)
"""


def register_operations_modules(app):
    """Register every migrated Operations sub-area module with the Flask app.

    Called once from app.py during startup. Each module owns a slice of the
    /operations/* URL space. Sub-areas still in app.py are NOT listed here
    yet — they'll be added as we migrate them step by step.
    See REFACTOR_PLAN.md.
    """
    # NGO Activities — first sub-area migrated (4 routes /operations/ngo-activities/*)
    from . import ngo
    ngo.register_routes(app)
