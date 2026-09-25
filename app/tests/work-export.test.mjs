// T073: the work screen's export panel over a fake document and a fake request.
// The owner sees the server's actual preview (items with their content mode,
// omissions with their reasons) before any consent; consent is an explicit,
// separate check bound to that preview's digest; a stale preview is refused and
// cleared; the bundle is offered as a same-origin download beside its digest.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CONFIRM_SCHEMA, ERROR_MESSAGES, MESSAGES, PREVIEW_SCHEMA, createWorkExport, exportRoutes,
} from '../static/work-export.mjs';

const WORK = '00000000-0000-4000-8000-00000000b0b1';
const REQ = '00000000-0000-4000-8000-00000000b0b2';
const BUNDLE = '11111111-1111-5111-8111-111111111111';
const HEX = '3'.repeat(32);

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.listeners = new Map();
    this._text = '';
    this.checked = false;
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
const crypto = { randomUUID: () => REQ };

function previewReply(overrides = {}) {
  return {
    request_id: REQ, work_id: WORK, preview_sha: 'a'.repeat(64), categories: ['events', 'originals'],
    include_raw: false, exportable: true,
    items: [
      { export_id: 'item-1', category: 'originals', relative_path: 'originals/revision-1.json',
        media_type: 'application/json', size_bytes: 120, export_sha256: 'b'.repeat(64),
        content_mode: 'metadata_only', label: '작업 설명 1판 (원문 제외)' },
      { export_id: 'item-2', category: 'events', relative_path: 'events/work-history.json',
        media_type: 'application/json', size_bytes: 2048, export_sha256: 'c'.repeat(64),
        content_mode: 'metadata_only', label: '작업 개정 기록' },
    ],
    missing: [{ category: 'alternatives', reason: 'unavailable', claim: 'x' },
      { category: 'tool_observations', reason: 'not_selected', claim: 'y' }],
    ...overrides,
  };
}

function panel(replies, { workId = WORK, base = '/' } = {}) {
  const root = new FakeElement('section');
  const asked = [];
  const request = async (path, options) => {
    asked.push([path, options]);
    const reply = replies.shift();
    if (reply instanceof Error) throw reply;
    return reply;
  };
  const exporter = createWorkExport({ root, document, basePath: base, request, crypto, workId: () => workId });
  return { root, asked, exporter };
}

const buttons = root => root.findAll(el => el.tagName === 'BUTTON');
const boxes = root => root.findAll(el => el.tagName === 'INPUT');

test('routes are strict and deployment-relative', () => {
  const routes = exportRoutes(`/${HEX}/`);
  assert.equal(routes.preview(WORK), `/${HEX}/api/v1/works/${WORK}/exports/preview`);
  assert.equal(routes.download(WORK, BUNDLE), `/${HEX}/api/v1/works/${WORK}/exports/${BUNDLE}`);
  assert.throws(() => routes.preview('../x'));
  assert.throws(() => routes.download(WORK, 'x'));
  assert.throws(() => exportRoutes('/x/'));
});

test('export is optional and needs a saved work', async () => {
  const { root, asked, exporter } = panel([], { workId: null });
  assert.match(root.textContent, /선택 사항/);
  assert.equal(await exporter.preview(), null);
  assert.match(root.textContent, new RegExp(MESSAGES.unsaved));
  assert.equal(asked.length, 0);
});

test('the preview shows actual items and every omission before any consent', async () => {
  const { root, asked, exporter } = panel([previewReply()]);
  await exporter.preview();
  const [path, options] = asked[0];
  assert.equal(path, `/api/v1/works/${WORK}/exports/preview`);
  assert.equal(options.method, 'POST');
  assert.deepEqual(options.body, { schema_version: PREVIEW_SCHEMA, request_id: REQ,
    categories: ['events', 'originals'], include_raw: false });
  assert.match(root.textContent, /포함될 항목 2개/);
  assert.match(root.textContent, /작업 개정 기록 · 원문 제외\(메타데이터만\) · 2\.0 KiB/);
  assert.match(root.textContent, /내 버전: 이 서버가 아직 모으지 않음/);
  assert.match(root.textContent, /도구 관측: 선택하지 않음/);
  // consent is a separate, unchecked control
  const consent = boxes(root).find(el => el.getAttribute('id') === 'export-consent');
  assert.equal(consent.checked, false);
});

