import os
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_file
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import calendar
from db import get_db

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'goocampus-leave-2026')
app.config['DEBUG'] = False

PHOTO_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'photos')
os.makedirs(PHOTO_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        conn = get_db()
        user = conn.execute('SELECT is_admin FROM employees WHERE id = ?', (session['user_id'],)).fetchone()
        conn.close()
        if not user or user['is_admin'] != 1:
            flash('Admin access required', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def get_user():
    if 'user_id' not in session:
        return None
    conn = get_db()
    user = conn.execute('SELECT * FROM employees WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    return user

def is_manager(user_id):
    """Check if user has any direct reports"""
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) as cnt FROM employees WHERE reporting_to = ? AND is_active = 1', (user_id,)).fetchone()
    conn.close()
    return count['cnt'] > 0

def get_pending_team_count(user_id):
    """Get count of pending leave requests from direct reports"""
    conn = get_db()
    count = conn.execute('''
        SELECT COUNT(*) as cnt FROM leave_records lr
        JOIN employees e ON lr.employee_id = e.id
        WHERE lr.status = 'pending' AND e.reporting_to = ?
    ''', (user_id,)).fetchone()
    conn.close()
    return count['cnt']

@app.context_processor
def inject_manager_status():
    """Make is_manager and pending_team_count available in all templates"""
    if 'user_id' in session:
        user_id = session['user_id']
        mgr = is_manager(user_id)
        pending_team = get_pending_team_count(user_id) if mgr else 0
        return {'is_manager': mgr, 'pending_team_count': pending_team}
    return {'is_manager': False, 'pending_team_count': 0}

def calculate_monthly_balance(employee_id, year, month):
    """Calculate running balance for a given month"""
    conn = get_db()

    # Get carry forward
    emp = conn.execute('SELECT carry_forward FROM employees WHERE id = ?', (employee_id,)).fetchone()
    carry_forward = emp['carry_forward'] if emp else 0

    # Total annual allocation = 25 + carry_forward
    total_allocation = 25 + carry_forward
    monthly_allocation = total_allocation / 12

    # Calculate balance up to and including the given month
    balance = 0
    for m in range(4, month + 1):  # FY starts April (month 4)
        balance += monthly_allocation
        # Subtract approved leaves in this month
        leaves = conn.execute('''
            SELECT SUM(days) as total_days FROM leave_records
            WHERE employee_id = ? AND status = 'approved'
            AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
        ''', (employee_id, str(year if m >= 4 else year - 1), str(m).zfill(2))).fetchone()

        if leaves['total_days']:
            balance -= leaves['total_days']

    conn.close()
    return max(0, balance)

def get_available_balance(employee_id, year, month):
    """Get available balance at the start of a month"""
    conn = get_db()

    emp = conn.execute('SELECT carry_forward FROM employees WHERE id = ?', (employee_id,)).fetchone()
    carry_forward = emp['carry_forward'] if emp else 0

    total_allocation = 25 + carry_forward
    monthly_allocation = total_allocation / 12

    # Get balance from start of FY to end of previous month
    balance = 0
    for m in range(4, month):
        balance += monthly_allocation
        leaves = conn.execute('''
            SELECT SUM(days) as total_days FROM leave_records
            WHERE employee_id = ? AND status = 'approved'
            AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
        ''', (employee_id, str(year if m >= 4 else year - 1), str(m).zfill(2))).fetchone()

        if leaves['total_days']:
            balance -= leaves['total_days']

    conn.close()
    return max(0, balance)

def get_leaves_for_month(employee_id, year, month):
    """Get all approved leaves for a specific month"""
    conn = get_db()
    leaves = conn.execute('''
        SELECT * FROM leave_records
        WHERE employee_id = ? AND status = 'approved'
        AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
        ORDER BY leave_date
    ''', (employee_id, str(year), str(month).zfill(2))).fetchall()
    conn.close()
    return leaves

def get_all_holidays():
    """Get all holidays"""
    conn = get_db()
    holidays = conn.execute('SELECT * FROM holidays ORDER BY holiday_date').fetchall()
    conn.close()
    return {row['holiday_date']: row for row in holidays}

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = get_user()
    if user and user['is_admin']:
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        emp_code = request.form.get('emp_code', '').strip()
        password = request.form.get('password', '').strip()

        if not emp_code or not password:
            flash('Employee code and password required', 'error')
            return render_template('login.html')

        conn = get_db()
        user = conn.execute('SELECT * FROM employees WHERE emp_code = ? AND is_active = 1', (emp_code,)).fetchone()
        conn.close()

        if user and user['password'] == hash_password(password):
            session['user_id'] = user['id']
            session['is_admin'] = user['is_admin']
            flash('Login successful', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials or account inactive', 'error')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    user = get_user()
    if request.method == 'POST':
        old_password = request.form.get('old_password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if not old_password or not new_password or not confirm_password:
            flash('All fields required', 'error')
            return render_template('change_password.html', user=user)

        if user['password'] != hash_password(old_password):
            flash('Current password is incorrect', 'error')
            return render_template('change_password.html', user=user)

        if new_password != confirm_password:
            flash('New passwords do not match', 'error')
            return render_template('change_password.html', user=user)

        if len(new_password) < 4:
            flash('Password must be at least 4 characters', 'error')
            return render_template('change_password.html', user=user)

        conn = get_db()
        conn.execute('UPDATE employees SET password = ? WHERE id = ?', (hash_password(new_password), user['id']))
        conn.commit()
        conn.close()

        flash('Password changed successfully', 'success')
        return redirect(url_for('dashboard'))

    return render_template('change_password.html', user=user)

@app.route('/dashboard')
@login_required
def dashboard():
    user = get_user()
    if user['is_admin']:
        return redirect(url_for('admin_dashboard'))

    conn = get_db()

    # Current FY (April to March)
    today = datetime.now()
    current_year = today.year
    current_month = today.month
    fy_year = current_year if current_month >= 4 else current_year - 1

    # Total balance calculation
    emp = conn.execute('SELECT carry_forward FROM employees WHERE id = ?', (user['id'],)).fetchone()
    carry_forward = emp['carry_forward'] if emp else 0
    total_allocation = 25 + carry_forward

    # Days taken this FY
    leaves = conn.execute('''
        SELECT SUM(days) as total_days FROM leave_records
        WHERE employee_id = ? AND status = 'approved'
        AND ((strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) >= '04')
             OR (strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) < '04'))
    ''', (user['id'], str(fy_year), str(fy_year + 1))).fetchone()

    days_taken = leaves['total_days'] if leaves['total_days'] else 0
    available_balance = total_allocation - days_taken

    # Pending requests
    pending = conn.execute('''
        SELECT COUNT(*) as count FROM leave_records
        WHERE employee_id = ? AND status = 'pending'
    ''', (user['id'],)).fetchone()

    # Recent leave history
    recent = conn.execute('''
        SELECT * FROM leave_records
        WHERE employee_id = ?
        ORDER BY created_at DESC LIMIT 10
    ''', (user['id'],)).fetchall()

    # Mini calendar data - current month
    holidays = get_all_holidays()
    month_leaves = get_leaves_for_month(user['id'], current_year, current_month)
    leave_dates = {lr['leave_date']: lr for lr in month_leaves}

    # Get direct reports if manager
    direct_reports = conn.execute('''
        SELECT e.id, e.name, e.photo_url, e.department, e.designation,
               (SELECT SUM(lr2.days) FROM leave_records lr2 WHERE lr2.employee_id = e.id AND lr2.status = 'approved') as total_taken,
               (SELECT COUNT(*) FROM leave_records lr3 WHERE lr3.employee_id = e.id AND lr3.status = 'pending') as pending_leaves
        FROM employees e WHERE e.reporting_to = ? AND e.is_active = 1 ORDER BY e.name
    ''', (user['id'],)).fetchall()

    # Get today's team status
    today_str = today.strftime('%Y-%m-%d')
    team_on_leave = conn.execute('''
        SELECT e.name, e.photo_url, lr.day_portion, lr.leave_type
        FROM leave_records lr JOIN employees e ON lr.employee_id = e.id
        WHERE e.reporting_to = ? AND lr.leave_date = ? AND lr.status = 'approved'
    ''', (user['id'], today_str)).fetchall()

    # Upcoming holidays this month
    month_end = today.strftime('%Y-%m-') + str(calendar.monthrange(today.year, today.month)[1])
    upcoming_holidays = conn.execute('''
        SELECT * FROM holidays
        WHERE holiday_date >= ? AND holiday_date <= ?
        ORDER BY holiday_date
    ''', (today.strftime('%Y-%m-%d'), month_end)).fetchall()

    conn.close()

    return render_template('employee_dashboard.html',
                         user=user,
                         available_balance=round(available_balance, 2),
                         days_taken=days_taken,
                         pending_count=pending['count'],
                         monthly_allocation=round(total_allocation / 12, 2),
                         recent_leaves=recent,
                         current_year=current_year,
                         current_month=current_month,
                         holidays=holidays,
                         leave_dates=leave_dates,
                         direct_reports=direct_reports,
                         team_on_leave=team_on_leave,
                         upcoming_holidays=upcoming_holidays,
                         current_month_name=calendar.month_name[current_month])

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = get_user()
    conn = get_db()

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        dob = request.form.get('dob', '').strip()
        address = request.form.get('address', '').strip()
        emergency_contact_name = request.form.get('emergency_contact_name', '').strip()
        emergency_contact_phone = request.form.get('emergency_contact_phone', '').strip()
        emergency_contact_relation = request.form.get('emergency_contact_relation', '').strip()

        conn.execute('''
            UPDATE employees
            SET email = ?, phone = ?, dob = ?, address = ?,
                emergency_contact_name = ?, emergency_contact_phone = ?, emergency_contact_relation = ?
            WHERE id = ?
        ''', (email, phone, dob, address, emergency_contact_name, emergency_contact_phone, emergency_contact_relation, user['id']))
        conn.commit()
        conn.close()

        flash('Profile updated successfully', 'success')
        return redirect(url_for('profile'))

    conn.close()
    return render_template('employee_profile.html', user=user)

@app.route('/apply-leave', methods=['GET', 'POST'])
@login_required
def apply_leave():
    user = get_user()

    if request.method == 'POST':
        leave_type = request.form.get('leave_type', '').strip()
        from_date = request.form.get('from_date', '').strip()
        to_date = request.form.get('to_date', '').strip()
        day_portion = request.form.get('day_portion', 'full').strip()  # for single day
        last_day_portion = request.form.get('last_day_portion', 'full').strip()  # for multi-day last day
        reason = request.form.get('reason', '').strip()

        if not leave_type or not from_date or not reason:
            flash('All fields required', 'error')
            return render_template('apply_leave.html', user=user)

        if leave_type not in ['annual', 'sick', 'casual']:
            flash('Invalid leave type', 'error')
            return render_template('apply_leave.html', user=user)

        # If no to_date, treat as single day
        if not to_date:
            to_date = from_date

        from_dt = datetime.strptime(from_date, '%Y-%m-%d')
        to_dt = datetime.strptime(to_date, '%Y-%m-%d')

        if to_dt < from_dt:
            flash('To date cannot be before from date', 'error')
            return render_template('apply_leave.html', user=user)

        conn = get_db()
        holidays_db = {row['holiday_date'] for row in conn.execute('SELECT holiday_date FROM holidays').fetchall()}

        # Build list of working days in the range
        leave_days = []
        current = from_dt
        while current <= to_dt:
            date_str = current.strftime('%Y-%m-%d')
            if current.weekday() < 5 and date_str not in holidays_db:
                leave_days.append(current)
            current += timedelta(days=1)

        if not leave_days:
            flash('No working days in the selected date range (weekends and holidays are excluded)', 'error')
            conn.close()
            return render_template('apply_leave.html', user=user)

        # Determine day portions for each day
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total_days = 0

        for i, day in enumerate(leave_days):
            date_str = day.strftime('%Y-%m-%d')
            is_single = (len(leave_days) == 1)
            is_last = (i == len(leave_days) - 1 and len(leave_days) > 1)

            if is_single:
                portion = day_portion if day_portion in ['full', 'first_half', 'second_half'] else 'full'
            elif is_last:
                portion = last_day_portion if last_day_portion in ['full', 'first_half', 'second_half'] else 'full'
            else:
                portion = 'full'

            day_val = 0.5 if portion in ['first_half', 'second_half'] else 1.0
            total_days += day_val

            # Check for duplicate
            existing = conn.execute('SELECT id FROM leave_records WHERE employee_id = ? AND leave_date = ? AND status != ?',
                                   (user['id'], date_str, 'rejected')).fetchone()
            if existing:
                flash(f'You already have a leave record for {date_str}', 'error')
                conn.close()
                return render_template('apply_leave.html', user=user)

            conn.execute('''
                INSERT INTO leave_records (employee_id, leave_type, leave_date, days, day_portion, reason, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            ''', (user['id'], leave_type, date_str, day_val, portion, reason, now_str))

        conn.commit()
        conn.close()

        day_label = 'day' if total_days == 1 else 'days'
        flash(f'Leave request submitted for {total_days:.1f} {day_label} ({len(leave_days)} working day{"s" if len(leave_days) > 1 else ""})', 'success')
        return redirect(url_for('dashboard'))

    return render_template('apply_leave.html', user=user)

@app.route('/cancel-leave/<int:leave_id>', methods=['POST'])
@login_required
def cancel_leave(leave_id):
    user = get_user()
    conn = get_db()

    leave = conn.execute('SELECT * FROM leave_records WHERE id = ?', (leave_id,)).fetchone()

    if not leave or leave['employee_id'] != user['id']:
        flash('Leave not found or unauthorized', 'error')
        conn.close()
        return redirect(url_for('dashboard'))

    if leave['status'] != 'pending':
        flash('Only pending leaves can be cancelled', 'error')
        conn.close()
        return redirect(url_for('dashboard'))

    conn.execute('DELETE FROM leave_records WHERE id = ?', (leave_id,))
    conn.commit()
    conn.close()

    flash('Leave request cancelled', 'success')
    return redirect(url_for('dashboard'))

@app.route('/approvals')
@login_required
def employee_approvals():
    """Approvals page for managers (non-admin employees who have direct reports)"""
    user = get_user()
    conn = get_db()

    # Get pending leave requests from direct reports
    pending = conn.execute('''
        SELECT lr.*, e.name, e.emp_code, e.department FROM leave_records lr
        JOIN employees e ON lr.employee_id = e.id
        WHERE lr.status = 'pending' AND e.reporting_to = ?
        ORDER BY lr.created_at DESC
    ''', (user['id'],)).fetchall()

    # Get recently approved/rejected by this manager
    recent = conn.execute('''
        SELECT lr.*, e.name, e.emp_code, e.department FROM leave_records lr
        JOIN employees e ON lr.employee_id = e.id
        WHERE lr.approved_by = ? AND lr.status IN ('approved', 'rejected')
        ORDER BY lr.approved_at DESC LIMIT 10
    ''', (user['id'],)).fetchall()

    # Get direct reports list
    direct_reports = conn.execute('''
        SELECT id, name, emp_code, department, designation FROM employees
        WHERE reporting_to = ? AND is_active = 1 ORDER BY name
    ''', (user['id'],)).fetchall()

    conn.close()

    return render_template('employee_approvals.html',
                         user=user,
                         pending_leaves=pending,
                         recent_actions=recent,
                         direct_reports=direct_reports)

@app.route('/approve/<int:leave_id>', methods=['POST'])
@login_required
def employee_approve_leave(leave_id):
    """Approve leave - for non-admin managers"""
    user = get_user()
    conn = get_db()

    leave = conn.execute('SELECT * FROM leave_records WHERE id = ?', (leave_id,)).fetchone()
    if not leave:
        flash('Leave not found', 'error')
        conn.close()
        return redirect(url_for('employee_approvals'))

    # Verify this user is the reporting manager
    emp = conn.execute('SELECT reporting_to FROM employees WHERE id = ?', (leave['employee_id'],)).fetchone()
    if emp['reporting_to'] != user['id']:
        flash('Not authorized to approve this leave', 'error')
        conn.close()
        return redirect(url_for('employee_approvals'))

    conn.execute('''
        UPDATE leave_records SET status = 'approved', approved_by = ?, approved_at = ? WHERE id = ?
    ''', (user['id'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), leave_id))
    conn.commit()
    conn.close()

    flash('Leave approved', 'success')
    return redirect(url_for('employee_approvals'))

@app.route('/reject/<int:leave_id>', methods=['POST'])
@login_required
def employee_reject_leave(leave_id):
    """Reject leave - for non-admin managers"""
    user = get_user()
    conn = get_db()

    leave = conn.execute('SELECT * FROM leave_records WHERE id = ?', (leave_id,)).fetchone()
    if not leave:
        flash('Leave not found', 'error')
        conn.close()
        return redirect(url_for('employee_approvals'))

    emp = conn.execute('SELECT reporting_to FROM employees WHERE id = ?', (leave['employee_id'],)).fetchone()
    if emp['reporting_to'] != user['id']:
        flash('Not authorized to reject this leave', 'error')
        conn.close()
        return redirect(url_for('employee_approvals'))

    conn.execute('''
        UPDATE leave_records SET status = 'rejected', approved_by = ?, approved_at = ? WHERE id = ?
    ''', (user['id'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), leave_id))
    conn.commit()
    conn.close()

    flash('Leave rejected', 'success')
    return redirect(url_for('employee_approvals'))

@app.route('/calendar')
@login_required
def calendar_view():
    user = get_user()
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))

    # Get calendar days
    month_days = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]

    # Get holidays and leaves
    holidays = get_all_holidays()
    leaves = get_leaves_for_month(user['id'], year, month)
    leave_dates = {}
    for leave in leaves:
        if leave['leave_date'] not in leave_dates:
            leave_dates[leave['leave_date']] = []
        leave_dates[leave['leave_date']].append(leave)

    # Navigation
    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1

    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    today = datetime.now().strftime('%Y-%m-%d')

    return render_template('employee_calendar.html',
                         user=user,
                         year=year,
                         month=month,
                         month_name=month_name,
                         month_days=month_days,
                         holidays=holidays,
                         leave_dates=leave_dates,
                         prev_month=prev_month,
                         prev_year=prev_year,
                         next_month=next_month,
                         next_year=next_year,
                         today=today)

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    user = get_user()
    conn = get_db()

    # Summary stats
    total_employees = conn.execute('SELECT COUNT(*) as count FROM employees WHERE is_admin = 0 AND is_active = 1').fetchone()

    today = datetime.now().strftime('%Y-%m-%d')
    leaves_today = conn.execute('''
        SELECT COUNT(DISTINCT employee_id) as count FROM leave_records
        WHERE leave_date = ? AND status = 'approved'
    ''', (today,)).fetchone()

    pending = conn.execute("SELECT COUNT(*) as count FROM leave_records WHERE status = 'pending'").fetchone()

    # Department-wise count
    departments = conn.execute('''
        SELECT department, COUNT(*) as count FROM employees
        WHERE is_admin = 0 AND is_active = 1
        GROUP BY department ORDER BY department
    ''').fetchall()

    # Who's on leave today
    on_leave_today = conn.execute('''
        SELECT e.name, e.photo_url, e.department, lr.day_portion, lr.leave_type
        FROM leave_records lr JOIN employees e ON lr.employee_id = e.id
        WHERE lr.leave_date = ? AND lr.status = 'approved'
        ORDER BY e.name
    ''', (today,)).fetchall()

    # Recent leave applications
    recent = conn.execute('''
        SELECT lr.*, e.name, e.emp_code, e.photo_url FROM leave_records lr
        JOIN employees e ON lr.employee_id = e.id
        ORDER BY lr.created_at DESC LIMIT 10
    ''').fetchall()

    # Total departments
    total_depts = len(departments)

    # Upcoming holidays this month
    now = datetime.now()
    month_start = now.strftime('%Y-%m-01')
    month_end = now.strftime('%Y-%m-') + str(calendar.monthrange(now.year, now.month)[1])
    upcoming_holidays = conn.execute('''
        SELECT * FROM holidays
        WHERE holiday_date >= ? AND holiday_date <= ?
        ORDER BY holiday_date
    ''', (now.strftime('%Y-%m-%d'), month_end)).fetchall()

    conn.close()

    return render_template('admin_dashboard.html',
                         user=user,
                         total_employees=total_employees['count'],
                         leaves_today=leaves_today['count'],
                         pending_count=pending['count'],
                         departments=departments,
                         total_departments=total_depts,
                         on_leave_today=on_leave_today,
                         recent_leaves=recent,
                         upcoming_holidays=upcoming_holidays,
                         current_month_name=calendar.month_name[now.month],
                         current_year=now.year)

@app.route('/admin/org-chart')
@admin_required
def org_chart():
    user = get_user()
    conn = get_db()
    # Get admin user (top of hierarchy)
    admin_user = conn.execute('SELECT * FROM employees WHERE is_admin = 1 LIMIT 1').fetchone()
    employees = conn.execute('''
        SELECT e.*, m.name as manager_name, m.photo_url as manager_photo
        FROM employees e
        LEFT JOIN employees m ON e.reporting_to = m.id
        WHERE e.is_admin = 0 AND e.is_active = 1
        ORDER BY e.department, e.name
    ''').fetchall()
    departments = conn.execute('''
        SELECT department, COUNT(*) as count FROM employees
        WHERE is_admin = 0 AND is_active = 1
        GROUP BY department ORDER BY department
    ''').fetchall()
    conn.close()
    return render_template('org_chart.html', user=user, admin_user=admin_user, employees=employees, departments=departments)

@app.route('/admin/calendar')
@admin_required
def admin_calendar():
    user = get_user()
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))

    # Get calendar days
    month_days = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]

    # Get all employees
    conn = get_db()
    employees = conn.execute('SELECT id, name FROM employees WHERE is_admin = 0 AND is_active = 1 ORDER BY name').fetchall()

    # Get all leaves for the month
    all_leaves = conn.execute('''
        SELECT lr.*, e.name, e.emp_code FROM leave_records lr
        JOIN employees e ON lr.employee_id = e.id
        WHERE lr.status = 'approved'
        AND strftime('%Y', lr.leave_date) = ? AND strftime('%m', lr.leave_date) = ?
        ORDER BY lr.leave_date, e.name
    ''', (str(year), str(month).zfill(2))).fetchall()

    conn.close()

    # Organize leaves by date
    leave_dates = {}
    for leave in all_leaves:
        if leave['leave_date'] not in leave_dates:
            leave_dates[leave['leave_date']] = []
        leave_dates[leave['leave_date']].append(leave)

    # Get holidays
    holidays = get_all_holidays()

    # Navigation
    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1

    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    today = datetime.now().strftime('%Y-%m-%d')

    return render_template('admin_calendar.html',
                         user=user,
                         year=year,
                         month=month,
                         month_name=month_name,
                         month_days=month_days,
                         holidays=holidays,
                         leave_dates=leave_dates,
                         employees=employees,
                         prev_month=prev_month,
                         prev_year=prev_year,
                         next_month=next_month,
                         next_year=next_year,
                         today=today)

