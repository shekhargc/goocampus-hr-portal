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


NEWS_CATEGORIES = [('registration', 'Registration'), ('choice_filling', 'Choice filling'),
                   ('seat_allotment', 'Seat allotment / result'), ('fee_payment', 'Fee payment'),
                   ('reporting', 'Reporting to college'), ('notification', 'Notification / schedule'),
                   ('other', 'Other')]
NEWS_DATE_FIELDS = [('registration_start', 'Registration starts'), ('registration_end', 'Registration last date'),
                    ('choice_filling_start', 'Choice filling starts'), ('choice_filling_end', 'Choice filling last date'),
                    ('payment_last_date', 'Fee payment last date'), ('reporting_last_date', 'Reporting last date'),
                    ('result_date', 'Result / allotment date')]


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
                               'quotes': {k: (v or {}).get('quote', '') for k, v in (dr.get('dates') or {}).items()},
                               'applies_to': dr.get('applies_to') or '', 'action': dr.get('action') or ''}
            except Exception as e:
                logging.warning("news_admin inbox prefill: %s", e)
                conn.rollback()
        from pg_admin.routes.api_news import ensure_news_seo_cols
        ensure_news_seo_cols(conn)
        items = [dict(r) for r in conn.execute(
            "SELECT id, scope, state, body_label, heading, body_text, source_url, "
            "COALESCE(category,'') AS category, COALESCE(summary,'') AS summary, COALESCE(key_dates,'') AS key_dates, "
            "(pdf_data IS NOT NULL) AS has_pdf, pdf_name, is_published, published_at, created_by "
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
            it['key_dates_d'] = {k: (v or {}).get('date', '') for k, v in (_json.loads(it.get('key_dates') or '{}') or {}).items()}
        except Exception:
            it['key_dates_d'] = {}
    return render_template('pg_admin/news.html', items=items, prefill=prefill,
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
    inbox_id = int(inbox_id) if inbox_id.isdigit() and not news_id else None
    category = _s(request.form.get('category'))
    category = category if category in dict(NEWS_CATEGORIES) else ''
    summary = _s(request.form.get('summary'))[:300]
    import json as _json
    key_dates = {}
    for k, _lbl in NEWS_DATE_FIELDS:
        v = _s(request.form.get('kd_' + k))
        if v:
            key_dates[k] = {'date': v[:10]}
    key_dates_json = _json.dumps(key_dates) if key_dates else ''

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
            conn.execute("UPDATE pg_news SET category = ?, summary = ?, key_dates = ? WHERE id = ?",
                         (category, summary, key_dates_json, news_id))
        else:
            news_id = conn.execute(
                "INSERT INTO pg_news (scope, state, body_label, heading, body_text, source_url, pdf_name, "
                "pdf_data, pdf_content_type, is_published, created_by, published_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (scope, state, body_label, heading, body_text, source_url, pdf_name, pdf_bytes, pdf_ctype,
                 is_published, who, (pub_dt or _dt.utcnow()))).fetchone()['id']
            flash('News posted.', 'success')
            conn.execute("UPDATE pg_news SET category = ?, summary = ?, key_dates = ? WHERE id = ?",
                         (category, summary, key_dates_json, news_id))
            if inbox_id:
                conn.execute("UPDATE pg_news_inbox SET status='posted', news_id=?, reviewed_by=?, "
                             "reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (news_id, who, inbox_id))
        conn.commit()
        saved_ok = True
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
            "is_published, published_at FROM pg_news WHERE id = ?", (nid,)).fetchone() if nid else None
    finally:
        conn.close()
    if not row:
        flash('Could not find that update to test.', 'error')
        return redirect(url_for('pg_news_admin'))
    news = dict(row)
    try:
        from pg_admin.news_email import build_news_email_html
        from email_utils import send_email
        base = f"[TEST] 📢 NEET-PG Update: {(news.get('heading') or '').strip()}"[:150]
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
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    nid = _s(request.form.get('news_id'))
    conn = get_db()
    try:
        conn.execute("DELETE FROM pg_news WHERE id=?", (nid,))
        conn.commit()
        flash('News deleted.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news_delete: %s", e)
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
