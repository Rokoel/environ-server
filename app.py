"""
Environ Server - Main Flask Application
A modded Minecraft server website with Telegram OAuth authentication
"""
import os
import json
import hashlib
import hmac
import time
import re
import requests
from datetime import datetime
from pathlib import Path
from functools import wraps
from transliterate import translit
import logging
import io
from flask_compress import Compress


from flask_wtf import CSRFProtect

import bleach
import markdown
from flask import (
    Flask, render_template, request, redirect, url_for, session,
    flash, jsonify, send_from_directory, abort, current_app
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config, TELEGRAM_BOT_TOKEN, MAX_CONTENT_LENGTH, ALLOWED_EXTENSIONS, UPLOAD_FOLDER, BASE_DIR
from models import db, User, Application, FormConfig

MINECRAFT_SERVER_HOST = os.environ.get('MINECRAFT_SERVER_HOST', 'server.environ-server.org')
MINECRAFT_SERVER_PORT = int(os.environ.get('MINECRAFT_SERVER_PORT', '25565'))

try:
    from mcstatus import JavaServer
    MCDISSTATUS_AVAILABLE = True
except ImportError:
    MCDISSTATUS_AVAILABLE = False
    print("Warning: mcstatus not installed. Player count feature disabled.")

# Initialize Flask app
app = Flask(__name__)
app.config.from_object('config.Config')

csrf = CSRFProtect(app)
Compress(app)

# Initialize database
db.init_app(app)

# Create upload directory
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "app.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# ============================================================================
# JINJA2 FILTERS
# ============================================================================

@app.template_filter('get_answer')
def get_answer(answers_json, question, default=''):
    """Get answer from JSON string by question"""
    if not answers_json:
        return default
    try:
        if isinstance(answers_json, str):
            answers = json.loads(answers_json)
        else:
            answers = answers_json
        return answers.get(question, default) or default
    except (json.JSONDecodeError, AttributeError):
        return default


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def load_admins():
    """Load admin IDs from JSON file"""
    admins_file = BASE_DIR / 'admins.json'
    if admins_file.exists():
        with open(admins_file, 'r') as f:
            data = json.load(f)
            return data.get('admin_ids', [])
    return []

def load_json(filename):
    """Load JSON file safely"""
    path = BASE_DIR / filename

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except FileNotFoundError:
        logging.error(f"JSON file not found: {filename}")
        return []

    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in {filename}: {e}")
        return []

def load_social_config():
    """Load social links configuration from JSON file"""
    social_file = BASE_DIR / 'social_config.json'
    if social_file.exists():
        with open(social_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"social_links": [], "social_section_text": "Свяжитесь с нами"}


def cleanup_user_files(user_telegram_id, current_file_fields):
    """Clean up uploaded files that are no longer in the form"""
    user_upload_dir = UPLOAD_FOLDER / str(user_telegram_id)

    if not user_upload_dir.exists():
        return

    # Get all files currently in the user's upload directory
    current_files = set()
    if user_upload_dir.exists():
        for file in user_upload_dir.iterdir():
            if file.is_file():
                current_files.add(file.name)

    # Get files that should exist based on current form fields
    required_files = set(current_file_fields)

    # Remove files that are no longer in the form
    files_to_remove = current_files - required_files
    for filename in files_to_remove:
        try:
            (user_upload_dir / filename).unlink()
        except Exception as e:
            print(f"Failed to remove file {filename}: {e}")

def convert_to_tg_html(text):
    """
    Converts basic markdown-like syntax to Telegram HTML.
    Supports: **bold**, *italic*, `code`, ```pre```, ||spoiler||, __underline__, ~~strikethrough~~
    """
    if not text:
        return ""
    
    # Escape existing HTML special chars first
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    # Pre-formatted
    text = re.sub(r'```(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)
    # Monospace
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
    # Bold
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    # Italic
    text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
    # Spoiler
    text = re.sub(r'\|\|(.*?)\|\|', r'<span class="tg-spoiler">\1</span>', text)
    # Underline
    text = re.sub(r'__(.*?)__', r'<u>\1</u>', text)
    # Strikethrough
    text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', text)
    
    return text

def send_telegram_broadcast(telegram_id, text, file_data=None, filename=None):
    """Send a message (with optional file) to a specific user"""
    if not TELEGRAM_BOT_TOKEN:
        return False
        
    html_text = convert_to_tg_html(text)
    base_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    
    try:
        if file_data:
            # Determine if image or document
            is_image = filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))
            method = "sendPhoto" if is_image else "sendDocument"
            caption_key = "caption"
            file_key = "photo" if is_image else "document"
            
            files = {file_key: (filename, file_data)}
            data = {
                'chat_id': telegram_id,
                caption_key: html_text,
                'parse_mode': 'HTML'
            }
            response = requests.post(f"{base_url}/{method}", data=data, files=files, timeout=30)
        else:
            data = {
                'chat_id': telegram_id,
                'text': html_text,
                'parse_mode': 'HTML'
            }
            response = requests.post(f"{base_url}/sendMessage", json=data, timeout=20)
            
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Broadcast error to {telegram_id}: {e}")
        return False

