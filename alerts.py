import os
import ssl
import time
import threading
import urllib.request
import urllib.parse


_INTERVAL         = 60    # poll every 60 s
_wg_was_down      = False
_last_wg_alert    = 0.0
_peer_alerted_at  = {}    # public_key -> unix ts of last alert
_peer_last_active = {}    # public_key -> bool (was active last check)


def _send(msg):
    token   = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        return
    data = urllib.parse.urlencode({
        'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML',
    }).encode()
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/sendMessage', data=data
    )
    try:
        urllib.request.urlopen(req, context=ctx, timeout=10)
    except Exception:
        pass


def _check():
    global _wg_was_down, _last_wg_alert

    from wireguard import get_interface_status, parse_wg_show, remove_peer_from_interface, WG_INTERFACE
    from database import (
        get_all_peers, disable_expired_peers,
        log_connection_event, trim_connection_events,
        create_alert, record_bandwidth_snapshot,
    )
    from datetime import datetime, date

    now = time.time()

    # ── WireGuard interface ────────────────────────────────────────────────
    running = get_interface_status()['running']
    if not running:
        if not _wg_was_down or (now - _last_wg_alert) >= 300:
            _wg_was_down   = True
            _last_wg_alert = now
            _send('🔴 <b>Traverse VPN</b>\n\nWireGuard (<code>wg0</code>) is <b>DOWN</b>.')
        try:
            create_alert('wg_down', f'WireGuard {WG_INTERFACE} is not running', severity='critical')
        except Exception:
            pass
    else:
        if _wg_was_down:
            _wg_was_down   = False
            _last_wg_alert = now
            _send('🟢 <b>Traverse VPN</b>\n\nWireGuard is back <b>UP</b>.')

    # ── Expire peers ───────────────────────────────────────────────────────
    try:
        for p in disable_expired_peers():
            try:
                remove_peer_from_interface(p['public_key'])
            except Exception:
                pass
    except Exception:
        pass

    live  = parse_wg_show()
    peers = get_all_peers()

    # ── Connection event tracking ──────────────────────────────────────────
    try:
        for peer in peers:
            pub     = peer['public_key']
            peer_id = peer['id']
            vpn_ip  = peer['vpn_ip']
            live_info = live.get(pub, {})
            last_hs   = live_info.get('last_handshake') or peer.get('last_handshake')
            try:
                hs_ts = int(last_hs or 0)
            except (ValueError, TypeError):
                hs_ts = 0
            is_active = hs_ts > 0 and (now - hs_ts) < 180
            was_active = _peer_last_active.get(pub)
            if was_active is not None:
                if is_active and not was_active:
                    log_connection_event(peer_id, 'connected', vpn_ip)
                elif not is_active and was_active:
                    log_connection_event(peer_id, 'disconnected', vpn_ip)
            _peer_last_active[pub] = is_active
        trim_connection_events(1000)
    except Exception:
        pass

    # ── Bandwidth snapshots ────────────────────────────────────────────────
    try:
        for peer in peers:
            pub = peer['public_key']
            live_info = live.get(pub, {})
            rx = live_info.get('rx_bytes') if live_info else None
            tx = live_info.get('tx_bytes') if live_info else None
            if rx is None:
                rx = peer.get('rx_bytes') or 0
            if tx is None:
                tx = peer.get('tx_bytes') or 0
            record_bandwidth_snapshot(peer['id'], rx, tx)
    except Exception:
        pass

    # ── Alert conditions ───────────────────────────────────────────────────
    try:
        today_str = datetime.utcnow().strftime('%Y-%m-%d')
        today_obj = date.today()
        seven_days = 7 * 86400

        for peer in peers:
            pub = peer['public_key']
            live_info = live.get(pub, {})
            last_hs = live_info.get('last_handshake') or peer.get('last_handshake')
            try:
                hs_ts = int(last_hs or 0)
            except (ValueError, TypeError):
                hs_ts = 0

            # Inactive 7+ days
            if hs_ts > 0 and (now - hs_ts) >= seven_days:
                days_ago = int((now - hs_ts) / 86400)
                create_alert(
                    'peer_inactive', f'{peer["name"]} hasn\'t connected in {days_ago} days',
                    peer_id=peer['id'], severity='warning'
                )

            # Expired
            if peer.get('expires_at') and peer['expires_at'] <= today_str:
                try:
                    exp_date = date.fromisoformat(peer['expires_at'])
                    days_ago = (today_obj - exp_date).days
                    label = f'{days_ago} day{"s" if days_ago != 1 else ""} ago'
                except Exception:
                    label = peer['expires_at']
                create_alert(
                    'peer_expired', f'{peer["name"]} expired {label}',
                    peer_id=peer['id'], severity='info'
                )
    except Exception:
        pass

    # ── Peer inactivity alerts ─────────────────────────────────────────────
    inactive_hours = float(os.getenv('ALERT_INACTIVE_HOURS', '0'))
    if inactive_hours <= 0:
        return

    inactive_secs = inactive_hours * 3600
    cooldown      = 3600

    for peer in peers:
        if not peer.get('enabled'):
            continue
        pub       = peer['public_key']
        live_info = live.get(pub, {})
        last_hs   = live_info.get('last_handshake') or peer.get('last_handshake')
        try:
            hs_ts = int(last_hs or 0)
        except (ValueError, TypeError):
            continue
        if hs_ts <= 0:
            continue
        age = now - hs_ts
        if age < inactive_secs:
            continue
        if now - _peer_alerted_at.get(pub, 0) < cooldown:
            continue
        _peer_alerted_at[pub] = now
        hours_ago = int(age / 3600)
        _send(
            f'⚠️ <b>Traverse VPN</b>\n\n'
            f'Peer <code>{peer["name"]}</code> ({peer["vpn_ip"]}) '
            f'last seen <b>{hours_ago}h ago</b>.'
        )


def _loop():
    while True:
        try:
            _check()
        except Exception:
            pass
        time.sleep(_INTERVAL)


def start_alerts():
    t = threading.Thread(target=_loop, daemon=True, name='traverse-alerts')
    t.start()
