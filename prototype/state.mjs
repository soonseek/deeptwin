import { SCENES, MODES, ROLES, DESIGNS, ROUNDS, RECORDS, CONTEXT, EXPLORATIONS } from './data.mjs';
export const STORAGE_KEY = 'deeptwin:click-prototype:v1';
const MAX_TEXT = 20000;
const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
const record = value => value && typeof value === 'object' && !Array.isArray(value);
const text = value => typeof value === 'string' ? value.slice(0, MAX_TEXT) : '';
const member = (items, value, fallback) => items.some(item => item.id === value) ? value : fallback;
const validSpan = (span, role) => record(span) && Number.isInteger(span.start) && Number.isInteger(span.end)
  && span.start >= 0 && span.end > span.start && span.end <= role.text.length;
const auxiliary = id => id === 'V07' || id === 'V08';
export const roleFor = state => ROLES.find(role => role.id === state.role) ?? ROLES[0];
export const prefixFor = role => `${CONTEXT.job}/${CONTEXT.run}/${role.id}/${role.input}/${role.artifact}@${role.version}/`;
export function createState() {
  return {
    scene: 'V01', returnContext: null, mode: 'workspace', role: ROLES[0].id,
    selections: Object.fromEntries(ROLES.map(role => [role.id, { start: 0, end: role.text.length }])),
    drafts: {}, conversations: {}, request: '', designNotes: {}, evidence: {},
    design: DESIGNS[0].id, exploration: 'alternative', round: ROUNDS[0].id,
    records: ['input', 'artifact', 'failure'], redact: true
  };
}
export function targetKey(state) {
  const role = roleFor(state);
  const span = state.selections[role.id];
  return `${prefixFor(role)}${span.start}:${span.end}`;
}
export const currentDraft = state => state.drafts[targetKey(state)] ?? { text: '', revision: 0 };
export const evidenceKey = state => `${state.exploration}/${state.design}/${targetKey(state)}`;
export function validTarget(key) {
  if (typeof key !== 'string') return false;
  return ROLES.some(role => {
    if (!key.startsWith(prefixFor(role))) return false;
    const match = key.slice(prefixFor(role).length).match(/^(0|[1-9]\d*):(0|[1-9]\d*)$/);
    return match && validSpan({ start: Number(match[1]), end: Number(match[2]) }, role);
  });
}
export function transition(state, action) {
  if (action.type === 'scene') {
    const value = member(SCENES, action.value, state.scene);
    return { ...state, scene: value, returnContext: auxiliary(value)
      ? (auxiliary(state.scene) ? state.returnContext : {
        scene: state.scene, mode: state.mode, role: state.role,
        selection: { ...state.selections[state.role] }
      }) : null };
  }
  if (action.type === 'return') {
    const context = state.returnContext;
    if (!context) return { ...state, scene: 'V03', returnContext: null };
    return { ...state, scene: context.scene, mode: context.mode, role: context.role,
      selections: { ...state.selections, [context.role]: { ...context.selection } }, returnContext: null };
  }
  if (action.type === 'mode') return { ...state, mode: member(MODES, action.value, state.mode) };
  if (action.type === 'role') return { ...state, role: member(ROLES, action.value, state.role) };
  if (action.type === 'selection') {
    const span = { start: action.start, end: action.end };
    if (!validSpan(span, roleFor(state))) return state;
    return { ...state, selections: { ...state.selections, [state.role]: span } };
  }
  if (action.type === 'draft') {
    const previous = currentDraft(state);
    return { ...state, drafts: { ...state.drafts, [targetKey(state)]: {
      text: text(action.text), revision: previous.revision + 1
    } } };
  }
  if (action.type === 'conversation') return { ...state,
    conversations: { ...state.conversations, [targetKey(state)]: text(action.text) } };
  if (action.type === 'field') {
    if (action.name === 'request') return { ...state, request: text(action.text) };
    if (action.name === 'designNotes') return { ...state,
      designNotes: { ...state.designNotes, [state.design]: text(action.text) } };
    if (action.name === 'evidence') return { ...state,
      evidence: { ...state.evidence, [evidenceKey(state)]: text(action.text) } };
  }
  if (action.type === 'design') return { ...state, design: member(DESIGNS, action.value, state.design) };
  if (action.type === 'round') return { ...state, round: member(ROUNDS, action.value, state.round) };
  if (action.type === 'exploration' && own(EXPLORATIONS, action.value)) return { ...state, exploration: action.value };
  if (action.type === 'redact') return { ...state, redact: Boolean(action.value) };
  if (action.type === 'record' && RECORDS.some(item => item.id === action.value)) {
    const records = new Set(state.records);
    action.checked ? records.add(action.value) : records.delete(action.value);
    return { ...state, records: [...records] };
  }
  return state;
}
export function hydrate(raw) {
  try {
    if (typeof raw !== 'string' || raw.length > 1000000) throw new Error('invalid');
    const envelope = JSON.parse(raw);
    if (envelope?.schema !== 1 || !record(envelope.state)) throw new Error('schema');
    const input = envelope.state;
    const state = createState();
    state.scene = member(SCENES, input.scene, state.scene);
    state.mode = member(MODES, input.mode, state.mode);
    state.role = member(ROLES, input.role, state.role);
    const context = input.returnContext;
    const callerRole = record(context) && ROLES.find(item => item.id === context.role);
    if (auxiliary(state.scene) && callerRole
      && SCENES.some(item => item.id === context.scene && !auxiliary(item.id))
      && MODES.some(item => item.id === context.mode) && validSpan(context.selection, callerRole)) {
      state.returnContext = { scene: context.scene, mode: context.mode, role: context.role,
        selection: { start: context.selection.start, end: context.selection.end } };
    }
    state.design = member(DESIGNS, input.design, state.design);
    state.round = member(ROUNDS, input.round, state.round);
    if (typeof input.exploration === 'string' && own(EXPLORATIONS, input.exploration)) state.exploration = input.exploration;
    state.request = text(input.request);
    for (const [key, value] of Object.entries(record(input.designNotes) ? input.designNotes : {})) {
      if (DESIGNS.some(item => item.id === key)) state.designNotes[key] = text(value);
    }
    for (const [key, value] of Object.entries(record(input.evidence) ? input.evidence : {})) {
      const [entry, design, ...target] = key.split('/');
      if (own(EXPLORATIONS, entry) && DESIGNS.some(item => item.id === design) && validTarget(target.join('/'))) state.evidence[key] = text(value);
    }
    for (const role of ROLES) {
      const span = input.selections?.[role.id];
      if (validSpan(span, role)) state.selections[role.id] = { start: span.start, end: span.end };
    }
    for (const [key, value] of Object.entries(record(input.drafts) ? input.drafts : {})) {
      if (validTarget(key) && record(value)) state.drafts[key] = {
        text: text(value.text), revision: Number.isSafeInteger(value.revision) && value.revision >= 0 ? value.revision : 0
      };
    }
    for (const [key, value] of Object.entries(record(input.conversations) ? input.conversations : {})) {
      if (validTarget(key)) state.conversations[key] = text(value);
    }
    state.redact = input.redact !== false;
    if (Array.isArray(input.records)) state.records = [...new Set(input.records.filter(id => RECORDS.some(item => item.id === id)))];
    return { valid: true, state };
  } catch {
    return { valid: false, state: createState() };
  }
}
export const serialize = state => JSON.stringify({ schema: 1, state });
export function loadState(storage) {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (raw === null) return { ok: true, state: createState(), message: '아직 보관된 작성 내용이 없습니다.' };
    const result = hydrate(raw);
    return { ok: result.valid, state: result.state, message: result.valid
      ? '이 탭에만 보관된 화면 상태를 불러왔습니다.'
      : '보관 형식이 맞지 않아 복원하지 못했습니다. 기존 값은 아직 덮어쓰지 않았습니다.' };
  } catch {
    return { ok: false, state: createState(), message: '탭 보관을 읽을 수 없습니다. 현재 화면의 메모리에서만 작성합니다.' };
  }
}
export function saveState(storage, state, { readFailed = false } = {}) {
  if (readFailed) return { ok: false, message: '이전 보관본을 읽거나 복원하지 못해 자동 보관을 중단했습니다. 현재 변경은 화면 메모리에만 있습니다. 탭 보관 다시 시도에서 이전 보관본 교체를 확인하거나 내용을 복사하세요.' };
  try {
    const serialized = serialize(state);
    if (serialized.length > 1000000) throw new Error('Prototype tab storage limit');
    storage.setItem(STORAGE_KEY, serialized);
    return { ok: true, message: '이 탭에만 보관 · 마지막 변경 반영됨' };
  } catch {
    return { ok: false, message: '탭 보관 실패 · 이번 변경은 현재 화면 메모리에만 남아 있습니다. 이전 보관본에 이번 변경은 없습니다. 새로고침 전에 내용을 복사하세요.' };
  }
}
export function resetState(storage) {
  try {
    storage.removeItem(STORAGE_KEY);
    return { ok: true, state: createState(), message: '이 시제품의 탭 보관과 작성 내용을 초기화했습니다.' };
  } catch {
    return { ok: false, message: '탭 보관을 지우지 못했습니다. 현재 작성 내용은 유지합니다.' };
  }
}
