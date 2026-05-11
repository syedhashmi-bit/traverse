"""TOTP 2FA flow: password step → code step → success / failure."""

import pyotp
import pytest


# Use a deterministic base32 secret across all tests in this file.
_TOTP_SECRET = 'JBSWY3DPEHPK3PXP'


@pytest.fixture
def totp_app(monkeypatch):
    """A fresh app that has TOTP enabled — overrides the conftest default
    of TOTP_SECRET='' so the verify step is actually exercised."""
    monkeypatch.setenv('TOTP_SECRET', _TOTP_SECRET)

    # Force the auth module to re-read env. routes/auth.py reads TOTP_SECRET
    # inside _get_totp() at call time, so an env update is enough — no reload
    # needed. But the conftest already imported the app factory chain, so we
    # build a fresh app here.
    import alerts, importlib, wireguard
    monkeypatch.setattr(alerts, 'start_alerts', lambda: None)
    importlib.reload(wireguard)

    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    app.config['SESSION_COOKIE_SECURE'] = False
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    return app


@pytest.fixture
def totp_client(totp_app):
    return totp_app.test_client()


def _hdrs(path='/login'):
    return {'Origin': 'http://localhost', 'Referer': f'http://localhost{path}'}


def test_password_step_redirects_to_totp_when_enabled(totp_client):
    resp = totp_client.post(
        '/login',
        data={'username': 'admin', 'password': 'hunter2'},
        headers=_hdrs(),
    )
    assert resp.status_code == 302
    assert '/login/verify' in resp.headers['Location']
    # Must NOT be logged in yet — only `totp_pending` should be set.
    with totp_client.session_transaction() as sess:
        assert sess.get('logged_in') is not True
        assert sess.get('totp_pending') is True


def test_totp_verify_with_correct_code_grants_session(totp_client):
    totp_client.post(
        '/login',
        data={'username': 'admin', 'password': 'hunter2'},
        headers=_hdrs(),
    )
    code = pyotp.TOTP(_TOTP_SECRET).now()
    resp = totp_client.post(
        '/login/verify',
        data={'code': code},
        headers=_hdrs('/login/verify'),
    )
    assert resp.status_code == 302
    with totp_client.session_transaction() as sess:
        assert sess.get('logged_in') is True
        assert sess.get('totp_pending') is False


def test_totp_verify_with_wrong_code_keeps_session_pending(totp_client):
    totp_client.post(
        '/login',
        data={'username': 'admin', 'password': 'hunter2'},
        headers=_hdrs(),
    )
    resp = totp_client.post(
        '/login/verify',
        data={'code': '000000'},
        headers=_hdrs('/login/verify'),
    )
    assert resp.status_code == 200
    assert b'Invalid code' in resp.data
    with totp_client.session_transaction() as sess:
        assert sess.get('logged_in') is not True


def test_totp_verify_unreachable_without_password_step(totp_client):
    """Going directly to /login/verify without completing the password
    step must redirect back to /login — no shortcut around the first
    factor."""
    resp = totp_client.get('/login/verify')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_totp_setup_page_requires_full_login(totp_client):
    """The TOTP enrol page must NOT be reachable with only `totp_pending`
    — a partial-auth attacker shouldn't be able to read the seed."""
    with totp_client.session_transaction() as sess:
        sess['totp_pending'] = True
    resp = totp_client.get('/totp-setup')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_totp_setup_visible_to_fully_logged_in_admin(totp_client):
    with totp_client.session_transaction() as sess:
        sess['logged_in'] = True
    resp = totp_client.get('/totp-setup')
    assert resp.status_code == 200
    # QR <img data-uri> should appear on the page.
    assert b'data:image/png;base64' in resp.data or b'qr' in resp.data.lower()
