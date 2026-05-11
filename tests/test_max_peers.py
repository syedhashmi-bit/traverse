"""MAX_PEERS env var handling: default, override, clamp, garbage."""

import importlib
import os


def _reload_with(monkeypatch, value):
    if value is None:
        monkeypatch.delenv('MAX_PEERS', raising=False)
    else:
        monkeypatch.setenv('MAX_PEERS', value)
    import wireguard
    importlib.reload(wireguard)
    return wireguard.MAX_PEERS


def test_default_is_20(monkeypatch):
    assert _reload_with(monkeypatch, None) == 20


def test_env_var_override(monkeypatch):
    assert _reload_with(monkeypatch, '35') == 35


def test_clamped_to_hard_ceiling(monkeypatch):
    assert _reload_with(monkeypatch, '999') == 50


def test_garbage_falls_back_to_default(monkeypatch):
    assert _reload_with(monkeypatch, 'not-a-number') == 20


def test_zero_or_negative_clamped_to_one(monkeypatch):
    assert _reload_with(monkeypatch, '0') == 1
    assert _reload_with(monkeypatch, '-5') == 1
