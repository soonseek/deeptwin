import test from 'node:test';
import assert from 'node:assert/strict';

import { ARTIFACTS, CASE, DESIGNS, LOGS, REVISED_DESIGN, ROUNDS, RUNS } from '../fixtures.mjs';
import {
  KEY,
  context,
  createState,
  draftKey,
  load,
  noteKey,
  reset,
  save,
  transition,
} from '../state.mjs';

class MemoryStorage {
  constructor(entries = {}) {
    this.values = new Map(Object.entries(entries));
    this.calls = [];
  }
  getItem(key) {
    this.calls.push(['getItem', key]);
    return this.values.has(key) ? this.values.get(key) : null;
  }
  setItem(key, value) {
    this.calls.push(['setItem', key, value]);
    this.values.set(key, value);
  }
  removeItem(key) {
    this.calls.push(['removeItem', key]);
    this.values.delete(key);
  }
}

const findOriginalAttempt = () => Object.values(RUNS).flatMap(run => run.attempts.map(attempt => ({ run, attempt })))
  .find(({ attempt }) => attempt.outputs.includes(CASE.original));
const otherRun = runId => Object.values(RUNS).find(run => run.id !== runId);
const findAttempt = (run, predicate) => run.attempts.find(predicate);
const stateFields = [
  'version', 'area', 'mode', 'run', 'targets', 'design', 'focus', 'round', 'pairs', 'sample',
  'difference', 'drafts', 'notes', 'workText', 'designText', 'overlay', 'records', 'redact',
];

test('seed selects the exact attempt that produced the case original and exposes only the scoped context', () => {
  const state = createState();
  const expected = findOriginalAttempt();

  assert.deepEqual(Object.keys(state), stateFields);
  assert.equal(state.version, 1);
  assert.equal(state.area, 'run');
  assert.equal(state.mode, 'graph');
  assert.equal(state.run, expected.run.id);
  assert.deepEqual(Object.keys(state.targets), [expected.run.id]);
  assert.deepEqual(context(state), {
    run: expected.run.id,
    node: expected.attempt.node,
    attempt: expected.attempt.id,
    artifact: CASE.original,
    scope: { kind: 'whole' },
  });
  assert.equal(state.design, DESIGNS[0].id);
  assert.equal(state.focus, 'transfer');
  assert.equal(state.round, ROUNDS[0].id);
  assert.equal(state.sample, false);
  assert.equal(state.difference, CASE.differences[0].id);
  assert.deepEqual(state.drafts, {});
  assert.deepEqual(state.notes, {});
  assert.equal(state.redact, true);
});

test('drafts preserve leading newlines and Korean across modes, overlays, and remembered run targets', () => {
  let state = createState();
  const originalRun = state.run;
  const originalKey = draftKey(state);
  const draft = '\n\n첫 줄을 비워 둔 한국어 초안';
  state = transition(state, { type: 'draft', value: draft });
  state = transition(state, { type: 'mode', value: 'workspace' });
  state = transition(state, { type: 'mode', value: 'conversation' });
  state = transition(state, { type: 'mode', value: 'graph' });
  state = transition(state, { type: 'overlay', value: 'logs' });
  state = transition(state, { type: 'overlay', value: 'connection' });
  state = transition(state, { type: 'close' });

  assert.equal(state.drafts[originalKey], draft);
  assert.equal(state.overlay, null);
  assert.equal(draftKey(state), originalKey);

  const nextRun = otherRun(originalRun);
  state = transition(state, { type: 'run', value: nextRun.id });
  assert.notEqual(draftKey(state), originalKey);
  const nextContext = context(state);
  assert.equal(nextContext.run, nextRun.id);
  assert.ok(nextRun.attempts.some(attempt => attempt.id === nextContext.attempt));

  state = transition(state, { type: 'run', value: originalRun });
  assert.equal(draftKey(state), originalKey);
  assert.equal(state.drafts[draftKey(state)], draft);
});

