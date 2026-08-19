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
    """Return the logged-in employee row, or None if no active session.

    SECURITY: employees and clients share the same `session['user_id']` key
    (an employee id vs a client_accounts id — independent sequences that DO
    collide). A client session is flagged is_client=True. If we resolved a
    client's user_id against `employees` we'd hand back the employee whose id
    happens to equal the client's id (e.g. a client landing in an ex-employee's
    account). Refuse any client/partner session here. (founder 2026-08-19)
    """
    if 'user_id' not in session:
        return None
    if session.get('is_client') or session.get('is_partner'):
        return None
    conn = get_db()
    # is_active is the single login-access switch: the moment HR marks an
    # employee resigned/inactive, their existing session stops resolving here
    # (login access disabled everywhere, not just at the login form).
    user = conn.execute(
        'SELECT * FROM employees WHERE id = ? AND is_active = 1',
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
