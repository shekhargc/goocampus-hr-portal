"""
Migration script to create the notifications table in production PostgreSQL.
Run this on Render Shell: python migrate_notifications.py
"""
import os
import psycopg2

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set. Run this on Render Shell.")
    exit(1)

conn = psycopg2.connect(DATABASE_URL)
c = conn.cursor()

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

# Create index for fast lookups
c.execute('''
    CREATE INDEX IF NOT EXISTS idx_notifications_target
    ON notifications(target_user_id, is_read, created_at DESC)
''')

c.execute('''
    CREATE INDEX IF NOT EXISTS idx_notifications_role
    ON notifications(target_role, is_read, created_at DESC)
''')

conn.commit()
conn.close()

print("SUCCESS: notifications table created with indexes.")
