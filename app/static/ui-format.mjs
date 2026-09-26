// Display rules shared by every page (docs/ui/2026-09-26-product-ux-redesign.md §2.3, §8):
// time as "3분 전" beside the absolute local time to the second, short identifiers with the
// full value kept for the "기술 정보" disclosure, byte sizes, media types as Korean labels,
// and one dictionary from internal terms (node kinds, edge kinds, failure policies, run
// controls, public event types) to the owner's words. Pure functions only: no DOM, no
// network. An unknown value is never dropped or guessed at: it falls back to a plain label
// and the caller keeps the raw value in the technical disclosure.

// graph-version-v1 node kinds (app/domain/graph_schema.py NODE_KINDS)
export const NODE_KIND_LABELS = Object.freeze({
  agent: '에이전트', deterministic: '정해진 처리', router: '분기', join: '합류', human_gate: '사람 승인',
  bounded_loop: '제한 반복',
});

// graph-version-v1 edge kinds (EDGE_KINDS)
export const EDGE_KIND_LABELS = Object.freeze({
  artifact: '산출물', control: '제어', approval: '승인', observation: '관찰',
});

// graph-version-v1 failure policies (FAILURE_POLICIES)
export const FAILURE_POLICY_LABELS = Object.freeze({
  fail_run: '실패하면 실행 전체 멈춤',
  block_dependants: '실패하면 뒤 단계 멈춤',
  continue_optional: '실패해도 나머지는 계속(선택 단계)',
});

// the run panel's three owner commands (run-panel.mjs, runtime.mjs)
export const RUN_CONTROL_LABELS = Object.freeze({
  resume: '이어서 진행',
  cancel: '새 작업 보내기 중단',
  recover: '복구 시도',
});

// ---- the run trace (GET {base}api/v1/runs/{run}/trace, run-trace-v1; UI phase 3) ----------
// the value the server writes for a fact the runtime did not record
export const NOT_RECORDED = 'not_recorded';
export const NOT_RECORDED_LABEL = '기록 없음';

