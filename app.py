import os
from flask import Flask, render_template
from dotenv import load_dotenv

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv('SECRET_KEY', 'changeme-set-in-dotenv')

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

    from routes.auth      import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.peers     import peers_bp
    from routes.settings  import settings_bp
    from routes.api       import api_bp
    from routes.map       import map_bp
    from routes.history   import history_bp
    from routes.alerts    import alerts_bp
    from routes.topology  import topology_bp
    from routes.logs      import logs_bp
    from routes.about     import about_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(peers_bp,    url_prefix='/peers')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(api_bp)
    app.register_blueprint(map_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(topology_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(about_bp)

    from alerts import start_alerts
    start_alerts()

    @app.context_processor
    def inject_globals():
        from wireguard import get_interface_status
        from database import count_unseen_alerts
        try:
            unseen = count_unseen_alerts()
        except Exception:
            unseen = 0
        return {
            'wg_running':          get_interface_status()['running'],
            'unseen_alert_count':  unseen,
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
