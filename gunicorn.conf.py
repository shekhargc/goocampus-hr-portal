"""Gunicorn settings — read automatically from the project folder at start-up.

Render's start command (set in the Render dashboard) passes only --bind / --workers / --timeout, so this file
adds what it doesn't say.

threads (founder 2026-11-17, STAGING FIRST): each of the 2 workers handles several requests at once, so one slow
page (a big report / Excel export) no longer makes every other request — including doctors' mock-test autosaves —
wait behind it. Load test: autosaves went from 3–6 s back to 10–18 ms with 2 slow reports running
(docs/sections/mock-tests-load-test.md).

Instant way back without a code change: set GUNICORN_THREADS=1 in that service's Render → Environment
(the service restarts and runs one request per worker again, exactly as before).
"""
import os

try:
    threads = max(1, int(os.environ.get('GUNICORN_THREADS', '8')))
except ValueError:
    threads = 8
