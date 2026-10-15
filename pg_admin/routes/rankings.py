"""GooCampus MCC College Rankings 2026 — one general list for ALL Internal + Paid doctors.

Founder 2026-10-15. By college only (not speciality, not location): for each MCC list —
All India Quota (Govt), Deemed Paid, Central Universities (DU/IP/BHU/AMU), Deemed NRI —
colleges are grouped Top / Good / Average using the SAME team-curated tiers as the Desk
(pg_college_tiers). The draft tiers come from how fast each college's seats went in the MAIN
rounds last year (Round 1, else Round 2; mop-up / stray ignored, so a good college whose few
leftover seats went late is not dragged down). Colleges new in 2026 are never tiered — they go
out as a separate "New colleges in 2026" PDF.

Rows show only college, state, institute type and 2026 seats in that list — no ranks.
Delivery: dashboard page (/api/pg/rankings, Internal + Paid + desk staff), two PDFs, and a Desk
"Email to all Internal + Paid doctors" (test-send first).
"""
import base64
import logging
import threading
import time
from datetime import datetime, timedelta

from flask import request, jsonify, Response
from db import get_db
from pg_admin.routes import recommended as rec

_TIER_ORDER = ('Top', 'Good', 'Average')


def _ist_now():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


_QUOTA_LABEL = {'All India': 'All India Quota', 'Self-Financed Merit Seat': 'Deemed Paid',
                'Non-Resident Indian': 'Deemed NRI', 'Muslim Minority Quota': 'Muslim Minority',
                'Jain Minority Quota': 'Jain Minority'}


def rankings_data(conn):
    """{lists:[{key,label,tiers:{Top:[..],Good:[..],Average:[..]},counts}], new_colleges:[..]}"""
    rec.ensure_rec_tables(conn)
    lists, new_by_code = [], {}
    for key, meta in rec.TIER_LISTS.items():
        rows = rec.tiers_payload(conn, key)
        tiers = {t: [] for t in _TIER_ORDER}
        for r in rows:
            item = {'college': r['college'], 'state': r['state'], 'institute_type': r.get('institute_type') or '',
                    'seats': r['seats'], 'college_code': r['college_code']}
            if r['tier'] == rec.NEW_TIER:
                continue                     # listed in the separate New colleges document
            tiers.setdefault(r['tier'], []).append(item)
        # within a tier: keep the curated order (tiers_payload sorts by tier then basis rank)
        lists.append({'key': key, 'label': meta['label'], 'tiers': tiers,
                      'counts': {t: len(v) for t, v in tiers.items()}})
    # New colleges come from EVERY official MCC seat list (incl. Deemed 'All India' + minority quotas,
    # which a brand-new deemed college may have alone), not only the 4 ranked lists.
    bodies = rec._bodies(conn)
    if bodies:
        ph = ','.join(['?'] * len(bodies))
        for r in conn.execute(
                f"SELECT college_code, MAX(college_name) AS name, MAX(state) AS state, MAX(institute_type) AS itype, "
                f"quota, SUM(seats) AS seats FROM pg_seat_matrix WHERE counselling_body IN ({ph}) "
                f"GROUP BY college_code, quota HAVING MAX(CASE WHEN COALESCE(cutoff_institute,'')<>'' THEN 1 ELSE 0 END)=0",
                bodies).fetchall():
            n = new_by_code.setdefault(r['college_code'], {
                'college': rec._short_name(r['name']), 'state': r['state'], 'institute_type': r['itype'] or '',
                'college_code': r['college_code'], 'lists': [], 'seats_by_list': {}})
            q = _QUOTA_LABEL.get(r['quota'], r['quota'])
            if q not in n['seats_by_list']:
                n['lists'].append(q)
            n['seats_by_list'][q] = int(r['seats'] or 0)
    news = sorted(new_by_code.values(), key=lambda x: (x['state'], x['college']))
    for n in news:
        n['seats'] = sum(n['seats_by_list'].values())
    return {'lists': lists, 'new_colleges': news, 'generated_at': _ist_now().strftime('%d %b %Y, %I:%M %p IST')}


