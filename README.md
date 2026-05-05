<p align="center">
  <img width="200" height="200" alt="app" src="https://github.com/user-attachments/assets/26d75f18-7a2e-4c23-be28-4ff3207a8e08" />
</p>

### Traverse

A self-hosted WireGuard VPN dashboard built with Flask. Manage peers, monitor live traffic, view connection maps, and control your WireGuard interface — all from a clean dark-themed web UI.

<img width="1633" height="1145" alt="image" src="https://github.com/user-attachments/assets/abe368e0-691f-458d-b5eb-eff73840fdff" />

<img width="1628" height="1110" alt="image" src="https://github.com/user-attachments/assets/4be98729-2577-4475-895c-56c4db91f40d" />

---

## Features

- **Peer management** — create, view, and delete WireGuard peers (hard cap of 50); each peer gets a unique VPN IP automatically allocated from the configured subnet
- **Config download & QR codes** — download a ready-to-use `.conf` file or scan an inline QR code to onboard any device in seconds
- **Peer expiry** — set an expiry date per peer; expired peers are automatically disabled when the server starts or on each scheduled check
- **Live traffic stats** — per-peer RX/TX bytes and transfer rate, polled every second with a 5-minute scrolling Chart.js waveform on the dashboard
- **Connection map** — Leaflet.js world map showing the real-world location of each connected peer's endpoint IP (GeoIP via ipapi.co, cached 1 hour)
- **Traffic history** — timestamped connection event log per peer: when they connected, disconnected, and how much data they transferred
- **Alerts** — in-app alert feed for peer events (new connections, inactivity, WireGuard going down); unread count shown in the navbar badge
- **Telegram notifications** — optional Telegram bot integration; get push alerts when a peer connects, goes inactive, or the WireGuard interface goes down
- **TOTP 2FA** — optional time-based two-factor authentication (Google Authenticator / Authy compatible) on top of username/password login
- **Interface control** — start, stop, and restart the WireGuard interface from the dashboard; view the current server config snippet
- **Full-tunnel routing** — `AllowedIPs = 0.0.0.0/0` so all client traffic exits through your VPS; your VPS public IP becomes the client's public IP
- **No CDN dependencies** — Chart.js, Leaflet.js, and all assets are bundled locally; works fully offline after install

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.12 |
| Framework | Flask 3.1 (Blueprints) |
| Database | SQLite (WAL mode) via stdlib `sqlite3` |
| WireGuard | `wg` / `wg-quick` CLI (wireguard-tools) |
| QR codes | `qrcode[pil]` + Pillow |
| 2FA | `pyotp` (TOTP / RFC 6238) |
| Alerts | Telegram Bot API (stdlib `urllib` only, no SDK) |
| Frontend | Custom dark CSS — no JS framework, no external CDN |
| Charts | Chart.js v4 (bundled locally) |
| Map | Leaflet.js v1.9.4 (bundled locally) |

---

## Requirements

- **OS**: Linux VPS — tested on Ubuntu 22.04 / Debian 12
- **Python**: 3.12+
- **WireGuard**: `apt install wireguard`
- **Privileges**: must run as `root` (needs access to `wg`, `wg-quick`, and `systemctl`)
- **Ports**: UDP `51820` open for WireGuard; TCP `443`/`80` open for the web UI (if using nginx + HTTPS)

---

## Installation

### 1. Install system dependencies

```bash
apt update && apt install -y wireguard python3.12 python3.12-venv python3-pip nginx
```

### 2. Clone the repository

```bash
git clone https://github.com/syedhashmi-bit/traverse.git /var/www/traverse
cd /var/www/traverse
```

### 3. Create a Python virtualenv and install packages

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Generate WireGuard server keys

```bash
wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key
chmod 600 /etc/wireguard/server_private.key
chmod 644 /etc/wireguard/server_public.key
```

### 5. Create the WireGuard server config

```bash
nano /etc/wireguard/wg0.conf
```

```ini
[Interface]
Address    = 10.8.0.1/24
ListenPort = 51820
PrivateKey = <contents of /etc/wireguard/server_private.key>
PostUp     = iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE
PostDown   = iptables -t nat -D POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE
```

> Replace `eth0` with your actual outbound network interface (`ip route | grep default` shows it).

```bash
chmod 600 /etc/wireguard/wg0.conf
```

### 6. Enable IP forwarding

```bash
echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
sysctl -p
```

### 7. Start WireGuard

