"""Audit log viewer.

Read-only listing of admin actions captured via database.audit().
Filtering by action prefix (e.g. 'peer.' or 'auth.'), pagination,
and CSV export.
"""

import csv
import io

from flask import Blueprint, render_template, request, Response

from database import get_audit_log, count_audit_log
from routes.auth import login_required


audit_bp = Blueprint('audit', __name__)


_PAGE_SIZE = 50


@audit_bp.route('/audit')
@login_required
def index():
    prefix = (request.args.get('prefix') or '').strip()
    try:
        page = max(1, int(request.args.get('page', '1')))
    except ValueError:
        page = 1

    total = count_audit_log(action_prefix=prefix or None)
    offset = (page - 1) * _PAGE_SIZE
    rows = get_audit_log(
        limit=_PAGE_SIZE, offset=offset, action_prefix=prefix or None,
    )
    pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)

    return render_template(
        'audit.html',
        rows=rows,
        prefix=prefix,
        page=page,
        pages=pages,
        total=total,
        page_size=_PAGE_SIZE,
    )


@audit_bp.route('/audit.csv')
@login_required
def export_csv():
    prefix = (request.args.get('prefix') or '').strip()
    rows = get_audit_log(limit=2000, action_prefix=prefix or None)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['ts', 'action', 'target_type', 'target_id',
                     'target_name', 'actor_ip', 'details'])
    for r in rows:
        writer.writerow([
            r.get('ts', ''), r.get('action', ''),
            r.get('target_type') or '', r.get('target_id') or '',
            r.get('target_name') or '', r.get('actor_ip') or '',
            r.get('details') or '',
        ])
    resp = Response(buf.getvalue(), mimetype='text/csv')
    resp.headers['Content-Disposition'] = 'attachment; filename="traverse-audit.csv"'
    return resp
