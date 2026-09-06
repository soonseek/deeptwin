import { ARTIFACTS, CASE, DESIGNS, LOGS, REVISED_DESIGN, ROUNDS, RUNS, WORK_MODEL } from './fixtures.mjs';
import { context, draftKey, noteKey } from './state.mjs';
import { artifact, button, e, graph, list } from './primitives.mjs';

const areas = { design: '설계 비교', run: '실행 관제', growth: '개선 실험' };
const modes = { workspace: '작업공간', conversation: '대화', graph: '그래프' };
const focuses = { transfer: '산출물 전달', approval: '책임·승인', memory: '기억 접근', evaluation: '평가·관측' };
const jobs = { j1: '화요일 공간 이용', j2: '목요일 공간 이용' };
const statuses = { complete: '완료', failed: '실패', waiting: '대기' };
const origin = Object.values(RUNS).find(run => run.attempts.some(attempt => attempt.outputs.includes(CASE.original)));
const chosenDesign = state => [...DESIGNS, REVISED_DESIGN].find(design => design.id === state.design);
const chosenRound = state => ROUNDS.find(round => round.id === state.round);
const attemptLabel = attempt => `수행 ${attempt.stage} · 시도 ${attempt.try} · ${statuses[attempt.status] ?? attempt.status}`;
const runLabel = run => `${jobs[run.job]} · ${run.id} · ${run.env}`;

function field(name, label, value) {
  return `<label class="text-field" for="${e(name)}-input">${e(label)}</label>`
    + `<textarea id="${e(name)}-input" data-field="${e(name)}" maxlength="20000" rows="6">${e(value)}</textarea>`;
}

function facts(entries) {
  return `<dl class="facts">${entries.map(([label, value]) => `<dt>${e(label)}</dt><dd>${e(value)}</dd>`).join('')}</dl>`;
}

function sourceContext(state) {
  const selected = context(state);
  const run = RUNS[selected.run];
  const attempt = run.attempts.find(item => item.id === selected.attempt);
  const file = ARTIFACTS[selected.artifact];
  const scope = selected.scope;
  const range = scope.kind === 'region' ? file?.regions.find(region => region.id === scope.id)?.label
    : scope.kind === 'text' ? `문자 ${scope.start}–${scope.end}` : '전체';
  return facts([
    ['실행', runLabel(run)], ['관찰 시점', run.observedAt],
    ['선택 노드', run.nodes.find(node => node.id === selected.node)?.label ?? selected.node],
    ['정확한 시도', attempt ? `${attempt.id} · ${attemptLabel(attempt)}` : '실제 수행 기록 없음'],
    ['산출물 버전', file ? `${file.id} · ${file.type}` : '출력 없음'], ['범위', range],
  ]);
}

function ribbon(state) {
  if (state.area === 'design') {
    const design = chosenDesign(state);
    return `<div class="ribbon">업무 모델 · ${e(design.label)} · ${e(design.version)} · 실행 전 설계 검토</div>`;
  }
  if (state.area === 'growth') {
    return state.sample
      ? `<div class="ribbon">고정 합성 사례 ${e(CASE.id)} · ${e(chosenRound(state).id)} · 현재 입력과 별개</div>`
      : `<div class="ribbon">현재 입력 미분석 · ${e(context(state).run)} · ${e(context(state).attempt ?? '수행 없음')} · ${e(context(state).artifact ?? '출력 없음')}</div>`;
  }
  return `<div class="ribbon">${e(runLabel(RUNS[state.run]))} · ${e(RUNS[state.run].observedAt)} · ${e(context(state).attempt ?? '수행 없음')} · ${e(context(state).artifact ?? '출력 없음')}</div>`;
}

function designDetails(design, focus, instance) {
  const functions = design.focus[focus].map(id => design.nodes.find(node => node.id === id).label);
  return `<h3>${e(design.label)}</h3><p class="version">${e(design.version)}</p>`
    + graph(design, design.focus[focus], 'designNode', `${design.id}:${instance}:`)
    + `<h4>${e(focuses[focus])}</h4><p>${e(design.contracts[focus])}</p>`
    + `<div class="focused-functions"><p>이 관점에서 확인할 기능</p>${list(functions)}</div>`
    + `<p class="qualification">${e(design.review)}</p>`;
}

