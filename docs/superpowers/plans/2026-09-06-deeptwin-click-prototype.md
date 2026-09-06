# DeepTwin Local Click Prototype Implementation Plan

> **For agentic workers:** REQUIRED: use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan. Steps use checkbox syntax for tracking.

**Goal:** Build a Korean local click prototype of the approved A shell and V-01–08, with readable fictional artifacts, real range selection, editable drafts, and continuous context across workspace, conversation, and graph modes.

**Architecture:** Native browser modules divide fictional data, validated session state, reusable views, scene rendering, and event handling. A Node HTTP server exposes an explicit static-file allowlist on loopback. Browser inputs stay in memory and, when available, this tab's `sessionStorage`; there are no AI, authentication, external-tool, sending, deployment, or learning integrations.

**Tech Stack:** HTML, CSS, native ES modules, Node built-in HTTP and test modules. No package installation. Use `/Users/soonseekyang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node` on this machine. The README's `node` commands are portable equivalents.

**Authoring status:** The code packet below records the pre-implementation plan committed in `aa1a27d`. Implementation is now in `prototype/`, first committed as `49bd17e`; review-driven changes are recorded at the end rather than retroactively rewriting the original packet. Checkboxes report actual execution. User usability acceptance, engine effects, provider connections, and production storage remain unvalidated.

**Design direction:** A 232px charcoal `#15262C` navigation rail, cool `#F5F8F9` workspace, white reading papers, `#087F83` teal actions, `#203640` ink, and `#A86A16` amber limitations. Korean system sans at 15px supports substantive paragraphs. The persistent artifact ribbon is functional: role, exact input/output versions, and selected range. Version references alone use monospace. The three modes respectively emphasize reading/comparison, reference-bound drafting, and selectable lineage. On small screens the navigation becomes a wrapped top area and papers stack.

**State contract:** Every alternative and conversation draft is keyed by example job/run, role, input version, artifact version, and exact UTF-16 range. Each role remembers its own selection. Text entry is explicitly a design-test draft, not a submitted alternative, request, evidence, or approval. An empty draft means no user alternative exists. Scene/mode switches and detail close do not generate synthetic events. A successful `sessionStorage.setItem` is the only basis for a tab-storage success message. Storage errors remain visible; the current in-memory text remains editable. Session storage normally lasts through reload until the tab closes; browser restore/duplicate behavior is browser-dependent and is not represented as durable or private storage. Reset removes only the namespaced key, and clears in-memory state only after that removal succeeds.

**Scope and evidence:** Reference [UI specification](/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure/docs/superpowers/specs/2026-09-06-deeptwin-ui-structure-design.md) §§1–9 and [review cases](/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure/docs/ui/initial-ui-review-cases.md). Initial design, critic review, and after-alternative exploration remain separate entries. General UI uses work language; only an explicitly labeled audit example exposes lens provenance, with `렌즈 출처: 엔진 미연결`. The fixture library is fictional and newly authored here. No user workflow, previous POC, historical philosopher engine, model score, generated PDF, real execution, or personalized result is claimed.

## Task 1: Implement and verify the complete local prototype

This is one cohesive task because state continuity is the acceptance boundary across all eight surfaces. Keep file responsibilities separate; do not split the task into disconnected screens that invent their own state.

**Create these exact files:**

- `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure/prototype/tests/prototype.test.mjs` — pure state/render and live loopback-server tests.
- `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure/prototype/data.mjs` — fictional source, complete role artifacts, three structures, iteration/evidence/log examples.
- `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure/prototype/state.mjs` — target keys, transitions, validation, tab storage, scoped reset.
- `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure/prototype/views.mjs` — escaped HTML helpers, artifact reader, comparison/editor, contextual modes, detail content.
- `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure/prototype/scenes.mjs` — eight meaningful scene panels and the common shell.
- `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure/prototype/app.mjs` — DOM events, selection capture, focus and dialog handling.
- `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure/prototype/styles.css` — responsive and accessible visual system.
- `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure/prototype/index.html` — static application entry point.
- `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure/prototype/server.mjs` — restricted loopback HTTP server.
- `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure/prototype/README.md` — operation, actual boundaries, and browser acceptance.

Do not stage or overwrite the existing dirty `docs/superpowers/plans/2026-09-06-deeptwin-ui-structure.md`. Use `apply_patch` for implementation edits. Do not install dependencies, create authentication, publish, or update historical review records as if actual connection/engine tests passed.

- [x] **Step 1: Write the failing tests first.** Create only `prototype/tests/prototype.test.mjs` with this complete content.

```js
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
```

- [x] **Step 2: Run the tests and observe the expected failure.** Run from `/Users/soonseekyang/Documents/Deeptwin/.worktrees/ui-structure`:

```sh
/Users/soonseekyang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --test prototype/tests/prototype.test.mjs
```

Expected: exit nonzero with `ERR_MODULE_NOT_FOUND` for `prototype/data.mjs`; record the actual output. If implementation files already exist, inspect them and use the tests to identify the missing behavior instead of overwriting work blindly.

- [x] **Step 3: Implement the fixture and state modules.** Create `prototype/data.mjs`:

