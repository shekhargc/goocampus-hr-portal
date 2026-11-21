"""Counselling Calendar — every dated step of NEET-PG counselling, per authority and round
(founder 2026-10-09). Filled automatically from AI-drafted schedule notices when the founder
posts them (posting = the human review); editable on /admin/pg/calendar. Feeds the site's
schedule section and the "upcoming deadlines" strip (/api/pg/news/deadlines merges it).

pg_counselling_events: one row per step — e.g. MCC · Round 1 · Registration · 12→21 Oct.
"""
import json
import logging
from datetime import date

EVENT_TYPES = [
    # a whole counselling round's window when the notice gives only that (e.g. the national schedule's
    # "State counselling Round-1: 21 Oct – 2 Nov") — founder 2026-10-14, Gujarat back-check
    ('round_window', 'Counselling round'),
    ('registration', 'Registration & fee payment'),
    ('verification', 'Document verification / slot booking'),
    ('choice_filling', 'Choice filling'),
    ('choice_locking', 'Choice locking'),
    ('payment', 'Fee / security deposit payment'),
    ('seat_processing', 'Seat allotment processing'),
    ('result', 'Result / seat allotment'),
    ('reporting', 'Reporting / joining'),
    ('other', 'Other'),
]
EVENT_LABELS = dict(EVENT_TYPES)
ROUNDS = ['Round 1', 'Round 2', 'Round 3', 'Round 4', 'Mop-up', 'Stray', 'Special Stray', '']


def norm_round(v):
    """'round 2' / 'R2' / 'Second round' / 'stray vacancy' → the shared vocabulary (or '')."""
    t = str(v or '').strip().lower().replace('-', ' ')
    if not t:
        return ''
    if 'special' in t and 'stray' in t:
        return 'Special Stray'
    if 'stray' in t:
        return 'Stray'
    if 'mop' in t:
        return 'Mop-up'
    for n, words in ((1, ('1', 'one', 'first', 'i')), (2, ('2', 'two', 'second', 'ii')),
                     (3, ('3', 'three', 'third', 'iii')), (4, ('4', 'four', 'fourth', 'iv'))):
        toks = t.replace('round', ' ').replace('r', ' ').split() if t.startswith('r') else t.replace('round', ' ').split()
        if any(w in toks for w in words):
            return f'Round {n}'
    return ''


_CAL_READY = {'done': False}


