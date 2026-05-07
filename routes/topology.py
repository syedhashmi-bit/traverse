from flask import Blueprint, render_template, jsonify
from database import get_all_peers
from wireguard import parse_wg_show, is_peer_active, format_bytes, format_handshake_short, WG_SUBNET, WG_ENDPOINT
from routes.auth import login_required

topology_bp = Blueprint('topology', __name__)


@topology_bp.route('/topology')
@login_required
def topology_view():
    return render_template('topology.html', subnet=WG_SUBNET, endpoint=WG_ENDPOINT)


@topology_bp.route('/api/topology')
@login_required
def topology_data():
    live  = parse_wg_show()
    peers = get_all_peers()
    nodes = []
    device_icons = {
        'phone': '📱', 'laptop': '💻', 'desktop': '🖥',
        'tablet': '📋', 'router': '🌐', 'other': '◈',
    }
    for p in peers:
        pub      = p['public_key']
        live_inf = live.get(pub, {})
        last_hs  = live_inf.get('last_handshake') or p.get('last_handshake')
        rx       = live_inf.get('rx_bytes') or p.get('rx_bytes') or 0
        tx       = live_inf.get('tx_bytes') or p.get('tx_bytes') or 0
        active   = bool(p.get('enabled')) and is_peer_active(last_hs)
        enabled  = bool(p.get('enabled'))
        nodes.append({
            'id':          p['id'],
            'name':        p['name'],
            'vpn_ip':      p['vpn_ip'],
            'device':      p.get('device') or 'other',
            'icon':        device_icons.get(p.get('device') or 'other', '◈'),
            'active':      active,
            'enabled':     enabled,
            'tunnel_mode': p.get('tunnel_mode') or 'full',
            'last_seen':   format_handshake_short(last_hs),
            'rx_fmt':      format_bytes(rx),
            'tx_fmt':      format_bytes(tx),
            'url':         f'/peers/{p["id"]}',
        })
    return jsonify({'nodes': nodes, 'endpoint': WG_ENDPOINT})
