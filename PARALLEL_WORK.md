# Parallel Development — Coordination

Multiple Claude Code sessions work on this portal at once, each in its **own git
worktree + branch**. Read this before editing so sessions don't collide.

## Active work-streams
| Stream | Worktree folder | Branch | Owns these files |
|---|---|---|---|
| **College** | `../portal-college` | `feature/college-module` | `college/**` — College Portal, Medical Predictor, NEET-PG PDFs, partner college pages |
| _(add rows as you spin up more sessions: HR, Operations, etc.)_ | | | |

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
