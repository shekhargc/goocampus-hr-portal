import os
import hashlib
import logging
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_file
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import calendar
from db import get_db
from email_utils import send_birthday_reminder, send_anniversary_reminder, send_announcement_email, send_happy_birthday_email

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

# Management codes that can post announcements (along with admin)
MANAGEMENT_CODES = ['GC001', 'GC002', 'GC003']

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
        user = get_user()
        if not has_module_access(user, 'sales'):
            flash('Sales module access required', 'error')
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
    """Make is_manager, pending_team_count, and has_sales_access available in all templates"""
    if 'user_id' in session:
        user_id = session['user_id']
        user = get_user()
        mgr = is_manager(user_id)
        pending_team = get_pending_team_count(user_id) if mgr else 0
        sales_access = has_module_access(user, 'sales') if user else False
        return {'is_manager': mgr, 'pending_team_count': pending_team, 'has_sales_access': sales_access}
    return {'is_manager': False, 'pending_team_count': 0, 'has_sales_access': False}

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
            # Check if password is still the default (first name lowercase)
            default_pw = user['name'].split()[0].lower()
            if password == default_pw:
                session['show_welcome'] = True
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

    # Days taken this FY - with type breakdown
    leaves = conn.execute('''
        SELECT SUM(days) as total_days,
               SUM(CASE WHEN leave_type = 'annual' THEN days ELSE 0 END) as annual_taken,
               SUM(CASE WHEN leave_type = 'sick' THEN days ELSE 0 END) as sick_taken,
               SUM(CASE WHEN leave_type = 'casual' THEN days ELSE 0 END) as casual_taken
        FROM leave_records
        WHERE employee_id = ? AND status = 'approved'
        AND ((strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) >= '04')
             OR (strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) < '04'))
    ''', (user['id'], str(fy_year), str(fy_year + 1))).fetchone()

    days_taken = leaves['total_days'] if leaves['total_days'] else 0
    annual_taken = leaves['annual_taken'] if leaves['annual_taken'] else 0
    sick_taken = leaves['sick_taken'] if leaves['sick_taken'] else 0
    casual_taken = leaves['casual_taken'] if leaves['casual_taken'] else 0
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

    # Upcoming holidays - current month + next month
    next_month = today.month + 1
    next_month_year = today.year
    if next_month > 12:
        next_month = 1
        next_month_year += 1
    next_month_end = '{}-{}-{}'.format(next_month_year, str(next_month).zfill(2), calendar.monthrange(next_month_year, next_month)[1])
    next_month_name = calendar.month_name[next_month]

    upcoming_holidays = conn.execute('''
        SELECT * FROM holidays
        WHERE holiday_date >= ? AND holiday_date <= ?
        ORDER BY holiday_date
    ''', (today.strftime('%Y-%m-%d'), next_month_end)).fetchall()

    # Birthdays this month (employees who have DOB set, matching current month)
    current_mm = str(current_month).zfill(2)
    birthdays_this_month = conn.execute('''
        SELECT name, dob, photo_url, department FROM employees
        WHERE is_active = 1 AND emp_code != 'admin' AND dob IS NOT NULL AND dob != ''
        AND strftime('%m', dob) = ?
        ORDER BY strftime('%d', dob)
    ''', (current_mm,)).fetchall()

    # Work anniversaries this month (employees with joining_date matching current month, excluding current year joins)
    anniversaries_this_month = conn.execute('''
        SELECT name, joining_date, photo_url, department FROM employees
        WHERE is_active = 1 AND emp_code != 'admin' AND joining_date IS NOT NULL AND joining_date != ''
        AND strftime('%m', joining_date) = ?
        AND strftime('%Y', joining_date) != ?
        ORDER BY strftime('%d', joining_date)
    ''', (current_mm, str(current_year))).fetchall()

    # Recent announcements (last 5 active)
    announcements = conn.execute('''
        SELECT a.*, e.name as posted_by_name FROM announcements a
        JOIN employees e ON a.posted_by = e.id
        WHERE a.is_active = 1
        ORDER BY a.created_at DESC LIMIT 5
    ''', ()).fetchall()

    conn.close()

    return render_template('employee_dashboard.html',
                         user=user,
                         total_allocation=total_allocation,
                         available_balance=round(available_balance, 2),
                         days_taken=days_taken,
                         annual_taken=annual_taken,
                         sick_taken=sick_taken,
                         casual_taken=casual_taken,
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
                         current_month_name=calendar.month_name[current_month],
                         next_month_name=next_month_name,
                         carry_forward=carry_forward,
                         current_month_available=round(calculate_monthly_balance(user['id'], fy_year, current_month), 2),
                         birthdays_this_month=birthdays_this_month,
                         anniversaries_this_month=anniversaries_this_month,
                         announcements=announcements,
                         can_announce=can_post_announcements(user))

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

        # Handle lock-once fields: designation and joining_date
        # Only update if the field is currently empty (not yet set)
        designation = request.form.get('designation', '').strip()
        joining_date = request.form.get('joining_date', '').strip()

        update_fields = '''
            UPDATE employees
            SET email = ?, phone = ?, dob = ?, address = ?,
                emergency_contact_name = ?, emergency_contact_phone = ?, emergency_contact_relation = ?
        '''
        params = [email, phone, dob, address, emergency_contact_name, emergency_contact_phone, emergency_contact_relation]

        # Only allow setting designation if not already set
        if designation and not user.get('designation'):
            update_fields += ', designation = ?'
            params.append(designation)

        # Only allow setting joining_date if not already set
        if joining_date and not user.get('joining_date'):
            update_fields += ', joining_date = ?'
            params.append(joining_date)

        update_fields += ' WHERE id = ?'
        params.append(user['id'])

        conn.execute(update_fields, tuple(params))
        conn.commit()
        conn.close()

        flash('Profile updated successfully', 'success')
        return redirect(url_for('profile'))

    # Get reporting manager name
    reporting_manager = None
    if user.get('reporting_to'):
        mgr = conn.execute('SELECT name FROM employees WHERE id = ?', (user['reporting_to'],)).fetchone()
        if mgr:
            reporting_manager = mgr['name']

    conn.close()
    return render_template('employee_profile.html', user=user, reporting_manager=reporting_manager)


@app.route('/profile/upload-photo', methods=['POST'])
@login_required
def profile_upload_photo():
    """Allow employees to upload their own profile photo."""
    user = get_user()

    if 'photo' not in request.files:
        flash('No photo selected', 'error')
        return redirect(url_for('profile'))

    file = request.files['photo']
    if file.filename == '':
        flash('No photo selected', 'error')
        return redirect(url_for('profile'))

    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{user['emp_code']}.{ext}"
        filepath = os.path.join(PHOTO_FOLDER, filename)

        # Remove old photos with different extensions
        for old_ext in ALLOWED_EXTENSIONS:
            old_path = os.path.join(PHOTO_FOLDER, f"{user['emp_code']}.{old_ext}")
            if os.path.exists(old_path) and old_path != filepath:
                os.remove(old_path)

        file.save(filepath)

        # Update photo_url in database
        conn = get_db()
        conn.execute('UPDATE employees SET photo_url = ? WHERE id = ?', (filename, user['id']))
        conn.commit()
        conn.close()

        flash('Photo updated successfully', 'success')
    else:
        flash('Invalid file type. Allowed: png, jpg, jpeg, gif, webp', 'error')

    return redirect(url_for('profile'))

@app.route('/apply-leave', methods=['GET', 'POST'])
@login_required
def apply_leave():
    user = get_user()

    # Admin control account cannot apply for personal leave
    if user['emp_code'] == 'admin':
        flash('Admin account cannot apply for leave. Use "Add Leave (Employee)" to apply on behalf of an employee.', 'error')
        return redirect(url_for('admin_dashboard'))

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

        conn2 = get_db()
        # Notify the reporting manager
        reporting_mgr = conn2.execute('SELECT reporting_to FROM employees WHERE id = ?', (user['id'],)).fetchone()
        if reporting_mgr and reporting_mgr['reporting_to']:
            try:
                create_notification(conn2, 'leave_request',
                    f"Leave Request from {user['name']}",
                    f"{user['name']} has applied for {total_days:.1f} day(s) of {leave_type} leave ({from_date} to {to_date})",
                    target_user_id=reporting_mgr['reporting_to'], target_role='manager')
                conn2.commit()
            except Exception as e:
                logging.error(f"Failed to create leave notification for manager: {e}")

        # Notify admin
        admins = conn2.execute('SELECT id FROM employees WHERE is_admin = 1 AND is_active = 1', ()).fetchall()
        for adm in admins:
            if not reporting_mgr or adm['id'] != reporting_mgr.get('reporting_to'):
                try:
                    create_notification(conn2, 'leave_request',
                        f"Leave Request from {user['name']}",
                        f"{user['name']} has applied for {total_days:.1f} day(s) of {leave_type} leave ({from_date} to {to_date})",
                        target_user_id=adm['id'], target_role='admin')
                    conn2.commit()
                except Exception as e:
                    logging.error(f"Failed to create leave notification for admin: {e}")
        conn2.close()

        day_label = 'day' if total_days == 1 else 'days'
        flash(f'Leave request submitted for {total_days:.1f} {day_label} ({len(leave_days)} working day{"s" if len(leave_days) > 1 else ""})', 'success')
        return redirect(url_for('dashboard'))

    return render_template('apply_leave.html', user=user)


@app.route('/apply-late-leave', methods=['GET', 'POST'])
@login_required
def apply_late_leave():
    """Late leave application — for past dates up to 15 days ago"""
    user = get_user()

    if user['emp_code'] == 'admin':
        flash('Admin account cannot apply for leave.', 'error')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        leave_type = request.form.get('leave_type', '').strip()
        from_date = request.form.get('from_date', '').strip()
        to_date = request.form.get('to_date', '').strip()
        day_portion = request.form.get('day_portion', 'full').strip()
        last_day_portion = request.form.get('last_day_portion', 'full').strip()
        reason = request.form.get('reason', '').strip()
        late_reason = request.form.get('late_reason', '').strip()

        if not leave_type or not from_date or not reason or not late_reason:
            flash('All fields are required, including reason for late application', 'error')
            conn = get_db()
            late_count = conn.execute('SELECT late_leave_count FROM employees WHERE id = ?', (user['id'],)).fetchone()
            conn.close()
            return render_template('apply_late_leave.html', user=user,
                                 late_leave_count=late_count['late_leave_count'] if late_count else 0)

        if leave_type not in ['annual', 'sick', 'casual']:
            flash('Invalid leave type', 'error')
            conn = get_db()
            late_count = conn.execute('SELECT late_leave_count FROM employees WHERE id = ?', (user['id'],)).fetchone()
            conn.close()
            return render_template('apply_late_leave.html', user=user,
                                 late_leave_count=late_count['late_leave_count'] if late_count else 0)

        if not to_date:
            to_date = from_date

        from_dt = datetime.strptime(from_date, '%Y-%m-%d')
        to_dt = datetime.strptime(to_date, '%Y-%m-%d')
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        min_date = today - timedelta(days=15)

        # Validate: dates must be in the past
        if from_dt >= today:
            flash('Late leave is for past dates only. Use regular leave application for today or future dates.', 'error')
            return redirect(url_for('apply_late_leave'))

        # Validate: not older than 15 days
        if from_dt < min_date:
            flash('Cannot apply late leave for dates older than 15 days', 'error')
            return redirect(url_for('apply_late_leave'))

        if to_dt < from_dt:
            flash('To date cannot be before from date', 'error')
            return redirect(url_for('apply_late_leave'))

        if to_dt >= today:
            flash('To date must also be a past date for late leave', 'error')
            return redirect(url_for('apply_late_leave'))

        conn = get_db()
        holidays_db = {row['holiday_date'] for row in conn.execute('SELECT holiday_date FROM holidays').fetchall()}

        # Build list of working days
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
            return redirect(url_for('apply_late_leave'))

        # Insert leave records with is_late = 1
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        total_days = 0
        combined_reason = f"{reason}\n\n[Late Application Reason]: {late_reason}"

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
                return redirect(url_for('apply_late_leave'))

            conn.execute('''
                INSERT INTO leave_records (employee_id, leave_type, leave_date, days, day_portion, reason, status, is_late, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', 1, ?)
            ''', (user['id'], leave_type, date_str, day_val, portion, combined_reason, now_str))

        # Increment late leave count
        conn.execute('UPDATE employees SET late_leave_count = late_leave_count + 1 WHERE id = ?', (user['id'],))
        conn.commit()
        conn.close()

        # Notify reporting manager with LATE flag
        conn2 = get_db()
        reporting_mgr = conn2.execute('SELECT reporting_to FROM employees WHERE id = ?', (user['id'],)).fetchone()
        if reporting_mgr and reporting_mgr['reporting_to']:
            try:
                create_notification(conn2, 'leave_request',
                    f"⚠️ Late Leave Request from {user['name']}",
                    f"{user['name']} has applied LATE for {total_days:.1f} day(s) of {leave_type} leave ({from_date} to {to_date}). Late reason: {late_reason}",
                    target_user_id=reporting_mgr['reporting_to'], target_role='manager')
                conn2.commit()
            except Exception as e:
                logging.error(f"Failed to create late leave notification for manager: {e}")

        # Notify admin
        admins = conn2.execute('SELECT id FROM employees WHERE is_admin = 1 AND is_active = 1', ()).fetchall()
        for adm in admins:
            if not reporting_mgr or adm['id'] != reporting_mgr.get('reporting_to'):
                try:
                    create_notification(conn2, 'leave_request',
                        f"⚠️ Late Leave Request from {user['name']}",
                        f"{user['name']} has applied LATE for {total_days:.1f} day(s) of {leave_type} leave ({from_date} to {to_date}). Late reason: {late_reason}",
                        target_user_id=adm['id'], target_role='admin')
                    conn2.commit()
                except Exception as e:
                    logging.error(f"Failed to create late leave notification for admin: {e}")
        conn2.close()

        day_label = 'day' if total_days == 1 else 'days'
        flash(f'Late leave request submitted for {total_days:.1f} {day_label}. Your late leave count has been updated.', 'success')
        return redirect(url_for('dashboard'))

    # GET request
    conn = get_db()
    late_count = conn.execute('SELECT late_leave_count FROM employees WHERE id = ?', (user['id'],)).fetchone()
    conn.close()
    return render_template('apply_late_leave.html', user=user,
                         late_leave_count=late_count['late_leave_count'] if late_count else 0)


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


