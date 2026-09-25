// T073: the owner's source deletion panel over a fake document and request. It lists
// stored and deleted originals, previews only a chosen set, shows the server's scope
// and what the deletion cannot reach, requires the separate consent bound to the
// preview digest, refuses a stale preview, and reports removal honestly.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CONFIRM_SCHEMA, ERROR_MESSAGES, MESSAGES, PREVIEW_SCHEMA, createSourceDeletion, deletionRoutes,
} from '../static/source-deletion.mjs';

const WORK = '00000000-0000-4000-8000-00000000c0c1';
const SRC = '00000000-0000-4000-8000-00000000c0c2';
const GONE = '00000000-0000-4000-8000-00000000c0c3';
const REQ = '00000000-0000-4000-8000-00000000c0c4';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map(); this._text = ''; this.checked = false; this.value = ''; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(_value) { throw new Error('markup is never written'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
  async dispatch(type) { for (const listener of this.listeners.get(type) ?? []) await listener({}); }
  findAll(predicate, found = []) { for (const child of this.children) { if (predicate(child)) found.push(child); child.findAll(predicate, found); } return found; }
}

const document = { createElement: tag => new FakeElement(tag) };
const crypto = { randomUUID: () => REQ };

function panel(replies, workId = WORK) {
  const root = new FakeElement('section');
  const asked = [];
  const request = async (path, options) => {
    asked.push([path, options]);
    const reply = typeof replies === 'function' ? replies(path, options) : replies.shift();
    if (reply instanceof Error) throw reply;
    return reply;
  };
  return { root, asked, deletion: createSourceDeletion({ root, document, request, crypto, workId: () => workId }) };
}

const work = { work_id: WORK, source_refs: [{ id: SRC }, { id: GONE }] };
const detail = (id, state, name) => ({ original_state: state, artifact: { name, size: 2048 } });
const view = { request_id: REQ, reason_code: 'user_requested', preview_sha256: 'a'.repeat(64),
  items: [{ source_id: SRC, name: '보고서.pdf', size: 2048, revisions_naming_it: 2, shared_with_other_sources: ['x'] }],
  affected_refs: [], affected_record_count: 4, not_reached: ['backups_made_before_this_deletion', 'copies_already_exported_or_sent'] };
const find = (root, predicate) => root.findAll(predicate)[0];
const button = (root, text) => find(root, el => el.tagName === 'BUTTON' && el.textContent === text);

test('routes are bounded to canonical ids', () => {
  const routes = deletionRoutes('/');
  assert.equal(routes.preview(WORK), `/api/v1/works/${WORK}/deletions/preview`);
  assert.throws(() => routes.preview('../x'));
});

test('stored originals can be chosen; deleted ones are listed but not selectable', async () => {
  const { root, deletion } = panel([work, detail(SRC, 'stored', '보고서.pdf'), detail(GONE, 'deleted', '옛 자료.pdf')]);
  await deletion.load();
  const text = root.textContent;
  assert.match(text, /보고서\.pdf · 2\.0 KiB/);
  assert.match(text, /옛 자료\.pdf · 2\.0 KiB · 삭제됨/);
  const boxes = root.findAll(el => el.tagName === 'INPUT' && el.getAttribute('type') === 'checkbox');
  assert.deepEqual(boxes.map(box => box.getAttribute('value')), [SRC]);
  assert.equal(boxes[0].checked, false);  // nothing preselected
});

test('the preview states scope and reach; consent is separate and bound to the digest', async () => {
  const result = { request_id: REQ, deleted: [{ source_id: SRC, size: 2048, sha256: 'b'.repeat(64), bytes_removed: true }], not_reached: [] };
  const { root, asked, deletion } = panel([work, detail(SRC, 'stored', '보고서.pdf'), detail(GONE, 'deleted', '옛'),
    view, result, { ...work, source_refs: [{ id: SRC }] }, detail(SRC, 'deleted', '보고서.pdf')]);
  await deletion.load();
  await button(root, '삭제 미리보기').dispatch('click');
  assert.match(root.textContent, new RegExp(MESSAGES.choose));
  assert.equal(asked.length, 3);  // nothing chosen: no request
  find(root, el => el.getAttribute('value') === SRC).checked = true;
  await button(root, '삭제 미리보기').dispatch('click');
  assert.deepEqual(asked[3][1].body, { schema_version: PREVIEW_SCHEMA, request_id: REQ, source_ids: [SRC], reason_code: 'user_requested' });
  const text = root.textContent;
  assert.match(text, /이 원본을 가리키는 수정본 2개/);
  assert.match(text, /같은 내용을 가진 다른 원본 1개도 함께/);
  assert.match(text, /영향받는 기록 4개/);
  assert.match(text, /이 삭제 전에 만든 백업/);
  await button(root, '선택한 원본 삭제').dispatch('click');
  assert.match(root.textContent, new RegExp(MESSAGES.needConsent));
  assert.equal(asked.length, 4);
  find(root, el => el.getAttribute('id') === 'deletion-consent').checked = true;
  await button(root, '선택한 원본 삭제').dispatch('click');
  assert.deepEqual(asked[4][1].body, { schema_version: CONFIRM_SCHEMA, request_id: REQ, source_ids: [SRC],
    reason_code: 'user_requested', preview_sha256: 'a'.repeat(64), confirmed: true });
  assert.match(root.textContent, /원본 1개를 삭제했고 파일 제거를 확인했습니다/);
  assert.match(root.textContent, /보고서\.pdf · 2\.0 KiB · 삭제됨/);
});

test('a stale preview is refused and cleared; pending removal is said as pending', async () => {
  const stale = Object.assign(new Error('conflict'), { code: 'conflict' });
  const { root, deletion } = panel([work, detail(SRC, 'stored', 'a'), detail(GONE, 'deleted', 'b'), view, stale]);
  await deletion.load();
  find(root, el => el.getAttribute('value') === SRC).checked = true;
  await deletion.preview();
  find(root, el => el.getAttribute('id') === 'deletion-consent').checked = true;
  await button(root, '선택한 원본 삭제').dispatch('click');
  assert.match(root.textContent, new RegExp(ERROR_MESSAGES.conflict));
  assert.equal(deletion.current, null);
  assert.equal(button(root, '선택한 원본 삭제'), undefined);

  const pending = { request_id: REQ, deleted: [{ source_id: SRC, size: 1, sha256: 'c'.repeat(64), bytes_removed: false }], not_reached: [] };
  const second = panel([work, detail(SRC, 'stored', 'a'), detail(GONE, 'deleted', 'b'), view, pending, work,
    detail(SRC, 'deleted', 'a'), detail(GONE, 'deleted', 'b')]);
  await second.deletion.load();
  find(second.root, el => el.getAttribute('value') === SRC).checked = true;
  await second.deletion.preview();
  find(second.root, el => el.getAttribute('id') === 'deletion-consent').checked = true;
  await button(second.root, '선택한 원본 삭제').dispatch('click');
  assert.match(second.root.textContent, /파일 제거 확인이 아직 끝나지 않았습니다/);
});

test('before the work is saved it says so and requests nothing', async () => {
  const { root, asked, deletion } = panel([], null);
  await deletion.load();
  assert.match(root.textContent, new RegExp(MESSAGES.unsaved));
  assert.equal(asked.length, 0);
});

test('the preview lists the readings erased with the original, the drafts kept, and what backups hold', async () => {
  const withReadings = { ...view, backups: { made_after: 'hold_neither_the_original_nor_text_read_from_it',
    made_before: 'still_hold_both_owner_held_and_not_rewritten' },
  items: [{ ...view.items[0], shared_with_other_sources: [],
    readings: [{ reading_id: 'r1', source_id: SRC, state: 'complete', kept_characters: 10, read_at_utc: 't', text_state: 'stored' },
      { reading_id: 'r2', source_id: SRC, state: 'unreadable', kept_characters: 0, read_at_utc: 't', text_state: 'none' }],
    reading_text_shared_with_other_readings: ['r9'], work_models_from_its_readings: ['m1'] }] };
  const result = { request_id: REQ, not_reached: [], deleted: [{ source_id: SRC, size: 2048, sha256: 'b'.repeat(64),
    bytes_removed: true, readings: [{ reading_id: 'r1', text_removed: true }, { reading_id: 'r2', text_removed: null }] }] };
  const { root, deletion } = panel([work, detail(SRC, 'stored', '보고서.pdf'), detail(GONE, 'deleted', '옛'),
    withReadings, result, { ...work, source_refs: [{ id: SRC }] }, detail(SRC, 'deleted', '보고서.pdf')]);
  await deletion.load();
  find(root, el => el.getAttribute('value') === SRC).checked = true;
  await deletion.preview();
  const text = root.textContent;
  assert.match(text, /이 원본에서 읽은 기록 2건\(읽은 글자 1건은 함께 지웁니다\)/);
  assert.match(text, /같은 글자를 가진 다른 읽기 1건도 "삭제됨"이 됩니다/);
  assert.match(text, /그 읽기로 만든 업무 모델 초안 1개는 남습니다/);
  assert.match(text, /이 삭제 뒤에 만드는 백업에는 이 원본도, 이 원본에서 읽은 글자도 들어가지 않습니다/);
  assert.match(text, /이 삭제 전에 만든 백업에는 원본과 읽은 글자가 그대로 남습니다/);
  assert.match(text, /읽기 기록\(상태·글자 수\)만 남습니다/);
  find(root, el => el.getAttribute('id') === 'deletion-consent').checked = true;
  await button(root, '선택한 원본 삭제').dispatch('click');
  assert.match(root.textContent, /파일 제거를 확인했습니다\. 이 원본에서 읽은 글자 1건도 지웠습니다/);
});
