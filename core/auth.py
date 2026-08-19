"""
core/auth.py — authentication & authorization decorators and helpers.

Moved out of app.py as part of the multi-step refactor (see REFACTOR_PLAN.md).
No behavior change — these are imported back into app.py and used exactly
as before.

Decorators here:
- login_required        : require a logged-in employee session
- admin_required        : require an admin employee
- client_required       : require a logged-in client session
- sales_access_required : require sales module access

Permission helpers:
- can_post_announcements : admin or management can post announcements
- can_approve_leave      : decides who can approve a given leave request
- has_module_access      : check CRM module grant (sales / projects / etc.)

Constants:
- MANAGEMENT_CODES : employee codes treated as management
"""

from functools import wraps
from flask import session, redirect, url_for, flash

from db import get_db


# Management codes that can post announcements (along with admin)
MANAGEMENT_CODES = ['GC001', 'GC002', 'GC003']


def login_required(f):
    """Require a logged-in EMPLOYEE session; otherwise redirect to /login.

    SECURITY: employee and client logins share session['user_id'] (an employee
    id vs a client_accounts id). A client session is is_client=True. Without the
    is_client/is_partner guard below, a logged-in client passes this decorator
    and the page's get_user() resolves their id against `employees`, silently
    logging them into the employee whose id matches — a cross-account leak
    (client landing in an ex-employee's account). Send client/partner sessions
    to their own area instead of the staff page. (founder 2026-08-19)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('is_client'):
            return redirect(url_for('client_dashboard'))
        if session.get('is_partner'):
            return redirect(url_for('login'))
        # Enforce is_active on every request: a resigned/disabled employee's
        # existing session must stop working immediately (not just at the login
        # form). is_active is set when HR marks them resigned.
        conn = get_db()
        row = conn.execute('SELECT is_active FROM employees WHERE id = ?',
                           (session['user_id'],)).fetchone()
        conn.close()
        if not row or not row['is_active']:
            session.clear()
            flash('Your account is inactive. Please contact HR.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Allow the request through if the logged-in employee is either:
      (a) flagged is_admin=1, or
      (b) holds at least one Access Master grant (user_section_permissions
          row with can_view=1).

    Background. The portal originally had two roles: admin (sees
    everything) and employee (sees their own HR/KRA). The Access Master
    system (rolled out in 6 phases ending 2026-06-01) introduced
    fine-grained per-section grants so a non-admin like a service-
    delivery specialist can be granted Operations access without
    becoming a full admin.

    Without (b), @admin_required rejected those users at the decorator
    layer, before the per-request access_master_request_audit could
    grant them access. That broke Alfiya's Operations access on
    2026-06-05 even though she had 61 matching grants.

    The real per-section enforcement happens in app.py's
    @app.before_request access_master_request_audit, which runs
    ACCESS_MASTER_ENFORCE=True against ACCESS_ROUTE_MAP and redirects
    users to the dashboard for sections they don't have. So at the
    decorator layer we only need the coarse check "is this user
    authorized for ANY internal section?".
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        # SECURITY: never let a client/partner session resolve as an employee
        # (shared session['user_id'] namespace — see login_required). A client
        # id colliding with an admin employee id would otherwise grant admin.
        if session.get('is_client'):
            return redirect(url_for('client_dashboard'))
        if session.get('is_partner'):
            return redirect(url_for('login'))
        conn = get_db()
        user = conn.execute(
            'SELECT is_admin, is_active FROM employees WHERE id = ?',
            (session['user_id'],)
        ).fetchone()
        # Resigned/disabled account: kill the live session immediately.
        if not user or not user['is_active']:
            conn.close()
            session.clear()
            flash('Your account is inactive. Please contact HR.', 'error')
            return redirect(url_for('login'))
        if user and user['is_admin'] == 1:
            conn.close()
            return f(*args, **kwargs)
        # Non-admin: allow if they hold at least one Access Master grant.
        # Per-route enforcement runs after this in @app.before_request.
        grant_row = conn.execute(
            "SELECT 1 FROM user_section_permissions "
            "WHERE employee_id = ? AND can_view = 1 LIMIT 1",
            (session['user_id'],),
        ).fetchone()
        conn.close()
        if grant_row:
            return f(*args, **kwargs)
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    return decorated_function


def client_required(f):
    """Require a logged-in client session (different login flow from employees)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_client'):
            flash('Please log in to continue', 'error')
            return redirect(url_for('client_login_page'))
        return f(*args, **kwargs)
    return decorated_function


def can_post_announcements(user):
    """Check if user is admin or management team."""
    return user['is_admin'] == 1 or user['emp_code'] in MANAGEMENT_CODES


def can_approve_leave(approver, leave_employee, conn):
    """Determine if approver can approve/reject a leave for leave_employee.
    Returns (allowed: bool, reason: str).
    Rules:
      1. Never self-approve
      2. Management (GC001-GC003) leaves → other management members can approve
      3. Employee with reporting_to → reporting manager OR any admin can approve
      4. Employee without reporting_to → only admin can approve
    """
    if approver['id'] == leave_employee['id']:
        return False, 'You cannot approve your own leave request'

    emp_code = leave_employee.get('emp_code', '')
    approver_code = approver.get('emp_code', '')

    # Management cross-approval: any management member can approve another's leave
    if emp_code in MANAGEMENT_CODES and approver_code in MANAGEMENT_CODES:
        return True, 'management_peer'

    # Admin can approve anyone else's leave
    if approver['is_admin'] == 1:
        return True, 'admin'

    # Reporting manager can approve their direct report's leave
    reporting_to = leave_employee.get('reporting_to')
    if reporting_to and reporting_to == approver['id']:
        return True, 'manager'

    return False, 'Not authorized to approve this leave'


def has_module_access(user, module):
    """Check if user has access to a CRM module (sales, projects, b2b_meetings).
    Admin and management always have access. Others need explicit grant."""
    if user['is_admin'] == 1 or user['emp_code'] in MANAGEMENT_CODES:
        return True
    conn = get_db()
    access = conn.execute(
        'SELECT id FROM module_access WHERE employee_id = ? AND module = ? AND is_active = 1',
        (user['id'], module)
    ).fetchone()
    conn.close()
    return access is not None


def sales_access_required(f):
    """Decorator requiring sales module access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        # Lazy import to avoid any startup ordering issue between auth.py & users.py
        from core.users import get_user
        user = get_user()
        if not has_module_access(user, 'sales'):
            flash('Sales module access required', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function
