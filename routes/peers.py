import io
import os
import re
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, send_file, abort,
)
import qrcode
from database import (
    get_all_peers, get_peer_by_id, get_peer_by_name,
    create_peer, set_peer_enabled, delete_peer, count_peers,
    update_peer_notes, update_peer_expiry, update_peer_keys,
    get_peer_connection_events,
)
from wireguard import (
    generate_keypair, get_next_vpn_ip, get_server_public_key,
    add_peer_to_interface, remove_peer_from_interface,
    generate_client_config, format_bytes, format_handshake,
    WG_ENDPOINT, WG_DNS, WG_PORT,
)
from routes.auth import login_required

peers_bp = Blueprint('peers', __name__)

_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,64}$')
_DEVICES = {'phone', 'laptop', 'desktop', 'tablet', 'router', 'other'}


def _safe_name(name):
    return bool(_NAME_RE.match(name))


# ── List ─────────────────────────────────────────────────────────────────────

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
        peer        = peer,
        server_pub  = server_pub,
        config_text = config_text,
        wg_port     = WG_PORT,
        events      = events,
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
