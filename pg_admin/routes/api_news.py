"""Public /api/pg/news* endpoints — the goocampus.in dashboard news feed + a
doctor's saved state subscriptions (founder 2026-09-30).

Feed model: every doctor sees All-India news + their home-state news by default.
Paid doctors (dash_news_follow) can FOLLOW extra states — saved to their profile,
so the admin sees the subscription on the Registered Doctors page and it persists.
The "add a state" picker only offers states that actually have published news.

X-PG-Key guards the reads; the follow endpoints ALSO need the doctor's Bearer token.
The PDF stream is public.
"""
import logging
from flask import request, jsonify, Response
from db import get_db
from pg_admin.routes.api import _authorized
from pg_admin.routes.api_choice import _user, _plan_has, _doctor_states


_NEWS_COLS_OK = False


def ensure_news_seo_cols(conn):
    """category / summary / key_dates on pg_news — request-time guard (boot DDL can skip
    on a Render cold start)."""
    global _NEWS_COLS_OK
    if _NEWS_COLS_OK:
        return
    try:
        for c in ('category', 'summary', 'key_dates', 'schedule'):
            conn.execute(f"ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS {c} TEXT DEFAULT ''")
        # source ('ai_inbox' | 'manual'), the inbox notice it came from, soft delete (2026-10-09)
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'manual'")
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS inbox_id INTEGER")
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP")
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS deleted_by TEXT DEFAULT ''")
        # big attachment archived in R2 instead of pdf_data (2026-10-17)
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS pdf_r2_key TEXT")
        # news that LINKS to an authority document's stored file + email audience (2026-10-22)
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS authority_doc_id INTEGER")
        conn.execute("ALTER TABLE pg_news ADD COLUMN IF NOT EXISTS email_audience TEXT DEFAULT 'all'")
        conn.commit()
        _NEWS_COLS_OK = True
        try:   # label news that was posted from the News Inbox (metadata only)
            conn.execute("UPDATE pg_news n SET source = 'ai_inbox', inbox_id = i.id FROM pg_news_inbox i "
                         "WHERE i.news_id = n.id AND n.inbox_id IS NULL")
            conn.commit()
        except Exception:
            conn.rollback()
    except Exception:
        try: conn.rollback()
        except Exception: pass


def _s(v):
    return (str(v).strip() if v is not None else '')


def _home_state(conn, uid):
    try:
        for st in _doctor_states(conn, uid):
            if (st.get('role') or '') == 'home':
                return st.get('state')
    except Exception:
        pass
    return None


def _follows(conn, uid):
    try:
        return [r['state'] for r in conn.execute(
            "SELECT state FROM pg_news_follows WHERE user_id=? ORDER BY state", [uid]).fetchall()]
    except Exception:
        return []


def _states_with_news(conn):
    """States that currently have published state-scoped news (for the picker)."""
    try:
        return [r['state'] for r in conn.execute(
            "SELECT DISTINCT state FROM pg_news WHERE is_published AND scope='state' "
            "AND COALESCE(state,'')<>'' ORDER BY state").fetchall()]
    except Exception:
        return []


