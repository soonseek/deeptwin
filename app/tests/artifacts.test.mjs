// T045: the run artifact viewer over a fake document and a fake request.
// Artifact content reaches the DOM only as text or attributes; the coverage
// and fidelity are shown beside every preview; a codec-only format is
// disclosed, never rendered; refusals are shown by the server's code.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ERROR_MESSAGES, INDEX_FILTERS, MAX_PAGES, MESSAGES, artifactList, artifactRoutes, createArtifactIndex,
  createArtifactViewer, indexPage, previewView, sizeText,
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
  // the owner's words for the declared type, with the declared-not-sniffed limit said once
  // above the list; the raw type and the full digest stay in each row's technical fold
  assert.match(root.textContent, /report · writer · 텍스트 · 2\.0 KiB/);
  assert.match(root.textContent, /chart · writer · 이미지 · 2\.0 KiB/);
  assert.match(root.textContent, new RegExp(MESSAGES.declared));
  const folds = root.findAll(el => el.tagName === 'DETAILS');
  assert.equal(folds.length, 2);
  assert.match(folds[0].textContent, /^기술 정보산출물 ID11111111-1111-5111-8111-111111111111밝힌 형식text\/plainSHA-256a{64}$/);
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

// --- document previews through the isolated worker, and the vault-wide index ---

function pagePreview(page, count) {
  return { artifact: item({ declared_media_type: 'application/pdf' }), preview: {
    kind: 'page_image', derived: true, sha256: 'c'.repeat(64), fidelity: `page ${page} of ${count} rasterized`,
    coverage: { original_bytes: 900, unit: 'page', page_count: count, covered: [[page, page]],
      omissions: page > 1 ? [[1, page - 1]] : [[2, count]], not_rendered: ['links', 'text_layer'] },
    body: { media_type: 'image/png', page, page_count: count, width: 619, height: 800, page_width_pt: 612,
      page_height_pt: 792, byte_length: 4000 } } };
}

test('page and index routes are strict', () => {
  const routes = artifactRoutes(`/${HEX}/`);
  assert.equal(routes.page(RUN, ART, 2), `/${HEX}/api/v1/runs/${RUN}/artifacts/${ART}/pages/2`);
  assert.equal(routes.pageImage(RUN, ART, 2), `/${HEX}/api/v1/runs/${RUN}/artifacts/${ART}/pages/2/image`);
  assert.equal(routes.index, `/${HEX}/api/v1/artifacts`);
  for (const bad of [0, -1, 1.5, '2', MAX_PAGES + 1]) assert.throws(() => routes.page(RUN, ART, bad));
  assert.throws(() => previewView({ preview: { kind: 'page_image', coverage: { original_bytes: 1, covered: [], omissions: [], unit: 'page' }, body: { page: 3, page_count: 2 } } }));
});

test('a PDF page is the worker-rendered image, with its page coverage and page-by-page navigation', async () => {
  const { root, asked, viewer } = viewerWith([listing([item({ declared_media_type: 'application/pdf' })]),
    pagePreview(1, 3), pagePreview(2, 3)]);
  await viewer.show(RUN);
  const view = await viewer.preview(ART);
  assert.equal(view.kind, 'page_image');
  const image = root.findAll(el => el.tagName === 'IMG')[0];
  assert.equal(image.getAttribute('src'), `/api/v1/runs/${RUN}/artifacts/${ART}/pages/1/image`);
  assert.equal(image.getAttribute('width'), '619');
  assert.match(root.textContent, /전체 3쪽 중 1쪽 표시 \(619×800 픽셀\)/);
  assert.match(root.textContent, /이미지에 없는 것: 링크, 텍스트 층/);
  assert.match(root.textContent, /1 \/ 3쪽/);
  assert.match(root.textContent, /미리보기 SHA-256 cccccccccccc/);
  const [previous, next] = root.findAll(el => el.tagName === 'BUTTON' && ['이전 쪽', '다음 쪽'].includes(el.textContent));
  assert.equal(previous.disabled, true);
  assert.equal(next.disabled, false);
  await next.dispatch('click');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(asked.at(-1)[0], `/api/v1/runs/${RUN}/artifacts/${ART}/pages/2`);
  assert.equal(root.findAll(el => el.tagName === 'IMG')[0].getAttribute('src'),
    `/api/v1/runs/${RUN}/artifacts/${ART}/pages/2/image`);
});

