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
        "ALTER TABLE feedback_invites ADD COLUMN IF NOT EXISTS quarter_key TEXT",
        "ALTER TABLE feedback_invites ADD COLUMN IF NOT EXISTS quarter_label TEXT",
        # Did the email actually send? 'sent' / 'failed' (NULL = unknown/legacy).
        "ALTER TABLE feedback_invites ADD COLUMN IF NOT EXISTS email_status TEXT",
        # When the team last clicked the WhatsApp 'Send' for this client (so the
        # button turns 'sent' colour and stays that way on reload).
        "ALTER TABLE feedback_invites ADD COLUMN IF NOT EXISTS wa_sent_at TIMESTAMP",
        # When the team last fired the bulk-WhatsApp send for a whole form's
        # follow-up list, and how many went out that time.
        "ALTER TABLE feedback_forms ADD COLUMN IF NOT EXISTS last_wa_bulk_at TIMESTAMP",
        "ALTER TABLE feedback_forms ADD COLUMN IF NOT EXISTS last_wa_bulk_count INTEGER",
        "CREATE INDEX IF NOT EXISTS idx_feedback_q_form ON feedback_questions(form_id)",
        "CREATE INDEX IF NOT EXISTS idx_feedback_inv_form ON feedback_invites(form_id)",
        "CREATE INDEX IF NOT EXISTS idx_feedback_inv_quarter ON feedback_invites(quarter_key)",
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


def _days_ago(dt):
    """Whole days between a timestamp and now — for 'sent N days ago' cues."""
    if not dt:
        return None
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt[:19])
        return (datetime.now() - dt).days
    except Exception:
        return None


# ─────────────────────────── quarters + metrics ───────────────────────────

_MONTHS = ['', 'January', 'February', 'March', 'April', 'May', 'June', 'July',
           'August', 'September', 'October', 'November', 'December']


def _quarter_for(dt):
    """Reporting quarter for a send date = the calendar quarter that just
    ended. Feedback is sent the month AFTER the quarter closes:
      sent Jul-Sep -> Apr-Jun (Q1) | Oct-Dec -> Jul-Sep (Q2)
      sent Jan-Mar -> Oct-Dec prev year (Q3) | Apr-Jun -> Jan-Mar (Q4)
    Returns (key, label). Key sorts chronologically by period start."""
    m, y = dt.month, dt.year
    if 7 <= m <= 9:      s, e, sy, ey = 4, 6, y, y
    elif 10 <= m <= 12:  s, e, sy, ey = 7, 9, y, y
    elif 1 <= m <= 3:    s, e, sy, ey = 10, 12, y - 1, y - 1
    else:                s, e, sy, ey = 1, 3, y, y
    return f"{sy}-{s:02d}", f"{_MONTHS[s]} {sy} - {_MONTHS[e]} {ey}"


def _metrics(conn, form_id=None, quarter_key=None):
    """CSAT / NPS / avg-star + invite counts, filtered by form and/or quarter.

    CSAT = % of 5-star answers that are 4 or 5 (satisfied).
    NPS  = %promoters(9-10) − %detractors(0-6) on the 0-10 recommend scale.
    """
    where, params = [], []
    if form_id:
        where.append("r.form_id = ?"); params.append(form_id)
    if quarter_key:
        where.append("i.quarter_key = ?"); params.append(quarter_key)
    wsql = (" AND " + " AND ".join(where)) if where else ""

    def nums(qtype):
        rows = conn.execute(
            "SELECT a.answer_value AS v FROM feedback_answers a "
            "JOIN feedback_responses r ON r.id = a.response_id "
            "JOIN feedback_invites i ON i.id = r.invite_id "
            "WHERE a.qtype = ?" + wsql, [qtype] + params).fetchall()
        out = []
        for r in rows:
            try: out.append(float(r['v']))
            except Exception: pass
        return out

    stars, scales = nums('star'), nums('scale')
    avg_star = round(sum(stars) / len(stars), 2) if stars else None
    csat = round(sum(1 for s in stars if s >= 4) / len(stars) * 100) if stars else None
    nps = None
    if scales:
        promo = sum(1 for s in scales if s >= 9)
        detr = sum(1 for s in scales if s <= 6)
        nps = round((promo - detr) / len(scales) * 100)

    iw, ip = [], []
    if form_id:
        iw.append("form_id = ?"); ip.append(form_id)
    if quarter_key:
        iw.append("quarter_key = ?"); ip.append(quarter_key)
    iwsql = (" WHERE " + " AND ".join(iw)) if iw else ""
    # Count DISTINCT clients, not raw invite rows — a client re-sent the form
    # (or historical duplicate invites) must not inflate the "sent" total.
    st = conn.execute(
        "SELECT COUNT(DISTINCT registration_number) AS sent, "
        "COUNT(DISTINCT CASE WHEN status='submitted' THEN registration_number END) AS submitted, "
        "COUNT(DISTINCT CASE WHEN status='opened' THEN registration_number END) AS opened, "
        "COUNT(DISTINCT CASE WHEN email_status='failed' THEN registration_number END) AS failed "
        "FROM feedback_invites" + iwsql, ip).fetchone()
    return {'avg_star': avg_star, 'csat': csat, 'nps': nps,
            'star_n': len(stars), 'nps_n': len(scales),
            'sent': st['sent'] or 0, 'submitted': st['submitted'] or 0,
            'opened': st['opened'] or 0, 'failed': st['failed'] or 0}