```bash
systemctl enable --now wg-quick@wg0
wg show wg0   # confirm it's running
```

### 8. Configure the application

```bash
cp .env.example .env
nano .env
```

Fill in every required variable — see the [Environment Variables](#environment-variables) table below. At minimum set:

- `SECRET_KEY` — generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"`
- `ADMIN_PASSWORD` — change from the default
- `WG_ENDPOINT` — your VPS public IP or domain name

---

## Environment Variables

All configuration lives in `.env`. Never commit this file.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | **yes** | — | Random 32+ char string used to sign Flask sessions. Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_USERNAME` | **yes** | `admin` | Dashboard login username |
| `ADMIN_PASSWORD` | **yes** | — | Dashboard login password — **change this** |
| `WG_ENDPOINT` | **yes** | — | Your VPS public IP or domain (put into every peer's client config) |
| `WG_INTERFACE` | no | `wg0` | WireGuard interface name |
| `WG_PORT` | no | `51820` | UDP port WireGuard listens on |
| `WG_SUBNET` | no | `10.8.0.0/24` | VPN subnet — IPs are auto-allocated from this range |
| `WG_SERVER_VPN_IP` | no | `10.8.0.1` | Server's own VPN IP — skipped during peer IP allocation |
| `WG_DNS` | no | `1.1.1.1` | DNS server pushed to clients in their config |
| `DATABASE_PATH` | no | `database.db` | Path to the SQLite file (relative to project root) |
| `TOTP_SECRET` | no | — | Enables TOTP 2FA. Generate: `python3 -c "import pyotp; print(pyotp.random_base32())"` then scan the QR at `/totp-setup` |
| `TELEGRAM_BOT_TOKEN` | no | — | Telegram bot token — both must be set to enable push alerts |
| `TELEGRAM_CHAT_ID` | no | — | Telegram chat ID to send alerts to |
| `ALERT_INACTIVE_HOURS` | no | `0` (disabled) | Hours of inactivity before a peer triggers an alert |

---

## Running the App

### Development

```bash
cd /var/www/traverse
source venv/bin/activate
python app.py   # listens on 0.0.0.0:5000
```

Open `http://localhost:5000` — log in with your `ADMIN_USERNAME` / `ADMIN_PASSWORD`.

### Production (systemd + gunicorn + nginx)

**a) Create the log directory**

```bash
mkdir -p /var/log/traverse
```

**b) Create the systemd service**

```bash
nano /etc/systemd/system/traverse.service
```

```ini
[Unit]
Description=Traverse WireGuard VPN Dashboard
After=network.target

[Service]
Type=notify
User=root
Group=root
WorkingDirectory=/var/www/traverse
EnvironmentFile=/var/www/traverse/.env
ExecStart=/var/www/traverse/venv/bin/gunicorn \
    --workers 2 \
    --bind 127.0.0.1:5000 \
    --timeout 60 \
    --access-logfile /var/log/traverse/access.log \
    --error-logfile /var/log/traverse/error.log \
    --capture-output \
    "app:create_app()"
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now traverse
systemctl status traverse
```

**c) Configure nginx**

```bash
nano /etc/nginx/sites-available/traverse
```

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass            http://127.0.0.1:5000;
        proxy_set_header      Host              $host;
        proxy_set_header      X-Real-IP         $remote_addr;
        proxy_set_header      X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header      X-Forwarded-Proto $scheme;
        proxy_read_timeout    60s;
        proxy_connect_timeout 10s;
        proxy_buffering       off;
    }
}
```

```bash
ln -sf /etc/nginx/sites-available/traverse /etc/nginx/sites-enabled/traverse
nginx -t && systemctl reload nginx
```

**d) Issue a free SSL certificate with Certbot**

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d your-domain.com
```

Certbot will automatically configure HTTPS and set up auto-renewal.

---

## Optional Features

### TOTP Two-Factor Authentication

1. Generate a secret and add it to `.env`:
   ```bash
   python3 -c "import pyotp; print(pyotp.random_base32())"
   # → add TOTP_SECRET=<output> to .env
   ```
2. Restart the app: `systemctl restart traverse`
3. Open `/totp-setup` in your browser — scan the QR code with Google Authenticator or Authy
4. From now on, login requires username + password + 6-digit TOTP code

### Telegram Alerts

