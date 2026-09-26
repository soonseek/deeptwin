// T030 (FR-003): the owner's common-work target on the work screen, over `work-models-v1`.
// Drafting is one explicit owner action that sends the saved work text to Claude through
// the owner's own connection (records page), with the model the owner picks here; the
// panel says so before the button is pressed. The draft is shown whole — goals,
// deliverables, completion conditions, authorities, risks, unknowns (blocking ones
// marked) and the recommended shape — and the owner accepts or rejects exactly that
// draft. A work without a retained original cannot be drafted, and the panel says why
// instead of sending. Server text reaches the DOM through textContent only.

const BASE_PATH = /^\/(?:[0-9a-f]{32}\/)?$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export const DRAFT_SCHEMA = 'work-model-draft-command-v1';
export const CONFIRM_SCHEMA = 'work-model-confirm-command-v1';

export const MESSAGES = Object.freeze({
  intro: '작업 모델은 설계를 시작하기 전에 목표·완료 조건·권한·위험·미결 사항을 확인하는 단계입니다.',
  transmission: '만들기를 누르면 저장된 설명과, 자료 목록에서 직접 읽은 자료의 읽힌 글자만 선택한 Claude 모델로 전송됩니다. 읽지 않은 자료의 내용은 전송하지 않습니다.',
  unsaved: '먼저 설명을 저장해야 작업 모델을 만들 수 있습니다.',
  noSources: '원본 자료를 하나 이상 추가해야 작업 모델을 만들 수 있습니다.',
  noConnection: 'Claude 연결이 준비되지 않았습니다. 설정 > 모델 연결에서 키를 저장하고 모델 목록을 읽어 주세요.',
  drafting: '작업 모델을 만드는 중… (보통 수십 초)',
  drafted: '작업 모델 초안입니다. 내용을 확인한 뒤 수락하거나 거절하세요.',
  confirmed: '이 작업 모델을 수락했습니다.',
  rejected: '이 작업 모델을 거절했습니다. 설명을 고쳐 저장한 뒤 다시 만들 수 있습니다.',
  blocking: '막힌 미결 사항이 있어 이 작업 모델로는 설계를 시작할 수 없습니다. 설명에 답을 보태 저장한 뒤 다시 만드세요.',
});

export const ERROR_MESSAGES = Object.freeze({
  invalid_input: '요청 형식이 맞지 않습니다.',
  unauthenticated: '브라우저 세션이 없습니다.',
  not_found: '저장된 설명이나 작업 모델을 찾지 못했습니다.',
  conflict: '다른 결정이 이미 기록되었거나, 확인한 초안과 저장된 초안이 다릅니다.',
  sources_required: MESSAGES.noSources,
  provider_unavailable: 'Claude에 연결하지 못했습니다. 설정 > 모델 연결에서 키와 모델 목록을 확인해 주세요.',
  model_output_invalid: '모델의 답이 작업 모델 형식에 맞지 않아 받아들이지 않았습니다. 다시 만들 수 있습니다.',
  unavailable: '처리하지 못했습니다.',
});

const SHAPE_LABELS = Object.freeze({
  single_agent: '에이전트 하나', deterministic: '정해진 절차(모델 없음)', multi_agent: '여러 에이전트',
  human_only: '사람만 수행',
});
const STATUS_LABELS = Object.freeze({ resolved: '해결됨', acknowledged: '확인됨', blocking: '막힘' });

function fail(message) {
  throw new Error(message);
}

