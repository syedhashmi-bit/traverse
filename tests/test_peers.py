"""Peer CRUD round-trip with a stubbed wg CLI."""


def _create_peer(client, name='test-peer'):
    return client.post(
        f'/peers/create',
        data={
            'name': name,
            'dns': '1.1.1.1',
            'endpoint': 'test.example',
            'tunnel_mode': 'full',
            'device': 'laptop',
        },
        headers={'Origin': 'http://localhost', 'Referer': 'http://localhost/peers/create'},
        follow_redirects=False,
    )


def test_peers_page_renders_when_logged_in(logged_in_client):
    resp = logged_in_client.get('/peers/')
    assert resp.status_code == 200


def test_create_peer_persists_to_db(logged_in_client):
    resp = _create_peer(logged_in_client, 'laptop-1')
    assert resp.status_code == 302, resp.data
    from database import get_peer_by_name
    peer = get_peer_by_name('laptop-1')
    assert peer is not None
    assert peer['public_key'].startswith('pub-')


def test_create_peer_with_invalid_name_is_rejected(logged_in_client):
    resp = _create_peer(logged_in_client, 'bad name with spaces')
    assert resp.status_code == 302  # redirect back to create form
    from database import get_peer_by_name
    assert get_peer_by_name('bad name with spaces') is None


def test_create_peer_with_injection_attempt_is_rejected(logged_in_client):
    resp = _create_peer(logged_in_client, 'evil; rm -rf /')
    assert resp.status_code == 302
    from database import get_peer_by_name
    assert get_peer_by_name('evil; rm -rf /') is None


def test_duplicate_peer_name_is_rejected(logged_in_client):
    _create_peer(logged_in_client, 'dup')
    resp = _create_peer(logged_in_client, 'dup')
    assert resp.status_code == 302
    # Still only one row.
    from database import get_all_peers
    names = [p['name'] for p in get_all_peers()]
    assert names.count('dup') == 1


def test_peer_cap_enforced(logged_in_client, monkeypatch):
    """Lower the cap and confirm the (cap+1)th create is rejected."""
    import wireguard
    import routes.peers as peers_route
    import routes.dashboard as dashboard_route
    monkeypatch.setattr(wireguard, 'MAX_PEERS', 2)
    monkeypatch.setattr(peers_route, 'MAX_PEERS', 2)
    monkeypatch.setattr(dashboard_route, 'MAX_PEERS', 2)

    assert _create_peer(logged_in_client, 'p1').status_code == 302
    assert _create_peer(logged_in_client, 'p2').status_code == 302
    resp = _create_peer(logged_in_client, 'p3')
    assert resp.status_code == 302
    from database import get_peer_by_name
    assert get_peer_by_name('p3') is None, 'peer above cap should not have been created'
