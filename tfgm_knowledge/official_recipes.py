"""Read TFGM's published recipe site, with explicit version isolation and lazy caching."""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import quote, parse_qs, urlsplit

from .ingest import fetch
from .player_pack import encoded, sha

SITE = 'https://wiki.terrafirmagreg.team/modern/recipe-book/'
LIMIT = 16 * 1024**2


def write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.download-')
    try:
        with os.fdopen(fd, 'wb') as stream: stream.write(encoded(data))
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def resource_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9_.-]+:[a-z0-9_./-]+', value):
        raise ValueError('无效的资源 ID')
    namespace, path = value.split(':', 1)
    if '..' in path.split('/') or '.' in path.split('/'):
        raise ValueError('资源 ID 不允许路径跳转')
    return namespace, path


def cache_write(root, path, raw):
    data = json.loads(raw)
    record = {'url': SITE + path, 'raw_sha256': sha(raw), 'data_sha256': sha(encoded(data)), 'data': data}
    write(Path(root) / 'cache' / (sha(path.encode()) + '.json'), record)
    return record


def sync(version, output):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version): raise ValueError('必须指定精确游戏版本')
    build_raw = fetch(SITE + 'build.json', LIMIT); build = json.loads(build_raw)
    bundles_raw = fetch(SITE + 'bundles.json', LIMIT); bundles = json.loads(bundles_raw)
    bundle = 'tfg-' + version
    if build.get('modpack') != version or bundle not in bundles.get('bundles', []):
        raise ValueError(f"官方当前提供 {build.get('modpack')}；拒绝当作 {version} 使用")
    if not re.fullmatch(r'[0-9a-f]+', build.get('contentHash', '')): raise ValueError('官方构建标识无效')
    root = Path(output) / (bundle + '-' + build['contentHash'])
    manifest_path = root / 'manifest.json'
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        if existing.get('build') != build: raise ValueError('已有快照与上游构建冲突')
        # Validate the existing bootstrap without silently rewriting it.
        client = OfficialRecipes(manifest_path, version, offline=True)
        client.get('bundle.json'); client.get('items/index.json'); client.get('items-lang/zh_cn.json')
        return manifest_path, existing
    paths = ['bundle.json', 'items/index.json', 'items-lang/zh_cn.json']
    records = {}
    for relative in paths:
        path = f'bundles/{bundle}/{relative}'
        records[relative] = cache_write(root, path, fetch(SITE + path, LIMIT))
    if json.loads(fetch(SITE + 'build.json', LIMIT)) != build: raise ValueError('下载期间官方站点版本变化，请重试')
    meta = records['bundle.json']['data']; catalog = records['items/index.json']['data']; labels = records['items-lang/zh_cn.json']['data']
    if meta.get('schema') != 2 or catalog.get('schema') != 1 or labels.get('schema') != 2:
        raise ValueError('不支持的官方索引 schema')
    manifest = {'schema':'tfgm-official-recipes/v1', 'game_version':version, 'bundle':bundle, 'build':build,
                'source_url':SITE, 'downloaded_at':datetime.now(timezone.utc).isoformat(),
                'declared_recipe_count':meta['recipeCount'], 'named_item_count':len(labels['items']),
                'indexed_item_count':sum(len(v) for k,v in catalog.items() if k!='schema' and isinstance(v,list)),
                'bootstrap_sha256':{key:value['data_sha256'] for key,value in records.items()},
                'coverage':'official site inventory; recipe details cached on demand, not a full offline mirror',
                'precision':'display data; omitted amounts and execution conditions remain unknown'}
    write(manifest_path, manifest)
    return manifest_path, manifest


