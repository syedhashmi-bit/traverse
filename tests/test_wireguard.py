"""Tests for wireguard.py wrappers and helpers.

These were the last big un-tested module. The subprocess wrappers
(`generate_keypair`, `add_peer_to_interface`, `remove_peer_from_interface`,
`parse_wg_show`) get a stubbed `_run` / `subprocess.run` so they exercise
real branching without touching the system.
"""

import subprocess
from unittest.mock import MagicMock

import pytest

import wireguard as wg


# ── _effective_allowed_ips ───────────────────────────────────────────────────

def test_allowed_ips_full_tunnel_is_default_route():
    assert wg._effective_allowed_ips('10.99.0.5', 'full') == '0.0.0.0/0, ::/0'


def test_allowed_ips_vpn_only_is_subnet():
    assert wg._effective_allowed_ips('10.99.0.5', 'vpn_only') == wg.WG_SUBNET


def test_allowed_ips_split_concatenates_custom_routes():
    out = wg._effective_allowed_ips('10.99.0.5', 'split', '192.168.1.0/24, 10.0.0.0/8')
    assert wg.WG_SUBNET in out
    assert '192.168.1.0/24' in out
    assert '10.0.0.0/8' in out


def test_allowed_ips_split_drops_empty_segments():
    out = wg._effective_allowed_ips('10.99.0.5', 'split', '192.168.1.0/24,,,10.0.0.0/8,')
    # No empty entries should leak through
    parts = [p.strip() for p in out.split(',')]
    assert '' not in parts
    assert '192.168.1.0/24' in parts
    assert '10.0.0.0/8' in parts


# ── is_peer_active ────────────────────────────────────────────────────────────

def test_is_peer_active_handles_zero_and_blank():
    assert wg.is_peer_active(None) is False
    assert wg.is_peer_active('') is False
    assert wg.is_peer_active('0') is False


def test_is_peer_active_within_threshold():
    import time as _t
    assert wg.is_peer_active(str(int(_t.time())))   is True
    assert wg.is_peer_active(str(int(_t.time()) - 60)) is True


def test_is_peer_active_past_threshold():
    import time as _t
    assert wg.is_peer_active(str(int(_t.time()) - 3600)) is False


def test_is_peer_active_garbage_returns_false():
    assert wg.is_peer_active('not-a-number') is False


# ── _safe_conf_value (config sanitisation) ───────────────────────────────────

def test_safe_conf_value_strips_newlines_and_brackets():
    # Injection attempt: try to start a second [Interface] section
    raw = 'evil.example\n[Interface]\nPrivateKey = stolen'
    cleaned = wg._safe_conf_value(raw)
    assert '\n' not in cleaned
    assert '[' not in cleaned
    assert ']' not in cleaned


def test_safe_conf_value_keeps_dots_colons_slashes_for_endpoints():
    out = wg._safe_conf_value('vpn.example.com:51820')
    assert out == 'vpn.example.com:51820'


def test_safe_conf_value_handles_empty():
    assert wg._safe_conf_value('') == ''
    assert wg._safe_conf_value(None) == ''


# ── generate_client_config sanitisation ──────────────────────────────────────

def test_generate_client_config_strips_injection_from_endpoint():
    peer = {
        'name':          'tst',
        'private_key':   'A' * 43 + '=',
        'preshared_key': 'B' * 43 + '=',
        'vpn_ip':        '10.99.0.5',
        'dns':           '1.1.1.1',
        # Attempt to smuggle an extra [Peer] section via a multi-line endpoint
        'endpoint':      'real.example\n[Peer]\nPublicKey = attacker',
        'tunnel_mode':   'full',
    }
    cfg = wg.generate_client_config(peer, 'S' * 43 + '=')
    # The injected newline + brackets must be stripped so no NEW section
    # appears — surviving characters all land inside the legitimate
    # `Endpoint = ...` value (wg-quick will then reject it as a hostname),
    # but the *structure* of the config is safe: exactly one [Interface]
    # and one [Peer] block, one Endpoint = ... line, and no stray brackets.
    assert cfg.count('[Interface]') == 1
    assert cfg.count('[Peer]') == 1
    assert '[' not in cfg.replace('[Interface]', '').replace('[Peer]', '')
    endpoint_lines = [l for l in cfg.splitlines() if l.startswith('Endpoint')]
    assert len(endpoint_lines) == 1


def test_generate_client_config_dns_override_wins():
    peer = {
        'name':          'tst',
        'private_key':   'A' * 43 + '=',
        'preshared_key': 'B' * 43 + '=',
        'vpn_ip':        '10.99.0.5',
        'dns':           '1.1.1.1',
        'dns_override':  '9.9.9.9',
        'endpoint':      'real.example',
        'tunnel_mode':   'full',
    }
    cfg = wg.generate_client_config(peer, 'S' * 43 + '=')
    assert 'DNS = 9.9.9.9' in cfg
    assert '1.1.1.1' not in cfg


def test_generate_client_config_full_tunnel_carries_default_route():
    peer = {
        'name':          'tst',
        'private_key':   'A' * 43 + '=',
        'preshared_key': 'B' * 43 + '=',
        'vpn_ip':        '10.99.0.5',
        'dns':           '1.1.1.1',
        'endpoint':      'real.example',
        'tunnel_mode':   'full',
    }
    cfg = wg.generate_client_config(peer, 'S' * 43 + '=')
    assert '0.0.0.0/0' in cfg


# ── format_bytes / format_handshake_short ────────────────────────────────────

