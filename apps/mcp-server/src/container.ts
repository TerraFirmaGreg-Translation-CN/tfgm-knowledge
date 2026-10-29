import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { KnowledgeLibrary } from '@tfgm/knowledge';
import { createHandler } from './http';
import { loadRagflow } from './ragflow';
const env=process.env;
const token=readFileSync(env.TFGM_TOKEN_FILE??'/run/secrets/mcp-token','utf8').trim();
if(token.length<32)throw new Error('MCP token must contain at least 32 characters');
const port=Number(env.PORT??8443);if(!Number.isInteger(port)||port<1||port>65535)throw new Error('Invalid port');
const kb=new KnowledgeLibrary(env.TFGM_KNOWLEDGE_LIBRARY??'/data/knowledge');
const ragflow=loadRagflow();
const handler=createHandler(kb,{token,instanceId:randomUUID(),allowedHosts:(env.TFGM_ALLOWED_HOSTS??'localhost,127.0.0.1').split(',').map(s=>s.trim()),ragflow});
const server=Bun.serve({hostname:'0.0.0.0',port,tls:{cert:readFileSync(env.TFGM_TLS_CERT??'/run/tls/cert.pem'),key:readFileSync(env.TFGM_TLS_KEY??'/run/tls/key.pem')},maxRequestBodySize:1024*1024,idleTimeout:30,fetch:handler});
console.log(JSON.stringify({event:'ready',port,snapshot_id:kb.snapshotId,ragflow:ragflow.status()}));
let stopping=false;
async function stop(){if(stopping)return;stopping=true;await server.stop(true);kb.close();process.exit(0)}
process.on('SIGTERM',stop);process.on('SIGINT',stop);
