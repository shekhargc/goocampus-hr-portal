"""
core/helpers.py — small, pure utility functions used across the app.

Moved out of app.py as part of the multi-step refactor (see REFACTOR_PLAN.md).
No behavior change — these functions are imported back into app.py and used
exactly as before.
"""

import hashlib


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    """Return True if the filename's extension is in ALLOWED_EXTENSIONS."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def hash_password(password):
    """SHA-256 hex digest of a password string."""
    return hashlib.sha256(password.encode()).hexdigest()
