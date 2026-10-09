"""Admin: post NEET-PG counselling News & Updates (founder 2026-09-30).

A dead-simple newsroom. The team picks a scope (All-India, shown to everyone, or a
State, shown to doctors following that state), a body label (the authority name), a
heading, and either pasted text or a PDF. Doctors see All-India + their home state
by default on the dashboard. True-admin gated.
"""
import logging
from flask import render_template, request, redirect, url_for, flash, Response
from db import get_db
from core.users import get_user
from core.auth import login_required
from pg_admin.routes.users_admin import _canonical_states


NEWS_CATEGORIES = [('bulletin', 'Information bulletin / brochure'),
                   ('registration', 'Registration'), ('verification', 'Document verification'),
                   ('choice_filling', 'Choice filling'),
                   ('seat_allotment', 'Seat allotment / result'), ('fee_payment', 'Fee payment'),
                   ('reporting', 'Reporting to college'), ('notification', 'Notification / schedule'),
                   ('other', 'Other')]
NEWS_DATE_FIELDS = [('registration_start', 'Registration starts'), ('registration_end', 'Registration last date'),
                    ('verification_start', 'Document verification / slot booking starts'),
                    ('verification_end', 'Document verification last date'),
                    ('choice_filling_start', 'Choice filling starts'), ('choice_filling_end', 'Choice filling last date'),
                    ('payment_last_date', 'Fee payment last date'), ('reporting_last_date', 'Reporting last date'),
                    ('result_date', 'Result / allotment date')]


def schedule_to_text(sch):
    """{"columns","rows"} → editable pipe text (header line first)."""
    if not isinstance(sch, dict) or not sch.get('rows'):
        return ''
    lines = []
    if sch.get('title'):
        lines.append('# ' + sch['title'])
    if sch.get('columns'):
        lines.append(' | '.join(sch['columns']))
    lines += [' | '.join(str(c) for c in r) for r in sch['rows']]
    return '\n'.join(lines)


def text_to_schedule(txt):
    """Pipe text → {"title","columns","rows"} (first non-# line = header). '' if empty."""
    import json as _json
    lines = [l.strip() for l in (txt or '').splitlines() if l.strip()]
    if not lines:
        return ''
    title = ''
    if lines[0].startswith('#'):
        title = lines.pop(0).lstrip('#').strip()
    rows = [[c.strip() for c in l.split('|')] for l in lines]
    if len(rows) < 2:
        return ''
    return _json.dumps({'title': title, 'columns': rows[0], 'rows': rows[1:]})


def _authority_code_for(scope, state):
    """News scope → counselling-authority code (MCC for All-India, else the state's body)."""
    from pg_admin.authorities import all_authorities
    if scope == 'all_india':
        return 'mcc'
    st = (state or '').strip().lower()
    for a in all_authorities():
        if a['kind'] == 'state' and a['state'].strip().lower() == st:
            return a['code']
    return ''


def _require_admin():
    u = get_user()
    return u if (u and u.get('is_admin')) else None


def _s(v):
    return (str(v).strip() if v is not None else '')


