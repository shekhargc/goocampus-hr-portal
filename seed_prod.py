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

        # Insert employees
        employees_data = [
            ("Deepak Pandey", "deepak", 0, "deepak@goocampus.in", "Admin", "Senior Executive - Administration", "2020-05-01", admin_id),
            ("Harish", "harish", 12.5, "harish@goocampus.in", "Admin", "Office Assistant", "2020-11-09", admin_id),
            ("Robin", "robin", 0, "", "Sales", "", "", admin_id),
            ("Vipin Vijayaraghavan", "vipin", 0, "vipin@goocampus.in", "Operations", "Team Lead - Customer Success & Delivery", "2020-11-01", admin_id),
            ("Ralph Leander D'cruz", "ralph", 0, "ralph@goocampus.in", "Operations", "Customer Success Manager", "2021-08-01", 5),  # vipin id=5
            ("Poornima", "poornima", 0, "poornima@goocampus.in", "Admin", "Executive - Front Office", "2022-01-05", admin_id),
            ("Nandu C", "nandu", 9.5, "nandu@goocampus.in", "Marketing", "Senior Video Production Specialist", "2022-11-21", admin_id),
            ("Gopi", "gopi", 0, "", "Sales", "", "", admin_id),
            ("Jacob", "jacob", 0, "", "Operations", "", "", 5),  # vipin id=5
            ("Arun Kannan", "arun", 0, "arunkannan@goocampus.in", "Operations", "Customer Success Specialist", "2023-09-01", 5),  # vipin id=5
            ("Praveen L", "praveen", 4.5, "praveen@goocampus.in", "Marketing", "Senior Graphic Designer", "2024-02-01", admin_id),
            ("Alfiya", "alfiya", 0, "", "Operations", "", "", 5),  # vipin id=5
            ("Varsha M", "varsha", 0, "varsha.m@goocampus.in", "Operations", "Operations Executive", "2024-08-01", admin_id),
            ("Lanciya Lalu Philip", "lanciya", 0, "lanciya@goocampus.in", "Operations", "Business Development Executive", "2024-10-21", admin_id),
            ("Shaju", "shaju", 0, "", "Sales", "", "", admin_id),
            ("Manya BM", "manya", 3.0, "manya.bm@goocampus.in", "Marketing", "Content Writer", "2025-04-07", admin_id),
            ("Nikhil Shyamraj", "nikhil", 0, "nikhil.s@goocampus.in", "Marketing", "Content Creator & Video Editor", "2025-04-02", admin_id),
        ]

        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for name, emp_code, carry_forward, email, department, designation, joining_date, reporting_to in employees_data:
            c.execute('''
                INSERT INTO employees (name, emp_code, password, email, department, designation,
                                      carry_forward, joining_date, reporting_to, is_active, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s)
                ON CONFLICT (emp_code) DO NOTHING
            ''', (name, emp_code, hash_password(emp_code), email or None, department,
                  designation or None, carry_forward, joining_date or None, reporting_to, created_at))

        # Add management team
        management_data = [
            ("Ashwini Suryanarayana", "ashwini", "ashwini.s@goocampus.in", "Co-founder & CEO", "2018-01-01", admin_id),
            ("Santosh Shekhar", "santosh", "shekhar@goocampus.in", "Co-founder & COO", "2018-01-01", admin_id),
            ("Maheen Ejaz", "ejaz", "maheenejaz@goocampus.in", "Co-founder & CMO", "2018-01-01", admin_id),
        ]

        for name, emp_code, email, designation, joining_date, reporting_to in management_data:
            c.execute('''
                INSERT INTO employees (name, emp_code, password, email, department, designation,
                                      joining_date, reporting_to, is_active, carry_forward, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, 0, %s)
                ON CONFLICT (emp_code) DO NOTHING
            ''', (name, emp_code, hash_password(emp_code), email, "Management",
                  designation, joining_date, reporting_to, created_at))

        # Now update reporting_to relationships for employees based on new IDs
        # Get the actual IDs first
        c.execute('SELECT id FROM employees WHERE emp_code = %s', ('deepak',))
        deepak_id = c.fetchone()[0] if c.fetchone() else 2

        c.execute('SELECT id FROM employees WHERE emp_code = %s', ('santosh',))
        santosh_id = c.fetchone()[0] if c.fetchone() else 20

        c.execute('SELECT id FROM employees WHERE emp_code = %s', ('ashwini',))
        ashwini_id = c.fetchone()[0] if c.fetchone() else 19

        c.execute('SELECT id FROM employees WHERE emp_code = %s', ('ejaz',))
        ejaz_id = c.fetchone()[0] if c.fetchone() else 21

        c.execute('SELECT id FROM employees WHERE emp_code = %s', ('vipin',))
        vipin_id = c.fetchone()[0] if c.fetchone() else 5

        # Update reporting_to relationships
        reporting_updates = [
            ("deepak", deepak_id, admin_id),  # deepak reports to admin
            ("harish", harish_id, admin_id),  # harish reports to admin
            ("robin", robin_id, santosh_id),  # robin reports to santosh
            ("vipin", vipin_id, ashwini_id),  # vipin reports to ashwini
            ("ralph", ralph_id, vipin_id),  # ralph reports to vipin
            ("poornima", poornima_id, santosh_id),  # poornima reports to santosh
            ("nandu", nandu_id, ejaz_id),  # nandu reports to ejaz
            ("gopi", gopi_id, santosh_id),  # gopi reports to santosh
            ("jacob", jacob_id, vipin_id),  # jacob reports to vipin
            ("arun", arun_id, vipin_id),  # arun reports to vipin
            ("praveen", praveen_id, ejaz_id),  # praveen reports to ejaz
            ("alfiya", alfiya_id, vipin_id),  # alfiya reports to vipin
            ("varsha", varsha_id, santosh_id),  # varsha reports to santosh
            ("lanciya", lanciya_id, ashwini_id),  # lanciya reports to ashwini
            ("shaju", shaju_id, santosh_id),  # shaju reports to santosh
            ("manya", manya_id, ejaz_id),  # manya reports to ejaz
            ("nikhil", nikhil_id, ejaz_id),  # nikhil reports to ejaz
        ]

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
        print(f"All other employees: password = emp_code")
        return True

    except Exception as e:
        print(f"ERROR: Failed to seed database: {e}")
        return False


if __name__ == '__main__':
    success = seed_production_db()
    exit(0 if success else 1)
