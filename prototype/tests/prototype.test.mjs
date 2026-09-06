import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { SCENES, MODES, ROLES, DESIGNS, ROUNDS } from '../data.mjs';
import {
  STORAGE_KEY, createState, transition, targetKey, currentDraft,
  loadState, saveState, resetState, hydrate, serialize
} from '../state.mjs';
import { escapeHTML, original, detail, scopeHistory, roleGraph } from '../views.mjs';
import { renderShell } from '../scenes.mjs';
import { createPrototypeServer } from '../server.mjs';

const memoryStorage = () => {
  const entries = new Map();
  return {
    entries,
    getItem: key => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: key => entries.delete(key)
  };
};

test('eight scenes have substantive content in all three modes', () => {
  assert.equal(SCENES.length, 8);
  assert.equal(MODES.length, 3);
  for (const scene of SCENES) for (const mode of MODES) {
    const state = { ...createState(), scene: scene.id, mode: mode.id };
    const html = renderShell(state);
    assert.match(html, new RegExp(`data-current-scene="${scene.id}"`));
    assert.ok(html.includes(scene.title));
    assert.ok(html.includes('화면 시제품 · 예시 자료 · AI/외부 도구 미연결'));
    assert.ok(html.includes('이 탭에만 보관'));
    assert.ok(html.includes('data-scene="V07"'));
    assert.ok(html.includes('data-scene="V08"'));
    if (mode.id === 'conversation') assert.ok(html.includes('id="conversation-draft"'));
    if (mode.id === 'graph') assert.ok(html.includes('aria-label="역할과 산출물 연결"'));
  }
});

test('full artifacts contain actual paragraphs and three distinct structures', () => {
  for (const role of ROLES) {
    assert.ok(role.paragraphs.length >= 3);
    assert.ok(role.text.length > 350);
    for (const paragraph of role.paragraphs) assert.ok(original(createState(), role).includes(paragraph));
  }
  assert.equal(new Set(DESIGNS.map(item => item.structure)).size, 3);
  assert.equal(new Set(DESIGNS.map(item => item.memory)).size, 3);
});

test('role, exact span, and version scope drafts across all navigation', () => {
  let state = createState();
  state = transition(state, { type: 'selection', start: 8, end: 42 });
  const originalKey = targetKey(state);
  state = transition(state, { type: 'draft', text: '내 부분 초안' });
  state = transition(state, { type: 'conversation', text: '설계 검토 메모' });
  for (const scene of SCENES) for (const mode of MODES) {
    state = transition(state, { type: 'scene', value: scene.id });
    state = transition(state, { type: 'mode', value: mode.id });
    assert.equal(targetKey(state), originalKey);
    assert.equal(currentDraft(state).text, '내 부분 초안');
    assert.equal(state.conversations[originalKey], '설계 검토 메모');
  }
  state = transition(state, { type: 'selection', start: 0, end: 7 });
  assert.equal(currentDraft(state).text, '');
  state = transition(state, { type: 'draft', text: '별도 범위' });
  state = transition(state, { type: 'role', value: 'writer' });
  assert.equal(currentDraft(state).text, '');
  state = transition(state, { type: 'draft', text: '다른 역할 초안' });
  state = transition(state, { type: 'role', value: 'organizer' });
  assert.equal(currentDraft(state).text, '별도 범위');
  state = transition(state, { type: 'selection', start: 8, end: 42 });
  assert.equal(targetKey(state), originalKey);
  assert.equal(currentDraft(state).text, '내 부분 초안');
});

test('auxiliary scenes return to entry without changing context', () => {
  let state = transition(createState(), { type: 'scene', value: 'V04' });
  state = transition(state, { type: 'mode', value: 'graph' });
  state = transition(state, { type: 'scene', value: 'V07' });
  state = transition(state, { type: 'scene', value: 'V08' });
  state = transition(state, { type: 'return' });
  assert.equal(state.scene, 'V04');
  assert.equal(state.mode, 'graph');
});

