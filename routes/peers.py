import io
import os
import re
from dotenv import load_dotenv
load_dotenv()
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, send_file, abort, jsonify,
)
import qrcode
from database import (
    get_all_peers, get_peer_by_id, get_peer_by_name,
    create_peer, set_peer_enabled, delete_peer, count_peers,
    update_peer_notes, update_peer_expiry, update_peer_keys,
    get_peer_connection_events, update_peer_pihole,
)
from wireguard import (
    generate_keypair, get_next_vpn_ip, get_server_public_key,
    add_peer_to_interface, remove_peer_from_interface,
    generate_client_config, format_bytes, format_handshake,
    WG_ENDPOINT, WG_DNS, WG_PORT,
)
from routes.auth import login_required

PIHOLE_ENABLED = bool(os.getenv('PIHOLE_ENABLED'))
PIHOLE_DNS     = '10.8.0.1'
FALLBACK_DNS   = '1.1.1.1'

peers_bp = Blueprint('peers', __name__)

_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,64}$')
_DEVICES = {'phone', 'laptop', 'desktop', 'tablet', 'router', 'other'}


def _safe_name(name):
    return bool(_NAME_RE.match(name))


# ── List ─────────────────────────────────────────────────────────────────────

def _last_seen(hs_raw):
    """Return (label, css_class) for last-seen display from raw handshake timestamp."""
    import time as _time
    try:
        ts = int(hs_raw or 0)
    except (ValueError, TypeError):
        ts = 0
    if not ts:
        return ('never', 'seen-never')
    age = int(_time.time()) - ts
    if age < 0:
        age = 0
    if age < 180:
        return ('online now', 'seen-online')
    if age < 3600:
        return (f'{age // 60}m ago', 'seen-recent')
    if age < 86400:
        return (f'{age // 3600}h ago', 'seen-today')
    if age < 604800:
        return (f'{age // 86400}d ago', 'seen-week')
    return (f'{age // 86400}d ago', 'seen-old')


@peers_bp.route('/')
@login_required
def list_peers():
    from datetime import datetime
    today = datetime.utcnow().strftime('%Y-%m-%d')
    peers = get_all_peers()
    for p in peers:
        p['last_handshake'] = format_handshake(p.get('last_handshake'))
        p['rx_fmt']         = format_bytes(p.get('rx_bytes') or 0)
        p['tx_fmt']         = format_bytes(p.get('tx_bytes') or 0)
        p['is_expired']     = bool(p.get('expires_at') and p['expires_at'] <= today)
        p['last_seen_label'], p['last_seen_cls'] = _last_seen(p.get('last_handshake'))
    return render_template('peers/list.html', peers=peers)


# ── Create ───────────────────────────────────────────────────────────────────

@peers_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    MAX_PEERS = 20

    if request.method == 'GET':
        current_count = count_peers()
        try:
            next_ip = get_next_vpn_ip()
        except ValueError:
            next_ip = 'subnet exhausted'
        return render_template(
            'peers/create.html',
            next_ip       = next_ip,
            endpoint      = WG_ENDPOINT,
            dns           = WG_DNS,
            current_count = current_count,
            max_peers     = MAX_PEERS,
        )

    current_count = count_peers()
    if current_count >= MAX_PEERS:
        flash(f'Peer limit reached ({MAX_PEERS} max). Delete an existing peer to add a new one.', 'error')
        return redirect(url_for('peers.create'))

    name     = request.form.get('name', '').strip()
    dns      = request.form.get('dns', WG_DNS).strip()
    endpoint = request.form.get('endpoint', WG_ENDPOINT).strip()

    if not _safe_name(name):
        flash('Peer name must be 1–64 alphanumeric/dash/underscore characters.', 'error')
        return redirect(url_for('peers.create'))

    if get_peer_by_name(name):
        flash(f'A peer named "{name}" already exists.', 'error')
        return redirect(url_for('peers.create'))

    try:
        vpn_ip = get_next_vpn_ip()
    except ValueError as e:
        flash(str(e), 'error')
        return redirect(url_for('peers.create'))

    try:
        priv, pub, psk = generate_keypair()
    except Exception as e:
        flash(f'Key generation failed: {e}', 'error')
        return redirect(url_for('peers.create'))

    peer_id = create_peer(
        name=name, private_key=priv, public_key=pub,
        preshared_key=psk, vpn_ip=vpn_ip,
        dns=dns, endpoint=endpoint,
    )

    notes      = request.form.get('notes', '').strip()
    device     = request.form.get('device', 'other').strip()
    expires_at = request.form.get('expires_at', '').strip() or None
    if device not in _DEVICES:
        device = 'other'
    update_peer_notes(peer_id, notes, device)
    if expires_at:
        update_peer_expiry(peer_id, expires_at)

    # Try to apply to live interface (non-fatal if WG not running)
    try:
        add_peer_to_interface(pub, psk, vpn_ip)
    except Exception as e:
        flash(f'Peer saved but could not add to live interface: {e}', 'warning')

    flash(f'Peer "{name}" created at {vpn_ip}.', 'success')
    return redirect(url_for('peers.detail', peer_id=peer_id))


