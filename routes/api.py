import re
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from flask import Blueprint, jsonify, request
from database import get_all_peers, upsert_traffic_sample, get_peer_daily_traffic
from wireguard import parse_wg_show, format_bytes, is_peer_active, format_handshake, get_interface_status, WG_INTERFACE
from routes.auth import login_required

api_bp = Blueprint('api', __name__)

_prev_sample  = {}
_rate_history = deque(maxlen=900)   # 900 × 1 s = 15 min

_wg_cache = {'ts': 0.0, 'data': {}}
_WG_TTL   = 0.85   # seconds

_daily_buffer   = {}   # peer_id -> {day, day_start_rx, day_start_tx, last_flush}
_FLUSH_INTERVAL = 60   # seconds between DB writes


def _live_peers():
    now = time.time()
    if now - _wg_cache['ts'] < _WG_TTL:
        return _wg_cache['data']
    data = parse_wg_show()
    _wg_cache['ts']  = now
    _wg_cache['data'] = data
    return data


@api_bp.route('/api/stats')
@login_required
def stats():
    now   = time.time()
    live  = _live_peers()
    peers = get_all_peers()
    today = datetime.utcnow().strftime('%Y-%m-%d')

    peer_stats = []
    total_rx = total_tx = 0
    total_rx_rate = total_tx_rate = 0.0
    active_count = 0

    for peer in peers:
        pub       = peer['public_key']
        peer_id   = peer['id']
        rx        = peer.get('rx_bytes') or 0
        tx        = peer.get('tx_bytes') or 0
        live_info = live.get(pub, {})

        if live_info:
            rx = live_info['rx_bytes']
            tx = live_info['tx_bytes']

        total_rx += rx
        total_tx += tx

        rx_rate = tx_rate = 0.0
        if pub in _prev_sample:
            prev_ts, prev_rx, prev_tx = _prev_sample[pub]
            dt = now - prev_ts
            if dt > 0:
                rx_rate = max(0.0, (rx - prev_rx) / dt)
                tx_rate = max(0.0, (tx - prev_tx) / dt)
        _prev_sample[pub] = (now, rx, tx)
        total_rx_rate += rx_rate
        total_tx_rate += tx_rate

        last_hs = live_info.get('last_handshake') or peer.get('last_handshake')
        active  = bool(peer.get('enabled')) and is_peer_active(last_hs)
        if active:
            active_count += 1

        # ── Daily traffic sampling ─────────────────────────────────────────
        buf = _daily_buffer.get(peer_id)
        if buf is None or buf['day'] != today:
            _daily_buffer[peer_id] = {
                'day': today, 'day_start_rx': rx,
                'day_start_tx': tx, 'last_flush': 0.0,
            }
            buf = _daily_buffer[peer_id]
        else:
            # Handle WireGuard counter reset (restart)
            if rx < buf['day_start_rx']:
                buf['day_start_rx'] = rx
            if tx < buf['day_start_tx']:
                buf['day_start_tx'] = tx

        if now - buf['last_flush'] >= _FLUSH_INTERVAL:
            day_rx = max(0, rx - buf['day_start_rx'])
            day_tx = max(0, tx - buf['day_start_tx'])
            if day_rx > 0 or day_tx > 0:
                try:
                    upsert_traffic_sample(peer_id, today, day_rx, day_tx)
                except Exception:
                    pass
            buf['last_flush'] = now

        try:
            hs_ts = int(last_hs or 0)
        except (ValueError, TypeError):
            hs_ts = 0

        peer_stats.append({
            'name':               peer['name'],
            'vpn_ip':             peer['vpn_ip'],
            'rx_bytes':           rx,
            'tx_bytes':           tx,
            'rx_rate':            round(rx_rate, 1),
            'tx_rate':            round(tx_rate, 1),
            'rx_fmt':             format_bytes(rx),
            'tx_fmt':             format_bytes(tx),
            'enabled':            bool(peer.get('enabled')),
            'is_active':          active,
            'last_handshake':     format_handshake(last_hs),
            'last_handshake_ts':  hs_ts,
        })

    _rate_history.append({
        'ts':      int(now),
        'rx_rate': round(total_rx_rate, 1),
        'tx_rate': round(total_tx_rate, 1),
    })

    return jsonify({
        'peers':         peer_stats,
        'peer_count':    len(peers),
        'active_count':  active_count,
        'total_rx_fmt':  format_bytes(total_rx),
        'total_tx_fmt':  format_bytes(total_tx),
        'total_rx_rate': round(total_rx_rate, 1),
        'total_tx_rate': round(total_tx_rate, 1),
        'wg_running':    get_interface_status()['running'],
        'history':       list(_rate_history),
    })