```js
export const SCENES = [
  { id: 'V01', title: '업무 입력', subtitle: '자료와 완료 조건을 나란히 확인합니다.' },
  { id: 'V02', title: '설계 비교', subtitle: '역할의 연결과 검토 책임이 다른 세 예시입니다.' },
  { id: 'V03', title: '역할과 산출물', subtitle: '역할별 완결된 원문과 앞뒤 입력을 읽습니다.' },
  { id: 'V04', title: '내 버전', subtitle: '원문 전체 또는 선택한 부분에 자기 내용을 남깁니다.' },
  { id: 'V05', title: '차이와 새 증거', subtitle: '관찰과 설명, 아직 필요한 증거를 구별합니다.' },
  { id: 'V06', title: '반복과 승인 대상', subtitle: '전체 회차와 별도 최종 확인 자료를 읽습니다.' },
  { id: 'V07', title: '연결과 복구', subtitle: '준비 상태와 돌아갈 수 있는 경계를 확인합니다.' },
  { id: 'V08', title: '기록 미리보기', subtitle: '포함 범위와 가림을 검토하고 업무로 돌아갑니다.' }
];
export const MODES = [
  { id: 'workspace', label: '작업공간' },
  { id: 'conversation', label: '대화' },
  { id: 'graph', label: '그래프' }
];
export const CONTEXT = {
  environment: '동네 도서관 · 디자인 테스트', job: 'sample-job-1',
  run: 'sample-run-1', sourceVersion: 'source-v1', environmentVersion: 'environment-example-1'
};
export const SOURCE = [
  '이 자료는 화면 검토를 위해 새로 작성한 가상의 새봄도서관 운영 메모다. 실제 기관, 일정, 모집 공고가 아니다. 안내 대상은 도서관을 처음 방문하는 주민이며, 주말 프로그램의 참여 조건을 한 장의 안내문으로 정리하려 한다.',
  '예시 프로그램 이름은 「함께 만드는 작은 책」이다. 예시 일정은 어느 토요일 오후 2시부터 4시까지, 장소는 1층 이야기방이다. 구체적인 날짜는 아직 정하지 않았다. 참가자는 각자 기억하고 싶은 동네의 모습을 그림이나 짧은 글로 표현하고, 마지막에 작은 책 한 권으로 묶는다.',
  '예시 참여 정원은 어린이와 보호자를 합쳐 12명이다. 어린이는 보호자와 함께 오며, 참여 비용은 없다. 종이와 색연필은 도서관이 준비하고, 개인 사진을 가져오는 것은 선택이다. 접수 방식과 접근성 지원 문의 방법은 담당자의 확인이 필요하다.',
  '작성자는 확정된 항목과 확인이 필요한 항목을 분리해야 한다. 빠진 날짜나 접수 주소를 추정해 채우지 않는다. 검토자는 안내문에서 필요한 준비물, 동반 조건, 미정 항목을 찾을 수 있는지 확인한다. 이 메모를 근거로 한 어떤 문장도 실제 모집이나 예약으로 사용하지 않는다.'
];
const roleData = [
  {
    id: 'organizer', name: '자료 정리', artifact: 'brief', version: 'brief-v1',
    title: '프로그램 자료 정리', input: 'source-v1', upstream: null, downstream: 'writer',
    tool: '제공된 텍스트 읽기 · 이 시제품의 고정 예시',
    paragraphs: [
      '새봄도서관의 「함께 만드는 작은 책」은 화면 검토용 가상 프로그램이다. 주민이 동네의 기억을 그림이나 짧은 글로 옮기고 작은 책으로 묶는 활동을 안내한다. 이 자료 정리는 운영 메모의 확정 항목과 미정 항목을 나누어 다음 작성 역할에 전달하기 위한 완결된 예시 산출물이다.',
      '현재 메모에서 읽을 수 있는 일정은 토요일 오후 2시부터 4시까지이며, 장소는 1층 이야기방이다. 실제 날짜는 없다. 어린이와 보호자를 합친 예시 정원은 12명이고, 어린이는 보호자와 함께 참여한다. 참여 비용이 없다는 조건은 안내문에 넣을 수 있다.',
      '종이와 색연필은 도서관이 준비한다. 개인 사진은 원하는 참여자만 가져오므로 필수 준비물로 바꾸지 않는다. 접수 방식과 접근성 지원 문의 방법은 담당자 확인이 필요하다. 확인 전에는 임의의 주소나 전화번호를 생성하지 않고 미정 상태를 유지한다.',
      '다음 역할에는 참여 대상, 활동 내용, 시간과 장소, 준비물, 확인할 항목 순서로 안내문을 작성하도록 자료를 건넨다. 원문에 없는 모집 시작일이나 확정 날짜를 추가하지 않았는지 검토할 수 있도록 source-v1을 출처로 남긴다. 실제 전달이나 내용 활용을 수행한 기록은 없으며 이 연결은 디자인 테스트 예시다.'
    ]
  },
  {
    id: 'writer', name: '안내문 작성', artifact: 'announcement', version: 'announcement-v1',
    title: '함께 만드는 작은 책 · 안내문', input: 'brief-v1', upstream: 'organizer', downstream: 'reviewer',
    tool: '텍스트 초안 · PDF 연결 전',
    paragraphs: [
      '동네에서 기억하고 싶은 장면이 있나요? 가상의 새봄도서관 「함께 만드는 작은 책」에서는 그 장면을 그림이나 짧은 글로 남기고, 함께 작은 책을 만듭니다. 이 안내문은 디자인 테스트용 예시이며 실제 프로그램의 모집 공고가 아닙니다.',
      '프로그램은 토요일 오후 2시부터 4시까지 1층 이야기방에서 진행하는 설정입니다. 구체적인 날짜는 담당자 확인 뒤 기재할 예정입니다. 어린이는 보호자와 함께 참여하며, 어린이와 보호자를 합친 예시 정원은 12명입니다. 참여 비용은 없습니다.',
      '종이와 색연필은 도서관이 준비하는 것으로 설정되어 있습니다. 개인 사진을 가져오는 것은 선택입니다. 별도의 사진이 없어도 동네의 기억을 글이나 그림으로 표현할 수 있습니다. 처음 작은 책을 만드는 사람도 활동 내용을 이해할 수 있도록 순서를 현장에서 안내한다는 문장은 아직 운영자 확인이 필요합니다.',
      '접수 방법과 접근성 지원 문의 방법은 아직 정해지지 않았습니다. 이 두 항목과 정확한 날짜를 확인한 뒤 실제 안내문으로 사용할 수 있는지 다시 검토해야 합니다. 이 텍스트는 brief-v1을 참고해 준비한 고정 예시이며, PDF 파일 생성이나 외부 게시를 수행하지 않았습니다.'
    ]
  },
  {
    id: 'reviewer', name: '발행 검토', artifact: 'review', version: 'review-v1',
    title: '안내문 발행 전 검토 기록', input: 'announcement-v1', upstream: 'writer', downstream: null,
    tool: '원문 대조 · 외부 게시 미연결',
    paragraphs: [
      '이 검토 기록은 가상의 프로그램 안내문 announcement-v1과 그 앞선 자료 정리 brief-v1을 나란히 읽는 디자인 테스트 예시다. 실제 검토 엔진을 실행한 결과가 아니며, 이 기록의 존재는 안내문 승인이나 발행을 뜻하지 않는다.',
      '안내문은 토요일 오후 시간, 1층 이야기방, 보호자 동반, 합계 12명 정원, 무료 참여 조건을 드러낸다. 종이와 색연필은 제공하고 개인 사진은 선택이라는 원 자료의 구별도 남아 있다. 날짜와 접수 방법이 확정되지 않았다는 점을 지우면 독자가 실제 접수가 가능한 것으로 오해할 수 있다.',
      '현장에서 활동 순서를 안내한다는 내용은 원 운영 메모에 없는 추가 문장이다. 안내문은 이를 운영자 확인 필요로 표시했지만, 실제 발행 전에는 담당자에게 확인하거나 문장을 제외하는 판단이 필요하다. 접근성 지원 문의 경로도 확인 전에는 주소나 연락처를 임의로 채울 수 없다.',
      '따라서 예시 검토 상태는 발행 보류다. 담당자는 정확한 날짜, 접수 방식, 접근성 지원 문의 경로와 현장 안내 여부를 확인해야 한다. 그 뒤 새 안내문 버전을 다시 대조할 수 있다. 외부 게시 요청, 승인 기록, 실제 운영 버전은 현재 없으며 이 문서가 그 공백을 대신하지 않는다.'
    ]
  }
];
export const ROLES = roleData.map(role => ({ ...role, text: role.paragraphs.join('\n\n') }));
export const DESIGNS = [
  { id: 'serial', name: '순차 전달', version: 'design-serial-v1', structure: '자료 정리 → 안내문 작성 → 발행 검토',
    memory: '앞선 역할의 확정 산출물만 다음 역할에 전달', permission: '각 역할은 입력 읽기와 텍스트 출력만 계획',
    reason: '처음 쓰는 업무에서 원문이 안내문으로 바뀌는 과정을 따라가기 쉽습니다.',
    tradeoff: '앞 단계 누락이 뒤로 전달될 수 있어 마지막 원문 대조가 필요합니다.',
    evidence: '설계 근거 예시: 출처와 미정 항목의 책임을 단계별로 나눕니다. 효과 실측 없음.' },
  { id: 'parallel', name: '독립 작성 후 합류', version: 'design-parallel-v1', structure: '원 자료 → 자료 정리 + 안내문 작성 → 발행 검토',
    memory: '정리와 작성은 같은 원 자료를 독립 열람하고 서로의 초안을 보지 않음', permission: '검토 역할만 두 산출물을 함께 읽도록 계획',
    reason: '정리 역할의 누락을 그대로 이어받지 않는 별도 확인 경로를 만듭니다.',
    tradeoff: '두 해석의 불일치를 해결할 합류 검토가 늘어납니다.',
    evidence: '설계 근거 예시: 독립 작성과 비교 책임이 순차안과 다릅니다. 실제 독립 실행 없음.' },
  { id: 'gated', name: '검토 후 되돌림', version: 'design-gated-v1', structure: '자료 정리 → 안내문 작성 → 발행 검토 ↺ 안내문 작성',
    memory: '초안과 검토 기록을 버전별 보존하고 확인된 항목만 수정에 반영', permission: '검토 통과 전 외부 게시 경로를 보류하도록 계획',
    reason: '미정 항목을 해결할 때 새 초안과 이전 검토 기준을 함께 추적합니다.',
    tradeoff: '종료 조건이 없으면 검토가 반복되므로 횟수와 담당자 판단 경계가 필요합니다.',
    evidence: '설계 근거 예시: 재검토와 발행 보류 경계가 추가됩니다. 자동 반복 엔진 없음.' }
];
export const ROUNDS = [
  { id: 'round-1', label: '1회 · 개선 예시', candidate: 'candidate-1', input: 'queue-A / source-v1',
    baseline: '개인 사진을 준비해 주세요.', result: '개인 사진은 선택입니다.',
    status: '개선', evidence: '선택 준비물 구별이 복원된 비교 예시. 독자 이해 효과는 미검증.' },
  { id: 'round-2', label: '2회 · 악화 예시', candidate: 'candidate-2', input: 'queue-A / source-v1',
    baseline: '구체적인 날짜는 담당자 확인 뒤 기재합니다.', result: '토요일에 만나요.',
    status: '악화', evidence: '짧게 만드는 변경에서 날짜 미확정 표시가 사라진 회귀 예시.' },
  { id: 'round-3', label: '3회 · 실패 예시', candidate: 'candidate-2', input: 'queue-B / source-example-B',
    baseline: '접수 방법 확인 필요.', result: '후보 산출물 없음 — 자료 읽기 실패 예시.',
    status: '실패', evidence: '입력 확보 실패는 품질 합격이나 사용자 선호로 해석하지 않습니다.' },
  { id: 'round-4', label: '4회 · 미확인 예시', candidate: 'candidate-3', input: 'queue-C / source-example-C',
    baseline: '접근성 문의 경로 확인 필요.', result: '수행 응답 없음 — 결과 미확인 예시.',
    status: '미확인', evidence: '응답 유실만으로 실패를 확정하거나 외부 행동을 반복하지 않습니다.' }
];
export const RECORDS = [
  { id: 'input', title: '초기 자료', ref: 'source-v1', text: '새로 작성한 가상 운영 메모. 실제 요청 수집 없음.' },
  { id: 'design', title: '설계 비교', ref: 'design-serial-v1', text: '세 구조를 비교하는 고정 예시. 실제 후보 생성 없음.' },
  { id: 'artifact', title: '역할 산출물', ref: 'announcement-v1', text: '읽기용 텍스트가 존재함. 실제 에이전트 실행·PDF 생성 없음.' },
  { id: 'alternative', title: '사용자 대안 범위', ref: 'local-draft', text: '이 고정 예시에 사용자 입력을 포함하지 않음. 작성 초안은 화면 상태로만 보관.' },
  { id: 'inquiry', title: '설명과 보류', ref: 'inquiry-example-1', text: '경쟁 설명 형식 예시. 확보한 새 수행 증거 없음.' },
  { id: 'failure', title: '탈락·실패·결손', ref: 'round-2 / round-3', text: '날짜 누락으로 후보 재검토, 입력 읽기 실패. 예시 담당자: 검토자 A.' },
  { id: 'iteration', title: '회차 비교', ref: 'round-1..4', text: '개선·악화·실패·미확인 전체 회차의 형식 예시.' },
  { id: 'approval', title: '승인·적용', ref: 'candidate-3', text: '승인 기록 없음. 실제 적용 없음. 운영 버전 없음.' }
];
export const EXPLORATIONS = {
  initial: { label: '초기 설계', source: 'source-v1의 미정 날짜·접수 조건', question: '미정 항목을 누가 확인하고 어느 단계에서 보류할까요?' },
  critic: { label: '설계 검토', source: '선택 설계 버전의 역할·권한 계획', question: '정리 역할이 날짜를 빠뜨리면 다음 검토에서 발견할 수 있을까요?' },
  alternative: { label: '내 버전 이후', source: '현재 역할·원본 버전·선택 범위와 사용자 초안', question: '표현 차이가 자료 누락 때문인지, 읽는 순서 때문인지 구별할 새 자료가 필요합니다.' }
};
```

Create `prototype/state.mjs`:

```js
import { SCENES, MODES, ROLES, DESIGNS, ROUNDS, RECORDS, CONTEXT, EXPLORATIONS } from './data.mjs';
export const STORAGE_KEY = 'deeptwin:click-prototype:v1';
const MAX_TEXT = 20000;
const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
const record = value => value && typeof value === 'object' && !Array.isArray(value);
const text = value => typeof value === 'string' ? value.slice(0, MAX_TEXT) : '';
const member = (items, value, fallback) => items.some(item => item.id === value) ? value : fallback;
const validSpan = (span, role) => record(span) && Number.isInteger(span.start) && Number.isInteger(span.end)
  && span.start >= 0 && span.end > span.start && span.end <= role.text.length;
export const roleFor = state => ROLES.find(role => role.id === state.role) ?? ROLES[0];
export const prefixFor = role => `${CONTEXT.job}/${CONTEXT.run}/${role.id}/${role.input}/${role.artifact}@${role.version}/`;
export function createState() {
  return {
    scene: 'V01', returnScene: null, mode: 'workspace', role: ROLES[0].id,
    selections: Object.fromEntries(ROLES.map(role => [role.id, { start: 0, end: role.text.length }])),
    drafts: {}, conversations: {}, request: '', designNotes: {}, evidence: {},
    design: DESIGNS[0].id, exploration: 'alternative', round: ROUNDS[0].id,
    records: ['input', 'artifact', 'failure'], redact: true
  };
}
export function targetKey(state) {
  const role = roleFor(state);
  const span = state.selections[role.id];
  return `${prefixFor(role)}${span.start}:${span.end}`;
}
export const currentDraft = state => state.drafts[targetKey(state)] ?? { text: '', revision: 0 };
export const evidenceKey = state => `${state.exploration}/${state.design}/${targetKey(state)}`;
export function validTarget(key) {
  if (typeof key !== 'string') return false;
  return ROLES.some(role => {
    if (!key.startsWith(prefixFor(role))) return false;
    const match = key.slice(prefixFor(role).length).match(/^(0|[1-9]\d*):(0|[1-9]\d*)$/);
    return match && validSpan({ start: Number(match[1]), end: Number(match[2]) }, role);
  });
}
export function transition(state, action) {
  if (action.type === 'scene') {
    const value = member(SCENES, action.value, state.scene);
    const auxiliary = id => id === 'V07' || id === 'V08';
    return { ...state, scene: value, returnScene: auxiliary(value)
      ? (auxiliary(state.scene) ? state.returnScene : state.scene) : null };
  }
  if (action.type === 'return') return { ...state, scene: state.returnScene ?? 'V03', returnScene: null };
  if (action.type === 'mode') return { ...state, mode: member(MODES, action.value, state.mode) };
  if (action.type === 'role') return { ...state, role: member(ROLES, action.value, state.role) };
  if (action.type === 'selection') {
    const span = { start: action.start, end: action.end };
    if (!validSpan(span, roleFor(state))) return state;
    return { ...state, selections: { ...state.selections, [state.role]: span } };
  }
  if (action.type === 'draft') {
    const previous = currentDraft(state);
    return { ...state, drafts: { ...state.drafts, [targetKey(state)]: {
      text: text(action.text), revision: previous.revision + 1
    } } };
  }
  if (action.type === 'conversation') return { ...state,
    conversations: { ...state.conversations, [targetKey(state)]: text(action.text) } };
  if (action.type === 'field') {
    if (action.name === 'request') return { ...state, request: text(action.text) };
    if (action.name === 'designNotes') return { ...state,
      designNotes: { ...state.designNotes, [state.design]: text(action.text) } };
    if (action.name === 'evidence') return { ...state,
      evidence: { ...state.evidence, [evidenceKey(state)]: text(action.text) } };
  }
  if (action.type === 'design') return { ...state, design: member(DESIGNS, action.value, state.design) };
  if (action.type === 'round') return { ...state, round: member(ROUNDS, action.value, state.round) };
  if (action.type === 'exploration' && own(EXPLORATIONS, action.value)) return { ...state, exploration: action.value };
  if (action.type === 'redact') return { ...state, redact: Boolean(action.value) };
  if (action.type === 'record' && RECORDS.some(item => item.id === action.value)) {
    const records = new Set(state.records);
    action.checked ? records.add(action.value) : records.delete(action.value);
    return { ...state, records: [...records] };
  }
  return state;
}
export function hydrate(raw) {
  try {
    if (typeof raw !== 'string' || raw.length > 1000000) throw new Error('invalid');
    const envelope = JSON.parse(raw);
    if (envelope?.schema !== 1 || !record(envelope.state)) throw new Error('schema');
    const input = envelope.state;
    const state = createState();
    state.scene = member(SCENES, input.scene, state.scene);
    state.mode = member(MODES, input.mode, state.mode);
    state.role = member(ROLES, input.role, state.role);
    state.returnScene = SCENES.some(item => item.id === input.returnScene && !['V07', 'V08'].includes(item.id)) ? input.returnScene : null;
    state.design = member(DESIGNS, input.design, state.design);
    state.round = member(ROUNDS, input.round, state.round);
    if (typeof input.exploration === 'string' && own(EXPLORATIONS, input.exploration)) state.exploration = input.exploration;
    state.request = text(input.request);
    for (const [key, value] of Object.entries(record(input.designNotes) ? input.designNotes : {})) {
      if (DESIGNS.some(item => item.id === key)) state.designNotes[key] = text(value);
    }
    for (const [key, value] of Object.entries(record(input.evidence) ? input.evidence : {})) {
      const [entry, design, ...target] = key.split('/');
      if (own(EXPLORATIONS, entry) && DESIGNS.some(item => item.id === design) && validTarget(target.join('/'))) state.evidence[key] = text(value);
    }
    for (const role of ROLES) {
      const span = input.selections?.[role.id];
      if (validSpan(span, role)) state.selections[role.id] = { start: span.start, end: span.end };
    }
    for (const [key, value] of Object.entries(record(input.drafts) ? input.drafts : {})) {
      if (validTarget(key) && record(value)) state.drafts[key] = {
        text: text(value.text), revision: Number.isSafeInteger(value.revision) && value.revision >= 0 ? value.revision : 0
      };
    }
    for (const [key, value] of Object.entries(record(input.conversations) ? input.conversations : {})) {
      if (validTarget(key)) state.conversations[key] = text(value);
    }
    state.redact = input.redact !== false;
    if (Array.isArray(input.records)) state.records = [...new Set(input.records.filter(id => RECORDS.some(item => item.id === id)))];
    return { valid: true, state };
  } catch {
    return { valid: false, state: createState() };
  }
}
export const serialize = state => JSON.stringify({ schema: 1, state });
export function loadState(storage) {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (raw === null) return { ok: true, state: createState(), message: '아직 보관된 작성 내용이 없습니다.' };
    const result = hydrate(raw);
    return { ok: result.valid, state: result.state, message: result.valid
      ? '이 탭에만 보관된 화면 상태를 불러왔습니다.'
      : '보관 형식이 맞지 않아 복원하지 못했습니다. 기존 값은 아직 덮어쓰지 않았습니다.' };
  } catch {
    return { ok: false, state: createState(), message: '탭 보관을 읽을 수 없습니다. 현재 화면의 메모리에서만 작성합니다.' };
  }
}
export function saveState(storage, state) {
  try {
    const serialized = serialize(state);
    if (serialized.length > 1000000) throw new Error('Prototype tab storage limit');
    storage.setItem(STORAGE_KEY, serialized);
    return { ok: true, message: '이 탭에만 보관 · 마지막 변경 반영됨' };
  } catch {
    return { ok: false, message: '탭 보관 실패 · 이번 변경은 현재 화면 메모리에만 남아 있습니다. 이전 보관본에 이번 변경은 없습니다. 새로고침 전에 내용을 복사하세요.' };
  }
}
export function resetState(storage) {
  try {
    storage.removeItem(STORAGE_KEY);
    return { ok: true, state: createState(), message: '이 시제품의 탭 보관과 작성 내용을 초기화했습니다.' };
  } catch {
    return { ok: false, message: '탭 보관을 지우지 못했습니다. 현재 작성 내용은 유지합니다.' };
  }
}
```

- [x] **Step 4: Implement reusable views and meaningful scenes.** Create `prototype/views.mjs`:

```js
import { SOURCE, ROLES, DESIGNS, ROUNDS, RECORDS, EXPLORATIONS } from './data.mjs';
import { roleFor, targetKey, currentDraft, prefixFor, evidenceKey } from './state.mjs';
export const escapeHTML = value => String(value).replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[character]));
export const e = escapeHTML;
export const button = (label, attribute, value, active = false) =>
  `<button type="button" ${attribute}="${e(value)}"${active ? ' aria-pressed="true"' : ''}>${e(label)}</button>`;
export const detailButton = (label, id) => button(label, 'data-detail', id);
export const sceneButton = (label, id) => button(label, 'data-scene', id);
export const sample = text => `<p class="sample">예시 자료 · ${e(text)}</p>`;
export const paper = (title, body, className = '') => `<section class="paper ${className}"><h2>${e(title)}</h2>${body}</section>`;
export function scopeLabel(state) {
  const role = roleFor(state);
  const span = state.selections[role.id];
  return span.start === 0 && span.end === role.text.length ? `전체 · ${role.text.length}자` : `부분 · ${span.start + 1}–${span.end}자`;
}
export function selectedText(state) {
  const span = state.selections[state.role];
  return roleFor(state).text.slice(span.start, span.end);
}
export function scopeHistory(state) {
  const role = roleFor(state);
  const prefix = prefixFor(role);
  const keys = [...new Set([...Object.keys(state.drafts), ...Object.keys(state.conversations)])]
    .filter(key => key.startsWith(prefix) && (state.drafts[key]?.text.trim() || state.conversations[key]?.trim()));
  if (!keys.length) return '';
  return `<div class="scope-history"><span class="hint">이 역할의 작성 범위로 돌아가기</span><div class="actions">${keys.map(key => {
    const range = key.slice(prefix.length);
    const [start, end] = range.split(':').map(Number);
    const label = start === 0 && end === role.text.length ? '전체 초안' : `부분 ${start + 1}–${end}자 초안`;
    return button(label, 'data-scope', range, key === targetKey(state));
  }).join('')}</div></div>`;
}
export function original(state, role = roleFor(state), selectable = true) {
  let offset = 0;
  const span = state.selections[role.id];
  const paragraphs = role.paragraphs.map((paragraph, index) => {
    const start = offset;
    const end = start + paragraph.length;
    offset = end + 2;
    const selected = role.id === state.role && span.start < end && span.end > start;
    const partial = span.start !== 0 || span.end !== role.text.length;
    const localStart = Math.max(0, span.start - start);
    const localEnd = Math.min(paragraph.length, span.end - start);
    const content = selected && partial
      ? `${e(paragraph.slice(0, localStart))}<mark>${e(paragraph.slice(localStart, localEnd))}</mark>${e(paragraph.slice(localEnd))}`
      : e(paragraph);
    const controls = selectable ? `<button type="button" class="paragraph-choice" data-paragraph="${index}" aria-label="${index + 1}문단 선택">${index + 1}문단 선택</button>` : '';
    return `<div class="paragraph${selected ? ' selected-paragraph' : ''}">${controls}<p data-start="${start}" data-end="${end}">${content}</p></div>`;
  }).join('');
  return `<div class="artifact-meta"><span>${e(role.name)}</span><code>${e(role.version)}</code><span>텍스트 전문 · 고정 예시</span></div>
    <h3>${e(role.title)}</h3>${selectable ? '<p class="hint">문구를 드래그한 뒤 ‘선택한 문구 사용’을 누르거나 문단 버튼을 사용하세요.</p>' : ''}
    <article ${selectable ? 'id="original-text"' : ''} aria-label="${e(role.title)} 전문">${paragraphs}</article>
    ${selectable ? '<div class="actions"><button type="button" id="select-range">선택한 문구 사용</button><button type="button" id="select-whole">전체 선택</button></div><p id="selection-feedback" role="status"></p>' : ''}`;
}
export function draftEditor(state) {
  const draft = currentDraft(state);
  return paper('같은 범위에 내 버전 작성', `
    <p class="scope">${e(scopeLabel(state))} · 원본을 본 뒤 작성하는 디자인 테스트 초안</p>
    <label for="own-draft">내 버전 내용</label>
    <textarea id="own-draft" maxlength="20000" rows="10" placeholder="선택한 범위에 들어갈 자기 내용을 적으세요. 이유는 쓰지 않아도 됩니다.">${e(draft.text)}</textarea>
    <p id="draft-state" class="hint">${draft.text.trim() ? `사용자 작성 초안 · 편집 ${draft.revision}회 · 제출/비교 증거 미확정` : '사용자 대안 없음 · 초안이 비어 있습니다.'}</p>
    <p class="hint">작성 범위만 참조합니다. 실제 검토한 범위·독립 수행 여부는 미확인입니다. 작성은 실행·학습·승인을 시작하지 않습니다.</p>
    ${sceneButton('차이와 새 증거 보기', 'V05')}`);
}
export function roleGraph(state) {
  const node = role => `<div class="graph-node">${button(`${role.name} · ${role.version}`, 'data-role', role.id, state.role === role.id)}<small>텍스트 예시 ${e(role.artifact)}</small></div>`;
  const arrow = '<span class="graph-arrow" aria-label="설계상 예정된 연결">→</span>';
  const design = DESIGNS.find(item => item.id === state.design);
  const designing = state.scene === 'V02';
  let graph = `<div class="role-graph">${ROLES.map(node).join(arrow)}</div>`;
  if (designing && design.id === 'parallel') graph = `<div class="branch-source">${detailButton('공통 원 자료', 'source')}<span>두 역할에 독립 입력 ↓</span></div><div class="graph-branches">${node(ROLES[0])}${node(ROLES[1])}</div><p class="join-label">두 산출물의 합류 ↓</p>${node(ROLES[2])}`;
  if (designing && design.id === 'gated') graph += `<p class="loop-note">검토 보류 시 ↺ ${button('안내문 작성 역할로 되돌림 탐색', 'data-role', 'writer')} · 새 초안 후 다시 검토하는 연결 예시</p>`;
  return paper(designing ? '선택 설계의 역할 구조' : '역할과 산출물 연결', `
    <p class="hint">${designing ? `${e(design.structure)} · ${e(design.version)}` : '고정 순차 예시의 설계상 연결'}입니다. 실제 전달·활용·인과 근거는 없습니다.</p>
    <div aria-label="역할과 산출물 연결" ${designing ? `data-design-graph="${design.id}"` : ''}>${graph}</div>
    <p class="hint">노드는 역할을 선택합니다. 열리는 전문과 입력 버전은 고정 순차 자료 예시이며, 선택 설계로 새 실행한 결과가 아닙니다.</p>
    ${detailButton('선택 산출물 전문 열기', 'original')} ${detailButton('연결 근거 수준', 'lineage')}`, 'graph-paper');
}
export function conversation(state) {
  return paper('현재 대상을 참조하는 대화 초안', `
    <div class="reference"><span>${e(roleFor(state).name)} · ${e(scopeLabel(state))}</span><code>${e(roleFor(state).version)}</code>
    <blockquote>${e(selectedText(state))}</blockquote>${detailButton('전체 문맥 열기', 'original')}</div>
    <p class="sample">디자인 테스트용 작성 영역 · 전송·응답 생성·학습 연결 없음</p>
    <label for="conversation-draft">이 대상에 대한 검토 메모</label>
    <textarea id="conversation-draft" rows="4" maxlength="20000" placeholder="화면을 검토하며 남길 메모">${e(state.conversations[targetKey(state)] ?? '')}</textarea>
    <p class="hint">이 메모를 자기 대안으로 추정하지 않습니다. 교체할 내용은 ‘내 버전’에서 작성하세요.</p>
    ${sceneButton('내 버전 작성 영역 열기', 'V04')}`, 'conversation-paper');
}
export function contextRibbon(state) {
  const role = roleFor(state);
  return `<div class="lineage-ribbon" aria-label="현재 원본과 선택 범위">
    <div><small>선택 역할</small><strong>${e(role.name)}</strong></div>
    <div><small>입력</small><code>${e(role.input)}</code></div><span class="ribbon-arrow">→</span>
    <div><small>출력</small><strong>${e(role.title)}</strong><code>${e(role.version)}</code></div>
    <div><small>원본에서 선택</small><strong>${e(scopeLabel(state))}</strong></div>
    ${detailButton('원본 전문', 'original')}</div>${scopeHistory(state)}`;
}
export function recordPreview(state) {
  const selected = RECORDS.filter(item => state.records.includes(item.id));
  if (!selected.length) return '<p>선택한 기록이 없습니다.</p>';
  return selected.map(item => {
    const content = state.redact ? item.text.replace('검토자 A', '[가림]') : item.text;
    return `<section class="record-preview"><h3>${e(item.title)}</h3><code>${e(item.ref)}</code><p>${e(content)}</p></section>`;
  }).join('');
}
export function detail(state, id) {
  const role = roleFor(state);
  const design = DESIGNS.find(item => item.id === state.design);
  const round = ROUNDS.find(item => item.id === state.round);
  const exploration = EXPLORATIONS[state.exploration];
  const contents = {
    original: `<h2>원본 전문</h2>${original(state, role, false)}`,
    source: `<h2>원 자료 · source-v1</h2>${sample('새로 작성한 가상 운영 메모; 외부 출처 조회 없음')}${SOURCE.map(paragraph => `<p>${e(paragraph)}</p>`).join('')}`,
    tool: `<h2>역할의 도구 준비</h2>${sample('실제 호출 기록 없음')}<p>${e(role.name)}: ${e(role.tool)}</p><p>현재 브라우저 화면·과거 스냅샷·기록 재생은 모두 없습니다. 원본 텍스트는 시제품 파일에서 읽습니다. 도구 입력/결과 시점·권한 확인은 미실시입니다.</p>`,
    lineage: '<h2>연결을 읽는 기준</h2><p>설계상 예정된 연결: 이 화면의 역할 사이 화살표.</p><p>실제 전달 기록: 없음. 관찰된 실행 산출물 계보: 없음. 개입으로 지지된 영향: 없음.</p><p>화살표만으로 다음 역할이 내용을 활용했다거나 원인이 확인됐다고 판단하지 않습니다.</p>',
    design: `<h2>${e(design.name)} 근거</h2>${sample(design.evidence)}<p>${e(design.reason)}</p><p>${e(design.tradeoff)}</p><p>도구 계획: 텍스트 읽기·작성·대조. 외부 계정·PDF·게시 도구 미연결, 권한/비용 검증 전.</p><p>설계 수정 메모는 별도 초안이며 새 구조 생성·검토를 수행하지 않았습니다.</p>`,
    designApproval: `<h2>설계 승인 대상 미리보기</h2><p>예시 대상: ${e(design.version)} / 자료 읽기·안내문 작성·발행 검토의 구조.</p><p>수정 메모는 포함되지 않은 고정 예시 버전입니다. 실제 설계 승인·구성·연결·실행 기록은 없습니다.</p><button disabled>실제 적용 미연결</button>`,
    evidence: `<h2>${e(exploration.label)}의 근거 위치</h2><p>출발: ${e(exploration.source)}</p><p>선택 설계: ${e(design.version)}. 원본: ${e(role.version)} / ${e(scopeLabel(state))}.</p><p>필요한 새 증거: ${e(exploration.question)}</p><p>확보된 실제 새 증거 없음. 아래 메모는 사용자가 쓴 디자인 테스트 초안입니다.</p><pre>${e(state.evidence[evidenceKey(state)] || '작성된 증거 메모 없음')}</pre>`,
    audit: `<h2>감사 화면 예시 · 실제 인증 없음</h2><p>경로: ${e(exploration.label)} / ${e(design.version)} / ${e(role.version)}</p><p>렌즈 출처: 엔진 미연결</p><p>출처 버전·조합/혼합 구성·봉인 기록: 연결 데이터 없음. 탈락/실패의 실제 탐구 이력: 없음.</p><p>초기 설계는 원 자료 조건, 설계 검토는 선택 후보, 내 버전 이후는 원본과 실제 사용자 초안에서 각각 출발하는 정보 구조입니다. 실제 권한 검사·원 수행 입력 주입·질문 생성은 연결되지 않았습니다.</p>`,
    round: `<h2>${e(round.label)}</h2>${sample('실행하지 않은 고정 비교 자료')}<p>입력 ${e(round.input)} · 기준 environment-example-1 · 후보 ${e(round.candidate)}</p><h3>기준 결과 예시</h3><p>${e(round.baseline)}</p><h3>후보 결과 예시</h3><p>${e(round.result)}</p><p>${e(round.evidence)}</p><p>부분 밖 영향: 안내문의 미정 항목과 발행 검토 역할, 다른 프로그램 업무까지 별도 확인이 필요합니다.</p>`,
    final: '<h2>별도 최종 확인 자료</h2><p>고정 후보 candidate-3 / 예시 최종 자료 final-example-D. 이전 튜닝 큐 A·B·C에 포함되지 않은 자료의 위치를 표시합니다.</p><p>최종 자료의 원문·실제 수행 결과·평가 근거는 연결되지 않았습니다. 상태: 확인 전. 앞선 회차를 최종 증거로 재사용하지 않습니다.</p>',
    approval: '<h2>운영 승인 대상 미리보기</h2><p>정확한 예시 대상: candidate-3. 기준: environment-example-1. 변경: 안내문에서 선택 준비물과 미정 조건을 명시하는 규칙.</p><p>예상 영향: 안내문 작성 역할 및 후속 발행 검토, 관련 프로그램 업무. 실제 검증 범위: 없음. 별도 최종 자료 final-example-D는 확인 전.</p><p>사람 승인 기록: 없음. 실제 적용: 없음. 운영 버전·되돌릴 버전: 없음.</p><button disabled>실제 적용 미연결</button>',
    recovery: '<h2>복구 경계 예시</h2><p>읽기 실패: 동일 권한의 원 자료 재조회 가능성을 확인하는 설계 예시이며 재시도를 실행하지 않습니다.</p><p>외부 게시 응답 유실: 성공·실패를 알 수 없어 재실행 보류. 제공자의 요청 기록이나 게시물 존재를 먼저 확인해야 합니다. 확인 경로가 없으면 미확인으로 남깁니다.</p><p>독립 작업: 이미 보유한 원문 읽기와 사용자 초안 편집은 가능합니다. 게시에 의존하는 후속 작업은 보류합니다. 저장한 실행 경계가 없어 실제 에이전트 재개는 지원하지 않습니다.</p>',
    logs: `<h2>추출 전 화면 미리보기</h2>${sample('선택한 고정 예시만 표시; 사용자 입력·자격증명·숨은 추론·다른 앱 자료는 포함하지 않음')}${recordPreview(state)}<p>재현 한계: 실제 호출·원 응답·권한 기록·평가 자료 없음. 파일 생성·다운로드·전송 없음.</p>`
  };
  return contents[id] ?? '<h2>상세 없음</h2><p>연결된 상세 자료가 없습니다.</p>';
}
```

Create `prototype/scenes.mjs`:

