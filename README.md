# Environ Server - Minecraft Server Website

## Project Overview

Flask-based website for a modded Minecraft server with Telegram OAuth authentication. Features Material You design, dynamic forms, admin panel, and file uploads.

![Environ Server website](docs/media/environ-desktop.png)

## Quick Start

### 1. Install Dependencies
```bash
cd environ-server
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create a `.env` file or set environment variables:
```bash
export TELEGRAM_BOT_TOKEN="your_bot_token_here"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

Keep the generated key in your private `.env` or service environment and reuse it
across restarts. Startup fails if the key is missing, shorter than 32 characters,
or is the old development default. Changing it invalidates existing sessions.

### 3. Add Video File
Place your webm video file at: `static/video/background.webm`
And a fallback image at: `static/video/fallback.jpg`

### 4. Run the Application
```bash
python app.py
```

The local server runs on port 5000 with debug mode disabled. For local development,
set `DEBUG=true` explicitly to enable it.

### 5. Access the Website
Open http://localhost:5000 in your browser

---

## VPS Deployment Instructions

### Using Gunicorn + Nginx (Recommended)

#### 1. Install Dependencies on VPS
```bash
pip install -r requirements.txt
pip install gunicorn
```

#### 2. Create Systemd Service
Create `/etc/systemd/system/environ-server.service`:
```ini
[Unit]
Description=Environ Server
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/path/to/environ-server
Environment="PATH=/path/to/venv/bin"
EnvironmentFile=/path/to/environ-server/.env
ExecStart=/path/to/venv/bin/gunicorn --config /path/to/environ-server/gunicorn.conf.py app:app

[Install]
WantedBy=multi-user.target
```

Put `SECRET_KEY=<your generated key>` and `TELEGRAM_BOT_TOKEN=<your bot token>` in
that private environment file (without `export`). Before starting Gunicorn,
initialize the database from the project directory with `flask --app app init-db`.

#### 3. Configure Nginx
Create `/etc/nginx/sites-available/environ-server`:
```nginx
# This file is included from nginx.conf's http context.
# Omit query strings and Referer: both can contain Telegram login credentials.
log_format environ_safe '$remote_addr [$time_local] '
                        '"$request_method $uri $server_protocol" '
                        '$status $body_bytes_sent';

server {
    listen 80;
    server_name your-domain.com;
    access_log /var/log/nginx/environ-access.log environ_safe;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /static/ {
        alias /path/to/environ-server/static/;
    }

    # /uploads must pass through location / to Flask's authorization checks.
}
```

Apply the same access-log format to your HTTPS server block. Enable HTTPS before
using Telegram login in production. Do not add a static alias for `/uploads`.
The Gunicorn configuration and `python app.py` also omit query strings from access
logs. Keep these formats when adding a proxy or log collector, and do not log
request bodies or full callback URLs there. The Werkzeug log filter also applies
when serving locally with `flask run`.

#### 4. Enable and Start
```bash
sudo ln -s /etc/nginx/sites-available/environ-server /etc/nginx/sites-enabled
sudo systemctl daemon-reload
sudo systemctl start environ-server
sudo systemctl enable environ-server
sudo nginx -t && sudo systemctl reload nginx
```

---

## Features

### Landing Page
- Full-screen video background with dark overlay
- Server name and tagline
- 5 alternating info blocks with scroll animations
- Social links (Telegram, Email, VK)
- Theme toggle (light/dark)

### Authentication
- Telegram OAuth via Login Widget
- Session-based authentication
- Admin access via `admins.json`

### User Dashboard
- Application form (dynamic, markdown-based)
- Status display (unverified/pending/verified/rejected/banned)
- Rejection reason display
- Server info for verified users (IP, instructions, downloads)
- File upload support

### Admin Panel
- View all applications
- Filter by status
- Sort by date/username/status
- Verify/Reject/Ban users
- Markdown form editor

### Security
- CSRF protection (Flask-WTF)
- Input sanitization (Bleach)
- Secure file uploads (extension whitelist, 30MB limit)
- Telegram hash verification

---

## Configuration Files

### admins.json
The repository ships with an empty admin list. Add your own Telegram IDs locally
to grant admin access; do not commit real IDs:
```json
{
  "admin_ids": ["123456789", "other_id"]
}
```

This file is the source of admin permissions. Changes take effect on the next
request, including existing sessions; banned users cannot use admin access.
`flask --app app create-admin` updates both the allowlist and the user record.

### form.md
Define your application form using markdown:
```markdown
## Question Title
- type: text|textarea|dropdown|multiselect|file
- required: true|false
- options: option1, option2, option3 (for dropdown/multiselect)
```

### Server Info (in dashboard.html)
Edit the `server-info-card` section to customize:
- Server IP and port
- Connection instructions
- Download buttons (use `data-filename` attribute)
- Discord link

---

## Download Button Usage

To add download buttons for verified users, add this to dashboard.html:
```html
<a href="#" class="download-button" data-filename="modpack.zip">
    <svg>...</svg>
    <span>Скачать модпак</span>
</a>
```

The `data-filename` attribute specifies which file to download from `/uploads/{telegram_id}/`.

---

## Project Structure
```
environ-server/
├── app.py              # Main Flask application
├── config.py           # Configuration
├── models.py           # Database models
├── admins.json         # Admin IDs
├── form.md            # Form definition
├── requirements.txt    # Dependencies
├── static/
│   ├── css/style.css  # Material You styles
│   ├── js/main.js     # Frontend JavaScript
│   └── video/         # Background video
├── templates/         # HTML templates
└── uploads/           # User uploads (auto-created)
```

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests use a temporary database, synthetic Telegram signatures, and temporary
uploads. They do not contact Telegram or the Minecraft server. To also test
Gunicorn's real access-log formatting, install it with `pip install gunicorn`.