def api_pg_news():
    """GET /api/pg/news — the filtered feed.
    Params:
      states   comma-separated states to include (optional)
      all      '0' to hide All-India items (default: include them)
      body     optional exact body_label filter
      page, page_size (<=100)
    If the doctor's Bearer token is present, their home state + followed states are
    added automatically (so the site can just send the token)."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    states = [s.strip() for s in _s(request.args.get('states')).split(',') if s.strip()]
    include_all = _s(request.args.get('all')) != '0'
    # scope lets the dashboard request ONE tab's news: 'mcc' (All-India/MCC only),
    # 'home' (the doctor's home state only), 'others' (followed states, excl home).
    # Empty = the default blended feed. (founder 2026-10-05)
    scope_req = _s(request.args.get('scope')).lower()
    body = _s(request.args.get('body'))
    try:
        page = max(1, int(request.args.get('page', 1)))
    except Exception:
        page = 1
    try:
        page_size = min(100, max(1, int(request.args.get('page_size', 20))))
    except Exception:
        page_size = 20

    conn = get_db()
    try:
        # Resolve the doctor's home + followed states (when a token is supplied).
        user = _user(conn)
        if scope_req in ('home', 'others') and not user:   # those tabs are the doctor's own — no token, no items
            return jsonify({'ok': True, 'items': [], 'count': 0, 'total': 0, 'page': page,
                            'page_size': page_size, 'total_pages': 0}), 200
        hs = _home_state(conn, user['id']) if user else None
        folls = _follows(conn, user['id']) if user else []
        if scope_req == 'mcc':
            include_all = True; states = []                      # All-India / MCC only
        elif scope_req == 'home':
            include_all = False; states = [hs] if hs else []     # home state only
        elif scope_req == 'others':
            include_all = False                                   # followed states, minus home
            _hl = (hs or '').strip().lower()
            states = [s for s in folls if s.strip().lower() != _hl]
        else:
            # Default blended feed: fold in home + followed states alongside the request.
            if hs:
                states.append(hs)
            states.extend(folls)
        states = list({s for s in states if s})

        scope_parts = []
        params = []
        if include_all:
            scope_parts.append("scope = 'all_india'")
        if any(x.lower() == 'all' for x in states):
            scope_parts.append("scope = 'state'")            # states=all → every state (public pages)
        elif states:
            placeholders = ','.join(['?'] * len(states))
            scope_parts.append(f"(scope = 'state' AND state IN ({placeholders}))")
            params.extend(states)
            _rsql, _rp = _regional_news_sql(states)        # e.g. RIMS Imphal news for a Meghalaya doctor
            if _rsql:
                scope_parts.append(_rsql); params.extend(_rp)
        if not scope_parts:
            scope_parts.append("scope = 'all_india'")
        where = "is_published AND deleted_at IS NULL AND (" + " OR ".join(scope_parts) + ")"
        if body:
            where += " AND body_label = ?"; params.append(body)

        ensure_news_seo_cols(conn)
        total = conn.execute(f"SELECT COUNT(*) AS n FROM pg_news WHERE {where}", params).fetchone()['n']
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT id, scope, state, body_label, heading, body_text, source_url, pdf_name, "
            f"COALESCE(category,'') AS category, COALESCE(summary,'') AS summary, "
            f"COALESCE(key_dates,'') AS key_dates, COALESCE(schedule,'') AS schedule, "
            f"(pdf_data IS NOT NULL OR COALESCE(pdf_r2_key,'') <> '' OR authority_doc_id IS NOT NULL) AS has_pdf, published_at "
            f"FROM pg_news WHERE {where} ORDER BY published_at DESC, id DESC "
            f"LIMIT {page_size} OFFSET {offset}", params).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d['pdf_url'] = (f"/api/pg/news/{d['id']}/pdf" if d.get('has_pdf') else None)
            # key_dates: {field: {date, time}} — only the dates the notice states (2026-10-08)
            try:
                import json as _json
                d['key_dates'] = _json.loads(d.get('key_dates') or '{}') or {}
            except Exception:
                d['key_dates'] = {}
            from pg_admin.data.calendar import short_time
            for _v in d['key_dates'].values():
                if isinstance(_v, dict) and _v.get('time'):
                    _v['time'], _full = short_time(_v['time'])
                    if _full:
                        _v['note'] = _full
            d['schedule'] = parse_schedule(d.get('schedule'))
            items.append(d)
        return jsonify({'ok': True, 'items': items, 'count': len(items),
                        'total': total, 'page': page, 'page_size': page_size,
                        'total_pages': (total + page_size - 1) // page_size if page_size else 1}), 200
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_news: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass


def parse_schedule(raw):
    """pg_news.schedule JSON → {"columns": [...], "rows": [[...]]} or None."""
    import json as _json
    try:
        t = _json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None
    if not isinstance(t, dict) or not t.get('rows'):
        return None
    return {'title': str(t.get('title') or ''), 'columns': [str(c) for c in (t.get('columns') or [])],
            'rows': [[str(c) for c in r] for r in t['rows'] if isinstance(r, list)]}


DEADLINE_LABELS = {
    'registration_start': 'Registration starts', 'registration_end': 'Registration closes',
    'verification_start': 'Document verification / slot booking starts',
    'verification_end': 'Document verification closes',
    'choice_filling_start': 'Choice filling starts', 'choice_filling_end': 'Choice filling closes',
    'payment_last_date': 'Fee payment last date', 'reporting_last_date': 'Reporting / joining last date',
    'result_date': 'Result / seat allotment',
}


def api_pg_news_deadlines():
    """GET /api/pg/news/deadlines — upcoming key dates across published news, flattened +
    sorted, for an "Upcoming deadlines" strip (site, /news, dashboard). (2026-10-09)
    Params: states (comma list), all ('0' hides All-India), days (default 45, max 180).
    A doctor's Bearer token adds their home + followed states, like /api/pg/news.
    Returns {deadlines:[{date, field, label, news_id, heading, body_label, scope, state}]}."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    import json as _json
    from datetime import date as _date, timedelta as _td
    states = [x.strip() for x in _s(request.args.get('states')).split(',') if x.strip()]
    include_all = _s(request.args.get('all')) != '0'
    try:
        days = min(180, max(1, int(request.args.get('days') or 45)))
    except (TypeError, ValueError):
        days = 45
    conn = get_db()
    try:
        ensure_news_seo_cols(conn)
        user = _user(conn)
        if user:
            hs = _home_state(conn, user['id'])
            if hs:
                states.append(hs)
            states.extend(_follows(conn, user['id']))
        states = list({x for x in states if x})
        parts, params = [], []
        if include_all:
            parts.append("scope = 'all_india'")
        if any(x.lower() == 'all' for x in states):
            parts.append("scope = 'state'")
        elif states:
            parts.append("(scope = 'state' AND state IN (" + ','.join(['?'] * len(states)) + "))")
            params.extend(states)
            _rsql, _rp = _regional_news_sql(states)
            if _rsql:
                parts.append(_rsql); params.extend(_rp)
        if not parts:
            parts.append("scope = 'all_india'")
        rows = conn.execute(
            "SELECT id, heading, body_label, scope, state, key_dates FROM pg_news "
            "WHERE is_published AND deleted_at IS NULL AND COALESCE(key_dates,'') <> '' AND (" + " OR ".join(parts) + ")",
            params).fetchall()
        today, until = _date.today(), _date.today() + _td(days=days)
        _base = {'registration_start': 'registration', 'registration_end': 'registration',
                 'verification_start': 'verification', 'verification_end': 'verification',
                 'choice_filling_start': 'choice_filling', 'choice_filling_end': 'choice_filling',
                 'payment_last_date': 'payment', 'reporting_last_date': 'reporting', 'result_date': 'result'}
        out, seen = [], set()
        headings = {r['id']: r['heading'] for r in rows}
        # 1) Counselling Calendar first — it carries the ROUND (and time) for every step, across
        #    all rounds of a notice. (founder + website session 2026-10-09)
        try:
            from pg_admin.data import calendar as CAL
            from pg_admin.authorities import get_authority
            CAL.ensure_calendar_table(conn)
            codes = _codes_for_states(states if states else [], include_all)
            for r in CAL.events_for(conn, codes, upcoming_only=True):
                a = get_authority(r['authority_code']) or {}
                st = '' if r['authority_code'] == 'mcc' else a.get('state', '')
                pairs = ([('start', r['start_date']), ('end', r['end_date'])] if r.get('end_date')
                         else [('on', r['start_date'])])
                lbl = r['label'] or CAL.EVENT_LABELS.get(r['event'], '')
                for kind, d in pairs:
                    if not d or not (today <= d <= until):
                        continue
                    seen.add(((st or 'ALL').lower(), d.isoformat(), r['event']))
                    if r['event'] == 'registration' and kind != 'start':
                        # the news "fee payment last date" is the same deadline as registration closing
                        seen.add(((st or 'ALL').lower(), d.isoformat(), 'payment'))
                    suffix = {'start': ' opens', 'end': ' closes', 'on': ''}[kind]
                    _t, _full = CAL.short_time(r.get('time_text')) if kind != 'start' else (None, None)
                    out.append({'date': d.isoformat(), 'field': f"{r['event']}_{kind}",
                                'label': f"{lbl}{suffix}", 'round': r['round'] or None,
                                'time': _t, 'note': _full,
                                'news_id': r.get('news_id'), 'heading': headings.get(r.get('news_id'), ''),
                                'body_label': 'All India MCC' if r['authority_code'] == 'mcc' else a.get('name', ''),
                                'scope': 'all_india' if r['authority_code'] == 'mcc' else 'state',
                                'state': st, 'source': 'calendar'})
        except Exception as _e:
            logging.warning("deadlines calendar: %s", _e)
            try: conn.rollback()
            except Exception: pass
        from pg_admin.data.calendar import short_time as _short
        # 2) News key dates — skipped when the calendar already has that step on that date.
        for r in rows:
            try:
                kd = _json.loads(r['key_dates'] or '{}') or {}
            except Exception:
                continue
            for field, v in kd.items():
                try:
                    d = _date.fromisoformat(str((v or {}).get('date') or '')[:10])
                except ValueError:
                    continue
                if not (today <= d <= until):
                    continue
                st = r['state'] or ''
                key = ((st if r['scope'] == 'state' else 'ALL').lower(), d.isoformat(), _base.get(field, field))
                if key in seen:
                    continue
                seen.add(key)
                out.append({'date': d.isoformat(), 'field': field,
                            'label': DEADLINE_LABELS.get(field, field.replace('_', ' ').title()),
                            'round': (v or {}).get('round') or None,
                            'time': _short((v or {}).get('time'))[0], 'note': _short((v or {}).get('time'))[1],
                            'news_id': r['id'], 'heading': r['heading'], 'body_label': r['body_label'],
                            'scope': r['scope'], 'state': st, 'source': 'news'})
        out.sort(key=lambda x: (x['date'], x.get('news_id') or 0))
        return jsonify({'ok': True, 'days': days, 'count': len(out), 'deadlines': out})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_news_deadlines: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def _viewer_states(conn, states_param):
    """(include_all_india, state list or ['all']) from ?states= + the doctor's token."""
    states = [x.strip() for x in _s(states_param).split(',') if x.strip()]
    user = _user(conn)
    if user:
        hs = _home_state(conn, user['id'])
        if hs:
            states.append(hs)
        states.extend(_follows(conn, user['id']))
    return list({x for x in states if x})


