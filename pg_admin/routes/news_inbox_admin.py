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
    if tab not in ('new', 'posted', 'document', 'dismissed'):
        tab = 'new'
    # authority tabs (founder 2026-10-13): '' = all authorities, else a source code
    src = (request.args.get('src') or '').strip()
    if src not in NS.SOURCES:
        src = ''
    conn = get_db()
    items, counts, sources = [], {'new': 0, 'posted': 0, 'document': 0, 'dismissed': 0}, []
    new_by_src, auth_tabs = {}, []
    try:
        NS.ensure_news_inbox_tables(conn)
        from pg_admin.data.big_files import ensure_cols as _bf_cols
        _bf_cols(conn)
        from pg_admin.ai_redraft import ensure_cols as _ai_cols
        _ai_cols(conn)
        for r in conn.execute("SELECT source_code, status, COUNT(*) AS n FROM pg_news_inbox "
                              "WHERE status IN ('new','posted','document','dismissed') GROUP BY source_code, status").fetchall():
            if not src or r['source_code'] == src:
                counts[r['status']] += r['n']
            if r['status'] == 'new':
                new_by_src[r['source_code']] = new_by_src.get(r['source_code'], 0) + r['n']
        where, params = "status = ?", [tab]
        if src:
            where += " AND source_code = ?"; params.append(src)
        items = [dict(r) for r in conn.execute(
            "SELECT id, source_code, authority_code, item_key, title, url, kind, notice_date, status, news_id, "
            "reviewed_by, reviewed_at, first_seen_at, draft_json, (pdf_data IS NOT NULL OR COALESCE(pdf_r2_key,'') <> '' OR pdf_doc_id IS NOT NULL) AS has_pdf, "
            "COALESCE(redraft_requested, FALSE) AS redraft_requested, COALESCE(history_note,'') AS history_note, "
            "COALESCE(notice_date_source,'') AS notice_date_source, COALESCE(redraft_status,'') AS redraft_status, "
            "COALESCE(redraft_error,'') AS redraft_error, redraft_at, COALESCE(redraft_note,'') AS redraft_note "
            "FROM pg_news_inbox WHERE " + where + " "
            "ORDER BY notice_date DESC NULLS LAST, first_seen_at DESC, id DESC LIMIT 300", params).fetchall()]
        auth_tabs = [{'code': c, 'name': s.get('short') or s['label'], 'new': new_by_src.get(c, 0)}
                     for c, s in NS.SOURCES.items() if s.get('enabled')]
        for code, s in NS.SOURCES.items():
            if src and code != src:
                continue
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
    import json as _json
    for it in items:
        try: it['draft'] = _json.loads(it.get('draft_json') or '{}') or None
        except Exception: it['draft'] = None
    _flag_similar(items)
    _flag_date_gaps(items)
    labels = {c: s['label'] for c, s in NS.SOURCES.items()}
    from pg_admin import ai_redraft as _ai
    return render_template('pg_admin/news_inbox.html', items=items, counts=counts, tab=tab, ai_ready=_ai.available(),
                           sources=sources, labels=labels, src=src, auth_tabs=auth_tabs,
                           doc_labels=dict(__import__('pg_admin.authorities', fromlist=['x']).DOC_CATEGORIES),
                           new_total=sum(new_by_src.values()), active_section='goocampus_in')


_STOP = set('the a an of for to in on and or by with from is are be at as 2026 2027 2026-27 neet pg medical counselling '
             'notice notification courses course admission admissions candidates round'.split())


def _words(t):
    import re
    return {w for w in re.findall(r'[a-z0-9]+', (t or '').lower()) if len(w) > 2 and w not in _STOP}


def _flag_similar(items):
    """Warn when a NEW notice looks like news already published for the same authority (founder
    2026-10-13: no duplicate news). Word overlap of headlines, within the last 120 days."""
    news_items = [it for it in items if it.get('status') in ('new', 'document')]
    if not news_items:
        return
    conn = get_db()
    try:
        pub = [dict(r) for r in conn.execute(
            "SELECT id, heading, scope, COALESCE(state,'') AS state FROM pg_news WHERE deleted_at IS NULL "
            "AND COALESCE(is_published, TRUE) AND published_at > CURRENT_TIMESTAMP - INTERVAL '120 days'").fetchall()]
    except Exception as e:
        logging.warning("inbox similar: %s", e)
        try: conn.rollback()
        except Exception: pass
        pub = []
    finally:
        conn.close()
    from pg_admin.authorities import get_authority
    for it in news_items:
        a = get_authority(it.get('authority_code') or '') or {}
        mine = _words((it.get('draft') or {}).get('headline') or it.get('title'))
        best = None
        for n in pub:
            same_auth = (n['scope'] == 'all_india') if it.get('authority_code') == 'mcc' else \
                        (n['state'] or '').lower() == (a.get('state') or '').lower()
            if not same_auth or not mine:
                continue
            w = _words(n['heading'])
            score = len(mine & w) / max(1, min(len(mine), len(w)))
            if score >= 0.6 and (not best or score > best[0]):
                best = (score, n)
        if best:
            it['similar'] = {'id': best[1]['id'], 'heading': best[1]['heading']}