def _quarters_with_data(conn, form_id=None):
    if form_id:
        rows = conn.execute(
            "SELECT DISTINCT quarter_key, quarter_label FROM feedback_invites "
            "WHERE form_id = ? AND quarter_key IS NOT NULL ORDER BY quarter_key DESC",
            (form_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT quarter_key, quarter_label FROM feedback_invites "
            "WHERE quarter_key IS NOT NULL ORDER BY quarter_key DESC").fetchall()
    return [dict(r) for r in rows]


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
        m = _metrics(conn, f['id'], None)  # all-time per form
        # How many distinct clients are in this form's follow-up list right now
        # (latest invite per client, not yet submitted) — the bulk-WA audience.
        try:
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM (SELECT DISTINCT ON (registration_number) status "
                "FROM feedback_invites WHERE form_id = ? "
                "ORDER BY registration_number, CASE WHEN status='submitted' THEN 0 ELSE 1 END, sent_at DESC) t "
                "WHERE status <> 'submitted'", (f['id'],)).fetchone()['n']
        except Exception:
            pending = 0
        lwa = f['last_wa_bulk_at'] if 'last_wa_bulk_at' in f.keys() else None
        last_wa_str = None
        if lwa:
            try: last_wa_str = lwa.strftime('%d %b %Y')
            except Exception: last_wa_str = str(lwa)[:10]
        cards.append({'form': f, 'pending': pending, 'last_wa_str': last_wa_str,
                      'last_wa_count': (f['last_wa_bulk_count'] if 'last_wa_bulk_count' in f.keys() else None),
                      **m})
    overall = _metrics(conn, None, None)  # product-wide, all-time
    conn.close()
    return render_template('admin_feedback.html', cards=cards, overall=overall,
                           active_section='clients')


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
    qkey, qlabel = _quarter_for(datetime.now())
    sent_rows = []
    email_ok = 0
    skipped = 0
    for reg in reg_numbers:
        c = conn.execute(
            "SELECT * FROM plab_clients WHERE registration_number = ? AND COALESCE(pathway,'plab') = ? LIMIT 1",
            (reg, form['pathway'])).fetchone()
        if not c:
            continue
        # De-dup: never re-send to a client who already submitted, and don't
        # create a second invite for the same client within the same quarter.
        dup = conn.execute(
            "SELECT 1 FROM feedback_invites WHERE form_id = ? AND registration_number = ? "
            "AND (status = 'submitted' OR quarter_key = ?) LIMIT 1",
            (form['id'], reg, qkey)).fetchone()
        if dup:
            skipped += 1
            continue
        name = ((c['prefix'] or '') + ' ' + (c['first_name'] or '') + ' ' + (c['last_name'] or '')).strip()
        token = uuid.uuid4().hex
        try:
            conn.execute(
                "INSERT INTO feedback_invites (token, form_id, registration_number, client_name, "
                "pathway, stage_key, mobile, email, sent_via, sent_by, sent_by_name, "
                "quarter_key, quarter_label) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (token, form['id'], reg, name, form['pathway'], form['stage_key'],
                 c['mobile'], c['email'], 'email', (user or {}).get('id'), (user or {}).get('name'),
                 qkey, qlabel))
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
        # Remember whether the email actually went, so Follow-up can flag failures.
        try:
            conn.execute("UPDATE feedback_invites SET email_status = ? WHERE token = ?",
                         ('sent' if ok else 'failed', token))
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
        sent_rows.append({
            'name': name, 'reg': reg, 'mobile': c['mobile'], 'email': c['email'],
            'link': link, 'email_ok': ok,
            'wa_link': _wa_link(c['mobile'], _feedback_message(name, link, form['title'])),
        })
    conn.close()
    msg = f"Created {len(sent_rows)} feedback link(s); {email_ok} email(s) sent."
    if skipped:
        msg += f" Skipped {skipped} already sent this quarter / already submitted."
    flash(msg + " Use the WhatsApp buttons below to send those too.", 'success')
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

    quarters = _quarters_with_data(conn, form_id)
    # Default to the most recent quarter with data; 'all' = every quarter.
    quarter = request.args.get('quarter')
    if quarter is None:
        quarter = quarters[0]['quarter_key'] if quarters else 'all'
    qfilter = None if quarter == 'all' else quarter

    metrics = _metrics(conn, form_id, qfilter)

    # per-question aggregates (quarter-filtered)
    qextra, qparams = "", []
    if qfilter:
        qextra = " AND i.quarter_key = ? "
        qparams = [qfilter]
    questions = _form_questions(conn, form_id)
    for q in questions:
        answers = conn.execute(
            "SELECT a.answer_value AS v FROM feedback_answers a "
            "JOIN feedback_responses r ON r.id = a.response_id "
            "JOIN feedback_invites i ON i.id = r.invite_id "
            "WHERE r.form_id = ? AND a.question_id = ?" + qextra,
            [form_id, q['id']] + qparams).fetchall()
        vals = [a['v'] for a in answers if (a['v'] or '').strip() != '']
        q['n'] = len(vals)
        if q['qtype'] in ('star', 'scale'):
            ns = []
            for v in vals:
                try: ns.append(float(v))
                except Exception: pass
            q['avg'] = round(sum(ns) / len(ns), 2) if ns else None
        elif q['qtype'] == 'choice':
            dist = {}
            for v in vals:
                dist[v] = dist.get(v, 0) + 1
            q['dist'] = dist
        else:
            q['comments'] = vals

    # submissions list (internal — who submitted), quarter-filtered
    subs = conn.execute(
        "SELECT r.id, r.submitted_at, i.registration_number, i.client_name "
        "FROM feedback_responses r JOIN feedback_invites i ON i.id = r.invite_id "
        "WHERE r.form_id = ?" + (" AND i.quarter_key = ?" if qfilter else "") +
        " ORDER BY r.submitted_at DESC", [form_id] + ([qfilter] if qfilter else [])).fetchall()
    conn.close()
    return render_template('admin_feedback_results.html', form=form, questions=questions,
                           subs=subs, metrics=metrics, quarters=quarters, quarter=quarter,
                           active_section='clients')


