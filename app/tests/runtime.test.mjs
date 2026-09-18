// T048 (logic half): the run observation GUI logic over the fixed runs-v1
// routes (POST {base}api/v1/runs, GET .../{run}, POST .../{run}/resume).
// Pure functions: route builders that refuse path injection, the closed
// create/resume commands mirrored from app/api/runs.py, an honest view of
// the server's run receipt (phases derived server-side, node states from the
// projection's identities only, past attempts kept distinct), accessible
// text rows, and an observer over an injected request. No DOM, no fetch,
// no live server; the Python side owns the route contract and a drift test
// pins the mirrored constants.

import test from 'node:test';
import assert from 'node:assert/strict';

import { approvalRoutes, awaitingHumanView } from '../static/approvals.mjs';
import {
  ERROR_CODES,
  INPUT_KINDS,
  NODE_STATES,
  PHASES,
  PHASE_LABELS,
  accessibleRows,
  createRunObserver,
  resumeCommand,
  runCommand,
  runRoutes,
  runView,
} from '../static/runtime.mjs';

const RUN_ID = '00000000-0000-4000-8000-00000000b0b1';
const COMMAND_ID = '11111111-2222-4333-8444-555555555555';
const BASE = `/${'2'.repeat(32)}/`;

function ref(kind, id = '33333333-3333-4333-8333-333333333333') {
  return { kind, id, version: 1, sha256: 'c'.repeat(64) };
}

function outcome(changes = {}) {
  return {
    run_id: RUN_ID, graph_digest: 'd'.repeat(64),
    completed_node_ids: ['intake', 'publish', 'writer'],
    execution_ids: [['intake', 'e-intake'], ['publish', 'e-publish'], ['writer', 'e-writer']],
    result_refs: [['e-intake', ref('artifact', '44444444-4444-4444-8444-444444444444')],
                  ['e-publish', ref('artifact', '55555555-5555-4555-8555-555555555555')],
                  ['e-writer', ref('artifact', '66666666-6666-4666-8666-666666666666')]],
    counters: { intake: 1, writer: 1, publish: 1 }, activations: [],
    awaiting_human: [], approvals: [], pending_node_ids: [], rejected_human: [],
    ...changes,
  };
}

function receipt(changes = {}, base = '/') {
  const prefix = base.slice(0, -1);
  return {
    command_id: COMMAND_ID, run_id: RUN_ID, graph_ref: ref('graph'), graph_digest: 'd'.repeat(64),
    phase: 'completed', outcome: outcome(),
    links: { self: `${prefix}/api/v1/runs/${RUN_ID}`, approvals: `${prefix}/api/v1/runs/${RUN_ID}/approvals`,
             events: `${prefix}/api/v1/events` },
    event_cursor: 'opaque-cursor', ...changes,
  };
}

test('routes bind the base path and the run id without path injection', () => {
  const routes = runRoutes();
  assert.equal(routes.create, '/api/v1/runs');
  assert.equal(routes.read(RUN_ID), `/api/v1/runs/${RUN_ID}`);
  assert.equal(routes.resume(RUN_ID), `/api/v1/runs/${RUN_ID}/resume`);
  assert.equal(runRoutes(BASE).read(RUN_ID), `/${'2'.repeat(32)}/api/v1/runs/${RUN_ID}`);
  for (const bad of ['not-a-uuid', `${RUN_ID}/..`, '', 42]) {
    assert.throws(() => routes.read(bad));
    assert.throws(() => routes.resume(bad));
  }
  for (const badBase of ['', 'api/', '/x/', `/${'2'.repeat(31)}/`, '/../']) {
    assert.throws(() => runRoutes(badBase));
  }
});

