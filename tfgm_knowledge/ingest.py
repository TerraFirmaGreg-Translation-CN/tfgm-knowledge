"""Verified release manifests -> isolated, resumable RAGFlow datasets."""
import contextlib
import fcntl
import io
import json
import os
import re
from pathlib import Path, PurePosixPath
import time
import urllib.parse
import urllib.request
import zipfile

from .player_pack import SCHEMA, sha, encoded
from .ragflow import Client

class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != 'https': raise ValueError('拒绝降级为非 HTTPS 的下载')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(url, limit):
    if urllib.parse.urlparse(url).scheme != 'https': raise ValueError('远程知识包必须使用 HTTPS')
    with urllib.request.build_opener(HTTPSOnly()).open(url,timeout=120) as r:
        data=r.read(limit+1)
    if len(data)>limit: raise ValueError('下载内容超过大小限制')
    return data

def validate_pack(manifest, archive):
    if manifest.get('schema') != SCHEMA: raise ValueError('不支持的知识包 schema')
    if not re.fullmatch(r'tfgm-[0-9]+(?:\.[0-9]+){2}-r[1-9][0-9]*',manifest.get('package_id','')):raise ValueError('知识包标识不合法')
    expected=manifest['archive']
    if not re.fullmatch(r'[0-9a-f]{64}',expected['sha256']) or not 0<expected['size']<=32*1024**2:raise ValueError('压缩包摘要或大小不合法')
    if len(archive)!=expected['size'] or sha(archive)!=expected['sha256']: raise ValueError('知识包 SHA256 或大小不匹配')
    docs=manifest['documents']
    if not docs or len(docs)>10000: raise ValueError('文档数量不合法')
    if len({d['id'] for d in docs})!=len(docs) or len({d['path'] for d in docs})!=len(docs): raise ValueError('重复文档标识或路径')
    contents={}
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        entries=z.infolist()
        if len({x.filename for x in entries})!=len(entries):raise ValueError('ZIP 内重复路径')
        if sum(x.file_size for x in entries)>64*1024**2:raise ValueError('解压后超过 64 MiB 限制')
        for x in entries:
            p=PurePosixPath(x.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in x.filename or (x.external_attr>>16)&0o170000==0o120000:raise ValueError('ZIP 包含不安全路径')
        for d in docs:
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',d['id']) or len(PurePosixPath(d['path']).parts)!=2 or any(ord(c)<32 or c=='"' for c in d['path']):raise ValueError('文档标识或路径不合法')
            if not d['path'].startswith('documents/') or not d['path'].endswith('.md') or d['size']>1024**2:raise ValueError('文档路径或大小不合法')
            value=z.read(d['path'])
            if len(value)!=d['size'] or sha(value)!=d['sha256']: raise ValueError('文档校验失败：'+d['id'])
            value.decode('utf-8')
            contents[d['id']]=value
        if json.loads(z.read('documents.json'))!=docs:raise ValueError('包内文档清单与发布清单不同')
    if not set(manifest['preview_ids'])<=set(contents):raise ValueError('预览引用了不存在的文档')
    return contents

def load_pack(location):
    if location.startswith('https://'):
        manifest=json.loads(fetch(location,8*1024**2)); archive=fetch(manifest['archive']['url'],32*1024**2)
    else:
        path=Path(location);manifest=json.loads(path.read_text())
        name=Path(urllib.parse.urlparse(manifest['archive']['url']).path).name
        archive=(path.parent/name).read_bytes()
    return manifest,validate_pack(manifest,archive)

def save(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=path.with_suffix('.tmp')
    with os.fdopen(os.open(tmp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600),'wb') as f:f.write(encoded(data))
    tmp.replace(path)

def listing(client,path,key=None):
    results=[]
    for page in range(1,1001):
        data,_=client.call('GET',path+f'?page={page}&page_size=100')
        rows=data[key] if key else data
        results.extend(rows)
        if len(rows)<100 or (key and len(results)>=data['total']):return results
    raise RuntimeError('分页超出限制')

def remote_content(client,dataset_id,document_id):
    request=urllib.request.Request(client.url+f'/datasets/{dataset_id}/documents/{document_id}',headers={'Authorization':'Bearer '+client.token})
    with client.opener.open(request,timeout=120) as r:return r.read(1024**2+1)

def import_pack(location,config_path,profile='preview',timeout=900,retry_failed=False):
    manifest,contents=load_pack(location) # No mutation before every checksum is verified.
    config=json.loads(Path(config_path).read_text());client=Client.configured(config_path)
    selected=[d for d in manifest['documents'] if profile=='full' or d['id'] in manifest['preview_ids']]
    if profile not in ('preview','full'):raise ValueError('未知导入范围')
    target=sha((client.url+'\0'+config['embedding_model']).encode())[:10]
    identity=manifest['package_id']+'-'+profile+'-'+manifest['archive']['sha256'][:10]
    name=identity+'-'+target
    state_dir=Path(config_path).parent/'imports';state_dir.mkdir(mode=0o700,exist_ok=True)
    with (state_dir/'import.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        matches=[d for d in listing(client,'/datasets') if d['name']==name]
        if len(matches)>1:raise RuntimeError('存在多个同名数据集，请人工检查')
        if matches:
            dataset=matches[0]
            if dataset['embedding_model']!=config['embedding_model']:raise RuntimeError('已有数据集模型不匹配')
        else:
            dataset,_=client.call('POST','/datasets',{'name':name,'embedding_model':config['embedding_model'],'language':'Chinese','permission':'me','parser_id':'naive','parse_type':1,'parser_config':{'chunk_token_num':512}})
        ds=dataset['id'];base=f'/datasets/{ds}/documents'
        report_path=state_dir/(identity+'-'+target+'.json')
        report={'package_id':manifest['package_id'],'archive_sha256':manifest['archive']['sha256'],'manifest_url':location,'profile':profile,'dataset_id':ds,'dataset_name':name,'embedding_model':config['embedding_model'],'expected_documents':len(selected),'ready':False,'documents':{}}
        save(report_path,report)
        remote=listing(client,base,'docs'); names={}
        for d in remote:
            if d['name'] in names:raise RuntimeError('远端存在同名重复文档，拒绝继续')
            names[d['name']]=d
        for i,document in enumerate(selected):
            filename=PurePosixPath(document['path']).name
            if filename in names:
                d=names[filename]
                if sha(remote_content(client,ds,d['id']))!=document['sha256']:raise RuntimeError('远端文档已被修改：'+filename)
            else:
                uploaded=client.upload(ds,filename,contents[document['id']])
                if len(uploaded)!=1:raise RuntimeError('上传响应不完整')
                d=uploaded[0]
            report['documents'][document['id']]={'document_id':d['id'],'name':filename,'title':document['title'],'source_url':document['source_url'],'sha256':document['sha256']}
            save(report_path,report)
            if (i+1)%12==0:print(f'文档已核对/上传：{i+1}/{len(selected)}',flush=True)
        expected={v['document_id'] for v in report['documents'].values()}
        rows=listing(client,base,'docs')
        if {d['id'] for d in rows}!=expected:raise RuntimeError('数据集含有知识包以外的文档，拒绝混入')
        failed=[d for d in rows if d['ingestion_status']=='FAILED']
        if failed and not retry_failed:raise RuntimeError('存在解析失败文档；检查模型后使用 --retry-failed')
        todo=[d['id'] for d in rows if d['ingestion_status'] in ('UNSTART','STOPPED') or (retry_failed and d['ingestion_status']=='FAILED')]
        for offset in range(0,len(todo),8):
            batch=todo[offset:offset+8]
            response,_=client.call('POST',base+'/parse',{'document_ids':batch})
            if response.get('success_count')!=len(batch):raise RuntimeError('部分解析任务未成功启动，重新运行可继续')
        deadline=time.monotonic()+timeout;previous=None;last=0
        while True:
            rows=listing(client,base,'docs'); counts={}
            for d in rows:counts[d['ingestion_status']]=counts.get(d['ingestion_status'],0)+1
            report.update(status_counts=counts,chunk_count=sum(d.get('chunk_count',0) for d in rows),updated_at=time.time())
            errors=[{'name':d['name'],'event':d.get('latest_ingestion_event'),'message':d.get('progress_msg')} for d in rows if d['ingestion_status']=='FAILED']
            report['errors']=errors
            complete=counts.get('COMPLETED',0)==len(expected) and len(rows)==len(expected)
            report['ready']=complete and all(d.get('chunk_count',0)>0 for d in rows)
            save(report_path,report)
            if counts!=previous or time.monotonic()-last>30:
                print('解析状态：'+json.dumps(counts,ensure_ascii=False),flush=True);previous=counts;last=time.monotonic()
            if errors:raise RuntimeError('解析失败，详细原因保存在 '+str(report_path))
            if complete:
                if not report['ready']:raise RuntimeError('部分文档解析完成但没有可检索分块')
                print('导入完成：'+ds+'；报告：'+str(report_path));return report,report_path
            if time.monotonic()>=deadline:raise RuntimeError('等待超时，任务继续运行；再次执行同一命令可恢复跟踪：'+str(report_path))
            time.sleep(3)
