import argparse
import json
from pathlib import Path
import sys
from .player_pack import build_pack
from .ingest import import_pack

def main():
    p=argparse.ArgumentParser(description='版本化玩家知识包发布与 RAGFlow 导入')
    sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--bundle');b.add_argument('--revision',default='r1');b.add_argument('--output',default='dist/player-releases')
    i=sub.add_parser('import');i.add_argument('--url',required=True,help='HTTPS manifest URL，或本地 manifest.json');i.add_argument('--config',default='.local/ragflow.json');i.add_argument('--profile',choices=['preview','full'],default='preview');i.add_argument('--timeout',type=int,default=900);i.add_argument('--retry-failed',action='store_true')
    for name in ['query','evaluate']:
        q=sub.add_parser(name);q.add_argument('--config',default='.local/ragflow.json');q.add_argument('--report',required=True)
        if name=='query':q.add_argument('question')
        else:q.add_argument('--cases',default='evaluations/preview-0.13.17.json');q.add_argument('--output',default='dist/evaluation-preview')
    connect=sub.add_parser('connect');connect.add_argument('--config',default='.local/ragflow.json')
    a=p.parse_args()
    try:
        if a.command=='build':
            bundle=a.bundle or str(Path('dist')/json.loads(Path('dist/latest.json').read_text())['directory'])
            path,m=build_pack(bundle,a.output,a.revision);print(f'{path}/manifest.json：{len(m["documents"])} 篇文档')
        elif a.command=='connect':
            from .ragflow import Client
            from .ingest import save
            path=Path(a.config)
            if path.exists():
                Client.configured(path).call('GET','/datasets?page_size=1');print('已有连接有效：'+str(path));return
            client=Client.local_session('.')
            models,_=client.call('GET','/users/me/models')
            if not models.get('embd_id'):raise ValueError('请先在 RAGFlow 设置默认 embedding 模型')
            data,_=client.call('POST','/system/tokens',{})
            save(path,{'url':client.url.removesuffix('/api/v1'),'api_key':data['token'],'ca':str(Path('.local/certs/cert.pem').resolve()),'embedding_model':models['embd_id']})
            print('本地连接已保存：'+str(path))
        elif a.command in ('query','evaluate'):
            from .evaluate import retrieve,evaluate
            if a.command=='query':print(json.dumps(retrieve(a.config,json.loads(Path(a.report).read_text()),a.question),ensure_ascii=False,indent=2))
            else:
                result=evaluate(a.config,a.report,a.cases,a.output)
                print(f"Top-5 证据命中：{result['hits']}/{result['total']}")
                if result['hits']!=result['total']:sys.exit(2)
        else:import_pack(a.url,a.config,a.profile,a.timeout,a.retry_failed)
    except Exception as e:
        print('ERROR: '+str(e),file=sys.stderr);sys.exit(1)

if __name__=='__main__':main()
