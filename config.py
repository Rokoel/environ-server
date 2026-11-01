"""
Configuration for Environ Server
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Base paths
BASE_DIR = Path(__file__).parent
UPLOAD_FOLDER = BASE_DIR / 'uploads'
STATIC_VIDEO_DIR = BASE_DIR / 'static' / 'video'

# Flask configuration
SECRET_KEY = os.environ.get('SECRET_KEY', '')
if (len(SECRET_KEY.strip()) < 32 or
        SECRET_KEY == 'dev-secret-key-change-in-production'):
    raise RuntimeError(
        'Set SECRET_KEY to a securely generated value of at least 32 characters. '
        'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
    )
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

# Database
SQLALCHEMY_DATABASE_URI = f'sqlite:///{BASE_DIR / "environ_server.db"}'
SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_pre_ping': True,
}

# Telegram configuration
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')

# File upload settings
MAX_CONTENT_LENGTH = 30 * 1024 * 1024  # 30 MB
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'zip', 'webm', 'webp'}
ALLOWED_MIME_TYPES = {
    'application/pdf',
    'image/png',
    'image/jpeg',
    'application/zip',
    'video/webm',
    'image/webp'
}

# Security
WTF_CSRF_ENABLED = True
WTF_CSRF_TIME_LIMIT = None

# Session
PERMANENT_SESSION_LIFETIME = 86400 * 30  # 30 days


class Config:
    """Flask configuration class"""

    # Flask configuration
    SECRET_KEY = SECRET_KEY
    DEBUG = DEBUG

    # Database
    SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = SQLALCHEMY_TRACK_MODIFICATIONS
    SQLALCHEMY_ENGINE_OPTIONS = SQLALCHEMY_ENGINE_OPTIONS

    # Telegram configuration
    TELEGRAM_BOT_TOKEN = TELEGRAM_BOT_TOKEN

    # File upload settings
    MAX_CONTENT_LENGTH = MAX_CONTENT_LENGTH

    # Security
    WTF_CSRF_ENABLED = WTF_CSRF_ENABLED
    WTF_CSRF_TIME_LIMIT = WTF_CSRF_TIME_LIMIT

    # Session
    PERMANENT_SESSION_LIFETIME = PERMANENT_SESSION_LIFETIME


# Create upload directory if not exists
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
