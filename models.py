"""
Database models for Environ Server
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    """User model for storing Telegram authenticated users"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    username = db.Column(db.String(100))
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    photo_url = db.Column(db.String(500))
    is_admin = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='unverified')  # unverified, verified, rejected, banned
    rejection_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    applications = db.relationship('Application', backref='user', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<User {self.telegram_id}: {self.username}>'

    def to_dict(self):
        return {
            'id': self.id,
            'telegram_id': self.telegram_id,
            'username': self.username,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'photo_url': self.photo_url,
            'is_admin': self.is_admin,
            'status': self.status,
            'rejection_reason': self.rejection_reason,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class Application(db.Model):
    """Application model for storing form submissions"""
    __tablename__ = 'applications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    answers = db.Column(db.Text, nullable=True)  # JSON string of answers
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    admin_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Application {self.id} by User {self.user_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'answers': self.answers,
            'status': self.status,
            'admin_notes': self.admin_notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class FormConfig(db.Model):
    """Form configuration stored in database"""
    __tablename__ = 'form_config'

    id = db.Column(db.Integer, primary_key=True)
    config_key = db.Column(db.String(100), unique=True, nullable=False)
    config_value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<FormConfig {self.config_key}>'

    @staticmethod
    def get(key, default=None):
        """Get configuration value"""
        config = FormConfig.query.filter_by(config_key=key).first()
        return config.config_value if config else default

    @staticmethod
    def set(key, value):
        """Set configuration value"""
        config = FormConfig.query.filter_by(config_key=key).first()
        if config:
            config.config_value = value
        else:
            config = FormConfig(config_key=key, config_value=value)
            db.session.add(config)
        db.session.commit()
