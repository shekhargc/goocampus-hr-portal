"""Email alert blast when a NEET-PG news item is posted to the dashboard (founder 2026-10-06).

When the founder posts a news item (and ticks "email this update"), every registered
doctor on goocampus.in gets a branded email with a glimpse of the news + a CTA to log in
and read / download the attached document. Free users (no active plan) also get a subtle
"upgrade to personalised counselling" banner; paid/complimentary users get just the update.

Access on the dashboard stays plan-gated — the email only teases + drives the login.

Sends run in a background daemon thread (one email per user, throttled to respect Resend's
2 req/sec cap), so posting news never blocks on the blast.
"""

import logging
import threading
import time
from datetime import datetime
from html import escape

from db import get_db

logger = logging.getLogger(__name__)

LOGIN_URL = "https://goocampus.in"
UPGRADE_URL = "https://goocampus.in"


def _fmt_date(v):
    """published_at → '06 Oct 2026' (best-effort; falls back to a trimmed string)."""
    if not v:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%d %b %Y")
    s = str(v)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 2].strip(), fmt).strftime("%d %b %Y")
        except Exception:
            continue
    return s[:10]


def _glimpse(body, limit=320):
    """A short plain-text teaser of the news body, HTML-escaped, newlines → <br>."""
    txt = (body or "").strip()
    if len(txt) > limit:
        cut = txt[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
        txt = cut + "…"
    return escape(txt).replace("\n", "<br>")


def _dr_name(name):
    """'Rahul Sharma' -> 'Dr. Rahul Sharma' (idempotent — won't double a 'Dr.' prefix).
    Returns '' for a blank/unusable name so the caller can fall back to a generic greeting."""
    n = (name or "").strip()
    if not n:
        return ""
    low = n.lower()
    if low.startswith("dr.") or low.startswith("dr "):
        return n
    return "Dr. " + n


def _authority_label(news):
    """Human authority/scope label for the news item."""
    lbl = (news.get("body_label") or "").strip()
    if lbl:
        return lbl
    scope = (news.get("scope") or "").strip()
    if scope == "state" and (news.get("state") or "").strip():
        return news["state"].strip()
    return "All India / MCC"


def build_news_email_html(news, is_free, name=""):
    """Branded HTML for one recipient. `is_free` adds the upgrade banner (free users, no name);
    paid/internal users are greeted by name ('Dear Dr. <name>,')."""
    from email_utils import render_branded_email, brand_button, brand_detail_rows, brand_callout

    # Greeting: paid/internal → by name (Dr. convention); free → generic, nameless.
    dr = "" if is_free else _dr_name(name)
    greeting = f"Dear {escape(dr)}," if dr else "Dear Doctor,"
    greet_block = (
        f'<p style="margin:0 0 10px;color:#0f172a;font-size:15px;">{greeting}</p>'
    )

    heading = escape((news.get("heading") or "NEET-PG Update").strip())
    authority = escape(_authority_label(news))
    has_doc = bool((news.get("pdf_name") or "").strip())
    source_url = (news.get("source_url") or "").strip()

    # Show only the authority — NOT the published date, which users can mistake for a
    # counselling date. (founder 2026-10-06)
    details = brand_detail_rows([("Authority", authority)])

    glimpse = _glimpse(news.get("body_text"))
    body_block = (
        f'<p style="margin:14px 0 4px;color:#0f172a;font-size:15px;line-height:1.65;">{glimpse}</p>'
        if glimpse else ""
    )

    doc_note = ""
    if has_doc:
        doc_note = brand_callout(
            "📄 A document is attached to this update — log in to view and download it.",
            color="#FFF7ED", border="#FED7AA", tcolor="#9A3412")

    cta = brand_button("Log in to read the full update →", LOGIN_URL)
    access_note = (
        '<p style="margin:14px 0 0;color:#64748b;font-size:13px;line-height:1.6;text-align:center;">'
        'Open your GooCampus dashboard to see this and all your counselling updates. '
        'What you can access depends on your plan.</p>'
    )

    upgrade = ""
    if is_free:
        upgrade = (
            '<div style="margin:24px 0 4px;background:linear-gradient(135deg,#fff5eb,#fef3e6);'
            'border:1px solid #fed7aa;border-radius:10px;padding:16px 18px;">'
            '<p style="margin:0 0 6px;color:#9a3412;font-weight:700;font-size:14px;">'
            '⭐ Get your best college for your NEET-PG 2026</p>'
            '<p style="margin:0 0 10px;color:#7c2d12;font-size:13px;line-height:1.6;">'
            'Upgrade to GooCampus and get personalised NEET-PG counselling — expert, '
            'one-on-one guidance on choices, documents and strategy to land you the best '
            'possible college.</p>'
            f'<a href="{UPGRADE_URL}" style="color:#ea580c;font-weight:700;font-size:13px;'
            'text-decoration:none;">Explore counselling plans →</a>'
            '</div>'
        )

    inner = f"{greet_block}{details}{body_block}{doc_note}{cta}{access_note}{upgrade}"
    preheader = _glimpse(news.get("body_text"), 110) or heading
    return render_branded_email(f"📢 {heading}", inner, preheader=preheader)


def _recipients(conn):
    """Everyone who should get a news alert, de-duplicated by email:
    - Registered doctors (pg_users) — incl. team members now (founder 2026-10-06).
      'free' (gets the upgrade banner) = a NON-team doctor with NO active paid/counselling plan.
    - Internal staff (active employees) — always the clean update, greeted by name, no banner.
    Paid users, internal clients and staff all get the personalised update with no banner."""
    out, seen = [], set()
    try:
        rows = conn.execute(
            "SELECT u.id, u.name, LOWER(TRIM(u.email)) AS email, "
            "  COALESCE((to_jsonb(u)->>'is_team_member')::int, 0) AS is_team, "
            "  EXISTS (SELECT 1 FROM pg_subscriptions s JOIN pg_plans p ON p.id = s.plan_id "
            "          WHERE s.user_id = u.id AND s.status = 'active' "
            "          AND p.plan_kind IN ('paid','counselling') "
            "          AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP)) AS has_plan "
            "FROM pg_users u "
            "WHERE COALESCE(u.email,'') <> '' AND strpos(u.email, '@') > 0"
        ).fetchall()
        for r in rows:
            r = dict(r)
            em = (r.get("email") or "").strip()
            if not em or "@" not in em or em in seen:
                continue
            seen.add(em)
            is_free = (not r.get("is_team")) and (not r.get("has_plan"))
            out.append({"email": em, "name": r.get("name") or "", "is_free": is_free})
    except Exception as e:
        logger.error("news blast recipients (doctors): %s", e)
        try: conn.rollback()
        except Exception: pass
    # Internal staff / employees — the clean update, named, no upgrade banner.
    try:
        for r in conn.execute(
                "SELECT name, LOWER(TRIM(email)) AS email FROM employees "
                "WHERE is_active = 1 AND COALESCE(email,'') <> '' AND strpos(email, '@') > 0").fetchall():
            r = dict(r)
            em = (r.get("email") or "").strip()
            if not em or "@" not in em or em in seen:
                continue
            seen.add(em)
            out.append({"email": em, "name": r.get("name") or "", "is_free": False})
    except Exception as e:
        logger.error("news blast recipients (staff): %s", e)
        try: conn.rollback()
        except Exception: pass
    return out


def send_news_blast(news_id):
    """Load the news item + all recipients, send one branded email each (throttled).
    Opens its own DB connection — safe to run in a background thread."""
    try:
        from email_utils import send_email
    except Exception as e:
        logger.error("news blast: email_utils import failed: %s", e)
        return
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, scope, state, body_label, heading, body_text, source_url, pdf_name, "
            "is_published, published_at FROM pg_news WHERE id = ?", (news_id,)).fetchone()
        if not row:
            logger.error("news blast: news %s not found", news_id)
            return
        news = dict(row)
        if not news.get("is_published", True):
            logger.info("news blast: news %s is not published — skipping", news_id)
            return
        recips = _recipients(conn)
    except Exception as e:
        logger.error("news blast: load failed: %s", e)
        try: conn.rollback()
        except Exception: pass
        return
    finally:
        try: conn.close()
        except Exception: pass

    subject = f"📢 NEET-PG Update: {(news.get('heading') or '').strip()}"[:150]
    sent = failed = 0
    logger.info("news blast #%s → %s recipient(s)", news_id, len(recips))
    for r in recips:
        try:
            html = build_news_email_html(news, r["is_free"], r.get("name"))
            if send_email([r["email"]], subject, html):
                sent += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.error("news blast: send to %s failed: %s", r.get("email"), e)
        time.sleep(0.4)   # stay under Resend's 2 req/sec cap
    logger.info("news blast #%s done: %s sent, %s failed", news_id, sent, failed)