export function createWorkModel({ root, document, request, crypto, basePath = '/', work, onChange = () => {} } = {}) {
  if (typeof root?.replaceChildren !== 'function') fail('a root is required');
  if (typeof request !== 'function') fail('a request adapter is required');
  if (typeof crypto?.randomUUID !== 'function') fail('a UUID source is required');
  if (typeof work !== 'function') fail('a work reader is required');
  if (typeof basePath !== 'string' || !BASE_PATH.test(basePath)) fail('base path is not a deployment base path');
  const api = `${basePath.slice(0, -1)}/api/v1`;
  let view = null;
  let busy = false;

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite' });
  const body = element('div');
  root.replaceChildren(element('h2', '작업 모델'), element('p', MESSAGES.intro), status, body);

  function say(text, code) {
    status.textContent = text;
    status.dataset.state = code;
  }

  function failed(error) {
    const code = Object.hasOwn(ERROR_MESSAGES, error?.code) ? error.code : 'unavailable';
    say(ERROR_MESSAGES[code], code);
  }

  function list(title, items, render) {
    const section = element('section');
    section.append(element('h3', title));
    const ul = element('ul');
    for (const item of items) ul.append(element('li', render(item)));
    if (!items.length) ul.append(element('li', '없음'));
    section.append(ul);
    return section;
  }

  function renderView() {
    const model = view.work_model;
    const parts = [
      list('목표', model.goals, item => item),
      list('산출물', model.deliverables, item => `${item.description} (${item.media_types.join(', ')} · ${item.min_items}–${item.max_items}개)`),
      list('완료 조건', model.completion_conditions, item => item),
      list('권한', model.authorities, item => `${item.capability} — ${item.scope} (${item.effect})`),
      list('위험', model.risks, item => `${item.description} · ${item.severity}${item.mitigation_required ? ' · 완화 필요' : ''}`),
      list('미결 사항', model.unknowns, item => `${item.question} · ${STATUS_LABELS[item.status] ?? item.status}`),
      element('p', `권장 형태: ${SHAPE_LABELS[model.suitability.recommended_shape] ?? model.suitability.recommended_shape} — ${model.suitability.rationale}`),
    ];
    if (view.blocking_unknown_ids.length) parts.push(element('p', MESSAGES.blocking, { 'data-state': 'blocking' }));
    if (view.state === 'unconfirmed') {
      const accept = element('button', '이 작업 모델 수락', { type: 'button' });
      const reject = element('button', '거절', { type: 'button' });
      accept.addEventListener('click', () => decide('accepted'));
      reject.addEventListener('click', () => decide('rejected'));
      parts.push(accept, reject);
    } else {
      parts.push(element('p', view.state === 'confirmed' ? MESSAGES.confirmed : MESSAGES.rejected));
    }
    return parts;
  }

  async function render() {
    const current = work();
    const parts = [];
    if (!current?.work_id || !UUID.test(current.work_id)) {
      body.replaceChildren(element('p', MESSAGES.unsaved));
      return;
    }
    if (!(current.sources > 0)) {
      body.replaceChildren(element('p', MESSAGES.noSources), ...(view ? renderView() : []));
      return;
    }
    let connection = null;
    try {
      connection = await request(`${api}/connections/claude`, {});
    } catch {
      connection = null;
    }
    const models = connection?.key_present && connection.catalog ? connection.catalog.model_ids : [];
    if (!models.length) {
      parts.push(element('p', MESSAGES.noConnection));
    } else {
      const select = element('select', undefined, { id: 'work-model-model', 'aria-label': '작업 모델에 쓸 모델' });
      for (const id of models) select.append(element('option', id, { value: id }));
      const make = element('button', view ? '작업 모델 다시 만들기' : '작업 모델 만들기', { type: 'button' });
      make.addEventListener('click', () => draft(select.value));
      parts.push(element('p', MESSAGES.transmission), element('label', '작업 모델에 쓸 모델', { for: 'work-model-model' }), select, make);
    }
    body.replaceChildren(...parts, ...(view ? renderView() : []));
  }

  async function draft(modelId) {
    if (busy) return;
    const current = work();
    if (!current?.work_id || !Number.isInteger(current.revision)) return;
    busy = true;
    say(MESSAGES.drafting, 'drafting');
    try {
      // the model-choice route is idempotent: it returns the exact ref of the owner's pick
      const chosen = await request(`${api}/connections/claude/model-choice`, { method: 'POST', body: { model_id: modelId } });
      view = await request(`${api}/work-models`, { method: 'POST', body: {
        schema_version: DRAFT_SCHEMA, command_id: crypto.randomUUID(), work_id: current.work_id,
        revision: current.revision, model_choice_ref: chosen.model_choice_ref } });
      say(MESSAGES.drafted, 'drafted');
    } catch (error) {
      failed(error);
    } finally {
      busy = false;
    }
    await render();
    onChange(view);
  }

  async function decide(decision) {
    if (busy || view === null) return;
    busy = true;
    try {
      view = await request(`${api}/work-models/${view.work_model_id}/confirm`, { method: 'POST', body: {
        schema_version: CONFIRM_SCHEMA, command_id: crypto.randomUUID(), work_model_ref: view.work_model_ref,
        decision } });
      say(decision === 'accepted' ? MESSAGES.confirmed : MESSAGES.rejected, view.state);
    } catch (error) {
      failed(error);
    } finally {
      busy = false;
    }
    await render();
    onChange(view);
  }

  // the conversation decided this draft (the same decision the buttons make): read it again
  async function refresh() {
    if (view === null) return render();
    try {
      view = await request(`${api}/work-models/${view.work_model_id}`, {});
      if (view.state !== 'unconfirmed') say(view.state === 'confirmed' ? MESSAGES.confirmed : MESSAGES.rejected, view.state);
    } catch (error) {
      failed(error);
    }
    return render();
  }

  return Object.freeze({ load: render, refresh, get view() { return view; } });
}