class OfficialRecipes:
    def __init__(self, manifest, version, offline=False):
        self.path = Path(manifest); self.root = self.path.parent
        self.manifest = json.loads(self.path.read_text()); self.offline = offline
        if self.manifest.get('schema') != 'tfgm-official-recipes/v1' or self.manifest['game_version'] != version:
            raise ValueError('配方快照版本与请求版本不匹配')
        if self.manifest['bundle'] != 'tfg-' + version or self.manifest['source_url'] != SITE:
            raise ValueError('来源不是受支持的官方配方站')
        self.prefix = 'bundles/' + self.manifest['bundle'] + '/'

    def get(self, relative):
        if relative.startswith('/') or '..' in relative.split('/') or '\\' in relative: raise ValueError('不安全的数据路径')
        path = self.prefix + relative
        cached = self.root / 'cache' / (sha(path.encode()) + '.json')
        if cached.exists():
            record = json.loads(cached.read_text())
            expected = self.manifest['bootstrap_sha256'].get(relative, record['data_sha256'])
            if record['url'] != SITE + path or sha(encoded(record['data'])) != expected or record['data_sha256'] != expected:
                raise ValueError('缓存校验失败：' + relative)
            return record['data']
        if self.offline: raise ValueError('离线缓存未包含：' + relative)
        # The live site can replace a bundle: fail closed before and after every new read.
        if json.loads(fetch(SITE + 'build.json', LIMIT)) != self.manifest['build']:
            raise ValueError('官方站点构建已变化；拒绝混入旧快照，请重新同步')
        raw = fetch(SITE + path, LIMIT)
        if json.loads(fetch(SITE + 'build.json', LIMIT)) != self.manifest['build']:
            raise ValueError('读取期间官方构建变化，数据未写入缓存')
        return cache_write(self.root, path, raw)['data']

    def result(self, **data):
        return {'game_version':self.manifest['game_version'], 'source_build':self.manifest['build']['releaseTag'],
                'source_url':SITE, 'coverage':self.manifest['coverage'], **data}

    def search(self, query, limit=20):
        if not query.strip(): raise ValueError('搜索词不能为空')
        if not 1 <= limit <= 100: raise ValueError('limit 必须介于 1 和 100')
        needle = query.strip().casefold()
        items = self.get('items-lang/zh_cn.json')['items']
        matches = [x for x in items if needle in x.get('haystack', x['id']+' '+x['label']).casefold()]
        matches.sort(key=lambda x:(x['id'].casefold()!=needle and x['label'].casefold()!=needle, x['id']))
        return self.result(total=len(matches), items=[{'id':x['id'],'name':x['label']} for x in matches[:limit]])

    def find(self, item, direction='output', offset=0, limit=20):
        if direction not in ('input', 'output'): raise ValueError('direction 必须为 input 或 output')
        if offset < 0 or not 1 <= limit <= 100: raise ValueError('无效分页参数')
        namespace, path = resource_id(item)
        if path.startswith('/'): raise ValueError('物品 ID 路径不能以 / 开头')
        data = self.get('items/' + namespace + '/' + path + '.json')
        if data.get('schema') != 2: raise ValueError('不支持的物品索引 schema')
        pairs = sorted({(category, rid) for category, ids in data.get(direction+'s',{}).items() for rid in ids})
        return self.result(item=item, direction=direction, total=len(pairs), offset=offset,
                           recipes=[{'id':rid,'category':category} for category,rid in pairs[offset:offset+limit]],
                           matching='official item reverse index; not locally inferred from displayId')

    def recipe(self, rid):
        namespace, path = resource_id(rid)
        relative = 'recipes/' + namespace + '/' + path.replace('/', '_')
        raw = self.get(relative + '.json')
        if raw.get('schema') != 1 or raw.get('id') != rid: raise ValueError('配方 ID 或 schema 不匹配')
        widgets = raw['widgets']
        image_format = self.get('bundle.json').get('recipeImageFormat', 'png')
        if image_format not in ('png','webp'): raise ValueError('未知图片格式')
        return self.result(id=rid, category=raw['category'],
                           inputs=[w for w in widgets if w.get('role')=='input'],
                           outputs=[w for w in widgets if w.get('role')=='output'], raw=raw,
                           recipe_source_url=SITE+self.prefix+quote(relative+'.json',safe='/'),
                           image_url=SITE+self.prefix+quote(relative+'.'+image_format,safe='/'),
                           image_version_policy='live official link; may change with upstream deployment',
                           completeness='emi-display-only', route_calculation_supported=False,
                           unknown_fields=['omitted quantities','duration','energy','chance','additional execution conditions'])


