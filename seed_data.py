import os
import sqlite3
import hashlib
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leave_manager.db")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    # Remove existing database to start fresh
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Create tables
    c.execute('''
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            emp_code TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            carry_forward REAL DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            email TEXT,
            phone TEXT,
            dob TEXT,
            photo_url TEXT,
            employee_id_number TEXT,
            department TEXT,
            designation TEXT,
            joining_date TEXT,
            reporting_to INTEGER,
            emergency_contact_name TEXT,
            emergency_contact_phone TEXT,
            emergency_contact_relation TEXT,
            address TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE leave_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            leave_type TEXT NOT NULL,
            leave_date TEXT NOT NULL,
            days REAL NOT NULL,
            day_portion TEXT DEFAULT 'full',
            reason TEXT,
            status TEXT DEFAULT 'pending',
            approved_by INTEGER,
            approved_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees(id),
            FOREIGN KEY (approved_by) REFERENCES employees(id)
        )
    ''')

    c.execute('''
        CREATE TABLE holidays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            holiday_date TEXT NOT NULL,
            name TEXT NOT NULL,
            holiday_type TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Insert admin user
    admin_created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute('''
        INSERT INTO employees (name, emp_code, password, is_admin, department, is_active, created_at)
        VALUES (?, ?, ?, 1, ?, 1, ?)
    ''', ('Admin', 'admin', hash_password('admin'), 'Admin', admin_created_at))

    admin_id = c.lastrowid

    # Insert employees with Airtable-verified data
    # Format: (full_name, emp_code, carry_forward, email, department, designation, joining_date)
    employees_data = [
        ("Deepak Pandey", "deepak", 0, "deepak@goocampus.in", "Admin", "Senior Executive - Administration", "2020-05-01"),
        ("Harish", "harish", 12.5, "harish@goocampus.in", "Admin", "Office Assistant", "2020-11-09"),
        ("Robin", "robin", 0, "", "Marketing", "", ""),
        ("Vipin Vijayaraghavan", "vipin", 0, "vipin@goocampus.in", "Operations", "Team Lead - Customer Success & Delivery", "2020-11-01"),
        ("Ralph Leander D'cruz", "ralph", 0, "ralph@goocampus.in", "Operations", "Customer Success Manager", "2021-08-01"),
        ("Poornima", "poornima", 0, "poornima@goocampus.in", "Admin", "Executive - Front Office", "2022-01-05"),
        ("Nandu C", "nandu", 9.5, "nandu@goocampus.in", "Marketing", "Senior Video Production Specialist", "2022-11-21"),
        ("Gopi", "gopi", 0, "", "Operations", "", ""),
        ("Jacob", "jacob", 0, "", "Marketing", "", ""),
        ("Arun Kannan", "arun", 0, "arunkannan@goocampus.in", "Operations", "Customer Success Specialist", "2023-09-01"),
        ("Praveen L", "praveen", 4.5, "praveen@goocampus.in", "Marketing", "Senior Graphic Designer", "2024-02-01"),
        ("Alfiya", "alfiya", 0, "", "HR", "", ""),
        ("Varsha M", "varsha", 0, "varsha.m@goocampus.in", "Operations", "Operations Executive", "2024-08-01"),
        ("Lanciya Lalu Philip", "lanciya", 0, "lanciya@goocampus.in", "Sales", "Business Development Executive", "2024-10-21"),
        ("Shaju", "shaju", 0, "", "Marketing", "", ""),
        ("Manya BM", "manya", 3.0, "manya.bm@goocampus.in", "Marketing", "Content Writer", "2025-04-07"),
        ("Nikhil Shyamraj", "nikhil", 0, "nikhil.s@goocampus.in", "Marketing", "Content Creator & Video Editor", "2025-04-02"),
    ]

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for name, emp_code, carry_forward, email, department, designation, joining_date in employees_data:
        c.execute('''
            INSERT INTO employees (name, emp_code, password, email, department, designation, carry_forward, joining_date, reporting_to, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ''', (name, emp_code, hash_password(emp_code), email or None, department, designation or None, carry_forward, joining_date or None, admin_id, created_at))

    # Insert holidays for 2026
    holidays_data = [
        ("2026-01-01", "New Year's Day", "Festival"),
        ("2026-01-15", "Makar Sankranti/Magh Bihu/Pongal", "Festival"),
        ("2026-01-26", "Republic Day", "National"),
        ("2026-03-19", "Ugadi / Gudhi Padwa", "Festival"),
        ("2026-03-20", "Id-ul-Fitr (Ramzan)", "Festival"),
        ("2026-04-03", "Good Friday", "Festival"),
        ("2026-05-01", "May Day", "National"),
        ("2026-05-27", "Bakrid", "Festival"),
        ("2026-09-14", "Ganesh Chaturthi", "Festival"),
        ("2026-10-02", "Gandhi Jayanthi", "National"),
        ("2026-10-20", "Dusshera", "National"),
        ("2026-12-25", "Christmas Day", "Festival"),
    ]

    for holiday_date, name, holiday_type in holidays_data:
        c.execute('''
            INSERT INTO holidays (holiday_date, name, holiday_type, created_at)
            VALUES (?, ?, ?, ?)
        ''', (holiday_date, name, holiday_type, created_at))

    conn.commit()
    conn.close()

    print(f"Database initialized at {DB_PATH}")
    print("Admin user created: emp_code='admin', password='admin'")
    print("17 employees created with password = emp_code")
    print("12 holidays for 2026 created")

if __name__ == '__main__':
    init_db()