test('run targets are created lazily and inherited object property names are rejected safely', () => {
  let state = createState();
  const before = state;
  assert.equal(transition(state, { type: 'run', value: 'toString' }), state);
  assert.equal(transition(state, { type: 'attempt', run: 'toString', value: 'anything' }), state);
  assert.equal(transition(state, { type: 'run', value: [state.run] }), state);
  assert.equal(transition(state, { type: 'attempt', run: [state.run], value: context(state).attempt }), state);

  const nextRun = otherRun(state.run);
  state = transition(state, { type: 'run', value: nextRun.id });
  assert.notEqual(state, before);
  assert.deepEqual(new Set(Object.keys(state.targets)), new Set([before.run, nextRun.id]));
});

test('empty-output attempts and resource nodes never inherit or invent artifacts', () => {
  let state = createState();
  const run = RUNS[state.run];
  const empty = findAttempt(run, attempt => attempt.outputs.length === 0);
  assert.ok(empty, 'fixture must contain an actual empty-output attempt');

  state = transition(state, { type: 'attempt', run: run.id, value: empty.id });
  assert.deepEqual(context(state), {
    run: run.id,
    node: empty.node,
    attempt: empty.id,
    artifact: null,
    scope: { kind: 'whole' },
  });

  const beforeTextScope = state;
  state = transition(state, { type: 'scope', value: { kind: 'text', start: 0, end: 1 } });
  assert.equal(state, beforeTextScope);
  assert.equal(transition(state, { type: 'artifact', value: 'not-an-artifact' }), state);

  state = transition(state, { type: 'node', value: 'files' });
  assert.deepEqual(context(state), {
    run: run.id,
    node: 'files',
    attempt: null,
    artifact: null,
    scope: { kind: 'whole' },
  });
});

test('artifact selection is restricted to the current attempt inputs and outputs', () => {
  let state = createState();
  const run = RUNS[state.run];
  const attempt = findAttempt(run, item => item.inputs.length && item.outputs.length);
  state = transition(state, { type: 'attempt', value: attempt.id });

  state = transition(state, { type: 'artifact', value: attempt.inputs[0] });
  assert.equal(context(state).artifact, attempt.inputs[0]);
  assert.deepEqual(context(state).scope, { kind: 'whole' });
  const rejected = transition(state, { type: 'artifact', value: CASE.alternative });
  assert.equal(rejected, state);
});

test('whole, declared region, and valid text scopes have distinct keys and drafts turn sampling off', () => {
  let state = createState();
  const artifact = ARTIFACTS[context(state).artifact];
  const wholeKey = draftKey(state);
  state = transition(state, { type: 'scope', value: { kind: 'region', id: artifact.regions[0].id } });
  const regionKey = draftKey(state);
  assert.notEqual(regionKey, wholeKey);

  state = transition(state, { type: 'sample', value: true });
  assert.equal(state.sample, true);
  state = transition(state, { type: 'draft', value: '\n새 부분 초안' });
  assert.equal(state.sample, false);
  assert.equal(state.drafts[draftKey(state)], '\n새 부분 초안');
});

test('text scope uses exact UTF-16 indices and rejects every invalid range', () => {
  let state = createState();
  const run = RUNS[state.run];
  const attempt = run.attempts.find(item => item.outputs.some(id => ARTIFACTS[id]?.type === 'text'));
  const artifactId = attempt.outputs.find(id => ARTIFACTS[id]?.type === 'text');
  const artifact = ARTIFACTS[artifactId];
  assert.ok(attempt && artifact, 'fixture must expose an actual text output');

  state = transition(state, { type: 'attempt', value: attempt.id });
  state = transition(state, { type: 'artifact', value: artifactId });
  const start = artifact.body.length - 1;
  state = transition(state, { type: 'scope', value: { kind: 'text', start, end: artifact.body.length } });
  assert.deepEqual(context(state).scope, { kind: 'text', start, end: artifact.body.length });
  assert.equal(artifact.body.slice(context(state).scope.start, context(state).scope.end).length, 1);

  for (const value of [
    { kind: 'text', start: -1, end: 1 },
    { kind: 'text', start: 1, end: 1 },
    { kind: 'text', start: 0, end: artifact.body.length + 1 },
    { kind: 'text', start: 0.5, end: 2 },
  ]) assert.equal(transition(state, { type: 'scope', value }), state);
});