@login_required
def news_admin():
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    items = []
    prefill = None
    try:
        try:
            conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS source_url TEXT DEFAULT ''")
        except Exception:
            conn.rollback()
        # "Add to News" from the News Inbox → pre-fill the form (founder 2026-10-08)
        inbox_id = _s(request.args.get('inbox'))
        if inbox_id.isdigit():
            try:
                from pg_admin import news_scraper as _NS
                r = conn.execute("SELECT * FROM pg_news_inbox WHERE id = ?", (int(inbox_id),)).fetchone()
                if r:
                    r = dict(r)
                    src = _NS.SOURCES.get(r['source_code']) or {}
                    import json as _json
                    try: dr = _json.loads(r.get('draft_json') or '{}') or {}
                    except Exception: dr = {}
                    prefill = {'inbox_id': r['id'], 'heading': dr.get('headline') or r['title'], 'source_url': r['url'],
                               'kind': r['kind'], 'status': r['status'],
                               'authority': src.get('news_authority') or '__all__',
                               'source_label': src.get('label') or r['source_code'],
                               'news_date': r['notice_date'].strftime('%Y-%m-%d') if r.get('notice_date') else '',
                               'has_pdf': bool(r.get('pdf_data')), 'drafted': bool(dr),
                               'body_text': dr.get('article') or '', 'summary': dr.get('summary') or '',
                               'category': dr.get('category') or '',
                               'dates': {k: (v or {}).get('date', '') for k, v in (dr.get('dates') or {}).items()},
                               'times': {k: (v or {}).get('time', '') for k, v in (dr.get('dates') or {}).items()},
                               'round': next((v.get('round') for v in (dr.get('dates') or {}).values() if (v or {}).get('round')), ''),
                               'quotes': {k: (v or {}).get('quote', '') for k, v in (dr.get('dates') or {}).items()},
                               'applies_to': dr.get('applies_to') or '', 'action': dr.get('action') or '',
                               'schedule_text': schedule_to_text(dr.get('schedule')),
                               'events': dr.get('events') or [], 'news_id': ''}
                    # Already posted (and not deleted) → this opens THAT news to update it.
                    if r.get('news_id'):
                        from pg_admin.routes.api_news import ensure_news_seo_cols as _ens
                        _ens(conn)
                        live = conn.execute("SELECT id FROM pg_news WHERE id = ? AND deleted_at IS NULL",
                                            (r['news_id'],)).fetchone()
                        if live:
                            prefill['news_id'] = live['id']
            except Exception as e:
                logging.warning("news_admin inbox prefill: %s", e)
                conn.rollback()
        from pg_admin.routes.api_news import ensure_news_seo_cols
        ensure_news_seo_cols(conn)
        items = [dict(r) for r in conn.execute(
            "SELECT id, scope, state, body_label, heading, body_text, source_url, "
            "COALESCE(category,'') AS category, COALESCE(summary,'') AS summary, COALESCE(key_dates,'') AS key_dates, "
            "COALESCE(schedule,'') AS schedule, "
            "(pdf_data IS NOT NULL) AS has_pdf, pdf_name, is_published, published_at, created_by, created_at, "
            "COALESCE(source,'manual') AS source, deleted_at, COALESCE(deleted_by,'') AS deleted_by "
            "FROM pg_news ORDER BY published_at DESC, id DESC").fetchall()]
    except Exception as e:
        logging.error("news_admin list: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    for it in items:
        try:
            import json as _json
            _kd = _json.loads(it.get('key_dates') or '{}') or {}
            it['key_dates_d'] = {k: (v or {}).get('date', '') for k, v in _kd.items()}
            it['key_times_d'] = {k: (v or {}).get('time', '') for k, v in _kd.items() if (v or {}).get('time')}
            it['key_round'] = next((v.get('round') for v in _kd.values() if (v or {}).get('round')), '')
        except Exception:
            it['key_dates_d'] = {}
        try:
            from pg_admin.routes.api_news import parse_schedule
            it['schedule_text'] = schedule_to_text(parse_schedule(it.get('schedule')))
        except Exception:
            it['schedule_text'] = ''
    deleted = [it for it in items if it.get('deleted_at')]
    items = [it for it in items if not it.get('deleted_at')]
    from pg_admin.data.calendar import EVENT_LABELS
    return render_template('pg_admin/news.html', items=items, prefill=prefill, deleted=deleted,
                           event_labels=EVENT_LABELS,
                           categories=NEWS_CATEGORIES, date_fields=NEWS_DATE_FIELDS,
                           states=_canonical_states(), active_section='goocampus_in')


@login_required
def news_save():
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    news_id = _s(request.form.get('news_id'))
    # New single "Counselling Authority" dropdown: '__all__' or 'state:<State>'.
    authority = _s(request.form.get('authority'))
    if authority:
        if authority == '__all__':
            scope, state, body_label = 'all_india', '', 'All India MCC'
        elif authority.startswith('state:'):
            state = authority[6:].strip()
            scope, body_label = 'state', state
        else:
            scope, state, body_label = 'all_india', '', 'All India MCC'
    else:
        # Backward-compat with the old scope/state/label fields.
        scope = _s(request.form.get('scope')) or 'all_india'
        state = _s(request.form.get('state')) if scope == 'state' else ''
        body_label = _s(request.form.get('body_label')) or ('All India MCC' if scope == 'all_india' else state)
    heading = _s(request.form.get('heading'))
    body_text = (request.form.get('body_text') or '').strip()
    news_date = _s(request.form.get('news_date'))            # YYYY-MM-DD, optional (else today)
    from datetime import datetime as _dt
    pub_dt = None
    if news_date:
        try:
            pub_dt = _dt.strptime(news_date, '%Y-%m-%d')
        except ValueError:
            pub_dt = None
    source_url = _s(request.form.get('source_url'))          # official link (optional)
    # Default published; only an explicit '0'/'off' unpublishes. (bool, not int → BOOLEAN col)
    is_published = False if request.form.get('is_published') in ('0', 'off') else True
    # Email this update to all registered doctors? (founder 2026-10-06)
    send_alert = request.form.get('send_alert') in ('1', 'on', 'true', 'yes')
    inbox_id = _s(request.form.get('inbox_id'))
    inbox_id = int(inbox_id) if inbox_id.isdigit() else None
    add_events = request.form.get('add_events') in ('1', 'on')
    category = _s(request.form.get('category'))
    category = category if category in dict(NEWS_CATEGORIES) else ''
    summary = _s(request.form.get('summary'))[:300]
    import json as _json
    key_dates = {}
    for k, _lbl in NEWS_DATE_FIELDS:
        v = _s(request.form.get('kd_' + k))
        if v:
            from pg_admin.data.calendar import norm_round
            ent = {'date': v[:10]}
            t = _s(request.form.get('kdt_' + k))[:40]
            if t:
                ent['time'] = t
            rd = norm_round(request.form.get('kd_round'))
            if rd:
                ent['round'] = rd
            key_dates[k] = ent
    key_dates_json = _json.dumps(key_dates) if key_dates else ''
    schedule_json = text_to_schedule(request.form.get('schedule_text'))
    save_brochure = request.form.get('save_brochure') in ('1', 'on')

    if not heading:
        flash('Please enter a heading.', 'error')
        return redirect(url_for('pg_news_admin'))
    if scope == 'state' and not state:
        flash('Please choose a state for a state-scoped update.', 'error')
        return redirect(url_for('pg_news_admin'))
    if not body_text and not (request.files.get('pdf_file') and request.files.get('pdf_file').filename):
        # allow text-less if an existing item already has a PDF/text and we're editing
        if not news_id and not (inbox_id and source_url):     # an inbox notice: heading + official link is enough
            flash('Add some news text or attach a PDF.', 'error')
            return redirect(url_for('pg_news_admin'))

    pdf_bytes = None; pdf_name = ''; pdf_ctype = 'application/pdf'
    pf = request.files.get('pdf_file')
    if pf and pf.filename:
        if not pf.filename.lower().endswith('.pdf'):
            flash('The attachment must be a .pdf file.', 'error')
            return redirect(url_for('pg_news_admin'))
        pdf_bytes = pf.read(); pdf_name = pf.filename; pdf_ctype = pf.mimetype or 'application/pdf'
    elif inbox_id and request.form.get('attach_pdf', '1') in ('1', 'on'):
        # Inbox notice that IS a PDF → attach the copy the Mac fetched (the server can't
        # reach the govt sites), else try downloading it.
        data, name_or_err = None, 'no PDF on this notice'
        try:
            _c = get_db()
            _r = _c.execute("SELECT pdf_data, pdf_name FROM pg_news_inbox WHERE id = ?", (inbox_id,)).fetchone()
            _c.close()
            if _r and _r['pdf_data']:
                data, name_or_err = bytes(_r['pdf_data']), (_r['pdf_name'] or 'notice.pdf')
        except Exception as _pe:
            logging.warning("news_save inbox pdf: %s", _pe)
        if not data and source_url.lower().split('?')[0].endswith('.pdf'):
            from pg_admin.news_scraper import fetch_pdf
            data, name_or_err = fetch_pdf(source_url)
        if data:
            pdf_bytes, pdf_name = data, name_or_err
        elif source_url.lower().split('?')[0].endswith('.pdf'):
            flash(f"Posted without the PDF — couldn't download it ({name_or_err}). "
                  "The official link is still on the update; you can attach the PDF via Edit.", 'info')

    user = get_user() or {}
    who = user.get('name') or user.get('emp_code') or 'admin'

    conn = get_db()
    try:
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS source_url TEXT DEFAULT ''")  # cold-start guard
        from pg_admin.routes.api_news import ensure_news_seo_cols
        ensure_news_seo_cols(conn)
        if news_id:
            if pdf_bytes is not None:
                conn.execute(
                    "UPDATE pg_news SET scope=?, state=?, body_label=?, heading=?, body_text=?, source_url=?, "
                    "pdf_name=?, pdf_data=?, pdf_content_type=?, is_published=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (scope, state, body_label, heading, body_text, source_url, pdf_name, pdf_bytes, pdf_ctype,
                     is_published, news_id))
            else:
                conn.execute(
                    "UPDATE pg_news SET scope=?, state=?, body_label=?, heading=?, body_text=?, source_url=?, "
                    "is_published=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (scope, state, body_label, heading, body_text, source_url, is_published, news_id))
            if pub_dt:
                conn.execute("UPDATE pg_news SET published_at = ? WHERE id=?", (pub_dt, news_id))
            flash('Update saved.', 'success')
            conn.execute("UPDATE pg_news SET category = ?, summary = ?, key_dates = ?, schedule = ? WHERE id = ?",
                         (category, summary, key_dates_json, schedule_json, news_id))
        else:
            news_id = conn.execute(
                "INSERT INTO pg_news (scope, state, body_label, heading, body_text, source_url, pdf_name, "
                "pdf_data, pdf_content_type, is_published, created_by, published_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (scope, state, body_label, heading, body_text, source_url, pdf_name, pdf_bytes, pdf_ctype,
                 is_published, who, (pub_dt or _dt.utcnow()))).fetchone()['id']
            flash('News posted.', 'success')
            conn.execute("UPDATE pg_news SET category = ?, summary = ?, key_dates = ?, schedule = ?, "
                         "source = ?, inbox_id = ? WHERE id = ?",
                         (category, summary, key_dates_json, schedule_json,
                          'ai_inbox' if inbox_id else 'manual', inbox_id, news_id))
            if inbox_id:
                conn.execute("UPDATE pg_news_inbox SET status='posted', news_id=?, reviewed_by=?, "
                             "reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (news_id, who, inbox_id))
        # Counselling Calendar: the AI-extracted dated steps of this notice (posting = review).
        cal_msg = ''
        if add_events and inbox_id:
            try:
                _ir = conn.execute("SELECT draft_json FROM pg_news_inbox WHERE id = ?", (inbox_id,)).fetchone()
                _ev = (_json.loads(_ir['draft_json'] or '{}') or {}).get('events') if _ir else None
                if _ev:
                    from pg_admin.data.calendar import ensure_calendar_table, clean_events, replace_events_for_news
                    ensure_calendar_table(conn)
                    _code = _authority_code_for(scope, state)
                    if _code:
                        n_ev = replace_events_for_news(conn, _code, int(news_id), inbox_id, clean_events(_ev), who)
                        cal_msg = f'{n_ev} date(s) added to the Counselling Calendar.'
            except Exception as _ce:
                logging.warning("news_save calendar: %s", _ce)
        # Information bulletin / brochure → also the authority's MAIN brochure document, so
        # registered doctors can download it from the dashboard. (founder 2026-10-09)
        brochure_msg = ''
        if save_brochure:
            code = _authority_code_for(scope, state)
            pdf_row = conn.execute("SELECT pdf_name, pdf_data, pdf_content_type FROM pg_news WHERE id = ?",
                                   (news_id,)).fetchone()
            if not code:
                brochure_msg = 'Not saved as a brochure — no counselling authority matches this state yet.'
            elif not (pdf_row and pdf_row['pdf_data']):
                brochure_msg = 'Not saved as a brochure — attach the bulletin PDF first.'
            else:
                from pg_admin.authorities import get_authority
                conn.execute("ALTER TABLE pg_authority_docs ADD COLUMN IF NOT EXISTS is_main BOOLEAN DEFAULT FALSE")
                conn.execute("UPDATE pg_authority_docs SET is_main = FALSE WHERE authority_code = ? AND category = 'brochure'",
                             (code,))
                existing = conn.execute("SELECT id FROM pg_authority_docs WHERE authority_code = ? AND category = 'brochure' "
                                        "AND file_name = ? LIMIT 1", (code, pdf_row['pdf_name'] or '')).fetchone()
                _ddate = (pub_dt or _dt.utcnow()).strftime('%Y-%m-%d')
                if existing:
                    conn.execute("UPDATE pg_authority_docs SET is_main = TRUE, title = ?, doc_date = ?, is_published = TRUE, "
                                 "updated_at = CURRENT_TIMESTAMP WHERE id = ?", (heading, _ddate, existing['id']))
                else:
                    conn.execute(
                        "INSERT INTO pg_authority_docs (authority_code, authority_name, category, title, doc_date, note, "
                        "file_name, file_data, file_content_type, is_published, uploaded_by, is_main) "
                        "VALUES (?,?,'brochure',?,?,?,?,?,?,TRUE,?,TRUE)",
                        (code, (get_authority(code) or {}).get('name', ''), heading, _ddate, summary,
                         pdf_row['pdf_name'] or 'brochure.pdf', pdf_row['pdf_data'],
                         pdf_row['pdf_content_type'] or 'application/pdf', who))
                brochure_msg = f"Also saved as the main brochure for {(get_authority(code) or {}).get('name', code)} — doctors can download it from the dashboard."
        conn.commit()
        saved_ok = True
        if brochure_msg:
            flash(brochure_msg, 'success' if brochure_msg.startswith('Also') else 'info')
        if cal_msg:
            flash(cal_msg, 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news_save: %s", e)
        flash('Could not save. Please try again.', 'error')
        saved_ok = False
    finally:
        conn.close()

    # Email alert to all registered doctors (only on a published item, when asked).
    try: _blast_id = int(news_id)
    except (TypeError, ValueError): _blast_id = None
    if saved_ok and send_alert and is_published and _blast_id:
        try:
            from pg_admin.news_email import trigger_news_blast, recipient_count
            n = recipient_count()
            trigger_news_blast(_blast_id)
            flash(f'Emailing this update to {n} registered users in the background…'
                  if n is not None else 'Emailing this update to all registered users in the background…',
                  'success')
        except Exception as e:
            logging.error("news_save: email alert failed to start: %s", e)
            flash('Saved, but the email alert could not be started.', 'error')
    if inbox_id and saved_ok:
        return redirect(url_for('pg_news_inbox'))
    return redirect(url_for('pg_news_admin'))


@login_required
def news_test_email():
    """Send a TEST of a posted news item (both free + paid views) to one address, so the
    founder can preview the real email in an inbox before blasting all users. Safe — goes
    only to the typed address. (founder 2026-10-06)"""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('pg_news_admin'))
    to = _s(request.form.get('to')).strip()
    if not to or '@' not in to:
        flash('Enter a valid email address to send the test to.', 'error')
        return redirect(url_for('pg_news_admin'))
    try: nid = int(_s(request.form.get('news_id')))
    except (TypeError, ValueError): nid = None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, scope, state, body_label, heading, body_text, source_url, pdf_name, "
            "COALESCE(category,'') AS category, COALESCE(summary,'') AS summary, COALESCE(key_dates,'') AS key_dates, "
            "COALESCE(schedule,'') AS schedule, "
            "is_published, published_at FROM pg_news WHERE id = ?", (nid,)).fetchone() if nid else None
    finally:
        conn.close()
    if not row:
        flash('Could not find that update to test.', 'error')
        return redirect(url_for('pg_news_admin'))
    news = dict(row)
    try:
        from pg_admin.news_email import build_news_email_html, news_subject
        from email_utils import send_email
        base = ("[TEST] " + news_subject(news))[:150]
        ok_free = send_email([to], base + " — FREE-user view", build_news_email_html(news, True))
        ok_paid = send_email([to], base + " — PAID-user view",
                             build_news_email_html(news, False, name="Rahul Sharma"))
        if ok_free or ok_paid:
            flash(f'Test email sent to {to} (free + paid views). Check that inbox.', 'success')
        else:
            flash('Test could not be sent — email service may be unconfigured on the server.', 'error')
    except Exception as e:
        logging.error("news_test_email: %s", e)
        flash('Test could not be sent. Please try again.', 'error')
    return redirect(url_for('pg_news_admin'))


