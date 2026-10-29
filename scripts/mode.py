#!/usr/bin/env python3
"""Linux development infrastructure manager. No third-party Python dependencies."""
import argparse
import base64
import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
import unicodedata
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
CONFIG = LOCAL / 'mode.json'
KEY = hashlib.sha256(('mode:v1\0' + str(ROOT)).encode()).hexdigest()
PROJECT = 'tfgm-kb-' + KEY[:12]
GENERATED = LOCAL / 'generated'
COMPOSE = GENERATED / 'compose.json'
UPSTREAM = ROOT / 'infra/ragflow/upstream'
STATE = LOCAL / 'state.json'
COMMANDS = {
    '服务管理': {'start': '启动并等待 HTTPS 和依赖就绪', 'stop': '停止本项目容器，保留全部数据'},
    '状态与排障': {'status': '查看状态、访问地址与空间', 'health': '检查真实服务健康，失败返回非零', 'logs': '显示最近日志（--follow 持续跟踪）', 'help': '显示分组帮助'},
    'MCP 服务': {'mcp:start': '启动 Bun MCP（独立于 RAGFlow）', 'mcp:stop': '停止 Bun MCP，保留知识包', 'mcp:status': '查看 MCP 地址、身份与知识包', 'mcp:health': '验证 MCP HTTPS 健康', 'mcp:logs': '查看 MCP 轮转日志', 'mcp:help': 'MCP 服务帮助'},
    '维护': {'clean': '清理登记的过期临时文件（--dry-run 只读预览）'},
}


