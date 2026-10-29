import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { Ragflow } from './ragflow';
import { z } from 'zod';
import { KnowledgeLibrary } from '@tfgm/knowledge';
import { KnowledgeError, versionSchema } from '@tfgm/contracts';
const version = { version: versionSchema.describe('Exact game version from kb_status; never silently substitute another version') };
const limit = z.number().int().min(1).max(100).default(20);
const offset = z.number().int().min(0).default(0);
export function createMcpServer(kb: KnowledgeLibrary, ragflow?: Ragflow) {
  const server = new McpServer({ name: 'tfgm-knowledge', version: '0.1.0' });
  const register = (name: string, description: string, inputSchema: any, action: (args: any) => any, external = false) => {
    server.registerTool(name, { description, inputSchema, annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: external } }, async (args: any) => {
      try {
        const data = await action(args);
        if (data.image) return { content: [{ type: 'text' as const, text: JSON.stringify(data.metadata) }, data.image], structuredContent: data.metadata };
        const result = data.metadata ?? data;
        return { content: [{ type: 'text' as const, text: JSON.stringify(result) }], structuredContent: result };
      } catch (error) {
        const result = { code: error instanceof KnowledgeError ? error.code : 'QUERY_FAILED', message: error instanceof Error ? error.message : '查询失败', source_mode: external ? 'external_ragflow' : 'offline', ...(external ? {} : {snapshot_id: kb.snapshotId}) };
        return { isError: true, content: [{ type: 'text' as const, text: JSON.stringify(result) }], structuredContent: result };
      }
    });
  };
  register('kb_status','列出本地知识库版本、覆盖范围和快照。没有联网补查。',{},()=>({...kb.status(),external_retrieval:ragflow?.status()??{enabled:false}}));
  register('kb_search','按短关键词检索本地文档，返回摘要；未命中不代表游戏里不存在。',{...version,query:z.string().min(1).max(200),limit:z.number().int().min(1).max(20).default(5)},a=>kb.search(a.version,a.query,a.limit));
  register('kb_read_document','按记录 ID 分页读取全文及文档级媒体关联。',{...version,id:z.string().min(1).max(128),offset,length:z.number().int().min(1).max(12000).default(6000)},a=>kb.document(a.version,a.id,a.offset,a.length));
  register('kb_search_items','查询中文名称或物品 ID，区分流体、桶装与同名候选。',{...version,query:z.string().min(1).max(200),limit},a=>kb.items(a.version,a.query,a.limit));
  for (const [name,direction] of [['kb_find_recipes','output'],['kb_find_uses','input']] as const) register(name, direction==='output'?'按物品 ID 查询制作配方索引；使用 get_recipe 读取细节。':'按物品 ID 查询用途；支持分页。',{...version,item:z.string().min(1).max(512),offset,limit},a=>kb.find(a.version,a.item,direction,a.offset,a.limit));
  register('kb_get_recipe','读取配方槽位和图片资源。缺失数量不是 1；不计算完整生产路线。候选过长时读取 raw_resource。',{...version,id:z.string().min(1).max(1024),offset,limit:z.number().int().min(1).max(50).default(20)},a=>kb.recipe(a.version,a.id,a.offset,a.limit));
  register('kb_get_asset','读取包内图片或分页文本资源（包括原始配方和结构 JSON）。仅访问数据库内资源，不读取任意系统文件。',{...version,path:z.string().min(1).max(1024),offset,length:z.number().int().min(1).max(12000).default(6000)},a=>kb.asset(a.version,a.path,a.offset,a.length));
  if(ragflow?.config.enabled) register('kb_search_semantic','调用外部 RAGFlow 的指定版本数据集进行语义检索；不是离线查询，不保证对应本地快照。',{...version,query:z.string().min(1).max(1000),limit:z.number().int().min(1).max(10).default(5)},a=>ragflow.search(a.version,a.query,a.limit),true);
  return server;
}
