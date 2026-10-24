import datetime
import os


class Config:
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'dev-secret-change-me')
    JWT_ACCESS_TOKEN_EXPIRES = datetime.timedelta(hours=int(os.getenv('JWT_ACCESS_TOKEN_HOURS', '6')))
    JWT_BLOCKLIST_ENABLED = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        f"sqlite:///{os.path.join(BASE_DIR, 'app.db')}?timeout={os.getenv('SQLITE_TIMEOUT', '15')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_BASE_FOLDER = os.getenv('UPLOAD_BASE_FOLDER', r'C:\upload')
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', os.path.join(UPLOAD_BASE_FOLDER, 'chat_images'))
    AVATAR_UPLOAD_FOLDER = os.getenv('AVATAR_UPLOAD_FOLDER', os.path.join(UPLOAD_BASE_FOLDER, 'avatars'))
    UPLOAD_FOLDER_MUSIC = os.getenv('UPLOAD_FOLDER_MUSIC', os.path.join(UPLOAD_BASE_FOLDER, 'music'))
    MAX_CONTENT_LENGTH = int(os.getenv('MAX_CONTENT_LENGTH_MB', '16')) * 1024 * 1024
    SOCKET_ASYNC_MODE = os.getenv('SOCKET_ASYNC_MODE', 'gevent')
    SOCKET_PING_TIMEOUT = int(os.getenv('SOCKET_PING_TIMEOUT', '60'))
    SOCKET_PING_INTERVAL = int(os.getenv('SOCKET_PING_INTERVAL', '25'))
    DEBUG = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
