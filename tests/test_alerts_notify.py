"""Telegram unification: _notify() routes through send_notification(),
and the legacy env-var Telegram fallback fires only for state-change
events that pass legacy_html=...
"""


def test_notify_routes_through_send_notification(app, monkeypatch):
    calls = []
    import notifications
    monkeypatch.setattr(notifications, 'send_notification',
                        lambda *a, **kw: calls.append(('send', a, kw)))

    import alerts
    with app.app_context():
        alerts._notify('peer_added', 'hello', severity='info')

    assert any(c[0] == 'send' and c[1][0] == 'peer_added' for c in calls)


def test_notify_does_not_call_legacy_fallback_without_html(app, monkeypatch):
    """Non-state-change events must NOT touch the env-var Telegram path —
    that's the whole point of the unification."""
    import alerts
    fallback = []
    monkeypatch.setattr(alerts, '_legacy_telegram_fallback',
                        lambda html: fallback.append(html))
    import notifications
    monkeypatch.setattr(notifications, 'send_notification',
                        lambda *a, **kw: None)

    with app.app_context():
        alerts._notify('peer_added', 'hi', severity='info')

    assert fallback == []


def test_notify_fires_legacy_fallback_when_html_provided(app, monkeypatch):
    """wg_down / wg_recovered pass legacy_html=... so the env-var
    Telegram path runs alongside send_notification — belt-and-suspenders
    for the case where the DB is broken at boot time."""
    import alerts
    fallback = []
    monkeypatch.setattr(alerts, '_legacy_telegram_fallback',
                        lambda html: fallback.append(html))
    import notifications
    monkeypatch.setattr(notifications, 'send_notification',
                        lambda *a, **kw: None)

    with app.app_context():
        alerts._notify('wg_down', 'down', severity='critical',
                       legacy_html='<b>DOWN</b>')

    assert fallback == ['<b>DOWN</b>']


def test_notify_swallows_send_notification_exception(app, monkeypatch):
    """A misbehaving notifications module must not propagate into the
    poller — otherwise one bad channel kills the whole tick."""
    import alerts
    monkeypatch.setattr(alerts, '_legacy_telegram_fallback',
                        lambda html: None)
    import notifications

    def _boom(*a, **kw):
        raise RuntimeError('notifications dispatch crashed')
    monkeypatch.setattr(notifications, 'send_notification', _boom)

    with app.app_context():
        alerts._notify('peer_added', 'hi', severity='info')  # must not raise


def test_legacy_fallback_skipped_when_token_missing(monkeypatch):
    """Without TELEGRAM_BOT_TOKEN+CHAT_ID, the fallback must short-circuit
    without ever hitting the network."""
    import alerts
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '')

    called = []
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen',
                        lambda *a, **kw: called.append('open'))
    alerts._legacy_telegram_fallback('<b>x</b>')
    assert called == []


def test_legacy_fallback_skipped_when_token_malformed(monkeypatch):
    """A malformed token gets rejected before the URL is built — the
    accept regex is strict so a tampered .env can't redirect the host."""
    import alerts
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'not-a-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '123')

    called = []
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen',
                        lambda *a, **kw: called.append('open'))
    alerts._legacy_telegram_fallback('<b>x</b>')
    assert called == []
