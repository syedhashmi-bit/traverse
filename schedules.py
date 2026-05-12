"""Pure helpers for per-peer schedule evaluation.

A schedule is an "allowed window" — the peer should be enabled when the
local clock is inside the window, and disabled when it isn't. The poller
in `alerts.py` consults this module every tick to decide whether to flip
a peer's state.

The helpers here are deliberately side-effect free: they take a
`datetime` and the schedule fields, return a boolean. This makes the
midnight-crossing edge cases easy to unit-test without spinning up a DB
or stubbing the WireGuard CLI.
"""

from datetime import time as _time


def parse_days(raw):
    """Coerce the stored CSV string (or a pre-built list) into a set of
    integers in 0..6 (Mon=0 .. Sun=6, matching `datetime.weekday()`).
    Invalid tokens are silently dropped — defence-in-depth on data that
    could in principle come back from a half-migrated DB."""
    if raw is None:
        return set()
    if isinstance(raw, (list, tuple, set)):
        items = raw
    else:
        items = str(raw).split(',')
    out = set()
    for item in items:
        try:
            v = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if 0 <= v <= 6:
            out.add(v)
    return out


def _parse_hm(hm):
    """'HH:MM' → datetime.time. Returns None on malformed input."""
    if not hm or ':' not in hm:
        return None
    try:
        h, m = hm.split(':', 1)
        return _time(int(h), int(m))
    except (TypeError, ValueError):
        return None


def is_within_window(now_local, days_of_week, enabled_from, enabled_to):
    """Return True when `now_local` falls inside the allowed window.

    `days_of_week` is anything `parse_days()` accepts.
    `enabled_from` / `enabled_to` are 'HH:MM' strings.

    Semantics:
    - Same-day window (`from < to`): in-window iff today is selected AND
      `from <= now < to`.
    - Midnight-crossing (`from > to`, e.g. 22:00–07:00): in-window iff
      EITHER (today is selected AND `now >= from`) OR (yesterday is
      selected AND `now < to`). The "yesterday is selected" branch is
      what makes "kid's laptop disabled 22:00–07:00 Mon–Fri" do the
      right thing at 3 a.m. on a Saturday morning (Friday is selected,
      so the window is still open).
    - Equal `from == to`: treated as never-in-window. A 24-hour window
      should be expressed as having all 7 days selected without a
      schedule at all (delete the schedule instead).
    """
    days = parse_days(days_of_week)
    if not days:
        return False
    t_from = _parse_hm(enabled_from)
    t_to   = _parse_hm(enabled_to)
    if t_from is None or t_to is None:
        return False
    if t_from == t_to:
        return False

    now_t = now_local.time().replace(microsecond=0)
    today = now_local.weekday()
    yesterday = (today - 1) % 7

    if t_from < t_to:
        return today in days and t_from <= now_t < t_to

    # Crosses midnight
    if t_from > t_to:
        if now_t >= t_from and today in days:
            return True
        if now_t < t_to and yesterday in days:
            return True
    return False


def format_days(days):
    """Pretty-print a set of weekday ints — 'Mon, Wed, Fri', 'Weekdays',
    'Weekends', 'Every day'."""
    s = parse_days(days)
    if not s:
        return '—'
    if s == {0, 1, 2, 3, 4, 5, 6}:
        return 'Every day'
    if s == {0, 1, 2, 3, 4}:
        return 'Weekdays'
    if s == {5, 6}:
        return 'Weekends'
    labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    return ', '.join(labels[i] for i in sorted(s))
