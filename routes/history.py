import csv, io
from datetime import datetime
from flask import Blueprint, render_template, send_file
from database import get_connection_events
from routes.auth import login_required

history_bp = Blueprint('history', __name__)


@history_bp.route('/history')
@login_required
def history_view():
    events = get_connection_events(limit=200)
    return render_template('history.html', events=events)


@history_bp.route('/history/export.csv')
@login_required
def export_csv():
    events = get_connection_events(limit=2000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['id', 'event_type', 'peer_name', 'peer_vpn_ip', 'timestamp'])
    for e in events:
        w.writerow([
            e.get('id'),
            e.get('event_type'),
            e.get('peer_name') or '',
            e.get('peer_vpn_ip') or '',
            e.get('timestamp') or '',
        ])
    today = datetime.utcnow().strftime('%Y-%m-%d')
    return send_file(
        io.BytesIO(buf.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'traverse-history-{today}.csv',
    )
