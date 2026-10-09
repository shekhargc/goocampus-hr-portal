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


def ensure_calendar_table(conn=None):
    own = conn is None
    if own:
        from db import get_db
        conn = get_db()
    try:
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
        conn.commit()
    except Exception as e:
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
        out.append({'round': norm_round(e.get('round')),
                    'event': ev,
                    'label': (str(e.get('label') or '').strip() or EVENT_LABELS[ev])[:120],
                    'start': s.isoformat(), 'end': en.isoformat() if en and en >= s else '',
                    'time': str(e.get('time') or '').strip()[:60],
                    'quote': str(e.get('quote') or '').strip()[:400]})
    return out


def replace_events_for_news(conn, authority_code, news_id, inbox_id, events, who):
    """Put a posted notice's events into the calendar, replacing any rows that same news /
    inbox notice added before (so re-posting an updated draft never duplicates)."""
    conn.execute("DELETE FROM pg_counselling_events WHERE (news_id = ? AND ? IS NOT NULL) "
                 "OR (inbox_id = ? AND ? IS NOT NULL)", (news_id, news_id, inbox_id, inbox_id))
    n = 0
    for e in events:
        conn.execute(
            "INSERT INTO pg_counselling_events (authority_code, round, event, label, start_date, end_date, "
            "time_text, quote, news_id, inbox_id, created_by, updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (authority_code, e['round'], e['event'], e['label'], e['start'], e['end'] or None,
             e['time'], e['quote'], news_id, inbox_id, who, who))
        n += 1
    return n


def events_for(conn, codes=None, upcoming_only=False):
    """Active events (optionally for some authority codes), ordered by date."""
    where, params = ["is_active"], []
    if codes:
        where.append("authority_code IN (" + ','.join(['?'] * len(codes)) + ")"); params.extend(codes)
    if upcoming_only:
        where.append("COALESCE(end_date, start_date) >= CURRENT_DATE")
    return [dict(r) for r in conn.execute(
        "SELECT id, authority_code, year, round, event, label, start_date, end_date, time_text, note, "
        "news_id FROM pg_counselling_events WHERE " + " AND ".join(where) +
        " ORDER BY start_date, CASE WHEN round = '' THEN 'zz' ELSE round END, id", params).fetchall()]


def as_json_row(r):
    return {'id': r['id'], 'authority_code': r['authority_code'], 'round': r['round'] or '',
            'event': r['event'], 'event_label': EVENT_LABELS.get(r['event'], 'Other'),
            'label': r['label'] or EVENT_LABELS.get(r['event'], ''),
            'start_date': r['start_date'].isoformat() if r.get('start_date') else '',
            'end_date': r['end_date'].isoformat() if r.get('end_date') else '',
            'time': r.get('time_text') or '', 'note': r.get('note') or '', 'news_id': r.get('news_id')}