@login_required
def news_send_alert():
    """Re-send the email alert for a posted item to everyone, on demand (regardless of the
    original checkbox). Lets the founder push a news update out again. (founder 2026-10-06)"""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('pg_news_admin'))
    try: nid = int(_s(request.form.get('news_id')))
    except (TypeError, ValueError): nid = None
    if not nid:
        flash('Could not find that update.', 'error'); return redirect(url_for('pg_news_admin'))
    try:
        from pg_admin.news_email import trigger_news_blast, recipient_count
        n = recipient_count()
        trigger_news_blast(nid)
        flash(f'Email alert is being sent to {n} recipient(s) in the background…'
              if n is not None else 'Email alert is being sent in the background…', 'success')
    except Exception as e:
        logging.error("news_send_alert: %s", e)
        flash('Could not start the email alert.', 'error')
    return redirect(url_for('pg_news_admin'))


@login_required
def news_recipients_diag():
    """Diagnostic: show exactly how many people a news blast reaches + the gaps (accounts
    with no email can't be mailed). ?check=<email> tells you if that address is included."""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('pg_news_admin'))
    check = _s(request.args.get('check'))
    conn = get_db()
    try:
        from pg_admin.news_email import recipients_breakdown
        b = recipients_breakdown(conn, check)
    except Exception as e:
        logging.error("news_recipients_diag: %s", e)
        b = {}
    finally:
        try: conn.close()
        except Exception: pass

    def esc(v):
        s = '' if v is None else str(v)
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    chk = ''
    if b.get('check_email'):
        yes = b.get('check_in_list')
        chk = (f"<p style='font-size:15px;'>Is <b>{esc(b['check_email'])}</b> in the blast list? "
               f"<b style='color:{'#16a34a' if yes else '#dc2626'}'>{'YES — will receive' if yes else 'NO — not a recipient (no email on file, or a team-only account)'}</b></p>")
    html = f"""<div style="font-family:system-ui;max-width:760px;margin:30px auto;padding:0 16px;">
<h2>News email — who it reaches</h2>
<p style="font-size:15px;">A news blast is being sent to <b>{esc(b.get('total','?'))}</b> unique email address(es):
<br>• {esc(b.get('paid_or_staff','?'))} paid doctors / internal / staff (clean update)
<br>• {esc(b.get('free','?'))} free doctors (with upgrade banner)</p>
<hr>
<p style="font-size:14px;color:#475569;">Why some don't get it — an account with no email can't be mailed:</p>
<ul style="font-size:14px;color:#475569;">
<li>Registered doctor accounts total: <b>{esc(b.get('pg_users_total','?'))}</b>, of which <b>{esc(b.get('pg_users_no_email','?'))}</b> have <b>no email</b> (mobile-OTP signup) → skipped.</li>
<li>Team-member accounts: <b>{esc(b.get('pg_team','?'))}</b>, of which <b>{esc(b.get('pg_team_no_email','?'))}</b> have no email on their doctor account.</li>
<li>Active staff (employees) with an email: <b>{esc(b.get('staff_with_email','?'))}</b> → these DO receive it.</li>
</ul>
<form method="GET" style="margin-top:14px;">Check an email: <input name="check" value="{esc(b.get('check_email',''))}" style="padding:7px;width:280px;"> <button>Check</button></form>
{chk}
<p style="margin-top:16px;"><a href="/admin/pg/news" style="color:#F58220;">← Back to News</a></p>
</div>"""
    return html


