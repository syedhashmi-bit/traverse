"""Notification dispatch: routing, per-event toggles, secret redaction,
SSRF/format guards on the channel senders."""

import pytest


def _enable(channel, **cfg):
    """Persist a channel as enabled with the given config (no real send)."""
    from database import update_notification_channel
    update_notification_channel(channel, True, cfg)


# ── Channel-sender input validation ──────────────────────────────────────────

def test_send_telegram_rejects_malformed_token():
    from notifications import send_telegram
    with pytest.raises(ValueError, match='token'):
        send_telegram({'token': 'not-a-token', 'chat_id': '123'}, 'hi')


def test_send_telegram_rejects_missing_chat_id():
    from notifications import send_telegram
    with pytest.raises(ValueError, match='chat_id'):
        send_telegram(
            {'token': '1234567:abcdefghijklmnopqrstuvwxyzABCDEFGHIJ', 'chat_id': ''},
            'hi',
        )


def test_send_discord_rejects_non_discord_host():
    """SSRF guard: only discord.com hosts may receive a webhook POST."""
    from notifications import send_discord
    with pytest.raises(ValueError, match='discord.com host'):
        send_discord({'webhook': 'https://evil.example/api/webhooks/1/x'}, 'hi')


def test_send_discord_rejects_http_scheme():
    from notifications import send_discord
    with pytest.raises(ValueError, match='discord.com host'):
        send_discord({'webhook': 'http://discord.com/api/webhooks/1/x'}, 'hi')


def test_send_discord_rejects_wrong_path():
    from notifications import send_discord
    with pytest.raises(ValueError, match='webhook path'):
        send_discord({'webhook': 'https://discord.com/totally-not-a-webhook'}, 'hi')


def test_send_email_rejects_missing_required_fields():
    from notifications import send_email
    with pytest.raises(ValueError):
        send_email({}, 'subj', 'msg')


# ── Secret redaction ─────────────────────────────────────────────────────────

def test_short_err_redacts_passwords():
    from notifications import _short_err
    s = _short_err(RuntimeError('password=supersecret123 not accepted'))
    assert 'supersecret123' not in s
    assert '[REDACTED]' in s


def test_short_err_redacts_telegram_token():
    from notifications import _short_err
    s = _short_err(RuntimeError('error using 1234567:abcdefghijklmnopqrstuvwxyz0123456789'))
    assert 'abcdefghijklmnopqrstuvwxyz' not in s


def test_short_err_redacts_discord_webhook_path():
    from notifications import _short_err
    s = _short_err(RuntimeError('failed POST /api/webhooks/123456789/seCrEt-ToKeN-ZZ'))
    assert 'seCrEt-ToKeN-ZZ' not in s


# ── Dispatch routing ─────────────────────────────────────────────────────────

def test_dispatch_only_calls_enabled_channels(app, monkeypatch):
    """Email is on, Telegram is off — only email should be invoked."""
    called = {'email': 0, 'telegram': 0, 'discord': 0}

    import notifications
    monkeypatch.setattr(notifications, 'send_email',
                        lambda cfg, subj, msg: called.__setitem__('email', called['email'] + 1))
    monkeypatch.setattr(notifications, 'send_telegram',
                        lambda cfg, msg: called.__setitem__('telegram', called['telegram'] + 1))
    monkeypatch.setattr(notifications, 'send_discord',
                        lambda cfg, msg, severity='info': called.__setitem__('discord', called['discord'] + 1))

    with app.app_context():
        _enable('email', **{'from': 'a@b', 'to': 'c@d',
                            'smtp_host': 'smtp.example', 'smtp_port': 587})
        notifications._dispatch('peer_added', 'hello', 'info')

    assert called['email'] == 1
    assert called['telegram'] == 0
    assert called['discord'] == 0


def test_dispatch_skips_disabled_event_type(app, monkeypatch):
    """If the operator has unchecked an event on /notifications, dispatch
    must not fire any channel for that event."""
    called = []
    import notifications
    monkeypatch.setattr(notifications, 'send_email',
                        lambda *a, **kw: called.append('email'))

    with app.app_context():
        _enable('email', **{'from': 'a@b', 'to': 'c@d', 'smtp_host': 'h'})
        from database import set_notification_event_toggles
        set_notification_event_toggles({'peer_added': False})
        notifications._dispatch('peer_added', 'hello', 'info')

    assert called == []


def test_dispatch_logs_success(app, monkeypatch):
    """A successful send writes a row to notification_log."""
    import notifications
    monkeypatch.setattr(notifications, 'send_email', lambda *a, **kw: None)

    with app.app_context():
        _enable('email', **{'from': 'a@b', 'to': 'c@d', 'smtp_host': 'h'})
        notifications._dispatch('peer_added', 'hello', 'info')
        from database import get_notification_log
        log = get_notification_log(limit=5)

    assert any(r['channel'] == 'email' and r['event_type'] == 'peer_added'
               and bool(r['success']) for r in log)


def test_dispatch_logs_failure(app, monkeypatch):
    """A raising sender writes a redacted failure row instead of crashing."""
    import notifications

    def _boom(*a, **kw):
        raise RuntimeError('password=secret123 was wrong')

    monkeypatch.setattr(notifications, 'send_email', _boom)

    with app.app_context():
        _enable('email', **{'from': 'a@b', 'to': 'c@d', 'smtp_host': 'h'})
        notifications._dispatch('peer_added', 'hello', 'info')
        from database import get_notification_log
        log = get_notification_log(limit=5)

    failures = [r for r in log
                if r['channel'] == 'email' and not bool(r['success'])]
    assert failures, 'failure row not written'
    assert 'secret123' not in failures[0]['error']


def test_is_any_channel_active_requires_minimum_config(app):
    """A channel that's flagged enabled but missing required config
    doesn't count as 'active' for the sidebar indicator."""
    import notifications
    with app.app_context():
        _enable('email', **{'from': '', 'to': '', 'smtp_host': ''})
        assert notifications.is_any_channel_active() is False
        _enable('email', **{'from': 'a@b', 'to': 'c@d', 'smtp_host': 'h'})
        assert notifications.is_any_channel_active() is True
