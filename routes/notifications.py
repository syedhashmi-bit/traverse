"""Notifications dashboard — /notifications.

Manage email, Telegram, and Discord channels, per-event toggles, and view a log
of recent notification attempts.
"""
import csv, io
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file

from database import (
    get_notification_settings, update_notification_channel,
    get_notification_log, clear_notification_log,
    get_notification_event_toggles, set_notification_event_toggles,
)
import notifications as notif
from routes.auth import login_required


notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/notifications')
@login_required
def index():
    settings = get_notification_settings()
    log_rows = get_notification_log(limit=20)
    toggles  = get_notification_event_toggles()
    return render_template(
        'notifications.html',
        settings        = settings,
        log_rows        = log_rows,
        event_labels    = notif.EVENT_LABELS,
        event_toggles   = toggles,
        any_channel_on  = notif.is_any_channel_active(),
    )


@notifications_bp.route('/notifications/save/<channel>', methods=['POST'])
@login_required
def save_channel(channel):
    if channel not in ('email', 'telegram', 'discord'):
        flash('Unknown channel.', 'error')
        return redirect(url_for('notifications.index'))

    enabled = request.form.get('enabled') == 'on'

    if channel == 'email':
        cfg = {
            'from':      request.form.get('from', '').strip(),
            'to':        request.form.get('to', '').strip(),
            'smtp_host': request.form.get('smtp_host', '').strip(),
            'smtp_port': request.form.get('smtp_port', '587').strip() or '587',
            'smtp_user': request.form.get('smtp_user', '').strip(),
            'smtp_pass': request.form.get('smtp_pass', '').strip(),
        }
    elif channel == 'telegram':
        cfg = {
            'token':   request.form.get('token', '').strip(),
            'chat_id': request.form.get('chat_id', '').strip(),
        }
    else:  # discord
        cfg = {
            'webhook': request.form.get('webhook', '').strip(),
        }

    update_notification_channel(channel, enabled, cfg)
    flash(f'{channel.capitalize()} settings saved.', 'success')
    return redirect(url_for('notifications.index') + f'#section-{channel}')


@notifications_bp.route('/notifications/test/<channel>', methods=['POST'])
@login_required
def test_channel(channel):
    """Send a test message synchronously and return JSON {ok, error}."""
    if channel not in ('email', 'telegram', 'discord'):
        return jsonify({'ok': False, 'error': 'unknown channel'}), 400

    data = request.get_json(silent=True) or {}
    if data:
        cfg = data
    else:
        # Fall back to saved config
        from database import get_notification_channel
        info = get_notification_channel(channel)
        cfg = (info or {}).get('config') or {}

    ok, err = notif.send_test(channel, cfg)
    return jsonify({'ok': ok, 'error': err})


@notifications_bp.route('/notifications/events', methods=['POST'])
@login_required
def save_events():
    """Save per-event toggle checkboxes. Unchecked boxes don't post — explicit list."""
    from notifications import EVENT_LABELS
    submitted = set(request.form.getlist('events'))
    toggles = {evt: (evt in submitted) for evt, _label in EVENT_LABELS}
    set_notification_event_toggles(toggles)
    flash('Event filters saved.', 'success')
    return redirect(url_for('notifications.index') + '#section-events')


@notifications_bp.route('/notifications/log/clear', methods=['POST'])
@login_required
def log_clear():
    clear_notification_log()
    flash('Notification log cleared.', 'success')
    return redirect(url_for('notifications.index') + '#section-log')


@notifications_bp.route('/api/notifications/status')
@login_required
def status():
    """Used by the sidebar dot — returns whether at least one channel is active."""
    return jsonify({'active': notif.is_any_channel_active()})


@notifications_bp.route('/notifications/log/export.csv')
@login_required
def export_log_csv():
    rows = get_notification_log(limit=500)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['id', 'channel', 'event_type', 'success', 'message', 'error', 'sent_at'])
    for r in rows:
        w.writerow([
            r.get('id'),
            r.get('channel') or '',
            r.get('event_type') or '',
            1 if r.get('success') else 0,
            (r.get('message') or '').replace('\r', ' ').replace('\n', ' '),
            (r.get('error')   or '').replace('\r', ' ').replace('\n', ' '),
            r.get('sent_at') or '',
        ])
    today = datetime.utcnow().strftime('%Y-%m-%d')
    return send_file(
        io.BytesIO(buf.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'traverse-notifications-{today}.csv',
    )