@login_required
def news_toggle():
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    nid = _s(request.form.get('news_id'))
    conn = get_db()
    try:
        conn.execute("UPDATE pg_news SET is_published = NOT COALESCE(is_published, TRUE), "
                     "updated_at=CURRENT_TIMESTAMP WHERE id=?", (nid,))
        conn.commit()
        flash('Visibility updated.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news_toggle: %s", e)
        flash('Could not update.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_news_admin'))


@login_required
def news_delete():
    """Move to Deleted (soft delete — founder 2026-10-09: nothing lost by mistake). Hidden
    from the site + emails; Restore brings it back. If it came from the News Inbox, that
    notice goes back to New (noted) so it can be posted again."""
    user = _require_admin()
    if not user:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    nid = _s(request.form.get('news_id'))
    who = user.get('name') or user.get('emp_code') or 'admin'
    conn = get_db()
    try:
        from pg_admin.data.calendar import ensure_calendar_table
        from pg_admin.news_scraper import ensure_news_inbox_tables
        ensure_calendar_table(conn); ensure_news_inbox_tables(conn)
        from pg_admin.routes.api_news import ensure_news_seo_cols
        ensure_news_seo_cols(conn)
        conn.execute("UPDATE pg_news SET deleted_at = CURRENT_TIMESTAMP, deleted_by = ?, is_published = FALSE "
                     "WHERE id = ?", (who, nid))
        try:
            from datetime import datetime, timedelta
            ist = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%d %b %Y, %I:%M %p')
            conn.execute("UPDATE pg_news_inbox SET status = 'new', news_id = NULL, "
                         "history_note = ? WHERE news_id = ?",
                         (f'Was posted as news #{nid}; removed from the news section on {ist} IST by {who}.', nid))
            conn.execute("UPDATE pg_counselling_events SET is_active = FALSE WHERE news_id = ?", (nid,))
        except Exception:
            conn.rollback()
            conn.execute("UPDATE pg_news SET deleted_at = CURRENT_TIMESTAMP, deleted_by = ?, is_published = FALSE "
                         "WHERE id = ?", (who, nid))
        conn.commit()
        flash('Moved to Deleted — hidden from the website. You can Restore it from the Deleted list below.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news_delete: %s", e)
        flash('Could not delete.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_news_admin'))


