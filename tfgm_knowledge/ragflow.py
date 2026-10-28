"""RAGFlow v1.0.0-rc2 HTTP client; credentials never enter release artifacts."""
import base64
import json
import os
from pathlib import Path
import ssl
import subprocess
import urllib.error
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class Client:
    def __init__(self, url, token=None, ca=None, session=False):
        if not url.startswith('https://'):raise ValueError('RAGFlow API 必须使用 HTTPS')
        self.url = url.rstrip('/') + '/api/v1'
        self.token = token
        self.session = session
        context = ssl.create_default_context(cafile=ca)
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))

    def call(self, method, path, data=None, raw=None, content_type=None):
        headers = {}
        if self.token: headers['Authorization'] = self.token if self.session else 'Bearer ' + self.token
        if data is not None:
            raw = json.dumps(data).encode()
            content_type = 'application/json'
        if content_type: headers['Content-Type'] = content_type
        req = urllib.request.Request(self.url + path, data=raw, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=120) as response:
                body = json.load(response)
                token = response.headers.get('Authorization')
        except urllib.error.HTTPError as e:
            raise RuntimeError(f'RAGFlow {method} {path}: HTTP {e.code}') from None
        if body.get('code') != 0:
            raise RuntimeError(f'RAGFlow {method} {path}: code={body.get("code")} {body.get("message", "")[:400]}')
        return body.get('data'), token

    @classmethod
    def local_session(cls, root):
        root = Path(root)
        config = json.loads((root / '.local/mode.json').read_text())
        credentials = json.loads((root / '.local/credentials.json').read_text())
        client = cls(f'https://127.0.0.1:{config["actualPort"]}', ca=str(root / '.local/certs/cert.pem'), session=True)
        encrypted = subprocess.run(['openssl', 'pkeyutl', '-encrypt', '-pubin', '-inkey', str(root / '.local/generated/login-public.pem'), '-pkeyopt', 'rsa_padding_mode:pkcs1'], input=base64.b64encode(credentials['user'].encode()), capture_output=True, check=True).stdout
        _, client.token = client.call('POST', '/auth/login', {'email': credentials['user_email'], 'password': base64.b64encode(encrypted).decode()})
        return client

    def upload(self, dataset_id, name, content):
        import secrets
        boundary = 'tfgm-' + secrets.token_hex(16)
        if any(c in name for c in '\r\n"'): raise ValueError('Invalid document filename')
        raw = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: text/markdown; charset=utf-8\r\n\r\n'.encode() + content + f'\r\n--{boundary}--\r\n'.encode())
        return self.call('POST', f'/datasets/{dataset_id}/documents', raw=raw, content_type='multipart/form-data; boundary=' + boundary)[0]

    @classmethod
    def configured(cls, path):
        conf = json.loads(Path(path).read_text())
        return cls(conf['url'], os.environ.get('RAGFLOW_API_KEY') or conf.get('api_key'), conf.get('ca'))
