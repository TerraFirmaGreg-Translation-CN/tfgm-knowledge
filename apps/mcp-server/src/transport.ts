import { readFileSync } from 'node:fs';

/** TLS may terminate at the public reverse proxy; never guess from forwarded headers. */
export function transportSettings(env: Record<string, string | undefined> = process.env) {
  const protocol = env.TFGM_TRANSPORT ?? 'https';
  if (protocol !== 'http' && protocol !== 'https') throw new Error('TFGM_TRANSPORT must be http or https');
  return { protocol, cert: env.TFGM_TLS_CERT ?? '/run/tls/cert.pem', key: env.TFGM_TLS_KEY ?? '/run/tls/key.pem' };
}
export function serverTLS(config: ReturnType<typeof transportSettings>) {
  return config.protocol === 'https' ? { tls: { cert: readFileSync(config.cert), key: readFileSync(config.key) } } : {};
}
