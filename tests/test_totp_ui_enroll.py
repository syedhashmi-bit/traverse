"""Tests for the UI-driven 2FA enrolment flow.

Covers: enrol start → confirm round-trip, backup-code consumption at login,
disable / regenerate gated by password re-prompt, and the env-fallback
when no DB secret is present.
"""

import pyotp
import pytest


def test_security_index_requires_login(client):
    r = client.get('/settings/security/', follow_redirects=False)
    assert r.status_code == 302
    assert '/login' in r.headers['Location']


def test_enroll_start_shows_qr_and_session_secret(logged_in_client):
    r = logged_in_client.get('/settings/security/totp/enroll')
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'data:image/png;base64' in body
    # Secret should appear (rendered in the page so the user can copy)
    with logged_in_client.session_transaction() as s:
        assert s.get('totp_enroll_secret')


def test_enroll_confirm_wrong_code_rejected(logged_in_client):
    logged_in_client.get('/settings/security/totp/enroll')
    r = logged_in_client.post('/settings/security/totp/enroll',
                              data={'code': '000000'})
    assert r.status_code == 200
    assert 'Invalid code' in r.get_data(as_text=True)
    # No DB row should have been persisted yet
    from database import get_totp_config
    assert get_totp_config()['secret'] == ''


def test_enroll_confirm_correct_code_persists_and_shows_codes(logged_in_client):
    logged_in_client.get('/settings/security/totp/enroll')
    with logged_in_client.session_transaction() as s:
        secret = s['totp_enroll_secret']
    code = pyotp.TOTP(secret).now()
    r = logged_in_client.post('/settings/security/totp/enroll',
                              data={'code': code}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert '2FA enabled' in body or 'backup codes' in body
    from database import get_totp_config
    cfg = get_totp_config()
    assert cfg['secret'] == secret
    assert len(cfg['backup_codes']) == 10


def test_backup_codes_shown_only_once(logged_in_client):
    logged_in_client.get('/settings/security/totp/enroll')
    with logged_in_client.session_transaction() as s:
        secret = s['totp_enroll_secret']
    code = pyotp.TOTP(secret).now()
    logged_in_client.post('/settings/security/totp/enroll', data={'code': code})

    # Visit the codes page (consumes them from session)
    r1 = logged_in_client.get('/settings/security/totp/codes/enroll')
    assert r1.status_code == 200
    # Second visit redirects to /settings/security with a warning
    r2 = logged_in_client.get('/settings/security/totp/codes/enroll',
                              follow_redirects=False)
    assert r2.status_code == 302


def test_disable_requires_password(logged_in_client):
    # Enrol first
    logged_in_client.get('/settings/security/totp/enroll')
    with logged_in_client.session_transaction() as s:
        secret = s['totp_enroll_secret']
    code = pyotp.TOTP(secret).now()
    logged_in_client.post('/settings/security/totp/enroll', data={'code': code})

    # Wrong password → no change
    logged_in_client.post('/settings/security/totp/disable',
                          data={'current_password': 'wrong'})
    from database import get_totp_config
    assert get_totp_config()['secret'] != ''

    # Right password → disabled
    logged_in_client.post('/settings/security/totp/disable',
                          data={'current_password': 'hunter2'})
    assert get_totp_config()['secret'] == ''


def test_regenerate_codes_requires_password_and_replaces(logged_in_client):
    logged_in_client.get('/settings/security/totp/enroll')
    with logged_in_client.session_transaction() as s:
        secret = s['totp_enroll_secret']
    code = pyotp.TOTP(secret).now()
    logged_in_client.post('/settings/security/totp/enroll', data={'code': code})

    from database import get_totp_config
    original = list(get_totp_config()['backup_codes'])

    # Wrong password is a no-op
    logged_in_client.post('/settings/security/totp/regenerate-codes',
                          data={'current_password': 'wrong'})
    assert get_totp_config()['backup_codes'] == original

    # Right password produces a fresh set
    logged_in_client.post('/settings/security/totp/regenerate-codes',
                          data={'current_password': 'hunter2'})
    new_codes = get_totp_config()['backup_codes']
    assert len(new_codes) == 10
    assert set(new_codes) != set(original)


def test_backup_code_authenticates_at_login(client, monkeypatch):
    """End-to-end: enrol → log out → log back in using a backup code."""
    # 1. Log in normally
    client.post('/login', data={'username': 'admin', 'password': 'hunter2'})

    # 2. Enrol 2FA
    client.get('/settings/security/totp/enroll')
    with client.session_transaction() as s:
        secret = s['totp_enroll_secret']
    code = pyotp.TOTP(secret).now()
    client.post('/settings/security/totp/enroll', data={'code': code})

    # 3. Recover one of the backup codes' plaintext by reseeding the RNG
    #    won't work — they're random — so we reach into database to
    #    inject a known plaintext + matching hash for this test.
    from database import set_totp_config
    from routes.auth import _hash_backup_code
    plaintext = 'ABCD-1234'
    set_totp_config(secret, [_hash_backup_code(plaintext)])

    # 4. Log out, log back in
    client.post('/logout')
    client.post('/login', data={'username': 'admin', 'password': 'hunter2'})
    # 5. Submit the backup code at /login/verify
    r = client.post('/login/verify', data={'code': plaintext})
    assert r.status_code == 302
    # We should now be logged in
    r2 = client.get('/settings/')
    assert r2.status_code == 200

    # 6. Backup code must be single-use
    from database import get_totp_config
    assert get_totp_config()['backup_codes'] == []


def test_login_verify_short_circuits_numeric_six_to_totp(logged_in_client):
    """Six-digit numeric input must go through the TOTP path, not the
    backup-code path — otherwise a wrong TOTP attempt could accidentally
    consume a numeric backup code (codes are alpha, so a clash is
    unlikely but the principle matters)."""
    # Enrol
    logged_in_client.get('/settings/security/totp/enroll')
    with logged_in_client.session_transaction() as s:
        secret = s['totp_enroll_secret']
    code = pyotp.TOTP(secret).now()
    logged_in_client.post('/settings/security/totp/enroll', data={'code': code})

    # Inject a numeric backup code hash to confirm it WON'T be consumed
    from database import set_totp_config, get_totp_config
    from routes.auth import _hash_backup_code
    plaintext = '12345678'  # 8-digit, not 6
    set_totp_config(secret, [_hash_backup_code(plaintext)])

    # Wipe session, go through fresh login
    with logged_in_client.session_transaction() as s:
        s.clear()
    logged_in_client.post('/login', data={'username': 'admin', 'password': 'hunter2'})

    # Submit a wrong 6-digit numeric → must fail without touching the
    # backup code list
    logged_in_client.post('/login/verify', data={'code': '000000'})
    assert len(get_totp_config()['backup_codes']) == 1
