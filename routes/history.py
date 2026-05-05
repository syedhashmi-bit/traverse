from flask import Blueprint, render_template
from database import get_connection_events
from routes.auth import login_required

history_bp = Blueprint('history', __name__)


@history_bp.route('/history')
@login_required
def history_view():
    events = get_connection_events(limit=200)
    return render_template('history.html', events=events)
