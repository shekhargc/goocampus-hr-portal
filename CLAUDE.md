# GooCampus Portal — project brief for Claude

**Read `docs/MAP.md` FIRST** to find the code for any area, instead of scanning the
~39k-line `app.py`. Full documentation lives in **`docs/`**:

- `docs/README.md` — index
- `docs/ARCHITECTURE.md` — stack, the core business flow, code layout, conventions
- `docs/MAP.md` — section → routes / files / tables (the navigation index)
- `docs/DATA-MODEL.md` — the ~150 tables + relationships
- `docs/DEPLOY.md` — Render services, deploy hooks, domains, env vars, recovery
- `docs/sections/*.md` — deep dives per section (with Mermaid flowcharts)

## What this is
A **Flask + PostgreSQL** server-rendered portal (no SPA, no ORM, no build step) for
GooCampus. One big `app.py` holds most routes + all table DDL; sections are being
extracted into `routes/` modules and a `college/` folder. Tables self-create/migrate at
boot via `ensure_*` / `seed_*` functions. Runs on Render at **`goocampus.org`**.

**Business spine:** sales closes a lead → client gets an invite → registers + fills a form
→ sales + ops verify → a `plab_clients` master record is created → operations delivers one
of 6 pathways → feedback measures the experience.

## Working conventions (do these)
- **Deploy:** develop → staging, then promote the same files to `main` for live; trigger
  the Render deploy hook after push (auto-deploy is flaky). See `docs/DEPLOY.md`.
- **Domain:** all client/portal/feedback links use **`goocampus.org`** — NOT `goocampus.in`
  (that's a separate marketing site).
- **DB:** rows are dicts (`row['col']`, RealDictCursor). A literal `%` in SQL collides with
  param substitution → escape `%%` or bind as `?`. Swallowed query errors need
  `conn.rollback()` or the whole request's transaction aborts.
- **Timezone:** store UTC, display IST (UTC+5:30). **GST** = 18% (packages ex-GST, installments
  incl-GST split ÷1.18). **FY** = April→March.
- **Text date columns** (`ops_call_notes.call_date`, `plab_clients.registration_date`) — don't
  order/compare as dates; use `created_at`/`id`.
- **Access Master:** admins bypass all permission checks, so a missing grant is invisible to an
  admin but breaks for normal staff — test permission changes as a non-admin, and wire ALL
  factors (catalogue, route map, sidebar, dashboard card, lookups). See
  `docs/sections/access-permissions.md`.
- **Founder is non-technical** — prefer plain explanations; confirm before destructive DB ops;
  never enter secrets (API keys/passwords) into fields — the founder pastes those.

## Commit trailer
End commit messages with:
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