@admin_required
def admin_feedback_response(response_id):
    """JSON — one client's full response, for the right-side drawer."""
    conn = get_db()
    r = conn.execute(
        "SELECT r.id, r.submitted_at, i.client_name, i.registration_number, "
        "i.pathway, i.stage_key, i.quarter_label "
        "FROM feedback_responses r JOIN feedback_invites i ON i.id = r.invite_id "
        "WHERE r.id = ?", (response_id,)).fetchone()
    if not r:
        conn.close()
        return jsonify({'error': 'not found'}), 404
    ans = conn.execute(
        "SELECT question_text, qtype, answer_value FROM feedback_answers "
        "WHERE response_id = ? ORDER BY id", (response_id,)).fetchall()
    conn.close()
    return jsonify({
        'client_name': r['client_name'], 'reg': r['registration_number'],
        'submitted_at': str(r['submitted_at'] or ''), 'quarter': r['quarter_label'] or '',
        'answers': [{'q': a['question_text'], 'type': a['qtype'],
                     'value': a['answer_value']} for a in ans],
    })


@admin_required
def admin_feedback_followup(form_id):
    """Persistent follow-up view: every client the form was sent to, with
    live status — once a client submits, their WhatsApp 'Send' turns into a
    'Submitted' badge. Lets the team send emails, wait a few days, then only
    WhatsApp the ones who haven't responded yet."""
    conn = get_db()
    form = conn.execute("SELECT * FROM feedback_forms WHERE id = ?", (form_id,)).fetchone()
    if not form:
        conn.close()
        flash('Form not found.', 'error')
        return redirect(url_for('admin_feedback'))
    quarters = _quarters_with_data(conn, form_id)
    quarter = request.args.get('quarter')
    if quarter is None:
        quarter = quarters[0]['quarter_key'] if quarters else 'all'
    qfilter = None if quarter == 'all' else quarter

    q = ("SELECT DISTINCT ON (registration_number) id, token, client_name, registration_number, "
         "mobile, email, status, submitted_at, sent_at, email_status, wa_sent_at FROM feedback_invites WHERE form_id = ?")
    params = [form_id]
    if qfilter:
        q += " AND quarter_key = ?"
        params.append(qfilter)
    # One row per client (collapse duplicate sends): prefer a submitted invite,
    # else the most recent. DISTINCT ON requires registration_number first.
    q += (" ORDER BY registration_number, "
          "CASE WHEN status = 'submitted' THEN 0 ELSE 1 END, sent_at DESC")
    invites = conn.execute(q, params).fetchall()
    conn.close()

    base = _base_url()
    sent_rows, opened_rows = [], []
    submitted_count = 0
    for iv in invites:
        submitted = (iv['status'] == 'submitted') or bool(iv['submitted_at'])
        if submitted:
            # Responders drop off the follow-up list entirely.
            submitted_count += 1
            continue
        link = f"{base}/feedback/{iv['token']}"
        row = {
            'invite_id': iv['id'], 'name': iv['client_name'], 'reg': iv['registration_number'],
            'mobile': iv['mobile'], 'email': iv['email'], 'status': iv['status'],
            'opened': iv['status'] == 'opened', 'sent_at': iv['sent_at'],
            'days_ago': _days_ago(iv['sent_at']), 'link': link,
            'email_status': iv['email_status'], 'failed': (iv['email_status'] == 'failed'),
            'wa_sent': bool(iv['wa_sent_at']),
            'wa_link': _wa_link(iv['mobile'], _feedback_message(iv['client_name'], link, form['title'])),
        }
        (opened_rows if row['opened'] else sent_rows).append(row)
    # Failed-email rows first (they need a correction), then by name.
    for lst in (sent_rows, opened_rows):
        lst.sort(key=lambda r: (0 if r['failed'] else 1, (r['name'] or '').lower()))
    failed_count = sum(1 for r in sent_rows + opened_rows if r['failed'])
    total = len(sent_rows) + len(opened_rows) + submitted_count
    # Most-recent send across this form/quarter, so the team sees how long it's been.
    _sent = [iv['sent_at'] for iv in invites if iv['sent_at']]
    last_sent = max(_sent) if _sent else None
    last_sent_str, last_sent_days = None, None
    if last_sent is not None:
        try:
            last_sent_str = last_sent.strftime('%d %b %Y')
        except Exception:
            last_sent_str = str(last_sent)[:10]
        last_sent_days = _days_ago(last_sent)
    return render_template('admin_feedback_followup.html', form=form,
                           sent_rows=sent_rows, opened_rows=opened_rows,
                           total=total, submitted_count=submitted_count,
                           sent_count=len(sent_rows), opened_count=len(opened_rows),
                           failed_count=failed_count,
                           last_sent_str=last_sent_str, last_sent_days=last_sent_days,
                           quarters=quarters, quarter=quarter, active_section='clients')