# ── PDFs ─────────────────────────────────────────────────────────────────────
def _pdf_base(title, subtitle):
    from pg_admin.choice_pdf import _PDF, _LOGO, _NAVY, _ORANGE, _t
    import os
    pdf = _PDF(orientation='P', unit='mm', format='A4')
    pdf.set_margins(12, 12, 12)
    pdf.set_auto_page_break(True, margin=16)
    pdf.alias_nb_pages()
    pdf.footer_note = ('GooCampus guidance based on last year\'s MCC main-round allotments. A suggestion only - '
                       'please verify before locking your choices.')
    pdf.add_page()
    try:
        if os.path.exists(_LOGO):
            pdf.image(_LOGO, x=12, y=10, h=12)
    except Exception:
        pass
    pdf.set_xy(60, 10)
    pdf.set_font('Helvetica', 'B', 15); pdf.set_text_color(*_NAVY)
    pdf.cell(0, 7, _t(title), align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.set_x(60); pdf.set_font('Helvetica', 'B', 10); pdf.set_text_color(*_ORANGE)
    pdf.cell(0, 6, _t(subtitle), align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(4); pdf.set_draw_color(*_ORANGE); pdf.set_line_width(0.6)
    pdf.line(12, pdf.get_y(), 198, pdf.get_y()); pdf.ln(3)
    return pdf


def _table(pdf, rows, heads, widths, aligns):
    from pg_admin.choice_pdf import _t, _head_style
    pdf.set_font('Helvetica', '', 8.6)
    pdf.set_draw_color(220, 224, 230); pdf.set_line_width(0.2)
    with pdf.table(col_widths=widths, text_align=aligns, line_height=4.8, headings_style=_head_style(),
                   first_row_as_headings=True, repeat_headings=1) as t:
        hr = t.row()
        for h in heads:
            hr.cell(h)
        for r in rows:
            row = t.row()
            for v in r:
                row.cell(_t(v))


def build_rankings_pdf(conn):
    from pg_admin.choice_pdf import _t, _NAVY, _GREY
    data = rankings_data(conn)
    pdf = _pdf_base('MCC College Rankings 2026', 'GooCampus guidance · Top · Good · Average colleges')
    pdf.set_font('Helvetica', '', 8.6); pdf.set_text_color(*_GREY)
    pdf.multi_cell(0, 4.4, _t(
        'How to read this: colleges are grouped by how quickly their seats were taken in the MAIN rounds of last '
        "year's MCC counselling (Round 1 / Round 2; mop-up and stray rounds are ignored). It is by college only - "
        'not by speciality or location. Colleges that are new in 2026 are listed in a separate document. '
        f"Prepared by the GooCampus team on {data['generated_at']}."), new_x='LMARGIN', new_y='NEXT')
    TIER_COL = {'Top': (22, 101, 52), 'Good': (37, 99, 235), 'Average': (107, 114, 128)}
    for lst in data['lists']:
        if not any(lst['tiers'].values()):
            continue
        if pdf.get_y() > 240:
            pdf.add_page()
        pdf.ln(4); pdf.set_font('Helvetica', 'B', 13); pdf.set_text_color(*_NAVY)
        pdf.cell(0, 8, _t(lst['label']), new_x='LMARGIN', new_y='NEXT')
        for tier in _TIER_ORDER:
            rows = lst['tiers'].get(tier) or []
            if not rows:
                continue
            if pdf.get_y() > 250:
                pdf.add_page()
            pdf.ln(1); pdf.set_font('Helvetica', 'B', 10.5); pdf.set_text_color(*TIER_COL[tier])
            pdf.cell(0, 6.5, f'{tier} colleges ({len(rows)})', new_x='LMARGIN', new_y='NEXT')
            _table(pdf, [[str(i), r['college'], r['state'], r['institute_type'], str(r['seats'])]
                         for i, r in enumerate(rows, start=1)],
                   ('#', 'College', 'State', 'Institute type', '2026 seats'), (9, 90, 32, 40, 15),
                   ('CENTER', 'LEFT', 'LEFT', 'LEFT', 'RIGHT'))
    return bytes(pdf.output()), 'GooCampus_MCC_College_Rankings_2026.pdf'


def build_new_colleges_pdf(conn):
    from pg_admin.choice_pdf import _t, _GREY
    data = rankings_data(conn)
    pdf = _pdf_base('New colleges in 2026', 'MCC PG counselling · colleges with no previous allotment')
    pdf.set_font('Helvetica', '', 8.8); pdf.set_text_color(*_GREY)
    pdf.multi_cell(0, 4.6, _t(
        "These colleges appear in MCC's 2026 seat matrix for the first time, so there is no previous year's "
        'allotment to judge them by. We have not graded them - look at each one on its own merits (hospital, '
        'faculty, location) before adding it to your choices.'), new_x='LMARGIN', new_y='NEXT')
    pdf.ln(3)
    rows = data['new_colleges']
    if rows:
        _table(pdf, [[str(i), r['college'], r['state'], r['institute_type'], ', '.join(r['lists']), str(r['seats'])]
                     for i, r in enumerate(rows, start=1)],
               ('#', 'College', 'State', 'Institute type', 'Seat lists', '2026 seats'), (8, 66, 26, 30, 42, 14),
               ('CENTER', 'LEFT', 'LEFT', 'LEFT', 'LEFT', 'RIGHT'))
    else:
        pdf.set_font('Helvetica', 'I', 10)
        pdf.cell(0, 8, 'No new colleges in this year\'s MCC seat matrix.', new_x='LMARGIN', new_y='NEXT')
    return bytes(pdf.output()), 'GooCampus_New_Colleges_2026.pdf'


def _pdf_resp(kind):
    conn = get_db()
    try:
        pdf, fn = (build_new_colleges_pdf if kind == 'new' else build_rankings_pdf)(conn)
        return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'attachment; filename="{fn}"'})
    finally:
        conn.close()