test('auxiliary return restores its first caller context while retaining all edits', () => {
  let state = transition(createState(), { type: 'scene', value: 'V04' });
  state = transition(state, { type: 'mode', value: 'conversation' });
  state = transition(state, { type: 'role', value: 'writer' });
  state = transition(state, { type: 'selection', start: 8, end: 42 });
  const callerKey = targetKey(state);
  state = transition(state, { type: 'draft', text: '진입 전 초안' });
  state = transition(state, { type: 'scene', value: 'V07' });
  state = transition(state, { type: 'selection', start: 50, end: 70 });
  const otherRangeKey = targetKey(state);
  state = transition(state, { type: 'conversation', text: '다른 범위 메모' });
  state = transition(state, { type: 'mode', value: 'graph' });
  state = transition(state, { type: 'role', value: 'reviewer' });
  state = transition(state, { type: 'selection', start: 2, end: 15 });
  const otherRoleKey = targetKey(state);
  state = transition(state, { type: 'draft', text: '보조 화면의 다른 역할 초안' });
  state = transition(state, { type: 'scene', value: 'V08' });
  state = hydrate(serialize(state)).state;
  state = transition(state, { type: 'return' });
  assert.equal(state.scene, 'V04');
  assert.equal(state.mode, 'conversation');
  assert.equal(state.role, 'writer');
  assert.deepEqual(state.selections.writer, { start: 8, end: 42 });
  assert.equal(targetKey(state), callerKey);
  assert.equal(currentDraft(state).text, '진입 전 초안');
  assert.equal(state.conversations[otherRangeKey], '다른 범위 메모');
  assert.equal(state.drafts[otherRoleKey].text, '보조 화면의 다른 역할 초안');
  assert.deepEqual(state.selections.reviewer, { start: 2, end: 15 });
  assert.equal(state.returnContext, null);
});

test('hydration rejects unsafe auxiliary return snapshots', () => {
  const snapshot = { scene: 'V04', mode: 'conversation', role: 'writer', selection: { start: 8, end: 42 } };
  const loaded = context => hydrate(serialize({ ...createState(), scene: 'V07', returnContext: context })).state;
  assert.deepEqual(loaded(snapshot).returnContext, snapshot);
  for (const invalid of [null, [], { ...snapshot, scene: 'V08' }, { ...snapshot, mode: 'bad' },
    { ...snapshot, role: '__proto__' }, { ...snapshot, selection: { start: -1, end: 42 } },
    { ...snapshot, selection: { start: 8, end: 99999 } }]) {
    assert.equal(loaded(invalid).returnContext, null);
  }
  const normal = hydrate(serialize({ ...createState(), returnContext: snapshot })).state;
  assert.equal(normal.returnContext, null);
});

test('exact range is highlighted and prior arbitrary-range drafts remain reachable', () => {
  let state = transition(createState(), { type: 'selection', start: 8, end: 42 });
  state = transition(state, { type: 'draft', text: '이 범위의 내용' });
  assert.ok(original(state).includes(`<mark>${escapeHTML(ROLES[0].text.slice(8, 42))}</mark>`));
  state = transition(state, { type: 'selection', start: 50, end: 70 });
  assert.ok(scopeHistory(state).includes('data-scope="8:42"'));
  for (const design of DESIGNS) {
    const graph = roleGraph({ ...state, scene: 'V02', design: design.id });
    assert.ok(graph.includes(`data-design-graph="${design.id}"`));
    assert.ok(graph.includes(design.structure));
  }
});

test('design and exploration memos do not migrate to other targets', () => {
  let state = transition(createState(), { type: 'field', name: 'designNotes', text: '순차안 메모' });
  state = transition(state, { type: 'design', value: 'parallel' });
  assert.equal(state.designNotes.parallel, undefined);
  assert.equal(state.designNotes.serial, '순차안 메모');
  state = transition(state, { type: 'field', name: 'evidence', text: '이 경로의 메모' });
  assert.ok(detail(state, 'evidence').includes('이 경로의 메모'));
  state = transition(state, { type: 'exploration', value: 'initial' });
  assert.ok(!detail(state, 'evidence').includes('이 경로의 메모'));
});

test('hydration rejects wrong schema and clamps all untrusted fields', () => {
  assert.equal(hydrate('{').valid, false);
  assert.equal(hydrate('{"schema":99,"state":{}}').valid, false);
  const state = createState();
  const key = targetKey(state);
  const raw = JSON.stringify({ schema: 1, state: {
    ...state, scene: '<script>', mode: 'broken', role: '__proto__',
    selections: { organizer: { start: -1, end: 999999 } },
    drafts: { [key]: { text: '유지', revision: 2 }, 'wrong-version': { text: '버림' } },
    conversations: { [key]: '메모', bad: '버림' }, records: ['failure', '<script>']
  } });
  const result = hydrate(raw);
  assert.equal(result.valid, true);
  assert.equal(result.state.scene, 'V01');
  assert.equal(result.state.mode, 'workspace');
  assert.equal(result.state.role, 'organizer');
  assert.deepEqual(result.state.selections.organizer, createState().selections.organizer);
  assert.equal(result.state.drafts[key].text, '유지');
  assert.equal(Object.keys(result.state.drafts).length, 1);
  assert.deepEqual(result.state.records, ['failure']);
});

