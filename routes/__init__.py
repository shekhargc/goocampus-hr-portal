"""
routes/ — one file per portal section (Flask Blueprints).

Planned blueprints (see REFACTOR_PLAN.md):
- dashboard.py    (auth, /, /dashboard, /profile)
- hr.py           (leave management, employees, holidays, wfh)
- kra.py          (/kra/*)
- sales.py        (/sales/*, projects, products, streams)
- finance.py      (/finance/*)
- operations/     (sub-folder — 130 routes split into PLAB, onboarding, GMC, EPIC, etc.)
- partners.py     (/partner/*, /partners/*, /b2b/*)
- colleges.py     (/colleges/*)
- company.py      (/company/*, country marketing pages)
- whatsapp.py     (/whatsapp/*)
- clients.py      (/client/*, /admin/clients, client-form-config)
- api.py          (/api/* — eventually distributed per-section)

Currently empty — routes will be migrated from app.py in subsequent steps.
"""
