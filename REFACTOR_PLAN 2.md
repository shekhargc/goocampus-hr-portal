# GooCampus Portal — Refactor Plan

**Goal:** Break the 28,829-line `app.py` (449 routes) into per-section files (Flask Blueprints) so multiple Claude agents can work on different sections in parallel without merge conflicts.

**Guiding rule:** This refactor changes NOTHING the user sees. Same URLs. Same pages. Same database. Same login. Only the *code organization* changes.

---

## Current state (what's in app.py today)

| Section URL prefix | Routes | Goes to |
|---|---:|---|
| `/operations/*` | 130 | Operations (has 20+ sub-areas: PLAB, onboarding, GMC, EPIC, coaching, vendors, etc.) |
| `/admin/*` | 54 | Split between HR (employees, leave, holidays, reports) and Clients (admin/clients, client-form-config) |
| `/api/*` | 32 | Shared API endpoints — split per section |
| `/finance/*` | 24 | Finance |
| `/sales/*` | 19 | Sales |
| `/whatsapp/*` | 18 | WhatsApp |
| `/partner/*` + `/partners/*` + `/b2b/*` | 36 | Partners |
| `/kra/*` | 12 | KRA |
| `/colleges/*` | 11 | Colleges |
| `/client/*` + admin client routes | ~14 | Clients |
| `/company/*` + country pages (Germany, Russia, Vietnam, etc.) | ~30 | Company / Marketing |
| `/dashboard`, `/login`, `/logout`, `/profile`, etc. | ~15 | Dashboard / Auth |
| Other utility routes (reports, projects, products, streams, wfh, etc.) | ~50 | Distribute by purpose |

---

## Proposed folder structure (after refactor)

```
goocampus-portal/
├── app.py                  ← shrinks to ~200 lines: app factory, register blueprints
├── core/
│   ├── __init__.py
│   ├── auth.py             ← login_required, admin_required, partner/client auth decorators
│   ├── db.py               ← (already exists, stays)
│   ├── email_utils.py      ← (already exists, stays)
│   ├── filters.py          ← Jinja filters (format_date, format_reg)
│   ├── helpers.py          ← hash_password, allowed_file, get_user, etc.
│   ├── leave_calc.py       ← calculate_monthly_balance, get_available_balance, holidays
│   └── notifications.py    ← _notify_* internal helpers
├── routes/
│   ├── __init__.py
│   ├── dashboard.py        ← /, /dashboard, /login, /logout, /profile, /change-password, /forgot-password, /reset-password
│   ├── hr.py               ← /admin/employee*, /admin/holidays, /admin/leave-*, /admin/reports/*, /apply-leave, /wfh/*, /my-leave-report
│   ├── kra.py              ← /kra/*
│   ├── sales.py            ← /sales/*, /projects/*, /products/*, /streams/*
│   ├── finance.py          ← /finance/*
│   ├── operations/         ← split because it's huge (130 routes)
│   │   ├── __init__.py     ← parent blueprint
│   │   ├── plab.py
│   │   ├── onboarding.py
│   │   ├── gmc_epic.py
│   │   ├── coaching.py
│   │   ├── visa_travel.py
│   │   ├── call_notes.py
│   │   ├── webinars.py
│   │   ├── vendors.py
│   │   ├── test_bookings.py
│   │   ├── field_manager.py
│   │   └── misc.py
│   ├── partners.py         ← /partner/*, /partners/*, /b2b/*, /germany-pathway-webinar/*
│   ├── colleges.py         ← /colleges/*
│   ├── company.py          ← /company/*, country pages (germanypathway, vietnam, russia, etc.)
│   ├── whatsapp.py         ← /whatsapp/*
│   ├── clients.py          ← /client/*, /admin/clients, /admin/client-form-config, /admin/client-invitations
│   └── api.py              ← /api/* (or split per section later)
├── templates/              ← unchanged — Flask finds them globally
├── static/                 ← unchanged
├── db.py, email_utils.py   ← stay at root for now (already imported as modules)
├── seed_data.py, seed_prod.py, migrate_*.py  ← unchanged (admin scripts, not part of app)
└── render.yaml, requirements.txt, Procfile  ← unchanged
```

**After this, each section is in its OWN file.** Two agents working on `routes/hr.py` and `routes/finance.py` never touch the same file → no merge conflicts.

---

## Migration order (safest first, biggest last)

Each step pushes to `develop` (staging) and we verify staging still works before moving on. **If anything breaks, we revert one commit and stop.**

1. **Setup** — create `core/` and `routes/` folders, move helpers into `core/`. No routes moved yet. Verify app still boots locally + on staging.
2. **Dashboard / Auth** (~15 routes) — extract first because it's small and well-defined. If this works, the pattern is proven.
3. **KRA** (12 routes) — second-smallest, self-contained.
4. **Colleges** (11 routes) — small, self-contained.
5. **WhatsApp** (18 routes) — likely self-contained.
6. **Finance** (24 routes).
7. **Sales** (19 routes) + related (`/projects`, `/products`, `/streams`).
8. **HR** (~70 routes including `/admin/employee*`, leave mgmt, holidays, `/wfh/*`, reports).
9. **Clients** (~14 routes mixing `/client/*` and `/admin/clients`).
10. **Partners** (36 routes — partner login, partner dashboards, B2B, webinars).
11. **Company** (~30 routes — country pages, marketing).
12. **Operations** (130 routes) — last and largest. Split into sub-blueprints (`operations/plab.py`, `operations/onboarding.py`, etc.).
13. **API cleanup** — distribute `/api/*` routes into their owning section, or keep a thin `api.py` if shared.
14. **Final pass** — confirm `app.py` only contains the app factory + blueprint registration.

After each step we run the app locally and click through the affected section. After every 2-3 steps we push to `develop` and verify staging.

---

## Safety nets

- **Branch:** All work happens on `develop` (staging). `main` (production) stays untouched until the full refactor is verified.
- **Atomic commits:** One commit per section moved. Easy to revert one step if it breaks.
- **No behavior change:** Same routes, same templates, same DB. Any visible diff = a bug, revert.
- **Smoke test checklist:** Login → Dashboard → click into each section → click 2-3 things per section → log out. Done before every push.
- **Staging deploy verification:** After each push to `develop`, wait for Render to redeploy, then run smoke test on the staging URL.

---

## What happens after refactor (the payoff)

Once `app.py` only has app-factory code and each section has its own file:

1. **Parallel agents become safe.** Run 3-5 Claude agents at once, each in its own worktree, each editing a different `routes/*.py` file.
2. **Reviews get easier.** PRs touch one section, not 28k-line files.
3. **Onboarding new devs gets easier.** They can read one section without drowning.
4. **Testing per section becomes possible.** Write unit tests per blueprint without spinning up the whole monolith.

---

## What I need from you before starting

1. Approval of this plan (or push back on anything that doesn't match how you think about the portal).
2. Confirmation that **`develop` is your staging branch** and pushing there is safe to trigger a staging deploy.
3. (Optional) Render staging URL so I can check the deploy after pushes.
4. A go-ahead to start step 1 (folder setup).
