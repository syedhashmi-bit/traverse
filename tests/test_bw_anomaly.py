"""Tests for the bandwidth-anomaly heuristic.

The poller flags a peer when the most-recent interval rate exceeds an
absolute floor (1 MB/s) AND is more than 5× the average of prior
intervals. The function is pure (`alerts.compute_bw_anomaly`), so we
build snapshot tuples directly and assert on the return value.
"""

from datetime import datetime, timedelta

from alerts import compute_bw_anomaly


def _snap(seconds_offset, rx, tx, base=None):
    base = base or datetime(2026, 1, 1, 12, 0, 0)
    return {
        'recorded_at': (base + timedelta(seconds=seconds_offset)).isoformat(),
        'rx_bytes': rx,
        'tx_bytes': tx,
    }


def test_too_few_snapshots_returns_no_anomaly():
    snaps = [_snap(0, 0, 0), _snap(60, 100, 100)]
    cur, avg, anom = compute_bw_anomaly(snaps)
    assert (cur, avg, anom) == (0.0, 0.0, False)


def test_flat_traffic_below_floor_is_not_anomalous():
    # Steady ~1 KB/s for several intervals — well under the 1 MB/s floor
    snaps = [_snap(i * 60, i * 60_000, i * 60_000) for i in range(6)]
    cur, avg, anom = compute_bw_anomaly(snaps)
    assert anom is False
    assert cur > 0 and avg > 0


def test_above_floor_but_not_5x_avg_is_not_anomalous():
    # Constant ~2 MB/s — above the absolute floor but no spike vs the avg
    snaps = [_snap(i * 60, i * 120_000_000, i * 120_000_000) for i in range(8)]
    cur, avg, anom = compute_bw_anomaly(snaps)
    assert cur > 1_048_576       # above the 1 MB/s floor
    assert anom is False


def test_clear_spike_is_anomalous():
    # 7 quiet intervals (~0 rate), then one big spike at the end
    snaps = []
    for i in range(7):
        snaps.append(_snap(i * 60, i * 1000, i * 1000))
    snaps.append(_snap(7 * 60, 7 * 1000 + 500_000_000, 7 * 1000 + 500_000_000))
    cur, avg, anom = compute_bw_anomaly(snaps)
    assert anom is True
    assert cur > avg * 5


def test_spike_below_floor_is_not_anomalous():
    # 6× the average but still under 1 MB/s — floor protects against tiny
    # background traffic getting flagged
    snaps = [_snap(i * 60, i * 1000, i * 1000) for i in range(6)]
    snaps.append(_snap(6 * 60, 6 * 1000 + 60_000, 6 * 1000 + 60_000))  # 1 KB/s avg, 1 KB/s spike
    cur, avg, anom = compute_bw_anomaly(snaps)
    assert anom is False


def test_zero_interval_is_skipped():
    # Two snapshots at the same timestamp shouldn't divide-by-zero
    base = datetime(2026, 1, 1, 12, 0, 0)
    snaps = [
        _snap(0, 0, 0, base),
        _snap(60, 100, 100, base),
        {'recorded_at': (base + timedelta(seconds=60)).isoformat(),
         'rx_bytes': 200, 'tx_bytes': 200},  # zero-interval after previous
        _snap(120, 300, 300, base),
    ]
    cur, avg, anom = compute_bw_anomaly(snaps)
    # Should still produce a valid result (no exception)
    assert anom is False


def test_counter_reset_does_not_produce_negative_rate():
    # WireGuard counters reset to 0 after `wg-quick down/up`; the helper
    # clamps the negative delta to 0 so the next interval doesn't show
    # a fake huge spike.
    snaps = [
        _snap(0,   500_000_000, 500_000_000),
        _snap(60,  600_000_000, 600_000_000),
        _snap(120, 700_000_000, 700_000_000),
        _snap(180, 800_000_000, 800_000_000),
        _snap(240, 0, 0),  # ← counter reset
        _snap(300, 50_000, 50_000),
    ]
    cur, avg, anom = compute_bw_anomaly(snaps)
    # The reset itself shouldn't be flagged as an anomaly
    assert anom is False


def test_custom_thresholds_passthrough():
    # Same data — tighten the ratio enough to make it anomalous, or loosen
    # to make it not. Verifies the params are wired.
    snaps = [_snap(i * 60, i * 60_000_000, i * 60_000_000) for i in range(6)]
    snaps.append(_snap(6 * 60, 6 * 60_000_000 + 90_000_000, 6 * 60_000_000 + 90_000_000))
    cur_def, _, anom_def = compute_bw_anomaly(snaps)
    cur_strict, _, anom_strict = compute_bw_anomaly(snaps, ratio=1)
    assert anom_strict is True or anom_def is True
    cur_floored, _, anom_floored = compute_bw_anomaly(snaps, min_rate=10**12)
    assert anom_floored is False
