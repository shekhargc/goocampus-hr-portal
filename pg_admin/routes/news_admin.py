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
    try:
        items = conn.execute(
            "SELECT id, scope, state, body_label, heading, "
            "(pdf_data IS NOT NULL) AS has_pdf, pdf_name, is_published, published_at, created_by "
            "FROM pg_news ORDER BY published_at DESC, id DESC").fetchall()
    except Exception as e:
        logging.error("news_admin list: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    return render_template('pg_admin/news.html', items=items,
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
    # Default published; only an explicit '0'/'off' unpublishes.
    is_published = 0 if request.form.get('is_published') in ('0', 'off') else 1

    if not heading:
        flash('Please enter a heading.', 'error')
        return redirect(url_for('pg_news_admin'))
    if scope == 'state' and not state:
        flash('Please choose a state for a state-scoped update.', 'error')
        return redirect(url_for('pg_news_admin'))
    if not body_text and not (request.files.get('pdf_file') and request.files.get('pdf_file').filename):
        # allow text-less if an existing item already has a PDF/text and we're editing
        if not news_id:
            flash('Add some news text or attach a PDF.', 'error')
            return redirect(url_for('pg_news_admin'))

    pdf_bytes = None; pdf_name = ''; pdf_ctype = 'application/pdf'
    pf = request.files.get('pdf_file')
    if pf and pf.filename:
        if not pf.filename.lower().endswith('.pdf'):
            flash('The attachment must be a .pdf file.', 'error')
            return redirect(url_for('pg_news_admin'))
        pdf_bytes = pf.read(); pdf_name = pf.filename; pdf_ctype = pf.mimetype or 'application/pdf'

    user = get_user() or {}
    who = user.get('name') or user.get('emp_code') or 'admin'

    conn = get_db()
    try:
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS source_url TEXT DEFAULT ''")  # cold-start guard
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
        else:
            conn.execute(
                "INSERT INTO pg_news (scope, state, body_label, heading, body_text, source_url, pdf_name, "
                "pdf_data, pdf_content_type, is_published, created_by, published_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (scope, state, body_label, heading, body_text, source_url, pdf_name, pdf_bytes, pdf_ctype,
                 is_published, who, (pub_dt or _dt.utcnow())))
            flash('News posted.', 'success')
        conn.commit()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("news_save: %s", e)
        flash('Could not save. Please try again.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_news_admin'))


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