function designWorkspace(state) {
  const selected = chosenDesign(state);
  return '<section class="work-model"><h2>업무 모델</h2>'
    + facts([['목적', WORK_MODEL.purpose], ['완료 조건', WORK_MODEL.done], ['입력 자료', WORK_MODEL.source], ['아직 모르는 것', WORK_MODEL.unknown]])
    + field('workText', '내 업무의 목적·입력·완료 조건', state.workText)
    + '<p>작성 내용은 이 탭에만 남습니다. 업무 모델 자동 분석은 연결되지 않았습니다.</p></section>'
    + `<nav class="focus-bar" aria-label="설계 비교 관점">${Object.entries(focuses).map(([value, label]) => button(label, 'focus', value, state.focus === value)).join('')}</nav>`
    + `<div class="candidates">${DESIGNS.map(design => `<section class="candidate" data-design="${e(design.id)}">`
      + designDetails(design, state.focus, 'candidate') + button('이 설계 살펴보기', 'design', design.id, state.design === design.id) + '</section>').join('')}</div>`
    + `<section class="selected-design" data-selected-design="${e(selected.id)}"><h2>선택한 설계의 전체 구조</h2>`
    + designDetails(selected, state.focus, 'selected')
    + field('designText', '설계에 반영하고 싶은 요청', state.designText)
    + '<p>작성 요청은 아직 처리되지 않았습니다. 아래 병합은 사전 구성된 예시이며 사용자 요청을 처리한 결과가 아닙니다. 별도 버전의 결합 검토와 승인 상태를 확인합니다.</p>'
    + button('사전 구성된 병합 예시 보기', 'design', REVISED_DESIGN.id, state.design === REVISED_DESIGN.id)
    + button('승인 대상 확인', 'overlay', 'approval') + button('설계 검토 기록', 'overlay', 'audit') + '</section>';
}

function artifactChoices(ids) {
  return ids.map(id => button(`${ARTIFACTS[id].label} · ${id}`, 'artifact', id)).join('');
}

function fullFiles(ids) {
  return ids.map(id => `<details class="file-detail" open><summary>${e(ARTIFACTS[id].label)} · ${e(id)}</summary>${artifact(id)}</details>`).join('');
}

function inspection(run, node, attempt, { historyAction, consumerAction, prefix = '', full = false }) {
  if (!node) return '<p>노드 미확인</p>';
  const history = run.attempts.filter(item => item.node === node.id);
  const heading = `<h3>${e(node.label)}</h3><p class="version">${e(runLabel(run))} · ${e(node.id)}</p>`;
  const controls = `<nav class="attempt-history" aria-label="${e(node.label)} 수행·시도 이력">${history.map(item => button(attemptLabel(item), historyAction, `${prefix}${item.id}`, item.id === attempt?.id)).join('')}</nav>`;
  if (!attempt) return `<div class="attempt-inspector">${heading}${controls}<p>실제 수행 기록 없음</p>`
    + '<h4>입력</h4><p>이 노드에 연결된 실제 입력 기록 없음</p><h4>출력</h4>' + artifact(null)
    + '<h4>사건·후속 수신자</h4><p>기록 없음 · 계획된 연결에서 실제 사용을 추정하지 않음</p></div>';
  const inputs = full ? fullFiles(attempt.inputs) : artifactChoices(attempt.inputs);
  const outputs = attempt.outputs.length ? (full ? fullFiles(attempt.outputs) : artifactChoices(attempt.outputs)) : artifact(null);
  const consumers = attempt.consumers.length
    ? `<ul class="consumers">${attempt.consumers.map(consumer => `<li><span>${e(consumer.artifact)} → </span>`
      + button(consumer.attempt, consumerAction, `${prefix}${consumer.attempt}`) + '</li>').join('')}</ul>`
    : '<p>기록된 실제 수신자 없음</p>';
  return `<div class="attempt-inspector" data-inspected-attempt="${e(attempt.id)}">${heading}${controls}`
    + `<p class="attempt-status">${e(attempt.id)} · ${e(attemptLabel(attempt))}</p>`
    + `<h4>정확한 입력 버전</h4>${inputs || '<p>입력 없음</p>'}<h4>이 시도의 모든 출력</h4>${outputs}`
    + `<h4>실제 후속 수신자</h4>${consumers}<details class="events" open><summary>이 시도의 사건 기록</summary>${list(attempt.events)}</details></div>`;
}