test('the create and resume commands are closed and mirror the server grammar', () => {
  const fields = {
    commandId: COMMAND_ID, graphRef: ref('graph'), workRevisionRef: ref('work_revision'),
    environmentRef: ref('environment'), consentRef: ref('run_consent'),
    budgetPolicyRef: ref('budget_policy'),
  };
  assert.deepEqual(runCommand(fields), {
    command_id: COMMAND_ID, graph_ref: ref('graph'), work_revision_ref: ref('work_revision'),
    environment_ref: ref('environment'), consent_ref: ref('run_consent'),
    budget_policy_ref: ref('budget_policy'),
  });
  assert.deepEqual(INPUT_KINDS, {
    graph_ref: 'graph', work_revision_ref: 'work_revision', environment_ref: 'environment',
    consent_ref: 'run_consent', budget_policy_ref: 'budget_policy',
  });
  for (const change of [
    { commandId: 'bad' }, { graphRef: ref('work_revision') }, { consentRef: { ...ref('run_consent'), extra: 1 } },
    { budgetPolicyRef: { ...ref('budget_policy'), sha256: 'zz' } },
    { environmentRef: { ...ref('environment'), version: '1' } }, { workRevisionRef: null },
  ]) {
    assert.throws(() => runCommand({ ...fields, ...change }));
  }
  assert.throws(() => runCommand({ ...fields, schema_version: 'run-create-command-v1' }));
  assert.throws(() => runCommand({ ...fields, mode: 'replay' }));
  assert.deepEqual(resumeCommand({ commandId: COMMAND_ID }), { command_id: COMMAND_ID });
  assert.throws(() => resumeCommand({ commandId: 'bad' }));
  assert.throws(() => resumeCommand({ commandId: COMMAND_ID, runId: RUN_ID }));
});

test('a completed receipt becomes an honest view: states from identities, visits distinct', () => {
  const view = runView(receipt());
  assert.deepEqual([...PHASES], ['created', 'running', 'awaiting_human', 'rejected', 'completed']);
  assert.equal(view.runId, RUN_ID);
  assert.equal(view.phase, 'completed');
  assert.equal(view.phaseLabel, PHASE_LABELS.completed);
  assert.equal(view.complete, true);
  assert.equal(view.graphDigest, 'd'.repeat(64));
  assert.deepEqual(view.graphRef, ref('graph'));
  assert.equal(view.eventCursor, 'opaque-cursor');
  assert.equal(view.eventsPath, '/api/v1/events');
  assert.equal(view.approvalsPath, `/api/v1/runs/${RUN_ID}/approvals`);
  assert.deepEqual(view.nodes.map(node => [node.nodeId, node.state, node.visits]),
    [['intake', 'completed', 1], ['publish', 'completed', 1], ['writer', 'completed', 1]]);
  assert.deepEqual(view.visits.map(row => [row.nodeId, row.executionId, row.resultRef?.id]), [
    ['intake', 'e-intake', '44444444-4444-4444-8444-444444444444'],
    ['publish', 'e-publish', '55555555-5555-4555-8555-555555555555'],
    ['writer', 'e-writer', '66666666-6666-4666-8666-666666666666'],
  ]);
  assert.equal(Object.isFrozen(view) && Object.isFrozen(view.nodes) && Object.isFrozen(view.visits), true);
  // nothing raw rides along: no counters copy, no checkpoint or graph content
  for (const name of ['counters', 'activations', 'result_refs', 'outcome', 'checkpoint', 'attempts']) {
    assert.equal(name in view, false);
  }
  assert.deepEqual([...NODE_STATES], ['completed', 'pending', 'awaiting_human', 'rejected', 'not_visited']);
});

