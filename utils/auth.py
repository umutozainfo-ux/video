from functools import wraps
from flask import session, redirect, url_for, request, jsonify

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api'):
                return jsonify({'error': 'Unauthorized'}), 401
            return redirect(url_for('pages.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function