def _regional_news_sql(states):
    """News of a REGIONAL authority (covers several states, e.g. RIMS Imphal posted under 'Manipur')
    also reaches doctors of every state it covers (Meghalaya/Nagaland/Sikkim…). Matched through the
    inbox notice it came from. → (sql or '', params). (2026-10-13)"""
    from pg_admin.authorities import all_authorities
    sl = {x.strip().lower() for x in states if x and x.lower() != 'all'}
    if not sl:
        return '', []
    codes = [a['code'] for a in all_authorities()
             if len(a.get('covers_states') or []) > 1
             and ({x.lower() for x in a['covers_states']} & sl) and a['state'].lower() not in sl]
    if not codes:
        return '', []
    return ("(inbox_id IN (SELECT id FROM pg_news_inbox WHERE authority_code IN (" +
            ','.join(['?'] * len(codes)) + ")))"), codes


def _codes_for_states(states, include_all=True):
    from pg_admin.authorities import all_authorities
    auths = all_authorities()
    if any(x.lower() == 'all' for x in states):
        return [a['code'] for a in auths if a['kind'] == 'state' or include_all]
    sl = {x.strip().lower() for x in states}
    # an authority serves every state in its covers_states (e.g. RIMS Imphal → 7 NE states)
    codes = [a['code'] for a in auths if a['kind'] == 'state' and
             ({x.strip().lower() for x in (a.get('covers_states') or [a['state']])} & sl)]
    if include_all:
        codes.insert(0, 'mcc')
    return codes