test('raw originals are asked for only by the explicit choice', async () => {
  const { root, asked, exporter } = panel([previewReply({ include_raw: true })]);
  boxes(root).find(el => el.getAttribute('id') === 'export-include-raw').checked = true;
  await exporter.preview();
  assert.equal(asked[0][1].body.include_raw, true);
});

test('confirmation needs the explicit check and binds the previewed digest', async () => {
  const receipt = { bundle_id: BUNDLE, bundle_sha256: 'd'.repeat(64), size_bytes: 4096, item_count: 2,
    manifest_sha256: 'e'.repeat(64), completed_at: '2026-09-23T00:00:00.000000Z', work_id: WORK,
    request_id: REQ, missing: [] };
  const { root, asked, exporter } = panel([previewReply(), receipt]);
  await exporter.preview();
  const go = buttons(root).find(el => el.textContent === '이 내용으로 내보내기');
  await go.dispatch('click');
  assert.equal(asked.length, 1);  // nothing sent without consent
  assert.match(root.textContent, new RegExp(MESSAGES.needConsent));
  boxes(root).find(el => el.getAttribute('id') === 'export-consent').checked = true;
  await go.dispatch('click');
  const [path, options] = asked[1];
  assert.equal(path, `/api/v1/works/${WORK}/exports`);
  assert.deepEqual(options.body, { schema_version: CONFIRM_SCHEMA, request_id: REQ,
    categories: ['events', 'originals'], include_raw: false, preview_sha: 'a'.repeat(64), confirmed: true });
  const link = root.findAll(el => el.tagName === 'A')[0];
  assert.equal(link.getAttribute('href'), `/api/v1/works/${WORK}/exports/${BUNDLE}`);
  assert.match(root.textContent, /묶음 SHA-256 d{64}/);
  assert.match(root.textContent, /자동으로 전송하지 않았습니다/);
});

test('a stale preview is refused and cleared; nothing-to-export offers no consent', async () => {
  const stale = Object.assign(new Error('x'), { code: 'conflict' });
  const { root, exporter } = panel([previewReply(), stale, previewReply({ items: [], exportable: false })]);
  await exporter.preview();
  boxes(root).find(el => el.getAttribute('id') === 'export-consent').checked = true;
  await buttons(root).find(el => el.textContent === '이 내용으로 내보내기').dispatch('click');
  assert.match(root.textContent, new RegExp(ERROR_MESSAGES.conflict));
  assert.equal(exporter.current, null);
  await exporter.preview();
  assert.match(root.textContent, new RegExp(MESSAGES.nothing));
  assert.equal(boxes(root).some(el => el.getAttribute('id') === 'export-consent'), false);
});

test('server text never becomes markup', async () => {
  const { root, exporter } = panel([previewReply({ items: [{ ...previewReply().items[0],
    label: '<img src=x onerror=alert(1)>' }] })]);
  await exporter.preview();
  assert.match(root.textContent, /<img src=x onerror=alert\(1\)>/);
});

// T074: raw originals with secret findings — kind and location only, withheld until the
// owner confirms the exact finding set, which re-previews and is carried by the export
const FINDINGS_SHA = 'f'.repeat(64);
function scanned(confirmed) {
  return previewReply({ include_raw: true, categories: ['originals'], preview_sha: confirmed ? '9'.repeat(64) : 'a'.repeat(64),
    items: [confirmed
      ? { ...previewReply().items[0], relative_path: 'originals/revision-1.txt', content_mode: 'raw', label: '작업 설명 1판 원문' }
      : { ...previewReply().items[0], label: '작업 설명 1판 (비밀로 보이는 값이 있어 원문 제외)' }],
    missing: confirmed ? [] : [{ category: 'originals', reason: 'redacted', claim: 'x' }],
    secret_scan: { findings: [
      { relative_path: 'originals/revision-1.txt', kind: 'anthropic_api_key', line: 2, column: 4 },
      { relative_path: 'originals/revision-1.txt', kind: 'aws_secret_access_key', line: 3, column: 1 }],
    truncated: false, findings_sha: FINDINGS_SHA, confirmed } });
}

