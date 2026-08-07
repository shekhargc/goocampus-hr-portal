"""
core/helpers.py — small, pure utility functions used across the app.

Moved out of app.py as part of the multi-step refactor (see REFACTOR_PLAN.md).
No behavior change — these functions are imported back into app.py and used
exactly as before.
"""

import hashlib
import re as _re


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def format_reg(value):
    """Canonical GooCampus registration-number display: <PREFIX>/YY-YY/NNN,
    for EVERY pathway prefix (GCUKIP, GCAUSIP, GCCSS, GCTRN, GCUAE/GCUAEIP,
    GCPPLUS, GCCONS, GCSE, and any future GC… prefix). Accepts either source
    form (4-digit year or YY-YY) and pads the trailing number to >=3 digits.
    Unknown shapes are returned as-is; empty/None becomes '—'.

    Single source of truth: app.py's `format_reg` Jinja filter and the Excel/
    CSV report exports all delegate here, so the format never drifts between
    the screen and the download.
    """
    if not value or not isinstance(value, str):
        return value or '—'
    value = value.strip()
    if not value:
        return '—'

    def _pad(n):
        try:
            return f"{int(n):03d}"
        except (ValueError, TypeError):
            return n

    m = _re.match(r'^(GC[A-Z0-9]+)/(\d{2,4}(?:-\d{2,4})?)/(\d+)$', value, _re.IGNORECASE)
    if not m:
        return value
    prefix = m.group(1).upper()
    middle = m.group(2)
    num = _pad(m.group(3))

    if _re.match(r'^\d{4}$', middle):
        year = int(middle)
        yy = year % 100
        middle = f"{yy:02d}-{(yy + 1) % 100:02d}"
    elif _re.match(r'^\d{2}-\d{2}$', middle):
        pass
    elif _re.match(r'^\d{2,4}-\d{2,4}$', middle):
        a, b = middle.split('-')
        try:
            middle = f"{int(a) % 100:02d}-{int(b) % 100:02d}"
        except ValueError:
            pass
    return f"{prefix}/{middle}/{num}"


def allowed_file(filename):
    """Return True if the filename's extension is in ALLOWED_EXTENSIONS."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def hash_password(password):
    """SHA-256 hex digest of a password string."""
    return hashlib.sha256(password.encode()).hexdigest()
