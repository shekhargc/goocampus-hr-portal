"""
routes/operations/_form_lookups.py — pathway-aware dropdown helpers used by
every AMC + Consulting edit handler so the section forms render the same
dropdowns the PLAB forms do.

WHY THIS EXISTS
---------------
Each pathway's edit form (e.g. ops_australia_payments_edit.html) needs to
render `<select>` dropdowns whose options come from the `lookup_options`
table scoped to that pathway. PLAB handlers each call
`get_lookup_options('plan_type')`, `get_lookup_options('payment_method')`,
etc. individually and pass them into render_template.

Doing the same for every AMC + Consulting handler (10 sections per pathway,
4 render_template calls each) would mean ~80 duplicated dict-building
blocks. Instead, this module exposes one function per section that
returns the right dict in a single call. Handlers can then do:

    return render_template(
        'ops_australia_payments_edit.html',
        record=record,
        **section_payment_lookups('australia'),
        ...
    )

This keeps the per-handler change to a single line and guarantees every
PLAB-equivalent dropdown is wired without anyone having to remember the
exact category names.

PATHWAY ARGUMENT
----------------
`pathway` must be 'australia' or 'consulting'. The underlying
`get_lookup_options(category, pathway=pw)` falls back to the PLAB set
when the AMC / Consulting Field Manager hasn't been seeded yet, so empty
dropdowns shouldn't happen as long as PLAB has values seeded.
"""

from app import get_lookup_options, get_vendors_by_category
from db import get_db


# Maps the pathway slug used by the AMC/Consulting routes to the
# vendors_providers.country value the centralised vendor list is stored
# under. AMC routes pass pathway='australia' → 'AMC Pathway'.
_VENDOR_COUNTRY = {
    'australia': 'AMC Pathway',
    'consulting': 'Standard Consulting',
    'portfolio': 'Portfolio Pathway',
    'plab': 'UK Pathway',
}


def vendor_names_for(category, pathway, fallback_lookup=None):
    """Return centralised vendor names for a category + pathway.

    Pulls active vendors from vendors_providers (scoped by country, e.g.
    'AMC Pathway') for the given vp_category and returns just their names —
    this is the option list for a vendor <select>. Falls back to the
    pathway-scoped lookup_options list (fallback_lookup) when the
    centralised vendor list is empty, so existing forms never go blank.
    """
    country = _VENDOR_COUNTRY.get((pathway or '').strip().lower(), 'UK Pathway')
    try:
        vendors = get_vendors_by_category(category, country)
        names = [v['name'] for v in vendors] if vendors else []
    except Exception:
        names = []
    if names:
        return names
    if fallback_lookup:
        return get_lookup_options(fallback_lookup, pathway=pathway) or []
    return []


def transfer_for_reg(conn, reg):
    """The open internal-transfer row whose destination is this client, or None.

    Used by every pathway's client edit page to show the "Submit for Ops
    verification" banner when the record is a transferred one still being
    completed (Phase 2). Returns the row only while it is approved and not yet
    'completed' (i.e. completion_stage is 'awaiting_sales' or 'awaiting_ops').
    """
    if not reg:
        return None
    try:
        return conn.execute(
            "SELECT * FROM internal_transfers "
            " WHERE to_reg = ? AND status = 'approved' "
            "   AND COALESCE(completion_stage, 'awaiting_sales') <> 'completed' "
            " ORDER BY id DESC LIMIT 1",
            (reg,),
        ).fetchone()
    except Exception:
        return None


def section_client_products(pathway):
    """Active Products/Services for a pathway as {'products': [ {id, name}, ... ]}.

    Drives the Product/Service <select> on the AMC / Consulting client edit
    forms. Plan Type then cascades from the chosen product via the
    /operations/api/plan-types endpoint (client-side JS in the template).
    """
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, name FROM products_services "
            "WHERE COALESCE(pathway,'')=? AND COALESCE(status,'active')='active' ORDER BY name",
            ((pathway or '').strip().lower(),)).fetchall()
        products = [{'id': r['id'], 'name': r['name']} for r in rows]
    except Exception:
        products = []
    finally:
        conn.close()
    return {'products': products}


# ── Per-section dropdown maps ──────────────────────────────────────────────
# Each function returns {jinja_var_name: [list of option strings]} for the
# corresponding edit/add form. Keys here MUST match the {% for x in <var> %}
# variable names already used in the matching template.