test('storage reports actual results, preserves drafts, and resets only its key', () => {
  const storage = memoryStorage();
  storage.setItem('unrelated', 'keep');
  let state = transition(createState(), { type: 'draft', text: '재열기 초안' });
  assert.equal(saveState(storage, state).ok, true);
  assert.equal(currentDraft(loadState(storage).state).text, '재열기 초안');
  assert.deepEqual(hydrate(serialize(state)).state, state);
  const blocked = {
    getItem() { throw new Error('blocked'); },
    setItem() { throw new Error('quota'); },
    removeItem() { throw new Error('blocked'); }
  };
  assert.equal(loadState(blocked).ok, false);
  assert.equal(saveState(blocked, state).ok, false);
  assert.equal(resetState(blocked).ok, false);
  assert.equal(currentDraft(state).text, '재열기 초안');
  assert.equal(resetState(storage).ok, true);
  assert.equal(storage.getItem(STORAGE_KEY), null);
  assert.equal(storage.getItem('unrelated'), 'keep');
});

test('failed initial restore prevents automatic writes from replacing the prior snapshot', () => {
  const storage = memoryStorage();
  const previous = '{unreadable prior snapshot';
  storage.setItem(STORAGE_KEY, previous);
  const loaded = loadState(storage);
  assert.equal(loaded.ok, false);
  let state = transition(loaded.state, { type: 'draft', text: '메모리에서 계속 작성' });
  state = transition(state, { type: 'scene', value: 'V04' });
  const result = saveState(storage, state, { readFailed: true });
  assert.equal(result.ok, false);
  assert.match(result.message, /이전 보관본/);
  assert.equal(storage.getItem(STORAGE_KEY), previous);
  assert.equal(currentDraft(state).text, '메모리에서 계속 작성');
  assert.equal(saveState(storage, state).ok, true);
  assert.equal(currentDraft(loadState(storage).state).text, '메모리에서 계속 작성');
});

test('user content escapes from textareas, quoted attributes, and comparisons', () => {
  const attack = '</textarea><img src=x onerror="alert(1)"><script>x</script>&';
  let state = transition(createState(), { type: 'draft', text: attack });
  state = transition(state, { type: 'conversation', text: attack });
  state = transition(state, { type: 'field', name: 'request', text: attack });
  state = transition(state, { type: 'field', name: 'evidence', text: attack });
  for (const scene of SCENES) for (const mode of MODES) {
    const html = renderShell({ ...state, scene: scene.id, mode: mode.id });
    assert.ok(!html.includes('<img src=x'));
    assert.ok(!html.includes('<script>x'));
  }
  assert.equal(escapeHTML('"\'<>&'), '&quot;&#39;&lt;&gt;&amp;');
});

test('absence, hypotheses, all rounds, final evidence, audit and approval are honest', () => {
  const state = { ...createState(), scene: 'V05' };
  const empty = renderShell(state);
  assert.ok(empty.includes('사용자 대안 없음'));
  assert.ok(empty.includes('작성된 대안에서 생성한 설명이 아닙니다'));
  assert.ok(!empty.includes('렌즈'));
  assert.ok(detail(state, 'audit').includes('감사 화면 예시 · 실제 인증 없음'));
  assert.ok(detail(state, 'audit').includes('렌즈 출처: 엔진 미연결'));
  const rounds = renderShell({ ...state, scene: 'V06' });
  for (const round of ROUNDS) assert.ok(rounds.includes(round.label));
  for (const term of ['악화', '실패', '미확인', '별도 최종 확인 자료', 'candidate-3', '실제 적용 미연결']) {
    assert.ok(rounds.includes(term));
  }
});

const request = (port, path, method = 'GET') => new Promise((resolve, reject) => {
  const req = http.request({ hostname: '127.0.0.1', port, path, method }, res => {
    const chunks = [];
    res.on('data', chunk => chunks.push(chunk));
    res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString() }));
  });
  req.on('error', reject);
  req.end();
});

