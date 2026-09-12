// T018 development canary: one route.fulfill capture over bounded stdio frames.
// This helper has no generic command, URL fetch, path, proxy, or CDP-server action.
import crypto from 'node:crypto';
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

const MAX_FRAME_BYTES = 65_536;
const SCHEMA = 'deeptwin-browser-ipc-v1';
const allowedKeys = [
  'action', 'body_base64', 'generation', 'headers', 'request_id', 'schema', 'status', 'url',
];

async function readExact(length) {
  const chunks = [];
  let total = 0;
  while (total < length) {
    const chunk = Buffer.alloc(length - total);
    const count = fs.readSync(0, chunk, 0, chunk.length, null);
    if (count === 0) throw new Error('unexpected_eof');
    chunks.push(chunk.subarray(0, count));
    total += count;
  }
  return Buffer.concat(chunks);
}

async function readFrame() {
  const header = await readExact(4);
  const length = header.readUInt32BE();
  if (length === 0 || length > MAX_FRAME_BYTES) throw new Error('invalid_frame_length');
  const text = (await readExact(length)).toString('utf8');
  assertNoDuplicateObjectKeys(text);
  return JSON.parse(text);
}

function writeAll(fd, value) {
  let offset = 0;
  while (offset < value.length) {
    const count = fs.writeSync(fd, value, offset, value.length - offset);
    if (!Number.isInteger(count) || count <= 0) throw new Error('incomplete_ipc_write');
    offset += count;
  }
}

function writeFrame(value) {
  const payload = Buffer.from(JSON.stringify(value));
  if (payload.length > MAX_FRAME_BYTES) throw new Error('reply_too_large');
  const header = Buffer.alloc(4);
  header.writeUInt32BE(payload.length);
  writeAll(1, header);
  writeAll(1, payload);
}

function assertNoDuplicateObjectKeys(text) {
  let position = 0;
  const whitespace = () => {
    while (position < text.length && /\s/.test(text[position])) position += 1;
  };
  const parseString = () => {
    if (text[position] !== '"') throw new Error('invalid_json');
    const start = position++;
    while (position < text.length) {
      const character = text[position++];
      if (character === '"') {
        try { return JSON.parse(text.slice(start, position)); } catch { throw new Error('invalid_json'); }
      }
      if (character === '\\') {
        if (position >= text.length) throw new Error('invalid_json');
        const escape = text[position++];
        if (escape === 'u') {
          if (!/^[0-9a-fA-F]{4}$/.test(text.slice(position, position + 4))) throw new Error('invalid_json');
          position += 4;
        } else if (!'"\\/bfnrt'.includes(escape)) throw new Error('invalid_json');
      } else if (character.charCodeAt(0) < 0x20) throw new Error('invalid_json');
    }
    throw new Error('invalid_json');
  };
  const parseValue = () => {
    whitespace();
    const character = text[position];
    if (character === '{') return parseObject();
    if (character === '[') return parseArray();
    if (character === '"') { parseString(); return; }
    const rest = text.slice(position);
    const token = rest.match(/^(?:-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)/)?.[0];
    if (!token) throw new Error('invalid_json');
    position += token.length;
  };
  const parseObject = () => {
    position += 1;
    const keys = new Set();
    whitespace();
    if (text[position] === '}') { position += 1; return; }
    while (position < text.length) {
      whitespace();
      const key = parseString();
      if (keys.has(key)) throw new Error(`duplicate_json_key:${key}`);
      keys.add(key);
      whitespace();
      if (text[position++] !== ':') throw new Error('invalid_json');
      parseValue();
      whitespace();
      const separator = text[position++];
      if (separator === '}') return;
      if (separator !== ',') throw new Error('invalid_json');
    }
    throw new Error('invalid_json');
  };
  const parseArray = () => {
    position += 1;
    whitespace();
    if (text[position] === ']') { position += 1; return; }
    while (position < text.length) {
      parseValue();
      whitespace();
      const separator = text[position++];
      if (separator === ']') return;
      if (separator !== ',') throw new Error('invalid_json');
    }
    throw new Error('invalid_json');
  };
  parseValue();
  whitespace();
  if (position !== text.length) throw new Error('invalid_json');
}

