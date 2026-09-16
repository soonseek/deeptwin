// T066/UX-AC06 (logic half): the human approval GUI logic over the fixed
// run-approval routes. Pure functions: route builders that refuse path
// injection, the closed approval command, the honest "awaiting human"
// view of a scheduler outcome projection, and receipt summaries. No DOM,
// no fetch, no live server; the Python side owns the route contract.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DECISIONS,
  approvalCommand,
  approvalRoutes,
  awaitingHumanView,
  receiptSummary,
  remainingGates,
} from '../static/approvals.mjs';

const RUN_ID = '00000000-0000-4000-8000-00000000a0a1';
const COMMAND_ID = '11111111-2222-4333-8444-555555555555';

test('routes bind the run id and gate segments without path injection', () => {
  const routes = approvalRoutes(RUN_ID);
  assert.equal(routes.record, `/api/v1/runs/${RUN_ID}/approvals`);
  assert.equal(routes.read('owner-gate', 'release-output'),
    `/api/v1/runs/${RUN_ID}/approvals/owner-gate/release-output`);
  for (const bad of ['not-a-uuid', `${RUN_ID}/..`, '', 42]) {
    assert.throws(() => approvalRoutes(bad));
  }
  for (const [node, scope] of [['../gate', 'x'], ['owner gate', 'x'], ['', 'x'], ['ok', 'a/b']]) {
    assert.throws(() => routes.read(node, scope));
  }
});

test('the approval command is closed and validated', () => {
  const command = approvalCommand({
    commandId: COMMAND_ID, nodeId: 'owner-gate',
    approvalScope: 'release-output', decision: 'approved',
  });
  assert.deepEqual(command, {
    command_id: COMMAND_ID, node_id: 'owner-gate',
    approval_scope: 'release-output', decision: 'approved',
  });
  assert.deepEqual([...DECISIONS], ['approved', 'rejected']);
  for (const change of [
    { decision: 'maybe' }, { decision: true }, { commandId: 'bad' },
    { nodeId: '../gate' }, { approvalScope: '' },
  ]) {
    assert.throws(() => approvalCommand({
      commandId: COMMAND_ID, nodeId: 'owner-gate',
      approvalScope: 'release-output', decision: 'approved', ...change,
    }));
  }
  assert.throws(() => approvalCommand({
    commandId: COMMAND_ID, nodeId: 'owner-gate',
    approvalScope: 'release-output', decision: 'approved', extra: 1,
  }));
});

test('the awaiting view shows exactly the pending gates and nothing raw', () => {
  const outcome = {
    run_id: RUN_ID,
    awaiting_human: [['owner-gate', 'release-output'], ['owner-gate', 'publish']],
    completed_node_ids: ['intake', 'writer'],
    counters: { intake: 1, writer: 1 },
    result_refs: [['exec-1', { kind: 'run_manifest' }]],
  };
  const view = awaitingHumanView(outcome);
  assert.equal(view.complete, false);
  assert.deepEqual(view.gates, [
    { nodeId: 'owner-gate', scope: 'release-output',
      readPath: `/api/v1/runs/${RUN_ID}/approvals/owner-gate/release-output` },
    { nodeId: 'owner-gate', scope: 'publish',
      readPath: `/api/v1/runs/${RUN_ID}/approvals/owner-gate/publish` },
  ]);
  assert.deepEqual(view.completedNodeIds, ['intake', 'writer']);
  assert.equal('result_refs' in view, false);
  assert.equal('counters' in view, false);
  const done = awaitingHumanView({ ...outcome, awaiting_human: [] });
  assert.equal(done.complete, true);
  assert.deepEqual(done.gates, []);
  assert.throws(() => awaitingHumanView({ ...outcome, awaiting_human: 'later' }));
  assert.throws(() => awaitingHumanView({ ...outcome, run_id: 'bad' }));
});

