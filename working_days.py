"""Item F: Working-day scheduler helpers.

Used wherever we need to compute "N working days from <date>" honouring:
  * Weekends (Saturday + Sunday treated as non-working)
  * Admin-managed holidays from the `holidays` table
  * A 5pm IST cutoff -- if base is today and the current IST hour is >=
    the cutoff, today is treated as already past (so add_working_days
    starts counting from tomorrow).

The module deliberately has no Flask / app.py dependency; pass in the
holidays set explicitly. Call load_holidays_set(conn) once per request
to populate it from the DB.
"""

from datetime import datetime, timedelta, date


IST_OFFSET = timedelta(hours=5, minutes=30)
DEFAULT_CUTOFF_HOUR = 17  # 5pm IST


def now_ist():
    """Current wall-clock time in IST (timezone-naive datetime)."""
    return datetime.utcnow() + IST_OFFSET


def _as_date(value):
    """Coerce date / datetime / 'YYYY-MM-DD' string to a date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value)[:10]
    return datetime.strptime(s, '%Y-%m-%d').date()


def is_working_day(d, holidays_set):
    """True iff d (a date or 'YYYY-MM-DD') is Mon-Fri AND not in holidays_set.

    holidays_set: an iterable of 'YYYY-MM-DD' strings. Pass an empty
    set if the DB lookup is unavailable -- only weekends will be
    skipped in that case.
    """
    d = _as_date(d)
    if d is None:
        return False
    if d.weekday() >= 5:
        return False
    return d.isoformat() not in (holidays_set or set())


def next_working_day(start, holidays_set):
    """Smallest date >= start that is a working day."""
    d = _as_date(start)
    while not is_working_day(d, holidays_set):
        d += timedelta(days=1)
    return d


def add_working_days(base, n, holidays_set,
                     cutoff_hour=DEFAULT_CUTOFF_HOUR,
                     now_ist_dt=None):
    """Return the date N working days after `base`.

    Semantics:
      * If `base` is today in IST and the current IST hour is >=
        cutoff_hour, the function silently advances `base` by one
        calendar day before doing any work (the "5pm cutoff" rule).
      * If `base` (post-cutoff-adjustment) lands on a weekend or
        holiday, it's first rolled forward to the next working day --
        THEN the n-day walk begins. So n=0 always returns a working
        day; n=1 returns the next working day after that.

    Arguments:
      base:         date / datetime / 'YYYY-MM-DD' string.
      n:            non-negative int.
      holidays_set: set of 'YYYY-MM-DD' strings.
      cutoff_hour:  hour-of-day in IST (0-23) after which 'today' is
                    treated as past. Pass None to disable.
      now_ist_dt:   override for testing. Defaults to now_ist().

    Returns: date.
    """
    if n < 0:
        raise ValueError("n must be >= 0")
    if now_ist_dt is None:
        now_ist_dt = now_ist()
    today_ist = now_ist_dt.date()

    b = _as_date(base)

    # 5pm cutoff rule: if base is today and we're past it, advance.
    if (cutoff_hour is not None
            and b == today_ist
            and now_ist_dt.hour >= cutoff_hour):
        b = b + timedelta(days=1)

    # Roll forward to the first working day at or after b.
    current = next_working_day(b, holidays_set)

    # n=0 means "this starting working day". n=1 means "one
    # working day after the start". And so on.
    days_added = 0
    while days_added < n:
        current += timedelta(days=1)
        if is_working_day(current, holidays_set):
            days_added += 1
    return current


def load_holidays_set(conn):
    """Pull all holiday_date values from the holidays table.
    Returns a set of 'YYYY-MM-DD' strings -- empty on any error so
    callers never crash from a missing table / column.
    """
    try:
        rows = conn.execute("SELECT holiday_date FROM holidays").fetchall()
        out = set()
        for r in rows:
            v = r['holiday_date']
            if v is None:
                continue
            out.add(str(v)[:10])
        return out
    except Exception:
        return set()