function runEditor(state) {
  const selected = context(state);
  if (!selected.artifact) return '';
  const key = draftKey(state);
  const hasDraft = (state.drafts[key] ?? '').length > 0;
  return '<section class="alternative-editor"><h2>같은 상태에서 나의 버전</h2>'
    + artifact(selected.artifact, { selectable: true, scope: selected.scope })
    + button('원본 넓게 보기', 'overlay', 'artifact')
    + field('draft', '전체 또는 선택한 부분의 자기 버전 · 이유 불필요', state.drafts[key] ?? '')
    + `<p id="draft-status" role="status">${hasDraft ? '이 정확한 맥락에 자기 버전이 있습니다.' : '이 정확한 맥락에는 아직 자기 버전이 없습니다.'}</p>`
    + '<label for="alternative-file">자기 버전 파일 · 이 탭의 메모리에만 유지</label>'
    + '<input id="alternative-file" type="file" accept=".pdf,.png,.jpg,.jpeg,.svg,.csv,.md,.txt"/>'
    + '<p id="file-status" role="status">파일 첨부 없음 · 새로고침하면 첨부 파일은 사라집니다.</p>'
    + '<p>부분 선택이나 작성은 학습·승인·운영 적용이 아닙니다. 이유를 쓰지 않아도 됩니다.</p>'
    + button('이 입력의 개선 영역 열기', 'currentGrowth') + '</section>';
}

function runWorkspace(state) {
  const run = RUNS[state.run];
  const selected = context(state);
  const node = run.nodes.find(item => item.id === selected.node);
  const attempt = run.attempts.find(item => item.id === selected.attempt) ?? null;
  return `<details class="run-picker"><summary>실행 선택 · ${e(runLabel(run))}</summary><nav aria-label="합성 실행 선택">`
    + Object.values(RUNS).map(item => button(runLabel(item), 'run', item.id, state.run === item.id)).join('') + '</nav></details>'
    + `<section class="run-workbench" data-run="${e(run.id)}"><h2>${e(jobs[run.job])}</h2>${sourceContext(state)}`
    + `<details class="run-graph"${state.mode === 'graph' ? ' open' : ''}><summary>실행 환경의 전체 관계도</summary>${graph(run, [selected.node])}</details>`
    + '<p class="trace-boundary">계획된 연결과 실제 산출물 전달은 다릅니다. 실제 전달 기록도 적절한 사용이나 인과관계의 증명이 아닙니다.</p>'
    + `<div class="run-columns">${inspection(run, node, attempt, { historyAction: 'attempt', consumerAction: 'consumer' })}${runEditor(state)}</div></section>`;
}

function freshGrowth(state) {
  return '<section class="fresh-growth"><h2>현재 입력의 개선 영역</h2>'
    + '<p class="qualification">분석 결과 없음 · 실제 탐구·실험 엔진 미연결</p>' + sourceContext(state)
    + `<h3>현재 맥락의 자기 버전</h3><blockquote>${e(state.drafts[draftKey(state)] || '현재 맥락에 작성된 자기 버전 없음')}</blockquote>`
    + '<p>작성한 입력과 선택 범위를 보존하고 있습니다. 이 입력에 대한 진단·가설·후보·점수는 생성되지 않았습니다.</p>'
    + button('현재 원본으로 돌아가기', 'area', 'run')
    + button('별도의 고정 합성 사례 탐색', 'sample', 'true') + '</section>';
}

