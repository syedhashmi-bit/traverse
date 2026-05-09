# Changelog

## [1.6.0] — 2026-05-09 (UI Primitives, Sortable Peers, Bulk Actions, CSV)

### Added
- **Toast notifications** — top-right slide-in toasts with success/error/warning/info variants, click-to-close, auto-dismiss after 4s. Mobile-responsive. `window.toast(msg, type, opts)`.
- **Confirm modal** — promise-based styled modal replacing every native `confirm()` dialog. Keyboard support (Esc cancels, Enter confirms). Capture-phase form handler auto-upgrades every existing `[data-confirm]` form without per-form changes. `window.confirmDialog({title, body, confirmLabel, danger})`.
- **Top loading bar** — 2px accent gradient at the top of the viewport during fetch activity. Auto-wraps `fetch()` globally; skip-list excludes 1-second pollers (`/api/stats`, `/api/server/health`, etc.) so it isn't perpetually active. `window.tvProgress.start() / .done()`.
- **Command palette** — `Cmd/Ctrl+K` opens a fuzzy-search palette with 15 commands (page navigation + theme toggle + help + sign out). Arrow-key navigation, Enter selects, Escape closes.
- **Keyboard shortcuts** — `?` opens help, `/` focuses search, `n` opens "new peer" wizard, sequence navigation: `g d` Dashboard, `g p` Peers, `g m` Map, `g a` Alerts, `g t` Topology, `g y` History, `g l` Logs, `g n` Notifications, `g f` Port Forwards, `g s` Settings.
- **Sortable peer table** — 10 sortable columns (id, name, device, IP, tunnel, status, last seen, RX/TX, expires, created). Click header to toggle asc/desc; arrow indicator; sort state persisted to `localStorage`. IPs zero-padded for correct numeric ordering.
- **Filter chips on `/peers/`** — three dimensions (Tunnel × Status × Device). Within-dimension OR, across-dimension AND, combinable with text search. Click a chip to toggle; "Clear filters" resets all.
- **Bulk actions on `/peers/`** — checkbox column with master checkbox respecting visible rows (indeterminate state included). Floating action bar exposes Disable/Enable/Delete with confirmation modal. Backend endpoints `POST /peers/bulk-disable | bulk-enable | bulk-delete` accept comma-separated IDs, sync wg0, and fire per-peer notifications.
- **CSV export** on `/peers/`, `/history`, `/alerts`, `/notifications`. Peer export strips `private_key` and `preshared_key` server-side as defense in depth. Capped at 2000 / 2000 / 2000 / 500 rows.
- **Real-time event feed** on the dashboard right column — polls `/api/events/recent` every 30 s, renders connect/disconnect/kill events with color-coded dots and relative timestamps. Respects the global pause toggle.
- **Skeleton states** for the rest of the live-loading panels — server health (CPU/RAM/disk/uptime/speed), Pi-hole bar (blocked/rate/blocklist/queries/clients), and the NOC PIHOLE indicator now shimmer until their `/api/server/health` and `/api/pihole-stats` fetches resolve.
- **Topology server-node ring** — DOM overlay with the existing `.topology-server-ring` CSS animation (slow-rotating dashed border) is now wired and visible on the topology page. Hidden when no peers are configured.

### Changed
- **Friendly empty states** — `/history`, `/alerts`, and the notifications log section now use `.empty-state-friendly` (large icon + heading + sub-text + optional CTA) matching the rest of the app.
- **Help overlay** — now lists every keyboard shortcut.
- **`/peers/` row Kill action** — now uses the new modal + toast flow instead of native `confirm()` + `alert()`.
- **SW cache name bumped `traverse-v2 → traverse-v3`** — installed PWA clients re-precache fresh `style.css` / `app.js` on next activation.

### Light theme
- ~150 lines of additional overrides covering: tables, search input, help overlay, form labels, badges, last-seen colors, NOC alert rows, quick nav, action buttons, install banner, sidebar nav, bottom nav, toasts, confirm modal, command palette, filter chips, skeleton, kbd, event feed, bulk action bar, sortable headers.

### Database
No schema changes. All new endpoints query existing tables.