@app.route('/retrieve-leave/<int:leave_id>', methods=['POST'])
@login_required
def retrieve_leave(leave_id):
    """Retrieve (recall) a leave — works for any status, before leave date."""
    user = get_user()
    conn = get_db()

    leave = conn.execute('SELECT * FROM leave_records WHERE id = ?', (leave_id,)).fetchone()
    if not leave or leave['employee_id'] != user['id']:
        flash('Leave not found or unauthorized', 'error')
        conn.close()
        return redirect(url_for('my_leave_report'))

    if leave['status'] == 'retrieved':
        flash('This leave has already been retrieved', 'error')
        conn.close()
        return redirect(url_for('my_leave_report'))

    # Check leave date is today or in the future
    try:
        leave_dt = datetime.strptime(leave['leave_date'], '%Y-%m-%d')
    except (ValueError, TypeError):
        leave_dt = leave['leave_date'] if hasattr(leave['leave_date'], 'strftime') else datetime.now()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    retrieve_reason = request.form.get('retrieve_reason', '').strip()
    if not retrieve_reason:
        flash('Please provide a reason for retrieving this leave', 'error')
        conn.close()
        return redirect(url_for('my_leave_report'))

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute('''
        UPDATE leave_records
        SET status = 'retrieved', modification_reason = ?, approved_at = ?
        WHERE id = ?
    ''', (retrieve_reason, now_str, leave_id))
    conn.commit()
    conn.close()

    flash('Leave retrieved successfully', 'success')
    return redirect(url_for('my_leave_report'))


@app.route('/modify-leave/<int:leave_id>', methods=['GET', 'POST'])
@login_required
def modify_leave(leave_id):
    """Modify an existing leave — creates new record, marks old as modified, goes to pending."""
    user = get_user()
    conn = get_db()

    leave = conn.execute('SELECT * FROM leave_records WHERE id = ?', (leave_id,)).fetchone()
    if not leave or leave['employee_id'] != user['id']:
        flash('Leave not found or unauthorized', 'error')
        conn.close()
        return redirect(url_for('my_leave_report'))

    if leave['status'] in ('retrieved', 'modified'):
        flash('This leave has already been retrieved or modified', 'error')
        conn.close()
        return redirect(url_for('my_leave_report'))

    if request.method == 'POST':
        new_leave_type = request.form.get('leave_type', '').strip()
        new_from_date = request.form.get('from_date', '').strip()
        new_to_date = request.form.get('to_date', '').strip() or new_from_date
        new_day_portion = request.form.get('day_portion', 'full').strip()
        new_last_day_portion = request.form.get('last_day_portion', 'full').strip()
        new_reason = request.form.get('reason', '').strip()
        mod_reason = request.form.get('modification_reason', '').strip()

        if not all([new_leave_type, new_from_date, new_reason, mod_reason]):
            flash('All fields including modification reason are required', 'error')
            conn.close()
            return redirect(url_for('modify_leave', leave_id=leave_id))

        try:
            from_dt = datetime.strptime(new_from_date, '%Y-%m-%d')
            to_dt = datetime.strptime(new_to_date, '%Y-%m-%d')
        except ValueError:
            flash('Invalid date format', 'error')
            conn.close()
            return redirect(url_for('modify_leave', leave_id=leave_id))

        if to_dt < from_dt:
            flash('To date cannot be before from date', 'error')
            conn.close()
            return redirect(url_for('modify_leave', leave_id=leave_id))

        # Check holidays
        holidays_db = {row['holiday_date'] for row in conn.execute('SELECT holiday_date FROM holidays').fetchall()}

        # Determine if this is a late leave modification
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        is_late = 1 if leave.get('is_late') else 0

        # Build working days
        leave_days = []
        current = from_dt
        while current <= to_dt:
            date_str = current.strftime('%Y-%m-%d')
            if current.weekday() < 5 and date_str not in holidays_db:
                leave_days.append(current)
            current += timedelta(days=1)

        if not leave_days:
            flash('No working days in the selected date range', 'error')
            conn.close()
            return redirect(url_for('modify_leave', leave_id=leave_id))

        # Mark original leave as 'modified'
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        original_reason = leave['reason'] or ''
        conn.execute('''
            UPDATE leave_records SET status = 'modified', modification_reason = ? WHERE id = ?
        ''', (mod_reason, leave_id))

        # Insert new leave records (one per working day)
        total_days = 0
        for i, day in enumerate(leave_days):
            date_str = day.strftime('%Y-%m-%d')
            is_single = (len(leave_days) == 1)
            is_first = (i == 0)
            is_last = (i == len(leave_days) - 1)

            if is_single:
                portion = new_day_portion
            elif is_first:
                portion = new_day_portion
            elif is_last:
                portion = new_last_day_portion
            else:
                portion = 'full'

            day_val = 0.5 if portion in ('first_half', 'second_half') else 1.0
            total_days += day_val

            conn.execute('''
                INSERT INTO leave_records (employee_id, leave_type, leave_date, days, day_portion,
                    reason, status, is_late, original_id, original_reason, modification_reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            ''', (user['id'], new_leave_type, date_str, day_val, portion,
                  new_reason, is_late, leave_id, original_reason, mod_reason, now_str))

        conn.commit()
        conn.close()

        flash(f'Leave modified ({total_days:.1f} day(s)). Re-approval is required.', 'success')
        return redirect(url_for('my_leave_report'))

    # GET: show modification form
    conn.close()
    today_str = datetime.now().strftime('%Y-%m-%d')
    return render_template('modify_leave.html', user=user, leave=leave, today=today_str)


# ─── Edit Leave (in-place update for future leaves) ───
@app.route('/edit-leave/<int:leave_id>', methods=['GET', 'POST'])
@login_required
def edit_leave(leave_id):
    """Edit a leave record in-place. Allowed for future-dated leaves only.
       Authorised users: the applicant, their reporting manager, or admin."""
    user = get_user()
    conn = get_db()

    leave = conn.execute('''
        SELECT lr.*, e.name, e.emp_code, e.reporting_to
        FROM leave_records lr JOIN employees e ON lr.employee_id = e.id
        WHERE lr.id = ?
    ''', (leave_id,)).fetchone()

    if not leave:
        flash('Leave not found', 'error')
        conn.close()
        return redirect(request.referrer or url_for('dashboard'))

    # Authorization: applicant, reporting manager, or admin
    is_owner = (leave['employee_id'] == user['id'])
    is_reporting = (leave['reporting_to'] == user['id'])
    is_admin_user = bool(user.get('is_admin'))
    if not (is_owner or is_reporting or is_admin_user):
        flash('You are not authorised to edit this leave', 'error')
        conn.close()
        return redirect(request.referrer or url_for('dashboard'))

    # Only future leaves can be edited
    today = datetime.now().strftime('%Y-%m-%d')
    if leave['leave_date'] < today:
        flash('Past leaves cannot be edited', 'error')
        conn.close()
        return redirect(request.referrer or url_for('dashboard'))

    if leave['status'] in ('retrieved', 'modified'):
        flash('This leave has already been retrieved or modified', 'error')
        conn.close()
        return redirect(request.referrer or url_for('dashboard'))

    if request.method == 'POST':
        new_leave_type = request.form.get('leave_type', '').strip()
        new_day_portion = request.form.get('day_portion', 'full').strip()
        new_reason = request.form.get('reason', '').strip()

        if not all([new_leave_type, new_reason]):
            flash('Leave type and reason are required', 'error')
            conn.close()
            return redirect(url_for('edit_leave', leave_id=leave_id))

        day_val = 0.5 if new_day_portion in ('first_half', 'second_half') else 1.0

        conn.execute('''
            UPDATE leave_records SET leave_type = ?, day_portion = ?, days = ?, reason = ?
            WHERE id = ?
        ''', (new_leave_type, new_day_portion, day_val, new_reason, leave_id))
        conn.commit()
        conn.close()

        flash('Leave updated successfully', 'success')
        return redirect(request.referrer or url_for('my_leave_applications'))

    # GET: show edit form
    conn.close()
    return render_template('edit_leave.html', user=user, leave=leave)


