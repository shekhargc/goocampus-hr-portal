"""Admin hub: manage per-authority counselling content (founder 2026-10-06).

One screen (/admin/pg/authorities): pick a counselling authority, then upload and
manage its documents by category (Registration Documents, Formats & Annexures, Fee
Structure, Seat Matrix, Other/Notifications). Files are stored as BYTEA. Quick links
to post News / upload the Seat Matrix for the same authority live alongside. True-admin
gated, like the other PG-admin screens.
"""

import logging
from flask import render_template, request, redirect, url_for, flash, Response, session
from db import get_db
from core.users import get_user
from core.auth import login_required
from pg_admin.authorities import (all_authorities, get_authority, DOC_CATEGORIES,
                                   category_label, valid_category)
from pg_admin.data.authority_docs_tables import ensure_pg_authority_docs


def _require_admin():
    return bool(session.get('is_admin'))


def _s(v):
    return (v or '').strip()


@login_required
def authorities_admin():
    """Pick an authority (?code=) and manage its documents by category."""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    code = _s(request.args.get('code'))
    authority = get_authority(code) if code else None
    conn = get_db()
    docs_by_cat = {c: [] for c, _ in DOC_CATEGORIES}
    counts, waiting_by_auth, waiting = {}, {}, []
    try:
        ensure_pg_authority_docs(conn)
        from pg_admin.data.main_brochures import ensure_cols as _mb_cols
        _mb_cols(conn)
        # Per-authority document counts (for the picker badges) + auto-filed docs still waiting.
        for r in conn.execute(
                "SELECT authority_code, COUNT(*) AS n, "
                "SUM(CASE WHEN COALESCE(review_pending, FALSE) THEN 1 ELSE 0 END) AS w "
                "FROM pg_authority_docs GROUP BY authority_code").fetchall():
            counts[r['authority_code']] = r['n']
            if r['w']:
                waiting_by_auth[r['authority_code']] = int(r['w'])
        if authority:
            for r in conn.execute(
                    "SELECT id, category, title, doc_date, note, body_text, file_name, is_published, "
                    "uploaded_by, uploaded_at, COALESCE(review_pending, FALSE) AS review_pending, "
                    "auto_inbox_id, COALESCE(source_url,'') AS source_url, COALESCE(is_main, FALSE) AS is_main, "
                    "COALESCE(main_label,'') AS main_label "
                    "FROM pg_authority_docs WHERE authority_code=? "
                    "ORDER BY category, sort_order, id DESC", (authority['code'],)).fetchall():
                r = dict(r)
                if r['review_pending']:
                    waiting.append(r)
                else:
                    docs_by_cat.setdefault(r['category'], []).append(r)
    except Exception as e:
        logging.error("authorities_admin: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        conn.close()
    return render_template('pg_admin/authorities.html',
                           authorities=all_authorities(), authority=authority,
                           categories=DOC_CATEGORIES, docs_by_cat=docs_by_cat,
                           counts=counts, waiting=waiting, waiting_by_auth=waiting_by_auth,
                           cat_labels=dict(DOC_CATEGORIES),
                           has_main=any(d.get('is_main') and d.get('is_published') for d in docs_by_cat.get('brochure', [])),
                           main_n=sum(1 for d in docs_by_cat.get('brochure', []) if d.get('is_main')),
                           label_suggestions=__import__('pg_admin.data.main_brochures', fromlist=['x']).LABEL_SUGGESTIONS,
                           guess=__import__('pg_admin.data.main_brochures', fromlist=['x']).guess_label,
                           active_section='goocampus_in')


@login_required
def authority_doc_save():
    """Upload one document for an authority + category."""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    code = _s(request.form.get('authority_code'))
    authority = get_authority(code)
    if not authority:
        flash('Pick a valid authority.', 'error')
        return redirect(url_for('pg_authorities_admin'))
    category = _s(request.form.get('category'))
    if not valid_category(category):
        flash('Pick a valid category.', 'error')
        return redirect(url_for('pg_authorities_admin', code=code))
    title = _s(request.form.get('title'))
    doc_date = _s(request.form.get('doc_date'))
    note = _s(request.form.get('note'))
    body_text = _s(request.form.get('body_text'))      # typed list / details (optional)
    f = request.files.get('doc_file')
    has_file = bool(f and f.filename)
    # A document needs a file OR a typed list — e.g. a registration-document checklist can
    # be typed in without a PDF. (founder 2026-10-06)
    if not has_file and not body_text:
        flash('Add a file or type the list/details (one is required).', 'error')
        return redirect(url_for('pg_authorities_admin', code=code))
    data = None; fname = ''; ctype = 'application/octet-stream'
    if has_file:
        data = f.read()
        if not data:
            flash('That file looks empty.', 'error')
            return redirect(url_for('pg_authorities_admin', code=code))
        if len(data) > 25 * 1024 * 1024:
            flash('File too large (max 25 MB).', 'error')
            return redirect(url_for('pg_authorities_admin', code=code))
        fname = f.filename
        ctype = f.mimetype or 'application/octet-stream'
    if not title:
        title = (fname.rsplit('.', 1)[0] if fname else category_label(category))
    who = (get_user() or {}).get('name') or (get_user() or {}).get('emp_code') or 'admin'
    conn = get_db()
    try:
        ensure_pg_authority_docs(conn)
        # Refuse a duplicate file name for the same authority (founder 2026-10-06).
        if fname:
            dup = conn.execute(
                "SELECT 1 FROM pg_authority_docs WHERE authority_code = ? "
                "AND LOWER(TRIM(file_name)) = LOWER(TRIM(?)) LIMIT 1",
                (authority['code'], fname)).fetchone()
            if dup:
                flash(f'A file named "{fname}" is already uploaded for {authority["name"]}. '
                      f'Rename the file or delete the existing one first.', 'error')
                return redirect(url_for('pg_authorities_admin', code=code))
        conn.execute(
            "INSERT INTO pg_authority_docs (authority_code, authority_name, category, title, doc_date, "
            "note, body_text, file_name, file_data, file_content_type, uploaded_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (authority['code'], authority['name'], category, title, doc_date, note, body_text,
             fname, data, ctype, who))
        conn.commit()
        flash(f'Saved "{title}" to {category_label(category)}.', 'success')
    except Exception as e:
        logging.error("authority_doc_save: %s", e)
        try: conn.rollback()
        except Exception: pass
        flash('Could not upload. Please try again.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_authorities_admin', code=code))