### Files Modified
```
routes/{peers, api, history, alerts, notifications}.py
static/{css/style.css, js/app.js, sw.js}
templates/{base, dashboard, peers/list, history, alerts, notifications, topology}.html
```
+1758 / -136 lines across 15 files.

---

## [1.5.0] — 2026-05-08 (Performance + Polish)

### Performance
- **Flask response caching** via `flask-caching` — `/api/server/health` cached 15s (avoids re-running `psutil.cpu_percent(interval=0.3)`, `systemctl status wg-quick@wg0`, `pihole status`, `gravity.db` query on every poll); `/api/pihole/top-blocked` cached 55s
- **Database indexes** — `peers.enabled`, `peers.expires_at`, `connection_events.{peer_id,timestamp}`, `peer_bandwidth_snapshots.{peer_id,recorded_at}` (composite + singles), `alerts.{seen,created_at}`, `notification_log.sent_at`, `peer_locations.{peer_id,last_seen_at}`, `speedtest_results.tested_at`, `traffic_samples (peer_id, day)` — created in `init_db()` via `IF NOT EXISTS`
- **Nginx gzip** — `gzip on; gzip_comp_level 6` for HTML/CSS/JS/JSON/SVG. Result: `style.css` 72.5 KB → 13.2 KB on the wire (82% smaller); login HTML 3.1 KB → 1.1 KB (64%)
- **Nginx static caching** — `/static/` returns `Cache-Control: public, immutable, max-age=604800`; `access_log off` (no log churn for fonts/icons/CSS)
- **JS deferred** — `app.js` now uses `defer` so it does not block parsing
- **Poller audit** — `alerts.py` already runs on a 60s tick (not a tight loop); single tick covers WG show + bandwidth + pi-hole probe within ~1s; no stagger needed

### Visual polish
- **Skeleton shimmer** utility (`.skeleton`) for placeholder loading states
- **Stat bars** — padding tightened by ~20%, accent border-bottom separator between bars
- **Number flash** — chart NOW/PEAK/AVG values now flash accent → normal over 0.32s on change
- **Online dot pulse** — peers table green dots pulse at 2.2s
- **Alt rows + hover** — peer table rows alternate at `rgba(255,255,255,0.018)`, hover at `rgba(124,106,247,0.06)`; action chevrons fade in on row hover only
- **Right panel** — left-accent border bar on each section
- **Form focus rings** — consistent accent border + 3px halo on every input/textarea/select focus
- **Touch feedback** — `transform: scale(0.97)` active state on every button + nav item
- **Toggle switches** — proper `.toggle-switch` CSS-only component (44×24, accent ON, focus ring)
- **Status banner** — peer detail page now shows green/red banner at the top reflecting enabled state
- **Topology** — radial dot grid background pattern; CSS for slow-rotating server ring + active peer pulse glow available
- **Map** — `.map-vignette` wrapper applies a subtle inner box-shadow for depth at the edges
- **Bottom nav** — 2px accent line on top of the active tab (mobile)
- **Pi-hole grid** — `.ph-blocked-warn` (amber) / `.ph-blocked-zero` (green) classes for state-aware blocked count
- **Mobile font floor** — any `font-size:9px/10px` inline style auto-bumped to 11px on ≤768px
- **Page transition** — fade-in trimmed from 0.15s → 0.1s on mobile
- **Scrollbars** — 6px thumb at `rgba(255,255,255,0.12)`, hover `0.22`, transparent track — applied universally
- **Border-radius consistency** — 6px on `.btn`/action buttons, 999px (pill) on badges, 4px on inputs

### Added
- `cache_ext.py` — shared `Cache` instance (SimpleCache, 30s default)
- `flask-caching>=2.4.0` in `requirements.txt`

### Files Modified
- `app.py` — `cache.init_app(app)` after Flask app creation
- `database.py` — index creation block in `migrate_db()`
- `routes/api.py` — `@cache.cached` on `/api/server/health` (15s) + `/api/pihole/top-blocked` (55s)
- `templates/base.html` — `defer` on `app.js`
- `templates/peers/detail.html` — peer status banner at top
- `templates/topology.html` — `.topology-grid-bg` class on canvas card
- `templates/map.html` — `.map-vignette` wrapper on map card
- `static/css/style.css` — appended polish block (~250 lines)
- `/etc/nginx/sites-available/traverse` — gzip directives, `location /static/` with 7d immutable caching
- `VERSION` → 1.5.0