function hypotheses(difference) {
  const labels = { support: '지지하는 관찰', counter: '반대 설명', unknown: '아직 모르는 것', probe: '다음에 확인할 탐구', newEvidence: '새 근거' };
  return `<div class="hypotheses">${difference.hypotheses.map(hypothesis => `<section data-hypothesis="${e(hypothesis.id)}">`
    + `<h3>${hypothesis.kind === 'system' ? '시스템 전달에 관한 설명' : '자기 버전의 판단에 관한 설명'}</h3><p>${e(hypothesis.claim)}</p>`
    + facts(Object.entries(labels).map(([key, label]) => [label, hypothesis[key]])) + '</section>').join('')}</div>`;
}

function pairedRun(state, round, side) {
  const run = RUNS[round[`${side}Run`]];
  const choice = state.pairs[`${round.id}:${side}`];
  const nodeId = choice?.startsWith('@') ? choice.slice(1) : null;
  const attempt = nodeId ? run.attempts.filter(item => item.node === nodeId).at(-1) ?? null
    : choice ? run.attempts.find(item => item.id === choice) ?? null
      : run.attempts.filter(item => item.outputs.length > 0).at(-1) ?? null;
  const node = run.nodes.find(item => item.id === (nodeId ?? attempt?.node));
  return `<section class="pair" data-pair="${side}" data-run="${e(run.id)}"><h3>${side === 'baseline' ? '기준 실행' : '후보 실행'}</h3>`
    + `<p class="version">${e(runLabel(run))} · ${e(run.observedAt)}</p>`
    + graph(run, node ? [node.id] : [], 'pairNode', `${side}:`)
    + inspection(run, node, attempt, { historyAction: 'pairAttempt', consumerAction: 'pairAttempt', prefix: `${side}:`, full: true }) + '</section>';
}

function fixedGrowth(state) {
  const difference = CASE.differences.find(item => item.id === state.difference);
  const round = chosenRound(state);
  const region = ARTIFACTS[CASE.original].regions.find(item => item.id === CASE.region);
  return '<section class="fixed-example"><h2>사전 구성된 합성 개선 사례</h2>'
    + '<p class="synthetic-banner">현재 입력과 별개 · 실제 진단·평가 결과가 아님 · 표시 내용은 작성된 합성 예시입니다.</p>'
    + button('현재 입력의 개선 영역으로 돌아가기', 'sample', 'false')
    + `<p>검토한 부분: ${e(region.label)} · ${e(CASE.region)}. 자기 버전이 제공되지 않은 나머지 부분은 승인되거나 수정된 것으로 보지 않습니다.</p>`
    + `<div class="artifact-pair"><section><h3>고정 예시의 원본</h3>${artifact(CASE.original)}</section>`
    + `<section><h3>고정 예시의 부분 자기 버전</h3>${artifact(CASE.alternative)}</section></div>`
    + `<nav aria-label="관찰된 차이">${CASE.differences.map(item => button(item.label, 'difference', item.id, state.difference === item.id)).join('')}</nav>`
    + `<h3>${e(difference.label)}</h3>${facts([['관찰된 원본', difference.original], ['관찰된 자기 버전', difference.alternative]])}`
    + `<h3>이 차이와 관련된 원 실행</h3><p>${e(origin.id)} · 노드를 열면 이 고정 예시의 정확한 수행 이력을 볼 수 있습니다. 현재 작성 중인 원본 선택은 바뀌지 않습니다.</p>`
    + graph(origin, difference.nodes, 'sampleNode') + hypotheses(difference) + button('합성 탐구 감사 기록', 'overlay', 'audit')
    + `<h2>비교 회차</h2><nav class="round-queue" aria-label="기준·후보 비교 회차">${ROUNDS.map(item => `<div data-round="${e(item.id)}">`
      + button(`${jobs[item.job]} · ${item.id} · ${item.result}`, 'round', item.id, state.round === item.id) + '</div>').join('')}</nav>`
    + `<h3>${e(round.candidate)}</h3><p>${e(round.result)}</p><p>${e(round.limits)}</p>`
    + `<div class="paired-runs">${pairedRun(state, round, 'baseline')}${pairedRun(state, round, 'candidate')}</div>`
    + '<h3>부분 밖 영향과 완결 산출물 확인</h3><table class="round-checks"><thead><tr><th>확인 범위</th><th>표시된 결과</th><th>근거 파일</th></tr></thead><tbody>'
    + round.checks.map(check => `<tr><td>${e(check.label)}</td><td>${e(check.result)}</td><td>${button(ARTIFACTS[check.evidence].label, 'evidence', check.evidence)}</td></tr>`).join('')
    + `</tbody></table><h3>별도 최종 근거</h3><p>${e(round.finalEvidence)}</p><p>조정에 사용한 사례는 봉인된 새 최종 근거로 셀 수 없습니다.</p>`
    + `<h3>정확한 버전의 승인 상태</h3><p>${e(round.approval)}</p><p>승인과 운영 적용은 별개입니다. 이 화면에서는 어느 쪽도 수행하지 않습니다.</p>`
    + button('승인 대상 확인', 'overlay', 'approval') + '</section>';
}

