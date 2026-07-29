# goocampus.in — Pricing, Entitlements & Coupons API

For the session building the goocampus.in site/dashboard. All endpoints are on the
portal (goocampus.org) and guarded by the **X-PG-Key** header (same handshake as the
mentor/PDF/OTP APIs). Endpoints that concern a specific doctor also need that
doctor's **login token** (issued by `/api/pg/otp/verify`) — send it as
`X-PG-User-Token`. No token = treated as a logged-out free visitor (never an error).

## The model in one paragraph
A **plan** (Free or paid) grants a set of **features**. A feature is either an on/off
switch (e.g. "PDF library") or a capped number (e.g. "PDF documents = 3",
"Predictor states = 1"). The admin configures all of this — the site never hard-codes
a limit. The **free plan** is what a logged-in doctor gets with no purchase. Free
users can still book+pay a mentor individually (that's a feature flag, kept ON on Free).

## Endpoints

### `GET /api/pg/plans`  — the pricing cards
Returns active + public plans as the founder designed them (name, tagline, price,
`compare_at_price` for the struck-through "was", `badge_text`/`badge_color` for the
Bestseller ribbon, `accent_color`, `highlights[]`, `cta_label`, `is_featured`) plus a
`features[]` list per plan: `{code, name, unit, included, value, note}` where `value`
is a number, `"Unlimited"`, `"Included"`, or null.

### `GET /api/pg/entitlements`  (send X-PG-User-Token)
The logged-in doctor's plan + every feature with `{allowed, unit, limit, used,
remaining, unlimited, reason, note}`. One call drives the whole dashboard: what to
show, what to grey out, and "2 of 3 PDFs used" nudges. `reason` is a code you can map
to an upgrade prompt (`limit_reached`, `not_in_plan`, `login_required`, …).

### `POST /api/pg/entitlements/consume`  {feature, item_key?}  (send X-PG-User-Token)
**Call this the instant a doctor opens a gated thing** (before streaming a PDF, before
revealing a new state). It re-checks server-side and records usage.
- `200 {allowed:true, info}` → proceed.
- `402 {allowed:false, info}` → blocked; show the upgrade prompt using `info.reason`.
- `401 {reason:"login_required"}` → send them to login.
`item_key` matters for "distinct item" features (PDFs, states): pass the PDF id / state
name. **Re-opening something already unlocked never costs another slot** — so it's safe
to call every open. Non-distinct features (searches) just decrement.

Suggested feature codes to gate against (all live in the admin catalogue):
`predictor_access`, `predictor_states` (item_key = state name), `pdf_library`,
`pdf_documents` (item_key = pdf id), `mentor_directory`, `mentor_sessions`,
`mentor_paid_booking`.

### `POST /api/pg/coupons/validate`  {code, plan_id}
Prices a coupon for the checkout: `{ok, result:{discount, payable, amount, ...}}` or
`{ok:false, result:{error:"plain English"}}`. **Read-only** — it never burns a use.
Actual redemption happens server-side at payment success (built with the Razorpay step,
not yet wired). Works logged-out, so the pricing page can preview a code.

## Not built yet (needs founder input / Razorpay)
- Razorpay checkout + the redemption call that burns a coupon and starts a paid
  subscription. The discount maths and the `pg_coupon_redemptions` ledger are ready;
  only "take the money" is missing.
