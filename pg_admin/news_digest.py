"""Combined news email (founder 2026-11-03: ~42,000 single-news emails sent so far — Resend counts every one).

On the news form the founder picks HOW an emailed update goes out:
  - "Send now, on its own" — the existing single-news blast (news_email.send_news_blast), unchanged.
  - "Add to the combined email" — the update is only QUEUED (pg_news.digest_status = 'queued').
Nothing is sent on a timer. When the founder presses "Send combined email now" on the News page, every update
queued up to that moment goes out together: each recipient gets ONE email holding every queued update meant for
them (each update keeps its own audience — all doctors / that state's doctors / team), in the same branded format
as the single email, stacked. A recipient with just one of the updates gets the normal single-news email.

pg_news columns: digest_status ('' | queued | sending | sent), digest_queued_at, digest_batch_id.
pg_news_digest_batches: one row per "Send combined email now" (who, which updates, recipients, sent, failed).
Opens/clicks are logged in pg_email_log as kind 'news_digest', ref_id = batch id (Dashboard → Analytics).
"""
import logging
import threading
import time

from db import get_db

logger = logging.getLogger(__name__)
_ready = False
NEWS_COLS = ("id, scope, state, body_label, heading, body_text, source_url, pdf_name, "
             "COALESCE(category,'') AS category, COALESCE(summary,'') AS summary, "
             "COALESCE(key_dates,'') AS key_dates, COALESCE(schedule,'') AS schedule, "
             "COALESCE(to_jsonb(pg_news)->>'email_audience', 'all') AS email_audience, "
             "is_published, published_at, digest_queued_at")