```js
import { SCENES, MODES, ROLES, SOURCE, CONTEXT, DESIGNS, ROUNDS, RECORDS, EXPLORATIONS } from './data.mjs';
import { roleFor, currentDraft, evidenceKey } from './state.mjs';
import { e, button, detailButton, sceneButton, sample, paper, original, draftEditor,
  roleGraph, conversation, contextRibbon, selectedText, scopeLabel, recordPreview } from './views.mjs';

function inputScene(state) {
  return `<div class="columns">${paper('업무 설명과 자료', `
    <label for="request-draft">디자인 테스트용 업무 설명</label>
    <textarea id="request-draft" data-field="request" maxlength="20000" rows="7" placeholder="화면에서 확인하고 싶은 업무 설명을 적으세요.">${e(state.request)}</textarea>
    <p class="hint">작성한 내용으로 자료 해석·설계·실행을 만들지 않습니다. 실제 업무 실행·산출물·대안은 아직 없습니다.</p>
    <div class="source-row"><div><strong>가상의 도서관 운영 메모</strong><code>source-v1</code></div>${detailButton('원 자료 전문', 'source')}</div>
    ${sample('고정 자료는 이 시제품에서 읽을 수 있음 · 사용자가 쓴 설명과 별개')}
    ${sceneButton('세 설계 예시 보기', 'V02')}
  `)}${paper('업무 이해 예시', `
    ${sample('작성한 업무 설명을 해석한 결과가 아닙니다')}
    <h3>목적</h3><p>처음 방문하는 주민이 프로그램 조건과 미정 항목을 이해할 수 있는 안내문.</p>
    <h3>완료 조건</h3><p>참여 대상·시간·장소·준비물과 확인이 필요한 항목을 구별합니다.</p>
    <h3>읽은 범위와 빈 곳</h3><p>가상 메모 1–4문단은 전문 열람 가능. 실제 날짜·접수 방식·접근성 문의 방법은 원 자료에 없습니다.</p>
    <p class="warning">외부 자료 조회·첨부 읽기·권한 확인은 미연결입니다.</p>
    ${sceneButton('연결 상태 확인', 'V07')}
  `)}</div>`;
}
function designScene(state) {
  const selected = DESIGNS.find(item => item.id === state.design);
  return `${paper('공통 조건', `${sample('source-v1 기준의 세 고정 설계; 사용자 메모로 새 후보를 생성하지 않음')}<p>미정 날짜를 추정하지 않기 · 선택 준비물을 필수로 바꾸지 않기 · 확인 전 외부 게시 보류</p>`)}
    <div class="design-grid">${DESIGNS.map(design => paper(design.name, `
      <code>${e(design.version)}</code><p class="structure">${e(design.structure)}</p>
      <h3>자료 공유</h3><p>${e(design.memory)}</p><h3>권한·검토 경계</h3><p>${e(design.permission)}</p>
      <h3>선택 이유</h3><p>${e(design.reason)}</p><p class="hint">${e(design.tradeoff)}</p>
      ${button('이 설계 보기', 'data-design', design.id, design.id === state.design)}
    `, design.id === state.design ? 'active-paper' : '')).join('')}</div>
    ${paper(`선택 설계 · ${selected.name}`, `<p>${e(selected.structure)}</p><p>역할: 자료 정리 / 안내문 작성 / 발행 검토. 산출물: 자료 정리 전문 / 안내문 전문 / 검토 전문.</p>
      <p>계획 도구: 텍스트 읽기·작성·대조. 실제 AI·브라우저·PDF·게시 미연결. 연결·권한·비용 검증 전.</p>
      <label for="design-notes">역할·자료·완료 조건 수정 메모</label>
      <textarea id="design-notes" data-field="designNotes" maxlength="20000" rows="3">${e(state.designNotes[state.design] ?? '')}</textarea>
      <p class="hint">수정 메모만 보관합니다. 현재 예시 설계 버전은 그대로이며 새 후보 구성은 미연결입니다.</p>
      <div class="actions">${detailButton('선택 설계 근거', 'design')}${detailButton('설계 승인 대상 미리보기', 'designApproval')}
      ${button('초기 설계 질문', 'data-exploration', 'initial')}${button('이 설계의 반례 검토', 'data-exploration', 'critic')}</div>`)}
  `;
}
function artifactScene(state, editing) {
  const role = roleFor(state);
  const related = [role.upstream, role.downstream].filter(Boolean).map(id => {
    const item = ROLES.find(candidate => candidate.id === id);
    return button(`${id === role.upstream ? '앞선 입력' : '후속 역할'} · ${item.name}`, 'data-role', id);
  }).join('');
  return `<div class="actions role-links">${related}${detailButton('도구·파일 상태', 'tool')}${detailButton('전달 근거 수준', 'lineage')}</div>
    <div class="columns reading-columns">${paper(role.title, `${sample('역할의 완결 텍스트 전문 · 실제 실행 없음')}<p class="hint">입력 ${e(role.input)} → 출력 ${e(role.version)} · PDF 연결 전</p>${original(state)}`)}
    ${editing ? draftEditor(state) : paper('현재 선택과 다음 조작', `<p class="scope">${e(scopeLabel(state))}</p><blockquote>${e(selectedText(state))}</blockquote>
      ${sceneButton('이 범위에 내 버전 작성', 'V04')}<p class="hint">다른 역할을 보고 돌아오면 각 역할의 원래 범위와 초안을 이어 봅니다.</p>`)}</div>`;
}
function inquiryScene(state) {
  const draft = currentDraft(state);
  const entry = EXPLORATIONS[state.exploration];
  const ownContent = draft.text.trim() ? `<h3>사용자가 작성한 디자인 테스트 초안</h3><pre>${e(draft.text)}</pre><p>편집 ${draft.revision}회 · 완성/제출 여부와 비교 증거 성립은 미확정입니다.</p>` : '<p class="empty">사용자 대안 없음 · 현재 원본과 선택 범위에 작성한 내용이 없습니다.</p>';
  return `${paper('탐구의 출발점', `<div class="actions">${Object.entries(EXPLORATIONS).map(([id, value]) => button(value.label, 'data-exploration', id, id === state.exploration)).join('')}</div>
    <h3>${e(entry.label)}</h3><p>${e(entry.source)}</p><p>${e(entry.question)}</p>${detailButton('이 경로의 근거 위치', 'evidence')}`)}
    <div class="columns">${paper('현재 원본과 사용자 작성 상태', `<p>${e(roleFor(state).version)} · ${e(scopeLabel(state))}</p><blockquote>${e(selectedText(state))}</blockquote>${ownContent}
    ${detailButton('원본 전문', 'original')}${sceneButton('내 버전으로 돌아가기', 'V04')}`)}
    ${paper('경쟁 설명을 읽는 예시', `${sample('작성된 대안에서 생성한 설명이 아닙니다. 아래는 고정된 가상 사례입니다.')}
      <h3>관찰 예시</h3><p>원 자료에는 사진이 선택인데 어떤 안내문 예시에는 필수로 표현됐습니다.</p>
      <h3>설명 1 · 전달에서 조건 누락</h3><p>앞선 정리에서 ‘선택’ 표시가 빠졌을 수 있습니다. 원 자료와 실제 전달본 대조가 필요합니다.</p>
      <h3>설명 2 · 읽는 순서의 차이</h3><p>조건은 전달됐으나 준비물 문장 작성에서 놓쳤을 수 있습니다. 같은 자료의 새 수행이 필요합니다.</p>
      <p class="warning">둘 다 가설입니다. 일회성 예외·사용자 대안 오류·시스템 실패 가능성도 남으며 원인은 미확정입니다.</p>
      <label for="evidence-note">필요한 증거 또는 보류 이유 메모 · 선택</label><textarea id="evidence-note" data-field="evidence" rows="4" maxlength="20000">${e(state.evidence[evidenceKey(state)] ?? '')}</textarea>
      <p class="hint">새 수행/응답 증거는 아직 없습니다. 메모만으로 변경 후보나 학습 결과를 만들지 않습니다.</p>
      <div class="actions">${detailButton('감사 상세 예시', 'audit')}${sceneButton('반복 결과 형식 보기', 'V06')}</div>`)}
    </div>`;
}
function iterationScene(state) {
  const round = ROUNDS.find(item => item.id === state.round);
  return `${paper('격리 비교의 기준과 후보', `${sample('아래 회차·상태·결과는 실행하지 않은 고정 예시')}<p>기준 <code>environment-example-1</code> · 선택 회차 후보 <code>${e(round.candidate)}</code> · 입력 <code>${e(round.input)}</code></p><p>실행 권한 없음 · 외부 쓰기 없음 · 현재 사용자 초안에서 생성한 실험 아님</p>`)}
    <div class="columns">${paper('이전 업무 큐 · 전체 회차', `<div class="round-list">${ROUNDS.map(item => button(item.label, 'data-round', item.id, item.id === state.round)).join('')}</div>
      <h3>${e(round.label)}</h3><p>기준 결과 예시: ${e(round.baseline)}</p><p>후보 결과 예시: ${e(round.result)}</p><p>${e(round.evidence)}</p>${detailButton('회차·부분 밖 영향 보기', 'round')}`)}
    ${paper('고정 후보와 별도 최종 확인 자료', `<p>고정 후보 <code>candidate-3</code> · 자료 <code>final-example-D</code></p><p>튜닝 큐와 별도인 자료 위치 예시입니다. 원문·실행·평가 미연결, 확인 전.</p>
      <p>검증할 영향: 선택 문구 밖의 미정 항목, 후속 발행 검토, 관련 프로그램 업무. 실제 검증 범위 없음.</p>
      <div class="actions">${detailButton('별도 최종 확인 자료', 'final')}${detailButton('정확한 운영 승인 대상', 'approval')}</div>
      <button disabled>실제 적용 미연결</button><p class="hint">사람 승인 없음 · 실제 적용 없음 · 운영/되돌릴 버전 없음</p>`)}
    </div>`;
}
function connectionScene() {
  return `<div class="columns">${paper('제공자와 도구 준비', `${sample('연결 기능과 공식 통합은 미구현·미검증')}
    <div class="status-row"><strong>Codex 구독 경로</strong><span>미연결 · 핵심 여정 통합 미검증</span></div>
    <div class="status-row"><strong>Claude 구독 경로</strong><span>미연결 · 핵심 여정 통합 미검증</span></div>
    <div class="status-row"><strong>추가 API 경로</strong><span>선택 안 됨 · 자동 전환 없음</span></div>
    <div class="status-row"><strong>브라우저 / PDF / 게시</strong><span>미지원 · 실제 도구 호출 없음</span></div>
    <p>설계 검토와 초안 편집은 지금 가능합니다. 실제 자료 조회·파일 생성·발행은 연결 전입니다.</p><button disabled>인증 연결 미구현</button>`)}
    ${paper('오류와 재개 경계', `${sample('읽기 실패·외부 결과 미확인·독립 작업의 상태 예시')}
      <h3>자료 읽기 실패</h3><p>자료 정리와 의존하는 새 작성은 보류. 허용 범위의 재조회 조건 확인이 필요합니다.</p>
      <h3>게시 응답 없음</h3><p>외부 결과 미확인. 요청 기록과 실제 게시 여부를 확인하기 전 반복하지 않습니다.</p>
      <h3>계속 가능한 독립 작업</h3><p>이 화면의 고정 원문 열람과 사용자 초안 편집은 계속할 수 있습니다.</p>
      <p class="warning">실제 실행 저장본이 없어 에이전트 재개는 할 수 없습니다. 브라우저 초안 보관 상태는 화면 아래 실제 메시지로 확인합니다.</p>${detailButton('복구 범위와 한계', 'recovery')}`)}</div>
    <button type="button" data-return>원래 장면으로 돌아가기</button>`;
}
function logScene(state) {
  return `<div class="columns">${paper('포함할 기록 예시', `${sample('선택·가림·미리보기만 실제 조작; 추출 파일·전송 없음')}
    <div class="record-options">${RECORDS.map(item => `<label><input type="checkbox" data-record="${e(item.id)}" ${state.records.includes(item.id) ? 'checked' : ''}>${e(item.title)} <code>${e(item.ref)}</code></label>`).join('')}</div>
    <label class="redact-option"><input type="checkbox" id="redact" ${state.redact ? 'checked' : ''}>예시 담당자 이름 가리기</label>
    <p class="hint">공유는 선택 사항입니다. 사용자 초안은 이 고정 기록 묶음에 포함되지 않습니다.</p>${detailButton('추출 전 미리보기 열기', 'logs')}`)}
    ${paper('현재 선택한 내용', `${recordPreview(state)}<p class="warning">결손: 실제 도구 호출·원 응답·권한·평가 자료 없음. 완전한 재현을 보장하지 않습니다.</p><p>추출: 미실행 · 전달 대상: 없음 · 전송: 없음</p>`)}</div>
    <button type="button" data-return>닫고 원래 장면으로 돌아가기</button>`;
}
const scenes = { V01: inputScene, V02: designScene, V03: state => artifactScene(state, false),
  V04: state => artifactScene(state, true), V05: inquiryScene, V06: iterationScene,
  V07: connectionScene, V08: logScene };
export function renderShell(state) {
  const scene = SCENES.find(item => item.id === state.scene);
  const modeIntro = state.mode === 'graph' ? roleGraph(state) : state.mode === 'conversation' ? conversation(state) : '';
  return `<a class="skip-link" href="#scene-title">본문으로 이동</a>
    <aside class="sidebar"><div class="brand">DeepTwin<span>LOCAL UI STUDY</span></div>
      <p class="environment-name">동네 도서관<span>가상의 업무 환경</span></p>
      <nav aria-label="장면 이동">${SCENES.map(item => `<button type="button" data-scene="${item.id}" ${state.scene === item.id ? 'aria-current="page"' : ''}><span>${item.id}</span>${e(item.title)}</button>`).join('')}</nav>
      <p class="sidebar-note">운영 버전 없음<br>예시 환경 <code>environment-example-1</code></p>
    </aside>
    <main id="main" data-current-scene="${state.scene}" data-current-mode="${state.mode}">
      <div class="prototype-banner">화면 시제품 · 예시 자료 · AI/외부 도구 미연결</div>
      <header class="page-heading"><div><p class="eyebrow">${e(CONTEXT.environment)}</p><h1 id="scene-title" tabindex="-1">${e(scene.title)}</h1><p>${e(scene.subtitle)}</p></div>
      <div class="context-refs"><code>${e(CONTEXT.job)}</code><span>실행 참조 예시 <code>${e(CONTEXT.run)}</code> · 실제 실행 없음</span></div></header>
      <div class="mode-bar" aria-label="보기 모드">${MODES.map(mode => button(mode.label, 'data-mode', mode.id, state.mode === mode.id)).join('')}</div>
      ${contextRibbon(state)}
      <div class="role-picker" aria-label="현재 역할">${ROLES.map(role => button(role.name, 'data-role', role.id, state.role === role.id)).join('')}</div>
      <div class="mode-content mode-${state.mode}">${modeIntro}${scenes[state.scene](state)}</div>
      <footer class="storage-footer"><p id="storage-status" role="status"></p><div class="actions"><button type="button" id="storage-retry">탭 보관 다시 시도</button><button type="button" id="reset-prototype">시험용 작성 내용 초기화</button></div>
      <p>이 탭에만 보관 · 보통 탭을 닫으면 종료됩니다. 브라우저의 탭 복원·복제는 다를 수 있습니다. 영구 저장·전송이 아닙니다. 입력 한도: 각 20,000자.</p></footer>
    </main>`;
}
```

