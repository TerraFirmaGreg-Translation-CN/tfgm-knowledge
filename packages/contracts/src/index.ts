import { z } from 'zod';
export const versionSchema = z.string().regex(/^\d+\.\d+\.\d+$/);
export const manifestSchema = z.object({
  schema: z.literal('tfgm-offline-knowledge/v1'),
  versions: z.record(versionSchema, z.record(z.string(), z.unknown())),
  counts: z.record(z.string(), z.number()),
  files: z.record(z.string(), z.object({ sha256: z.string().regex(/^[a-f0-9]{64}$/), size: z.number().nonnegative() })),
  network_required_for_queries: z.literal(false),
}).passthrough();
export class KnowledgeError extends Error {
  constructor(public code: string, message: string) { super(message); }
}
export const bounds = { snippet: 1200, page: 12000, assetBytes: 2 * 1024 * 1024 };
export function safePath(path: string): string {
  if (!path || path.startsWith('/') || path.includes('\\') || path.split('/').some(p => p === '..' || p === '.') || /[\x00-\x1f]/.test(path))
    throw new KnowledgeError('INVALID_PATH', '资源路径无效');
  return path;
}
