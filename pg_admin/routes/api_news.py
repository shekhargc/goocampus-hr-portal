"""Public /api/pg/news* endpoints — the goocampus.in dashboard news feed + a
doctor's saved state subscriptions (founder 2026-09-30).

Feed model: every doctor sees All-India news + their home-state news by default.
Paid doctors (dash_news_follow) can FOLLOW extra states — saved to their profile,
so the admin sees the subscription on the Registered Doctors page and it persists.
The "add a state" picker only offers states that actually have published news.

X-PG-Key guards the reads; the follow endpoints ALSO need the doctor's Bearer token.
The PDF stream is public.
"""
import re
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
      id       one published post by id (any scope), returned inside items[]
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
        # ?id=<n> → that one published post (any scope — the public site shows every state's news), same item
        # shape inside items[]; post pages no longer depend on the list window (website request 2026-11-20)
        _one = _s(request.args.get('id'))
        if _one.isdigit():
            where, params = "is_published AND deleted_at IS NULL AND id = ?", [int(_one)]

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


_PLURAL_ENDS = ('options', 'choices', 'results', 'lists', 'documents', 'seats', 'orders', 'letters', 'dates')


def _hold_label(lbl, suffix):
    """Strip label + opens/closes, with "open"/"close" after a plural noun ("Phase-II web options open (CQ)",
    website 2026-11-22)."""
    out = _hold_label_raw(lbl, suffix)
    v = suffix.strip().lower()
    if v in ('opens', 'closes'):
        i = out.find(' ' + v)
        head = out[:i].rstrip() if i > 0 else ''
        if head and head.split()[-1].lower().strip('.,') in _PLURAL_ENDS:
            out = out[:i] + ' ' + v[:-1] + out[i + 1 + len(v):]
    return out