def ensure_calendar_table(conn=None):
    """Once per process (2026-11-17 outage fix): /api/pg/news/deadlines, /calendar and /counselling-status call this
    on every dashboard page — each ALTER/CREATE INDEX took an exclusive lock on pg_counselling_events and helped jam
    the shared DB. lock_timeout: never wait on a busy table."""
    if _CAL_READY['done']:
        return
    own = conn is None
    if own:
        from db import get_db
        conn = get_db()
    try:
        conn.execute("SET LOCAL lock_timeout = '3s'")
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_counselling_events (
            id SERIAL PRIMARY KEY,
            authority_code TEXT NOT NULL DEFAULT '',
            year TEXT DEFAULT '2026',
            round TEXT DEFAULT '',
            event TEXT DEFAULT 'other',
            label TEXT DEFAULT '',
            start_date DATE,
            end_date DATE,
            time_text TEXT DEFAULT '',
            note TEXT DEFAULT '',
            quote TEXT DEFAULT '',
            news_id INTEGER,
            inbox_id INTEGER,
            is_active BOOLEAN DEFAULT TRUE,
            created_by TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_cal_auth ON pg_counselling_events (authority_code, start_date)")
        # One entry per (authority, round, step) — updated only when a NEWER notice changes the
        # date; every change is logged (founder 2026-10-10).
        for col, typ in (('source_notice_date', 'DATE'), ('changed_at', 'TIMESTAMP'), ('prev_start', 'DATE'),
                         ('prev_end', 'DATE'), ('change_count', 'INTEGER DEFAULT 0'),
                         ('manual_edit', 'BOOLEAN DEFAULT FALSE')):
            conn.execute(f"ALTER TABLE pg_counselling_events ADD COLUMN IF NOT EXISTS {col} {typ}")
        # Each inbox draft's schedule is merged into the calendar ONCE (on arrival / re-draft), never again on
        # every Calendar page view — re-merging every draft undid manual fixes and revived removed rows
        # (2026-11-20: KEA's misprinted 19 Nov draft put 21/23 Dec back; a relabelled Punjab row came back).
        # First time the column appears, every draft already there is marked synced (they were merged long ago).
        had = conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'pg_news_inbox' "
                           "AND column_name = 'calendar_synced_at'").fetchone()
        if not had and conn.execute("SELECT to_regclass('pg_news_inbox') AS t").fetchone()['t']:
            conn.execute("ALTER TABLE pg_news_inbox ADD COLUMN IF NOT EXISTS calendar_synced_at TIMESTAMP")
            conn.execute("UPDATE pg_news_inbox SET calendar_synced_at = CURRENT_TIMESTAMP WHERE draft_json IS NOT NULL")
        conn.execute('''CREATE TABLE IF NOT EXISTS pg_counselling_event_log (
            id SERIAL PRIMARY KEY, event_id INTEGER NOT NULL,
            old_start DATE, old_end DATE, new_start DATE, new_end DATE,
            inbox_id INTEGER, notice_date DATE, changed_by TEXT DEFAULT '', note TEXT DEFAULT '',
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        _CAL_READY['done'] = True
    except Exception as e:
        _CAL_READY['done'] = True        # one attempt per process — never retry DDL on every request
        logging.warning("ensure_calendar_table: %s", e)
        try: conn.rollback()
        except Exception: pass
    finally:
        if own:
            conn.close()


def _d(v):
    try:
        return date.fromisoformat(str(v or '').strip()[:10])
    except ValueError:
        return None


def clean_events(raw):
    """Whitelist an AI `events` list → [{round, event, label, start, end, time, quote}]."""
    out = []
    for e in (raw or [])[:80]:
        if not isinstance(e, dict):
            continue
        s = _d(e.get('start') or e.get('date'))
        if not s:
            continue
        en = _d(e.get('end'))
        ev = e.get('event') if e.get('event') in EVENT_LABELS else 'other'
        rnd = norm_round(e.get('round'))
        if not rnd:      # safety net: the date's own quote/label names the round but the AI left it blank
            import re as _re
            m = _re.search(r'\b(?:round|phase)[\s-]*(?:\d|i{1,3}v?|iv|one|two|three|four|first|second|third|fourth)\b'
                           r'|special\s+stray|stray(?:\s+vacancy)?(?:\s+round)?|mop[\s-]*up',
                           f"{e.get('label') or ''} {e.get('quote') or ''}", _re.I)
            if m:
                rnd = norm_round(m.group(0).replace('phase', 'round').replace('Phase', 'round'))
        out.append({'round': rnd,
                    'event': ev,
                    'label': (str(e.get('label') or '').strip() or EVENT_LABELS[ev])[:120],
                    'start': s.isoformat(), 'end': en.isoformat() if en and en >= s else '',
                    'time': str(e.get('time') or '').strip()[:60],
                    'quote': str(e.get('quote') or '').strip()[:400]})
    return out


def _norm_label(t):
    import re
    return re.sub(r'[^a-z0-9]+', ' ', (t or '').lower()).strip()


def _key(rnd, event, label):
    """Identity of a calendar entry: authority + round + step (+ label for 'other' steps)."""
    return ((rnd or '').strip(), event, _norm_label(label) if event == 'other' else '')


# Which row represents a step when old (pre-merge) data has several: active, newest notice, last edited.
_PICK_ORDER = ("ORDER BY is_active DESC, source_notice_date DESC NULLS LAST, updated_at DESC NULLS LAST, id DESC")


def merge_events(conn, authority_code, events, news_id=None, inbox_id=None, notice_date=None,
                 who='AI (auto)'):
    """MERGE a notice's steps into the authority's calendar (founder 2026-10-10):
      - same step (round + kind) already there with the same dates → no change, no duplicate;
      - different dates from a notice that is NOT older than the one the entry came from →
        the entry is UPDATED (old dates kept in prev_* + pg_counselling_event_log);
      - an older notice never overwrites a newer date (manual fixes count as today);
      - a brand-new step → added.
    Returns {'added','changed','unchanged','skipped_older'}."""
    stats = {'added': 0, 'changed': 0, 'unchanged': 0, 'skipped_older': 0}
    nd = notice_date if isinstance(notice_date, date) else _d(notice_date)
    existing = {}
    for r in conn.execute("SELECT * FROM pg_counselling_events WHERE authority_code = ? " + _PICK_ORDER,
                          (authority_code,)).fetchall():
        r = dict(r)
        k = _key(r['round'], r['event'], r['label'])
        # several rows for one step (legacy, pre-merge) → the first in _PICK_ORDER is "the" entry
        existing.setdefault(k, r)
    for e in events:
        k = _key(e['round'], e['event'], e['label'])
        s0, e0 = _d(e['start']), _d(e['end']) if e.get('end') else None
        row = existing.get(k)
        if not row:
            # the same step re-classified (e.g. 'other' → 'round_window'): same round + same label →
            # update that entry's step type instead of adding a second one
            for k2, r2 in list(existing.items()):
                if (k2[0] == (e['round'] or '').strip() and _norm_label(r2.get('label')) == _norm_label(e['label'])
                        and r2.get('event') != e['event']):
                    conn.execute("UPDATE pg_counselling_events SET event = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP "
                                 "WHERE id = ?", (e['event'], who, r2['id']))
                    r2 = dict(r2, event=e['event'])
                    existing.pop(k2, None)
                    existing[k] = r2
                    row = r2
                    break
        if not row:
            new_id = conn.execute(
                "INSERT INTO pg_counselling_events (authority_code, round, event, label, start_date, end_date, "
                "time_text, quote, news_id, inbox_id, source_notice_date, created_by, updated_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (authority_code, e['round'], e['event'], e['label'], s0, e0, e['time'], e['quote'],
                 news_id, inbox_id, nd, who, who)).fetchone()['id']
            existing[k] = {'id': new_id, 'start_date': s0, 'end_date': e0, 'is_active': True,
                           'source_notice_date': nd, 'news_id': news_id, 'time_text': e['time']}
            stats['added'] += 1
            continue
        same = (row['start_date'] == s0) and ((row.get('end_date') or None) == (e0 or None))
        if same:
            sets, vals = [], []
            if not row.get('time_text') and e['time']:
                sets.append("time_text = ?"); vals.append(e['time'])
            if news_id and not row.get('news_id'):
                sets.append("news_id = ?"); vals.append(news_id)
            if sets:
                conn.execute(f"UPDATE pg_counselling_events SET {', '.join(sets)} WHERE id = ?", vals + [row['id']])
            stats['unchanged'] += 1
            continue
        src = row.get('source_notice_date')
        if src and (nd is None or nd < src):
            stats['skipped_older'] += 1                 # an older / undated notice can't override
            continue
        # A row the team fixed or removed by hand: an automatic AI merge changes it only for a STRICTLY newer
        # notice (a same-day draft — e.g. the misprinted one a fix corrected — must not undo the fix). 2026-11-20
        if who == 'AI (auto)' and (row.get('manual_edit') or row.get('is_active') is False) and src and nd is not None \
                and nd <= src:
            stats['skipped_older'] += 1
            continue
        conn.execute("INSERT INTO pg_counselling_event_log (event_id, old_start, old_end, new_start, new_end, "
                     "inbox_id, notice_date, changed_by, note) VALUES (?,?,?,?,?,?,?,?,?)",
                     (row['id'], row['start_date'], row.get('end_date'), s0, e0, inbox_id, nd, who,
                      'date revised by a newer notice'))
        conn.execute("UPDATE pg_counselling_events SET start_date = ?, end_date = ?, time_text = ?, quote = ?, "
                     "prev_start = ?, prev_end = ?, changed_at = CURRENT_TIMESTAMP, "
                     "change_count = COALESCE(change_count,0) + 1, source_notice_date = ?, inbox_id = ?, "
                     "news_id = COALESCE(?, news_id), is_active = TRUE, manual_edit = FALSE, updated_by = ?, "
                     "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (s0, e0, e['time'] or row.get('time_text') or '', e['quote'], row['start_date'],
                      row.get('end_date'), nd, inbox_id, news_id, who, row['id']))
        stats['changed'] += 1
    return stats


def replace_events_for_news(conn, authority_code, news_id, inbox_id, events, who, notice_date=None):
    """Back-compat name: now a MERGE (never deletes / duplicates). Returns rows added+changed."""
    st = merge_events(conn, authority_code, events, news_id, inbox_id, notice_date, who)
    return st['added'] + st['changed']


_DNB_RE = None


def is_dnb_only(text):
    """True for a DNB-only step / notice ("DNB — submit NOC…", "Post-Diploma DNB — …"); False when MD/MS is
    named too ("Choice filling (MD/MS/DNB)"). (website + founder 2026-11-21: site hides DNB for now)"""
    global _DNB_RE
    import re
    if _DNB_RE is None:
        _DNB_RE = (re.compile(r'\bDNB\b', re.I), re.compile(r'\b(MD|MS|MDS)\b', re.I))
    t = text or ''
    return bool(_DNB_RE[0].search(t)) and not _DNB_RE[1].search(t)


def show_dnb(conn):
    """Public feeds hide DNB-only steps unless pg_kv 'calendar_show_dnb' = 'on' (default hidden, like the
    website's SHOW_DNB=false). The admin Calendar always lists them."""
    try:
        r = conn.execute("SELECT value FROM pg_kv WHERE key = 'calendar_show_dnb'").fetchone()
        return bool(r and r['value'] == 'on')
    except Exception:
        conn.rollback()
        return False


def public_rows(conn, rows):
    """Drop DNB-only steps from a public feed while DNB is hidden."""
    if show_dnb(conn):
        return rows
    return [r for r in rows if not is_dnb_only(r.get('label'))]


def events_for(conn, codes=None, upcoming_only=False, public=False):
    """Active events (optionally for some authority codes), ordered by date. public=True (website feeds,
    reminder emails) also hides DNB-only steps while DNB is hidden."""
    where, params = ["is_active"], []
    if codes:
        where.append("authority_code IN (" + ','.join(['?'] * len(codes)) + ")"); params.extend(codes)
    if upcoming_only:
        where.append("COALESCE(end_date, start_date) >= CURRENT_DATE")
    rows = [dict(r) for r in conn.execute(
        "SELECT id, authority_code, year, round, event, label, start_date, end_date, time_text, note, "
        "news_id, inbox_id, created_by, changed_at, prev_start, prev_end, COALESCE(change_count,0) AS change_count, "
        "COALESCE(manual_edit, FALSE) AS manual_edit, "
        # the posted news article of the notice that last changed this step (website links the "Revised" tag)
        "(SELECT n.id FROM pg_news n WHERE n.inbox_id = pg_counselling_events.inbox_id AND n.deleted_at IS NULL "
        "ORDER BY n.id DESC LIMIT 1) AS change_news_id FROM pg_counselling_events WHERE " + " AND ".join(where) +
        " ORDER BY start_date, CASE WHEN round = '' THEN 'zz' ELSE round END, id", params).fetchall()]
    hide = {d["id"] for d in duplicate_steps(conn, codes)}
    rows = [r for r in rows if r["id"] not in hide]
    return public_rows(conn, rows) if public else rows


def duplicate_steps(conn, codes=None):
    """Old (pre-merge) leftovers: active rows for a step that already has a preferred entry.
    Hidden from every feed; the Calendar page lists them with a "Tidy up" button (founder decides)."""
    where, params = ["is_active"], []
    if codes:
        where.append("authority_code IN (" + ','.join(['?'] * len(codes)) + ")"); params.extend(codes)
    seen, dups = set(), []
    for r in conn.execute("SELECT id, authority_code, round, event, label, start_date, end_date, news_id, inbox_id "
                          "FROM pg_counselling_events WHERE " + " AND ".join(where) + " " + _PICK_ORDER,
                          params).fetchall():
        k = (r['authority_code'],) + _key(r['round'], r['event'], r['label'])
        if k in seen:
            dups.append(dict(r))
        else:
            seen.add(k)
    return dups


_TIME_RE = None


def short_time(t):
    """Website wants `time` short (≤16 chars, e.g. "12 noon"); the full wording goes to `note`.
    → (short or None, full text when it was shortened else None). (website session 2026-10-13)"""
    global _TIME_RE
    import re
    t = (t or '').strip()
    if not t:
        return None, None
    if len(t) <= 16:
        return t, None
    if _TIME_RE is None:
        _TIME_RE = re.compile(r"\b(\d{1,2}(?:[:.]\d{2})?\s*(?:a\.?m\.?|p\.?m\.?|hrs)|12\s*noon|noon|midnight|\d{1,2}:\d{2})",
                              re.I)
    m = _TIME_RE.search(t)
    return ((m.group(0).strip()[:16] if m else None), t)


def _join_note(*parts):
    return ' · '.join(p for p in parts if p) or ''


def as_json_row(r):
    return {'id': r['id'], 'authority_code': r['authority_code'], 'round': r['round'] or '',
            'event': r['event'], 'event_label': EVENT_LABELS.get(r['event'], 'Other'),
            'label': r['label'] or EVENT_LABELS.get(r['event'], ''),
            'start_date': r['start_date'].isoformat() if r.get('start_date') else '',
            'end_date': r['end_date'].isoformat() if r.get('end_date') else '',
            'time': short_time(r.get('time_text'))[0] or '',
            'note': _join_note(short_time(r.get('time_text'))[1], r.get('note')), 'news_id': r.get('news_id'),
            # date moved by a newer notice → the website can show "Revised" (2026-10-10)
            'revised': ({'at': r['changed_at'].date().isoformat() if r.get('changed_at') else '',
                         'previous_start': r['prev_start'].isoformat() if r.get('prev_start') else '',
                         'previous_end': r['prev_end'].isoformat() if r.get('prev_end') else '',
                         'news_id': None if r.get('manual_edit') else r.get('change_news_id')}
                        if r.get('change_count') else None)}


def sync_from_inbox(conn, inbox_id=None):
    """AUTO-FILL (founder 2026-10-09/10): merge every AI-drafted notice's schedule `events` into
    the calendar as soon as the draft arrives — no posting needed. Notices are applied oldest →
    newest so the latest dates win; re-running changes nothing. Returns merge stats."""
    from pg_admin import news_scraper as NS
    ensure_calendar_table(conn)
    where = "draft_json IS NOT NULL AND status <> 'seen'"
    params = []
    conn.execute("SAVEPOINT cal_col")
    try:
        conn.execute("SELECT calendar_synced_at FROM pg_news_inbox LIMIT 0")
        has_col = True
        conn.execute("RELEASE SAVEPOINT cal_col")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT cal_col")
        has_col = False
    if inbox_id:
        where += " AND id = ?"; params.append(inbox_id)          # explicit (arrival / re-draft): always apply
    elif has_col:
        where += " AND calendar_synced_at IS NULL"               # catch-up: only drafts never merged yet
    else:
        return {'added': 0, 'changed': 0, 'unchanged': 0, 'skipped_older': 0}       # never re-merge everything
    tot = {'added': 0, 'changed': 0, 'unchanged': 0, 'skipped_older': 0}
    for r in conn.execute(f"SELECT id, source_code, news_id, notice_date, draft_json FROM pg_news_inbox "
                          f"WHERE {where} ORDER BY notice_date ASC NULLS FIRST, first_seen_at ASC, id ASC",
                          params).fetchall():
        try:
            ev = clean_events((json.loads(r['draft_json'] or '{}') or {}).get('events'))
        except Exception:
            ev = []
        code = (NS.SOURCES.get(r['source_code']) or {}).get('authority_code')
        if ev and code:
            st = merge_events(conn, code, ev, r['news_id'], r['id'], r['notice_date'])
            for k in tot:
                tot[k] += st[k]
        if has_col:
            conn.execute("UPDATE pg_news_inbox SET calendar_synced_at = CURRENT_TIMESTAMP WHERE id = ?", (r['id'],))
    return tot


# ── Dates typed into the NEWS FORM → the calendar (founder 2026-10-31) ───────
# The news form has date boxes (registration / verification / choice filling start & end, fee payment,
# reporting, result). They used to stay on the news item only, so the website's stage tracker (built from
# this calendar) never showed them — e.g. Karnataka's Round 1 choice-filling dates typed into the Option
# Entry news. Now they become calendar steps: matched to an existing step by ROUND + STEP TYPE (whatever its
# label), updated with the change logged, or added. Typed dates count as today's notice, so they win over
# older AI dates.
KEY_DATE_STEPS = [('registration', 'registration_start', 'registration_end'),
                  ('verification', 'verification_start', 'verification_end'),
                  ('choice_filling', 'choice_filling_start', 'choice_filling_end'),
                  ('payment', None, 'payment_last_date'),
                  ('reporting', None, 'reporting_last_date'),
                  ('result', 'result_date', None)]
_ROUND_EVENTS = {'choice_filling', 'choice_locking', 'payment', 'seat_processing', 'result', 'reporting'}


def _round_from_text(text):
    import re as _re
    m = _re.search(r'\b(?:round|phase)[\s-]*(?:\d|i{1,3}v?|iv|one|two|three|four|first|second|third|fourth)\b'
                   r'|special\s+stray|stray(?:\s+vacancy)?(?:\s+round)?|mop[\s-]*up', text or '', _re.I)
    return norm_round(m.group(0).replace('phase', 'round').replace('Phase', 'round')) if m else ''


def events_from_key_dates(key_dates, heading=''):
    """A news item's key_dates ({field: {date, time?, round?}}) → calendar steps (clean_events shape).
    Round: the one picked on the form, else named in the heading, else Round 1 for allotment steps
    (choice filling / payment / result / reporting); registration / verification may stay general."""
    try:
        kd = json.loads(key_dates) if isinstance(key_dates, str) else (key_dates or {})
    except Exception:
        kd = {}
    if not isinstance(kd, dict):
        return []
    raw = []
    for ev, ks, ke in KEY_DATE_STEPS:
        s = (kd.get(ks) or {}) if ks else {}
        e = (kd.get(ke) or {}) if ke else {}
        sd, ed = _d(s.get('date')), _d(e.get('date'))
        if not (sd or ed):
            continue
        rnd = norm_round(s.get('round') or e.get('round')) or _round_from_text(heading)
        if not rnd and ev in _ROUND_EVENTS:
            rnd = 'Round 1'
        raw.append({'event': ev, 'round': rnd, 'label': EVENT_LABELS[ev],
                    'start': (sd or ed).isoformat(), 'end': ed.isoformat() if (sd and ed and ed >= sd) else '',
                    'time': e.get('time') or s.get('time') or '', 'quote': 'Entered on the news form'})
    return clean_events(raw)


def _step_row(conn, code, rnd, ev):
    return conn.execute("SELECT * FROM pg_counselling_events WHERE authority_code = ? AND COALESCE(round,'') = ? "
                        "AND event = ? AND is_active ORDER BY COALESCE(source_notice_date, DATE '1900-01-01') DESC, id DESC "
                        "LIMIT 1", (code, rnd or '', ev)).fetchone()


def news_date_changes(conn, code, events):
    """[(event, existing_row | None, 'add' | 'update')] — only steps whose dates are missing or different."""
    out = []
    for e in events:
        row = _step_row(conn, code, e['round'], e['event'])
        if row:
            row = dict(row)
            if row['start_date'] == _d(e['start']) and (row.get('end_date') or None) == (_d(e['end']) if e['end'] else None):
                continue
            out.append((e, row, 'update'))
        else:
            out.append((e, None, 'add'))
    return out


def apply_news_dates(conn, code, events, news_id=None, inbox_id=None, who='news form'):
    """Put a news item's typed dates into the calendar (see news_date_changes). Returns merge stats."""
    stats = {'added': 0, 'changed': 0, 'unchanged': 0, 'skipped_older': 0}
    if not (code and events):
        return stats
    # NO ensure_calendar_table() here: it COMMITS, which breaks the caller's SAVEPOINT / transaction
    # (2026-11-01: news save showed "Update saved" + "Could not save"). Callers ensure the table first.
    for e, row, _what in news_date_changes(conn, code, events):
        if row:                       # same step under the existing label → merge_events updates it (logged)
            e = dict(e, label=row.get('label') or e['label'])
        st = merge_events(conn, code, [e], news_id, inbox_id, date.today(), who)
        for k in stats:
            stats[k] += st[k]
    return stats


def pending_news_dates(conn, codes=None):
    """Published news whose typed dates are NOT in the calendar yet (for the Calendar page review list):
    [{news_id, heading, authority_code, event, event_label, round, start, end, existing_start, existing_end, what}]."""
    from pg_admin.authorities import all_authorities
    states = {a['state'].strip().lower(): a['code'] for a in all_authorities() if a['kind'] == 'state'}
    ensure_calendar_table(conn)
    out = []
    try:
        rows = conn.execute("SELECT id, heading, scope, COALESCE(state,'') AS state, key_dates, "
                            "CAST(COALESCE(published_at, created_at) AS DATE) AS ndate FROM pg_news "
                            "WHERE is_published AND deleted_at IS NULL AND COALESCE(key_dates,'') NOT IN ('', '{}') "
                            "ORDER BY id").fetchall()
    except Exception:
        conn.rollback()
        return out
    for n in rows:
        code = 'mcc' if n['scope'] == 'all_india' else states.get((n['state'] or '').strip().lower(), '')
        if not code or (codes and code not in codes):
            continue
        for e, row, what in news_date_changes(conn, code, events_from_key_dates(n['key_dates'], n['heading'])):
            # Only dates still worth acting on (founder 2026-11-21: 150 old items, adding them would undo revisions):
            last = _d(e['end']) if e['end'] else _d(e['start'])
            if last and last < date.today():
                continue                      # already over
            if row and n['ndate'] and row.get('source_notice_date') and n['ndate'] < row['source_notice_date']:
                continue                      # the calendar has this step from a LATER notice
            if row and not row.get('is_active') and row.get('manual_edit'):
                continue                      # hidden by hand (e.g. step postponed) — don't bring it back
            out.append({'news_id': n['id'], 'heading': n['heading'], 'authority_code': code, 'event': e['event'],
                        'event_label': EVENT_LABELS.get(e['event'], e['event']), 'round': e['round'] or 'General',
                        'start': e['start'], 'end': e['end'], 'what': what,
                        'existing_start': str(row['start_date']) if row else '',
                        'existing_end': str(row.get('end_date') or '') if row else ''})
    return out
