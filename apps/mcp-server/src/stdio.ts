import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { KnowledgeLibrary } from '@tfgm/knowledge';
import { createMcpServer } from './tools';
const library=process.env.TFGM_KNOWLEDGE_LIBRARY;
if (!library) throw new Error('TFGM_KNOWLEDGE_LIBRARY must name the offline library directory');
const kb=new KnowledgeLibrary(library);
const server=createMcpServer(kb);
await server.connect(new StdioServerTransport());
process.on('SIGTERM',async()=>{await server.close();kb.close();process.exit(0)});
