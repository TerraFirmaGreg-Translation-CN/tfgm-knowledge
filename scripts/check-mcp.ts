/** Integration probe for the managed local service; never prints its credentials. */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { local, readJson, statePath } from './mcp-runtime';
const state=readJson(statePath);
const ca=readFileSync(resolve(local,'certs/cert.pem'));
const token=readFileSync(resolve(local,'token'),'utf8').trim();
const client=new Client({name:'local-integration',version:'1'});
const checkedFetch:typeof fetch=((input:any,init:any)=>fetch(input,{...init,tls:{ca}})) as typeof fetch;
try {
 await client.connect(new StreamableHTTPClientTransport(new URL(`https://127.0.0.1:${state.port}/mcp`),{fetch:checkedFetch,requestInit:{headers:{Authorization:`Bearer ${token}`}}}));
 const tools=await client.listTools();if(tools.tools.length!==8)throw new Error('Unexpected tool count');
 const recipe=await client.callTool({name:'kb_get_recipe',arguments:{version:'0.13.15',id:'tfg:mixer/limewater_from_flux'}});
 if(recipe.isError||!JSON.stringify(recipe.structuredContent).includes('500'))throw new Error('Recipe check failed');
 const image=await client.callTool({name:'kb_get_asset',arguments:{version:'0.13.15',path:(recipe.structuredContent as any).image_resource}});
 if(!(image.content as any[]).some(x=>x.type==='image'))throw new Error('Image check failed');
 const wrong=await client.callTool({name:'kb_get_recipe',arguments:{version:'0.13.17',id:'tfg:mixer/limewater_from_flux'}});
 if(!wrong.isError)throw new Error('Version isolation failed');
 const denied=await checkedFetch(`https://127.0.0.1:${state.port}/health`);if(denied.status!==401)throw new Error('Auth check failed');
 console.log(JSON.stringify({ok:true,tools:tools.tools.length,snapshot:state.snapshotId,recipe:'tfg:mixer/limewater_from_flux',image:true,version_isolation:true}));
}finally{await client.close()}