export function render(state) {
  const content = state.area === 'design' ? designWorkspace(state)
    : state.area === 'run' ? runWorkspace(state) : state.sample ? fixedGrowth(state) : freshGrowth(state);
  const conversation = state.mode === 'conversation'
    ? '<section class="conversation"><h2>현재 맥락에 남기는 대화</h2><p>자동 응답은 연결되지 않았습니다. 지금 보고 있는 대상에 메모를 남길 수 있습니다.</p>'
      + field('note', '이 맥락의 메모', state.notes[noteKey(state)] ?? '') + '</section>' : '';
  return `<div class="shell" data-area="${e(state.area)}" data-mode="${e(state.mode)}"><aside class="rail"><h1>DeepTwin</h1><p>멀티에이전트 관제</p>`
    + `<nav aria-label="작업 영역">${Object.entries(areas).map(([value, label]) => button(label, 'area', value, state.area === value)).join('')}</nav>`
    + `<div class="utilities">${button('연결·복구', 'overlay', 'connection')}${button('기록 추출', 'overlay', 'logs')}</div></aside>`
    + '<main><p class="synthetic-banner">화면 시제품 · 합성 실행 기록 · AI/외부 도구/학습 미연결</p>' + ribbon(state)
    + `<h1 id="page-title" tabindex="-1">${e(areas[state.area])}</h1><nav class="mode-bar" aria-label="화면 모드">`
    + Object.entries(modes).map(([value, label]) => button(label, 'mode', value, state.mode === value)).join('')
    + `</nav>${conversation}${content}<footer class="storage-footer"><p id="storage-status" role="status">아직 보관 상태를 확인하지 않음</p>`
    + '<p>작성 내용은 이 탭에만 보관합니다. 첨부 파일은 메모리에만 있으며 새로고침하면 사라집니다.</p>'
    + button('탭 보관 다시 시도', 'save') + button('시험용 작성 내용 초기화', 'reset') + '</footer></main></div>';
}

function approvalPreview(state) {
  let target;
  if (state.area === 'design') {
    const design = chosenDesign(state);
    target = facts([['정확한 설계 버전', design.version], ['검토 상태', design.review]]);
  } else if (state.area === 'growth' && state.sample) {
    const round = chosenRound(state);
    target = facts([['정확한 후보 버전', round.candidate], ['승인 상태', round.approval]]);
  } else {
    target = '<p>현재 입력에 대한 실제 외부 승인 요청은 없습니다.</p>' + sourceContext(state);
  }
  return '<h2>승인 대상 미리보기 · 실제 승인 미연결</h2>' + target
    + '<p>대화상자를 여는 것은 권한 변경이나 승인이 아닙니다. 사람의 승인과 실제 운영 적용을 각각 연결해야 합니다.</p>'
    + '<button type="button" disabled aria-disabled="true">실제 적용 · 연결되지 않음</button>';
}

