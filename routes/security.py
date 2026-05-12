"""Account security: DB-backed 2FA enrolment with backup codes.

The legacy env-based `TOTP_SECRET` path keeps working as a read-only fallback
(see `routes/auth.py._get_totp_secret`), but the canonical setup flow lives
here. State-changing endpoints (`disable`, `regenerate-codes`, even re-enrol
while already enrolled) all require a fresh password re-confirmation, so a
session left open on a shared device can't lose 2FA without the password.
"""
import base64
import hmac
import io
import os
import secrets
import string

import pyotp
import qrcode
from flask import (
    Blueprint, abort, flash, redirect, render_template, request, session, url_for,
)
from dotenv import load_dotenv

load_dotenv()

from routes.auth import (
    login_required, _client_ip, _hash_backup_code,
)

security_bp = Blueprint('security', __name__, url_prefix='/settings/security')


_BACKUP_CODE_ALPHABET = string.ascii_uppercase + string.digits
_BACKUP_CODE_COUNT    = 10
_BACKUP_CODE_LEN      = 8   # group of 4 + 4 displayed as XXXX-XXXX


def _generate_backup_codes():
    """Return (display_codes, hashes). 10 codes, 8 uppercase alnum chars each.
    Displayed with a mid-dash for readability; storage is sha256-hashed."""
    plain = [
        ''.join(secrets.choice(_BACKUP_CODE_ALPHABET) for _ in range(_BACKUP_CODE_LEN))
        for _ in range(_BACKUP_CODE_COUNT)
    ]
    display = [c[:4] + '-' + c[4:] for c in plain]
    hashes  = [_hash_backup_code(c) for c in plain]
    return display, hashes


def _password_ok(supplied: str) -> bool:
    """Constant-time compare against ADMIN_PASSWORD."""
    expected = os.getenv('ADMIN_PASSWORD', '')
    return hmac.compare_digest(
        (supplied or '').encode('utf-8'),
        expected.encode('utf-8'),
    )


def _qr_b64(secret: str) -> str:
    """Render an otpauth:// URI as base64 PNG for the enrol page."""
    totp = pyotp.TOTP(secret)
    uri  = totp.provisioning_uri(name='admin', issuer_name='Traverse VPN')
    img  = qrcode.make(uri)
    buf  = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


@security_bp.route('/')
@login_required
def index():
    from database import get_totp_config
    cfg = get_totp_config()
    env_secret_present = bool(os.getenv('TOTP_SECRET', '').strip())
    return render_template(
        'security/index.html',
        enrolled            = bool(cfg.get('secret')),
        enrolled_at         = cfg.get('enrolled_at'),
        codes_remaining     = len(cfg.get('backup_codes') or []),
        env_legacy_active   = env_secret_present and not cfg.get('secret'),
    )


# ── Enrol: two-step (start → confirm) ────────────────────────────────────────

@security_bp.route('/totp/enroll', methods=['GET'])
@login_required
def enroll_totp_start():
    # Fresh secret each visit, stashed in the session so a refresh doesn't
    # reset enrolment progress mid-flow. Only persisted to DB on confirm.
    secret = session.get('totp_enroll_secret')
    if not secret:
        secret = pyotp.random_base32()
        session['totp_enroll_secret'] = secret
    return render_template(
        'security/enroll.html',
        secret = secret,
        qr_b64 = _qr_b64(secret),
        error  = None,
    )


@security_bp.route('/totp/enroll', methods=['POST'])
@login_required
def enroll_totp_confirm():
    secret = session.get('totp_enroll_secret', '')
    if not secret:
        flash('Enrolment session expired — start again.', 'error')
        return redirect(url_for('security.enroll_totp_start'))

    code = (request.form.get('code', '') or '').strip().replace(' ', '')
    totp = pyotp.TOTP(secret)
    if not (code.isdigit() and len(code) == 6 and totp.verify(code, valid_window=1)):
        return render_template(
            'security/enroll.html',
            secret = secret,
            qr_b64 = _qr_b64(secret),
            error  = 'Invalid code — try again.',
        )

    display_codes, hashes = _generate_backup_codes()
    from database import set_totp_config, audit
    set_totp_config(secret, hashes)
    session.pop('totp_enroll_secret', None)
    audit('security.totp_enrolled', actor_ip=_client_ip())
    try:
        from notifications import send_notification
        send_notification(
            'totp_enrolled',
            f'🔐 2FA enrolled on traverse (IP `{_client_ip()}`)',
            severity='info',
        )
    except Exception:
        pass

    # Stash codes for one-shot display — the next view consumes & clears them.
    session['totp_codes_to_show'] = display_codes
    return redirect(url_for('security.show_backup_codes', context='enroll'))


@security_bp.route('/totp/codes/<context>')
@login_required
def show_backup_codes(context):
    codes = session.pop('totp_codes_to_show', None)
    if not codes:
        # Stale link / refresh after close — nothing left to reveal.
        flash('Backup codes are only shown once. Regenerate to see new ones.', 'warning')
        return redirect(url_for('security.index'))
    return render_template(
        'security/backup_codes.html',
        codes   = codes,
        context = context if context in ('enroll', 'regenerate') else 'enroll',
    )


# ── Regenerate backup codes ──────────────────────────────────────────────────

@security_bp.route('/totp/regenerate-codes', methods=['POST'])
@login_required
def regenerate_codes():
    if not _password_ok(request.form.get('current_password', '')):
        flash('Password incorrect — backup codes were not regenerated.', 'error')
        return redirect(url_for('security.index'))
    from database import get_totp_config, replace_backup_codes, audit
    if not get_totp_config().get('secret'):
        flash('2FA is not enrolled.', 'error')
        return redirect(url_for('security.index'))
    display_codes, hashes = _generate_backup_codes()
    replace_backup_codes(hashes)
    audit('security.backup_codes_regenerated', actor_ip=_client_ip())
    session['totp_codes_to_show'] = display_codes
    return redirect(url_for('security.show_backup_codes', context='regenerate'))


# ── Disable ──────────────────────────────────────────────────────────────────

@security_bp.route('/totp/disable', methods=['POST'])
@login_required
def disable_totp():
    if not _password_ok(request.form.get('current_password', '')):
        flash('Password incorrect — 2FA was not disabled.', 'error')
        return redirect(url_for('security.index'))
    from database import clear_totp_config, audit
    clear_totp_config()
    audit('security.totp_disabled', actor_ip=_client_ip())
    try:
        from notifications import send_notification
        send_notification(
            'totp_disabled',
            f'⚠️ 2FA was disabled on traverse (IP `{_client_ip()}`)',
            severity='warning',
        )
    except Exception:
        pass
    flash('2FA disabled.', 'success')
    return redirect(url_for('security.index'))
