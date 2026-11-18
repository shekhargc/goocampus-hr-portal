"""WhatsApp delivery tracking + the "Delivery report" page in the WhatsApp section (founder 2026-11-18: "How do we know
the WhatsApp was delivered? … build it in the WhatsApp section so I can check, for each template, which messages went
out, delivered or not, and what message it was — a combined news message or a registration message").

How a message's fate comes back from Infobip
  1. notifyUrl — every template the portal sends (sign-up, reminder, enquiry, news, group send, tests) carries
     notifyUrl = https://goocampus.org/api/wa/dlr/<token>, so Infobip posts its delivery report straight back.
  2. Pull backup — every 10 minutes (live) GET /whatsapp/1/reports collects any report that wasn't pushed
     (e.g. Quick Send / older sends without notifyUrl). Each report can be pulled once, so nothing is lost twice.
  3. The existing /whatsapp/webhook also passes every report through handle_report().
  "Read" needs Infobip's SEEN report; it arrives on the same URLs when Infobip sends it.

Stored on pg_wa_nudge_log (msg_id, dlr, dlr_reason, delivered_at, read_at, dlr_at, ref) and, for the older WhatsApp
section (Quick Send / Campaigns), on wa_messages (status / delivered_at / read_at / error_text).
"""
import hashlib
import hmac
import logging
import os
import re

from db import get_db

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get('PORTAL_PUBLIC_URL') or 'https://goocampus.org'
_READY = {'done': False}
_MSGID_RE = re.compile(r'"messageId"\s*:\s*"([^"]+)"')


def token():
    key = os.environ.get('SECRET_KEY', 'goocampus-session-2026-08-19')
    return hmac.new(key.encode(), b'wa-dlr-2026-11-18', hashlib.sha256).hexdigest()[:32]


def notify_url():
    return f"{BASE_URL}/api/wa/dlr/{token()}"


def msg_id_from(resp):
    m = _MSGID_RE.search(resp or '')
    return m.group(1) if m else ''


def ensure(conn):
    """Delivery columns on pg_wa_nudge_log — once per process, short lock wait (never DDL on every request)."""
    if _READY['done']:
        return
    try:
        conn.execute("SET LOCAL lock_timeout = '3s'")
        have = {r['column_name'] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'pg_wa_nudge_log'").fetchall()}
        for c, typ in (('msg_id', 'TEXT'), ('dlr', 'TEXT'), ('dlr_reason', 'TEXT'), ('delivered_at', 'TIMESTAMP'),
                       ('read_at', 'TIMESTAMP'), ('dlr_at', 'TIMESTAMP'), ('ref', 'TEXT')):
            if c not in have:
                conn.execute(f"ALTER TABLE pg_wa_nudge_log ADD COLUMN IF NOT EXISTS {c} {typ}")
        conn.commit()
        if 'msg_id' not in have:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_wa_log_msgid ON pg_wa_nudge_log (msg_id)")
            conn.commit()
        # Messages sent before this existed: their Infobip reply (kept in `response`) holds the id.
        conn.execute("UPDATE pg_wa_nudge_log SET msg_id = substring(response from '\"messageId\"\\s*:\\s*\"([^\"]+)\"') "
                     "WHERE msg_id IS NULL AND status IN ('sent', 'failed') AND response LIKE ?", ('%messageId%',))
        conn.commit()
        _READY['done'] = True          # only once the columns really exist (a lock timeout retries next time)
    except Exception as e:
        logger.warning("wa_delivery.ensure: %s", e)
        try: conn.rollback()
        except Exception: pass


# ── reports ────────────────────────────────────────────────────────────────
_FAIL_GROUPS = ('UNDELIVERABLE', 'EXPIRED', 'REJECTED')


def handle_report(conn, r):
    """One Infobip result (delivery report OR seen report). Returns True if it matched a message we sent."""
    mid = (r or {}).get('messageId')
    if not mid:
        return False
    ensure(conn)
    hit = False
    sname = str((r.get('status') or {}).get('name') or '').upper()
    if r.get('seenAt') or r.get('readAt') or 'SEEN' in sname or 'READ' in sname:     # seen ("read") report
        n = conn.execute("UPDATE pg_wa_nudge_log SET dlr = 'read', read_at = CURRENT_TIMESTAMP, dlr_at = CURRENT_TIMESTAMP, "
                         "delivered_at = COALESCE(delivered_at, CURRENT_TIMESTAMP) WHERE msg_id = ? RETURNING id",
                         (mid,)).fetchall()
        hit = bool(n)
        conn.execute("UPDATE wa_messages SET status = 'read', read_at = CURRENT_TIMESTAMP WHERE infobip_message_id = ?",
                     (mid,))
        return hit
    st = r.get('status') or {}
    group = str(st.get('groupName') or '').upper()
    err = r.get('error') or {}
    reason = ' · '.join(x for x in (st.get('description') or st.get('name') or '',
                                    err.get('description') if err.get('groupName') not in (None, 'OK') else '') if x)
    if group == 'DELIVERED':
        n = conn.execute("UPDATE pg_wa_nudge_log SET dlr = CASE WHEN dlr = 'read' THEN 'read' ELSE 'delivered' END, "
                         "delivered_at = COALESCE(delivered_at, CURRENT_TIMESTAMP), dlr_at = CURRENT_TIMESTAMP, "
                         "dlr_reason = '' WHERE msg_id = ? RETURNING id", (mid,)).fetchall()
        conn.execute("UPDATE wa_messages SET status = CASE WHEN status = 'read' THEN 'read' ELSE 'delivered' END, "
                     "delivered_at = COALESCE(delivered_at, CURRENT_TIMESTAMP) WHERE infobip_message_id = ?", (mid,))
        hit = bool(n)
    elif group in _FAIL_GROUPS:
        n = conn.execute("UPDATE pg_wa_nudge_log SET dlr = 'failed', dlr_reason = ?, dlr_at = CURRENT_TIMESTAMP "
                         "WHERE msg_id = ? RETURNING id", ((group.title() + ': ' + reason)[:300], mid)).fetchall()
        conn.execute("UPDATE wa_messages SET status = 'failed', error_text = ? WHERE infobip_message_id = ?",
                     ((group.title() + ': ' + reason)[:300], mid))
        hit = bool(n)
    elif group == 'PENDING':
        conn.execute("UPDATE pg_wa_nudge_log SET dlr = COALESCE(NULLIF(dlr, ''), 'pending'), dlr_at = CURRENT_TIMESTAMP "
                     "WHERE msg_id = ?", (mid,))
    return hit


def dlr_endpoint(tok):
    """POST /api/wa/dlr/<token> — Infobip delivery / seen reports (notifyUrl)."""
    from flask import request, jsonify
    if not hmac.compare_digest(str(tok or ''), token()):
        return jsonify({'ok': False}), 404
    data = request.get_json(silent=True) or {}
    n = 0
    conn = get_db()
    try:
        for r in data.get('results') or []:
            try:
                n += 1 if handle_report(conn, r) else 0
            except Exception as e:
                conn.rollback()
                logger.warning("wa dlr one: %s", e)
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True, 'matched': n})


