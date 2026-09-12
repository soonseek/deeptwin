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
