# Deployment & Infrastructure Runbook

Everything you need to deploy, host, and operate the GooCampus portal — and to
recover if the Claude account is unavailable.

---

## Render services (shared PostgreSQL)

| Env | Service name | Service ID | Branch | URL |
|---|---|---|---|---|
| **Live** | `goocampus-hr-portal` | `srv-d7732b3uibrs73a4fj60` | `main` | https://goocampus.org · https://goocampus-hr-portal.onrender.com |
| **Staging** | `goocampus-hr-portal-staging` | `srv-d8bd6t4m0tmc73desvb0` | `develop` | (onrender staging URL) |

Both services share **one PostgreSQL database** (so a data change on staging affects live).
Python 3 web services, region Oregon.

## Domains

- **`goocampus.org`** = the portal (client login `goocampus.org/client/login`,
  registration invites, feedback `goocampus.org/feedback/<token>`, staff portal). Render
  custom domain, verified + SSL. `www.goocampus.org` redirects to it.
- **`goocampus.in`** = a **different site** (NEET Rank Predictor / marketing). It answers
  `200` on every path with its own page — it does **NOT** serve the portal. Never put
  portal/client/feedback links on goocampus.in.
- DNS is managed on **DigitalOcean**.

---

## Deploying

The app deploys on push to the branch, **but Render's GitHub auto-deploy webhook is
unreliable** — after pushing, trigger the deploy hook explicitly.

**Deploy hooks (secret — keep out of public places):**
```bash
# Live
curl -s "https://api.render.com/deploy/srv-d7732b3uibrs73a4fj60?key=IrV9QAOLPL8"
# Staging
curl -s "https://api.render.com/deploy/srv-d8bd6t4m0tmc73desvb0?key=u3dXuSo9SUc"
```
A deploy takes ~3–5 min (build + boot runs all `ensure_*` table migrations). Keys can be
rotated in Render → service → Settings → "Regenerate hook".

### Standard flow: develop → live
`main` and `develop` have divergent SHAs but near-identical content. To promote a change:
```bash
git checkout develop && git add <files> && git commit -m "…" && git push origin develop
curl -s "…staging hook…"                       # deploy staging

git fetch origin -q
git checkout main && git reset --hard origin/main -q
git checkout origin/develop -- <the same files>  # bring just those files to live
git commit -m "Promote to live: …" && git push origin main
git diff --stat main origin/develop              # should be empty = content parity
curl -s "…live hook…"                            # deploy live
git checkout develop
```
Verify a deploy landed by curling a route that only exists in the new code (a `404`→`302`
or `404`→`200` transition), or checking response headers.

---

## Environment variables (set in Render → service → Environment)

| Var | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection (Render-managed) |
| `RESEND_API_KEY` | Email (Resend, Pro account "Samvaya", from `info@goocampus.in`) |
| `INFOBIP_API_KEY` | WhatsApp (Infobip) |
| `INFOBIP_BASE_URL` | e.g. `yp9l99.api.infobip.com` |
| `INFOBIP_SENDER` | WhatsApp sender, default `15558246314` (GooCampus dedicated) |
| `INFOBIP_DLR_URL` | delivery-report webhook (default `https://goocampus.org/webhooks/infobip/dlr`) |
| R2 (Cloudflare) creds (×5) | contract/document storage — access key, secret, account id, bucket, endpoint |

> **Live vs staging env can drift.** Live was once missing all 5 R2 creds (contracts
> wouldn't load). If storage/email/WhatsApp misbehaves on one env, compare env vars.
> **Never paste secrets into code or chat** — set them directly in the Render dashboard.

---

## Render web shell (live DB access)

Render → service → **Shell** opens a terminal *inside* the running service, with all env
vars set — so `from db import get_db` works with the live DB and no secret handling.

```bash
python3 <<'PY'
from db import get_db
c = get_db()
print(c.execute("SELECT COUNT(*) AS n FROM plab_clients").fetchone()['n'])
PY
```
Used for one-off inspections, data fixes, and reproducing route 500s
(`app.test_request_context()` + set `session`). During a deploy the shell may drop and
reconnect to a new instance — reload the Shell page.

---

## Recovery checklist (if starting fresh / Claude unavailable)

1. Clone the repo. Live = branch `main`, staging = branch `develop`.
2. Render already hosts both services from GitHub — pushes + the deploy hooks above deploy.
3. All tables self-create on boot (`ensure_*` in `app.py`) — a fresh DB will scaffold itself,
   but **production data lives only in the Render Postgres** (back it up via Render).
4. Set the env vars above (secrets from Resend / Infobip / Cloudflare dashboards).
5. `docs/` (this folder) + `MEMORY.md`-style notes are the human reference.