def pull_reports(conn):
    """Backup: collect reports Infobip couldn't push (live, every 10 min). Each report is returned once."""
    key, base = os.environ.get('INFOBIP_API_KEY', ''), os.environ.get('INFOBIP_BASE_URL', '')
    if not key or not base:
        return 0
    import requests as _rq
    got = 0
    try:
        r = _rq.get(f"https://{base}/whatsapp/1/reports", params={'limit': 1000},
                    headers={"Authorization": f"App {key}"}, timeout=20)
        if r.status_code >= 300:
            logger.info("wa dlr pull: %s %s", r.status_code, r.text[:200])
            return 0
        for res in (r.json() or {}).get('results') or []:
            try:
                got += 1 if handle_report(conn, res) else 0
            except Exception as e:
                conn.rollback()
                logger.warning("wa dlr pull one: %s", e)
        conn.commit()
    except Exception as e:
        logger.warning("wa dlr pull: %s", e)
        try: conn.rollback()
        except Exception: pass
    return got


# ── the page: WhatsApp → Delivery report ───────────────────────────────────
STATUS_CHOICES = (('delivered', 'Delivered'), ('read', 'Read'), ('failed', 'Failed'), ('waiting', 'Sent, no report yet'),
                  ('not_sent', 'Not sent (provider refused)'))
TYPE_CHOICES = (('welcome', 'Welcome'), ('incomplete', 'Profile reminder'), ('enquiry', 'Enquiry thank-you'),
                ('daily', 'News update'), ('campaign', 'Group send'), ('test', 'Test send'), ('quick', 'Quick Send / old campaigns'))


def _status_of(row):
    if row.get('status') == 'failed':
        return 'not_sent'
    d = row.get('dlr') or ''
    return d if d in ('delivered', 'read', 'failed') else 'waiting'