# ── Wizard ───────────────────────────────────────────────────────────────────

@peers_bp.route('/wizard')
@login_required
def wizard():
    MAX_PEERS = 20
    current_count = count_peers()
    try:
        next_ip = get_next_vpn_ip()
    except ValueError:
        next_ip = 'subnet exhausted'
    return render_template(
        'peers/wizard.html',
        next_ip       = next_ip,
        endpoint      = WG_ENDPOINT,
        dns           = WG_DNS,
        current_count = current_count,
        max_peers     = MAX_PEERS,
    )


@peers_bp.route('/api/preview', methods=['POST'])
@login_required
def api_preview():
    """Generate keys + config preview WITHOUT saving to DB."""
    data     = request.get_json(silent=True) or {}
    name     = data.get('name', '').strip()
    dns      = data.get('dns', WG_DNS).strip()
    endpoint = data.get('endpoint', WG_ENDPOINT).strip()
    device   = data.get('device', 'other').strip()
    notes    = data.get('notes', '').strip()
    expires  = data.get('expires_at', '').strip()

    if not _safe_name(name):
        return jsonify({'error': 'Invalid peer name — 1–64 alphanumeric/dash/underscore chars.'}), 400
    if get_peer_by_name(name):
        return jsonify({'error': f'A peer named "{name}" already exists.'}), 409
    if count_peers() >= 20:
        return jsonify({'error': 'Peer limit reached (20 max).'}), 429

    try:
        vpn_ip = get_next_vpn_ip()
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    try:
        priv, pub, psk = generate_keypair()
    except Exception as e:
        return jsonify({'error': f'Key generation failed: {e}'}), 500

    server_pub = get_server_public_key()
    fake_peer = {
        'name': name, 'private_key': priv, 'public_key': pub,
        'preshared_key': psk, 'vpn_ip': vpn_ip,
        'allowed_ips': '0.0.0.0/0', 'dns': dns,
        'endpoint': endpoint, 'enabled': 1,
    }
    config_text = generate_client_config(fake_peer, server_pub)

    return jsonify({
        'name':       name,
        'vpn_ip':     vpn_ip,
        'private_key': priv,
        'public_key':  pub,
        'psk':         psk,
        'config':      config_text,
        'device':      device,
        'notes':       notes,
        'expires_at':  expires,
        'dns':         dns,
        'endpoint':    endpoint,
    })