def api_pg_calendar():
    """GET /api/pg/calendar — the Counselling Calendar, per authority and round (2026-10-09).
    Params: authority=<code> (one) OR states=<comma list | all> (+ MCC unless all=0);
    upcoming=1 hides finished steps. A doctor's Bearer token adds home + followed states.
    → {authorities:[{code,name,state,rounds:[{round, events:[{event,event_label,label,start_date,
       end_date,time,note,news_id}]}]}]}"""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    from pg_admin.data import calendar as CAL
    from pg_admin.authorities import get_authority
    conn = get_db()
    try:
        CAL.ensure_calendar_table(conn)
        code = _s(request.args.get('authority')).lower()
        if code:
            codes = [code] if get_authority(code) else []
        else:
            codes = _codes_for_states(_viewer_states(conn, request.args.get('states')),
                                      _s(request.args.get('all')) != '0')
        rows = CAL.events_for(conn, codes, upcoming_only=_s(request.args.get('upcoming')) == '1') if codes else []
        order = {r: i for i, r in enumerate(CAL.ROUNDS)}
        by_auth = {}
        for r in rows:
            by_auth.setdefault(r['authority_code'], {}).setdefault(r['round'] or '', []).append(CAL.as_json_row(r))
        heads = {r['id']: r['heading'] for r in conn.execute(
            "SELECT id, heading FROM pg_news WHERE deleted_at IS NULL").fetchall()} if rows else {}
        for evs in by_auth.values():
            for lst in evs.values():
                for e in lst:
                    e['heading'] = heads.get(e.get('news_id'), '')
        out = []
        for c in _authority_order(codes):
            if c not in by_auth:
                continue
            a = get_authority(c) or {'code': c, 'name': c, 'state': ''}
            out.append({'code': c, 'name': a['name'], 'state': a['state'],
                        'rounds': [{'round': rd or 'General', 'events': evs}
                                   for rd, evs in sorted(by_auth[c].items(), key=lambda kv: order.get(kv[0], 50))]})
        return jsonify({'ok': True, 'as_of': _ist_today().isoformat(), 'count': len(rows), 'authorities': out})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_calendar: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


