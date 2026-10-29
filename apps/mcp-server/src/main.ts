import { readFileSync, existsSync, unlinkSync } from 'node:fs';
import { resolve } from 'node:path';
import { KnowledgeLibrary } from '@tfgm/knowledge';
import { createHandler } from './http';
import { identity, ips, local, log, repoKey, root, settings, statePath, writeJson } from '../../../scripts/mcp-runtime';
const instanceId=Bun.argv[Bun.argv.indexOf('--instance')+1];
if(!/^[a-f0-9-]{36}$/.test(instanceId??''))throw new Error('Use mode:mcp:start to launch the managed server');
try{
 const c=settings();const kb=new KnowledgeLibrary(c.library);
 const token=readFileSync(resolve(local,'token'),'utf8').trim();if(token.length<32)throw new Error('MCP token invalid');
 const addresses=ips();const handler=createHandler(kb,{token,instanceId,allowedHosts:['localhost','127.0.0.1',...addresses]});
 let server:ReturnType<typeof Bun.serve>|undefined;
 for(let n=0;n<32;n++){
  try{server=Bun.serve({hostname:c.bindHost,port:c.portBase+n,tls:{cert:Bun.file(resolve(local,'certs/cert.pem')),key:Bun.file(resolve(local,'certs/key.pem'))},maxRequestBodySize:1024*1024,idleTimeout:30,fetch:handler});break}
  catch(e){if((e as any).code!=='EADDRINUSE')throw e}
 }
 if(!server)throw new Error('MCP ports exhausted');
 const own=identity(process.pid);writeJson(statePath,{version:1,repoKey,root,instanceId,pid:process.pid,startTicks:own.startTicks,startedAt:new Date().toISOString(),port:server.port,bindHost:c.bindHost,addresses,snapshotId:kb.snapshotId});
 log(`MCP ready instance=${instanceId} port=${server.port} snapshot=${kb.snapshotId}`);
 const shutdown=async()=>{await server!.stop(true);kb.close();log('MCP stopped instance='+instanceId);if(existsSync(statePath)&&JSON.parse(readFileSync(statePath,'utf8')).instanceId===instanceId)unlinkSync(statePath);process.exit(0)};
 process.on('SIGTERM',shutdown);process.on('SIGINT',shutdown);
 process.on('uncaughtException',error=>{log('fatal: '+error.message);process.exit(1)});
}catch(error){log('startup failed: '+(error as Error).message);process.exit(1)}
