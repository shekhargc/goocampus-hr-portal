"""
routes/feedback.py — anonymous, stage-wise client feedback system.

Goal: measure the OPERATIONS team's performance from the client's point of
view, stage by stage, without asking the client to identify themselves (so
they answer openly). Each send generates a UNIQUE token link tied to the
registration number — the form itself collects no identity, but internally
we know exactly who submitted.

Pieces
------
- Public (no-login) form:      GET/POST /feedback/<token>
- Centralised admin (under Clients, Access Master 'clients'/'feedback'):
    /admin/feedback                     dashboard (forms + response stats)
    /admin/feedback/send                pick a stage form -> select clients
    /admin/feedback/send  (POST)        create invites + email + WA links
    /admin/feedback/results/<form_id>   responses + ops-performance analytics
    /admin/feedback/form/<id>/edit      edit questions / title / thank-you

Delivery: branded email now (Resend). Plus a "Send on WhatsApp" click-to-send
button — a wa.me link with the SAME token URL pre-filled, so the team taps
send from their own WhatsApp (no Meta template approval needed).
"""

import os
import json
import uuid
import logging
from datetime import datetime

from flask import (
    render_template, request, redirect, url_for, flash, jsonify, session,
)

from core.auth import admin_required
from core.users import get_user
from db import get_db
from routes.feedback_seed import FEEDBACK_FORM_SEED


# ─────────────────────────── migration + seed ───────────────────────────