// the run's phase (app/services/runs.py PHASES) as a chip: words, glyph and tone
export const RUN_PHASE_TEXT = Object.freeze({
  created: ['시작 전', 'neutral'], running: ['미완료', 'info'], awaiting_human: ['사람 승인 대기', 'warn'],
  rejected: ['거절됨', 'error'], cancelled: ['취소됨', 'neutral'], completed: ['완료', 'ok'],
});
// a node's state in the trace (services/run_traces.py)
export const TRACE_NODE_STATE_TEXT = Object.freeze({
  completed: ['완료', 'ok'], failed: ['실패', 'error'], pending: ['대기', 'info'],
  awaiting_approval: ['승인 대기', 'warn'], rejected: ['거절됨', 'error'], not_visited: ['미방문', 'neutral'],
});
export const VISIT_STATUS_TEXT = Object.freeze({
  completed: ['완료', 'ok'], failed: ['실패', 'error'], no_result: ['결과 없음', 'warn'],
});
// an attempt's terminal outcome (app/runtime/ledger.py TERMINAL_OUTCOMES)
export const ATTEMPT_OUTCOME_TEXT = Object.freeze({
  succeeded: ['완료', 'ok'], failed: ['실패', 'error'], denied: ['거부됨', 'error'], timed_out: ['시간 초과', 'error'],
  cancelled: ['취소됨', 'neutral'], outcome_unknown: ['결과 미상', 'warn'],
});
// why an attempt ended (RESULT_REASONS), in the owner's words
export const RESULT_REASON_LABELS = Object.freeze({
  provider_terminal: '도구·제공자의 응답으로 끝남', validation_failed: '결과 검증 실패', permission_denied: '권한 거부',
  deadline: '시간 초과', transport_failure: '전송 실패', transport_unknown: '전송 결과 미상',
  cancel_requested: '취소 요청', restart_reconciliation: '재시작 뒤 대조',
});
// the attempt journal's transitions (JOURNAL_TRANSITIONS)
export const JOURNAL_LABELS = Object.freeze({
  reserved: '예약', preflighting: '사전 확인', awaiting_human: '사람 대기', send_intent: '보냄', running: '실행 중',
  validating: '검증 중', lease_renewed: '작업 연장', cancel_requested: '취소 요청', cancel_terminal: '취소 끝',
  result_accepted: '결과 받음', result_duplicate: '중복 결과', result_late: '늦은 결과', recovery_pending: '복구 대기',
  recovery_terminal: '복구 끝', transport_observed: '전송 확인', response_captured: '응답 받음',
});
// a ToolCall's state (TOOL_CALL_STATES) and the ports' effect classes
export const TOOL_CALL_STATE_TEXT = Object.freeze({
  intent: ['결과 대기', 'info'], succeeded: ['성공', 'ok'], failed: ['실패', 'error'], unknown: ['결과 미상', 'warn'],
});
export const EFFECT_CLASS_LABELS = Object.freeze({
  none: '효과 없음', read: '읽기', write_reversible: '되돌릴 수 있는 쓰기',
  external_reversible: '되돌릴 수 있는 외부 효과', external_irreversible: '되돌릴 수 없는 외부 효과',
  instance_critical_secret: '인스턴스 비밀', instance_critical_storage: '인스턴스 저장소',
});
// a model call's terminal state as the Claude executor recorded it
export const MODEL_CALL_STATE_TEXT = Object.freeze({
  completed: ['완료', 'ok'], failed: ['실패', 'error'], cancelled: ['취소됨', 'neutral'], unknown: ['결과 미상', 'warn'],
});
export const APPROVAL_STATE_TEXT = Object.freeze({
  consumed: ['승인됨', 'ok'], approved: ['승인됨', 'ok'], pending: ['결정 대기', 'warn'], rejected: ['거절됨', 'error'],
  expired: ['시한 지남', 'neutral'], superseded: ['새 복구로 대체됨', 'neutral'],
});
// the stop events of a run (run.stopped reason_code)
export const STOP_REASON_LABELS = Object.freeze({
  completed: '완료', cancelled: '취소·거절로 멈춤', infrastructure_failure: '실행 중 실패로 멈춤',
});
// why a trace category is absent (services/run_traces.py GAP_REASONS), in the owner's words
export const TRACE_GAP_LABELS = Object.freeze({
  attempt_tokens: '시도 기록에는 예약과 정산만 있고, 제공자가 알린 토큰 수는 없습니다.',
  handoff_receipt: '받은 쪽의 수신 확인은 이 실행기가 기록하지 않습니다. 보낸 결과와 받은 수행만 기록됩니다.',
  handler_attempts: '실행기가 직접 처리한 단계는 시도 기록이 없습니다. 결과와 호출 기록은 수행에 붙어 있습니다.',
  handler_error: '직접 처리한 단계가 실패한 이유는 기록하지 않습니다(실패했다는 사실만 남습니다).',
  model_cost: '이 실행 경로는 모델 호출의 토큰 수는 기록하지만 비용은 기록하지 않습니다.',
  reasoning: '모델의 숨은 추론은 저장하지 않으므로 볼 수 없습니다.',
});

export function approvalScopeLabel(scope) {
  if (typeof scope !== 'string') return '';
  if (scope === 'release-output') return '결과 내보내기 승인';
  if (/^tool-[0-9a-f-]{36}$/.test(scope)) return '도구 호출 승인(시도마다)';
  return scope;
}

// a count of currency microunits as money; USD shows "$", others their code
export function formatMoney(microunits, currency) {
  if (!Number.isSafeInteger(microunits) || microunits < 0) return '';
  const amount = microunits / 1_000_000;
  const digits = amount >= 1 ? 2 : amount >= 0.01 ? 3 : 4;
  const text = amount.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '');
  return currency === 'USD' ? `$${text}` : `${text} ${typeof currency === 'string' ? currency : ''}`.trim();
}

