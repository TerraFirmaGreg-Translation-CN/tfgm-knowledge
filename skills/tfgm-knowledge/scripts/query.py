#!/usr/bin/env python3
"""Locate the installed offline library and delegate read-only queries to its CLI."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    p=argparse.ArgumentParser(description='TFGM Skill 离线查询入口')
    p.add_argument('--repo');p.add_argument('--library')
    p.add_argument('command',choices=['status','search','items','find','recipe','document','asset'])
    args,rest=p.parse_known_args()
    skill=Path(__file__).resolve().parents[1]
    settings_path=skill/'settings.json'
    settings=json.loads(settings_path.read_text()) if settings_path.exists() else {}
    repo=args.repo or os.environ.get('TFGM_KNOWLEDGE_REPO') or settings.get('repo')
    if repo is None:
        candidates=[skill.parent.parent,*Path.cwd().parents,Path.cwd(),Path.cwd()/'tfgm-knowledge']
        repo=next((str(x) for x in candidates if (x/'tfgm_knowledge/offline.py').is_file()),None)
    if not repo or not (Path(repo).expanduser()/'tfgm_knowledge/offline.py').is_file():p.exit(1,'未找到知识库代码；请设置 --repo 或 TFGM_KNOWLEDGE_REPO\n')
    repo=Path(repo).expanduser().resolve()
    library=Path(args.library or os.environ.get('TFGM_KNOWLEDGE_LIBRARY') or settings.get('library') or repo/'dist/offline/tfgm-library-r1').expanduser().resolve()
    if not (library/'manifest.json').is_file() or not (library/'knowledge.sqlite').is_file():p.exit(1,'未找到离线知识包；请设置 --library 或 TFGM_KNOWLEDGE_LIBRARY\n')
    manifest=json.loads((library/'manifest.json').read_text())
    if manifest.get('schema')!='tfgm-offline-knowledge/v1':p.exit(1,'知识包 schema 不受支持\n')
    if args.command=='status':
        if rest:p.error('status 不接受其他参数')
        print(json.dumps({'repository':str(repo),'library':str(library),'versions':manifest['versions'],'counts':manifest['counts'],'network_required_for_queries':False,'retrieval':manifest.get('retrieval')},ensure_ascii=False,indent=2))
        return
    sys.path.insert(0,str(repo))
    from tfgm_knowledge.offline import main as query
    sys.argv=[sys.argv[0],args.command,'--library',str(library),*rest]
    query()


if __name__=='__main__':main()
