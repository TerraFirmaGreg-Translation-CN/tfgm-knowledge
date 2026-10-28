"""Deterministic, source-attributed player documentation release artifacts."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

SCHEMA = 'tfgm-player-pack/v1'

def sha(data): return hashlib.sha256(data).hexdigest()
def encoded(value): return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()

def plain(text):
    text = re.sub(r'[&§][0-9a-fk-or]', '', str(text), flags=re.I)
    def macro(m):
        key = m[1]
        return {'tfg':'TerraFirmaGreg Modern','tfc':'群峦传说','br':'\n','br2':'\n\n','li':'\n- ','li2':'\n  - ', 'k:key.use':'使用键', 'k:key.sneak':'潜行键', 'k:key.attack':'攻击键'}.get(key, ('按键 ' + key[2:]) if key.startswith('k:') else '')
    text = re.sub(r'\$\(([^)]*)\)', macro, text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()

def player_text(record, quests):
    data = record.get('data') or {}
    if record['kind'] == 'quest':
        if data.get('missing_translation_keys'): return None
        q = data['localized']
        pieces = [q.get('subtitle', ''), *q.get('description', [])]
        tasks = []
        for task in q.get('tasks', []):
            item = task.get('item')
            item_id = item if isinstance(item, str) else (item or {}).get('id', '')
            title = task.get('title') or item_id or task.get('type', '')
            count = task.get('count')
            tasks.append('- ' + str(title) + (f'；物品 ID：{item_id}' if item_id and item_id != title else '') + (f'；任务要求数量：{count}' if count is not None else ''))
        if tasks: pieces += ['## 任务目标', '\n'.join(tasks)]
        deps = data.get('dependencies', [])
        if deps: pieces += ['## 前置任务', '\n'.join('- ' + plain(quests.get(d, d)) + f'（{d}）' for d in deps)]
        pieces += [f"任务 ID：{data['quest_id']}；章节：{data['chapter_file']}"]
        return plain('\n\n'.join(str(p) for p in pieces if p))
    if record['kind'] == 'field-guide':
        if '/entries/' not in record['source_path']: return None
        pages = []
        for page in data.get('pages', []):
            if page.get('anchor') == 'index': continue
            texts = [page[k] for k in ['text','text1','text2','description'] if isinstance(page.get(k),str)]
            if not texts: continue
            title = page.get('title') or page.get('name')
            pages.append(('## ' + str(title) + '\n\n' if title else '') + '\n\n'.join(texts))
        return plain('\n\n'.join(pages)) or None
    path = record['source_path']
    # Player installation/update notes only; no developer guides or historical changelogs.
    if record['source_id'] != 'wiki' or not any(x in path for x in ['/modpack/', '/upgrade-guides/from-0.12-to-0.13.md']): return None
    if path.endswith('/index.md'): return None
    text = re.sub(r'^---\n.*?\n---\n', '', record['text'], count=1, flags=re.S)
    return plain(text)

def build_pack(bundle, output, revision='r1', repository='TerraFirmaGreg-Translation-CN/tfgm-knowledge', media_site=None, media_source=None):
    bundle, output = Path(bundle), Path(output)
    source_manifest = json.loads((bundle/'manifest.json').read_text())
    version = source_manifest['modpack_version']
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}',version) or not re.fullmatch(r'r[1-9][0-9]*',revision): raise ValueError('Invalid game version or revision')
    package_id = f'tfgm-{version}-{revision}'
    with (bundle/'records.jsonl').open() as stream:
        records = [json.loads(line) for line in stream]
    media_files, media = {}, None
    if bool(media_site) != bool(media_source): raise ValueError('媒体附件和来源清单必须同时指定')
    if media_site:
        from .media import prepare_media
        media_files, media = prepare_media(bundle, records, media_site, media_source)
    selected = [r for r in records if r['language']=='zh_cn' and r['kind'] in ['quest','field-guide','document']]
    quests = {r['data']['quest_id']:r['title'] for r in selected if r['kind']=='quest'}
    files, documents, skipped, references = {}, [], [], []
    for r in sorted(selected,key=lambda r:r['id']):
        body = player_text(r,quests)
        relation = media['documents'].get(r['id']) if media else None
        if relation:
            body = (body or '') + '\n\n## 关联图示与配方\n\n'
            for item in relation['images']:
                body += f"第 {item['page']} 页：{item['caption']}；图片路径：{item['path']}\n\n"
            for item in relation['structures']:
                body += f"结构：{item['caption']}；结构记录：{item['id']}\n\n"
            if relation['recipes']: body += '同版本配方 ID：' + '、'.join(relation['recipes']) + '\n'
            if relation['unresolved_recipes']: body += '本次导出未解析的配方 ID：' + '、'.join(relation['unresolved_recipes']) + '\n'
        if not body:
            skipped.append(r['id']); continue
        if r['license'] == 'NOASSERTION':
            references.append({k:r[k] for k in ['title','source_url','commit','license','version_relation']})
            continue
        title = plain(r['title'])
        version_note = f"适用游戏版本：{version}" if r['version_relation']=='release-matched' else f"来源为独立快照，不能确认适用于 {version}，使用前需核对游戏版本"
        text = f"# {title}\n\n{version_note}\n语言：简体中文；资料类别：{r['kind']}\n\n{body}\n\n## 来源与适用范围\n\n来源：{r['source_url']}\n来源 commit：{r['commit']}\n许可证：{r['license']}\n记录 ID：{r['id']}\n\n本文由上游资料确定性整理，未由模型补写。任务目标数量不是合成配方用量；游戏内图示与配方需要在对应版本游戏中核实。\n"
        filename = r['id'] + '-' + re.sub(r'[^\w\u4e00-\u9fff-]','_', title)[:32] + '.md'
        path = 'documents/' + filename
        files[path] = text.encode()
        documents.append({k:r[k] for k in ['id','kind','source_id','source_url','source_path','commit','license','language','version_relation','applicable_modpack_version']} | {'title':title,'path':path,'sha256':sha(files[path]),'size':len(files[path])})
    if media:
        files.update(media_files)
        from .media import recipe_text
        for recipe in media['recipes'].values():
            rid = 'emi-' + sha(recipe['id'].encode())[:24]
            title = 'EMI 配方：' + recipe['id']
            path = 'documents/' + rid + '.md'
            files[path] = (f"# {title}\n\n适用游戏版本：{version}\n\n" + recipe_text(recipe) + f"\n\n来源：{media['source']['url']}\n来源文件：{recipe['source_path']}\n").encode()
            documents.append({'id':rid, 'kind':'recipe-display', 'title':title, 'path':path, 'sha256':sha(files[path]), 'size':len(files[path]), 'source_id':'field-guide-runtime', 'source_url':media['source']['url'], 'source_path':recipe['source_path'], 'commit':media['build'].get('field-guide-modern'), 'license':'upstream-asset-specific', 'language':'zh_cn', 'version_relation':'release-matched', 'applicable_modpack_version':version})
            media['documents'][rid] = {'images':[recipe['image']] if recipe['image'] else [], 'structures':[], 'recipes':[recipe['id']], 'unresolved_recipes':[]}
        files['media.json'] = encoded(media)
    # Selected broad subjects are a repeatable first-run preview, not a claim of full coverage.
    priority = ['营养素与口渴值','锻铁炉','蒸汽锅炉','耐火黏土','三级砧：锻铁','蒸汽时代矿石处理','赛特斯石英','高炉','木炭','黏土','陶器','食物腐烂','更新与重装整合包']
    if media: priority[8:8] = ['大桶','EMI 配方：tfc:barrel/limewater','EMI 配方：tfc:barrel/tannin','EMI 配方：tfc:crafting/barrel_rack']
    ordered = sorted(documents,key=lambda d:(next((i for i,t in enumerate(priority) if t in d['title']),999),d['kind']!='field-guide',d['id']))
    preview_ids = [d['id'] for d in ordered[:48]]
    files['documents.json'] = encoded(documents)
    files['references.json'] = encoded(references)
    files['sources.lock.json'] = (bundle/'sources.lock.json').read_bytes()
    files['NOTICE.md'] = (bundle/'NOTICE.md').read_bytes() + b'\nPlayer export: formatting and selection transformed; see documents.json for per-document attribution.\n'
    # Include upstream license texts already present in the locked raw bundle.
    for path in sorted((bundle/'raw').rglob('*')):
        if path.is_file() and re.match(r'^(LICENSE|COPYING|NOTICE)(\.|$)',path.name,re.I):
            files['licenses/' + path.relative_to(bundle/'raw').as_posix()] = path.read_bytes()
    release_dir = output/package_id
    release_dir.mkdir(parents=True,exist_ok=True)
    archive_name = package_id+'-zh_cn.zip'
    archive_path = release_dir/archive_name
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(files.items()):
            info = zipfile.ZipInfo(name,(2020,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            z.writestr(info,data)
    archive = buffer.getvalue()
    manifest = {'schema':SCHEMA,'package_id':package_id,'game_version':version,'revision':revision,'language':'zh_cn','source_build_id':source_manifest['build_id'],
                'archive':{'url':f'https://github.com/{repository}/releases/download/{package_id}/{archive_name}','sha256':sha(archive),'size':len(archive)},
                'documents':documents,'preview_ids':preview_ids,'excluded_records':len(skipped),'references_only':references,
                'retrieval':{'parser_id':'naive','parse_type':1,'chunk_token_num':512},
                'limitations':['仅中文玩家资料，不含源码和运行时完整配方','Wiki 独立快照不代表与游戏版本严格匹配','图示和多方块布局未重建','不包含模型或 API 密钥']}
    if media:
        manifest['media'] = {'path':'media.json', 'sha256':sha(files['media.json']), 'size':len(files['media.json']), 'assets':len(media['assets']), 'recipes':len(media['recipes']), 'structures':len(media['structures']), 'coverage':media['coverage'], 'distribution':'local-preview; asset license review pending'}
        manifest['limitations'] = ['配方仅为官方手册引用的 EMI 展示子集，不是完整执行定义', '未导出的数量、耗时、能耗和概率保持未知', '图片为原始资产；未执行视觉理解；结构仅保留原始 pattern/mapping', '媒体许可证尚未逐项审查，本版仅作本地预览']
    for path,data in [(archive_path,archive),(release_dir/'manifest.json',encoded(manifest))]:
        if path.exists() and path.read_bytes()!=data: raise ValueError('不可覆盖已有不同内容的知识包；请增加 revision')
        path.write_bytes(data)
    return release_dir,manifest
