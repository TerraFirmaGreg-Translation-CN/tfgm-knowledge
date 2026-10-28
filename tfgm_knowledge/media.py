"""Version-checked Patchouli media and EMI widget exports (not complete recipes)."""
import html
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

from .player_pack import encoded, plain, sha


def safe_path(value):
    p = PurePosixPath(value)
    if not value or p.is_absolute() or '..' in p.parts or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('不安全的媒体路径')
    return p.as_posix()


def interaction_text(value):
    kind = value.get('kind')
    if kind == 'list':
        return '替代候选（不是同时投入）：' + ' / '.join(interaction_text(x) for x in value.get('entries', []))
    identity = ('标签 #' + value.get('tag', '')) if kind == 'tag' else value.get('id', '未知对象')
    if 'amountMb' in value:
        amount = str(value['amountMb']) + ' mB'
    elif 'amount' in value:
        amount = str(value['amount'])
    else:
        amount = '导出未注明数量'
    return identity + '；' + amount


def recipe_text(recipe):
    lines = [f"配方 ID：{recipe['id']}", f"配方类别：{recipe['category']}"]
    for role, label in [('input', '输入槽位'), ('output', '输出槽位')]:
        lines.append('## ' + label)
        for slot in recipe[role + 's']:
            lines.append('- ' + interaction_text(slot['interaction']))
    lines.append('这是同版本 EMI 展示导出，不是完整配方执行定义。未注明数量不能默认为 1；耗时、能耗、概率及其他未导出条件未知。标签展示物品不是唯一材料，多个槽位不能丢失或随意合并。')
    return '\n\n'.join(lines)


def prepare_media(bundle, records, site_path, source_path):
    source = json.loads(Path(source_path).read_text())
    archive = Path(site_path).read_bytes()
    if len(archive) > 64 * 1024**2 or sha(archive) != source['sha256']:
        raise ValueError('官方手册附件 SHA256 不匹配或过大')
    version = json.loads((Path(bundle) / 'manifest.json').read_text())['modpack_version']
    if source['game_version'] != version:
        raise ValueError('媒体来源版本与知识包不匹配')
    files, assets, structures, recipes, links, missing = {}, {}, {}, {}, {}, []
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        members = {}
        total = 0
        for member in tar.getmembers():
            name = safe_path(member.name[2:] if member.name.startswith('./') else member.name)
            if member.isdir():
                continue
            if not member.isfile() or name in members:
                raise ValueError('手册附件含链接、特殊文件或重复路径')
            total += member.size
            if total > 256 * 1024**2 or member.size > 16 * 1024**2:
                raise ValueError('手册附件解压大小超限')
            members[name] = member
        # Read in archive order once: random seeks in gzip would repeatedly decompress it.
        payloads = {name:tar.extractfile(member).read() for name,member in members.items() if name.endswith(('.png','.json'))}
        def read(name):
            return payloads[safe_path(name)]
        build = json.loads(read('build.json'))
        if build.get('modpack') != version or build.get('releaseTag') != source['release_tag']:
            raise ValueError('手册 build.json 版本或发布标签不匹配')
        def asset(name, caption):
            name = safe_path(name)
            if name not in members:
                missing.append({'kind': 'image', 'path': name}); return None
            data = read(name)
            if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                missing.append({'kind': 'unsupported-image', 'path': name}); return None
            path = 'assets/' + sha(data) + '.png'
            files[path] = data
            assets.setdefault(path, {'path': path, 'sha256': sha(data), 'size': len(data), 'mime_type': 'image/png', 'origin_paths': [], 'source_archive': source['url'], 'source_archive_sha256': source['sha256']})
            if name not in assets[path]['origin_paths']: assets[path]['origin_paths'].append(name)
            return {'path': path, 'caption': caption, 'origin_path': name}
        for name in sorted(members):
            if not name.startswith('emi/recipes/') or not name.endswith('.json'): continue
            raw = json.loads(read(name))
            if raw.get('schema') != 1 or not isinstance(raw.get('widgets'), list):
                raise ValueError('不支持的 EMI 展示导出 schema')
            rid = raw['id']
            if rid in recipes: raise ValueError('重复配方 ID')
            image = asset(name[:-5] + '.png', rid + ' 的 EMI 配方图')
            recipe = {'id': rid, 'game_version': version, 'category': raw['category'],
                      'source_path': name, 'source_archive': source['url'], 'source_archive_sha256': source['sha256'],
                      'inputs': [w for w in raw['widgets'] if w.get('role') == 'input'],
                      'outputs': [w for w in raw['widgets'] if w.get('role') == 'output'],
                      'image': image, 'completeness': 'emi-display-only',
                      'unknown_fields': ['omitted amounts', 'duration', 'energy', 'chance', 'additional execution conditions'], 'raw': raw}
            recipes[rid] = recipe
        for record in records:
            if record['kind'] != 'field-guide' or record['language'] != 'zh_cn' or '/entries/' not in record['source_path']: continue
            relation = {'images': [], 'structures': [], 'recipes': [], 'unresolved_recipes': []}
            for page_number, page in enumerate((record.get('data') or {}).get('pages', []), 1):
                caption = plain(page.get('text') or page.get('title') or f'手册第 {page_number} 页')
                for resource in page.get('images', []):
                    if ':' not in resource: continue
                    namespace, path = resource.split(':', 1)
                    image = asset('assets/' + namespace + '/' + path, caption)
                    if image: relation['images'].append({**image, 'page': page_number})
                blocks = ([page['multiblock']] if 'multiblock' in page else []) + page.get('multiblocks', [])
                for variant, block in enumerate(blocks):
                    sid = f"{record['id']}-{page_number}-{variant}"
                    path = 'structures/' + sid + '.json'
                    structure = {'id': sid, 'path': path, 'document_id': record['id'], 'page': page_number, 'variant': variant,
                                 'caption': caption, 'source_url': record['source_url'], 'commit': record['commit'],
                                 'game_version': version, 'raw': block,
                                 'interpretation': '原始 Patchouli pattern/mapping；保留层与字符顺序，不推断世界坐标、方向或未定义字符'}
                    files[path] = encoded(structure)
                    structures[sid] = structure
                    relation['structures'].append({'id': sid, 'path': path, 'caption': caption, 'page': page_number})
                for key in ('recipe', 'recipe2'):
                    rid = page.get(key)
                    if not isinstance(rid, str): continue
                    target = 'recipes' if rid in recipes else 'unresolved_recipes'
                    if rid not in relation[target]: relation[target].append(rid)
            if any(relation.values()): links[record['id']] = relation
    for rid, recipe in recipes.items():
        recipe['path'] = 'recipes/' + sha(rid.encode())[:24] + '.json'
        files[recipe['path']] = encoded(recipe)
    index = {'schema': 'tfgm-media/v1', 'game_version': version, 'source': source, 'build': build,
             'coverage': 'official field-guide referenced subset; not all modpack recipes',
             'assets': sorted(assets.values(), key=lambda a: a['path']), 'structures': structures,
             'recipes': recipes, 'documents': links, 'missing': missing}
    files['media.json'] = encoded(index)
    files['preview.html'] = preview(index, records).encode()
    return files, index


