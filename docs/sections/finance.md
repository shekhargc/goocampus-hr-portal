# Finance

Budget planning, expense/revenue tracking, product economics, salaries & subscriptions.
All in `app.py`. **FY = April–March** (default `fy='2026-2027'`, hardcoded — update yearly).
Multi-currency with live INR conversion.

---

## Building blocks

```mermaid
flowchart TD
    PRJ[Projects] --> RS[Revenue Streams<br/>global, not per-project]
    RS --> PRD[Products & Services<br/>cost · sale_price · currencies · pathway]
    PRD -->|sync| RCAT[Revenue budget categories<br/>auto-mirrored from streams]
    SAL[Salary Items<br/>per employee] --> SALCAT["Salaries & Wages" category]
    SUB[Subscription Items<br/>vendor · frequency] --> SUBCAT["Software Subscription" category]
    ECAT[Expense Categories] --> BE[(budget_entries<br/>category|salary|subscription|product<br/>× month × budget/actual)]
    RCAT & SALCAT & SUBCAT & ECAT --> BE
    BE --> DASH[Dashboard · Expenses · Revenue · Project P&L · Reports]
```

## Core data model

| Table | Role |
|---|---|
| `projects` | business initiatives (name, description, status) |
| `revenue_streams` | revenue channels — **global** (legacy `project_id` nulled) |
| `products_services` | sellable items: `product_cost`, `sale_price`, `cost_currency`, `sale_currency`, `project_id`, `revenue_stream_id`, `pathway` |
| `budget_categories` | `cat_type` = expense / revenue (auto from streams) / department; `is_recurring`, `stream_id` |
| `salary_items` | per-employee salary (`monthly_cost`, `currency`, `department`, `project_id`) |
| `subscription_items` | recurring vendor cost (`cost`, `frequency`, `primary_department`) |
| `budget_entries` | **the atomic table:** exactly one of `category_id`/`salary_id`/`subscription_id`/`product_id` set, per `(fy_year, month, year)`; `budget_amount`, `actual_amount`, `budget_units`, `actual_units`, `is_locked` |

## Key routes

| URL | What |
|---|---|
| `/finance/budget` | dashboard — monthly totals, department rollups, locked months |
| `/finance/budget/expenses` | expense grid (categories × months); salary/subscription auto-roll-up |
| `/finance/budget/revenue` | revenue grid (products × months, grouped by stream) |
| `/finance/budget/edit/<month>/<year>` | the entry form (expenses, salaries, subs, product revenue) |
| `/finance/budget/lock|unlock/<month>/<year>` | freeze/unfreeze a month |
| `/finance/budget/report` | full-FY report |
| `/finance/budget/projects` | per-project P&L (revenue − expense = net margin) |
| `/finance/budget/settings` | manage categories; **syncs revenue streams → categories** |
| `/finance/salaries`, `/finance/subscriptions` | masters (+ add/edit/delete/sync) |
| `/products`, `/products/add/<project_id>`, `/finance/products` | product catalogue + economics |
| `/projects`, `/projects/add`, `/projects/<id>` | projects |

## Formulas

- **Product margin (INR):** `to_inr(sale_price, sale_currency) − to_inr(product_cost, cost_currency)`.
- **Revenue line (units mode, if sale_price>0):** `amount = units × to_inr(sale_price, sale_currency)`.
- **Subscription monthly equivalent:** monthly=cost, quarterly=cost/3, annual=cost/12, one_time=0.
- **Currency:** `to_inr(amount, currency)` (~L8058) uses `get_fx_rates_inr()` (open.er-api.com,
  **cached 6h**, hardcoded fallback). ~20 currencies. `/api/forex-rates` returns rates JSON.
- **FY quarters:** Q1 Apr–Jun, Q2 Jul–Sep, Q3 Oct–Dec, Q4 Jan–Mar (`get_fy_months`).

## Gotchas

- **Revenue categories are auto-synced from Sales streams** — a manually-created revenue category
  gets overwritten on next `/finance/budget/settings` load. Deleting a stream deletes its category
  (+ its budget_entries).
- **Salary/subscription auto-roll-up matches categories by name** (`"Salaries & Wages"`, `"Software
  Tool Subscription"`) — renaming those categories breaks the roll-up.
- **Locking is per-month, all-or-nothing.** No category-level lock.
- **`sale_price` change flips a product's entry mode** (units vs rupees) — old entries can orphan.
- **FY default hardcoded `'2026-2027'`** — needs a code update / year selector for FY 2027-28.
- Cost & revenue can be in **different currencies**; both convert to INR independently.
- **Company → Locations** (`/company/locations`) manages the `states`/`cities` master (CRM, not
  finance) — includes a "backfill" that harvests state/city combos from partners + plab_clients.