@app.route('/approvals')
@login_required
def employee_approvals():
    """Approvals page for managers and management peers"""
    user = get_user()
    conn = get_db()

    # Get pending leave requests from direct reports (late leaves first)
    pending = conn.execute('''
        SELECT lr.*, e.name, e.emp_code, e.department FROM leave_records lr
        JOIN employees e ON lr.employee_id = e.id
        WHERE lr.status = 'pending' AND e.reporting_to = ?
        ORDER BY lr.is_late DESC, lr.created_at DESC
    ''', (user['id'],)).fetchall()
    pending = list(pending)

    # If current user is management, also show pending from other management members
    if user['emp_code'] in MANAGEMENT_CODES:
        mgmt_pending = conn.execute('''
            SELECT lr.*, e.name, e.emp_code, e.department FROM leave_records lr
            JOIN employees e ON lr.employee_id = e.id
            WHERE lr.status = 'pending' AND e.emp_code IN (?, ?, ?)
            AND e.id != ?
            ORDER BY lr.is_late DESC, lr.created_at DESC
        ''', (*MANAGEMENT_CODES, user['id'])).fetchall()
        # Merge, avoiding duplicates
        existing_ids = {l['id'] for l in pending}
        for leave in mgmt_pending:
            if leave['id'] not in existing_ids:
                pending.append(leave)

    # Get recently approved/rejected by this manager
    recent = conn.execute('''
        SELECT lr.*, e.name, e.emp_code, e.department FROM leave_records lr
        JOIN employees e ON lr.employee_id = e.id
        WHERE lr.approved_by = ? AND lr.status IN ('approved', 'rejected')
        ORDER BY lr.approved_at DESC LIMIT 10
    ''', (user['id'],)).fetchall()

    # Get direct reports list (include late leave count)
    direct_reports = conn.execute('''
        SELECT id, name, emp_code, department, designation, late_leave_count FROM employees
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

    leave_emp = conn.execute('SELECT * FROM employees WHERE id = ?', (leave['employee_id'],)).fetchone()
    allowed, reason = can_approve_leave(user, leave_emp, conn)
    if not allowed:
        flash(reason, 'error')
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
    """Reject leave - for managers and management peers"""
    user = get_user()
    conn = get_db()

    leave = conn.execute('SELECT * FROM leave_records WHERE id = ?', (leave_id,)).fetchone()
    if not leave:
        flash('Leave not found', 'error')
        conn.close()
        return redirect(url_for('employee_approvals'))

    leave_emp = conn.execute('SELECT * FROM employees WHERE id = ?', (leave['employee_id'],)).fetchone()
    allowed, reason = can_approve_leave(user, leave_emp, conn)
    if not allowed:
        flash(reason, 'error')
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

@app.route('/holidays')
@login_required
def employee_holidays():
    user = get_user()
    conn = get_db()
    holidays = conn.execute('SELECT * FROM holidays ORDER BY holiday_date').fetchall()
    conn.close()
    today_date = datetime.now().strftime('%Y-%m-%d')
    return render_template('employee_holidays.html', user=user, holidays=holidays, today_date=today_date)

@app.route('/org-chart')
@login_required
def employee_org_chart():
    user = get_user()
    conn = get_db()
    employees = conn.execute('''
        SELECT e.*, m.name as manager_name, m.photo_url as manager_photo
        FROM employees e
        LEFT JOIN employees m ON e.reporting_to = m.id
        WHERE e.is_active = 1 AND e.emp_code != 'admin'
        ORDER BY e.department, e.name
    ''').fetchall()
    departments = conn.execute('''
        SELECT department, COUNT(*) as count FROM employees
        WHERE is_active = 1 AND emp_code != 'admin'
        GROUP BY department ORDER BY department
    ''').fetchall()
    conn.close()
    return render_template('employee_org_chart.html', user=user, employees=employees, departments=departments)

@app.route('/my-leave-report')
@login_required
def my_leave_report():
    user = get_user()

    # Admin control account has no personal leave report
    if user['emp_code'] == 'admin':
        return redirect(url_for('admin_employee_leave_report'))
    conn = get_db()

    today = datetime.now()
    current_month = today.month
    fy_year = today.year if current_month >= 4 else today.year - 1

    # Total balance and carry forward
    emp = conn.execute('SELECT carry_forward FROM employees WHERE id = ?', (user['id'],)).fetchone()
    carry_forward = emp['carry_forward'] if emp else 0
    total_allocation = 25 + carry_forward
    monthly_alloc = round(total_allocation / 12, 2)

    # Pending requests count
    pending_count = conn.execute(
        'SELECT COUNT(*) as cnt FROM leave_records WHERE employee_id = ? AND status = ?',
        (user['id'], 'pending')
    ).fetchone()['cnt']

    # Month-wise leave report for the full FY with running balance
    monthly_leave_data = []
    running_balance = 0
    for m in range(12):
        report_month = ((m + 3) % 12) + 1
        report_year = fy_year if report_month >= 4 else fy_year + 1

        month_data = conn.execute('''
            SELECT SUM(days) as total_days,
                   SUM(CASE WHEN leave_type = 'annual' THEN days ELSE 0 END) as annual,
                   SUM(CASE WHEN leave_type = 'sick' THEN days ELSE 0 END) as sick,
                   SUM(CASE WHEN leave_type = 'casual' THEN days ELSE 0 END) as casual,
                   COUNT(*) as count
            FROM leave_records
            WHERE employee_id = ? AND status = 'approved'
            AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
        ''', (user['id'], str(report_year), str(report_month).zfill(2))).fetchone()

        month_total = month_data['total_days'] or 0
        running_balance = round(running_balance + monthly_alloc - month_total, 2)

        monthly_leave_data.append({
            'month': calendar.month_name[report_month],
            'month_short': calendar.month_abbr[report_month],
            'year': report_year,
            'total': month_total,
            'annual': month_data['annual'] or 0,
            'sick': month_data['sick'] or 0,
            'casual': month_data['casual'] or 0,
            'count': month_data['count'] or 0,
            'monthly_alloc': monthly_alloc,
            'balance': running_balance
        })

    # All leave records for the FY
    all_leaves = conn.execute('''
        SELECT * FROM leave_records
        WHERE employee_id = ?
        AND ((strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) >= '04')
             OR (strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) < '04'))
        ORDER BY leave_date DESC
    ''', (user['id'], str(fy_year), str(fy_year + 1))).fetchall()

    # Days taken - with type breakdown
    total_taken = sum(m['total'] for m in monthly_leave_data)
    annual_total = sum(m['annual'] for m in monthly_leave_data)
    sick_total = sum(m['sick'] for m in monthly_leave_data)
    casual_total = sum(m['casual'] for m in monthly_leave_data)
    available_balance = total_allocation - total_taken

    conn.close()

    return render_template('employee_leave_report.html',
                         user=user,
                         monthly_leave_data=monthly_leave_data,
                         all_leaves=all_leaves,
                         fy_year=fy_year,
                         total_allocation=total_allocation,
                         total_taken=total_taken,
                         annual_total=annual_total,
                         sick_total=sick_total,
                         casual_total=casual_total,
                         available_balance=round(available_balance, 2),
                         pending_count=pending_count,
                         carry_forward=carry_forward,
                         monthly_alloc=monthly_alloc)

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    user = get_user()
    conn = get_db()

    # Summary stats
    total_employees = conn.execute("SELECT COUNT(*) as count FROM employees WHERE is_active = 1 AND emp_code != 'admin'").fetchone()

    today = datetime.now().strftime('%Y-%m-%d')
    leaves_today = conn.execute('''
        SELECT COUNT(DISTINCT employee_id) as count FROM leave_records
        WHERE leave_date = ? AND status = 'approved'
    ''', (today,)).fetchone()

    pending = conn.execute("SELECT COUNT(*) as count FROM leave_records WHERE status = 'pending'").fetchone()

    # Department-wise count (include management as employees, exclude admin login)
    departments = conn.execute('''
        SELECT department, COUNT(*) as count FROM employees
        WHERE is_active = 1 AND emp_code != 'admin'
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

    # Birthdays this month
    current_mm = str(now.month).zfill(2)
    birthdays_this_month = conn.execute('''
        SELECT name, dob, photo_url, department FROM employees
        WHERE is_active = 1 AND emp_code != 'admin' AND dob IS NOT NULL AND dob != ''
        AND strftime('%m', dob) = ?
        ORDER BY strftime('%d', dob)
    ''', (current_mm,)).fetchall()

    # Work anniversaries this month
    anniversaries_this_month = conn.execute('''
        SELECT name, joining_date, photo_url, department FROM employees
        WHERE is_active = 1 AND emp_code != 'admin' AND joining_date IS NOT NULL AND joining_date != ''
        AND strftime('%m', joining_date) = ?
        AND strftime('%Y', joining_date) != ?
        ORDER BY strftime('%d', joining_date)
    ''', (current_mm, str(now.year))).fetchall()

    # Recent announcements
    announcements = conn.execute('''
        SELECT a.*, e.name as posted_by_name FROM announcements a
        JOIN employees e ON a.posted_by = e.id
        WHERE a.is_active = 1
        ORDER BY a.created_at DESC LIMIT 5
    ''', ()).fetchall()

    # Management user leave balance (for welcome banner)
    is_management = user['emp_code'] in MANAGEMENT_CODES
    mgmt_leave_data = {}
    if is_management:
        fy_year = now.year if now.month >= 4 else now.year - 1
        carry_forward = user['carry_forward'] or 0
        total_allocation = 25 + carry_forward
        leaves_taken = conn.execute('''
            SELECT SUM(days) as total_days FROM leave_records
            WHERE employee_id = ? AND status = 'approved'
            AND ((strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) >= '04')
                 OR (strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) < '04'))
        ''', (user['id'], str(fy_year), str(fy_year + 1))).fetchone()
        days_taken = leaves_taken['total_days'] if leaves_taken['total_days'] else 0
        my_pending = conn.execute(
            "SELECT COUNT(*) as cnt FROM leave_records WHERE employee_id = ? AND status = 'pending'",
            (user['id'],)
        ).fetchone()['cnt']
        mgmt_leave_data = {
            'total_allocation': total_allocation,
            'available_balance': round(total_allocation - days_taken, 2),
            'days_taken': days_taken,
            'pending_count': my_pending
        }

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
                         current_year=now.year,
                         birthdays_this_month=birthdays_this_month,
                         anniversaries_this_month=anniversaries_this_month,
                         announcements=announcements,
                         can_announce=can_post_announcements(user),
                         is_management=is_management,
                         mgmt_leave_data=mgmt_leave_data)

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
        WHERE e.is_active = 1 AND e.emp_code != 'admin'
        ORDER BY e.department, e.name
    ''').fetchall()
    departments = conn.execute('''
        SELECT department, COUNT(*) as count FROM employees
        WHERE is_active = 1 AND emp_code != 'admin'
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
    employees = conn.execute("SELECT id, name FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY name").fetchall()

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

    employees = conn.execute("SELECT id, name FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY name").fetchall()

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

    employees = conn.execute("SELECT id, name FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY name").fetchall()

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
        dept_employees = conn.execute('SELECT id FROM employees WHERE department = ? AND is_active = 1', (department,)).fetchall()

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
        ''', (name, emp_code, hash_password(name.split()[0].lower()), department, datetime.now().strftime('%Y-%m-%d'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()

        flash('Employee added successfully', 'success')
        return redirect(url_for('manage_employees'))

    employees = conn.execute("SELECT * FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY department, name").fetchall()

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
    employees = conn.execute("SELECT * FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY name").fetchall()

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
    employees = conn.execute("SELECT * FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY name").fetchall()

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
            ORDER BY lr.is_late DESC, lr.created_at DESC
        ''').fetchall()
        # Get late leave summary for all employees with late_leave_count > 0
        late_summary = conn.execute('''
            SELECT name, emp_code, late_leave_count FROM employees
            WHERE late_leave_count > 0 AND is_active = 1 AND emp_code != 'admin'
            ORDER BY late_leave_count DESC
        ''').fetchall()
    else:
        # If manager, show pending from direct reports
        pending = conn.execute('''
            SELECT lr.*, e.name, e.emp_code FROM leave_records lr
            JOIN employees e ON lr.employee_id = e.id
            WHERE lr.status = 'pending' AND e.reporting_to = ?
            ORDER BY lr.is_late DESC, lr.created_at DESC
        ''', (user['id'],)).fetchall()
        # Late leave summary for direct reports only
        late_summary = conn.execute('''
            SELECT name, emp_code, late_leave_count FROM employees
            WHERE late_leave_count > 0 AND reporting_to = ? AND is_active = 1
            ORDER BY late_leave_count DESC
        ''', (user['id'],)).fetchall()

    conn.close()

    return render_template('pending_approvals.html', user=user, pending_leaves=pending,
                         late_leave_summary=late_summary)

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

    leave_emp = conn.execute('SELECT * FROM employees WHERE id = ?', (leave['employee_id'],)).fetchone()
    allowed, reason = can_approve_leave(user, leave_emp, conn)
    if not allowed:
        flash(reason, 'error')
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

    leave_emp = conn.execute('SELECT * FROM employees WHERE id = ?', (leave['employee_id'],)).fetchone()
    allowed, reason = can_approve_leave(user, leave_emp, conn)
    if not allowed:
        flash(reason, 'error')
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

# ===== NOTIFICATION HELPERS =====

def create_notification(conn, ntype, title, message, target_user_id=None, target_role='all', reference_id=None):
    """Create a notification record.
    target_user_id: specific user (for leave notifications)
    target_role: 'all', 'admin', 'manager' for broader targeting
    """
    conn.execute('''
        INSERT INTO notifications (type, title, message, target_user_id, target_role, reference_id, is_read, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
    ''', (ntype, title, message, target_user_id, target_role, reference_id,
          datetime.now().strftime('%Y-%m-%d %H:%M:%S')))


def get_unread_count(user_id, is_admin=False):
    """Get unread notification count for a user."""
    conn = get_db()
    # Notifications targeted to this specific user OR to 'all' OR to their role
    if is_admin:
        count = conn.execute('''
            SELECT COUNT(*) as cnt FROM notifications
            WHERE is_read = 0 AND (target_user_id = ? OR target_user_id IS NULL)
            AND (target_role IN ('all', 'admin'))
        ''', (user_id,)).fetchone()
    else:
        count = conn.execute('''
            SELECT COUNT(*) as cnt FROM notifications
            WHERE is_read = 0 AND (target_user_id = ? OR target_user_id IS NULL)
            AND (target_role = 'all')
        ''', (user_id,)).fetchone()
    conn.close()
    return count['cnt'] if count else 0


@app.context_processor
def inject_notification_count():
    """Make unread notification count available in all templates."""
    if 'user_id' in session:
        is_admin = session.get('is_admin', False)
        count = get_unread_count(session['user_id'], is_admin)
        return {'unread_notification_count': count}
    return {'unread_notification_count': 0}


@app.route('/api/notifications')
@login_required
def get_notifications():
    """Get notifications for the current user."""
    user = get_user()
    conn = get_db()

    if user['is_admin']:
        notifications = conn.execute('''
            SELECT * FROM notifications
            WHERE (target_user_id = ? OR target_user_id IS NULL)
            AND (target_role IN ('all', 'admin'))
            ORDER BY created_at DESC LIMIT 30
        ''', (user['id'],)).fetchall()
    else:
        # Check if user is a manager
        mgr = is_manager(user['id'])
        if mgr:
            notifications = conn.execute('''
                SELECT * FROM notifications
                WHERE (target_user_id = ? OR target_user_id IS NULL)
                AND (target_role IN ('all', 'manager'))
                ORDER BY created_at DESC LIMIT 30
            ''', (user['id'],)).fetchall()
        else:
            notifications = conn.execute('''
                SELECT * FROM notifications
                WHERE (target_user_id = ? OR target_user_id IS NULL)
                AND (target_role = 'all')
                ORDER BY created_at DESC LIMIT 30
            ''', (user['id'],)).fetchall()

    conn.close()

    result = []
    for n in notifications:
        result.append({
            'id': n['id'],
            'type': n['type'],
            'title': n['title'],
            'message': n['message'],
            'is_read': n['is_read'],
            'created_at': str(n['created_at'])
        })

    return jsonify(result)


