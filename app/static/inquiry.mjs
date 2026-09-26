// T060 (US5): after the owner freezes their own version, what the framework observes
// and what it does not yet know. The observation is sealed on the server as a
// `difference` record (positions and operations only, never a reason). Competing
// explanations are made only when the owner asks, through the owner's own Claude
// connection, and stay `proposed`. The owner may then open an inquiry — explicitly —
// whose questions come from the explanations' predictions and the missing evidence
// (optionally plus model-proposed questions, labelled as proposals). Every question is
// optional: the owner answers, skips or ignores it, and nothing is ever filled in for
// them — no philosophy quiz, no stand-in answer. Evidence the owner supplies can be cited
// to confirm or refute an explanation; a confirmed one shows a change candidate
// *proposal* that is never applied here. The audit detail shows who did what and when,
// which model turns ran and which owner inputs exist. The partial scope stays visible:
// what the owner changed is the evidence, the rest is unreviewed, and the impact is
// still to be investigated. All text goes through textContent.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;

export const FAMILY_LABELS = Object.freeze({
  system: '시스템 결손(정보 추출·검색·활용·전달 실패)',
  expert_judgment: '새로운 조건부 판단',
  exception: '일회성 예외',
  alternative_error: '대안 쪽의 오류',
  no_generalization: '일반화할 지식 없음',
});

export const PROPOSE_SCHEMA = 'hypotheses-propose-command-v1';
export const INQUIRY_SCHEMAS = Object.freeze({
  open: 'inquiry-open-command-v1',
  answer: 'inquiry-answer-command-v1',
  evidence: 'inquiry-evidence-command-v1',
  judgment: 'inquiry-judgment-command-v1',
});

export const ORIGIN_LABELS = Object.freeze({
  hypothesis_prediction: '설명의 예측에서',
  hypothesis_without_prediction: '예측 없는 설명에서',
  missing_evidence: '빠진 근거에서',
  model_proposal: '모델 제안 질문',
});

export const JUDGMENT_LABELS = Object.freeze({
  proposed: '제안', confirmed: '소유자 확인', refuted: '소유자 반박', unresolved: '미결',
});

export const CHANGE_LABELS = Object.freeze({
  restore: '복원 변경 제안', learn: '학습 변경 제안', protect: '보호 변경 제안',
});

