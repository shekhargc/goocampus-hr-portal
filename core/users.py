"""
core/users.py — small user-related query helpers.

Moved out of app.py as part of the multi-step refactor (see REFACTOR_PLAN.md).
No behavior change.

Functions:
- get_user                : load the logged-in employee row from DB
- is_manager              : does this user have any direct reports?
- get_pending_team_count  : count of pending leave requests from direct reports
"""

from flask import session

from db import get_db


def get_user():
    """Return the logged-in employee row, or None if no active session."""
    if 'user_id' not in session:
        return None
    conn = get_db()
    user = conn.execute(
        'SELECT * FROM employees WHERE id = ?',
        (session['user_id'],)
    ).fetchone()
    conn.close()
    return user


def is_manager(user_id):
    """Check if user has any direct reports."""
    conn = get_db()
    count = conn.execute(
        'SELECT COUNT(*) as cnt FROM employees WHERE reporting_to = ? AND is_active = 1',
        (user_id,)
    ).fetchone()
    conn.close()
    return count['cnt'] > 0


def get_pending_team_count(user_id):
    """Get count of pending leave requests from direct reports."""
    conn = get_db()
    count = conn.execute('''
        SELECT COUNT(*) as cnt FROM leave_records lr
        JOIN employees e ON lr.employee_id = e.id
        WHERE lr.status = 'pending' AND e.reporting_to = ?
    ''', (user_id,)).fetchone()
    conn.close()
    return count['cnt']
