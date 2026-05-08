"""PWA-related public routes — manifest, service worker, offline fallback.

These three endpoints intentionally bypass `login_required`:
  * `/manifest.json` and `/sw.js` must be reachable for the browser install /
    registration flow, which happens before (and outside of) any user session.
  * `/offline` is the fallback the service worker shows when the network is
    unreachable — it must be cacheable as a public resource.
"""
from flask import Blueprint, make_response, render_template, send_from_directory

pwa_bp = Blueprint('pwa', __name__)


@pwa_bp.route('/manifest.json')
def manifest():
    resp = make_response(send_from_directory('static', 'manifest.json'))
    resp.headers['Content-Type'] = 'application/manifest+json'
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp


@pwa_bp.route('/sw.js')
def service_worker():
    resp = make_response(send_from_directory('static', 'sw.js'))
    resp.headers['Content-Type'] = 'application/javascript'
    # Allow the SW to control the entire origin, not just /static/.
    resp.headers['Service-Worker-Allowed'] = '/'
    # Never cache the SW itself — clients must pick up updates immediately.
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@pwa_bp.route('/offline')
def offline():
    return render_template('offline.html')