def send_telegram_notification(telegram_id, status, rejection_reason=None):
    """
    Send Telegram notification to user about status change.
    Returns True if successful, False otherwise.
    """
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN not configured, skipping notification")
        return False

    # Status messages
    status_messages = {
        'verified': {
            'emoji': '✅',
            'title': 'Ваша заявка одобрена!',
            'message': 'Поздравляем! Теперь вы можете присоединиться к серверу.\n\n'
                       'IP сервера: server.environ-server.org\n'
                       'Версия: 1.20.1\n'
                       'Подробнee: https://environ-server.org/dashboard'
        },
        'rejected': {
            'emoji': '❌',
            'title': 'Ваша заявка отклонена',
            'message': 'К сожалению, ваша заявка была отклонена. Зайдите на сайт, чтобы посмотреть, что с ней, и отправить ее снова: environ-server.org'
        },
        'banned': {
            'emoji': '🚫',
            'title': 'Доступ заблокирован',
            'message': 'Вы были заблокированы на сервере :('
        }
    }

    if status not in status_messages:
        return False

    # Add rejection reason if provided
    message_text = status_messages[status]['message']
    if status == 'rejected' and rejection_reason:
        message_text += f'\n\nПричина: {rejection_reason}'

    text = f"{status_messages[status]['emoji']} *{status_messages[status]['title']}*\n\n{message_text}"

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': telegram_id,
            'text': text,
            'parse_mode': 'Markdown'
        }
        response = requests.post(url, json=data, timeout=10)

        if response.status_code == 200:
            print(f"Notification sent to {telegram_id}: {status}")
            return True
        else:
            print(f"Failed to send notification: {response.text}")
            return False
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")
        return False

def notify_admins_new_application(user, is_resubmission=False):
    """
    Send Telegram notification to all admins about new/resubmitted application.
    Returns number of notifications sent.
    """
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN not configured, skipping admin notification")
        return 0

    # Get admin IDs
    admin_ids = load_admins()

    if not admin_ids:
        print("No admins configured, skipping notification")
        return 0

    # Build message
    status_text = "📝 Новая заявка!" if not is_resubmission else "📝 Обновлённая заявка!"

    text = f"{status_text}\n\n" \
           f"👤 Игрок: {user.first_name or 'Неизвестно'} {user.last_name or ''}\n" \
           f"🔗 Telegram: @{user.username or 'нет username'}\n\n" \
           f"🔗 Ссылка: https://environ-server.org/admin"

    sent_count = 0

    for admin_id in admin_ids:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                'chat_id': str(admin_id),
                'text': text,
                'parse_mode': 'Markdown'
            }
            response = requests.post(url, json=data, timeout=10)

            if response.status_code == 200:
                sent_count += 1
            else:
                print(f"Failed to notify admin {admin_id}: {response.text}")
        except Exception as e:
            print(f"Error notifying admin {admin_id}: {e}")

    print(f"Notified {sent_count} admins about new application from user {user.telegram_id}")
    return sent_count


def is_admin(telegram_id):
    """Check if user is admin"""
    return str(telegram_id) in [str(admin_id) for admin_id in load_admins()]


