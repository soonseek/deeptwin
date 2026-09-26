// The shared display rules (ui-format.mjs): every dictionary entry, the unknown fallbacks,
// sizes, short ids and time with a fixed clock and a fixed local time zone. The event-type
// list is pinned to the server's registry by app/tests/test_ui_format_mirror.py.

import test from 'node:test';
import assert from 'node:assert/strict';

process.env.TZ = 'Asia/Seoul';

const {
  EDGE_KIND_LABELS, EVENT_ERROR_LABELS, EVENT_STATUS_LABELS, EVENT_STATUS_TONES, EVENT_TEXT, FAILURE_POLICY_LABELS,
  MEDIA_LABELS, NODE_KIND_LABELS, RUN_CONTROL_LABELS, UNKNOWN_EVENT, UNKNOWN_MEDIA, absoluteTime, edgeKindLabel,
  eventErrorLabel, eventSentence, eventStatusLabel, eventStatusTone, failurePolicyLabel, formatBytes, mediaTypeLabel,
  nodeKindLabel, parseUtc, relativeTime, shortId, termLabel, timeText,
} = await import('../static/ui-format.mjs');

test('graph terms read in the owner\'s words, and an unknown term is shown as itself', () => {
  assert.deepEqual({ ...NODE_KIND_LABELS }, {
    agent: '에이전트', deterministic: '정해진 처리', router: '분기', join: '합류', human_gate: '사람 승인',
    bounded_loop: '제한 반복',
  });
  assert.deepEqual({ ...EDGE_KIND_LABELS }, { artifact: '산출물', control: '제어', approval: '승인', observation: '관찰' });
  assert.deepEqual({ ...FAILURE_POLICY_LABELS }, {
    fail_run: '실패하면 실행 전체 멈춤',
    block_dependants: '실패하면 뒤 단계 멈춤',
    continue_optional: '실패해도 나머지는 계속(선택 단계)',
  });
  for (const [table, lookup] of [[NODE_KIND_LABELS, nodeKindLabel], [EDGE_KIND_LABELS, edgeKindLabel],
    [FAILURE_POLICY_LABELS, failurePolicyLabel]]) {
    for (const [key, label] of Object.entries(table)) assert.equal(lookup(key), label, key);
  }
  assert.equal(nodeKindLabel('future_kind'), 'future_kind');
  assert.equal(failurePolicyLabel(undefined), '');
  // a prototype member is not a term
  assert.equal(termLabel(NODE_KIND_LABELS, 'toString'), 'toString');
  assert.equal(termLabel(NODE_KIND_LABELS, 'constructor'), 'constructor');
});

test('the run controls say what they do: cancel stops sending new work', () => {
  assert.deepEqual({ ...RUN_CONTROL_LABELS }, { resume: '이어서 진행', cancel: '새 작업 보내기 중단', recover: '복구 시도' });
  assert.ok(!Object.values(RUN_CONTROL_LABELS).some(label => /dispatch/i.test(label)));
});

test('media types become Korean labels; parameters and case never change them; others are a file', () => {
  assert.deepEqual({ ...MEDIA_LABELS }, {
    'text/plain': '텍스트', 'text/markdown': '마크다운 문서', 'text/csv': '표(CSV)', 'application/pdf': 'PDF',
    'application/json': 'JSON 데이터',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '워드 문서(DOCX)',
  });
  for (const [type, label] of Object.entries(MEDIA_LABELS)) assert.equal(mediaTypeLabel(type), label, type);
  assert.equal(mediaTypeLabel('text/plain; charset=utf-8'), '텍스트');
  assert.equal(mediaTypeLabel('Text/CSV'), '표(CSV)');
  for (const image of ['image/png', 'image/jpeg', 'image/svg+xml']) assert.equal(mediaTypeLabel(image), '이미지');
  for (const other of ['application/zip', 'application/octet-stream', 'video/mp4', '', 'nonsense', null, 42]) {
    assert.equal(mediaTypeLabel(other), UNKNOWN_MEDIA, String(other));
  }
});