@admin_required
def admin_feedback_resend(invite_id):
    """Re-send the feedback email for an existing invite (reuses the same
    token/link — no new invite row, so counts and follow-up stay clean).
    Only from the Follow-up page; the first send is done from the Send page."""
    conn = get_db()
    iv = conn.execute(
        "SELECT fi.*, f.title AS form_title FROM feedback_invites fi "
        "LEFT JOIN feedback_forms f ON f.id = fi.form_id WHERE fi.id = ?", (invite_id,)).fetchone()
    if not iv:
        conn.close()
        flash('Invite not found.', 'error')
        return redirect(url_for('admin_feedback'))
    if iv['status'] == 'submitted':
        fid = iv['form_id']
        conn.close()
        flash('That client already submitted — no need to re-send.', 'info')
        return redirect(url_for('admin_feedback_followup', form_id=fid))
    fid = iv['form_id']
    # Optional inline email correction from Follow-up: fix a wrong/invalid address
    # on the invite AND at the source (the client record), then re-send.
    new_email = (request.form.get('email') or '').strip()
    email_to_use = iv['email']
    if new_email and new_email != (iv['email'] or ''):
        try:
            conn.execute("UPDATE feedback_invites SET email = ? WHERE id = ?", (new_email, invite_id))
            conn.execute("UPDATE plab_clients SET email = ? WHERE registration_number = ? "
                         "AND COALESCE(pathway,'plab') = ?",
                         (new_email, iv['registration_number'], iv['pathway'] or 'plab'))
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
        email_to_use = new_email
    if not email_to_use:
        conn.close()
        flash('No email on file — enter an email address, then re-send.', 'error')
        return redirect(url_for('admin_feedback_followup', form_id=fid))
    link = f"{_base_url()}/feedback/{iv['token']}"
    ok = _send_feedback_email(email_to_use, iv['client_name'], link, iv['form_title'] or 'Feedback')
    conn.execute("UPDATE feedback_invites SET sent_at = CURRENT_TIMESTAMP, email_status = ? WHERE id = ?",
                 ('sent' if ok else 'failed', invite_id))
    conn.commit()
    conn.close()
    flash('Re-sent the feedback email.' if ok else 'Still could not send — double-check the email address.',
          'success' if ok else 'error')
    return redirect(url_for('admin_feedback_followup', form_id=fid))


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


