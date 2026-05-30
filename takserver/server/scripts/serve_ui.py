import os
import sys

from flask import send_from_directory
from flask_security.signals import user_registered

sys.path.insert(0, '/usr/local/lib/python3.11/site-packages')

from opentakserver.app import create_app, main

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'frontend')

app = create_app(cli=False)

@app.route('/')
def serve_index():
    return send_from_directory(FRONTEND_DIR, 'index.html')

@app.route('/assets/<path:path>')
def serve_assets(path):
    return send_from_directory(os.path.join(FRONTEND_DIR, 'assets'), path)

@app.route('/locales/<path:path>')
def serve_locales(path):
    return send_from_directory(os.path.join(FRONTEND_DIR, 'locales'), path)

@app.route('/map_icons/<path:path>')
def serve_map_icons(path):
    return send_from_directory(os.path.join(FRONTEND_DIR, 'map_icons'), path)

@app.route('/<path:path>')
def serve_frontend(path):
    file_path = os.path.join(FRONTEND_DIR, path)
    if os.path.exists(file_path) and not os.path.isdir(file_path):
        return send_from_directory(FRONTEND_DIR, path)
    return send_from_directory(FRONTEND_DIR, 'index.html')

@user_registered.connect_via(app)
def user_registered_sighandler(app, user, confirmation_token, **kwargs):
    from opentakserver.models.role import Role
    from opentakserver.models.user import User
    default_role = app.security.datastore.find_or_create_role(
        name="user", permissions={"user-read", "user-write"}
    )
    app.security.datastore.add_role_to_user(user, default_role)

main(app)
