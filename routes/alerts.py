import csv, io
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, abort, send_file
from database import get_all_alerts, mark_all_alerts_seen, dismiss_alert
from routes.auth import login_required

alerts_bp = Blueprint('alerts', __name__)


@alerts_bp.route('/alerts')
@login_required
def alerts_view():
    alerts = get_all_alerts(limit=200)
    return render_template('alerts.html', alerts=alerts)


@alerts_bp.route('/alerts/mark-seen', methods=['POST'])
@login_required
def mark_seen():
    mark_all_alerts_seen()
    return redirect(url_for('alerts.alerts_view'))


@alerts_bp.route('/alerts/<int:alert_id>/dismiss', methods=['POST'])
@login_required
def dismiss(alert_id):
    dismiss_alert(alert_id)
    return redirect(url_for('alerts.alerts_view'))


@alerts_bp.route('/alerts/export.csv')
@login_required
def export_csv():
    alerts = get_all_alerts(limit=2000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['id', 'type', 'severity', 'message', 'peer_id', 'peer_name', 'seen', 'created_at'])
    for a in alerts:
        w.writerow([
            a.get('id'),
            a.get('type') or '',
            a.get('severity') or '',
            (a.get('message') or '').replace('\r', ' ').replace('\n', ' '),
            a.get('peer_id') or '',
            a.get('peer_name') or '',
            1 if a.get('seen') else 0,
            a.get('created_at') or '',
        ])
    today = datetime.utcnow().strftime('%Y-%m-%d')
    return send_file(
        io.BytesIO(buf.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'traverse-alerts-{today}.csv',
    )
