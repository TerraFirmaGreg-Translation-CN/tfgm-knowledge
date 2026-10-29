import { parseArgs } from 'node:util';
import { KnowledgeLibrary } from '@tfgm/knowledge';
const {values,positionals}=parseArgs({args:Bun.argv.slice(2),allowPositionals:true,options:{library:{type:'string'},version:{type:'string'},limit:{type:'string',default:'10'},offset:{type:'string',default:'0'},direction:{type:'string',default:'output'}}});
const kb=new KnowledgeLibrary(values.library??process.env.TFGM_KNOWLEDGE_LIBRARY??'dist/offline/tfgm-library-r1');
try {
  const [command,value='']=positionals;const v=values.version??'';let result;
  switch(command){
    case 'status':result=kb.status();break;
    case 'search':result=kb.search(v,value,Number(values.limit));break;
    case 'items':result=kb.items(v,value,Number(values.limit));break;
    case 'find':result=kb.find(v,value,values.direction as 'input'|'output',Number(values.offset),Number(values.limit));break;
    case 'recipe':result=kb.recipe(v,value,Number(values.offset));break;
    case 'document':result=kb.document(v,value,Number(values.offset));break;
    default:throw new Error('用法：status | search | items | find | recipe | document；数据查询必须指定 --version');
  }
  console.log(JSON.stringify(result,null,2));
} finally{kb.close()}
