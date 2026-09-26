import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'fallback-secret-key')

    if os.environ.get('WEBSITE_SITE_NAME'):
        db_path = '/home/site.db'
    else:
        db_path = os.path.join(os.path.dirname(__file__), 'site.db')

    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = bool(os.environ.get('WEBSITE_SITE_NAME'))
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB uploads

    db.init_app(app)
    login_manager.init_app(app)

    from app.routes import main_bp, auth_bp, agent_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(agent_bp)

    with app.app_context():
        db.create_all()

    return app