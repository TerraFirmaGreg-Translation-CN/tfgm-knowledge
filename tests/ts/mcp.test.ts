import { test, expect, afterAll } from 'bun:test';
import { Database } from 'bun:sqlite';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { KnowledgeLibrary, digest } from '../../packages/knowledge/src';
import { createHandler } from '../../apps/mcp-server/src/http';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
const root=mkdtempSync(join(tmpdir(),'tfgm-test-'));
const db=new Database(join(root,'knowledge.sqlite'));
db.exec(`CREATE TABLE documents(version,id,kind,title,text,source_url,recipe_id); CREATE VIRTUAL TABLE documents_fts USING fts5(title,text,version UNINDEXED,document_id UNINDEXED,tokenize='trigram'); CREATE TABLE resources(version,path,sha256,data); CREATE TABLE items(version,id,name); CREATE TABLE recipes(version,id,category,path,image);`);
for(const version of ['0.13.15','0.13.17']) {
 db.query('INSERT INTO documents VALUES(?,?,?,?,?,?,?)').run(version,'doc','guide','石灰水','石灰水 '+version+' % literal','https://example.org',null);
 db.query('INSERT INTO documents_fts VALUES(?,?,?,?)').run('石灰水','石灰水 '+version+' % literal',version,'doc');
}
function resource(path:string,data:Buffer){db.query('INSERT INTO resources VALUES(?,?,?,?)').run('0.13.15',path,digest(data),data)}
resource('items/tfc/limewater.json',Buffer.from(JSON.stringify({schema:2,outputs:{mixer:['r1','r2']},inputs:{}})));
resource('recipes/r1.json',Buffer.from(JSON.stringify({widgets:[{type:'slot',content:{id:'tfc:flux'}},{type:'fluid',amount:500}]})));
resource('image.png',Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9WQAAAAASUVORK5CYII=','base64'));
db.query('INSERT INTO recipes VALUES(?,?,?,?,?)').run('0.13.15','r1','mixer','recipes/r1.json','image.png');
db.query('INSERT INTO resources VALUES(?,?,?,?)').run('0.13.15','bad.txt','0'.repeat(64),Buffer.from('bad'));
db.close();const bytes=readFileSync(join(root,'knowledge.sqlite'));
writeFileSync(join(root,'manifest.json'),JSON.stringify({schema:'tfgm-offline-knowledge/v1',versions:{'0.13.15':{},'0.13.17':{}},counts:{documents:2},files:{'knowledge.sqlite':{sha256:digest(bytes),size:bytes.length}},network_required_for_queries:false}));
const kb=new KnowledgeLibrary(root);
afterAll(()=>{kb.close();rmSync(root,{recursive:true,force:true})});
test('version isolation and literal keyword matching',()=>{
 const result=kb.search('0.13.15','石灰水') as any;
 expect(result.results).toHaveLength(1);expect(result.results[0].snippet).toContain('0.13.15');
 expect((kb.search('0.13.17','%') as any).results).toHaveLength(1);
 expect(()=>kb.search('0.13.16','石灰水')).toThrow('未收录版本');
 expect(()=>kb.recipe('0.13.17','r1')).toThrow('未收录');
 expect(()=>kb.db.exec('DELETE FROM documents')).toThrow();
});
test('pagination, unknown amounts, integrity and path boundaries',()=>{
 const result=kb.find('0.13.15','tfc:limewater','output',0,1) as any;
 expect(result.total).toBe(2);expect(result.nextOffset).toBe(1);
 expect((kb.recipe('0.13.15','r1') as any).slots[0].content.amount).toBeUndefined();
 expect((kb.document('0.13.15','doc',0,3) as any).document.nextOffset).toBe(3);
 expect(()=>kb.asset('0.13.15','../token')).toThrow('路径');
 expect(()=>kb.asset('0.13.15','bad.txt')).toThrow('摘要');
 expect(kb.asset('0.13.15','image.png').image?.mimeType).toBe('image/png');
});
test('HTTP authorization and origin boundaries',async()=>{
 const handler=createHandler(kb,{token:'secret',instanceId:'test',allowedHosts:['localhost']});
 expect((await handler(new Request('http://localhost/health'))).status).toBe(401);
 expect((await handler(new Request('http://evil/health',{headers:{authorization:'Bearer secret'}}))).status).toBe(403);
 expect((await handler(new Request('http://localhost/health',{headers:{authorization:'Bearer secret',origin:'http://evil'}}))).status).toBe(403);
});
test('official SDK initializes, lists and calls stateless HTTP tools including images',async()=>{
 const server=Bun.serve({hostname:'127.0.0.1',port:0,fetch:createHandler(kb,{token:'secret',instanceId:'test',allowedHosts:['127.0.0.1']})});
 const client=new Client({name:'test-client',version:'1'});
 try {
  await client.connect(new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${server.port}/mcp`),{requestInit:{headers:{Authorization:'Bearer secret'}}}));
  expect((await client.listTools()).tools).toHaveLength(8);
  const result=await client.callTool({name:'kb_get_recipe',arguments:{version:'0.13.15',id:'r1'}});
  expect(result.isError).not.toBe(true);expect((result.structuredContent as any)?.game_version).toBe('0.13.15');
  expect((await client.callTool({name:'kb_get_recipe',arguments:{version:'0.13.17',id:'r1'}})).isError).toBe(true);
  const image=await client.callTool({name:'kb_get_asset',arguments:{version:'0.13.15',path:'image.png'}});
  expect((image.content as any[])[1].type).toBe('image');
 } finally {await client.close();await server.stop(true)}
});

test('external semantic tool is opt-in and does not alter offline tools',async()=>{
 const {Ragflow}=await import('../../apps/mcp-server/src/ragflow');
 const key=join(root,'api-key');writeFileSync(key,'secret');
 const ragflow=new Ragflow({enabled:true,url:'https://rag.example',apiKeyFile:key,datasets:{'0.13.17':['d']}},(async()=>Response.json({code:0,data:{total:1,chunks:[{dataset_id:'d',content:'高炉说明',id:'c',document_id:'doc'}]}})) as unknown as typeof fetch);
 const server=Bun.serve({hostname:'127.0.0.1',port:0,fetch:createHandler(kb,{token:'secret',instanceId:'test',allowedHosts:['127.0.0.1'],ragflow})});
 const client=new Client({name:'external-test',version:'1'});
 try{
  await client.connect(new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${server.port}/mcp`),{requestInit:{headers:{Authorization:'Bearer secret'}}}));
  const list=await client.listTools();expect(list.tools).toHaveLength(9);expect(list.tools.find(t=>t.name==='kb_search_semantic')?.annotations?.openWorldHint).toBe(true);
  const result=await client.callTool({name:'kb_search_semantic',arguments:{version:'0.13.17',query:'高炉'}});expect((result.structuredContent as any).source_mode).toBe('external_ragflow');
  const fail=await client.callTool({name:'kb_search_semantic',arguments:{version:'0.13.15',query:'高炉'}});expect(fail.isError).toBe(true);expect((fail.structuredContent as any).snapshot_id).toBeUndefined();
  const local=await client.callTool({name:'kb_get_recipe',arguments:{version:'0.13.15',id:'r1'}});expect(local.isError).not.toBe(true);
 }finally{await client.close();await server.stop(true)}
});

test('reverse proxy public Origin is accepted only when explicitly configured',async()=>{
 const handler=createHandler(kb,{token:'secret',instanceId:'test',allowedHosts:['localhost'],allowedOrigins:['https://mcp.example.com']});
 const call=(origin:string)=>handler(new Request('http://localhost/health',{headers:{authorization:'Bearer secret',origin}}));
 expect((await call('https://mcp.example.com')).status).toBe(200);
 expect((await call('https://other.example.com')).status).toBe(403);
});