def image_reference(image, index, directory=None):
    """Prefer official HTTP links; keep the immutable snapshot hash and local fallback."""
    from urllib.parse import quote
    result = dict(image)
    asset = next(a for a in index['assets'] if a['path'] == image['path'])
    origin = image.get('origin_path') or asset['origin_paths'][0]
    official_release = 'https://github.com/TerraFirmaGreg-Team/Field-Guide-Modern/releases/download/'
    if index['source']['url'].startswith(official_release):
        result['url'] = 'https://wiki.terrafirmagreg.team/modern/field-guide/' + quote(safe_path(origin), safe='/')
        result['url_version_policy'] = 'live upstream URL; may change after site update; sha256 identifies the verified snapshot'
    result.update(sha256=asset['sha256'], source_archive=asset['source_archive'], game_version=index['game_version'])
    if directory is not None: result['local_path'] = str(Path(directory) / image['path'])
    return result


def preview(index, records, layered=False, remote_images=False):
    """Offline overview: original images, raw structure layers, and exact recipe fields."""
    escape = html.escape
    def image_path(image):
        reference = image_reference(image, index) if remote_images else image
        return escape(reference.get('url', image['path']), quote=True)
    out = ['<!doctype html><meta charset="utf-8"><title>TFGM 图文与配方预览</title>',
           '<style>body{max-width:1100px;margin:40px auto;padding:0 24px;font:16px/1.7 system-ui;background:#15191f;color:#e6edf3}img{max-width:100%;image-rendering:pixelated;background:#ddd;padding:12px}pre{overflow:auto;background:#222a33;padding:16px}.layers{display:flex;gap:12px;flex-wrap:wrap}.layer{border-collapse:collapse}.layer td{border:1px solid #677584;min-width:30px;height:30px;text-align:center}.block{background:#3c6575}section{border-top:1px solid #465363;margin:32px 0}a{color:#81c7ff}details{margin:16px 0}</style>',
           '<h1>TFGM ' + escape(index['game_version']) + ' 图文与配方预览</h1>',
           '<p>图片为官方附件原图；结构展示保留原始层序，不推断朝向。配方仅覆盖手册引用子集，未导出的数量和条件保持未知。</p>']
    titles = {r['id']: r['title'] for r in records}
    for did, relation in index['documents'].items():
        if titles.get(did) not in ['高炉', '大桶']: continue
        out.append('<section><h2>' + escape(titles[did]) + '</h2>')
        for image in relation['images']:
            out.append('<figure><img src="' + image_path(image) + '"><figcaption>' + escape(image['caption']) + '</figcaption></figure>')
        for structure in relation['structures']:
            raw = index['structures'][structure['id']]['raw']
            if not layered:
                out.append('<details><summary>' + escape(structure['caption']) + '</summary><pre>' + escape(json.dumps(raw, ensure_ascii=False, indent=2)) + '</pre></details>')
                continue
            out.append('<details><summary>' + escape(structure['caption']) + '</summary><p>原始数组层序；字符 0 和空格保留原样，未映射字符不推断含义。</p><div class=layers>')
            for number, layer in enumerate(raw.get('pattern', []), 1):
                out.append('<div>层索引 ' + str(number) + '<table class=layer>')
                for row in layer:
                    out.append('<tr>' + ''.join('<td class="' + ('block' if c in raw.get('mapping', {}) else '') + '" title="' + escape(str(raw.get('mapping', {}).get(c, '未映射字符')), quote=True) + '">' + escape(c) + '</td>' for c in row) + '</tr>')
                out.append('</table></div>')
            out.append('</div><pre>' + escape(json.dumps(raw, ensure_ascii=False, indent=2)) + '</pre></details>')
        out.append('</section>')
    out.append('<section><h2>同版本 EMI 配方子集（' + str(len(index['recipes'])) + ' 条）</h2>')
    for recipe in index['recipes'].values():
        out.append('<details><summary>' + escape(recipe['id']) + '</summary>')
        if recipe['image']: out.append('<img src="' + image_path(recipe['image']) + '">')
        out.append('<pre>' + escape(recipe_text(recipe)) + '</pre></details>')
    result = '\n'.join(out) + '</section>'
    if not layered:
        result = result.replace('.layers{display:flex;gap:12px;flex-wrap:wrap}.layer{border-collapse:collapse}.layer td{border:1px solid #677584;min-width:30px;height:30px;text-align:center}.block{background:#3c6575}', '')
    return result