def section_client_lookups(pathway, current=None):
    """Client registration / edit form (ops_*_client_edit_form.html).

    PLAB form (ops_plab_form.html) uses these dropdowns. AMC / Consulting
    edit forms historically used plain text inputs for the same fields —
    after this lookup wiring they should switch to <select>.

    `current` = the client's existing counsellor value; always included in the
    options so editing an OLD record (whose counsellor is now an inactive employee)
    can never drop the name on save. (founder 2026-08-23)
    """
    # Counsellors = the configured lookup names PLUS every current Sales/Operations
    # employee, so a client's counsellor can be set to an actual team member (e.g.
    # an ops person who owns a transferred client) on ANY pathway's edit form — not
    # just the historical fixed name list. (founder 2026-08-20)
    counsellors = list(get_lookup_options('counsellor', pathway=pathway) or [])
    try:
        conn = get_db()
        for r in conn.execute(
                "SELECT name FROM employees WHERE is_active = 1 "
                "AND LOWER(COALESCE(department,'')) IN ('sales','operations') "
                "AND COALESCE(TRIM(name),'') <> ''").fetchall():
            counsellors.append(r['name'])
        conn.close()
    except Exception:
        pass
    if current and str(current).strip():
        counsellors.append(str(current).strip())
    counsellors = sorted({c for c in counsellors if c}, key=str.lower)
    return {
        'plan_types':           get_lookup_options('plan_type',          pathway=pathway),
        'joined_stages':        get_lookup_options('joined_stage',       pathway=pathway),
        'account_statuses':     get_lookup_options('account_status',     pathway=pathway),
        'plab_stages':          get_lookup_options('current_stage',      pathway=pathway),
        'switched_programs':    get_lookup_options('switched_program',   pathway=pathway),
        'lead_sources':         get_lookup_options('lead_source',        pathway=pathway),
        'operations_referrals': get_lookup_options('operations_referral',pathway=pathway),
        'counsellors':          counsellors,
    }


def section_payment_lookups(pathway):
    """Payments edit form (ops_*_payments_edit.html)."""
    return {
        'instalment_options': get_lookup_options('instalment',     pathway=pathway),
        'payment_methods':    get_lookup_options('payment_method', pathway=pathway),
        # plan_type also appears here so the AMC payment row inherits the
        # admin-configured Plan Type list.
        'plan_types':         get_lookup_options('plan_type',      pathway=pathway),
    }


def section_test_bookings_lookups(pathway):
    """Test Bookings edit form (ops_*_test_bookings_edit.html)."""
    return {
        'exam_names':         get_lookup_options('exam_name',     pathway=pathway),
        'exam_statuses':      get_lookup_options('exam_status',   pathway=pathway),
        'exam_results':       get_lookup_options('exam_result',   pathway=pathway),
        'exam_methods':       get_lookup_options('exam_method',   pathway=pathway),
        'exam_booked_by':     get_lookup_options('exam_booked_by',pathway=pathway),
        'exam_countries':     get_lookup_options('exam_country',  pathway=pathway),
        'revaluation_options':get_lookup_options('revaluation',   pathway=pathway) or ['Yes', 'No'],
        'reval_results':      get_lookup_options('exam_result',   pathway=pathway),
    }


def section_epic_lookups(pathway):
    """EPIC Registration / Verification edit form
    (ops_australia_epic_edit.html, ops_consulting_epic_edit.html)."""
    return {
        'epic_reg_statuses':       get_lookup_options('epic_reg_status',    pathway=pathway),
        'epic_statuses':           get_lookup_options('epic_status',        pathway=pathway),
        'notary_camp_statuses':    get_lookup_options('notary_camp_status', pathway=pathway),
        'doc_stage_options':       get_lookup_options('doc_stage',          pathway=pathway),
        'doc_stage_status_options':get_lookup_options('doc_stage_status',   pathway=pathway),
    }


def section_academic_lookups(pathway):
    """Academic Details edit form (ops_*_academic_edit.html)."""
    return {
        'img_fmg_options':         get_lookup_options('img_fmg',           pathway=pathway),
        'mbbs_statuses':           get_lookup_options('mbbs_status',       pathway=pathway),
        'internship_statuses':     get_lookup_options('internship_status', pathway=pathway),
        'internship_gap_options':  get_lookup_options('internship_gap',    pathway=pathway) or ['Yes', 'No'],
        'working_statuses':        get_lookup_options('working_status',    pathway=pathway),
        # PG (postgraduate) medical education — shown once MBBS + internship done.
        'pg_done_options':         get_lookup_options('pg_done',           pathway=pathway) or ['Yes', 'No'],
        'pg_type_options':         get_lookup_options('pg_type',           pathway=pathway) or ['NEET PG (MD/MS)', 'DNB'],
        'pg_status_options':       get_lookup_options('pg_status',         pathway=pathway) or ['First Year', 'Second Year', 'Final Year', 'Completed'],
        # The specialty picklist depends on the PG type; both lists are seeded
        # from the NEET-PG PDF course data and are editable in the Field Manager.
        'pg_specialty_neetpg':     get_lookup_options('pg_specialty_neetpg', pathway=pathway),
        'pg_specialty_dnb':        get_lookup_options('pg_specialty_dnb',    pathway=pathway),
    }