@admin_required
def admin_feedback_wa_sent(invite_id):
    """Mark that the team clicked 'Send on WhatsApp' for this invite, so the
    button shows the 'sent' colour and stays that way on reload."""
    conn = get_db()
    try:
        conn.execute("UPDATE feedback_invites SET wa_sent_at = CURRENT_TIMESTAMP WHERE id = ?", (invite_id,))
        conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass
    conn.close()
    return ('', 204)


def _send_feedback_wa_batch(recipients):
    """Send the approved 'client_feedback_request' WhatsApp template to many
    clients in one (chunked) Infobip call. Each recipient dict needs
    mobile, name, stage, token, invite_id. Body placeholders = [name, stage];
    the URL-button parameter = the feedback token (the {{1}} Infobip appends to
    the template's fixed base URL https://goocampus.in/feedback/). Reuses the
    same env config as the registration-invite WhatsApp sender.
    Returns (accepted_invite_ids:set, rejected:int, config_ok:bool)."""
    import os, requests as http
    key = os.environ.get('INFOBIP_API_KEY', '')
    base = os.environ.get('INFOBIP_BASE_URL', '')
    sender = os.environ.get('INFOBIP_SENDER', '15558246314')
    if not key or not base:
        logging.error("feedback WA bulk NOT sent: INFOBIP_API_KEY / INFOBIP_BASE_URL not configured")
        return set(), 0, False
    url = f"https://{base}/whatsapp/1/message/template"
    headers = {"Authorization": f"App {key}", "Content-Type": "application/json", "Accept": "application/json"}
    accepted, rejected = set(), 0
    CHUNK = 50
    for start in range(0, len(recipients), CHUNK):
        chunk = recipients[start:start + CHUNK]
        msgs = []
        for r in chunk:
            digits = ''.join(ch for ch in (r['mobile'] or '') if ch.isdigit())
            if digits and not digits.startswith('91') and len(digits) == 10:
                digits = '91' + digits
            msgs.append({
                "from": sender, "to": digits,
                "content": {
                    "templateName": "client_feedback_request",
                    "templateData": {
                        "body": {"placeholders": [r['name'] or 'there', r['stage'] or 'GooCampus']},
                        "buttons": [{"type": "URL", "parameter": r['token']}],
                    },
                    "language": "en_GB",
                }})
        try:
            resp = http.post(url, json={"messages": msgs}, headers=headers, timeout=25)
            if resp.status_code >= 300:
                logging.error(f"feedback WA bulk REJECTED ({resp.status_code}): {resp.text[:500]}")
                rejected += len(chunk)
                continue
            data = resp.json() if resp.text else {}
            rmsgs = data.get('messages') or []
            for i, r in enumerate(chunk):
                grp = ''
                if i < len(rmsgs):
                    grp = (((rmsgs[i] or {}).get('status') or {}).get('groupName') or '').upper()
                if grp == 'REJECTED':
                    rejected += 1
                else:
                    accepted.add(r['invite_id'])
        except Exception as e:
            logging.error(f"_send_feedback_wa_batch: {e}")
            rejected += len(chunk)
    return accepted, rejected, True


