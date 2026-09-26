const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const USER_ORIGINS = new Set([
  'work_request',
  'clarification',
  'own_artifact',
  'analysis_evidence',
]);
const REF_KINDS = new Set([
  'actor', 'access_policy', 'retention_policy', 'work_revision', 'chat_message',
  'proposed_command', 'source', 'extraction', 'work_model', 'model_catalog',
  'model_choice', 'runtime_profile', 'design_decision', 'design_candidate', 'graph',
  'environment', 'design_approval', 'run_consent', 'action_approval', 'run_manifest',
  'budget_policy', 'frozen_turn', 'artifact', 'artifact_projection', 'handoff',
  'memory_event', 'decision_record', 'original_execution', 'own_alternative',
  'selector', 'difference', 'hypothesis', 'inquiry', 'change_candidate',
  'comparison_plan', 'comparison_result', 'promotion_decision', 'lens_definition',
  'lens_composition', 'inquiry_audit', 'knowledge_candidate', 'evaluation_dataset',
  'evaluation_profile', 'validation_report', 'independence_profile', 'qualification',
  'extension_manifest', 'backup_manifest', 'export_manifest', 'tool_definition',
  'grant', 'execution_envelope', 'task_spec', 'rubric', 'observation_contract',
]);
const TARGET_KINDS = new Set([
  ...REF_KINDS, 'work', 'setup', 'session', 'connection', 'run', 'node_execution',
  'attempt', 'tool_call', 'budget_reservation', 'approval_challenge',
  'environment_head', 'speech_session', 'series', 'round', 'event', 'record_gap',
  'backup', 'export',
]);

function exactKeys(value, keys) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === keys.length
    && keys.every(key => Object.hasOwn(value, key));
}

function uuid(value, label) {
  if (typeof value !== 'string' || !UUID.test(value) || /^0{8}-/.test(value)) {
    throw new TypeError(`${label} 식별자를 확인해 주세요.`);
  }
  return value;
}

function positiveInteger(value, label) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new TypeError(`${label} 버전을 확인해 주세요.`);
  }
  return value;
}

function workBinding(value) {
  if (!exactKeys(value, ['id', 'revision'])) throw new TypeError('현재 업무 저장본을 확인해 주세요.');
  return { id: uuid(value.id, '업무'), revision: positiveInteger(value.revision, '업무') };
}

function text(value) {
  if (typeof value !== 'string' || !value.trim() || value.length > 20_000) {
    throw new TypeError('덧붙일 내용은 1자 이상 20,000자 이하로 입력해 주세요.');
  }
  return value;
}

function entityRef(value) {
  if (!exactKeys(value, ['kind', 'id', 'version', 'sha256'])
      || !REF_KINDS.has(value.kind) || !SHA256.test(value.sha256)) {
    throw new TypeError('참조할 자료의 정확한 저장본을 확인해 주세요.');
  }
  return {
    kind: value.kind,
    id: uuid(value.id, '참조'),
    version: positiveInteger(value.version, '참조'),
    sha256: value.sha256,
  };
}

function objectRef(value) {
  if (!exactKeys(value, ['kind', 'id', 'version', 'content_hash'])
      || !TARGET_KINDS.has(value.kind) || !SHA256.test(value.content_hash)) {
    throw new TypeError('행동 대상의 정확한 저장본을 확인해 주세요.');
  }
  return {
    kind: value.kind,
    id: uuid(value.id, '행동 대상'),
    version: positiveInteger(value.version, '행동 대상'),
    content_hash: value.content_hash,
  };
}

export function messagePayload(work, content, referencedEntityRefs = [],
  semanticOrigin = 'clarification') {
  const binding = workBinding(work);
  if (!USER_ORIGINS.has(semanticOrigin)) {
    throw new TypeError('이 입력 경로에서는 일반 업무 맥락만 기록할 수 있습니다.');
  }
  if (!Array.isArray(referencedEntityRefs) || referencedEntityRefs.length > 64) {
    throw new TypeError('참조할 자료가 너무 많거나 형식이 다릅니다.');
  }
  const refs = referencedEntityRefs.map(entityRef);
  const identities = refs.map(item => JSON.stringify(item));
  if (new Set(identities).size !== refs.length) throw new TypeError('같은 자료를 두 번 참조할 수 없습니다.');
  return {
    work_revision: binding.revision,
    content: text(content),
    semantic_origin: semanticOrigin,
    referenced_entity_refs: refs,
  };
}

