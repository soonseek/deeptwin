// T045: the run artifact viewer over a fake document and a fake request.
// Artifact content reaches the DOM only as text or attributes; the coverage
// and fidelity are shown beside every preview; a codec-only format is
// disclosed, never rendered; refusals are shown by the server's code.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ERROR_MESSAGES, MESSAGES, artifactList, artifactRoutes, createArtifactViewer, previewView, sizeText,
} from '../static/artifacts.mjs';

const RUN = '00000000-0000-4000-8000-00000000a0a1';
const ART = '11111111-1111-5111-8111-111111111111';
const HEX = '3'.repeat(32);

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.listeners = new Map();
    this._text = '';
  }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  set innerHTML(_value) { throw new Error('markup is never written'); }

  append(...nodes) { this.children.push(...nodes); }

  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }

  async dispatch(type) { for (const listener of this.listeners.get(type) ?? []) await listener({}); }

  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll(predicate, found);
    }
    return found;
  }
}

const document = { createElement: tag => new FakeElement(tag) };

function listing(items) {
  return { run_id: RUN, artifacts: items };
}

function item(overrides = {}) {
  return { artifact_id: ART, execution_id: RUN, node_id: 'writer', ordinal: 0, role: 'report',
    declared_media_type: 'text/plain', sha256: 'a'.repeat(64), size: 2048, result_ref: {},
    availability: 'available', ...overrides };
}

function preview(kind, body, coverage = { original_bytes: 10, covered: [[0, 10]], omissions: [] }) {
  return { artifact: item(), preview: { kind, derived: true, sha256: 'b'.repeat(64), fidelity: 'note', coverage, body } };
}

function viewerWith(replies, base = '/') {
  const root = new FakeElement('section');
  const asked = [];
  const request = async (path, options) => {
    asked.push([path, options]);
    const reply = replies.shift();
    if (reply instanceof Error) throw reply;
    return reply;
  };
  return { root, asked, viewer: createArtifactViewer({ root, document, request, basePath: base }) };
}

test('routes, sizes and shapes are strict', () => {
  const routes = artifactRoutes(`/${HEX}/`);
  assert.equal(routes.list(RUN), `/${HEX}/api/v1/runs/${RUN}/artifacts`);
  assert.equal(routes.content(RUN, ART), `/${HEX}/api/v1/runs/${RUN}/artifacts/${ART}/content`);
  assert.throws(() => routes.list('../x'));
  assert.throws(() => artifactRoutes('/x/'));
  assert.equal(sizeText(512), '512 B');
  assert.equal(sizeText(2048), '2.0 KiB');
  assert.throws(() => artifactList({ artifacts: 'no' }));
  assert.throws(() => previewView({ preview: { kind: 'html', coverage: {} } }));
  assert.equal(artifactList(listing([item()]))[0].nodeId, 'writer');
});

test('the list shows each artifact with its declared type, size, digest and a download link', async () => {
  const { root, asked, viewer } = viewerWith([listing([item(), item({ artifact_id: '22222222-2222-5222-8222-222222222222', ordinal: 1, role: 'chart', declared_media_type: 'image/png' })])], `/${HEX}/`);
  const items = await viewer.show(RUN);
  assert.equal(items.length, 2);
  assert.equal(asked[0][0], `/${HEX}/api/v1/runs/${RUN}/artifacts`);
  assert.match(root.textContent, /산출물 2개/);
  assert.match(root.textContent, /report · writer · text\/plain \(선언\) · 2\.0 KiB/);
  const links = root.findAll(el => el.tagName === 'A');
  assert.equal(links[0].getAttribute('href'), `/${HEX}/api/v1/runs/${RUN}/artifacts/${ART}/content`);
  assert.equal(links[0].getAttribute('download'), 'report-0');
});

test('text is shown as text, never markup, with its coverage and fidelity', async () => {
  const { root, viewer } = viewerWith([listing([item()]),
    preview('text', { text: '<img src=x onerror=alert(1)>' },
      { original_bytes: 100000, covered: [[0, 65536]], omissions: [[65536, 100000]] })]);
  await viewer.show(RUN);
  const view = await viewer.preview(ART);
  assert.equal(view.truncated, true);
  const pre = root.findAll(el => el.tagName === 'PRE')[0];
  assert.equal(pre.textContent, '<img src=x onerror=alert(1)>');
  assert.equal(root.findAll(el => el.tagName === 'IMG').length, 0);
  assert.match(root.textContent, /잘렸습니다/);
  assert.match(root.textContent, /note/);
});

test('a table renders text cells and an image renders the same-origin original', async () => {
  const { root, viewer } = viewerWith([listing([item()]), preview('table', { rows: [['a', '=1+1'], ['b', '<b>']], truncated: false }),
    preview('image', { media_type: 'image/png' })]);
  await viewer.show(RUN);
  await viewer.preview(ART);
  const cells = root.findAll(el => el.tagName === 'TD').map(el => el.textContent);
  assert.deepEqual(cells, ['a', '=1+1', 'b', '<b>']);
  await viewer.preview(ART);
  const image = root.findAll(el => el.tagName === 'IMG')[0];
  assert.equal(image.getAttribute('src'), `/api/v1/runs/${RUN}/artifacts/${ART}/content`);
});

test('a codec-only format is disclosed and an unsupported one is named', async () => {
  const { root, viewer } = viewerWith([listing([item()]),
    preview('codec_required', { format: 'pdf' }, { original_bytes: 9, covered: [], omissions: [[0, 9]] }),
    preview('unsupported', {}, { original_bytes: 9, covered: [], omissions: [[0, 9]] })]);
  await viewer.show(RUN);
  await viewer.preview(ART);
  assert.ok(root.textContent.includes(MESSAGES.codec_required));
  await viewer.preview(ART);
  assert.match(root.textContent, /지원하지 않습니다/);
});

test('refusals show the server code and an empty run says so', async () => {
  const refused = viewerWith([Object.assign(new Error('x'), { code: 'not_found' })]);
  await assert.rejects(refused.viewer.show(RUN));
  assert.ok(refused.root.textContent.includes(ERROR_MESSAGES.not_found));
  const empty = viewerWith([listing([])]);
  await empty.viewer.show(RUN);
  assert.match(empty.root.textContent, /산출물 파일이 없습니다/);
  const odd = viewerWith([Object.assign(new Error('x'), { code: 'weird' })]);
  await assert.rejects(odd.viewer.show(RUN));
  assert.ok(odd.root.textContent.includes(ERROR_MESSAGES.unavailable));
});

test('a stale answer never overwrites a newer run', async () => {
  let release;
  const slow = new Promise(resolve => { release = resolve; });
  const root = new FakeElement('section');
  const replies = [slow, Promise.resolve(listing([]))];
  const viewer = createArtifactViewer({ root, document, request: async () => replies.shift() });
  const first = viewer.show(RUN);
  const second = viewer.show('00000000-0000-4000-8000-00000000a0a2');
  await second;
  release(listing([item()]));
  assert.equal(await first, null);
  assert.match(root.textContent, /산출물 파일이 없습니다/);
});