@login_required
def authority_doc_toggle():
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    did = _s(request.form.get('doc_id'))
    code = _s(request.form.get('authority_code'))
    conn = get_db()
    try:
        conn.execute("UPDATE pg_authority_docs SET is_published = NOT COALESCE(is_published, TRUE), "
                     "review_pending = FALSE, updated_at=CURRENT_TIMESTAMP WHERE id=?", (did,))
        conn.commit()
        flash('Visibility updated.', 'success')
    except Exception as e:
        logging.error("authority_doc_toggle: %s", e)
        try: conn.rollback()
        except Exception: pass
        flash('Could not update.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_authorities_admin', code=code))


@login_required
def authority_doc_delete():
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    did = _s(request.form.get('doc_id'))
    code = _s(request.form.get('authority_code'))
    conn = get_db()
    try:
        r = conn.execute("SELECT auto_inbox_id FROM pg_authority_docs WHERE id=?", (did,)).fetchone()
        if r and r['auto_inbox_id']:
            from pg_admin.data.auto_docs import ensure_cols
            ensure_cols(conn)
            conn.execute("UPDATE pg_news_inbox SET doc_rejected = TRUE WHERE id = ?", (r['auto_inbox_id'],))
        conn.execute("DELETE FROM pg_authority_docs WHERE id=?", (did,))
        conn.commit()
        flash('Document deleted.', 'success')
    except Exception as e:
        logging.error("authority_doc_delete: %s", e)
        try: conn.rollback()
        except Exception: pass
        flash('Could not delete.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_authorities_admin', code=code))


