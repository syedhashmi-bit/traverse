# Roadmap

Forward-looking plans for Traverse. Retrospective work lives in `CHANGELOG.md`.

This is a personal project, so the roadmap is small and opinionated. Items
are grouped by theme, not by milestone — the project ships when something is
ready, not on a calendar.

## Near-term polish

- **Finish the light theme.** Toggle works but some surfaces (panels,
  charts, certain table backgrounds) stay dark. Audit `static/css/style.css`
  for hard-coded `#xxx` colours that should be CSS variables, then add the
  light-theme overrides at the end of the file (per the project's
  append-only CSS rule).
- **Unify the two Telegram code paths.** `alerts.py` `_send()` (legacy, env
  vars) and `notifications.py` (DB-backed) both send to Telegram. The
  legacy path is only retained for early-boot WG-down alerts; tighten the
  fallback boundary so the rest of the codebase only uses
  `send_notification()`.

## Reliability & quality

- **Grow the pytest suite.** Initial pass (25 tests) covers auth,
  CSRF/origin check, peer CRUD + cap, backup-export secret stripping,
  and `MAX_PEERS` env-var handling. Still missing: TOTP flow,
  notifications dispatch, bulk-action endpoints, alerts poller logic
  in isolation, port-forwards CRUD.

## Security

- **Move 2FA enrolment into the UI.** Currently `TOTP_SECRET` is set in
  `.env` and `/totp-setup` only displays the QR. Add a real enrol/disable
  flow with backup codes and a fresh-login confirmation step.
- **Audit log.** Append-only DB table of admin actions (peer create /
  delete / disable, settings changes, login events). Surfaced at
  `/history` or a new `/audit` page.
- **CSP tightening.** The current policy still allows `'unsafe-inline'`
  for scripts and styles. Move inline handlers to `static/js/app.js`,
  generate per-request nonces, and drop `'unsafe-inline'`.

## Features under consideration

These are ideas, not commitments — happy to drop any if they bloat the
scope.

- **Per-peer bandwidth quotas.** Daily / monthly caps with auto-disable
  when exceeded; status surfaced on the peer list and detail pages.
- **IPv6 on `wg0`.** Dual-stack tunnel with NAT66 (or routed `/64`) so
  clients get a v6 address through the VPS as well.
- **Scheduled peer enable/disable.** Cron-style schedule per peer
  (e.g. "kid's laptop: disabled 22:00–07:00").
- **Server-side speedtest history graph.** The dashboard shows the latest
  result; surface a sparkline of the last N runs on `/settings` instead of
  the current table.
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