test('all bounded controls validate references and invalid actions return the original object', () => {
  let state = createState();
  const original = state;
  assert.equal(transition(state, { type: 'unknown', value: true }), state);
  assert.equal(transition(state, { type: 'area', value: 'other' }), state);
  assert.equal(transition(state, { type: 'draft', value: 'x'.repeat(20001) }), state);
  assert.equal(transition(state, { type: 'sample', value: 1 }), state);
  assert.equal(transition(state, { type: 'record', value: 'missing-log' }), state);

  state = transition(state, { type: 'area', value: 'design' });
  state = transition(state, { type: 'design', value: REVISED_DESIGN.id });
  state = transition(state, { type: 'focus', value: 'evaluation' });
  state = transition(state, { type: 'note', value: '설계 메모' });
  assert.equal(state.notes[noteKey(state)], '설계 메모');
  state = transition(state, { type: 'workText', value: '업무 문장' });
  state = transition(state, { type: 'designText', value: '설계 문장' });
  state = transition(state, { type: 'record', value: LOGS[0].id });
  assert.deepEqual(state.records, [LOGS[0].id]);
  state = transition(state, { type: 'record', value: LOGS[0].id });
  assert.deepEqual(state.records, []);
  assert.notEqual(state, original);
});

test('pair values are scoped to the selected round and side run', () => {
  let state = createState();
  const round = ROUNDS[0];
  const baselineAttempt = RUNS[round.baselineRun].attempts[0];
  const candidateNode = RUNS[round.candidateRun].attempts[0].node;

  state = transition(state, { type: 'pair', side: 'baseline', value: baselineAttempt.id });
  state = transition(state, { type: 'pair', side: 'candidate', value: `@${candidateNode}` });
  assert.equal(state.pairs[`${round.id}:baseline`], baselineAttempt.id);
  assert.equal(state.pairs[`${round.id}:candidate`], `@${candidateNode}`);
  assert.equal(transition(state, { type: 'pair', side: 'candidate', value: baselineAttempt.id }), state);
});

test('storage round trip writes only the state key, retains unrelated data, and explains file limits', () => {
  const storage = new MemoryStorage({ unrelated: 'keep' });
  let state = createState();
  state = transition(state, { type: 'note', value: '\n보관 메모' });

  assert.deepEqual(save(storage, state, false), {
    ok: true,
    message: '이 탭에만 보관 · 파일 첨부는 메모리에만 있음',
  });
  assert.equal(storage.values.get('unrelated'), 'keep');
  assert.deepEqual(storage.calls.filter(([method]) => method === 'setItem').map(([, key]) => key), [KEY]);

  const restored = load(storage);
  assert.equal(restored.blocked, false);
  assert.deepEqual(restored.state, state);
  assert.match(restored.message, /파일.*복원되지/);
});

test('a note scoped to a resource with no attempt remains a valid persisted context', () => {
  const storage = new MemoryStorage();
  let state = createState();
  state = transition(state, { type: 'node', value: 'files' });
  state = transition(state, { type: 'note', value: '파일 연결 전 메모' });
  assert.equal(state.notes[noteKey(state)], '파일 연결 전 메모');

  assert.equal(save(storage, state, false).ok, true);
  const restored = load(storage);
  assert.equal(restored.blocked, false);
  assert.deepEqual(restored.state, state);
});