### Measurements
| Asset                | Before  | After (gzip) | Reduction |
|----------------------|--------:|-------------:|----------:|
| style.css            | 72.5 KB |     13.2 KB  | 82%       |
| login HTML           |  3.1 KB |      1.1 KB  | 64%       |
| Repeat-visit static  | network |  browser     | 100%      |

Cold load (`GET /` → 302 to `/login`): ~78 ms → ~50–65 ms (latency-bound; gains compound across the asset graph on first authenticated visit, where chart.min.js (200 KB → ~58 KB) and leaflet.min.js (147 KB → ~42 KB) compress).

---

## [1.4.0] — 2026-05-08 (Progressive Web App)

### Added
- **Installable PWA** — traverse can now be installed as a standalone app on iOS Safari, Android Chrome, and desktop Chromium browsers
- **Web App Manifest** at `/manifest.json` — eight icon sizes (72→512), maskable variants for Android adaptive icons, three app shortcuts (All Peers, Add Peer, Alerts)
- **Service worker** at `/sw.js` — precaches the app shell on install, runtime network-first with cache fallback, falls back to `/offline` page when network is unreachable. API calls (`/api/*`) bypass the cache so live data is always fresh.
- **Offline page** at `/offline` — standalone dark page with traverse logo, retry button, and auto-reload when the browser fires `online`
- **iOS PWA support** — apple-touch-icon, apple-touch-startup-image (1242×2688 splash with centered logo), `apple-mobile-web-app-capable`/`-status-bar-style`/`-title` meta tags
- **Install banner** — slim top bar that surfaces on Android/desktop Chrome via `beforeinstallprompt`; dismissable, remembers dismissal via localStorage, hides automatically once installed
- **iOS install tip** — static "Add to Home Screen" tooltip for iOS Safari (which doesn't fire `beforeinstallprompt`); separate dismissal key
- **Push notification handler** in the SW (server-side VAPID wiring is future work; the listener is in place)

### Files Added
- `static/manifest.json`
- `static/sw.js`
- `static/icons/` — `icon-{72,96,128,144,152,192,384,512}.png`, `apple-touch-icon.png`, `splash-1242x2688.png`
- `templates/offline.html`
- `routes/pwa.py` — new blueprint with `/manifest.json`, `/sw.js`, `/offline` (all public, no `login_required`)

### Files Modified
- `app.py` — registered `pwa_bp`
- `templates/base.html` — PWA meta tags in `<head>`, install banner + iOS tip elements, SW registration script, install prompt controllers
- `static/css/style.css` — `.install-banner` styles + slide-down animation + mobile breakpoint
- `VERSION` → 1.4.0

### Implementation notes
- `sw.js` is served with `Service-Worker-Allowed: /` so the SW can scope to the entire origin even though the file lives under `/static/` on disk
- `sw.js` is served `no-cache, no-store, must-revalidate` so updates propagate immediately; the SW versions its own asset cache via `CACHE_NAME` (currently `traverse-v1`)
- `/` is intentionally not in the precache list — it 302s to `/login` for unauthenticated visits, so precaching it would store the redirect or login page
- The original brief specified `/static/css/main.css` in the SW precache list; the actual CSS file is `style.css`, so the precache list was corrected to point at the real file
- All 10 generated icons composite correctly on Android adaptive backgrounds — the source `app.png` is RGB and gets `convert('RGBA')` before resize

---

## [1.3.0] — 2026-05-08 (Notifications)

### Added
- **Notifications page** at `/notifications` — manage Email (SMTP), Telegram, and Discord channels in one place
  - Each channel has its own enable toggle, configuration form, "Send Test" button (synchronous, shows ✅/❌ inline), and Save button
  - Telegram and Discord sections include collapsible setup instructions
  - Per-event toggles let you choose which of 15 event types fire notifications (peer_connected, peer_disconnected, peer_inactive_long, peer_expired, bw_anomaly, wg_down, wg_recovered, pihole_down, pihole_recovered, peer_added, peer_deleted, peer_killed, config_regenerated, login_success, login_failed)
  - Recent attempts log shows last 20 sends (timestamp, channel icon, event type, message snippet, ✅/❌ status, expandable error detail); "Clear log" button
  - Sidebar bell icon with green dot when at least one channel is enabled and minimally configured
- **Multi-channel notification dispatch** — every wired event fires on all enabled channels simultaneously, in a background thread (never blocks request handlers or the poller)
- **Wired event hooks**:
  - `alerts.py` poller: peer connect/disconnect (handshake transition), peer expired, traffic anomaly, peer inactive 7+ days (24 h throttle), WireGuard up/down, Pi-hole up/down (TCP probe to admin URL)
  - `routes/peers.py`: peer added (form + wizard), peer deleted, config regenerated
  - `routes/api.py`: peer killed
  - `routes/auth.py`: login success (post-TOTP), failed login attempt (wrong password or wrong TOTP code) — includes client IP

### Database
- New table `notification_settings(id, channel UNIQUE, enabled, config JSON, updated_at)` — seeded on first run with email/telegram/discord rows
- New table `notification_log(id, channel, event_type, message, success, error, sent_at)` — auto-trimmed to 500 most-recent rows
- New table `notification_event_toggles(event_type PRIMARY KEY, enabled)` — seeded with all 15 events default-on

### Implementation notes
- `notifications.py` (new module) uses stdlib only — `smtplib`, `urllib.request`, `email.mime`, `json`. No new pip dependencies.
- All sends wrapped in try/except; failures are logged but never crash the app.
- `.env` gains `NOTIFY_EMAIL_*`, `NOTIFY_TELEGRAM_*`, `NOTIFY_DISCORD_WEBHOOK` keys (also editable from the UI).

---

## [1.2.0] — 2026-05-07 (Batch 3 — Split Tunneling, DNS Override, Port Forwarding, Map Colours)

### Added
- **Peer tunnel mode** — three modes per peer: Full Tunnel (0.0.0.0/0), VPN Only (subnet only), Split Tunnel (subnet + custom CIDRs)
  - New `tunnel_mode` and `custom_routes` columns on `peers` table
  - `AllowedIPs` in client config computed from tunnel mode; server-side `wg set allowed-ips` remains `vpn_ip/32`
  - Create form: tunnel selector + JS-revealed custom CIDR input for split mode
  - Edit form on peer detail: tunnel mode + custom routes
  - Peers list: FULL / VPN / SPLIT badges per peer
  - Peer detail: Tunnel Mode row + effective AllowedIPs display
- **DNS override per peer** — full DNS selector replacing the binary Pi-hole toggle
  - Presets: Pi-hole (10.8.0.1), Cloudflare (1.1.1.1, 1.0.0.1), Google (8.8.8.8, 8.8.4.4), Quad9 (9.9.9.9), Custom
  - `dns_override` column; `generate_client_config()` uses override if set, else falls back to `dns` field
  - Selector on both create and edit forms
- **Port forwarding rules** — DNAT iptables rules forwarding public VPS ports to VPN peers
  - New `port_forwards` table; new blueprint at `/port-forwards/`
  - Create, toggle, delete via `/port-forwards/<id>/toggle|delete`
  - Rules applied with `iptables` and persisted to `/etc/iptables/rules.v4`
  - Security warning in UI; sidebar nav link (⇄)
  - Per-peer Port Forwards section on peer detail page
- **Map tunnel mode colours** — active peer markers, polylines, and right-panel dots are coloured by tunnel mode
  - Full tunnel: green; VPN only: cyan; Split: amber
  - Legend updated with all three modes; summary table adds Tunnel column
  - `tunnel_mode` included in `/api/peer-locations` response

### Database
- New columns on `peers`: `tunnel_mode TEXT DEFAULT 'full'`, `custom_routes TEXT DEFAULT ''`, `dns_override TEXT DEFAULT ''`
- New table `port_forwards(id, peer_id, description, protocol, external_port, internal_port, enabled, created_at)`

---

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
