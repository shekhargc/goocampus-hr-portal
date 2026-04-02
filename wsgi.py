"""
WSGI entry point for PythonAnywhere.
This file tells PythonAnywhere how to run the app.
"""

import sys
import os

# Add project folder to Python path
project_home = os.path.dirname(os.path.abspath(__file__))
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set the database path explicitly
os.environ['DB_PATH'] = os.path.join(project_home, 'leave_manager.db')

from app import app as application

# Initialize the database on first run
from app import init_db
init_db()
