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

    # Finance — read-only "Client Registrations" audit across ALL pathways +
    # payments (/finance/registrations). Gated by finance→registrations.
    from . import finance_registrations
    finance_registrations.register_routes(app)

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

    # AMC Pathway — Mentorship Sessions. Mirror of the Consulting Mentorship
    # handlers (cs_mentorship) scoped to pathway='australia'.
    from . import au_mentorship
    au_mentorship.register_routes(app)

    # Portfolio Pathway — Mentorship Sessions. Mirror of cs_mentorship scoped
    # to pathway='portfolio'. Shared ops_mentorship table + shared provider list.
    from . import pf_mentorship
    pf_mentorship.register_routes(app)

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

    # Standard Consulting — Test Bookings. Clone of au_test_bookings scoped
    # to pathway='consulting' (shared ops_test_bookings table). List (with
    # drawer) + detail + add + edit.
    from . import cs_test_bookings
    cs_test_bookings.register_routes(app)

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

    # Portfolio Pathway — Services sections (manual data entry, no import).
    # Each clones the Standard Consulting section module scoped to
    # pathway='portfolio'; list (with drawer) + detail + add + edit. They
    # keep the vendor-first cascade (vendor select on top, deliverable
    # cascades via /operations/api/vendor-services?pathway=portfolio).
    #   Research & Publications  -> ops_research_publication
    #   Courses & Certifications -> ops_online_courses
    #   Webinars & Conferences   -> ops_webinars_conferences
    from . import pf_research, pf_courses, pf_webinars
    pf_research.register_routes(app)
    pf_courses.register_routes(app)
    pf_webinars.register_routes(app)

    # UAE Pathway — mirrors Portfolio (Registration / Documents / Payments /
    # Call Notes + the pathway dashboard, reg prefix GCUAE, pathway='uae')
    # PLUS three brand-new sections: Self Assessment, Eligibility Letter,
    # and Data Flow. Six modules, all scoped to pathway='uae'.
    #   uae               (/operations/uae, clients, documents, dashboard)
    #   uae_payments      (/operations/uae/payments)
    #   uae_call_notes    (/operations/uae/call-notes)
    #   uae_self_assessment (/operations/uae/self-assessment)
    #   uae_eligibility   (/operations/uae/eligibility-letter)
    #   uae_data_flow     (/operations/uae/data-flow)
    from . import uae, uae_payments, uae_call_notes
    from . import uae_self_assessment, uae_eligibility, uae_data_flow
    uae.register_routes(app)
    uae_payments.register_routes(app)
    uae_call_notes.register_routes(app)
    uae_self_assessment.register_routes(app)
    uae_eligibility.register_routes(app)
    uae_data_flow.register_routes(app)

    from . import training, tr_payments, tr_call_notes
    training.register_routes(app)
    tr_payments.register_routes(app)
    tr_call_notes.register_routes(app)

    # Cross-pathway add: drop an existing client (consulting / australia /
    # etc.) into the Training pathway list without re-registering them.
    from . import cross_pathway_add
    cross_pathway_add.register_routes(app)

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

    # Call Notes -> Reports tab: ONE shared report engine for every pathway
    # (plab / consulting / uae / australia / portfolio / training).
    from . import call_notes_report
    call_notes_report.register_routes(app)