test('remaining gates drop only the ones whose receipt was recorded', () => {
  const view = awaitingHumanView({
    run_id: RUN_ID, completed_node_ids: [],
    awaiting_human: [['owner-gate', 'release-output'], ['owner-gate', 'publish']],
  });
  const receipt = { command_id: COMMAND_ID, state: 'recorded', decision: 'approved',
    approval_ref: { kind: 'action_approval', id: RUN_ID, version: 1, sha256: 'a'.repeat(64) },
    links: { self: `/api/v1/runs/${RUN_ID}/approvals/owner-gate/release-output`,
             events: '/api/v1/events' } };
  const left = remainingGates(view, [receiptSummary(receipt)]);
  assert.deepEqual(left.map(g => g.scope), ['publish']);
  // a receipt for another run or a rejected decision never clears a gate
  const foreign = receiptSummary({ ...receipt,
    links: { ...receipt.links, self: `/api/v1/runs/${COMMAND_ID}/approvals/owner-gate/publish` } });
  assert.equal(remainingGates(view, [foreign]).length, 2);
  const rejected = receiptSummary({ ...receipt, decision: 'rejected',
    links: { ...receipt.links, self: `/api/v1/runs/${RUN_ID}/approvals/owner-gate/publish` } });
  assert.equal(remainingGates(view, [rejected]).length, 2);
  assert.equal(rejected.decision, 'rejected');
});

test('receipt summaries are closed projections of the server receipt', () => {
  const summary = receiptSummary({
    command_id: COMMAND_ID, state: 'recorded', decision: 'approved',
    approval_ref: { kind: 'action_approval', id: RUN_ID, version: 1, sha256: 'b'.repeat(64) },
    event_cursor: { sequence: 3 },
    links: { self: `/api/v1/runs/${RUN_ID}/approvals/owner-gate/release-output`, events: '/api/v1/events' },
  });
  assert.deepEqual(summary, {
    commandId: COMMAND_ID, decision: 'approved', runId: RUN_ID,
    nodeId: 'owner-gate', scope: 'release-output',
    approvalRef: { kind: 'action_approval', id: RUN_ID, version: 1, sha256: 'b'.repeat(64) },
    eventsPath: '/api/v1/events',
  });
  assert.throws(() => receiptSummary({ state: 'recorded' }));
  assert.throws(() => receiptSummary({
    command_id: COMMAND_ID, state: 'recorded', decision: 'approved',
    approval_ref: { kind: 'design_approval', id: RUN_ID, version: 1, sha256: 'b'.repeat(64) },
    links: { self: `/api/v1/runs/${RUN_ID}/approvals/owner-gate/release-output`, events: '/api/v1/events' },
  }));
});

// --- independent review closures (2026-09-17) ---------------------------------

const BASE = `/${'2'.repeat(32)}/`;

test('F4: routes and receipts honour the deployment base path', () => {
  const routes = approvalRoutes(RUN_ID, BASE);
  assert.equal(routes.record, `${BASE}api/v1/runs/${RUN_ID}/approvals`);
  assert.equal(routes.read('owner-gate', 'release-output'),
    `${BASE}api/v1/runs/${RUN_ID}/approvals/owner-gate/release-output`);
  const receipt = { command_id: COMMAND_ID, state: 'recorded', decision: 'approved',
    approval_ref: { kind: 'action_approval', id: RUN_ID, version: 1, sha256: 'c'.repeat(64) },
    links: { self: `${BASE}api/v1/runs/${RUN_ID}/approvals/owner-gate/release-output`,
             events: `${BASE}api/v1/events` } };
  const summary = receiptSummary(receipt);
  assert.equal(summary.runId, RUN_ID);
  assert.equal(summary.nodeId, 'owner-gate');
  assert.equal(summary.scope, 'release-output');
  const view = awaitingHumanView({ run_id: RUN_ID, completed_node_ids: [],
    awaiting_human: [['owner-gate', 'release-output']] }, BASE);
  assert.equal(view.gates[0].readPath, routes.read('owner-gate', 'release-output'));
  assert.deepEqual(remainingGates(view, [summary]), []);
  for (const bad of ['/not-hex/', 'relative/', '/x/y/']) {
    assert.throws(() => approvalRoutes(RUN_ID, bad));
  }
});

test('F8: only a recorded receipt summary can clear a gate', () => {
  const base = { command_id: COMMAND_ID, decision: 'approved',
    approval_ref: { kind: 'action_approval', id: RUN_ID, version: 1, sha256: 'd'.repeat(64) },
    links: { self: `/api/v1/runs/${RUN_ID}/approvals/owner-gate/release-output`, events: '/api/v1/events' } };
  assert.throws(() => receiptSummary({ ...base, state: 'pending' }));
  assert.throws(() => receiptSummary({ ...base }));
  const view = awaitingHumanView({ run_id: RUN_ID, completed_node_ids: [],
    awaiting_human: [['owner-gate', 'release-output']] });
  assert.throws(() => remainingGates(view, [{ decision: 'approved', runId: RUN_ID,
    nodeId: 'owner-gate', scope: 'release-output' }]));
});
