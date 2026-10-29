import { createHash, X509Certificate } from 'node:crypto';
import { chmodSync, existsSync, mkdirSync, readFileSync, realpathSync, renameSync, statSync, unlinkSync, writeFileSync, appendFileSync } from 'node:fs';
import { networkInterfaces } from 'node:os';
import { resolve } from 'node:path';
export const root=realpathSync(resolve(import.meta.dir,'..'));
export const local=resolve(root,'.local/mcp');
export const repoKey=createHash('sha256').update('mode:v1\0'+root).digest('hex');
export const statePath=resolve(local,'state.json');
export const logPath=resolve(local,'service.log');
export function readJson(path:string){return JSON.parse(readFileSync(path,'utf8'))}
export function writeJson(path:string,value:unknown){writeFileSync(path+'.tmp',JSON.stringify(value,null,2)+'\n',{mode:0o600});renameSync(path+'.tmp',path)}
export function settings(){
 const c=readJson(resolve(root,'.local/mode.json'));
 if(c.version!==1||c.repoKey!==repoKey)throw new Error('配置身份或版本不匹配');
 const m=c.mcp;
 if(!m||!Number.isInteger(m.portBase)||m.portBase<1024||m.portBase>32735||!['127.0.0.1','0.0.0.0'].includes(m.bindHost)||typeof m.library!=='string'||m.logMaxBytes<1024||!Number.isInteger(m.logBackups)||m.logBackups<1||m.logBackups>10)throw new Error('MCP 配置无效');
 return m as {library:string;bindHost:string;portBase:number;logMaxBytes:number;logBackups:number};
}
export function ips(){return [...new Set(Object.values(networkInterfaces()).flat().filter(x=>x?.family==='IPv4'&&!x.internal).map(x=>x!.address))]}
export function identity(pid:number){
 const stat=readFileSync(`/proc/${pid}/stat`,'utf8');const fields=stat.slice(stat.lastIndexOf(')')+2).split(' ');
 return {startTicks:fields[19],group:Number(fields[2]),cwd:realpathSync(`/proc/${pid}/cwd`),cmd:readFileSync(`/proc/${pid}/cmdline`,'utf8').split('\0')};
}
export function owns(s:any){
 try{const i=identity(s.pid);return s.repoKey===repoKey&&s.root===root&&i.startTicks===s.startTicks&&i.group===s.pid&&i.cwd===root&&i.cmd.includes(resolve(root,'apps/mcp-server/src/main.ts'))&&i.cmd.includes(s.instanceId)}catch{return false}
}
export async function run(argv:string[]){const p=Bun.spawn(argv,{cwd:root,stdout:'pipe',stderr:'pipe'});const [stdout,stderr,code]=await Promise.all([new Response(p.stdout).text(),new Response(p.stderr).text(),p.exited]);if(code!==0)throw new Error(stderr||stdout||`Command failed: ${argv[0]}`);return stdout}
export async function certificates(){
 const dir=resolve(local,'certs');mkdirSync(dir,{recursive:true,mode:0o700});const cert=resolve(dir,'cert.pem'),key=resolve(dir,'key.pem');const addresses=ips();
 let valid=false;
 try{const x=new X509Certificate(readFileSync(cert));valid=Date.parse(x.validTo)>Date.now()+86400000&&!!x.checkHost('localhost')&&['127.0.0.1',...addresses].every(a=>!!x.checkIP(a))&&existsSync(key)}catch{}
 if(!valid){await run(['openssl','req','-x509','-nodes','-newkey','rsa:2048','-days','90','-keyout',key,'-out',cert,'-subj','/CN=tfgm-mcp.local','-addext','subjectAltName='+['DNS:localhost','IP:127.0.0.1',...addresses.map(x=>'IP:'+x)].join(',')]);chmodSync(key,0o600)}
 return {cert,key,addresses};
}
export function log(message:string){
 const c=settings();
 if(existsSync(logPath)&&statSync(logPath).size+Buffer.byteLength(message)>c.logMaxBytes){
  for(let i=c.logBackups-1;i>=1;i--){const from=logPath+'.'+i,to=logPath+'.'+(i+1);if(existsSync(from))renameSync(from,to)}
  renameSync(logPath,logPath+'.1');
 }
 appendFileSync(logPath,new Date().toISOString()+' '+message.slice(0,16000)+'\n',{mode:0o600});
}
