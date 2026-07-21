# Session: College Module + goocampus.in Admin Panel

**Read this first, then `CLAUDE.md`, `PARALLEL_WORK.md`, and `docs/MAP.md`.**
You are one of three coordinated Claude Code sessions. This is the settled split
(2026-07-21):

| Session | Owns | Deploys |
|---|---|---|
| **Portal Dashboard (integrator)** | Core goocampus.org (`app.py`, `routes/**`, Sales/Ops/Clients/HR/Access Master) | **The only one that merges to `develop`/`main` + pushes live** |
| **← YOU: College + goocampus.in Admin** | `college/**` + a new goocampus.in **admin panel** module + the `/api/pg/*` endpoints | No — you commit to your branch; the integrator merges |
| **goocampus.in website + user panel** | The Next.js `goocampus-pg` repo — public site + **doctor/user panel** | Its own Render service |

## Your scope
1. **College module** (`college/`) — already live: College Portal, Medical Predictor,
   NEET-PG PDF library, leads. Improve/extend here.
2. **The goocampus.in ADMIN panel** (new) — internal screens (in goocampus.org, for GooCampus
   staff) that control goocampus.in: manage NEET-PG PDFs, predictor data, content, and the
   leads/doctors coming from the site. Much of this already exists in `college/routes/neetpg.py`
   — extend it; don't rebuild.
3. **The `/api/pg/*` API layer** — goocampus.org is the BACKEND for goocampus.in. The user
   panel (session 3) calls these. `POST /api/pg/lead` already exists. Add new endpoints here
   as session 3 needs them (e.g. predictor data, PDF list, doctor auth/session), each guarded
   by the `X-PG-Key == env PG_API_KEY` handshake.

## Architecture you're implementing
- **User-facing = goocampus.in** (session 3, Next.js). **Data + admin + APIs = goocampus.org**
  (you). **No separate Mongo backend** — goocampus.org is the single backend.
- Doctor login on goocampus.in uses **goocampus.org's WhatsApp OTP**. A reusable helper already
  exists: `_send_whatsapp_otp(mobile10, otp)` in `app.py` (Infobip; env `INFOBIP_API_KEY` +
  `INFOBIP_BASE_URL`, both live). Expose OTP send/verify as `/api/pg/*` endpoints for the user panel.

## Boundaries (keep merges painless)
- **Stay in `college/**` and your new admin-panel module folder.** Do NOT edit core `app.py`
  routes that aren't yours; the Portal Dashboard session owns `app.py`. If you must touch
  `app.py` (e.g. one `register_*(app)` line, or a new `/api/pg/*` route that can't live in a
  module yet), keep it to the smallest possible addition and flag it for the integrator.
- **New code → new module files**, not the 40k-line `app.py`. Mirror the `college/` layout.
- **Shared DB + R2** across all sessions (staging + live point at the SAME DB). Coordinate any
  schema change; never backfill/modify existing production data — read what's there first.
- **You do NOT push to `develop`/`main`.** Commit to `feature/pg-admin-panel`, then tell the
  user; the Portal Dashboard session merges → staging → live.

## Deploy (handled by the integrator, for reference)
Live `goocampus-hr-portal` (`main`) · Staging `goocampus-hr-portal-staging` (`develop`).
Both share ONE DB. Auto-deploy is flaky — the integrator curls the Render hook after each push.

## Start here
1. Read `docs/MAP.md` → the College section, and `college/routes/neetpg.py`.
2. Read `goocampus-pg/API_CONTRACT.md` (the other repo) — the live contract with session 3.
3. Ask the user what the first admin-panel screen should be, or which `/api/pg/*` endpoint
   session 3 needs next.

---

## Reference: the already-built admin dashboard (replicate these)

An earlier, working admin dashboard exists (React + Material-UI) in the OTHER repo:
`goocampus-pg/goocampus-rank-predictor-main/frontend/src/pages/Admin/` (backend in
`.../backend/modules/admin/`). **Get read access with** `/add-dir ~/Desktop/Claude Code/goocampus-pg`.
**Reference ONLY** — study the screens (fields, filters, actions) and rebuild them as
Flask/Jinja pages here. Do NOT connect to, deploy, or modify the old system.

### Build first — new + core to goocampus.in (in this order)
1. **DoctorManagement** — list/search/manage doctor (user) accounts.
2. **BookingManagement** — manage counselling-call bookings (status + admin notes).
3. **UserManagement** — users + roles (pairs with DoctorManagement).

### Build when paid plans go live (Razorpay phase) — replicate as a set
**PlanManagement · SubscriptionManagement · PaymentConfiguration · CouponManagement.**

### Reuse the LAYOUT but wire to what already exists (don't build a 2nd data layer)
- **CollegeManagement** → the existing `college/` module (college directory).
- **ExamManagement** → existing NEET-PG PDFs + Medical Predictor (`college/routes/neetpg.py`, predictor).
- **InstitutionInquiries** → existing partner / B2B leads in the portal.

### SKIP — old 12thplus/UG platform, out of scope for goocampus.in
EducationLoan, IncomingNews, NewsSources, RejectedItems, AIUsage, CareerManagement,
CollegeApplication, InternationalPathways.

### Decide early with the founder
**Where do doctor accounts + bookings live?** goocampus.org is now the backend, so they'd
be NEW tables in the portal DB, exposed to goocampus.in via `/api/pg/*`. Propose the data
model (tables + endpoints) and confirm with the founder before building.