def run(args, check=True, timeout=60):
    p = subprocess.run([str(x) for x in args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f'{args[0]} 执行失败：{p.stderr[-2500:]}')
    return p


def read(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(path.suffix + '.tmp')
    with os.fdopen(os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), 'w') as f:
        f.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def config():
    c = read(CONFIG)
    if c is not None and (c.get('version') != 1 or c.get('repoKey') != KEY):
        raise ValueError('配置版本或仓库身份不匹配；请保留原数据后人工检查 .local/mode.json')
    if c is not None:
        policy = c['storage']
        triggers, exits = policy['triggers'], policy['exits']
        if len(triggers) != 3 or len(exits) != 3 or triggers != sorted(triggers) or any(not 0 < e < t < 100 for e, t in zip(exits, triggers)):
            raise ValueError('磁盘水位配置不合法')
        if not 1024 <= c['portBase'] <= 32735 or not c['portBase'] <= c['actualPort'] < c['portBase'] + 32:
            raise ValueError('端口配置不合法')
        ipaddress.ip_address(c['bindHost'])
    return c


@contextlib.contextmanager
def lock():
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    with (LOCAL / 'lifecycle.lock').open('a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('另一个基础设施操作正在进行，请稍后重试')
        yield


def docker_identity():
    context = run(['docker', 'context', 'show']).stdout.strip()
    endpoint = os.environ.get('DOCKER_HOST') or json.loads(run(['docker', 'context', 'inspect', context]).stdout)[0]['Endpoints']['docker']['Host']
    info = json.loads(run(['docker', 'info', '--format', '{{json .}}']).stdout)
    return {'context': context, 'endpoint': endpoint, 'id': info['ID'], 'root': info['DockerRootDir']}


def verify_daemon(c):
    actual = docker_identity()
    if c and c.get('docker') and actual != c['docker']:
        raise RuntimeError('Docker context/daemon 与初始化时不一致，拒绝操作其它实例')
    return actual


def compose(*args, check=True, timeout=60):
    return run(['docker', 'compose', '-p', PROJECT, '-f', COMPOSE, *args], check, timeout)


def containers():
    ids = run(['docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={PROJECT}']).stdout.split()
    if not ids:
        return []
    cs = json.loads(run(['docker', 'inspect', *ids]).stdout)
    for c in cs:
        labels = c['Config']['Labels']
        service = labels.get('com.docker.compose.service')
        if labels.get('dev.tfgm.repo') != KEY or labels.get('dev.tfgm.managed') != 'mode-v1' or labels.get('dev.tfgm.service') != service:
            raise RuntimeError('发现归属不匹配的容器，拒绝继续：' + c['Id'][:12])
    return cs


def lan_ips():
    interfaces = json.loads(run(['ip', '-j', '-4', 'address', 'show', 'scope', 'global']).stdout)
    return sorted({a['local'] for interface in interfaces if interface['ifname'] != 'docker0' and not interface['ifname'].startswith(('br-', 'veth')) for a in interface.get('addr_info', [])})


def pressure(used, previous=0, triggers=None, exits=None):
    triggers, exits = triggers or [75, 85, 92], exits or [70, 78, 85]
    level = sum(used >= x for x in triggers)
    if previous and used >= exits[previous - 1]:
        level = max(level, previous)
    return level


def filesystem(path):
    try:
        s = os.statvfs(path)
        total, available = s.f_blocks * s.f_frsize, s.f_bavail * s.f_frsize
        return {'path': str(path), 'device': os.stat(path).st_dev, 'capacity': total, 'available': available,
                'usedPercent': round((1 - available / total) * 100, 2), 'inodesAvailable': s.f_favail if s.f_files else None}
    except OSError as e:
        return {'path': str(path), 'unknown': str(e)}


def storage(c):
    policy = c['storage'] if c else {'budgetFraction': .01, 'budgetCapBytes': 2 * 1024**3, 'temporaryDays': 7, 'triggers': [75,85,92], 'exits': [70,78,85]}
    project = filesystem(ROOT)
    daemon = {'unknown': 'Docker 文件系统未获取'}
    if c and c.get('docker') and c['docker']['endpoint'].startswith('unix://'):
        daemon = filesystem(c['docker']['root'])
    if daemon.get('device') == project.get('device'):
        daemon = {**daemon, 'sameAsProject': True}
    return {'project': project, 'docker': daemon, 'budget': min(project.get('capacity', 0) * policy['budgetFraction'], policy['budgetCapBytes']),
            'policy': f"{policy['triggers']}% 触发，{policy['exits']}% 退出；临时缓存 {policy['temporaryDays']} 天；共享镜像跳过",
            'last': read(LOCAL / 'maintenance.json', {'summary': '尚未维护'})}


def candidates(now, manifest, days=7):
    result = []
    for item in manifest:
        p = Path(item['path'])
        if item.get('repoKey') != KEY or item.get('kind') != 'temporary':
            continue
        base = LOCAL / 'cache'
        if p.is_symlink() or base.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(base.resolve()):
            continue
        if any(parent.is_symlink() for parent in p.parents if parent != base.parent):
            continue
        last = item.get('lastUsed', item.get('firstObserved', now))
        if now - last >= days * 86400 and not item.get('protected'):
            result.append({**item, 'bytes': p.stat().st_size, 'reason': f'登记的临时文件闲置至少 {days} 天'})
    return sorted(result, key=lambda x: (x.get('cost', 0), x.get('lastUsed', x.get('firstObserved', now))))


def clean(c, dry=False):
    manifest = read(LOCAL / 'cache-manifest.json', [])
    days = c['storage']['temporaryDays'] if c else 7
    chosen = candidates(time.time(), manifest, days)
    result = {'dryRun': dry, 'candidates': chosen, 'skipped': '持久卷、源码、凭据、证书、知识库产物及共享镜像全部保护', 'deletedBytes': 0}
    if not dry:
        begin = time.monotonic()
        removed = set()
        for item in chosen[:20]:
            if time.monotonic() - begin > 5 or result['deletedBytes'] + item['bytes'] > 256 * 1024**2:
                break
            if item not in candidates(time.time(), [item], days):
                continue
            Path(item['path']).unlink()
            result['deletedBytes'] += item['bytes']
            removed.add(item['path'])
        write(LOCAL / 'cache-manifest.json', [x for x in manifest if x['path'] not in removed])
        write(LOCAL / 'maintenance.json', {'time': time.time(), 'summary': f"已清理 {result['deletedBytes']} 字节；无其它可安全回收资源"})
    return result


def admission(c):
    clean(c)
    disks = storage(c)
    policy = c['storage']
    old = read(LOCAL / 'pressure.json', {})
    levels = {}
    for name in ('project', 'docker'):
        d = disks[name]
        if 'unknown' in d:
            raise RuntimeError(f'{name} 磁盘状态未知，无法进行镜像准备：{d["unknown"]}')
        levels[name] = pressure(d['usedPercent'], old.get(name, 0), policy['triggers'], policy['exits'])
        write(LOCAL / 'pressure.json', {**old, **levels})
        if levels[name] == 3 or (d['inodesAvailable'] is not None and d['inodesAvailable'] < 100):
            raise RuntimeError(f'{name} 空间处于临界状态 {d["usedPercent"]}%，保留已有服务并停止部署；本项目无权清理其他项目')


def prepare():
    c = config()
    daemon = verify_daemon(c)
    if c is None:
        port = 18000 + int(hashlib.sha256((KEY + '\0docker\0port\0https').encode()).hexdigest()[:8], 16) % 10000
        c = {'version': 1, 'repoKey': KEY, 'docker': daemon, 'portBase': port, 'actualPort': port, 'bindHost': '0.0.0.0',
             'storage': {'triggers': [75, 85, 92], 'exits': [70, 78, 85], 'temporaryDays': 7, 'budgetFraction': .01, 'budgetCapBytes': 2 * 1024**3}}
        write(CONFIG, c)
    if not c.get('docker'):
        c['docker'] = daemon
        write(CONFIG, c)
    GENERATED.mkdir(mode=0o700, exist_ok=True)
    secret_path = LOCAL / 'credentials.json'
    if not secret_path.exists() and containers():
        raise RuntimeError('已有容器但凭据文件缺失，拒绝重置数据库密码')
    if not secret_path.exists():
        write(secret_path, {k: secrets.token_hex(24) for k in ('mysql', 'elastic', 'minio', 'redis', 'admin')})
    creds = read(secret_path)
    ips = lan_ips()
    certdir = LOCAL / 'certs'
    certdir.mkdir(mode=0o700, exist_ok=True)
    cert, key = certdir / 'cert.pem', certdir / 'key.pem'
    sans = ['DNS:localhost', 'IP:127.0.0.1', *['IP:' + ip for ip in ips]]
    if not cert.exists() or read(certdir / 'sans.json') != sans or run(['openssl', 'x509', '-checkend', '86400', '-noout', '-in', cert], check=False).returncode:
        run(['openssl', 'req', '-x509', '-nodes', '-newkey', 'rsa:2048', '-days', '90', '-keyout', key, '-out', cert,
             '-subj', '/CN=tfgm-knowledge.local', '-addext', 'subjectAltName=' + ','.join(sans)])
        key.chmod(0o600)
        write(certdir / 'sans.json', sans)
    c['lanIPs'] = ips
    write(CONFIG, c)
    template = (UPSTREAM / 'service_conf.yaml.template').read_text()
    template += '\nlog:\n  level: info\n  max_size: 10\n  max_backups: 3\n  max_age: 7\n  compress: true\n'
    (GENERATED / 'service_conf.yaml.template').write_text(template)
    nginx = f'''events {{}}
http {{
  access_log /dev/stdout;
  error_log /dev/stderr warn;
  map $http_upgrade $connection_upgrade {{ default upgrade; '' close; }}
  server {{
    listen 443 ssl;
    ssl_certificate /certs/cert.pem;
    ssl_certificate_key /certs/key.pem;
    client_max_body_size 100m;
    add_header X-TFGM-Instance "{KEY}" always;
    location / {{
      proxy_pass http://ragflow:80;
      proxy_http_version 1.1;
      proxy_set_header Host $http_host;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header X-Forwarded-For $remote_addr;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection $connection_upgrade;
      proxy_buffering off;
      proxy_read_timeout 600s;
    }}
  }}
}}
'''
    (GENERATED / 'nginx.conf').write_text(nginx)
    env = {'DOC_ENGINE': 'elasticsearch', 'DB_TYPE': 'mysql', 'MYSQL_HOST': 'mysql', 'MYSQL_PORT': '3306', 'MYSQL_DBNAME': 'rag_flow',
           'MYSQL_PASSWORD': creds['mysql'], 'ES_HOST': 'es01', 'ELASTIC_PASSWORD': creds['elastic'],
           'MINIO_HOST': 'minio', 'MINIO_USER': 'rag_flow', 'MINIO_PASSWORD': creds['minio'],
           'KVROCKS_HOST': 'kvrocks', 'KVROCKS_PORT': '6379', 'REDIS_PASSWORD': creds['redis'],
           'NATS_HOST': 'nats', 'NATS_PORT': '4222', 
           'REGISTER_ENABLED': '0', 'ENABLE_REGISTER': '0', 'OAUTH_AUTO_REGISTER': 'false', 'TZ': 'Asia/Shanghai'}
    def health(cmd):
        return {'test': ['CMD-SHELL', cmd], 'interval': '10s', 'timeout': '5s', 'retries': 60, 'start_period': '30s'}
    services = {
        'mysql': {'image': 'mysql:8.0.40', 'environment': {'MYSQL_ROOT_PASSWORD': creds['mysql']},
                  'command': ['--character-set-server=utf8mb4', '--collation-server=utf8mb4_unicode_ci', '--init-file=/init.sql', '--innodb-buffer-pool-size=256M', '--max-connections=200', '--binlog-expire-logs-seconds=86400'],
                  'volumes': ['mysql:/var/lib/mysql', f'{UPSTREAM}/init.sql:/init.sql:ro'], 'mem_limit': '1g',
                  'healthcheck': health('mysqladmin ping -h 127.0.0.1 -uroot -p"$MYSQL_ROOT_PASSWORD"')},
        'es01': {'image': 'elasticsearch:8.11.3', 'environment': {'ELASTIC_PASSWORD': creds['elastic'], 'discovery.type': 'single-node', 'xpack.security.enabled': 'true', 'xpack.security.http.ssl.enabled': 'false', 'ES_JAVA_OPTS': '-Xms512m -Xmx512m'},
                 'volumes': ['elastic:/usr/share/elasticsearch/data'], 'tmpfs': ['/tmp:mode=1777,size=256m'], 'mem_limit': '1536m',
                 'healthcheck': health('curl -fsS -u "elastic:$ELASTIC_PASSWORD" http://localhost:9200/_cluster/health >/dev/null')},
        'minio': {'image': 'pgsty/silo:RELEASE.2026-08-06T00-00-00Z', 'command': ['server', '/data'], 'environment': {'MINIO_ROOT_USER': 'rag_flow', 'MINIO_ROOT_PASSWORD': creds['minio']}, 'volumes': ['minio:/data'], 'mem_limit': '512m', 'healthcheck': health('curl -fsS http://localhost:9000/minio/health/live')},
        'kvrocks': {'image': 'apache/kvrocks:2.16.0', 'user': '0:0', 'entrypoint': ['/bin/sh', '/etc/kvrocks/entrypoint.sh'], 'environment': {'REDIS_PASSWORD': creds['redis']}, 'volumes': ['kvrocks:/var/lib/kvrocks', f'{UPSTREAM}/kvrocks-entrypoint.sh:/etc/kvrocks/entrypoint.sh:ro'], 'mem_limit': '768m', 'healthcheck': health('redis-cli -a "$REDIS_PASSWORD" ping | grep PONG')},
        'nats': {'image': 'nats:2.14.2', 'command': ['-js', '-sd', '/data', '--http_port', '8222'], 'volumes': ['nats:/data'], 'mem_limit': '256m'},
        'ragflow': {'image': 'infiniflow/ragflow:v1.0.0-rc2', 'command': ['--enable-adminserver', '--init-superuser'], 'environment': env,
                    'volumes': [f'{GENERATED}/service_conf.yaml.template:/ragflow/conf/service_conf.yaml.template:ro', 'logs:/ragflow/logs'], 'mem_limit': '4g', 'cpus': 2,
                    'depends_on': {name: {'condition': 'service_started' if name == 'nats' else 'service_healthy'} for name in ['mysql', 'es01', 'minio', 'kvrocks', 'nats']},
                    'healthcheck': health('curl -fsS http://localhost:9380/api/v1/system/healthz >/dev/null')},
        'https': {'image': 'nginx:1.28.0-alpine', 'ports': [f'{c["bindHost"]}:{c["actualPort"]}:443'], 'volumes': [f'{GENERATED}/nginx.conf:/etc/nginx/nginx.conf:ro', f'{certdir}:/certs:ro'], 'mem_limit': '64m', 'depends_on': {'ragflow': {'condition': 'service_healthy'}}},
    }
    image_digests = read(ROOT / 'infra/ragflow/images.json')
    for name, service in services.items():
        service['image'] += '@' + image_digests[service['image']]
        service['labels'] = {'dev.tfgm.repo': KEY, 'dev.tfgm.managed': 'mode-v1', 'dev.tfgm.service': name}
        service['restart'] = 'unless-stopped'
        service['logging'] = {'driver': 'json-file', 'options': {'max-size': '10m', 'max-file': '3'}}
    # Escape literal environment references for Compose; values never pass through a shell on the host.
    for s in services.values():
        if 'healthcheck' in s:
            s['healthcheck']['test'][-1] = s['healthcheck']['test'][-1].replace('$', '$$')
    write(COMPOSE, {'services': services, 'volumes': {name: {} for name in ['mysql', 'elastic', 'minio', 'kvrocks', 'nats', 'logs']}})
    return c


def bootstrap_admin():
    """v1.0.0-rc2 ignores ADMIN_DEFAULT_PASSWORD; rotate before publishing HTTPS."""
    marker = LOCAL / 'admin-initialized.json'
    if marker.exists():
        if read(marker).get('repoKey') != KEY:
            raise RuntimeError('管理员初始化记录归属错误')
        if read(marker).get('version') == 2:
            return
    cs = containers()
    app = next(x for x in cs if x['Config']['Labels']['dev.tfgm.service'] == 'ragflow')
    container_id = app['Id']
    keypath = GENERATED / 'login-public.pem'
    keypath.write_text(run(['docker', 'exec', container_id, 'cat', '/ragflow/conf/public.pem']).stdout)
    def encrypt(password):
        p = subprocess.run(['openssl', 'pkeyutl', '-encrypt', '-pubin', '-inkey', str(keypath), '-pkeyopt', 'rsa_padding_mode:pkcs1'],
                           input=base64.b64encode(password.encode()), capture_output=True, check=True)
        return base64.b64encode(p.stdout).decode()
    def request(path, data=None, token=None, method='POST', admin=True):
        # Pass auth and body on stdin, never in argv, logs or error messages.
        base = 'http://127.0.0.1:9381/api/v1/admin' if admin else 'http://127.0.0.1:9380/api/v1'
        options = {'url': base + path, 'request': method, 'header': 'Content-Type: application/json'}
        if data is not None: options['data'] = json.dumps(data)
        cfg = '\n'.join(k + ' = ' + json.dumps(v) for k, v in options.items()) + '\n'
        if token: cfg += 'header = ' + json.dumps('Authorization: ' + token) + '\n'
        p = subprocess.run(['docker', 'exec', '-i', container_id, 'curl', '-sS', '--max-time', '15', '-i', '--config', '-'], input=cfg, capture_output=True, text=True)
        if p.returncode: raise RuntimeError('管理员内部 API 请求失败')
        headers, body = p.stdout.split('\n\n', 1)
        response = json.loads(body)
        auth = next((line.split(':', 1)[1].strip() for line in headers.splitlines() if line.lower().startswith('authorization:')), None)
        return response, auth
    password = read(LOCAL / 'credentials.json')['admin']
    data, token = request('/login', {'email': 'admin@ragflow.io', 'password': encrypt(password)})
    if data.get('code') != 0:
        data, token = request('/login', {'email': 'admin@ragflow.io', 'password': encrypt('admin')})
        if data.get('code') != 0 or not token:
            raise RuntimeError('管理员初始化失败：本地凭据和初始账户均无法登录；入口保持关闭')
        data, _ = request('/users/admin%40ragflow.io/password', {'new_password': encrypt(password)}, token, 'PUT')
        if data.get('code') != 0:
            raise RuntimeError('管理员密码更新失败，入口保持关闭')
        data, token = request('/login', {'email': 'admin@ragflow.io', 'password': encrypt(password)})
    if data.get('code') != 0 or not token:
        raise RuntimeError('新管理员密码验证失败，入口保持关闭')
    # Superusers are deliberately excluded from normal workspace APIs in this release.
    credentials = read(LOCAL / 'credentials.json')
    if 'user' not in credentials:
        credentials.update(user=secrets.token_hex(24), user_email='developer@tfgm.local')
        write(LOCAL / 'credentials.json', credentials)
    email = credentials['user_email']
    login = {'email': email, 'password': encrypt(credentials['user'])}
    user, user_token = request('/auth/login', login, admin=False)
    if user.get('code') != 0:
        created, _ = request('/users', {'username': email, 'password': encrypt(credentials['user']), 'role': 'user'}, token)
        if created.get('code') != 0:
            raise RuntimeError('开发账户创建失败；已有同名账户时请核对本地凭据，不会重置其密码')
        user, user_token = request('/auth/login', login, admin=False)
    if user.get('code') != 0 or not user_token:
        raise RuntimeError('开发账户登录失败')
    for endpoint in ['/users/me/models', '/datasets', '/system/stats', '/chats']:
        result, _ = request(endpoint, token=user_token, method='GET', admin=False)
        if result.get('code') != 0 or result.get('data') is None:
            raise RuntimeError('开发账户无权读取工作区接口：' + endpoint)
        if endpoint == '/chats' and not isinstance(result['data'].get('chats'), list):
            raise RuntimeError('聊天列表接口缺少 chats 数据')
    write(marker, {'version': 2, 'repoKey': KEY, 'initializedAt': time.time()})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def status(c):
    result = {'state': 'stopped', 'repoKey': KEY, 'project': PROJECT, 'config': str(CONFIG), 'storage': storage(c), 'services': [], 'urls': [], 'tls': '自签证书 · 浏览器信任未验证'}
    if not c:
        return result
    try:
        verify_daemon(c)
        cs = containers()
        result['services'] = [{'id': x['Id'], 'service': x['Config']['Labels']['dev.tfgm.service'], 'status': x['State']['Status'], 'health': x['State'].get('Health', {}).get('Status')} for x in cs]
        running = [x for x in cs if x['State']['Running']]
        if not running:
            return result
        result['state'] = 'unhealthy'
        result['reason'] = '容器正在启动或依赖未就绪'
        if len(running) != 7 or any(x['State'].get('Health', {}).get('Status', 'healthy') != 'healthy' for x in running):
            return result
        proxy = next(x for x in cs if x['Config']['Labels']['dev.tfgm.service'] == 'https')
        published = proxy['NetworkSettings']['Ports']['443/tcp']
        port = int(published[0]['HostPort'])
        if port != c['actualPort'] or published[0]['HostIp'] != c['bindHost']:
            raise ValueError('实际发布端口与配置不一致')
        ctx = ssl.create_default_context(cafile=str(LOCAL / 'certs/cert.pem'))
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))
        url = f'https://127.0.0.1:{port}'
        for path in ['/', '/api/v1/system/healthz']:
            with opener.open(url + path, timeout=8) as r:
                if r.status != 200 or r.headers.get('X-TFGM-Instance') != KEY or r.url != url + path:
                    raise ValueError('HTTPS 实例或响应异常')
                body = r.read()
                if path != '/':
                    result['backend'] = json.loads(body)
                    if result['backend'].get('status') != 'ok':
                        raise ValueError('后端依赖健康状态异常')
        result.update(state='healthy', reason='HTTPS、首页、后端与依赖均已就绪', urls=[url, *[f'https://{ip}:{port}' for ip in c.get('lanIPs', [])]])
    except Exception as e:
        result.update(state='unhealthy', reason=str(e))
    return result