export function commandResponsePayload(work, value) {
  const binding = workBinding(work);
  if (!exactKeys(value, [
    'commandId', 'challengeId', 'token', 'content', 'exactTargetRef',
  ]) || typeof value.token !== 'string' || !value.token || value.token.length > 256) {
    throw new TypeError('현재 행동 확인 정보를 다시 열어 주세요.');
  }
  return {
    work_revision: binding.revision,
    command_id: uuid(value.commandId, '행동'),
    challenge_id: uuid(value.challengeId, '확인'),
    token: value.token,
    content: text(value.content),
    exact_target_ref: objectRef(value.exactTargetRef),
  };
}

function message(value) {
  if (!value || typeof value !== 'object' || typeof value.content !== 'string'
      || !Number.isSafeInteger(value.sequence) || value.sequence < 1
      || !value.actor || !['human', 'agent', 'system'].includes(value.actor.kind)
      || !USER_ORIGINS.has(value.semantic_origin)
      && value.semantic_origin !== 'command_request'
      || !Array.isArray(value.referenced_entity_refs)) {
    throw new TypeError('저장된 대화 기록을 확인하지 못했습니다.');
  }
  return {
    ...value,
    actor: { ...value.actor },
    referenced_entity_refs: value.referenced_entity_refs.map(item => ({ ...item })),
    exact_target_ref: value.exact_target_ref ? { ...value.exact_target_ref } : null,
  };
}

function safeError(error) {
  return error instanceof Error && error.message
    ? error.message
    : '대화 기록을 처리하지 못했습니다. 입력은 이 화면에 남아 있습니다.';
}

export function createConversationController({ request, onChange = () => {} }) {
  if (typeof request !== 'function' || typeof onChange !== 'function') {
    throw new TypeError('대화 화면에는 요청 함수와 상태 수신기가 필요합니다.');
  }
  const drafts = new Map();
  let generation = 0;
  let state = {
    workId: '', revision: null, messages: [], draft: '', busy: false, error: '',
  };

  function snapshot() {
    return {
      ...state,
      messages: state.messages.map(item => ({
        ...item,
        actor: { ...item.actor },
        referenced_entity_refs: item.referenced_entity_refs.map(ref => ({ ...ref })),
        exact_target_ref: item.exact_target_ref ? { ...item.exact_target_ref } : null,
      })),
    };
  }

  function emit() { onChange(snapshot()); }

  async function setWork(nextWork) {
    if (state.workId) drafts.set(state.workId, state.draft);
    const selected = nextWork === null ? null : workBinding(nextWork);
    const selectedGeneration = ++generation;
    state = {
      workId: selected?.id || '',
      revision: selected?.revision || null,
      messages: [],
      draft: selected ? drafts.get(selected.id) || '' : '',
      busy: Boolean(selected),
      error: '',
    };
    emit();
    if (!selected) return snapshot();
    try {
      const result = await request(`/api/v1/works/${encodeURIComponent(selected.id)}/messages`);
      if (selectedGeneration !== generation || state.workId !== selected.id) return snapshot();
      if (!result || !Array.isArray(result.messages) || result.messages.length > 10_000) {
        throw new TypeError('저장된 대화 기록 형식이 다릅니다.');
      }
      state.messages = result.messages.map(message);
      state.error = '';
      return snapshot();
    } catch (error) {
      if (selectedGeneration === generation && state.workId === selected.id) {
        state.error = safeError(error);
      }
      throw error;
    } finally {
      if (selectedGeneration === generation && state.workId === selected.id) {
        state.busy = false;
        emit();
      }
    }
  }

  function setDraft(value) {
    if (typeof value !== 'string' || value.length > 20_000) {
      throw new TypeError('덧붙일 내용은 20,000자 이하로 입력해 주세요.');
    }
    state.draft = value;
    if (state.workId) drafts.set(state.workId, value);
    state.error = '';
    emit();
  }

  async function send({ semanticOrigin = 'clarification', referencedEntityRefs = [] } = {}) {
    if (!state.workId || state.busy) throw new TypeError('현재 업무 대화가 준비되지 않았습니다.');
    const selected = { id: state.workId, revision: state.revision };
    const selectedGeneration = generation;
    const submittedDraft = state.draft;
    const body = messagePayload(
      selected, submittedDraft, referencedEntityRefs, semanticOrigin,
    );
    state.busy = true;
    state.error = '';
    emit();
    try {
      const result = await request(
        `/api/v1/works/${encodeURIComponent(selected.id)}/messages`,
        { method: 'POST', body },
      );
      const recorded = message(result?.message);
      if (selectedGeneration !== generation || state.workId !== selected.id) return recorded;
      state.messages = [...state.messages, recorded];
      if (state.draft === submittedDraft) {
        state.draft = '';
        drafts.set(selected.id, '');
      }
      return recorded;
    } catch (error) {
      if (selectedGeneration === generation && state.workId === selected.id) {
        state.error = safeError(error);
      }
      throw error;
    } finally {
      if (selectedGeneration === generation && state.workId === selected.id) {
        state.busy = false;
        emit();
      }
    }
  }

  return { setWork, setDraft, send, snapshot };
}