- [x] **Step 5: Implement browser control, styling, and entry point.** Create `prototype/app.mjs`:

```js
import { ROLES } from './data.mjs';
import { loadState, saveState, resetState, transition, roleFor, currentDraft } from './state.mjs';
import { renderShell } from './scenes.mjs';
import { detail } from './views.mjs';

const root = document.querySelector('#app');
const dialog = document.querySelector('#detail-dialog');
const detailBody = document.querySelector('#detail-body');
const closeButton = document.querySelector('#detail-close');
let storage;
try { storage = window.sessionStorage; } catch { storage = null; }
let result = loadState(storage);
let state = result.state;
let storageResult = { ok: result.ok, message: result.message };
let lastDetailTrigger = null;
let candidateRange = null;

function showStorage() {
  const status = document.querySelector('#storage-status');
  status.textContent = storageResult.message;
  status.classList.toggle('warning', !storageResult.ok);
}
function persist() {
  storageResult = saveState(storage, state);
  showStorage();
}
function render(focusSelector = null) {
  root.innerHTML = renderShell(state);
  candidateRange = null;
  showStorage();
  if (focusSelector) document.querySelector(focusSelector)?.focus();
}
function change(action, focusSelector = '#scene-title') {
  state = transition(state, action);
  render(focusSelector);
  persist();
}
function openDetail(id, trigger) {
  lastDetailTrigger = trigger;
  detailBody.innerHTML = detail(state, id);
  dialog.showModal();
  closeButton.focus();
}
closeButton.addEventListener('click', () => dialog.close());
dialog.addEventListener('close', () => {
  lastDetailTrigger?.focus({ preventScroll: true });
  lastDetailTrigger = null;
});

// Only ranges within real artifact paragraphs are accepted. Paragraph action
// buttons are siblings and never count toward the canonical text offsets.
function captureSelection() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount !== 1) return;
  const range = selection.getRangeAt(0);
  const container = document.querySelector('#original-text');
  if (!container || !container.contains(range.startContainer) || !container.contains(range.endContainer)) return;
  const paragraphFor = node => (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement)?.closest('p[data-start]');
  const first = paragraphFor(range.startContainer);
  const last = paragraphFor(range.endContainer);
  if (!first || !last || !container.contains(first) || !container.contains(last)) return;
  const offset = (paragraph, node, nodeOffset) => {
    const prefix = document.createRange();
    prefix.selectNodeContents(paragraph);
    prefix.setEnd(node, nodeOffset);
    return Number(paragraph.dataset.start) + prefix.toString().length;
  };
  const start = offset(first, range.startContainer, range.startOffset);
  const end = offset(last, range.endContainer, range.endOffset);
  if (start < end) candidateRange = { start, end, role: state.role };
}
document.addEventListener('selectionchange', captureSelection);
root.addEventListener('pointerup', captureSelection);
root.addEventListener('keyup', captureSelection);
root.addEventListener('pointerdown', event => {
  if (event.target.closest('#select-range')) {
    captureSelection();
    event.preventDefault();
  }
});

root.addEventListener('input', event => {
  const element = event.target;
  if (!(element instanceof HTMLTextAreaElement)) return;
  if (element.id === 'own-draft') state = transition(state, { type: 'draft', text: element.value });
  else if (element.id === 'conversation-draft') state = transition(state, { type: 'conversation', text: element.value });
  else if (element.dataset.field) state = transition(state, { type: 'field', name: element.dataset.field, text: element.value });
  else return;
  persist();
  // Do not replace a composing/focused textarea on each keystroke (Korean IME).
  if (element.id === 'own-draft') {
    const draft = currentDraft(state);
    document.querySelector('#draft-state').textContent = draft.text.trim()
      ? `사용자 작성 초안 · 편집 ${draft.revision}회 · 제출/비교 증거 미확정`
      : '사용자 대안 없음 · 초안이 비어 있습니다.';
  }
});
root.addEventListener('change', event => {
  const element = event.target;
  if (!(element instanceof HTMLInputElement)) return;
  if (element.dataset.record) change({ type: 'record', value: element.dataset.record, checked: element.checked }, `[data-record="${element.dataset.record}"]`);
  if (element.id === 'redact') change({ type: 'redact', value: element.checked }, '#redact');
});
root.addEventListener('click', event => {
  const target = event.target.closest('button');
  if (!target || target.disabled) return;
  if (target.dataset.detail) return openDetail(target.dataset.detail, target);
  if (target.dataset.scene) return change({ type: 'scene', value: target.dataset.scene });
  if (target.dataset.mode) return change({ type: 'mode', value: target.dataset.mode }, `[data-mode="${target.dataset.mode}"]`);
  if (target.dataset.role) return change({ type: 'role', value: target.dataset.role }, '.role-picker [aria-pressed="true"]');
  if (target.dataset.design) return change({ type: 'design', value: target.dataset.design }, `[data-design="${target.dataset.design}"]`);
  if (target.dataset.round) return change({ type: 'round', value: target.dataset.round }, `[data-round="${target.dataset.round}"]`);
  if (target.dataset.exploration) {
    state = transition(state, { type: 'exploration', value: target.dataset.exploration });
    return change({ type: 'scene', value: 'V05' });
  }
  if (target.hasAttribute('data-return')) return change({ type: 'return' });
  if (target.dataset.scope) {
    const [start, end] = target.dataset.scope.split(':').map(Number);
    return change({ type: 'selection', start, end }, `[data-scope="${target.dataset.scope}"]`);
  }
  if (target.dataset.paragraph !== undefined) {
    const index = Number(target.dataset.paragraph);
    const paragraphs = roleFor(state).paragraphs;
    if (!Number.isInteger(index) || index < 0 || index >= paragraphs.length) return;
    const start = paragraphs.slice(0, index).reduce((length, paragraph) => length + paragraph.length + 2, 0);
    return change({ type: 'selection', start, end: start + paragraphs[index].length }, `[data-paragraph="${index}"]`);
  }
  if (target.id === 'select-whole') return change({ type: 'selection', start: 0, end: roleFor(state).text.length }, '#select-whole');
  if (target.id === 'select-range') {
    captureSelection();
    if (!candidateRange || candidateRange.role !== state.role) {
      document.querySelector('#selection-feedback').textContent = '원문 문구를 먼저 선택하세요. 키보드로 문단 선택 버튼을 사용할 수도 있습니다.';
      return;
    }
    return change({ type: 'selection', start: candidateRange.start, end: candidateRange.end }, '#select-range');
  }
  if (target.id === 'storage-retry') return persist();
  if (target.id === 'reset-prototype') {
    if (!window.confirm('이 시제품의 업무 설명·내 버전·대화 메모·화면 선택을 이 탭에서 초기화할까요?')) return;
    const reset = resetState(storage);
    storageResult = reset;
    if (reset.ok) {
      state = reset.state;
      render('#scene-title');
    } else showStorage();
  }
});
render();
```

Create `prototype/styles.css`:

```css
:root {
  color-scheme: light;
  --rail: #15262c;
  --workspace: #f5f8f9;
  --paper: #fff;
  --accent: #087f83;
  --ink: #203640;
  --muted: #526972;
  --line: #d5e1e5;
  --amber: #a86a16;
  font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
  color: var(--ink);
  font-size: 15px;
  background: var(--workspace);
}
* { box-sizing: border-box; }
body { margin: 0; line-height: 1.65; }
button, textarea, input { font: inherit; }
button { cursor: pointer; min-height: 42px; padding: 8px 13px; border: 1px solid var(--line); border-radius: 6px; color: var(--ink); background: white; text-align: left; }
button:hover:not(:disabled) { background: #ecf6f5; border-color: var(--accent); }
button[aria-pressed='true'] { background: #e0f1f0; border-color: var(--accent); color: #06686b; box-shadow: inset 0 -2px var(--accent); }
button:disabled { cursor: not-allowed; opacity: 1; color: #63777e; background: #edf1f2; border-style: dashed; }
:focus-visible { outline: 3px solid #b56b0b; outline-offset: 3px; }
h1, h2, h3, p { margin-top: 0; }
h1 { font-size: clamp(25px, 2.5vw, 35px); line-height: 1.25; letter-spacing: -.035em; margin-bottom: 9px; }
h2 { font-size: 19px; line-height: 1.4; letter-spacing: -.025em; margin-bottom: 17px; }
h3 { font-size: 15px; line-height: 1.5; margin: 20px 0 8px; }
p { margin-bottom: 15px; }
small, .hint { font-size: 13px; color: var(--muted); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; overflow-wrap: anywhere; }
pre { font: inherit; white-space: pre-wrap; overflow-wrap: anywhere; padding: 16px; background: var(--workspace); border: 1px solid var(--line); }
label { display: block; font-weight: 600; margin-bottom: 8px; }
textarea { display: block; width: 100%; resize: vertical; min-height: 100px; padding: 13px; border: 1px solid #9caeb6; border-radius: 5px; background: white; color: var(--ink); line-height: 1.75; margin-bottom: 12px; }
input[type='checkbox'] { accent-color: var(--accent); width: 18px; height: 18px; flex-shrink: 0; }
blockquote { margin: 12px 0 18px; padding: 14px 17px; border-left: 3px solid var(--accent); background: #f3f8f8; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; }
.skip-link { position: fixed; z-index: 20; top: -80px; left: 16px; padding: 10px 20px; background: white; color: var(--ink); }
.skip-link:focus { top: 10px; }
.sidebar { position: fixed; inset: 0 auto 0 0; width: 232px; padding: 30px 18px 22px; background: var(--rail); color: #eff6f6; display: flex; flex-direction: column; overflow-y: auto; }
.brand { font-weight: 750; font-size: 26px; letter-spacing: -.04em; padding: 0 12px; }
.brand span { display: block; color: #9db9bf; font-size: 10px; letter-spacing: .12em; margin-top: 2px; }
.environment-name { margin: 34px 12px 24px; font-weight: 600; }
.environment-name span { display: block; font-size: 12px; color: #a8bec3; font-weight: 400; }
.sidebar nav { display: grid; gap: 6px; }
.sidebar nav button { display: flex; gap: 11px; border: none; background: transparent; color: #d4e4e7; width: 100%; padding: 10px 11px; border-radius: 4px; }
.sidebar nav button span { color: #99b4bb; font-size: 12px; align-self: center; }
.sidebar nav button:hover { background: #244047; }
.sidebar nav button[aria-current] { color: white; background: #245158; box-shadow: inset 3px 0 #71d2cc; }
.sidebar-note { margin: auto 12px 0; padding-top: 28px; font-size: 12px; color: #a8bec3; }
.sidebar-note code { display: block; margin-top: 5px; }
main { margin-left: 232px; padding: 0 35px 24px; max-width: 1800px; min-width: 0; }
.prototype-banner { font-size: 12px; color: #3d5a63; border-bottom: 1px solid var(--line); padding: 12px 0; letter-spacing: .015em; }
.page-heading { display: flex; justify-content: space-between; gap: 24px; padding: 27px 0 18px; align-items: flex-end; }
.page-heading > div { min-width: 0; }
.page-heading p { margin-bottom: 0; color: var(--muted); }
.page-heading .eyebrow { font-size: 12px; margin-bottom: 9px; }
.context-refs { text-align: right; display: grid; gap: 4px; max-width: 270px; font-size: 11px; color: var(--muted); }
.mode-bar { display: flex; border-bottom: 1px solid var(--line); gap: 18px; margin-bottom: 18px; }
.mode-bar button { border: 0; background: transparent; border-radius: 0; min-width: 76px; text-align: center; padding: 11px 6px; }
.mode-bar button[aria-pressed='true'] { color: var(--accent); box-shadow: inset 0 -3px var(--accent); font-weight: 700; }
.lineage-ribbon { display: flex; align-items: center; flex-wrap: wrap; gap: 15px; border: 1px solid #bad4d7; border-left: 3px solid var(--accent); padding: 14px 18px; background: #edf6f5; margin-bottom: 14px; }
.lineage-ribbon > div { min-width: 90px; display: grid; gap: 1px; }
.lineage-ribbon strong { font-size: 13px; }
.lineage-ribbon button { margin-left: auto; }
.ribbon-arrow { color: var(--accent); }
.role-picker { display: flex; flex-wrap: wrap; gap: 7px; margin: 0 0 21px; }
.role-picker button { font-size: 13px; min-height: 36px; padding: 5px 11px; }
.mode-content { min-width: 0; }
.paper { min-width: 0; background: var(--paper); border: 1px solid var(--line); border-radius: 7px; padding: 23px; margin-bottom: 20px; overflow-wrap: anywhere; }
.paper > :last-child { margin-bottom: 0; }
.columns { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 20px; align-items: start; }
.reading-columns { grid-template-columns: minmax(0, 1.45fr) minmax(270px, 1fr); }
.design-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 15px; }
.design-grid .paper { padding: 20px; }
.active-paper { border-color: var(--accent); box-shadow: inset 0 3px var(--accent); }
.structure { font-weight: 700; margin-top: 15px; padding-bottom: 15px; border-bottom: 1px solid var(--line); }
.sample { color: #596f78; background: #f0f5f7; padding: 8px 11px; border-radius: 3px; font-size: 12px; }
.warning { color: #815110; background: #fff5e6; padding: 10px 12px; border-left: 3px solid var(--amber); font-size: 13px; }
.actions { display: flex; flex-wrap: wrap; gap: 9px; margin: 15px 0; }
.source-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; border: 1px solid var(--line); padding: 15px; margin: 21px 0 12px; }
.source-row > div { min-width: 0; }
.source-row code { display: block; margin-top: 4px; }
.artifact-meta { display: flex; flex-wrap: wrap; gap: 9px; color: var(--muted); font-size: 11px; margin-top: 20px; }
.paragraph { position: relative; padding: 0 0 17px 13px; border-left: 2px solid transparent; margin-bottom: 15px; }
.paragraph p { line-height: 1.9; margin: 8px 0 0; white-space: pre-wrap; }
.paragraph-choice { color: var(--muted); font-size: 11px; min-height: 30px; padding: 3px 8px; background: #f8fafb; }
.selected-paragraph { border-color: #79b9b8; }
.selected-paragraph .paragraph-choice { color: #076e72; border-color: #83bcbe; }
mark { color: inherit; background: #ceece7; padding: 0; }
::selection { color: #102f33; background: #abe5df; }
.scope { color: #076e72; font-size: 13px; font-weight: 600; }
.empty { padding: 20px; background: #f6f8f9; border: 1px dashed #9caeb6; color: var(--muted); }
.round-list { display: grid; gap: 8px; margin-bottom: 20px; }
.status-row { display: grid; grid-template-columns: minmax(120px, .8fr) minmax(0, 1fr); gap: 15px; padding: 15px 0; border-bottom: 1px solid var(--line); }
.status-row span { font-size: 13px; }
.record-options { display: grid; gap: 12px; }
.record-options label, .redact-option { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; font-size: 13px; font-weight: 400; }
.redact-option { margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--line); }
.record-preview { padding: 0 0 15px; border-bottom: 1px solid var(--line); margin-bottom: 14px; }
.record-preview h3 { margin: 0; }
.record-preview p { margin: 9px 0 0; }
.graph-paper { background: #f8fcfc; }
.role-graph { display: flex; align-items: center; gap: 11px; margin: 20px 0; }
.graph-node { flex: 1; min-width: 0; display: grid; gap: 7px; }
.graph-node button { min-height: 66px; width: 100%; }
.graph-node small { font-size: 11px; }
.graph-arrow { color: var(--accent); font-size: 24px; }
.branch-source { display: flex; align-items: center; gap: 15px; flex-wrap: wrap; margin: 20px 0; }
.graph-branches { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 25px; padding: 15px; border-top: 2px solid #83bcbe; border-bottom: 2px solid #83bcbe; }
.join-label { color: var(--accent); margin: 12px 0; text-align: center; }
.loop-note { border-left: 2px solid var(--accent); padding: 12px; background: #eaf5f3; }
.conversation-paper { border-top: 3px solid var(--accent); max-width: 900px; }
.reference { padding: 12px 15px; border-left: 2px solid var(--accent); margin-bottom: 18px; }
.reference > span, .reference > code { display: block; font-size: 12px; }
.reference blockquote { max-height: 140px; font-size: 13px; }
.mode-conversation .columns { grid-template-columns: minmax(0, 1fr); max-width: 900px; }
.mode-graph .reading-columns { grid-template-columns: minmax(0, 1.2fr) minmax(260px, 1fr); }
.storage-footer { border-top: 1px solid var(--line); margin-top: 20px; padding-top: 18px; color: var(--muted); font-size: 12px; }
.storage-footer p { margin-bottom: 7px; }
.storage-footer button { font-size: 12px; }
dialog { width: min(760px, calc(100vw - 32px)); max-height: calc(100dvh - 40px); padding: 0; border: 1px solid var(--line); border-radius: 9px; color: var(--ink); background: white; overflow: auto; }
dialog::backdrop { background: rgb(13 35 42 / 45%); }
.dialog-header { position: sticky; top: 0; z-index: 1; padding: 12px 20px; border-bottom: 1px solid var(--line); background: white; display: flex; justify-content: space-between; align-items: center; gap: 15px; }
.dialog-header span { color: var(--muted); font-size: 12px; }
#detail-body { padding: 25px; overflow-wrap: anywhere; }
@media (min-width: 1700px) { main { padding-left: 50px; padding-right: 50px; } }
@media (max-width: 1200px) {
  main { padding-left: 24px; padding-right: 24px; }
  .design-grid { grid-template-columns: minmax(0, 1fr); }
  .design-grid .paper { margin-bottom: 0; }
  .design-grid { margin-bottom: 20px; }
  .columns, .reading-columns, .mode-graph .reading-columns { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .page-heading { align-items: flex-start; }
  .context-refs { max-width: 170px; }
}
@media (max-width: 760px) {
  .sidebar { position: static; width: 100%; padding: 17px 16px; overflow: visible; }
  .brand { font-size: 22px; padding: 0; }
  .brand span { display: inline; margin-left: 12px; font-size: 9px; }
  .environment-name, .sidebar-note { display: none; }
  .sidebar nav { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 7px; margin-top: 13px; }
  .sidebar nav button { font-size: 12px; padding: 7px 8px; min-height: 38px; }
  .sidebar nav button span { font-size: 10px; }
  main { margin-left: 0; padding: 0 16px 20px; }
  .prototype-banner { font-size: 10px; }
  .page-heading { display: block; padding-top: 21px; }
  .context-refs { max-width: none; text-align: left; margin-top: 10px; }
  .lineage-ribbon { gap: 13px; padding: 12px; }
  .lineage-ribbon > div { min-width: 0; max-width: 100%; }
  .lineage-ribbon button { margin-left: 0; }
  .lineage-ribbon strong { font-size: 12px; }
  .ribbon-arrow { display: none; }
  .paper { padding: 18px 16px; }
  .source-row { flex-direction: column; align-items: flex-start; }
  .role-graph { flex-direction: column; align-items: stretch; }
  .graph-arrow { text-align: center; transform: rotate(90deg); line-height: 1; }
  .graph-node button { min-height: 50px; }
  .graph-branches { grid-template-columns: minmax(0, 1fr); }
  .status-row { grid-template-columns: minmax(0, 1fr); gap: 3px; }
  .mode-bar { gap: 13px; }
  #detail-body { padding: 20px 16px; }
}
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; } }
```

Create `prototype/index.html`:

```html
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light">
    <title>DeepTwin · 화면 시제품</title>
    <link rel="icon" href="data:,">
    <link rel="stylesheet" href="/styles.css">
    <script type="module" src="/app.mjs"></script>
  </head>
  <body>
    <div id="app"></div>
    <dialog id="detail-dialog" aria-label="대상 상세">
      <div class="dialog-header"><span>대상·버전·작성 상태를 유지한 상세</span><button type="button" id="detail-close">닫기</button></div>
      <div id="detail-body"></div>
    </dialog>
    <noscript>이 로컬 시제품의 이동과 초안 편집에는 JavaScript가 필요합니다.</noscript>
  </body>
</html>
```

- [x] **Step 6: Add the restricted local server and operational README.** Create `prototype/server.mjs`:

```js
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
```

Create `prototype/README.md`:

````md
# DeepTwin 로컬 화면 시제품

A 골격에서 V-01–08과 작업공간·대화·그래프 이동을 검토하는 한국어 클릭 시제품입니다. 모든 기관·자료·시스템 결과·사건은 새로 작성한 고정 예시입니다. 실제 AI, 외부 도구, 인증, 과금, PDF 생성, 전송, 학습, 평가, 승인, 운영 적용은 연결되지 않았습니다.

## 실행

저장소 작업 폴더에서 Node를 사용합니다. 패키지 설치는 필요하지 않습니다.

```sh
node prototype/server.mjs
```

