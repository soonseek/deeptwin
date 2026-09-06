import test from 'node:test';
import assert from 'node:assert/strict';
import { request } from 'node:http';
import { readFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { ARTIFACTS } from '../fixtures.mjs';
import { createServer, port } from '../server.mjs';

const CSP = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

async function withServer(check) {
  const server = createServer();
  assert.equal(server.listening, false);
  try {
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(0, '127.0.0.1', resolve);
    });
    const address = server.address();
    assert.equal(address.address, '127.0.0.1');
    const fetchRaw = (path, method = 'GET') => new Promise((resolve, reject) => {
      const req = request({ hostname: address.address, port: address.port, path, method, agent: false }, res => {
        const chunks = [];
        res.on('data', chunk => chunks.push(chunk));
        res.on('error', reject);
        res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
      });
      req.on('error', reject);
      req.setTimeout(3000, () => req.destroy(new Error('Local request timed out')));
      req.end();
    });
    await check(fetchRaw);
  } finally {
    await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
}

function assertResponseHeaders(response) {
  assert.equal(response.headers['content-security-policy'], CSP);
  assert.equal(response.headers['x-content-type-options'], 'nosniff');
  assert.equal(response.headers['referrer-policy'], 'no-referrer');
  assert.equal(response.headers['cache-control'], 'no-store');
}

test('port accepts only decimal port strings in range and has a local default', () => {
  assert.equal(port(undefined), 4183);
  assert.equal(port('1'), 1);
  assert.equal(port('65535'), 65535);
  assert.equal(port('04183'), 4183);
  for (const value of ['0', '65536', 'abc', '', ' 4183', '4183 ', '1.5', '+4183', '1e3', '0x1057', '-1', null, 4183]) {
    assert.throws(() => port(value), /port/i, String(value));
  }
});

test('fixture initialization rejects unsafe paths and unknown file extensions', () => {
  const fixturesURL = new URL('../fixtures.mjs', import.meta.url).href;
  const serverURL = new URL('../server.mjs', import.meta.url).href;
  for (const file of ['assets/example.toString', 'assets/example.exe', '../private.pdf', 'assets/../private.pdf', 'assets/.hidden.pdf', 'assets/folder/file.pdf', 'assets/bad%2fpath.pdf', null]) {
    // Isolate the fixture import boundary without changing files or exposing a test-only server API.
    const fixtureSource = `export const ARTIFACTS = ${JSON.stringify({ fixture: { path: file } })};`;
    const code = `
      import { registerHooks } from 'node:module';
      registerHooks({ load(url, context, nextLoad) {
        if (url === ${JSON.stringify(fixturesURL)}) return { format: 'module', source: ${JSON.stringify(fixtureSource)}, shortCircuit: true };
        return nextLoad(url, context);
      } });
      await import(${JSON.stringify(serverURL)});
    `;
    const result = spawnSync(process.execPath, ['--input-type=module', '--eval', code], { encoding: 'utf-8', timeout: 5000 });
    assert.equal(result.status, 1, String(file));
    assert.match(result.stderr, /Unsafe fixture asset path/, String(file));
  }
});

test('raw traversal and files outside the exact allowlist are unavailable', async () => {
  await withServer(async fetchRaw => {
    for (const path of [
      '/server.mjs', '/tests/server.test.mjs', '/build-assets.mjs', '/README.md',
      '/../README.md', '/%2e%2e/README.md', '/assets/../fixtures.mjs', '/assets/%2e%2e/fixtures.mjs',
      '/.git/config', '/docs/ui/control-workspace-review.md', '/assets/missing.pdf', '/assets/manifest.json',
      '/%5cfixtures.mjs', '/assets\\missing.pdf', '/fixtures.mjs%00', '/.hidden',
      '//fixtures.mjs', 'http://localhost/fixtures.mjs',
    ]) {
      const response = await fetchRaw(path);
      assert.equal(response.status, 404, path);
      assertResponseHeaders(response);
      assert.doesNotMatch(response.body.toString(), /\/Users\/|ENOENT|Error:/, path);
    }
  });
});

test('malformed percent encoding returns a bounded bad-request response', async () => {
  await withServer(async fetchRaw => {
    for (const path of ['/%', '/%GG', '/%E0%A4%A']) {
      const response = await fetchRaw(path);
      assert.equal(response.status, 400, path);
      assertResponseHeaders(response);
      assert.doesNotMatch(response.body.toString(), /URIError|\/Users\//);
    }
  });
});

test('only GET is permitted even for existing assets', async () => {
  await withServer(async fetchRaw => {
    for (const method of ['POST', 'HEAD', 'PUT', 'DELETE', 'OPTIONS']) {
      const response = await fetchRaw('/', method);
      assert.equal(response.status, 405, method);
      assert.equal(response.headers.allow, 'GET');
      assertResponseHeaders(response);
    }
  });
});

test('real fixture files retain bytes, declared types and restrictive headers', async () => {
  await withServer(async fetchRaw => {
    const expectedTypes = { pdf: 'application/pdf', svg: 'image/svg+xml', csv: 'text/csv; charset=utf-8', text: 'text/plain; charset=utf-8' };
    for (const [type, contentType] of Object.entries(expectedTypes)) {
      const file = Object.values(ARTIFACTS).find(item => item.type === type);
      assert.ok(file, `fixture type ${type}`);
      const response = await fetchRaw(`/${file.path}?review=true`);
      assert.equal(response.status, 200, file.path);
      assert.equal(response.headers['content-type'], contentType);
      assertResponseHeaders(response);
      assert.deepEqual(response.body, await readFile(new URL(`../${file.path}`, import.meta.url)));
      if (type === 'pdf') assert.equal(response.body.subarray(0, 5).toString(), '%PDF-');
    }
    const pdf = Object.values(ARTIFACTS).find(item => item.type === 'pdf');
    const preview = await fetchRaw(`/${pdf.preview}`);
    assert.equal(preview.status, 200);
    assert.equal(preview.headers['content-type'], 'image/svg+xml');
    assertResponseHeaders(preview);
  });
});

test('explicit UI routes resolve from the module and missing files report no local paths', async () => {
  await withServer(async fetchRaw => {
    const uiFiles = {
      '/': ['index.html', 'text/html; charset=utf-8'],
      '/index.html': ['index.html', 'text/html; charset=utf-8'],
      '/styles.css': ['styles.css', 'text/css; charset=utf-8'],
      ...Object.fromEntries(['app', 'fixtures', 'state', 'primitives', 'workspace'].map(name => [`/${name}.mjs`, [`${name}.mjs`, 'text/javascript; charset=utf-8']])),
    };
    for (const [path, [file, contentType]] of Object.entries(uiFiles)) {
      let expected;
      try { expected = await readFile(new URL(`../${file}`, import.meta.url)); }
      catch (error) { if (error.code !== 'ENOENT') throw error; }
      const response = await fetchRaw(path);
      assertResponseHeaders(response);
      if (expected) {
        assert.equal(response.status, 200, path);
        assert.equal(response.headers['content-type'], contentType);
        assert.deepEqual(response.body, expected);
      } else {
        assert.equal(response.status, 500, path);
        assert.equal(response.body.toString(), 'Local asset unavailable');
      }
    }
  });
});