STEP_ORDER = ['round_window', 'registration', 'verification', 'choice_filling', 'choice_locking', 'payment',
              'seat_processing', 'result', 'reporting']
ROUND_STEPS = {'round_window', 'choice_filling', 'choice_locking', 'seat_processing', 'result', 'reporting'}
FINAL_ROUNDS = {'Mop-up', 'Stray', 'Special Stray'}
BAR_STEPS = {'round_window': 'Counselling round', 'registration': 'Registration', 'verification': 'Document verification',
             'choice_filling': 'Choice filling', 'result': 'Result', 'reporting': 'Reporting / joining'}


# The usual flow of every counselling (founder 2026-10-31: show every authority's rounds like MCC, with
# 'dates awaited' until the dates come). Opt-in with template=1 so an older site never sees dateless steps.
TEMPLATE_ROUNDS = {'mcc': ['Round 1', 'Round 2', 'Round 3', 'Stray']}
DEFAULT_TEMPLATE_ROUNDS = ['Round 1', 'Round 2', 'Mop-up', 'Stray']
TEMPLATE_STEPS = ['registration', 'choice_filling', 'result', 'reporting']


def _template_steps(code, rnd):
    # MCC registers again every round; states register once (Round 1) and run later rounds on that registration
    return [s for s in TEMPLATE_STEPS if s != 'registration' or rnd == 'Round 1' or code == 'mcc']


def add_template(code, st):
    """Fill a counselling_status result with the steps / rounds that have no dates yet: status 'awaited',
    start / end None, expected True (a round with no dates at all is status 'awaited'). Dated steps untouched."""
    from pg_admin.data import calendar as CAL
    rorder = {r: i for i, r in enumerate(CAL.ROUNDS)}
    st = dict(st or {'status': 'not_started', 'stage': None, 'next_deadline': None, 'progress': 0, 'rounds': [],
                     'headline': 'Round 1 dates awaited'})
    have = {r['round']: r for r in st.get('rounds') or []}
    general = have.get('General')
    # a general (round-less) registration counts as Round 1's registration
    gen_steps = {i['step'] for i in (general or {}).get('steps', [])}
    rounds = [r for r in st.get('rounds') or [] if r['round'] not in (TEMPLATE_ROUNDS.get(code) or DEFAULT_TEMPLATE_ROUNDS)]
    for rnd in TEMPLATE_ROUNDS.get(code) or DEFAULT_TEMPLATE_ROUNDS:
        cur = have.get(rnd)
        steps = list(cur['steps']) if cur else []
        dated = {i['step'] for i in steps} | (gen_steps if rnd == 'Round 1' else set())
        for stp in _template_steps(code, rnd):
            if stp not in dated:
                steps.append({'round': rnd, 'step': stp, 'label': CAL.EVENT_LABELS.get(stp, stp),
                              'bar_label': BAR_STEPS.get(stp), 'start': None, 'end': None, 'time': None, 'note': None,
                              'status': 'awaited', 'expected': True, 'news_id': None, 'revised': None})
        steps.sort(key=lambda i: STEP_ORDER.index(i['step']) if i['step'] in STEP_ORDER else 99)
        if cur:
            rounds.append({**cur, 'steps': steps})
        else:
            rounds.append({'round': rnd, 'status': 'awaited', 'start': None, 'end': None, 'live_step': None,
                           'steps': steps, 'expected': True})
    rounds.sort(key=lambda r: -1 if r['round'] == 'General' else rorder.get(r['round'], 50))
    return {**st, 'rounds': rounds, 'template': True}


