import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, statfsSync, writeFileSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import { randomBytes, randomUUID } from 'node:crypto';
import { certificates, identity, local, logPath, owns, readJson, repoKey, root, run, settings, statePath, writeJson } from './mcp-runtime';
const args=Bun.argv.slice(2);const command=args[0]??'help';const machine=args.includes('--json');
const allowed=new Set(['start','stop','status','health','logs','help']);
if(!allowed.has(command)||args.slice(1).some(a=>!['--json','--locked'].includes(a)))throw new Error('用法：start|stop|status|health|logs|help [--json]');
const color=!machine&&!('NO_COLOR'in process.env)&&process.env.FORCE_COLOR!=='0'&&(!!process.env.FORCE_COLOR||!!process.stdout.isTTY&&process.env.TERM!=='dumb');
const paint=(s:string,c:number)=>color?`\x1b[${c}m${s}\x1b[0m`:s;
const width=(s:string)=>[...s].reduce((n,c)=>n+(c.charCodeAt(0)>255?2:1),0);
const rows=(label:string,value:unknown)=>'  '+paint(label+' '.repeat(Math.max(2,16-width(label))),2)+String(value);
function panel(data:any){
 const line=paint('─'.repeat(Math.min(process.stdout.columns||76,76)),2);
 if(command==='help')return [line,paint('  tfgm-knowledge · Bun MCP 开发命令',1),line,rows('用法','bun run mode:mcp:<命令>'),'',paint('  生命周期',1),rows('start','启动独立 Bun MCP，默认自签 HTTPS'),rows('stop','仅停止已核验归属的 MCP 进程，保留知识包'),'',paint('  状态与排障',1),rows('status','查看实际 URL、身份、磁盘和知识快照'),rows('health','验证 HTTPS、令牌和本次实例；失败返回非零'),rows('logs','显示最近日志；每份 10 MiB，保留 3 份备份'),rows('help','显示本帮助'),'',rows('配置 owner','.local/mode.json；由原有 mode.py 初始化 MCP 配置'),rows('示例','bun run mode:mcp:start'),rows('机器输出','bun --silent run mode:mcp:status --json'),rows('维护预览','bun run mode:clean --dry-run（现有登记资源）'),line].join('\n');
 return [line,paint('  tfgm-knowledge · Bun MCP',1),line,rows('运行状态',paint(data.state==='healthy'?'● 运行正常':data.state==='stopped'?'○ 已停止':'⚠ 健康异常',data.state==='healthy'?32:33)),...(data.urls??[]).map((u:string,i:number)=>rows(i?'局域网':'MCP 地址',paint(u,36))),rows('健康检查',data.reason), '',rows('TLS','自签 HTTPS · 信任需由客户端配置'),rows('证书',resolve(local,'certs/cert.pem')),rows('令牌文件',resolve(local,'token')),rows('知识快照',data.snapshotId??'未获取'),rows('线上工具','未启用'),'',rows('磁盘使用',`${data.disk.usedPercent}%（当前用户可用空间口径）`),rows('缓存策略','MCP 无持久查询缓存；知识包、依赖和凭据受保护'),rows('日志预算','10 MiB × 4，写入时轮转；无后台清理任务'),rows('最近维护','MCP 无可重建构建产物；日志按大小维护'),rows('配置',resolve(root,'.local/mode.json')),rows('仓库标识',repoKey.slice(0,12)),line,paint('  mode:mcp:logs 排障 · mode:mcp:stop 停止 · mode:mcp:help 帮助',36)].join('\n');
}
function disk(){const f=statfsSync(root);return {usedPercent:Number(((1-f.bavail/f.blocks)*100).toFixed(2)),available:f.bavail*f.bsize}}
async function status(){
 const d=disk();let s:any;try{s=readJson(statePath)}catch{return {state:'stopped',reason:'尚未启动或无运行状态',disk:d,urls:[]}}
 if(!owns(s))return {state:'stopped',reason:'无可核验的本项目进程；未探测旧端口',disk:d,urls:[]};
 try{
  const response=await fetch(`https://127.0.0.1:${s.port}/health`,{headers:{Authorization:'Bearer '+readFileSync(resolve(local,'token'),'utf8').trim()},tls:{ca:readFileSync(resolve(local,'certs/cert.pem'))},redirect:'error',signal:AbortSignal.timeout(3000)});
  const body=await response.json() as any;
  if(!response.ok||body.instanceId!==s.instanceId||response.headers.get('X-TFGM-Instance')!==s.instanceId||body.status!=='ok'||body.snapshot_id!==s.snapshotId)throw new Error('实例或快照不匹配');
  return {...s,state:'healthy',reason:'HTTPS 与实例、知识库均已验证',disk:d,urls:[`https://127.0.0.1:${s.port}/mcp`,...(s.bindHost==='0.0.0.0'?s.addresses.map((ip:string)=>`https://${ip}:${s.port}/mcp`):[])]};
 }catch(error){return {...s,state:'unhealthy',reason:(error as Error).message,disk:d,urls:[]}}
}
const emit=(data:any)=>console.log(machine?JSON.stringify(data):panel(data));
if(command==='help'){emit({});process.exit(0)}
if(command==='status'||command==='health'){const s=await status();emit(s);process.exit(command==='health'&&s.state!=='healthy'?1:0)}
if(command==='logs'){const text=existsSync(logPath)?readFileSync(logPath,'utf8').slice(-20000):'暂无 MCP 日志';console.log(machine?JSON.stringify({log:text}):text);process.exit(0)}
mkdirSync(local,{recursive:true,mode:0o700});
// Persistent configuration is written only by the existing owner under its lock.
if(command==='start'&&!args.includes('--locked'))await run(['python3',resolve(root,'scripts/mode.py'),'mcp-config','--json']);
if(!args.includes('--locked')){
 const child=Bun.spawn(['flock','-n',resolve(root,'.local/lifecycle.lock'),process.execPath,resolve(root,'scripts/mcp-mode.ts'),command,...(machine?['--json']:[]),'--locked'],{cwd:root,stdout:'inherit',stderr:'inherit'});
 process.exit(await child.exited);
}
if(command==='stop'){
 if(existsSync(statePath)){
  const s=readJson(statePath);if(!owns(s))throw new Error('状态存在但不能核验进程归属；拒绝发送停止信号');
  process.kill(-s.pid,'SIGTERM');
  for(let i=0;i<50&&owns(s);i++)await Bun.sleep(100);
  if(owns(s))throw new Error('MCP 尚未退出，请检查日志');
 }
 emit(await status());process.exit(0);
}
const existing=await status();if(existing.state==='healthy'){emit(existing);process.exit(0)}
if(existing.state==='unhealthy')throw new Error('本项目 MCP 仍在运行但异常，请先检查或停止');
const config=settings();const d=disk();
// No automatic dependency install/build: preserve live services and all persistent data.
if(d.usedPercent>=92)throw new Error('磁盘使用达到 92%；停止新启动，保留已有服务和数据');
await certificates();
const tokenFile=resolve(local,'token');if(!existsSync(tokenFile))writeFileSync(tokenFile,randomBytes(32).toString('hex')+'\n',{mode:0o600});
const instanceId=randomUUID();
const child=spawn(process.execPath,[resolve(root,'apps/mcp-server/src/main.ts'),'--instance',instanceId],{cwd:root,detached:true,stdio:'ignore',env:process.env});child.unref();
if(!child.pid)throw new Error('无法启动 MCP');
for(let i=0;i<100;i++){
 await Bun.sleep(100);const s=await status();
 if(s.state==='healthy'&&s.instanceId===instanceId){
  writeJson(resolve(local,'astrbot.example.json'),{url:s.urls[0],transport:'streamable_http',headers:{Authorization:'Bearer <读取 .local/mcp/token 的值>'}});
  emit(s);process.exit(0);
 }
 try{process.kill(child.pid,0)}catch{throw new Error('MCP 启动失败；请运行 mode:mcp:logs')}
}
// Do not leave a startup owned by this invocation running after readiness timeout.
try{const s=readJson(statePath);if(s.instanceId===instanceId&&owns(s))process.kill(-s.pid,'SIGTERM')}catch{}
throw new Error('MCP 启动超时；请检查日志');
