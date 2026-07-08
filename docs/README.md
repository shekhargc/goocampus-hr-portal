# GooCampus Portal — Documentation

Full documentation of the GooCampus internal + client portal (`goocampus.org`). Written so that
**any developer can understand and run the project even without the Claude account**, and so future
work can jump straight to the right code.

## Start here

1. **[ARCHITECTURE.md](ARCHITECTURE.md)** — what the app is, tech stack, the core business flow, code
   layout, and the cross-cutting conventions/gotchas. **Read this first.**
2. **[MAP.md](MAP.md)** — "where does X live": every area → its routes, files, and tables. Use this
   to navigate without reading the whole 39k-line `app.py`.
3. **[DATA-MODEL.md](DATA-MODEL.md)** — the ~150 tables that matter and how they relate.
4. **[DEPLOY.md](DEPLOY.md)** — Render services, deploy hooks, domains, env vars, the web shell, and
   a recovery checklist.

## Section deep-dives (`sections/`)

| Doc | Covers |
|---|---|
| [sales.md](sections/sales.md) | Leads, closures, the client-invitation spine, targets, revenue report |
| [operations.md](sections/operations.md) | 6 pathways, client delivery, ops_* sub-sections, verification queues |
| [client-portal-registration.md](sections/client-portal-registration.md) | Invite → register → form (phone/academic cascade) → docs → verify |
| [feedback.md](sections/feedback.md) | Stage-wise feedback + WhatsApp/email + delivery report |
| [packages-products.md](sections/packages-products.md) | Product catalogue + per-plan packages/services |
| [hr-leave-attendance.md](sections/hr-leave-attendance.md) | Leave, attendance, WFH, travel, employees, KRA |
| [finance.md](sections/finance.md) | Budget, revenue streams, product economics, salaries, subscriptions |
| [access-permissions.md](sections/access-permissions.md) | Login, roles, **Access Master** (the security backbone), navigation |
| [partners-college.md](sections/partners-college.md) | Partner portal + College module (predictor, NEET-PG) |

## One-paragraph summary

A **Flask + PostgreSQL** server-rendered app (no SPA, no ORM, no build step). One big `app.py`
(~39k lines) holds most routes and all table DDL; sections are being extracted into `routes/`
modules (Operations, Feedback) and a `college/` folder. Tables self-create/migrate at boot via
`ensure_*`/`seed_*` functions. It runs on **Render** (live = `main`, staging = `develop`, shared
Postgres) at **`goocampus.org`**. The spine of the business: **sales closes a lead → the client
gets an invite → registers and fills a form → sales + ops verify → a `plab_clients` master record
is created → operations delivers the pathway → feedback measures the experience.**

_Docs generated 2026-07-09. Keep them updated when a section changes materially._