def _fmt_d(d):
    return d.strftime('%d %b').lstrip('0') if d else ''


def _ist_today():
    from datetime import datetime, timedelta
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()


def counselling_status(conn, code, today=None, headings=None):
    """Where an authority's counselling is right now (2026-10-09; shape agreed with the
    website session): status not_started | in_progress | completed, rounds → steps
    (done / live / upcoming), current stage, next deadline, progress, headline (≤90 chars)."""
    from pg_admin.data import calendar as CAL
    today = today or _ist_today()
    headings = headings or {}
    rows = CAL.events_for(conn, [code])
    rorder = {r: i for i, r in enumerate(CAL.ROUNDS)}
    steps = {}
    for r in rows:
        if r['event'] not in STEP_ORDER:
            continue
        k = (r['round'] or '', r['event'])
        s0, e0 = r['start_date'], r['end_date'] or r['start_date']
        cur = steps.get(k)
        rev = CAL.as_json_row(r)['revised']   # date moved by a newer notice (website "was …" tag)
        if cur:
            steps[k] = {**cur, 'start': min(cur['start'], s0), 'end': max(cur['end'], e0),
                        'time': (r.get('time_text') or cur['time']) if e0 >= cur['end'] else cur['time'],
                        'revised': max([x for x in (cur['revised'], rev) if x], key=lambda x: x['at'], default=None)}
        else:
            steps[k] = {'start': s0, 'end': e0, 'time': r.get('time_text') or None, 'news_id': r.get('news_id'),
                        'revised': rev}
    if not steps:
        return None
    rounds, flat = {}, []
    for (rnd, ev), v in steps.items():
        st = 'done' if v['end'] < today else ('live' if v['start'] <= today <= v['end'] else 'upcoming')
        item = {'round': rnd or None, 'step': ev, 'label': CAL.EVENT_LABELS.get(ev, ev),
                'bar_label': BAR_STEPS.get(ev), 'start': v['start'].isoformat(), 'end': v['end'].isoformat(),
                'time': CAL.short_time(v['time'])[0], 'note': CAL.short_time(v['time'])[1],
                'status': st, 'news_id': v['news_id'], 'revised': v['revised']}
        rounds.setdefault(rnd, []).append(item)
        flat.append(item)
    out_rounds = []
    for rnd in sorted(rounds, key=lambda x: rorder.get(x, 50)):
        its = sorted(rounds[rnd], key=lambda i: (STEP_ORDER.index(i['step']), i['start']))
        if all(i['status'] == 'done' for i in its):
            rst = 'done'
        elif all(i['status'] == 'upcoming' for i in its):
            rst = 'upcoming'
        else:
            rst = 'live'
        live_bar = next((i['bar_label'] for i in its if i['status'] == 'live' and i['bar_label']), None)
        out_rounds.append({'round': rnd or 'General', 'status': rst, 'start': min(i['start'] for i in its),
                           'end': max(i['end'] for i in its), 'live_step': live_bar, 'steps': its})
    flat.sort(key=lambda i: (i['start'], STEP_ORDER.index(i['step'])))
    live = [i for i in flat if i['status'] == 'live']
    nxt = next((i for i in flat if i['status'] == 'upcoming'), None)
    current = live[0] if live else None
    dl = min((i for i in flat if i['status'] in ('live', 'upcoming')), key=lambda i: i['end'], default=None)
    next_deadline = ({'date': dl['end'], 'label': dl['label'], 'round': dl['round'], 'time': dl['time'], 'note': dl['note'],
                      'news_id': dl['news_id'], 'heading': headings.get(dl['news_id'], '')} if dl else None)
    from datetime import date as _date
    if current:
        headline = (f"{current['round'] + ': ' if current['round'] else ''}{current['label']} open"
                    f" — closes {_fmt_d(_date.fromisoformat(current['end']))}")
    elif nxt:
        headline = (f"Next: {nxt['round'] + ' ' if nxt['round'] else ''}{nxt['label'].lower()}"
                    f" from {_fmt_d(_date.fromisoformat(nxt['start']))}")
    done = sum(1 for i in flat if i['status'] == 'done')
    # 'completed' only once a FINAL round (Mop-up / Stray) is published and every step is done — dates
    # all passed with just registration / verification, or only Round 1-2 out, is NOT the end of
    # counselling (2026-10-22: AP/Goa/KEA/Kerala/TN showed "Counselling completed" before Round 1)
    alloc = [i for i in flat if i['step'] in ROUND_STEPS and i['round']]
    final = any(i['round'] in FINAL_ROUNDS for i in alloc)
    status = 'completed' if done == len(flat) and final else 'in_progress'
    if not (current or nxt):
        if status == 'completed':
            headline = 'All scheduled rounds completed'
        elif not alloc:
            headline = ('Registration closed — Round 1 dates awaited' if any(i['step'] == 'registration' for i in flat)
                        else 'Round 1 dates awaited')
        else:
            last = max((i['round'] for i in alloc), key=lambda r: rorder.get(r, 50))
            headline = f'{last} completed — next round dates awaited'
    return {'status': status, 'stage': current or nxt, 'headline': headline[:90], 'next_deadline': next_deadline,
            'progress': round(100 * done / len(flat)) if flat else 0, 'rounds': out_rounds}