def _hold_label_raw(lbl, suffix):
    """"Choice filling — ON HOLD (Madras High Court order)" + " closes" → "Choice filling closes (on hold — Madras
    High Court order)": the opens/closes word goes before the hold text, not after it. (website 2026-11-21)"""
    import re
    m = re.search(r'\s*[—–-]\s*on hold\b\s*(?:\((.*)\))?\s*$', lbl or '', re.I)
    if not m:
        # a trailing bracketed note: "Choice filling & locking (opens 7 PM on 21 Nov)" → the verb goes before it
        # ("… opens (7 PM on 21 Nov)"); a note that names the OTHER end ("opens …" on the closes card) is dropped.
        b = re.search(r'\s*\(([^()]*)\)\s*$', lbl or '')
        if b and suffix.strip():
            base, note, verb = lbl[:b.start()].strip(), b.group(1).strip(), suffix.strip().lower()
            first = note.split(' ', 1)[0].lower()
            if first in ('opens', 'closes', 'open', 'close', 'from', 'till', 'until', 'upto', 'up'):
                if not first.startswith(verb[:4]) and not (verb == 'opens' and first == 'from') \
                        and not (verb == 'closes' and first in ('till', 'until', 'upto', 'up')):
                    return f"{base}{suffix}"
                if first.startswith(verb[:4]):
                    note = note.split(' ', 1)[1] if ' ' in note else ''
            return f"{base}{suffix}" + (f" ({note})" if note else '')
        return f"{lbl}{suffix}"
    why = (m.group(1) or '').strip()
    return f"{lbl[:m.start()].strip()}{suffix} (on hold{' — ' + why if why else ''})"


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
        out, seen, seen_steps = [], set(), set()
        headings = {r['id']: r['heading'] for r in rows}
        # 1) Counselling Calendar first — it carries the ROUND (and time) for every step, across
        #    all rounds of a notice. (founder + website session 2026-10-09)
        try:
            from pg_admin.data import calendar as CAL
            from pg_admin.authorities import get_authority
            CAL.ensure_calendar_table(conn)
            codes = _codes_for_states(states if states else [], include_all)
            for r in CAL.events_for(conn, codes, upcoming_only=True, public=True):
                a = get_authority(r['authority_code']) or {}
                st = '' if r['authority_code'] == 'mcc' else a.get('state', '')
                pairs = ([('start', r['start_date']), ('end', r['end_date'])] if r.get('end_date')
                         else [('on', r['start_date'])])
                lbl = r['label'] or CAL.EVENT_LABELS.get(r['event'], '')
                for kind, d in pairs:
                    if not d or not (today <= d <= until):
                        continue
                    seen.add(((st or 'ALL').lower(), d.isoformat(), r['event']))
                    if r['round']:   # the calendar owns this round's step → an older news date for it is stale
                        seen_steps.add(((st or 'ALL').lower(), r['round'], r['event']))
                    if r['event'] == 'registration' and kind != 'start':
                        # the news "fee payment last date" is the same deadline as registration closing
                        seen.add(((st or 'ALL').lower(), d.isoformat(), 'payment'))
                    suffix = {'start': ' opens', 'end': ' closes', 'on': ''}[kind]
                    _t, _full = CAL.short_time(r.get('time_text')) if kind != 'start' else (None, None)
                    out.append({'date': d.isoformat(), 'field': f"{r['event']}_{kind}",
                                'label': _hold_label(lbl, suffix), 'round': r['round'] or None,
                                'time': _t, 'note': _full,
                                'news_id': r.get('news_id'), 'heading': headings.get(r.get('news_id'), ''),
                                'body_label': 'All India MCC' if r['authority_code'] == 'mcc' else a.get('name', ''),
                                'scope': 'all_india' if r['authority_code'] == 'mcc' else 'state',
                                'state': st, 'source': 'calendar'})
        except Exception as _e:
            logging.warning("deadlines calendar: %s", _e)
            try: conn.rollback()
            except Exception: pass
        from pg_admin.data.calendar import short_time as _short, is_dnb_only as _dnb_only, show_dnb as _show_dnb
        _hide_dnb = not _show_dnb(conn)
        # 2) News key dates — skipped when the calendar already has that step on that date.
        for r in rows:
            if _hide_dnb and _dnb_only(r['heading']):
                continue
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
                # the calendar already dates this round's step (e.g. MCC Round 2 result moved 14 → 17 Nov) — the
                # news' own older date must not show as a second deadline (2026-11-14)
                _rnd = (v or {}).get('round')
                if _rnd and (key[0], _rnd, key[2]) in seen_steps:
                    continue
                seen.add(key)
                out.append({'date': d.isoformat(), 'field': field,
                            'label': DEADLINE_LABELS.get(field, field.replace('_', ' ').title()),
                            'round': (v or {}).get('round') or None,
                            'time': _short((v or {}).get('time'))[0], 'note': _short((v or {}).get('time'))[1],
                            'news_id': r['id'], 'heading': r['heading'], 'body_label': r['body_label'],
                            'scope': r['scope'], 'state': st, 'source': 'news'})
        out.sort(key=lambda x: (x['date'], x.get('news_id') or 0))
        try:   # website shows "Remind me — free login" only while the reminder emails are switched on (2026-11-21)
            from pg_admin.deadline_reminders import is_enabled as _rem_on
            reminders_on = _rem_on(conn)
        except Exception:
            reminders_on = False
        return jsonify({'ok': True, 'days': days, 'count': len(out), 'deadlines': out, 'reminders_on': reminders_on})
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
        rows = CAL.events_for(conn, codes, upcoming_only=_s(request.args.get('upcoming')) == '1', public=True) if codes else []
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
# Where an authority's rules differ from the usual flow (from its own notices):
#   KEA (30-10-2026 schedule): "Candidates will not be allowed to enter OPTIONS again for second round" —
#   Round 1 options carry over, so Round 2 has no choice-filling step.
TEMPLATE_OVERRIDES = {'kea': {'Round 2': ['result', 'reporting']}}


def _template_steps(code, rnd):
    if rnd in TEMPLATE_OVERRIDES.get(code, {}):
        return TEMPLATE_OVERRIDES[code][rnd]
    # MCC registers again every round; states register once (Round 1) and run later rounds on that registration
    return [s for s in TEMPLATE_STEPS if s != 'registration' or rnd == 'Round 1' or code == 'mcc']


def _date_order(steps):
    """Dated steps by start date (step order breaks ties) — Chhattisgarh verifies documents AFTER the result. A step
    with no date yet keeps its usual place: right after the nearest earlier (in STEP_ORDER) step that has a date."""
    idx = lambda i: STEP_ORDER.index(i['step']) if i['step'] in STEP_ORDER else 99
    by_order = sorted(steps, key=idx)
    keyed, last = [], ''
    for i in by_order:
        if i.get('start'):
            last = i['start']
            keyed.append(((i['start'], idx(i)), i))
        else:
            keyed.append(((last, idx(i)), i))
    return [i for _, i in sorted(keyed, key=lambda x: x[0])]


