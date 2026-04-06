"""
Production database seeding script for PostgreSQL.
Creates tables and seeds initial data for the Employee Dashboard.
"""
import os
import hashlib
from datetime import datetime


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def seed_production_db():
    """Seed the production PostgreSQL database."""
    database_url = os.environ.get('DATABASE_URL')

    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        return False

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2-binary is required. Install with: pip install psycopg2-binary")
        return False

    try:
        conn = psycopg2.connect(database_url)
        c = conn.cursor()

        # Create tables
        c.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                emp_code TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                carry_forward DOUBLE PRECISION DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                email TEXT,
                phone TEXT,
                dob TEXT,
                photo_url TEXT,
                employee_id_number TEXT,
                department TEXT,
                designation TEXT,
                joining_date TEXT,
                reporting_to INTEGER REFERENCES employees(id),
                emergency_contact_name TEXT,
                emergency_contact_phone TEXT,
                emergency_contact_relation TEXT,
                address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS leave_records (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                leave_type TEXT NOT NULL,
                leave_date TEXT NOT NULL,
                days DOUBLE PRECISION NOT NULL,
                day_portion TEXT DEFAULT 'full',
                reason TEXT,
                status TEXT DEFAULT 'pending',
                approved_by INTEGER REFERENCES employees(id),
                approved_at TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS holidays (
                id SERIAL PRIMARY KEY,
                holiday_date TEXT NOT NULL,
                name TEXT NOT NULL,
                holiday_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS announcements (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                posted_by INTEGER NOT NULL REFERENCES employees(id),
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                target_user_id INTEGER REFERENCES employees(id),
                target_role TEXT DEFAULT 'all',
                reference_id INTEGER,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Insert admin user
        admin_created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute('''
            INSERT INTO employees (name, emp_code, password, is_admin, department, is_active, created_at)
            VALUES (%s, %s, %s, 1, %s, 1, %s)
            ON CONFLICT (emp_code) DO NOTHING
        ''', ('Admin', 'admin', hash_password('admin'), 'Admin', admin_created_at))

        # Get admin id
        c.execute('SELECT id FROM employees WHERE emp_code = %s', ('admin',))
        admin_result = c.fetchone()
        admin_id = admin_result[0] if admin_result else 1

        # Insert employees with GC-format codes
        # Format: (full_name, emp_code, first_name_password, carry_forward, email, department, designation, joining_date)
        employees_data = [
            ("Santosh Shekhar", "GC001", "santosh", 0, "", "Management", "", ""),
            ("Ashwini S", "GC002", "ashwini", 0, "", "HR", "", ""),
            ("Maheen Ejaz", "GC003", "maheen", 0, "", "Marketing", "", ""),
            ("Robin Johnson", "GC006", "robin", 0, "", "Marketing", "", ""),
            ("Deepak Kumar Pandey", "GC011", "deepak", 0, "deepak@goocampus.in", "Admin", "Senior Executive - Administration", "2020-05-01"),
            ("Vipin Vijaya Raghavan", "GC012", "vipin", 0, "vipin@goocampus.in", "Operations", "Team Lead - Customer Success & Delivery", "2020-11-01"),
            ("Ralph Leander D Cruz", "GC021", "ralph", 0, "ralph@goocampus.in", "Operations", "Customer Success Manager", "2021-08-01"),
            ("Jeswin Jacob", "GC024", "jeswin", 0, "", "Marketing", "", ""),
            ("Gopi Krishnan A", "GC032", "gopi", 0, "", "Operations", "", ""),
            ("Poornima S", "GC033", "poornima", 0, "poornima@goocampus.in", "Admin", "Executive - Front Office", "2022-01-05"),
            ("Nandu C", "GC044", "nandu", 9.5, "nandu@goocampus.in", "Marketing", "Senior Video Production Specialist", "2022-11-21"),
            ("Harish S", "GC046", "harish", 12.5, "harish@goocampus.in", "Admin", "Office Assistant", "2020-11-09"),
            ("Jeswin Shaju", "GC050", "jeswin", 0, "", "Marketing", "", ""),
            ("Arun Kannan", "GC061", "arun", 0, "arunkannan@goocampus.in", "Operations", "Customer Success Specialist", "2023-09-01"),
            ("Praveen L", "GC067", "praveen", 4.5, "praveen@goocampus.in", "Marketing", "Senior Graphic Designer", "2024-02-01"),
            ("Varsha M", "GC074", "varsha", 0, "varsha.m@goocampus.in", "Operations", "Operations Executive", "2024-08-01"),
            ("Alfiya Naaz", "GC075", "alfiya", 0, "", "HR", "", ""),
            ("Lanciya Lulu Philip", "GC080", "lanciya", 0, "lanciya@goocampus.in", "Sales", "Business Development Executive", "2024-10-21"),
            ("Nikhil Shyamraj", "GC083", "nikhil", 0, "nikhil.s@goocampus.in", "Marketing", "Content Creator & Video Editor", "2025-04-02"),
            ("Manya B M", "GC092", "manya", 3.0, "manya.bm@goocampus.in", "Marketing", "Content Writer", "2025-04-07"),
        ]

        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for name, emp_code, first_name_pwd, carry_forward, email, department, designation, joining_date in employees_data:
            c.execute('''
                INSERT INTO employees (name, emp_code, password, email, department, designation,
                                      carry_forward, joining_date, reporting_to, is_active, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s)
                ON CONFLICT (emp_code) DO NOTHING
            ''', (name, emp_code, hash_password(first_name_pwd), email or None, department,
                  designation or None, carry_forward, joining_date or None, admin_id, created_at))

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
                VALUES (%s, %s, %s, %s)
            ''', (holiday_date, name, holiday_type, created_at))

        conn.commit()
        conn.close()

        print("Production database seeded successfully!")
        print(f"Admin user: emp_code='admin', password='admin'")
        print(f"All other employees: username = GC code, password = first name (lowercase)")
        return True

    except Exception as e:
        print(f"ERROR: Failed to seed database: {e}")
        return False


if __name__ == '__main__':
    success = seed_production_db()
    exit(0 if success else 1)
