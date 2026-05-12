"""Verify the poller logs swallowed exceptions instead of hiding them."""


def test_swallow_context_logs_exceptions(monkeypatch, tmp_path):
    """Force an exception inside `_swallow` and confirm the rotating
    file logger captured it. Guards CLAUDE.md's note that 'the poller
    swallows all exceptions — failures are silent' — they shouldn't be
    silent any more."""
    log_path = tmp_path / 'poller.log'
    monkeypatch.setenv('TRAVERSE_POLLER_LOG', str(log_path))

    # The named logger (`logging.getLogger('traverse.poller')`) is a
    # process-wide singleton — handlers attached in earlier tests survive
    # module reloads. Clear them so _build_logger reinitialises against
    # the per-test tmp_path.
    import logging as _lg
    for h in list(_lg.getLogger('traverse.poller').handlers):
        try: h.close()
        except Exception: pass
        _lg.getLogger('traverse.poller').removeHandler(h)

    # Reload alerts so the new env var is picked up by _build_logger.
    import importlib
    import alerts
    importlib.reload(alerts)

    with alerts._swallow('demo_section'):
        raise RuntimeError('sentinel-boom-7e8a')

    # RotatingFileHandler doesn't flush on every write, so close handlers
    # to force a flush before we read the file.
    for h in alerts._log.handlers:
        h.flush()
        h.close()

    body = log_path.read_text()
    assert 'demo_section' in body
    assert 'sentinel-boom-7e8a' in body
    assert 'RuntimeError' in body


def test_swallow_doesnt_propagate(monkeypatch, tmp_path):
    """Whatever happens inside _swallow, the caller keeps going."""
    monkeypatch.setenv('TRAVERSE_POLLER_LOG', str(tmp_path / 'poller.log'))
    import importlib
    import alerts
    importlib.reload(alerts)

    reached = []
    with alerts._swallow('demo'):
        raise ValueError('boom')
    reached.append('after')
    assert reached == ['after']
