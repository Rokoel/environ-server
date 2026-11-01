"""Security regressions using synthetic identities and isolated application data."""
import contextlib
from datetime import timedelta
import hashlib
import hmac
import http.client
import io
import json
import logging
import os
from pathlib import Path
import runpy
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from werkzeug.datastructures import MultiDict
from werkzeug.serving import make_server

# Configure an in-memory database before Flask-SQLAlchemy creates its engine.
os.environ['SECRET_KEY'] = secrets.token_hex(32)
with patch('dotenv.load_dotenv'):
    import config
config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
import app as website


def signed_payload(**overrides):
    payload = {
        'id': '100001',
        'first_name': 'AUTH_NAME_SENTINEL',
        'auth_date': str(int(time.time())),
        **overrides,
    }
    check = '\n'.join(f'{key}={value}' for key, value in sorted(payload.items()))
    secret = hashlib.sha256(b'synthetic-bot-token').digest()
    payload['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return payload


class WebsiteSecurityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.uploads = self.root / 'uploads'
        self.uploads.mkdir()
        self.admin_file = self.root / 'admins.json'
        self.admin_file.write_text(json.dumps({'admin_ids': ['300003']}))
        for name, value in (
            ('BASE_DIR', self.root),
            ('UPLOAD_FOLDER', self.uploads),
            ('TELEGRAM_BOT_TOKEN', 'synthetic-bot-token'),
            ('get_server_status', lambda: {'online': False}),
        ):
            patcher = patch.object(website, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.notify = patch.object(website, 'notify_admins_new_application').start()
        self.addCleanup(patch.stopall)
        website.app.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
        self.context = website.app.app_context()
        self.context.push()
        website.db.create_all()
        self.addCleanup(self.clean_database)
        for telegram_id in ['100001', '200002', '300003']:
            website.db.session.add(website.User(
                telegram_id=telegram_id,
                first_name='Synthetic user',
                status='unverified',
                is_admin=telegram_id == '300003',
            ))
            folder = self.uploads / telegram_id
            folder.mkdir()
            (folder / 'private.txt').write_text(f'PRIVATE_{telegram_id}')
        website.db.session.commit()
        self.client = website.app.test_client()

    def clean_database(self):
        website.db.session.remove()
        website.db.drop_all()
        self.context.pop()

    def login(self, telegram_id='100001', **session_overrides):
        user = website.User.query.filter_by(telegram_id=telegram_id).one()
        with self.client.session_transaction() as session:
            session.clear()
            session.update(user_id=user.id, telegram_id=telegram_id,
                           is_admin=user.is_admin, status=user.status)
            session.update(session_overrides)
        return user

    def form(self, markdown):
        website.FormConfig.set('form_markdown', markdown)

    def submit(self, data):
        # Exercise real CSRF validation using the token rendered by the dashboard.
        response = self.client.get('/dashboard')
        import re
        token = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        if token is not None:
            self.csrf_token = token.group(1).decode()
        # A previously rendered token remains valid if the user's status changes
        # and their dashboard no longer contains an editable form.
        self.assertTrue(getattr(self, 'csrf_token', None))
        values = MultiDict(data)
        values.add('csrf_token', self.csrf_token)
        return self.client.post('/form/submit', data=values)

    def answers(self):
        return json.loads(website.Application.query.one().answers)

    def test_owner_can_download_own_upload(self):
        self.login()
        with self.client.get('/uploads/100001/private.txt') as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'PRIVATE_100001')

    def test_anonymous_download_requires_login(self):
        self.assertEqual(self.client.get('/uploads/100001/private.txt').status_code, 302)

    def test_cross_user_download_is_denied(self):
        self.login()
        self.assertEqual(self.client.get('/uploads/200002/private.txt').status_code, 403)

    def test_traversal_and_encoded_traversal_are_denied(self):
        self.login()
        for path in [
            '/uploads/100001/../200002/private.txt',
            '/uploads/100001/%2e%2e/200002/private.txt',
            '/uploads/100001/%2e%2e%2f200002/private.txt',
            '/uploads/100001/../../admins.json',
            '/uploads/100001/%5c../200002/private.txt',
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_symlink_cannot_escape_owner_directory(self):
        self.login()
        (self.uploads / '100001' / 'linked.txt').symlink_to(self.uploads / '200002' / 'private.txt')
        self.assertEqual(self.client.get('/uploads/100001/linked.txt').status_code, 403)

    def test_admin_can_read_other_uploads_but_not_escape_root(self):
        self.login('300003')
        with self.client.get('/uploads/200002/private.txt') as response:
            self.assertEqual(response.status_code, 200)
        (self.uploads / '300003' / 'outside.txt').symlink_to(self.admin_file)
        self.assertEqual(self.client.get('/uploads/300003/outside.txt').status_code, 403)

    def test_revocation_applies_to_existing_admin_session_and_downloads(self):
        admin = self.login('300003')
        self.assertEqual(self.client.get('/admin').status_code, 200)
        self.admin_file.write_text('{"admin_ids": []}')
        self.assertEqual(self.client.get('/admin').status_code, 302)
        self.assertEqual(self.client.get('/uploads/200002/private.txt').status_code, 403)
        self.assertFalse(website.db.session.get(website.User, admin.id).is_admin)
        with self.client.session_transaction() as session:
            self.assertFalse(session['is_admin'])

    def test_stale_admin_boolean_cannot_grant_access(self):
        self.login(is_admin=True)
        self.assertEqual(self.client.get('/admin').status_code, 302)

    def test_revoked_admin_cannot_submit_a_previously_rendered_action(self):
        import re
        self.login('300003')
        response = self.client.get('/admin')
        token = re.search(rb'name="csrf_token" value="([^"]+)"', response.data).group(1).decode()
        target = website.User.query.filter_by(telegram_id='100001').one()
        self.admin_file.write_text('{"admin_ids": []}')
        response = self.client.post(f'/admin/user/{target.id}/status',
                                    data={'csrf_token': token, 'status': 'verified'})
        self.assertTrue(response.location.endswith('/dashboard'))
        self.assertEqual(target.status, 'unverified')

    def test_invalid_admin_configuration_denies_access(self):
        self.login('300003')
        for contents in ['{broken', '[]', '{"admin_ids": "300003"}']:
            with self.subTest(contents=contents):
                self.admin_file.write_text(contents)
                self.assertEqual(self.client.get('/admin').status_code, 302)

    def test_ban_revokes_existing_admin_session(self):
        user = self.login('300003')
        user.status = 'banned'
        website.db.session.commit()
        self.assertEqual(self.client.get('/admin').status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session['status'], 'banned')
            self.assertFalse(session['is_admin'])

    def test_deleted_users_session_is_cleared(self):
        user = self.login()
        website.db.session.delete(user)
        website.db.session.commit()
        self.assertEqual(self.client.get('/dashboard').status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn('user_id', session)

    def test_create_admin_updates_canonical_allowlist(self):
        result = website.app.test_cli_runner().invoke(args=['create-admin'], input='100001\n')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('100001', website.load_admins())
        self.login()
        self.assertEqual(self.client.get('/admin').status_code, 200)

    def test_required_text_and_textarea_are_enforced_on_server(self):
        self.login()
        for field_type in ['text', 'textarea']:
            with self.subTest(field_type=field_type):
                self.form(f'## Answer\n- type: {field_type}\n- required: true')
                self.submit([('Answer', '   ')])
                self.assertEqual(website.Application.query.count(), 0)
        self.notify.assert_not_called()

    def test_dropdown_rejects_unknown_or_duplicate_values(self):
        self.login()
        self.form('## Choice\n- type: dropdown\n- required: true\n- options: A, B')
        for data in [[], [('Choice', 'C')], [('Choice', 'A'), ('Choice', 'B')]]:
            with self.subTest(data=data):
                self.submit(data)
                self.assertEqual(website.Application.query.count(), 0)
        self.submit([('Choice', 'B')])
        self.assertEqual(self.answers()['Choice'], 'B')

    def test_multiselect_saves_all_selected_values(self):
        self.login()
        self.form('## Choices\n- type: multiselect\n- required: true\n- options: A, B, C')
        self.submit([('Choices', 'A'), ('Choices', 'C')])
        self.assertEqual(self.answers()['Choices'], 'A,C')
        response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.count(b'checked>'), 2)

    def test_multiselect_rejects_missing_or_unknown_choices(self):
        self.login()
        self.form('## Choices\n- type: multiselect\n- required: true\n- options: A, B')
        for data in [[], [('Choices', 'C')], [('Choices', 'A'), ('Choices', 'C')]]:
            with self.subTest(data=data):
                self.submit(data)
                self.assertEqual(website.Application.query.count(), 0)

    def test_optional_fields_can_be_empty(self):
        self.login()
        self.form('## Answer\n- type: text\n## Choice\n- type: dropdown\n- options: A, B\n## Choices\n- type: multiselect\n- options: A, B\n## Attachment\n- type: file')
        self.submit([])
        self.assertEqual(self.answers(), {'Answer': '', 'Choice': '', 'Choices': ''})

    def test_required_file_and_extension_are_validated(self):
        self.login()
        self.form('## Attachment\n- type: file\n- required: true')
        self.submit([])
        self.assertEqual(website.Application.query.count(), 0)
        self.submit([('Attachment', (io.BytesIO(b'bad'), 'script.exe'))])
        self.assertEqual(website.Application.query.count(), 0)
        self.assertEqual(list((self.uploads / '100001').glob('Attachment.*')), [])

    def test_invalid_form_does_not_save_files_or_change_status(self):
        user = self.login()
        self.form('## Attachment\n- type: file\n## Required\n- type: text\n- required: true')
        self.submit([('Attachment', (io.BytesIO(b'%PDF-synthetic'), 'file.pdf'))])
        self.assertEqual(website.Application.query.count(), 0)
        self.assertEqual(user.status, 'unverified')
        self.assertFalse((self.uploads / '100001' / 'Attachment.pdf').exists())
        self.notify.assert_not_called()

    def test_required_upload_is_preserved_when_resubmitting(self):
        self.login()
        self.form('## Attachment\n- type: file\n- required: true\n## Answer\n- type: text')
        self.submit([('Attachment', (io.BytesIO(b'%PDF-synthetic'), 'file.pdf')), ('Answer', 'first')])
        filename = self.answers()['Attachment']
        path = self.uploads / '100001' / filename
        self.assertEqual(path.read_bytes(), b'%PDF-synthetic')
        self.submit([('Answer', 'edited')])
        self.assertEqual(self.answers(), {'Attachment': filename, 'Answer': 'edited'})
        self.assertEqual(path.read_bytes(), b'%PDF-synthetic')
        self.assertEqual(website.Application.query.count(), 1)

    def test_missing_existing_required_upload_is_not_accepted(self):
        self.login()
        self.form('## Attachment\n- type: file\n- required: true')
        self.submit([('Attachment', (io.BytesIO(b'%PDF-synthetic'), 'file.pdf'))])
        filename = self.answers()['Attachment']
        (self.uploads / '100001' / filename).unlink()
        self.notify.reset_mock()
        self.submit([])
        self.notify.assert_not_called()

    def test_invalid_edit_keeps_existing_answers_and_status(self):
        user = self.login()
        self.form('## Answer\n- type: text\n- required: true')
        self.submit([('Answer', 'existing')])
        user.status = 'verified'
        website.db.session.commit()
        self.submit([('Answer', '')])
        self.assertEqual(self.answers()['Answer'], 'existing')
        self.assertEqual(user.status, 'verified')

    def test_csrf_is_still_required(self):
        self.login()
        self.assertEqual(self.client.post('/form/submit', data={}).status_code, 400)

    def test_valid_login_has_no_payload_or_hash_output(self):
        payload = signed_payload()
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        with contextlib.redirect_stdout(output), patch.object(website.hmac, 'compare_digest', wraps=hmac.compare_digest) as compare:
            response = self.client.get('/auth/telegram', query_string=payload)
            self.assertTrue(compare.called)
        self.assertTrue(response.location.endswith('/dashboard'))
        for private_value in [payload['hash'], payload['first_name'], 'auth_date=']:
            self.assertNotIn(private_value, output.getvalue())

    def test_auth_rejects_tampering_expiration_future_dates_and_malformed_fields(self):
        valid = signed_payload()
        for payload in [
            {**valid, 'first_name': 'tampered'},
            signed_payload(auth_date=str(int(time.time()) - 86401)),
            signed_payload(auth_date=str(int(time.time()) + 86400)),
            signed_payload(auth_date='bad-date'),
            signed_payload(id=''),
            signed_payload(id='../bad-id'),
            {**valid, 'hash': 'invalid'},
        ]:
            with self.subTest(payload_type=list(payload.keys())):
                self.assertFalse(website.verify_telegram_auth(payload))

    def test_duplicate_auth_parameters_are_rejected(self):
        values = MultiDict(signed_payload())
        values.add('id', '200002')
        self.assertEqual(self.client.get('/auth/telegram', query_string=values).status_code, 400)

    def test_form_post_login_validates_csrf_and_telegram_signature(self):
        self.login()
        self.form('## Answer\n- type: text')
        self.submit([('Answer', 'prepare a CSRF token')])
        payload = signed_payload()
        self.assertEqual(self.client.post('/auth/telegram', data=payload).status_code, 400)
        response = self.client.post('/auth/telegram', data={**payload, 'csrf_token': self.csrf_token})
        self.assertTrue(response.location.endswith('/dashboard'))


class ConfigurationAndLoggingTests(unittest.TestCase):
    def test_unsafe_or_missing_secret_keys_fail_startup(self):
        script = 'from unittest.mock import patch\nwith patch("dotenv.load_dotenv"):\n import config'
        for secret in [None, '', 'short', 'dev-secret-key-change-in-production']:
            with self.subTest(secret=secret):
                environment = dict(os.environ)
                if secret is None:
                    environment.pop('SECRET_KEY', None)
                else:
                    environment['SECRET_KEY'] = secret
                result = subprocess.run([sys.executable, '-c', script], env=environment,
                                        cwd=Path(__file__).resolve().parents[1],
                                        capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Set SECRET_KEY', result.stderr)

    def test_generated_secret_allows_startup(self):
        environment = {**os.environ, 'SECRET_KEY': secrets.token_hex(32)}
        result = subprocess.run([sys.executable, '-c', 'import config'], env=environment,
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_werkzeug_access_logs_omit_callback_queries(self):
        def application(environ, start_response):
            start_response('200 OK', [('Content-Type', 'text/plain')])
            return [b'ok']

        server = make_server('127.0.0.1', 0, application)
        server.timeout = 3
        worker = threading.Thread(target=server.handle_request, daemon=True)
        worker.start()
        try:
            with self.assertLogs('werkzeug', level='INFO') as logs:
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                try:
                    connection.request('GET', '/auth/telegram?hash=HASH_SENTINEL&first_name=NAME_SENTINEL')
                    self.assertEqual(connection.getresponse().read(), b'ok')
                finally:
                    connection.close()
            log_text = '\n'.join(logs.output)
            self.assertIn('GET /auth/telegram HTTP/', log_text)
            self.assertNotIn('SENTINEL', log_text)
            self.assertNotIn('?', log_text)
        finally:
            worker.join(timeout=3)
            server.server_close()

    def test_gunicorn_format_omits_query_and_referrer(self):
        try:
            from gunicorn.glogging import Logger
        except ImportError:
            self.skipTest('Install gunicorn to exercise its access logger')
        settings = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'gunicorn.conf.py'))
        logger = object.__new__(Logger)
        response = SimpleNamespace(status='302 Found', sent=0, headers=[])
        environ = {
            'REQUEST_METHOD': 'GET', 'SERVER_PROTOCOL': 'HTTP/1.1',
            'RAW_URI': '/auth/telegram?hash=HASH_SENTINEL',
            'PATH_INFO': '/auth/telegram', 'QUERY_STRING': 'hash=HASH_SENTINEL',
            'HTTP_REFERER': 'https://example.test/auth/telegram?hash=REFERER_SENTINEL',
        }
        line = settings['access_log_format'] % logger.atoms(response, [], environ, timedelta())
        self.assertIn('GET /auth/telegram HTTP/1.1', line)
        self.assertNotIn('SENTINEL', line)


if __name__ == '__main__':
    unittest.main()
