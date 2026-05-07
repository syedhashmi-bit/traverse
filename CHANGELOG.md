# Changelog

## [1.1.0] — 2026-05-07 (Batch 2 — UX & Notifications)

### Added
- Clickable peer rows on `/peers` — entire row navigates to detail (View button removed; QR retained; row click ignores nested links/buttons/forms)
- Copy-to-clipboard icon button next to VPN IP on peer detail page (✓ feedback for 2 s)
- Client-side peer search/filter (matches name, VPN IP, device type) with × clear and "🔍 No peers match" empty row
- Mini RX+TX sparklines per peer row, drawn on a `<canvas>` (no library) — green for active peers, grey for inactive, flat baseline if no data
- Session timer column on `/peers` showing duration since last `connected` event (e.g. `2h 14m`); refreshes every 60 s client-side
- Browser push notifications for peer connect/disconnect — `Notification.requestPermission()` asked once (state in `localStorage`); `/api/events/latest` polled every 60 s
- Sound alert toggle (🔔 / 🔕) in topbar — Web Audio API tones (880 Hz on connect, 440 Hz on disconnect); only plays when sound enabled AND notifications granted
- Kill button per peer (⚡) on detail page and each row — `POST /api/peer/<id>/kill` removes from wg0 and sets `enabled = 0`
- Peer location history (`peer_locations` table) — endpoint IP changes recorded with geo lookup; last 5 shown on detail page with flag emoji, city/country, masked IP, first/last seen
- Smooth `fadeIn` page transitions (150 ms CSS, respects `prefers-reduced-motion`)
- Help overlay (`?` topbar button) — tips, page index, quick stats, version; closes on outside click or Escape
- Friendly empty states on `/peers` and dashboard when no peers exist (large 🔒, "No peers yet", "Add your first device to get started", prominent + Add Peer CTA)

### Changed
- Live traffic chart on dashboard rebuilt — NOW / PEAK / AVG header stats, pulsing `● LIVE` dot (turns amber `● PAUSED` when paused), Chart.js v4 responsive gradients via `chartArea`, RX colour switched to cyan `#22d3ee`
- Speedtest now reports 1 decimal place instead of 2
- WG SHOW panel: `overflow-x: hidden` + `max-width: 100%` so long public keys can't blow the column

### Fixed
- `list_peers()` raw-timestamp bug — `last_handshake` was being overwritten with a formatted string before `_last_seen()` parsed it (always returned `never`)
- Pi-hole `api_seats_exceeded` — `_pihole_logout()` now `DELETE`s the old session before creating a new one; `max_sessions = 64` in `pihole.toml`
- `is_peer_active` threshold raised 180 → 300 s to avoid false-inactive flips during the ~170 s WireGuard rekey window
- Removed the duplicate Pi-hole `● ACTIVE` indicator on the dashboard (it was rendered both in the NOC bar and the Pi-hole bar)

### Database
- New table `peer_locations(id, peer_id, endpoint_ip, endpoint_port, geo_country, geo_city, geo_lat, geo_lon, geo_country_code, first_seen_at, last_seen_at)` — capped at 10 rows per peer (oldest by `last_seen_at` evicted)
- `connection_events.event_type` now includes `killed` (logged when `POST /api/peer/<id>/kill` succeeds)

### API
- `POST /api/peer/<id>/kill` — disconnect & disable a peer; preserves the DB record
- `GET  /api/peer/<id>/sparkline` — returns up to 10 RX+TX rate values from `peer_bandwidth_snapshots`
- `GET  /api/events/latest` — connection events from the last 70 s (drives the notification poller)

---

## [1.0.0] — 2026-05-07

### Added
- Full WireGuard VPN dashboard with peer CRUD (create, view, edit, delete, enable/disable)
- Auto-assigned VPN IPs from configurable subnet (10.8.0.0/24)
- WireGuard keypair generation (private, public, preshared keys) via `wg` CLI
- Client `.conf` file download and inline QR code on peer detail page
- Live traffic dashboard: 1-second polling, Chart.js RX/TX waveform, RAF-animated speed numbers
- NOC-style status bar (peers, active count, total RX/TX, WireGuard state)
- Server health bar: CPU, RAM, disk, WG uptime, VPS speed
- Pi-hole v6 integration: DNS blocking for all VPN clients
- Pi-hole status bar on dashboard: blocked count, rate, blocklist size, query count, client count
- Pi-hole DNS query log per peer on peer detail page
- Top blocked domains widget on dashboard (5-minute refresh)
- Connection map with Leaflet.js, peer geolocation via ipapi.co
- Background poller (60 s): WG down detection, peer connect/disconnect events, expired peer auto-disable, bandwidth anomaly alerts
- Telegram alert notifications (optional, via TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)
- TOTP 2FA support (optional, via TOTP_SECRET in .env)
- Traffic history chart per peer (30-day daily RX/TX)
- Speedtest widget (speedtest-cli integration)
- Backup / restore (JSON export/import of all peers and events)
- Per-peer device type (phone/laptop/desktop/tablet/router/other) with emoji icons
- Per-peer notes and optional expiry date with auto-disable
- Per-peer Pi-hole DNS toggle (use Pi-hole or fall back to 1.1.1.1)
- Connection history log (/history)
- Alerts page with severity badges (/alerts)
- Dark/light theme toggle (localStorage persistent)
- Dashboard auto-refresh pause/resume toggle
- Last-seen indicator on peers list (colour-coded relative time)
- One-page peer setup wizard with config preview step (/peers/wizard)
- Network topology diagram with Canvas — clickable peer nodes (/topology)
- System log viewer with live mode + client-side filter (/logs)
- Changelog and about page (/about)
- Settings page: WireGuard control, Pi-hole control, backup/restore, speedtest history, TOTP setup
