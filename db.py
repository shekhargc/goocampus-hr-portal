"""
Database abstraction layer for Flask app.
Supports both SQLite (local development) and PostgreSQL (production).
"""
import os
import re
import sqlite3


class CursorWrapper:
    """Wraps a cursor to provide dict-like row access for both SQLite and PostgreSQL."""

    def __init__(self, cursor, is_postgres=False):
        self.cursor = cursor
        self.is_postgres = is_postgres

    def fetchone(self):
        """Fetch one row and ensure it's dict-accessible."""
        row = self.cursor.fetchone()
        if row is None:
            return None
        # Both psycopg2 RealDictCursor and sqlite3.Row support dict-like access
        return row

    def fetchall(self):
        """Fetch all rows."""
        return self.cursor.fetchall()


class DatabaseConnection:
    """Wrapper providing a consistent interface for SQLite and PostgreSQL."""

    def __init__(self, conn, is_postgres=False):
        self.conn = conn
        self.is_postgres = is_postgres
        self.last_cursor = None

    def execute(self, sql, params=None):
        """Execute SQL, converting placeholders and syntax as needed."""
        if params is None:
            params = ()

        # Convert SQL based on database type
        if self.is_postgres:
            sql = self._convert_to_postgres(sql)

        cursor = self.conn.cursor()
        cursor.execute(sql, params)
        self.last_cursor = CursorWrapper(cursor, self.is_postgres)
        return self.last_cursor

    def _convert_to_postgres(self, sql):
        """Convert SQLite SQL syntax to PostgreSQL."""
        # Convert ? placeholders to %s
        sql = sql.replace('?', '%s')

        # Convert strftime functions
        # strftime('%Y', column) or strftime('%Y', table.column) -> TO_CHAR(column::date, 'YYYY')
        sql = re.sub(
            r"strftime\('%Y',\s*([\w.]+)\)",
            r"TO_CHAR(\1::date, 'YYYY')",
            sql
        )

        # strftime('%m', column) or strftime('%m', table.column) -> TO_CHAR(column::date, 'MM')
        sql = re.sub(
            r"strftime\('%m',\s*([\w.]+)\)",
            r"TO_CHAR(\1::date, 'MM')",
            sql
        )

        # strftime('%d', column) or strftime('%d', table.column) -> TO_CHAR(column::date, 'DD')
        sql = re.sub(
            r"strftime\('%d',\s*([\w.]+)\)",
            r"TO_CHAR(\1::date, 'DD')",
            sql
        )

        return sql

    def commit(self):
        """Commit the transaction."""
        self.conn.commit()

    def close(self):
        """Close the connection."""
        self.conn.close()


def get_db():
    """
    Get database connection based on environment.
    Returns a DatabaseConnection that handles both SQLite and PostgreSQL.
    """
    database_url = os.environ.get('DATABASE_URL')

    if database_url:
        # Use PostgreSQL
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError:
            raise ImportError("psycopg2-binary is required for PostgreSQL support. "
                            "Install it with: pip install psycopg2-binary")

        conn = psycopg2.connect(database_url)
        # Set cursor factory to return dicts
        conn.cursor_factory = RealDictCursor
        return DatabaseConnection(conn, is_postgres=True)
    else:
        # Use SQLite
        db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "leave_manager.db"
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return DatabaseConnection(conn, is_postgres=False)