@login_required
def news_inbox_check():
    """'Check now' — check every source right away, in the background (bypasses the
    20-minute skip). The page shows the result once the check finishes."""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    NS.run_all_background(trigger='manual')
    flash('Checking the websites now — this takes up to a minute. Refresh this page to see new notices.',
          'info')
    return redirect(url_for('pg_news_inbox'))


@login_required
def news_inbox_redraft():
    """'↻ Re-draft with AI' — the Mac re-reads this notice at its next check and sends a fresh
    draft (headline/article/dates/schedule/calendar events). (founder 2026-10-09)"""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    try:
        iid = int(request.form.get('id') or 0)
    except ValueError:
        iid = 0
    back = request.form.get('tab') or 'new'
    back_src = request.form.get('src') or None
    from pg_admin import ai_redraft
    if ai_redraft.available():
        # instant: the portal sends the stored PDF to Claude now (founder 2026-10-22)
        why = ai_redraft.start(iid, (request.form.get('note') or '').strip(), _who())
        if why:
            flash(why, 'error')
        else:
            flash('Re-drafting now — the AI is re-reading the notice. Refresh this page in a minute to see the new draft.', 'success')
        return redirect(url_for('pg_news_inbox', tab=back, src=back_src))
    conn = get_db()
    try:
        NS.ensure_news_inbox_tables(conn)
        ai_redraft.ensure_cols(conn)
        # queued for the Mac: its watcher checks every 2 minutes and re-drafts with the founder's
        # Claude account (founder 2026-10-22, option B — no API key)
        conn.execute("UPDATE pg_news_inbox SET redraft_requested = TRUE, redraft_status = 'queued', redraft_error = '', "
                     "redraft_note = ?, redraft_at = CURRENT_TIMESTAMP WHERE id = ?",
                     ((request.form.get('note') or '').strip()[:500], iid))
        conn.commit()
        flash('Re-draft queued — your Mac re-reads the notice within about 5 minutes (while it is on). '
              'Refresh this page to see the new draft.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news_inbox_redraft: %s", e)
        flash('Could not request a re-draft.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_news_inbox', tab=back, src=back_src))


