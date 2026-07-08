# Project Map — "where does X live"

Use this to jump straight to the code for any area **without scanning `app.py`**. Format:
**what → route prefix · file(s) · main tables · deep-dive doc**.

---

## By section

| Area | Route prefix | Code | Main tables | Doc |
|---|---|---|---|---|
| Login / auth / roles | `/login` `/client/login` `/partner-login` | `core/auth.py`, app.py L505+ | employees, client_accounts, partners | [access-permissions](sections/access-permissions.md) |
| **Access Master** (permissions) | `/admin/access-master` | app.py L31914 (catalog), L34901 (route map), L35326–35549 (checks) | user_section_permissions | [access-permissions](sections/access-permissions.md) |
| Dashboard | `/dashboard` | app.py L3576 | employees, leave_records | — |
| **Sales** — dashboard/leads/closures | `/sales` `/sales/leads` `/sales/closures` | app.py L26200–27600 | sales_leads, sales_closures, sales_lead_stages, sales_team, sales_targets | [sales](sections/sales.md) |
| Sales — closure form (→ invite) | `sales_leads_add` | app.py ~L26580, `sales_lead_form.html` | sales_closures, client_invitations | [sales](sections/sales.md) |
| Sales — revenue report | `/sales/revenue-report` | app.py (`sales_revenue_report`) | plab_clients, plan_packages | [sales](sections/sales.md) |
| Verification queues | `/verifications/sales` `/verifications/ops` | `routes/verification_queues.py` | client_registrations, internal_transfers | [operations](sections/operations.md) |
| **Operations** — dashboard | `/operations` | app.py L16628 | plab_clients | [operations](sections/operations.md) |
| Ops — PLAB (legacy) | `/operations/plab*` | app.py L19560–19672, `ops_plab_dashboard.html` | plab_clients, ops_* | [operations](sections/operations.md) |
| Ops — other pathways | `/operations/{australia,consulting,uae,portfolio,training}/*` | `routes/operations/{pathway}.py` + `{au,cs,uae,pf,tr}_*.py` | plab_clients, ops_* | [operations](sections/operations.md) |
| Ops — Call Notes report | `/operations/{pathway}/call-notes/report` | `routes/operations/call_notes_report.py` | ops_call_notes | [operations](sections/operations.md) |
| Module wiring | — | `routes/operations/__init__.py` (`register_operations_modules`) | — | [architecture](ARCHITECTURE.md) |
| **HR** — leave | `/apply-leave` `/approve` `/admin/monthly-report` | app.py L186–430 (calc), L4135–7400 | leave_records, holidays, employees | [hr](sections/hr-leave-attendance.md) |
| HR — attendance | `/admin/upload-attendance` `/time-log` | app.py L30317+ | attendance_logs | [hr](sections/hr-leave-attendance.md) |
| HR — WFH / travel | `/wfh/*` `/official-travel/*` | app.py L8743+, L9009+ | wfh_requests, official_travel_requests | [hr](sections/hr-leave-attendance.md) |
| HR — employees | `/admin/manage-employees` `/admin/employee/<id>` | app.py L5685–6220 | employees | [hr](sections/hr-leave-attendance.md) |
| **KRA** | `/kra/*` | app.py L11218–11923 | kra_templates, kra_assignments, kra_monthly_ratings | [hr](sections/hr-leave-attendance.md) |
| **Finance** — budget | `/finance/budget*` | app.py L12276–13800 | budget_entries, budget_categories | [finance](sections/finance.md) |
| Finance — salaries/subscriptions | `/finance/salaries` `/finance/subscriptions` | app.py L13878–14300 | salary_items, subscription_items | [finance](sections/finance.md) |
| Products / Projects | `/products` `/projects` | app.py L9382–9870 | products_services, projects, revenue_streams | [finance](sections/finance.md) / [packages](sections/packages-products.md) |
| **Packages / Plans** | `/admin/packages` | app.py L1340–1560, L28980+ | plan_packages, package_services, service_catalogue | [packages](sections/packages-products.md) |
| **Client portal** | `/client/*` `/register/<token>` | app.py L975–1970, `client_form.html`, `client_dashboard.html` | client_accounts, client_registrations, client_academics, client_documents | [client-portal](sections/client-portal-registration.md) |
| Client form config | `/admin/client-form-config` | app.py L2113+ | client_form_configs | [client-portal](sections/client-portal-registration.md) |
| **Feedback** | `/admin/feedback*` `/feedback/<token>` | `routes/feedback.py`, `routes/feedback_seed.py` | feedback_forms/questions/invites/responses/answers | [feedback](sections/feedback.md) |
| Infobip DLR webhook | `/webhooks/infobip/dlr` | `routes/feedback.py` | feedback_invites | [feedback](sections/feedback.md) |
| **WhatsApp** section | `/whatsapp/*` | app.py | wa_campaigns, wa_contacts, wa_templates, wa_messages | [feedback](sections/feedback.md) (WA infra) |
| **Partners** | `/partner/*` `/partners/*` | app.py L700–929, L27700–29000 | partners, partner_leads, partner_b2b_leads | [partners-college](sections/partners-college.md) |
| **College** module | `/colleges` `/medical-predictor` `/neet-pg-2025` | `college/` folder | colleges, mbbs_cutoffs, neetpg_* | [partners-college](sections/partners-college.md) |
| Country landing pages | `/germany-pathway` `/russia` `/georgia` `/vietnam` `/uzbekistan` `/jss-mauritius` | app.py | germany_pathway_leads, *_leads | [partners-college](sections/partners-college.md) |
| **Clients admin hub** | `/admin/clients*` `/admin/payments-hub` `/admin/refunds` `/admin/internal-transfers` | app.py | client_registrations, ops_payments, refunds, internal_transfers | [client-portal](sections/client-portal-registration.md) |
| **Company** — holidays/locations/announcements/email templates | `/company/*` `/admin/holidays` | app.py | holidays, states, cities, email_templates, announcements | [hr](sections/hr-leave-attendance.md) |
| Reports (Excel exports) | `/reports/*` | app.py | (various) | — |
| Lookups (dropdowns) | `/admin/...lookups` | `core/lookups.py`, app.py | lookup_options | — |
| Storage (R2) | — | `core/storage.py` | (files) | [deploy](DEPLOY.md) |
| Email | — | `email_utils.py` | email_templates | [feedback](sections/feedback.md) |
| Reg-number generator | — | `core/registration.py` | plab_clients, client_registrations | [operations](sections/operations.md) |

## Quick facts

- **App entry:** `app.py` (routes + all table DDL). Extracted modules: `routes/` (feedback,
  operations, verification), `college/`.
- **Templates:** `templates/*.html` (~404). Client-facing: `client_*`, `feedback_public`. Ops:
  `ops_*`. Section sidebars: `*_sidebar_base.html`.
- **Helpers:** `core/{auth,users,helpers,lookups,registration,storage}.py`, `db.py`, `email_utils.py`.
- **Deploy:** [DEPLOY.md](DEPLOY.md) — Render hooks, domains, env vars.

> **When an instruction comes in:** find the area here → open only those files. Most "add/change a
> field/section" tasks touch: a route in app.py or a `routes/` module, a template, a table
> `ensure_*`/`ALTER`, and (for gated sections) `ACCESS_ROUTE_MAP` + the sidebar.
