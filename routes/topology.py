from flask import Blueprint, render_template, jsonify
from database import get_all_peers
from wireguard import parse_wg_show, is_peer_active, WG_SUBNET
from routes.auth import login_required

topology_bp = Blueprint('topology', __name__)


@topology_bp.route('/topology')
@login_required
def topology_view():
    return render_template('topology.html', subnet=WG_SUBNET)


@topology_bp.route('/api/topology')
@login_required
def topology_data():
    live  = parse_wg_show()
    peers = get_all_peers()
    nodes = []
    for p in peers:
        pub      = p['public_key']
        live_inf = live.get(pub, {})
        last_hs  = live_inf.get('last_handshake') or p.get('last_handshake')
        active   = bool(p.get('enabled')) and is_peer_active(last_hs)
        enabled  = bool(p.get('enabled'))
        icons = {'phone': '📱', 'laptop': '💻', 'desktop': '🖥',
                 'tablet': '📋', 'router': '🌐', 'other': '◈'}
        nodes.append({
            'id':      p['id'],
            'name':    p['name'],
            'vpn_ip':  p['vpn_ip'],
            'device':  p.get('device') or 'other',
            'icon':    icons.get(p.get('device') or 'other', '◈'),
            'active':  active,
            'enabled': enabled,
            'url':     f'/peers/{p["id"]}',
        })
    return jsonify({'nodes': nodes})