def section_research_lookups(pathway):
    """Research & Publication edit form (ops_*_research_edit.html).

    research_providers is sourced from the centralised vendor list
    (vendors_providers, category 'Research & Publications') so the vendor
    select matches the PLAB form; falls back to the research_provider
    lookup_options list when no vendors are seeded. research_services is the
    full server-rendered deliverable list the cascade narrows from.
    """
    return {
        'research_statuses':  get_lookup_options('research_status',  pathway=pathway),
        'author_positions':   get_lookup_options('author_position',  pathway=pathway),
        'research_providers': vendor_names_for('Research & Publications', pathway,
                                               fallback_lookup='research_provider'),
        'research_services':  get_lookup_options('research_service', pathway=pathway),
    }


def section_training_lookups(pathway):
    """Training / Coaching edit form (ops_australia_training_edit.html).

    Mirrors PLAB Coaching form (ops_coaching_form.html) dropdowns.
    """
    return {
        'course_types':       get_lookup_options('coaching_course_type', pathway=pathway),
        'coaching_methods':   get_lookup_options('coaching_method',      pathway=pathway),
        'coaching_statuses':  get_lookup_options('coaching_status',      pathway=pathway),
        'training_programs':  get_lookup_options('training_program',     pathway=pathway),
        'batch_months':       get_lookup_options('batch_month',          pathway=pathway),
        'batch_years':        get_lookup_options('batch_year',           pathway=pathway),
        'booked_by_options':  get_lookup_options('coaching_booked_by',   pathway=pathway),
        'attendance_options': get_lookup_options('coaching_attendance',  pathway=pathway) or ['Present', 'Absent'],
        # Centralised vendor list for the Training Programs category — drives
        # the vendor-first <select>; training_program then cascades from it.
        'training_vendors':   vendor_names_for('Training Programs', pathway,
                                               fallback_lookup='training_program'),
    }


def section_online_courses_lookups(pathway):
    """Online Courses / Online Subscriptions edit form
    (ops_australia_online_courses_edit.html).

    Mirrors PLAB Online Courses form (ops_courses_form.html). The AMC
    edit template's fields are actually online_subscription /
    activation_type / booked_by (the data model treats Online Courses
    and Online Subscriptions as the same section). Category names
    follow seed_australia_lookups.py.
    """
    return {
        'subscription_types':     get_lookup_options('subscription_type',      pathway=pathway),
        'activation_types':       get_lookup_options('activation_type',        pathway=pathway),
        'booked_by_options':      get_lookup_options('subscription_booked_by', pathway=pathway),
        # Centralised vendor list for the Online Subscriptions category —
        # drives the vendor-first <select>; the subscription/course name then
        # cascades from it.
        'subscription_vendors':   vendor_names_for('Online Subscriptions', pathway,
                                                   fallback_lookup='subscription_type'),
    }


def section_webinars_lookups(pathway):
    """Webinars & Conferences edit form (ops_*_webinars_edit.html)."""
    return {
        'event_types':         get_lookup_options('event_type',         pathway=pathway),
        'event_values':        get_lookup_options('event_value',        pathway=pathway),
        'participation_types': get_lookup_options('participation_type', pathway=pathway),
        'event_statuses':      get_lookup_options('event_status',       pathway=pathway),
        # Centralised vendor list for the Webinars category — drives the
        # vendor-first Provider <select>; event_type then cascades from it.
        'webinar_vendors':     vendor_names_for('Webinars', pathway,
                                                fallback_lookup='event_type'),
    }


def section_call_notes_lookups(pathway):
    """Call Notes edit form (ops_*_call_notes_edit.html)."""
    return {
        'note_types':       get_lookup_options('call_note_type',  pathway=pathway),
        'call_outcomes':    get_lookup_options('call_outcome',    pathway=pathway),
        'follow_up_types':  get_lookup_options('follow_up_type',  pathway=pathway),
    }