// a recorded cost in words: an estimate says so, an unrecorded one is "미확인"
export function costText(cost) {
  if (typeof cost !== 'object' || cost === null) return '미확인';
  const money = formatMoney(cost.microunits, cost.currency);
  if (cost.state === 'settled' && money) return `${money} (정산 기록)`;
  if (cost.state === 'estimate' && money) return `약 ${money} (예약 상한 기준 추정)`;
  if (cost.state === 'partial_estimate' && money) return `약 ${money} 이상 (일부 미확인)`;
  if (cost.basis === 'subscription_mode') return '미확인 (구독 방식: 호출별 금액 없음)';
  return '미확인';
}

// a count, or the plain "기록 없음" for a value the runtime did not record
export function countText(value, unit = '') {
  if (value === NOT_RECORDED || value === null || value === undefined) return NOT_RECORDED_LABEL;
  if (!Number.isSafeInteger(value)) return NOT_RECORDED_LABEL;
  return `${value.toLocaleString('ko-KR')}${unit}`;
}

// how long between two recorded stamps; either missing is "기록 없음", never a guess
export function durationText(start, end) {
  const from = parseUtc(start);
  const to = parseUtc(end);
  if (from === null || to === null) return NOT_RECORDED_LABEL;
  const ms = Math.max(0, to.getTime() - from.getTime());
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.round(ms / 100) / 10;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}초`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds - minutes * 60);
  if (minutes < 60) return rest ? `${minutes}분 ${rest}초` : `${minutes}분`;
  const hours = Math.floor(minutes / 60);
  return `${hours}시간 ${minutes - hours * 60}분`;
}

// a time of day (HH:MM:SS, local) for a timeline line; the full stamp is the title
export function clockTime(value) {
  const date = parseUtc(value);
  if (date === null) return '';
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

// a [label, tone] pair from one of the tables above; unknown values stay themselves
export function stateText(table, value) {
  if (typeof value === 'string' && Object.hasOwn(table, value)) return table[value];
  return [value === NOT_RECORDED || value === null || value === undefined ? NOT_RECORDED_LABEL : String(value), 'neutral'];
}

// public event statuses (app/domain/public_events.py STATUSES), spelled out beside a glyph
export const EVENT_STATUS_LABELS = Object.freeze({
  succeeded: '성공', failed: '실패', cancelled: '취소', pending: '대기', unknown: '결과 미상',
  started: '시작됨', progress: '진행 중', blocked: '막힘',
});
// the chip tone of each status: never colour alone, the label and glyph say it too
export const EVENT_STATUS_TONES = Object.freeze({
  succeeded: 'ok', failed: 'error', cancelled: 'neutral', pending: 'info', unknown: 'warn',
  started: 'info', progress: 'info', blocked: 'warn',
});

// public event error codes (app/domain/public_events.py ERROR_CODES)
export const EVENT_ERROR_LABELS = Object.freeze({
  invalid_input: '입력 형식 오류', unauthenticated: '세션 없음', access_denied: '접근 거부',
  stale_state: '그사이 바뀐 상태', not_found: '대상을 찾지 못함', capacity_exhausted: '처리 한도 초과',
  dependency_unavailable: '연결된 구성 요소 응답 없음', storage_failed: '저장 실패', corrupt: '손상된 기록',
  missing: '기록 없음', outcome_unknown: '결과 미상', budget_exhausted: '한도 소진', cancelled: '취소됨',
});

// every public event type the server can emit (app/domain/events.py EVENT_TYPES; a Python
// mirror test keeps this list complete): [topic, sentence]. The sentence is used for a
// succeeded event; any other status shows the topic beside the status, so a failed or
// pending record never reads as done.
export const EVENT_TEXT = Object.freeze({
  'alternative.saved': ['내 버전 저장', '내 버전을 저장했습니다'],
  'approval.decided': ['승인 결정', '승인 결정을 기록했습니다'],
  'approval.requested': ['사람 승인 요청', '사람 승인을 요청했습니다'],
  'artifact.missing': ['산출물 없음', '산출물을 찾지 못했습니다'],
  'artifact.sealed': ['산출물 보관', '산출물을 보관했습니다'],
  'attempt.dispatched': ['시도 보내기', '시도를 보냈습니다'],
  'attempt.reserved': ['시도 예약', '시도를 예약했습니다'],
  'attempt.response_captured': ['시도 응답 받기', '시도의 응답을 받았습니다'],
  'attempt.terminal': ['시도 끝', '시도가 끝났습니다'],
  'auth.recovery_completed': ['소유자 복구 완료', '소유자 복구를 마쳤습니다'],
  'auth.recovery_failed': ['소유자 복구 실패', '소유자 복구에 실패했습니다'],
  'auth.recovery_started': ['소유자 복구 시작', '소유자 복구를 시작했습니다'],
  'backup.created': ['백업 만들기', '백업을 만들었습니다'],
  'backup.verified': ['백업 확인', '백업을 확인했습니다'],
  'candidate.created': ['변경 후보 만들기', '변경 후보를 만들었습니다'],
  'candidate.frozen': ['변경 후보 고정', '변경 후보를 고정했습니다'],
  'catalog.invalidated': ['모델 목록 무효', '모델 목록이 더는 유효하지 않습니다'],
  'catalog.refreshed': ['모델 목록 읽기', '모델 목록을 새로 읽었습니다'],
  'connection.changed': ['모델 연결 변경', '모델 연결을 바꿨습니다'],
  'connection.checked': ['모델 연결 확인', '모델 연결을 확인했습니다'],
  'credential.cleanup_completed': ['자격증명 정리', '자격증명 정리를 마쳤습니다'],
  'credential.erasure_confirmed': ['자격증명 삭제 확인', '자격증명 삭제를 확인했습니다'],
  'credential.erasure_failed': ['자격증명 삭제 실패', '자격증명 삭제에 실패했습니다'],
  'credential.retired': ['자격증명 폐기', '자격증명을 폐기했습니다'],
  'deployment.receipt_committed': ['배포 영수증 기록', '배포 영수증을 기록했습니다'],
  'deployment.request_accepted': ['배포 요청 수락', '배포 요청이 받아들여졌습니다'],
  'deployment.request_cancelled': ['배포 요청 취소', '배포 요청을 취소했습니다'],
  'deployment.request_expired': ['배포 요청 만료', '배포 요청이 만료되었습니다'],
  'deployment.request_prepared': ['배포 요청 준비', '배포 요청을 준비했습니다'],
  'design.proposed': ['설계 후보 제안', '설계 후보를 제안했습니다'],
  'design.repaired': ['설계 후보 수정', '설계 후보를 고쳤습니다'],
  'design.selected': ['설계 선택', '설계를 선택했습니다'],
  'difference.observed': ['차이 관찰', '원본과 내 버전의 차이를 관찰했습니다'],
  'evaluation.result': ['평가 결과', '평가 결과를 기록했습니다'],
  'evaluation.started': ['평가 시작', '평가를 시작했습니다'],
  'export.created': ['내보내기 파일 만들기', '내보내기 파일을 만들었습니다'],
  'export.previewed': ['내보내기 미리보기', '내보낼 내용을 미리 봤습니다'],
  'extension.binding_activated': ['확장 연결 켜기', '확장 연결을 켰습니다'],
  'extension.binding_changed': ['확장 연결 변경', '확장 연결을 바꿨습니다'],
  'extension.binding_disabled': ['확장 연결 끄기', '확장 연결을 껐습니다'],
  'extension.binding_rolled_back': ['확장 연결 되돌리기', '확장 연결을 이전으로 되돌렸습니다'],
  'extension.binding_superseded': ['확장 연결 교체', '확장 연결이 새 연결로 교체되었습니다'],
  'extension.candidate_registered': ['확장 후보 등록', '확장 후보를 등록했습니다'],
  'extension.compatibility_failed': ['확장 호환성 검사 실패', '확장 호환성 검사에 실패했습니다'],
  'extension.discovered': ['확장 발견', '확장을 발견했습니다'],
  'extension.enabled': ['확장 켜기', '확장을 켰습니다'],
  'extension.failed': ['확장 문제', '확장에 문제가 생겼습니다'],
  'extension.qualified': ['확장 적합성 통과', '확장이 적합성 검사를 통과했습니다'],
  'extension.removed': ['확장 제거', '확장을 제거했습니다'],
  'extension.revoked': ['확장 철회', '확장 사용을 철회했습니다'],
  'extension.rollback_retention_consumed': ['되돌리기 보존분 사용', '확장 되돌리기에 보존분을 사용했습니다'],
  'extension.rollback_retention_created': ['되돌리기 보존분 만들기', '확장 되돌리기 보존분을 남겼습니다'],
  'extension.rollback_retention_released': ['되돌리기 보존 해제', '확장 되돌리기 보존을 해제했습니다'],
  'extension.staged': ['확장 설치 대기', '확장을 설치 대기 상태로 두었습니다'],
  'extension.suspended': ['확장 일시 중지', '확장을 일시 중지했습니다'],
  'extension.verified': ['확장 설치 검증', '확장 설치를 검증했습니다'],
  'handoff.acknowledged': ['전달물 수신 확인', '전달물 수신을 확인했습니다'],
  'handoff.delivered': ['전달', '다음 단계로 산출물을 전달했습니다'],
  'hypothesis.updated': ['설명 갱신', '차이에 대한 설명을 갱신했습니다'],
  'ingestion.completed': ['자료 읽기', '자료 읽기를 마쳤습니다'],
  'ingestion.failed': ['자료 읽기 실패', '자료 읽기에 실패했습니다'],
  'inquiry.declined': ['탐구 보류', '탐구를 하지 않기로 했습니다'],
  'inquiry.evidence': ['탐구 근거 추가', '탐구 근거를 추가했습니다'],
  'inquiry.frozen': ['탐구 질문 고정', '탐구 질문을 고정했습니다'],
  'lens.abstained': ['렌즈 판단 보류', '렌즈가 판단을 보류했습니다'],
  'lens.composed': ['렌즈 조합', '렌즈를 조합했습니다'],
  'lens.selected': ['렌즈 선택', '렌즈를 골랐습니다'],
  'loop.stopped': ['개선 반복 멈춤', '개선 반복을 멈췄습니다'],
  'loop.updated': ['개선 반복 갱신', '개선 반복을 갱신했습니다'],
  'managed_login.cancelled': ['관리형 로그인 취소', '관리형 로그인을 취소했습니다'],
  'managed_login.completed': ['관리형 로그인 완료', '관리형 로그인을 마쳤습니다'],
  'managed_login.failed': ['관리형 로그인 실패', '관리형 로그인에 실패했습니다'],
  'managed_login.started': ['관리형 로그인 시작', '관리형 로그인을 시작했습니다'],
  'memory.read': ['기억 읽기', '기억을 읽었습니다'],
  'memory.written': ['기억 쓰기', '기억에 기록했습니다'],
  'model.mismatch': ['모델 불일치', '선택한 모델과 실제로 응답한 모델이 달랐습니다'],
  'model.selected': ['모델 선택', '모델을 선택했습니다'],
  'owner.created': ['소유자 만들기', '이 인스턴스의 소유자를 만들었습니다'],
  'promotion.applied': ['새 환경 버전 적용', '새 환경 버전을 적용했습니다'],
  'promotion.failed': ['환경 버전 적용 실패', '환경 버전 적용에 실패했습니다'],
  'provider.conformance_completed': ['제공자 적합성 검사', '제공자 적합성 검사를 마쳤습니다'],
  'provider.conformance_started': ['제공자 적합성 검사 시작', '제공자 적합성 검사를 시작했습니다'],
  'record.gap': ['기록 빈 구간', '기록에 빠진 구간이 있습니다'],
  'recovery.reconciled': ['중단된 작업 대조', '중단된 작업을 기록과 대조했습니다'],
  'retention.changed': ['보존 설정 변경', '보존 설정을 바꿨습니다'],
  'retention.deleted': ['보존 항목 정리', '소유자가 고른 보존 항목을 정리했습니다'],
  'retention.pruned': ['오래된 항목 정리', '오래된 항목을 정리했습니다'],
  'review.completed': ['설계 검토', '설계 검토를 마쳤습니다'],
  'review.invalid': ['설계 검토 무효', '설계 검토 결과가 유효하지 않습니다'],
  'rollback.applied': ['이전 환경 버전으로 되돌리기', '이전 환경 버전으로 되돌렸습니다'],
  'run.started': ['실행 시작', '실행을 시작했습니다'],
  'run.stopped': ['실행 멈춤', '실행이 멈췄습니다'],
  'security.denied': ['보안 거절', '보안 검사가 요청을 막았습니다'],
  'service_client.created': ['서비스 클라이언트 만들기', '서비스 클라이언트를 만들었습니다'],
  'service_client.denied': ['서비스 클라이언트 거절', '서비스 클라이언트의 요청을 거절했습니다'],
  'service_client.revoked': ['서비스 클라이언트 폐기', '서비스 클라이언트를 폐기했습니다'],
  'service_client.rotated': ['서비스 클라이언트 키 교체', '서비스 클라이언트 키를 바꿨습니다'],
  'session.created': ['로그인', '로그인 세션을 시작했습니다'],
  'session.revoked': ['세션 끝내기', '로그인 세션을 끝냈습니다'],
  'setup.component_progress': ['설치 진행', '설치 구성 요소를 준비했습니다'],
  'setup.failed': ['설치 실패', '설치에 실패했습니다'],
  'setup.started': ['설치 시작', '설치를 시작했습니다'],
  'source.stored': ['원본 보관', '원본 자료를 보관했습니다'],
  'speech.interrupted': ['음성 입력 중단', '음성 입력이 중단되었습니다'],
  'speech.raw_unavailable': ['원음 없음', '원래 음성을 쓸 수 없습니다'],
  'speech.segment': ['음성 받아쓰기', '음성 한 구간을 받아 적었습니다'],
  'speech.started': ['음성 입력 시작', '음성 입력을 시작했습니다'],
  'speech.stopped': ['음성 입력 멈춤', '음성 입력을 멈췄습니다'],
  'tool.requested': ['도구 호출 요청', '도구 호출을 요청했습니다'],
  'tool.terminal': ['도구 호출 끝', '도구 호출이 끝났습니다'],
  'understanding.completed': ['업무 이해', '업무 이해를 마쳤습니다'],
  'understanding.requested': ['업무 이해 요청', '업무 이해를 요청했습니다'],
  'update.failed': ['업데이트 실패', '업데이트에 실패했습니다'],
  'update.started': ['업데이트 시작', '업데이트를 시작했습니다'],
  'validation.completed': ['검증', '검증을 마쳤습니다'],
  'work.created': ['업무 만들기', '업무를 만들었습니다'],
  'work.revised': ['업무 설명 수정', '업무 설명을 고쳤습니다'],
});
export const UNKNOWN_EVENT = '기록된 사건';

// media types as the owner reads them; parameters (`; charset=…`) never change the label
export const MEDIA_LABELS = Object.freeze({
  'text/plain': '텍스트',
  'text/markdown': '마크다운 문서',
  'text/csv': '표(CSV)',
  'application/pdf': 'PDF',
  'application/json': 'JSON 데이터',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '워드 문서(DOCX)',
});
export const MEDIA_FAMILY_LABELS = Object.freeze({ image: '이미지' });
export const UNKNOWN_MEDIA = '파일';

const own = (table, key) => (typeof key === 'string' && Object.hasOwn(table, key) ? table[key] : null);

// a dictionary lookup that never invents: an unknown value is shown as itself
export function termLabel(table, value) {
  return own(table, value) ?? (value === null || value === undefined ? '' : String(value));
}

export const nodeKindLabel = value => termLabel(NODE_KIND_LABELS, value);
export const edgeKindLabel = value => termLabel(EDGE_KIND_LABELS, value);
export const failurePolicyLabel = value => termLabel(FAILURE_POLICY_LABELS, value);

export function mediaTypeLabel(mediaType) {
  if (typeof mediaType !== 'string') return UNKNOWN_MEDIA;
  const bare = mediaType.split(';', 1)[0].trim().toLowerCase();
  const exact = own(MEDIA_LABELS, bare);
  if (exact) return exact;
  return own(MEDIA_FAMILY_LABELS, bare.split('/', 1)[0]) ?? UNKNOWN_MEDIA;
}

export function eventStatusLabel(status) {
  return own(EVENT_STATUS_LABELS, status) ?? EVENT_STATUS_LABELS.unknown;
}

export const eventErrorLabel = code => termLabel(EVENT_ERROR_LABELS, code);

export function eventStatusTone(status) {
  return own(EVENT_STATUS_TONES, status) ?? 'warn';
}

// the facts a public event's allowlisted metadata may add to its sentence
function eventDetail(type, metadata) {
  if (typeof metadata !== 'object' || metadata === null) return '';
  const count = value => Number.isSafeInteger(value) && value >= 0;
  if ((type === 'work.created' || type === 'work.revised') && count(metadata.revision)) return ` (수정본 ${metadata.revision})`;
  if (type === 'run.started' && count(metadata.node_count)) return ` (노드 ${metadata.node_count}개)`;
  if (type === 'run.stopped' && typeof metadata.reason_code === 'string') {
    return ` (${own(STOP_REASON_LABELS, metadata.reason_code) ?? metadata.reason_code})`;
  }
  return '';
}

// one human sentence for a public event: `known` is false for a type this page does not
// know, whose raw name the caller keeps in the technical disclosure
export function eventSentence(event) {
  const type = typeof event?.event_type === 'string' ? event.event_type : '';
  const text = own(EVENT_TEXT, type);
  if (text === null) return Object.freeze({ text: UNKNOWN_EVENT, known: false });
  const [topic, sentence] = text;
  const base = event?.status === 'succeeded' ? sentence : topic;
  return Object.freeze({ text: base + eventDetail(type, event?.public_metadata), known: true });
}

// the first characters of an identifier; the full value belongs in the "기술 정보" disclosure
export function shortId(value, length = 8) {
  if (typeof value !== 'string') return '';
  return value.length > length ? value.slice(0, length) : value;
}

// a human size, spelled out (the same units the server's bounds are stated in)
export function formatBytes(bytes) {
  if (!Number.isSafeInteger(bytes) || bytes < 0) throw new TypeError('size must be a byte count');
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GiB`;
}