@app.route('/admin/employee/<int:emp_id>')
@admin_required
def admin_employee_detail(emp_id):
    user = get_user()
    conn = get_db()

    employee = conn.execute('SELECT * FROM employees WHERE id = ?', (emp_id,)).fetchone()
    if not employee:
        flash('Employee not found', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    leaves = conn.execute('''
        SELECT * FROM leave_records
        WHERE employee_id = ?
        ORDER BY leave_date DESC
    ''', (emp_id,)).fetchall()

    # Calculate balance
    emp_data = conn.execute('SELECT carry_forward FROM employees WHERE id = ?', (emp_id,)).fetchone()
    carry_forward = emp_data['carry_forward'] if emp_data else 0
    total_allocation = 25 + carry_forward

    approved_leaves = conn.execute('''
        SELECT SUM(days) as total_days FROM leave_records
        WHERE employee_id = ? AND status = 'approved'
    ''', (emp_id,)).fetchone()

    days_taken = approved_leaves['total_days'] if approved_leaves['total_days'] else 0
    available = total_allocation - days_taken

    conn.close()

    return render_template('admin_employee_detail.html',
                         user=user,
                         employee=employee,
                         leaves=leaves,
                         total_allocation=total_allocation,
                         days_taken=days_taken,
                         available_balance=max(0, available))

@app.route('/admin/employee/<int:emp_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_employee_edit(emp_id):
    user = get_user()
    conn = get_db()

    employee = conn.execute('SELECT * FROM employees WHERE id = ?', (emp_id,)).fetchone()
    if not employee:
        flash('Employee not found', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        dob = request.form.get('dob', '').strip()
        address = request.form.get('address', '').strip()
        department = request.form.get('department', '').strip()
        designation = request.form.get('designation', '').strip()
        joining_date = request.form.get('joining_date', '').strip()
        carry_forward = request.form.get('carry_forward', '0').strip()

        try:
            carry_forward = float(carry_forward)
        except ValueError:
            carry_forward = 0

        reporting_to = request.form.get('reporting_to', '').strip()
        reporting_to = int(reporting_to) if reporting_to else None

        emergency_contact_name = request.form.get('emergency_contact_name', '').strip()
        emergency_contact_phone = request.form.get('emergency_contact_phone', '').strip()
        emergency_contact_relation = request.form.get('emergency_contact_relation', '').strip()

        conn.execute('''
            UPDATE employees
            SET name = ?, email = ?, phone = ?, dob = ?, address = ?, department = ?,
                designation = ?, joining_date = ?, carry_forward = ?, reporting_to = ?,
                emergency_contact_name = ?, emergency_contact_phone = ?, emergency_contact_relation = ?
            WHERE id = ?
        ''', (name, email, phone, dob, address, department, designation, joining_date, carry_forward,
              reporting_to, emergency_contact_name, emergency_contact_phone, emergency_contact_relation, emp_id))
        conn.commit()
        conn.close()

        flash('Employee updated successfully', 'success')
        return redirect(url_for('admin_employee_detail', emp_id=emp_id))

    # Get all active employees as potential managers (exclude the employee being edited)
    managers = conn.execute('SELECT id, name, emp_code FROM employees WHERE is_active = 1 AND id != ? ORDER BY name', (emp_id,)).fetchall()

    conn.close()

    departments = ['Sales', 'Operations', 'Marketing', 'Admin', 'Senior Management', 'HR', 'Management']

    return render_template('admin_employee_profile.html',
                         user=user,
                         employee=employee,
                         departments=departments,
                         managers=managers)

@app.route('/admin/employee/<int:emp_id>/upload-photo', methods=['POST'])
@admin_required
def admin_upload_photo(emp_id):
    conn = get_db()
    employee = conn.execute('SELECT * FROM employees WHERE id = ?', (emp_id,)).fetchone()
    if not employee:
        flash('Employee not found', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    if 'photo' not in request.files:
        flash('No photo selected', 'error')
        conn.close()
        return redirect(url_for('admin_employee_edit', emp_id=emp_id))

    file = request.files['photo']
    if file.filename == '':
        flash('No photo selected', 'error')
        conn.close()
        return redirect(url_for('admin_employee_edit', emp_id=emp_id))

    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{employee['emp_code']}.{ext}"
        filepath = os.path.join(PHOTO_FOLDER, filename)

        # Remove old photos with different extensions
        for old_ext in ALLOWED_EXTENSIONS:
            old_path = os.path.join(PHOTO_FOLDER, f"{employee['emp_code']}.{old_ext}")
            if os.path.exists(old_path) and old_path != filepath:
                os.remove(old_path)

        file.save(filepath)

        # Update photo_url in database
        conn.execute('UPDATE employees SET photo_url = ? WHERE id = ?', (filename, emp_id))
        conn.commit()
        conn.close()

        flash('Photo uploaded successfully', 'success')
        return redirect(url_for('admin_employee_edit', emp_id=emp_id))
    else:
        flash('Invalid file type. Allowed: png, jpg, jpeg, gif, webp', 'error')
        conn.close()
        return redirect(url_for('admin_employee_edit', emp_id=emp_id))

@app.route('/admin/add-leave', methods=['GET', 'POST'])
@admin_required
def admin_add_leave():
    user = get_user()
    conn = get_db()

    employees = conn.execute('SELECT id, name FROM employees WHERE is_admin = 0 AND is_active = 1 ORDER BY name').fetchall()

    if request.method == 'POST':
        employee_id = request.form.get('employee_id', '').strip()
        leave_type = request.form.get('leave_type', '').strip()
        leave_date = request.form.get('leave_date', '').strip()
        day_portion = request.form.get('day_portion', 'full').strip()
        reason = request.form.get('reason', '').strip()

        if not employee_id or not leave_type or not leave_date:
            flash('Required fields missing', 'error')
            return render_template('admin_add_leave.html', user=user, employees=employees)

        try:
            employee_id = int(employee_id)
        except ValueError:
            flash('Invalid input', 'error')
            return render_template('admin_add_leave.html', user=user, employees=employees)

        if leave_type not in ['annual', 'sick', 'casual']:
            flash('Invalid leave type', 'error')
            return render_template('admin_add_leave.html', user=user, employees=employees)

        if day_portion not in ['full', 'first_half', 'second_half']:
            flash('Invalid duration', 'error')
            return render_template('admin_add_leave.html', user=user, employees=employees)

        days = 0.5 if day_portion in ['first_half', 'second_half'] else 1.0

        conn.execute('''
            INSERT INTO leave_records (employee_id, leave_type, leave_date, days, day_portion, reason, status, approved_by, approved_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'approved', ?, ?, ?)
        ''', (employee_id, leave_type, leave_date, days, day_portion, reason or '', user['id'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()

        flash('Leave added successfully', 'success')
        return redirect(url_for('admin_dashboard'))

    conn.close()

    return render_template('admin_add_leave.html', user=user, employees=employees)

@app.route('/admin/bulk-leave', methods=['GET', 'POST'])
@admin_required
def admin_bulk_leave():
    user = get_user()
    conn = get_db()

    employees = conn.execute('SELECT id, name FROM employees WHERE is_admin = 0 AND is_active = 1 ORDER BY name').fetchall()

    if request.method == 'POST':
        department = request.form.get('department', '').strip()
        leave_type = request.form.get('leave_type', '').strip()
        leave_date = request.form.get('leave_date', '').strip()
        days = request.form.get('days', '').strip()
        reason = request.form.get('reason', '').strip()

        if not department or not leave_type or not leave_date or not days:
            flash('All fields required', 'error')
            return render_template('admin_bulk_leave.html', user=user, employees=employees)

        try:
            days = float(days)
            if days <= 0:
                flash('Days must be positive', 'error')
                return render_template('admin_bulk_leave.html', user=user, employees=employees)
        except ValueError:
            flash('Invalid days value', 'error')
            return render_template('admin_bulk_leave.html', user=user, employees=employees)

        # Get all employees in department
        dept_employees = conn.execute('SELECT id FROM employees WHERE department = ? AND is_admin = 0 AND is_active = 1', (department,)).fetchall()

        count = 0
        for emp in dept_employees:
            conn.execute('''
                INSERT INTO leave_records (employee_id, leave_type, leave_date, days, reason, status, approved_by, approved_at, created_at)
                VALUES (?, ?, ?, ?, ?, 'approved', ?, ?, ?)
            ''', (emp['id'], leave_type, leave_date, days, reason or '', user['id'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            count += 1

        conn.commit()
        conn.close()

        flash(f'Added leave for {count} employees', 'success')
        return redirect(url_for('admin_dashboard'))

    conn.close()

    departments = ['Sales', 'Operations', 'Marketing', 'Admin', 'Senior Management', 'HR', 'Management']

    return render_template('admin_bulk_leave.html', user=user, employees=employees, departments=departments)

@app.route('/admin/manage-employees', methods=['GET', 'POST'])
@admin_required
def manage_employees():
    user = get_user()
    conn = get_db()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        emp_code = request.form.get('emp_code', '').strip()
        email = request.form.get('email', '').strip()
        department = request.form.get('department', '').strip()

        if not name or not emp_code or not department:
            flash('Required fields missing', 'error')
            return redirect(url_for('manage_employees'))

        # Check if emp_code already exists
        existing = conn.execute('SELECT id FROM employees WHERE emp_code = ?', (emp_code,)).fetchone()
        if existing:
            flash('Employee code already exists', 'error')
            return redirect(url_for('manage_employees'))

        conn.execute('''
            INSERT INTO employees (name, emp_code, password, department, is_active, joining_date, created_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
        ''', (name, emp_code, hash_password(emp_code), department, datetime.now().strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()

        flash('Employee added successfully', 'success')
        return redirect(url_for('manage_employees'))

    employees = conn.execute('SELECT * FROM employees WHERE is_admin = 0 ORDER BY department, name').fetchall()

    # Group employees by department
    dept_employees = {}
    for emp in employees:
        dept = emp['department'] or 'Unassigned'
        if dept not in dept_employees:
            dept_employees[dept] = []
        dept_employees[dept].append(emp)

    conn.close()

    departments = ['Sales', 'Operations', 'Marketing', 'Admin', 'Senior Management', 'HR', 'Management']

    return render_template('manage_employees.html',
                         user=user,
                         employees=employees,
                         dept_employees=dept_employees,
                         departments=departments)

@app.route('/admin/delete-employee/<int:emp_id>', methods=['POST'])
@admin_required
def delete_employee(emp_id):
    conn = get_db()

    employee = conn.execute('SELECT * FROM employees WHERE id = ?', (emp_id,)).fetchone()
    if not employee:
        flash('Employee not found', 'error')
        conn.close()
        return redirect(url_for('manage_employees'))

    # Delete all leave records for this employee
    conn.execute('DELETE FROM leave_records WHERE employee_id = ?', (emp_id,))

    # Delete employee
    conn.execute('DELETE FROM employees WHERE id = ?', (emp_id,))
    conn.commit()
    conn.close()

    flash(f'Employee {employee["name"]} and all their records deleted', 'success')
    return redirect(url_for('manage_employees'))

@app.route('/admin/delete-leave/<int:leave_id>', methods=['POST'])
@admin_required
def delete_leave(leave_id):
    conn = get_db()

    leave = conn.execute('SELECT * FROM leave_records WHERE id = ?', (leave_id,)).fetchone()
    if not leave:
        flash('Leave not found', 'error')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    conn.execute('DELETE FROM leave_records WHERE id = ?', (leave_id,))
    conn.commit()
    conn.close()

    flash('Leave record deleted', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route('/admin/monthly-report')
@admin_required
def admin_monthly_report():
    user = get_user()
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))

    conn = get_db()
    employees = conn.execute('SELECT * FROM employees WHERE is_admin = 0 AND is_active = 1 ORDER BY name').fetchall()

    report_data = []
    for emp in employees:
        carry_forward = emp['carry_forward']
        total_allocation = 25 + carry_forward
        monthly_allocation = total_allocation / 12

        # Get leaves taken in this month
        month_leaves = conn.execute('''
            SELECT SUM(days) as total_days FROM leave_records
            WHERE employee_id = ? AND status = 'approved'
            AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
        ''', (emp['id'], str(year), str(month).zfill(2))).fetchone()

        days_taken_month = month_leaves['total_days'] if month_leaves['total_days'] else 0

        # Get balance at start of month
        balance_start = get_available_balance(emp['id'], year, month)
        balance_available = balance_start + monthly_allocation

        # Calculate deduction
        deduction = max(0, days_taken_month - balance_available)

        report_data.append({
            'name': emp['name'],
            'emp_code': emp['emp_code'],
            'department': emp['department'],
            'monthly_allocation': round(monthly_allocation, 2),
            'balance_start': round(balance_start, 2),
            'balance_available': round(balance_available, 2),
            'days_taken': round(days_taken_month, 2),
            'deduction': round(deduction, 2)
        })

    conn.close()

    month_name = calendar.month_name[month]

    return render_template('admin_monthly_report.html',
                         user=user,
                         year=year,
                         month=month,
                         month_name=month_name,
                         report_data=report_data)

@app.route('/admin/monthly-report/download')
@admin_required
def admin_monthly_report_download():
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))
    file_format = request.args.get('format', 'xlsx')

    conn = get_db()
    employees = conn.execute('SELECT * FROM employees WHERE is_admin = 0 AND is_active = 1 ORDER BY name').fetchall()

    if file_format == 'xlsx':
        wb = Workbook()
        ws = wb.active
        ws.title = f"Leave Report {month}-{year}"

        # Headers
        headers = ['Name', 'Employee Code', 'Department', 'Monthly Allocation', 'Balance Start', 'Balance Available', 'Days Taken', 'Salary Deduction']
        ws.append(headers)

        # Style headers
        header_fill = PatternFill(start_color='1a56db', end_color='1a56db', fill_type='solid')
        header_font = Font(bold=True, color='FFFFFF')

        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')

        # Data
        for emp in employees:
            carry_forward = emp['carry_forward']
            total_allocation = 25 + carry_forward
            monthly_allocation = total_allocation / 12

            month_leaves = conn.execute('''
                SELECT SUM(days) as total_days FROM leave_records
                WHERE employee_id = ? AND status = 'approved'
                AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
            ''', (emp['id'], str(year), str(month).zfill(2))).fetchone()

            days_taken_month = month_leaves['total_days'] if month_leaves['total_days'] else 0
            balance_start = get_available_balance(emp['id'], year, month)
            balance_available = balance_start + monthly_allocation
            deduction = max(0, days_taken_month - balance_available)

            ws.append([
                emp['name'],
                emp['emp_code'],
                emp['department'],
                round(monthly_allocation, 2),
                round(balance_start, 2),
                round(balance_available, 2),
                round(days_taken_month, 2),
                round(deduction, 2)
            ])

        # Adjust column widths
        ws.column_dimensions['A'].width = 20
        ws.column_dimensions['B'].width = 15
        ws.column_dimensions['C'].width = 18
        ws.column_dimensions['D'].width = 16
        ws.column_dimensions['E'].width = 14
        ws.column_dimensions['F'].width = 17
        ws.column_dimensions['G'].width = 12
        ws.column_dimensions['H'].width = 17

        output = BytesIO()
        wb.save(output)
        output.seek(0)

        conn.close()

        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'Leave_Report_{month}_{year}.xlsx'
        )

    conn.close()
    flash('Invalid format', 'error')
    return redirect(url_for('admin_monthly_report', year=year, month=month))

@app.route('/admin/holidays', methods=['GET', 'POST'])
@admin_required
def admin_holidays():
    user = get_user()
    conn = get_db()

    if request.method == 'POST':
        holiday_date = request.form.get('holiday_date', '').strip()
        name = request.form.get('name', '').strip()
        holiday_type = request.form.get('holiday_type', '').strip()

        if not holiday_date or not name:
            flash('Required fields missing', 'error')
            return redirect(url_for('admin_holidays'))

        # Check if holiday already exists
        existing = conn.execute('SELECT id FROM holidays WHERE holiday_date = ?', (holiday_date,)).fetchone()
        if existing:
            flash('Holiday already exists for this date', 'error')
            return redirect(url_for('admin_holidays'))

        conn.execute('''
            INSERT INTO holidays (holiday_date, name, holiday_type, created_at)
            VALUES (?, ?, ?, ?)
        ''', (holiday_date, name, holiday_type, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()

        flash('Holiday added successfully', 'success')
        return redirect(url_for('admin_holidays'))

    holidays = conn.execute('SELECT * FROM holidays ORDER BY holiday_date').fetchall()
    conn.close()

    return render_template('admin_holidays.html', user=user, holidays=holidays)

@app.route('/admin/delete-holiday/<int:holiday_id>', methods=['POST'])
@admin_required
def delete_holiday(holiday_id):
    conn = get_db()

    conn.execute('DELETE FROM holidays WHERE id = ?', (holiday_id,))
    conn.commit()
    conn.close()

    flash('Holiday deleted', 'success')
    return redirect(url_for('admin_holidays'))

@app.route('/admin/pending-approvals')
@login_required
def pending_approvals():
    user = get_user()
    conn = get_db()

    # If admin, show all pending
    if user['is_admin']:
        pending = conn.execute('''
            SELECT lr.*, e.name, e.emp_code FROM leave_records lr
            JOIN employees e ON lr.employee_id = e.id
            WHERE lr.status = 'pending'
            ORDER BY lr.created_at DESC
        ''').fetchall()
    else:
        # If manager, show pending from direct reports
        pending = conn.execute('''
            SELECT lr.*, e.name, e.emp_code FROM leave_records lr
            JOIN employees e ON lr.employee_id = e.id
            WHERE lr.status = 'pending' AND e.reporting_to = ?
            ORDER BY lr.created_at DESC
        ''', (user['id'],)).fetchall()

    conn.close()

    return render_template('pending_approvals.html', user=user, pending_leaves=pending)

@app.route('/admin/approve-leave/<int:leave_id>', methods=['POST'])
@login_required
def approve_leave(leave_id):
    user = get_user()
    conn = get_db()

    leave = conn.execute('SELECT * FROM leave_records WHERE id = ?', (leave_id,)).fetchone()
    if not leave:
        flash('Leave not found', 'error')
        conn.close()
        return redirect(url_for('pending_approvals'))

    # Check authorization
    if not user['is_admin']:
        emp = conn.execute('SELECT reporting_to FROM employees WHERE id = ?', (leave['employee_id'],)).fetchone()
        if emp['reporting_to'] != user['id']:
            flash('Not authorized to approve this leave', 'error')
            conn.close()
            return redirect(url_for('pending_approvals'))

    conn.execute('''
        UPDATE leave_records
        SET status = 'approved', approved_by = ?, approved_at = ?
        WHERE id = ?
    ''', (user['id'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), leave_id))
    conn.commit()
    conn.close()

    flash('Leave approved', 'success')
    return redirect(request.referrer or url_for('pending_approvals'))

@app.route('/admin/reject-leave/<int:leave_id>', methods=['POST'])
@login_required
def reject_leave(leave_id):
    user = get_user()
    conn = get_db()

    leave = conn.execute('SELECT * FROM leave_records WHERE id = ?', (leave_id,)).fetchone()
    if not leave:
        flash('Leave not found', 'error')
        conn.close()
        return redirect(url_for('pending_approvals'))

    # Check authorization
    if not user['is_admin']:
        emp = conn.execute('SELECT reporting_to FROM employees WHERE id = ?', (leave['employee_id'],)).fetchone()
        if emp['reporting_to'] != user['id']:
            flash('Not authorized to reject this leave', 'error')
            conn.close()
            return redirect(url_for('pending_approvals'))

    conn.execute('''
        UPDATE leave_records
        SET status = 'rejected', approved_by = ?, approved_at = ?
        WHERE id = ?
    ''', (user['id'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), leave_id))
    conn.commit()
    conn.close()

    flash('Leave rejected', 'success')
    return redirect(request.referrer or url_for('pending_approvals'))

@app.route('/api/balance')
@login_required
def api_balance():
    emp_id = request.args.get('emp_id', type=int)
    if not emp_id:
        return jsonify({'error': 'emp_id required'}), 400

    user = get_user()
    if not user['is_admin'] and user['id'] != emp_id:
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_db()
    emp = conn.execute('SELECT carry_forward FROM employees WHERE id = ?', (emp_id,)).fetchone()

    if not emp:
        conn.close()
        return jsonify({'error': 'Employee not found'}), 404

    carry_forward = emp['carry_forward']
    total_allocation = 25 + carry_forward

    approved_leaves = conn.execute('''
        SELECT SUM(days) as total_days FROM leave_records
        WHERE employee_id = ? AND status = 'approved'
    ''', (emp_id,)).fetchone()

    days_taken = approved_leaves['total_days'] if approved_leaves['total_days'] else 0
    available = total_allocation - days_taken

    conn.close()

    return jsonify({
        'total_allocation': total_allocation,
        'days_taken': days_taken,
        'available_balance': max(0, available),
        'monthly_allocation': round(total_allocation / 12, 2)
    })

@app.route('/api/employee-name')
@login_required
def api_employee_name():
    emp_id = request.args.get('emp_id', type=int)
    if not emp_id:
        return jsonify({'error': 'emp_id required'}), 400

    conn = get_db()
    emp = conn.execute('SELECT name FROM employees WHERE id = ?', (emp_id,)).fetchone()
    conn.close()

    if not emp:
        return jsonify({'error': 'Employee not found'}), 404

    return jsonify({'name': emp['name']})

if __name__ == '__main__':
    PORT = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=PORT, debug=False)