def ensure_feedback_tables():
    conn = get_db()
    for ddl in (
        """CREATE TABLE IF NOT EXISTS feedback_forms (
            id SERIAL PRIMARY KEY, pathway TEXT, stage_key TEXT,
            title TEXT NOT NULL, description TEXT, thank_you_message TEXT,
            match_stages TEXT, is_active INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pathway, stage_key))""",
        """CREATE TABLE IF NOT EXISTS feedback_questions (
            id SERIAL PRIMARY KEY,
            form_id INTEGER NOT NULL REFERENCES feedback_forms(id) ON DELETE CASCADE,
            qtype TEXT NOT NULL, question_text TEXT NOT NULL,
            is_required INTEGER DEFAULT 1, options TEXT, sort_order INTEGER DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS feedback_invites (
            id SERIAL PRIMARY KEY, token TEXT UNIQUE NOT NULL,
            form_id INTEGER NOT NULL, registration_number TEXT, client_name TEXT,
            pathway TEXT, stage_key TEXT, mobile TEXT, email TEXT,
            sent_via TEXT, sent_by INTEGER, sent_by_name TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            opened_at TIMESTAMP, submitted_at TIMESTAMP, status TEXT DEFAULT 'sent')""",
        """CREATE TABLE IF NOT EXISTS feedback_responses (
            id SERIAL PRIMARY KEY,
            invite_id INTEGER REFERENCES feedback_invites(id) ON DELETE CASCADE,
            form_id INTEGER, submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS feedback_answers (
            id SERIAL PRIMARY KEY,
            response_id INTEGER NOT NULL REFERENCES feedback_responses(id) ON DELETE CASCADE,
            question_id INTEGER, qtype TEXT, question_text TEXT, answer_value TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_feedback_q_form ON feedback_questions(form_id)",
        "CREATE INDEX IF NOT EXISTS idx_feedback_inv_form ON feedback_invites(form_id)",
        "CREATE INDEX IF NOT EXISTS idx_feedback_inv_reg ON feedback_invites(registration_number)",
        "CREATE INDEX IF NOT EXISTS idx_feedback_ans_resp ON feedback_answers(response_id)",
    ):
        try:
            conn.execute(ddl); conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
    _seed_forms(conn)
    conn.close()


def _seed_forms(conn):
    """Insert any seed form (by pathway+stage_key) that doesn't exist yet.
    Additive + idempotent: editing questions in the DB later is never
    overwritten, and adding a new form to the seed inserts just that one."""
    for i, f in enumerate(FEEDBACK_FORM_SEED):
        try:
            existing = conn.execute(
                "SELECT id FROM feedback_forms WHERE pathway = ? AND stage_key = ?",
                (f['pathway'], f['stage_key'])).fetchone()
            if existing:
                continue
            conn.execute(
                "INSERT INTO feedback_forms (pathway, stage_key, title, match_stages, sort_order, "
                "thank_you_message) VALUES (?, ?, ?, ?, ?, ?)",
                (f['pathway'], f['stage_key'], f['title'], json.dumps(f.get('match_stages') or []),
                 i, "Thank you for your feedback! It helps us serve you better."))
            fid = conn.execute(
                "SELECT id FROM feedback_forms WHERE pathway = ? AND stage_key = ?",
                (f['pathway'], f['stage_key'])).fetchone()['id']
            for j, (qtype, text, required, opts) in enumerate(f['questions']):
                conn.execute(
                    "INSERT INTO feedback_questions (form_id, qtype, question_text, is_required, "
                    "options, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                    (fid, qtype, text, 1 if required else 0,
                     json.dumps(opts) if opts is not None else None, j))
            conn.commit()
        except Exception as e:
            logging.error(f"_seed_forms {f.get('stage_key')}: {e}")
            try: conn.rollback()
            except Exception: pass


# ─────────────────────────── shared helpers ───────────────────────────

def _form_questions(conn, form_id):
    rows = conn.execute(
        "SELECT * FROM feedback_questions WHERE form_id = ? ORDER BY sort_order, id",
        (form_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d['options_parsed'] = json.loads(d['options']) if d.get('options') else None
        except Exception:
            d['options_parsed'] = None
        out.append(d)
    return out


def _base_url():
    return request.host_url.rstrip('/')


def _wa_link(mobile, message):
    """Click-to-send wa.me link — team taps it to send from their WhatsApp."""
    import urllib.parse
    digits = ''.join(ch for ch in (mobile or '') if ch.isdigit())
    if digits and not digits.startswith('91') and len(digits) == 10:
        digits = '91' + digits
    return f"https://wa.me/{digits}?text=" + urllib.parse.quote(message)


def _feedback_message(name, link, stage_title):
    # Full name incl. prefix (e.g. "Dr. Sonali Nanda"); collapse stray spaces.
    greeting = ' '.join((name or '').split()) or 'there'
    return (f"Hi {greeting},\n\n"
            f"We'd love your honest feedback on your {stage_title} experience with GooCampus. "
            f"It's anonymous and takes under 2 minutes — it genuinely helps us improve our "
            f"service for you:\n\n"
            f"{link}")


def _send_feedback_email(email, name, link, stage_title):
    if not email:
        return False
    try:
        from email_utils import send_email
        # Full name incl. prefix (e.g. "Dr. Sonali Nanda"); collapse stray spaces.
        greeting = ' '.join((name or '').split()) or 'there'
        html = f'''<html><body style="font-family:Arial,sans-serif;color:#333;line-height:1.6;margin:0;padding:0;background:#f5f5f5;">
  <div style="max-width:600px;margin:0 auto;background:#fff;">
    <div style="background-color:#1e3a5f;padding:22px;text-align:center;"><h1 style="color:white;margin:0;font-size:22px;">GooCampus Edu Solutions</h1></div>
    <div style="padding:30px;">
      <h2 style="color:#1e3a5f;margin-top:0;">Your feedback shapes our service</h2>
      <p style="font-size:16px;">Hello {greeting},</p>
      <p>We're committed to giving you the best possible support on your journey. Could you spare
      <strong>under 2 minutes</strong> to tell us how we're doing?</p>
      <p style="background:#f0f6ff;border-left:4px solid #1e3a5f;padding:12px 16px;border-radius:4px;font-size:14px;">
      Your feedback is <strong>completely anonymous</strong> — please be open and honest. It's the
      single most valuable thing you can give us to keep improving the service we deliver for you.</p>
      <div style="text-align:center;margin:30px 0;">
        <a href="{link}" style="background-color:#F58220;color:white;padding:14px 34px;text-decoration:none;border-radius:6px;font-weight:bold;font-size:16px;display:inline-block;">Share Your Feedback</a>
      </div>
      <p style="font-size:13px;color:#666;">Or copy this link:<br><a href="{link}" style="color:#F58220;word-break:break-all;">{link}</a></p>
      <p style="margin-top:28px;">With gratitude,<br><strong style="color:#1e3a5f;">The GooCampus Team</strong></p>
    </div>
    <div style="background-color:#f5f5f5;padding:15px;text-align:center;border-top:3px solid #F58220;"><p style="color:#999;font-size:11px;margin:0;">GooCampus Edu Solutions Pvt Ltd</p></div>
  </div>
</body></html>'''
        return send_email([email], 'We value your feedback — GooCampus', html,
                          from_address="GooCampus <info@goocampus.in>")
    except Exception as e:
        logging.error(f"_send_feedback_email: {e}")
        return False


# ─────────────────────────── PUBLIC form (no login) ───────────────────────────

def feedback_public(token):
    conn = get_db()
    inv = conn.execute("SELECT * FROM feedback_invites WHERE token = ?", (token,)).fetchone()
    if not inv:
        conn.close()
        return render_template('feedback_public.html', invalid=True), 404
    form = conn.execute("SELECT * FROM feedback_forms WHERE id = ?", (inv['form_id'],)).fetchone()
    if inv['status'] == 'submitted' or inv['submitted_at']:
        thanks = form['thank_you_message'] if form else None
        conn.close()
        return render_template('feedback_public.html', already=True,
                               thank_you=thanks, form=form)

    if request.method == 'POST':
        questions = _form_questions(conn, inv['form_id'])
        try:
            conn.execute(
                "INSERT INTO feedback_responses (invite_id, form_id) VALUES (?, ?)",
                (inv['id'], inv['form_id']))
            resp_id = conn.execute(
                "SELECT id FROM feedback_responses WHERE invite_id = ? ORDER BY id DESC LIMIT 1",
                (inv['id'],)).fetchone()['id']
            for q in questions:
                val = (request.form.get(f"q_{q['id']}") or '').strip()
                conn.execute(
                    "INSERT INTO feedback_answers (response_id, question_id, qtype, question_text, "
                    "answer_value) VALUES (?, ?, ?, ?, ?)",
                    (resp_id, q['id'], q['qtype'], q['question_text'], val))
            conn.execute(
                "UPDATE feedback_invites SET status = 'submitted', submitted_at = CURRENT_TIMESTAMP "
                "WHERE id = ?", (inv['id'],))
            conn.commit()
        except Exception as e:
            logging.error(f"feedback submit: {e}")
            try: conn.rollback()
            except Exception: pass
            conn.close()
            return render_template('feedback_public.html', error=True,
                                   form=form, questions=_form_questions(get_db(), inv['form_id']),
                                   token=token)
        thanks = form['thank_you_message'] if form else None
        conn.close()
        return render_template('feedback_public.html', submitted=True,
                               thank_you=thanks, form=form)

    # GET — mark opened, render
    if not inv['opened_at']:
        try:
            conn.execute("UPDATE feedback_invites SET status = CASE WHEN status='sent' THEN 'opened' "
                         "ELSE status END, opened_at = CURRENT_TIMESTAMP WHERE id = ?", (inv['id'],))
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
    questions = _form_questions(conn, inv['form_id'])
    conn.close()
    return render_template('feedback_public.html', form=form, questions=questions, token=token)


# ─────────────────────────── ADMIN: dashboard ───────────────────────────

@admin_required
def admin_feedback():
    conn = get_db()
    forms = conn.execute("SELECT * FROM feedback_forms ORDER BY sort_order, id").fetchall()
    cards = []
    for f in forms:
        stats = conn.execute(
            "SELECT COUNT(*) AS sent, "
            "SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END) AS submitted "
            "FROM feedback_invites WHERE form_id = ?", (f['id'],)).fetchone()
        cards.append({'form': f, 'sent': stats['sent'] or 0, 'submitted': stats['submitted'] or 0})
    conn.close()
    return render_template('admin_feedback.html', cards=cards, active_section='clients')


# ─────────────────────────── ADMIN: send ───────────────────────────

def _clients_for_form(conn, form, status='In Process'):
    """Clients eligible for this form: same pathway, and (if the form lists
    match_stages) whose current_stage is in that list. By default only
    'In Process' (active) clients — feedback shouldn't chase dropped ones;
    pass status='all' to include every status."""
    try:
        stages = json.loads(form['match_stages']) if form['match_stages'] else []
    except Exception:
        stages = []
    q = ("SELECT id, registration_number, prefix, first_name, last_name, mobile, email, "
         "current_stage, account_status, plan_type FROM plab_clients "
         "WHERE COALESCE(pathway,'plab') = ? ")
    params = [form['pathway']]
    if stages:
        ph = ','.join(['?'] * len(stages))
        q += f" AND current_stage IN ({ph}) "
        params += stages
    if status and status != 'all':
        q += " AND account_status = ? "
        params.append(status)
    q += " ORDER BY first_name, last_name"
    try:
        return conn.execute(q, params).fetchall()
    except Exception:
        return []


@admin_required
def admin_feedback_send():
    conn = get_db()
    forms = conn.execute("SELECT * FROM feedback_forms WHERE is_active = 1 ORDER BY sort_order, id").fetchall()
    form_id = request.args.get('form_id', type=int)
    status = request.args.get('status', 'In Process')
    selected = None
    clients = []
    if form_id:
        selected = conn.execute("SELECT * FROM feedback_forms WHERE id = ?", (form_id,)).fetchone()
        if selected:
            clients = _clients_for_form(conn, selected, status)
    conn.close()
    return render_template('admin_feedback_send.html', forms=forms, selected=selected,
                           clients=clients, status=status, active_section='clients')


@admin_required
def admin_feedback_send_post():
    conn = get_db()
    user = get_user()
    form_id = request.form.get('form_id', type=int)
    form = conn.execute("SELECT * FROM feedback_forms WHERE id = ?", (form_id,)).fetchone() if form_id else None
    if not form:
        conn.close()
        flash('Pick a feedback form first.', 'error')
        return redirect(url_for('admin_feedback_send'))
    reg_numbers = request.form.getlist('reg')
    if not reg_numbers:
        conn.close()
        flash('Select at least one client.', 'error')
        return redirect(url_for('admin_feedback_send', form_id=form_id))

    base = _base_url()
    sent_rows = []
    email_ok = 0
    for reg in reg_numbers:
        c = conn.execute(
            "SELECT * FROM plab_clients WHERE registration_number = ? AND COALESCE(pathway,'plab') = ? LIMIT 1",
            (reg, form['pathway'])).fetchone()
        if not c:
            continue
        name = ((c['prefix'] or '') + ' ' + (c['first_name'] or '') + ' ' + (c['last_name'] or '')).strip()
        token = uuid.uuid4().hex
        try:
            conn.execute(
                "INSERT INTO feedback_invites (token, form_id, registration_number, client_name, "
                "pathway, stage_key, mobile, email, sent_via, sent_by, sent_by_name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (token, form['id'], reg, name, form['pathway'], form['stage_key'],
                 c['mobile'], c['email'], 'email', (user or {}).get('id'), (user or {}).get('name')))
            conn.commit()
        except Exception as e:
            logging.error(f"feedback invite insert {reg}: {e}")
            try: conn.rollback()
            except Exception: pass
            continue
        link = f"{base}/feedback/{token}"
        ok = _send_feedback_email(c['email'], name, link, form['title'])
        if ok:
            email_ok += 1
        sent_rows.append({
            'name': name, 'reg': reg, 'mobile': c['mobile'], 'email': c['email'],
            'link': link, 'email_ok': ok,
            'wa_link': _wa_link(c['mobile'], _feedback_message(name, link, form['title'])),
        })
    conn.close()
    flash(f"Created {len(sent_rows)} feedback link(s); {email_ok} email(s) sent. "
          f"Use the WhatsApp buttons below to send those too.", 'success')
    return render_template('admin_feedback_sent.html', form=form, rows=sent_rows,
                           active_section='clients')


# ─────────────────────────── ADMIN: results ───────────────────────────

@admin_required
def admin_feedback_results(form_id):
    conn = get_db()
    form = conn.execute("SELECT * FROM feedback_forms WHERE id = ?", (form_id,)).fetchone()
    if not form:
        conn.close()
        flash('Form not found.', 'error')
        return redirect(url_for('admin_feedback'))
    questions = _form_questions(conn, form_id)
    # aggregate per question
    for q in questions:
        answers = conn.execute(
            "SELECT a.answer_value FROM feedback_answers a "
            "JOIN feedback_responses r ON r.id = a.response_id "
            "WHERE r.form_id = ? AND a.question_id = ?", (form_id, q['id'])).fetchall()
        vals = [a['answer_value'] for a in answers if (a['answer_value'] or '').strip() != '']
        q['n'] = len(vals)
        if q['qtype'] in ('star', 'scale'):
            nums = []
            for v in vals:
                try: nums.append(float(v))
                except Exception: pass
            q['avg'] = round(sum(nums) / len(nums), 2) if nums else None
        elif q['qtype'] == 'choice':
            dist = {}
            for v in vals:
                dist[v] = dist.get(v, 0) + 1
            q['dist'] = dist
        else:  # text
            q['comments'] = vals
    # submissions list (internal — who submitted)
    subs = conn.execute(
        "SELECT r.id, r.submitted_at, i.registration_number, i.client_name "
        "FROM feedback_responses r JOIN feedback_invites i ON i.id = r.invite_id "
        "WHERE r.form_id = ? ORDER BY r.submitted_at DESC", (form_id,)).fetchall()
    inv_stats = conn.execute(
        "SELECT COUNT(*) AS sent, SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END) AS submitted, "
        "SUM(CASE WHEN status='opened' THEN 1 ELSE 0 END) AS opened FROM feedback_invites WHERE form_id = ?",
        (form_id,)).fetchone()
    conn.close()
    return render_template('admin_feedback_results.html', form=form, questions=questions,
                           subs=subs, stats=inv_stats, active_section='clients')


# ─────────────────────────── ADMIN: edit form/questions ───────────────────────────

@admin_required
def admin_feedback_form_edit(form_id):
    conn = get_db()
    form = conn.execute("SELECT * FROM feedback_forms WHERE id = ?", (form_id,)).fetchone()
    if not form:
        conn.close()
        flash('Form not found.', 'error')
        return redirect(url_for('admin_feedback'))
    if request.method == 'POST':
        act = request.form.get('action')
        try:
            if act == 'form_meta':
                conn.execute("UPDATE feedback_forms SET title = ?, description = ?, thank_you_message = ?, "
                             "is_active = ? WHERE id = ?",
                             (request.form.get('title', '').strip(), request.form.get('description', '').strip(),
                              request.form.get('thank_you_message', '').strip(),
                              1 if request.form.get('is_active') else 0, form_id))
            elif act == 'q_edit':
                qid = request.form.get('qid', type=int)
                opts = request.form.get('options', '').strip()
                opts_json = None
                if opts:
                    opts_json = json.dumps([o.strip() for o in opts.split('\n') if o.strip()])
                conn.execute("UPDATE feedback_questions SET question_text = ?, qtype = ?, is_required = ?, "
                             "options = ? WHERE id = ? AND form_id = ?",
                             (request.form.get('question_text', '').strip(), request.form.get('qtype', 'star'),
                              1 if request.form.get('is_required') else 0, opts_json, qid, form_id))
            elif act == 'q_add':
                mx = conn.execute("SELECT COALESCE(MAX(sort_order),0) AS m FROM feedback_questions WHERE form_id = ?",
                                  (form_id,)).fetchone()['m']
                opts = request.form.get('options', '').strip()
                opts_json = json.dumps([o.strip() for o in opts.split('\n') if o.strip()]) if opts else None
                conn.execute("INSERT INTO feedback_questions (form_id, qtype, question_text, is_required, options, "
                             "sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                             (form_id, request.form.get('qtype', 'star'), request.form.get('question_text', '').strip(),
                              1 if request.form.get('is_required') else 0, opts_json, mx + 1))
            elif act == 'q_delete':
                conn.execute("DELETE FROM feedback_questions WHERE id = ? AND form_id = ?",
                             (request.form.get('qid', type=int), form_id))
            conn.commit()
            flash('Saved.', 'success')
        except Exception as e:
            logging.error(f"feedback form edit: {e}")
            try: conn.rollback()
            except Exception: pass
            flash(f'Error: {e}', 'error')
        conn.close()
        return redirect(url_for('admin_feedback_form_edit', form_id=form_id))
    questions = _form_questions(conn, form_id)
    conn.close()
    return render_template('admin_feedback_form_edit.html', form=form, questions=questions,
                           active_section='clients')


def register_routes(app):
    ensure_feedback_tables()
    # Public (no login)
    app.add_url_rule('/feedback/<token>', endpoint='feedback_public',
                     view_func=feedback_public, methods=['GET', 'POST'])
    # Admin (Access Master 'clients'/'feedback')
    app.add_url_rule('/admin/feedback', endpoint='admin_feedback',
                     view_func=admin_feedback, methods=['GET'])
    app.add_url_rule('/admin/feedback/send', endpoint='admin_feedback_send',
                     view_func=admin_feedback_send, methods=['GET'])
    app.add_url_rule('/admin/feedback/send', endpoint='admin_feedback_send_post',
                     view_func=admin_feedback_send_post, methods=['POST'])
    app.add_url_rule('/admin/feedback/results/<int:form_id>', endpoint='admin_feedback_results',
                     view_func=admin_feedback_results, methods=['GET'])
    app.add_url_rule('/admin/feedback/form/<int:form_id>/edit', endpoint='admin_feedback_form_edit',
                     view_func=admin_feedback_form_edit, methods=['GET', 'POST'])
