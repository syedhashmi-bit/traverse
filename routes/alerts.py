from flask import Blueprint, render_template, redirect, url_for, abort
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
