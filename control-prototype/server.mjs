import { createServer as httpServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { ARTIFACTS } from './fixtures.mjs';

const CSP = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
const routes = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/index.html', ['index.html', 'text/html; charset=utf-8']],
  ['/styles.css', ['styles.css', 'text/css; charset=utf-8']],
  ...['app', 'fixtures', 'state', 'primitives', 'workspace'].map(name => [`/${name}.mjs`, [`${name}.mjs`, 'text/javascript; charset=utf-8']]),
]);
const assetTypes = {
  pdf: 'application/pdf',
  svg: 'image/svg+xml',
  csv: 'text/csv; charset=utf-8',
  md: 'text/plain; charset=utf-8',
  txt: 'text/plain; charset=utf-8',
};

for (const artifact of Object.values(ARTIFACTS)) {
  for (const value of [artifact.path, ...(artifact.preview === undefined ? [] : [artifact.preview])]) {
    if (typeof value !== 'string') throw new Error('Unsafe fixture asset path');
    const file = value.replace(/^\//, '');
    const extension = file.split('.').at(-1);
    const type = Object.hasOwn(assetTypes, extension) ? assetTypes[extension] : undefined;
    if (!/^assets\/[a-zA-Z0-9._-]+$/.test(file) || file.split('/').some(part => part.startsWith('.')) || !type) {
      throw new Error('Unsafe fixture asset path');
    }
    routes.set(`/${file}`, [file, type]);
  }
}

export function port(value) {
  if (value === undefined) return 4183;
  if (typeof value !== 'string' || !/^[0-9]+$/.test(value) || Number(value) < 1 || Number(value) > 65535) {
    throw new Error('PORT must contain only digits for a port from 1 to 65535');
  }
  return Number(value);
}

export function createServer() {
  return httpServer(async (req, res) => {
    res.setHeader('Content-Security-Policy', CSP);
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    if (req.method !== 'GET') {
      res.writeHead(405, { Allow: 'GET' });
      res.end('Method not allowed');
      return;
    }

    let path;
    try { path = decodeURIComponent((req.url ?? '').split('?')[0]); }
    catch {
      res.writeHead(400);
      res.end('Bad request');
      return;
    }
    if (!path.startsWith('/') || path.includes('\\') || path.includes('\0') || path.split('/').some(part => part.startsWith('.'))) {
      res.writeHead(404);
      res.end('Not found');
      return;
    }
    const route = routes.get(path);
    if (!route) {
      res.writeHead(404);
      res.end('Not found');
      return;
    }
    try {
      const bytes = await readFile(new URL(route[0], import.meta.url));
      res.writeHead(200, { 'Content-Type': route[1] });
      res.end(bytes);
    } catch {
      res.writeHead(500);
      res.end('Local asset unavailable');
    }
  });
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  try {
    const selectedPort = port(process.env.PORT);
    const server = createServer();
    server.once('error', error => {
      console.error(error.code === 'EADDRINUSE'
        ? 'Port is already in use. Choose another port with PORT.'
        : 'Local server could not start.');
      process.exitCode = 1;
    });
    server.listen(selectedPort, '127.0.0.1', () => {
      console.log(`http://127.0.0.1:${server.address().port}`);
    });
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