test('server exposes only allowlisted GET assets with security headers', async () => {
  const server = createPrototypeServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const port = server.address().port;
    const page = await request(port, '/');
    assert.equal(page.status, 200);
    assert.match(page.headers['content-type'], /text\/html/);
    assert.match(page.headers['content-security-policy'], /connect-src 'none'/);
    assert.match(page.headers['content-security-policy'], /script-src 'self'/);
    assert.equal(page.headers['x-content-type-options'], 'nosniff');
    const script = await request(port, '/state.mjs');
    assert.equal(script.status, 200);
    assert.match(script.headers['content-type'], /text\/javascript/);
    for (const path of ['/server.mjs', '/README.md', '/tests/prototype.test.mjs', '/.env', '/../README.md', '/%2e%2e/README.md', '/%2fetc/passwd', '/bad%ZZ']) {
      assert.notEqual((await request(port, path)).status, 200);
    }
    assert.equal((await request(port, '/', 'POST')).status, 405);
    assert.equal((await request(port, '/', 'HEAD')).status, 405);
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
});

const browserOptions = { skip: !process.env.PROTOTYPE_PLAYWRIGHT_MODULE };
async function withBrowser(check) {
  const { chromium } = await import(process.env.PROTOTYPE_PLAYWRIGHT_MODULE);
  const server = createPrototypeServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await check(page);
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
}

test('browser: draft inquiry uses the alternative entry and keeps its exact target', browserOptions, async () => {
  await withBrowser(async page => {
    await page.locator('nav [data-scene="V02"]').click();
    await page.locator('[data-exploration="critic"]').click();
    assert.equal(await page.locator('[data-exploration][aria-pressed="true"]').getAttribute('data-exploration'), 'critic');
    await page.locator('nav [data-scene="V04"]').click();
    await page.locator('.role-picker [data-role="writer"]').click();
    await page.locator('[data-paragraph="2"]').click();
    await page.locator('#own-draft').fill('이 범위의 자기 대안');
    const before = JSON.parse(await page.evaluate(key => sessionStorage.getItem(key), STORAGE_KEY)).state;
    await page.getByRole('button', { name: '차이와 새 증거 보기', exact: true }).click();
    assert.equal(await page.locator('[data-exploration][aria-pressed="true"]').getAttribute('data-exploration'), 'alternative');
    const after = JSON.parse(await page.evaluate(key => sessionStorage.getItem(key), STORAGE_KEY)).state;
    assert.equal(after.role, before.role);
    assert.deepEqual(after.selections, before.selections);
    assert.deepEqual(after.drafts, before.drafts);
    for (const entry of ['initial', 'critic']) {
      await page.locator('nav [data-scene="V02"]').click();
      await page.locator(`[data-exploration="${entry}"]`).click();
      assert.equal(await page.locator('[data-exploration][aria-pressed="true"]').getAttribute('data-exploration'), entry);
    }
  });
});

test('browser: stale native selections are rejected and valid button activations remain exact', browserOptions, async () => {
  await withBrowser(async page => {
    await page.locator('nav [data-scene="V04"]').click();
    const text = await page.locator('#original-text p').first().textContent();
    const select = async () => page.evaluate(async () => {
      const captured = new Promise(resolve => document.addEventListener('selectionchange', resolve, { once: true }));
      const paragraph = document.querySelector('#original-text p');
      const range = document.createRange();
      const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
      const point = offset => {
        walker.currentNode = paragraph;
        let node;
        while ((node = walker.nextNode())) {
          if (offset <= node.length) return [node, offset];
          offset -= node.length;
        }
        throw new Error('Missing text offset');
      };
      range.setStart(...point(3));
      range.setEnd(...point(8));
      const selection = getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      await captured;
    });
    await select();
    await page.evaluate(() => getSelection().collapseToEnd());
    await page.locator('#select-range').click();
    assert.equal(await page.locator('#original-text mark').count(), 0);
    assert.match(await page.locator('#selection-feedback').textContent(), /먼저 선택/);
    await select();
    await page.evaluate(() => {
      const range = document.createRange();
      range.selectNodeContents(document.querySelector('#scene-title'));
      getSelection().removeAllRanges();
      getSelection().addRange(range);
    });
    await page.locator('#select-range').click();
    assert.equal(await page.locator('#original-text mark').count(), 0);
    for (const activation of ['click', 'Enter', 'Space']) {
      await select();
      if (activation === 'click') await page.locator('#select-range').click();
      else {
        await page.locator('#select-range').focus();
        await page.keyboard.press(activation);
      }
      assert.equal(await page.locator('#original-text mark').textContent(), text.slice(3, 8));
    }
  });
});
