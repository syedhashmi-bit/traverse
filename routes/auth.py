import base64
import hmac
import io
import os
from functools import wraps

import pyotp
import qrcode
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session,
)
from dotenv import load_dotenv

load_dotenv()

auth_bp = Blueprint('auth', __name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_next(target):
    """Accept only relative paths — blocks open-redirect attacks."""
    if target and target.startswith('/') and not target.startswith('//'):
        return target
    return url_for('dashboard.index')


def _get_totp():
    secret = os.getenv('TOTP_SECRET', '')
    return pyotp.TOTP(secret) if secret else None


def _client_ip():
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def _notify_login_success():
    try:
        from notifications import send_notification
        send_notification(
            'login_success',
            f'🔐 Someone logged into traverse dashboard (IP `{_client_ip()}`)',
            severity='info',
        )
    except Exception:
        pass


def _notify_login_failed(who):
    try:
        from notifications import send_notification
        send_notification(
            'login_failed',
            f'🚫 Failed login attempt on traverse dashboard (IP `{_client_ip()}`)',
            severity='warning',
        )
    except Exception:
        pass


# ── Decorator ─────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('auth.login', next=request.path))
        return f(*args, **kwargs)
    return decorated


# ── Step 1: username + password ───────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard.index'))

    error = None

    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        expected_user = os.getenv('ADMIN_USERNAME', '')
        expected_pass = os.getenv('ADMIN_PASSWORD', '')

        # hmac.compare_digest prevents timing-based enumeration
        user_match = hmac.compare_digest(
            username.encode('utf-8'),
            expected_user.encode('utf-8'),
        )
        pass_match = hmac.compare_digest(
            password.encode('utf-8'),
            expected_pass.encode('utf-8'),
        )

        if user_match and pass_match:
            session.permanent = False
            session.clear()
            next_url = _safe_next(
                request.form.get('next') or request.args.get('next')
            )
            if _get_totp() is None:
                # No TOTP secret configured — skip 2FA
                session['logged_in'] = True
                _notify_login_success()
                return redirect(next_url)
            session['totp_pending'] = True
            session['totp_next'] = next_url
            return redirect(url_for('auth.verify_totp'))

        _notify_login_failed(username)
        error = 'Invalid credentials.'

    return render_template(
        'login.html',
        error    = error,
        next_url = request.args.get('next', ''),
    )


# ── Step 2: TOTP code ─────────────────────────────────────────────────────────

@auth_bp.route('/login/verify', methods=['GET', 'POST'])
def verify_totp():
    if not session.get('totp_pending'):
        return redirect(url_for('auth.login'))
    if session.get('logged_in'):
        return redirect(url_for('dashboard.index'))

    error = None

    if request.method == 'POST':
        code = request.form.get('code', '').strip().replace(' ', '')
        totp = _get_totp()
        # valid_window=1 accepts one step before/after for clock skew
        if totp and totp.verify(code, valid_window=1):
            next_url = session.pop('totp_next', '/')
            session['totp_pending'] = False
            session['logged_in'] = True
            _notify_login_success()
            return redirect(_safe_next(next_url))
        _notify_login_failed('totp')
        error = 'Invalid code. Try again.'

    return render_template('totp_verify.html', error=error)


# ── TOTP setup / QR display ───────────────────────────────────────────────────

@auth_bp.route('/totp-setup')
def totp_setup():
    # Accessible right after password check (totp_pending) or when already in
    if not session.get('logged_in') and not session.get('totp_pending'):
        return redirect(url_for('auth.login'))

    secret = os.getenv('TOTP_SECRET', '')
    totp   = pyotp.TOTP(secret)
    uri    = totp.provisioning_uri(name='admin', issuer_name='Traverse VPN')

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return render_template('totp_setup.html', secret=secret, qr_b64=qr_b64)


# ── Logout ────────────────────────────────────────────────────────────────────

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