// ---------------------------------------------------------------------------------------
// T023 (FR-009): the supported factory's shared conversation on the work screen, over
// `conversations-v1`. What the owner writes is recorded as a message bound to the work's
// current revision and to the exact records the owner ticks (the saved revision, an
// original, a reading, the work model on screen). Words never approve anything: a
// referenced-object command (confirm or reject the work model) is proposed explicitly,
// and it runs only when the owner answers the challenge the server opened — the
// `승인` button, or the exact phrase typed and sent as an approval answer. Anything else
// (`응`, `네`, a near miss) is refused as ambiguous and the typed text stays. The token
// lives only in this page's memory; after a reload a fresh challenge is asked for. The
// unsent text and a message whose answer was lost are kept in this browser only (said so)
// and resent under the same command id. Server text reaches the DOM through textContent.
// ---------------------------------------------------------------------------------------

const CONVERSATION_BASE = /^\/(?:[0-9a-f]{32}\/)?$/;
const WORK_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export const CONVERSATION_SCHEMAS = Object.freeze({
  message: 'conversation-message-command-v1',
  proposal: 'conversation-proposal-command-v1',
  challenge: 'conversation-challenge-command-v1',
  approval: 'conversation-approval-command-v1',
});
export const CONVERSATION_MESSAGES = Object.freeze({
  intro: '대화에 남긴 말은 이 업무의 현재 수정본과 표시한 자료에 묶여 이 인스턴스에 기록됩니다. 말만으로는 아무것도 승인되지 않습니다.',
  approvalRule: '작업 모델 확정·반려는 제안한 뒤, 표시된 확인 문구를 정확히 입력해 “승인 응답으로 보내기”를 누르거나 “승인”을 눌러야만 실행됩니다.',
  unsaved: '업무를 저장하면 대화를 남길 수 있습니다.',
  draftKept: '보내지 않은 대화 입력은 이 브라우저에만 임시 보관됩니다.',
  sending: '기록하는 중…',
  sent: '대화에 기록했습니다.',
  proposed: '제안을 기록했습니다. 확인 문구로 승인해야 실행됩니다.',
  executed: '승인했고, 작업 모델에 결정이 기록되었습니다.',
  failed: '승인은 기록되었지만 실행하지 못했습니다.',
  needTarget: '명령을 제안하려면 작업 모델을 참조로 표시해 주세요.',
  reissued: '새 확인 문구를 받았습니다.',
});
export const CONVERSATION_ERRORS = Object.freeze({
  invalid_input: '입력 형식이 맞지 않습니다. 입력은 그대로 남아 있습니다.',
  unauthenticated: '세션이 끝났습니다. 시작 화면에서 다시 로그인해 주세요. 입력은 이 브라우저에 남아 있습니다.',
  access_denied: '세션 확인에 실패했습니다. 화면을 다시 열어 주세요.',
  not_found: '대상을 이 업무에서 찾지 못했습니다.',
  conflict: '승인·제안 조건이 맞지 않습니다(확인 문구가 만료·교체되었거나, 업무가 바뀌었거나, 이미 결정되었습니다). 아무것도 바뀌지 않았습니다.',
  approval_ambiguous: '정확한 확인 문구가 아니어서 승인으로 처리하지 않았습니다. 아무것도 바뀌지 않았고 입력은 그대로 남아 있습니다.',
  capacity: '대화 기록 한도에 도달했습니다.',
  unavailable: '서버가 처리하지 못했습니다. 입력은 그대로 남아 있으며 다시 보낼 수 있습니다.',
});
const ORIGIN_LABELS = Object.freeze({ owner_message: '소유자 메시지', approval_response: '승인 응답' });
const KIND_LABELS = Object.freeze({ 'work_model.confirm': '작업 모델 확정', 'work_model.reject': '작업 모델 반려' });
const PROPOSAL_STATES = Object.freeze({
  proposed: '승인 대기', approved: '승인됨 · 실행 확인 중', executed: '실행됨', failed: '실행 실패',
});

