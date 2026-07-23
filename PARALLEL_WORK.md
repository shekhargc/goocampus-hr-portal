# Parallel Development — Coordination

Multiple Claude Code sessions work on this portal at once, each in its **own git
worktree + branch**. Read this before editing so sessions don't collide.

## The three sessions (settled 2026-07-21)
| Session | Repo / worktree | Branch | Owns | Deploys? |
|---|---|---|---|---|
| **1. Portal Dashboard (integrator)** | `goocampus-portal` (this main checkout) | `develop` / `main` | Core goocampus.org — `app.py`, `routes/**`, Sales/Ops/Clients/HR/Access-Master | **YES — the only session that merges to `develop`/`main` + pushes live** |
| **2. College + goocampus.in Admin Panel** | `../portal-pg-admin` | `feature/pg-admin-panel` | `college/**` (College Portal, Medical Predictor, NEET-PG PDFs) **+ the goocampus.in admin panel** (new module folder) + the `/api/pg/*` endpoints the .in user panel calls | No — commits to its branch; session 1 merges |
| **3. goocampus.in website + user panel** | separate repo `goocampus-pg` (Next.js) | its own | The public goocampus.in site **+ the doctor/user panel**. Talks to goocampus.org via `/api/pg/*` + the WhatsApp OTP. Its own Render service. | Deploys its own Next.js service |

**Architecture (settled 2026-07-21):** user-facing lives on **goocampus.in** (session 3);
the **data + admin + APIs** for goocampus.in live on **goocampus.org** (session 2 builds the
admin panel + APIs; the college module already holds NEET-PG PDFs/predictor/leads). No
separate Mongo backend — goocampus.org IS the backend for goocampus.in. The user panel
authenticates doctors with goocampus.org's WhatsApp OTP and reads/writes via `/api/pg/*`.

_(Old note: the `../portal-college` worktree on `feature/college-module` is superseded by
`../portal-pg-admin`; that branch is stale — don't build on it.)_

## Rules (keep merges painless)
1. **Stay in your stream's files.** The College session edits `college/**` (+ its
   own templates/static). Don't edit another stream's files or `app.py` routes
   that aren't yours.
2. **New code → new module files, not `app.py`.** `app.py` is the shared 37k-line
   monolith — piling into it causes merge conflicts. Put new features in
   `routes/<area>.py` or your own module folder (like `college/`).
3. **One DB migration at a time.** All sessions share ONE database + R2 bucket
   (staging and live both point at it). Coordinate any schema change (new
   column/table) — ideally funnel migrations through one "lead" session. Be
   careful with data writes: it's the live DB.
4. **Merge daily.** Short-lived branches barely conflict; week-old ones fight.
   Flow: your branch → `develop` → test on staging → `main` (live).
5. **Don't do big work directly on `develop`/`main`.** Branch first.
6. **Only the integrator session merges to `develop`/`main`.** Feature sessions
   (College, etc.) **commit to their own branch and stop there** — do NOT push to
   `develop` or `main` yourself. One designated "integrator" session pulls each
   feature branch into `develop` → staging → `main`. This serializes deploys and
   prevents two sessions racing on `develop`. When your work is committed and
   ready, tell the user; the integrator does the merge.

## The College module — `college/` (self-contained)
```
college/
├── __init__.py              register_college(app)  — wired once in app.py
├── routes/
│   ├── portal.py            /colleges + admin CRUD
│   ├── predictor.py         /medical-predictor + /api/predictor/*
│   ├── neetpg.py            /neet-pg-2025/* + /admin/neetpg-*
│   └── partner.py           /partner/colleges, /partner/medical-predictor
├── data/tables.py           college tables + seed/import (runs at boot)
├── utils.py                 currency conversion + slug helpers
├── templates/college/       6 templates, rendered as 'college/<name>.html'
└── static/college/          college-only assets
```
- **Endpoint names + URLs are unchanged** — `url_for('colleges_list')` etc. still work.
- `app.py` now contains only one college line: `from college import register_college; register_college(app)`.
- Shared `get_partner_visible_sections` stays in `app.py` (other partner routes use
  it); `college/routes/partner.py` calls it via a lazy import — no circular import.

## Validation status (feature/college-module)
- ✅ All files compile; `register_college` registers all **39** routes cleanly; module imports clean; no orphan refs in `app.py`.
- ⏳ Full end-to-end boot validates on the **staging deploy** (local boot is unreliable against the remote DB).