def trigger_news_blast(news_id):
    """Fire the blast in a background daemon thread so the request returns immediately.
    Returns the recipient count (quick pre-count) for the admin flash, or None."""
    try:
        t = threading.Thread(target=send_news_blast, args=(news_id,), daemon=True)
        t.start()
    except Exception as e:
        logger.error("news blast: could not start thread: %s", e)


def recipient_count():
    """Quick count of who a blast would reach (for the admin confirmation flash)."""
    conn = get_db()
    try:
        return len(_recipients(conn))
    except Exception:
        try: conn.rollback()
        except Exception: pass
        return None
    finally:
        try: conn.close()
        except Exception: pass


def recipients_breakdown(conn, check_email=''):
    """Diagnostic: how many people a blast reaches + the gaps. Returns a dict with the
    totals and (if check_email given) whether that address is in the recipient list."""
    recips = _recipients(conn)
    emails = {r['email'] for r in recips}
    out = {'total': len(recips),
           'free': sum(1 for r in recips if r['is_free']),
           'paid_or_staff': sum(1 for r in recips if not r['is_free'])}
    try:
        out['pg_users_total'] = conn.execute("SELECT COUNT(*) AS n FROM pg_users").fetchone()['n']
        out['pg_users_no_email'] = conn.execute(
            "SELECT COUNT(*) AS n FROM pg_users WHERE strpos(COALESCE(email,''), '@') = 0"
        ).fetchone()['n']
        out['pg_team'] = conn.execute(
            "SELECT COUNT(*) AS n FROM pg_users WHERE COALESCE((to_jsonb(pg_users)->>'is_team_member')::int,0)=1"
        ).fetchone()['n']
        out['pg_team_no_email'] = conn.execute(
            "SELECT COUNT(*) AS n FROM pg_users WHERE COALESCE((to_jsonb(pg_users)->>'is_team_member')::int,0)=1 "
            "AND strpos(COALESCE(email,''), '@') = 0"
        ).fetchone()['n']
        out['staff_with_email'] = conn.execute(
            "SELECT COUNT(*) AS n FROM employees WHERE is_active=1 AND strpos(COALESCE(email,''), '@') > 0"
        ).fetchone()['n']
    except Exception as e:
        logger.error("recipients_breakdown counts: %s", e)
        try: conn.rollback()
        except Exception: pass
    if check_email:
        ce = check_email.strip().lower()
        out['check_email'] = check_email
        out['check_in_list'] = ce in emails
    return out