def color_enabled(env=None, tty=None, machine=False):
    env = os.environ if env is None else env
    if machine or 'NO_COLOR' in env or env.get('FORCE_COLOR') == '0':
        return False
    if env.get('FORCE_COLOR'):
        return True
    return (sys.stdout.isatty() if tty is None else tty) and env.get('TERM') != 'dumb'


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in s)


def render(kind, data=None, color=False, columns=None):
    columns = columns or shutil.get_terminal_size((80, 24)).columns
    def paint(s, n): return f'\033[{n}m{s}\033[0m' if color else s
    rule = paint('─' * min(76, columns), 2)
    lines = [rule, '  ' + paint('tfgm-knowledge · ' + ('开发命令' if kind == 'help' else '本地知识库'), 1), rule]
    def row(label, value, n=0):
        prefix = '  ' + label + ' ' * max(1, (16 if kind == 'help' else 12) - width(label))
        if width(prefix + str(value)) > columns:
            lines.extend(['  ' + paint(label, 2), '    ' + paint(str(value), n)])
        else:
            lines.append('  ' + paint(label + ' ' * max(1, (16 if kind == 'help' else 12) - width(label)), 36 if label.startswith('mode:') else 2) + paint(str(value), n))
    if kind == 'help':
        row('用法', 'bun run mode:<命令> [参数]')
        row('当前模式', 'RAGFlow：Docker；MCP：独立 Bun 服务')
        row('配置文件', CONFIG)
        for group, cmds in COMMANDS.items():
            lines.extend(['', '  ' + paint(group, 1)])
            for cmd, description in cmds.items(): row('mode:' + cmd, description, 36)
        lines.extend(['', '  常用操作', '    ' + paint('bun run mode:start', 36), '    ' + paint('bun run mode:clean --dry-run', 36), '    ' + paint('bun --silent run mode:health --json', 36)])
    elif kind == 'clean':
        row('清理模式', '只读预览' if data['dryRun'] else '维护完成')
        row('候选文件', len(data['candidates']))
        row('已回收', str(data['deletedBytes']) + ' 字节')
        row('保护范围', data['skipped'])
    else:
        healthy = data['state'] == 'healthy'
        row('运行状态', {'healthy': '● 运行正常', 'stopped': '○ 已停止', 'unhealthy': '⚠ 健康异常'}[data['state']], 32 if healthy else 33)
        row('当前模式', 'Docker · 本地开发')
        for i, url in enumerate(data['urls']): row('访问地址' if i == 0 else '局域网', url, 36)
        if data.get('reason'): row('健康检查', data['reason'], 32 if healthy else 33)
        lines.append('')
        row('TLS 证书', data['tls'], 33)
        row('证书文件', LOCAL / 'certs/cert.pem')
        row('容器状态', '，'.join(x['service'] + ':' + {'healthy':'健康','running':'运行中','starting':'启动中','unhealthy':'异常','exited':'已停止','created':'待启动','restarting':'重启中'}.get((x['health'] or x['status']) if x['status'] == 'running' else x['status'], '未获取') for x in data['services']) or '未启动')
        lines.append('')
        for name, label in [('project', '项目磁盘'), ('docker', 'Docker 磁盘')]:
            disk = data['storage'][name]
            row(label, '未获取' if 'unknown' in disk else f"{disk['usedPercent']}%（当前用户可用空间口径）" + (' · 与项目同盘' if disk.get('sameAsProject') else ''))
        row('缓存预算', f"{data['storage']['budget'] / 1024**3:.2f} GiB；当前管理器无下载缓存")
        row('维护策略', data['storage']['policy'])
        row('最近维护', data['storage']['last']['summary'])
        row('配置文件', CONFIG)
        row('仓库标识', KEY[:12])
    lines.extend([rule, '  ' + paint('bun run mode:start · bun run mode:logs · bun run mode:help', 36)])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=[x for group in COMMANDS.values() for x in group] + ['mcp-config'])
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--follow', action='store_true')
    args = parser.parse_args()
    if args.command == 'mcp-config':
        with lock():
            c = config()
            if c is None:
                port = 18000 + int(hashlib.sha256((KEY + '\0docker\0port\0https').encode()).hexdigest()[:8], 16) % 10000
                c = {'version':1, 'repoKey':KEY, 'docker':None, 'portBase':port, 'actualPort':port, 'bindHost':'0.0.0.0', 'storage':{'triggers':[75,85,92], 'exits':[70,78,85], 'temporaryDays':7, 'budgetFraction':.01, 'budgetCapBytes':2*1024**3}}
            c.setdefault('mcp', {'library':str(ROOT/'dist/offline/tfgm-library-r1'), 'bindHost':'0.0.0.0', 'portBase':18000+int(hashlib.sha256((KEY+'\0mcp\0https').encode()).hexdigest()[:8],16)%10000, 'logMaxBytes':10*1024**2, 'logBackups':3})
            write(CONFIG,c)
            print(json.dumps(c['mcp']))
        return 0
    if args.command.startswith('mcp:'):
        forwarded = [flag for flag,enabled in [('--json',args.json),('--dry-run',args.dry_run),('--follow',args.follow)] if enabled]
        return subprocess.call(['bun', str(ROOT/'scripts/mcp-mode.ts'), args.command.split(':',1)[1], *forwarded], cwd=ROOT)
    def emit(kind, data):
        print(json.dumps(data, ensure_ascii=False) if args.json else render(kind, data, color_enabled(machine=args.json)))
    def step(text): print('→ ' + text, file=sys.stderr)
    if args.command == 'help':
        emit('help', COMMANDS)
        return 0
    c = config()
    if args.command in ('status', 'health'):
        s = status(c)
        emit(args.command, s)
        return int(args.command == 'health' and s['state'] != 'healthy')
    if args.command == 'clean' and args.dry_run:
        emit('clean', clean(c, True))
        return 0
    if args.command == 'logs':
        if not c: raise RuntimeError('尚未初始化，请先运行 mode:start')
        verify_daemon(c)
        containers()
        return subprocess.call(['docker', 'compose', '-p', PROJECT, '-f', str(COMPOSE), 'logs', '--tail', '100', *(['--follow'] if args.follow else [])], stdout=sys.stderr if args.json else None)
    with lock():
        c = config()
        if args.command == 'clean':
            emit('clean', clean(c))
        elif args.command == 'stop':
            if c:
                verify_daemon(c)
                cs = containers()
                if cs:
                    run(['docker', 'stop', '--time', '30', *[x['Id'] for x in cs]], timeout=240)
            emit('status', status(c))
        elif args.command == 'start':
            if c:
                existing = status(c)
                if existing['state'] == 'healthy' and read(LOCAL / 'admin-initialized.json', {}).get('version') == 2:
                    emit('status', existing)
                    return 0
            c = prepare()
            containers()  # Verify ownership before any Compose mutation.
            if not (LOCAL / 'admin-initialized.json').exists():
                for item in containers():
                    if item['Config']['Labels']['dev.tfgm.service'] == 'https' and item['State']['Running']:
                        run(['docker', 'stop', item['Id']])
            admission(c)
            step('准备固定版本镜像（首次下载可能较慢）')
            p = subprocess.run(['docker', 'compose', '-p', PROJECT, '-f', str(COMPOSE), 'pull', '--quiet', '--policy', 'missing'], stdout=sys.stderr, stderr=sys.stderr)
            if p.returncode: raise RuntimeError('镜像拉取失败；已有数据和服务保留')
            admission(c)
            step('启动数据库、索引、对象存储与 RAGFlow')
            for attempt in range(32):
                result = compose('up', '-d', '--wait', '--wait-timeout', '600', 'ragflow', check=False, timeout=660)
                if result.returncode == 0:
                    step('初始化管理员与开发账户，验证工作区权限后开放 HTTPS')
                    bootstrap_admin()
                    result = compose('up', '-d', 'https', check=False, timeout=90)
                if result.returncode == 0:
                    break
                if any(x in result.stderr.lower() for x in ['address already in use', 'port is already allocated']):
                    if c['actualPort'] + 1 >= c['portBase'] + 32:
                        raise RuntimeError('候选端口已耗尽，原占用服务保持不变')
                    c['actualPort'] += 1
                    write(CONFIG, c)
                    c = prepare()
                else:
                    raise RuntimeError(result.stderr[-3000:])
            else: raise RuntimeError('32 个候选端口均不可用，未停止任何外部服务')
            step('等待 HTTPS 和后端就绪')
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                s = status(c)
                if s['state'] == 'healthy':
                    write(STATE, {'repoKey': KEY, 'containers': s['services'], 'healthyAt': time.time()})
                    try: clean(c)
                    except Exception as e: step('维护告警：' + str(e))
                    emit('status', status(c))
                    return 0
                time.sleep(3)
            if not args.json: emit('status', s)
            raise RuntimeError('就绪超时；运行 bun run mode:logs 排查，数据卷已保留')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Exception, KeyboardInterrupt) as e:
        if '--json' in sys.argv:
            print(json.dumps({'error': str(e)}, ensure_ascii=False))
        else:
            print('✗ ' + str(e) + '\n  排障：bun run mode:logs', file=sys.stderr)
        sys.exit(1)