1. Create a bot via [@BotFather](https://t.me/BotFather) and copy the token
2. Get your chat ID (message [@userinfobot](https://t.me/userinfobot))
3. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-your-token
   TELEGRAM_CHAT_ID=your-chat-id
   ALERT_INACTIVE_HOURS=24
   ```
4. Restart: `systemctl restart traverse`

You'll receive Telegram messages when:
- A peer connects or reconnects
- A peer goes inactive for longer than `ALERT_INACTIVE_HOURS`
- The WireGuard interface goes down

---

## Managing the Service

```bash
# Status of all three services
systemctl status traverse nginx wg-quick@wg0

# Restart after config/code changes
systemctl restart traverse

# Reload nginx after config changes (zero-downtime)
nginx -t && systemctl reload nginx

# Restart WireGuard (drops all VPN connections briefly)
systemctl restart wg-quick@wg0

# Live app logs
journalctl -u traverse -f

# Access and error logs
tail -f /var/log/traverse/access.log
tail -f /var/log/traverse/error.log

# WireGuard peer status
wg show wg0

# Check SSL certificate expiry
openssl x509 -in /etc/letsencrypt/live/your-domain.com/fullchain.pem -noout -dates

# Force SSL renewal (auto-renewal is configured by Certbot)
certbot renew --force-renewal
```

---

## Project Structure

```
traverse/
├── app.py                  # Flask app factory, blueprints, error handlers
├── database.py             # SQLite init + all DB helpers (peers, alerts, history)
├── wireguard.py            # wg CLI wrappers, key gen, IP allocation, config gen
├── alerts.py               # Background thread: peer/WG monitoring + Telegram push
├── routes/
│   ├── auth.py             # /login, /logout, login_required decorator
│   ├── dashboard.py        # GET / — status cards, live chart, recent peers
│   ├── peers.py            # Peer CRUD, config download, QR code, expiry
│   ├── api.py              # GET /api/stats — live JSON (1-s polling, 0.85-s cache)
│   ├── map.py              # GET /map, GET /api/peer-locations (30-s poll, 1-h geo cache)
│   ├── settings.py         # WireGuard interface control, server config view
│   ├── alerts.py           # Alert feed, mark-seen, dismiss
│   └── history.py          # Per-peer connection event history
├── templates/
│   ├── base.html           # Sidebar layout, flash messages, nav, alert badge
│   ├── dashboard.html      # Live stats, Chart.js waveform, recent peers table
│   ├── login.html          # Login form (+ TOTP field when 2FA is enabled)
│   ├── map.html            # Leaflet map + peer sidebar
│   ├── alerts.html         # Alert feed
│   ├── history.html        # Connection history table
│   ├── settings.html       # Interface control + config snippet
│   ├── totp_setup.html     # QR code setup for TOTP 2FA
│   ├── totp_verify.html    # TOTP verification step
│   ├── 404.html / 500.html # Error pages
│   └── peers/
│       ├── list.html       # Full peer table (no private keys shown)
│       ├── create.html     # Create peer form (shows X/50 counter)
│       ├── detail.html     # Peer detail, keys, config, QR, live stats
│       └── qr.html         # Standalone QR code page
├── static/
│   ├── css/
│   │   ├── style.css       # Complete dark theme (CSS variables, animations)
│   │   └── leaflet.min.css # Leaflet CSS (bundled)
│   ├── js/
│   │   ├── app.js          # Copy-to-clipboard, confirm-delete, flash dismiss
│   │   ├── chart.min.js    # Chart.js v4 (bundled)
│   │   └── leaflet.min.js  # Leaflet.js v1.9.4 (bundled)
│   └── img/                # App screenshot, icons, Leaflet marker images
├── .env.example            # Environment variable template (safe to commit)
├── requirements.txt        # Python dependencies
└── database.db             # SQLite file — created automatically on first run
```

---

## Security Notes

- **Private keys** are shown only on the peer detail page and in downloaded `.conf` files — never in the peer list or any API response
- **No shell injection** — all `subprocess` calls use list form (`shell=False`)
- **Peer name validation** — enforced against `^[a-zA-Z0-9_\-]{1,64}$`
- **Preshared keys** are written to a temp file during `wg set` to keep them off the process argument list
- **Credential comparison** uses `hmac.compare_digest` (timing-safe; prevents timing oracle attacks)
- **Session expiry** — `session.permanent = False` so sessions die when the browser closes
- **Secrets in `.env` only** — no credentials in code or the database
- **50-peer hard cap** — enforced server-side in the create route; prevents runaway config growth

---

## License

MIT