@login_required
def news_inbox_status():
    """Dismiss / restore a notice — or several ticked ones at once ("Dismiss selected" /
    "Restore selected", founder 2026-10-16). (Posting happens via the newsroom form.)"""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    ids = [int(x) for x in request.form.getlist('ids') if str(x).isdigit()]
    if not ids:
        try:
            ids = [int(request.form.get('id') or 0)]
        except ValueError:
            ids = []
    ids = [i for i in ids if i][:300]
    to = (request.form.get('to') or '').strip()
    back = request.form.get('tab') or 'new'
    back_src = request.form.get('src') or None
    if not ids or to not in ('new', 'dismissed'):
        flash('Nothing selected.', 'error'); return redirect(url_for('pg_news_inbox', tab=back, src=back_src))
    conn = get_db()
    try:
        conn.execute("UPDATE pg_news_inbox SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP "
                     "WHERE id IN (" + ','.join(['?'] * len(ids)) + ") AND status <> 'posted'",
                     [to, _who()] + ids)
        conn.commit()
        n = len(ids)
        if n == 1:
            flash('Dismissed.' if to == 'dismissed' else 'Moved back to New.', 'success')
        else:
            flash(f'{n} notices dismissed.' if to == 'dismissed' else f'{n} notices moved back to New.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news_inbox_status: %s", e)
        flash('Could not update.', 'error')
    finally:
        conn.close()
    if request.form.get('next') == 'coverage':
        return redirect(url_for('pg_news_coverage'))
    return redirect(url_for('pg_news_inbox', tab=back, src=back_src))



def _flag_date_gaps(items):
    """Dates written in a draft's text that aren't in its date fields (founder 2026-10-22). 'missing' =
    not in the authority's schedule either (doctors can't see that date anywhere) → red; otherwise amber."""
    from pg_admin.data.date_check import gaps, calendar_dates
    todo = [it for it in items if it.get('draft') and it.get('status') in ('new', 'document', 'posted')]
    if not todo:
        return
    conn = get_db()
    try:
        cal = {}
        for it in todo:
            code = it.get('authority_code') or ''
            if code not in cal:
                cal[code] = calendar_dates(conn, code)
            g = gaps(it['draft'], it.get('notice_date'), cal[code])
            if g:
                it['date_gaps'] = [{'date': d.strftime('%d %b'), 'snippet': sn, 'in_calendar': c} for d, sn, c in g]
                it['date_gaps_missing'] = sum(1 for _d, _s, c in g if not c)
    except Exception as e:
        logging.warning("inbox date gaps: %s", e)
    finally:
        conn.close()


@login_required
def news_coverage():
    """Coverage (founder 2026-10-22: "a cleaner way of monitoring" — Kerala was blocked for 3 days,
    Rajasthan was read from the wrong site, an Odisha notice was set aside, a notice was posted
    unread). One row per source: is its website being read, when was its last notice, what was set
    aside as last season (with Restore), what is still unread, and drafts whose dates need a look."""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    import json as _json
    from datetime import datetime, timedelta
    from pg_admin.authorities import get_authority
    from pg_admin.data.date_check import gaps, calendar_dates
    conn = get_db()
    rows, totals = [], {'errors': 0, 'quiet': 0, 'set_aside': 0, 'unread': 0, 'date_red': 0, 'date_amber': 0, 'waiting': 0}
    last_run = None
    try:
        NS.ensure_news_inbox_tables(conn)
        lr = conn.execute("SELECT MAX(ran_at) AS t FROM pg_news_scrape_runs WHERE trigger = 'mac'").fetchone()
        last_run = lr['t'] if lr else None
        since = datetime.utcnow() - timedelta(days=21)
        for code, s in NS.SOURCES.items():
            if not s.get('enabled'):
                continue
            auth = get_authority(s.get('authority_code') or '') or {}
            last = conn.execute("SELECT ran_at, ok, found, error FROM pg_news_scrape_runs WHERE source_code = ? "
                                "ORDER BY ran_at DESC LIMIT 1", (code,)).fetchone()
            last_ok = conn.execute("SELECT MAX(ran_at) AS t FROM pg_news_scrape_runs WHERE source_code = ? AND ok",
                                   (code,)).fetchone()['t']
            inbox = [dict(r) for r in conn.execute(
                "SELECT id, status, title, url, notice_date, first_seen_at, draft_json, news_id "
                "FROM pg_news_inbox WHERE source_code = ? ORDER BY id DESC", (code,)).fetchall()]
            current = [i for i in inbox if i['status'] != 'seen']
            last_notice = max((i['notice_date'] for i in current if i['notice_date']), default=None)
            # only set-asides that LOOK like this season (dated in season, or undated without an old year) —
            # a new source's first run sets aside years of old notices correctly; those are just noise here
            set_aside = [i for i in inbox if i['status'] == 'seen' and i['first_seen_at'] and i['first_seen_at'] >= since
                         and NS.in_season({'title': i['title'], 'url': i['url'], 'notice_date': i['notice_date']})]
            unread = [i for i in inbox if i['status'] in ('new', 'document') and not i['draft_json']]
            waiting = [i for i in inbox if i['status'] == 'new' and i['draft_json']]
            cal = calendar_dates(conn, s.get('authority_code') or '')
            red, amber = [], []
            for i in inbox:
                if i['status'] not in ('new', 'document', 'posted') or not i['draft_json']:
                    continue
                try:
                    d = _json.loads(i['draft_json']) or {}
                except Exception:
                    continue
                g = gaps(d, i['notice_date'], cal)
                if not g:
                    continue
                entry = {'id': i['id'], 'status': i['status'], 'news_id': i['news_id'],
                         'headline': (d.get('headline') or i['title'] or '')[:140],
                         'dates': ', '.join(x.strftime('%d %b') + ('' if c else ' (not in schedule)') for x, _s, c in g)}
                (red if any(not c for _x, _s, c in g) else amber).append(entry)
            ok = bool(last and last['ok'])
            stale = (not last_ok) or (datetime.utcnow() - last_ok > timedelta(hours=26))
            quiet_days = (datetime.utcnow().date() - last_notice).days if last_notice else None
            status = 'down' if (not ok or stale) else ('warn' if (red or unread or (quiet_days is not None and quiet_days > 10)) else 'ok')
            rows.append({'code': code, 'label': s.get('short') or auth.get('state') or code, 'source_label': s['label'],
                         'url': s['url'], 'authority': auth.get('name') or s.get('authority_code'),
                         'state': auth.get('state') or '', 'status': status, 'ok': ok,
                         'error': (last['error'] if last and not last['ok'] else '') or '',
                         'last_run': last['ran_at'] if last else None, 'last_ok': last_ok,
                         'found': last['found'] if last else 0, 'last_notice': last_notice, 'quiet_days': quiet_days,
                         'set_aside': set_aside[:30], 'unread': unread[:30], 'waiting': len(waiting),
                         'red': red, 'amber': amber})
            totals['errors'] += 0 if ok and not stale else 1
            totals['quiet'] += 1 if (quiet_days is not None and quiet_days > 10) else 0
            totals['set_aside'] += len(set_aside)
            totals['unread'] += len(unread)
            totals['date_red'] += len(red)
            totals['date_amber'] += len(amber)
            totals['waiting'] += len(waiting)
    except Exception as e:
        logging.error("news_coverage: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    order = {'down': 0, 'warn': 1, 'ok': 2}
    rows.sort(key=lambda r: (order[r['status']], r['label']))
    return render_template('pg_admin/news_coverage.html', rows=rows, totals=totals, last_run=last_run,
                           active_section='goocampus_in')
