"""
CRM Migration Script - Adds new tables for WFH, Projects, Products/Services,
Sales News, B2B Meetings, Meeting Types, and Module Access.
Run this once on the production database.
"""
import os
import sys
from datetime import datetime


def run_migration():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        return False

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2-binary required")
        return False

    try:
        conn = psycopg2.connect(database_url)
        c = conn.cursor()

        # 1. WFH Requests
        c.execute('''
            CREATE TABLE IF NOT EXISTS wfh_requests (
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
            )
        ''')

        # 2. Projects
        c.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'active',
                created_by INTEGER REFERENCES employees(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 3. Products & Services (linked to projects)
        c.execute('''
            CREATE TABLE IF NOT EXISTS products_services (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                type TEXT NOT NULL DEFAULT 'product',
                project_id INTEGER REFERENCES projects(id),
                status TEXT DEFAULT 'active',
                created_by INTEGER REFERENCES employees(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 4. Sales News
        c.execute('''
            CREATE TABLE IF NOT EXISTS sales_news (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                posted_by INTEGER NOT NULL REFERENCES employees(id),
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 5. Meeting Types (admin-configurable)
        c.execute('''
            CREATE TABLE IF NOT EXISTS meeting_types (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 6. B2B Meetings (parent record for a trip/visit)
        c.execute('''
            CREATE TABLE IF NOT EXISTS b2b_trips (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                trip_type TEXT NOT NULL,
                from_date TEXT NOT NULL,
                to_date TEXT NOT NULL,
                travel_date TEXT,
                project_id INTEGER REFERENCES projects(id),
                notes TEXT,
                status TEXT DEFAULT 'planned',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 7. B2B Meeting entries (multiple meetings per trip)
        c.execute('''
            CREATE TABLE IF NOT EXISTS b2b_meetings (
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
            )
        ''')

        # 8. Module Access (admin grants specific users access to modules)
        c.execute('''
            CREATE TABLE IF NOT EXISTS module_access (
                id SERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                module TEXT NOT NULL,
                granted_by INTEGER REFERENCES employees(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(employee_id, module)
            )
        ''')

        # Seed default meeting types
        default_types = ['School', 'College', 'Partner', 'Branch Partner', 'Agent']
        for mt in default_types:
            c.execute('''
                INSERT INTO meeting_types (name) VALUES (%s)
                ON CONFLICT (name) DO NOTHING
            ''', (mt,))

        # Grant Sales department employees access to sales module by default
        c.execute('''
            SELECT id FROM employees WHERE department = 'Sales' AND is_active = 1
        ''')
        sales_employees = c.fetchall()
        for emp in sales_employees:
            c.execute('''
                INSERT INTO module_access (employee_id, module)
                VALUES (%s, 'sales')
                ON CONFLICT (employee_id, module) DO NOTHING
            ''', (emp[0],))

        # Grant management access to all modules
        c.execute('''
            SELECT id FROM employees WHERE emp_code IN ('GC001', 'GC002', 'GC003')
        ''')
        mgmt_employees = c.fetchall()
        for emp in mgmt_employees:
            for module in ['sales', 'projects', 'b2b_meetings']:
                c.execute('''
                    INSERT INTO module_access (employee_id, module)
                    VALUES (%s, %s)
                    ON CONFLICT (employee_id, module) DO NOTHING
                ''', (emp[0], module))

        conn.commit()
        conn.close()
        print("Migration completed successfully!")
        print(f"Tables created: wfh_requests, projects, products_services, sales_news, meeting_types, b2b_trips, b2b_meetings, module_access")
        print(f"Default meeting types seeded: {', '.join(default_types)}")
        return True

    except Exception as e:
        print(f"ERROR: Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = run_migration()
    sys.exit(0 if success else 1)
