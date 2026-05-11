"""Alerts poller logic: WG up/down transitions, connection event
detection, expired peer disablement. Stubs all external side effects
(wg CLI, notifications, geo) so the test stays hermetic."""

import time
import pytest


@pytest.fixture
def poller(app, monkeypatch):
    """Reset module-level state and stub side effects so _check() can be
    called in isolation. Returns the `alerts` module."""
    import alerts as a

    # Reset stateful globals so test order doesn't leak.
    a._wg_was_down      = False
    a._last_wg_alert    = 0.0
    a._peer_last_active = {}
    a._peer_last_ip     = {}
    a._pihole_was_down  = False
    a._inactive_notified = {}
    a._expired_notified  = set()

    # Silence outbound side-effects. After the Telegram-unification
    # refactor, _send was renamed to _legacy_telegram_fallback and the
    # poller now routes everything through _notify().
    monkeypatch.setattr(a, '_legacy_telegram_fallback', lambda html: None)
    import notifications
    monkeypatch.setattr(notifications, 'send_notification',
                        lambda *args, **kw: None)

    # _check() does `from routes.map import _geolocate_ip` lazily. Patch
    # the source module so geo lookups don't try the network.
    from routes import map as map_route
    monkeypatch.setattr(map_route, '_geolocate_ip', lambda ip: None)

    return a


def _seed_peer(name='poller-peer', enabled=1):
    """Create a peer via the DB helpers (skipping the route + wg sync)."""
    from database import create_peer, set_peer_enabled
    pid = create_peer(
        name=name, private_key='priv', public_key='pub-' + name,
        preshared_key='psk', vpn_ip=f'10.99.0.{2 + abs(hash(name)) % 250}',
        dns='1.1.1.1', endpoint='x.example',
    )
    if not enabled:
        set_peer_enabled(pid, False)
    return pid


# ── WG up/down transitions ───────────────────────────────────────────────────

def test_wg_down_creates_alert_and_flips_state(poller, monkeypatch):
    """First tick with wg=down sets _wg_was_down=True and writes a wg_down
    alert to the DB."""
    import wireguard
    monkeypatch.setattr(wireguard, 'get_interface_status',
                        lambda: {'running': False, 'since': None})
    monkeypatch.setattr(wireguard, 'parse_wg_show', lambda: {})

    poller._check()

    assert poller._wg_was_down is True
    from database import get_all_alerts
    alerts = [a for a in get_all_alerts(limit=20) if a['type'] == 'wg_down']
    assert alerts, 'wg_down alert should be created'


def test_wg_recovery_flips_state_back(poller, monkeypatch):
    """If _wg_was_down was True and the interface is now up, the next
    tick must flip _wg_was_down back to False."""
    poller._wg_was_down = True
    poller._last_wg_alert = time.time() - 10

    import wireguard
    monkeypatch.setattr(wireguard, 'get_interface_status',
                        lambda: {'running': True, 'since': '2026-05-11'})
    monkeypatch.setattr(wireguard, 'parse_wg_show', lambda: {})

    poller._check()
    assert poller._wg_was_down is False


def test_wg_up_steady_state_does_not_create_alert(poller, monkeypatch):
    """Tick with wg=up and previous state=up should NOT spam wg_down
    alerts — that was the original bug the state machine prevents."""
    import wireguard
    monkeypatch.setattr(wireguard, 'get_interface_status',
                        lambda: {'running': True, 'since': '2026-05-11'})
    monkeypatch.setattr(wireguard, 'parse_wg_show', lambda: {})

    poller._check()
    from database import get_all_alerts
    assert not [a for a in get_all_alerts(limit=20) if a['type'] == 'wg_down']


# ── Connection event tracking ────────────────────────────────────────────────

def test_peer_connect_event_logged(poller, monkeypatch):
    """Peer transitioning inactive→active inside the 180-second window
    must be written as a `connected` row in connection_events."""
    pid = _seed_peer('connector')

    # First tick: peer not in `live` → marks last_active=False.
    import wireguard
    monkeypatch.setattr(wireguard, 'get_interface_status',
                        lambda: {'running': True, 'since': '2026-05-11'})
    monkeypatch.setattr(wireguard, 'parse_wg_show', lambda: {})
    poller._check()

    # Second tick: peer present with a fresh handshake → transitions to active.
    fresh = str(int(time.time()) - 5)
    monkeypatch.setattr(wireguard, 'parse_wg_show', lambda: {
        'pub-connector': {
            'last_handshake': fresh,
            'rx_bytes': 100, 'tx_bytes': 200,
            'endpoint': '203.0.113.1:51820',
        },
    })
    poller._check()

    from database import get_connection_events
    events = [e for e in get_connection_events(limit=20) if e['peer_id'] == pid]
    assert any(e['event_type'] == 'connected' for e in events)


def test_peer_disconnect_event_logged(poller, monkeypatch):
    """Peer transitioning active→inactive must log a `disconnected` row."""
    pid = _seed_peer('disconnector')

    import wireguard
    monkeypatch.setattr(wireguard, 'get_interface_status',
                        lambda: {'running': True, 'since': '2026-05-11'})

    # First tick: peer active.
    fresh = str(int(time.time()) - 5)
    monkeypatch.setattr(wireguard, 'parse_wg_show', lambda: {
        'pub-disconnector': {
            'last_handshake': fresh,
            'rx_bytes': 1, 'tx_bytes': 1, 'endpoint': '203.0.113.2:51820',
        },
    })
    poller._check()

    # Second tick: peer's last_handshake is ancient → inactive.
    stale = str(int(time.time()) - 3600)
    monkeypatch.setattr(wireguard, 'parse_wg_show', lambda: {
        'pub-disconnector': {
            'last_handshake': stale,
            'rx_bytes': 1, 'tx_bytes': 1, 'endpoint': '203.0.113.2:51820',
        },
    })
    poller._check()

    from database import get_connection_events
    events = [e for e in get_connection_events(limit=20) if e['peer_id'] == pid]
    assert any(e['event_type'] == 'disconnected' for e in events)


# ── Expired peer handling ────────────────────────────────────────────────────

def test_expired_peer_gets_disabled_and_removed_from_wg(poller, monkeypatch):
    """A peer past its expires_at must be disabled in the DB and
    removed from the live wg0 interface."""
    pid = _seed_peer('expires-soon')
    from database import update_peer_expiry, get_peer_by_id
    # Date in the past.
    update_peer_expiry(pid, '2020-01-01')

    removed = []
    import wireguard
    monkeypatch.setattr(wireguard, 'get_interface_status',
                        lambda: {'running': True, 'since': '2026-05-11'})
    monkeypatch.setattr(wireguard, 'parse_wg_show', lambda: {})
    monkeypatch.setattr(wireguard, 'remove_peer_from_interface',
                        lambda pub: removed.append(pub))

    poller._check()

    assert get_peer_by_id(pid)['enabled'] == 0, \
        'expired peer should be marked disabled'
    assert 'pub-expires-soon' in removed, \
        'expired peer should be removed from wg0 by pubkey'