@app.route('/api/notifications/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    """Mark all notifications as read for the current user."""
    user = get_user()
    conn = get_db()

    if user['is_admin']:
        conn.execute('''
            UPDATE notifications SET is_read = 1
            WHERE is_read = 0 AND (target_user_id = ? OR target_user_id IS NULL)
            AND (target_role IN ('all', 'admin'))
        ''', (user['id'],))
    else:
        mgr = is_manager(user['id'])
        if mgr:
            conn.execute('''
                UPDATE notifications SET is_read = 1
                WHERE is_read = 0 AND (target_user_id = ? OR target_user_id IS NULL)
                AND (target_role IN ('all', 'manager'))
            ''', (user['id'],))
        else:
            conn.execute('''
                UPDATE notifications SET is_read = 1
                WHERE is_read = 0 AND (target_user_id = ? OR target_user_id IS NULL)
                AND (target_role = 'all')
            ''', (user['id'],))

    conn.commit()
    conn.close()

    return jsonify({'status': 'ok'})


@app.route('/api/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_single_notification_read(notif_id):
    """Mark a single notification as read."""
    conn = get_db()
    conn.execute('UPDATE notifications SET is_read = 1 WHERE id = ?', (notif_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})


@app.route('/api/dismiss-welcome', methods=['POST'])
@login_required
def dismiss_welcome():
    """Dismiss the first-login welcome popup."""
    session.pop('show_welcome', None)
    return jsonify({'status': 'ok'})


@app.route('/notifications')
@login_required
def notifications_page():
    """Dedicated notifications page with all notifications."""
    user = get_user()
    conn = get_db()

    if user['is_admin']:
        notifications = conn.execute('''
            SELECT * FROM notifications
            WHERE (target_user_id = ? OR target_user_id IS NULL)
            AND (target_role IN ('all', 'admin'))
            ORDER BY created_at DESC LIMIT 100
        ''', (user['id'],)).fetchall()
    else:
        mgr = is_manager(user['id'])
        if mgr:
            notifications = conn.execute('''
                SELECT * FROM notifications
                WHERE (target_user_id = ? OR target_user_id IS NULL)
                AND (target_role IN ('all', 'manager'))
                ORDER BY created_at DESC LIMIT 100
            ''', (user['id'],)).fetchall()
        else:
            notifications = conn.execute('''
                SELECT * FROM notifications
                WHERE (target_user_id = ? OR target_user_id IS NULL)
                AND (target_role = 'all')
                ORDER BY created_at DESC LIMIT 100
            ''', (user['id'],)).fetchall()

    # Count unread
    unread_count = sum(1 for n in notifications if n['is_read'] == 0)

    conn.close()
    return render_template('notifications.html', user=user, notifications=notifications, unread_count=unread_count)


@app.route('/announcements')
@login_required
def announcements():
    user = get_user()
    if not can_post_announcements(user):
        flash('You do not have permission to manage announcements', 'error')
        return redirect(url_for('dashboard'))

    conn = get_db()
    all_announcements = conn.execute('''
        SELECT a.*, e.name as posted_by_name FROM announcements a
        JOIN employees e ON a.posted_by = e.id
        ORDER BY a.created_at DESC
    ''', ()).fetchall()
    conn.close()

    return render_template('announcements.html', user=user, announcements=all_announcements)


@app.route('/announcements/create', methods=['POST'])
@login_required
def create_announcement():
    user = get_user()
    if not can_post_announcements(user):
        flash('You do not have permission to post announcements', 'error')
        return redirect(url_for('dashboard'))

    title = request.form.get('title', '').strip()
    message = request.form.get('message', '').strip()

    if not title or not message:
        flash('Title and message are required', 'error')
        return redirect(url_for('announcements'))

    conn = get_db()
    conn.execute('''
        INSERT INTO announcements (title, message, posted_by, is_active, created_at)
        VALUES (?, ?, ?, 1, ?)
    ''', (title, message, user['id'], datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()

    # Create notification for all users
    try:
        create_notification(conn, 'announcement', title,
                          f"New announcement by {user['name']}: {message[:100]}",
                          target_role='all')
        conn.commit()
    except Exception as e:
        logging.error(f"Failed to create announcement notification: {e}")

    # Send email to all active employees with email addresses
    recipients = conn.execute('''
        SELECT email FROM employees WHERE is_active = 1 AND email IS NOT NULL AND email != ''
    ''', ()).fetchall()
    conn.close()

    recipient_emails = [r['email'] for r in recipients]
    if recipient_emails:
        try:
            send_announcement_email(title, message, user['name'], recipient_emails)
        except Exception as e:
            logging.error(f"Failed to send announcement email: {e}")

    flash('Announcement posted successfully', 'success')
    return redirect(url_for('announcements'))


@app.route('/announcements/delete/<int:ann_id>', methods=['POST'])
@login_required
def delete_announcement(ann_id):
    user = get_user()
    if not can_post_announcements(user):
        flash('You do not have permission to delete announcements', 'error')
        return redirect(url_for('dashboard'))

    conn = get_db()
    conn.execute('UPDATE announcements SET is_active = 0 WHERE id = ?', (ann_id,))
    conn.commit()
    conn.close()

    flash('Announcement removed', 'success')
    return redirect(url_for('announcements'))


@app.route('/api/daily-notifications')
def daily_notifications():
    """
    API endpoint to send birthday and anniversary reminder emails.
    Call this daily via cron job. Sends reminders for tomorrow's events.
    Also sends a happy birthday email directly to the birthday person.
    Creates in-app notifications for all users.
    """
    conn = get_db()
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    tomorrow_mm = tomorrow[5:7]
    tomorrow_dd = tomorrow[8:10]
    current_year = datetime.now().year

    # Get all active employee emails for recipients
    all_employees = conn.execute('''
        SELECT email FROM employees WHERE is_active = 1 AND email IS NOT NULL AND email != ''
    ''', ()).fetchall()
    recipient_emails = [e['email'] for e in all_employees]

    results = {'birthdays_sent': 0, 'birthday_wishes_sent': 0, 'anniversaries_sent': 0, 'notifications_created': 0, 'errors': []}

    if not recipient_emails:
        conn.close()
        return jsonify({'status': 'ok', 'message': 'No recipients with email addresses', **results})

    # Birthday reminders for tomorrow
    birthday_people = conn.execute('''
        SELECT name, dob, email FROM employees
        WHERE is_active = 1 AND emp_code != 'admin' AND dob IS NOT NULL AND dob != ''
        AND strftime('%m', dob) = ? AND strftime('%d', dob) = ?
    ''', (tomorrow_mm, tomorrow_dd)).fetchall()

    for person in birthday_people:
        # Send team reminder email
        try:
            send_birthday_reminder(person['name'], tomorrow, recipient_emails)
            results['birthdays_sent'] += 1
        except Exception as e:
            results['errors'].append(f"Birthday reminder for {person['name']}: {str(e)}")

        # Send happy birthday email directly to the person
        if person['email']:
            try:
                send_happy_birthday_email(person['name'], person['email'])
                results['birthday_wishes_sent'] += 1
            except Exception as e:
                results['errors'].append(f"Happy birthday email for {person['name']}: {str(e)}")

        # Create in-app notification for everyone
        try:
            create_notification(conn, 'birthday',
                f"🎂 {person['name']}'s Birthday Tomorrow!",
                f"Tomorrow is {person['name']}'s birthday! Join us in wishing them a wonderful day.",
                target_role='all')
            results['notifications_created'] += 1
        except Exception as e:
            results['errors'].append(f"Birthday notification for {person['name']}: {str(e)}")

    # Anniversary reminders for tomorrow
    anniversary_people = conn.execute('''
        SELECT name, joining_date, email FROM employees
        WHERE is_active = 1 AND emp_code != 'admin' AND joining_date IS NOT NULL AND joining_date != ''
        AND strftime('%m', joining_date) = ? AND strftime('%d', joining_date) = ?
        AND strftime('%Y', joining_date) != ?
    ''', (tomorrow_mm, tomorrow_dd, str(current_year))).fetchall()

    for person in anniversary_people:
        try:
            join_year = int(person['joining_date'][:4])
            years = current_year - join_year
            send_anniversary_reminder(person['name'], years, tomorrow, recipient_emails)
            results['anniversaries_sent'] += 1
        except Exception as e:
            results['errors'].append(f"Anniversary email for {person['name']}: {str(e)}")

        # Create in-app notification for everyone
        try:
            join_year = int(person['joining_date'][:4])
            years = current_year - join_year
            yr_text = f"{years} year{'s' if years != 1 else ''}"
            create_notification(conn, 'anniversary',
                f"🌟 {person['name']}'s Work Anniversary!",
                f"Tomorrow marks {person['name']}'s {yr_text} at GooCampus! Congratulations!",
                target_role='all')
            results['notifications_created'] += 1
        except Exception as e:
            results['errors'].append(f"Anniversary notification for {person['name']}: {str(e)}")

    # Create notifications for upcoming holidays (next 2 days)
    day_after = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')
    upcoming = conn.execute('''
        SELECT holiday_name, holiday_date, holiday_type FROM holidays
        WHERE holiday_date = ? OR holiday_date = ?
    ''', (tomorrow, day_after)).fetchall()

    for holiday in upcoming:
        try:
            create_notification(conn, 'holiday',
                f"🏖️ Holiday: {holiday['holiday_name']}",
                f"Upcoming holiday on {holiday['holiday_date']} — {holiday['holiday_name']} ({holiday['holiday_type']})",
                target_role='all')
            results['notifications_created'] += 1
        except Exception as e:
            results['errors'].append(f"Holiday notification: {str(e)}")

    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', **results})


# ─── Quarterly Report Routes ───
@app.route('/admin/quarterly-report')
@admin_required
def admin_quarterly_report():
    user = get_user()
    year = int(request.args.get('year', datetime.now().year))
    quarter = int(request.args.get('quarter', 1))

    # Q1=Apr-Jun, Q2=Jul-Sep, Q3=Oct-Dec, Q4=Jan-Mar
    quarter_months = {
        1: [4, 5, 6],
        2: [7, 8, 9],
        3: [10, 11, 12],
        4: [1, 2, 3]
    }
    months = quarter_months.get(quarter, [4, 5, 6])

    conn = get_db()
    employees = conn.execute("SELECT * FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY name").fetchall()

    report_data = []
    for emp in employees:
        # Get leaves for each month in quarter
        quarterly_days = 0
        leave_breakdown = {'annual': 0, 'sick': 0, 'casual': 0}

        for m in months:
            # Adjust year for Q4 (Jan-Mar of next year)
            check_year = year + 1 if m < 4 else year
            leaves = conn.execute('''
                SELECT SUM(days) as total_days, leave_type FROM leave_records
                WHERE employee_id = ? AND status = 'approved'
                AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
                GROUP BY leave_type
            ''', (emp['id'], str(check_year), str(m).zfill(2))).fetchall()

            for row in leaves:
                if row['total_days']:
                    quarterly_days += row['total_days']
                    leave_type = (row['leave_type'] or 'casual').lower()
                    if leave_type in leave_breakdown:
                        leave_breakdown[leave_type] += row['total_days']

        report_data.append({
            'name': emp['name'],
            'emp_code': emp['emp_code'],
            'department': emp['department'],
            'total_days': quarterly_days,
            'annual': leave_breakdown['annual'],
            'sick': leave_breakdown['sick'],
            'casual': leave_breakdown['casual']
        })

    conn.close()
    quarter_name = f"Q{quarter} (FY {year}-{year+1})"

    return render_template('admin_quarterly_report.html',
                         user=user,
                         year=year,
                         quarter=quarter,
                         quarter_name=quarter_name,
                         report_data=report_data)


@app.route('/admin/quarterly-report/download')
@admin_required
def admin_quarterly_report_download():
    year = int(request.args.get('year', datetime.now().year))
    quarter = int(request.args.get('quarter', 1))

    quarter_months = {1: [4, 5, 6], 2: [7, 8, 9], 3: [10, 11, 12], 4: [1, 2, 3]}
    months = quarter_months.get(quarter, [4, 5, 6])

    conn = get_db()
    employees = conn.execute("SELECT * FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY name").fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = f"Q{quarter} Report {year}"

    headers = ['Name', 'Employee Code', 'Department', 'Total Days', 'Annual', 'Sick', 'Casual']
    ws.append(headers)

    header_fill = PatternFill(start_color='1a56db', end_color='1a56db', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for emp in employees:
        quarterly_days = 0
        leave_breakdown = {'annual': 0, 'sick': 0, 'casual': 0}

        for m in months:
            check_year = year + 1 if m < 4 else year
            leaves = conn.execute('''
                SELECT SUM(days) as total_days, leave_type FROM leave_records
                WHERE employee_id = ? AND status = 'approved'
                AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
                GROUP BY leave_type
            ''', (emp['id'], str(check_year), str(m).zfill(2))).fetchall()

            for row in leaves:
                if row['total_days']:
                    quarterly_days += row['total_days']
                    leave_type = (row['leave_type'] or 'casual').lower()
                    if leave_type in leave_breakdown:
                        leave_breakdown[leave_type] += row['total_days']

        ws.append([
            emp['name'],
            emp['emp_code'],
            emp['department'],
            quarterly_days,
            leave_breakdown['annual'],
            leave_breakdown['sick'],
            leave_breakdown['casual']
        ])

    for col in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
        ws.column_dimensions[col].width = 15

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    conn.close()

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'Quarterly_Report_Q{quarter}_{year}.xlsx'
    )


# ─── Annual Report Routes ───
@app.route('/admin/annual-report')
@admin_required
def admin_annual_report():
    user = get_user()
    # year parameter is the FY start year (e.g. 2025 for FY 2025-26)
    year = int(request.args.get('year', datetime.now().year))

    conn = get_db()
    employees = conn.execute("SELECT * FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY name").fetchall()

    report_data = []
    for emp in employees:
        carry_forward = emp['carry_forward']
        total_allocation = 25 + carry_forward

        # Get approved leaves for the entire FY (Apr year to Mar year+1)
        fy_leaves = conn.execute('''
            SELECT SUM(days) as total_days FROM leave_records
            WHERE employee_id = ? AND status = 'approved'
            AND ((strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) >= '04')
                 OR (strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) <= '03'))
        ''', (emp['id'], str(year), str(year + 1))).fetchone()

        total_taken = fy_leaves['total_days'] if fy_leaves['total_days'] else 0
        remaining_balance = total_allocation - total_taken

        # Get monthly breakdown
        monthly_breakdown = []
        for m in range(1, 13):
            check_year = year if m >= 4 else year + 1
            month_leaves = conn.execute('''
                SELECT SUM(days) as total_days FROM leave_records
                WHERE employee_id = ? AND status = 'approved'
                AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
            ''', (emp['id'], str(check_year), str(m).zfill(2))).fetchone()
            month_days = month_leaves['total_days'] if month_leaves['total_days'] else 0
            monthly_breakdown.append(month_days)

        report_data.append({
            'name': emp['name'],
            'emp_code': emp['emp_code'],
            'department': emp['department'],
            'total_allocation': total_allocation,
            'total_taken': total_taken,
            'remaining_balance': remaining_balance,
            'monthly_breakdown': monthly_breakdown
        })

    conn.close()
    fy_label = f"FY {year}-{year+1}"

    return render_template('admin_annual_report.html',
                         user=user,
                         year=year,
                         fy_label=fy_label,
                         report_data=report_data)


@app.route('/admin/annual-report/download')
@admin_required
def admin_annual_report_download():
    year = int(request.args.get('year', datetime.now().year))

    conn = get_db()
    employees = conn.execute("SELECT * FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY name").fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = f"Annual Report {year}"

    headers = ['Name', 'Employee Code', 'Department', 'Total Allocation', 'Days Taken', 'Remaining Balance']
    # Add month headers
    month_names = ['Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar']
    headers.extend(month_names)
    ws.append(headers)

    header_fill = PatternFill(start_color='1a56db', end_color='1a56db', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for emp in employees:
        carry_forward = emp['carry_forward']
        total_allocation = 25 + carry_forward

        fy_leaves = conn.execute('''
            SELECT SUM(days) as total_days FROM leave_records
            WHERE employee_id = ? AND status = 'approved'
            AND ((strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) >= '04')
                 OR (strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) <= '03'))
        ''', (emp['id'], str(year), str(year + 1))).fetchone()

        total_taken = fy_leaves['total_days'] if fy_leaves['total_days'] else 0
        remaining_balance = total_allocation - total_taken

        row = [emp['name'], emp['emp_code'], emp['department'], total_allocation, total_taken, remaining_balance]

        # Add monthly breakdown
        for m in range(1, 13):
            check_year = year if m >= 4 else year + 1
            month_leaves = conn.execute('''
                SELECT SUM(days) as total_days FROM leave_records
                WHERE employee_id = ? AND status = 'approved'
                AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
            ''', (emp['id'], str(check_year), str(m).zfill(2))).fetchone()
            month_days = month_leaves['total_days'] if month_leaves['total_days'] else 0
            row.append(month_days)

        ws.append(row)

    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 15
    ws.column_dimensions['C'].width = 18
    ws.column_dimensions['D'].width = 16
    ws.column_dimensions['E'].width = 14
    ws.column_dimensions['F'].width = 17
    for i, col in enumerate(['G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R']):
        ws.column_dimensions[col].width = 10

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    conn.close()

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'Annual_Report_FY_{year}_{year+1}.xlsx'
    )



# ─── Admin Employee Leave Report (select any employee) ───
@app.route('/admin/employee-leave-report')
@admin_required
def admin_employee_leave_report():
    user = get_user()
    conn = get_db()

    employees = conn.execute("SELECT id, name, emp_code, department FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY name").fetchall()

    selected_emp_id = request.args.get('employee_id', type=int)
    selected_emp = None
    monthly_leave_data = []
    all_leaves = []
    total_allocation = 0
    total_taken = 0
    annual_total = 0
    sick_total = 0
    casual_total = 0
    available_balance = 0
    pending_count = 0
    carry_forward = 0
    monthly_alloc = 0

    today = datetime.now()
    current_month = today.month
    fy_year = today.year if current_month >= 4 else today.year - 1

    if selected_emp_id:
        selected_emp = conn.execute('SELECT * FROM employees WHERE id = ?', (selected_emp_id,)).fetchone()
        if selected_emp:
            carry_forward = selected_emp['carry_forward'] or 0
            total_allocation = 25 + carry_forward
            monthly_alloc = round(total_allocation / 12, 2)

            pending_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM leave_records WHERE employee_id = ? AND status = 'pending'",
                (selected_emp_id,)
            ).fetchone()['cnt']

            running_balance = 0
            for m in range(12):
                report_month = ((m + 3) % 12) + 1
                report_year = fy_year if report_month >= 4 else fy_year + 1

                month_data = conn.execute('''
                    SELECT SUM(days) as total_days,
                           SUM(CASE WHEN leave_type = 'annual' THEN days ELSE 0 END) as annual,
                           SUM(CASE WHEN leave_type = 'sick' THEN days ELSE 0 END) as sick,
                           SUM(CASE WHEN leave_type = 'casual' THEN days ELSE 0 END) as casual,
                           COUNT(*) as count
                    FROM leave_records
                    WHERE employee_id = ? AND status = 'approved'
                    AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
                ''', (selected_emp_id, str(report_year), str(report_month).zfill(2))).fetchone()

                month_total = month_data['total_days'] or 0
                running_balance = round(running_balance + monthly_alloc - month_total, 2)

                monthly_leave_data.append({
                    'month': calendar.month_name[report_month],
                    'month_short': calendar.month_abbr[report_month],
                    'year': report_year,
                    'total': month_total,
                    'annual': month_data['annual'] or 0,
                    'sick': month_data['sick'] or 0,
                    'casual': month_data['casual'] or 0,
                    'count': month_data['count'] or 0,
                    'monthly_alloc': monthly_alloc,
                    'balance': running_balance
                })

            all_leaves = conn.execute('''
                SELECT * FROM leave_records
                WHERE employee_id = ?
                AND ((strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) >= '04')
                     OR (strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) < '04'))
                ORDER BY leave_date DESC
            ''', (selected_emp_id, str(fy_year), str(fy_year + 1))).fetchall()

            total_taken = sum(m['total'] for m in monthly_leave_data)
            annual_total = sum(m['annual'] for m in monthly_leave_data)
            sick_total = sum(m['sick'] for m in monthly_leave_data)
            casual_total = sum(m['casual'] for m in monthly_leave_data)
            available_balance = round(total_allocation - total_taken, 2)

    conn.close()

    return render_template('admin_employee_leave_report.html',
                         user=user,
                         employees=employees,
                         selected_emp=selected_emp,
                         selected_emp_id=selected_emp_id,
                         monthly_leave_data=monthly_leave_data,
                         all_leaves=all_leaves,
                         fy_year=fy_year,
                         total_allocation=total_allocation,
                         total_taken=total_taken,
                         annual_total=annual_total,
                         sick_total=sick_total,
                         casual_total=casual_total,
                         available_balance=available_balance,
                         pending_count=pending_count,
                         carry_forward=carry_forward,
                         monthly_alloc=monthly_alloc)


# ─── Team Leave Report Routes ───
@app.route('/reports/team')
@login_required
def team_leave_report():
    user = get_user()
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))

    # Check if user is a manager
    conn = get_db()
    direct_reports = conn.execute(
        'SELECT * FROM employees WHERE reporting_to = ? AND is_active = 1 ORDER BY name',
        (user['id'],)
    ).fetchall()

    if not direct_reports:
        conn.close()
        flash('You have no direct reports', 'info')
        return redirect(url_for('dashboard'))

    report_data = []
    for emp in direct_reports:
        carry_forward = emp['carry_forward']
        total_allocation = 25 + carry_forward
        monthly_allocation = total_allocation / 12

        # Get leaves for this month
        month_leaves = conn.execute('''
            SELECT SUM(days) as total_days FROM leave_records
            WHERE employee_id = ? AND status = 'approved'
            AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
        ''', (emp['id'], str(year), str(month).zfill(2))).fetchone()

        days_taken = month_leaves['total_days'] if month_leaves['total_days'] else 0
        balance_start = get_available_balance(emp['id'], year, month)
        balance_available = balance_start + monthly_allocation

        report_data.append({
            'name': emp['name'],
            'emp_code': emp['emp_code'],
            'allocation': round(monthly_allocation, 2),
            'balance_start': round(balance_start, 2),
            'balance_available': round(balance_available, 2),
            'days_taken': days_taken
        })

    conn.close()
    month_name = calendar.month_name[month]

    return render_template('team_leave_report.html',
                         user=user,
                         year=year,
                         month=month,
                         month_name=month_name,
                         report_data=report_data)


@app.route('/reports/team/download')
@login_required
def team_leave_report_download():
    user = get_user()
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))

    conn = get_db()
    direct_reports = conn.execute(
        'SELECT * FROM employees WHERE reporting_to = ? AND is_active = 1 ORDER BY name',
        (user['id'],)
    ).fetchall()

    if not direct_reports:
        conn.close()
        flash('You have no direct reports', 'info')
        return redirect(url_for('team_leave_report', year=year, month=month))

    wb = Workbook()
    ws = wb.active
    ws.title = f"Team Report {month}-{year}"

    headers = ['Name', 'Employee Code', 'Monthly Allocation', 'Balance Start', 'Balance Available', 'Days Taken']
    ws.append(headers)

    header_fill = PatternFill(start_color='1a56db', end_color='1a56db', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for emp in direct_reports:
        carry_forward = emp['carry_forward']
        total_allocation = 25 + carry_forward
        monthly_allocation = total_allocation / 12

        month_leaves = conn.execute('''
            SELECT SUM(days) as total_days FROM leave_records
            WHERE employee_id = ? AND status = 'approved'
            AND strftime('%Y', leave_date) = ? AND strftime('%m', leave_date) = ?
        ''', (emp['id'], str(year), str(month).zfill(2))).fetchone()

        days_taken = month_leaves['total_days'] if month_leaves['total_days'] else 0
        balance_start = get_available_balance(emp['id'], year, month)
        balance_available = balance_start + monthly_allocation

        ws.append([
            emp['name'],
            emp['emp_code'],
            round(monthly_allocation, 2),
            round(balance_start, 2),
            round(balance_available, 2),
            days_taken
        ])

    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 15
    ws.column_dimensions['C'].width = 18
    ws.column_dimensions['D'].width = 16
    ws.column_dimensions['E'].width = 17
    ws.column_dimensions['F'].width = 14

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    conn.close()

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'Team_Report_{month}_{year}.xlsx'
    )