@api_bp.route('/api/peer-history/<int:peer_id>')
@login_required
def peer_history(peer_id):
    from database import get_peer_by_id
    peer = get_peer_by_id(peer_id)
    if not peer:
        return jsonify({'error': 'not found'}), 404
    samples = get_peer_daily_traffic(peer_id, days=30)
    return jsonify({'peer_id': peer_id, 'samples': samples})


@api_bp.route('/api/peer/<int:peer_id>/ping')
@login_required
def peer_ping(peer_id):
    import re
    import subprocess
    from database import get_peer_by_id, update_peer_ping
    peer = get_peer_by_id(peer_id)
    if not peer:
        return jsonify({'error': 'not found'}), 404
    if not peer.get('enabled'):
        return jsonify({'reachable': False, 'reason': 'Peer is disabled'})
    live_info = _live_peers().get(peer['public_key'], {})
    last_hs   = live_info.get('last_handshake') or peer.get('last_handshake')
    if not is_peer_active(last_hs):
        return jsonify({'reachable': False, 'reason': 'No recent handshake — peer may be offline'})
    try:
        r = subprocess.run(
            ['ping', '-c', '4', '-W', '2', peer['vpn_ip']],
            capture_output=True, text=True, timeout=15
        )
        out = r.stdout
        loss_m = re.search(r'(\d+)% packet loss', out)
        loss   = int(loss_m.group(1)) if loss_m else 100
        rtt_m  = re.search(r'rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms', out)
        if rtt_m:
            min_ms = float(rtt_m.group(1))
            avg_ms = float(rtt_m.group(2))
            max_ms = float(rtt_m.group(3))
            update_peer_ping(peer_id, avg_ms)
            return jsonify({'reachable': True, 'loss': loss,
                            'min': min_ms, 'avg': avg_ms, 'max': max_ms})
        return jsonify({'reachable': False,
                        'reason': f'Ping sent but no RTT in output (loss: {loss}%)', 'loss': loss})
    except subprocess.TimeoutExpired:
        return jsonify({'reachable': False, 'reason': 'Ping timed out'})
    except Exception as e:
        return jsonify({'reachable': False, 'reason': str(e)})


@api_bp.route('/api/peer/<int:peer_id>/bandwidth')
@login_required
def peer_bandwidth(peer_id):
    from datetime import datetime as dt
    from database import get_peer_by_id, get_peer_bandwidth_snapshots
    peer = get_peer_by_id(peer_id)
    if not peer:
        return jsonify({'error': 'not found'}), 404
    snaps = get_peer_bandwidth_snapshots(peer_id, limit=61)
    if len(snaps) < 2:
        return jsonify({'peer_id': peer_id, 'points': []})
    points = []
    for i in range(1, len(snaps)):
        prev, curr = snaps[i - 1], snaps[i]
        try:
            t1 = dt.fromisoformat(prev['recorded_at'])
            t2 = dt.fromisoformat(curr['recorded_at'])
            secs = (t2 - t1).total_seconds()
            if secs <= 0:
                continue
            rx_rate = max(0.0, curr['rx_bytes'] - prev['rx_bytes']) / secs
            tx_rate = max(0.0, curr['tx_bytes'] - prev['tx_bytes']) / secs
            points.append({
                'ts':      curr['recorded_at'][11:16],   # HH:MM for chart label
                'rx_rate': round(rx_rate, 1),
                'tx_rate': round(tx_rate, 1),
            })
        except Exception:
            continue
    return jsonify({'peer_id': peer_id, 'points': points})


# ── Server health ─────────────────────────────────────────────────────────────

def _cpu_percent():
    try:
        import psutil
        return round(psutil.cpu_percent(interval=0.3), 1)
    except ImportError:
        return None


def _mem_info():
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {'percent': round(vm.percent, 1),
                'used_gb': round(vm.used / 1073741824, 2),
                'total_gb': round(vm.total / 1073741824, 2)}
    except ImportError:
        pass
    try:
        mem = {}
        with open('/proc/meminfo') as f:
            for line in f:
                k, v = line.split(':')
                mem[k.strip()] = int(v.split()[0]) * 1024
        total = mem.get('MemTotal', 0)
        avail = mem.get('MemAvailable', 0)
        used  = total - avail
        pct   = round(used / total * 100, 1) if total else 0
        return {'percent': pct,
                'used_gb': round(used / 1073741824, 2),
                'total_gb': round(total / 1073741824, 2)}
    except Exception:
        return None


