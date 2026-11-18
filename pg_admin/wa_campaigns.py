"""WhatsApp — "what template to whom" (founder 2026-11-17: "I can't go to each registered user and switch on …
I need an option to decide what template to whom to send").

Two parts, both on Registered Doctors → 💬 WhatsApp:

1. WHO GETS each AUTOMATIC message (pg_kv 'wa_aud_<msg>', JSON). Welcome + Daily update: doctor type
   (Free / Paid / Internal) + home states (none chosen = every state). Profile reminder: Free / Paid / Internal
   (no states — their state is what's missing).
   Enquiry: which enquiry sources (website enquiries / Management-NRI call-backs). The default (nothing saved)
   is exactly the old behaviour, so saving nothing changes nothing.

2. SEND TO A GROUP NOW (/admin/pg/users/whatsapp/send). Pick any APPROVED template from the register
   (WhatsApp → Templates), say what each {{n}} is (doctor name / home state / fixed text), pick the group with
   the same filters as the Registered Doctors list (type, states, signed-up window or dates, profile, NEET
   qualified, seat allotment, lead status), see the count + sample + the real message, then Send.
   Each recipient is queued in pg_wa_nudge_log as kind 'campaign:<id>' (UNIQUE per doctor → never twice) and
   sent by a background thread on the LIVE service (staging previews only — both share one DB). A stalled
   send is resumed by the 10-minute sweep. Numbers that replied STOP / "Stop updates" are always skipped.
"""
import json
import logging
import os
import re
import threading
import time

from db import get_db

logger = logging.getLogger(__name__)

TYPES = (('free', 'Free'), ('paid', 'Paid'), ('internal', 'Internal (comped)'), ('team', 'Team'))
DEFAULT_TYPES = ['free', 'paid', 'internal']           # team never, unless ticked on a group send
AUTO_MSGS = ('welcome', 'incomplete', 'daily', 'enquiry')
ENQ_SOURCES = (('website', 'goocampus.in website enquiries (Sales → Inquiries)'),
               ('mgmt', 'Management / NRI call-backs'))
VAR_SOURCES = (('name', 'Doctor name'), ('state', 'Home state'), ('fixed', 'Fixed text (same for everyone)'))
MAX_PER_SEND = 5000
_READY = {'done': False}


def _is_staging():
    return (os.environ.get('RENDER_SERVICE_NAME') or '').endswith('staging')