const STAMP = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?Z$/;

// a server UTC stamp (microsecond precision) as a Date, or null when it is not one
export function parseUtc(stamp) {
  if (stamp instanceof Date) return Number.isNaN(stamp.getTime()) ? null : stamp;
  if (typeof stamp !== 'string') return null;
  const match = STAMP.exec(stamp);
  if (!match) return null;
  const [, y, mo, d, h, mi, s, fraction = '0'] = match;
  const ms = Number(fraction.padEnd(3, '0').slice(0, 3));
  const time = Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s), ms);
  const date = new Date(time);
  return Number.isNaN(time) || date.getUTCDate() !== Number(d) ? null : date;
}

const pad = value => String(value).padStart(2, '0');

// the absolute local time to the second: YYYY-MM-DD HH:MM:SS
export function absoluteTime(value) {
  const date = parseUtc(value);
  if (date === null) return '';
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} `
    + `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

// how long ago, in the owner's words; a time ahead of this clock is "방금 전", never "앞으로"
export function relativeTime(value, now = Date.now()) {
  const date = parseUtc(value);
  const reference = now instanceof Date ? now.getTime() : now;
  if (date === null || !Number.isFinite(reference)) return '';
  const seconds = Math.max(0, Math.floor((reference - date.getTime()) / 1000));
  if (seconds < 45) return '방금 전';
  const minutes = Math.max(1, Math.floor(seconds / 60));
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}일 전`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}개월 전`;
  return `${Math.floor(days / 365)}년 전`;
}

// both forms at once, with the machine value for a <time datetime>
export function timeText(value, now = Date.now()) {
  const date = parseUtc(value);
  if (date === null) return Object.freeze({ relative: '', absolute: '', iso: '' });
  return Object.freeze({ relative: relativeTime(date, now), absolute: absoluteTime(date), iso: date.toISOString() });
}