test('secret findings are shown by kind and location, and withheld until the exact set is confirmed', async () => {
  const receipt = { bundle_id: BUNDLE, bundle_sha256: 'd'.repeat(64), size_bytes: 10, item_count: 1,
    manifest_sha256: 'e'.repeat(64), completed_at: '2026-09-23T00:00:00.000000Z', work_id: WORK,
    request_id: REQ, missing: [] };
  const { root, asked, exporter } = panel([scanned(false), scanned(true), receipt]);
  boxes(root).find(el => el.getAttribute('id') === 'export-include-raw').checked = true;
  await exporter.preview();
  assert.equal('acknowledged_findings_sha' in asked[0][1].body, false);
  const findings = root.findAll(el => el.getAttribute?.('class') === 'export-findings')[0];
  assert.deepEqual(findings.children.map(li => li.textContent), [
    'Anthropic API 키 형태 · 작업 설명 1판 2행 4열', 'AWS 비밀 액세스 키 지정 · 작업 설명 1판 3행 1열']);
  assert.match(root.textContent, new RegExp(MESSAGES.findings));
  assert.match(root.textContent, /원문 제외\(메타데이터만\)/);
  const again = buttons(root).find(el => el.textContent.startsWith('확인한 값과 함께'));
  // the confirmation is an explicit, unchecked control; nothing is sent without it
  await again.dispatch('click');
  assert.equal(asked.length, 1);
  assert.match(root.textContent, new RegExp(MESSAGES.needFindings));
  // the owner switching checkboxes afterwards does not change the confirmed selection
  boxes(root).find(el => el.getAttribute('id') === 'export-category-events').checked = true;
  boxes(root).find(el => el.getAttribute('id') === 'export-confirm-findings').checked = true;
  await again.dispatch('click');
  assert.deepEqual(asked[1][1].body, { schema_version: PREVIEW_SCHEMA, request_id: REQ, categories: ['originals'],
    include_raw: true, acknowledged_findings_sha: FINDINGS_SHA });
  assert.match(root.textContent, new RegExp(MESSAGES.findingsConfirmed));
  assert.equal(boxes(root).some(el => el.getAttribute('id') === 'export-confirm-findings'), false);
  boxes(root).find(el => el.getAttribute('id') === 'export-consent').checked = true;
  await buttons(root).find(el => el.textContent === '이 내용으로 내보내기').dispatch('click');
  assert.deepEqual(asked[2][1].body, { schema_version: CONFIRM_SCHEMA, request_id: REQ, categories: ['originals'],
    include_raw: true, preview_sha: '9'.repeat(64), confirmed: true, acknowledged_findings_sha: FINDINGS_SHA });
});

test('a withheld preview exports without any finding confirmation', async () => {
  const receipt = { bundle_id: BUNDLE, bundle_sha256: 'd'.repeat(64), size_bytes: 10, item_count: 1,
    manifest_sha256: 'e'.repeat(64), completed_at: '2026-09-23T00:00:00.000000Z', work_id: WORK,
    request_id: REQ, missing: [] };
  const { root, asked, exporter } = panel([scanned(false), receipt]);
  boxes(root).find(el => el.getAttribute('id') === 'export-include-raw').checked = true;
  await exporter.preview();
  boxes(root).find(el => el.getAttribute('id') === 'export-consent').checked = true;
  await buttons(root).find(el => el.textContent === '이 내용으로 내보내기').dispatch('click');
  assert.equal('acknowledged_findings_sha' in asked[1][1].body, false);
  await assert.rejects(exporter.preview({ acknowledged: 'x', selection: { include_raw: true, categories: [] } }));
});
