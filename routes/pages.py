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
        user = User.get_by_passcode(passcode)
        if user:
            session.permanent = True
            session['logged_in'] = True
            session['user_id'] = user['id']
            session['user_role'] = user['role']
            return redirect(url_for('pages.index'))
        else:
            flash('Invalid passcode')
    return render_template('login.html')

@pages_bp.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('pages.login'))

