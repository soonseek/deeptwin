// T087: the execution-bound approval GUI logic over the fixed routes
// GET/POST {base}api/v1/runs/{run}/approvals/executions. Pure functions: the
// owner is shown exactly the execution, executing node, attempt number and
// inputs digest the ledger asked about; the command echoes them verbatim; a
// decision for attempt 1 never authorizes the retry attempt 2.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  EXECUTION_STATES,
  attemptAuthorized,
  executionApprovalCommand,
  executionApprovalPrompt,
  executionApprovalRoutes,
  executionRequestsView,
} from '../static/approvals.mjs';

const RUN_ID = '00000000-0000-4000-8000-00000000a0a1';
const EXECUTION_ID = '00000000-0000-5000-8000-0000000000e1';
const COMMAND_ID = '11111111-2222-4333-8444-555555555555';
const SCOPE = 'tool-0f6c3a52-2d5b-5b1a-9f0e-3f0d6d7c1a11';
const DIGEST = 'ab'.repeat(32);

function ask(changes = {}) {
  return {
    run_id: RUN_ID, node_id: 'tool-gate', approval_scope: SCOPE, execution_id: EXECUTION_ID,
    execution_node_id: 'writer', attempt_no: 1, inputs_digest: DIGEST, state: 'pending',
    approval_ref: null, ...changes,
  };
}

test('routes name the fixed execution-approval path under the deployment base', () => {
  assert.deepEqual(executionApprovalRoutes(RUN_ID), {
    list: `/api/v1/runs/${RUN_ID}/approvals/executions`,
    record: `/api/v1/runs/${RUN_ID}/approvals/executions`,
  });
  const base = `/${'a'.repeat(32)}/`;
  assert.equal(executionApprovalRoutes(RUN_ID, base).record,
    `/${'a'.repeat(32)}/api/v1/runs/${RUN_ID}/approvals/executions`);
  assert.throws(() => executionApprovalRoutes('../x'));
  assert.deepEqual([...EXECUTION_STATES], ['pending', 'approved', 'rejected', 'superseded']);
});

test('the owner is shown the exact execution and attempt, and the command echoes it', () => {
  const view = executionRequestsView({ run_id: RUN_ID, requests: [ask()] });
  const [entry] = view.pending;
  const prompt = executionApprovalPrompt(entry);
  assert.match(prompt, new RegExp(`실행 ${EXECUTION_ID}`));
  assert.match(prompt, /노드 writer/);
  assert.match(prompt, /시도 1 /);
  assert.match(prompt, new RegExp(`sha256 ${DIGEST}`));
  assert.deepEqual(executionApprovalCommand(entry, { commandId: COMMAND_ID, decision: 'approved' }), {
    command_id: COMMAND_ID, node_id: 'tool-gate', approval_scope: SCOPE, execution_id: EXECUTION_ID,
    execution_node_id: 'writer', attempt_no: 1, inputs_digest: DIGEST, decision: 'approved',
  });
  const none = executionRequestsView({ run_id: RUN_ID, requests: [ask({ inputs_digest: null })] }).pending[0];
  assert.match(executionApprovalPrompt(none), /입력 digest 없음/);
  assert.equal(executionApprovalCommand(none, { commandId: COMMAND_ID, decision: 'rejected' }).inputs_digest, null);
  // only an entry issued by the view can be decided — never a hand-built object
  assert.throws(() => executionApprovalCommand(Object.freeze({ ...entry }), { commandId: COMMAND_ID, decision: 'approved' }));
  assert.throws(() => executionApprovalCommand(entry, { commandId: COMMAND_ID, decision: 'maybe' }));
  assert.throws(() => executionApprovalCommand(entry, { commandId: 'bad', decision: 'approved' }));
});

test('a retry attempt is its own ask: attempt 1 approved never authorizes attempt 2', () => {
  const view = executionRequestsView({ run_id: RUN_ID, requests: [
    ask({ state: 'approved', approval_ref: { kind: 'action_approval' } }),
    ask({ attempt_no: 2 }),
  ] });
  const attempt = { nodeId: 'tool-gate', scope: SCOPE, executionId: EXECUTION_ID };
  assert.equal(attemptAuthorized(view, { ...attempt, attemptNo: 1 }), true);
  assert.equal(attemptAuthorized(view, { ...attempt, attemptNo: 2 }), false);
  assert.deepEqual(view.pending.map(entry => entry.attemptNo), [2]);
  const [retry] = view.pending;
  assert.match(executionApprovalPrompt(retry), /시도 2 /);
  assert.equal(executionApprovalCommand(retry, { commandId: COMMAND_ID, decision: 'approved' }).attempt_no, 2);
  // a decided attempt is not offered again
  assert.throws(() => executionApprovalCommand(view.requests[0], { commandId: COMMAND_ID, decision: 'approved' }));
  // a superseded decision authorizes nothing and cannot be decided again
  const superseded = executionRequestsView({ run_id: RUN_ID, requests: [ask({ state: 'superseded' })] });
  assert.equal(attemptAuthorized(superseded, { ...attempt, attemptNo: 1 }), false);
  assert.equal(superseded.pending.length, 0);
});

test('the listing grammar is closed', () => {
  for (const change of [
    { run_id: '00000000-0000-4000-8000-00000000a0a2' }, { state: 'maybe' }, { attempt_no: 0 },
    { attempt_no: '1' }, { attempt_no: 1001 }, { execution_id: 'x' }, { execution_node_id: '../w' },
    { inputs_digest: 'ABC' }, { node_id: '' },
  ]) {
    assert.throws(() => executionRequestsView({ run_id: RUN_ID, requests: [ask(change)] }), undefined, JSON.stringify(change));
  }
  assert.throws(() => executionRequestsView({ run_id: RUN_ID, requests: [ask(), ask()] }));
  assert.throws(() => executionRequestsView({ run_id: RUN_ID }));
});
