"""Admin: News Inbox — notices the scraper found on counselling-authority sites, waiting for
review (founder 2026-10-08). "Add to News" opens the newsroom form pre-filled (and attaches
the PDF on save); "Dismiss" hides a notice that isn't worth posting. Admin-only, like News.
"""
import logging
from flask import render_template, request, redirect, url_for, flash
from db import get_db
from core.users import get_user
from core.auth import login_required
from pg_admin import news_scraper as NS


def _require_admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def _who():
    u = get_user() or {}
    return u.get('name') or u.get('emp_code') or 'admin'


@login_required
def news_inbox():
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    tab = (request.args.get('tab') or 'new').strip()
    if tab not in ('new', 'posted', 'dismissed'):
        tab = 'new'
    conn = get_db()
    items, counts, sources = [], {'new': 0, 'posted': 0, 'dismissed': 0}, []
    try:
        NS.ensure_news_inbox_tables(conn)
        for r in conn.execute("SELECT status, COUNT(*) AS n FROM pg_news_inbox GROUP BY status").fetchall():
            counts[r['status']] = r['n']
        items = [dict(r) for r in conn.execute(
            "SELECT * FROM pg_news_inbox WHERE status = ? "
            "ORDER BY notice_date DESC NULLS LAST, first_seen_at DESC, id DESC LIMIT 300", (tab,)).fetchall()]
        for code, s in NS.SOURCES.items():
            last = conn.execute(
                "SELECT ran_at, ok, found, new_count, error, trigger FROM pg_news_scrape_runs "
                "WHERE source_code = ? ORDER BY ran_at DESC LIMIT 1", (code,)).fetchone()
            last_ok = conn.execute(
                "SELECT ran_at FROM pg_news_scrape_runs WHERE source_code = ? AND ok "
                "ORDER BY ran_at DESC LIMIT 1", (code,)).fetchone()
            sources.append({'code': code, 'label': s['label'], 'url': s['url'], 'enabled': s.get('enabled'),
                            'last': dict(last) if last else None,
                            'last_ok_at': last_ok['ran_at'] if last_ok else None})
    except Exception as e:
        logging.error("news_inbox: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    labels = {c: s['label'] for c, s in NS.SOURCES.items()}
    return render_template('pg_admin/news_inbox.html', items=items, counts=counts, tab=tab,
                           sources=sources, labels=labels, active_section='goocampus_in')


@login_required
def news_inbox_check():
    """'Check now' — run every source immediately (bypasses the 20-minute skip)."""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    res = NS.run_all(trigger='manual')
    new = sum(r['new'] for r in res)
    bad = [r for r in res if r['error']]
    busy = [r for r in res if r['skipped']]
    if bad:
        flash('Could not read: ' + '; '.join(f"{NS.SOURCES[r['source']]['label']} — {r['error']}" for r in bad),
              'error')
    if busy:
        flash('Already being checked right now — try again in a minute.', 'info')
    if not bad and not busy:
        flash(f'Checked {len(res)} source(s): {new} new notice(s).' if new
              else f'Checked {len(res)} source(s): nothing new.', 'success' if new else 'info')
    return redirect(url_for('pg_news_inbox'))


@login_required
def news_inbox_status():
    """Dismiss / restore a notice. (Posting happens via the newsroom form.)"""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    try:
        iid = int(request.form.get('id') or 0)
    except ValueError:
        iid = 0
    to = (request.form.get('to') or '').strip()
    back = request.form.get('tab') or 'new'
    if not iid or to not in ('new', 'dismissed'):
        flash('Nothing to update.', 'error'); return redirect(url_for('pg_news_inbox', tab=back))
    conn = get_db()
    try:
        conn.execute("UPDATE pg_news_inbox SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP "
                     "WHERE id = ? AND status <> 'posted'", (to, _who(), iid))
        conn.commit()
        flash('Dismissed.' if to == 'dismissed' else 'Moved back to New.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news_inbox_status: %s", e)
        flash('Could not update.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_news_inbox', tab=back))