@admin_required
def admin_feedback_wa_bulk(form_id):
    """Bulk-send the approved WhatsApp feedback template (Infobip) to every
    client currently in this form's FOLLOW-UP list (not yet submitted), each
    with their own unique link. Records when the blast was last fired + count."""
    quarter = request.form.get('quarter') or request.args.get('quarter')
    conn = get_db()
    form = conn.execute("SELECT * FROM feedback_forms WHERE id = ?", (form_id,)).fetchone()
    if not form:
        conn.close()
        flash('Form not found.', 'error')
        return redirect(url_for('admin_feedback'))
    # Exactly the follow-up selection: one row per client, most recent, not submitted.
    q = ("SELECT DISTINCT ON (registration_number) id, token, client_name, mobile, status "
         "FROM feedback_invites WHERE form_id = ?")
    params = [form_id]
    if quarter and quarter != 'all':
        q += " AND quarter_key = ?"
        params.append(quarter)
    q += " ORDER BY registration_number, CASE WHEN status='submitted' THEN 0 ELSE 1 END, sent_at DESC"
    invites = conn.execute(q, params).fetchall()
    stage = form['title'] or 'GooCampus'
    recips, no_mobile = [], 0
    for iv in invites:
        if iv['status'] == 'submitted':
            continue  # responders drop off the follow-up list
        digits = ''.join(ch for ch in (iv['mobile'] or '') if ch.isdigit())
        if not digits:
            no_mobile += 1
            continue
        recips.append({'invite_id': iv['id'], 'mobile': iv['mobile'],
                       'name': iv['client_name'], 'stage': stage, 'token': iv['token']})
    if not recips:
        conn.close()
        flash('Nobody to message — the follow-up list is empty (everyone responded, or no mobiles on file).', 'info')
        return redirect(url_for('admin_feedback'))
    accepted, rejected, config_ok = _send_feedback_wa_batch(recips)
    if not config_ok:
        conn.close()
        flash('WhatsApp is not configured on the server (Infobip keys missing). Nothing was sent.', 'error')
        return redirect(url_for('admin_feedback'))
    for iid in accepted:
        try:
            conn.execute("UPDATE feedback_invites SET wa_sent_at = CURRENT_TIMESTAMP WHERE id = ?", (iid,))
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
    try:
        conn.execute("UPDATE feedback_forms SET last_wa_bulk_at = CURRENT_TIMESTAMP, last_wa_bulk_count = ? "
                     "WHERE id = ?", (len(accepted), form_id))
        conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass
    conn.close()
    msg = f"WhatsApp sent to {len(accepted)} client(s) in the follow-up list."
    if rejected:
        msg += f" {rejected} rejected by WhatsApp."
    if no_mobile:
        msg += f" {no_mobile} had no mobile."
    flash(msg, 'success' if accepted else 'error')
    return redirect(url_for('admin_feedback'))


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
    app.add_url_rule('/admin/feedback/response/<int:response_id>', endpoint='admin_feedback_response',
                     view_func=admin_feedback_response, methods=['GET'])
    app.add_url_rule('/admin/feedback/followup/<int:form_id>', endpoint='admin_feedback_followup',
                     view_func=admin_feedback_followup, methods=['GET'])
    app.add_url_rule('/admin/feedback/resend/<int:invite_id>', endpoint='admin_feedback_resend',
                     view_func=admin_feedback_resend, methods=['POST'])
    app.add_url_rule('/admin/feedback/wa-sent/<int:invite_id>', endpoint='admin_feedback_wa_sent',
                     view_func=admin_feedback_wa_sent, methods=['POST'])
    app.add_url_rule('/admin/feedback/wa-bulk/<int:form_id>', endpoint='admin_feedback_wa_bulk',
                     view_func=admin_feedback_wa_bulk, methods=['POST'])
    app.add_url_rule('/admin/feedback/form/<int:form_id>/edit', endpoint='admin_feedback_form_edit',
                     view_func=admin_feedback_form_edit, methods=['GET', 'POST'])