test('different no-attempt resource nodes keep separate notes', () => {
  let state = createState();
  state = transition(state, { type: 'node', value: 'files' });
  const filesKey = noteKey(state);
  state = transition(state, { type: 'note', value: '파일 메모' });
  state = transition(state, { type: 'node', value: 'model' });
  const modelKey = noteKey(state);
  state = transition(state, { type: 'note', value: '모델 메모' });

  assert.notEqual(filesKey, modelKey);
  assert.equal(typeof JSON.parse(filesKey)[1], 'string');
  assert.equal(typeof JSON.parse(modelKey)[1], 'string');
  assert.equal(state.notes[filesKey], '파일 메모');
  assert.equal(state.notes[modelKey], '모델 메모');
});

test('fresh growth notes follow the actual scoped run source and recover when switching back', () => {
  let state = transition(createState(), { type: 'area', value: 'growth' });
  const firstRun = state.run;
  const firstKey = noteKey(state);
  state = transition(state, { type: 'note', value: '첫 실행의 새 근거 메모' });

  const nextRun = otherRun(firstRun);
  state = transition(state, { type: 'run', value: nextRun.id });
  const nextKey = noteKey(state);
  assert.notEqual(nextKey, firstKey);
  assert.equal(state.notes[nextKey], undefined);
  state = transition(state, { type: 'note', value: '다른 실행의 새 근거 메모' });

  state = transition(state, { type: 'run', value: firstRun });
  assert.equal(noteKey(state), firstKey);
  assert.equal(state.notes[firstKey], '첫 실행의 새 근거 메모');
  assert.equal(state.notes[nextKey], '다른 실행의 새 근거 메모');
});

test('fresh growth notes ignore fixed-example controls while fixed examples remain round-scoped', () => {
  let state = transition(createState(), { type: 'area', value: 'growth' });
  const freshKey = noteKey(state);
  state = transition(state, { type: 'note', value: '현재 실제 출처 메모' });
  state = transition(state, { type: 'sample', value: true });
  const fixedFirstKey = noteKey(state);
  assert.notEqual(fixedFirstKey, freshKey);
  state = transition(state, { type: 'note', value: '첫 고정 예시 메모' });
  state = transition(state, { type: 'round', value: ROUNDS[1].id });
  const fixedSecondKey = noteKey(state);
  assert.notEqual(fixedSecondKey, fixedFirstKey);
  state = transition(state, { type: 'sample', value: false });

  assert.equal(noteKey(state), freshKey);
  assert.equal(state.notes[freshKey], '현재 실제 출처 메모');
  assert.equal(state.notes[fixedFirstKey], '첫 고정 예시 메모');

  const storage = new MemoryStorage();
  assert.equal(save(storage, state, false).ok, true);
  assert.deepEqual(load(storage), {
    state,
    blocked: false,
    message: '이 탭 보관본 복원 · 파일 첨부는 복원되지 않음',
  });
});

test('fresh growth notes distinguish no-attempt resource sources', () => {
  let state = transition(createState(), { type: 'area', value: 'growth' });
  state = transition(state, { type: 'node', value: 'files' });
  const filesKey = noteKey(state);
  state = transition(state, { type: 'node', value: 'model' });
  assert.notEqual(noteKey(state), filesKey);
});

test('safe persisted target subsets load without inventing unvisited run history', () => {
  const state = createState();
  const storage = new MemoryStorage({ [KEY]: JSON.stringify(state) });
  const restored = load(storage);
  assert.equal(restored.blocked, false);
  assert.deepEqual(restored.state, state);
  assert.deepEqual(Object.keys(restored.state.targets), [state.run]);
});