test('every public event type has a topic and a past-tense sentence; the status decides which is shown', () => {
  const types = Object.keys(EVENT_TEXT);
  assert.equal(types.length, 118);  // UI phase 4 added feedback.recorded
  for (const type of types) {
    const entry = EVENT_TEXT[type];
    assert.ok(Array.isArray(entry) && entry.length === 2, type);
    const [topic, sentence] = entry;
    assert.ok(typeof topic === 'string' && topic.length > 0 && !/[a-z_]{3,}/i.test(topic), `${type} topic`);
    assert.ok(typeof sentence === 'string' && /다$/.test(sentence) && !/[a-z_]{3,}/i.test(sentence), `${type} sentence`);
    assert.deepEqual(eventSentence({ event_type: type, status: 'succeeded' }), { text: sentence, known: true });
    for (const status of ['failed', 'pending', 'cancelled', 'unknown', 'started', 'progress', 'blocked', undefined]) {
      assert.deepEqual(eventSentence({ event_type: type, status }), { text: topic, known: true }, `${type} ${status}`);
    }
  }
  assert.deepEqual(eventSentence({ event_type: 'work.revised', status: 'succeeded', public_metadata: { revision: 4 } }),
    { text: '업무 설명을 고쳤습니다 (수정본 4)', known: true });
  assert.deepEqual(eventSentence({ event_type: 'work.created', status: 'failed', public_metadata: { revision: 1 } }),
    { text: '업무 만들기 (수정본 1)', known: true });
  assert.deepEqual(eventSentence({ event_type: 'run.started', status: 'succeeded', public_metadata: { node_count: 20 } }),
    { text: '실행을 시작했습니다 (노드 20개)', known: true });
  // metadata the page does not know how to read adds nothing
  assert.equal(eventSentence({ event_type: 'work.revised', status: 'succeeded', public_metadata: { revision: -1 } }).text,
    '업무 설명을 고쳤습니다');
  assert.equal(eventSentence({ event_type: 'backup.created', status: 'succeeded', public_metadata: { byte_count: 9 } }).text,
    '백업을 만들었습니다');
});

test('an unknown event type is a plain "기록된 사건" and never borrows another sentence', () => {
  assert.equal(UNKNOWN_EVENT, '기록된 사건');
  for (const type of ['future.kind', 'toString', '__proto__', '', undefined]) {
    assert.deepEqual(eventSentence({ event_type: type, status: 'succeeded' }), { text: UNKNOWN_EVENT, known: false }, String(type));
  }
  assert.deepEqual(eventSentence(null), { text: UNKNOWN_EVENT, known: false });
});

test('event statuses and error codes are spelled out; an unknown one reads as unknown', () => {
  assert.deepEqual({ ...EVENT_STATUS_LABELS }, {
    succeeded: '성공', failed: '실패', cancelled: '취소', pending: '대기', unknown: '결과 미상',
    started: '시작됨', progress: '진행 중', blocked: '막힘',
  });
  assert.deepEqual(Object.keys(EVENT_STATUS_TONES).sort(), Object.keys(EVENT_STATUS_LABELS).sort());
  for (const [status, label] of Object.entries(EVENT_STATUS_LABELS)) assert.equal(eventStatusLabel(status), label);
  assert.equal(eventStatusTone('succeeded'), 'ok');
  assert.equal(eventStatusTone('failed'), 'error');
  assert.equal(eventStatusLabel('mystery'), '결과 미상');
  assert.equal(eventStatusTone('mystery'), 'warn');
  assert.deepEqual({ ...EVENT_ERROR_LABELS }, {
    invalid_input: '입력 형식 오류', unauthenticated: '세션 없음', access_denied: '접근 거부',
    stale_state: '그사이 바뀐 상태', not_found: '대상을 찾지 못함', capacity_exhausted: '처리 한도 초과',
    dependency_unavailable: '연결된 구성 요소 응답 없음', storage_failed: '저장 실패', corrupt: '손상된 기록',
    missing: '기록 없음', outcome_unknown: '결과 미상', budget_exhausted: '한도 소진', cancelled: '취소됨',
  });
  for (const [code, label] of Object.entries(EVENT_ERROR_LABELS)) assert.equal(eventErrorLabel(code), label);
  assert.equal(eventErrorLabel('new_code'), 'new_code');
});

test('short ids keep the first eight characters; sizes are spelled out', () => {
  assert.equal(shortId('4ca10636-ee80-5d92-a560-59aaecd0ea64'), '4ca10636');
  assert.equal(shortId('abc'), 'abc');
  assert.equal(shortId('abcdef0123', 4), 'abcd');
  assert.equal(shortId(null), '');
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(1023), '1023 B');
  assert.equal(formatBytes(2048), '2.0 KiB');
  assert.equal(formatBytes(5 * 1024 * 1024), '5.0 MiB');
  assert.equal(formatBytes(3 * 1024 ** 3), '3.0 GiB');
  for (const bad of [-1, 1.5, '12', null, Number.MAX_SAFE_INTEGER + 1]) assert.throws(() => formatBytes(bad));
});

