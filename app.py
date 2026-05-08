import os
from flask import Flask, render_template
from dotenv import load_dotenv

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv('SECRET_KEY', 'changeme-set-in-dotenv')

    from cache_ext import cache
    cache.init_app(app)

    from database import init_db, disable_expired_peers
    init_db()

    # Disable any peers that expired while the server was offline
    try:
        from wireguard import remove_peer_from_interface
        for p in disable_expired_peers():
            try:
                remove_peer_from_interface(p['public_key'])
            except Exception:
                pass
    except Exception:
        pass

    from routes.auth          import auth_bp
    from routes.dashboard     import dashboard_bp
    from routes.peers         import peers_bp
    from routes.settings      import settings_bp
    from routes.api           import api_bp
    from routes.map           import map_bp
    from routes.history       import history_bp
    from routes.alerts        import alerts_bp
    from routes.topology      import topology_bp
    from routes.logs          import logs_bp
    from routes.about         import about_bp
    from routes.port_forwards import pf_bp
    from routes.notifications import notifications_bp
    from routes.pwa           import pwa_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(peers_bp,         url_prefix='/peers')
    app.register_blueprint(settings_bp,      url_prefix='/settings')
    app.register_blueprint(api_bp)
    app.register_blueprint(map_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(topology_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(about_bp)
    app.register_blueprint(pf_bp,            url_prefix='/port-forwards')
    app.register_blueprint(notifications_bp)
    app.register_blueprint(pwa_bp)

    from alerts import start_alerts
    start_alerts()

    # Read version once at startup
    _version = 'dev'
    try:
        _version_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'VERSION')
        if os.path.exists(_version_path):
            with open(_version_path) as _f:
                _version = _f.read().strip() or 'dev'
    except Exception:
        pass

    @app.context_processor
    def inject_globals():
        from wireguard import get_interface_status
        from database import count_unseen_alerts, count_peers
        try:
            unseen = count_unseen_alerts()
        except Exception:
            unseen = 0
        try:
            peer_total = count_peers()
        except Exception:
            peer_total = 0
        try:
            from notifications import is_any_channel_active
            notif_active = is_any_channel_active()
        except Exception:
            notif_active = False
        return {
            'wg_running':              get_interface_status()['running'],
            'unseen_alert_count':      unseen,
            'app_version':             _version,
            'app_peer_total':          peer_total,
            'app_wg_subnet':           os.getenv('WG_SUBNET', '10.8.0.0/24'),
            'app_wg_endpoint':         os.getenv('WG_ENDPOINT', ''),
            'app_pihole_url':          os.getenv('PIHOLE_URL', 'http://10.8.0.1:8080/admin'),
            'app_pihole_enabled':      bool(os.getenv('PIHOLE_ENABLED')),
            'notifications_active':    notif_active,
        }

    @app.errorhandler(404)
    def not_found(e):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('500.html'), 500

    return app


if __name__ == '__main__':
    app = create_app()
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