# ─── Redirect Routes for Report Navigation ───
@app.route('/reports/monthly')
@login_required
def reports_monthly_redirect():
    year = request.args.get('year', datetime.now().year)
    month = request.args.get('month', datetime.now().month)
    return redirect(url_for('my_leave_report', year=year, month=month))


@app.route('/reports/quarterly')
@login_required
def reports_quarterly_redirect():
    year = request.args.get('year', datetime.now().year)
    quarter = request.args.get('quarter', 1)
    return redirect(url_for('my_leave_report', year=year))


@app.route('/reports/annual')
@login_required
def reports_annual_redirect():
    year = request.args.get('year', datetime.now().year)
    return redirect(url_for('my_leave_report', year=year))


def ensure_crm_tables():
    """Create CRM tables if they don't exist (safe to run repeatedly)."""
    try:
        conn = get_db()
        tables_sql = [
            '''CREATE TABLE IF NOT EXISTS wfh_requests (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                from_date TEXT NOT NULL,
                to_date TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                approved_by INTEGER REFERENCES employees(id),
                approved_at TEXT,
                rejection_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'active',
                created_by INTEGER REFERENCES employees(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS products_services (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                type TEXT NOT NULL DEFAULT 'product',
                project_id INTEGER REFERENCES projects(id),
                status TEXT DEFAULT 'active',
                created_by INTEGER REFERENCES employees(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS sales_news (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                posted_by INTEGER NOT NULL REFERENCES employees(id),
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS meeting_types (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS b2b_trips (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                trip_type TEXT NOT NULL,
                meeting_category TEXT DEFAULT 'face_to_face',
                from_date TEXT NOT NULL,
                to_date TEXT NOT NULL,
                travel_date TEXT,
                project_id INTEGER REFERENCES projects(id),
                notes TEXT,
                status TEXT DEFAULT 'planned',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS b2b_meetings (
                id SERIAL PRIMARY KEY,
                trip_id INTEGER NOT NULL REFERENCES b2b_trips(id) ON DELETE CASCADE,
                meeting_type_id INTEGER REFERENCES meeting_types(id),
                meeting_with TEXT NOT NULL,
                meeting_date TEXT NOT NULL,
                project_id INTEGER REFERENCES projects(id),
                location TEXT,
                contact_person TEXT,
                contact_phone TEXT,
                outcome TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''',
            '''CREATE TABLE IF NOT EXISTS module_access (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                module TEXT NOT NULL,
                granted_by INTEGER REFERENCES employees(id),
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(employee_id, module)
            )''',
        ]
        for sql in tables_sql:
            conn.execute(sql)
        conn.commit()
        # Add is_active column if not exists (migration for existing deployments)
        try:
            conn.execute('ALTER TABLE module_access ADD COLUMN is_active INTEGER DEFAULT 1')
            conn.commit()
        except Exception:
            conn.rollback()  # Required for PostgreSQL to reset aborted transaction state
        # Add meeting_category column to b2b_trips (migration for existing deployments)
        try:
            conn.execute("ALTER TABLE b2b_trips ADD COLUMN meeting_category TEXT DEFAULT 'face_to_face'")
            conn.commit()
        except Exception:
            conn.rollback()
        conn.close()
        logging.info("CRM tables ensured.")
    except Exception as e:
        logging.error(f"ensure_crm_tables: {e}")


