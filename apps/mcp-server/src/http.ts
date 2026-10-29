import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js';
import { KnowledgeLibrary } from '@tfgm/knowledge';
import { timingSafeEqual } from 'node:crypto';
import { createMcpServer } from './tools';
export function createHandler(kb: KnowledgeLibrary, options: { token: string; instanceId: string; allowedHosts: string[] }) {
  function authorized(header: string | null) {
    const given = Buffer.from(header ?? ''); const expected = Buffer.from('Bearer ' + options.token);
    return given.length === expected.length && timingSafeEqual(given, expected);
  }
  return async (request: Request): Promise<Response> => {
    const url = new URL(request.url);
    if (!options.allowedHosts.includes(url.hostname)) return new Response('Invalid host',{status:403});
    const origin=request.headers.get('origin');
    if (origin && origin!==url.origin) return new Response('Invalid origin',{status:403});
    if (!authorized(request.headers.get('authorization'))) return new Response('Unauthorized',{status:401});
    if (url.pathname==='/health') return Response.json({status:'ok',instanceId:options.instanceId,snapshot_id:kb.snapshotId,online_tools_enabled:false},{headers:{'X-TFGM-Instance':options.instanceId}});
    if (url.pathname!=='/mcp') return new Response('Not found',{status:404});
    if (request.method!=='POST') return new Response('Use POST',{status:405,headers:{Allow:'POST'}});
    const server=createMcpServer(kb);
    const transport=new WebStandardStreamableHTTPServerTransport({sessionIdGenerator:undefined,enableJsonResponse:true,maxRequestBodySize:1024*1024});
    try { await server.connect(transport); return await transport.handleRequest(request); }
    finally { await server.close(); }
  };
}
