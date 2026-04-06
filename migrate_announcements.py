import os
import sys

try:
    import psycopg2
except ImportError:
    print("Error: psycopg2 is not installed. Please install it with: pip install psycopg2-binary")
    sys.exit(1)

def migrate_announcements():
    """
    Creates the announcements table in the PostgreSQL production database.
    Connects using the DATABASE_URL environment variable.
    """
    database_url = os.getenv('DATABASE_URL')

    if not database_url:
        print("Error: DATABASE_URL environment variable is not set.")
        sys.exit(1)

    try:
        # Connect to the database
        conn = psycopg2.connect(database_url)
        cursor = conn.cursor()

        # Create the announcements table
        create_table_sql = '''
            CREATE TABLE IF NOT EXISTS announcements (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                posted_by INTEGER NOT NULL REFERENCES employees(id),
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        '''

        cursor.execute(create_table_sql)
        conn.commit()

        print("Success: announcements table created successfully in the production database.")

        cursor.close()
        conn.close()

    except psycopg2.OperationalError as e:
        print(f"Error: Failed to connect to the database. {e}")
        sys.exit(1)
    except psycopg2.ProgrammingError as e:
        print(f"Error: Failed to execute SQL command. {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: An unexpected error occurred. {e}")
        sys.exit(1)

if __name__ == '__main__':
    migrate_announcements()