def login_required(f):
    """Decorator for routes that require login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator for routes that require admin privileges"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        if not session.get('is_admin'):
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def verify_telegram_auth(data):
    """Verify Telegram login data using HMAC-SHA256"""
    if not TELEGRAM_BOT_TOKEN:
        print("TG_BOT_TOKEN FAIL")
        return False

    hash_str = data.get('hash', '')
    auth_date = data.get('auth_date', '')

    # Build data check string
    data_check_string = "\n".join([f"{key}={value}" for key, value in sorted(data.items()) if key != 'hash'])

    # Calculate expected hash
    print(data_check_string)
    print(hash_str)

    secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    print(expected_hash)

    # Verify hash and timestamp (not more than 24 hours old)
    if hash_str != expected_hash:
        return False

    try:
        auth_timestamp = int(auth_date)
        if time.time() - auth_timestamp > 86400:  # 24 hours
            print("OLD AUTH FAILURE")
            return False
    except (ValueError, TypeError):
        print("EXCEPTION FAILURE")
        return False

    return True


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def sanitize_html(html):
    """Sanitize HTML content using bleach"""
    allowed_tags = bleach.sanitizer.ALLOWED_TAGS + [
        'p', 'br', 'strong', 'em', 'u', 's', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'a', 'img', 'blockquote', 'code', 'pre', 'hr',
        'table', 'thead', 'tbody', 'tr', 'th', 'td'
    ]
    allowed_attrs = {
        **bleach.sanitizer.ALLOWED_ATTRIBUTES,
        'a': ['href', 'title', 'target'],
        'img': ['src', 'alt', 'title', 'width', 'height']
    }
    return bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs)


def parse_markdown_form(markdown_text):
    """
    Parse markdown text to extract form fields
    Supported syntax:
    ## Question Title
    - type: text|textarea|dropdown|multiselect|file
    - options: option1, option2, option3 (for dropdown/multiselect)
    - required: true|false
    """
    fields = []
    current_field = None

    lines = markdown_text.split('\n')
    for line in lines:
        line = line.strip()

        # Check for section headers (questions)
        if line.startswith('## '):
            if current_field:
                fields.append(current_field)

            current_field = {
                'question': line[3:].strip(),
                'type': 'text',
                'required': False,
                'options': []
            }

        # Check for field type
        elif line.startswith('- type:') and current_field:
            field_type = line.split(':')[1].strip()
            current_field['type'] = field_type

        # Check for required flag
        elif line.startswith('- required:') and current_field:
            required = line.split(':')[1].strip().lower() == 'true'
            current_field['required'] = required

        # Check for options
        elif line.startswith('- options:') and current_field:
            options_str = line.split(':')[1].strip()
            current_field['options'] = [opt.strip() for opt in options_str.split(',')]

    # Add last field
    if current_field:
        fields.append(current_field)

    return fields


def get_form_markdown():
    """Get form markdown from database or file"""
    markdown_text = FormConfig.get('form_markdown')

    if not markdown_text:
        # Try to load from file
        form_file = BASE_DIR / 'form.md'
        if form_file.exists():
            with open(form_file, 'r', encoding='utf-8') as f:
                markdown_text = f.read()

    return markdown_text or ''


def get_server_status():
    """
    Get Minecraft server status including player count.
    Returns dict with 'online', 'players_online', 'players_max', 'version', 'latency'
    """
    if not MCDISSTATUS_AVAILABLE:
        return {
            'online': False,
            'players_online': 0,
            'players_max': 0,
            'version': '1.20.1',
            'latency': None,
            'error': 'mcstatus not installed'
        }

    try:
        server = JavaServer.lookup(f"{MINECRAFT_SERVER_HOST}:{MINECRAFT_SERVER_PORT}")
        status = server.status()

        return {
            'online': True,
            'players_online': status.players.online,
            'players_max': status.players.max,
            'version': status.version.name,
            'latency': round(status.latency, 1) if status.latency else None
        }
    except Exception as e:
        return {
            'online': False,
            'players_online': 0,
            'players_max': 0,
            'version': 'N/A',
            'latency': None,
            'error': str(e)
        }

# ============================================================================
# ROUTES
# ============================================================================

@app.route('/')
def index():
    """Main landing page"""

    user_logged_in = 'user_id' in session
    user_status = session.get('status', 'unverified') if user_logged_in else None

    # Load social config
    social_config = load_social_config()
    
    server_status = get_server_status()

    return render_template('index.html',
                           user_logged_in=user_logged_in,
                           user_status=user_status,
                           server_name="Environ Server",
                           tagline="Бесплатный приватный Майнкрафт сервер с модами",
                           social_links=social_config.get('social_links', []),
                           social_section_text=social_config.get('social_section_text', 'Свяжитесь с нами')
                           )


@app.route('/api/server-status')
def api_server_status():
    """API endpoint to get Minecraft server status"""
    status = get_server_status()
    return jsonify(status)


@app.route('/about')
def about():
    """About page with server info, screenshots and mods list"""
    
    user_logged_in = 'user_id' in session
    user_status = session.get('status', 'unverified') if user_logged_in else None
    
    screenshots = load_json("screenshots.json")
    mods = load_json("mods.json")

    return render_template(
        'about.html',
        user_logged_in=user_logged_in,
        user_status=user_status,
        screenshots=screenshots,
        mods=mods
    )


@app.route('/auth/telegram', methods=['GET', 'POST'])
def telegram_auth():
    """Handle Telegram OAuth authentication"""
    data = request.args
    print(data)

    # Verify Telegram auth
    if not verify_telegram_auth(data):
        flash('Authentication failed. Please try again.', 'error')
        return redirect(url_for('index'))

    # Extract user data

    telegram_id = str(data.get('id', ''))
    username = data.get('username', '')
    first_name = data.get('first_name', '')
    last_name = data.get('last_name', '')
    photo_url = data.get('photo_url', '')

    # Find or create user
    user = User.query.filter_by(telegram_id=telegram_id).first()

    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            photo_url=photo_url,
            is_admin=is_admin(telegram_id),
            status='unverified'
        )
        db.session.add(user)
    else:
        # Update user info
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        user.photo_url = photo_url
        user.is_admin = is_admin(telegram_id)

    db.session.commit()

    # Set session
    session['user_id'] = user.id
    session['telegram_id'] = user.telegram_id
    session['username'] = user.username
    session['is_admin'] = user.is_admin
    session['status'] = user.status
    session.permanent = True

    # Redirect based on user status
    if user.is_admin:
        return redirect(url_for('admin'))
    else:
        return redirect(url_for('dashboard'))


@app.route('/dashboard')
@login_required
def dashboard():
    """User dashboard - shows form or status"""
    user = User.query.get(session['user_id'])

    if not user:
        return redirect(url_for('index'))
    
    # if is_admin(session['telegram_id']):
    #     return redirect(url_for('admin'))
    
    user_logged_in = 'user_id' in session
    user_status = session.get('status', 'unverified') if user_logged_in else None

    # Get user's application
    application = Application.query.filter_by(user_id=user.id).order_by(Application.created_at.desc()).first()

    # Get form fields
    form_markdown = get_form_markdown()
    form_fields = parse_markdown_form(form_markdown)

    return render_template('dashboard.html',
                           user_logged_in=user_logged_in,
                           user_status=user_status,
                           user=user,
                           application=application,
                           form_fields=form_fields,
                           form_markdown=form_markdown)


@app.route('/form/submit', methods=['POST'])
@login_required
def submit_form():
    """Submit application form"""
    user = User.query.get(session['user_id'])

    if not user:
        return redirect(url_for('index'))

    # Check if user is banned
    if user.status == 'banned':
        flash('Your account has been banned.', 'error')
        return redirect(url_for('dashboard'))

    # Parse form fields
    form_markdown = get_form_markdown()
    form_fields = parse_markdown_form(form_markdown)

    # Collect answers
    answers = {}
    current_file_fields = []

    for field in form_fields:
        field_name = field['question']

        if field['type'] == 'file':
            # Track file fields for cleanup
            current_file_fields.append(field_name)

            # Handle file upload
            if field_name in request.files:
                file = request.files[field_name]
                if file and file.filename:
                    if allowed_file(file.filename):
                        # Save file
                        user_upload_dir = UPLOAD_FOLDER / str(user.telegram_id)
                        user_upload_dir.mkdir(parents=True, exist_ok=True)

                        # Use original filename (as specified in markdown)
                        filename = secure_filename(translit(field_name, 'ru', reversed=True)) + '.' + secure_filename(file.filename.split('.')[-1])  # Use field name as filename
                        file_path = user_upload_dir / filename
                        file.save(str(file_path))

                        answers[field_name] = filename
                    else:
                        flash(f'File type not allowed for {field_name}', 'error')
        else:
            # Handle text inputs
            value = request.form.get(field_name, '')
            answers[field_name] = value

    # Clean up files that are no longer in the form
    # cleanup_user_files(user.telegram_id, current_file_fields)

    # Save or update application
    application = Application.query.filter_by(user_id=user.id).order_by(Application.created_at.desc()).first()
    
    is_resubmission = application is not None and application.answers

    if application:
        application.answers = json.dumps(answers)
        application.status = 'pending'
    else:
        application = Application(
            user_id=user.id,
            answers=json.dumps(answers),
            status='pending'
        )
        db.session.add(application)

    # Update user status
    user.status = 'pending'
    db.session.commit()
    
    notify_admins_new_application(user, is_resubmission=is_resubmission)

    flash('Application submitted successfully!', 'success')
    return redirect(url_for('dashboard'))


@app.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    """Serve uploaded files"""
    user = User.query.get(session['user_id'])

    if not user:
        abort(403)

    # Check if user has access to this file
    path_parts = filename.split('/')
    if path_parts[0] != str(user.telegram_id):
        # Check if admin
        if not session.get('is_admin'):
            abort(403)

    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/admin')
@admin_required
def admin():
    """Admin panel - view and manage applications"""
    # Get filter parameters
    status_filter = request.args.get('status', 'all')
    sort_by = request.args.get('sort', 'created_at')
    order = request.args.get('order', 'desc')

    user_logged_in = 'user_id' in session
    user_status = session.get('status', 'unverified') if user_logged_in else None
    
    # Build query
    query = User.query

    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    # Apply sorting
    if sort_by == 'created_at':
        query = query.order_by(User.created_at.desc() if order == 'desc' else User.created_at.asc())
    elif sort_by == 'username':
        query = query.order_by(User.username.asc() if order == 'asc' else User.username.desc())
    elif sort_by == 'status':
        query = query.order_by(User.status.asc() if order == 'asc' else User.status.desc())

    users = query.all()

    # Get applications with answers
    applications_data = []
    for user in users:
        app = Application.query.filter_by(user_id=user.id).order_by(Application.created_at.desc()).first()
        if app:
            applications_data.append({
                'user': user,
                'application': app,
                'answers': json.loads(app.answers) if app.answers else {}
            })

    # Get form fields for display
    form_markdown = get_form_markdown()
    form_fields = parse_markdown_form(form_markdown)

    return render_template('admin.html',
                           user_logged_in=user_logged_in,
                           user_status=user_status,
                           applications=applications_data,
                           form_fields=form_fields,
                           status_filter=status_filter,
                           sort_by=sort_by,
                           order=order)

@app.route('/admin/broadcast', methods=['GET', 'POST'])
@admin_required
def admin_broadcast():
    """Page for sending broadcast messages to users"""
    if request.method == 'POST':
        target_type = request.form.get('target_type')  # 'status' or 'individual'
        message_text = request.form.get('message_text', '')
        file = request.files.get('attachment')
        
        target_telegram_ids = []
        
        if target_type == 'status':
            status = request.form.get('target_status')
            users = User.query.filter_by(status=status).all()
            target_telegram_ids = [u.telegram_id for u in users]
        else:
            target_telegram_ids = request.form.getlist('target_users')

        if not target_telegram_ids:
            flash('No users selected for broadcast.', 'error')
            return redirect(url_for('admin_broadcast'))

        # Read file into memory once to avoid multiple disk reads during loop
        file_content = None
        filename = None
        if file and file.filename:
            file_content = file.read()
            filename = secure_filename(file.filename)

        success_count = 0
        for tid in target_telegram_ids:
            # Re-wrap in BytesIO for each request
            f_data = io.BytesIO(file_content) if file_content else None
            if send_telegram_broadcast(tid, message_text, f_data, filename):
                success_count += 1
        
        flash(f'Successfully sent to {success_count}/{len(target_telegram_ids)} users.', 'success')
        return redirect(url_for('admin_broadcast'))

    # GET request: Load users and statuses
    all_users = User.query.order_by(User.first_name).all()
    user_logged_in = 'user_id' in session
    user_status = session.get('status', 'unverified')
    
    return render_template('admin-broadcast.html', 
                           users=all_users, 
                           user_logged_in=user_logged_in, 
                           user_status=user_status)

@app.route('/admin/user/<int:user_id>/status', methods=['POST'])
@admin_required
def update_user_status(user_id):
    """Update user status (verify, reject, ban)"""
    user = User.query.get(user_id)

    if not user:
        flash('User not found', 'error')
        return redirect(url_for('admin'))

    new_status = request.form.get('status', '')
    rejection_reason = request.form.get('rejection_reason', '')

    if new_status in ['verified', 'rejected', 'banned', 'unverified']:
        user.status = new_status

        if new_status == 'rejected':
            user.rejection_reason = rejection_reason
        else:
            user.rejection_reason = None

        db.session.commit()
        if new_status in ['verified', 'rejected', 'banned']:
            send_telegram_notification(
                user.telegram_id,
                new_status,
                rejection_reason if new_status == 'rejected' else None
            )
        flash(f'User status updated to {new_status}', 'success')
    else:
        flash('Invalid status', 'error')

    return redirect(url_for('admin'))


@app.route('/admin/form/edit', methods=['GET', 'POST'])
@admin_required
def edit_form():
    """Edit form markdown"""
    if request.method == 'POST':
        form_markdown = request.form.get('form_markdown', '')

        # Sanitize markdown (basic)
        form_markdown = bleach.clean(form_markdown, tags=[], strip=True)

        # Save to database
        FormConfig.set('form_markdown', form_markdown)

        # Also save to file
        form_file = BASE_DIR / 'form.md'
        with open(form_file, 'w', encoding='utf-8') as f:
            f.write(form_markdown)

        flash('Form configuration saved!', 'success')
        return redirect(url_for('admin'))

    form_markdown = get_form_markdown()
    form_fields = parse_markdown_form(form_markdown)

    user_logged_in = 'user_id' in session
    user_status = session.get('status', 'unverified') if user_logged_in else None
    return render_template('form_edit.html',
                           user_logged_in=user_logged_in,
                           user_status=user_status,
                           form_markdown=form_markdown,
                           form_fields=form_fields)


@app.route('/logout')
def logout():
    """Logout user"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(413)