def _authority_order(codes):
    from pg_admin.authorities import get_authority
    return sorted(codes, key=lambda c: (c != 'mcc', ((get_authority(c) or {}).get('state') or '').lower()))


def api_pg_counselling_status():
    """GET /api/pg/counselling-status[?authority=<code> | states=<list|all>][&template=1] — per-authority
    counselling STAGE for the website's stage bar (2026-10-09). Doctor token → MCC + their states.
    template=1 also returns the usual rounds / steps that have no dates yet (status 'awaited', start/end null,
    expected true) — MCC Round 1-3 + Stray, states Round 1, 2, Mop-up, Stray (founder 2026-10-31).
    Authorities with a bulletin / news but no dates yet come back as status 'not_started'."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    from pg_admin.data import calendar as CAL
    from pg_admin.authorities import get_authority
    conn = get_db()
    try:
        CAL.ensure_calendar_table(conn)
        code = _s(request.args.get('authority')).lower()
        codes = ([code] if get_authority(code) else []) if code else _codes_for_states(
            _viewer_states(conn, request.args.get('states')), _s(request.args.get('all')) != '0')
        headings = {r['id']: r['heading'] for r in conn.execute(
            "SELECT id, heading FROM pg_news WHERE deleted_at IS NULL").fetchall()}
        brochure = set()
        try:
            brochure = {r['authority_code'] for r in conn.execute(
                "SELECT DISTINCT authority_code FROM pg_authority_docs WHERE COALESCE(is_main, FALSE) "
                "AND COALESCE(is_published, TRUE)").fetchall()}
        except Exception:
            conn.rollback()
        news_states = set()
        for r in conn.execute("SELECT DISTINCT scope, LOWER(TRIM(COALESCE(state,''))) AS st FROM pg_news "
                              "WHERE is_published AND deleted_at IS NULL").fetchall():
            news_states.add('mcc' if r['scope'] == 'all_india' else r['st'])
        out = []
        tmpl = _s(request.args.get('template')) == '1'     # also the steps / rounds with no dates yet
        for c in _authority_order(codes):
            a = get_authority(c)
            st = counselling_status(conn, c, headings=headings)
            has_news = ('mcc' in news_states) if c == 'mcc' else ((a['state'] or '').lower() in news_states)
            if not st:
                if not (c in brochure or has_news):
                    continue
                st = {'status': 'not_started', 'stage': None, 'next_deadline': None, 'progress': 0, 'rounds': [],
                      'headline': ('Information bulletin released — schedule awaited' if c in brochure
                                   else 'Counselling updates out — schedule awaited')}
            if tmpl:
                st = add_template(c, st)
            out.append({'code': c, 'name': a['name'], 'state': a['state'], 'has_brochure': c in brochure, **st})
        return jsonify({'ok': True, 'as_of': _ist_today().isoformat(), 'authorities': out})
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_counselling_status: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        conn.close()


def api_pg_news_states():
    """GET /api/pg/news/states — states that have published news (for the picker)."""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        return jsonify({'ok': True, 'states': _states_with_news(conn)}), 200
    finally:
        try: conn.close()
        except Exception: pass


def api_pg_news_follows():
    """GET/POST/DELETE /api/pg/news/follows — a doctor's saved state subscriptions.
    GET  → {home_state, follows[], can_follow, available[]}
    POST {state} → add (paid only; state must have news)
    DELETE {state} → remove"""
    if not _authorized():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    conn = get_db()
    try:
        user = _user(conn)
        if not user:
            return jsonify({'ok': False, 'error': 'no_token'}), 401
        uid = user['id']
        # the Plan Features matrix, or full access for Internal / team / desk accounts (founder 2026-10-23)
        from pg_admin.data import entitlements as _ent
        can_follow = _plan_has(conn, uid, 'dash_news_follow') or _ent.full_news_access(conn, uid)

        if request.method == 'GET':
            avail = _states_with_news(conn)
            home = _home_state(conn, uid)
            follows = _follows(conn, uid)
            # picker = states with news, minus home + already followed
            skip = {(home or '').strip().lower()} | {f.strip().lower() for f in follows}
            available = [s for s in avail if s.strip().lower() not in skip]
            return jsonify({'ok': True, 'home_state': home, 'follows': follows,
                            'can_follow': can_follow, 'available': available,
                            'tier': ('paid' if can_follow else 'free')}), 200

        # Accept the state from JSON body, form, OR query string — DELETE requests
        # commonly carry it in the URL rather than a body.
        state = _s((request.get_json(silent=True) or {}).get('state')
                   or request.form.get('state') or request.args.get('state'))
        if not state:
            return jsonify({'ok': False, 'error': 'state_required'}), 400

        if request.method == 'DELETE':
            conn.execute("DELETE FROM pg_news_follows WHERE user_id=? AND state=?", (uid, state))
            conn.commit()
            return jsonify({'ok': True, 'follows': _follows(conn, uid)}), 200

        # POST (add)
        if not can_follow:
            return jsonify({'ok': False, 'error': 'upgrade_required',
                            'message': 'Following other states’ news is a paid feature. '
                                       'You already get All-India and your home-state news.'}), 403
        if state not in _states_with_news(conn):
            return jsonify({'ok': False, 'error': 'no_news_for_state',
                            'message': 'No news is available for that state yet.'}), 400
        home = _home_state(conn, uid)
        if home and state.strip().lower() == home.strip().lower():
            return jsonify({'ok': True, 'follows': _follows(conn, uid),
                            'message': 'That is already your home state.'}), 200
        try:
            conn.execute("INSERT INTO pg_news_follows (user_id, state) VALUES (?, ?) "
                         "ON CONFLICT DO NOTHING", (uid, state))
            conn.commit()
        except Exception:
            conn.rollback()
        return jsonify({'ok': True, 'follows': _follows(conn, uid)}), 200
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logging.error("api_pg_news_follows: %s", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
    finally:
        try: conn.close()
        except Exception: pass


def api_pg_news_pdf(news_id):
    """GET /api/pg/news/<id>/pdf — stream a news attachment. Public (no key)."""
    from pg_admin.routes.api import file_key_block
    blk = file_key_block()
    if blk:
        return blk
    conn = get_db()
    try:
        from pg_admin.data.big_files import ensure_cols as _bf_cols
        _bf_cols(conn)
        ensure_news_seo_cols(conn)
        row = conn.execute(
            "SELECT pdf_name, pdf_data, pdf_content_type, pdf_r2_key, authority_doc_id FROM pg_news "
            "WHERE id=? AND is_published", (news_id,)).fetchone()
    except Exception as e:
        logging.error("api_pg_news_pdf: %s", e)
        row = None
    finally:
        try: conn.close()
        except Exception: pass
    if row and not row['pdf_data'] and not row.get('pdf_r2_key') and row.get('authority_doc_id'):
        from pg_admin.data.big_files import serve_authority_doc      # news links to the one stored document
        rr = serve_authority_doc(row['authority_doc_id'])
        if rr:
            return rr
    if row and not row['pdf_data'] and row.get('pdf_r2_key'):       # big file kept in R2 (2026-10-17)
        from pg_admin.data.big_files import r2_redirect
        rr = r2_redirect(row['pdf_r2_key'])
        if rr:
            return rr
    if not row or not row['pdf_data']:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    return Response(bytes(row['pdf_data']), mimetype=row['pdf_content_type'] or 'application/pdf',
                    headers={'Content-Disposition': f'inline; filename="{row["pdf_name"] or "news.pdf"}"'})
