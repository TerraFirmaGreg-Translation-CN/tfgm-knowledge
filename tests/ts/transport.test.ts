import { test, expect } from 'bun:test';
import { transportSettings, serverTLS } from '../../apps/mcp-server/src/transport';
test('HTTP requires no certificate or key files',()=>{
 const config=transportSettings({TFGM_TRANSPORT:'http',TFGM_TLS_CERT:'/does/not/exist',TFGM_TLS_KEY:'/does/not/exist'});
 expect(config.protocol).toBe('http');expect(serverTLS(config)).toEqual({});
});
test('invalid transport is rejected; existing HTTPS default remains explicit',()=>{
 expect(transportSettings({}).protocol).toBe('https');
 expect(()=>transportSettings({TFGM_TRANSPORT:'typo'})).toThrow('must be http or https');
});