def _disk_info():
    try:
        import psutil
        d = psutil.disk_usage('/')
        return {'percent': round(d.percent, 1),
                'used_gb': round(d.used / 1073741824, 2),
                'total_gb': round(d.total / 1073741824, 2)}
    except ImportError:
        import shutil
        d = shutil.disk_usage('/')
        pct = round(d.used / d.total * 100, 1) if d.total else 0
        return {'percent': pct,
                'used_gb': round(d.used / 1073741824, 2),
                'total_gb': round(d.total / 1073741824, 2)}


def _wg_uptime():
    try:
        r = subprocess.run(
            ['systemctl', 'status', f'wg-quick@{WG_INTERFACE}'],
            capture_output=True, text=True, timeout=5
        )
        m = re.search(r'Active: active \(\w+\) since (.+?)(?:;|\n)', r.stdout)
        if not m:
            return None
        since_str = m.group(1).strip()
        since_str = re.sub(r'^\w{3}\s+', '', since_str)  # strip "Thu " prefix
        from datetime import timezone
        for fmt in ['%Y-%m-%d %H:%M:%S %Z', '%Y-%m-%d %H:%M:%S']:
            try:
                dt = datetime.strptime(since_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        else:
            return None
        diff = int((datetime.now(timezone.utc) - dt).total_seconds())
        if diff < 0:
            return None
        d, rem = divmod(diff, 86400)
        h, rem = divmod(rem, 3600)
        mn     = rem // 60
        parts  = []
        if d:  parts.append(f'{d}d')
        if h or d: parts.append(f'{h}h')
        parts.append(f'{mn}m')
        return ' '.join(parts)
    except Exception:
        return None


@api_bp.route('/api/server/health')
@login_required
def server_health():
    from database import get_last_speedtest
    from wireguard import WG_ENDPOINT
    last_st = get_last_speedtest()
    return jsonify({
        'cpu_percent':  _cpu_percent(),
        'memory':       _mem_info(),
        'disk':         _disk_info(),
        'wg_uptime':    _wg_uptime(),
        'wg_running':   get_interface_status()['running'],
        'server_ip':    WG_ENDPOINT,
        'last_speedtest': {
            'download_mbps': last_st['download_mbps'],
            'upload_mbps':   last_st['upload_mbps'],
            'ping_ms':       last_st['ping_ms'],
            'tested_at':     last_st['tested_at'],
        } if last_st else None,
    })


# ── Speedtest ─────────────────────────────────────────────────────────────────

_speedtest_job  = {'running': False, 'result': None, 'error': None}
_speedtest_lock = threading.Lock()


def _run_speedtest_bg():
    import json as _json
    try:
        r = subprocess.run(
            ['speedtest-cli', '--json', '--secure'],
            capture_output=True, text=True, timeout=120
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or 'speedtest-cli failed')
        data     = _json.loads(r.stdout)
        download = round(data['download'] / 1_000_000, 2)
        upload   = round(data['upload']   / 1_000_000, 2)
        ping     = round(data['ping'], 1)
        srv      = data.get('server', {})
        srv_name = f"{srv.get('name','')}, {srv.get('country','')}".strip(', ')
        from database import record_speedtest
        record_speedtest(download, upload, ping, srv_name)
        with _speedtest_lock:
            _speedtest_job.update({'running': False,
                                   'result': {'download': download, 'upload': upload,
                                              'ping': ping, 'server': srv_name},
                                   'error': None})
    except Exception as exc:
        with _speedtest_lock:
            _speedtest_job.update({'running': False, 'result': None, 'error': str(exc)})


@api_bp.route('/api/speedtest/run', methods=['POST'])
@login_required
def speedtest_run():
    with _speedtest_lock:
        if _speedtest_job['running']:
            return jsonify({'status': 'already_running'})
        _speedtest_job.update({'running': True, 'result': None, 'error': None})
    t = threading.Thread(target=_run_speedtest_bg, daemon=True, name='speedtest')
    t.start()
    return jsonify({'status': 'running'})


@api_bp.route('/api/speedtest/status')
@login_required
def speedtest_status():
    with _speedtest_lock:
        return jsonify({
            'running': _speedtest_job['running'],
            'result':  _speedtest_job['result'],
            'error':   _speedtest_job['error'],
        })
