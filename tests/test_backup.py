"""Backup export safety: never leak private keys."""

import json


def test_backup_export_strips_private_key(logged_in_client, monkeypatch):
    """Create a peer with a known key, then export — the key MUST NOT
    appear anywhere in the JSON body. Multiple backup users have been
    bitten by this kind of leak; the assertion is a tripwire."""
    # routes.peers grabbed generate_keypair by name at import; patch the
    # local binding rather than wireguard.generate_keypair. The conftest
    # already patches both, but we override here so the keys are
    # deterministic sentinels we can grep for in the backup body.
    import routes.peers as peers_route
    monkeypatch.setattr(
        peers_route, 'generate_keypair',
        lambda: ('PRIVATE-KEY-SENTINEL-XYZZY',
                 'PUBLIC-KEY-SENTINEL',
                 'PSK-SENTINEL-ABCDE'),
    )

    logged_in_client.post(
        '/peers/create',
        data={
            'name': 'backup-test',
            'dns': '1.1.1.1',
            'endpoint': 'test.example',
            'tunnel_mode': 'full',
            'device': 'laptop',
        },
        headers={'Origin': 'http://localhost', 'Referer': 'http://localhost/peers/create'},
    )

    resp = logged_in_client.get('/settings/backup/export')
    assert resp.status_code == 200

    body = resp.data.decode('utf-8')
    assert 'PRIVATE-KEY-SENTINEL-XYZZY' not in body, \
        'private_key MUST NOT appear in backup export'
    assert 'PSK-SENTINEL-ABCDE' not in body, \
        'preshared_key MUST NOT appear in backup export'

    parsed = json.loads(body)
    assert parsed['peers'], 'peer should still be in the export, just without secrets'
    for p in parsed['peers']:
        assert 'private_key' not in p
        assert 'preshared_key' not in p
    assert parsed['peers'][0]['public_key'] == 'PUBLIC-KEY-SENTINEL'
