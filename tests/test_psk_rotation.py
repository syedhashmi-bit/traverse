"""POST /peers/<id>/rotate-psk: replace PSK, keep keypair, re-sync wg0."""


def _create(logged_in_client, name='psk-test'):
    return logged_in_client.post(
        '/peers/create',
        data={'name': name, 'dns': '1.1.1.1', 'endpoint': 'test.example',
              'tunnel_mode': 'full', 'device': 'laptop'},
        headers={'Origin': 'http://localhost', 'Referer': 'http://localhost/peers/create'},
    )


def test_rotate_psk_changes_only_psk(logged_in_client, monkeypatch):
    import routes.peers as peers_route
    # Deterministic key generation so we can compare before/after.
    monkeypatch.setattr(peers_route, 'generate_keypair',
                        lambda: ('PRIV-ORIG', 'PUB-ORIG', 'PSK-ORIG'))
    # First call (in /peers/create) returns ORIG; rotate_psk uses
    # generate_preshared_key separately.
    monkeypatch.setattr(peers_route, 'generate_preshared_key',
                        lambda: 'PSK-ROTATED')

    _create(logged_in_client, 'p1')
    from database import get_peer_by_name
    before = get_peer_by_name('p1')
    pid = before['id']
    assert before['preshared_key'] == 'PSK-ORIG'

    resp = logged_in_client.post(
        f'/peers/{pid}/rotate-psk',
        headers={'Origin': 'http://localhost', 'Referer': f'http://localhost/peers/{pid}'},
    )
    assert resp.status_code == 302

    after = get_peer_by_name('p1')
    assert after['preshared_key'] == 'PSK-ROTATED'
    # Keypair MUST be unchanged.
    assert after['public_key'] == before['public_key']
    assert after['private_key'] == before['private_key']
    assert after['config_regenerated_at'], \
        'rotation should bump config_regenerated_at so the UI surfaces it'


def test_rotate_psk_resyncs_wg_with_new_key(logged_in_client, monkeypatch):
    """The DB update must be paired with a wg0 re-add using the new PSK."""
    calls = []

    def _add(pub, psk, ip, mode, routes):
        calls.append({'pub': pub, 'psk': psk, 'ip': ip})

    import routes.peers as peers_route
    monkeypatch.setattr(peers_route, 'add_peer_to_interface', _add)
    monkeypatch.setattr(peers_route, 'generate_preshared_key',
                        lambda: 'NEW-PSK-XYZ')

    _create(logged_in_client, 'p2')
    from database import get_peer_by_name
    peer = get_peer_by_name('p2')

    calls.clear()
    logged_in_client.post(
        f'/peers/{peer["id"]}/rotate-psk',
        headers={'Origin': 'http://localhost', 'Referer': 'http://localhost/'},
    )
    assert len(calls) == 1
    assert calls[0]['psk'] == 'NEW-PSK-XYZ'
    assert calls[0]['pub'] == peer['public_key']


def test_rotate_psk_404_on_missing_peer(logged_in_client):
    resp = logged_in_client.post(
        '/peers/99999/rotate-psk',
        headers={'Origin': 'http://localhost', 'Referer': 'http://localhost/'},
    )
    assert resp.status_code == 404


def test_rotate_psk_requires_login(client):
    resp = client.post(
        '/peers/1/rotate-psk',
        headers={'Origin': 'http://localhost', 'Referer': 'http://localhost/'},
    )
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