test('waiting, rejected, running and created receipts are never complete', () => {
  const waiting = runView(receipt({ phase: 'awaiting_human', outcome: outcome({
    completed_node_ids: ['intake', 'writer'], counters: { intake: 1, writer: 1 },
    execution_ids: [['intake', 'e-intake'], ['writer', 'e-writer']],
    result_refs: [['e-intake', ref('artifact')], ['e-writer', ref('artifact')]],
    awaiting_human: [['owner-gate', 'release-output']], pending_node_ids: ['owner-gate'],
  }) }));
  assert.equal(waiting.complete, false);
  assert.equal(waiting.phaseLabel, PHASE_LABELS.awaiting_human);
  assert.deepEqual(waiting.awaiting, [{ nodeId: 'owner-gate', scope: 'release-output' }]);
  const gate = waiting.nodes.find(node => node.nodeId === 'owner-gate');
  assert.equal(gate.state, 'awaiting_human');
  assert.deepEqual(gate.awaitingScopes, ['release-output']);
  assert.deepEqual(gate.rejectedScopes, []);
  assert.equal(gate.visits, 0);
  assert.equal(waiting.nodes.find(node => node.nodeId === 'publish'), undefined);

  const rejected = runView(receipt({ phase: 'rejected', outcome: outcome({
    completed_node_ids: ['intake', 'writer'], counters: { intake: 1, writer: 1 },
    execution_ids: [['intake', 'e-intake'], ['writer', 'e-writer']], result_refs: [],
    rejected_human: [['owner-gate', 'release-output']], pending_node_ids: ['owner-gate'],
  }) }));
  assert.equal(rejected.complete, false);
  assert.deepEqual(rejected.rejected, [{ nodeId: 'owner-gate', scope: 'release-output' }]);
  assert.equal(rejected.nodes.find(node => node.nodeId === 'owner-gate').state, 'rejected');

  const running = runView(receipt({ phase: 'running', outcome: outcome({
    completed_node_ids: ['intake'], counters: { intake: 1 },
    execution_ids: [['intake', 'e-intake']], result_refs: [], pending_node_ids: ['writer'],
  }) }));
  assert.equal(running.complete, false);
  assert.equal(running.nodes.find(node => node.nodeId === 'writer').state, 'pending');
  assert.equal(running.visits[0].resultRef, null);

  const created = runView(receipt({ phase: 'created', outcome: outcome({
    completed_node_ids: [], counters: {}, execution_ids: [], result_refs: [], pending_node_ids: [],
  }) }));
  assert.equal(created.complete, false);
  assert.deepEqual(created.nodes, []);
  // the server derives the phase; a receipt that contradicts itself is refused
  assert.throws(() => runView(receipt({ phase: 'completed', outcome: outcome({
    awaiting_human: [['owner-gate', 'release-output']],
  }) })), /complete/);
  assert.throws(() => runView(receipt({ phase: 'completed', outcome: outcome({
    pending_node_ids: ['publish'],
  }) })));
  assert.throws(() => runView(receipt({ phase: 'finished' })));
  assert.throws(() => runView(receipt({ outcome: outcome({ completed_node_ids: ['ghost'] }) })));
  // the phase rule is mirrored fully: created ⇔ nothing visited, running ⇔ pending
  assert.throws(() => runView(receipt({ phase: 'created' })));  // visits but "시작 전"
  assert.throws(() => runView(receipt({ phase: 'running' })));  // nothing pending but "실행 중"
  assert.throws(() => runView(receipt({ phase: 'completed', outcome: outcome({
    completed_node_ids: [], counters: {}, execution_ids: [], result_refs: [],
  }) })));
  assert.throws(() => runView(receipt({ phase: 'rejected', outcome: outcome({
    awaiting_human: [['owner-gate', 'release-output']], rejected_human: [['owner-gate', 'other']],
    pending_node_ids: ['owner-gate'],
  }) })));
});

test('a result reference never attaches to a node or attempt that did not produce it', () => {
  // two executions of the same node (a bounded loop): each attempt keeps its own result
  const view = runView(receipt({ outcome: outcome({
    completed_node_ids: ['writer'], counters: { writer: 2 },
    execution_ids: [['writer', 'e-writer-0'], ['writer', 'e-writer-1']],
    result_refs: [['e-writer-0', ref('artifact', '44444444-4444-4444-8444-444444444444')],
                  ['e-writer-1', ref('artifact', '55555555-5555-4555-8555-555555555555')]],
  }) }));
  assert.deepEqual(view.visits.map(row => [row.executionId, row.loopIndex, row.resultRef.id]), [
    ['e-writer-0', 0, '44444444-4444-4444-8444-444444444444'],
    ['e-writer-1', 1, '55555555-5555-4555-8555-555555555555'],
  ]);
  assert.equal(view.nodes[0].visits, 2);
  assert.deepEqual(view.nodes[0].resultRefs.map(item => item.id),
    ['44444444-4444-4444-8444-444444444444', '55555555-5555-4555-8555-555555555555']);
  // a result for an execution the run never recorded is refused, never shown as the latest
  assert.throws(() => runView(receipt({ outcome: outcome({
    result_refs: [['e-ghost', ref('artifact')]],
  }) })));
  // a "completed" node without any recorded visit is not evidence of completion
  assert.throws(() => runView(receipt({ outcome: outcome({
    completed_node_ids: ['intake', 'publish', 'writer'], counters: { intake: 1, writer: 1 },
  }) })));
});

