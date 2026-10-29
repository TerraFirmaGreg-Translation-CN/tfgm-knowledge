import { readFileSync } from 'node:fs';
import { transportSettings } from './transport';
const transport=transportSettings();
const r=await fetch(`${transport.protocol}://127.0.0.1:${process.env.PORT??8443}/health`,{headers:{Authorization:'Bearer '+readFileSync(process.env.TFGM_TOKEN_FILE??'/run/secrets/mcp-token','utf8').trim()},...(transport.protocol==='https'?{tls:{ca:readFileSync(transport.cert)}}:{}),signal:AbortSignal.timeout(5000)});
if(!r.ok||(await r.json() as any).status!=='ok')process.exit(1);
