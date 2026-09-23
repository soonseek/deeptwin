// T060 (US5): after the owner freezes their own version, what the framework observes
// and what it does not yet know. The observation is sealed on the server as a
// `difference` record (positions and operations only, never a reason). Competing
// explanations, questions and change candidates are shown with their actual state:
// when no explanation generator is connected, none is invented; when the premise for
// asking (a confirmed judgment hypothesis with diverging explanations) is absent, the
// owner is not asked anything — no philosophy quiz, no stand-in answer. The partial
// scope stays visible: what the owner changed is the evidence, the rest is unreviewed,
// and the impact is still to be investigated. All text goes through textContent.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;

export const FAMILY_LABELS = Object.freeze({
  system: '시스템 결손(정보 추출·검색·활용·전달 실패)',
  expert_judgment: '새로운 조건부 판단',
  exception: '일회성 예외',
  alternative_error: '대안 쪽의 오류',
  no_generalization: '일반화할 지식 없음',
});

export const MESSAGES = Object.freeze({
  idle: '내 버전을 고정하면 원본과의 차이를 관측할 수 있습니다.',
  observing: '차이를 관측하는 중…',
  noQuiz: '이 화면은 질문에 답하도록 요구하지 않습니다. 답하지 않아도 작업은 계속됩니다.',
  unreviewed: '바꾸지 않은 부분은 검토하지 않은 영역으로 남고, 영향 범위는 따로 조사합니다.',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '이 대안에서는 차이를 관측할 수 없습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  not_found: '고정된 내 버전을 찾지 못했습니다.',
  unavailable: '저장소에 연결하지 못했습니다.',
});

function fail(message) {
  throw Object.assign(new Error(message), { code: 'invalid_input' });
}

export function differenceRoute(basePath, runId, artifactId, alternativeId) {
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  for (const [value, label] of [[runId, 'run id'], [artifactId, 'artifact id'], [alternativeId, 'alternative id']]) {
    if (typeof value !== 'string' || !UUID.test(value)) fail(`${label} is not a canonical UUID`);
  }
  return `${basePath.slice(0, -1)}/api/v1/runs/${runId}/artifacts/${artifactId}/alternatives/${alternativeId}/difference`;
}

export function createInquiryPanel({ root, document, request, basePath = '/' } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', MESSAGES.idle, { role: 'status', 'aria-live': 'polite' });
  const body = element('div');
  root.replaceChildren(element('h2', '차이와 설명'), status, body);
  let target = null;

  function say(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function render(value) {
    const observations = element('ul', undefined, { 'aria-label': '관측된 차이' });
    for (const item of value.observations) observations.append(element('li', String(item.description)));
    const uncertainties = value.uncertainties.map(text => element('p', String(text)));
    const families = element('ul', undefined, { 'aria-label': '경쟁하는 설명' });
    for (const family of value.hypotheses.families) {
      families.append(element('li', `${FAMILY_LABELS[family] ?? family}: 검토되지 않음`));
    }
    const scope = value.evidence_scope.includes('whole') ? '내 버전 전체가 근거입니다.'
      : `내가 바꾼 ${value.evidence_scope.length}곳이 근거입니다.`;
    body.replaceChildren(
      element('h3', `관측된 차이 ${value.observations.length}개`), observations, ...uncertainties,
      element('p', `${scope} ${MESSAGES.unreviewed}`),
      element('h3', '경쟁하는 설명'), element('p', String(value.hypotheses.reason)), families,
      element('h3', '질문'), element('p', String(value.inquiry.reason)), element('p', MESSAGES.noQuiz),
      element('h3', '변경 후보'), element('p', String(value.change_candidates.reason)),
    );
    say('차이를 기록했습니다. 원인은 아직 해석하지 않았습니다.', 'observed');
  }

  async function show(runId, artifactId, alternativeId) {
    target = { route: differenceRoute(basePath, runId, artifactId, alternativeId) };
    body.replaceChildren();
    say(MESSAGES.observing, 'observing');
    try {
      let value;
      try {
        value = await request(target.route, {});
      } catch (error) {
        if (error?.code !== 'not_found') throw error;
        value = await request(target.route, { method: 'POST', body: {} });  // observe once, then read
      }
      render(value);
      return value;
    } catch (error) {
      const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
      say(ERROR_MESSAGES[code], code);
      throw error;
    }
  }

  return Object.freeze({ show });
}