test('the view composes with the approvals module on the same base path', () => {
  const waiting = receipt({ phase: 'awaiting_human', outcome: outcome({
    completed_node_ids: ['intake', 'writer'], counters: { intake: 1, writer: 1 },
    execution_ids: [['intake', 'e-intake'], ['writer', 'e-writer']], result_refs: [],
    awaiting_human: [['owner-gate', 'release-output']], pending_node_ids: ['owner-gate'],
  }) }, BASE);
  const view = runView(waiting, BASE);
  assert.equal(view.approvalsPath, approvalRoutes(RUN_ID, BASE).record);
  const gates = awaitingHumanView(waiting.outcome, BASE);
  assert.equal(gates.gates[0].readPath, approvalRoutes(RUN_ID, BASE).read('owner-gate', 'release-output'));
  assert.equal(gates.complete, false);
  // a receipt whose self link is not the fixed read route of this base is refused
  assert.throws(() => runView(waiting, '/'));
  assert.throws(() => runView(receipt({ links: { self: '/api/v1/runs/other', approvals: 'x', events: 'y' } })));
});

test('accessible rows spell every state out in text, never colour alone', () => {
  const view = runView(receipt({ phase: 'awaiting_human', outcome: outcome({
    completed_node_ids: ['intake', 'writer'], counters: { intake: 1, writer: 1 },
    execution_ids: [['intake', 'e-intake'], ['writer', 'e-writer']],
    result_refs: [['e-writer', ref('artifact')]],
    awaiting_human: [['owner-gate', 'release-output']], pending_node_ids: ['owner-gate'],
  }) }));
  const rows = accessibleRows(view);
  assert.equal(rows.length, 3);
  assert.match(rows.find(row => row.startsWith('intake')), /완료/);
  assert.match(rows.find(row => row.startsWith('intake')), /수행 1회/);
  assert.match(rows.find(row => row.startsWith('intake')), /산출물 0건/);
  assert.match(rows.find(row => row.startsWith('writer')), /산출물 1건/);
  const gate = rows.find(row => row.startsWith('owner-gate'));
  assert.match(gate, /사람 대기/);
  assert.match(gate, /대기 근거: release-output/);
  for (const row of rows) assert.equal(typeof row, 'string');
  assert.deepEqual(Object.keys(PHASE_LABELS).sort(), [...PHASES].sort());
});

test('the observer starts, reads and resumes through the injected request only', async () => {
  const calls = [];
  const states = [];
  let reply = receipt({ phase: 'awaiting_human', outcome: outcome({
    completed_node_ids: ['intake', 'writer'], counters: { intake: 1, writer: 1 },
    execution_ids: [['intake', 'e-intake'], ['writer', 'e-writer']], result_refs: [],
    awaiting_human: [['owner-gate', 'release-output']], pending_node_ids: ['owner-gate'],
  }) });
  const observer = createRunObserver({
    request: async (path, options = {}) => { calls.push([path, options]); return reply; },
    onChange: state => states.push(state),
  });
  const fields = {
    commandId: COMMAND_ID, graphRef: ref('graph'), workRevisionRef: ref('work_revision'),
    environmentRef: ref('environment'), consentRef: ref('run_consent'),
    budgetPolicyRef: ref('budget_policy'),
  };
  const started = await observer.start(fields);
  assert.equal(started.phase, 'awaiting_human');
  assert.deepEqual(calls[0], ['/api/v1/runs', { method: 'POST', body: runCommand(fields) }]);
  assert.equal(observer.snapshot().view.runId, RUN_ID);
  assert.equal(observer.snapshot().busy, false);
  assert.equal(states.some(state => state.busy), true);
  await observer.read(RUN_ID);
  assert.deepEqual(calls[1], [`/api/v1/runs/${RUN_ID}`, {}]);  // a read never posts
  reply = receipt();
  const resumed = await observer.resume(RUN_ID, '77777777-7777-4777-8777-777777777777');
  assert.equal(resumed.phase, 'completed');
  assert.deepEqual(calls[2], [`/api/v1/runs/${RUN_ID}/resume`,
    { method: 'POST', body: { command_id: '77777777-7777-4777-8777-777777777777' } }]);
  assert.equal(observer.snapshot().view.complete, true);
  assert.equal(observer.snapshot().error, null);
  // the closed error partition: a failure carrying the envelope code keeps it, a failure
  // carrying only the HTTP status (app.mjs's api helper) maps by status, anything else is unavailable
  const conflict = Object.assign(new Error('same command, different inputs'), { code: 'conflict' });
  const failing = createRunObserver({ request: async () => { throw conflict; } });
  await assert.rejects(failing.start(fields));
  assert.deepEqual(failing.snapshot().error,
    { code: 'conflict', message: 'same command, different inputs', target: '/api/v1/runs' });
  for (const [status, code] of [[400, 'invalid_input'], [401, 'unauthenticated'], [403, 'access_denied'],
    [404, 'not_found'], [409, 'conflict'], [413, 'too_large'], [503, 'unavailable'], [500, 'unavailable']]) {
    const byStatus = createRunObserver({ request: async () => { throw Object.assign(new Error('x'), { status }); } });
    await assert.rejects(byStatus.read(RUN_ID));
    assert.equal(byStatus.snapshot().error.code, code, String(status));
  }
  const unknown = createRunObserver({ request: async () => { throw new Error('boom'); } });
  await assert.rejects(unknown.read(RUN_ID));
  assert.equal(unknown.snapshot().error.code, 'unavailable');
  // bad input is a rejected promise with a recorded error, never a synchronous throw
  const strict = createRunObserver({ request: async () => reply });
  await assert.rejects(strict.read('not-a-uuid'));
  assert.equal(strict.snapshot().error.code, 'invalid_input');
  await assert.rejects(strict.start({ commandId: 'bad' }));
  assert.throws(() => createRunObserver({ request: async () => reply, onChange: 'no' }));
  assert.deepEqual([...ERROR_CODES].sort(), ['access_denied', 'conflict', 'invalid_input', 'not_found',
    'too_large', 'unauthenticated', 'unavailable']);
  // a reply that is not an honest receipt never becomes the view
  const lying = createRunObserver({ request: async () => receipt({ phase: 'completed', outcome: outcome({
    awaiting_human: [['owner-gate', 'release-output']] }) }) });
  await assert.rejects(lying.read(RUN_ID));
  assert.equal(lying.snapshot().view, null);
  assert.throws(() => createRunObserver({}));
});