def seed_default_meeting_types():
    """Seed default meeting client types if table is empty."""
    try:
        conn = get_db()
        count = conn.execute('SELECT COUNT(*) as cnt FROM meeting_types').fetchone()
        if count['cnt'] == 0:
            for mt in ['School', 'College', 'Partner', 'Branch Partner', 'Agent']:
                conn.execute('INSERT INTO meeting_types (name) VALUES (?)', (mt,))
            conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"seed_default_meeting_types: {e}")


# ─── WFH (Work from Home) Routes ───

@app.route('/wfh/apply', methods=['GET', 'POST'])
@login_required
def apply_wfh():
    user = get_user()

    # Admin control account cannot apply for WFH
    if user['emp_code'] == 'admin':
        flash('Admin account cannot apply for WFH.', 'error')
        return redirect(url_for('wfh_approvals'))

    if request.method == 'POST':
        from_date = request.form.get('from_date')
        to_date = request.form.get('to_date')
        reason = request.form.get('reason', '').strip()

        if not from_date or not to_date or not reason:
            flash('All fields are required', 'error')
            return redirect(url_for('apply_wfh'))

        if to_date < from_date:
            flash('To date cannot be before from date', 'error')
            return redirect(url_for('apply_wfh'))

        conn = get_db()
        conn.execute('''
            INSERT INTO wfh_requests (employee_id, from_date, to_date, reason)
            VALUES (?, ?, ?, ?)
        ''', (user['id'], from_date, to_date, reason))
        conn.commit()

        # Notify reporting manager and admins
        admins = conn.execute('SELECT id FROM employees WHERE is_admin = 1 AND is_active = 1').fetchall()
        for admin in admins:
            if admin['id'] != user['id']:
                conn.execute('''
                    INSERT INTO notifications (type, title, message, target_user_id, reference_id)
                    VALUES ('wfh_request', ?, ?, ?, NULL)
                ''', (
                    f"WFH Request from {user['name']}",
                    f"{user['name']} has requested WFH from {from_date} to {to_date}. Reason: {reason}",
                    admin['id']
                ))
        conn.commit()
        conn.close()

        flash('WFH request submitted successfully', 'success')
        return redirect(url_for('my_wfh_requests'))

    return render_template('apply_wfh.html', user=user)


@app.route('/wfh/my-requests')
@login_required
def my_wfh_requests():
    user = get_user()

    if user['emp_code'] == 'admin':
        return redirect(url_for('wfh_approvals'))

    conn = get_db()
    requests_list = conn.execute('''
        SELECT w.*, a.name as approver_name
        FROM wfh_requests w
        LEFT JOIN employees a ON w.approved_by = a.id
        WHERE w.employee_id = ?
        ORDER BY w.created_at DESC
    ''', (user['id'],)).fetchall()
    conn.close()
    return render_template('my_wfh_requests.html', user=user, requests=requests_list)


@app.route('/wfh/approvals')
@login_required
def wfh_approvals():
    user = get_user()
    conn = get_db()

    is_mgmt = user['emp_code'] in MANAGEMENT_CODES
    is_admin_user = user['is_admin'] == 1

    if not is_admin_user and not is_mgmt:
        # Only show direct reports' WFH requests
        direct_report_ids = [r['id'] for r in conn.execute(
            'SELECT id FROM employees WHERE reporting_to = ? AND is_active = 1', (user['id'],)
        ).fetchall()]
        if not direct_report_ids:
            flash('No team members to manage', 'error')
            conn.close()
            return redirect(url_for('dashboard'))
        placeholders = ','.join('?' * len(direct_report_ids))
        requests_list = conn.execute(f'''
            SELECT w.*, e.name, e.emp_code, e.department, a.name as approver_name
            FROM wfh_requests w
            JOIN employees e ON w.employee_id = e.id
            LEFT JOIN employees a ON w.approved_by = a.id
            WHERE w.employee_id IN ({placeholders})
            ORDER BY w.created_at DESC
        ''', direct_report_ids).fetchall()
    else:
        # Admin/management see all
        requests_list = conn.execute('''
            SELECT w.*, e.name, e.emp_code, e.department, a.name as approver_name
            FROM wfh_requests w
            JOIN employees e ON w.employee_id = e.id
            LEFT JOIN employees a ON w.approved_by = a.id
            ORDER BY w.created_at DESC
        ''').fetchall()

    conn.close()
    return render_template('wfh_approvals.html', user=user, requests=requests_list)


@app.route('/wfh/approve/<int:wfh_id>', methods=['POST'])
@login_required
def approve_wfh(wfh_id):
    user = get_user()
    action = request.form.get('action')  # 'approve' or 'reject'
    rejection_reason = request.form.get('rejection_reason', '').strip()

    conn = get_db()
    wfh = conn.execute('SELECT * FROM wfh_requests WHERE id = ?', (wfh_id,)).fetchone()
    if not wfh:
        flash('WFH request not found', 'error')
        conn.close()
        return redirect(url_for('wfh_approvals'))

    if wfh['status'] != 'pending':
        flash('This request has already been processed', 'error')
        conn.close()
        return redirect(url_for('wfh_approvals'))

    new_status = 'approved' if action == 'approve' else 'rejected'
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn.execute('''
        UPDATE wfh_requests SET status = ?, approved_by = ?, approved_at = ?, rejection_reason = ?
        WHERE id = ?
    ''', (new_status, user['id'], now, rejection_reason if action == 'reject' else None, wfh_id))

    # Notify the employee
    emp = conn.execute('SELECT name FROM employees WHERE id = ?', (wfh['employee_id'],)).fetchone()
    status_text = 'approved' if action == 'approve' else 'rejected'
    msg = f"Your WFH request ({wfh['from_date']} to {wfh['to_date']}) has been {status_text} by {user['name']}."
    if action == 'reject' and rejection_reason:
        msg += f" Reason: {rejection_reason}"
    conn.execute('''
        INSERT INTO notifications (type, title, message, target_user_id)
        VALUES ('wfh_update', ?, ?, ?)
    ''', (f"WFH Request {status_text.title()}", msg, wfh['employee_id']))

    conn.commit()
    conn.close()

    flash(f'WFH request {status_text}', 'success')
    return redirect(url_for('wfh_approvals'))


# ─── Projects Routes ───

@app.route('/projects')
@login_required
def projects_list():
    user = get_user()
    if not has_module_access(user, 'projects') and not user['is_admin']:
        # All employees can view projects, but only certain can manage
        pass
    conn = get_db()
    projects = conn.execute('''
        SELECT p.*, e.name as created_by_name,
               (SELECT COUNT(*) FROM products_services ps WHERE ps.project_id = p.id) as product_count
        FROM projects p
        LEFT JOIN employees e ON p.created_by = e.id
        ORDER BY p.status, p.name
    ''').fetchall()
    conn.close()
    return render_template('projects.html', user=user, projects=projects,
                         can_manage=has_module_access(user, 'projects') or user['is_admin'])


@app.route('/projects/add', methods=['GET', 'POST'])
@login_required
def add_project():
    user = get_user()
    if not has_module_access(user, 'projects') and not user['is_admin']:
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        if not name:
            flash('Project name is required', 'error')
            return redirect(url_for('add_project'))

        conn = get_db()
        conn.execute('INSERT INTO projects (name, description, created_by) VALUES (?, ?, ?)',
                    (name, description, user['id']))
        conn.commit()
        conn.close()
        flash('Project added successfully', 'success')
        return redirect(url_for('projects_list'))

    return render_template('add_project.html', user=user)


@app.route('/projects/<int:project_id>')
@login_required
def project_detail(project_id):
    user = get_user()
    conn = get_db()
    project = conn.execute('SELECT p.*, e.name as created_by_name FROM projects p LEFT JOIN employees e ON p.created_by = e.id WHERE p.id = ?', (project_id,)).fetchone()
    if not project:
        flash('Project not found', 'error')
        conn.close()
        return redirect(url_for('projects_list'))

    products = conn.execute('''
        SELECT ps.*, e.name as created_by_name
        FROM products_services ps
        LEFT JOIN employees e ON ps.created_by = e.id
        WHERE ps.project_id = ?
        ORDER BY ps.type, ps.name
    ''', (project_id,)).fetchall()

    conn.close()
    return render_template('project_detail.html', user=user, project=project, products=products,
                         can_manage=has_module_access(user, 'projects') or user['is_admin'])


@app.route('/projects/<int:project_id>/edit', methods=['POST'])
@login_required
def edit_project(project_id):
    user = get_user()
    if not has_module_access(user, 'projects') and not user['is_admin']:
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    status = request.form.get('status', 'active')

    conn = get_db()
    conn.execute('UPDATE projects SET name = ?, description = ?, status = ? WHERE id = ?',
                (name, description, status, project_id))
    conn.commit()
    conn.close()
    flash('Project updated', 'success')
    return redirect(url_for('project_detail', project_id=project_id))


# ─── Products & Services Routes ───

