import base64
import hmac
import io
import os
import threading
import time
from functools import wraps

import pyotp
import qrcode
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, abort,
)
from dotenv import load_dotenv

load_dotenv()

auth_bp = Blueprint('auth', __name__)


# ── Brute-force throttle ──────────────────────────────────────────────────────
# In-memory per-IP failure counter with sliding window. Survives single-process
# restarts only — fine for a 2-worker gunicorn admin tool with one operator.
# Locks the bucket per IP to keep increments correct under concurrency.
_FAIL_LIMIT  = 5            # consecutive failures before lockout kicks in
_FAIL_WINDOW = 15 * 60      # window over which failures count (seconds)
_LOCK_BACKOFF = 60          # base lockout in seconds; doubles per extra fail
_fail_lock = threading.Lock()
_fail_state = {}            # ip -> {'fails': [ts, ...], 'locked_until': ts}


def _record_failure(ip):
    now = time.time()
    with _fail_lock:
        s = _fail_state.setdefault(ip, {'fails': [], 'locked_until': 0.0})
        s['fails'] = [t for t in s['fails'] if now - t < _FAIL_WINDOW]
        s['fails'].append(now)
        if len(s['fails']) >= _FAIL_LIMIT:
            extra = len(s['fails']) - _FAIL_LIMIT
            s['locked_until'] = now + _LOCK_BACKOFF * (2 ** extra)


def _record_success(ip):
    with _fail_lock:
        _fail_state.pop(ip, None)


def _seconds_locked(ip):
    now = time.time()
    with _fail_lock:
        s = _fail_state.get(ip)
        if not s:
            return 0
        remaining = int(s['locked_until'] - now)
        return remaining if remaining > 0 else 0


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
    ip = _client_ip()

    if request.method == 'POST':
        locked = _seconds_locked(ip)
        if locked:
            error = f'Too many failed attempts. Try again in {locked}s.'
            return render_template(
                'login.html',
                error    = error,
                next_url = request.args.get('next', ''),
            ), 429

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
            next_url = _safe_next(
                request.form.get('next') or request.args.get('next')
            )
            session.clear()
            session.permanent = True
            if _get_totp() is None:
                # No TOTP secret configured — skip 2FA
                session['logged_in'] = True
                _record_success(ip)
                _notify_login_success()
                try:
                    from database import audit
                    audit('auth.login_success', actor_ip=ip)
                except Exception:
                    pass
                return redirect(next_url)
            session['totp_pending'] = True
            session['totp_next'] = next_url
            return redirect(url_for('auth.verify_totp'))

        _record_failure(ip)
        _notify_login_failed(username)
        try:
            from database import audit
            audit('auth.login_failed', actor_ip=ip,
                  details=f'username={username!r}' if username else None)
        except Exception:
            pass
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
    ip = _client_ip()

    if request.method == 'POST':
        locked = _seconds_locked(ip)
        if locked:
            error = f'Too many failed attempts. Try again in {locked}s.'
            return render_template('totp_verify.html', error=error), 429

        code = request.form.get('code', '').strip().replace(' ', '')
        totp = _get_totp()
        # valid_window=1 accepts one step before/after for clock skew
        if totp and totp.verify(code, valid_window=1):
            next_url = session.pop('totp_next', '/')
            session['totp_pending'] = False
            session['logged_in'] = True
            session.permanent = True
            _record_success(ip)
            _notify_login_success()
            try:
                from database import audit
                audit('auth.login_success', actor_ip=ip, details='totp')
            except Exception:
                pass
            return redirect(_safe_next(next_url))
        _record_failure(ip)
        _notify_login_failed('totp')
        try:
            from database import audit
            audit('auth.login_failed', actor_ip=ip, details='totp')
        except Exception:
            pass
        error = 'Invalid code. Try again.'

    return render_template('totp_verify.html', error=error)


# ── TOTP setup / QR display ───────────────────────────────────────────────────

@auth_bp.route('/totp-setup')
def totp_setup():
    # Only fully authenticated admins can view the TOTP secret/QR. The
    # earlier `totp_pending` gate let anyone with just the password fetch
    # the seed and forever bypass 2FA.
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    secret = os.getenv('TOTP_SECRET', '')
    if not secret:
        abort(404)
    totp   = pyotp.TOTP(secret)
    uri    = totp.provisioning_uri(name='admin', issuer_name='Traverse VPN')

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return render_template('totp_setup.html', secret=secret, qr_b64=qr_b64)


# ── Logout ────────────────────────────────────────────────────────────────────

@auth_bp.route('/logout', methods=['POST'])
def logout():
    try:
        from database import audit
        audit('auth.logout', actor_ip=_client_ip())
    except Exception:
        pass
    session.clear()
    return redirect(url_for('auth.login'))
