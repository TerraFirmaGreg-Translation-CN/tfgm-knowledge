import { Database } from 'bun:sqlite';
import { createHash } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { bounds, KnowledgeError, manifestSchema, safePath, versionSchema } from '@tfgm/contracts';

type Doc = { version: string; id: string; kind: string; title: string; text: string; source_url: string; recipe_id: string | null; score?: number };
type Recipe = { version: string; id: string; category: string; path: string; image: string | null };
export const digest = (bytes: Uint8Array | string) => createHash('sha256').update(bytes).digest('hex');
function page(offset: number, limit: number, max = 100) {
  if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > max) throw new KnowledgeError('INVALID_PAGE', '分页参数无效');
}
function sliced(text: string, offset: number, length: number) {
  return { text: text.slice(offset, offset + length), offset, totalCharacters: text.length, nextOffset: offset + length < text.length ? offset + length : null };
}
function compact(value: any, depth = 0): any {
  if (depth > 8) return { truncated: true, reason: 'nested alternatives; read raw resource' };
  if (!value || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.slice(0, 10).map(v => compact(v, depth + 1));
  const out: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(value)) {
    out[key] = typeof field === 'string' && field.length > 1000 ? field.slice(0, 1000) : compact(field, depth + 1);
    if (Array.isArray(field) && field.length > 10) out[key + '_pagination'] = { total: field.length, returned: 10, truncated: true };
  }
  return out;
}
export class KnowledgeLibrary {
  readonly db: Database;
  readonly manifest;
  readonly snapshotId: string;
  readonly root: string;
  constructor(directory: string) {
    this.root = resolve(directory);
    const bytes = readFileSync(join(this.root, 'manifest.json'));
    this.manifest = manifestSchema.parse(JSON.parse(bytes.toString()));
    this.snapshotId = digest(bytes);
    const dbPath = join(this.root, 'knowledge.sqlite');
    if (statSync(dbPath).size !== this.manifest.files['knowledge.sqlite']?.size) throw new KnowledgeError('INTEGRITY_ERROR', '知识库大小与 manifest 不一致，请运行整库校验');
    this.db = new Database(dbPath, { readonly: true, strict: true });
    this.db.exec('PRAGMA query_only=ON');
    // Fail during startup if this SQLite build cannot use the existing FTS tokenizer.
    this.db.query('SELECT count(*) AS n FROM documents_fts WHERE documents_fts MATCH ?').get('"__tfgm_startup_check__"');
  }
  close() { this.db.close(); }
  version(version: string) {
    if (!versionSchema.safeParse(version).success || !this.manifest.versions[version]) throw new KnowledgeError('VERSION_NOT_AVAILABLE', `未收录版本 ${version}；可用版本：${Object.keys(this.manifest.versions).join('、')}`);
  }
  result(version: string, data: Record<string, unknown>) { this.version(version); return { game_version: version, snapshot_id: this.snapshotId, source_mode: 'offline', ...data }; }
  status() { return { snapshot_id: this.snapshotId, source_mode: 'offline', versions: this.manifest.versions, counts: this.manifest.counts, online_tools_enabled: false, retrieval: 'local lexical FTS5; not semantic embeddings' }; }
  search(version: string, query: string, limit = 5) {
    this.version(version); page(0, limit, 20);
    const terms = query.trim().split(/\s+/);
    if (!query.trim() || query.length > 200 || terms.length > 12) throw new KnowledgeError('INVALID_QUERY', '请输入不超过 200 字的短关键词');
    let rows: Doc[];
    if (terms.every(t => t.length >= 3)) {
      const match = terms.map(t => '"' + t.replaceAll('"', '""') + '"').join(' AND ');
      rows = this.db.query<Doc, [string, string, number]>(`SELECT d.*,bm25(documents_fts) AS score FROM documents_fts JOIN documents d ON d.version=documents_fts.version AND d.id=documents_fts.document_id WHERE documents_fts MATCH ? AND documents_fts.version=? ORDER BY score LIMIT ?`).all(match, version, limit);
    } else {
      rows = this.db.query<Doc, any>(`SELECT * FROM documents WHERE version=? AND ${terms.map(() => 'instr(text,?)>0').join(' AND ')} LIMIT ?`).all(version, ...terms, limit);
    }
    return this.result(version, { query, results: rows.map(({ text, ...r }) => ({ ...r, snippet: text.slice(0, bounds.snippet), truncated: text.length > bounds.snippet })), method: 'keyword search; read_document for complete evidence' });
  }
  document(version: string, id: string, offset = 0, length = 6000) {
    this.version(version); page(offset, length, bounds.page);
    const row = this.db.query<Doc, [string, string]>('SELECT * FROM documents WHERE version=? AND id=?').get(version, id);
    if (!row) throw new KnowledgeError('NOT_FOUND', '当前版本未收录该文档');
    const { text, ...meta } = row;
    let relation: unknown = null;
    if (this.db.query('SELECT 1 FROM resources WHERE version=? AND path=?').get(version, 'media.json')) {
      const media = JSON.parse(this.resource(version, 'media.json').toString());
      relation = compact(media.documents[id] ?? {});
    }
    return this.result(version, { document: { ...meta, ...sliced(text, offset, length), media: relation }, media_scope: 'document-level candidate associations; raw media.json retains full lists' });
  }
  items(version: string, query: string, limit = 20) {
    this.version(version); page(0, limit);
    if (!query.trim() || query.length > 200) throw new KnowledgeError('INVALID_QUERY', '物品查询词无效');
    const rows = this.db.query<{ id: string; name: string }, [string, string, string, string, number]>('SELECT id,name FROM items WHERE version=? AND (instr(name,?)>0 OR instr(id,?)>0) ORDER BY name=? DESC,id LIMIT ?').all(version, query, query, query, limit);
    return this.result(version, { items: rows, limit, coverage: this.manifest.versions[version] });
  }
  find(version: string, item: string, direction: 'input' | 'output', offset = 0, limit = 20) {
    this.version(version); page(offset, limit);
    if (!['input','output'].includes(direction) || !/^[a-z0-9_.-]+:[a-z0-9_./-]+$/.test(item)) throw new KnowledgeError('INVALID_ITEM', '物品或查询方向无效');
    const [namespace, path] = item.split(':');
    const data = JSON.parse(this.resource(version, `items/${namespace}/${safePath(path!)}.json`).toString());
    if (data.schema !== 2) throw new KnowledgeError('UNSUPPORTED_SCHEMA', '未知物品索引格式');
    const entries = new Map<string, { id: string; category: string }>();
    for (const [category, ids] of Object.entries(data[direction + 's'] ?? {}) as [string, string[]][]) for (const id of ids) entries.set(category + '\0' + id, { id, category });
    const rows = [...entries.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([,v]) => v);
    return this.result(version, { item, direction, total: rows.length, offset, nextOffset: offset + limit < rows.length ? offset + limit : null, recipes: rows.slice(offset, offset + limit) });
  }
  recipe(version: string, id: string, offset = 0, limit = 20) {
    this.version(version); page(offset, limit, 50);
    const row = this.db.query<Recipe, [string, string]>('SELECT * FROM recipes WHERE version=? AND id=?').get(version, id);
    if (!row) throw new KnowledgeError('NOT_FOUND', '当前版本精确配方表未收录该配方');
    const raw = JSON.parse(this.resource(version, row.path).toString());
    const widgets = raw.widgets as any[];
    return this.result(version, { id, category: row.category, slots: widgets.slice(offset, offset + limit).map(w => compact(w)), offset, totalSlots: widgets.length,
      nextOffset: offset + limit < widgets.length ? offset + limit : null, raw_resource: row.path, image_resource: row.image,
      precision: 'EMI display data; omitted quantities, duration, energy, chance and other conditions remain unknown', route_calculation_supported: false });
  }
  resource(version: string, path: string): Buffer {
    this.version(version); safePath(path);
    const row = this.db.query<{ sha256: string; data: Uint8Array }, [string, string]>('SELECT sha256,data FROM resources WHERE version=? AND path=?').get(version, path);
    if (!row) throw new KnowledgeError('NOT_FOUND', '当前版本未收录资源：' + path);
    const buffer = Buffer.from(row.data);
    if (digest(buffer) !== row.sha256) throw new KnowledgeError('INTEGRITY_ERROR', '资源摘要校验失败');
    return buffer;
  }
  asset(version: string, path: string, offset = 0, length = 6000) {
    page(offset, length, bounds.page);
    const bytes = this.resource(version, path);
    if (/\.(png|webp|jpe?g)$/i.test(path)) {
      if (bytes.length > bounds.assetBytes) throw new KnowledgeError('ASSET_TOO_LARGE', '图片超过 2 MiB 工具返回上限');
      const mime = bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])) ? 'image/png' : bytes.subarray(0,3).equals(Buffer.from([255,216,255])) ? 'image/jpeg' : bytes.toString('ascii',0,4)==='RIFF' && bytes.toString('ascii',8,12)==='WEBP' ? 'image/webp' : null;
      if (!mime) throw new KnowledgeError('UNSUPPORTED_ASSET', '图片签名与格式不受支持');
      return { metadata: this.result(version,{ path, sha256: digest(bytes), mime_type: mime, size: bytes.length }), image: { type: 'image' as const, mimeType: mime, data: bytes.toString('base64') } };
    }
    if (!/\.(json|md|txt)$/i.test(path)) throw new KnowledgeError('UNSUPPORTED_ASSET', '仅支持图像和文本资源');
    return { metadata: this.result(version,{ path, sha256: digest(bytes), ...sliced(new TextDecoder('utf-8',{fatal:true}).decode(bytes), offset, length) }) };
  }
}