@login_required
def news_restore():
    user = _require_admin()
    if not user:
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    nid = _s(request.form.get('news_id'))
    conn = get_db()
    try:
        from pg_admin.data.calendar import ensure_calendar_table
        from pg_admin.news_scraper import ensure_news_inbox_tables
        ensure_calendar_table(conn); ensure_news_inbox_tables(conn)
        conn.execute("UPDATE pg_news SET deleted_at = NULL, deleted_by = '', is_published = TRUE, "
                     "updated_at = CURRENT_TIMESTAMP WHERE id = ?", (nid,))
        try:
            conn.execute("UPDATE pg_news_inbox SET status = 'posted', news_id = ?, history_note = '' "
                         "WHERE id = (SELECT inbox_id FROM pg_news WHERE id = ?) AND status <> 'posted'", (nid, nid))
            conn.execute("UPDATE pg_counselling_events SET is_active = TRUE WHERE news_id = ?", (nid,))
        except Exception:
            conn.rollback()
            conn.execute("UPDATE pg_news SET deleted_at = NULL, deleted_by = '', is_published = TRUE WHERE id = ?", (nid,))
        conn.commit()
        flash('Restored — the update is live again.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news_restore: %s", e)
        flash('Could not restore.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_news_admin'))


@login_required
def news_purge():
    """Delete permanently — only from the Deleted list."""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    nid = _s(request.form.get('news_id'))
    conn = get_db()
    try:
        from pg_admin.data.calendar import ensure_calendar_table
        from pg_admin.news_scraper import ensure_news_inbox_tables
        ensure_calendar_table(conn); ensure_news_inbox_tables(conn)
        conn.execute("DELETE FROM pg_news WHERE id = ? AND deleted_at IS NOT NULL", (nid,))
        try:
            conn.execute("DELETE FROM pg_counselling_events WHERE news_id = ?", (nid,))
        except Exception:
            conn.rollback()
            conn.execute("DELETE FROM pg_news WHERE id = ? AND deleted_at IS NOT NULL", (nid,))
        conn.commit()
        flash('Deleted permanently.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news_purge: %s", e)
        flash('Could not delete.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_news_admin'))


@login_required
def news_pdf_admin():
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    nid = _s(request.args.get('id'))
    conn = get_db()
    try:
        row = conn.execute("SELECT pdf_name, pdf_data, pdf_content_type FROM pg_news WHERE id=?",
                           (nid,)).fetchone()
    finally:
        conn.close()
    if not row or not row['pdf_data']:
        flash('No PDF on that item.', 'error')
        return redirect(url_for('pg_news_admin'))
    return Response(bytes(row['pdf_data']), mimetype=row['pdf_content_type'] or 'application/pdf',
                    headers={'Content-Disposition': f'inline; filename="{row["pdf_name"] or "news.pdf"}"'})