export function conversationStorageKey(basePath, workId) {
  return `deeptwin:conversation:${basePath}:${workId}`;
}

export function createWorkConversation({ root, document, request, crypto, basePath = '/', work, references = () => [],
  storage = null, onDecided = () => {}, headingLevel = 2 } = {}) {
  if (typeof root?.replaceChildren !== 'function') throw new TypeError('a root is required');
  if (typeof request !== 'function' || typeof crypto?.randomUUID !== 'function') throw new TypeError('request and crypto are required');
  if (typeof work !== 'function' || typeof references !== 'function' || typeof onDecided !== 'function') {
    throw new TypeError('work and reference readers are required');
  }
  if (typeof basePath !== 'string' || !CONVERSATION_BASE.test(basePath)) throw new TypeError('base path is not a deployment base path');
  const api = `${basePath.slice(0, -1)}/api/v1/conversations`;
  const tokens = new Map();  // proposal id → { challenge_id, token, response_text }: memory only
  let view = null;
  let busy = false;
  let workId = null;
  let offeredNow = [];
  let generation = 0;  // the latest load wins: an older answer arriving late is dropped

  function element(tag, text, attributes = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
    return node;
  }

  function stored() {
    try {
      const raw = workId ? storage?.getItem?.(conversationStorageKey(basePath, workId)) : null;
      const value = raw && raw.length <= 200000 ? JSON.parse(raw) : {};
      return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch {
      return {};
    }
  }

  function keep(value) {
    try {
      if (!workId) return;
      if (!value.draft && !value.pending) storage?.removeItem?.(conversationStorageKey(basePath, workId));
      else storage?.setItem?.(conversationStorageKey(basePath, workId), JSON.stringify(value));
    } catch {
      // the conversation never depends on the browser store
    }
  }

  const status = element('p', '', { role: 'status', 'aria-live': 'polite', id: 'conversation-status' });
  const log = element('ol', undefined, { class: 'conversation-log', 'aria-label': '대화 기록' });
  const proposals = element('ul', undefined, { class: 'conversation-proposals', 'aria-label': '제안된 명령' });
  const refBox = element('fieldset', undefined, { class: 'conversation-references' });
  const input = element('input', undefined, { id: 'conversation-input', type: 'text', maxlength: '20000', autocomplete: 'off' });
  const kind = element('select', undefined, { id: 'conversation-command' });
  for (const [value, label] of [['', '명령 제안 없음'], ['work_model.confirm', '작업 모델 확정 제안'], ['work_model.reject', '작업 모델 반려 제안']]) {
    kind.append(element('option', label, { value }));
  }
  const send = element('button', '메시지 남기기', { type: 'button' });
  const answer = element('button', '승인 응답으로 보내기', { type: 'button' });
  answer.hidden = true;
  const composer = element('div', undefined, { class: 'conversation-composer' });
  composer.append(element('label', '대화 입력', { for: 'conversation-input' }), input, refBox,
    element('label', '함께 제안할 명령', { for: 'conversation-command' }), kind, send, answer,
    element('p', CONVERSATION_MESSAGES.draftKept, { class: 'conversation-draft-note' }));
  root.replaceChildren(element(`h${headingLevel === 3 ? 3 : 2}`, '대화'), element('p', CONVERSATION_MESSAGES.intro),
    element('p', CONVERSATION_MESSAGES.approvalRule), status, log, proposals, composer);

  function say(text, code) {
    status.textContent = text;
    status.dataset.state = code;
  }

  function failed(error) {
    // the session's closed partition keeps the envelope's exact reason beside its code
    const named = Object.hasOwn(CONVERSATION_ERRORS, error?.reason) ? error.reason : error?.code;
    const code = Object.hasOwn(CONVERSATION_ERRORS, named) ? named : 'unavailable';
    say(CONVERSATION_ERRORS[code], code);
    return code;
  }

  input.addEventListener('input', () => keep({ ...stored(), draft: input.value }));

  const identity = ref => `${ref.kind}:${ref.id}:${ref.version}`;

  function renderReferences() {
    const checked = new Set(offeredNow.filter(item => item.box.checked).map(item => identity(item.ref)));
    const items = references();
    offeredNow = (Array.isArray(items) ? items : []).filter(item => item && typeof item.label === 'string' && item.ref)
      .map((item, index) => {
        const box = element('input', undefined, { type: 'checkbox', id: `conversation-ref-${index}` });
        box.checked = checked.has(identity(item.ref));
        return { ...item, box };
      });
    const nodes = [element('legend', '참조할 기록')];
    offeredNow.forEach((item, index) => {
      const label = element('label', undefined, { for: `conversation-ref-${index}` });
      label.append(item.box, element('span', item.label));
      nodes.push(label);
    });
    refBox.replaceChildren(...nodes);
  }

  function chosenReferences() {
    return offeredNow.filter(item => item.box.checked).map(item => item.ref);
  }

  function openChallenge() {
    const pending = (view?.proposals ?? []).find(item => item.state === 'proposed' && tokens.has(item.proposal_id));
    return pending ? { proposal: pending, challenge: tokens.get(pending.proposal_id) } : null;
  }

  function render() {
    if (!view) {
      log.replaceChildren(element('li', CONVERSATION_MESSAGES.unsaved));
      proposals.replaceChildren();
      composer.hidden = true;
      return;
    }
    composer.hidden = false;
    log.replaceChildren(...view.messages.map(message => {
      const item = element('li', undefined, { 'data-origin': message.semantic_origin, 'data-message-id': message.message_id });
      item.append(element('span', ORIGIN_LABELS[message.semantic_origin] ?? '기록', { class: 'conversation-origin' }),
        element('p', message.text, { class: 'conversation-text' }),
        element('span', `수정본 ${message.work_revision} · 참조 ${message.references.length}개`, { class: 'conversation-meta' }));
      return item;
    }));
    proposals.replaceChildren(...view.proposals.map(proposal => {
      const item = element('li', undefined, { 'data-proposal-state': proposal.state, 'data-proposal-id': proposal.proposal_id });
      item.append(element('span', `${KIND_LABELS[proposal.command_kind] ?? proposal.command_kind} · ${PROPOSAL_STATES[proposal.state] ?? proposal.state}`));
      if (proposal.state === 'failed' && proposal.result?.code) item.append(element('span', ` (${proposal.result.code})`));
      if (proposal.state === 'proposed') {
        const challenge = tokens.get(proposal.proposal_id);
        if (challenge) {
          item.append(element('p', `확인 문구: ${challenge.response_text}`, { class: 'conversation-phrase' }));
          const approve = element('button', '승인', { type: 'button' });
          approve.addEventListener('click', () => approveWith(proposal, 'button'));
          item.append(approve);
        } else {
          const again = element('button', '확인 문구 다시 받기', { type: 'button' });
          again.addEventListener('click', () => reissue(proposal));
          item.append(again);
        }
      }
      if (proposal.state === 'approved') {
        const resume = element('button', '실행 다시 확인', { type: 'button' });
        resume.addEventListener('click', () => load());
        item.append(resume);
      }
      return item;
    }));
    answer.hidden = openChallenge() === null;
    renderReferences();
  }

  async function load() {
    const current = work();
    const id = current?.work_id;
    if (typeof id !== 'string' || !WORK_UUID.test(id)) {
      workId = null;
      view = null;
      render();
      return null;
    }
    if (id !== workId) {
      workId = id;
      tokens.clear();
      const draft = stored().draft;
      input.value = typeof draft === 'string' ? draft : '';
    }
    const mine = ++generation;
    try {
      const value = await request(`${api}/${id}`, {});
      if (mine !== generation) return view;
      view = value;
    } catch (error) {
      if (mine !== generation) return view;
      failed(error);
    }
    render();
    return view;
  }

  async function sendMessage() {
    if (busy || !view || !workId) return;
    const text = input.value;
    if (!text.trim()) {
      say(CONVERSATION_ERRORS.invalid_input, 'invalid_input');
      return;
    }
    const refs = chosenReferences();
    const command = kind.value;
    const target = refs.find(ref => ref.kind === 'work_model');
    if (command && !target) {
      say(CONVERSATION_MESSAGES.needTarget, 'invalid_input');
      return;
    }
    const saved = stored();
    // a message whose answer was lost is resent under its own command id, never doubled
    const pending = saved.pending && saved.pending.text === text && saved.pending.expected_revision === view.revision
      ? saved.pending : { command_id: crypto.randomUUID(), text, expected_revision: view.revision,
        references: refs.map(ref => ({ kind: ref.kind, id: ref.id, version: ref.version, sha256: ref.sha256 })) };
    keep({ draft: text, pending });
    busy = true;
    say(CONVERSATION_MESSAGES.sending, 'sending');
    try {
      const result = await request(`${api}/${workId}/messages`, { method: 'POST', body: {
        schema_version: CONVERSATION_SCHEMAS.message, command_id: pending.command_id,
        expected_revision: pending.expected_revision, text: pending.text, references: pending.references } });
      keep({});
      input.value = '';
      say(CONVERSATION_MESSAGES.sent, 'sent');
      if (command) {
        const opened = await request(`${api}/${workId}/proposals`, { method: 'POST', body: {
          schema_version: CONVERSATION_SCHEMAS.proposal, command_id: crypto.randomUUID(),
          message_id: result.message.message_id, command_kind: command, target_ref: target } });
        if (opened.challenge) tokens.set(opened.proposal.proposal_id, opened.challenge);
        kind.value = '';
        say(CONVERSATION_MESSAGES.proposed, 'proposed');
      }
    } catch (error) {
      const code = failed(error);
      if (['conflict', 'invalid_input'].includes(code)) keep({ draft: text });  // a refused command id is spent
    } finally {
      busy = false;
    }
    const message = status.textContent;
    const state = status.dataset.state;
    await load();
    say(message, state);
  }

  async function reissue(proposal) {
    if (busy || !workId) return;
    busy = true;
    try {
      const result = await request(`${api}/${workId}/challenges`, { method: 'POST', body: {
        schema_version: CONVERSATION_SCHEMAS.challenge, command_id: crypto.randomUUID(), proposal_id: proposal.proposal_id } });
      tokens.set(proposal.proposal_id, result.challenge);
      say(CONVERSATION_MESSAGES.reissued, 'reissued');
    } catch (error) {
      failed(error);
    } finally {
      busy = false;
    }
    await load();
  }

  async function approveWith(proposal, route) {
    const challenge = tokens.get(proposal.proposal_id);
    if (busy || !workId || !challenge) return;
    busy = true;
    const text = route === 'chat' ? input.value : null;
    try {
      const result = await request(`${api}/${workId}/approvals`, { method: 'POST', body: {
        schema_version: CONVERSATION_SCHEMAS.approval, command_id: crypto.randomUUID(), proposal_id: proposal.proposal_id,
        challenge_id: challenge.challenge_id, token: challenge.token, route, text } });
      tokens.delete(proposal.proposal_id);
      if (route === 'chat') {
        input.value = '';
        keep({});
      }
      say(result.proposal.state === 'executed' ? CONVERSATION_MESSAGES.executed : CONVERSATION_MESSAGES.failed, result.proposal.state);
      onDecided(result.proposal);
    } catch (error) {
      failed(error);  // an ambiguous or refused answer changes nothing; the text stays
    } finally {
      busy = false;
    }
    const message = status.textContent;
    const state = status.dataset.state;
    await load();
    say(message, state);
  }

  send.addEventListener('click', sendMessage);
  answer.addEventListener('click', () => {
    const open = openChallenge();
    if (open) approveWith(open.proposal, 'chat');
  });

  render();
  return Object.freeze({ load, get view() { return view; }, refreshReferences: renderReferences });
}