def ensure(conn):
    """Columns + batch table (idempotent; called on use, so a cold-start skip can't break a page)."""
    global _ready
    if _ready:
        return
    conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS digest_status TEXT DEFAULT ''")
    conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS digest_queued_at TIMESTAMP")
    conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS digest_batch_id INTEGER")
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_news_digest_batches (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_by TEXT DEFAULT '',
        news_ids TEXT DEFAULT '',
        status TEXT DEFAULT 'sending',      -- sending | sent
        recipients INTEGER DEFAULT 0,
        sent INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0,
        finished_at TIMESTAMP
    )''')
    conn.commit()
    _ready = True


def _live(row):
    return bool(row.get('is_published', True)) and str(row.get('is_published')).lower() not in ('0', 'false')


def queue(conn, news_id):
    ensure(conn)
    conn.execute("UPDATE pg_news SET digest_status='queued', digest_queued_at=CURRENT_TIMESTAMP, digest_batch_id=NULL "
                 "WHERE id = ?", (news_id,))
    conn.commit()


def unqueue(conn, news_id):
    ensure(conn)
    conn.execute("UPDATE pg_news SET digest_status='', digest_queued_at=NULL WHERE id = ? AND digest_status='queued'",
                 (news_id,))
    conn.commit()


def queued_items(conn):
    """Updates waiting for the combined email, in the order they were added (deleted ones never count)."""
    ensure(conn)
    return [dict(r) for r in conn.execute(
        f"SELECT {NEWS_COLS} FROM pg_news WHERE digest_status = 'queued' AND deleted_at IS NULL "
        "ORDER BY digest_queued_at, id").fetchall()]


def plan(conn, items):
    """email → {email, name, is_free, user_id, items:[news, …]} — each update reaches exactly the people its own
    audience setting reaches (news_email._recipients), so nobody gets an update they wouldn't get on its own."""
    from pg_admin.news_email import _recipients, _audience
    out = {}
    for it in items:
        for r in _recipients(conn, *_audience(it)):
            p = out.setdefault(r['email'], {'email': r['email'], 'name': r.get('name') or '', 'is_free': r['is_free'],
                                            'user_id': r.get('user_id'), 'items': []})
            p['is_free'] = p['is_free'] and r['is_free']         # staff / paid anywhere → no upgrade banner
            p['name'] = p['name'] or r.get('name') or ''
            p['user_id'] = p['user_id'] or r.get('user_id')
            p['items'].append(it)
    return out


def summary(conn):
    """For the News page box: waiting updates (+ audience words) and how many people would get ONE email."""
    from pg_admin.news_email import audience_label
    items = queued_items(conn)
    for it in items:
        it['audience_words'] = audience_label(it.get('email_audience'), it.get('state') if it.get('scope') == 'state' else '')
        it['hidden'] = not _live(it)
    live = [it for it in items if not it['hidden']]
    people = plan(conn, live) if live else {}
    singles = sum(len(p['items']) for p in people.values())
    last = conn.execute("SELECT id, created_at, created_by, status, recipients, sent, failed, news_ids "
                        "FROM pg_news_digest_batches ORDER BY id DESC LIMIT 1").fetchone()
    return {'items': items, 'recipients': len(people), 'would_be_singles': singles,
            'last': dict(last) if last else None}


def build(person):
    """(subject, html) for one recipient: the normal single email for one update, the combined one for several."""
    from pg_admin.news_email import build_news_email_html, news_subject, build_digest_html, digest_subject
    items = person['items']
    if len(items) == 1:
        return news_subject(items[0]), build_news_email_html(items[0], person['is_free'], person.get('name'))
    return digest_subject(items), build_digest_html(items, person['is_free'], person.get('name'))


def start(actor):
    """'Send combined email now': claim every queued, live update into a new batch and send it in the background.
    Returns (batch_id, n_updates, n_recipients) or (None, 0, 0) when nothing is waiting. The claim is one UPDATE,
    so a double click can't send the same updates twice."""
    conn = get_db()
    try:
        ensure(conn)
        items = [it for it in queued_items(conn) if _live(it)]
        if not items:
            return None, 0, 0
        ids = [it['id'] for it in items]
        bid = conn.execute("INSERT INTO pg_news_digest_batches (created_by, news_ids) VALUES (?, ?) RETURNING id",
                           (actor or '', ','.join(map(str, ids)))).fetchone()['id']
        claimed = [r['id'] for r in conn.execute(
            "UPDATE pg_news SET digest_status='sending', digest_batch_id=? WHERE digest_status='queued' "
            "AND id = ANY(?) RETURNING id", (bid, ids)).fetchall()]
        if not claimed:
            conn.execute("DELETE FROM pg_news_digest_batches WHERE id = ?", (bid,))
            conn.commit()
            return None, 0, 0
        conn.execute("UPDATE pg_news_digest_batches SET news_ids = ? WHERE id = ?", (','.join(map(str, claimed)), bid))
        conn.commit()
        n = len(plan(conn, [it for it in items if it['id'] in claimed]))
    finally:
        conn.close()
    threading.Thread(target=_send_batch, args=(bid,), daemon=True, name=f'pg-news-digest-{bid}').start()
    return bid, len(claimed), n


def _send_batch(bid):
    try:
        from email_utils import send_email
    except Exception as e:
        logger.error("news digest: email_utils import failed: %s", e)
        return
    from pg_admin import email_tracking as ET
    conn = get_db()
    try:
        items = [dict(r) for r in conn.execute(
            f"SELECT {NEWS_COLS} FROM pg_news WHERE digest_batch_id = ? AND digest_status = 'sending' "
            "ORDER BY digest_queued_at, id", (bid,)).fetchall()]
        people = plan(conn, items)
        conn.execute("UPDATE pg_news_digest_batches SET recipients = ? WHERE id = ?", (len(people), bid))
        conn.commit()
    except Exception as e:
        logger.error("news digest #%s: load failed: %s", bid, e)
        try: conn.rollback()
        except Exception: pass
        conn.close()
        return
    sent = failed = 0
    label = f"Combined email #{bid} ({len(items)} updates)"
    logger.info("news digest #%s → %s update(s), %s recipient(s)", bid, len(items), len(people))
    try:
        for p in people.values():
            try:
                subject, html = build(p)
                html, tok = ET.wrap(conn, html, kind='news_digest', email=p['email'], subject=subject,
                                    ref_id=bid, ref_label=label, user_id=p.get('user_id'))
                ok = send_email([p['email']], subject, html)
                ET.mark_sent(conn, tok, ok)
                sent, failed = sent + (1 if ok else 0), failed + (0 if ok else 1)
            except Exception as e:
                failed += 1
                logger.error("news digest #%s: send to %s failed: %s", bid, p.get('email'), e)
            if (sent + failed) % 50 == 0:
                try:
                    conn.execute("UPDATE pg_news_digest_batches SET sent = ?, failed = ? WHERE id = ?", (sent, failed, bid))
                    conn.commit()
                except Exception:
                    conn.rollback()
            time.sleep(0.4)    # stay under Resend's 2 req/sec cap (same as the single blast)
        conn.execute("UPDATE pg_news SET digest_status='sent' WHERE digest_batch_id = ? AND digest_status='sending'", (bid,))
        conn.execute("UPDATE pg_news_digest_batches SET status='sent', sent=?, failed=?, finished_at=CURRENT_TIMESTAMP "
                     "WHERE id = ?", (sent, failed, bid))
        conn.commit()
    except Exception as e:
        logger.error("news digest #%s: %s", bid, e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    logger.info("news digest #%s done: %s sent, %s failed", bid, sent, failed)


def send_test(to, name=''):
    """The combined email for the CURRENT waiting list to one address, free + paid views (nothing is claimed)."""
    from email_utils import send_email
    conn = get_db()
    try:
        items = [it for it in queued_items(conn) if _live(it)]
    finally:
        conn.close()
    if not items:
        return None
    ok = 0
    for is_free, who, tag in ((True, '', 'FREE-user view'), (False, name or 'Rahul Sharma', 'PAID-user view')):
        subject, html = build({'items': items, 'is_free': is_free, 'name': who})
        ok += 1 if send_email([to], f"[TEST] {subject} — {tag}"[:180], html) else 0
    return ok
