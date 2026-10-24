"""One-off announcement emails to every goocampus.in user (founder 2026-10-24: "MCC Round 1 final result is
out"). Same recipients and branded design as the news alerts (news_email.py), but fixed founder-approved
wording. Generic on purpose: no doctor's allotment is quoted (a stale profile rank would announce the
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
        'preheader': 'Check your Round 1 allotment and the seats still open at your rank for Round 2.',
        'lead': 'MCC has published the NEET PG 2026 Round 1 <b>final</b> seat allotment (24 Oct 2026).',
        'links': [
            ('Check your result', 'https://goocampus.in/dashboard/results'),
            ('Seats still open at your rank for Round 2', 'https://goocampus.in/dashboard/round-analysis?tab=open'),
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


def recipients(conn):
    from pg_admin.news_email import _recipients
    seen, out = set(), []
    for r in _recipients(conn, None):
        em = (r.get('email') or '').strip().lower()
        if em and em not in seen:
            seen.add(em); out.append({'email': em, 'name': r.get('name') or ''})
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
        for r in todo:
            ok = 0
            try:
                ok = 1 if send_email([r['email']], a['subject'], build_html(key, r['name'])) else 0
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
        return {'recipients': len(recipients(conn)), 'sent': int(r['ok'] or 0),
                'failed': int(r['n'] or 0) - int(r['ok'] or 0)}
    finally:
        conn.close()
