import json
import os
import subprocess
from flask import Blueprint, make_response, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv
load_dotenv()
from wireguard import (
    get_interface_status, get_server_public_key,
    WG_INTERFACE, WG_SUBNET, WG_SERVER_IP, WG_ENDPOINT, WG_PORT, WG_DNS,
)
from routes.auth import login_required

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/')
@login_required
def index():
    status     = get_interface_status()
    server_pub = get_server_public_key()

    # Generate server-side wg0.conf snippet for reference
    server_conf_snippet = _build_server_conf_snippet(server_pub)

    totp_secret     = os.getenv('TOTP_SECRET', '').strip()
    totp_configured = bool(totp_secret)

    from database import get_speedtest_results
    speedtest_results = get_speedtest_results(limit=5)

    return render_template(
        'settings.html',
        wg_status          = status,
        server_pub         = server_pub,
        server_conf_snippet = server_conf_snippet,
        interface          = WG_INTERFACE,
        subnet             = WG_SUBNET,
        server_ip          = WG_SERVER_IP,
        endpoint           = WG_ENDPOINT,
        wg_port            = WG_PORT,
        dns                = WG_DNS,
        totp_configured    = totp_configured,
        speedtest_results  = speedtest_results,
    )


@settings_bp.route('/restart', methods=['POST'])
@login_required
def restart_wg():
    try:
        r = subprocess.run(
            ['systemctl', 'restart', f'wg-quick@{WG_INTERFACE}'],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            flash('WireGuard interface restarted.', 'success')
        else:
            flash(f'Restart failed: {r.stderr}', 'error')
    except Exception as e:
        flash(f'Could not restart WireGuard: {e}', 'error')
    return redirect(url_for('settings.index'))


@settings_bp.route('/stop', methods=['POST'])
@login_required
def stop_wg():
    try:
        r = subprocess.run(
            ['systemctl', 'stop', f'wg-quick@{WG_INTERFACE}'],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            flash('WireGuard interface stopped.', 'success')
        else:
            flash(f'Stop failed: {r.stderr}', 'error')
    except Exception as e:
        flash(f'Could not stop WireGuard: {e}', 'error')
    return redirect(url_for('settings.index'))


@settings_bp.route('/start', methods=['POST'])
@login_required
def start_wg():
    try:
        r = subprocess.run(
            ['systemctl', 'start', f'wg-quick@{WG_INTERFACE}'],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            flash('WireGuard interface started.', 'success')
        else:
            flash(f'Start failed: {r.stderr}', 'error')
    except Exception as e:
        flash(f'Could not start WireGuard: {e}', 'error')
    return redirect(url_for('settings.index'))


@settings_bp.route('/backup/export')
@login_required
def backup_export():
    from datetime import datetime
    from database import get_all_peers, get_connection_events, get_all_alerts
    peers = get_all_peers()
    safe_peers = []
    for p in peers:
        pc = dict(p)
        pc.pop('private_key', None)   # never export peer private keys
        safe_peers.append(pc)
    data = {
        'traverse_version': '1.0',
        'exported_at':      datetime.utcnow().isoformat() + 'Z',
        'settings': {
            'WG_INTERFACE':    WG_INTERFACE,
            'WG_PORT':         WG_PORT,
            'WG_SUBNET':       WG_SUBNET,
            'WG_SERVER_VPN_IP': WG_SERVER_IP,
            'WG_ENDPOINT':     WG_ENDPOINT,
            'WG_DNS':          WG_DNS,
        },
        'peers':             safe_peers,
        'connection_events': get_connection_events(limit=10000),
        'alerts':            get_all_alerts(limit=10000),
    }
    filename = f"traverse-backup-{datetime.utcnow().strftime('%Y-%m-%d')}.json"
    resp = make_response(json.dumps(data, indent=2, default=str))
    resp.headers['Content-Type']        = 'application/json'
    resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


@settings_bp.route('/backup/import', methods=['POST'])
@login_required
def backup_import():
    f = request.files.get('backup_file')
    if not f or not f.filename:
        flash('No file selected.', 'error')
        return redirect(url_for('settings.index'))
    try:
        data = json.loads(f.read().decode('utf-8'))
    except Exception:
        flash('Invalid JSON backup file.', 'error')
        return redirect(url_for('settings.index'))
    if not isinstance(data.get('peers'), list):
        flash('Backup file contains no peer data.', 'error')
        return redirect(url_for('settings.index'))

    from database import get_all_peers, create_peer, update_peer_expiry, update_peer_notes
    from wireguard import add_peer_to_interface

    existing_keys = {p['public_key'] for p in get_all_peers()}
    imported = skipped = 0
    errors = []

    for p in data.get('peers', []):
        pub = p.get('public_key', '').strip()
        if not pub:
            skipped += 1
            continue
        if pub in existing_keys:
            skipped += 1
            continue
        if not p.get('vpn_ip') or not p.get('name'):
            skipped += 1
            continue
        try:
            peer_id = create_peer(
                name          = p['name'],
                private_key   = '',   # excluded from backup; user must regenerate config
                public_key    = pub,
                preshared_key = p.get('preshared_key', ''),
                vpn_ip        = p['vpn_ip'],
                dns           = p.get('dns', WG_DNS),
                endpoint      = p.get('endpoint', WG_ENDPOINT),
                allowed_ips   = p.get('allowed_ips', '0.0.0.0/0'),
            )
            existing_keys.add(pub)
            if p.get('preshared_key') and p.get('vpn_ip'):
                try:
                    add_peer_to_interface(pub, p['preshared_key'], p['vpn_ip'])
                except Exception:
                    pass
            if p.get('expires_at'):
                update_peer_expiry(peer_id, p['expires_at'])
            if p.get('notes') or p.get('device'):
                update_peer_notes(peer_id, p.get('notes', ''), p.get('device', 'other'))
            imported += 1
        except Exception as e:
            errors.append(f"{p.get('name', 'unknown')}: {e}")

    parts = [f'Imported {imported} peer(s)']
    if skipped:
        parts.append(f'{skipped} skipped (already exist / incomplete)')
    if errors:
        parts.append('Errors: ' + '; '.join(errors[:3]))
    if imported:
        parts.append('Use Regenerate Config on each peer to get new client configs.')
    flash(' — '.join(parts), 'success' if imported else 'warning')
    return redirect(url_for('settings.index'))


def _build_server_conf_snippet(server_pub):
    """Build reference server config snippet (no private key)."""
    return f"""[Interface]
# PrivateKey = <your-server-private-key>
Address = {WG_SERVER_IP}/24
ListenPort = {WG_PORT}
PostUp   = iptables -A FORWARD -i {WG_INTERFACE} -j ACCEPT; iptables -A FORWARD -o {WG_INTERFACE} -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i {WG_INTERFACE} -j ACCEPT; iptables -D FORWARD -o {WG_INTERFACE} -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# Peers are managed by traverse and added dynamically via wg set
"""
