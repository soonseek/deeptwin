import { SCENES, MODES, ROLES, SOURCE, CONTEXT, DESIGNS, ROUNDS, RECORDS, EXPLORATIONS } from './data.mjs';
import { roleFor, currentDraft, evidenceKey } from './state.mjs';
import { e, button, detailButton, sceneButton, sample, paper, original, draftEditor,
  roleGraph, conversation, contextRibbon, selectedText, scopeLabel, recordPreview } from './views.mjs';

function inputScene(state) {
  return `<div class="columns">${paper('업무 설명과 자료', `
    <label for="request-draft">디자인 테스트용 업무 설명</label>
    <textarea id="request-draft" data-field="request" maxlength="20000" rows="7" placeholder="화면에서 확인하고 싶은 업무 설명을 적으세요.">\n${e(state.request)}</textarea>
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
      <textarea id="design-notes" data-field="designNotes" maxlength="20000" rows="3">\n${e(state.designNotes[state.design] ?? '')}</textarea>
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
      <label for="evidence-note">필요한 증거 또는 보류 이유 메모 · 선택</label><textarea id="evidence-note" data-field="evidence" rows="4" maxlength="20000">\n${e(state.evidence[evidenceKey(state)] ?? '')}</textarea>
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
