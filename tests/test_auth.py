"""Auth flow: login redirect, valid creds, invalid creds."""


def test_unauthenticated_root_redirects_to_login(client):
    resp = client.get('/')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_login_with_valid_credentials(client):
    resp = client.post(
        '/login',
        data={'username': 'admin', 'password': 'hunter2'},
        headers={'Origin': 'http://localhost', 'Referer': 'http://localhost/login'},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get('logged_in') is True


def test_login_with_wrong_password(client):
    resp = client.post(
        '/login',
        data={'username': 'admin', 'password': 'wrong'},
        headers={'Origin': 'http://localhost', 'Referer': 'http://localhost/login'},
    )
    assert resp.status_code == 200
    assert b'Invalid credentials' in resp.data
    with client.session_transaction() as sess:
        assert sess.get('logged_in') is not True


def test_login_with_unknown_user(client):
    resp = client.post(
        '/login',
        data={'username': 'nobody', 'password': 'hunter2'},
        headers={'Origin': 'http://localhost', 'Referer': 'http://localhost/login'},
    )
    assert resp.status_code == 200
    assert b'Invalid credentials' in resp.data


def test_logout_clears_session(logged_in_client):
    resp = logged_in_client.post(
        '/logout',
        headers={'Origin': 'http://localhost', 'Referer': 'http://localhost/'},
    )
    assert resp.status_code == 302
    with logged_in_client.session_transaction() as sess:
        assert sess.get('logged_in') is not True


def test_dashboard_blocked_when_logged_out(client):
    resp = client.get('/')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_dashboard_accessible_when_logged_in(logged_in_client):
    resp = logged_in_client.get('/')
    assert resp.status_code == 200
