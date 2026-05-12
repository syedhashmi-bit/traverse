# Roadmap

Forward-looking plans for Traverse. Retrospective work lives in `CHANGELOG.md`.

This is a personal project, so the roadmap is small and opinionated. Items
are grouped by theme, not by milestone — the project ships when something is
ready, not on a calendar.

## Near-term polish

Empty. New near-term items land here as they come up.

## Reliability & quality

- **Pytest suite — 140 tests** across auth, TOTP (env + UI enrolment + backup
  codes), CSRF, peers (CRUD + bulk + PSK rotation), notifications dispatch,
  audit log, port-forwards, the alerts poller, the bandwidth-anomaly
  heuristic, the Pi-hole v6 API client, the wireguard CLI wrappers,
  backup export, and `MAX_PEERS` handling. Coverage gaps called out
  earlier (anomaly maths, Pi-hole client, wg wrappers) are now closed.

## Security

- **`script-src` nonce-only CSP shipped in 1.8.0.** The remaining
  `'unsafe-inline'` on `style-src` is intentional — too many inline
  `style="..."` attributes across admin views, and the XSS risk from
  style is low relative to scripts. Revisit if/when the templates are
  refactored to lose inline styling.

## Features under consideration (unscheduled)

These are ideas, not commitments — happy to drop any if they bloat the
scope. Not assigned to a version because they're meatier than a single
release bump.

- **Per-peer bandwidth quotas.** Daily / monthly caps with auto-disable
  when exceeded; status surfaced on the peer list and detail pages.
- **IPv6 on `wg0`.** Dual-stack tunnel with NAT66 (or routed `/64`) so
  clients get a v6 address through the VPS as well.
- **Scheduled peer enable/disable.** Cron-style schedule per peer
  (e.g. "kid's laptop: disabled 22:00–07:00").
- **Mobile PWA polish pass.** Bottom nav is good; the wizard and the
  topology view still feel desktop-first.

## Explicit non-goals

- **Multi-tenant / public SaaS.** Personal use only — the auth model is
  single-admin and there's no plan to change that.
- **Replacing the `wg` CLI with a Go/Rust binding.** The CLI wrappers are
  simple, predictable, and easy to debug; the perf is fine for this scale.
- **Heavy JS frontend.** No React/Vue/Svelte. The "no CDN, no framework"
  constraint is load-bearing for the dark-theme aesthetic and the offline
  PWA story.