function gated(changes = {}, base = '/') {
  return receipt({ phase: 'awaiting_human', outcome: outcome({
    completed_node_ids: ['intake', 'writer'], counters: { intake: 1, writer: 1 },
    execution_ids: [['intake', 'e-intake'], ['writer', 'e-writer']], result_refs: [],
    awaiting_human: [['owner-gate', 'release-output']], pending_node_ids: ['owner-gate'],
    ...changes,
  }) }, base);
}

test('a loop node completed once and pending again is pending, with its visit kept', () => {
  const view = runView(receipt({ phase: 'running', outcome: outcome({
    completed_node_ids: ['writer'], counters: { writer: 1 },
    execution_ids: [['writer', 'e-writer-0']], result_refs: [['e-writer-0', ref('artifact')]],
    pending_node_ids: ['writer'],
  }) }));
  const writer = view.nodes.find(node => node.nodeId === 'writer');
  assert.equal(writer.state, 'pending');
  assert.equal(writer.visits, 1);
  assert.equal(writer.resultRefs.length, 1);
  // a visited node records every result or none: a gap is not a receipt this view trusts
  assert.throws(() => runView(receipt({ outcome: outcome({
    completed_node_ids: ['writer'], counters: { writer: 3 },
    execution_ids: [['writer', 'e-writer-0'], ['writer', 'e-writer-2']],
    result_refs: [['e-writer-0', ref('artifact')], ['e-writer-2', ref('artifact')]],
  }) })), /every result or none/);
});