@peers_bp.route('/api/create', methods=['POST'])
@login_required
def api_create():
    """Create a peer from wizard — accepts JSON with pre-generated keys."""
    data       = request.get_json(silent=True) or {}
    name       = data.get('name', '').strip()
    priv       = data.get('private_key', '').strip()
    pub        = data.get('public_key', '').strip()
    psk        = data.get('psk', '').strip()
    vpn_ip     = data.get('vpn_ip', '').strip()
    dns        = data.get('dns', WG_DNS).strip()
    endpoint   = data.get('endpoint', WG_ENDPOINT).strip()
    device     = data.get('device', 'other').strip()
    notes      = data.get('notes', '').strip()
    expires_at = data.get('expires_at', '').strip() or None

    if not all([name, priv, pub, psk, vpn_ip]):
        return jsonify({'error': 'Missing required fields.'}), 400
    if not _safe_name(name):
        return jsonify({'error': 'Invalid peer name.'}), 400
    if get_peer_by_name(name):
        return jsonify({'error': f'Peer "{name}" already exists.'}), 409
    if count_peers() >= 20:
        return jsonify({'error': 'Peer limit reached.'}), 429
    if device not in _DEVICES:
        device = 'other'

    peer_id = create_peer(name=name, private_key=priv, public_key=pub,
                          preshared_key=psk, vpn_ip=vpn_ip, dns=dns, endpoint=endpoint)
    update_peer_notes(peer_id, notes, device)
    if expires_at:
        update_peer_expiry(peer_id, expires_at)
    try:
        add_peer_to_interface(pub, psk, vpn_ip)
    except Exception:
        pass

    return jsonify({'ok': True, 'peer_id': peer_id, 'redirect': url_for('peers.detail', peer_id=peer_id)})


# ── Detail ───────────────────────────────────────────────────────────────────

@peers_bp.route('/<int:peer_id>')
@login_required
def detail(peer_id):
    from datetime import datetime
    peer = get_peer_by_id(peer_id)
    if not peer:
        abort(404)
    server_pub  = get_server_public_key()
    config_text = generate_client_config(peer, server_pub or '(server-key-unavailable)')
    peer['last_handshake'] = format_handshake(peer.get('last_handshake'))
    peer['rx_fmt']         = format_bytes(peer.get('rx_bytes') or 0)
    peer['tx_fmt']         = format_bytes(peer.get('tx_bytes') or 0)
    today = datetime.utcnow().strftime('%Y-%m-%d')
    peer['is_expired'] = bool(peer.get('expires_at') and peer['expires_at'] <= today)
    events = get_peer_connection_events(peer_id, limit=10)
    return render_template(
        'peers/detail.html',
        peer           = peer,
        server_pub     = server_pub,
        config_text    = config_text,
        wg_port        = WG_PORT,
        events         = events,
        pihole_enabled = PIHOLE_ENABLED,
    )


# ── Config download ───────────────────────────────────────────────────────────

@peers_bp.route('/<int:peer_id>/config')
@login_required
def download_config(peer_id):
    peer = get_peer_by_id(peer_id)
    if not peer:
        abort(404)
    server_pub  = get_server_public_key()
    config_text = generate_client_config(peer, server_pub or '(server-key-unavailable)')
    buf = io.BytesIO(config_text.encode('utf-8'))
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', peer['name'])
    return send_file(
        buf,
        mimetype='text/plain',
        as_attachment=True,
        download_name=f'{safe_name}.conf',
    )


# ── QR code page ──────────────────────────────────────────────────────────────

@peers_bp.route('/<int:peer_id>/qr')
@login_required
def qr_page(peer_id):
    peer = get_peer_by_id(peer_id)
    if not peer:
        abort(404)
    return render_template('peers/qr.html', peer=peer)


@peers_bp.route('/<int:peer_id>/qr.png')
@login_required
def qr_image(peer_id):
    peer = get_peer_by_id(peer_id)
    if not peer:
        abort(404)
    server_pub  = get_server_public_key()
    config_text = generate_client_config(peer, server_pub or '(server-key-unavailable)')
    img = qrcode.make(config_text)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


# ── Edit notes / device ──────────────────────────────────────────────────────

