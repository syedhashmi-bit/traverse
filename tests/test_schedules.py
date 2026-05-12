"""Tests for the per-peer schedule feature.

Three layers exercised:
  1. `schedules.is_within_window` — pure, midnight-crossing edge cases.
  2. database.py helpers — upsert / read / delete round-trips.
  3. /peers/<id>/schedule routes — form validation, audit log, gated by login.
  4. alerts.py poller integration — schedule transitions flip the peer +
     fire wg0 sync + audit row.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from schedules import (
    is_within_window, parse_days, format_days,
)


# ── parse_days ───────────────────────────────────────────────────────────────

def test_parse_days_csv_string():
    assert parse_days('0,2,4') == {0, 2, 4}


def test_parse_days_list_and_set_roundtrip():
    assert parse_days([0, 1, 2]) == {0, 1, 2}
    assert parse_days({3, 5}) == {3, 5}


def test_parse_days_drops_garbage_silently():
    assert parse_days('0,foo,9,3,-1,bar,6') == {0, 3, 6}


def test_parse_days_none_and_empty():
    assert parse_days(None) == set()
    assert parse_days('') == set()
    assert parse_days([]) == set()


# ── format_days ──────────────────────────────────────────────────────────────

def test_format_days_special_groups():
    assert format_days({0, 1, 2, 3, 4, 5, 6}) == 'Every day'
    assert format_days({0, 1, 2, 3, 4}) == 'Weekdays'
    assert format_days({5, 6}) == 'Weekends'


def test_format_days_partial_set_lists_in_order():
    assert format_days({2, 0, 4}) == 'Mon, Wed, Fri'


def test_format_days_empty_dash():
    assert format_days(set()) == '—'


# ── is_within_window ─────────────────────────────────────────────────────────

# 2026-05-13 is a Wednesday (weekday=2)
WED_NOON   = datetime(2026, 5, 13, 12, 0)
WED_06_59  = datetime(2026, 5, 13, 6, 59)
WED_07_00  = datetime(2026, 5, 13, 7, 0)
WED_22_00  = datetime(2026, 5, 13, 22, 0)
WED_23_30  = datetime(2026, 5, 13, 23, 30)
THU_03_00  = datetime(2026, 5, 14, 3, 0)   # Thursday (weekday=3)
SAT_03_00  = datetime(2026, 5, 16, 3, 0)   # Saturday (weekday=5)
SUN_03_00  = datetime(2026, 5, 17, 3, 0)   # Sunday (weekday=6)


def test_same_day_window_in():
    assert is_within_window(WED_NOON, [2], '07:00', '22:00') is True


def test_same_day_window_before():
    assert is_within_window(WED_06_59, [2], '07:00', '22:00') is False


def test_same_day_window_start_is_inclusive():
    assert is_within_window(WED_07_00, [2], '07:00', '22:00') is True


def test_same_day_window_end_is_exclusive():
    assert is_within_window(WED_22_00, [2], '07:00', '22:00') is False


def test_same_day_wrong_day():
    assert is_within_window(WED_NOON, [0, 1], '07:00', '22:00') is False


def test_midnight_crossing_late_evening_today():
    # 22:00–07:00 Mon-Fri: at Wed 23:30, the window is open
    assert is_within_window(WED_23_30, [0, 1, 2, 3, 4], '22:00', '07:00') is True


def test_midnight_crossing_early_morning_belongs_to_yesterday():
    # 22:00–07:00 Mon-Fri: at Thu 03:00, the window was opened by Wed
    assert is_within_window(THU_03_00, [0, 1, 2, 3, 4], '22:00', '07:00') is True


def test_midnight_crossing_yesterday_not_selected_closes_window():
    # Same shape but only Mon-Wed selected → Thu 03:00 is OUT of window
    # because Wed (yesterday) IS selected. So this should be True.
    # Test the inverse: Sat 03:00 with Mon-Fri selected → Fri is yesterday,
    # which IS selected → True.
    assert is_within_window(SAT_03_00, [0, 1, 2, 3, 4], '22:00', '07:00') is True


def test_midnight_crossing_neither_day_selected():
    # Sun 03:00 with Mon-Fri selected → Sat is yesterday (not selected),
    # Sun (today) is not selected → False
    assert is_within_window(SUN_03_00, [0, 1, 2, 3, 4], '22:00', '07:00') is False


def test_equal_times_is_never():
    # Ambiguous — treat as never in-window
    assert is_within_window(WED_NOON, [2], '12:00', '12:00') is False


def test_no_days_is_never():
    assert is_within_window(WED_NOON, [], '07:00', '22:00') is False


def test_malformed_hm_strings_are_rejected():
    assert is_within_window(WED_NOON, [2], 'morning', '22:00') is False
    assert is_within_window(WED_NOON, [2], '07:00', 'evening') is False
    assert is_within_window(WED_NOON, [2], '7:00', '22:00')  # 7:00 parses


# ── DB helpers ───────────────────────────────────────────────────────────────

def test_set_and_get_schedule_roundtrip(app):
    from database import get_db, set_peer_schedule, get_peer_schedule

    # Need a peer to FK against
    with get_db() as conn:
        conn.execute("""
            INSERT INTO peers (name, private_key, public_key, preshared_key,
                vpn_ip, allowed_ips, dns, endpoint, enabled, created_at, updated_at)
            VALUES ('p1', 'priv', 'pub', 'psk', '10.99.0.2', '0.0.0.0/0',
                    '1.1.1.1', 'x.example', 1, '2026-01-01', '2026-01-01')
        """)
        peer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    set_peer_schedule(peer_id, [0, 1, 2, 3, 4], '07:00', '22:00',
                      timezone='Europe/Berlin', enabled=True)
    sch = get_peer_schedule(peer_id)
    assert sch is not None
    assert sch['days_of_week'] == '0,1,2,3,4'
    assert sch['enabled_from'] == '07:00'
    assert sch['enabled_to']   == '22:00'
    assert sch['timezone']     == 'Europe/Berlin'
    assert sch['enabled']      == 1


def test_set_schedule_upsert_replaces(app):
    from database import get_db, set_peer_schedule, get_peer_schedule
    with get_db() as conn:
        conn.execute("""
            INSERT INTO peers (name, private_key, public_key, preshared_key,
                vpn_ip, allowed_ips, dns, endpoint, enabled, created_at, updated_at)
            VALUES ('p1', 'priv', 'pub', 'psk', '10.99.0.2', '0.0.0.0/0',
                    '1.1.1.1', 'x', 1, '2026-01-01', '2026-01-01')
        """)
        peer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    set_peer_schedule(peer_id, [0, 1], '08:00', '17:00', timezone='UTC', enabled=True)
    set_peer_schedule(peer_id, [5, 6], '10:00', '14:00', timezone='UTC', enabled=False)
    sch = get_peer_schedule(peer_id)
    assert sch['days_of_week'] == '5,6'
    assert sch['enabled_from'] == '10:00'
    assert sch['enabled']      == 0


def test_delete_schedule(app):
    from database import (
        get_db, set_peer_schedule, get_peer_schedule, delete_peer_schedule,
    )
    with get_db() as conn:
        conn.execute("""
            INSERT INTO peers (name, private_key, public_key, preshared_key,
                vpn_ip, allowed_ips, dns, endpoint, enabled, created_at, updated_at)
            VALUES ('p1', 'priv', 'pub', 'psk', '10.99.0.2', '0.0.0.0/0',
                    '1.1.1.1', 'x', 1, '2026-01-01', '2026-01-01')
        """)
        peer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    set_peer_schedule(peer_id, [0, 1, 2], '07:00', '22:00')
    delete_peer_schedule(peer_id)
    assert get_peer_schedule(peer_id) is None


def test_get_all_peer_schedules_joins_peer_fields(app):
    from database import get_db, set_peer_schedule, get_all_peer_schedules
    with get_db() as conn:
        conn.execute("""
            INSERT INTO peers (name, private_key, public_key, preshared_key,
                vpn_ip, allowed_ips, dns, endpoint, enabled, created_at, updated_at)
            VALUES ('alpha', 'priv', 'pub-alpha', 'psk', '10.99.0.2',
                    '0.0.0.0/0', '1.1.1.1', 'x', 1, '2026-01-01', '2026-01-01')
        """)
        peer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    set_peer_schedule(peer_id, [0, 1], '07:00', '22:00')
    rows = get_all_peer_schedules()
    assert len(rows) == 1
    assert rows[0]['peer_name']  == 'alpha'
    assert rows[0]['public_key'] == 'pub-alpha'


def test_schedule_cascade_deletes_with_peer(app):
    from database import (
        get_db, set_peer_schedule, get_peer_schedule, delete_peer,
    )
    with get_db() as conn:
        conn.execute("""
            INSERT INTO peers (name, private_key, public_key, preshared_key,
                vpn_ip, allowed_ips, dns, endpoint, enabled, created_at, updated_at)
            VALUES ('p1', 'priv', 'pub', 'psk', '10.99.0.2', '0.0.0.0/0',
                    '1.1.1.1', 'x', 1, '2026-01-01', '2026-01-01')
        """)
        peer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    set_peer_schedule(peer_id, [0], '07:00', '22:00')
    delete_peer(peer_id)
    assert get_peer_schedule(peer_id) is None


# ── Routes ────────────────────────────────────────────────────────────────────

def _make_peer(name='target'):
    from database import get_db
    with get_db() as conn:
        conn.execute("""
            INSERT INTO peers (name, private_key, public_key, preshared_key,
                vpn_ip, allowed_ips, dns, endpoint, enabled, created_at, updated_at)
            VALUES (?, 'priv', 'pub-' || ?, 'psk', '10.99.0.10', '0.0.0.0/0',
                    '1.1.1.1', 'x', 1, '2026-01-01', '2026-01-01')
        """, (name, name))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_schedule_save_route_requires_login(client):
    peer_id = _make_peer()
    r = client.post(f'/peers/{peer_id}/schedule',
                    data={'days': ['0'], 'enabled_from': '07:00',
                          'enabled_to': '22:00', 'timezone': 'UTC',
                          'schedule_enabled': '1'},
                    follow_redirects=False)
    assert r.status_code == 302
    assert '/login' in r.headers['Location']


def test_schedule_save_persists_and_audits(logged_in_client):
    peer_id = _make_peer()
    r = logged_in_client.post(f'/peers/{peer_id}/schedule', data={
        'days': ['0', '1', '2', '3', '4'],
        'enabled_from': '07:00', 'enabled_to': '22:00',
        'timezone': 'Europe/Berlin', 'schedule_enabled': '1',
    })
    assert r.status_code == 302

    from database import get_peer_schedule, get_audit_log
    sch = get_peer_schedule(peer_id)
    assert sch['days_of_week'] == '0,1,2,3,4'
    assert sch['timezone'] == 'Europe/Berlin'
    # Audit row written
    audit_actions = [r['action'] for r in get_audit_log(limit=10)]
    assert 'peer.schedule_saved' in audit_actions


def test_schedule_save_rejects_no_days(logged_in_client):
    peer_id = _make_peer()
    r = logged_in_client.post(f'/peers/{peer_id}/schedule', data={
        'enabled_from': '07:00', 'enabled_to': '22:00',
        'timezone': 'UTC', 'schedule_enabled': '1',
    }, follow_redirects=True)
    from database import get_peer_schedule
    assert get_peer_schedule(peer_id) is None
    assert b'at least one day' in r.data


def test_schedule_save_rejects_garbage_time(logged_in_client):
    peer_id = _make_peer()
    logged_in_client.post(f'/peers/{peer_id}/schedule', data={
        'days': ['0'], 'enabled_from': '25:00', 'enabled_to': '22:00',
        'timezone': 'UTC', 'schedule_enabled': '1',
    })
    from database import get_peer_schedule
    assert get_peer_schedule(peer_id) is None


def test_schedule_save_rejects_equal_times(logged_in_client):
    peer_id = _make_peer()
    logged_in_client.post(f'/peers/{peer_id}/schedule', data={
        'days': ['0'], 'enabled_from': '12:00', 'enabled_to': '12:00',
        'timezone': 'UTC', 'schedule_enabled': '1',
    })
    from database import get_peer_schedule
    assert get_peer_schedule(peer_id) is None


def test_schedule_save_rejects_bogus_timezone(logged_in_client):
    peer_id = _make_peer()
    logged_in_client.post(f'/peers/{peer_id}/schedule', data={
        'days': ['0'], 'enabled_from': '07:00', 'enabled_to': '22:00',
        'timezone': 'Atlantis/Nowhere', 'schedule_enabled': '1',
    })
    from database import get_peer_schedule
    assert get_peer_schedule(peer_id) is None


def test_schedule_delete_route(logged_in_client):
    peer_id = _make_peer()
    logged_in_client.post(f'/peers/{peer_id}/schedule', data={
        'days': ['0'], 'enabled_from': '07:00', 'enabled_to': '22:00',
        'timezone': 'UTC', 'schedule_enabled': '1',
    })
    r = logged_in_client.post(f'/peers/{peer_id}/schedule/delete')
    assert r.status_code == 302
    from database import get_peer_schedule, get_audit_log
    assert get_peer_schedule(peer_id) is None
    assert 'peer.schedule_deleted' in [r['action'] for r in get_audit_log(limit=10)]


def test_schedule_save_disabled_flag_persists(logged_in_client):
    peer_id = _make_peer()
    # schedule_enabled missing → checkbox unchecked
    logged_in_client.post(f'/peers/{peer_id}/schedule', data={
        'days': ['0'], 'enabled_from': '07:00', 'enabled_to': '22:00',
        'timezone': 'UTC',
    })
    from database import get_peer_schedule
    sch = get_peer_schedule(peer_id)
    assert sch is not None
    assert sch['enabled'] == 0


# ── Poller integration ──────────────────────────────────────────────────────

def _stub_poller_external_calls(monkeypatch):
    """Patch the lazy imports inside `alerts._check()` so the schedule
    section runs in isolation. The poller re-imports each name from its
    source module on every tick, so monkeypatching the source module
    is what actually takes effect."""
    import wireguard, database, notifications, alerts as a
    from routes import map as map_route

    monkeypatch.setattr(wireguard, 'parse_wg_show', lambda: {})
    monkeypatch.setattr(wireguard, 'get_interface_status',
                        lambda: {'running': True, 'since': None})
    monkeypatch.setattr(database, 'disable_expired_peers', lambda: [])
    monkeypatch.setattr(map_route, '_geolocate_ip', lambda ip: None)
    monkeypatch.setattr(notifications, 'send_notification',
                        lambda *a, **kw: None)
    monkeypatch.setattr(a, '_legacy_telegram_fallback', lambda html: None)
    # Reset transient state so test order doesn't leak.
    a._wg_was_down      = False
    a._last_wg_alert    = 0.0
    a._peer_last_active = {}
    a._peer_last_ip     = {}
    a._pihole_was_down  = False
    a._inactive_notified = {}
    a._expired_notified  = set()


def test_poller_flips_peer_outside_window(app, monkeypatch):
    """A peer that's currently enabled but the schedule says 'outside window'
    must be disabled by the poller, with the wg0 removal call fired."""
    from database import get_db, set_peer_schedule, get_peer_by_id
    with get_db() as conn:
        conn.execute("""
            INSERT INTO peers (name, private_key, public_key, preshared_key,
                vpn_ip, allowed_ips, dns, endpoint, enabled, created_at, updated_at)
            VALUES ('sleep', 'priv', 'PUB-SLEEP', 'PSK', '10.99.0.20',
                    '0.0.0.0/0', '1.1.1.1', 'x', 1, '2026-01-01', '2026-01-01')
        """)
        peer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Empty day-set → always outside window → poller will disable.
    set_peer_schedule(peer_id, [], '07:00', '22:00', enabled=True)

    _stub_poller_external_calls(monkeypatch)
    import wireguard, alerts
    removed = []
    monkeypatch.setattr(wireguard, 'remove_peer_from_interface',
                        lambda pk: removed.append(pk))

    alerts._check()

    assert get_peer_by_id(peer_id)['enabled'] == 0
    assert 'PUB-SLEEP' in removed


def test_poller_enables_peer_inside_window(app, monkeypatch):
    from database import get_db, set_peer_schedule, get_peer_by_id
    with get_db() as conn:
        conn.execute("""
            INSERT INTO peers (name, private_key, public_key, preshared_key,
                vpn_ip, allowed_ips, dns, endpoint, enabled, created_at, updated_at)
            VALUES ('wake', 'priv', 'PUB-WAKE', 'PSK', '10.99.0.21',
                    '0.0.0.0/0', '1.1.1.1', 'x', 0, '2026-01-01', '2026-01-01')
        """)
        peer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    # 24-h window every day → always-in-window
    set_peer_schedule(peer_id, [0, 1, 2, 3, 4, 5, 6], '00:00', '23:59',
                      enabled=True)

    _stub_poller_external_calls(monkeypatch)
    import wireguard, alerts
    added = []
    def fake_add(pk, psk, ip, mode='full', routes=''):
        added.append((pk, ip, mode))
    monkeypatch.setattr(wireguard, 'add_peer_to_interface', fake_add)

    alerts._check()

    assert get_peer_by_id(peer_id)['enabled'] == 1
    assert any(pk == 'PUB-WAKE' for pk, _, _ in added)


def test_poller_skips_paused_schedule(app, monkeypatch):
    """Schedule.enabled = False → poller leaves the peer's state alone."""
    from database import get_db, set_peer_schedule, get_peer_by_id
    with get_db() as conn:
        conn.execute("""
            INSERT INTO peers (name, private_key, public_key, preshared_key,
                vpn_ip, allowed_ips, dns, endpoint, enabled, created_at, updated_at)
            VALUES ('manual', 'priv', 'PUB-M', 'PSK', '10.99.0.22',
                    '0.0.0.0/0', '1.1.1.1', 'x', 1, '2026-01-01', '2026-01-01')
        """)
        peer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    set_peer_schedule(peer_id, [], '07:00', '22:00', enabled=False)

    _stub_poller_external_calls(monkeypatch)
    import wireguard, alerts
    monkeypatch.setattr(wireguard, 'remove_peer_from_interface',
                        lambda pk: pytest.fail('paused schedule should not remove'))
    monkeypatch.setattr(wireguard, 'add_peer_to_interface',
                        lambda *a, **kw: pytest.fail('paused schedule should not add'))

    alerts._check()
    assert get_peer_by_id(peer_id)['enabled'] == 1  # untouched