def query_recipes(index, recipe_id=None, item=None, direction='output'):
    if direction not in ('input', 'output'): raise ValueError('方向必须为 input 或 output')
    def matches(value):
        return value.get('id') == item or value.get('tag') == item or any(matches(x) for x in value.get('entries', []))
    return [r for r in index['recipes'].values() if (recipe_id is None or r['id'] == recipe_id) and
            (item is None or any(matches(w['interaction']) for w in r[direction + 's']))]


def validate_media(manifest, archive):
    """Validate all sidecar references before importer performs any remote mutation."""
    import zipfile
    info = manifest.get('media')
    if not info: return None
    if info['path'] != 'media.json' or info['size'] > 16 * 1024**2:
        raise ValueError('媒体索引路径或大小不合法')
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        data = z.read('media.json')
        if len(data) != info['size'] or sha(data) != info['sha256']: raise ValueError('媒体索引校验失败')
        index = json.loads(data)
        if index.get('schema') != 'tfgm-media/v1' or index['game_version'] != manifest['game_version'] or index['build']['modpack'] != manifest['game_version']:
            raise ValueError('媒体版本不匹配')
        assets = {}
        for asset in index['assets']:
            path = asset['path']
            if not re.fullmatch(r'assets/[0-9a-f]{64}\.png', path) or path in assets: raise ValueError('媒体资源路径重复或不合法')
            value = z.read(path)
            if len(value) != asset['size'] or sha(value) != asset['sha256'] or not value.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('图片校验失败')
            assets[path] = asset
        paths = set(assets)
        for kind in ('structures', 'recipes'):
            for key, record in index[kind].items():
                path = safe_path(record['path'])
                if len(PurePosixPath(path).parts) != 2 or not path.startswith(kind + '/') or not path.endswith('.json') or path in paths:
                    raise ValueError('结构或配方路径不合法')
                paths.add(path)
                if record['id'] != key or record['game_version'] != manifest['game_version'] or json.loads(z.read(path)) != record:
                    raise ValueError('结构或配方内容与索引不一致')
                if kind == 'recipes' and record.get('image') and record['image']['path'] not in assets: raise ValueError('配方引用不存在的图片')
        doc_ids = {d['id'] for d in manifest['documents']}
        for did, relation in index['documents'].items():
            if did not in doc_ids: raise ValueError('媒体关联不存在的文档')
            if any(x['path'] not in assets for x in relation['images']): raise ValueError('文档引用不存在的图片')
            if any(x['id'] not in index['structures'] or x['path'] != index['structures'][x['id']]['path'] for x in relation['structures']): raise ValueError('文档引用不存在的结构')
            if any(x not in index['recipes'] for x in relation['recipes']): raise ValueError('文档引用不存在的配方')
    return index


def cache_media(manifest, archive, directory):
    import zipfile
    index = validate_media(manifest, archive)
    if index is None: return None
    directory = Path(directory).resolve() / manifest['archive']['sha256']
    directory.mkdir(parents=True, exist_ok=True)
    paths = ['media.json'] + [a['path'] for a in index['assets']] + [r['path'] for kind in ('structures', 'recipes') for r in index[kind].values()]
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        for path in paths:
            target = directory / path
            if target.is_symlink() or target.parent.is_symlink(): raise ValueError('媒体缓存路径不能是符号链接')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(path))
    return directory