# ── Access ───────────────────────────────────────────────────────────────────
def _doctor_or_desk():
    """Internal / Paid doctor (choice-list plan) or a Desk team member. → (ok, err_response)."""
    from pg_admin.routes.api import _authorized, _bearer_token, _pg_user_by_token
    from pg_admin.routes.api_choice import _plan_has
    if not _authorized():
        return False, (jsonify({'ok': False, 'error': 'unauthorized'}), 401)
    conn = get_db()
    try:
        tok = _bearer_token()
        u = _pg_user_by_token(conn, tok) if tok else None
        if not u:
            return False, (jsonify({'ok': False, 'error': 'no_token'}), 401)
        u = dict(u)
        if int(u.get('desk_access') or 0) == 1 and int(u.get('is_team_member') or 0) == 1:
            return True, None
        if _plan_has(conn, u['id'], 'dash_choice_list'):
            return True, None
        return False, (jsonify({'ok': False, 'error': 'not_entitled',
                                'message': 'The GooCampus College Rankings are for Internal and paid doctors.'}), 403)
    finally:
        conn.close()


def api_rankings():
    """GET /api/pg/rankings → the rankings for the dashboard page (Internal / Paid / desk)."""
    ok, err = _doctor_or_desk()
    if not ok:
        return err
    conn = get_db()
    try:
        return jsonify({'ok': True, **rankings_data(conn)})
    except Exception as e:
        logging.error("api_rankings: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_rankings_pdf():
    """GET /api/pg/rankings/pdf?kind=rankings|new"""
    ok, err = _doctor_or_desk()
    if not ok:
        return err
    return _pdf_resp('new' if (request.args.get('kind') or '') == 'new' else 'rankings')


def admin_rankings_pdf():
    from core.users import get_user
    u = get_user()
    if not (u and u.get('is_admin')):
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    return _pdf_resp('new' if (request.args.get('kind') or '') == 'new' else 'rankings')


# ── Email to all Internal + Paid doctors ─────────────────────────────────────
def _ensure_log(conn):
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_rankings_email_log (
            id SERIAL PRIMARY KEY,
            kind TEXT DEFAULT 'all',          -- all | test
            requested_by TEXT DEFAULT '',
            recipients INTEGER DEFAULT 0,
            sent INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'queued',     -- queued | sending | done
            test_to TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP
        )''')
        conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass


def _recipients(conn):
    """Internal + Paid doctors with an email (desk categorisation), de-duplicated."""
    from pg_admin.routes.desk_api import _type_sql
    rows = conn.execute(
        f"SELECT x.name, LOWER(TRIM(x.email)) AS email FROM (SELECT u.name, u.email, {_type_sql('u')} AS t "
        f"FROM pg_users u WHERE COALESCE(u.is_blocked,0)=0) x WHERE x.t IN ('internal','paid') "
        f"AND COALESCE(x.email,'') <> '' AND strpos(x.email, '@') > 0").fetchall()
    seen, out = set(), []
    for r in rows:
        if r['email'] in seen:
            continue
        seen.add(r['email']); out.append({'email': r['email'], 'name': r['name'] or ''})
    return out


def _email_html(name, sender):
    from email_utils import render_branded_email
    from html import escape
    n = (name or '').strip()
    dr = n if n.lower().startswith('dr') else ('Dr. ' + n if n else 'Doctor')
    inner = (f"<p style='margin:0 0 14px;font-size:15px;color:#0F1B33;'>Dear {escape(dr)},</p>"
             "<p style='margin:0 0 14px;font-size:14px;color:#374151;line-height:1.6;'>Please find attached the "
             "<b>GooCampus MCC College Rankings 2026</b> — the All India Quota, Deemed (Paid and NRI) and Central "
             "University colleges grouped as <b>Top, Good and Average</b>, based on how quickly their seats were "
             "taken in last year's main counselling rounds. A second document lists the <b>colleges that are new "
             "in 2026</b>, which have no previous allotment to grade them by.</p>"
             "<p style='margin:0 0 14px;font-size:14px;color:#374151;line-height:1.6;'>Use this alongside your "
             "personalised choice list on <a href='https://goocampus.in/dashboard' style='color:#EA6C1E;'>"
             "goocampus.in</a>. Your counsellor is happy to talk it through.</p>"
             "<p style='margin:0 0 16px;font-size:12px;color:#6b7280;line-height:1.55;border-left:3px solid #fdba74;"
             "padding:6px 10px;background:#fff7ed;'>This is GooCampus guidance based on last year's allotments — a "
             "suggestion only. Please verify every choice before you lock it; the final decision is yours.</p>"
             f"<p style='margin:0;font-size:14px;color:#374151;'>Warm regards,<br>{escape(sender)}<br>Team GooCampus</p>")
    return render_branded_email('MCC College Rankings 2026', inner,
                                preheader='Top, Good and Average MCC colleges + new colleges in 2026')


def _send_all(log_id, sender, test_to=''):
    from email_utils import send_email
    conn = get_db()
    try:
        a, fa = build_rankings_pdf(conn)
        b, fb = build_new_colleges_pdf(conn)
        recips = [{'email': test_to, 'name': ''}] if test_to else _recipients(conn)
        conn.execute("UPDATE pg_rankings_email_log SET status='sending', recipients=? WHERE id=?", [len(recips), log_id])
        conn.commit()
    except Exception as e:
        logging.error("rankings email prepare: %s", e)
        try: conn.rollback()
        except Exception: pass
        conn.close()
        return
    atts = [{'filename': fa, 'content': base64.b64encode(a).decode('ascii')},
            {'filename': fb, 'content': base64.b64encode(b).decode('ascii')}]
    sent = failed = 0
    for r in recips:
        try:
            ok = send_email([r['email']], 'GooCampus MCC College Rankings 2026 — Top, Good & Average colleges',
                            _email_html(r['name'], sender), from_address='GooCampus <info@goocampus.in>',
                            attachments=atts)
            sent += 1 if ok else 0
            failed += 0 if ok else 1
        except Exception as e:
            failed += 1
            logging.error("rankings email to %s: %s", r['email'], e)
        time.sleep(0.4)            # Resend: 2 req/sec
    try:
        conn.execute("UPDATE pg_rankings_email_log SET status='done', sent=?, failed=?, finished_at=CURRENT_TIMESTAMP "
                     "WHERE id=?", [sent, failed, log_id])
        conn.commit()
    finally:
        conn.close()


def desk_rankings_email():
    """GET → recent sends + recipient count.  POST {test_to?} → test to one address, else to ALL
    Internal + Paid doctors (background, throttled)."""
    from pg_admin.routes.desk_api import _guard, _actor_name
    import re
    m, _, err = _guard()
    if err:
        return err
    conn = get_db()
    try:
        _ensure_log(conn)
        if request.method == 'GET':
            log = [dict(r) for r in conn.execute(
                "SELECT kind, requested_by, recipients, sent, failed, status, test_to, created_at, finished_at "
                "FROM pg_rankings_email_log ORDER BY id DESC LIMIT 20").fetchall()]
            for r in log:
                for k in ('created_at', 'finished_at'):
                    r[k] = str(r[k])[:19] if r.get(k) else ''
            return jsonify({'ok': True, 'recipients': len(_recipients(conn)), 'log': log})
        body = request.get_json(silent=True) or {}
        test_to = (body.get('test_to') or '').strip()
        if test_to and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', test_to):
            return jsonify({'ok': False, 'error': 'bad_email'}), 400
        if not test_to and not body.get('confirm'):
            return jsonify({'ok': False, 'error': 'confirm_required',
                            'message': 'Send {confirm:true} to email every Internal + Paid doctor.'}), 400
        who = _actor_name(m)
        lid = conn.execute("INSERT INTO pg_rankings_email_log (kind, requested_by, test_to) VALUES (?,?,?) RETURNING id",
                           ['test' if test_to else 'all', who, test_to]).fetchone()['id']
        n = 1 if test_to else len(_recipients(conn))
        conn.commit()
    finally:
        conn.close()
    threading.Thread(target=_send_all, args=(lid, who, test_to), daemon=True).start()
    return jsonify({'ok': True, 'queued': n, 'log_id': lid, 'test': bool(test_to)})
