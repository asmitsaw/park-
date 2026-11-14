import os
from pathlib import Path
from flask import Flask, render_template, redirect, url_for, session, send_from_directory
from flask_cors import CORS
from backend.config import Config, BASE_DIR
from backend.database import close_db, init_db

def create_app(test_config=None):
    template_folder = str(BASE_DIR / "frontend" / "templates")
    static_folder = str(BASE_DIR / "frontend" / "static")

    app = Flask(
        __name__,
        template_folder=template_folder,
        static_folder=static_folder,
        static_url_path="/static"
    )

    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    # Enable CORS for local network and ESP32
    CORS(app, supports_credentials=True)

    # Register Teardown
    app.teardown_appcontext(close_db)

    # Register Blueprints
    from backend.routes.auth import auth_bp
    from backend.routes.dashboard import dashboard_bp
    from backend.routes.users import users_bp
    from backend.routes.vehicles import vehicles_bp
    from backend.routes.rfid import rfid_bp
    from backend.routes.subscriptions import subscriptions_bp
    from backend.routes.parking import parking_bp
    from backend.routes.security import security_bp
    from backend.routes.helpdesk import helpdesk_bp
    from backend.routes.devices import devices_bp
    from backend.routes.analytics import analytics_bp
    from backend.routes.settings import settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(rfid_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(parking_bp)
    app.register_blueprint(security_bp)
    app.register_blueprint(helpdesk_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(settings_bp)

    # Web Page Routes
    @app.route("/")
    def index():
        if "admin_id" in session:
            return redirect("/dashboard")
        return redirect("/login")

    @app.route("/login")
    def login_page():
        return render_template("login.html")

    @app.route("/dashboard")
    def dashboard_page():
        if "admin_id" not in session:
            return redirect("/login")
        return render_template("index.html")

    # Serve static assets or favicon if needed
    @app.route("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(static_folder + "/assets", filename)

    return app

if __name__ == "__main__":
    app = create_app()
    # Ensure database is initialized
    init_db()
    # Bind to 0.0.0.0 so ESP32 on the local Wi-Fi can reach it via PC's LAN IP
    port = int(os.getenv("PORT", 5000))
    print(f"\n=======================================================")
    print(f"  PARK+ Backend Server running on http://0.0.0.0:{port}")
    print(f"  Admin Portal: http://localhost:{port}/login")
    print(f"  ESP32 Endpoint: http://<YOUR_LOCAL_IP>:{port}/api/parking/entry")
    print(f"=======================================================\n")
    app.run(host="0.0.0.0", port=port, debug=True)