test('DOCX text is shown as text with the parts it leaves out; worker outcomes are disclosed, never faked', async () => {
  const docx = { artifact: item(), preview: { kind: 'document_text', derived: true, sha256: 'd'.repeat(64),
    fidelity: 'extracted by the isolated document worker',
    coverage: { original_bytes: 5000, unit: 'text_layer', covered: ['body_paragraphs', 'table_cells'],
      omissions: ['headers_footers', 'images'] },
    body: { text: '<b>제목</b>\na\tb', truncated: false, paragraphs: 1, tables: 1, table_cells: 2 } } };
  const none = { original_bytes: 9, covered: [], omissions: [[0, 9]] };
  const disclosed = (kind, body) => ({ artifact: item(), preview: { kind, derived: false, sha256: null, fidelity: 'f', coverage: none, body } });
  const { root, viewer } = viewerWith([listing([item()]), docx,
    disclosed('codec_required', { format: 'pdf', reason: 'too_large' }),
    disclosed('codec_required', { format: 'pdf', reason: 'unavailable' }),
    disclosed('codec_failed', { format: 'pdf', code: 'content_rejected' })]);
  await viewer.show(RUN);
  await viewer.preview(ART);
  assert.equal(root.findAll(el => el.tagName === 'PRE')[0].textContent, '<b>제목</b>\na\tb');
  assert.match(root.textContent, /본문 문단 1개, 표 1개\(셀 2개\)의 텍스트 — 포함하지 않은 것: 머리글·바닥글, 이미지/);
  await viewer.preview(ART);
  assert.ok(root.textContent.includes(MESSAGES.codec_too_large));
  await viewer.preview(ART);
  assert.ok(root.textContent.includes(MESSAGES.codec_unavailable));
  await viewer.preview(ART);
  assert.ok(root.textContent.includes(MESSAGES.codec_failed));
  assert.equal(root.findAll(el => el.tagName === 'IMG').length, 0);
});

test('a page refusal shows the server code', async () => {
  const { root, viewer } = viewerWith([listing([item()]),
    Object.assign(new Error('x'), { code: 'range_not_satisfiable' }),
    Object.assign(new Error('x'), { code: 'unavailable' })]);
  await viewer.show(RUN);
  await assert.rejects(viewer.showPage(ART, 9));
  assert.ok(root.textContent.includes(ERROR_MESSAGES.range_not_satisfiable));
  await assert.rejects(viewer.showPage(ART, 1));
  assert.ok(root.textContent.includes(ERROR_MESSAGES.unavailable));
});

function indexReply(items, { total = items.length, next = null, unreadable = 0 } = {}) {
  return { artifacts: items, total, cursor: 0, limit: 25, next_cursor: next, filters: {},
    runs: { scanned: 2, unreadable, omitted: 0 } };
}

test('the index lists artifacts across runs, filters by type, pages on and opens any one', async () => {
  const OTHER = '00000000-0000-4000-8000-00000000a0a2';
  const root = new FakeElement('section');
  const asked = [];
  const opened = [];
  const replies = [
    indexReply([{ ...item(), run_id: RUN }], { total: 2, next: '1', unreadable: 1 }),
    indexReply([{ ...item({ artifact_id: '22222222-2222-5222-8222-222222222222', declared_media_type: 'application/pdf' }), run_id: OTHER }], { total: 2 }),
    indexReply([]),
  ];
  const index = createArtifactIndex({ root, document, basePath: `/${HEX}/`,
    request: async (path, options) => { asked.push([path, options]); return replies.shift(); },
    onOpen: (runId, artifactId) => { opened.push([runId, artifactId]); } });
  await index.refresh();
  assert.deepEqual(asked[0], [`/${HEX}/api/v1/artifacts`, { query: { limit: '25' } }]);
  assert.match(root.textContent, /산출물 2개 중 1개 표시 \(읽지 못한 실행 1개\)/);
  await index.more();
  assert.deepEqual(asked[1][1], { query: { limit: '25', cursor: '1' } });
  assert.equal(index.items.length, 2);
  const buttons = root.findAll(el => el.tagName === 'BUTTON' && el.textContent === '열기');
  await buttons[1].dispatch('click');
  assert.deepEqual(opened, [[OTHER, '22222222-2222-5222-8222-222222222222']]);
  await index.setFilter('application/pdf');
  assert.deepEqual(asked[2][1], { query: { limit: '25', media_type: 'application/pdf' } });
  assert.match(root.textContent, /조건에 맞는 산출물이 없습니다/);
  assert.throws(() => index.setFilter('text/html'));
  assert.throws(() => indexPage({ artifacts: [{ ...item(), run_id: '../x' }], total: 1, next_cursor: null, runs: { scanned: 1, unreadable: 0, omitted: 0 } }));
  assert.ok(INDEX_FILTERS.length >= 5);
});

test('an index refusal names the code; the viewer opens an indexed artifact by run and id', async () => {
  const root = new FakeElement('section');
  const index = createArtifactIndex({ root, document, request: async () => { throw Object.assign(new Error('x'), { code: 'unauthenticated' }); },
    onOpen: () => {} });
  await assert.rejects(index.refresh());
  assert.ok(root.textContent.includes(ERROR_MESSAGES.unauthenticated));
  const { asked, viewer } = viewerWith([listing([item()]), preview('text', { text: 'x' })]);
  const view = await viewer.open(RUN, ART);
  assert.equal(view.kind, 'text');
  assert.deepEqual(asked.map(([path]) => path), [`/api/v1/runs/${RUN}/artifacts`, `/api/v1/runs/${RUN}/artifacts/${ART}/preview`]);
});
