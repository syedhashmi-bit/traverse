import subprocess
import sys
from pathlib import Path
from flask import Blueprint, render_template
from routes.auth import login_required

about_bp = Blueprint('about', __name__)

_ROOT = Path(__file__).parent.parent


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (r.stdout or r.stderr or '').strip()
    except Exception as e:
        return f'Error: {e}'


@about_bp.route('/about')
@login_required
def about():
    version  = (_ROOT / 'VERSION').read_text().strip() if (_ROOT / 'VERSION').exists() else 'unknown'
    changelog = (_ROOT / 'CHANGELOG.md').read_text() if (_ROOT / 'CHANGELOG.md').exists() else ''

    py_ver  = f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'
    wg_ver  = _run(['wg', '--version'])
    ph_ver  = _run(['pihole', 'version'])
    uptime  = _run(['uptime', '-p'])

    return render_template('about.html',
        version=version,
        changelog=changelog,
        py_ver=py_ver,
        wg_ver=wg_ver,
        ph_ver=ph_ver,
        uptime=uptime,
    )
