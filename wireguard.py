import subprocess
import os
import ipaddress
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

WG_INTERFACE  = os.getenv('WG_INTERFACE',    'wg0')
WG_SUBNET     = os.getenv('WG_SUBNET',       '10.8.0.0/24')
WG_SERVER_IP  = os.getenv('WG_SERVER_VPN_IP', '10.8.0.1')
WG_ENDPOINT   = os.getenv('WG_ENDPOINT',     'your-server-ip')
WG_PORT       = os.getenv('WG_PORT',         '51820')
WG_DNS        = os.getenv('WG_DNS',          '1.1.1.1')


# ── Key generation ──────────────────────────────────────────────────────────

def _run(cmd, stdin=None, check=True, timeout=10):
    result = subprocess.run(
        cmd, input=stdin, capture_output=True, text=True, timeout=timeout
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Command failed: {cmd}")
    return result.stdout.strip()

def generate_private_key():
    return _run(['wg', 'genkey'])

def generate_public_key(private_key):
    return _run(['wg', 'pubkey'], stdin=private_key)

def generate_preshared_key():
    return _run(['wg', 'genpsk'])

def generate_keypair():
    priv = generate_private_key()
    pub  = generate_public_key(priv)
    psk  = generate_preshared_key()
    return priv, pub, psk


# ── IP allocation ────────────────────────────────────────────────────────────

def get_next_vpn_ip():
    from database import get_db
    network   = ipaddress.IPv4Network(WG_SUBNET, strict=False)
    server_ip = ipaddress.IPv4Address(WG_SERVER_IP)
    hosts     = [str(h) for h in network.hosts() if h != server_ip]

    with get_db() as conn:
        used = {r[0] for r in conn.execute("SELECT vpn_ip FROM peers")}

    for ip in hosts:
        if ip not in used:
            return ip
    raise ValueError("No available VPN IPs — subnet exhausted")


# ── Server info ──────────────────────────────────────────────────────────────

def get_server_public_key():
    try:
        return _run(['wg', 'show', WG_INTERFACE, 'public-key'], check=False) or None
    except Exception:
        return None

def get_interface_status():
    try:
        r = subprocess.run(
            ['wg', 'show', WG_INTERFACE],
            capture_output=True, text=True, timeout=10
        )
        return {'running': r.returncode == 0, 'output': r.stdout}
    except Exception:
        return {'running': False, 'output': ''}


# ── Live peer management ─────────────────────────────────────────────────────

def _effective_allowed_ips(vpn_ip, tunnel_mode, custom_routes=''):
    """Return the client-side AllowedIPs string for a given tunnel mode.
    Used in client config generation only — not for wg set server-side."""
    if tunnel_mode == 'vpn_only':
        return WG_SUBNET
    if tunnel_mode == 'split':
        parts = [WG_SUBNET]
        for cidr in (custom_routes or '').split(','):
            cidr = cidr.strip()
            if cidr:
                parts.append(cidr)
        return ', '.join(parts)
    # default: full tunnel
    return '0.0.0.0/0, ::/0'


def add_peer_to_interface(public_key, preshared_key, vpn_ip,
                          tunnel_mode='full', custom_routes=''):
    """Add peer to running WireGuard interface via wg set.
    Server-side allowed-ips is always vpn_ip/32 — tunnel mode is client-side only."""
    import tempfile, os as _os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.psk', delete=False) as f:
        f.write(preshared_key)
        psk_path = f.name
    try:
        _run([
            'wg', 'set', WG_INTERFACE,
            'peer', public_key,
            'preshared-key', psk_path,
            'allowed-ips', f'{vpn_ip}/32',
        ])
        _save_wg_config()
    finally:
        _os.unlink(psk_path)

def remove_peer_from_interface(public_key):
    """Remove peer from running WireGuard interface."""
    _run(['wg', 'set', WG_INTERFACE, 'peer', public_key, 'remove'], check=False)
    _save_wg_config()

def _save_wg_config():
    subprocess.run(
        ['wg-quick', 'save', WG_INTERFACE],
        capture_output=True, timeout=10
    )


# ── Statistics ───────────────────────────────────────────────────────────────

def parse_wg_show():
    """
    Returns dict keyed by public_key with last_handshake, rx_bytes, tx_bytes.
    Uses `wg show <iface> dump` which outputs TSV:
      interface: private_key public_key listen_port fwmark
      peer:      public_key  psk        endpoint allowed_ips last_handshake rx_bytes tx_bytes persistent_keepalive
    """
    try:
        out = _run(['wg', 'show', WG_INTERFACE, 'dump'], check=False)
        if not out:
            return {}
        peers = {}
        lines = out.strip().split('\n')
        for line in lines[1:]:   # first line is the interface row
            parts = line.split('\t')
            if len(parts) < 8:
                continue
            pub_key  = parts[0]
            endpoint = parts[2] if parts[2] != '(none)' else ''
            last_hs  = parts[4]
            rx       = int(parts[5]) if parts[5].isdigit() else 0
            tx       = int(parts[6]) if parts[6].isdigit() else 0
            peers[pub_key] = {
                'endpoint':       endpoint,
                'last_handshake': last_hs,
                'rx_bytes':       rx,
                'tx_bytes':       tx,
            }
        return peers
    except Exception:
        return {}

def is_peer_active(last_handshake_ts, threshold=300):
    """True if last handshake was within threshold seconds (default 5 min)."""
    if not last_handshake_ts or last_handshake_ts == '0':
        return False
    try:
        return (time.time() - int(last_handshake_ts)) < threshold
    except (ValueError, TypeError):
        return False


# ── Config generation ─────────────────────────────────────────────────────────

def generate_client_config(peer, server_public_key):
    endpoint = peer.get('endpoint') or WG_ENDPOINT
    # dns_override takes precedence over dns field, which falls back to WG_DNS
    dns = peer.get('dns_override') or peer.get('dns') or WG_DNS
    tunnel_mode   = peer.get('tunnel_mode') or 'full'
    custom_routes = peer.get('custom_routes') or ''
    allowed_ips   = _effective_allowed_ips(peer['vpn_ip'], tunnel_mode, custom_routes)
    return (
        f"[Interface]\n"
        f"PrivateKey = {peer['private_key']}\n"
        f"Address = {peer['vpn_ip']}/32\n"
        f"DNS = {dns}\n"
        f"\n"
        f"[Peer]\n"
        f"PublicKey = {server_public_key}\n"
        f"PresharedKey = {peer['preshared_key']}\n"
        f"Endpoint = {endpoint}:{WG_PORT}\n"
        f"AllowedIPs = {allowed_ips}\n"
        f"PersistentKeepalive = 25\n"
    )


# ── Formatting helpers ────────────────────────────────────────────────────────

def format_bytes(b):
    b = int(b or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if b < 1024:
            return f"{b:.1f} {unit}" if unit != 'B' else f"{b} B"
        b /= 1024
    return f"{b:.1f} PB"

def format_handshake(ts):
    if not ts or ts == '0':
        return 'Never'
    try:
        return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d %H:%M:%S UTC')
    except (ValueError, OSError):
        return 'Unknown'

def format_handshake_short(ts):
    """Compact relative time for dense tables: '2m', '1h', '3d', 'Never'."""
    if not ts or ts == '0':
        return 'Never'
    try:
        age = int(time.time() - int(ts))
        if age < 0:      return 'now'
        if age < 60:     return f'{age}s'
        if age < 3600:   return f'{age // 60}m'
        if age < 86400:  return f'{age // 3600}h'
        return f'{age // 86400}d'
    except (ValueError, OSError):
        return '?'