def request_entity_too_large(error):
    flash('File too large. Maximum size is 30MB.', 'error')
    return redirect(request.referrer or url_for('index'))


@app.errorhandler(404)
def not_found(error):
    user_logged_in = 'user_id' in session
    user_status = session.get('status', 'unverified') if user_logged_in else None
    return render_template('error.html', user_logged_in=user_logged_in, user_status=user_status, error='Page not found'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    user_logged_in = 'user_id' in session
    user_status = session.get('status', 'unverified') if user_logged_in else None
    return render_template('error.html', user_logged_in=user_logged_in, user_status=user_status, error='Internal server error'), 500


# ============================================================================
# CLI COMMANDS
# ============================================================================

@app.cli.command('init-db')
def init_db():
    """Initialize database"""
    db.create_all()
    print('Database initialized!')


@app.cli.command('create-admin')
def create_admin():
    """Create admin user"""
    telegram_id = input('Enter Telegram ID: ')
    user = User.query.filter_by(telegram_id=telegram_id).first()

    if user:
        user.is_admin = True
        print(f'User {telegram_id} is now admin')
    else:
        user = User(
            telegram_id=telegram_id,
            username='admin',
            first_name='Admin',
            is_admin=True,
            status='verified'
        )
        db.session.add(user)
        print(f'Admin user created: {telegram_id}')

    db.session.commit()


if __name__ == '__main__':
    # Initialize database
    with app.app_context():
        db.create_all()

        # Load admins and set admin flag for user 733806517
        admin_ids = load_admins()
        admin_user = User.query.filter_by(telegram_id='733806517').first()
        if admin_user:
            admin_user.is_admin = True
            db.session.commit()
            print(f'Admin user 733806517 updated')

    # Run app
    app.run(host='0.0.0.0', port=80, debug=True)