function validRequest(message) {
  if (!message || typeof message !== 'object' || Array.isArray(message)) return false;
  if (Object.keys(message).sort().join('|') !== allowedKeys.join('|')) return false;
  if (message.schema !== SCHEMA || message.action !== 'capture') return false;
  if (!/^[0-9a-f]{32}$/.test(message.request_id) || !/^[0-9a-f]{32}$/.test(message.generation)) return false;
  if (typeof message.url !== 'string' || message.url.length > 256) return false;
  let url;
  try { url = new URL(message.url); } catch { return false; }
  if (url.protocol !== 'https:' || url.hostname !== 'fixture.deeptwin.invalid' || !url.pathname.startsWith('/t018/')) return false;
  if (url.port || url.username || url.password || url.search || url.hash || message.status !== 200) return false;
  if (!Array.isArray(message.headers) || message.headers.length < 1 || message.headers.length > 4) return false;
  const names = new Set();
  for (const item of message.headers) {
    if (!Array.isArray(item) || item.length !== 2 || !item.every(value => typeof value === 'string')) return false;
    const [name, value] = item;
    const lowered = name.toLowerCase();
    if (name !== lowered || !['content-type', 'cache-control'].includes(lowered) || names.has(lowered)) return false;
    if (value.length > 256 || value.includes('\r') || value.includes('\n')) return false;
    names.add(lowered);
  }
  const contentType = message.headers.find(([name]) => name === 'content-type')?.[1];
  if (contentType !== 'text/html; charset=utf-8') return false;
  if (typeof message.body_base64 !== 'string' || message.body_base64.length > 43_692) return false;
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(message.body_base64)) return false;
  const decoded = Buffer.from(message.body_base64, 'base64');
  return decoded.length > 0 && decoded.length <= 32_768 && decoded.toString('base64') === message.body_base64;
}

const request = await readFrame();
if (!validRequest(request)) throw new Error('invalid_capture_request');
const playwrightModule = process.env.DEEPTWIN_PLAYWRIGHT_MODULE;
const browserPath = process.env.DEEPTWIN_BROWSER_PATH;
if (!playwrightModule || !browserPath) throw new Error('missing_owned_component_path');
const { chromium } = await import(pathToFileURL(playwrightModule).href);

let unexpectedRequestCount = 0;
let browser;
try {
  browser = await chromium.launch({
    executablePath: browserPath,
    headless: true,
    chromiumSandbox: true,
    args: [
      '--disable-background-networking',
      '--disable-component-update',
      '--disable-default-apps',
      '--disable-domain-reliability',
      '--disable-sync',
      '--metrics-recording-only',
      '--no-first-run',
      '--safebrowsing-disable-auto-update',
    ],
  });
  const context = await browser.newContext({ acceptDownloads: false, serviceWorkers: 'block' });
  await context.route('**/*', async route => {
    const routed = route.request();
    if (routed.url() === request.url && routed.method() === 'GET') {
      await route.fulfill({
        status: request.status,
        headers: Object.fromEntries(request.headers),
        body: Buffer.from(request.body_base64, 'base64'),
      });
      return;
    }
    unexpectedRequestCount += 1;
    await route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  await page.goto(request.url, { waitUntil: 'load', timeout: 10_000 });
  const screenshot = await page.screenshot({ type: 'png' });
  writeFrame({
    schema: 'deeptwin-browser-helper-reply-v1',
    request_id: request.request_id,
    generation: request.generation,
    state: 'captured_waiting_for_shutdown',
    broker_fulfilled: true,
    unexpected_request_count: unexpectedRequestCount,
    marker: await page.locator('#marker').textContent(),
    javascript: await page.locator('body').getAttribute('data-js'),
    browser_version: browser.version(),
    screenshot_base64: screenshot.toString('base64'),
    screenshot_sha256: crypto.createHash('sha256').update(screenshot).digest('hex'),
  });
  const shutdown = await readFrame();
  if (
    shutdown?.schema !== SCHEMA || shutdown?.action !== 'shutdown'
    || shutdown?.request_id !== request.request_id || shutdown?.generation !== request.generation
    || Object.keys(shutdown).sort().join('|') !== 'action|generation|request_id|schema'
  ) throw new Error('invalid_shutdown_request');
  await browser.close();
  browser = undefined;
  writeFrame({
    schema: 'deeptwin-browser-helper-reply-v1',
    request_id: request.request_id,
    generation: request.generation,
    state: 'terminated',
  });
} finally {
  if (browser) await browser.close().catch(() => {});
}
