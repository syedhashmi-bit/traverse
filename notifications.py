"""Multi-channel notification helper — email, Telegram, Discord.

All sends use stdlib only (smtplib, urllib.request, json).
Sends run on a background thread so callers never block.
Every send is wrapped in try/except — a failed channel never crashes the app.
"""
import json
import os
import re
import smtplib
import ssl
import threading
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# Telegram bot token format: <bot_id>:<35-char alphanumeric+_-> — keep this strict
# so a malicious token can't smuggle URL components (e.g. "x@evil.com/y") into the
# api.telegram.org request and pivot the host via userinfo or path injection.
_TELEGRAM_TOKEN_RE = re.compile(r'^\d{6,12}:[A-Za-z0-9_-]{30,80}$')

# Only accept official Discord webhook hosts so user-supplied webhook URLs can't
# be turned into an SSRF gadget against internal services.
_DISCORD_WEBHOOK_HOSTS = ('discord.com', 'discordapp.com', 'canary.discord.com',
                          'ptb.discord.com')


# ── Channel senders ──────────────────────────────────────────────────────────

def send_email(config, subject, message):
    """Send via SMTP. Raises on error."""
    host = (config.get('smtp_host') or '').strip()
    port = int(config.get('smtp_port') or 587)
    user = (config.get('smtp_user') or '').strip()
    pwd  = (config.get('smtp_pass') or '').strip()
    fr   = (config.get('from') or '').strip()
    to   = (config.get('to') or '').strip()
    if not (host and fr and to):
        raise ValueError('email: from, to, and smtp_host are required')

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = fr
    msg['To']      = to
    msg.attach(MIMEText(message, 'plain', 'utf-8'))
    html = (
        '<div style="font-family:system-ui,sans-serif;font-size:14px;color:#222">'
        f'<p>{_html_escape(message)}</p>'
        '<p style="color:#888;font-size:12px;border-top:1px solid #eee;padding-top:8px">'
        '— traverse VPN dashboard'
        '</p></div>'
    )
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
            if user:
                s.login(user, pwd)
            s.sendmail(fr, [to], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo()
            try:
                s.starttls(context=ctx)
                s.ehlo()
            except smtplib.SMTPNotSupportedError:
                pass
            if user:
                s.login(user, pwd)
            s.sendmail(fr, [to], msg.as_string())


def send_telegram(config, message):
    """POST to Telegram Bot API. Raises on error."""
    token   = (config.get('token') or '').strip()
    chat_id = (config.get('chat_id') or '').strip()
    if not (token and chat_id):
        raise ValueError('telegram: token and chat_id are required')
    if not _TELEGRAM_TOKEN_RE.match(token):
        raise ValueError('telegram: token format is invalid')

    data = urllib.parse.urlencode({
        'chat_id':    chat_id,
        'text':       message,
        'parse_mode': 'Markdown',
    }).encode('utf-8')
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    req = urllib.request.Request(url, data=data)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        body = resp.read()
        try:
            j = json.loads(body)
        except Exception:
            j = {}
        if not j.get('ok', False):
            raise RuntimeError(f'telegram api error: {body[:200].decode("utf-8", "replace")}')


def send_discord(config, message, severity='info'):
    """POST to a Discord webhook. Raises on error."""
    url = (config.get('webhook') or '').strip()
    if not url:
        raise ValueError('discord: webhook url is required')

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in _DISCORD_WEBHOOK_HOSTS:
        raise ValueError('discord: webhook must be an https URL on a discord.com host')
    if not parsed.path.startswith('/api/webhooks/'):
        raise ValueError('discord: webhook path must start with /api/webhooks/')

    color_map = {'info': 0x3b82f6, 'warning': 0xf59e0b, 'critical': 0xef4444}
    payload = {
        'username':    'traverse',
        'avatar_url':  '',
        'embeds': [{
            'description': message,
            'color':       color_map.get(severity, 0x3b82f6),
        }],
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url, data=data,
        headers={'Content-Type': 'application/json', 'User-Agent': 'traverse-vpn/1.0'},
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        # Discord returns 204 on success
        if resp.status not in (200, 204):
            raise RuntimeError(f'discord webhook returned status {resp.status}')


# ── Public API ───────────────────────────────────────────────────────────────

def send_notification(event_type, message, severity='info'):
    """Fire-and-forget: dispatches to all enabled channels in a background thread.

    Logs each attempt to notification_log. Honors per-event toggles.
    Never raises — safe to call from request handlers and the poller.
    """
    t = threading.Thread(
        target=_dispatch, args=(event_type, message, severity),
        daemon=True, name=f'notify-{event_type}',
    )
    t.start()


def send_test(channel, config):
    """Synchronous test send for the /notifications page Send Test buttons.

    Returns (success: bool, error: str). Logs to notification_log.
    """
    from database import log_notification
    msg = '🧪 traverse test notification — if you see this, the channel works.'
    try:
        if channel == 'email':
            send_email(config, 'traverse test notification', msg)
        elif channel == 'telegram':
            send_telegram(config, msg)
        elif channel == 'discord':
            send_discord(config, msg, severity='info')
        else:
            return False, f'unknown channel: {channel}'
        try:
            log_notification(channel, 'test', msg, success=True, error='')
        except Exception:
            pass
        return True, ''
    except Exception as e:
        err = _short_err(e)
        try:
            log_notification(channel, 'test', msg, success=False, error=err)
        except Exception:
            pass
        return False, err


def is_any_channel_active():
    """For sidebar dot — true if at least one enabled channel has minimum config."""
    try:
        from database import get_notification_settings
        s = get_notification_settings()
    except Exception:
        return False
    for ch, info in s.items():
        if not info.get('enabled'):
            continue
        cfg = info.get('config') or {}
        if ch == 'email' and cfg.get('from') and cfg.get('to') and cfg.get('smtp_host'):
            return True
        if ch == 'telegram' and cfg.get('token') and cfg.get('chat_id'):
            return True
        if ch == 'discord' and cfg.get('webhook'):
            return True
    return False


# ── Internals ────────────────────────────────────────────────────────────────

def _dispatch(event_type, message, severity):
    try:
        from database import (
            get_notification_settings, log_notification,
            is_notification_event_enabled,
        )
    except Exception:
        return

    # Per-event filter
    try:
        if not is_notification_event_enabled(event_type):
            return
    except Exception:
        pass

    try:
        settings = get_notification_settings()
    except Exception:
        return

    for channel, info in settings.items():
        if not info.get('enabled'):
            continue
        cfg = info.get('config') or {}
        try:
            if channel == 'email':
                subject = f'[traverse] {event_type}'
                send_email(cfg, subject, message)
            elif channel == 'telegram':
                send_telegram(cfg, message)
            elif channel == 'discord':
                send_discord(cfg, message, severity=severity)
            else:
                continue
            try:
                log_notification(channel, event_type, message, success=True, error='')
            except Exception:
                pass
        except Exception as e:
            try:
                log_notification(channel, event_type, message, success=False,
                                 error=_short_err(e))
            except Exception:
                pass


def _short_err(e):
    s = str(e) or e.__class__.__name__
    return s if len(s) < 300 else s[:297] + '...'


def _html_escape(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;').replace('"', '&quot;'))


# Event type → human label (used by the settings page)
EVENT_LABELS = [
    ('peer_connected',     'Peer connected'),
    ('peer_disconnected',  'Peer disconnected'),
    ('peer_inactive_long', 'Peer inactive 7+ days'),
    ('peer_expired',       'Peer expired'),
    ('bw_anomaly',         'Traffic anomaly'),
    ('wg_down',            'WireGuard down'),
    ('wg_recovered',       'WireGuard recovered'),
    ('pihole_down',        'Pi-hole down'),
    ('pihole_recovered',   'Pi-hole recovered'),
    ('peer_added',         'New peer added'),
    ('peer_deleted',       'Peer deleted'),
    ('peer_killed',        'Peer killed (force disconnected)'),
    ('config_regenerated', 'Config regenerated'),
    ('login_success',      'Login to dashboard'),
    ('login_failed',       'Failed login attempt'),
]