def report_page():
    from flask import request, render_template
    from pg_admin import wa_nudges as w
    f = {k: (request.args.get(k) or '').strip() for k in ('template', 'type', 'status', 'from', 'to', 'q')}
    for k in ('from', 'to'):
        if f[k] and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', f[k]):
            f[k] = ''
    rows, summary, templates = [], [], []
    conn = get_db()
    try:
        w.ensure_tables(conn)
        ensure(conn)
        ist = "(l.created_at + INTERVAL '330 minutes')"
        conds, params = ["l.status IN ('sent', 'failed')"], []
        if f['template']:
            conds.append("l.template = ?"); params.append(f['template'])
        if f['type'] and f['type'] != 'quick':
            conds.append("split_part(l.kind, ':', 1) LIKE ?"); params.append(f['type'] + '%')
        if f['from']:
            conds.append(f"{ist}::date >= ?::date"); params.append(f['from'])
        if f['to']:
            conds.append(f"{ist}::date <= ?::date"); params.append(f['to'])
        if f['q']:
            conds.append("(u.name ILIKE ? OR l.mobile LIKE ? OR COALESCE(l.ref,'') ILIKE ?)")
            params += [f"%{f['q']}%", f"%{f['q'][-4:]}%", f"%{f['q']}%"]
        where = ' AND '.join(conds)
        if f['type'] != 'quick':
            for r in conn.execute(
                    "SELECT l.id, l.created_at, l.template, l.kind, l.ref, l.mobile, l.status, l.response, l.dlr, l.dlr_reason, "
                    "l.delivered_at, l.read_at, l.user_id, l.sent_by, u.name AS doctor_name "
                    f"FROM pg_wa_nudge_log l LEFT JOIN pg_users u ON u.id = l.user_id WHERE {where} "
                    "ORDER BY l.id DESC LIMIT 3000", tuple(params)).fetchall():
                r = dict(r)
                r['what'] = _what(r, w)
                r['st'] = _status_of(r)
                r['who'] = r['doctor_name'] or ('website enquiry' if (r['kind'] or '').startswith('enquiry')
                                                 else ('test by ' + (r['sent_by'] or '')) if r['kind'] == 'test' else '')
                r['src'] = 'auto'
                rows.append(r)
        if not f['type'] or f['type'] == 'quick':        # older WhatsApp section: Quick Send / Campaigns
            qc, qp = ["m.direction = 'outbound'"], []
            if f['template']:
                qc.append("m.template_name = ?"); qp.append(f['template'])
            mist = "(COALESCE(m.sent_at, m.created_at) + INTERVAL '330 minutes')"
            if f['from']:
                qc.append(f"{mist}::date >= ?::date"); qp.append(f['from'])
            if f['to']:
                qc.append(f"{mist}::date <= ?::date"); qp.append(f['to'])
            if f['q']:
                qc.append("(c.name ILIKE ? OR c.phone LIKE ?)"); qp += [f"%{f['q']}%", f"%{f['q']}%"]
            try:
                for m in conn.execute(
                        "SELECT m.id, COALESCE(m.sent_at, m.created_at) AS created_at, m.template_name AS template, "
                        "m.status AS mstatus, m.error_text, m.delivered_at, m.read_at, m.campaign_id, c.name AS cname, c.phone "
                        "FROM wa_messages m LEFT JOIN wa_contacts c ON c.id = m.contact_id "
                        f"WHERE {' AND '.join(qc)} ORDER BY m.id DESC LIMIT 2000", tuple(qp)).fetchall():
                    m = dict(m)
                    ms = (m['mstatus'] or '').lower()
                    rows.append({'id': 'q%d' % m['id'], 'created_at': m['created_at'], 'template': m['template'] or '(free text)',
                                 'what': ('Campaign #%s' % m['campaign_id']) if m['campaign_id'] else 'Quick Send',
                                 'who': m['cname'] or '', 'mobile': (m['phone'] or '')[-4:], 'user_id': None,
                                 'st': {'delivered': 'delivered', 'read': 'read', 'failed': 'not_sent'}.get(ms, 'waiting'),
                                 'dlr_reason': m['error_text'] or '', 'delivered_at': m['delivered_at'],
                                 'read_at': m['read_at'], 'src': 'quick'})
            except Exception as e:
                conn.rollback()
                logger.warning("wa report quick: %s", e)
        rows.sort(key=lambda r: r['created_at'] or 0, reverse=True)
        if f['status']:
            rows = [r for r in rows if r['st'] == f['status']]
        # Totals per template (for the current filters)
        by = {}
        for r in rows:
            t = by.setdefault(r['template'], {'template': r['template'], 'total': 0, 'delivered': 0, 'read': 0,
                                              'failed': 0, 'waiting': 0, 'not_sent': 0})
            t['total'] += 1
            t[r['st']] += 1
        summary = sorted(by.values(), key=lambda t: -t['total'])
        templates = sorted({r['template'] for r in conn.execute(
            "SELECT DISTINCT template FROM pg_wa_nudge_log WHERE COALESCE(template,'') <> ''").fetchall()} |
            {r['template_name'] for r in conn.execute(
                "SELECT DISTINCT template_name FROM wa_messages WHERE COALESCE(template_name,'') <> ''").fetchall()})
    except Exception as e:
        logger.error("wa delivery report: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    shown = rows[:1500]
    return render_template('wa_delivery.html', rows=shown, total=len(rows), summary=summary, templates=templates, f=f,
                           status_choices=STATUS_CHOICES, type_choices=TYPE_CHOICES,
                           totals={k: sum(t[k] for t in summary) for k in ('total', 'delivered', 'read', 'failed',
                                                                            'waiting', 'not_sent')})


def _what(r, w):
    kind = r.get('kind') or ''
    base = w.kind_label(kind)
    if r.get('ref'):
        return f"{base} · {r['ref']}"
    if kind.startswith('campaign:'):
        return f"Group send #{kind.split(':', 1)[1]}"
    if kind.startswith('daily:e'):
        return f"{base} · with news email"
    return base


def register(app):
    from core.auth import admin_required
    app.add_url_rule('/api/wa/dlr/<tok>', 'pg_wa_dlr', dlr_endpoint, methods=['POST'])
    app.add_url_rule('/whatsapp/delivery', 'wa_delivery_report', admin_required(report_page), methods=['GET'])
