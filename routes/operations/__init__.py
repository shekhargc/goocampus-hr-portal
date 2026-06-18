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

To add a new sub-area (e.g. AMC Pathway, which will mirror PLAB ~75%):
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

    # AMC Pathway — v2 client management dashboard (/operations/australia-pathway)
    # and the Australia client list (/operations/australia/clients) live in australia.py.
    # Test bookings now lives in its own au_test_bookings module (drawer/detail/edit).
    from . import australia
    australia.register_routes(app)

    # Standard Consulting — S-0 foundation (/operations/consulting dashboard
    # + /operations/consulting/clients list). Houses the four consulting
    # products (AMC / UAE / USA / UK Consulting).
    from . import consulting
    consulting.register_routes(app)

    # Standard Consulting — S-1a Onboarding (list / detail / update /
    # send-welcome-email). Clones the AMC onboarding handlers with
    # pathway='consulting'.
    from . import cs_onboarding
    cs_onboarding.register_routes(app)

    # Standard Consulting — S-1b Academic Details + Call Notes.
    # Clones of au_academic + au_call_notes scoped to
    # pathway='consulting'.
    from . import cs_academic, cs_call_notes
    cs_academic.register_routes(app)
    cs_call_notes.register_routes(app)

    # Standard Consulting — S-1c Payments + EPIC Verification.
    # Clones of au_payments + au_epic scoped to pathway='consulting'.
    from . import cs_payments, cs_epic
    cs_payments.register_routes(app)
    cs_epic.register_routes(app)

    # Standard Consulting — S-2a GMC Registration. Clone of the PLAB
    # GMC handlers (ops_gmc_*) scoped to pathway='consulting'.
    from . import cs_gmc
    cs_gmc.register_routes(app)

    # Standard Consulting — S-2b AMC Registration. New section, new
    # table ops_amc_registration, schema mirrors GMC. Module clones
    # cs_gmc.py with gmc -> amc renames.
    from . import cs_amc
    cs_amc.register_routes(app)

    # Standard Consulting — S-2c Mentorship Sessions. Clone of the
    # PLAB Mentorship handlers (ops_mentorship_*) scoped to
    # pathway='consulting'. Shared ops_mentorship table.
    from . import cs_mentorship
    cs_mentorship.register_routes(app)

    # Standard Consulting — Services sections (manual data entry, no import).
    # Each clones the AMC (australia) section module scoped to
    # pathway='consulting'; list (with drawer) + detail + add + edit.
    #   Training              -> ops_coaching
    #   Online Subscriptions  -> ops_online_subscriptions
    #   Webinars & Conferences-> ops_webinars_conferences
    #   Research & Publication-> ops_research_publication
    #   Online Courses        -> ops_online_courses (DISTINCT from subscriptions)
    from . import cs_training, cs_online_subscriptions, cs_webinars
    from . import cs_research, cs_online_courses
    cs_training.register_routes(app)
    cs_online_subscriptions.register_routes(app)
    cs_webinars.register_routes(app)
    cs_research.register_routes(app)
    cs_online_courses.register_routes(app)

    # Phase 4 lightweight pathways — Portfolio + Training.
    # Each is a clone of Standard Consulting trimmed to 5 sections:
    # Dashboard, Registration (clients), Payments, Documents, Call Notes.
    # No medical sections (EPIC / GMC / AMC reg / academic / mentorship / etc.).
    #   Portfolio  (/operations/portfolio, prefix GCPPLUS, pathway='portfolio')
    #   Training   (/operations/training,  prefix GCTRN,   pathway='training')
    from . import portfolio, pf_payments, pf_call_notes
    portfolio.register_routes(app)
    pf_payments.register_routes(app)
    pf_call_notes.register_routes(app)

    from . import training, tr_payments, tr_call_notes
    training.register_routes(app)
    tr_payments.register_routes(app)
    tr_call_notes.register_routes(app)

    # Australia Operations sub-sections (Phase 3 + Phase 4 standardization).
    # Each module owns one /operations/australia/<section>/* slice:
    #   list (with drawer), detail page, edit form GET, edit save POST.
    from . import au_test_bookings, au_academic, au_epic, au_training
    from . import au_online_courses, au_payments, au_call_notes, au_research, au_webinars
    from . import au_amc
    au_test_bookings.register_routes(app)
    au_academic.register_routes(app)
    au_epic.register_routes(app)
    au_amc.register_routes(app)
    au_training.register_routes(app)
    au_online_courses.register_routes(app)
    au_payments.register_routes(app)
    au_call_notes.register_routes(app)
    au_research.register_routes(app)
    au_webinars.register_routes(app)
