"""
WSGI entrypoint for production servers (gunicorn on Render). `app.py`'s
schema init only runs under `if __name__ == "__main__"`, which gunicorn
never triggers since it imports the module rather than executing it directly
-- so it's done here instead, once, before the app is handed to the server.
"""

from app import app, init_db

init_db()