@login_required
def authority_doc_file_admin(doc_id):
    """Admin preview/download of a stored document (any publish state)."""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    conn = get_db()
    try:
        row = conn.execute("SELECT file_name, file_data, file_content_type "
                           "FROM pg_authority_docs WHERE id=?", (doc_id,)).fetchone()
    except Exception as e:
        logging.error("authority_doc_file_admin: %s", e); row = None
    finally:
        conn.close()
    if not row or not row['file_data']:
        flash('File not found.', 'error'); return redirect(url_for('pg_authorities_admin'))
    return Response(bytes(row['file_data']),
                    mimetype=row['file_content_type'] or 'application/octet-stream',
                    headers={'Content-Disposition': f'inline; filename="{row["file_name"] or "document"}"'})


def _publish(conn, ids, who, make_main=False, main_label=None):
    """Publish auto-filed documents. A brochure becomes the authority's MAIN brochure when it has none."""
    n = 0
    for did in ids:
        r = conn.execute("SELECT id, authority_code, category FROM pg_authority_docs WHERE id=?", (did,)).fetchone()
        if not r:
            continue
        conn.execute("UPDATE pg_authority_docs SET is_published = TRUE, review_pending = FALSE, "
                     "updated_at = CURRENT_TIMESTAMP WHERE id=?", (did,))
        if r['category'] == 'brochure':
            from pg_admin.data.main_brochures import set_main
            first = not conn.execute("SELECT 1 FROM pg_authority_docs WHERE authority_code=? AND category='brochure' "
                                     "AND COALESCE(is_main,FALSE) AND id <> ? LIMIT 1", (r['authority_code'], did)).fetchone()
            if make_main or first:      # ticked, or the authority has no main bulletin yet
                set_main(conn, did, True, main_label)
        n += 1
    return n


@login_required
def authority_doc_publish():
    """Publish one auto-filed document (or all waiting ones for the authority with all=1),
    optionally moving it to another category first."""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    code = _s(request.form.get('authority_code'))
    conn = get_db()
    try:
        if request.form.get('all') == '1':
            ids = [r['id'] for r in conn.execute(
                "SELECT id FROM pg_authority_docs WHERE authority_code=? AND COALESCE(review_pending,FALSE)",
                (code,)).fetchall()]
        else:
            ids = [int(_s(request.form.get('doc_id')) or 0)]
            cat = _s(request.form.get('category'))
            if cat and valid_category(cat):
                conn.execute("UPDATE pg_authority_docs SET category=? WHERE id=?", (cat, ids[0]))
        n = _publish(conn, ids, session.get('name') or 'admin', make_main=request.form.get('make_main') == '1',
                     main_label=(_s(request.form.get('main_label')) or None))
        conn.commit()
        flash(f'Published {n} document(s) — doctors can see them on the dashboard now.', 'success')
    except Exception as e:
        logging.error("authority_doc_publish: %s", e)
        try: conn.rollback()
        except Exception: pass
        flash('Could not publish.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_authorities_admin', code=code))


@login_required
def authority_doc_category():
    """Move a document to another category (e.g. the AI picked the wrong bucket)."""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    code = _s(request.form.get('authority_code'))
    cat = _s(request.form.get('category'))
    conn = get_db()
    try:
        if valid_category(cat):
            conn.execute("UPDATE pg_authority_docs SET category=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (cat, int(_s(request.form.get('doc_id')) or 0)))
            conn.commit()
            flash('Category changed.', 'success')
    except Exception as e:
        logging.error("authority_doc_category: %s", e)
        try: conn.rollback()
        except Exception: pass
        flash('Could not change the category.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_authorities_admin', code=code))


@login_required
def authority_doc_main():
    """Make a brochure a main bulletin (with a short label) or remove it from the mains."""
    if not _require_admin():
        flash('Access denied', 'error'); return redirect(url_for('dashboard'))
    code = _s(request.form.get('authority_code'))
    conn = get_db()
    try:
        from pg_admin.data.main_brochures import set_main
        ok, msg = set_main(conn, int(_s(request.form.get('doc_id')) or 0), request.form.get('on') == '1',
                           _s(request.form.get('main_label')) or None)
        conn.commit()
        flash(msg, 'success' if ok else 'error')
    except Exception as e:
        logging.error("authority_doc_main: %s", e)
        try: conn.rollback()
        except Exception: pass
        flash('Could not update.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_authorities_admin', code=code))