@peers_bp.route('/<int:peer_id>/edit', methods=['POST'])
@login_required
def edit(peer_id):
    peer = get_peer_by_id(peer_id)
    if not peer:
        abort(404)
    notes      = request.form.get('notes', '').strip()
    device     = request.form.get('device', 'other').strip()
    expires_at = request.form.get('expires_at', '').strip() or None
    if device not in _DEVICES:
        device = 'other'
    update_peer_notes(peer_id, notes, device)
    update_peer_expiry(peer_id, expires_at)
    flash('Peer updated.', 'success')
    return redirect(url_for('peers.detail', peer_id=peer_id))


# ── Regenerate config ─────────────────────────────────────────────────────────

@peers_bp.route('/<int:peer_id>/regenerate', methods=['POST'])
@login_required
def regenerate(peer_id):
    peer = get_peer_by_id(peer_id)
    if not peer:
        abort(404)
    old_pubkey = peer['public_key']
    try:
        priv, pub, psk = generate_keypair()
    except Exception as e:
        flash(f'Key generation failed: {e}', 'error')
        return redirect(url_for('peers.detail', peer_id=peer_id))
    update_peer_keys(peer_id, priv, pub, psk)
    try:
        remove_peer_from_interface(old_pubkey)
        add_peer_to_interface(pub, psk, peer['vpn_ip'])
    except Exception as e:
        flash(f'Keys updated but WireGuard sync failed: {e}', 'warning')
    flash('Config regenerated. The old config will no longer work — download or scan the new one below.', 'success')
    return redirect(url_for('peers.detail', peer_id=peer_id))


# ── Toggle enable/disable ─────────────────────────────────────────────────────

@peers_bp.route('/<int:peer_id>/toggle', methods=['POST'])
@login_required
def toggle(peer_id):
    peer = get_peer_by_id(peer_id)
    if not peer:
        abort(404)

    new_state = not bool(peer['enabled'])
    set_peer_enabled(peer_id, new_state)

    try:
        if new_state:
            add_peer_to_interface(peer['public_key'], peer['preshared_key'], peer['vpn_ip'])
            flash(f'Peer "{peer["name"]}" enabled.', 'success')
        else:
            remove_peer_from_interface(peer['public_key'])
            flash(f'Peer "{peer["name"]}" disabled.', 'success')
    except Exception as e:
        flash(f'DB updated but WireGuard sync failed: {e}', 'warning')

    return redirect(url_for('peers.detail', peer_id=peer_id))


# ── Delete ────────────────────────────────────────────────────────────────────

@peers_bp.route('/<int:peer_id>/delete', methods=['POST'])
@login_required
def delete(peer_id):
    peer = get_peer_by_id(peer_id)
    if not peer:
        abort(404)

    try:
        remove_peer_from_interface(peer['public_key'])
    except Exception as e:
        flash(f'Could not remove from live interface: {e}', 'warning')

    delete_peer(peer_id)
    flash(f'Peer "{peer["name"]}" deleted.', 'success')
    return redirect(url_for('peers.list_peers'))


# ── Pi-hole DNS toggle ────────────────────────────────────────────────────────

@peers_bp.route('/<int:peer_id>/toggle-pihole', methods=['POST'])
@login_required
def toggle_pihole(peer_id):
    if not PIHOLE_ENABLED:
        abort(404)
    peer = get_peer_by_id(peer_id)
    if not peer:
        abort(404)
    new_state = not bool(peer.get('use_pihole', 1))
    update_peer_pihole(peer_id, new_state)
    # Also update the dns field so existing config downloads reflect the change
    from database import get_db
    from datetime import datetime
    new_dns = PIHOLE_DNS if new_state else FALLBACK_DNS
    with get_db() as conn:
        conn.execute(
            "UPDATE peers SET dns = ?, updated_at = ? WHERE id = ?",
            (new_dns, datetime.utcnow().isoformat(), peer_id)
        )
    state_label = 'enabled' if new_state else 'disabled'
    flash(f'Ad blocking (Pi-hole DNS) {state_label} for "{peer["name"]}".', 'success')
    return redirect(url_for('peers.detail', peer_id=peer_id))
