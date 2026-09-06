import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const files = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/index.html', ['index.html', 'text/html; charset=utf-8']],
  ['/styles.css', ['styles.css', 'text/css; charset=utf-8']],
  ...['app.mjs', 'data.mjs', 'state.mjs', 'views.mjs', 'scenes.mjs'].map(name => [
    `/${name}`, [name, 'text/javascript; charset=utf-8']
  ])
]);
const csp = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
export function createPrototypeServer() {
  return http.createServer(async (request, response) => {
    response.setHeader('Content-Security-Policy', csp);
    response.setHeader('X-Content-Type-Options', 'nosniff');
    response.setHeader('Referrer-Policy', 'no-referrer');
    response.setHeader('Cache-Control', 'no-store');
    const reject = (status, message) => {
      response.writeHead(status, { 'Content-Type': 'text/plain; charset=utf-8' });
      response.end(message);
    };
    if (request.method !== 'GET') {
      response.setHeader('Allow', 'GET');
      return reject(405, 'GET only');
    }
    let pathname;
    try {
      // Validate raw path before URL normalization can erase traversal segments.
      pathname = decodeURIComponent((request.url ?? '').split('?')[0]);
      if (!pathname.startsWith('/') || pathname.includes('\\') || pathname.includes('\0')
        || pathname.split('/').some(part => part.startsWith('.'))) return reject(404, 'Not found');
    } catch { return reject(400, 'Invalid path'); }
    const asset = files.get(pathname);
    if (!asset) return reject(404, 'Not found');
    try {
      const body = await readFile(new URL(asset[0], import.meta.url));
      response.writeHead(200, { 'Content-Type': asset[1] });
      response.end(body);
    } catch { reject(500, 'Local asset unavailable'); }
  });
}
export function resolvePort(value) {
  if (value === undefined) return 4173;
  if (!/^\d+$/.test(value)) throw new Error('PORT must be an integer from 1 to 65535');
  const port = Number(value);
  if (port < 1 || port > 65535) throw new Error('PORT must be an integer from 1 to 65535');
  return port;
}
const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : '';
if (invokedPath === import.meta.url) {
  try {
    const port = resolvePort(process.env.PORT);
    const server = createPrototypeServer();
    server.on('error', error => {
      console.error(error.code === 'EADDRINUSE' ? `Port ${port} is already in use. Choose another numeric PORT.` : 'Local prototype server could not start.');
      process.exitCode = 1;
    });
    server.listen(port, '127.0.0.1', () => console.log(`DeepTwin local prototype: http://127.0.0.1:${port}`));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