@app.route('/products/add/<int:project_id>', methods=['GET', 'POST'])
@login_required
def add_product(project_id):
    user = get_user()
    if not has_module_access(user, 'projects') and not user['is_admin']:
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))

    conn = get_db()
    project = conn.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone()
    if not project:
        flash('Project not found', 'error')
        conn.close()
        return redirect(url_for('projects_list'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        ps_type = request.form.get('type', 'product')

        if not name:
            flash('Name is required', 'error')
            conn.close()
            return redirect(url_for('add_product', project_id=project_id))

        conn.execute('''
            INSERT INTO products_services (name, description, type, project_id, created_by)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, description, ps_type, project_id, user['id']))
        conn.commit()
        conn.close()
        flash('Product/Service added', 'success')
        return redirect(url_for('project_detail', project_id=project_id))

    conn.close()
    return render_template('add_product.html', user=user, project=project)


@app.route('/products/<int:ps_id>/edit', methods=['POST'])
@login_required
def edit_product(ps_id):
    user = get_user()
    if not has_module_access(user, 'projects') and not user['is_admin']:
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))

    conn = get_db()
    ps = conn.execute('SELECT * FROM products_services WHERE id = ?', (ps_id,)).fetchone()
    if not ps:
        flash('Not found', 'error')
        conn.close()
        return redirect(url_for('projects_list'))

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    ps_type = request.form.get('type', ps['type'])
    status = request.form.get('status', ps['status'])

    conn.execute('UPDATE products_services SET name = ?, description = ?, type = ?, status = ? WHERE id = ?',
                (name, description, ps_type, status, ps_id))
    conn.commit()
    conn.close()
    flash('Updated successfully', 'success')
    return redirect(url_for('project_detail', project_id=ps['project_id']))


# ─── Sales News Routes ───

@app.route('/sales/news')
@login_required
@sales_access_required
def sales_news():
    user = get_user()
    conn = get_db()
    news = conn.execute('''
        SELECT n.*, e.name as posted_by_name, e.photo_url
        FROM sales_news n
        JOIN employees e ON n.posted_by = e.id
        WHERE n.is_active = 1
        ORDER BY n.created_at DESC
    ''').fetchall()
    conn.close()
    return render_template('sales_news.html', user=user, news=news,
                         can_post=user['is_admin'] or user['emp_code'] in MANAGEMENT_CODES)


@app.route('/sales/news/add', methods=['GET', 'POST'])
@login_required
@sales_access_required
def add_sales_news():
    user = get_user()
    if not user['is_admin'] and user['emp_code'] not in MANAGEMENT_CODES:
        flash('Only admin/management can post news', 'error')
        return redirect(url_for('sales_news'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        category = request.form.get('category', 'general')

        if not title or not content:
            flash('Title and content are required', 'error')
            return redirect(url_for('add_sales_news'))

        conn = get_db()
        conn.execute('INSERT INTO sales_news (title, content, category, posted_by) VALUES (?, ?, ?, ?)',
                    (title, content, category, user['id']))
        conn.commit()
        conn.close()
        flash('News posted', 'success')
        return redirect(url_for('sales_news'))

    return render_template('add_sales_news.html', user=user)


@app.route('/sales/news/delete/<int:news_id>', methods=['POST'])
@login_required
@sales_access_required
def delete_sales_news(news_id):
    user = get_user()
    if not user['is_admin'] and user['emp_code'] not in MANAGEMENT_CODES:
        flash('Access denied', 'error')
        return redirect(url_for('sales_news'))

    conn = get_db()
    conn.execute('UPDATE sales_news SET is_active = 0 WHERE id = ?', (news_id,))
    conn.commit()
    conn.close()
    flash('News removed', 'success')
    return redirect(url_for('sales_news'))


# ─── Sales Dashboard ───

@app.route('/sales')
@login_required
@sales_access_required
def sales_dashboard():
    user = get_user()
    conn = get_db()

    now = datetime.now()
    month_start = now.strftime('%Y-%m-01')
    month_end = now.strftime('%Y-%m-') + str(calendar.monthrange(now.year, now.month)[1])
    month_name = calendar.month_name[now.month]

    # Determine if user sees company-wide or personal view
    is_company_view = user['is_admin'] == 1 or user['emp_code'] in MANAGEMENT_CODES
    emp_filter = '' if is_company_view else ' AND t.employee_id = ?'
    emp_params = [] if is_company_view else [user['id']]

    # Recent news (always company-wide)
    recent_news = conn.execute('''
        SELECT n.*, e.name as posted_by_name, e.photo_url
        FROM sales_news n JOIN employees e ON n.posted_by = e.id
        WHERE n.is_active = 1
        ORDER BY n.created_at DESC LIMIT 5
    ''').fetchall()

    # Recent B2B trips (filtered for employees)
    recent_trips = conn.execute('''
        SELECT t.*, e.name as employee_name, e.photo_url as emp_photo, e.emp_code, p.name as project_name,
               (SELECT COUNT(*) FROM b2b_meetings m WHERE m.trip_id = t.id) as meeting_count
        FROM b2b_trips t
        JOIN employees e ON t.employee_id = e.id
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE 1=1''' + emp_filter + '''
        ORDER BY t.created_at DESC LIMIT 5
    ''', emp_params).fetchall()

    # Active projects count (company-wide, all can see)
    project_count = conn.execute("SELECT COUNT(*) as cnt FROM projects WHERE status = 'active'").fetchone()['cnt']

    # Total products/services count
    product_count = conn.execute("SELECT COUNT(*) as cnt FROM products_services").fetchone()['cnt']

    # Total trips count (filtered)
    if is_company_view:
        total_trips = conn.execute("SELECT COUNT(*) as cnt FROM b2b_trips").fetchone()['cnt']
        outstation_count = conn.execute("SELECT COUNT(*) as cnt FROM b2b_trips WHERE trip_type = 'outstation'").fetchone()['cnt']
        city_count = conn.execute("SELECT COUNT(*) as cnt FROM b2b_trips WHERE trip_type = 'city'").fetchone()['cnt']
    else:
        total_trips = conn.execute("SELECT COUNT(*) as cnt FROM b2b_trips WHERE employee_id = ?", (user['id'],)).fetchone()['cnt']
        outstation_count = conn.execute("SELECT COUNT(*) as cnt FROM b2b_trips WHERE trip_type = 'outstation' AND employee_id = ?", (user['id'],)).fetchone()['cnt']
        city_count = conn.execute("SELECT COUNT(*) as cnt FROM b2b_trips WHERE trip_type = 'city' AND employee_id = ?", (user['id'],)).fetchone()['cnt']

    # Meeting stats this month (filtered)
    if is_company_view:
        meeting_count = conn.execute('''
            SELECT COUNT(*) as cnt FROM b2b_meetings
            WHERE meeting_date >= ? AND meeting_date <= ?
        ''', (month_start, month_end)).fetchone()['cnt']
    else:
        meeting_count = conn.execute('''
            SELECT COUNT(*) as cnt FROM b2b_meetings m
            JOIN b2b_trips t ON m.trip_id = t.id
            WHERE m.meeting_date >= ? AND m.meeting_date <= ? AND t.employee_id = ?
        ''', (month_start, month_end, user['id'])).fetchone()['cnt']

    # Meeting type breakdown this month (filtered)
    if is_company_view:
        meeting_types = conn.execute('''
            SELECT mt.name, COUNT(m.id) as cnt
            FROM b2b_meetings m
            JOIN meeting_types mt ON m.meeting_type_id = mt.id
            WHERE m.meeting_date >= ? AND m.meeting_date <= ?
            GROUP BY mt.name ORDER BY cnt DESC
        ''', (month_start, month_end)).fetchall()
    else:
        meeting_types = conn.execute('''
            SELECT mt.name, COUNT(m.id) as cnt
            FROM b2b_meetings m
            JOIN meeting_types mt ON m.meeting_type_id = mt.id
            JOIN b2b_trips t ON m.trip_id = t.id
            WHERE m.meeting_date >= ? AND m.meeting_date <= ? AND t.employee_id = ?
            GROUP BY mt.name ORDER BY cnt DESC
        ''', (month_start, month_end, user['id'])).fetchall()

    # Top performers (always company-wide — everyone can see the leaderboard)
    top_performers = conn.execute('''
        SELECT e.name, e.photo_url, e.emp_code, COUNT(m.id) as meeting_count
        FROM b2b_meetings m
        JOIN b2b_trips t ON m.trip_id = t.id
        JOIN employees e ON t.employee_id = e.id
        WHERE m.meeting_date >= ? AND m.meeting_date <= ?
        GROUP BY e.id ORDER BY meeting_count DESC LIMIT 5
    ''', (month_start, month_end)).fetchall()

    # Active projects list (company-wide)
    active_projects = conn.execute('''
        SELECT p.*, (SELECT COUNT(*) FROM products_services ps WHERE ps.project_id = p.id) as product_count
        FROM projects p WHERE p.status = 'active' ORDER BY p.name LIMIT 6
    ''').fetchall()

    # Upcoming meetings (next 7 days, filtered)
    today_str = now.strftime('%Y-%m-%d')
    week_end = (now + timedelta(days=7)).strftime('%Y-%m-%d')
    if is_company_view:
        upcoming_meetings = conn.execute('''
            SELECT m.*, mt.name as type_name, e.name as emp_name, e.photo_url as emp_photo, t.trip_type
            FROM b2b_meetings m
            JOIN meeting_types mt ON m.meeting_type_id = mt.id
            JOIN b2b_trips t ON m.trip_id = t.id
            JOIN employees e ON t.employee_id = e.id
            WHERE m.meeting_date >= ? AND m.meeting_date <= ?
            ORDER BY m.meeting_date ASC LIMIT 8
        ''', (today_str, week_end)).fetchall()
    else:
        upcoming_meetings = conn.execute('''
            SELECT m.*, mt.name as type_name, e.name as emp_name, e.photo_url as emp_photo, t.trip_type
            FROM b2b_meetings m
            JOIN meeting_types mt ON m.meeting_type_id = mt.id
            JOIN b2b_trips t ON m.trip_id = t.id
            JOIN employees e ON t.employee_id = e.id
            WHERE m.meeting_date >= ? AND m.meeting_date <= ? AND t.employee_id = ?
            ORDER BY m.meeting_date ASC LIMIT 8
        ''', (today_str, week_end, user['id'])).fetchall()

    conn.close()
    return render_template('sales_dashboard.html', user=user,
                         recent_news=recent_news, recent_trips=recent_trips,
                         project_count=project_count, product_count=product_count,
                         total_trips=total_trips, meeting_count=meeting_count,
                         outstation_count=outstation_count, city_count=city_count,
                         meeting_types=meeting_types, top_performers=top_performers,
                         active_projects=active_projects, upcoming_meetings=upcoming_meetings,
                         month_name=month_name, current_year=now.year,
                         is_company_view=is_company_view)


# ─── B2B Meetings Routes ───

@app.route('/b2b')
@login_required
@sales_access_required
def b2b_trips_list():
    user = get_user()
    conn = get_db()

    trip_type = request.args.get('type', '')
    f_from = request.args.get('from_date', '')
    f_to = request.args.get('to_date', '')

    is_company_view = user['is_admin'] == 1 or user['emp_code'] in MANAGEMENT_CODES

    query = '''
        SELECT t.*, e.name as employee_name, e.emp_code, e.photo_url as emp_photo, p.name as project_name,
               t.meeting_category, (SELECT COUNT(*) FROM b2b_meetings m WHERE m.trip_id = t.id) as meeting_count
        FROM b2b_trips t
        JOIN employees e ON t.employee_id = e.id
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE 1=1
    '''
    params = []

    # Non-admin/non-management employees only see their own trips
    if not is_company_view:
        query += ' AND t.employee_id = ?'
        params.append(user['id'])

    if trip_type:
        query += ' AND t.trip_type = ?'
        params.append(trip_type)
    if f_from:
        query += ' AND t.from_date >= ?'
        params.append(f_from)
    if f_to:
        query += ' AND t.to_date <= ?'
        params.append(f_to)

    query += ' ORDER BY t.from_date DESC'
    trips = conn.execute(query, params).fetchall()
    conn.close()

    return render_template('meetings_list.html', user=user, trips=trips,
                         trip_type=trip_type, f_from=f_from, f_to=f_to,
                         is_company_view=is_company_view)


@app.route('/b2b/add', methods=['GET', 'POST'])
@login_required
@sales_access_required
def add_b2b_trip():
    user = get_user()
    conn = get_db()

    if request.method == 'POST':
        trip_type = request.form.get('trip_type')
        meeting_category = request.form.get('meeting_category', 'face_to_face')
        from_date = request.form.get('from_date')
        to_date = request.form.get('to_date')
        travel_date = request.form.get('travel_date', '')
        project_id = request.form.get('project_id') or None
        notes = request.form.get('notes', '').strip()

        if not from_date or not to_date:
            flash('From date and to date are required', 'error')
            projects = conn.execute("SELECT id, name FROM projects WHERE status = 'active' ORDER BY name").fetchall()
            meeting_clients = conn.execute("SELECT * FROM meeting_types WHERE is_active = 1 ORDER BY name").fetchall()
            conn.close()
            return render_template('add_meeting.html', user=user, projects=projects, meeting_clients=meeting_clients)

        conn.execute('''
            INSERT INTO b2b_trips (employee_id, trip_type, meeting_category, from_date, to_date, travel_date, project_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user['id'], trip_type, meeting_category, from_date, to_date, travel_date or None, project_id, notes))
        conn.commit()

        # Get the new trip ID
        trip = conn.execute('SELECT id FROM b2b_trips WHERE employee_id = ? ORDER BY id DESC LIMIT 1', (user['id'],)).fetchone()
        trip_id = trip['id']

        # Process multiple meetings
        meeting_dates = request.form.getlist('meeting_date[]')
        meeting_withs = request.form.getlist('meeting_with[]')
        meeting_type_ids = request.form.getlist('meeting_type_id[]')
        meeting_locations = request.form.getlist('meeting_location[]')
        meeting_contacts = request.form.getlist('contact_person[]')
        meeting_phones = request.form.getlist('contact_phone[]')
        meeting_project_ids = request.form.getlist('meeting_project_id[]')

        for i in range(len(meeting_dates)):
            if meeting_dates[i] and meeting_withs[i]:
                m_project_id = meeting_project_ids[i] if i < len(meeting_project_ids) and meeting_project_ids[i] else project_id
                m_type_id = meeting_type_ids[i] if i < len(meeting_type_ids) and meeting_type_ids[i] else None
                conn.execute('''
                    INSERT INTO b2b_meetings (trip_id, meeting_type_id, meeting_with, meeting_date, project_id, location, contact_person, contact_phone)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (trip_id, m_type_id, meeting_withs[i], meeting_dates[i],
                      m_project_id, meeting_locations[i] if i < len(meeting_locations) else '',
                      meeting_contacts[i] if i < len(meeting_contacts) else '',
                      meeting_phones[i] if i < len(meeting_phones) else ''))

        conn.commit()
        conn.close()
        flash('Meeting created successfully', 'success')
        return redirect(url_for('b2b_trip_detail', trip_id=trip_id))

    projects = conn.execute("SELECT id, name FROM projects WHERE status = 'active' ORDER BY name").fetchall()
    meeting_clients = conn.execute("SELECT * FROM meeting_types WHERE is_active = 1 ORDER BY name").fetchall()
    conn.close()
    return render_template('add_meeting.html', user=user, projects=projects, meeting_clients=meeting_clients)


@app.route('/b2b/<int:trip_id>')
@login_required
@sales_access_required
def b2b_trip_detail(trip_id):
    user = get_user()
    conn = get_db()
    trip = conn.execute('''
        SELECT t.*, e.name as employee_name, e.emp_code, p.name as project_name
        FROM b2b_trips t
        JOIN employees e ON t.employee_id = e.id
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE t.id = ?
    ''', (trip_id,)).fetchone()

    if not trip:
        flash('Trip not found', 'error')
        conn.close()
        return redirect(url_for('b2b_trips_list'))

    meetings = conn.execute('''
        SELECT m.*, mt.name as meeting_type_name, p.name as project_name
        FROM b2b_meetings m
        LEFT JOIN meeting_types mt ON m.meeting_type_id = mt.id
        LEFT JOIN projects p ON m.project_id = p.id
        WHERE m.trip_id = ?
        ORDER BY m.meeting_date, m.id
    ''', (trip_id,)).fetchall()

    meeting_clients = conn.execute("SELECT * FROM meeting_types WHERE is_active = 1 ORDER BY name").fetchall()
    projects = conn.execute("SELECT id, name FROM projects WHERE status = 'active' ORDER BY name").fetchall()

    conn.close()
    return render_template('meeting_detail.html', user=user, trip=trip, meetings=meetings, meeting_clients=meeting_clients, projects=projects)


@app.route('/b2b/<int:trip_id>/add-meeting', methods=['POST'])
@login_required
@sales_access_required
def add_meeting_to_trip(trip_id):
    user = get_user()
    conn = get_db()

    trip = conn.execute('SELECT * FROM b2b_trips WHERE id = ?', (trip_id,)).fetchone()
    if not trip:
        flash('Trip not found', 'error')
        conn.close()
        return redirect(url_for('b2b_trips_list'))

    meeting_date = request.form.get('meeting_date')
    meeting_with = request.form.get('meeting_with', '').strip()
    meeting_type_id = request.form.get('meeting_type_id') or None
    project_id = request.form.get('project_id') or trip['project_id']
    location = request.form.get('location', '').strip()
    contact_person = request.form.get('contact_person', '').strip()
    contact_phone = request.form.get('contact_phone', '').strip()

    if not meeting_date or not meeting_with:
        flash('Meeting date and name are required', 'error')
        conn.close()
        return redirect(url_for('b2b_trip_detail', trip_id=trip_id))

    conn.execute('''
        INSERT INTO b2b_meetings (trip_id, meeting_type_id, meeting_with, meeting_date, project_id, location, contact_person, contact_phone)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (trip_id, meeting_type_id, meeting_with, meeting_date, project_id, location, contact_person, contact_phone))
    conn.commit()
    conn.close()
    flash('Meeting added', 'success')
    return redirect(url_for('b2b_trip_detail', trip_id=trip_id))


@app.route('/b2b/meeting/<int:meeting_id>/outcome', methods=['POST'])
@login_required
@sales_access_required
def update_meeting_outcome(meeting_id):
    user = get_user()
    conn = get_db()

    meeting = conn.execute('SELECT * FROM b2b_meetings WHERE id = ?', (meeting_id,)).fetchone()
    if not meeting:
        flash('Meeting not found', 'error')
        conn.close()
        return redirect(url_for('b2b_trips_list'))

    outcome = request.form.get('outcome', '').strip()
    notes = request.form.get('notes', '').strip()

    conn.execute('UPDATE b2b_meetings SET outcome = ?, notes = ? WHERE id = ?',
                (outcome, notes, meeting_id))
    conn.commit()
    conn.close()
    flash('Meeting outcome updated', 'success')
    return redirect(url_for('b2b_trip_detail', trip_id=meeting['trip_id']))


# ─── Meeting Types Management (Admin) ───

@app.route('/admin/meeting-types', methods=['GET', 'POST'])
@admin_required
def manage_meeting_types():
    user = get_user()
    conn = get_db()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name', '').strip()
            if name:
                conn.execute('INSERT INTO meeting_types (name) VALUES (?)', (name,))
                conn.commit()
                flash('Meeting type added', 'success')
        elif action == 'toggle':
            mt_id = request.form.get('id')
            conn.execute('UPDATE meeting_types SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?', (mt_id,))
            conn.commit()
            flash('Meeting type updated', 'success')
        conn.close()
        return redirect(url_for('manage_meeting_types'))

    types = conn.execute('SELECT * FROM meeting_types ORDER BY name').fetchall()
    conn.close()
    return render_template('manage_meeting_types.html', user=user, types=types, page_title='Meeting Client Types')


# ─── Module Access Management (Admin) ───

@app.route('/admin/module-access', methods=['GET', 'POST'])
@admin_required
def manage_module_access():
    user = get_user()
    conn = get_db()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'grant':
            employee_ids = request.form.getlist('employee_ids')
            modules = request.form.getlist('modules')
            if employee_ids and modules:
                for emp_id in employee_ids:
                    for module in modules:
                        conn.execute('''
                            INSERT INTO module_access (employee_id, module, granted_by, is_active)
                            VALUES (?, ?, ?, 1)
                            ON CONFLICT (employee_id, module) DO UPDATE SET is_active = 1, granted_by = ?
                        ''', (emp_id, module, user['id'], user['id']))
                conn.commit()
                flash(f'Access granted to {len(employee_ids)} employee(s) for {len(modules)} module(s)', 'success')
            else:
                flash('Please select at least one employee and one module', 'error')

        elif action == 'toggle':
            access_id = request.form.get('access_id')
            new_status = request.form.get('new_status', '1')
            if access_id:
                conn.execute('UPDATE module_access SET is_active = ? WHERE id = ?', (int(new_status), access_id))
                conn.commit()
                flash('Access status updated', 'success')

        elif action == 'revoke':
            access_id = request.form.get('access_id')
            if access_id:
                conn.execute('DELETE FROM module_access WHERE id = ?', (access_id,))
                conn.commit()
                flash('Access revoked', 'success')

        conn.close()
        return redirect(url_for('manage_module_access'))

    employees = conn.execute("SELECT id, name, emp_code, department, photo_url FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY name").fetchall()
    access_list = conn.execute('''
        SELECT ma.id as access_id, ma.employee_id, ma.module, ma.is_active, ma.created_at,
               e.name, e.emp_code, e.department, e.photo_url,
               g.name as granted_by_name
        FROM module_access ma
        JOIN employees e ON ma.employee_id = e.id
        LEFT JOIN employees g ON ma.granted_by = g.id
        ORDER BY e.name, ma.module
    ''').fetchall()

    modules = ['sales', 'projects', 'b2b_meetings']
    conn.close()
    return render_template('manage_module_access.html', user=user, employees=employees,
                         access_list=access_list, modules=modules)


def ensure_management_admins():
    """Ensure MANAGEMENT_CODES employees always have is_admin = 1."""
    try:
        conn = get_db()
        for code in MANAGEMENT_CODES:
            conn.execute('UPDATE employees SET is_admin = 1 WHERE emp_code = ? AND is_admin = 0', (code,))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"ensure_management_admins: {e}")

# ─── Leave Applications (All) ─── Admin / Management view ───
@app.route('/admin/leave-applications')
@login_required
@admin_required
def admin_leave_applications():
    user = get_user()
    conn = get_db()

    # Read filter params
    f_employee = request.args.get('employee', '').strip()
    f_type = request.args.get('leave_type', '').strip()
    f_status = request.args.get('status', '').strip()
    f_from = request.args.get('from_date', '').strip()
    f_to = request.args.get('to_date', '').strip()

    # Build query
    query = '''
        SELECT lr.*, e.name, e.emp_code, e.department, e.photo_url
        FROM leave_records lr
        JOIN employees e ON lr.employee_id = e.id
        WHERE 1=1
    '''
    params = []

    if f_employee:
        query += " AND (LOWER(e.name) LIKE LOWER(?) OR LOWER(e.emp_code) LIKE LOWER(?))"
        params.extend([f'%{f_employee}%', f'%{f_employee}%'])
    if f_type:
        query += " AND lr.leave_type = ?"
        params.append(f_type)
    if f_status:
        query += " AND lr.status = ?"
        params.append(f_status)
    if f_from:
        query += " AND lr.leave_date >= ?"
        params.append(f_from)
    if f_to:
        query += " AND lr.leave_date <= ?"
        params.append(f_to)

    query += " ORDER BY lr.leave_date DESC, lr.created_at DESC"

    leaves = conn.execute(query, params).fetchall()

    # Get employee list for filter dropdown
    employees = conn.execute(
        "SELECT id, name, emp_code FROM employees WHERE is_active = 1 AND emp_code != 'admin' ORDER BY name"
    ).fetchall()

    # Summary counts
    total = len(leaves)
    pending_count = sum(1 for l in leaves if l['status'] == 'pending')
    approved_count = sum(1 for l in leaves if l['status'] == 'approved')
    rejected_count = sum(1 for l in leaves if l['status'] == 'rejected')

    conn.close()
    today_str = datetime.now().strftime('%Y-%m-%d')
    return render_template('admin_leave_applications.html',
        user=user, leaves=leaves, employees=employees,
        total=total, pending_count=pending_count,
        approved_count=approved_count, rejected_count=rejected_count,
        f_employee=f_employee, f_type=f_type, f_status=f_status,
        f_from=f_from, f_to=f_to, today=today_str)


# ─── My Leave Applications ─── Employee's own leaves ───
@app.route('/my-applications')
@login_required
def my_leave_applications():
    user = get_user()

    # Admin control account has no personal applications
    if user['emp_code'] == 'admin':
        return redirect(url_for('admin_leave_applications'))

    conn = get_db()

    f_type = request.args.get('leave_type', '').strip()
    f_status = request.args.get('status', '').strip()
    f_from = request.args.get('from_date', '').strip()
    f_to = request.args.get('to_date', '').strip()

    query = '''
        SELECT lr.*, e.name, e.emp_code, e.department
        FROM leave_records lr
        JOIN employees e ON lr.employee_id = e.id
        WHERE lr.employee_id = ?
    '''
    params = [user['id']]

    if f_type:
        query += " AND lr.leave_type = ?"
        params.append(f_type)
    if f_status:
        query += " AND lr.status = ?"
        params.append(f_status)
    if f_from:
        query += " AND lr.leave_date >= ?"
        params.append(f_from)
    if f_to:
        query += " AND lr.leave_date <= ?"
        params.append(f_to)

    query += " ORDER BY lr.leave_date DESC, lr.created_at DESC"

    leaves = conn.execute(query, params).fetchall()

    total = len(leaves)
    pending_count = sum(1 for l in leaves if l['status'] == 'pending')
    approved_count = sum(1 for l in leaves if l['status'] == 'approved')
    rejected_count = sum(1 for l in leaves if l['status'] == 'rejected')

    conn.close()
    today_str = datetime.now().strftime('%Y-%m-%d')
    return render_template('my_leave_applications.html',
        user=user, leaves=leaves,
        total=total, pending_count=pending_count,
        approved_count=approved_count, rejected_count=rejected_count,
        f_type=f_type, f_status=f_status,
        f_from=f_from, f_to=f_to, today=today_str)


# ─── Team Leave Applications ─── Manager view of team leaves ───
@app.route('/team-applications')
@login_required
def team_leave_applications():
    user = get_user()
    conn = get_db()

    # Check if user is a manager or management
    direct_reports = conn.execute(
        "SELECT id FROM employees WHERE reporting_to = ? AND is_active = 1",
        (user['id'],)
    ).fetchall()

    is_mgmt = user['emp_code'] in MANAGEMENT_CODES

    if not direct_reports and not is_mgmt:
        flash('You do not have team members to view', 'error')
        conn.close()
        return redirect(url_for('dashboard'))

    # Build list of viewable employee IDs
    viewable_ids = [r['id'] for r in direct_reports]

    # Management can also see other management members' leaves
    if is_mgmt:
        mgmt_employees = conn.execute(
            "SELECT id FROM employees WHERE emp_code IN ({})".format(
                ','.join('?' * len(MANAGEMENT_CODES))
            ), MANAGEMENT_CODES
        ).fetchall()
        for m in mgmt_employees:
            if m['id'] not in viewable_ids and m['id'] != user['id']:
                viewable_ids.append(m['id'])

    f_employee = request.args.get('employee', '').strip()
    f_type = request.args.get('leave_type', '').strip()
    f_status = request.args.get('status', '').strip()
    f_from = request.args.get('from_date', '').strip()
    f_to = request.args.get('to_date', '').strip()

    placeholders = ','.join('?' * len(viewable_ids))
    query = f'''
        SELECT lr.*, e.name, e.emp_code, e.department, e.photo_url
        FROM leave_records lr
        JOIN employees e ON lr.employee_id = e.id
        WHERE lr.employee_id IN ({placeholders})
    '''
    params = list(viewable_ids)

    if f_employee:
        query += " AND (LOWER(e.name) LIKE LOWER(?) OR LOWER(e.emp_code) LIKE LOWER(?))"
        params.extend([f'%{f_employee}%', f'%{f_employee}%'])
    if f_type:
        query += " AND lr.leave_type = ?"
        params.append(f_type)
    if f_status:
        query += " AND lr.status = ?"
        params.append(f_status)
    if f_from:
        query += " AND lr.leave_date >= ?"
        params.append(f_from)
    if f_to:
        query += " AND lr.leave_date <= ?"
        params.append(f_to)

    query += " ORDER BY lr.leave_date DESC, lr.created_at DESC"

    leaves = conn.execute(query, params).fetchall()

    # Get team member names for filter
    team_members = conn.execute(
        f"SELECT id, name, emp_code FROM employees WHERE id IN ({placeholders}) ORDER BY name",
        viewable_ids
    ).fetchall()

    total = len(leaves)
    pending_count = sum(1 for l in leaves if l['status'] == 'pending')
    approved_count = sum(1 for l in leaves if l['status'] == 'approved')
    rejected_count = sum(1 for l in leaves if l['status'] == 'rejected')

    conn.close()
    return render_template('team_leave_applications.html',
        user=user, leaves=leaves, team_members=team_members,
        total=total, pending_count=pending_count,
        approved_count=approved_count, rejected_count=rejected_count,
        f_employee=f_employee, f_type=f_type, f_status=f_status,
        f_from=f_from, f_to=f_to)


# Run on startup
ensure_crm_tables()
seed_default_meeting_types()
ensure_management_admins()

if __name__ == '__main__':
    PORT = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=PORT, debug=False)