def add_template(code, st):
    """Fill a counselling_status result with the steps / rounds that have no dates yet: status 'awaited',
    start / end None, expected True (a round with no dates at all is status 'awaited'). Dated steps untouched."""
    from pg_admin.data import calendar as CAL
    rorder = {r: i for i, r in enumerate(CAL.ROUNDS)}
    st = dict(st or {'status': 'not_started', 'stage': None, 'next_deadline': None, 'progress': 0, 'rounds': [],
                     'headline': 'Round 1 dates awaited'})
    have = {r['round']: r for r in st.get('rounds') or []}
    # round-less steps (a state's registration / verification before Round 1) are shown INSIDE Round 1, like MCC
    # (founder 2026-11-01: no separate "Before Round 1" tab)
    general = have.pop('General', None)
    if general:
        r1 = have.get('Round 1')
        moved = [dict(i, round='Round 1') for i in general['steps']]
        if r1:
            have['Round 1'] = dict(r1, steps=moved + list(r1['steps']),
                                   start=min(x for x in (r1.get('start'), general.get('start')) if x),
                                   status=('live' if 'live' in (r1['status'], general['status']) else
                                           'done' if r1['status'] == general['status'] == 'done' else
                                           'upcoming' if r1['status'] == general['status'] == 'upcoming' else 'live'))
        else:
            have['Round 1'] = dict(general, round='Round 1', steps=moved)
    rounds = [r for r in have.values() if r['round'] not in (TEMPLATE_ROUNDS.get(code) or DEFAULT_TEMPLATE_ROUNDS)]
    for rnd in TEMPLATE_ROUNDS.get(code) or DEFAULT_TEMPLATE_ROUNDS:
        cur = have.get(rnd)
        steps = list(cur['steps']) if cur else []
        dated = {i['step'] for i in steps}
        for stp in _template_steps(code, rnd):
            if stp not in dated:
                steps.append({'round': rnd, 'step': stp, 'label': CAL.EVENT_LABELS.get(stp, stp),
                              'bar_label': BAR_STEPS.get(stp), 'start': None, 'end': None, 'time': None, 'note': None,
                              'status': 'awaited', 'expected': True, 'news_id': None, 'revised': None})
        steps = _date_order(steps)
        if cur:
            # a round whose dated steps are all over but which still has awaited steps isn't finished — unless a
            # LATER round has already started (then those steps were never going to get dates; 2026-11-14:
            # Assam / Goa / Punjab showed "Round 1 · live" while Round 2 registration was open)
            later_started = any(o['status'] in ('live', 'done') for k2, o in have.items()
                                if rorder.get(k2, 50) > rorder.get(rnd, 50))
            done_but_waiting = (cur['status'] == 'done' and not later_started
                                and any(i['status'] == 'awaited' for i in steps))
            rounds.append({**cur, 'steps': steps, 'status': 'live' if done_but_waiting else cur['status']})
        else:
            rounds.append({'round': rnd, 'status': 'awaited', 'start': None, 'end': None, 'live_step': None,
                           'steps': steps, 'expected': True})
    rounds.sort(key=lambda r: rorder.get(r['round'], 50))
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
    rows = CAL.events_for(conn, [code], public=True)
    rorder = {r: i for i, r in enumerate(CAL.ROUNDS)}
    steps = {}
    # ON HOLD (2026-11-18, MCC Round 2 result stayed by the Madras High Court): a calendar step whose label says
    # "on hold" is flagged explicitly — on_hold + hold_reason on the step, the round and next_deadline, and the
    # headline says so — so the website keys off a flag, not words. Reason = text in brackets, else the note.
    holds = {}
    for r in rows:
        lab = r.get('label') or ''
        if 'on hold' in lab.lower():
            m = re.search(r'\(([^)]+)\)', lab)
            holds[(r['round'] or '', r['event'])] = (m.group(1) if m else (r.get('note') or '')[:80]).strip()
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
    # (moved below: `published` is needed to add a result step the calendar doesn't carry)
    # A round whose result is already PUBLISHED on the portal (results page) has its result step done from that
    # day — the calendar only dates it, so on result day it read "Result / seat allotment open — closes 20 Nov"
    # after MCC's final list was out (website session 2026-11-20). {round: 'final' | 'provisional'}
    import datetime as _dt
    published, pub_on = {}, {}
    try:
        from pg_admin.routes.results_api import YEAR as _RY
        for r in conn.execute("SELECT round, status, published_on, uploaded_at FROM pg_results_source "
                              "WHERE authority_code = ? AND academic_year = ? AND COALESCE(is_hidden,0) = 0",
                              (code, _RY)).fetchall():
            published[r['round']] = r['status'] or ''
            try:
                pub_on[r['round']] = _dt.date.fromisoformat((r['published_on'] or '')[:10])
            except ValueError:
                pub_on[r['round']] = r['uploaded_at'].date() if r['uploaded_at'] else today
    except Exception:
        try: conn.rollback()
        except Exception: pass
    # Every authority (founder 2026-11-24): a round whose result list is loaded shows its Result step as done
    # ("provisional / final result out") even when the calendar has no 'result' step for it — e.g. KEA Round 2:
    # the provisional list came late, the final date was withdrawn, and the tracker read "Result · dates awaited"
    # while the banner said the result was out. Dated from the list's own date.
    rounds_known = {k[0] for k in steps}
    for rnd, d in pub_on.items():
        if rnd in rounds_known and (rnd, 'result') not in steps:
            steps[(rnd, 'result')] = {'start': d, 'end': d, 'time': None, 'news_id': None, 'revised': None}
    # rounds whose result list is loaded (and not older than the result step) — their seat-processing / choice-locking
    # steps are over too (website 2026-11-24: TN read "Next: Seat allotment processing · Today" with R2 result out)
    result_out = {rnd for (rnd, ev), v in steps.items()
                  if ev == 'result' and rnd in published and pub_on.get(rnd, v['start']) >= v['start']}
    rounds, flat = {}, []
    for (rnd, ev), v in steps.items():
        st = 'done' if v['end'] < today else ('live' if v['start'] <= today <= v['end'] else 'upcoming')
        if ev in ('seat_processing', 'choice_locking') and rnd in result_out:
            st = 'done'
        # the loaded list counts only if it isn't OLDER than the step (website 2026-11-24: Rajasthan's 23 Nov
        # INDICATIVE list marked the 24 Nov "provisional allotment list" step done before RUHS published it)
        by_list = ev == 'result' and rnd in published and pub_on.get(rnd, v['start']) >= v['start']
        if by_list:
            st = 'done'
        item = {'round': rnd or None, 'step': ev, 'label': CAL.EVENT_LABELS.get(ev, ev),
                'bar_label': BAR_STEPS.get(ev), 'start': v['start'].isoformat(), 'end': v['end'].isoformat(),
                'time': CAL.short_time(v['time'])[0], 'note': CAL.short_time(v['time'])[1],
                'status': st, 'news_id': v['news_id'], 'revised': v['revised'],
                'on_hold': (rnd, ev) in holds, 'hold_reason': holds.get((rnd, ev)) or None,
                # result list loaded on the portal → 'provisional' | 'final' (website: "Provisional result out")
                'result_status': (published.get(rnd) or 'provisional') if by_list else None}
        rh = next((holds[k] for k in holds if k[0] == rnd and k[1] != ev), None)
        item['subject_to_hold'] = rh if (rh and not item['on_hold'] and st != 'done') else None
        rounds.setdefault(rnd, []).append(item)
        flat.append(item)
    out_rounds = []
    for rnd in sorted(rounds, key=lambda x: rorder.get(x, 50)):
        # date order first (Chhattisgarh / Karnataka verify documents AFTER the result), step order breaks ties
        its = sorted(rounds[rnd], key=lambda i: (i['start'], STEP_ORDER.index(i['step'])))
        if all(i['status'] == 'done' for i in its):
            rst = 'done'
        elif all(i['status'] == 'upcoming' for i in its):
            rst = 'upcoming'
        else:
            rst = 'live'
        live_bar = next((i['bar_label'] for i in its if i['status'] == 'live' and i['bar_label']), None)
        rhold = next((i for i in its if i['on_hold']), None)
        out_rounds.append({'round': rnd or 'General', 'status': rst, 'start': min(i['start'] for i in its),
                           'end': max(i['end'] for i in its), 'live_step': live_bar, 'steps': its,
                           'on_hold': bool(rhold), 'hold_step': rhold['step'] if rhold else None,
                           'hold_reason': rhold['hold_reason'] if rhold else None})
    flat.sort(key=lambda i: (i['start'], STEP_ORDER.index(i['step'])))
    live = [i for i in flat if i['status'] == 'live']
    nxt = next((i for i in flat if i['status'] == 'upcoming'), None)
    current = live[0] if live else None
    dl = min((i for i in flat if i['status'] in ('live', 'upcoming')), key=lambda i: i['end'], default=None)
    next_deadline = ({'date': dl['end'], 'label': dl['label'], 'round': dl['round'], 'time': dl['time'], 'note': dl['note'],
                      'news_id': dl['news_id'], 'heading': headings.get(dl['news_id'], ''),
                      'on_hold': dl['on_hold'], 'subject_to_hold': dl['subject_to_hold'],
                      'hold_reason': dl['hold_reason'] or dl['subject_to_hold']} if dl else None)
    # No main step live / upcoming but an extra calendar step ('other' — e.g. AP's management-quota Phase-2 web
    # options next to the CQ round) is still open → it is the next deadline (website 2026-11-25: AP card had no
    # "Next:" line while MQ options were open till 26 Nov 2 PM)
    extra = None
    if not dl:
        ex = [r for r in rows if r['event'] == 'other' and 'on hold' not in (r.get('label') or '').lower()
              and (r['end_date'] or r['start_date']) >= today]
        if ex:
            x = min(ex, key=lambda r: (r['end_date'] or r['start_date'], r['start_date']))
            extra = {'round': x['round'] or None, 'label': x.get('label') or 'Other', 'start': x['start_date'],
                     'end': x['end_date'] or x['start_date'], 'time': CAL.short_time(x.get('time_text'))[0],
                     'note': CAL.short_time(x.get('time_text'))[1], 'news_id': x.get('news_id')}
            next_deadline = {'date': extra['end'].isoformat(), 'label': extra['label'], 'round': extra['round'],
                             'time': extra['time'], 'note': extra['note'], 'news_id': extra['news_id'],
                             'heading': headings.get(extra['news_id'], ''), 'on_hold': False,
                             'subject_to_hold': None, 'hold_reason': None}
    from datetime import date as _date
    if current:
        headline = (f"{current['round'] + ': ' if current['round'] else ''}{current['label']} open"
                    f" — closes {_fmt_d(_date.fromisoformat(current['end']))}")
    elif nxt:
        headline = (f"Next: {nxt['round'] + ' ' if nxt['round'] else ''}{nxt['label'].lower()}"
                    f" from {_fmt_d(_date.fromisoformat(nxt['start']))}")
    # Result just published and reporting is the round's next step → say so (website session 2026-11-20)
    if not current:
        rep = next((i for i in flat if i['step'] == 'reporting' and i['status'] in ('live', 'upcoming')
                    and i['round'] in published
                    and any(j['round'] == i['round'] and j['step'] == 'result' and j['status'] == 'done' for j in flat)), None)
        if rep:
            kind = 'final' if published.get(rep['round']) == 'final' else 'provisional'
            headline = (f"{rep['round']} {kind} result out — report by {_fmt_d(_date.fromisoformat(rep['end']))}"
                        + (f", {rep['time']}" if rep['time'] else '')
                        + (' (no extension)' if 'no extension' in (rep['note'] or '').lower() else ''))
    # A step on hold in a round that isn't finished leads the headline.
    hold = next((i for i in flat if i['on_hold'] and any(j['round'] == i['round'] and j['status'] != 'done'
                                                         for j in flat)), None)
    if hold:
        rest = next((j for j in flat if j['round'] == hold['round'] and j['status'] in ('live', 'upcoming')
                     and not j['on_hold']), None)
        headline = f"{hold['round'] + ' ' if hold['round'] else ''}{hold['label'].lower()} on hold" + (
            f" ({hold['hold_reason']})" if hold['hold_reason'] else '')
        if rest:
            more = f" · {rest['label'].lower()} from {_fmt_d(_date.fromisoformat(rest['start']))} subject to it"
            if len(headline + more) <= 90:
                headline += more
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
            # 'completed' only when that round's allotment has happened (result step done / list loaded); a round
            # whose choice filling closed but whose allotment hasn't come is "allotment awaited" (website 2026-11-25)
            allotted = last in published or any(i['round'] == last and i['step'] == 'result' and i['status'] == 'done'
                                                for i in flat)
            headline = (f'{last} completed — next round dates awaited' if allotted
                        else f'{last}: allotment dates awaited')
            if extra:
                more = (f" · {extra['label'][0].lower() + extra['label'][1:]} open till {_fmt_d(extra['end'])}"
                        + (f", {extra['time']}" if extra['time'] else ''))
                if not allotted:
                    headline = f'{last}: allotment awaited'
                headline = (headline + more) if len(headline + more) <= 90 else (
                    f"{last}: {extra['label']} open till {_fmt_d(extra['end'])}"
                    + (f", {extra['time']}" if extra['time'] else ''))
    return {'status': status, 'stage': current or nxt, 'headline': headline[:90], 'next_deadline': next_deadline,
            'progress': round(100 * done / len(flat)) if flat else 0, 'rounds': out_rounds,
            'on_hold': [{'round': i['round'], 'step': i['step'], 'reason': i['hold_reason']} for i in flat if i['on_hold']]}


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
