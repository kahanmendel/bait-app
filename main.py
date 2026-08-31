from flask import Flask
from extensions import db, login_manager
from dotenv import load_dotenv
import os

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

    db_url = os.getenv('DATABASE_URL', 'sqlite:///bait_app.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    with app.app_context():
        from models import User

        @login_manager.user_loader
        def load_user(user_id):
            return db.session.get(User, int(user_id))

        from routes.auth import auth_bp
        from routes.veeset import veeset_bp
        from routes.dashboard import dashboard_bp
        from routes.api import api_bp
        from routes.settings import settings_bp
        from routes.reminders import reminders_bp
        from routes.cron import cron_bp
        from routes.pregnancy import pregnancy_bp
        from routes.admin import admin_bp
        from routes.yemot import yemot_bp

        app.register_blueprint(auth_bp)
        app.register_blueprint(veeset_bp)
        app.register_blueprint(dashboard_bp)
        app.register_blueprint(api_bp, url_prefix='/api')
        app.register_blueprint(settings_bp)
        app.register_blueprint(reminders_bp)
        app.register_blueprint(cron_bp)
        app.register_blueprint(pregnancy_bp)
        app.register_blueprint(admin_bp)
        app.register_blueprint(yemot_bp)

        try:
            db.create_all()
        except Exception as e:
            app.logger.warning(f"db.create_all() failed: {e}")

        try:
            from logic.schema import ensure_schema
            added = ensure_schema(db)
            if added:
                app.logger.info(f"schema: added columns {', '.join(added)}")
        except Exception as e:
            app.logger.warning(f"ensure_schema() failed: {e}")

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
