from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from utils.auth import login_required
from config import Config

from database.models import User

pages_bp = Blueprint('pages', __name__)

@pages_bp.route('/')
@login_required
def index():
    """Main page"""
    return render_template('index.html', user_role=session.get('user_role'))

@pages_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        passcode = request.form.get('password')
        from flask import current_app
        import json
        import os
        
        current_app.logger.info(f"Login attempt with passcode: {passcode[:2]}***")
        
        # 1. Priority check: admin_config.json
        config_path = os.path.join(os.getcwd(), 'admin_config.json')
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    admin_passcode = config.get('admin_passcode')
                    if admin_passcode and passcode == admin_passcode:
                        # Find the admin user in DB to get the ID, or create a mock session
                        user = User.get_by_passcode(passcode)
                        if not user:
                            # If for some reason user isn't in DB, try getting by username
                            from database.schema import get_db_manager
                            db = get_db_manager()
                            row = db.execute_query("SELECT * FROM users WHERE username = 'admin'", fetch_one=True)
                            user = dict(row) if row else None
                        
                        if user:
                            current_app.logger.info(f"Verified admin via JSON config")
                            session.permanent = True
                            session['logged_in'] = True
                            session['user_id'] = user['id']
                            session['user_role'] = user['role']
                            return redirect(url_for('pages.index'))
            except Exception as e:
                current_app.logger.error(f"Error checking admin_config.json during login: {e}")

        # 2. Regular check: Database
        user = User.get_by_passcode(passcode)
        if user:
            current_app.logger.info(f"Login successful for user: {user['username']}")
            session.permanent = True
            session['logged_in'] = True
            session['user_id'] = user['id']
            session['user_role'] = user['role']
            return redirect(url_for('pages.index'))
        else:
            current_app.logger.warning("Login failed: Invalid passcode")
            flash('Invalid passcode')
    return render_template('login.html')

@pages_bp.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('pages.login'))