def openapi(port=20260):
    version = {'name':'version','in':'query','required':True,'schema':{'type':'string'},'description':'Exact TFGM version; mismatches are rejected'}
    def operation(operation_id, parameters):
        return {'get':{'operationId':operation_id,'parameters':[version]+parameters,'responses':{'200':{'description':'Versioned official data','content':{'application/json':{'schema':{'type':'object'}}}},'400':{'description':'Invalid request, version mismatch, upstream unavailable or uncached offline resource'}}}}
    def parameter(name, required=False, default=None):
        schema = {'type':'integer' if name in ('offset','limit') else 'string'}
        if default is not None: schema['default']=default
        if name=='direction': schema['enum']=['input','output']
        return {'name':name,'in':'query','required':required,'schema':schema}
    return {'openapi':'3.0.3','info':{'title':'TFGM official recipe queries','version':'1.0.0','description':'Uses official preprocessed data. Does not calculate exact multi-step routes.'},
            'servers':[{'url':f'http://127.0.0.1:{port}'}], 'paths':{
                '/v1/status':operation('recipe_source_status',[]),
                '/v1/items':operation('search_items',[parameter('q',True),parameter('limit',default=20)]),
                '/v1/recipes':operation('find_recipes_or_uses',[parameter('item',True),parameter('direction',default='output'),parameter('offset',default=0),parameter('limit',default=20)]),
                '/v1/recipe':operation('get_recipe',[parameter('id',True)])}}


def serve(client, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path); args = parse_qs(parsed.query)
            def arg(name, default=None): return args.get(name,[default])[0]
            try:
                if parsed.path != '/openapi.json' and arg('version') != client.manifest['game_version']: raise ValueError('必须指定匹配的 version 参数')
                if parsed.path == '/openapi.json': data = openapi(self.server.server_port)
                elif parsed.path == '/v1/items': data = client.search(arg('q',''),int(arg('limit',20)))
                elif parsed.path == '/v1/recipes': data = client.find(arg('item',''),arg('direction','output'),int(arg('offset',0)),int(arg('limit',20)))
                elif parsed.path == '/v1/recipe': data = client.recipe(arg('id',''))
                elif parsed.path == '/v1/status': data = client.manifest
                else: self.send_error(404); return
                body=encoded(data); self.send_response(200)
            except Exception as exc:
                body=encoded({'error':str(exc)}); self.send_response(400)
            self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'Official recipe API: http://127.0.0.1:{server.server_port} (version required)',flush=True)
    try: server.serve_forever()
    finally: server.server_close()


def main():
    parser=argparse.ArgumentParser(description='TFGM 官方配方站同步与 Agent 查询')
    sub=parser.add_subparsers(dest='command',required=True)
    sync_parser=sub.add_parser('sync'); sync_parser.add_argument('--version',required=True); sync_parser.add_argument('--output',default='.local/official-recipes')
    for name in ('search','find','get','serve'):
        p=sub.add_parser(name);p.add_argument('--manifest',required=True);p.add_argument('--version',required=True);p.add_argument('--offline',action='store_true')
        if name=='search':p.add_argument('query');p.add_argument('--limit',type=int,default=20)
        if name=='find':p.add_argument('item');p.add_argument('--direction',choices=['input','output'],default='output');p.add_argument('--offset',type=int,default=0);p.add_argument('--limit',type=int,default=20)
        if name=='get':p.add_argument('id')
        if name=='serve':p.add_argument('--port',type=int,default=20260)
    args=parser.parse_args()
    try:
        if args.command=='sync':
            path,manifest=sync(args.version,args.output);print(json.dumps({'manifest':str(path),**manifest},ensure_ascii=False,indent=2));return
        client=OfficialRecipes(args.manifest,args.version,args.offline)
        if args.command=='serve':serve(client,args.port);return
        if args.command=='search':result=client.search(args.query,args.limit)
        elif args.command=='find':result=client.find(args.item,args.direction,args.offset,args.limit)
        else:result=client.recipe(args.id)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as exc:
        parser.exit(1,'ERROR: '+str(exc)+'\n')

if __name__=='__main__':main()
