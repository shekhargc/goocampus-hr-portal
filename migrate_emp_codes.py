"""
Migration script to update employee codes to GC-format and passwords to first names.
Run this against the production PostgreSQL database.
"""
import os
import hashlib


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def migrate():
    database_url = os.environ.get('DATABASE_URL')

    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        return False

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2-binary is required")
        return False

    try:
        conn = psycopg2.connect(database_url)
        c = conn.cursor()

        # Mapping: old_emp_code -> (new_emp_code, new_name, first_name_password)
        updates = [
            ("santosh", "GC001", "Santosh Shekhar", "santosh"),
            ("ashwini", "GC002", "Ashwini S", "ashwini"),
            ("ejaz", "GC003", "Maheen Ejaz", "maheen"),
            ("robin", "GC006", "Robin Johnson", "robin"),
            ("deepak", "GC011", "Deepak Kumar Pandey", "deepak"),
            ("vipin", "GC012", "Vipin Vijaya Raghavan", "vipin"),
            ("ralph", "GC021", "Ralph Leander D Cruz", "ralph"),
            ("jacob", "GC024", "Jeswin Jacob", "jeswin"),
            ("gopi", "GC032", "Gopi Krishnan A", "gopi"),
            ("poornima", "GC033", "Poornima S", "poornima"),
            ("nandu", "GC044", "Nandu C", "nandu"),
            ("harish", "GC046", "Harish S", "harish"),
            ("shaju", "GC050", "Jeswin Shaju", "jeswin"),
            ("arun", "GC061", "Arun Kannan", "arun"),
            ("praveen", "GC067", "Praveen L", "praveen"),
            ("varsha", "GC074", "Varsha M", "varsha"),
            ("alfiya", "GC075", "Alfiya Naaz", "alfiya"),
            ("lanciya", "GC080", "Lanciya Lulu Philip", "lanciya"),
            ("nikhil", "GC083", "Nikhil Shyamraj", "nikhil"),
            ("manya", "GC092", "Manya B M", "manya"),
        ]

        updated = 0
        for old_code, new_code, new_name, first_name in updates:
            c.execute(
                'UPDATE employees SET emp_code = %s, name = %s, password = %s WHERE emp_code = %s',
                (new_code, new_name, hash_password(first_name), old_code)
            )
            if c.rowcount > 0:
                print(f"  Updated: {old_code} -> {new_code} ({new_name})")
                updated += 1
            else:
                print(f"  Not found: {old_code} (skipped)")

        conn.commit()
        conn.close()

        print(f"\nMigration complete! Updated {updated} employees.")
        print("Login: username = employee code (e.g. GC011), password = first name (e.g. deepak)")
        return True

    except Exception as e:
        print(f"ERROR: Migration failed: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False


if __name__ == '__main__':
    success = migrate()
    exit(0 if success else 1)
