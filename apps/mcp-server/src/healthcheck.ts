import { readFileSync } from 'node:fs';
const r=await fetch(`https://127.0.0.1:${process.env.PORT??8443}/health`,{headers:{Authorization:'Bearer '+readFileSync(process.env.TFGM_TOKEN_FILE??'/run/secrets/mcp-token','utf8').trim()},tls:{ca:readFileSync(process.env.TFGM_TLS_CERT??'/run/tls/cert.pem')},signal:AbortSignal.timeout(5000)});
if(!r.ok||(await r.json() as any).status!=='ok')process.exit(1);
