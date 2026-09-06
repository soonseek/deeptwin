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
    ${button('차이와 새 증거 보기', 'data-exploration', 'alternative')}`);
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
