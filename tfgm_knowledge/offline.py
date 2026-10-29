"""Build and query a self-contained knowledge library. Query paths never use the network."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tarfile
import tempfile
import zipfile

from .player_pack import encoded, sha
from .media import safe_path

SCHEMA = 'tfgm-offline-knowledge/v1'


def file_sha(path):
    with open(path, 'rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def create_tables(db):
    db.executescript('''
        CREATE TABLE resources(version TEXT,path TEXT,sha256 TEXT,data BLOB,PRIMARY KEY(version,path));
        CREATE TABLE items(version TEXT,id TEXT,name TEXT,PRIMARY KEY(version,id));
        CREATE TABLE recipes(version TEXT,id TEXT,category TEXT,path TEXT,image TEXT,PRIMARY KEY(version,id));
        CREATE TABLE documents(version TEXT,id TEXT,kind TEXT,title TEXT,text TEXT,source_url TEXT,recipe_id TEXT,PRIMARY KEY(version,id));
        CREATE VIRTUAL TABLE documents_fts USING fts5(title,text,version UNINDEXED,document_id UNINDEXED,tokenize='trigram');
        CREATE INDEX documents_version ON documents(version);
    ''')


def add_resource(db, version, path, data):
    path = safe_path(path)
    db.execute('INSERT INTO resources VALUES(?,?,?,?)', (version,path,sha(data),data))


def raw_resource(db, version, path):
    row = db.execute('SELECT sha256,data FROM resources WHERE version=? AND path=?',(version,path)).fetchone()
    if row is None: raise ValueError('知识包未收录资源：'+path)
    if sha(row['data']) != row['sha256']: raise ValueError('资源内容校验失败：'+path)
    return row['data']


def get_json(db, version, path): return json.loads(raw_resource(db,version,path))


def add_document(db, version, did, kind, title, text, url, recipe_id=None):
    db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)',(version,did,kind,title,text,url,recipe_id))
    db.execute('INSERT INTO documents_fts(title,text,version,document_id) VALUES(?,?,?,?)',(title,text,version,did))


def describe(value, names, depth=0):
    if depth > 12: return '嵌套候选见原始数据'
    kind = value.get('kind')
    if kind == 'list':
        entries = value.get('entries',[])
        return '任选一种：' + ' / '.join(describe(x,names,depth+1) for x in entries[:12]) + (f'；另有 {len(entries)-12} 个候选，完整列表见原始数据' if len(entries)>12 else '')
    identity = value.get('tag') if kind == 'tag' else value.get('id','未知对象')
    label = ('材料标签 #'+str(identity)) if kind=='tag' else names.get(identity,identity)
    amount = str(value['amountMb'])+' mB' if 'amountMb' in value else str(value['amount']) if 'amount' in value else '导出未注明数量'
    return f'{label}（{identity}）；{amount}'


def recipe_document(raw, names, version, image):
    outputs = [describe(w['interaction'],names) for w in raw['widgets'] if w.get('role')=='output']
    title = (' / '.join(outputs) or raw['id'])[:220] + ' 的配方'
    lines = [f'# {title}',f'游戏版本：{version}',f'配方 ID：{raw["id"]}',f'配方类别：{raw["category"]}']
    for role,label in [('input','输入槽位'),('output','输出槽位')]:
        lines += ['## '+label] + ['- '+describe(w['interaction'],names) for w in raw['widgets'] if w.get('role')==role]
    lines += [f'包内配方图片：{image}' if image else '上游未提供配方图片',
              '此记录来自官方 EMI 展示导出。未注明数量不是 1；耗时、能耗、概率和其他执行条件未完整导出。替代列表不是同时投入；材料标签的展示图标不是唯一原料。']
    return title,'\n\n'.join(lines)


def build(archive, source_path, output, player_manifest=None):
    source=json.loads(Path(source_path).read_text());version=source['game_version']
    if not re.fullmatch(r'\d+\.\d+\.\d+',version): raise ValueError('版本无效')
    if file_sha(archive)!=source['sha256']: raise ValueError('官方附件 SHA256 不匹配')
    output=Path(output)
    if output.exists(): raise ValueError('输出已存在；请指定新的知识库目录')
    output.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.offline-build-',dir=output.parent))
    db=None
    try:
        db=connect(staging/'knowledge.sqlite');db.execute('PRAGMA journal_mode=OFF');create_tables(db)
        count,total=0,0;seen=set();prefix='bundles/tfg-'+version+'/'
        # Stream the archive; never extract tar paths to the filesystem.
        with tarfile.open(archive,'r|gz') as tar:
            for member in tar:
                name=safe_path(member.name[2:] if member.name.startswith('./') else member.name)
                if member.isdir(): continue
                if not member.isfile() or name in seen: raise ValueError('附件含链接、特殊文件或重复路径')
                seen.add(name);total+=member.size
                if total>16*1024**3 or member.size>128*1024**2: raise ValueError('附件超出解压限制')
                if name in ('build.json','bundles.json') or name.startswith(prefix) or PurePosixPath(name).name.upper().startswith(('LICENSE','NOTICE','COPYING')):
                    data=tar.extractfile(member).read()
                    path=name[len(prefix):] if name.startswith(prefix) else '@site/'+name
                    add_resource(db,version,path,data);count+=1
                    if count%20000==0:print(f'已收录官方资源：{count}',flush=True)
        build_info=get_json(db,version,'@site/build.json')
        if build_info['modpack']!=version or build_info['releaseTag']!=source['release_tag']: raise ValueError('官方附件版本不匹配')
        bundle=get_json(db,version,'bundle.json')
        if bundle.get('schema')!=2: raise ValueError('未知配方包 schema')
        labels=get_json(db,version,'items-lang/zh_cn.json')
        names={r['id']:r['label'] for r in labels['items']}
        catalog=get_json(db,version,'items/index.json')
        for namespace,paths in catalog.items():
            if namespace=='schema':continue
            for path in paths:
                iid=namespace+':'+path;db.execute('INSERT INTO items VALUES(?,?,?)',(version,iid,names.get(iid,iid)))
        recipe_count=0;missing_images=[];fmt=bundle.get('recipeImageFormat','png')
        if fmt not in ('png','webp'):raise ValueError('未知配方图片格式')
        for row in db.execute("SELECT path,data FROM resources WHERE version=? AND path LIKE 'recipes/%.json' ORDER BY path",(version,)):
            raw=json.loads(row['data'])
            if raw.get('schema')!=1 or not isinstance(raw.get('widgets'),list):raise ValueError('未知配方 schema')
            image=row['path'][:-5]+'.'+fmt
            if not db.execute('SELECT 1 FROM resources WHERE version=? AND path=?',(version,image)).fetchone():missing_images.append(raw['id']);image=None
            db.execute('INSERT INTO recipes VALUES(?,?,?,?,?)',(version,raw['id'],raw['category'],row['path'],image))
            title,text=recipe_document(raw,names,version,image)
            add_document(db,version,'recipe-'+sha(raw['id'].encode())[:24],'recipe',title,text,source['url']+'#'+row['path'],raw['id'])
            recipe_count+=1
            if recipe_count%10000==0:print(f'已生成配方知识文档：{recipe_count}',flush=True)
        if recipe_count!=bundle['recipeCount']:raise ValueError(f'官方声明配方数与实际不一致：{recipe_count}/{bundle["recipeCount"]}')
        unresolved=[];indexes=0
        for row in db.execute("SELECT path,data FROM resources WHERE version=? AND path LIKE 'items/%.json'",(version,)):
            data=json.loads(row['data'])
            if data.get('schema')!=2 or not any(k in data for k in ('inputs','outputs')):continue
            indexes+=1
            for direction in ('inputs','outputs'):
                for ids in data.get(direction,{}).values():
                    for rid in ids:
                        if not db.execute('SELECT 1 FROM recipes WHERE version=? AND id=?',(version,rid)).fetchone():unresolved.append({'item_path':row['path'],'recipe_id':rid})
        if unresolved:raise ValueError(f'官方物品索引存在 {len(unresolved)} 个未收录配方引用')
        versions={version:{'source':source,'recipe_count':recipe_count,'declared_recipe_count':bundle['recipeCount'],'item_count':db.execute('SELECT count(*) FROM items').fetchone()[0],'item_reverse_indexes':indexes,'missing_recipe_images':missing_images}}
        if player_manifest:
            from .ingest import load_archive
            # Only local packages: build is reproducible and does not implicitly fetch.
            if str(player_manifest).startswith(('http://','https://')):raise ValueError('请先下载玩家包，再传入本地 manifest')
            manifest,blob=load_archive(str(player_manifest));pv=manifest['game_version']
            if pv==version:raise ValueError('本版暂不支持同版本玩家包覆盖官方配方包')
            with zipfile.ZipFile(__import__('io').BytesIO(blob)) as z:
                for member in z.infolist():
                    if member.is_dir():continue
                    add_resource(db,pv,member.filename,z.read(member))
                for doc in manifest['documents']:
                    add_document(db,pv,doc['id'],doc['kind'],doc['title'],z.read(doc['path']).decode(),doc['source_url'])
            versions[pv]={'source_package':manifest['package_id'],'archive_sha256':manifest['archive']['sha256'],'documents':len(manifest['documents']),'media':manifest.get('media')}
        db.commit()
        print('生成可移植 JSONL 文档全集……',flush=True)
        with (staging/'documents.jsonl').open('wb') as stream:
            for row in db.execute('SELECT * FROM documents ORDER BY version,id'):
                stream.write(json.dumps(dict(row),ensure_ascii=False,separators=(',',':')).encode()+b'\n')
        counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('documents','recipes','items','resources')}
        db.execute("INSERT INTO documents_fts(documents_fts) VALUES('optimize')");db.commit();db.close();db=None
        manifest={'schema':SCHEMA,'versions':versions,'counts':counts,'network_required_for_queries':False,'retrieval':'SQLite FTS5 trigram + short-term literal matching; no remote embeddings',
                  'limitations':['配方为官方展示数据；缺失参数保持未知','不同版本不能混用','不执行多步路线优化','图片与数据仅本地打包，未进行公开再发布许可审查'],
                  'files':{p.name:{'sha256':file_sha(p),'size':p.stat().st_size} for p in sorted(staging.iterdir())}}
        (staging/'manifest.json').write_bytes(encoded(manifest));staging.rename(output)
        return output,manifest
    except BaseException:
        if db is not None:db.close()
        shutil.rmtree(staging)
        raise


class Knowledge:
    def __init__(self, directory, version):
        self.root=Path(directory);self.manifest=json.loads((self.root/'manifest.json').read_text())
        if self.manifest.get('schema')!=SCHEMA or version not in self.manifest['versions']:raise ValueError('知识库未收录请求版本')
        self.version=version
        self.db=sqlite3.connect((self.root/'knowledge.sqlite').resolve().as_uri()+'?mode=ro',uri=True);self.db.row_factory=sqlite3.Row

    def close(self):self.db.close()
    def envelope(self, **data):return {'game_version':self.version,'offline':True,**data}

    def search(self, query, limit=10):
        if not query.strip() or not 1<=limit<=100:raise ValueError('搜索词或 limit 无效')
        terms=query.strip().split()
        if all(len(t)>=3 for t in terms):
            match=' AND '.join('"'+t.replace('"','""')+'"' for t in terms)
            rows=self.db.execute('''SELECT d.*,bm25(documents_fts) AS score FROM documents_fts JOIN documents d ON d.version=documents_fts.version AND d.id=documents_fts.document_id
                WHERE documents_fts MATCH ? AND documents_fts.version=? ORDER BY score LIMIT ?''',(match,self.version,limit)).fetchall()
        else:
            # instr uses literal input: %, _, quotes are not wildcard operators.
            rows=self.db.execute('SELECT * FROM documents WHERE version=? AND '+' AND '.join('instr(text,?)>0' for _ in terms)+' LIMIT ?',[self.version,*terms,limit]).fetchall()
        return self.envelope(results=[dict(r) for r in rows],method='local lexical search; not semantic embeddings')

    def items(self, query, limit=20):
        if not query or not 1<=limit<=100:raise ValueError('搜索词或 limit 无效')
        rows=self.db.execute('SELECT id,name FROM items WHERE version=? AND (instr(name,?)>0 OR instr(id,?)>0) ORDER BY name=? DESC,id LIMIT ?',(self.version,query,query,query,limit)).fetchall()
        return self.envelope(items=[dict(r) for r in rows])

    def find(self, item, direction='output', limit=20, offset=0):
        from .official_recipes import resource_id
        if direction not in ('input','output') or not 1<=limit<=100 or offset<0:raise ValueError('查询参数无效')
        namespace,path=resource_id(item)
        data=get_json(self.db,self.version,'items/'+namespace+'/'+path+'.json')
        matches=sorted({(category,rid) for category,ids in data.get(direction+'s',{}).items() for rid in ids})
        return self.envelope(item=item,direction=direction,total=len(matches),offset=offset,recipes=[{'id':rid,'category':category} for category,rid in matches[offset:offset+limit]])

    def recipe(self, rid):
        row=self.db.execute('SELECT * FROM recipes WHERE version=? AND id=?',(self.version,rid)).fetchone()
        if row is None:raise ValueError('当前版本未收录该配方')
        raw=get_json(self.db,self.version,row['path'])
        return self.envelope(id=rid,category=row['category'],raw=raw,image_resource=row['image'],
                             inputs=[w for w in raw['widgets'] if w.get('role')=='input'],outputs=[w for w in raw['widgets'] if w.get('role')=='output'],
                             precision='display-only; omitted amounts and execution conditions unknown')

    def document(self, did):
        row=self.db.execute('SELECT * FROM documents WHERE version=? AND id=?',(self.version,did)).fetchone()
        if row is None:raise ValueError('当前版本未收录该文档')
        result=dict(row)
        if self.db.execute("SELECT 1 FROM resources WHERE version=? AND path='media.json'",(self.version,)).fetchone():
            media=get_json(self.db,self.version,'media.json');result['media']=media['documents'].get(did,{})
        return self.envelope(document=result)

    def asset(self, path, output):
        value=raw_resource(self.db,self.version,safe_path(path));target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
        return self.envelope(path=str(target.resolve()),sha256=sha(value),size=len(value))


def verify(directory):
    root=Path(directory);manifest=json.loads((root/'manifest.json').read_text())
    if manifest.get('schema')!=SCHEMA:raise ValueError('未知知识包 schema')
    for name,info in manifest['files'].items():
        if safe_path(name)!=name or '/' in name:raise ValueError('无效文件名')
        path=root/name
        if path.stat().st_size!=info['size'] or file_sha(path)!=info['sha256']:raise ValueError('知识包文件校验失败：'+name)
    db=sqlite3.connect(root/'knowledge.sqlite')
    try:
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('数据库损坏')
    finally:db.close()
    return {'verified':True,**manifest['counts']}


def export_ragflow(directory, version, output, batch_size=500, revision_start=100):
    """Export text in bounded existing-importer-compatible shards; no embedding calls."""
    from .player_pack import SCHEMA as PLAYER_SCHEMA
    if not 1 <= batch_size <= 1000 or revision_start < 1:raise ValueError('分包参数无效')
    output=Path(output)
    if output.exists():raise ValueError('导出目录已存在')
    kb=Knowledge(directory,version);output.mkdir(parents=True)
    catalog={'schema':'tfgm-ragflow-shards/v1','game_version':version,'library_manifest_sha256':file_sha(Path(directory)/'manifest.json'),'shards':[],
             'note':'Text-only ingestion artifacts. Images, structures and exact data remain in the offline library. No API or embedding calls performed.'}
    try:
        cursor=kb.db.execute('SELECT * FROM documents WHERE version=? ORDER BY id',(version,))
        number=0
        while rows:=cursor.fetchmany(batch_size):
            revision='r'+str(revision_start+number);package_id=f'tfgm-{version}-{revision}';folder=output/package_id;folder.mkdir()
            documents=[];filename=package_id+'-zh_cn.zip';archive=folder/filename
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
                for row in rows:
                    path='documents/'+row['id']+'.md'
                    content=(row['text']+'\n\n来源：'+row['source_url']+'\n记录 ID：'+row['id']+'\n').encode()
                    doc={k:row[k] for k in ('id','kind','title','source_url')}
                    doc.update(path=path,sha256=sha(content),size=len(content),language='zh_cn',applicable_modpack_version=version)
                    z.writestr(path,content);documents.append(doc)
                z.writestr('documents.json',encoded(documents))
            manifest={'schema':PLAYER_SCHEMA,'package_id':package_id,'game_version':version,'revision':revision,'language':'zh_cn',
                      'archive':{'url':'https://offline.invalid/'+filename,'sha256':file_sha(archive),'size':archive.stat().st_size},
                      'documents':documents,'preview_ids':[d['id'] for d in documents[:8]],
                      'limitations':['本地导出，archive URL 仅为本地文件名占位，不是已发布下载链接','图像和精确数据位于配套离线知识库','不把未注明配方参数当作已知']}
            if manifest['archive']['size']>32*1024**2:raise ValueError('分包过大；请减小 batch-size')
            (folder/'manifest.json').write_bytes(encoded(manifest))
            catalog['shards'].append({'manifest':package_id+'/manifest.json','documents':len(documents),'sha256':file_sha(folder/'manifest.json')})
            number+=1
            if number%25==0:print(f'已导出 RAGFlow 文档分包：{number}',flush=True)
        (output/'catalog.json').write_bytes(encoded(catalog))
    finally:kb.close()
    return {'catalog':str(output/'catalog.json'),'shards':len(catalog['shards']),'documents':sum(s['documents'] for s in catalog['shards'])}


def pack(directory, output):
    root=Path(directory);verify(root);target=Path(output)
    if target.exists():raise ValueError('压缩包已存在')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
        for name in ('manifest.json','knowledge.sqlite','documents.jsonl'):z.write(root/name,name)
    receipt={'schema':SCHEMA,'archive':target.name,'sha256':file_sha(target),'size':target.stat().st_size,'manifest_sha256':file_sha(root/'manifest.json')}
    target.with_suffix(target.suffix+'.json').write_bytes(encoded(receipt))
    return receipt


def unpack(archive, receipt_path, output):
    receipt=json.loads(Path(receipt_path).read_text());target=Path(output)
    if target.exists():raise ValueError('安装目录已存在')
    if receipt.get('schema')!=SCHEMA or Path(archive).stat().st_size!=receipt['size'] or file_sha(archive)!=receipt['sha256']:raise ValueError('离线包摘要或大小不匹配')
    target.parent.mkdir(parents=True,exist_ok=True);staging=Path(tempfile.mkdtemp(prefix='.offline-install-',dir=target.parent))
    try:
        with zipfile.ZipFile(archive) as z:
            members=z.infolist()
            if len(members)!=3 or {m.filename for m in members}!={'manifest.json','documents.jsonl','knowledge.sqlite'}:raise ValueError('离线包文件清单不合法')
            if sum(m.file_size for m in members)>16*1024**3:raise ValueError('离线包解压大小超限')
            if sha(z.read('manifest.json'))!=receipt['manifest_sha256']:raise ValueError('manifest 摘要不匹配')
            for member in members:
                if (member.external_attr>>16)&0o170000==0o120000:raise ValueError('离线包包含符号链接')
                with z.open(member) as source,(staging/member.filename).open('wb') as dest:shutil.copyfileobj(source,dest,1024*1024)
        result=verify(staging);staging.rename(target);return {'library':str(target),**result}
    except BaseException:
        shutil.rmtree(staging);raise


def main():
    p=argparse.ArgumentParser(description='完整离线知识库构建与检索（查询不联网）');sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--archive',required=True);b.add_argument('--source',required=True);b.add_argument('--output',required=True);b.add_argument('--player-pack')
    v=sub.add_parser('verify');v.add_argument('--library',required=True)
    u=sub.add_parser('unpack');u.add_argument('--archive',required=True);u.add_argument('--receipt',required=True);u.add_argument('--output',required=True)
    e=sub.add_parser('export-ragflow');e.add_argument('--library',required=True);e.add_argument('--version',required=True);e.add_argument('--output',required=True);e.add_argument('--batch-size',type=int,default=500);e.add_argument('--revision-start',type=int,default=100)
    archive=sub.add_parser('pack');archive.add_argument('--library',required=True);archive.add_argument('--output',required=True)
    for name in ('search','items','find','recipe','document','asset'):
        q=sub.add_parser(name);q.add_argument('--library',required=True);q.add_argument('--version',required=True);q.add_argument('value')
        if name in ('search','items','find'):q.add_argument('--limit',type=int,default=10)
        if name=='find':q.add_argument('--direction',choices=['input','output'],default='output');q.add_argument('--offset',type=int,default=0)
        if name=='asset':q.add_argument('--output',required=True)
    a=p.parse_args();kb=None
    try:
        if a.command=='build':
            path,m=build(a.archive,a.source,a.output,a.player_pack);result={'path':str(path),**m['counts']}
        elif a.command=='verify':result=verify(a.library)
        elif a.command=='unpack':result=unpack(a.archive,a.receipt,a.output)
        elif a.command=='pack':result=pack(a.library,a.output)
        elif a.command=='export-ragflow':result=export_ragflow(a.library,a.version,a.output,a.batch_size,a.revision_start)
        else:
            kb=Knowledge(a.library,a.version)
            if a.command in ('search','items'):result=getattr(kb,a.command)(a.value,a.limit)
            elif a.command=='find':result=kb.find(a.value,a.direction,a.limit,a.offset)
            elif a.command=='asset':result=kb.asset(a.value,a.output)
            else:result=getattr(kb,a.command)(a.value)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as exc:p.exit(1,'ERROR: '+str(exc)+'\n')
    finally:
        if kb:kb.close()

if __name__=='__main__':main()