def ensure(conn):
    if _READY['done']:
        return
    from pg_admin import wa_nudges as w
    w.ensure_tables(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS pg_wa_campaigns (
        id SERIAL PRIMARY KEY, template TEXT NOT NULL, language TEXT DEFAULT 'en', sender TEXT DEFAULT '',
        variables TEXT DEFAULT '[]', filters TEXT DEFAULT '{}', audience_label TEXT DEFAULT '',
        total INTEGER DEFAULT 0, sent INTEGER DEFAULT 0, failed INTEGER DEFAULT 0, skipped INTEGER DEFAULT 0,
        status TEXT DEFAULT 'sending', created_by TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        heartbeat TIMESTAMP, finished_at TIMESTAMP)''')
    conn.commit()
    _READY['done'] = True


# ── 1. automatic-message audiences ─────────────────────────────────────────
def get_aud(conn, msg):
    from pg_admin import wa_nudges as w
    raw = w._kv(conn, 'wa_aud_' + msg)
    try:
        a = json.loads(raw) if raw else {}
    except Exception:
        a = {}
    if msg == 'enquiry':
        src = a.get('sources')
        return {'sources': [s for s in src if s in dict(ENQ_SOURCES)] if isinstance(src, list) else ['website', 'mgmt']}
    allowed = ['free', 'paid', 'internal', 'team']
    # Default (nothing saved): news update also goes to team members (founder 2026-11-18); the sign-up messages don't.
    default = list(allowed) if msg == 'daily' else ['free', 'paid', 'internal']
    t = a.get('types')
    types = [x for x in t if x in allowed] if isinstance(t, list) else default
    st = a.get('states') if isinstance(a.get('states'), list) else []
    return {'types': types, 'states': [s for s in st if s]}


def set_aud(conn, msg, aud, who):
    from pg_admin import wa_nudges as w
    w.ensure_tables(conn)
    conn.execute("INSERT INTO pg_kv (key, value, updated_by, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                 "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, "
                 "updated_at = CURRENT_TIMESTAMP", ('wa_aud_' + msg, json.dumps(aud), who))
    conn.commit()


def aud_label(msg, aud):
    if msg == 'enquiry':
        s = aud.get('sources') or []
        return 'nobody (no source ticked)' if not s else ' + '.join(
            {'website': 'website enquiries', 'mgmt': 'Management / NRI call-backs'}[x] for x in s)
    t = aud.get('types') or []
    if not t:
        return 'nobody (switched off for this message)'
    who = ' + '.join(dict(TYPES)[x].split(' ')[0] for x in t) + ' doctors'
    st = aud.get('states') or []
    return who + (', home state: ' + ', '.join(st[:6]) + (' …' if len(st) > 6 else '') if st else ', all states')


def cat_sql(ualias='u'):
    """The Registered Doctors category rule, with Counselling-Desk logins counted as Team."""
    from pg_admin.routes.users_admin import _category_case
    return (f"CASE WHEN COALESCE((to_jsonb({ualias})->>'desk_access')::int,0) = 1 THEN 'team' "
            f"ELSE ({_category_case(ualias)}) END")


def categories(conn, ids=None):
    """{user_id: 'team'|'internal'|'paid'|'free'} — the Registered Doctors list's own category rule."""
    sql = f"SELECT u.id, ({cat_sql('u')}) AS cat FROM pg_users u"
    params = ()
    if ids is not None:
        ids = [int(i) for i in ids if i]
        if not ids:
            return {}
        sql += " WHERE u.id IN (" + ','.join(['?'] * len(ids)) + ")"
        params = tuple(ids)
    return {r['id']: r['cat'] for r in conn.execute(sql, params).fetchall()}


def aud_allows(aud, cat, state):
    if cat not in (aud.get('types') or []):
        return False
    st = [s.strip().lower() for s in aud.get('states') or []]
    return not st or (state or '').strip().lower() in st


# ── 2. group sends ─────────────────────────────────────────────────────────
def parse_filters(form):
    """Group filters from a form / stored JSON (lists come from getlist when available)."""
    def lst(k):
        if hasattr(form, 'getlist'):
            return [v for v in form.getlist(k) if v]
        v = form.get(k)
        return v if isinstance(v, list) else ([v] if v else [])
    f = {'types': [t for t in lst('types') if t in dict(TYPES)],
         'states': lst('states'),
         'reg': (form.get('reg') or '').strip(), 'reg_from': (form.get('reg_from') or '').strip(),
         'reg_to': (form.get('reg_to') or '').strip(), 'prof': (form.get('prof') or '').strip(),
         'qual': (form.get('qual') or '').strip(), 'allot': (form.get('allot') or '').strip(),
         'lead': (form.get('lead') or '').strip(),
         'skip_got': str(form.get('skip_got') or '') in ('1', 'on', 'true', 'True')}
    for k in ('reg_from', 'reg_to'):
        if f[k] and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', f[k]):
            f[k] = ''
    return f


def filters_label(f):
    from pg_admin.routes import users_admin as ua
    bits = [' + '.join(dict(TYPES)[t].split(' ')[0] for t in f.get('types') or []) or 'no type ticked']
    if f.get('states'):
        bits.append('home state ' + ', '.join(f['states'][:5]) + (' …' if len(f['states']) > 5 else ''))
    if f.get('reg') in ua._REG_WINDOWS:
        bits.append('signed up ' + ua._REG_WINDOWS[f['reg']][0].lower())
    if f.get('reg_from') or f.get('reg_to'):
        bits.append(f"signed up {f.get('reg_from') or '…'} to {f.get('reg_to') or 'today'}")
    if f.get('prof') in ua._PROF_FILTERS:
        bits.append(ua._PROF_FILTERS[f['prof']][0].lower())
    if f.get('qual') in ua._QUAL_LABELS:
        bits.append('NEET ' + ua._QUAL_LABELS[f['qual']].lower())
    if f.get('allot') in ('yes', 'no', 'norank'):
        bits.append({'yes': 'seat allotted', 'no': 'no seat yet', 'norank': 'no rank entered'}[f['allot']])
    if f.get('lead'):
        bits.append('status ' + f['lead'])
    return ' · '.join(bits)


def audience(conn, f, need_name=False, need_state=False):
    """Doctors matching the group filters → [{id, name, mobile, state, cat}], deduped by mobile, opted-out and
    unusable numbers removed. Returns (rows, skipped_counts)."""
    from pg_admin.routes import users_admin as ua
    from pg_admin import wa_nudges as w
    types = f.get('types') or []
    if not types:
        return [], {}
    cat = cat_sql('u')
    conds = ["COALESCE(u.is_blocked,0) = 0", "COALESCE(u.mobile,'') <> ''",
             f"({cat}) IN (" + ','.join(['?'] * len(types)) + ")"]
    params = list(types)
    if f.get('states'):
        conds.append("LOWER(TRIM(COALESCE(u.state,''))) IN (" + ','.join(['?'] * len(f['states'])) + ")")
        params += [s.strip().lower() for s in f['states']]
    if f.get('reg') in ua._REG_WINDOWS:
        conds.append(ua._REG_WINDOWS[f['reg']][1])
    if f.get('reg_from'):
        conds.append(f"{ua._IST_DAY} >= ?::date"); params.append(f['reg_from'])
    if f.get('reg_to'):
        conds.append(f"{ua._IST_DAY} <= ?::date"); params.append(f['reg_to'])
    if f.get('prof') in ua._PROF_FILTERS:
        conds.append(ua._PROF_FILTERS[f['prof']][1])
    if f.get('qual') in ua._QUAL_LABELS:
        from pg_admin import neet_qualify as nq
        conds.append(nq.qual_sql(conn)[f['qual']])
    if f.get('allot') in ('yes', 'no', 'norank'):
        has = ua._allotted_sql()
        norank = "(COALESCE(u.neet_pg_rank,0) <= 0 AND COALESCE(u.home_state_rank,0) <= 0)"
        conds.append({'yes': has, 'no': f"(NOT {norank} AND NOT {has})", 'norank': norank}[f['allot']])
    if need_name:
        conds.append("TRIM(COALESCE(u.name,'')) <> ''")
    if need_state:
        conds.append("TRIM(COALESCE(u.state,'')) <> ''")
    rows = [dict(r) for r in conn.execute(
        f"SELECT u.id, u.name, u.mobile, u.email, u.state, ({cat}) AS cat FROM pg_users u "
        f"WHERE {' AND '.join(conds)} ORDER BY u.id", tuple(params)).fetchall()]
    if f.get('lead'):
        from pg_admin import followups as fu
        sts = fu.statuses_for(conn, rows)
        rows = [r for r, s in zip(rows, sts) if s == f['lead']]
    skipped = {'bad_number': 0, 'duplicate_number': 0, 'stopped': 0}
    optout = {r['mobile10'] for r in conn.execute("SELECT mobile10 FROM pg_wa_optout").fetchall()}
    out, seen = [], set()
    for r in rows:
        to = w.mobile_to(r.get('mobile'))
        if not to:
            skipped['bad_number'] += 1; continue
        if to in seen:
            skipped['duplicate_number'] += 1; continue
        seen.add(to)
        if to[-10:] in optout:
            skipped['stopped'] += 1; continue
        r['to'] = to
        out.append(r)
    return out, skipped


def approved_templates(conn):
    """The register's APPROVED templates: [{name, language, sender, body_text, buttons, category, nvars}]."""
    try:
        from pg_admin import wa_registry
        wa_registry.prepare(conn)
    except Exception:
        pass
    rows = [dict(r) for r in conn.execute(
        "SELECT name, language, sender, body_text, buttons, category, purpose FROM wa_templates "
        "WHERE UPPER(COALESCE(status,'')) = 'APPROVED' ORDER BY name, id").fetchall()]
    out, seen = [], set()
    for r in rows:
        if r['name'] in seen:
            continue
        seen.add(r['name'])
        r['nvars'] = max([int(n) for n in re.findall(r'\{\{\s*(\d+)\s*\}\}', r.get('body_text') or '')] or [0])
        out.append(r)
    return out


def parse_vars(form, nvars):
    """[{src, text}] for {{1}}..{{n}}."""
    out = []
    for i in range(1, nvars + 1):
        src = form.get(f'v{i}_src') or ('name' if i == 1 else 'fixed')
        if src not in dict(VAR_SOURCES):
            src = 'fixed'
        out.append({'src': src, 'text': (form.get(f'v{i}_text') or '').strip()[:200]})
    return out


def placeholders_for(vars_, doc):
    from pg_admin import wa_nudges as w
    ph = []
    for v in vars_:
        if v['src'] == 'name':
            ph.append(w.welcome_name(doc.get('name')) or 'Doctor')
        elif v['src'] == 'state':
            ph.append(w.clean_placeholder(doc.get('state')) or 'your state')
        else:
            ph.append(w.clean_placeholder(v.get('text'), 200))
    return ph


def render_body(body, ph):
    return re.sub(r'\{\{\s*(\d+)\s*\}\}', lambda m: ph[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(ph)
                  else m.group(0), body or '')


def create(conn, tpl, vars_, f, docs, who):
    """Queue one group send. Returns campaign id."""
    ensure(conn)
    if f.get('skip_got'):
        got = {r['user_id'] for r in conn.execute(
            "SELECT DISTINCT user_id FROM pg_wa_nudge_log WHERE template = ? AND status = 'sent' AND user_id IS NOT NULL",
            (tpl['name'],)).fetchall()}
        docs = [d for d in docs if d['id'] not in got]
    docs = docs[:MAX_PER_SEND]
    cid = conn.execute(
        "INSERT INTO pg_wa_campaigns (template, language, sender, variables, filters, audience_label, total, "
        "status, created_by, heartbeat) VALUES (?, ?, ?, ?, ?, ?, ?, 'sending', ?, CURRENT_TIMESTAMP) RETURNING id",
        (tpl['name'], tpl.get('language') or 'en', tpl.get('sender') or '', json.dumps(vars_), json.dumps(f),
         filters_label(f), len(docs), who)).fetchone()['id']
    kind = f'campaign:{cid}'
    for d in docs:
        conn.execute("INSERT INTO pg_wa_nudge_log (user_id, kind, template, mobile, status, sent_by) "
                     "VALUES (?, ?, ?, ?, 'queued', ?) ON CONFLICT (user_id, kind) DO NOTHING",
                     (d['id'], kind, tpl['name'], d['to'][-4:], who))
    conn.commit()
    return cid


def _counts(conn, cid):
    r = {x['status']: x['n'] for x in conn.execute(
        "SELECT status, COUNT(*) AS n FROM pg_wa_nudge_log WHERE kind = ? GROUP BY status",
        (f'campaign:{cid}',)).fetchall()}
    return r


def run_campaign(cid):
    """Send every queued recipient of one campaign. One runner per campaign (advisory lock)."""
    from pg_admin import wa_nudges as w
    conn = get_db()
    locked = False
    try:
        ensure(conn)
        locked = conn.execute("SELECT pg_try_advisory_lock(hashtext(?)) AS ok", (f'pg_wa_camp_{cid}',)).fetchone()['ok']
        conn.commit()
        if not locked:
            return
        c = conn.execute("SELECT * FROM pg_wa_campaigns WHERE id = ?", (cid,)).fetchone()
        if not c or c['status'] != 'sending':
            return
        c = dict(c)
        vars_ = json.loads(c.get('variables') or '[]')
        langs = tuple(dict.fromkeys([c.get('language') or 'en'] + list(w.LANGS)))
        kind = f'campaign:{cid}'
        while True:
            st = conn.execute("SELECT status FROM pg_wa_campaigns WHERE id = ?", (cid,)).fetchone()
            if not st or st['status'] != 'sending':
                break
            batch = conn.execute(
                "SELECT l.id, l.user_id, u.name, u.state, u.mobile FROM pg_wa_nudge_log l "
                "LEFT JOIN pg_users u ON u.id = l.user_id WHERE l.kind = ? AND l.status = 'queued' "
                "ORDER BY l.id LIMIT 25", (kind,)).fetchall()
            if not batch:
                break
            for b in batch:
                got = conn.execute("UPDATE pg_wa_nudge_log SET status = 'sending' WHERE id = ? AND status = 'queued' "
                                   "RETURNING id", (b['id'],)).fetchone()
                conn.commit()
                if not got:
                    continue
                to = w.mobile_to(b['mobile'])
                if not to or w.opted_out(conn, to):
                    conn.execute("UPDATE pg_wa_nudge_log SET status = 'skipped', response = ? WHERE id = ?",
                                 ('no valid number' if not to else 'opted out', b['id']))
                    conn.commit()
                    continue
                ok, resp = w.send_template(to, c['template'], placeholders_for(vars_, dict(b)),
                                           sender=c.get('sender') or None, langs=langs)
                w._finish(conn, b['id'], ok, resp)
                time.sleep(0.15)
            n = _counts(conn, cid)
            conn.execute("UPDATE pg_wa_campaigns SET sent = ?, failed = ?, skipped = ?, heartbeat = CURRENT_TIMESTAMP "
                         "WHERE id = ?", (n.get('sent', 0), n.get('failed', 0), n.get('skipped', 0), cid))
            conn.commit()
        n = _counts(conn, cid)
        conn.execute("UPDATE pg_wa_campaigns SET sent = ?, failed = ?, skipped = ?, heartbeat = CURRENT_TIMESTAMP, "
                     "status = CASE WHEN status = 'sending' AND ? = 0 THEN 'done' ELSE status END, "
                     "finished_at = CASE WHEN status = 'sending' AND ? = 0 THEN CURRENT_TIMESTAMP ELSE finished_at END "
                     "WHERE id = ?", (n.get('sent', 0), n.get('failed', 0), n.get('skipped', 0),
                                      n.get('queued', 0), n.get('queued', 0), cid))
        conn.commit()
    except Exception as e:
        logger.error("wa campaign %s: %s", cid, e)
        try: conn.rollback()
        except Exception: pass
    finally:
        if locked:
            try:
                conn.execute("SELECT pg_advisory_unlock(hashtext(?))", (f'pg_wa_camp_{cid}',)); conn.commit()
            except Exception:
                pass
        conn.close()


def start(cid):
    threading.Thread(target=run_campaign, args=(cid,), daemon=True, name=f'wa-camp-{cid}').start()


def resume_stalled(conn):
    """Called by the 10-minute sweep (live only): restart any send whose runner died (deploy / restart)."""
    try:
        ensure(conn)
        rows = conn.execute("SELECT id FROM pg_wa_campaigns WHERE status = 'sending' AND "
                            "(heartbeat IS NULL OR heartbeat < CURRENT_TIMESTAMP - INTERVAL '3 minutes')").fetchall()
        conn.commit()
        for r in rows:
            start(r['id'])
    except Exception as e:
        logger.warning("wa campaign resume: %s", e)
        try: conn.rollback()
        except Exception: pass


# ── pages ──────────────────────────────────────────────────────────────────
def _admin():
    from pg_admin.routes.users_admin import _require_users_section
    return _require_users_section('view')


def _who(a):
    return a.get('name') or a.get('emp_code') or 'admin'


def admin_audience():
    """POST — save 'who gets it' for one automatic message."""
    from flask import request, redirect, url_for, flash
    a = _admin()
    if not a or not a.get('is_admin'):
        flash('Only an admin can change who gets the messages.', 'error'); return redirect(url_for('pg_wa_nudges'))
    msg = request.form.get('msg')
    if msg not in AUTO_MSGS:
        return redirect(url_for('pg_wa_nudges'))
    if msg == 'enquiry':
        aud = {'sources': [s for s in request.form.getlist('sources') if s in dict(ENQ_SOURCES)]}
    else:
        allowed = ['free', 'paid', 'internal', 'team']
        aud = {'types': [t for t in request.form.getlist('types') if t in allowed],
               'states': [] if msg == 'incomplete' else [s for s in request.form.getlist('states') if s]}
    conn = get_db()
    try:
        set_aud(conn, msg, aud, _who(a))
        flash('Saved — ' + aud_label(msg, aud) + '.', 'success')
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("wa audience save: %s", e)
        flash('Could not save.', 'error')
    finally:
        conn.close()
    return redirect(url_for('pg_wa_nudges') + '#aud-' + msg)


def send_page():
    """GET = form; POST action=preview | test | send."""
    from flask import request, render_template, redirect, url_for, flash
    from pg_admin.routes import users_admin as ua
    from pg_admin import wa_nudges as w
    a = _admin()
    if not a:
        flash('Admin access required', 'error'); return redirect(url_for('dashboard'))
    can_send = bool(a.get('is_admin'))
    conn = get_db()
    ctx = {'preview': None, 'sample': [], 'skipped': {}, 'msg': '', 'camps': []}
    try:
        ensure(conn)
        tpls = approved_templates(conn)
        form = request.form if request.method == 'POST' else request.args
        tname = form.get('template') or ''
        tpl = next((t for t in tpls if t['name'] == tname), None)
        f = parse_filters(form) if request.method == 'POST' else {
            'types': list(DEFAULT_TYPES), 'states': [], 'reg': '', 'reg_from': '', 'reg_to': '', 'prof': '',
            'qual': '', 'allot': '', 'lead': '', 'skip_got': True}
        vars_ = parse_vars(form, tpl['nvars']) if tpl else []
        action = request.form.get('action') if request.method == 'POST' else ''
        if action and not tpl:
            flash('Pick a template first.', 'error'); action = ''
        if action and not can_send:
            flash('Only an admin can send.', 'error'); action = ''
        if action and any(v['src'] == 'fixed' and not v['text'] for v in vars_):
            flash('Fill in the text for every {{n}} set to "Fixed text".', 'error'); action = ''
        if action:
            need_name = any(v['src'] == 'name' for v in vars_)
            need_state = any(v['src'] == 'state' for v in vars_)
            docs, skipped = audience(conn, f, need_name, need_state)
            if f.get('skip_got'):
                got = {r['user_id'] for r in conn.execute(
                    "SELECT DISTINCT user_id FROM pg_wa_nudge_log WHERE template = ? AND status = 'sent' "
                    "AND user_id IS NOT NULL", (tpl['name'],)).fetchall()}
                before = len(docs)
                docs = [d for d in docs if d['id'] not in got]
                skipped['already_got'] = before - len(docs)
            ctx.update(preview=len(docs), sample=docs[:15], skipped=skipped,
                       msg=render_body(tpl['body_text'], placeholders_for(vars_, docs[0] if docs else
                                                                          {'name': 'Example', 'state': 'Karnataka'})))
            if action == 'test':
                to = w.mobile_to(request.form.get('test_mobile'))
                if not to:
                    flash('Enter your 10-digit mobile for the test.', 'error')
                else:
                    ok, resp = w.send_template(to, tpl['name'], placeholders_for(
                        vars_, docs[0] if docs else {'name': 'Test', 'state': 'Karnataka'}),
                        sender=tpl.get('sender') or None,
                        langs=tuple(dict.fromkeys([tpl.get('language') or 'en'] + list(w.LANGS))))
                    conn.execute("INSERT INTO pg_wa_nudge_log (user_id, kind, template, mobile, status, response, "
                                 "sent_by) VALUES (NULL, 'test', ?, ?, ?, ?, ?)",
                                 (tpl['name'], to[-4:], 'sent' if ok else 'failed', resp[:900], _who(a)))
                    conn.commit()
                    flash(('Test accepted — check your phone. ' if ok else 'Test FAILED: ') + resp[:250],
                          'success' if ok else 'error')
            elif action == 'send':
                if _is_staging():
                    flash('Staging only previews. Send from goocampus.org (live).', 'error')
                elif not docs:
                    flash('Nobody matches — nothing sent.', 'error')
                elif str(request.form.get('confirm_n') or '') != str(min(len(docs), MAX_PER_SEND)):
                    flash('The group changed since the preview — check the new count and press Send again.', 'error')
                else:
                    cid = create(conn, tpl, vars_, f, docs, _who(a))
                    start(cid)
                    flash(f'Sending "{tpl["name"]}" to {len(docs)} doctors — progress below.', 'success')
                    return redirect(url_for('pg_wa_send') + f'#camp-{cid}')
        ctx['camps'] = [dict(r) for r in conn.execute(
            "SELECT * FROM pg_wa_campaigns ORDER BY id DESC LIMIT 30").fetchall()]
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.error("wa send page: %s", e)
        flash('Something went wrong: ' + str(e)[:200], 'error')
        tpls, tpl, f, vars_ = locals().get('tpls') or [], None, parse_filters({}), []
    finally:
        conn.close()
    from pg_admin import followups as fu
    return render_template('pg_admin/wa_send.html', tpls=tpls, tpl=tpl, f=f, vars_=vars_, can_send=can_send,
                           types=TYPES, var_sources=VAR_SOURCES, states=ua._canonical_states(),
                           reg_windows=ua._REG_WINDOWS, prof_filters=ua._PROF_FILTERS, qual_labels=ua._QUAL_LABELS,
                           lead_statuses=fu.STATUSES, is_staging=_is_staging(), max_per_send=MAX_PER_SEND,
                           active='wa', active_section='goocampus_in', **ctx)


def stop_campaign(cid):
    from flask import redirect, url_for, flash
    a = _admin()
    if not a or not a.get('is_admin'):
        flash('Only an admin can stop a send.', 'error'); return redirect(url_for('pg_wa_send'))
    conn = get_db()
    try:
        conn.execute("UPDATE pg_wa_campaigns SET status = 'stopped', finished_at = CURRENT_TIMESTAMP "
                     "WHERE id = ? AND status = 'sending'", (cid,))
        conn.execute("UPDATE pg_wa_nudge_log SET status = 'cancelled' WHERE kind = ? AND status = 'queued'",
                     (f'campaign:{cid}',))
        conn.commit()
        flash('Stopped — nobody else in that group will get it.', 'success')
    finally:
        conn.close()
    return redirect(url_for('pg_wa_send'))


def register(app):
    from core.auth import login_required
    app.add_url_rule('/admin/pg/users/whatsapp/audience', 'pg_wa_audience', login_required(admin_audience),
                     methods=['POST'])
    app.add_url_rule('/admin/pg/users/whatsapp/send', 'pg_wa_send', login_required(send_page),
                     methods=['GET', 'POST'])
    app.add_url_rule('/admin/pg/users/whatsapp/send/<int:cid>/stop', 'pg_wa_send_stop',
                     login_required(stop_campaign), methods=['POST'])