def test_format_bytes_unit_boundaries():
    assert wg.format_bytes(0) == '0 B'
    assert wg.format_bytes(1023) == '1023 B'
    assert wg.format_bytes(1024).endswith('KB')
    assert wg.format_bytes(1024 * 1024).endswith('MB')
    assert wg.format_bytes(1024 ** 3).endswith('GB')


def test_format_handshake_short_buckets():
    import time as _t
    now = int(_t.time())
    assert wg.format_handshake_short(None) == 'Never'
    assert wg.format_handshake_short('0') == 'Never'
    assert wg.format_handshake_short(str(now)).endswith('s') or wg.format_handshake_short(str(now)) == 'now'
    assert wg.format_handshake_short(str(now - 120)).endswith('m')
    assert wg.format_handshake_short(str(now - 7200)).endswith('h')
    assert wg.format_handshake_short(str(now - 86400 * 3)).endswith('d')


# ── parse_wg_show ────────────────────────────────────────────────────────────

def test_parse_wg_show_returns_empty_on_empty_output(monkeypatch):
    monkeypatch.setattr(wg, '_run', lambda *a, **kw: '')
    assert wg.parse_wg_show() == {}


def test_parse_wg_show_skips_short_rows(monkeypatch):
    out = '\n'.join([
        'priv_key\tpub_key\tport\tfwmark',                     # interface row
        'short\trow',                                          # invalid
        'PEER_PUB\tPSK\tendpoint:51820\t10.99.0.2/32\t1700000000\t12345\t6789\t25',
    ])
    monkeypatch.setattr(wg, '_run', lambda *a, **kw: out)
    parsed = wg.parse_wg_show()
    assert 'PEER_PUB' in parsed
    p = parsed['PEER_PUB']
    assert p['endpoint'] == 'endpoint:51820'
    assert p['last_handshake'] == '1700000000'
    assert p['rx_bytes'] == 12345
    assert p['tx_bytes'] == 6789


def test_parse_wg_show_substitutes_none_endpoint(monkeypatch):
    out = '\n'.join([
        'priv\tpub\tport\tfwmark',
        'PEER_PUB\tPSK\t(none)\t10.99.0.2/32\t0\t0\t0\t0',
    ])
    monkeypatch.setattr(wg, '_run', lambda *a, **kw: out)
    parsed = wg.parse_wg_show()
    assert parsed['PEER_PUB']['endpoint'] == ''


# ── Subprocess-backed wrappers ───────────────────────────────────────────────

def test_generate_keypair_chains_priv_pub_psk(monkeypatch):
    seq = iter(['PRIV', 'PUB', 'PSK'])
    def fake_run(cmd, stdin=None, check=True, timeout=10):
        return next(seq)
    monkeypatch.setattr(wg, '_run', fake_run)
    priv, pub, psk = wg.generate_keypair()
    assert (priv, pub, psk) == ('PRIV', 'PUB', 'PSK')


def test_add_peer_uses_temp_file_for_psk(monkeypatch):
    captured = {}
    import os as _os
    def fake_run(cmd, stdin=None, check=True, timeout=10):
        captured['cmd'] = list(cmd)
        # The temp file should still exist while wg is invoked
        psk_idx = cmd.index('preshared-key') + 1
        assert _os.path.exists(cmd[psk_idx]), 'PSK temp file missing during wg set'
        with open(cmd[psk_idx]) as f:
            captured['psk_contents'] = f.read()
        return ''
    monkeypatch.setattr(wg, '_run', fake_run)
    monkeypatch.setattr(wg.subprocess, 'run',
                        lambda *a, **kw: MagicMock(returncode=0, stdout='', stderr=''))

    wg.add_peer_to_interface('PUB-KEY', 'PRESHARED-KEY', '10.99.0.5')

    cmd = captured['cmd']
    assert cmd[:3] == ['wg', 'set', wg.WG_INTERFACE]
    assert 'peer' in cmd and 'PUB-KEY' in cmd
    # PSK contents must match what was passed in, not '(none)' or empty
    assert captured['psk_contents'] == 'PRESHARED-KEY'
    # PSK must NOT have been passed on the command line directly (would
    # leak via /proc/<pid>/cmdline)
    assert 'PRESHARED-KEY' not in cmd


def test_remove_peer_calls_wg_set_remove(monkeypatch):
    captured = {}
    def fake_run(cmd, stdin=None, check=True, timeout=10):
        captured['cmd'] = list(cmd)
        return ''
    monkeypatch.setattr(wg, '_run', fake_run)
    monkeypatch.setattr(wg.subprocess, 'run',
                        lambda *a, **kw: MagicMock(returncode=0, stdout='', stderr=''))
    wg.remove_peer_from_interface('PUB-KEY')
    assert captured['cmd'][:3] == ['wg', 'set', wg.WG_INTERFACE]
    assert 'peer' in captured['cmd']
    assert 'PUB-KEY' in captured['cmd']
    assert 'remove' in captured['cmd']


def test_run_raises_on_nonzero_when_check_true(monkeypatch):
    def fake_run(cmd, input=None, capture_output=True, text=True, timeout=10):
        return MagicMock(returncode=1, stdout='', stderr='boom')
    monkeypatch.setattr(wg.subprocess, 'run', fake_run)
    with pytest.raises(RuntimeError):
        wg._run(['wg', 'genkey'])


def test_run_returns_stdout_on_success(monkeypatch):
    def fake_run(cmd, input=None, capture_output=True, text=True, timeout=10):
        return MagicMock(returncode=0, stdout='HELLO\n', stderr='')
    monkeypatch.setattr(wg.subprocess, 'run', fake_run)
    assert wg._run(['wg', 'genkey']) == 'HELLO'