export const MESSAGES = Object.freeze({
  idle: '내 버전을 고정하면 원본과의 차이를 관측할 수 있습니다.',
  transmission: '만들기를 누르면 관측된 차이와(텍스트 형식이면) 원본·내 버전이 선택한 Claude 모델로 전송됩니다.',
  proposing: '경쟁 설명을 만드는 중… (보통 수십 초)',
  proposed: '모든 설명은 제안 상태입니다. 실제 비교·행동 증거 없이 확인되지 않습니다.',
  noConnection: 'Claude 연결이 준비되지 않아 경쟁 설명을 만들 수 없습니다. 기록 화면에서 키와 모델 목록을 준비해 주세요.',
  observing: '차이를 관측하는 중…',
  noQuiz: '이 화면은 질문에 답하도록 요구하지 않습니다. 답하지 않아도 작업은 계속됩니다.',
  unreviewed: '바꾸지 않은 부분은 검토하지 않은 영역으로 남고, 영향 범위는 따로 조사합니다.',
  inquiryClosed: '탐구는 직접 열 때만 열립니다. 열면 질문과 구별 예측을 새 근거보다 먼저 고정합니다.',
  inquiryModel: '모델을 고르면 설명과 관측된 차이가 그 모델로 전송되고, 모델은 질문만 제안합니다(답하지 않습니다).',
  optional: '모든 질문은 선택입니다. 답하지 않거나 건너뛰어도 되고, 답하지 않은 질문은 누구의 답으로도 채우지 않습니다.',
  opening: '탐구를 여는 중…',
  opened: '탐구를 열었습니다. 질문과 예측이 고정되었습니다.',
  saved: '기록했습니다.',
  confirmNeeds: '확인하려면 다른 설명을 먼저 반박하거나 미결로 두고, 이 탐구의 근거를 인용해야 합니다.',
  candidateNote: '변경 후보는 제안일 뿐이며 여기서 적용되지 않습니다.',
  noCandidate: '소유자가 근거를 들어 확인한 설명이 아직 없어 변경 후보가 없습니다.',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '이 대안에서는 차이를 관측할 수 없습니다.',
  unauthenticated: '브라우저 세션이 없습니다. 세션을 다시 연결해 주세요.',
  access_denied: '이 요청은 허용되지 않았습니다.',
  not_found: '고정된 내 버전을 찾지 못했습니다.',
  unavailable: '저장소에 연결하지 못했습니다.',
  provider_unavailable: 'Claude에 연결하지 못했습니다. 기록 화면에서 키와 모델 목록을 확인해 주세요.',
  model_output_invalid: '모델의 답이 경쟁 설명 형식에 맞지 않아 받아들이지 않았습니다. 다시 만들 수 있습니다.',
  conflict: '관측된 차이가 저장된 기록과 달라 설명을 만들지 않았습니다.',
  hypotheses_required: '경쟁 설명이 먼저 있어야 탐구를 열 수 있습니다.',
  not_opened: '탐구가 아직 열리지 않았습니다.',
  evidence_required: '확인·반박에는 이 탐구에 추가한 근거를 하나 이상 인용해야 합니다.',
  competitors_unexamined: '다른 설명을 먼저 반박하거나 미결로 두어야 이 설명을 확인할 수 있습니다.',
  already_judged: '이 설명은 이미 판단했습니다.',
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

export function createInquiryPanel({ root, document, request, basePath = '/', crypto = null } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const api = `${basePath.slice(0, -1)}/api/v1`;
  let busy = false;

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

  function hypothesisList(set) {
    const list = element('ul', undefined, { 'aria-label': '경쟁하는 설명' });
    for (const item of set.hypotheses) {
      const row = element('li');
      row.append(element('strong', `${FAMILY_LABELS[item.family] ?? item.family} · 제안`), element('p', String(item.claim)));
      if (item.conditions.length) row.append(element('p', `성립 조건: ${item.conditions.join(' / ')}`));
      if (item.predictions.length) row.append(element('p', `구별할 예측: ${item.predictions.join(' / ')}`));
      list.append(row);
    }
    return [element('p', MESSAGES.proposed), list];
  }

  async function explanations(value) {
    // the difference's own hypothesis set, or an explicit way to ask for one
    const differenceId = value.difference_ref?.id;
    if (typeof differenceId !== 'string' || !UUID.test(differenceId)) return [];
    const route = `${api}/differences/${differenceId}/hypotheses`;
    let set = null;
    try {
      set = await request(route, {});
    } catch {
      return [];
    }
    if (set.state === 'proposed') return hypothesisList(set);
    if (crypto === null || typeof crypto.randomUUID !== 'function') return [];
    let connection = null;
    try {
      connection = await request(`${api}/connections/claude`, {});
    } catch {
      connection = null;
    }
    const models = connection?.key_present && connection.catalog ? connection.catalog.model_ids : [];
    if (!models.length) return [element('p', MESSAGES.noConnection)];
    const select = element('select', undefined, { id: 'hypothesis-model', 'aria-label': '경쟁 설명에 쓸 모델' });
    for (const id of models) select.append(element('option', id, { value: id }));
    const make = element('button', '경쟁 설명 만들기', { type: 'button' });
    make.addEventListener('click', async () => {
      if (busy) return;
      busy = true;
      say(MESSAGES.proposing, 'proposing');
      try {
        const chosen = await request(`${api}/connections/claude/model-choice`, { method: 'POST', body: { model_id: select.value } });
        await request(route, { method: 'POST', body: { schema_version: PROPOSE_SCHEMA, command_id: crypto.randomUUID(),
          model_choice_ref: chosen.model_choice_ref } });
        await render(value);
        say(MESSAGES.proposed, 'proposed');
      } catch (error) {
        const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
        say(ERROR_MESSAGES[code], code);
      } finally {
        busy = false;
      }
    });
    return [element('p', MESSAGES.transmission), element('label', '경쟁 설명에 쓸 모델', { for: 'hypothesis-model' }), select, make];
  }

  function codeOf(error) {
    // the inquiry routes repeat their exact closed code as `reason` (the session keeps only generic codes)
    if (typeof error?.reason === 'string' && Object.hasOwn(ERROR_MESSAGES, error.reason)) return error.reason;
    return Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
  }

  async function act(section, differenceId, path, body) {
    if (busy) return;
    busy = true;
    try {
      await request(path, { method: 'POST', body });
      await inquiry(section, differenceId);
      say(MESSAGES.saved, 'saved');
    } catch (error) {
      const code = codeOf(error);
      say(ERROR_MESSAGES[code], code);
    } finally {
      busy = false;
    }
  }

  function questionRow(section, differenceId, item, answered) {
    const route = `${api}/inquiries/${differenceId}/answers`;
    const row = element('li', undefined, { 'data-question': item.question_id });
    row.append(element('strong', `${item.question_id} · ${ORIGIN_LABELS[item.origin] ?? item.origin}`), element('p', String(item.text)));
    if (item.if_yes && item.if_no) row.append(element('p', `그렇다면: ${item.if_yes} / 아니라면: ${item.if_no}`));
    const state = answered === undefined ? '답하지 않음'
      : answered.state === 'skipped' ? '건너뜀' : `내 답: ${answered.text}`;
    row.append(element('p', state, { 'data-answer-state': answered?.state ?? 'unanswered' }));
    const id = `inquiry-answer-${item.question_id}`;
    const box = element('textarea', undefined, { id, rows: '2' });
    const save = element('button', `${item.question_id} 답 저장`, { type: 'button' });
    const skip = element('button', `${item.question_id} 건너뛰기`, { type: 'button' });
    save.addEventListener('click', () => {
      const text = String(box.value ?? '');
      if (!text.trim()) { say('답을 입력해야 저장합니다. 답하지 않아도 됩니다.', 'invalid_input'); return undefined; }
      return act(section, differenceId, route, { schema_version: INQUIRY_SCHEMAS.answer, command_id: crypto.randomUUID(),
        question_id: item.question_id, action: 'answer', text });
    });
    skip.addEventListener('click', () => act(section, differenceId, route, { schema_version: INQUIRY_SCHEMAS.answer,
      command_id: crypto.randomUUID(), question_id: item.question_id, action: 'skip', text: null }));
    row.append(element('label', `${item.question_id}에 대한 내 답 (선택)`, { for: id }), box, save, skip);
    return row;
  }

  function evidenceForm(section, differenceId) {
    const text = element('textarea', undefined, { id: 'inquiry-evidence-text', rows: '3' });
    const sources = element('textarea', undefined, { id: 'inquiry-evidence-sources', rows: '2' });
    const add = element('button', '근거 추가', { type: 'button' });
    add.addEventListener('click', () => {
      const value = String(text.value ?? '');
      if (!value.trim()) { say('근거 내용을 입력해 주세요.', 'invalid_input'); return undefined; }
      const refs = String(sources.value ?? '').split('\n').map(line => line.trim()).filter(Boolean);
      return act(section, differenceId, `${api}/inquiries/${differenceId}/evidence`, {
        schema_version: INQUIRY_SCHEMAS.evidence, command_id: crypto.randomUUID(), text: value, sources: refs });
    });
    return [element('label', '근거 내용', { for: 'inquiry-evidence-text' }), text,
      element('label', '출처 (한 줄에 하나, 선택)', { for: 'inquiry-evidence-sources' }), sources, add];
  }

  function judgmentRow(section, differenceId, item, evidence) {
    const row = element('li', undefined, { 'data-hypothesis': item.hypothesis_id });
    row.append(element('strong', `${item.hypothesis_id} · ${FAMILY_LABELS[item.family] ?? item.family} · ${JUDGMENT_LABELS[item.status] ?? item.status}`),
      element('p', String(item.claim)));
    if (item.status !== 'proposed') return row;
    const id = `inquiry-judgment-${item.hypothesis_id}`;
    const verdict = element('select', undefined, { id });
    for (const [value, label] of [['confirmed', '확인'], ['refuted', '반박'], ['unresolved', '미결로 둠']]) {
      verdict.append(element('option', label, { value }));
    }
    row.append(element('label', `${item.hypothesis_id}에 대한 내 판단`, { for: id }), verdict);
    const cited = [];
    for (const [index, entry] of evidence.entries()) {
      const boxId = `${id}-cite-${entry.evidence_id}`;
      const box = element('input', undefined, { type: 'checkbox', id: boxId, value: entry.evidence_id });
      cited.push([box, entry.evidence_id]);
      row.append(box, element('label', `${item.hypothesis_id}: 근거 ${index + 1} 인용`, { for: boxId }));
    }
    const note = element('input', undefined, { type: 'text', id: `${id}-note` });
    const record = element('button', `${item.hypothesis_id} 판단 기록`, { type: 'button' });
    record.addEventListener('click', () => {
      const text = String(note.value ?? '');
      return act(section, differenceId, `${api}/inquiries/${differenceId}/judgments`, {
        schema_version: INQUIRY_SCHEMAS.judgment, command_id: crypto.randomUUID(), hypothesis_id: item.hypothesis_id,
        judgment: verdict.value, evidence_ids: cited.filter(([box]) => box.checked).map(([, evidenceId]) => evidenceId),
        note: text.trim() ? text : null });
    });
    row.append(element('label', `${item.hypothesis_id} 메모 (선택)`, { for: `${id}-note` }), note, record);
    return row;
  }

  function candidateList(state) {
    const nodes = [element('h3', '변경 후보')];
    const conclusions = state.no_change_conclusions ?? [];
    if (!state.change_candidates.length && !conclusions.length) {
      nodes.push(element('p', MESSAGES.noCandidate));
      return nodes;
    }
    const list = element('ul', undefined, { 'aria-label': '변경 후보 제안' });
    for (const item of state.change_candidates) {
      const leak = item.leak_check === 'copies_owner_wording'
        ? '주의: 내 버전의 문구를 그대로 옮긴 부분이 있어 이대로는 쓸 수 없습니다.'
        : item.leak_check === 'passed' ? '내 버전 문구 복사 검사: 통과' : '내 버전 문구 복사 검사: 텍스트가 아니어서 하지 않음';
      const row = element('li', undefined, { 'data-candidate': item.candidate_id });
      row.append(element('strong', `${CHANGE_LABELS[item.kind] ?? item.kind} · 제안 · 적용되지 않음`),
        element('p', String(item.claim)), element('p', `근거 ${item.evidence_refs.length}개 · 영향 범위: 조사 전`),
        element('p', leak), element('p', String(item.next_step)));
      list.append(row);
    }
    for (const item of conclusions) list.append(element('li', String(item.reason)));
    nodes.push(element('p', MESSAGES.candidateNote), list);
    return nodes;
  }

  function auditView(detail) {
    const inputs = detail.owner_inputs;
    const turns = element('ul', undefined, { 'aria-label': '모델 호출' });
    for (const turn of detail.model_turns) {
      const outcome = turn.outcome?.state ?? '기록 없음';
      turns.append(element('li', `${turn.purpose === 'inquiry_questions' ? '질문 제안' : '경쟁 설명'} · ${turn.model_id ?? '모델 불명'} · ${turn.requested_at ?? ''} · 결과 ${outcome}`));
    }
    if (!detail.model_turns.length) turns.append(element('li', '모델 호출 없음'));
    const timeline = element('ol', undefined, { 'aria-label': '기록 순서' });
    const kinds = { difference_observed: '차이 관측', hypotheses_proposed: '경쟁 설명 제안', opened: '탐구 열기(질문 고정)',
      answer: '답', skip: '건너뜀', evidence: '근거 추가', judgment: '판단' };
    const actors = { owner: '소유자', model: '모델(소유자 요청)', framework: '프레임워크', unknown: '알 수 없음' };
    for (const item of detail.timeline) {
      const extra = item.question_id ? ` ${item.question_id}` : item.hypothesis_id ? ` ${item.hypothesis_id} → ${item.judgment}` : '';
      timeline.append(element('li', `${item.at} · ${actors[item.actor] ?? item.actor} · ${kinds[item.kind] ?? item.kind}${extra}`));
    }
    return [element('h4', '감사 상세'),
      element('p', `소유자 입력: 답 ${inputs.answers} · 건너뜀 ${inputs.skips} · 근거 ${inputs.evidence} · 판단 ${inputs.judgments}`),
      element('p', `소유자 입력이 아닌 사람 답: ${detail.inputs_not_from_owner}`), element('p', String(detail.note)),
      element('h5', '모델 호출'), turns, element('h5', '누가 무엇을 언제'), timeline];
  }

  async function modelPicker(id) {
    let connection = null;
    try {
      connection = await request(`${api}/connections/claude`, {});
    } catch {
      connection = null;
    }
    const models = connection?.key_present && connection.catalog ? connection.catalog.model_ids : [];
    const select = element('select', undefined, { id });
    select.append(element('option', '모델 제안 없이', { value: '' }));
    for (const model of models) select.append(element('option', model, { value: model }));
    return select;
  }

  async function closedInquiry(section, differenceId, state) {
    const nodes = [element('h3', '탐구'), element('p', MESSAGES.inquiryClosed), element('p', MESSAGES.noQuiz)];
    if (state.can_open && crypto !== null && typeof crypto.randomUUID === 'function') {
      const select = await modelPicker('inquiry-model');
      const start = element('button', '탐구 열기', { type: 'button' });
      start.addEventListener('click', async () => {
        if (busy) return;
        busy = true;
        say(MESSAGES.opening, 'opening');
        try {
          let choice = null;
          if (select.value) {
            choice = (await request(`${api}/connections/claude/model-choice`, { method: 'POST', body: { model_id: select.value } })).model_choice_ref;
          }
          await request(`${api}/inquiries/${differenceId}`, { method: 'POST', body: {
            schema_version: INQUIRY_SCHEMAS.open, command_id: crypto.randomUUID(), model_choice_ref: choice } });
          await inquiry(section, differenceId);
          say(MESSAGES.opened, 'opened');
        } catch (error) {
          const code = codeOf(error);
          say(ERROR_MESSAGES[code], code);
        } finally {
          busy = false;
        }
      });
      nodes.push(element('p', MESSAGES.inquiryModel), element('label', '질문을 더 제안받을 모델 (선택)', { for: 'inquiry-model' }), select, start);
    }
    nodes.push(...candidateList({ change_candidates: [] }));
    section.replaceChildren(...nodes);
  }

  async function inquiry(section, differenceId) {
    let state;
    try {
      state = await request(`${api}/inquiries/${differenceId}`, {});
    } catch {
      state = null;
    }
    if (!state || typeof state !== 'object' || !Array.isArray(state.questions)) {
      section.replaceChildren();
      return;
    }
    if (state.state === 'not_opened') {
      await closedInquiry(section, differenceId, state);
      return;
    }
    const answers = new Map(state.answers.map(item => [item.question_id, item]));
    const questions = element('ol', undefined, { 'aria-label': '탐구 질문' });
    for (const item of state.questions) questions.append(questionRow(section, differenceId, item, answers.get(item.question_id)));
    const evidence = element('ol', undefined, { 'aria-label': '내가 추가한 근거' });
    for (const item of state.evidence) {
      evidence.append(element('li', `${item.text}${item.sources.length ? ` (출처: ${item.sources.join(', ')})` : ''}`));
    }
    const judgments = element('ul', undefined, { 'aria-label': '설명별 내 판단' });
    for (const item of state.hypotheses) judgments.append(judgmentRow(section, differenceId, item, state.evidence));
    const auditRoot = element('div');
    const showAudit = element('button', '감사 상세 보기', { type: 'button' });
    showAudit.addEventListener('click', async () => {
      try {
        auditRoot.replaceChildren(...auditView(await request(`${api}/inquiries/${differenceId}/audit`, {})));
      } catch (error) {
        const code = codeOf(error);
        say(ERROR_MESSAGES[code], code);
      }
    });
    section.replaceChildren(
      element('h3', '탐구'), element('p', `질문 고정: ${state.frozen_at}`), element('p', MESSAGES.optional),
      questions, element('p', `답하지 않은 질문 ${state.unanswered_count}개`),
      element('h3', '근거'), evidence, ...evidenceForm(section, differenceId),
      element('h3', '판단'), element('p', MESSAGES.confirmNeeds), judgments,
      ...candidateList(state), element('p', String(state.spli?.reason ?? '')),
      element('h3', '감사'), showAudit, auditRoot,
    );
  }

  async function render(value) {
    const observations = element('ul', undefined, { 'aria-label': '관측된 차이' });
    for (const item of value.observations) observations.append(element('li', String(item.description)));
    const uncertainties = value.uncertainties.map(text => element('p', String(text)));
    const families = element('ul', undefined, { 'aria-label': '경쟁하는 설명' });
    for (const family of value.hypotheses.families) {
      families.append(element('li', `${FAMILY_LABELS[family] ?? family}: 검토되지 않음`));
    }
    const scope = value.evidence_scope.includes('whole') ? '내 버전 전체가 근거입니다.'
      : `내가 바꾼 ${value.evidence_scope.length}곳이 근거입니다.`;
    const proposed = await explanations(value);
    const generated = proposed.length > 0 && proposed[0].textContent === MESSAGES.proposed;
    const head = [
      element('h3', `관측된 차이 ${value.observations.length}개`), observations, ...uncertainties,
      element('p', `${scope} ${MESSAGES.unreviewed}`),
      element('h3', '경쟁하는 설명'), ...(generated ? proposed : [element('p', String(value.hypotheses.reason)), families, ...proposed]),
    ];
    if (generated) {
      const section = element('section', undefined, { 'aria-label': '탐구', 'data-difference-id': value.difference_ref.id });
      await inquiry(section, value.difference_ref.id);
      body.replaceChildren(...head, section);
    } else {
      body.replaceChildren(...head,
        element('h3', '질문'), element('p', String(value.inquiry.reason)), element('p', MESSAGES.noQuiz),
        element('h3', '변경 후보'), element('p', String(value.change_candidates.reason)));
    }
    if (!generated) say('차이를 기록했습니다. 원인은 아직 해석하지 않았습니다.', 'observed');
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
      await render(value);
      return value;
    } catch (error) {
      const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
      say(ERROR_MESSAGES[code], code);
      throw error;
    }
  }

  return Object.freeze({ show });
}
