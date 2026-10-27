"""One-off announcement emails to FREE goocampus.in users (founder 2026-10-24: "MCC Round 1 final result is
out"; 2026-10-26: not to paid / internal / team). Branded like the news alerts (news_email.py), with fixed
founder-approved wording. Generic on purpose: no doctor's allotment is quoted (a stale profile rank would announce the
wrong seat).

Safety: a test goes to ONE address; the full send needs an explicit confirm word, runs in a background
thread (throttled for Resend), and records every address it sent to in pg_announcement_sends, so a second
"send to all" can never email anyone twice.
"""
import logging
import threading
import time
from html import escape

from db import get_db

logger = logging.getLogger(__name__)

ANNOUNCEMENTS = {
    'mcc_r1_final_2026': {
        'subject': 'MCC NEET PG Round 1 final result is out — check your allotment',
        'title': 'MCC NEET PG 2026 — Round 1 final result is out',
        'preheader': 'Check your Round 1 allotment and plan Round 2 with the 2025 vs 2026 closing ranks.',
        'lead': 'MCC has published the NEET PG 2026 Round 1 <b>final</b> seat allotment (24 Oct 2026).',
        'links': [
            ('Check your result', 'https://goocampus.in/dashboard/results'),
            ('Plan Round 2: see how closing ranks compare with 2025', 'https://goocampus.in/dashboard/round-analysis'),
            ('Not logged in? Check by rank', 'https://goocampus.in/neet-pg-mcc-round-1-result-2026'),
            ('Official MCC result (PDF)',
             'https://cdnbbsr.s3waas.gov.in/s3e0f7a4d0ef9b84b83b693bbf3feb8e6e/uploads/2026/10/202610241746468472.pdf'),
        ],
        'button': ('Check your Round 1 result →', 'https://goocampus.in/dashboard/results'),
        'note': 'For final confirmation, always check your allotment in the official MCC PDF or on mcc.nic.in '
                'before you act.',
    },
}


def ensure_table(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_announcement_sends (
        id SERIAL PRIMARY KEY,
        announcement TEXT NOT NULL,
        email TEXT NOT NULL,
        ok INTEGER DEFAULT 0,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pg_announcement_sends ON pg_announcement_sends (announcement, email)")


def build_html(key, name=''):
    from email_utils import render_branded_email, brand_button, brand_callout
    from pg_admin.news_email import _dr_name
    a = ANNOUNCEMENTS[key]
    dr = _dr_name(name) if (name or '').strip() else ''
    greeting = f"Dear {escape(dr)}," if dr else "Dear Doctor,"
    links = ''.join(
        f'<li style="margin:6px 0;"><a href="{u}" style="color:#ea580c;font-weight:700;text-decoration:none;">'
        f'{escape(t)}</a></li>' for t, u in a['links'])
    inner = (
        f'<p style="margin:0 0 10px;color:#0f172a;font-size:15px;">{greeting}</p>'
        f'<p style="margin:0 0 12px;color:#0f172a;font-size:16px;line-height:1.55;">{a["lead"]}</p>'
        f'<ul style="margin:0 0 14px;padding-left:20px;color:#334155;font-size:15px;line-height:1.6;">{links}</ul>'
        + brand_button(*a['button'])
        + brand_callout(escape(a['note']), color="#FFF7ED", border="#FED7AA", tcolor="#9A3412")
        + '<p style="margin:16px 0 0;color:#334155;font-size:14px;">— Team GooCampus</p>')
    return render_branded_email(a['title'], inner, preheader=a['preheader'])


def recipients(conn, counts=None):
    """FREE registered doctors only (founder 2026-10-26): never paid plans (any active paid / counselling plan),
    internal clients, team members, Counselling Desk accounts or staff. One email per address."""
    from pg_admin.data.entitlements import full_news_access
    rows = conn.execute(
        "SELECT u.id, u.name, LOWER(TRIM(COALESCE(u.email,''))) AS email, "
        "  EXISTS (SELECT 1 FROM pg_subscriptions s JOIN pg_plans p ON p.id = s.plan_id "
        "          WHERE s.user_id = u.id AND s.status = 'active' AND p.plan_kind IN ('paid','counselling') "
        "          AND (s.expires_at IS NULL OR s.expires_at > CURRENT_TIMESTAMP)) AS has_plan "
        "FROM pg_users u ORDER BY u.id").fetchall()
    staff = {r['email'] for r in conn.execute(
        "SELECT LOWER(TRIM(email)) AS email FROM employees WHERE COALESCE(email,'') <> ''").fetchall()}
    seen, out = set(), []
    c = {'registered': len(rows), 'no_email': 0, 'paid_internal_team': 0, 'staff_email': 0, 'duplicate_email': 0}
    for r in rows:
        em = r['email']
        if not em or '@' not in em:
            c['no_email'] += 1; continue
        if r['has_plan'] or full_news_access(conn, r['id']):
            c['paid_internal_team'] += 1; continue
        if em in staff:
            c['staff_email'] += 1; continue
        if em in seen:
            c['duplicate_email'] += 1; continue
        seen.add(em)
        out.append({'email': em, 'name': r['name'] or ''})
    c['free_to_email'] = len(out)
    if counts is not None:
        counts.update(c)
    return out


def send_test(key, to):
    from email_utils import send_email
    a = ANNOUNCEMENTS[key]
    return bool(send_email([to], '[TEST] ' + a['subject'], build_html(key, 'Test Doctor')))


def _send_all(key):
    from email_utils import send_email
    a = ANNOUNCEMENTS[key]
    conn = get_db()
    try:
        ensure_table(conn)
        done = {r['email'] for r in conn.execute(
            "SELECT email FROM pg_announcement_sends WHERE announcement=?", [key]).fetchall()}
        todo = [r for r in recipients(conn) if r['email'] not in done]
        conn.commit()
        logger.info("announcement %s → %s recipient(s)", key, len(todo))
        from pg_admin import email_tracking as ET
        for r in todo:
            ok = 0
            try:
                html, tok = ET.wrap(conn, build_html(key, r['name']), kind='announcement', email=r['email'],
                                    subject=a['subject'], ref_label=key)
                ok = 1 if send_email([r['email']], a['subject'], html) else 0
                ET.mark_sent(conn, tok, ok)
            except Exception as e:
                logger.error("announcement %s: %s failed: %s", key, r['email'], e)
            conn.execute("INSERT INTO pg_announcement_sends (announcement, email, ok) VALUES (?,?,?) "
                         "ON CONFLICT (announcement, email) DO NOTHING", [key, r['email'], ok])
            conn.commit()
            time.sleep(0.4)          # Resend: 2 requests / second
        logger.info("announcement %s done", key)
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("announcement %s: %s", key, e)
    finally:
        conn.close()


def start_send_all(key):
    threading.Thread(target=_send_all, args=(key,), daemon=True).start()


def status(key):
    conn = get_db()
    try:
        ensure_table(conn)
        conn.commit()
        r = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(ok),0) AS ok FROM pg_announcement_sends "
                         "WHERE announcement=?", [key]).fetchone()
        counts = {}
        n = len(recipients(conn, counts))
        return {'recipients': n, 'breakdown': counts, 'sent': int(r['ok'] or 0),
                'failed': int(r['n'] or 0) - int(r['ok'] or 0)}
    finally:
        conn.close()
