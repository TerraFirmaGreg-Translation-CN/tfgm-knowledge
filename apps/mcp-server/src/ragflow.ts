import { readFileSync } from 'node:fs';
import { z } from 'zod';
import { versionSchema, KnowledgeError } from '@tfgm/contracts';
const schema=z.object({
  enabled:z.boolean().default(false),
  url:z.string().url().optional(), apiKeyFile:z.string().optional(), caFile:z.string().optional(),
  timeoutMs:z.number().int().min(100).max(60000).default(15000),
  datasets:z.record(versionSchema,z.array(z.string().min(1)).min(1)).default({}),
}).strict();
export class Ragflow {
  readonly config: z.infer<typeof schema>;
  private token=''; private ca?:Buffer;
  constructor(config:unknown,private request:typeof fetch=fetch){
    this.config=schema.parse(config);
    if(!this.config.enabled)return;
    if(!this.config.url||!this.config.apiKeyFile||!Object.keys(this.config.datasets).length)throw new Error('RAGFlow requires url, apiKeyFile and version datasets');
    const url=new URL(this.config.url);
    if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash)throw new Error('RAGFlow requires a clean HTTPS base URL');
    const ids=Object.values(this.config.datasets).flat();
    if(new Set(ids).size!==ids.length)throw new Error('Each RAGFlow dataset must belong to exactly one game version');
    this.token=readFileSync(this.config.apiKeyFile,'utf8').trim();
    if(!this.token)throw new Error('RAGFlow API key file is empty');
    if(this.config.caFile)this.ca=readFileSync(this.config.caFile);
  }
  status(){return {enabled:this.config.enabled,versions:Object.keys(this.config.datasets),source_mode:'external_ragflow',health:'not_probed'};}
  async search(version:string,question:string,limit=5){
    if(!this.config.enabled)throw new KnowledgeError('RAGFLOW_DISABLED','外部 RAGFlow 未启用');
    const datasets=this.config.datasets[version];
    if(!datasets)throw new KnowledgeError('VERSION_NOT_AVAILABLE','该版本未配置 RAGFlow 数据集');
    if(!question.trim()||question.length>1000||!Number.isInteger(limit)||limit<1||limit>10)throw new KnowledgeError('INVALID_QUERY','检索参数无效');
    try{
      const response=await this.request(this.config.url!.replace(/\/$/,'')+'/api/v1/retrieval',{
        method:'POST',headers:{Authorization:'Bearer '+this.token,'Content-Type':'application/json'},
        body:JSON.stringify({question,dataset_ids:datasets,page:1,page_size:limit}),
        redirect:'error',signal:AbortSignal.timeout(this.config.timeoutMs),...(this.ca?{tls:{ca:this.ca}}:{}),
      });
      if(!response.ok)throw new Error('HTTP failure');
      // Bound even chunked responses before JSON parsing.
      const reader=response.body?.getReader();if(!reader)throw new Error('Missing response');
      const parts:Uint8Array[]=[];let size=0;
      try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>2*1024*1024)throw new Error('Response too large');parts.push(value)}}finally{await reader.cancel()}
      const data=JSON.parse(Buffer.concat(parts).toString());
      if(data.code!==0||!Array.isArray(data.data?.chunks))throw new Error('Invalid response');
      const chunks=data.data.chunks;
      if(chunks.some((c:any)=>!datasets.includes(c.dataset_id??c.kb_id)||typeof c.content!=='string'))throw new Error('Dataset mismatch');
      return {source_mode:'external_ragflow',game_version:version,version_basis:'configured_dataset_mapping',retrieved_at:new Date().toISOString(),
        total:data.data.total,results:chunks.slice(0,limit).map((c:any)=>({dataset_id:c.dataset_id??c.kb_id,document_id:c.document_id,chunk_id:c.id,title:String(c.document_keyword??'').slice(0,500),text:c.content.slice(0,6000),truncated:c.content.length>6000,similarity:c.similarity})),
        note:'External datasets are independently managed; no local snapshot guarantee'};
    }catch{throw new KnowledgeError('RAGFLOW_UNAVAILABLE','外部检索失败、超时或响应不符合配置范围；本地工具仍可使用');}
  }
}
export function loadRagflow(path=process.env.TFGM_RAGFLOW_CONFIG){return new Ragflow(path?JSON.parse(readFileSync(path,'utf8')):{enabled:false})}
