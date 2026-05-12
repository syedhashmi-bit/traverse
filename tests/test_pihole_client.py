"""Tests for the Pi-hole v6 API client in routes/api.py.

`_pihole_auth` POSTs the password to /api/auth and caches the returned
SID until just before its `validity` window expires. `_fetch_pihole_summary`
re-uses the SID and caches the parsed JSON for 55s. Both wrap urlopen,
so we monkeypatch that to return canned responses.
"""

import io
import json
import time
from unittest.mock import MagicMock

import pytest

import routes.api as api_mod


@pytest.fixture(autouse=True)
def _reset_pihole_caches(monkeypatch):
    """Force a fresh SID + stats cache for every test."""
    monkeypatch.setattr(api_mod, '_pihole_session',
                        {'sid': None, 'expires': 0.0}, raising=False)
    monkeypatch.setattr(api_mod, '_pihole_stats_cache',
                        {'ts': 0.0, 'data': None}, raising=False)
    monkeypatch.setenv('PIHOLE_PASSWORD', 'pihole-pw')
    yield


class _FakeResp:
    """Minimal context-manager stand-in for urlopen()'s return value."""
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_auth_returns_sid_and_caches(monkeypatch):
    calls = []
    def fake_urlopen(req, timeout=5):
        calls.append(req)
        return _FakeResp({'session': {'valid': True, 'sid': 'SID-AAA', 'validity': 1800}})
    monkeypatch.setattr(api_mod._ureq, 'urlopen', fake_urlopen)

    sid1 = api_mod._pihole_auth()
    sid2 = api_mod._pihole_auth()
    assert sid1 == 'SID-AAA'
    assert sid2 == 'SID-AAA'
    # Second call hit the cache, not the network
    assert len(calls) == 1


def test_auth_returns_none_without_password(monkeypatch):
    monkeypatch.setenv('PIHOLE_PASSWORD', '')
    def boom(*a, **kw):  # urlopen should never be called
        raise AssertionError('urlopen called when PIHOLE_PASSWORD empty')
    monkeypatch.setattr(api_mod._ureq, 'urlopen', boom)
    assert api_mod._pihole_auth() is None


def test_auth_returns_none_on_invalid_session(monkeypatch):
    def fake_urlopen(req, timeout=5):
        return _FakeResp({'session': {'valid': False}})
    monkeypatch.setattr(api_mod._ureq, 'urlopen', fake_urlopen)
    assert api_mod._pihole_auth() is None


def test_auth_returns_none_on_network_error(monkeypatch):
    def fake_urlopen(req, timeout=5):
        raise OSError('network unreachable')
    monkeypatch.setattr(api_mod._ureq, 'urlopen', fake_urlopen)
    assert api_mod._pihole_auth() is None


def test_auth_expires_after_validity_window(monkeypatch):
    # Only POST /api/auth calls consume from the sequence; DELETE /api/auth
    # (logout for the expired session) returns a generic empty payload so it
    # doesn't eat a queued auth response.
    auth_seq = iter([
        {'session': {'valid': True, 'sid': 'SID-1', 'validity': 1800}},
        {'session': {'valid': True, 'sid': 'SID-2', 'validity': 1800}},
    ])
    posts = []
    def fake_urlopen(req, timeout=5):
        method = getattr(req, 'method', '') or ''
        if method == 'POST':
            posts.append(req)
            return _FakeResp(next(auth_seq))
        return _FakeResp({})   # DELETE / GET / etc.
    monkeypatch.setattr(api_mod._ureq, 'urlopen', fake_urlopen)

    sid1 = api_mod._pihole_auth()
    api_mod._pihole_session['expires'] = time.time() - 1
    sid2 = api_mod._pihole_auth()
    assert sid1 == 'SID-1'
    assert sid2 == 'SID-2'
    assert len(posts) == 2


def test_summary_caches_and_serves_canned_data(monkeypatch):
    payload = {
        'queries':  {'total': 1234, 'blocked': 89, 'percent_blocked': 7.2},
        'clients':  {'active': 4},
        'gravity':  {'domains_being_blocked': 241_000},
    }
    seq = iter([
        # /api/auth
        {'session': {'valid': True, 'sid': 'SID-X', 'validity': 1800}},
        # /api/stats/summary
        payload,
    ])
    def fake_urlopen(req, timeout=5):
        return _FakeResp(next(seq))
    monkeypatch.setattr(api_mod._ureq, 'urlopen', fake_urlopen)

    d1 = api_mod._fetch_pihole_summary()
    d2 = api_mod._fetch_pihole_summary()
    assert d1 == payload
    # Second call served from cache (would otherwise raise StopIteration on next())
    assert d2 == payload


def test_summary_returns_none_when_auth_fails(monkeypatch):
    def fake_urlopen(req, timeout=5):
        return _FakeResp({'session': {'valid': False}})
    monkeypatch.setattr(api_mod._ureq, 'urlopen', fake_urlopen)
    assert api_mod._fetch_pihole_summary() is None


def test_summary_returns_none_on_fetch_error(monkeypatch):
    # First call (auth) succeeds, second (summary) raises
    auth_payload = {'session': {'valid': True, 'sid': 'SID', 'validity': 1800}}
    state = {'n': 0}
    def fake_urlopen(req, timeout=5):
        state['n'] += 1
        if state['n'] == 1:
            return _FakeResp(auth_payload)
        raise OSError('upstream down')
    monkeypatch.setattr(api_mod._ureq, 'urlopen', fake_urlopen)
    assert api_mod._fetch_pihole_summary() is None
