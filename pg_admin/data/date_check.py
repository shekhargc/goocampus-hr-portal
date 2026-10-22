"""Date coverage check for AI drafts (founder 2026-10-22: a Kerala draft said "extended to 24 Oct,
11 AM" in its text while its date fields were empty — every deadline a doctor reads must also be a
date field, so the schedule, deadline reminders and the website show it).

gaps(draft) → the dates written in headline / summary / article / action that are NOT in the draft's
`dates`, `events` or `issued_on`. Reference dates ("notification dated 12.10.2026", "earlier notices of
12 and 16 October") are ignored. Read-only; used for an Inbox warning and the Coverage page.
"""
import re
from datetime import date

SEASON_START = date(2026, 7, 1)          # = news_scraper.SEASON_FROM (bump each year)
_MON = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct',
                                    'nov', 'dec'], 1)}
_MONTH = r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
# "24 October 2026", "24 Oct", "24th October", "22–26 October" (both days), "October 24, 2026"
_DMY_WORD = re.compile(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*(?:[-–]|to|and|&)\s*(\d{{1,2}})(?:st|nd|rd|th)?)?\s+{_MONTH}\b\.?(?:,?\s+(20\d\d))?', re.I)
_MDY_WORD = re.compile(rf'\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(20\d\d))?\b', re.I)
_NUMERIC = re.compile(r'\b(\d{1,2})[./-](\d{1,2})[./-](20\d\d|\d\d)\b')
# a date that names ANOTHER notice ("the 16 October notice", "22 Oct 2026 extension")
_REF_AFTER = re.compile(r'^\W{0,3}(?:20\d\d\W{1,3})?(?:notice|notification|press\s+release|extension|order|letter|circular|corrigendum)', re.I)
# eligibility / document cut-offs, not counselling steps ("internship completed by 30 September 2026")
_ELIGIBILITY = re.compile(r'internship|as\s+on|born|date\s+of\s+birth|valid(?:ity)?\s+(?:till|up\s*to|on)|certificate\s+(?:issued|dated)|'
                          r'header|printed\s+date|academic\s+year', re.I)
_REFERENCE = re.compile(r'(dated|notifications?\s+(?:of|dated)|earlier\s+(?:notice|notification)s?|issued\s+on|'
                        r'letter\s+(?:no|dated)|order\s+dated|vide)\W*(?:\w+\W+){0,4}$', re.I)


def _mk(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except (TypeError, ValueError):
        return None


def mentioned(text, year=2026):
    """{date: 'snippet'} for every calendar date written in the text, minus reference dates."""
    out = {}
    t = text or ''

    def add(dt, start, end):
        if not dt or dt < SEASON_START:
            return                                   # last season's dates (old headers) aren't steps
        before = t[max(0, start - 60):start]
        if _REFERENCE.search(before) or _REF_AFTER.search(t[end:end + 40]):
            return
        if _ELIGIBILITY.search(t[max(0, start - 70):start]):
            return
        out.setdefault(dt, t[max(0, start - 25):start + 30].replace('\n', ' ').strip())

    for m in _DMY_WORD.finditer(t):
        mon = _MON[m.group(3)[:3].lower()]
        y = m.group(4) or year
        add(_mk(y, mon, m.group(1)), m.start(), m.end())
        if m.group(2):
            add(_mk(y, mon, m.group(2)), m.start(), m.end())
    for m in _MDY_WORD.finditer(t):
        add(_mk(m.group(3) or year, _MON[m.group(1)[:3].lower()], m.group(2)), m.start(), m.end())
    for m in _NUMERIC.finditer(t):
        y = m.group(3)
        y = int(y) + 2000 if len(y) == 2 else int(y)
        add(_mk(y, m.group(2), m.group(1)), m.start(), m.end())
    return out


def _d(v):
    try:
        return date.fromisoformat(str(v or '')[:10])
    except ValueError:
        return None


def field_dates(draft):
    """Every date the draft carries in structured fields (dates, events start..end, issued_on)."""
    s = set()
    for v in (draft.get('dates') or {}).values():
        if isinstance(v, dict) and _d(v.get('date')):
            s.add(_d(v.get('date')))
    for e in draft.get('events') or []:
        a, b = _d(e.get('start')), _d(e.get('end'))
        if a:
            s.add(a)
        if b:
            s.add(b)
        if a and b and 0 < (b - a).days <= 62:      # a window covers the days inside it
            s.update(date.fromordinal(a.toordinal() + i) for i in range(1, (b - a).days))
    io = draft.get('issued_on') or {}
    if isinstance(io, dict) and _d(io.get('date')):
        s.add(_d(io.get('date')))
    return s


def gaps(draft, notice_date=None, calendar_dates=None):
    """Sorted [(date, snippet, in_calendar)] written in the text but missing from the draft's date
    fields. in_calendar = the authority's schedule already shows that date (from another notice)."""
    if not isinstance(draft, dict):
        return []
    if (draft.get('document') or {}).get('category') == 'none' and str(draft.get('headline') or '').lower().startswith('duplicate'):
        return []
    text = '\n'.join(str(draft.get(k) or '') for k in ('headline', 'summary', 'article', 'action'))
    have = field_dates(draft)
    nd = _d(notice_date)
    out = []
    for dt, snip in mentioned(text).items():
        if dt in have or (nd and dt == nd):
            continue
        out.append((dt, snip, bool(calendar_dates and dt in calendar_dates)))
    return sorted(out)


def calendar_dates(conn, authority_code):
    """Every date an authority's active calendar steps cover (start, end and the days between)."""
    s = set()
    try:
        for r in conn.execute("SELECT start_date, end_date FROM pg_counselling_events WHERE authority_code = ? "
                              "AND COALESCE(is_active, TRUE)", (authority_code,)).fetchall():
            a, b = r['start_date'], r['end_date'] or r['start_date']
            if a:
                s.add(a)
                s.add(b)
                if b and 0 < (b - a).days <= 62:
                    s.update(date.fromordinal(a.toordinal() + i) for i in range(1, (b - a).days))
    except Exception:
        try: conn.rollback()
        except Exception: pass
    return s
