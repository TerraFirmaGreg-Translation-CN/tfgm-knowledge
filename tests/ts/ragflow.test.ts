import {test,expect,afterAll} from 'bun:test';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Ragflow} from '../../apps/mcp-server/src/ragflow';
const dir=mkdtempSync(join(tmpdir(),'ragflow-test-'));const key=join(dir,'key');writeFileSync(key,'test-secret');
afterAll(()=>rmSync(dir,{recursive:true,force:true}));
const config={enabled:true,url:'https://rag.example',apiKeyFile:key,datasets:{'0.13.17':['dataset-a']}};
test('disabled and unknown versions never call upstream',async()=>{
 let calls=0;const request=(async()=>{calls++;throw Error('unexpected')}) as unknown as typeof fetch;
 await expect(new Ragflow({enabled:false},request).search('0.13.17','test')).rejects.toThrow('未启用');
 await expect(new Ragflow(config,request).search('0.13.15','test')).rejects.toThrow('未配置');expect(calls).toBe(0);
});
test('version dataset scope, bounded output and source provenance',async()=>{
 const request=(async(url:any,init:any)=>{expect(url).toBe('https://rag.example/api/v1/retrieval');expect(init.redirect).toBe('error');expect(JSON.parse(init.body).dataset_ids).toEqual(['dataset-a']);return Response.json({code:0,data:{total:1,chunks:[{dataset_id:'dataset-a',content:'x'.repeat(7000),id:'chunk',document_id:'doc'}]}})}) as typeof fetch;
 const r=await new Ragflow(config,request).search('0.13.17','高炉');expect(r.source_mode).toBe('external_ragflow');expect(r.results[0].text.length).toBe(6000);expect(r.results[0].truncated).toBe(true);expect(JSON.stringify(r)).not.toContain('test-secret');
});
test('reject unscoped chunks and sanitize upstream failures',async()=>{
 for(const response of [Response.json({code:0,data:{chunks:[{dataset_id:'other',content:'private'}]}}),Response.json({code:102,message:'test-secret'}),new Response('',{status:401})]){
  const r=new Ragflow(config,(async()=>response) as unknown as typeof fetch);await expect(r.search('0.13.17','test')).rejects.toThrow('外部检索失败');
 }
 expect(()=>new Ragflow({...config,datasets:{'0.13.17':['dataset-a'],'0.13.15':['dataset-a']}})).toThrow('exactly one');
 expect(()=>new Ragflow({...config,url:'http://rag.example'})).toThrow('HTTPS');
});