test('time: the server stamp parsed to the millisecond, shown local to the second and relative to a fixed clock', () => {
  const stamp = '2026-09-25T15:04:05.123456Z';
  assert.equal(parseUtc(stamp).toISOString(), '2026-09-25T15:04:05.123Z');
  assert.equal(parseUtc('2026-09-25T15:04:05Z').toISOString(), '2026-09-25T15:04:05.000Z');
  for (const bad of ['2026-02-30T00:00:00Z', '2026-09-25 15:04:05', '2026-09-25T15:04:05+09:00', '', null, 7]) {
    assert.equal(parseUtc(bad), null, String(bad));
  }
  // Asia/Seoul is UTC+9: the absolute time is the owner's local wall clock
  assert.equal(absoluteTime(stamp), '2026-09-26 00:04:05');
  assert.equal(absoluteTime('not a time'), '');
  const at = offset => Date.parse('2026-09-25T15:04:05.123Z') + offset * 1000;
  const cases = [[0, '방금 전'], [44, '방금 전'], [50, '1분 전'], [3 * 60 + 5, '3분 전'], [59 * 60, '59분 전'],
    [2 * 3600, '2시간 전'], [23 * 3600 + 59 * 60, '23시간 전'], [3 * 86400, '3일 전'], [29 * 86400, '29일 전'],
    [65 * 86400, '2개월 전'], [800 * 86400, '2년 전'], [-120, '방금 전']];
  for (const [offset, text] of cases) assert.equal(relativeTime(stamp, at(offset)), text, String(offset));
  assert.equal(relativeTime(stamp, new Date(at(180))), '3분 전');
  assert.equal(relativeTime('bad', at(0)), '');
  assert.deepEqual({ ...timeText(stamp, at(180)) },
    { relative: '3분 전', absolute: '2026-09-26 00:04:05', iso: '2026-09-25T15:04:05.123Z' });
  assert.deepEqual({ ...timeText('bad', at(0)) }, { relative: '', absolute: '', iso: '' });
});

// UI phase 4: a stop reads as what it means for the run, and the feedback event names its target
test('a run.stopped chip is the run outcome; a feedback event says what was marked, never the memo', async () => {
  const { RUN_STOP_OUTCOME_TEXT, runStopOutcome, FEEDBACK_MARK_LABELS } = await import('../static/ui-format.mjs');
  const stop = reason => ({ event_type: 'run.stopped', status: 'succeeded', public_metadata: { reason_code: reason } });
  assert.deepEqual({ ...runStopOutcome(stop('infrastructure_failure')) }, { label: '실패로 멈춤', tone: 'error' });
  assert.deepEqual({ ...runStopOutcome(stop('completed')) }, { label: '완료', tone: 'ok' });
  assert.deepEqual({ ...runStopOutcome(stop('cancelled')) }, { label: '취소·거절로 멈춤', tone: 'neutral' });
  // a failure is never "완료" or "성공", and every closed reason has words
  for (const [reason, [label, tone]] of Object.entries(RUN_STOP_OUTCOME_TEXT)) {
    assert.deepEqual({ ...runStopOutcome(stop(reason)) }, { label, tone });
    if (reason !== 'completed') assert.ok(label !== '완료' && label !== '성공', reason);
  }
  assert.deepEqual({ ...runStopOutcome(stop('new_reason')) }, { label: '멈춤 (new_reason)', tone: 'warn' });
  assert.deepEqual({ ...runStopOutcome({ event_type: 'run.stopped', status: 'succeeded', public_metadata: {} }) },
    { label: '멈춤 (이유 기록 없음)', tone: 'warn' });
  // a stop whose own record failed keeps the record's status; other events are not stops
  assert.equal(runStopOutcome({ ...stop('completed'), status: 'failed' }), null);
  assert.equal(runStopOutcome({ event_type: 'run.started', status: 'succeeded' }), null);
  assert.deepEqual({ ...FEEDBACK_MARK_LABELS }, { ok: '괜찮음', needs_attention: '확인 필요' });
  const feedback = metadata => eventSentence({ event_type: 'feedback.recorded', status: 'succeeded', public_metadata: metadata }).text;
  assert.equal(feedback({ scope: 'run', mark: 'needs_attention', memo: false, cleared: false, revision: 1 }),
    '과정 피드백을 남겼습니다 (실행 전체 · 확인 필요)');
  assert.equal(feedback({ scope: 'step', mark: 'ok', memo: true, cleared: false, revision: 2 }),
    '과정 피드백을 남겼습니다 (단계 · 괜찮음 · 메모)');
  assert.equal(feedback({ scope: 'step', mark: 'none', memo: true, cleared: false, revision: 1 }),
    '과정 피드백을 남겼습니다 (단계 · 메모)');
  assert.equal(feedback({ scope: 'step', mark: 'none', memo: false, cleared: true, revision: 3 }),
    '과정 피드백을 남겼습니다 (단계 · 지움)');
});

test('UI phase 5: every event type falls in exactly one "종류" group, each within the server filter bound', async () => {
  const { EVENT_GROUPS, eventGroupOf } = await import('../static/ui-format.mjs');
  const seen = new Map();
  for (const group of EVENT_GROUPS) {
    assert.ok(group.types.length >= 1 && group.types.length <= 64, group.id);
    assert.equal(typeof group.label, 'string');
    for (const type of group.types) seen.set(type, (seen.get(type) ?? 0) + 1);
  }
  assert.deepEqual([...seen.keys()].sort(), Object.keys(EVENT_TEXT).sort());
  assert.ok([...seen.values()].every(count => count === 1));
  assert.equal(eventGroupOf('run.started').id, 'run');
  assert.equal(eventGroupOf('feedback.recorded').id, 'approval');
  assert.equal(eventGroupOf('future.kind'), null);
});
