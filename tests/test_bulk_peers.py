"""Bulk peer actions: /peers/bulk-disable | bulk-enable | bulk-delete."""


def _hdrs():
    return {'Origin': 'http://localhost', 'Referer': 'http://localhost/peers/'}


def _make_peers(client, n):
    """Create n peers via the form path; return their IDs in order."""
    ids = []
    for i in range(n):
        client.post(
            '/peers/create',
            data={'name': f'b{i}', 'dns': '1.1.1.1',
                  'endpoint': 'test.example', 'tunnel_mode': 'full',
                  'device': 'laptop'},
            headers={'Origin': 'http://localhost',
                     'Referer': 'http://localhost/peers/create'},
        )
        from database import get_peer_by_name
        ids.append(get_peer_by_name(f'b{i}')['id'])
    return ids


# ── bulk-disable ─────────────────────────────────────────────────────────────

def test_bulk_disable_disables_all_listed(logged_in_client):
    ids = _make_peers(logged_in_client, 3)
    resp = logged_in_client.post(
        '/peers/bulk-disable',
        data={'ids': ','.join(str(i) for i in ids)},
        headers=_hdrs(),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['count'] == 3
    from database import get_peer_by_id
    for pid in ids:
        assert get_peer_by_id(pid)['enabled'] == 0


def test_bulk_disable_skips_already_disabled(logged_in_client):
    """An already-disabled peer is silently skipped — count reflects
    actual transitions, not number of IDs received."""
    ids = _make_peers(logged_in_client, 2)
    from database import set_peer_enabled
    set_peer_enabled(ids[0], False)

    resp = logged_in_client.post(
        '/peers/bulk-disable',
        data={'ids': ','.join(str(i) for i in ids)},
        headers=_hdrs(),
    )
    assert resp.get_json()['count'] == 1  # only the second one transitioned


def test_bulk_disable_requires_login(client):
    resp = client.post('/peers/bulk-disable', data={'ids': '1'}, headers=_hdrs())
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_bulk_disable_rejects_empty_ids(logged_in_client):
    resp = logged_in_client.post(
        '/peers/bulk-disable', data={'ids': ''}, headers=_hdrs(),
    )
    assert resp.status_code == 400


def test_bulk_disable_ignores_non_digit_tokens(logged_in_client):
    """The id parser drops non-digit tokens silently (defence against
    injection / malformed bulk payloads)."""
    ids = _make_peers(logged_in_client, 1)
    resp = logged_in_client.post(
        '/peers/bulk-disable',
        data={'ids': f'{ids[0]},foo,;DROP TABLE peers,9999999'},
        headers=_hdrs(),
    )
    assert resp.status_code == 200
    # Only one valid id (the real one); 9999999 doesn't exist; non-digits dropped.
    assert resp.get_json()['count'] == 1


# ── bulk-enable ──────────────────────────────────────────────────────────────

def test_bulk_enable_enables_disabled_peers(logged_in_client):
    ids = _make_peers(logged_in_client, 2)
    from database import set_peer_enabled, get_peer_by_id
    for pid in ids:
        set_peer_enabled(pid, False)

    resp = logged_in_client.post(
        '/peers/bulk-enable',
        data={'ids': ','.join(str(i) for i in ids)},
        headers=_hdrs(),
    )
    assert resp.get_json()['count'] == 2
    for pid in ids:
        assert get_peer_by_id(pid)['enabled'] == 1


def test_bulk_enable_skips_already_enabled(logged_in_client):
    ids = _make_peers(logged_in_client, 2)
    resp = logged_in_client.post(
        '/peers/bulk-enable',
        data={'ids': ','.join(str(i) for i in ids)},
        headers=_hdrs(),
    )
    # Newly-created peers are already enabled, so nothing transitions.
    assert resp.get_json()['count'] == 0


# ── bulk-delete ──────────────────────────────────────────────────────────────

def test_bulk_delete_removes_peers_from_db(logged_in_client):
    ids = _make_peers(logged_in_client, 3)
    resp = logged_in_client.post(
        '/peers/bulk-delete',
        data={'ids': ','.join(str(i) for i in ids)},
        headers=_hdrs(),
    )
    assert resp.get_json()['count'] == 3
    from database import get_peer_by_id
    for pid in ids:
        assert get_peer_by_id(pid) is None


def test_bulk_delete_writes_audit_rows_with_via_bulk(logged_in_client):
    ids = _make_peers(logged_in_client, 2)
    logged_in_client.post(
        '/peers/bulk-delete',
        data={'ids': ','.join(str(i) for i in ids)},
        headers=_hdrs(),
    )
    from database import get_audit_log
    rows = get_audit_log(action_prefix='peer.delete', limit=20)
    bulk = [r for r in rows if (r.get('details') or '') == 'via=bulk']
    # One per peer deleted via bulk.
    assert len(bulk) == 2