test('broken snapshots block automatic writes without replacing the original raw value', () => {
  const broken = '{broken';
  const storage = new MemoryStorage({ [KEY]: broken });
  const result = load(storage);
  assert.equal(result.blocked, true);
  assert.equal(result.message, '보관본 읽기 실패 · 이전 값은 덮어쓰지 않음');
  assert.deepEqual(result.state, createState());

  assert.deepEqual(save(storage, result.state, result.blocked), {
    ok: false,
    message: '자동 보관 중지 · 기존 보관본 유지',
  });
  assert.equal(storage.values.get(KEY), broken);
  assert.equal(storage.calls.filter(([method]) => method === 'setItem').length, 0);

  assert.equal(save(storage, result.state, false).ok, true, 'caller may explicitly allow a replacement');
  assert.notEqual(storage.values.get(KEY), broken);
});

test('oversized serialized state is not reported saved and cannot replace a good snapshot', () => {
  const prior = JSON.stringify(createState());
  const storage = new MemoryStorage({ [KEY]: prior });
  const oversized = { ...createState(), padding: 'x'.repeat(2_000_000) };

  assert.deepEqual(save(storage, oversized, false), {
    ok: false,
    message: '보관 실패 · 현재 입력은 메모리에 남음 · 새로고침 주의',
  });
  assert.equal(storage.values.get(KEY), prior);
  assert.equal(storage.calls.filter(([method]) => method === 'setItem').length, 0);
});

test('reset deletes only the state key', () => {
  const storage = new MemoryStorage({ [KEY]: '{}', unrelated: 'keep' });
  assert.deepEqual(reset(storage), { ok: true });
  assert.equal(storage.values.has(KEY), false);
  assert.equal(storage.values.get('unrelated'), 'keep');
  assert.deepEqual(storage.calls.filter(([method]) => method === 'removeItem'), [['removeItem', KEY]]);
});

test('storage read, write, and delete exceptions return the documented honest messages', () => {
  const read = { getItem() { throw new Error('read'); } };
  assert.deepEqual(load(read), {
    state: createState(),
    blocked: true,
    message: '보관본 읽기 실패 · 이전 값은 덮어쓰지 않음',
  });

  const write = { setItem() { throw new Error('write'); } };
  assert.deepEqual(save(write, createState(), false), {
    ok: false,
    message: '보관 실패 · 현재 입력은 메모리에 남음 · 새로고침 주의',
  });

  const remove = { removeItem() { throw new Error('remove'); } };
  assert.deepEqual(reset(remove), { ok: false, message: '초기화 실패 · 현재 작성 내용 유지' });
});

test('unsafe snapshots are rejected rather than partially salvaged', () => {
  const valid = createState();
  const nodeLessResourceNote = JSON.stringify([
    'run',
    JSON.stringify([valid.run, null, [], null, { kind: 'whole' }]),
  ]);
  const legacyFreshGrowthNote = JSON.stringify([
    'growth',
    [false, valid.difference, valid.round],
  ]);
  const invalidStates = [
    { ...valid, surprise: true },
    { ...valid, mode: 'invalid' },
    { ...valid, targets: { ...valid.targets, missing: valid.targets[valid.run] } },
    { ...valid, records: [LOGS[0].id, LOGS[0].id] },
    { ...valid, pairs: { [`${ROUNDS[0].id}:wrong`]: '@extract' } },
    { ...valid, notes: { bad: 'orphan' } },
    { ...valid, notes: { [nodeLessResourceNote]: 'legacy orphan' } },
    { ...valid, notes: { [legacyFreshGrowthNote]: 'unscoped legacy orphan' } },
    { ...valid, run: [valid.run] },
    { ...valid, drafts: { [JSON.stringify(['missing-run', 'missing-attempt', [], 'missing', { kind: 'whole' }])]: 'orphan' } },
  ];

  for (const invalid of invalidStates) {
    const result = load(new MemoryStorage({ [KEY]: JSON.stringify(invalid) }));
    assert.equal(result.blocked, true);
    assert.deepEqual(result.state, createState());
  }

  const oversized = load(new MemoryStorage({ [KEY]: ' '.repeat(2_000_001) }));
  assert.equal(oversized.blocked, true);
});
