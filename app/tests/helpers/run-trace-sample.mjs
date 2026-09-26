// A synthetic run-trace-v1 payload shaped like the server's (services/run_traces.py), shared by
// the run trace unit tests: a writer model call recorded by the executor, a store step whose
// attempt 1 failed and attempt 2 succeeded, and a final report. Test-actor data only.

export const RUN = '00000000-0000-4000-8000-00000000aaa1';
export const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
export const ref = (n, kind = 'artifact') => ({ kind, id: id(n), version: 1, sha256: 'a'.repeat(64) });
export const art = (n, role, media = 'text/markdown') => ({ artifact_id: id(n), role, ordinal: 0, declared_media_type: media,
  size: 120 + n, sha256: String(n % 10).repeat(64), result_ref: ref(n) });

export function sampleTrace(overrides = {}) {
  const draft = art(200, 'draft');
  const report = art(300, 'report');
  const source = art(100, 'source');
  const attempt = (no, outcome, outputs, extra = {}) => ({
    attempt_id: id(500 + no), attempt_no: no, phase: 'terminal', terminal_outcome: outcome,
    reserved_at_utc: `2026-09-26T05:00:1${no}.000000Z`, sent_at_utc: `2026-09-26T05:00:1${no}.100000Z`,
    transport_closed_at_utc: 'not_recorded', updated_at_utc: `2026-09-26T05:00:1${no}.300000Z`,
    ended_at_utc: `2026-09-26T05:00:1${no}.200000Z`, send_finality: 'remote_terminal', cancel_state: 'none',
    usage_finality: 'final', remote_terminal_observed: outcome, produced_visit_result: outcome === 'succeeded',
    result_ref: outcome === 'succeeded' ? ref(400) : 'not_recorded', outputs,
    error: outcome === 'succeeded' ? null : { outcome, reason_code: 'provider_terminal', remote_terminal_observed: outcome },
    tool_calls: [{ tool_call_id: id(600 + no), tool_id: 'test_actor_notify', version: '1.0.0',
      effect_class: 'external_irreversible', state: outcome, declared_inputs: [{ ordinal: 0, role: 'document_source',
        media_type: 'text/plain', declared_size: 224, sha256: 'b'.repeat(64) }], binding: 'not_recorded',
      approval_ref: ref(700 + no, 'action_approval'), requested_at_utc: `2026-09-26T05:00:1${no}.100000Z`,
      settled_at_utc: `2026-09-26T05:00:1${no}.200000Z`, result_ref: outcome === 'succeeded' ? ref(400) : 'not_recorded',
      result_artifacts: [] }],
    budget_reservation: { state: 'finalized', usage_finality: 'known', reserved: { model_calls: 0, tool_calls: 1,
      output_bytes: 10, api_microunits: 'not_recorded' }, settled: { model_calls: 0, tool_calls: 1, output_bytes: 5,
      api_microunits: 'not_recorded' }, reserved_at_utc: 'not_recorded', settled_at_utc: 'not_recorded' },
    cost: { state: 'unknown', basis: 'subscription_mode' },
    journal: [{ transition: 'reserved', at_utc: `2026-09-26T05:00:1${no}.000000Z` },
      { transition: 'send_intent', at_utc: `2026-09-26T05:00:1${no}.100000Z` }],
    ...extra,
  });
  const visit = (node, n, outputs, inputs, extra = {}) => ({ execution_id: id(n), visit_no: 1, loop_index: 0,
    status: 'completed', recorded_at_utc: `2026-09-26T05:00:0${n % 10}.000000Z`,
    result_ref: outputs.length ? outputs[0].result_ref : 'not_recorded', outputs, produced_by_attempt_no: 'not_recorded',
    inputs, attempts: [], model_calls: [], ...extra });
  const trace = {
    schema_version: 'run-trace-v1', run_id: RUN, phase: 'completed', graph_ref: ref(1, 'graph'), graph_digest: 'c'.repeat(64),
    work: { work_revision_ref: ref(2, 'work_revision'), work_id: id(2), revision: 1, title: '화요일 공간 안내' },
    budget_mode: 'subscription', started_at_utc: '2026-09-26T05:00:00.000000Z', ended_at_utc: '2026-09-26T05:00:21.500000Z',
    stops: [{ reason: 'infrastructure_failure', at_utc: '2026-09-26T05:00:11.500000Z', duration_ms: 11500 },
      { reason: 'completed', at_utc: '2026-09-26T05:00:21.500000Z', duration_ms: 21500 }],
    totals: { model_calls: 1, tool_calls: 2, attempts: 2, retries: 1, input_tokens: 812, output_tokens: 164,
      tokens_complete: true, cost: { state: 'unknown', microunits: 'not_recorded', currency: null } },
    exit: { node_ids: ['report'], basis: 'completion_criteria' },
    final_results: [{ ...report, node_id: 'report', execution_id: id(15), visit_no: 1, produced_by_attempt_no: 'not_recorded' }],
    stopped_at: [],
    nodes: [
      { node_id: 'intake', kind: 'deterministic', responsibility: '업무 설명을 정리한다', state: 'completed',
        visits: [visit('intake', 11, [source], [])] },
      { node_id: 'writer', kind: 'agent', responsibility: '안내문 초안을 쓴다', state: 'completed',
        visits: [visit('writer', 12, [draft], [{ from_node_id: 'intake', from_execution_id: id(11), from_attempt_no: 'not_recorded',
          result_ref: source.result_ref, artifacts: [source] }], { model_calls: [{ call_id: id(800), recorded_by: 'claude_run_executor',
          provider: 'claude', model_label: 'model-x', observed_model: 'model-x', effort: 'low', max_output_tokens: 512,
          state: 'completed', stop_reason: 'end_turn', error: null, tokens: { input: 812, output: 164,
            cache_creation_input: 0, cache_read_input: 0 }, started_at_utc: '2026-09-26T05:00:02.100000Z',
          ended_at_utc: '2026-09-26T05:00:02.600000Z', inputs: [source.result_ref], output_ref: draft.result_ref,
          cost: { state: 'unknown', basis: 'not_recorded' }, reasoning: 'not_stored', provider_message_id: 'm', request_id: 'r' }] })] },
      { node_id: 'publish', kind: 'deterministic', responsibility: '저장 도구로 기록한다', state: 'completed',
        visits: [visit('publish', 14, [], [{ from_node_id: 'writer', from_execution_id: id(12), from_attempt_no: 'not_recorded',
          result_ref: draft.result_ref, artifacts: [draft] }], { produced_by_attempt_no: 2, result_ref: ref(400),
          attempts: [attempt(1, 'failed', []), attempt(2, 'succeeded', [])] })] },
      { node_id: 'report', kind: 'deterministic', responsibility: '최종 보고서로 묶는다', state: 'completed',
        visits: [visit('report', 15, [report], [{ from_node_id: 'publish', from_execution_id: id(14), from_attempt_no: 2,
          result_ref: ref(400), artifacts: [] }])] },
    ],
    handoffs: [
      { from_node_id: 'intake', from_execution_id: id(11), from_attempt_no: 'not_recorded', to_node_id: 'writer',
        to_execution_id: id(12), to_attempt_nos: [], artifacts: [source], result_ref: source.result_ref,
        designed_edge_ids: ['e1'], receipt: 'not_recorded' },
      { from_node_id: 'writer', from_execution_id: id(12), from_attempt_no: 'not_recorded', to_node_id: 'publish',
        to_execution_id: id(14), to_attempt_nos: [1, 2], artifacts: [draft], result_ref: draft.result_ref,
        designed_edge_ids: ['e2'], receipt: 'not_recorded' },
    ],
    approvals: { gates: [{ node_id: 'tool-gate', approval_scope: 'release-output', decision: 'approved',
      decided_at_utc: '2026-09-26T05:00:05.000000Z', approval_ref: ref(900, 'action_approval'), state: 'consumed' }],
    executions: [1, 2].map(no => ({ node_id: 'tool-gate', approval_scope: `tool-${id(950)}`, execution_id: id(14),
      execution_node_id: 'publish', attempt_no: no, state: 'approved', decided_at_utc: `2026-09-26T05:00:1${no}.000000Z`,
      expires_at_utc: '2026-09-26T05:30:00.000000Z', inputs_digest: 'd'.repeat(64), approval_ref: ref(700 + no, 'action_approval') })) },
    timeline: [
      { at_utc: '2026-09-26T05:00:01.000000Z', kind: 'visit', node_id: 'intake', execution_id: id(11), visit_no: 1, status: 'completed' },
      { at_utc: '2026-09-26T05:00:02.100000Z', kind: 'model_call', node_id: 'writer', execution_id: id(12), visit_no: 1,
        status: 'completed', ended_at_utc: '2026-09-26T05:00:02.600000Z' },
      { at_utc: '2026-09-26T05:00:11.000000Z', kind: 'attempt', node_id: 'publish', execution_id: id(14), visit_no: 1,
        attempt_no: 1, status: 'failed', ended_at_utc: '2026-09-26T05:00:11.200000Z' },
      { at_utc: '2026-09-26T05:00:12.000000Z', kind: 'attempt', node_id: 'publish', execution_id: id(14), visit_no: 1,
        attempt_no: 2, status: 'succeeded', ended_at_utc: '2026-09-26T05:00:12.200000Z' },
    ],
    gaps: [{ category: 'handoff_receipt', reason: 'x' }, { category: 'model_cost', reason: 'y' }],
    links: { self: `/api/v1/runs/${RUN}/trace` },
    ...overrides,
  };
  return trace;
}