function connectionPreview() {
  return '<h2>연결·복구</h2><h3>계정 연결 요구사항</h3>'
    + '<p>제품 요구사항: Claude와 Codex는 각각 사용자가 보유한 구독을 연결하는 경로가 필수입니다. 두 제품의 공식 통합 가능 여부는 미검증이며, 현재 어느 계정도 연결되지 않았습니다.</p>'
    + '<p>API 사용은 선택 사항입니다. 사용자의 명시적인 선택 없이 자동으로 전환하거나 과금하지 않습니다.</p>'
    + '<h3>도구와 실행 환경</h3><p>브라우저·파일 도구는 프레임워크가 소유하는 연결로 구분합니다. 이 화면에는 해당 도구나 실행 엔진이 연결되지 않았습니다.</p>'
    + '<h3>중단 뒤 복구</h3><p>부분 완료나 결과 불명 상태는 그대로 남깁니다. 결과를 확인하기 전 외부 작업을 자동으로 반복하지 않습니다.</p>';
}

function logsPreview(state) {
  return '<h2>기록 추출 범위</h2><p>아래 기록은 모두 합성 예시입니다. 선택은 추출 범위의 미리보기이며 전송이 아닙니다.</p>'
    + `<label><input id="redact" type="checkbox"${state.redact ? ' checked' : ''}/>출처 표지만 가림 · 본문 자동 가림 아님</label>`
    + `<ul class="log-records">${LOGS.map(record => `<li><label><input type="checkbox" data-record="${e(record.id)}"${state.records.includes(record.id) ? ' checked' : ''}/>${e(record.label)}</label>`
      + (state.redact ? '' : `<small class="source-marker">${e(record.source)}</small>`) + '</li>').join('')}</ul>`
    + `<p>선택한 기록 ${state.records.length}개</p><p>기록 추출과 외부 전송은 각각 별도의 선택 사항입니다. 실제 추출·전송은 연결되지 않았습니다.</p>`
    + '<button type="button" disabled aria-disabled="true">실제 추출·전송 · 연결되지 않음</button>';
}

function auditPreview() {
  const headings = { generation: '설계 생성·병합 기록', critic: '별도 검토 기록', diagnosis: '차이 해석·탐구 기록' };
  return '<h2>합성 감사 기록</h2><p>내부 명칭을 포함한 작성 예시입니다. 철학적 원전 검증이나 판단 오류의 독립성 증명이 아닙니다. 사후 해석은 원 실행의 입력에 포함되지 않습니다.</p>'
    + Object.entries(headings).map(([key, heading]) => `<section><h3>${e(heading)}</h3>${list(CASE.audit[key])}</section>`).join('');
}

export function overlay(state, id) {
  const content = id === 'artifact' ? '<h2>현재 원본 산출물</h2>' + artifact(context(state).artifact)
    : id === 'approval' ? approvalPreview(state)
      : id === 'connection' ? connectionPreview()
        : id === 'logs' ? logsPreview(state)
          : id === 'audit' ? auditPreview() : '<h2>보기 미확인</h2>';
  return `<div class="overlay-content">${content}${button('닫기', 'close')}</div>`;
}

export function sampleInspection(nodeId, attemptId) {
  const node = origin.nodes.find(item => item.id === nodeId);
  if (!node) return '<h2>고정 합성 사례 · 노드 미확인</h2>';
  const history = origin.attempts.filter(item => item.node === nodeId);
  const attempt = attemptId === undefined ? history.at(-1) ?? null : history.find(item => item.id === attemptId);
  if (attemptId !== undefined && !attempt) return '<h2>고정 합성 사례 · 시도 미확인</h2><p>선택 노드에 속한 실제 시도만 열 수 있습니다.</p>';
  return '<h2>고정 합성 사례의 실행 이력</h2><p>현재 입력과 별개의 사전 구성 기록입니다. 열람은 실제 분석이나 원본 선택 변경이 아닙니다.</p>'
    + inspection(origin, node, attempt, { historyAction: 'sampleAttempt', consumerAction: 'sampleConsumer', full: true });
}