[로컬 시제품](http://127.0.0.1:4173)을 엽니다. 서버는 `127.0.0.1`에만 바인딩하며 포트를 바꾸려면 `PORT=4174 node prototype/server.mjs`를 사용합니다. 정수 1–65535만 허용합니다. 종료는 실행한 터미널에서 Ctrl+C입니다.

이 기기의 Node 경로는 `/Users/soonseekyang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`입니다. 이 절대 경로로 위의 `node`를 대체할 수 있습니다.

```sh
node --test prototype/tests/prototype.test.mjs
```

서버는 명시된 HTML/CSS/브라우저 모듈만 제공합니다. 서버 소스·테스트·README·저장소 파일은 제공하지 않습니다. GET 외 요청, 경로 순회, 숨김 파일 접근은 거절합니다. CSP가 외부 연결과 인라인 스크립트를 막으며 요청 내용은 기록하지 않습니다.

## 실제 조작과 작성 내용

장면·모드·역할·설계·회차 이동, 원문 전문, DOM 문구 선택과 문단 선택, 자기 초안과 대화 메모, 상세 열기/닫기, 예시 기록 포함/가림이 작동합니다. 승인 버튼은 정확한 대상을 보여 주는 미리보기입니다. 실제 적용 버튼은 비활성입니다.

대화 메모는 디자인 테스트 초안입니다. 전송되거나 자기 대안·학습 증거로 해석되지 않습니다. 자기 버전 역시 사용자 작성 초안이며 완료·제출·실제 비교 증거를 자동 확정하지 않습니다. 사용자가 쓴 내용과 고정된 시스템 결과 예시는 연결해 생성하지 않습니다.

각 역할의 선택 범위와 원본 버전마다 자기 초안·대화 초안이 따로 남습니다. 범위를 바꿨다가 돌아오면 그 범위의 초안을 불러옵니다. 원본은 UTF-16 문자 위치와 문단 사이 두 줄바꿈으로 범위를 식별합니다. 이유 입력이나 전체 문서 완성은 필수가 아닙니다. 입력은 필드당 20,000자까지입니다.

## 탭 보관과 초기화

메모리 상태를 `sessionStorage`의 `deeptwin:click-prototype:v1` 키에 보관합니다. 성공한 쓰기 뒤에만 `이 탭에만 보관 · 마지막 변경 반영됨`을 표시합니다. 같은 탭 새로고침에서 불러올 수 있고 보통 탭을 닫으면 끝납니다. 브라우저의 탭 복원·복제 정책에 따라 복원되거나 사본이 생길 수 있어 비밀 보관이나 영구 저장을 보장하지 않습니다. 서버·계정·다른 서비스로 전송하지 않습니다.

저장 차단/할당량 오류 때는 경고를 표시하고 현재 메모리의 작성 내용을 유지합니다. 새로고침 전에 필요한 내용을 직접 복사하세요. `탭 보관 다시 시도`는 현재 상태 쓰기를 다시 시도합니다. `시험용 작성 내용 초기화`는 확인 후 이 시제품 키만 지웁니다. 키 삭제가 실패하면 화면 상태도 유지합니다. 다른 앱의 저장 키는 지우지 않습니다. 스키마 또는 원본 버전과 맞지 않는 데이터는 임의 연결하지 않습니다.

## 브라우저 확인 절차

1. 데스크톱에서 V03을 열고 안내문 작성 역할을 선택합니다. 전문의 3문단을 읽고 문단 버튼으로 선택한 뒤 V04에서 `사진은 가져오고 싶은 분만 준비합니다.`를 적습니다. 원본·입력 버전·부분 범위를 확인합니다.
2. 같은 화면의 대화·그래프·작업공간을 모두 오갑니다. 선택 범위와 초안이 유지되는지 확인합니다. 대화에 별도 메모를 쓰고 다시 돌아와 그 내용도 확인합니다. 그래프에서는 역할 버튼으로 산출물을 선택할 수 있어야 합니다.
3. 발행 검토 역할을 선택합니다. 앞서 작성한 초안이 이 역할의 내용으로 나타나면 실패입니다. 다른 내용을 작성한 뒤 안내문 작성으로 돌아와 원래 3문단 초안이 남아 있는지 확인합니다.
4. 원문의 실제 글자 일부를 마우스 드래그 또는 키보드 DOM 선택하고 `선택한 문구 사용`을 누릅니다. 부분 범위가 선택한 실제 문자열과 일치하는지, 새 범위에 별도 자기 초안을 적은 뒤 원래 문단으로 돌아왔을 때 기존 초안이 살아 있는지 확인합니다. 전체 선택도 확인합니다.
5. `원본 전문`과 근거 상세를 열고 Escape로 닫습니다. 같은 역할·버전·범위·작성 내용과 상세를 열었던 버튼의 초점으로 돌아와야 합니다. 닫기 버튼으로도 같습니다.
6. V01 설명·V02 세 구조와 근거·V03 전문·V04 빈/작성 초안·V05 세 진입과 가설/증거·V06 모든 회차/별도 최종 근거/정확한 승인 대상·V07 연결/복구·V08 포함/가림을 세 모드에서 확인합니다. V07/V08은 어느 단계에서든 열리고 원래 장면으로 돌아옵니다.
7. 새 탭 또는 초기화 상태에서 V05를 읽습니다. 실제 사용자 대안이 없고 고정 가설 예시가 별도라는 표시가 있어야 합니다. 감사 상세에만 출처 정보가 있고 실제 인증·엔진이 없음을 표시해야 합니다.
8. 같은 탭 새로고침 후 보관된 역할·선택·작성 내용을 확인합니다. 개발자 도구 또는 테스트 초기 스크립트로 `Storage.prototype.setItem`을 예외로 바꾸고 입력했을 때 실패 경고와 메모리 초안 유지도 확인합니다. `getItem`이 차단된 시작 상태와 `removeItem` 실패 초기화도 별도로 확인합니다.
9. 390px 너비에서 모든 장면/모드에 대해 문서 가로 스크롤이 없는지, 키보드 초점이 보이는지, 원문·편집·모달이 읽히는지 확인합니다. 긴 사용자 문자열과 한국어 IME 입력을 포함합니다. 모바일 모달 내부는 세로 스크롤을 허용합니다.
10. 브라우저 네트워크/콘솔에서 외부 요청·스크립트 오류가 없고, 입력한 `<script>`나 `</textarea>`가 실행되지 않는지 확인합니다. 승인·인증·게시·파일 추출이 완료됐다는 거짓 알림이 없어야 합니다.

자동 브라우저 확인은 저장소 의존성을 추가하지 않고 번들 Playwright와 설치된 Chrome의 `chromium.launch({ channel: 'chrome', headless: true })`를 사용할 수 있습니다. 번들 브라우저가 없다는 이유로 설치하지 않습니다. DOM 테스트와 스크린샷은 사람의 실제 화면 선택, 연결 시험, 엔진 효과 검증을 대신하지 않습니다.
````

- [x] **Step 7: Run the tests and correct real failures.** Use the exact Step 2 command. Expected: all tests pass. Inspect each failure; do not weaken evidence, isolation, escaping, or server restrictions to make a test pass. Run `git diff --check` after edits.

- [x] **Step 8: Start the server and inspect the actual browser.** Run:

```sh
/Users/soonseekyang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node prototype/server.mjs
```

Use the running terminal session; open `http://127.0.0.1:4173` in the Codex browser panel. Use the README's exact browser procedure. For independent automated acceptance, root can use bundled Playwright with installed Chrome (`channel: 'chrome'`). Do not install browser/dependency packages. Check 1440px and 390px, actual DOM range selection, Korean input continuity, modal Escape/focus, role/span draft isolation, same-tab reload, blocked/quota storage, and all 24 scene/mode combinations. Save screenshots and actual results in the root worker's designated observation record; do not rewrite historical UI/engine verification fields. If visual or behavior findings require code changes, correct them and repeat only affected checks.

- [x] **Step 9: Review, commit the scoped implementation, and hand off the running UI.** Inspect `git status --short`, the explicit prototype diff, and the actual browser results. Commit only these new prototype files after tests and browser checks pass:

```sh
git add prototype/tests/prototype.test.mjs prototype/data.mjs prototype/state.mjs prototype/views.mjs prototype/scenes.mjs prototype/app.mjs prototype/styles.css prototype/index.html prototype/server.mjs prototype/README.md
git commit -m "feat: add local DeepTwin click prototype"
```

The root worker decides how the approved scope/plan/observation documents are committed separately. Do not stage the older dirty plan. Hand off the local URL, the verification actually run, and the limits (synthetic examples; no AI/auth/tools/PDF/sending/learning). Leave the local server available for the user's screen review if the execution environment supports a persistent session.

## Root self-review and execution handoff

The root worker read the complete plan against UI §9.3 and §§6/9. All eight scenes and three modes map to scene/render/state code and browser checks; original text, exact partial selection, empty alternative state, separate exploration entries, every queue outcome, final evidence/approval target, auxiliary return, and optional log preview are covered. No placeholder code remains. Export names, event hooks, state keys and saved range history were checked across modules. The review corrected exact-range visual highlighting and selected-design graph consistency, and retained scoped design/exploration drafts and explicit storage-size failure.

Node syntax checks of all seven JavaScript blocks passed before implementation; this is not a runtime test. The existing linked worktree and old dirty plan were verified and preserved. The user's established preference is fresh implementation worker followed by independent specification and quality reviews. Execute continuously within the approved click-prototype scope; no further generic execution-choice question is needed. Actual screen observation and provider/engine verification remain separate.

## Execution and review record — 2026-09-06

The initial implementation of all ten files was committed in `49bd17e`. The first missing-module test failure established that the test command was wired before implementation; it was setup evidence, not a behavioral regression demonstration. Later regressions were reproduced as real assertion failures before their fixes. The original packet above is historical: the runtime source is authoritative for subsequent fixes.

Root's first full verification passed 14 Node tests and 20 browser groups, including 48 viewport/scene/mode combinations. During construction, auxiliary return was strengthened from a scene-only reference to an origin mode/role/span snapshot, and unreadable initial storage now blocks automatic replacement until explicit confirmation. These changes preserve the original target/draft and storage-honesty contracts rather than expanding the product scope.

A fresh independent specification reviewer re-read the code and reran 14 tests and all 48 view combinations. Two interaction findings prevented specification approval: V04's exploration link retained a previously selected initial/critic entry, and a cancelled native text selection could apply a stale range. Both were corrected with real DOM regressions in `4fad833`; the same reviewer independently reran all 16 tests (zero skipped) and returned `SPEC_PASS`. Root then passed all 16 tests and an expanded 22-group browser suite. A fresh quality reviewer follows this specification pass. User-facing engine work is not added to resolve these UI findings.

Actual browser verification and its limits are recorded separately in [the observation record](../../ui/initial-ui-review-cases.md#클릭-시제품-에이전트-검증). The local server is available at [127.0.0.1:4173](http://127.0.0.1:4173/) and the visible Codex browser was opened and refreshed after code changes. Opening it does not establish user acceptance. The protected older dirty UI plan remains outside every implementation commit.

The fresh quality reviewer read all ten files, independently passed 16 tests including both real-DOM cases, and returned `QUALITY_PASS` with no Critical/Important issues. One Minor was nevertheless selected for correction: HTML textarea parsing dropped a leading newline on rerender, which could become a saved edit on subsequent input. All five editable fields must preserve zero, one, and multiple leading newlines. A focused regression and final re-review follow; no new product feature is introduced.

Final result: `d6dfca7` fixes that newline loss in all five fields. Root and the quality reviewer each passed all 32 reported tests (14 basic tests, three browser tests, and 15 nested field/newline cases; zero failures/skips). The quality re-review returned `QUALITY_PASS` with the Minor resolved. Root's separate 22-group browser suite, including 48 scene/mode/viewport views, also passed with no runtime errors or external requests. Code commits contain only `prototype/`; documentation tracking is committed separately. The earlier worker-owned preview server ended, so root restarted it in a PTY, confirmed HTTP 200, and refreshed the visible empty V04 writer view. No user-authored alternative was fabricated, no actual engine was connected, and no merge/push was performed. The continuing parent plan awaits user screen review, not a blanket product approval.
