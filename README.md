<img width="1254" height="1254" alt="app" src="https://github.com/user-attachments/assets/26d75f18-7a2e-4c23-be28-4ff3207a8e08" />


### Traverse

A self-hosted WireGuard VPN dashboard built with Flask. Manage peers, monitor live traffic, view connection maps, and control your WireGuard interface — all from a clean dark-themed web UI.

<img width="1633" height="1145" alt="image" src="https://github.com/user-attachments/assets/abe368e0-691f-458d-b5eb-eff73840fdff" />

<img width="1628" height="1110" alt="image" src="https://github.com/user-attachments/assets/4be98729-2577-4475-895c-56c4db91f40d" />



## Features

- **Peer management** — create, view, delete peers (hard cap of 50); download `.conf` files or scan QR codes
- **Live traffic stats** — 1-second polling with a 5-minute scrolling Chart.js waveform
- **Connection map** — Leaflet.js map showing where peers are connecting from (GeoIP via ipapi.co)
- **Interface control** — start/stop WireGuard, view server config snippet
- **Traffic history** — per-peer RX/TX history log
- **Alerts** — configurable alerts for peer events
- **Auth** — login-protected with timing-safe credential comparison; session expires on browser close
- **Full-tunnel routing** — `AllowedIPs = 0.0.0.0/0` so all client traffic exits through the VPS

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.12 |
| Framework | Flask 3.1 (Blueprints) |
| Database | SQLite (WAL mode) via stdlib `sqlite3` |
| WireGuard | `wg` / `wg-quick` CLI |
| QR codes | `qrcode[pil]` + Pillow |
| Frontend | Custom dark CSS (no external CDN, no JS framework) |
| Charts | Chart.js v4 (bundled locally) |
| Map | Leaflet.js v1.9.4 (bundled locally) |

## Requirements

- Linux VPS (tested on Ubuntu/Debian)
- Python 3.12+
- WireGuard installed: `apt install wireguard`
- App must run as root (needs `wg` and `systemctl` access)

## Setup

### 1. Clone and install

```bash
git clone https://github.com/syedhashmi-bit/traverse.git /var/www/traverse
cd /var/www/traverse
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
nano .env
```

Set these variables in `.env`:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Random 32+ char string for Flask sessions |
| `ADMIN_USERNAME` | Dashboard login username |
| `ADMIN_PASSWORD` | Dashboard login password |
| `WG_ENDPOINT` | Your VPS public IP or domain |
| `WG_INTERFACE` | WireGuard interface name (default: `wg0`) |
| `WG_PORT` | UDP listen port (default: `51820`) |
| `WG_SUBNET` | VPN subnet (default: `10.8.0.0/24`) |
| `WG_DNS` | DNS pushed to clients (default: `1.1.1.1`) |

### 3. Set up WireGuard server keys

```bash
wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key
chmod 600 /etc/wireguard/server_private.key
```

### 4. Run (development)

```bash
source venv/bin/activate
python app.py   # listens on 0.0.0.0:5000
```

### 5. Production (systemd + gunicorn + nginx)

Run the app via gunicorn and proxy with nginx. Enable IP forwarding and configure NAT:

```bash
# IP forwarding
sysctl -w net.ipv4.ip_forward=1
echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf

# NAT (replace eth0 with your outbound interface)
iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE
```

## Project Structure

```
traverse/
├── app.py              # Flask app factory
├── database.py         # SQLite helpers
├── wireguard.py        # wg CLI wrappers, key gen, IP allocation
├── alerts.py           # Alert logic
├── routes/
│   ├── auth.py         # Login/logout + login_required decorator
│   ├── dashboard.py    # Home — status cards + recent peers
│   ├── peers.py        # Peer CRUD, config download, QR codes
│   ├── api.py          # /api/stats — live JSON (1-s polling)
│   ├── map.py          # /map + /api/peer-locations
│   ├── settings.py     # Interface control
│   ├── alerts.py       # Alert routes
│   └── history.py      # Traffic history
├── templates/          # Jinja2 HTML templates
├── static/
│   ├── css/style.css   # Dark theme CSS
│   ├── js/             # app.js, Chart.js, Leaflet.js (all bundled)
│   └── img/            # Icons and app screenshot
├── .env.example        # Environment variable template
└── requirements.txt
```

## Security Notes

- Private keys are shown **only** on the peer detail page and in downloaded config files — never in the peer list
- All `subprocess` calls use list form (`shell=False`) to prevent injection
- Peer names validated against `^[a-zA-Z0-9_\-]{1,64}$`
- Preshared keys are written to a temp file during `wg set` to keep them off the process list
- Credentials stored only in `.env`, compared with `hmac.compare_digest` (timing-safe)

## License

MIT