test('a gate rejected on one scope and awaiting another shows both, and the routes and approvals stay', () => {
  const view = runView(gated({
    awaiting_human: [['owner-gate', 'scope-a']], rejected_human: [['owner-gate', 'scope-b']],
  }));
  const gate = view.nodes.find(node => node.nodeId === 'owner-gate');
  assert.equal(gate.state, 'awaiting_human');
  assert.deepEqual(gate.awaitingScopes, ['scope-a']);
  assert.deepEqual(gate.rejectedScopes, ['scope-b']);
  const row = accessibleRows(view).find(item => item.startsWith('owner-gate'));
  assert.match(row, /대기 근거: scope-a/);
  assert.match(row, /거절: scope-b/);
  // the sealed router activations are the "실제 전달" lines; consumed approvals are the gate's 근거
  const routed = runView(receipt({ outcome: outcome({
    completed_node_ids: ['accept', 'choose', 'join', 'owner-gate'],
    counters: { accept: 1, choose: 1, join: 1, 'owner-gate': 1 },
    execution_ids: [['accept', 'e-accept'], ['choose', 'e-choose'], ['join', 'e-join'], ['owner-gate', 'e-gate']],
    result_refs: [['e-accept', ref('artifact')], ['e-join', ref('artifact')], ['e-gate', ref('artifact')]],
    activations: [['choose', 'act-1', ['accept']]],
    approvals: [['owner-gate', [ref('action_approval')]]],
  }) }));
  assert.deepEqual(routed.routes, [{ routerId: 'choose', activationId: 'act-1', targets: ['accept'] }]);
  assert.deepEqual(routed.nodes.find(node => node.nodeId === 'owner-gate').approvalRefs, [ref('action_approval')]);
  assert.equal(routed.nodes.find(node => node.nodeId === 'choose').state, 'completed');
});

test('the graph node universe makes never-visited nodes visible as 미수행', () => {
  const view = runView(gated(), '/', { nodeIds: ['intake', 'writer', 'owner-gate', 'publish'] });
  const publish = view.nodes.find(node => node.nodeId === 'publish');
  assert.equal(publish.state, 'not_visited');
  assert.equal(publish.stateLabel, '미수행');
  assert.match(accessibleRows(view).find(row => row.startsWith('publish')), /미수행/);
  // a receipt naming a node outside the declared universe is refused
  assert.throws(() => runView(gated(), '/', { nodeIds: ['intake', 'writer'] }));
  assert.equal(runView(gated()).nodes.find(node => node.state === 'not_visited'), undefined);
});

test('overlapping exchanges never publish a stale view or a false idle', async () => {
  const pending = new Map();
  const states = [];
  const observer = createRunObserver({
    request: path => new Promise(resolve => pending.set(path, resolve)),
    onChange: state => states.push(state),
  });
  const other = '99999999-9999-4999-8999-999999999999';
  const first = observer.read(RUN_ID);
  const second = observer.read(other);
  assert.equal(observer.snapshot().busy, true);
  pending.get(`/api/v1/runs/${other}`)(receipt({ run_id: other,
    outcome: outcome({ run_id: other }),
    links: { self: `/api/v1/runs/${other}`, approvals: `/api/v1/runs/${other}/approvals`, events: '/api/v1/events' } }));
  await second;
  assert.equal(observer.snapshot().busy, true);  // the first exchange is still in flight
  assert.equal(observer.snapshot().view.runId, other);
  pending.get(`/api/v1/runs/${RUN_ID}`)(receipt());
  const late = await first;
  assert.equal(late.runId, RUN_ID);  // the caller still gets its own view
  assert.equal(observer.snapshot().view.runId, other);  // but the newer exchange stays published
  assert.equal(observer.snapshot().busy, false);
  // identical polls do not re-announce: no redundant emissions for a screen reader
  const quiet = [];
  const same = createRunObserver({ request: async () => receipt(), onChange: state => quiet.push(state) });
  await same.read(RUN_ID);
  const after = quiet.length;
  await same.read(RUN_ID);
  assert.equal(quiet.length - after, 2);  // busy on, busy off — the unchanged view is not re-published
  assert.equal(quiet[quiet.length - 1].view, quiet[after - 1].view);
});

test('an error for another run never leaves the previous run on screen', async () => {
  let fails = false;
  const observer = createRunObserver({ request: async (path) => {
    if (fails) throw Object.assign(new Error('gone'), { status: 404 });
    return receipt();
  } });
  await observer.read(RUN_ID);
  fails = true;
  const other = '99999999-9999-4999-8999-999999999999';
  await assert.rejects(observer.read(other));
  assert.equal(observer.snapshot().view, null);
  assert.deepEqual(observer.snapshot().error, { code: 'not_found', message: 'gone', target: `/api/v1/runs/${other}` });
  // the same run's failure keeps the last honest view alongside the error
  fails = false;
  await observer.read(RUN_ID);
  fails = true;
  await assert.rejects(observer.read(RUN_ID));
  assert.equal(observer.snapshot().view.runId, RUN_ID);
});
